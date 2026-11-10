from __future__ import annotations

import pytest

from cutandheal.model import Scenario
from cutandheal.plan import Pod, Topology

SCENARIO = {
    "name": "t",
    "title": "test",
    "regions": {
        "inside": {"nodes": 4, "domestic": {"delay_ms": 10, "jitter_ms": 2}},
        "outside": {"nodes": 6, "domestic": {"delay_ms": 20}},
    },
    "borders": {
        "edge": {"between": ["inside", "outside"], "gated": "inside", "healthy": {"delay_ms": 50, "loss_pct": 0.5}}
    },
    "bootstrap_region": "outside",
    "timeline": [
        {"name": "baseline", "duration_s": 60},
        {"name": "cut", "duration_s": 60, "borders": {"edge": {"open_nodes": 0}}},
        {"name": "bridge", "duration_s": 60, "borders": {"edge": {"open_nodes": 1}}},
        {"name": "half", "duration_s": 60, "borders": {"edge": {"open_fraction": 0.5}}},
        {"name": "healed", "duration_s": 60},
    ],
}


def make_topology(scn: Scenario) -> Topology:
    cidrs = {"inside": ("10.42.2.0/23",), "outside": ("10.42.4.0/23",)}
    base = {"inside": "10.42.2.", "outside": "10.42.4."}
    pods = []
    for region, spec in scn.regions.items():
        for i in range(spec.nodes):
            pods.append(Pod(f"{region}-{i}", region, f"{base[region]}{10 + i}", f"node-{region}"))
    return Topology(pods=tuple(pods), region_cidrs=cidrs)


@pytest.fixture
def scn() -> Scenario:
    return Scenario.model_validate(SCENARIO)


@pytest.fixture
def topo(scn: Scenario) -> Topology:
    return make_topology(scn)
