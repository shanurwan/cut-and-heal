"""Scenarios about the lab: CPU caps on region nodes, and borders shut by NetworkPolicy."""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from cutandheal.model import Scenario
from cutandheal.plan import pod_plan
from cutandheal.policy import border_policies, desired_policies
from cutandheal.render import RenderOptions, render
from cutandheal.report import write_report

from .conftest import SCENARIO, make_topology
from .synth import write_run

# Every border either fully open or fully shut, which a policy cut requires.
WHOLE = copy.deepcopy(SCENARIO)
WHOLE["timeline"] = [
    {"name": "baseline", "duration_s": 60},
    {"name": "cut", "duration_s": 60, "borders": {"edge": {"open_nodes": 0}}},
    {"name": "healed", "duration_s": 60},
]


def _policy_scn() -> Scenario:
    return Scenario.model_validate({**WHOLE, "cut": "networkpolicy"})


def test_a_policy_cut_cannot_open_part_of_a_border() -> None:
    with pytest.raises(ValidationError, match="every pod or none"):
        Scenario.model_validate({**SCENARIO, "cut": "networkpolicy"})
    assert _policy_scn().cut == "networkpolicy"


def test_lab_cpus_must_name_regions_and_be_positive() -> None:
    assert Scenario.model_validate({**WHOLE, "lab": {"cpus": {"inside": 0.5}}}).lab.cpus == {"inside": 0.5}
    with pytest.raises(ValidationError, match="unknown region"):
        Scenario.model_validate({**WHOLE, "lab": {"cpus": {"mars": 1}}})
    with pytest.raises(ValidationError, match="positive"):
        Scenario.model_validate({**WHOLE, "lab": {"cpus": {"inside": 0}}})


def test_with_a_policy_cut_the_shaper_never_drops_and_the_controller_shuts_both_sides() -> None:
    scn = _policy_scn()
    topo = make_topology(scn)
    for pod in topo.pods:
        assert all("drop" not in s.argv and "100%" not in s.argv for s in pod_plan(scn, topo, pod, 7))
    assert desired_policies(scn, 0) == {} and desired_policies(scn, 2) == {}
    shut = desired_policies(scn, 1)
    assert set(shut) == {"cut-edge-inside", "cut-edge-outside"}
    spec = shut["cut-edge-inside"]["spec"]
    assert spec["podSelector"] == {"matchLabels": {"cut-and-heal/region": "inside"}}
    assert spec["policyTypes"] == ["Ingress", "Egress"]
    far = {"key": "cut-and-heal/region", "operator": "NotIn", "values": ["outside"]}
    assert spec["ingress"][0]["from"][0]["podSelector"]["matchExpressions"] == [far]
    assert spec["egress"][0]["to"][0]["podSelector"]["matchExpressions"] == [far]
    assert border_policies(scn, "edge") == shut


def test_only_a_policy_cut_lets_the_controller_write_and_only_policies() -> None:
    opt = RenderOptions(namespace="cah", run_id="r1", seed=7, controller_image="cah:test")

    def writes(scn: Scenario) -> list[dict]:
        roles = [d for d in render(scn, opt, "") if d["kind"] == "Role" and d["metadata"]["name"] == "controller"]
        return [r for r in roles[0]["rules"] if set(r["verbs"]) - {"get", "list", "watch"}]

    assert writes(Scenario.model_validate(WHOLE)) == []
    assert writes(_policy_scn()) == [
        {"apiGroups": ["networking.k8s.io"], "resources": ["networkpolicies"], "verbs": ["create", "delete"]}
    ]


def _stat(wall_s: float, usage_s: float, periods: int, throttled: int, throttled_s: float) -> str:
    return (
        f"wall_ns {int(wall_s * 1e9)}\nusage_usec {int(usage_s * 1e6)}\nuser_usec 1\nsystem_usec 1\n"
        f"nr_periods {periods}\nnr_throttled {throttled}\nthrottled_usec {int(throttled_s * 1e6)}\n"
    )


def test_report_states_region_cpu_and_policy_requests_even_when_every_run_is_withdrawn(tmp_path) -> None:
    scn = _policy_scn()
    topo = make_topology(scn)
    run = write_run(tmp_path / "a", scn, topo, cpu_busy=0.99)  # withdrawn under V6
    lab = run / "lab"
    lab.mkdir()
    (lab / "cah-inside.cpu.start").write_text(_stat(100, 10, 1000, 0, 0))
    (lab / "cah-inside.cpu.end").write_text(_stat(300, 110, 3000, 500, 40))
    (run / "policies.csv").write_text(
        "phase,policy,action,planned_ms,sent_ms,done_ms,status\n"
        "cut,cut-edge-inside,create,1000,1004,1031,201\n"
        "healed,cut-edge-inside,delete,2000,2002,2010,200\n"
    )
    text = write_report([run], tmp_path / "out").read_text(encoding="utf-8")
    assert "no results" in text
    assert "| synthetic | cah-inside | 200 | 0.5 | 25.0% | 40.0 |" in text
    assert "| synthetic | cut | cut-edge-inside | create | 4 | 27 | 201 |" in text
    assert "Borders shut by: Kubernetes NetworkPolicy" in text


def test_a_policy_cut_reports_leaks_as_a_result_not_a_fault(tmp_path) -> None:
    scn = _policy_scn()
    topo = make_topology(scn)
    leaky = write_run(tmp_path / "a", scn, topo, respect_borders=False)
    write_report([leaky], tmp_path / "out")
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    v4 = next(v for v in results[0]["verdicts"] if v["rule"] == "V4")
    assert v4["passed"] and v4["detail"].startswith("measured, not judged") and "received" in v4["detail"]


def test_a_policy_cut_probes_fresh_connections_from_the_first_pod_of_each_region(tmp_path) -> None:
    scn = _policy_scn()
    opt = RenderOptions(namespace="cah", run_id="r1", seed=7, controller_image="cah:test")
    sets = {d["metadata"]["name"]: d for d in render(scn, opt, "") if d["kind"] == "StatefulSet"}
    env = {r: sets[r]["spec"]["template"]["spec"]["containers"][1]["env"] for r in ("inside", "outside")}
    assert {"name": "CAH_PROBE", "value": "bootstrap:5000"} in env["inside"]
    assert {"name": "CAH_PROBE", "value": "inside-0.nodes:5000"} in env["outside"]
    plain = {
        d["metadata"]["name"]: d for d in render(Scenario.model_validate(WHOLE), opt, "") if d["kind"] == "StatefulSet"
    }
    assert "CAH_PROBE" not in str(plain)

    topo = make_topology(scn)
    run = write_run(tmp_path / "a", scn, topo)
    record = json.loads((run / "run.json").read_text())
    cut = next(p for p in record["phases"] if p["name"] == "cut")
    lines = []
    for k in range(6):
        at = cut["start_ms"] + k * 10_000
        rc, err = ("124", "") if k % 2 else ("1", "connect:_Connection_refused")
        lines.append(f"2026-01-01T00:00:00Z shaper probe target=bootstrap:5000 at_ms={at} rc={rc} err={err}")
    import gzip as gz

    (run / "logs" / "inside-0.shaper.log.gz").write_bytes(gz.compress(("\n".join(lines) + "\n").encode()))
    (run / "lab").mkdir()
    (run / "lab" / "host.txt").write_text("4 CPUs,\nAMD EPYC 7763\n, kernel 7.0.0\n")
    text = write_report([run], tmp_path / "out").read_text(encoding="utf-8")
    # Probes at 0 and 10 s fall in the first 20 s and are left out.
    assert "| synthetic | inside-0 | cut | bootstrap:5000 | 4 | 0 | 2 | 2 |" in text
    assert "Runner of `synthetic`: 4 CPUs, AMD EPYC 7763 , kernel 7.0.0." in text
