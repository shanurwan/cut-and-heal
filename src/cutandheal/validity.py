"""Validity rules. A run that fails any of them produces no results, only a reason.

The rules and their limits are fixed in docs/METHOD.md. They exist because every one of
these failures yields a run that completes, looks plausible, and measures something other
than the protocol.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .analyze import Cell
from .evidence import Run


@dataclass(frozen=True)
class Limits:
    max_shaper_late_ms: int = 500
    baseline_min_ratio: float = 0.99
    max_publish_late_p99_ms: int = 50
    max_publish_transport_error: float = 0.001
    max_cpu_busy_p95: float = 0.85


DEFAULT_LIMITS = Limits()


@dataclass
class Verdict:
    rule: str
    title: str
    passed: bool
    detail: str


def _v1_topology(run: Run) -> Verdict:
    final = run.record.get("pods_final", [])
    restarted = [p["name"] for p in final if p["restarts"]]
    not_running = [p["name"] for p in final if p["phase"] != "Running"]
    ok = (
        run.record.get("status") == "completed"
        and len(final) == run.scenario.total_nodes
        and not restarted
        and not not_running
    )
    detail = (
        f"status={run.record.get('status')} {run.record.get('failure', '')}".strip()
        + f"; {len(final)}/{run.scenario.total_nodes} pods at end, {len(restarted)} restarted, "
        f"{len(not_running)} not running"
    )
    return Verdict("V1", "The run completed on the intended topology, with no pod restarts", ok, detail)


def _v2_shaping(run: Run, lim: Limits) -> Verdict:
    pods = {p.name for p in run.topology.pods}
    setup_ok = {a["pod"] for a in run.acks if a["kind"] == "setup" and a["rc"] == 0}
    problems = []
    if pods - setup_ok:
        problems.append(f"{len(pods - setup_ok)} pods without a clean shaper setup")
    late: list[int] = []
    for phase in run.phases:
        acks = [a for a in run.acks if a["kind"] == "phase" and a["phase"] == phase.name]
        clean = {a["pod"] for a in acks if a["rc"] == 0}
        if pods - clean:
            problems.append(f"phase {phase.name}: {len(pods - clean)} pods did not apply it cleanly")
        late += [a["applied_ms"] - a["planned_ms"] for a in acks]
    if late:
        q = np.quantile(late, [0.5, 0.99])
        stats = f"lateness p50 {q[0]:.0f} ms, p99 {q[1]:.0f} ms, max {max(late)} ms over {len(late)} applications"
        if max(late) > lim.max_shaper_late_ms or min(late) < 0:
            problems.append(f"shaper off schedule (limit {lim.max_shaper_late_ms} ms)")
    else:
        stats = "no phase acknowledgements"
        problems.append(stats)
    return Verdict("V2", "Every pod applied every phase, on schedule", not problems, "; ".join([stats, *problems]))


def _v3_baseline(run: Run, cells: list[Cell], lim: Limits) -> Verdict:
    base = [c for c in cells if c.phase == run.phases[0].name and c.window == "steady"] if run.phases else []
    worst = min((c.ratio for c in base if c.ratio is not None), default=None)
    ok = worst is not None and worst >= lim.baseline_min_ratio and all(c.pairs for c in base)
    detail = f"lowest baseline delivery {worst:.4f}" if worst is not None else "no baseline messages"
    return Verdict("V3", f"The network was healthy before anything was cut (>= {lim.baseline_min_ratio})", ok, detail)


def _v4_no_leak(cells: list[Cell]) -> Verdict:
    leaks = [c for c in cells if c.window == "steady" and not c.path_exists and (c.delivered or c.late)]
    closed = [c for c in cells if c.window == "steady" and not c.path_exists]
    detail = f"{len(closed)} closed region pairs checked, {sum(c.pairs for c in closed)} pairs, " + (
        "none delivered"
        if not leaks
        else "; ".join(f"{c.phase} {c.src}->{c.dst}: {c.delivered + c.late} delivered" for c in leaks)
    )
    return Verdict("V4", "No message crossed a border that had no open node", not leaks, detail)


def _v5_publisher(run: Run, lim: Limits) -> Verdict:
    pubs = run.publishes
    if not pubs:
        return Verdict("V5", "The publisher kept its schedule and reached the nodes", False, "no publishes recorded")
    late = [r["sent_ms"] - r["planned_ms"] for r in pubs]
    transport = sum(1 for r in pubs if r["status"] == 0)
    p99 = float(np.quantile(late, 0.99))
    ok = p99 <= lim.max_publish_late_p99_ms and transport / len(pubs) <= lim.max_publish_transport_error
    refused = sum(1 for r in pubs if r["status"] == 500)
    detail = (
        f"{len(pubs)} publishes, send lateness p99 {p99:.0f} ms, {transport} never reached a node, "
        f"{refused} refused by the node for having no peers (an outcome, not a fault)"
    )
    return Verdict("V5", "The publisher kept its schedule and reached the nodes", ok, detail)


def _v6_headroom(run: Run, lim: Limits) -> Verdict:
    if not run.load:
        return Verdict("V6", "The host had CPU headroom throughout", False, "no load samples")
    busy = [r["cpu_busy"] for r in run.load]
    p95 = float(np.quantile(busy, 0.95))
    return Verdict(
        "V6",
        f"The host had CPU headroom throughout (p95 busy <= {lim.max_cpu_busy_p95:.0%})",
        p95 <= lim.max_cpu_busy_p95,
        f"CPU busy p50 {np.median(busy):.0%}, p95 {p95:.0%}, max {max(busy):.0%} over {len(busy)} samples",
    )


def _v7_evidence(run: Run) -> Verdict:
    problems = []
    if run.logs_missing:
        problems.append(f"{len(run.logs_missing)} logs missing")
    if run.logs_without_start:
        problems.append(f"{len(run.logs_without_start)} node logs truncated (no start line)")
    if run.record.get("log_errors"):
        problems.append(f"{len(run.record['log_errors'])} log collection errors")
    if run.orphan_receives:
        problems.append(f"{run.orphan_receives} receive lines for messages nobody logged sending")
    # Two independent records of the same events: the controller's publish log and the
    # nodes' own "Sent" lines. They must agree pod by pod.
    reached: dict[str, int] = {}
    for r in run.publishes:
        if r["status"] in (200, 500):
            reached[r["pod"]] = reached.get(r["pod"], 0) + 1
    mismatched = [p for p in set(reached) | set(run.sent_per_pod) if reached.get(p, 0) != run.sent_per_pod.get(p, 0)]
    if mismatched:
        problems.append(f"{len(mismatched)} pods where the controller and the node disagree on messages sent")
    detail = f"{sum(reached.values())} publishes reconciled against {sum(run.sent_per_pod.values())} node send lines"
    return Verdict(
        "V7", "The evidence is complete and two records of it agree", not problems, "; ".join([detail, *problems])
    )


def judge(run: Run, cells: list[Cell], lim: Limits = DEFAULT_LIMITS) -> list[Verdict]:
    return [
        _v1_topology(run),
        _v2_shaping(run, lim),
        _v3_baseline(run, cells, lim),
        _v4_no_leak(cells),
        _v5_publisher(run, lim),
        _v6_headroom(run, lim),
        _v7_evidence(run),
    ]


def as_dicts(verdicts: list[Verdict]) -> list[dict]:
    return [asdict(v) for v in verdicts]
