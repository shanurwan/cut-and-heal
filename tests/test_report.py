from __future__ import annotations

import json

from cutandheal.evidence import load_run
from cutandheal.report import held_messages, write_report

from .synth import write_run


def test_report_uses_valid_runs_and_withdraws_the_rest(tmp_path, scn, topo) -> None:
    good = write_run(tmp_path / "a", scn, topo)
    also_good = write_run(tmp_path / "b", scn, topo)
    leaky = write_run(tmp_path / "c", scn, topo, respect_borders=False)
    report = write_report([good, also_good, leaky], tmp_path / "out")
    text = report.read_text(encoding="utf-8")
    assert "| V4 No message was received across a border while it had no open node | pass | pass | **FAIL** |" in text
    assert "is withdrawn and contributes no numbers" in text
    assert "mean of 2 valid run(s)" in text
    assert "| cut | 0/4 open | 100.00% | 0.00% *(no path)* | 0.00% *(no path)* | 100.00% |" in text
    assert (tmp_path / "out" / "delivery.png").stat().st_size > 10_000
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    assert [r["valid"] for r in results] == [True, True, False]


def test_a_report_with_no_valid_run_has_no_results(tmp_path, scn, topo) -> None:
    text = write_report([write_run(tmp_path / "a", scn, topo, cpu_busy=0.99)], tmp_path / "out").read_text()
    assert "this report has no results" in text
    assert "## Delivery" not in text


def test_report_states_the_tcp_settings_the_pods_recorded(tmp_path, scn, topo) -> None:
    before = write_report([write_run(tmp_path / "a", scn, topo)], tmp_path / "o1").read_text(encoding="utf-8")
    assert "Kernel TCP settings" not in before

    run = write_run(tmp_path / "b", scn, topo, tcp_retries2="15")
    text = write_report([run], tmp_path / "o2").read_text(encoding="utf-8")
    pods = len(topo.pods)
    assert f"| tcp_retries2 | 15 ({pods} pods) |" in text
    results = json.loads((tmp_path / "o2" / "results.json").read_text())
    assert results[0]["kernel"] == {"tcp_retries2": {"15": pods}}


def _vm(series: list[tuple[dict, list[tuple[int, float]]]]) -> str:
    return json.dumps(
        {"data": {"result": [{"metric": m, "values": [[t / 1000, str(v)] for t, v in pts]} for m, pts in series]}}
    )


def test_report_relates_the_mesh_fall_to_node_age_and_stream_timeouts(tmp_path, scn, topo) -> None:
    run = write_run(tmp_path / "a", scn, topo)
    record = json.loads((run / "run.json").read_text())
    cut = next(p for p in record["phases"] if p["name"] == "cut")
    t0, end, fall = record["t0_ms"], record["end_ms"], cut["start_ms"] + 40_000
    ticks = range(t0, end, 5000)
    inside = [p.name for p in topo.pods if p.region == "inside"]
    # Every node log written by write_run starts at 2026-01-01T00:00:00Z.
    started = 1_767_225_600_000

    def size(t: int) -> float:
        return 6.0 if t < fall else 4.0

    (run / "metrics").mkdir()
    (run / "metrics" / "mesh_by_pod.json").write_text(
        _vm([({"pod": pod, "region": "inside"}, [(t, size(t)) for t in ticks]) for pod in inside])
    )
    (run / "metrics" / "mesh_mean_by_region.json").write_text(
        _vm([({"region": "inside"}, [(t, size(t)) for t in ticks])])
    )
    (run / "metrics" / "stream_timeouts_by_region.json").write_text(
        _vm(
            [
                ({"region": "inside", "type": "YamuxStream"}, [(t, 3.0 if t < fall - 5000 else 23.0) for t in ticks]),
                ({"region": "inside", "type": "SecureConn"}, [(t, 500.0 + t % 7) for t in ticks]),
            ]
        )
    )

    text = write_report([run], tmp_path / "out").read_text(encoding="utf-8")
    age_at_cut = (cut["start_ms"] - started) // 1000
    assert f"| {record['run_id']} | cut | inside | {len(inside)} | 40 | {age_at_cut} | {age_at_cut + 40} |" in text
    assert f"| {record['run_id']} | cut | inside | 40 | 20 | 0 |" in text
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    assert results[0]["mesh_drop_ages"][0]["node_age_s"] == age_at_cut + 40
    assert results[0]["stream_timeouts"] == [
        {"phase": "cut", "region": "inside", "reacted_after_s": 40, "around": 20, "earlier_in_phase": 0}
    ]


def test_report_without_node_start_times_or_the_counter_has_neither_section(tmp_path, scn, topo) -> None:
    text = write_report([write_run(tmp_path / "a", scn, topo)], tmp_path / "out").read_text(encoding="utf-8")
    assert "Mesh reaction against node age" not in text
    assert "Stream idle timeouts" not in text


def test_report_finds_the_bursts_of_idle_timeouts(tmp_path, scn, topo) -> None:
    run = write_run(tmp_path / "a", scn, topo)
    record = json.loads((run / "run.json").read_text())
    cut = next(p for p in record["phases"] if p["name"] == "cut")
    start = cut["start_ms"]
    ticks = range(record["t0_ms"], record["end_ms"], 5000)

    def count(t: int) -> float:
        # 150 at 10 s, 250 more at 15 s, then nothing; 40 in the next phase, too few to be a burst.
        after = (t - start) / 1000
        return 7.0 + (150 if after >= 10 else 0) + (250 if after >= 15 else 0) + (40 if after >= 80 else 0)

    (run / "metrics").mkdir()
    (run / "metrics" / "stream_timeouts_by_region.json").write_text(
        _vm([({"region": "inside", "type": "YamuxStream"}, [(t, count(t)) for t in ticks])])
    )
    text = write_report([run], tmp_path / "out").read_text(encoding="utf-8")
    assert f"| {record['run_id']} | cut | inside | 10 | 15 | 15 | 400 |" in text
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    assert results[0]["timeout_bursts"] == [
        {"phase": "cut", "region": "inside", "from_s": 10, "to_s": 15, "peak_s": 15, "timeouts": 400}
    ]


def test_report_follows_messages_held_through_a_shutdown(tmp_path, scn, topo) -> None:
    # In the cut phase (60 s), messages from inside cross 30 s after the border reopens and
    # messages from outside never do; everything else is delivered at once.
    def held(phase: str, origin: str, receiver: str, t: float) -> float | None:
        crossing = origin.split("-")[0] != receiver.split("-")[0]
        if phase != "cut" or not crossing:
            return 120.0
        return (60 - t + 30) * 1000 if origin.startswith("inside") else None

    run = write_run(tmp_path / "a", scn, topo, held, respect_borders=False)
    text = write_report([run], tmp_path / "out").read_text(encoding="utf-8")
    assert "is withdrawn" not in text
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    rows = {(r["src"], r["dst"]): r for r in results[0]["held_messages"]}
    assert set(rows) == {("inside", "outside"), ("outside", "inside")}
    out = rows[("inside", "outside")]
    assert out["phase"] == "cut" and out["closed_s"] == 60 and out["ratio"] == 1.0
    assert out["first_s"] == out["last_s"] == 30.0
    assert rows[("outside", "inside")]["ratio"] == 0.0 and rows[("outside", "inside")]["last_s"] is None
    assert out["during"] == 0
    assert "| cut | inside | outside | 60 |" in text and "| 0.00% | 100.00% | 30 | 30 | 30 |" in text


def test_report_separates_messages_that_crossed_during_the_cut(tmp_path, scn, topo) -> None:
    # A cut that leaves existing connections alone: everything crosses at once, cut or not.
    rows = held_messages(load_run(write_run(tmp_path / "a", scn, topo, lambda *_: 120.0, respect_borders=False)))
    assert rows
    for row in rows:
        assert row["ratio"] == 0.0 and row["first_s"] is None
        assert row["during_ratio"] == 1.0
