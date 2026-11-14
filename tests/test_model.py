from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from cutandheal.model import BLOCKED, LinkProfile, Scenario, load_scenario

from .conftest import SCENARIO

SCENARIOS = sorted((Path(__file__).parent.parent / "scenarios").glob("*.yaml"))


def _with(**changes) -> dict:
    data = copy.deepcopy(SCENARIO)
    data.update(changes)
    return data


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_shipped_scenarios_load(path: Path) -> None:
    scn = load_scenario(path)
    assert scn.name == path.stem
    assert scn.duration_s == sum(p.duration_s for p in scn.timeline)


def test_netem_args_are_always_explicit() -> None:
    # `tc qdisc change` keeps unspecified fields, so a profile must spell out zeros:
    # reopening a border has to reset loss from 100% back to its healthy value.
    assert LinkProfile().netem_args() == ["delay", "0ms", "0ms", "loss", "0%"]
    assert BLOCKED.netem_args()[-2:] == ["loss", "100%"]
    assert LinkProfile(delay_ms=100, jitter_ms=20, loss_pct=0.5, rate_mbit=20).netem_args() == [
        "delay",
        "100ms",
        "20ms",
        "loss",
        "0.5%",
        "rate",
        "20mbit",
    ]


def test_jitter_larger_than_delay_is_refused() -> None:
    with pytest.raises(ValidationError, match="reorder"):
        LinkProfile(delay_ms=5, jitter_ms=10)


def test_first_phase_must_be_a_healthy_baseline() -> None:
    data = _with()
    data["timeline"][0]["borders"] = {"edge": {"open_nodes": 3}}
    with pytest.raises(ValidationError, match="baseline"):
        Scenario.model_validate(data)


def test_unknown_border_in_a_phase_is_refused() -> None:
    data = _with()
    data["timeline"][1]["borders"] = {"nowhere": {"open_nodes": 0}}
    with pytest.raises(ValidationError, match="unknown border"):
        Scenario.model_validate(data)


def test_open_nodes_cannot_exceed_the_region() -> None:
    data = _with()
    data["timeline"][1]["borders"] = {"edge": {"open_nodes": 5}}
    with pytest.raises(ValidationError, match="exceeds"):
        Scenario.model_validate(data)


def test_duplicate_phase_names_are_refused() -> None:
    data = _with()
    data["timeline"][2]["name"] = "cut"
    with pytest.raises(ValidationError, match="unique"):
        Scenario.model_validate(data)


def test_phases_shorter_than_protocol_timers_are_refused() -> None:
    data = _with()
    data["timeline"][1]["duration_s"] = 5
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_open_fraction_resolves_against_the_gated_region(scn: Scenario) -> None:
    by_name = {p.name: p for p in scn.timeline}
    assert scn.open_count(by_name["baseline"], "edge") == 4
    assert scn.open_count(by_name["cut"], "edge") == 0
    assert scn.open_count(by_name["half"], "edge") == 2
    assert scn.open_count(by_name["healed"], "edge") == 4


def test_typos_in_a_scenario_fail_loudly() -> None:
    data = _with()
    data["regions"]["inside"]["node"] = 4
    with pytest.raises(ValidationError, match="Extra inputs"):
        Scenario.model_validate(data)


def test_only_tcp_sysctls_can_be_set() -> None:
    data = _with()
    data["sysctls"] = {"net.ipv4.tcp_retries2": "5"}
    assert Scenario.model_validate(data).sysctls == {"net.ipv4.tcp_retries2": "5"}
    data["sysctls"] = {"kernel.shm_rmid_forced": "1"}
    with pytest.raises(ValidationError, match="not allowed"):
        Scenario.model_validate(data)
