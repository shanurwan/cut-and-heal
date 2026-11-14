"""Write a synthetic run directory in the exact formats the controller produces.

Tests build a run whose true behaviour is known, then check that analysis recovers it and
that each validity rule fires on the fault it exists for.
"""

from __future__ import annotations

import csv
import gzip
import json
from collections.abc import Callable
from pathlib import Path

from cutandheal.model import Scenario
from cutandheal.plan import Topology, expected_reach

T0_MS = 1_800_000_000_000
SEED = 7

# (phase name, origin pod, receiver pod, seconds since phase start) -> delay in ms, or None to drop
Fate = Callable[[str, str, str, float], float | None]


def honest(_phase: str, _origin: str, _receiver: str, _t: float) -> float | None:
    return 120.0


def write_run(
    path: Path,
    scn: Scenario,
    topo: Topology,
    fate: Fate = honest,
    *,
    respect_borders: bool = True,
    shaper_late_ms: int = 12,
    cpu_busy: float = 0.3,
    restarts: dict[str, int] | None = None,
    drop_sent_line: str | None = None,
    tcp_retries2: str | None = None,
) -> Path:
    (path / "logs").mkdir(parents=True)
    shaper_log = b"shaper setup rc=0\n"
    if tcp_retries2 is not None:
        shaper_log += f"2026-01-01T00:00:00Z shaper kernel tcp_retries2={tcp_retries2}\n".encode()
    phases = [{"name": n, "start_ms": T0_MS + s * 1000, "end_ms": T0_MS + e * 1000} for n, s, e in scn.phase_windows()]
    pods = list(topo.pods)
    by_region = {r: topo.by_region(r) for r in scn.regions}
    logs = {p.name: ["INF 2026-01-01 00:00:00.000+00:00 Host info tid=1 hostname=x peer=0 muxer=yamux"] for p in pods}
    publishes, regions = [], sorted(scn.regions)
    for seq in range(scn.duration_s):
        sent_ms = T0_MS + seq * 1000
        region = regions[seq % len(regions)]
        origin = by_region[region][(seq // len(regions)) % len(by_region[region])]
        idx, phase = next((i, ph) for i, ph in enumerate(phases) if ph["start_ms"] <= sent_ms < ph["end_ms"])
        reach = expected_reach(scn, topo, idx, SEED)
        sent_ns, msg_id = sent_ms * 1_000_000, 10_000 + seq
        publishes.append(
            {
                "seq": seq,
                "planned_ms": sent_ms,
                "sent_ms": sent_ms + 1,
                "pod": origin.name,
                "region": region,
                "status": 200,
                "http_ms": 3,
                "error": "",
            }
        )
        if origin.name != drop_sent_line or seq % 7:
            logs[origin.name].append(
                f"INF x Sent message                tid=1 msgId={msg_id} timestamp={sent_ns + 900}"
            )
        logs[origin.name].append(
            f"INF x Received message tid=1 msgId={msg_id} sentAt={sent_ns} current={sent_ns + 5000} delayMs=0"
        )
        for rcv in pods:
            if rcv.name == origin.name:
                continue
            if respect_borders and not reach[(origin.region, rcv.region)]:
                continue
            delay = fate(phase["name"], origin.name, rcv.name, (sent_ms - phase["start_ms"]) / 1000)
            if delay is None:
                continue
            recv_ns = sent_ns + int(delay * 1e6)
            logs[rcv.name].append(
                f"INF x Received message tid=1 msgId={msg_id} sentAt={sent_ns} current={recv_ns} delayMs={int(delay)}"
            )
    for pod in pods:
        (path / "logs" / f"{pod.name}.node.log.gz").write_bytes(gzip.compress("\n".join(logs[pod.name]).encode()))
        (path / "logs" / f"{pod.name}.shaper.log.gz").write_bytes(gzip.compress(shaper_log))

    acks = [
        {
            "received_ms": T0_MS - 5000,
            "pod": p.name,
            "kind": "setup",
            "phase": "setup",
            "planned_ms": 0,
            "applied_ms": T0_MS - 5000,
            "rc": 0,
        }
        for p in pods
    ]
    for ph in phases:
        acks += [
            {
                "received_ms": ph["start_ms"] + shaper_late_ms + 2,
                "pod": p.name,
                "kind": "phase",
                "phase": ph["name"],
                "planned_ms": ph["start_ms"],
                "applied_ms": ph["start_ms"] + shaper_late_ms,
                "rc": 0,
            }
            for p in pods
        ]
    load = [
        {"t_ms": T0_MS + i * 5000, "cpu_busy": cpu_busy, "load1": 2.0, "cpus": 12} for i in range(scn.duration_s // 5)
    ]
    for name, rows in (("publishes", publishes), ("acks", acks), ("load", load)):
        with (path / f"{name}.csv").open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    restarts = restarts or {}
    record = {
        "run_id": "synthetic",
        "seed": SEED,
        "status": "completed",
        "failure": "",
        "scenario": scn.model_dump(mode="json"),
        "topology": {
            "pods": [vars(p) for p in pods],
            "region_cidrs": {r: list(c) for r, c in topo.region_cidrs.items()},
        },
        "t0_ms": T0_MS,
        "phases": phases,
        "end_ms": phases[-1]["end_ms"],
        "pods_final": [
            {
                "name": p.name,
                "region": p.region,
                "ip": p.ip,
                "node": p.node,
                "phase": "Running",
                "ready": True,
                "restarts": restarts.get(p.name, 0),
            }
            for p in pods
        ],
        "log_errors": {},
    }
    (path / "run.json").write_text(json.dumps(record))
    return path
