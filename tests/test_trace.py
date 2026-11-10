from __future__ import annotations

import math

import pytest

from cutandheal.trace import DAY, segment, to_availability

STEP = 1800
SLOTS = DAY // STEP


def _diurnal(day_levels: list[float]) -> list[float]:
    """Traffic with a daily cycle, scaled per day: what an outage signal really looks like."""
    out = []
    for level in day_levels:
        for slot in range(SLOTS):
            out.append(level * (1000 + 600 * math.sin(2 * math.pi * slot / SLOTS)))
    return out


def test_the_daily_cycle_is_not_mistaken_for_an_outage() -> None:
    samples = to_availability(0, STEP, _diurnal([1, 1, 1, 1]), baseline_days=2)
    assert all(s.availability == pytest.approx(1.0) for s in samples)
    assert [s.level for s in segment(samples, levels=(0, 0.5, 1))] == [1]


def test_a_shutdown_and_staged_restoration_segment_into_levels() -> None:
    values = _diurnal([1, 1, 0.018, 0.018, 0.022, 0.6, 1])
    samples = to_availability(0, STEP, values, baseline_days=2)
    segs = segment(samples, levels=(0.0, 0.02, 0.1, 0.5, 1.0))
    assert [s.level for s in segs] == [1.0, 0.02, 0.5, 1.0]
    assert [s.hours for s in segs] == [48.0, 72.0, 24.0, 24.0]
    assert segs[1].median_availability == pytest.approx(0.018, abs=0.001)


def test_short_dips_are_absorbed() -> None:
    values = _diurnal([1, 1, 1])
    for i in range(2 * SLOTS + 4, 2 * SLOTS + 8):  # a two-hour dip
        values[i] = 0
    samples = to_availability(0, STEP, values, baseline_days=2)
    assert [s.level for s in segment(samples, levels=(0, 1), min_hours=6)] == [1]
    assert [s.level for s in segment(samples, levels=(0, 1), min_hours=1)] == [1, 0, 1]


def test_gaps_in_the_signal_are_skipped_not_read_as_zero() -> None:
    values: list[float | None] = _diurnal([1, 1, 1])
    values[2 * SLOTS + 3] = None
    samples = to_availability(0, STEP, values, baseline_days=2)
    assert len(samples) == 3 * SLOTS - 1
    assert min(s.availability for s in samples) == pytest.approx(1.0)


def test_a_baseline_that_misses_a_time_of_day_is_refused() -> None:
    values: list[float | None] = _diurnal([1, 1])
    values[5] = values[5 + SLOTS] = None
    with pytest.raises(ValueError, match="time-of-day"):
        to_availability(0, STEP, values, baseline_days=2)
