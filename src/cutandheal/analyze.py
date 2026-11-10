"""Turn a run's evidence into numbers. Every definition a reader could dispute is a named
parameter here, fixed in docs/METHOD.md before any run.

Unit of analysis: a (message, receiver) pair, where the receiver is any node other than the
origin. A pair is *delivered* if the receiver logged the message within `deadline_s` of the
send. Pairs are grouped by the phase the message was sent in and by (origin region,
receiver region).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .evidence import Message, PhaseWindow, Run
from .plan import expected_reach, open_set


@dataclass(frozen=True)
class Params:
    deadline_s: float = 10.0
    """A pair counts as delivered only within this long of the send."""
    guard_s: float = 20.0
    """Messages sent this soon after a phase starts are transition, not steady state."""
    settle_tolerance: float = 0.01
    """A message is 'below steady' if its delivery ratio is this far under the phase's level."""
    bootstrap_resamples: int = 2000
    confidence: float = 0.95


DEFAULTS = Params()


@dataclass
class Cell:
    """Delivery from one region to another during one phase."""

    phase: str
    src: str
    dst: str
    path_exists: bool
    window: str  # "steady" or "whole"
    messages: int
    pairs: int
    delivered: int
    ratio: float | None
    ci_low: float | None
    ci_high: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    late: int  # received, but after the deadline


@dataclass
class Transition:
    """How long delivery took to reach its steady level after a phase began."""

    phase: str
    src: str
    dst: str
    steady_ratio: float | None
    settle_s: float | None
    messages_below: int
    first_full_s: float | None


def _receivers(run: Run, msg: Message, dst: str) -> list[str]:
    return [p.name for p in run.topology.pods if p.region == dst and p.name != msg.origin]


def _pair_stats(run: Run, msg: Message, dst: str, deadline_ms: float) -> tuple[int, int, int, list[float]]:
    """(pairs, delivered, late, delays_ms of delivered pairs)."""
    names = _receivers(run, msg, dst)
    delays = [msg.delay_ms(n) for n in names]
    ok = [d for d in delays if d is not None and d <= deadline_ms]
    late = sum(1 for d in delays if d is not None and d > deadline_ms)
    return len(names), len(ok), late, ok


def _bootstrap_ci(per_msg: list[tuple[int, int]], p: Params, seed: int) -> tuple[float | None, float | None]:
    """CI for a ratio of sums, resampling messages: pairs from one message are not independent."""
    if len(per_msg) < 2:
        return None, None
    arr = np.array(per_msg, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(p.bootstrap_resamples, len(arr)))
    sums = arr[idx].sum(axis=1)
    ratios = sums[:, 1] / np.maximum(sums[:, 0], 1)
    alpha = (1 - p.confidence) / 2
    lo, hi = np.quantile(ratios, [alpha, 1 - alpha])
    return float(lo), float(hi)


def _in_window(msg: Message, phase: PhaseWindow, window: str, p: Params) -> bool:
    t = msg.sent_ns / 1e6
    if not (phase.start_ms <= t < phase.end_ms):
        return False
    if window == "whole":
        return True
    # Steady: past the transition, and early enough that the delivery deadline falls inside
    # the phase, so the next phase cannot take credit or blame.
    return phase.start_ms + p.guard_s * 1000 <= t <= phase.end_ms - p.deadline_s * 1000


def cells(run: Run, p: Params = DEFAULTS) -> list[Cell]:
    regions = sorted(run.scenario.regions)
    out: list[Cell] = []
    for phase in run.phases:
        reach = expected_reach(run.scenario, run.topology, phase.index, run.seed)
        for window in ("steady", "whole"):
            msgs = [m for m in run.messages if _in_window(m, phase, window, p)]
            for src in regions:
                src_msgs = [m for m in msgs if m.origin_region == src]
                for dst in regions:
                    per_msg, delays, late = [], [], 0
                    for m in src_msgs:
                        n, k, n_late, d = _pair_stats(run, m, dst, p.deadline_s * 1000)
                        if n:
                            per_msg.append((n, k))
                            delays += d
                            late += n_late
                    pairs = sum(n for n, _ in per_msg)
                    delivered = sum(k for _, k in per_msg)
                    lo, hi = _bootstrap_ci(per_msg, p, seed=run.seed + phase.index)
                    q = np.quantile(delays, [0.5, 0.95, 0.99]) if delays else [None] * 3
                    out.append(
                        Cell(
                            phase=phase.name,
                            src=src,
                            dst=dst,
                            path_exists=reach[(src, dst)],
                            window=window,
                            messages=len(per_msg),
                            pairs=pairs,
                            delivered=delivered,
                            ratio=delivered / pairs if pairs else None,
                            ci_low=lo,
                            ci_high=hi,
                            p50_ms=_f(q[0]),
                            p95_ms=_f(q[1]),
                            p99_ms=_f(q[2]),
                            late=late,
                        )
                    )
    return out


def _f(x) -> float | None:
    return None if x is None else round(float(x), 2)


def transitions(run: Run, cell_list: list[Cell], p: Params = DEFAULTS) -> list[Transition]:
    """For each phase and region pair with a path: when did delivery reach its steady level?

    `settle_s` is the send time, measured from the phase start, of the last message whose
    delivery ratio was more than `settle_tolerance` below the phase's steady ratio. Zero
    means no message was ever below it. None means there is no steady level to settle to.
    """
    steady = {(c.phase, c.src, c.dst): c for c in cell_list if c.window == "steady"}
    out: list[Transition] = []
    for phase in run.phases:
        msgs = [m for m in run.messages if _in_window(m, phase, "whole", p)]
        for (ph, src, dst), cell in steady.items():
            if ph != phase.name or not cell.path_exists or cell.ratio is None:
                continue
            series = []
            for m in msgs:
                if m.origin_region != src:
                    continue
                n, k, _late, _d = _pair_stats(run, m, dst, p.deadline_s * 1000)
                if n:
                    series.append(((m.sent_ns / 1e6 - phase.start_ms) / 1000, k / n))
            below = [t for t, r in series if r < cell.ratio - p.settle_tolerance]
            full = [t for t, r in series if r >= cell.ratio - p.settle_tolerance]
            out.append(
                Transition(
                    phase=phase.name,
                    src=src,
                    dst=dst,
                    steady_ratio=cell.ratio,
                    settle_s=round(max(below), 2) if below else 0.0,
                    messages_below=len(below),
                    first_full_s=round(min(full), 2) if full else None,
                )
            )
    return out


def delivery_series(run: Run, p: Params = DEFAULTS) -> list[dict]:
    """One row per message and destination region: the raw series behind every figure."""
    regions = sorted(run.scenario.regions)
    t0 = run.phases[0].start_ms if run.phases else 0
    rows = []
    for m in run.messages:
        phase = run.phase_of(m.sent_ns / 1e6)
        for dst in regions:
            n, k, late, delays = _pair_stats(run, m, dst, p.deadline_s * 1000)
            if n:
                rows.append(
                    {
                        "t_s": round((m.sent_ns / 1e6 - t0) / 1000, 3),
                        "phase": phase.name if phase else "",
                        "origin": m.origin,
                        "src": m.origin_region,
                        "dst": dst,
                        "pairs": n,
                        "delivered": k,
                        "late": late,
                        "p50_ms": _f(np.median(delays)) if delays else None,
                        "max_ms": _f(max(delays)) if delays else None,
                    }
                )
    return rows


def border_state(run: Run) -> list[dict]:
    """What each phase asked of each border, resolved against the real topology."""
    rows = []
    for phase in run.phases:
        for bid, border in run.scenario.borders.items():
            opened = open_set(run.scenario, run.topology, bid, phase.index, run.seed)
            rows.append(
                {
                    "phase": phase.name,
                    "border": bid,
                    "gated": border.gated,
                    "open_nodes": len(opened),
                    "gated_nodes": run.scenario.regions[border.gated].nodes,
                    "link": run.scenario.link(run.scenario.timeline[phase.index], bid).model_dump(),
                    "open": sorted(opened),
                }
            )
    return rows


def summarise(run: Run, p: Params = DEFAULTS) -> dict:
    cell_list = cells(run, p)
    return {
        "run_id": run.record.get("run_id"),
        "params": asdict(p),
        "phases": [asdict(ph) for ph in run.phases],
        "borders": border_state(run),
        "cells": [asdict(c) for c in cell_list],
        "transitions": [asdict(t) for t in transitions(run, cell_list, p)],
        "messages": len(run.messages),
    }
