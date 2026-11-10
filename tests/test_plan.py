from __future__ import annotations

from dataclasses import replace

from cutandheal.model import Scenario
from cutandheal.plan import (
    Pod,
    Topology,
    check_topology,
    expected_reach,
    open_order,
    open_set,
    pod_plan,
    setup_commands,
)

SEED = 7


def _pod(topo: Topology, name: str) -> Pod:
    return next(p for p in topo.pods if p.name == name)


def _phase_index(scn: Scenario, name: str) -> int:
    return [p.name for p in scn.timeline].index(name)


def test_setup_classifies_domestic_and_border_traffic_and_leaves_the_rest_alone(scn, topo) -> None:
    cmds = [" ".join(c) for c in setup_commands(scn, topo, _pod(topo, "inside-0"))]
    # Everything defaults to band 1, which has no netem: the API server, DNS, metrics and the
    # controller must never be shaped or a cut would also cut the experiment's own control.
    assert cmds[0] == "qdisc replace dev eth0 root handle 1: prio bands 3 priomap " + " ".join(["0"] * 16)
    assert "qdisc add dev eth0 parent 1:2 handle 20: netem delay 10ms 2ms loss 0%" in cmds
    assert "qdisc add dev eth0 parent 1:3 handle 30: netem delay 50ms 0ms loss 0.5%" in cmds
    assert any("match ip dst 10.42.2.0/23 flowid 1:2" in c for c in cmds)
    assert any("match ip dst 10.42.4.0/23 flowid 1:3" in c for c in cmds)
    assert cmds[-1] == "qdisc add dev eth0 handle ffff: ingress"


def test_the_far_side_sees_the_same_border_from_its_own_addresses(scn, topo) -> None:
    cmds = [" ".join(c) for c in setup_commands(scn, topo, _pod(topo, "outside-0"))]
    assert any("match ip dst 10.42.4.0/23 flowid 1:2" in c for c in cmds)
    assert any("match ip dst 10.42.2.0/23 flowid 1:3" in c for c in cmds)


def test_open_sets_are_nested_and_reproducible(scn, topo) -> None:
    order = open_order(scn, topo, "edge", SEED)
    assert sorted(order) == [f"inside-{i}" for i in range(4)]
    assert order == open_order(scn, topo, "edge", SEED)
    cut, bridge, half, healed = (
        open_set(scn, topo, "edge", _phase_index(scn, n), SEED) for n in ("cut", "bridge", "half", "healed")
    )
    assert cut == set()
    assert len(bridge) == 1 and len(half) == 2 and len(healed) == 4
    # The node that keeps the border at 1 open is still open at 2: restoration never closes
    # a link it had already opened.
    assert cut < bridge < half < healed


def test_a_closed_node_drops_both_directions_ingress_first(scn, topo) -> None:
    closed = next(
        n
        for n in open_order(scn, topo, "edge", SEED)
        if n not in open_set(scn, topo, "edge", _phase_index(scn, "bridge"), SEED)
    )
    steps = [s for s in pod_plan(scn, topo, _pod(topo, closed), SEED) if s.phase == "cut"]
    argv = [" ".join(s.argv) for s in steps]
    assert argv == [
        "filter add dev eth0 parent ffff: protocol ip prio 100 u32 match ip src 10.42.4.0/23 action drop",
        "qdisc change dev eth0 parent 1:3 handle 30: netem delay 0ms 0ms loss 100%",
    ]
    assert {s.at_s for s in steps} == {60}


def test_reopening_restores_the_healthy_profile_then_lifts_the_ingress_drop(scn, topo) -> None:
    order = open_order(scn, topo, "edge", SEED)
    first_open = order[0]
    steps = [" ".join(s.argv) for s in pod_plan(scn, topo, _pod(topo, first_open), SEED) if s.phase == "bridge"]
    assert steps == [
        "qdisc change dev eth0 parent 1:3 handle 30: netem delay 50ms 0ms loss 0.5%",
        "filter del dev eth0 parent ffff: protocol ip prio 100",
    ]


def test_a_pod_only_changes_in_the_phase_its_own_state_changes(scn, topo) -> None:
    order = open_order(scn, topo, "edge", SEED)
    last = order[-1]  # reopens only when the border is fully healed
    phases = [s.phase for s in pod_plan(scn, topo, _pod(topo, last), SEED)]
    assert set(phases) == {"cut", "healed"}


def test_the_ungated_side_never_blocks(scn, topo) -> None:
    # Outside nodes keep sending; packets die at the closed node's ingress. With the link
    # profile unchanged across phases, an outside node has nothing to do at all.
    assert pod_plan(scn, topo, _pod(topo, "outside-3"), SEED) == []


def test_a_degraded_border_changes_both_sides(scn, topo) -> None:
    data = scn.model_dump()
    data["timeline"][3]["borders"]["edge"]["link"] = {"delay_ms": 300, "loss_pct": 5, "rate_mbit": 1}
    throttled = Scenario.model_validate(data)
    outside = [" ".join(s.argv) for s in pod_plan(throttled, topo, _pod(topo, "outside-0"), SEED)]
    assert outside == [
        "qdisc change dev eth0 parent 1:3 handle 30: netem delay 300ms 0ms loss 5% rate 1mbit",
        "qdisc change dev eth0 parent 1:3 handle 30: netem delay 50ms 0ms loss 0.5%",
    ]


def test_expected_reach_follows_open_borders(scn, topo) -> None:
    cut = expected_reach(scn, topo, _phase_index(scn, "cut"), SEED)
    assert cut[("inside", "inside")] and cut[("outside", "outside")]
    assert not cut[("inside", "outside")] and not cut[("outside", "inside")]
    bridge = expected_reach(scn, topo, _phase_index(scn, "bridge"), SEED)
    assert all(bridge.values())


def test_reach_is_transitive_across_three_regions() -> None:
    scn = Scenario.model_validate(
        {
            "name": "chain",
            "title": "a-b-c",
            "regions": {r: {"nodes": 2} for r in ("a", "b", "c")},
            "borders": {
                "ab": {"between": ["a", "b"], "gated": "a", "healthy": {}},
                "bc": {"between": ["b", "c"], "gated": "c", "healthy": {}},
            },
            "bootstrap_region": "b",
            "timeline": [
                {"name": "baseline", "duration_s": 30},
                {"name": "c-cut", "duration_s": 30, "borders": {"bc": {"open_nodes": 0}}},
            ],
        }
    )
    topo = Topology(
        pods=tuple(Pod(f"{r}-{i}", r, f"10.42.{n}.{10 + i}", r) for n, r in enumerate("abc") for i in range(2)),
        region_cidrs={r: (f"10.42.{n}.0/24",) for n, r in enumerate("abc")},
    )
    assert check_topology(scn, topo) == []
    assert all(expected_reach(scn, topo, 0, 1).values())
    cut = expected_reach(scn, topo, 1, 1)
    assert cut[("a", "b")] and not cut[("a", "c")] and not cut[("c", "b")]
    # b sits on two borders, so it needs a band for each.
    b_cmds = [" ".join(c) for c in setup_commands(scn, topo, topo.pods[2])]
    assert "bands 4" in b_cmds[0]
    assert any("dst 10.42.0.0/24 flowid 1:3" in c for c in b_cmds)
    assert any("dst 10.42.2.0/24 flowid 1:4" in c for c in b_cmds)


def test_topology_problems_are_named(scn, topo) -> None:
    assert check_topology(scn, topo) == []
    stray = replace(topo.pods[0], ip="10.42.4.99")
    problems = check_topology(scn, Topology(pods=(stray, *topo.pods[1:]), region_cidrs=topo.region_cidrs))
    assert any("shaped as if it were somewhere else" in p for p in problems)
    short = Topology(pods=topo.pods[1:], region_cidrs=topo.region_cidrs)
    assert any("3 pods, scenario wants 4" in p for p in check_topology(scn, short))
    overlapping = Topology(pods=topo.pods, region_cidrs={"inside": ("10.42.0.0/16",), "outside": ("10.42.4.0/23",)})
    assert any("overlap" in p for p in check_topology(scn, overlapping))
    assert any(
        "no pod CIDR" in p
        for p in check_topology(scn, Topology(pods=topo.pods, region_cidrs={"inside": ("10.42.2.0/23",)}))
    )
