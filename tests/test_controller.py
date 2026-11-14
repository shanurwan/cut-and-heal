from __future__ import annotations

from collections import Counter

import yaml
from aiohttp.test_utils import TestClient, TestServer

from cutandheal.controller import State, make_app, parse_metric_sum, plan_text, publish_order
from cutandheal.render import RenderOptions, render

T0 = 1_800_000_000_000


def test_every_pod_gets_a_line_for_every_phase(scn, topo) -> None:
    # A pod with nothing to change still acknowledges the phase, so a missing
    # acknowledgement always means a shaper that did not run.
    for pod in topo.pods:
        lines = plan_text(scn, topo, pod, seed=7, t0_ms=T0).strip().splitlines()
        phases = [line.split("|")[1] for line in lines]
        assert list(dict.fromkeys(phases)) == [p.name for p in scn.timeline]
        times = [int(line.split("|")[0]) for line in lines]
        assert times == sorted(times) and times[0] == T0


def test_plan_lines_carry_absolute_times_and_plain_tc_arguments(scn, topo) -> None:
    text = plan_text(scn, topo, topo.pods[0], seed=7, t0_ms=T0)
    cut = [line for line in text.splitlines() if "|cut|" in line]
    assert all(line.startswith(f"{T0 + 60_000}|cut|") for line in cut)
    assert not any(ch in text for ch in ";&$`")  # these lines are fed to `tc -batch`, never to a shell


def test_publishing_is_balanced_across_regions_and_visits_every_node(scn, topo) -> None:
    order = publish_order(scn, topo, seed=7)
    assert len(order) == scn.duration_s
    per_region = Counter(p.region for p in order)
    assert per_region["inside"] == per_region["outside"]
    assert {p.name for p in order} == {p.name for p in topo.pods}
    assert order == publish_order(scn, topo, seed=7)


def test_metric_sum_matches_the_name_exactly() -> None:
    text = (
        'libp2p_gossipsub_peers_per_topic_mesh{topic="other"} 3.0\n'
        'libp2p_gossipsub_peers_per_topic_mesh{topic="test"} 2.0\n'
        "libp2p_gossipsub_peers_per_topic_mesh_created 1794336438.0\n"
        "libp2p_peers 4.0\n"
    )
    assert parse_metric_sum(text, "libp2p_gossipsub_peers_per_topic_mesh") == 5.0
    assert parse_metric_sum(text, "libp2p_peers") == 4.0
    assert parse_metric_sum(text, "absent") is None


async def test_shaper_protocol_setup_then_plan_then_ack() -> None:
    state = State()
    async with TestClient(TestServer(make_app(state))) as client:
        assert (await client.get("/v1/setup/inside-0")).status == 204  # not ready: shaper retries
        state.setup["inside-0"] = "qdisc replace dev eth0 root\n"
        resp = await client.get("/v1/setup/inside-0")
        assert resp.status == 200 and (await resp.text()).startswith("qdisc replace")
        assert (await client.get("/v1/plan/inside-0")).status == 204
        resp = await client.post(
            "/v1/ack",
            params={
                "pod": "inside-0",
                "kind": "phase",
                "phase": "cut",
                "planned_ms": T0,
                "applied_ms": T0 + 9,
                "rc": 0,
            },
        )
        assert resp.status == 204
    assert state.acked("phase", "cut") == {"inside-0"}
    assert state.acks[0]["applied_ms"] - state.acks[0]["planned_ms"] == 9


def test_manifests_pin_nodes_to_their_region_and_give_only_the_shaper_net_admin(scn) -> None:
    opt = RenderOptions(namespace="cah", run_id="r1", seed=7, controller_image="cah:test")
    docs = render(scn, opt, "name: t\n")
    yaml.safe_dump_all(docs)
    sets = {d["metadata"]["name"]: d for d in docs if d["kind"] == "StatefulSet"}
    assert set(sets) == {"bootstrap", "inside", "outside"}
    spec = sets["inside"]["spec"]
    assert spec["replicas"] == 4
    pod = spec["template"]["spec"]
    assert pod["nodeSelector"] == {"cut-and-heal/region": "inside"}
    node, shaper = pod["containers"]
    assert "securityContext" not in node
    assert shaper["securityContext"] == {"capabilities": {"add": ["NET_ADMIN"]}}
    assert "@sha256:" in node["image"] and node["image"] == shaper["image"]
    assert sets["bootstrap"]["spec"]["template"]["spec"]["nodeSelector"] == {"cut-and-heal/region": "outside"}


def test_the_controller_can_read_pods_and_nodes_and_nothing_else(scn) -> None:
    docs = render(scn, RenderOptions(namespace="cah", run_id="r1", seed=7, controller_image="cah:test"), "")
    rules = [
        (d["kind"], d["metadata"]["name"], r) for d in docs if d["kind"] in ("Role", "ClusterRole") for r in d["rules"]
    ]
    verbs = {v for _, _, r in rules for v in r["verbs"]}
    assert verbs <= {"get", "list", "watch"}
    cluster = [r for kind, _, r in rules if kind == "ClusterRole"]
    assert cluster == [{"apiGroups": [""], "resources": ["nodes"], "verbs": ["get", "list"]}]


def test_the_dashboard_queries_only_metrics_the_run_exports(scn) -> None:
    from cutandheal.controller import VM_QUERIES
    from cutandheal.render import DASHBOARD_PANELS, dashboard

    opt = RenderOptions(namespace="cah", run_id="r1", seed=7, controller_image="cah:test", grafana=True)
    kinds = [(d["kind"], d["metadata"]["name"]) for d in render(scn, opt, "")]
    assert ("Pod", "grafana") in kinds and ("ConfigMap", "grafana") in kinds
    known = " ".join(VM_QUERIES.values())
    for _title, expr, _unit in DASHBOARD_PANELS:
        metric = expr.split("(")[-1].split("{")[0].split(")")[0].split("[")[0]
        assert metric in known, metric
    assert len({p["id"] for p in dashboard()["panels"]}) == len(DASHBOARD_PANELS)


def test_sysctls_reach_every_libp2p_pod_and_nothing_else(scn) -> None:
    opt = RenderOptions(namespace="cah", run_id="r1", seed=7, controller_image="cah:test")
    plain = [d for d in render(scn, opt, "") if d["kind"] == "StatefulSet"]
    assert all("securityContext" not in d["spec"]["template"]["spec"] for d in plain)

    tuned = scn.model_copy(update={"sysctls": {"net.ipv4.tcp_retries2": "5"}})
    docs = render(tuned, opt, "")
    want = {"sysctls": [{"name": "net.ipv4.tcp_retries2", "value": "5"}]}
    sets = [d for d in docs if d["kind"] == "StatefulSet"]
    assert len(sets) == 3 and all(d["spec"]["template"]["spec"]["securityContext"] == want for d in sets)
    others = [d for d in docs if d["kind"] in ("Pod", "Deployment")]
    assert all("sysctls" not in str(d) for d in others)
