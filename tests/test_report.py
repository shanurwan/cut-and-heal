from __future__ import annotations

import json

from cutandheal.report import write_report

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
