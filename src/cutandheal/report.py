"""Write a report across replicate runs of one scenario.

The report states what was measured and whether each run may be believed. Runs that fail a
validity rule are listed with the reason and contribute no numbers. Interpretation is left
to the person who signs the report.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from statistics import median

from .analyze import DEFAULTS, cells, delivery_series, transitions
from .evidence import Run, load_metric, load_run
from .plan import expected_reach, open_order
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


def mesh_reaction(run: Run, change: float = 0.1) -> list[dict]:
    """When, after each phase began, a region's mean mesh size first moved by more than
    `change` from its value at the start of the phase. None means it never did.

    This is how long the mesh took to *notice*: a node whose peers have been cut off keeps
    counting them as mesh members until its connections to them time out.
    """
    out = []
    for series in load_metric(run.path, "mesh_mean_by_region"):
        region = series["labels"].get("region", "?")
        for ph in run.phases[1:]:
            pts = [(t, v) for t, v in zip(series["t"], series["v"], strict=True) if ph.start_ms <= t < ph.end_ms]
            if not pts or pts[0][1] <= 0:
                continue
            start = pts[0][1]
            moved = next((t for t, v in pts if abs(v - start) / start > change), None)
            out.append(
                {
                    "phase": ph.name,
                    "region": region,
                    "mesh_at_start": round(start, 2),
                    "mesh_at_end": round(pts[-1][1], 2),
                    "reacted_after_s": None if moved is None else round((moved - ph.start_ms) / 1000),
                }
            )
    return out


def mesh_drop_ages(run: Run) -> list[dict]:
    """For each phase and region whose mean mesh moved: the pods whose own mesh fell below its
    size at the start of the phase, and the median moment of that first fall, counted from the
    change and from the start of the pod's node.

    A reaction tied to the change comes the same number of seconds after it in every run. One
    tied to a clock that began with the node, such as a periodic idle check, comes at the same
    node age instead, whenever the change happened.
    """
    moved = {(row["phase"], row["region"]) for row in mesh_reaction(run) if row["reacted_after_s"] is not None}
    by_pod = load_metric(run.path, "mesh_by_pod")
    out = []
    for ph in run.phases[1:]:
        falls: dict[str, list[tuple[float, float]]] = {}
        for series in by_pod:
            region = series["labels"].get("region", "?")
            started = run.started_ms.get(series["labels"].get("pod", ""))
            pts = [(t, v) for t, v in zip(series["t"], series["v"], strict=True) if ph.start_ms <= t < ph.end_ms]
            if started is None or not pts or (ph.name, region) not in moved:
                continue
            fell = next((t for t, v in pts if v < pts[0][1]), None)
            if fell is not None:
                falls.setdefault(region, []).append(((fell - ph.start_ms) / 1000, (fell - started) / 1000))
        for region, rows in sorted(falls.items()):
            out.append(
                {
                    "phase": ph.name,
                    "region": region,
                    "pods": len(rows),
                    "after_change_s": round(median(a for a, _ in rows)),
                    "node_age_at_change_s": round(median(age - a for a, age in rows)),
                    "node_age_s": round(median(age for _, age in rows)),
                }
            )
    return out


def stream_timeouts(run: Run, stream_type: str = "YamuxStream", before_s: int = 25, after_s: int = 5) -> list[dict]:
    """For each phase and region whose mean mesh moved: how many streams of `stream_type` the
    region's nodes closed for inactivity around that moment, and how many earlier in the phase.

    The count is the nodes' own counter. "Around" runs from `before_s` before the mesh moved to
    `after_s` after it, which covers one scrape on either side.
    """
    counters = {
        s["labels"].get("region", "?"): s
        for s in load_metric(run.path, "stream_timeouts_by_region")
        if s["labels"].get("type") == stream_type
    }
    if not counters:
        return []

    def at(series: dict, t_ms: float) -> float:
        return next((v for t, v in zip(reversed(series["t"]), reversed(series["v"]), strict=True) if t <= t_ms), 0.0)

    out = []
    starts = {ph.name: ph.start_ms for ph in run.phases}
    for row in mesh_reaction(run):
        series = counters.get(row["region"])
        if row["reacted_after_s"] is None or series is None:
            continue
        begin = starts[row["phase"]]
        moved = begin + row["reacted_after_s"] * 1000
        lo = max(begin, moved - before_s * 1000)
        out.append(
            {
                "phase": row["phase"],
                "region": row["region"],
                "reacted_after_s": row["reacted_after_s"],
                "around": round(at(series, moved + after_s * 1000) - at(series, lo)),
                "earlier_in_phase": round(at(series, lo) - at(series, begin)),
            }
        )
    return out


def timeout_bursts(run: Run, stream_type: str = "YamuxStream", gap_s: int = 60, least: int = 100) -> list[dict]:
    """For each phase after the first and each region: the bursts in which the region's nodes
    closed streams of `stream_type` for inactivity.

    A burst is a run of samples in which the nodes' counter rose, ended by `gap_s` seconds
    without a rise; bursts of fewer than `least` timeouts are left out. `peak_s` is the sample
    with the largest rise. Times are seconds after the phase began.
    """
    out = []
    for series in load_metric(run.path, "stream_timeouts_by_region"):
        if series["labels"].get("type") != stream_type:
            continue
        pts = list(zip(series["t"], series["v"], strict=True))
        rises = [(t, v - v0) for (_t0, v0), (t, v) in zip(pts, pts[1:], strict=False) if v > v0]
        for ph in run.phases[1:]:
            bursts: list[list[tuple[int, float]]] = []
            for t, dv in rises:
                if not ph.start_ms <= t < ph.end_ms:
                    continue
                if bursts and t - bursts[-1][-1][0] <= gap_s * 1000:
                    bursts[-1].append((t, dv))
                else:
                    bursts.append([(t, dv)])
            for burst in bursts:
                total = sum(dv for _t, dv in burst)
                if total < least:
                    continue
                out.append(
                    {
                        "phase": ph.name,
                        "region": series["labels"].get("region", "?"),
                        "from_s": round((burst[0][0] - ph.start_ms) / 1000),
                        "to_s": round((burst[-1][0] - ph.start_ms) / 1000),
                        "peak_s": round((max(burst, key=lambda x: x[1])[0] - ph.start_ms) / 1000),
                        "timeouts": round(total),
                    }
                )
    return out


def held_messages(run: Run, guard_s: float = 2.0) -> list[dict]:
    """For each phase in which a pair of regions had no path, followed by a phase in which it
    had one again: of the messages published in the first region during the closed phase, the
    share of (message, node) pairs in the second that were delivered by the end of the run, and
    when those deliveries came, in seconds after the path reopened. Messages published in the
    first `guard_s` of the phase are left out: they may have crossed before the cut landed.

    Gossipsub keeps no store of past messages beyond a few heartbeats, so a message that crosses
    after a reopening was held in a connection that survived the cut.
    """
    by_region: dict[str, list[str]] = {}
    for pod in run.topology.pods:
        by_region.setdefault(pod.region, []).append(pod.name)
    moved = {(row["phase"], row["region"]): row["reacted_after_s"] for row in mesh_reaction(run)}
    out = []
    for ph, nxt in zip(run.phases, run.phases[1:], strict=False):
        closed = expected_reach(run.scenario, run.topology, ph.index, run.seed)
        after = expected_reach(run.scenario, run.topology, nxt.index, run.seed)
        for (src, dst), ok in sorted(closed.items()):
            if ok or src == dst or not after[(src, dst)]:
                continue
            # Messages already in flight when the cut landed are not held; skip the first seconds.
            begin = ph.start_ms + guard_s * 1000
            msgs = [m for m in run.messages if m.origin_region == src and begin <= m.sent_ns / 1e6 < ph.end_ms]
            lags = sorted(
                (m.received[pod] / 1e6 - ph.end_ms) / 1000 for m in msgs for pod in by_region[dst] if pod in m.received
            )
            pairs = len(msgs) * len(by_region[dst])
            reacted = moved.get((ph.name, src))
            out.append(
                {
                    "phase": ph.name,
                    "src": src,
                    "dst": dst,
                    "closed_s": round((ph.end_ms - ph.start_ms) / 1000),
                    "messages": len(msgs),
                    "pairs": pairs,
                    "delivered": len(lags),
                    "ratio": len(lags) / pairs if pairs else None,
                    "first_s": round(lags[0], 1) if lags else None,
                    "median_s": round(median(lags), 1) if lags else None,
                    "last_s": round(lags[-1], 1) if lags else None,
                    "src_mesh_moved_after_s": reacted,
                }
            )
    return out


def _cpu_stat(path: Path) -> dict[str, int]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition(" ")
        if value.strip().isdigit():
            out[key] = int(value)
    return out


def region_cpu(run: Run) -> list[dict]:
    """CPU of each region's Kubernetes node over the run, from its cgroup, if the workflow
    recorded it (`lab/<node>.cpu.start` and `.end`, each `wall_ns` plus `cpu.stat`).

    `cores` is the average CPU used. `throttled_share` is the share of scheduler periods in
    which the node hit its cap: a pod there waited for CPU, whatever the host's load was.
    """
    lab = run.path / "lab"
    out = []
    for start in sorted(lab.glob("*.cpu.start")) if lab.is_dir() else []:
        end = start.with_suffix(".end")
        if not end.exists():
            continue
        a, b = _cpu_stat(start), _cpu_stat(end)
        wall = (b.get("wall_ns", 0) - a.get("wall_ns", 0)) / 1e9
        periods = b.get("nr_periods", 0) - a.get("nr_periods", 0)
        out.append(
            {
                "node": start.name.removesuffix(".cpu.start"),
                "seconds": round(wall),
                "cores": round((b.get("usage_usec", 0) - a.get("usage_usec", 0)) / 1e6 / wall, 3) if wall > 0 else None,
                "throttled_share": round((b.get("nr_throttled", 0) - a.get("nr_throttled", 0)) / periods, 3)
                if periods
                else None,
                "throttled_s": round((b.get("throttled_usec", 0) - a.get("throttled_usec", 0)) / 1e6, 1),
            }
        )
    return out


def policy_timing(run: Run) -> list[dict]:
    """For a run that shut borders with NetworkPolicies: each request, how long the API took to
    answer, and its status."""
    path = run.path / "policies.csv"
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "phase": r["phase"],
                    "policy": r["policy"],
                    "action": r["action"],
                    "late_ms": int(r["sent_ms"]) - int(r["planned_ms"]),
                    "api_ms": int(r["done_ms"]) - int(r["sent_ms"]),
                    "status": int(r["status"]),
                }
            )
    return rows


def kernel_settings(run: Run) -> dict[str, dict[str, int]]:
    """Each TCP setting the shapers recorded, with the number of pods that had each value."""
    out: dict[str, dict[str, int]] = {}
    for settings in run.kernel.values():
        for key, value in settings.items():
            counts = out.setdefault(key, {})
            counts[value] = counts.get(value, 0) + 1
    return out


def bridge_load(run: Run) -> list[dict]:
    """Bytes sent per node in steady state: nodes with the border open against the rest of
    their region, for every phase where only some nodes are open."""
    import numpy as np

    per_pod = load_metric(run.path, "bytes_out_rate_by_pod")
    out = []
    for border_id, border in sorted(run.scenario.borders.items()):
        total = run.scenario.regions[border.gated].nodes
        order = open_order(run.scenario, run.topology, border_id, run.seed)
        for ph in run.phases:
            count = run.scenario.open_count(run.scenario.timeline[ph.index], border_id)
            if not 0 < count < total:
                continue
            opened = set(order[:count])
            begin = ph.end_ms - DEFAULTS.steady_fraction * (ph.end_ms - ph.start_ms)
            means: dict[bool, list[float]] = {True: [], False: []}
            for series in per_pod:
                if series["labels"].get("region") != border.gated:
                    continue
                vals = [v for t, v in zip(series["t"], series["v"], strict=True) if begin <= t < ph.end_ms]
                if vals:
                    means[series["labels"].get("pod") in opened].append(sum(vals) / len(vals))
            if means[True] and means[False]:
                a, b = float(np.median(means[True])), float(np.median(means[False]))
                out.append(
                    {
                        "phase": ph.name,
                        "border": border_id,
                        "open_nodes": count,
                        "open_bytes_per_s": round(a),
                        "other_bytes_per_s": round(b),
                        "ratio": round(a / b, 2) if b else None,
                    }
                )
    return out


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
        *(["- Borders shut by: Kubernetes NetworkPolicy (see `policy.py`)."] if scn.cut == "networkpolicy" else []),
        *(
            [
                "- CPU cap per region node: "
                + ", ".join(f"`{r}` {c:g} cores" for r, c in sorted(scn.lab.cpus.items()))
                + "."
            ]
            if scn.lab.cpus
            else []
        ),
        *(
            ["- Node settings: " + ", ".join(f"`{k}={v}`" for k, v in sorted(scn.node.env.items())) + "."]
            if scn.node.env
            else []
        ),
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
    cpu = [(r.record.get("run_id"), region_cpu(r)) for r, *_ in analysed]
    if any(rows for _id, rows in cpu):
        md += [
            "",
            "## CPU of the region machines",
            "",
            "From each region node's cgroup, before and after the run, for every run including withdrawn ones. "
            "*Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.",
            "",
            "| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |",
            "|---|---|---|---|---|---|",
        ]
        for run_id, rows in cpu:
            for row in rows:
                share = "n/a" if row["throttled_share"] is None else f"{row['throttled_share']:.1%}"
                md.append(
                    f"| {run_id} | {row['node']} | {row['seconds']} | {row['cores']} | {share} | {row['throttled_s']} |"
                )
    policies = [(r.record.get("run_id"), policy_timing(r)) for r, *_ in analysed]
    if any(rows for _id, rows in policies):
        md += [
            "",
            "## NetworkPolicy requests",
            "",
            "Each policy the controller created or deleted: how late after the phase began it asked, how long "
            "the API server took to answer, and the HTTP status. When the network plugin enforced it is read "
            "from the deliveries, not from here.",
            "",
            "| Run | Phase | Policy | Action | Asked after (ms) | API answered in (ms) | Status |",
            "|---|---|---|---|---|---|---|",
        ]
        for run_id, rows in policies:
            for row in rows:
                md.append(
                    f"| {run_id} | {row['phase']} | {row['policy']} | {row['action']} | {row['late_ms']} "
                    f"| {row['api_ms']} | {row['status']} |"
                )
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

    reactions = [(r.record.get("run_id"), mesh_reaction(r)) for r, *_ in valid]
    if any(rows for _id, rows in reactions):
        md += [
            "",
            "## When the mesh noticed",
            "",
            "Seconds after each change until a region's mean mesh size first moved by more than 10%. One value "
            "per valid run; *never* means it stayed within 10% for the whole phase. The size is what each node "
            "reports about itself, so it includes peers the node has not yet found to be unreachable.",
            "",
            "| Phase | Region | Mesh size at start | at end | Reacted after (s) |",
            "|---|---|---|---|---|",
        ]
        keys = sorted({(row["phase"], row["region"]) for _id, rows in reactions for row in rows},
                      key=lambda k: ([p.name for p in valid[0][0].phases].index(k[0]), k[1]))  # fmt: skip
        for phase, region in keys:
            rows = [row for _id, rs in reactions for row in rs if (row["phase"], row["region"]) == (phase, region)]
            at_start = sum(row["mesh_at_start"] for row in rows) / len(rows)
            at_end = sum(row["mesh_at_end"] for row in rows) / len(rows)
            reacted = ", ".join(
                "never" if row["reacted_after_s"] is None else str(row["reacted_after_s"]) for row in rows
            )
            md.append(f"| {phase} | {region} | {at_start:.1f} | {at_end:.1f} | {reacted} |")
    held = [(r.record.get("run_id"), held_messages(r)) for r, *_ in valid]
    if any(rows for _id, rows in held):
        md += [
            "",
            "## Messages sent while a border was shut",
            "",
            "Of the messages published in one region while it had no path to another, the share of (message, "
            "node) pairs in the other region delivered by the end of the run, and when, in seconds after the "
            "path reopened. The last column is when the sending region's mean mesh first moved by more than "
            "10% during the shutdown, if it did.",
            "",
            "| Run | Phase | From | To | Shut (s) | Messages | Delivered later | First (s) | Median (s) | Last (s) "
            "| Sender's mesh moved after (s) |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for run_id, rows in held:
            for row in rows:
                ratio = "n/a" if row["ratio"] is None else f"{row['ratio']:.2%}"
                cells_ = [row[k] for k in ("first_s", "median_s", "last_s")]
                when = ["" if v is None else f"{v:g}" for v in cells_]
                moved = "never" if row["src_mesh_moved_after_s"] is None else str(row["src_mesh_moved_after_s"])
                md.append(
                    f"| {run_id} | {row['phase']} | {row['src']} | {row['dst']} | {row['closed_s']} "
                    f"| {row['messages']} | {ratio} | {when[0]} | {when[1]} | {when[2]} | {moved} |"
                )
    ages = [(r.record.get("run_id"), mesh_drop_ages(r)) for r, *_ in valid]
    if any(rows for _id, rows in ages):
        md += [
            "",
            "## Mesh reaction against node age",
            "",
            "For the pods whose own mesh fell below its size at the start of the phase: the median moment of "
            "that first fall, counted from the change and from the start of the pod's node. A reaction tied to "
            "the change keeps the first number from run to run; one tied to a clock that began with the node "
            "keeps the last.",
            "",
            "| Run | Phase | Region | Pods | After the change (s) | Node age at the change (s) "
            "| Node age at the fall (s) |",
            "|---|---|---|---|---|---|---|",
        ]
        for run_id, rows in ages:
            for row in rows:
                md.append(
                    f"| {run_id} | {row['phase']} | {row['region']} | {row['pods']} | {row['after_change_s']} "
                    f"| {row['node_age_at_change_s']} | {row['node_age_s']} |"
                )
    timeouts = [(r.record.get("run_id"), stream_timeouts(r)) for r, *_ in valid]
    if any(rows for _id, rows in timeouts):
        md += [
            "",
            "## Stream idle timeouts when the mesh moved",
            "",
            "Multiplexer streams the region's nodes closed for inactivity, from the nodes' own counter "
            "`libp2p_stream_timeouts`: from 25 s before the region's mean mesh first moved to 5 s after, and "
            "earlier in the same phase.",
            "",
            "| Run | Phase | Region | Mesh moved after (s) | Timeouts around it | Earlier in the phase |",
            "|---|---|---|---|---|---|",
        ]
        for run_id, rows in timeouts:
            for row in rows:
                md.append(
                    f"| {run_id} | {row['phase']} | {row['region']} | {row['reacted_after_s']} | {row['around']} "
                    f"| {row['earlier_in_phase']} |"
                )
    bursts = [(r.record.get("run_id"), timeout_bursts(r)) for r, *_ in valid]
    if any(rows for _id, rows in bursts):
        md += [
            "",
            "## Bursts of stream idle timeouts",
            "",
            "Stretches in which a region's nodes closed multiplexer streams for inactivity, from the same "
            "counter. A burst ends after 60 s without a timeout; bursts of fewer than 100 are left out. "
            "Seconds after the phase began.",
            "",
            "| Run | Phase | Region | From (s) | To (s) | Peak (s) | Timeouts |",
            "|---|---|---|---|---|---|---|",
        ]
        for run_id, rows in bursts:
            for row in rows:
                md.append(
                    f"| {run_id} | {row['phase']} | {row['region']} | {row['from_s']} | {row['to_s']} "
                    f"| {row['peak_s']} | {row['timeouts']} |"
                )
    kernels = [kernel_settings(r) for r, *_ in valid]
    if any(kernels):
        md += [
            "",
            "## Kernel TCP settings on the nodes",
            "",
            "Read by each pod's shaper from the pod's own network namespace when it started. Pods per "
            "value, one column per valid run.",
            "",
            "| Setting | " + " | ".join(str(r.record.get("run_id")) for r, *_ in valid) + " |",
            "|---|" + "---|" * len(valid),
        ]
        for key in sorted({k for per_run in kernels for k in per_run}):
            row = [
                ", ".join(f"{value} ({n} pods)" for value, n in sorted(per_run.get(key, {}).items())) or "not recorded"
                for per_run in kernels
            ]
            md.append(f"| {key} | " + " | ".join(row) + " |")
    loads = [row for r, *_ in valid for row in bridge_load(r)]
    if loads:
        md += [
            "",
            "## Load on the nodes that keep the border",
            "",
            "Median bytes sent per second in steady state: nodes with the border open against the other nodes "
            "of their region. One row per valid run.",
            "",
            "| Phase | Open nodes | Open nodes (B/s) | Other nodes (B/s) | Ratio |",
            "|---|---|---|---|---|",
        ]
        md += [
            f"| {row['phase']} | {row['open_nodes']} | {row['open_bytes_per_s']} | {row['other_bytes_per_s']} | "
            f"{row['ratio']} |"
            for row in sorted(loads, key=lambda row: [p.name for p in valid[0][0].phases].index(row["phase"]))
        ]

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
                    "transitions": [asdict(t) for t in trs], "kernel": kernel_settings(r),
                    "mesh_drop_ages": mesh_drop_ages(r), "stream_timeouts": stream_timeouts(r),
                    "timeout_bursts": timeout_bursts(r), "held_messages": held_messages(r),
                    "region_cpu": region_cpu(r), "policies": policy_timing(r),
                }
                for r, cs, trs, vs, ok in analysed
            ],
            indent=1,
        ),
        encoding="utf-8",
    )  # fmt: skip
    return out / "report.md"
