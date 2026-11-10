"""Write a report across replicate runs of one scenario.

The report states what was measured and whether each run may be believed. Runs that fail a
validity rule are listed with the reason and contribute no numbers. Interpretation is left
to the person who signs the report.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .analyze import DEFAULTS, cells, delivery_series, transitions
from .evidence import Run, load_metric, load_run
from .plan import open_order
from .validity import judge

# Categorical slots in fixed order; a region keeps its colour in every figure.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "text.color": INK,
            "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID,
            "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
            "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left",
            "lines.linewidth": 2, "legend.frameon": False,
        }
    )  # fmt: skip
    return plt


def _phase_marks(ax, run: Run, labels: bool) -> None:
    t0 = run.phases[0].start_ms
    borders = {b: run.scenario.regions[spec.gated].nodes for b, spec in run.scenario.borders.items()}
    for ph in run.phases:
        x = (ph.start_ms - t0) / 1000
        if ph.index:
            ax.axvline(x, color=MUTED, linewidth=0.8, linestyle=(0, (3, 3)))
        if labels:
            opened = ", ".join(
                f"{run.scenario.open_count(run.scenario.timeline[ph.index], b)}/{n} open" for b, n in borders.items()
            )
            ax.annotate(
                f"{ph.name}\n{opened}", (x, 1.0), xycoords=("data", "axes fraction"), xytext=(3, 6),
                textcoords="offset points", fontsize=8, color=MUTED, va="bottom",
            )  # fmt: skip


def fig_delivery(run: Run, path: Path) -> None:
    plt = _plt()
    regions = sorted(run.scenario.regions)
    rows = delivery_series(run)
    fig, axes = plt.subplots(len(regions), 1, figsize=(11, 2.6 * len(regions) + 0.6), sharex=True, squeeze=False)
    for ax, src in zip(axes[:, 0], regions, strict=True):
        for i, dst in enumerate(regions):
            pts = [(r["t_s"], r["delivered"] / r["pairs"]) for r in rows if r["src"] == src and r["dst"] == dst]
            if not pts:
                continue
            xs, ys = zip(*pts, strict=True)
            # One point per message, joined as published. No smoothing: a moving average
            # would turn an instant cut into a ramp, and the speed of the change is the result.
            ax.plot(xs, ys, color=SERIES[i], linewidth=1.4, marker="o", markersize=2.2, label=f"received in {dst}")
        ax.set_ylim(-0.04, 1.04)
        ax.set_ylabel("share of nodes reached")
        ax.set_title(f"Messages published in {src}", pad=30 if ax is axes[0, 0] else 6)
        _phase_marks(ax, run, labels=ax is axes[0, 0])
    axes[-1, 0].set_xlabel("seconds since the timeline started")
    axes[-1, 0].legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncols=len(regions))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _series_by_region(metric: list[dict], t0: int) -> dict[str, tuple[list[float], list[float]]]:
    return {s["labels"].get("region", "?"): ([(t - t0) / 1000 for t in s["t"]], s["v"]) for s in metric}


def fig_mesh(run: Run, path: Path) -> bool:
    mean = load_metric(run.path, "mesh_mean_by_region")
    low = load_metric(run.path, "mesh_min_by_region")
    if not mean:
        return False
    plt = _plt()
    t0 = run.phases[0].start_ms
    regions = sorted(run.scenario.regions)
    fig, ax = plt.subplots(figsize=(11, 3.4))
    lows = _series_by_region(low, t0)
    for i, region in enumerate(regions):
        xs, ys = _series_by_region(mean, t0).get(region, ([], []))
        ax.plot(xs, ys, color=SERIES[i], label=f"{region}: mean")
        if region in lows:
            ax.plot(*lows[region], color=SERIES[i], linewidth=1, linestyle=(0, (1, 2)), label=f"{region}: lowest node")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("gossipsub mesh peers per node")
    ax.set_xlabel("seconds since the timeline started")
    ax.set_title("Mesh size", pad=30)
    _phase_marks(ax, run, labels=True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncols=len(regions) * 2)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


def fig_bridge_load(run: Run, path: Path) -> bool:
    """Bytes sent by the nodes that reopen first, against the rest of their region."""
    per_pod = load_metric(run.path, "bytes_out_rate_by_pod")
    if not per_pod or not run.scenario.borders:
        return False
    plt = _plt()
    import numpy as np

    t0 = run.phases[0].start_ms
    border_id = sorted(run.scenario.borders)[0]
    gated = run.scenario.borders[border_id].gated
    counts = [run.scenario.open_count(p, border_id) for p in run.scenario.timeline]
    partial = [c for c in counts if 0 < c < run.scenario.regions[gated].nodes]
    if not partial:
        return False
    first = set(open_order(run.scenario, run.topology, border_id, run.seed)[: min(partial)])
    groups = {f"the {len(first)} nodes that reopen first": [], f"other {gated} nodes": []}
    grid = sorted({t for s in per_pod for t in s["t"]})
    for s in per_pod:
        if s["labels"].get("region") != gated:
            continue
        lookup = dict(zip(s["t"], s["v"], strict=True))
        key = list(groups)[0 if s["labels"].get("pod") in first else 1]
        groups[key].append([lookup.get(t, np.nan) for t in grid])
    fig, ax = plt.subplots(figsize=(11, 3.4))
    xs = [(t - t0) / 1000 for t in grid]
    for i, (label, series) in enumerate(groups.items()):
        if series:
            arr = np.array(series)
            arr = arr[:, ~np.isnan(arr).all(axis=0)]
            keep = [x for x, col in zip(xs, np.isnan(np.array(series)).all(axis=0), strict=True) if not col]
            ax.plot(keep, np.nanmedian(arr, axis=0) / 1000, color=SERIES[i], label=f"{label} (median)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("kB/s sent per node")
    ax.set_xlabel("seconds since the timeline started")
    ax.set_title(f"Load on bridging nodes in {gated}", pad=30)
    _phase_marks(ax, run, labels=True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncols=2)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


def _fmt_ratio(values: list[float]) -> str:
    if not values:
        return "n/a"
    mean = sum(values) / len(values)
    if len(values) == 1 or max(values) - min(values) < 5e-5:
        return f"{mean:.2%}"
    return f"{mean:.2%} ({min(values):.2%} to {max(values):.2%})"


def _fmt_ms(values: list[float | None]) -> str:
    vals = [v for v in values if v is not None]
    return f"{sum(vals) / len(vals):.0f}" if vals else "n/a"


def write_report(run_dirs: list[Path], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    runs = [load_run(d) for d in run_dirs]
    scn = runs[0].scenario
    if any(r.scenario != scn for r in runs):
        raise ValueError("a report covers replicates of one scenario; these runs differ")
    analysed = []
    for run in runs:
        cs = cells(run, DEFAULTS)
        verdicts = judge(run, cs)
        analysed.append((run, cs, transitions(run, cs, DEFAULTS), verdicts, all(v.passed for v in verdicts)))
    valid = [a for a in analysed if a[4]]

    md: list[str] = [f"# {scn.title}", ""]
    if scn.source:
        s = scn.source
        md += [
            f"**Event.** {s.event}",
            "",
            f"**Signal.** {s.dataset} ([view]({s.url})), window {s.window_utc[0]} to {s.window_utc[1]} UTC, "
            f"retrieved {s.retrieved}.",
            "",
            f"**Derivation.** {s.method}",
            "",
        ]
    regions = ", ".join(f"{n} nodes in `{r}`" for r, n in ((r, spec.nodes) for r, spec in scn.regions.items()))
    images = runs[0].record.get("images", {})
    run_list = ", ".join(f"`{r.record.get('run_id')}` (seed {r.seed})" for r in runs)
    md += [
        "## Setup",
        "",
        f"- {regions}; bootstrap node in `{scn.bootstrap_region}`.",
        f"- Publish rate {scn.publish.rate_hz:g} msg/s, {scn.publish.size_bytes} bytes, origins alternating "
        "between regions.",
        f"- System under test: `{images.get('node', 'unknown')}`.",
        f"- {len(runs)} run(s): {run_list}.",
        f"- A pair (message, receiving node) counts as delivered within {DEFAULTS.deadline_s:g} s. Steady-state "
        f"figures cover the last {DEFAULTS.steady_fraction:.0%} of each phase.",
        "",
        "## Validity",
        "",
        "| Rule | " + " | ".join(f"`{r.record.get('run_id')}`" for r in runs) + " |",
        "|---|" + "---|" * len(runs),
    ]
    for i, v in enumerate(analysed[0][3]):
        md.append(
            f"| {v.rule} {v.title} | " + " | ".join("pass" if a[3][i].passed else "**FAIL**" for a in analysed) + " |"
        )
    md.append("")
    for run, _cs, _tr, verdicts, ok in analysed:
        if not ok:
            reasons = "; ".join(f"{v.rule}: {v.detail}" for v in verdicts if not v.passed)
            md.append(f"Run `{run.record.get('run_id')}` is withdrawn and contributes no numbers. {reasons}")
            md.append("")
    if not valid:
        md.append("No run passed every validity rule, so this report has no results.")
        (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        return out / "report.md"

    names = sorted(scn.regions)
    pairs = [(s, d) for s in names for d in names]
    md += [
        "## Delivery in steady state",
        "",
        f"Share of (message, node) pairs delivered, mean of {len(valid)} valid run(s) with the range across runs. "
        "*no path* marks a pair of regions with no open border between them in that phase. *late* is the share "
        f"that arrived after the {DEFAULTS.deadline_s:g} s deadline, for example once a border reopened.",
        "",
        "| Phase | Border | " + " | ".join(f"{s} to {d}" for s, d in pairs) + " |",
        "|---|---|" + "---|" * len(pairs),
    ]
    lat_rows = []
    for ph in valid[0][0].phases:
        state = ", ".join(
            f"{scn.open_count(scn.timeline[ph.index], b)}/{scn.regions[spec.gated].nodes} open"
            for b, spec in scn.borders.items()
        )
        row, lat = [], []
        for s, d in pairs:
            got = [
                c for _r, cs, *_ in valid for c in cs
                if (c.phase, c.src, c.dst, c.window) == (ph.name, s, d, "steady") and c.pairs
            ]  # fmt: skip
            text = _fmt_ratio([c.ratio for c in got])
            late = sum(c.late for c in got) / max(1, sum(c.pairs for c in got))
            if late >= 0.0005:
                text += f", {late:.1%} late"
            row.append(f"{text} *(no path)*" if got and not got[0].path_exists else text)
            lat.append(f"{_fmt_ms([c.p50_ms for c in got])} / {_fmt_ms([c.p99_ms for c in got])}")
        md.append(f"| {ph.name} | {state} | " + " | ".join(row) + " |")
        lat_rows.append(f"| {ph.name} | " + " | ".join(lat) + " |")
    md += [
        "",
        "## Latency of delivered pairs",
        "",
        "Median / 99th percentile, milliseconds, steady state.",
        "",
        "| Phase | " + " | ".join(f"{s} to {d}" for s, d in pairs) + " |",
        "|---|" + "---|" * len(pairs),
        *lat_rows,
        "",
        "## Time to settle after each change",
        "",
        "Seconds from the start of a phase to the last message whose delivery was more than "
        f"{DEFAULTS.settle_tolerance:.0%} below that phase's steady level. One value per valid run.",
        "",
        "| Phase | " + " | ".join(f"{s} to {d}" for s, d in pairs) + " |",
        "|---|" + "---|" * len(pairs),
    ]
    for ph in valid[0][0].phases[1:]:
        row = []
        for s, d in pairs:
            vals = [t.settle_s for _r, _cs, trs, *_ in valid for t in trs if (t.phase, t.src, t.dst) == (ph.name, s, d)]
            row.append(", ".join(f"{v:g}" for v in vals) if vals else "no path")
        md.append(f"| {ph.name} | " + " | ".join(row) + " |")

    lead = valid[0][0]
    md += ["", "## Figures", "", f"From run `{lead.record.get('run_id')}`.", ""]
    fig_delivery(lead, out / "delivery.png")
    md += ["![Share of nodes reached by each message, by origin and destination region](delivery.png)", ""]
    if fig_mesh(lead, out / "mesh.png"):
        md += ["![Gossipsub mesh size per region over time](mesh.png)", ""]
    if fig_bridge_load(lead, out / "bridge-load.png"):
        md += ["![Bytes sent by bridging nodes compared with the rest of their region](bridge-load.png)", ""]

    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "results.json").write_text(
        json.dumps(
            [
                {
                    "run_id": r.record.get("run_id"), "seed": r.seed, "valid": ok,
                    "verdicts": [asdict(v) for v in vs], "cells": [asdict(c) for c in cs],
                    "transitions": [asdict(t) for t in trs],
                }
                for r, cs, trs, vs, ok in analysed
            ],
            indent=1,
        ),
        encoding="utf-8",
    )  # fmt: skip
    return out / "report.md"
