"""Turn a public outage signal into the availability levels a scenario is built from.

Source: IODA (Internet Outage Detection and Analysis, Georgia Tech), https://ioda.live.
IODA's data is copyrighted and not redistributed here. This module fetches it on demand;
scenarios in this repository carry only the handful of levels derived from it, with the
query that reproduces them.

What the signal is, and is not. `gtr-norm` is traffic from a country to Google services,
normalised. Google is outside the country, so the signal tracks how much traffic crossed the
border. It is a measure of traffic, not of how many networks stayed connected; reading it as
"the fraction of nodes that still have a border link" is a modelling choice, stated in
docs/METHOD.md and varied in the sensitivity runs.
"""

from __future__ import annotations

import json
import statistics
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

IODA_API = "https://api.ioda.inetintel.cc.gatech.edu/v2/signals/raw/country"
DAY = 86400


@dataclass(frozen=True)
class Sample:
    t: int  # epoch seconds, UTC
    availability: float  # 0..1, relative to the same time of day before the event


@dataclass(frozen=True)
class Segment:
    start_utc: str
    end_utc: str
    hours: float
    level: float
    median_availability: float


def _epoch(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp())


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%MZ")


def to_availability(t0: int, step: int, values: list[float | None], baseline_days: int) -> list[Sample]:
    """Divide each sample by the median of the same time-of-day slot in the baseline days.

    Traffic has a strong daily cycle; without this, every night looks like a small outage.
    """
    slots_per_day = DAY // step
    baseline: dict[int, list[float]] = {}
    for i, v in enumerate(values[: baseline_days * slots_per_day]):
        if v is not None:
            baseline.setdefault(i % slots_per_day, []).append(v)
    if len(baseline) < slots_per_day:
        raise ValueError("baseline days do not cover every time-of-day slot")
    ref = {slot: statistics.median(vs) for slot, vs in baseline.items()}
    out = []
    for i, v in enumerate(values):
        if v is None or ref[i % slots_per_day] <= 0:
            continue
        out.append(Sample(t0 + i * step, max(0.0, min(1.0, v / ref[i % slots_per_day]))))
    return out


def segment(samples: list[Sample], levels: tuple[float, ...], min_hours: float = 6.0) -> list[Segment]:
    """Piecewise-constant approximation: snap each sample to the nearest level, then absorb
    runs shorter than `min_hours` into the run before them. Short dips are noise at the
    resolution a compressed replay can represent."""
    if not samples:
        return []
    runs: list[list[Sample]] = []
    run_levels: list[float] = []
    for s in samples:
        level = min(levels, key=lambda lv: abs(lv - s.availability))
        if run_levels and run_levels[-1] == level:
            runs[-1].append(s)
        else:
            runs.append([s])
            run_levels.append(level)
    step = samples[1].t - samples[0].t if len(samples) > 1 else 0
    merged: list[list[Sample]] = []
    merged_levels: list[float] = []
    for run, level in zip(runs, run_levels, strict=True):
        short = len(run) * step < min_hours * 3600
        if merged and (short or merged_levels[-1] == level):
            merged[-1] += run
        else:
            merged.append(list(run))
            merged_levels.append(level)
    out = []
    for run in merged:
        med = statistics.median(s.availability for s in run)
        out.append(
            Segment(
                start_utc=_iso(run[0].t),
                end_utc=_iso(run[-1].t + step),
                hours=round(len(run) * step / 3600, 1),
                level=min(levels, key=lambda lv: abs(lv - med)),
                median_availability=round(med, 4),
            )
        )
    return out


def fetch_ioda(country: str, start: str, end: str, baseline_days: int, datasource: str = "gtr-norm") -> list[Sample]:
    """Fetch one country's signal. The first `baseline_days` of the window must predate the event."""
    url = f"{IODA_API}/{country}?from={_epoch(start)}&until={_epoch(end)}&datasource={datasource}"
    req = urllib.request.Request(url, headers={"User-Agent": "cut-and-heal"})  # noqa: S310 - fixed https host
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        body = json.load(resp)
    for group in body.get("data") or []:
        for series in group:
            if series.get("datasource") == datasource:
                return to_availability(series["from"], series["step"], series["values"], baseline_days)
    raise LookupError(f"IODA returned no {datasource} series for {country} in {start}..{end}")
