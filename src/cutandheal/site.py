"""Export what the explorer page replays: one compact JSON file per scenario.

Everything in the file is measured, per run: which pod published each message and how many
pods of each region received it, each pod's mesh size and send rate over time, when each
pod's shaper applied each phase, and which pods kept the border. The page draws those
values; it does not simulate the protocol.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .analyze import DEFAULTS, border_state, cells, delivery_series, transitions
from .evidence import Run, load_metric, load_run
from .validity import judge

STEP_S = 20  # resolution of the per-pod series


def _natural(name: str) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name))


def _binned(series: dict, t0_ms: int, end_ms: int, scale: float) -> list[int | None]:
    """Mean of a series in STEP_S bins from t0, as scaled integers. None where it has no sample."""
    bins: list[list[float]] = [[] for _ in range(max(1, -(-(end_ms - t0_ms) // (STEP_S * 1000))))]
    for t, v in zip(series["t"], series["v"], strict=True):
        i = (t - t0_ms) // (STEP_S * 1000)
        if 0 <= i < len(bins):
            bins[i].append(v)
    return [round(sum(b) / len(b) * scale) if b else None for b in bins]


def _per_pod(run: Run, metric: str, index: dict[str, int], t0: int, end: int, scale: float) -> list[list]:
    out: list[list] = [[] for _ in index]
    for series in load_metric(run.path, metric):
        pod = series["labels"].get("pod")
        if pod in index:
            out[index[pod]] = _binned(series, t0, end, scale)
    return out


def run_data(run: Run, index: dict[str, int]) -> dict:
    t0, end = run.phases[0].start_ms, run.phases[-1].end_ms
    regions = sorted(run.scenario.regions)
    cs = cells(run, DEFAULTS)
    verdicts = judge(run, cs)
    valid = all(v.passed for v in verdicts)
    out: dict = {
        "run_id": run.record.get("run_id"),
        "seed": run.seed,
        "valid": valid,
        "failed": [{"rule": v.rule, "title": v.title, "detail": v.detail} for v in verdicts if not v.passed],
    }
    if not valid:
        return out  # a withdrawn run is listed, never drawn

    messages: dict[tuple[float, str], dict] = {}
    for row in delivery_series(run, DEFAULTS):
        m = messages.setdefault((row["t_s"], row["origin"]), {})
        m[row["dst"]] = (row["delivered"], row["pairs"], row["p50_ms"])
    keys = sorted(messages)
    out["messages"] = {
        "t_s": [round(t, 1) for t, _ in keys],
        "origin": [index[o] for _, o in keys],
        "delivered": {r: [messages[k].get(r, (0, 0, None))[0] for k in keys] for r in regions},
        "of": {r: [messages[k].get(r, (0, 0, None))[1] for k in keys] for r in regions},
        "p50_ms": {
            r: [None if messages[k].get(r, (0, 0, None))[2] is None else round(messages[k][r][2]) for k in keys]
            for r in regions
        },
    }
    out["open"] = {
        row["phase"]: [index[p] for p in row["open"]] for row in border_state(run) if row["open_nodes"] is not None
    }
    out["mesh_x10"] = _per_pod(run, "mesh_by_pod", index, t0, end, 10)
    out["bytes_per_s"] = _per_pod(run, "bytes_out_rate_by_pod", index, t0, end, 1)
    out["mesh_mean_x10"] = {
        s["labels"].get("region", "?"): _binned(s, t0, end, 10) for s in load_metric(run.path, "mesh_mean_by_region")
    }
    late: dict[str, list] = {}
    for ack in run.acks:
        if ack.get("kind") == "phase" and ack.get("pod") in index:
            late.setdefault(ack["phase"], [None] * len(index))[index[ack["pod"]]] = int(ack["applied_ms"]) - int(
                ack["planned_ms"]
            )
    out["shaper_late_ms"] = late
    out["settle_s"] = [
        {"phase": t.phase, "src": t.src, "dst": t.dst, "settle_s": t.settle_s}
        for t in transitions(run, cs, DEFAULTS)
        if t.settle_s
    ]
    out["steady"] = [
        {"phase": c.phase, "src": c.src, "dst": c.dst, "ratio": c.ratio, "p50_ms": c.p50_ms, "p99_ms": c.p99_ms}
        for c in cs
        if c.window == "steady"
    ]
    return out


def write_site_data(run_dirs: list[Path], out: Path, evidence_url: str = "") -> Path:
    runs = [load_run(d) for d in run_dirs]
    scn = runs[0].scenario
    if any(r.scenario != scn for r in runs):
        raise ValueError("one file covers replicates of one scenario; these runs differ")
    pods = sorted((p for p in runs[0].topology.pods), key=lambda p: (p.region, _natural(p.name)))
    index = {p.name: i for i, p in enumerate(pods)}
    t0 = runs[0].phases[0].start_ms
    states = {(row["phase"], row["border"]): row for row in border_state(runs[0])}
    data = {
        "name": scn.name,
        "title": scn.title,
        "source": scn.source.model_dump() if scn.source else None,
        "evidence_url": evidence_url,
        "step_s": STEP_S,
        "publish_hz": scn.publish.rate_hz,
        "regions": {
            name: {"nodes": r.nodes, "description": r.description, "domestic": r.domestic.model_dump()}
            for name, r in scn.regions.items()
        },
        "borders": {
            bid: {"between": list(b.between), "gated": b.gated, "healthy": b.healthy.model_dump()}
            for bid, b in scn.borders.items()
        },
        "pods": [{"name": p.name, "region": p.region} for p in pods],
        "phases": [
            {
                "name": ph.name,
                "start_s": round((ph.start_ms - t0) / 1000),
                "end_s": round((ph.end_ms - t0) / 1000),
                "note": scn.timeline[ph.index].note or "",
                "open_nodes": {bid: states[(ph.name, bid)]["open_nodes"] for bid in scn.borders},
            }
            for ph in runs[0].phases
        ],
        "runs": [run_data(r, index) for r in runs],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return out
