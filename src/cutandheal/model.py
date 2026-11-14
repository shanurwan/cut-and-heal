"""Scenario schema: regions, the borders between them, and a timeline of border states.

A scenario is a statement about the network, not about Kubernetes. It says which regions
exist, what the links inside and between them look like when healthy, and how each border
changes over time. `plan.py` turns it into per-pod `tc` commands once pod addresses are known.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Phases shorter than this cannot be told apart from protocol timers: the gossipsub heartbeat
# is 1 s, and a mesh needs several heartbeats to react to anything.
MIN_PHASE_S = 30

Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,30}$")]

# The only kernel settings a scenario may change, and only inside a node's own network
# namespace. `cluster/up.sh` allows the same pattern and nothing wider.
SYSCTL = re.compile(r"^net\.ipv4\.tcp_[a-z0-9_]+$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LinkProfile(_Model):
    """One direction of a link, as netem sees it. Applied on egress at both ends."""

    delay_ms: float = Field(default=0, ge=0)
    jitter_ms: float = Field(default=0, ge=0)
    loss_pct: float = Field(default=0, ge=0, le=100)
    rate_mbit: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _jitter_needs_delay(self) -> LinkProfile:
        if self.jitter_ms > self.delay_ms:
            raise ValueError(
                f"jitter {self.jitter_ms} ms exceeds delay {self.delay_ms} ms; netem would "
                "reorder packets, which is a different experiment"
            )
        return self

    def netem_args(self) -> list[str]:
        """Arguments after `netem`. Always explicit, so `qdisc change` resets every field."""
        args = ["delay", f"{self.delay_ms:g}ms", f"{self.jitter_ms:g}ms", "loss", f"{self.loss_pct:g}%"]
        if self.rate_mbit is not None:
            args += ["rate", f"{self.rate_mbit:g}mbit"]
        return args


BLOCKED = LinkProfile(loss_pct=100)


class Region(_Model):
    nodes: int = Field(ge=1)
    domestic: LinkProfile = LinkProfile()
    description: str = ""


class Border(_Model):
    """A border between two regions. `gated` is the side whose nodes lose the border."""

    between: tuple[Name, Name]
    gated: Name
    healthy: LinkProfile

    @model_validator(mode="after")
    def _check(self) -> Border:
        if self.between[0] == self.between[1]:
            raise ValueError("a border needs two different regions")
        if self.gated not in self.between:
            raise ValueError(f"gated region {self.gated!r} is not one of {self.between}")
        return self

    def other(self, region: str) -> str:
        a, b = self.between
        return b if region == a else a


class BorderState(_Model):
    """What a border looks like during one phase.

    `open_nodes` is how many nodes of the gated region still have the border. Real shutdowns
    are rarely total: some networks stay connected. Nodes are opened in a fixed seeded order,
    so the nodes open at 2 are a subset of those open at 5.
    """

    open_nodes: int | None = Field(default=None, ge=0)
    open_fraction: float | None = Field(default=None, ge=0, le=1)
    link: LinkProfile | None = None

    @model_validator(mode="after")
    def _one_way_to_say_it(self) -> BorderState:
        if self.open_nodes is not None and self.open_fraction is not None:
            raise ValueError("give open_nodes or open_fraction, not both")
        return self

    def resolve_open(self, gated_nodes: int) -> int:
        if self.open_nodes is not None:
            if self.open_nodes > gated_nodes:
                raise ValueError(f"open_nodes {self.open_nodes} exceeds the region's {gated_nodes}")
            return self.open_nodes
        if self.open_fraction is not None:
            return round(self.open_fraction * gated_nodes)
        return gated_nodes


class Phase(_Model):
    name: Name
    duration_s: int = Field(ge=MIN_PHASE_S)
    borders: dict[Name, BorderState] = {}
    note: str = ""


class Source(_Model):
    """Where the timeline comes from. Kept in the scenario so a report can cite it."""

    event: str
    dataset: str
    url: str
    window_utc: tuple[str, str]
    retrieved: str
    method: str


class Publish(_Model):
    rate_hz: float = Field(default=1.0, gt=0, le=50)
    size_bytes: int = Field(default=1000, ge=64, le=1_000_000)
    topic: str = "test"


class Scenario(_Model):
    name: Name
    title: str
    source: Source | None = None
    regions: dict[Name, Region]
    borders: dict[Name, Border]
    bootstrap_region: Name
    publish: Publish = Publish()
    sysctls: dict[str, str] = Field(default_factory=dict)
    """Kernel TCP settings for every gossipsub node, for experiments that ask which timer
    governs a behaviour. Empty means the kernel defaults, which is what every report
    before `long-cut` used."""
    timeline: tuple[Phase, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _check(self) -> Scenario:
        for bid, border in self.borders.items():
            for region in border.between:
                if region not in self.regions:
                    raise ValueError(f"border {bid!r} names unknown region {region!r}")
        if self.bootstrap_region not in self.regions:
            raise ValueError(f"bootstrap_region {self.bootstrap_region!r} is not a region")
        for key in self.sysctls:
            if not SYSCTL.match(key):
                raise ValueError(
                    f"sysctl {key!r} is not allowed: only net.ipv4.tcp_* can be set, and only "
                    "inside a node's own network namespace"
                )
        names = [p.name for p in self.timeline]
        if len(set(names)) != len(names):
            raise ValueError("phase names must be unique; analysis keys results by phase name")
        for phase in self.timeline:
            for bid, state in phase.borders.items():
                if bid not in self.borders:
                    raise ValueError(f"phase {phase.name!r} names unknown border {bid!r}")
                state.resolve_open(self.regions[self.borders[bid].gated].nodes)
        first = self.timeline[0]
        for bid, border in self.borders.items():
            gated = self.regions[border.gated].nodes
            if self.open_count(first, bid) != gated or self.link(first, bid) != border.healthy:
                raise ValueError(
                    f"the first phase must leave border {bid!r} fully open and healthy: it is "
                    "the baseline every later phase is compared against"
                )
        return self

    def open_count(self, phase: Phase, border_id: str) -> int:
        border = self.borders[border_id]
        state = phase.borders.get(border_id, BorderState())
        return state.resolve_open(self.regions[border.gated].nodes)

    def link(self, phase: Phase, border_id: str) -> LinkProfile:
        state = phase.borders.get(border_id)
        return state.link if state and state.link else self.borders[border_id].healthy

    @property
    def duration_s(self) -> int:
        return sum(p.duration_s for p in self.timeline)

    @property
    def total_nodes(self) -> int:
        return sum(r.nodes for r in self.regions.values())

    def phase_windows(self) -> list[tuple[str, int, int]]:
        """(name, start_s, end_s) relative to the start of the timeline."""
        out, t = [], 0
        for p in self.timeline:
            out.append((p.name, t, t + p.duration_s))
            t += p.duration_s
        return out


def load_scenario(path: str | Path) -> Scenario:
    return Scenario.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
