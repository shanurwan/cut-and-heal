"""Compile a scenario plus real pod addresses into per-pod `tc` commands.

Pure functions: no clock, no network, no Kubernetes. Everything here is unit tested, because
a wrong filter silently produces a run that looks healthy and measures nothing.

Shape of the qdisc tree on every pod's eth0:

    1: prio, every packet defaults to band 1 (unshaped: API server, DNS, metrics, controller)
    1:2 -> netem  domestic link     (dst in this region's pod CIDRs)
    1:3 -> netem  border #1         (dst in the far region's pod CIDRs)
    1:4 -> netem  border #2 ...
    ffff: ingress, where a closed node also drops what the far side sends it

Egress alone is not a partition: TCP data still arrives at a node that only drops its own
ACKs, and a gossip message gets delivered through a "cut" link until the sender's window
stalls. A closed node therefore drops border traffic in both directions.
"""

from __future__ import annotations

import ipaddress
import random
from dataclasses import dataclass

from .model import BLOCKED, LinkProfile, Scenario

DEV = "eth0"
MAX_BANDS = 16  # prio qdisc limit
INGRESS_PRIO_BASE = 100


@dataclass(frozen=True)
class Pod:
    name: str
    region: str
    ip: str
    node: str


@dataclass(frozen=True)
class Topology:
    pods: tuple[Pod, ...]
    region_cidrs: dict[str, tuple[str, ...]]

    def by_region(self, region: str) -> list[Pod]:
        return sorted((p for p in self.pods if p.region == region), key=lambda p: _ordinal(p.name))

    def region_of_ip(self, ip: str) -> str | None:
        addr = ipaddress.ip_address(ip)
        for region, cidrs in self.region_cidrs.items():
            if any(addr in ipaddress.ip_network(c) for c in cidrs):
                return region
        return None


@dataclass(frozen=True)
class Step:
    """One `tc` invocation, `at_s` seconds after the timeline starts."""

    at_s: int
    phase: str
    argv: tuple[str, ...]
    tolerate_failure: bool = False


def _ordinal(pod_name: str) -> int:
    return int(pod_name.rsplit("-", 1)[1])


def check_topology(scn: Scenario, topo: Topology) -> list[str]:
    """Reasons this topology cannot carry the scenario. Empty means it can."""
    problems: list[str] = []
    for region, spec in scn.regions.items():
        have = len(topo.by_region(region))
        if have != spec.nodes:
            problems.append(f"region {region}: {have} pods, scenario wants {spec.nodes}")
        if not topo.region_cidrs.get(region):
            problems.append(f"region {region}: no pod CIDR, so its traffic cannot be classified")
    nets = [(r, ipaddress.ip_network(c)) for r, cs in topo.region_cidrs.items() for c in cs]
    for i, (ra, na) in enumerate(nets):
        for rb, nb in nets[i + 1 :]:
            if ra != rb and na.overlaps(nb):
                problems.append(f"pod CIDRs of {ra} ({na}) and {rb} ({nb}) overlap")
    for pod in topo.pods:
        if topo.region_of_ip(pod.ip) != pod.region:
            problems.append(
                f"pod {pod.name} has {pod.ip}, outside region {pod.region}'s CIDRs; it would "
                "be shaped as if it were somewhere else"
            )
    for region in scn.regions:
        if 1 + 1 + len(_borders_of(scn, region)) > MAX_BANDS:
            problems.append(f"region {region} touches too many borders for one prio qdisc")
    return problems


def _borders_of(scn: Scenario, region: str) -> list[str]:
    return sorted(b for b, spec in scn.borders.items() if region in spec.between)


def _band(scn: Scenario, region: str, border_id: str) -> int:
    """Band number (1-based) for a border class. 1 is unshaped, 2 is domestic."""
    return 3 + _borders_of(scn, region).index(border_id)


def open_order(scn: Scenario, topo: Topology, border_id: str, seed: int) -> list[str]:
    """The fixed order in which a gated region's nodes regain the border."""
    gated = scn.borders[border_id].gated
    names = [p.name for p in topo.by_region(gated)]
    random.Random(f"{seed}:{border_id}").shuffle(names)
    return names


def open_set(scn: Scenario, topo: Topology, border_id: str, phase_idx: int, seed: int) -> set[str]:
    count = scn.open_count(scn.timeline[phase_idx], border_id)
    return set(open_order(scn, topo, border_id, seed)[:count])


@dataclass(frozen=True)
class BorderView:
    """One pod's view of one border during one phase."""

    egress: LinkProfile
    drop_ingress: bool


def border_view(scn: Scenario, topo: Topology, pod: Pod, border_id: str, phase_idx: int, seed: int) -> BorderView:
    border = scn.borders[border_id]
    link = scn.link(scn.timeline[phase_idx], border_id)
    if pod.region == border.gated and pod.name not in open_set(scn, topo, border_id, phase_idx, seed):
        return BorderView(egress=BLOCKED, drop_ingress=True)
    return BorderView(egress=link, drop_ingress=False)


def setup_commands(scn: Scenario, topo: Topology, pod: Pod) -> list[tuple[str, ...]]:
    """Build the qdisc tree with every border healthy. Idempotent: `replace` at the root."""
    borders = _borders_of(scn, pod.region)
    bands = 2 + len(borders)
    cmds: list[tuple[str, ...]] = [
        ("qdisc", "replace", "dev", DEV, "root", "handle", "1:", "prio", "bands", str(bands), "priomap", *["0"] * 16),
        (
            "qdisc",
            "add",
            "dev",
            DEV,
            "parent",
            "1:2",
            "handle",
            "20:",
            "netem",
            *scn.regions[pod.region].domestic.netem_args(),
        ),
    ]
    for border_id in borders:
        band = _band(scn, pod.region, border_id)
        cmds.append(
            (
                "qdisc",
                "add",
                "dev",
                DEV,
                "parent",
                f"1:{band}",
                "handle",
                f"{band}0:",
                "netem",
                *scn.borders[border_id].healthy.netem_args(),
            )
        )
    prio = 1
    for cidr in topo.region_cidrs[pod.region]:
        cmds.append(_egress_filter(prio, cidr, 2))
        prio += 1
    for border_id in borders:
        far = scn.borders[border_id].other(pod.region)
        for cidr in topo.region_cidrs[far]:
            cmds.append(_egress_filter(prio, cidr, _band(scn, pod.region, border_id)))
            prio += 1
    cmds.append(("qdisc", "add", "dev", DEV, "handle", "ffff:", "ingress"))
    return cmds


def _egress_filter(prio: int, cidr: str, band: int) -> tuple[str, ...]:
    return (
        "filter",
        "add",
        "dev",
        DEV,
        "parent",
        "1:",
        "protocol",
        "ip",
        "prio",
        str(prio),
        "u32",
        "match",
        "ip",
        "dst",
        cidr,
        "flowid",
        f"1:{band}",
    )


def _ingress_prio(scn: Scenario, topo: Topology, pod: Pod, border_id: str, cidr: str) -> int:
    """Stable per (border, CIDR), so a drop filter can be deleted by priority alone."""
    slot = 0
    for bid in _borders_of(scn, pod.region):
        for c in topo.region_cidrs[scn.borders[bid].other(pod.region)]:
            if bid == border_id and c == cidr:
                return INGRESS_PRIO_BASE + slot
            slot += 1
    raise KeyError((border_id, cidr))


def pod_plan(scn: Scenario, topo: Topology, pod: Pod, seed: int) -> list[Step]:
    """Every change this pod must make, phase by phase. Phases that change nothing emit nothing."""
    steps: list[Step] = []
    borders = _borders_of(scn, pod.region)
    prev = {b: BorderView(egress=scn.borders[b].healthy, drop_ingress=False) for b in borders}
    for idx, (phase, start_s, _end) in enumerate(scn.phase_windows()):
        for border_id in borders:
            view = border_view(scn, topo, pod, border_id, idx, seed)
            before = prev[border_id]
            far_cidrs = topo.region_cidrs[scn.borders[border_id].other(pod.region)]
            # Close ingress before egress and open it after, so a border is never half open
            # in the direction that leaks delivered messages.
            if view.drop_ingress and not before.drop_ingress:
                for cidr in far_cidrs:
                    p = _ingress_prio(scn, topo, pod, border_id, cidr)
                    steps.append(
                        Step(
                            start_s,
                            phase,
                            (
                                "filter",
                                "add",
                                "dev",
                                DEV,
                                "parent",
                                "ffff:",
                                "protocol",
                                "ip",
                                "prio",
                                str(p),
                                "u32",
                                "match",
                                "ip",
                                "src",
                                cidr,
                                "action",
                                "drop",
                            ),
                        )
                    )
            if view.egress != before.egress:
                band = _band(scn, pod.region, border_id)
                steps.append(
                    Step(
                        start_s,
                        phase,
                        (
                            "qdisc",
                            "change",
                            "dev",
                            DEV,
                            "parent",
                            f"1:{band}",
                            "handle",
                            f"{band}0:",
                            "netem",
                            *view.egress.netem_args(),
                        ),
                    )
                )
            if before.drop_ingress and not view.drop_ingress:
                for cidr in far_cidrs:
                    p = _ingress_prio(scn, topo, pod, border_id, cidr)
                    steps.append(
                        Step(
                            start_s,
                            phase,
                            ("filter", "del", "dev", DEV, "parent", "ffff:", "protocol", "ip", "prio", str(p)),
                        )
                    )
            prev[border_id] = view
    return steps


def expected_reach(scn: Scenario, topo: Topology, phase_idx: int, seed: int) -> dict[tuple[str, str], bool]:
    """Whether a network path exists between each ordered pair of regions in a phase.

    A path exists if the regions are the same, or some chain of borders joins them where each
    border has at least one open node. Analysis uses this to tell "the protocol failed to
    deliver" from "there was no path to deliver over".
    """
    regions = list(scn.regions)
    adj: dict[str, set[str]] = {r: {r} for r in regions}
    for bid, border in scn.borders.items():
        if open_set(scn, topo, bid, phase_idx, seed):
            a, b = border.between
            adj[a].add(b)
            adj[b].add(a)
    reach: dict[tuple[str, str], bool] = {}
    for src in regions:
        seen, frontier = {src}, [src]
        while frontier:
            for nxt in adj[frontier.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        for dst in regions:
            reach[(src, dst)] = dst in seen
    return reach
