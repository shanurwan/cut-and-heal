"""Load a run's raw files into typed records. No judgement here, only parsing.

The node's log lines are the ground truth for delivery: each receiver logs the message id,
the send time carried in the payload, and its own receive time.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .model import Scenario
from .plan import Pod, Topology

_SENT = re.compile(r"Sent message\s.*?msgId=(\d+) timestamp=(\d+)")
_RECV = re.compile(r"Received message\s.*?msgId=(\d+) sentAt=(\d+) current=(\d+)")
# Written by the shaper once its qdisc tree is up: `shaper kernel tcp_retries2=15`.
_KERNEL = re.compile(r"shaper kernel (\w+)=(\S+)")
# The first line the node writes. Its absence means the log was rotated or truncated.
START_MARKER = "Host info"


@dataclass
class Message:
    msg_id: int
    origin: str
    origin_region: str
    sent_ns: int
    received: dict[str, int] = field(default_factory=dict)  # pod -> receive time, ns

    def delay_ms(self, pod: str) -> float | None:
        t = self.received.get(pod)
        return None if t is None else (t - self.sent_ns) / 1e6


@dataclass(frozen=True)
class PhaseWindow:
    index: int
    name: str
    start_ms: int
    end_ms: int


@dataclass
class Run:
    path: Path
    record: dict
    scenario: Scenario
    topology: Topology
    phases: list[PhaseWindow]
    messages: list[Message]
    publishes: list[dict]
    acks: list[dict]
    load: list[dict]
    sent_per_pod: dict[str, int]
    logs_missing: list[str]
    logs_without_start: list[str]
    orphan_receives: int
    kernel: dict[str, dict[str, str]] = field(default_factory=dict)
    """Per pod, the kernel TCP settings its shaper read at start. Empty for evidence
    collected before shapers recorded them."""

    @property
    def seed(self) -> int:
        return int(self.record["seed"])

    def phase_of(self, t_ms: float) -> PhaseWindow | None:
        for p in self.phases:
            if p.start_ms <= t_ms < p.end_ms:
                return p
        return None


def _read_csv(path: Path, ints: tuple[str, ...] = (), floats: tuple[str, ...] = ()) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for k in ints:
            row[k] = int(row[k])
        for k in floats:
            row[k] = float(row[k])
    return rows


def parse_node_log(text: str) -> tuple[list[tuple[int, int]], list[tuple[int, int, int]], bool]:
    """(sent, received, has_start_marker). sent: (msg_id, ts_ns); received: (msg_id, sent_ns, recv_ns)."""
    sent = [(int(m[1]), int(m[2])) for m in _SENT.finditer(text)]
    recv = [(int(m[1]), int(m[2]), int(m[3])) for m in _RECV.finditer(text)]
    return sent, recv, START_MARKER in text


def parse_shaper_log(text: str) -> dict[str, str]:
    """The kernel settings a shaper recorded."""
    return dict(_KERNEL.findall(text))


def load_run(path: str | Path) -> Run:
    path = Path(path)
    record = json.loads((path / "run.json").read_text(encoding="utf-8"))
    scn = Scenario.model_validate(record["scenario"])
    topo_raw = record.get("topology", {"pods": [], "region_cidrs": {}})
    topo = Topology(
        pods=tuple(Pod(**p) for p in topo_raw["pods"]),
        region_cidrs={r: tuple(c) for r, c in topo_raw["region_cidrs"].items()},
    )
    phases = [PhaseWindow(i, p["name"], p["start_ms"], p["end_ms"]) for i, p in enumerate(record.get("phases", []))]

    messages: dict[int, Message] = {}
    receives: list[tuple[str, int, int, int]] = []
    sent_per_pod: dict[str, int] = {}
    missing, no_start = [], []
    kernel: dict[str, dict[str, str]] = {}
    for pod in topo.pods:
        log_path = path / "logs" / f"{pod.name}.node.log.gz"
        if not log_path.exists():
            missing.append(pod.name)
            continue
        sent, recv, started = parse_node_log(gzip.decompress(log_path.read_bytes()).decode("utf-8", "replace"))
        if not started:
            no_start.append(pod.name)
        sent_per_pod[pod.name] = len(sent)
        for msg_id, ts in sent:
            messages[msg_id] = Message(msg_id, pod.name, pod.region, ts)
        receives += [(pod.name, m, s, r) for m, s, r in recv]
        shaper_path = path / "logs" / f"{pod.name}.shaper.log.gz"
        if not shaper_path.exists():
            missing.append(f"{pod.name}/shaper")
            continue
        settings = parse_shaper_log(gzip.decompress(shaper_path.read_bytes()).decode("utf-8", "replace"))
        if settings:
            kernel[pod.name] = settings

    orphans = 0
    for pod_name, msg_id, sent_ns, recv_ns in receives:
        msg = messages.get(msg_id)
        if msg is None:
            orphans += 1
            continue
        # The payload timestamp is the send time every receiver measures against; the
        # origin's own "Sent" line is logged a few microseconds later.
        msg.sent_ns = sent_ns
        if pod_name != msg.origin:
            prev = msg.received.get(pod_name)
            msg.received[pod_name] = recv_ns if prev is None else min(prev, recv_ns)

    return Run(
        path=path,
        record=record,
        scenario=scn,
        topology=topo,
        phases=phases,
        messages=sorted(messages.values(), key=lambda m: m.sent_ns),
        publishes=_read_csv(path / "publishes.csv", ints=("seq", "planned_ms", "sent_ms", "status", "http_ms")),
        acks=_read_csv(path / "acks.csv", ints=("received_ms", "planned_ms", "applied_ms", "rc")),
        load=_read_csv(path / "load.csv", ints=("t_ms",), floats=("cpu_busy", "load1")),
        sent_per_pod=sent_per_pod,
        logs_missing=missing,
        logs_without_start=no_start,
        orphan_receives=orphans,
        kernel=kernel,
    )


def load_metric(run_path: Path, name: str) -> list[dict]:
    """A VictoriaMetrics range-query export: [{labels, t (ms list), v (float list)}]."""
    f = run_path / "metrics" / f"{name}.json"
    if not f.exists():
        return []
    out = []
    for series in json.loads(f.read_text()).get("data", {}).get("result", []):
        out.append(
            {
                "labels": series["metric"],
                "t": [int(float(t) * 1000) for t, _ in series["values"]],
                "v": [float(v) for _, v in series["values"]],
            }
        )
    return out
