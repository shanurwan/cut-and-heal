"""In-cluster run controller.

One process owns a run end to end, so the run has one clock and one record:

  1. wait for every node pod, read the real pod CIDRs, refuse a topology that cannot
     carry the scenario
  2. hand each shaper its qdisc setup, wait until all have acknowledged
  3. wait until every node has a gossipsub mesh, then fix T0 and publish the timeline
  4. publish messages at a fixed rate on an absolute schedule
  5. collect raw evidence: node logs, shaper logs, acknowledgements, host load, metrics

It judges nothing. Verdicts are computed offline from the files it writes, so they can be
recomputed, and argued with, without rerunning anything.
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import json
import logging
import os
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import aiohttp
from aiohttp import web

from . import __version__
from .kube import Kube, PodInfo
from .model import Scenario, load_scenario
from .plan import Pod, Topology, check_topology, open_order, pod_plan, setup_commands

log = logging.getLogger("cah.controller")

MESH_METRIC = "libp2p_gossipsub_peers_per_topic_mesh"
PUBLISH_PORT = 8645
METRICS_PORT = 8008

# Exported for the report. `region` and `pod` labels are attached at scrape time.
VM_QUERIES = {
    "mesh_mean_by_region": f"avg by (region) ({MESH_METRIC})",
    "mesh_min_by_region": f"min by (region) ({MESH_METRIC})",
    "mesh_by_pod": f"sum by (pod, region) ({MESH_METRIC})",
    "peers_mean_by_region": "avg by (region) (libp2p_peers)",
    "no_peers_nodes_by_region": "sum by (region) (libp2p_gossipsub_no_peers_topics)",
    "low_peers_nodes_by_region": "sum by (region) (libp2p_gossipsub_low_peers_topics)",
    "bytes_out_rate_by_pod": 'sum by (pod, region) (rate(libp2p_network_bytes_total{direction="out"}[20s]))',
    "dial_rate_by_region": "sum by (region) (rate(libp2p_total_dial_attempts_total[20s]))",
    "failed_dial_rate_by_region": "sum by (region) (rate(libp2p_failed_dials_total[20s]))",
    "scraped_nodes_by_region": 'count by (region) (up{job="nodes"} == 1)',
}


def now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass
class Config:
    scenario_path: str = os.environ.get("CAH_SCENARIO", "/config/scenario.yaml")
    results: Path = Path(os.environ.get("CAH_RESULTS", "/results"))
    run_id: str = os.environ.get("CAH_RUN_ID", "run")
    seed: int = int(os.environ.get("CAH_SEED", "1"))
    lead_s: int = int(os.environ.get("CAH_LEAD_S", "20"))
    settle_s: int = int(os.environ.get("CAH_SETTLE_S", "45"))
    drain_s: int = int(os.environ.get("CAH_DRAIN_S", "30"))
    min_mesh: int = int(os.environ.get("CAH_MIN_MESH", "4"))
    ready_timeout_s: int = int(os.environ.get("CAH_READY_TIMEOUT_S", "900"))
    vm_url: str = os.environ.get("CAH_VM_URL", "")
    images: str = os.environ.get("CAH_IMAGES", "{}")
    port: int = int(os.environ.get("CAH_PORT", "8080"))


@dataclass
class State:
    setup: dict[str, str] = field(default_factory=dict)
    plan: dict[str, str] = field(default_factory=dict)
    acks: list[dict] = field(default_factory=list)
    stage: str = "starting"

    def acked(self, kind: str, phase: str | None = None) -> set[str]:
        return {a["pod"] for a in self.acks if a["kind"] == kind and (phase is None or a["phase"] == phase)}


def make_app(state: State) -> web.Application:
    async def setup(req: web.Request) -> web.Response:
        text = state.setup.get(req.match_info["pod"])
        return web.Response(text=text) if text else web.Response(status=204)

    async def plan(req: web.Request) -> web.Response:
        text = state.plan.get(req.match_info["pod"])
        return web.Response(text=text) if text else web.Response(status=204)

    async def ack(req: web.Request) -> web.Response:
        q = req.query
        state.acks.append(
            {
                "received_ms": now_ms(),
                "pod": q["pod"],
                "kind": q["kind"],
                "phase": q["phase"],
                "planned_ms": int(q["planned_ms"]),
                "applied_ms": int(q["applied_ms"]),
                "rc": int(q["rc"]),
            }
        )
        return web.Response(status=204)

    async def status(_req: web.Request) -> web.Response:
        return web.json_response({"stage": state.stage, "acks": len(state.acks)})

    app = web.Application()
    app.add_routes(
        [
            web.get("/v1/setup/{pod}", setup),
            web.get("/v1/plan/{pod}", plan),
            web.post("/v1/ack", ack),
            web.get("/v1/status", status),
        ]
    )
    return app


def plan_text(scn: Scenario, topo: Topology, pod: Pod, seed: int, t0_ms: int) -> str:
    """Wire format for the shaper: `epoch_ms|phase|tc args`, one line per command.

    A phase in which this pod changes nothing still gets one line with empty args, so every
    pod acknowledges every phase and a missing acknowledgement always means something.
    """
    by_phase: dict[str, list] = {}
    for step in pod_plan(scn, topo, pod, seed):
        by_phase.setdefault(step.phase, []).append(step)
    lines = []
    for name, start_s, _end in scn.phase_windows():
        at = t0_ms + start_s * 1000
        steps = by_phase.get(name, [])
        if not steps:
            lines.append(f"{at}|{name}|")
        for s in steps:
            lines.append(f"{at}|{name}|{' '.join(s.argv)}")
    return "\n".join(lines) + "\n"


async def wait_for_topology(kube: Kube, scn: Scenario, timeout_s: int) -> tuple[Topology, list[PodInfo]]:
    deadline = time.monotonic() + timeout_s
    while True:
        infos = await kube.node_pods()
        running = [p for p in infos if p.phase == "Running" and p.ip]
        if len(running) == scn.total_nodes == len(infos):
            cidrs = await kube.region_cidrs()
            pods = tuple(Pod(p.name, p.region, p.ip, p.node) for p in running)
            return Topology(pods=pods, region_cidrs=cidrs), infos
        if time.monotonic() > deadline:
            raise TimeoutError(f"{len(running)}/{scn.total_nodes} node pods running after {timeout_s}s")
        log.info("waiting for pods: %d/%d running", len(running), scn.total_nodes)
        await asyncio.sleep(5)


async def wait_for_acks(state: State, kind: str, want: set[str], timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        missing = want - state.acked(kind)
        if not missing:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"{len(missing)} pods never acknowledged {kind}: {sorted(missing)[:5]}")
        await asyncio.sleep(1)


def parse_metric_sum(text: str, name: str) -> float | None:
    total, seen = 0.0, False
    for line in text.splitlines():
        if line.startswith(name) and line[len(name) : len(name) + 1] in ("{", " "):
            total += float(line.rsplit(" ", 1)[1])
            seen = True
    return total if seen else None


async def mesh_sizes(session: aiohttp.ClientSession, topo: Topology) -> dict[str, float | None]:
    async def one(pod: Pod) -> tuple[str, float | None]:
        try:
            async with session.get(
                f"http://{pod.ip}:{METRICS_PORT}/metrics", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return pod.name, parse_metric_sum(await resp.text(), MESH_METRIC)
        except (TimeoutError, aiohttp.ClientError):
            return pod.name, None

    return dict(await asyncio.gather(*(one(p) for p in topo.pods)))


async def wait_for_mesh(session: aiohttp.ClientSession, topo: Topology, min_mesh: int, timeout_s: int) -> dict:
    """Every node must hold a mesh before T0. A run that starts unmeshed measures bootstrapping."""
    need = min(min_mesh, len(topo.pods) - 1)
    deadline = time.monotonic() + timeout_s
    while True:
        sizes = await mesh_sizes(session, topo)
        short = {p: s for p, s in sizes.items() if s is None or s < need}
        if not short:
            return sizes
        if time.monotonic() > deadline:
            raise TimeoutError(f"{len(short)} nodes below mesh size {need}: {dict(list(short.items())[:5])}")
        log.info("waiting for mesh: %d/%d nodes at >= %d", len(sizes) - len(short), len(sizes), need)
        await asyncio.sleep(5)


def publish_order(scn: Scenario, topo: Topology, seed: int) -> list[Pod]:
    """Origins alternate between regions so each region originates the same number of messages,
    however small it is; within a region, a seeded shuffle visits every node before repeating."""
    rng = random.Random(f"{seed}:publish")
    per_region = {}
    for region in sorted(scn.regions):
        pods = topo.by_region(region)
        rng.shuffle(pods)
        per_region[region] = pods
    regions = sorted(per_region)
    order = []
    for i in range(int(scn.duration_s * scn.publish.rate_hz)):
        pods = per_region[regions[i % len(regions)]]
        order.append(pods[(i // len(regions)) % len(pods)])
    return order


async def publisher(
    session: aiohttp.ClientSession, scn: Scenario, order: list[Pod], t0_ms: int, out: list[dict]
) -> None:
    body = {"topic": scn.publish.topic, "msgSize": scn.publish.size_bytes, "version": 1}
    interval_ms = 1000 / scn.publish.rate_hz
    tasks = set()

    async def send(seq: int, pod: Pod, planned: int) -> None:
        sent = now_ms()
        rec = {
            "seq": seq,
            "planned_ms": planned,
            "sent_ms": sent,
            "pod": pod.name,
            "region": pod.region,
            "status": 0,
            "http_ms": 0,
            "error": "",
        }
        try:
            async with session.post(
                f"http://{pod.ip}:{PUBLISH_PORT}/publish", json=body, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                await resp.read()
                rec["status"] = resp.status
        except (TimeoutError, aiohttp.ClientError) as exc:
            rec["error"] = type(exc).__name__
        rec["http_ms"] = now_ms() - sent
        out.append(rec)

    for seq, pod in enumerate(order):
        planned = t0_ms + round(seq * interval_ms)
        delay = (planned - now_ms()) / 1000
        if delay > 0:
            await asyncio.sleep(delay)
        task = asyncio.create_task(send(seq, pod, planned))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    if tasks:
        await asyncio.gather(*tasks)


async def load_sampler(out: list[dict], stop: asyncio.Event, period_s: float = 5.0) -> None:
    """Host CPU and load. A saturated host stretches every latency; the run must show it was not."""

    def read() -> tuple[int, int]:
        parts = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        idle = parts[3] + parts[4]
        return sum(parts), idle

    total0, idle0 = read()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=period_s)
        except TimeoutError:
            pass
        total1, idle1 = read()
        dt = total1 - total0
        busy = 1 - (idle1 - idle0) / dt if dt else 0.0
        out.append(
            {
                "t_ms": now_ms(),
                "cpu_busy": round(busy, 4),
                "load1": float(Path("/proc/loadavg").read_text().split()[0]),
                "cpus": os.cpu_count(),
            }
        )
        total0, idle0 = total1, idle1


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


async def collect_logs(kube: Kube, pods: list[str], out: Path) -> dict[str, str]:
    out.mkdir(parents=True, exist_ok=True)
    errors: dict[str, str] = {}
    sem = asyncio.Semaphore(16)

    async def one(pod: str, container: str) -> None:
        async with sem:
            try:
                data = await kube.pod_log(pod, container)
                (out / f"{pod}.{container}.log.gz").write_bytes(gzip.compress(data))
            except Exception as exc:  # recorded, then judged by the validity rules
                errors[f"{pod}/{container}"] = repr(exc)

    await asyncio.gather(*(one(p, c) for p in pods for c in ("node", "shaper")))
    return errors


async def export_metrics(
    session: aiohttp.ClientSession, vm_url: str, start_ms: int, end_ms: int, out: Path
) -> dict[str, str]:
    out.mkdir(parents=True, exist_ok=True)
    errors: dict[str, str] = {}
    for name, query in VM_QUERIES.items():
        try:
            async with session.get(
                f"{vm_url}/api/v1/query_range",
                params={"query": query, "start": start_ms / 1000, "end": end_ms / 1000, "step": "5s"},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                resp.raise_for_status()
                (out / f"{name}.json").write_text(json.dumps(await resp.json()))
        except Exception as exc:
            errors[name] = repr(exc)
    return errors


async def run(cfg: Config) -> None:
    scn = load_scenario(cfg.scenario_path)
    cfg.results.mkdir(parents=True, exist_ok=True)
    state = State()
    runner = web.AppRunner(make_app(state), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", cfg.port).start()

    kube = Kube.in_cluster()
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0))
    record: dict = {
        "run_id": cfg.run_id,
        "seed": cfg.seed,
        "tool_version": __version__,
        "scenario": scn.model_dump(mode="json"),
        "images": json.loads(cfg.images),
        "config": {"lead_s": cfg.lead_s, "settle_s": cfg.settle_s, "drain_s": cfg.drain_s, "min_mesh": cfg.min_mesh},
        "status": "failed",
        "failure": "",
    }
    publishes: list[dict] = []
    load: list[dict] = []
    stop = asyncio.Event()
    sampler = None
    try:
        state.stage = "waiting-for-pods"
        topo, _ = await wait_for_topology(kube, scn, cfg.ready_timeout_s)
        record["topology"] = {"pods": [asdict(p) for p in topo.pods], "region_cidrs": topo.region_cidrs}
        record["open_order"] = {b: open_order(scn, topo, b, cfg.seed) for b in scn.borders}
        problems = check_topology(scn, topo)
        if problems:
            raise RuntimeError("topology cannot carry the scenario: " + "; ".join(problems))

        state.stage = "shaper-setup"
        names = {p.name for p in topo.pods}
        state.setup = {p.name: "\n".join(" ".join(c) for c in setup_commands(scn, topo, p)) + "\n" for p in topo.pods}
        await wait_for_acks(state, "setup", names, cfg.ready_timeout_s)

        state.stage = "waiting-for-mesh"
        record["mesh_at_start"] = await wait_for_mesh(session, topo, cfg.min_mesh, cfg.ready_timeout_s)
        await asyncio.sleep(cfg.settle_s)

        t0_ms = now_ms() + cfg.lead_s * 1000
        record["t0_ms"] = t0_ms
        record["phases"] = [
            {"name": n, "start_ms": t0_ms + s * 1000, "end_ms": t0_ms + e * 1000} for n, s, e in scn.phase_windows()
        ]
        state.plan = {p.name: plan_text(scn, topo, p, cfg.seed, t0_ms) for p in topo.pods}
        state.stage = "running"
        sampler = asyncio.create_task(load_sampler(load, stop))
        log.info("T0 in %ds; timeline %ds; %d nodes", cfg.lead_s, scn.duration_s, len(topo.pods))

        await publisher(session, scn, publish_order(scn, topo, cfg.seed), t0_ms, publishes)
        end_ms = t0_ms + scn.duration_s * 1000
        await asyncio.sleep(max(0.0, (end_ms - now_ms()) / 1000) + cfg.drain_s)
        record["end_ms"] = end_ms
        record["status"] = "completed"
    except Exception as exc:
        log.exception("run failed")
        record["failure"] = repr(exc)
    finally:
        stop.set()
        if sampler:
            await sampler
        state.stage = "collecting"
        infos = await kube.node_pods()
        record["pods_final"] = [asdict(p) for p in infos]
        record["log_errors"] = await collect_logs(kube, [p.name for p in infos], cfg.results / "logs")
        if cfg.vm_url and "t0_ms" in record:
            record["metric_errors"] = await export_metrics(
                session, cfg.vm_url, record["t0_ms"] - 60_000, now_ms(), cfg.results / "metrics"
            )
        write_csv(cfg.results / "publishes.csv", sorted(publishes, key=lambda r: r["seq"]))
        write_csv(cfg.results / "acks.csv", state.acks)
        write_csv(cfg.results / "load.csv", load)
        (cfg.results / "run.json").write_text(json.dumps(record, indent=1))
        (cfg.results / "DONE").write_text(record["status"] + "\n")
        state.stage = record["status"]
        log.info("run %s: %s %s", cfg.run_id, record["status"], record["failure"])
        await session.close()
        await kube.close()
    # Stay up so the operator can copy the results out; the pod has no other storage.
    await asyncio.Event().wait()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run(Config()))


if __name__ == "__main__":
    main()
