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
