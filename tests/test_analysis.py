from __future__ import annotations

import pytest

from cutandheal.analyze import Params, cells, summarise, transitions
from cutandheal.evidence import load_run, parse_node_log
from cutandheal.validity import judge

from .synth import write_run

P = Params(deadline_s=10, guard_s=20)


def _cell(cs, phase, src, dst, window="steady"):
    return next(c for c in cs if (c.phase, c.src, c.dst, c.window) == (phase, src, dst, window))


def _verdicts(run):
    return {v.rule: v for v in judge(run, cells(run, P))}


def test_real_node_log_lines_parse() -> None:
    # Lines copied from albertodst/regression-node-amd64:v2.4.0.
    text = (
        "INF 2026-11-10 19:14:01.485+00:00 Host info                                  tid=1 hostname=inside-0 peer=0 muxer=yamux\n"
        "INF 2026-11-10 18:46:18.258+00:00 Sent message                               tid=1 msgId=5871328469820093183 timestamp=1794336378259416320\n"
        "INF 2026-11-10 18:47:53.935+00:00 Received message                           tid=1 msgId=7040115899689817385 sentAt=1794336473935658752 current=1794336473936122880 delayMs=0\n"
    )
    sent, recv, started = parse_node_log(text)
    assert sent == [(5871328469820093183, 1794336378259416320)]
    assert recv == [(7040115899689817385, 1794336473935658752, 1794336473936122880)]
    assert started


def test_a_clean_run_is_valid_and_its_numbers_are_exact(tmp_path, scn, topo) -> None:
    run = load_run(write_run(tmp_path / "r", scn, topo))
    cs = cells(run, P)
    assert all(v.passed for v in judge(run, cs)), [v for v in judge(run, cs) if not v.passed]

    base = _cell(cs, "baseline", "inside", "outside")
    assert base.ratio == 1.0 and base.p50_ms == 120.0 and base.path_exists
    # Steady window of a 60 s phase at 1 msg/s, alternating two origin regions:
    # sends at 20..50 s inclusive, 31 messages, 15 or 16 from each region.
    assert base.messages in (15, 16)
    assert base.pairs == base.messages * 6

    cut = _cell(cs, "cut", "inside", "outside")
    assert not cut.path_exists and cut.delivered == 0 and cut.ratio == 0.0
    inside = _cell(cs, "cut", "inside", "inside")
    assert inside.ratio == 1.0 and inside.pairs == inside.messages * 3  # the origin is never its own receiver


def test_late_deliveries_are_counted_apart_from_delivered(tmp_path, scn, topo) -> None:
    def slow(phase, _origin, receiver, _t):
        return 15_000.0 if phase == "healed" and receiver == "outside-0" else 100.0

    run = load_run(write_run(tmp_path / "r", scn, topo, slow))
    cell = _cell(cells(run, P), "healed", "inside", "outside")
    assert cell.late == cell.messages
    assert cell.ratio == pytest.approx(5 / 6)


def test_settle_time_is_the_last_message_below_the_steady_level(tmp_path, scn, topo) -> None:
    def slow_heal(phase, origin, receiver, t):
        crossing = origin.split("-")[0] != receiver.split("-")[0]
        return None if phase == "healed" and crossing and t < 14 else 100.0

    run = load_run(write_run(tmp_path / "r", scn, topo, slow_heal))
    cs = cells(run, P)
    tr = next(t for t in transitions(run, cs, P) if (t.phase, t.src, t.dst) == ("healed", "outside", "inside"))
    assert tr.steady_ratio == 1.0
    assert 12 <= tr.settle_s < 14 and tr.first_full_s >= 14
    assert tr.messages_below == 7  # every other second for 14 s
    same = next(t for t in transitions(run, cs, P) if (t.phase, t.src, t.dst) == ("healed", "inside", "inside"))
    assert same.settle_s == 0.0 and same.messages_below == 0


def test_the_confidence_interval_resamples_messages_not_pairs(tmp_path, scn, topo) -> None:
    # Half the messages reach everyone, half reach no one across the border. Pairs within a
    # message are perfectly correlated, so the interval must be wide; treating the pairs as
    # independent would report a tight one.
    def all_or_nothing(phase, origin, receiver, t):
        crossing = origin.split("-")[0] != receiver.split("-")[0]
        return None if phase == "half" and crossing and int(t) % 4 < 2 else 100.0

    run = load_run(write_run(tmp_path / "r", scn, topo, all_or_nothing))
    cell = _cell(cells(run, P), "half", "inside", "outside")
    assert 0.3 < cell.ratio < 0.7
    assert cell.ci_high - cell.ci_low > 0.3


def test_v4_catches_a_partition_that_leaks(tmp_path, scn, topo) -> None:
    run = load_run(write_run(tmp_path / "r", scn, topo, respect_borders=False))
    v = _verdicts(run)
    assert not v["V4"].passed and "cut inside->outside" in v["V4"].detail
    assert v["V3"].passed


def test_v4_accepts_messages_that_arrive_after_the_border_reopens(tmp_path, scn, topo) -> None:
    # Seen in the first end-to-end run: a 60 s cut does not kill TCP connections. Messages
    # published during it sit in send buffers and are delivered when the border reopens.
    # They are late, they are not delivered on time, and they are not a leak.
    def buffered(phase, origin, receiver, t):
        crossing = origin.split("-")[0] != receiver.split("-")[0]
        return (60 - t) * 1000 + 800 if phase == "cut" and crossing else 100.0

    run = load_run(write_run(tmp_path / "r", scn, topo, buffered, respect_borders=False))
    cs = cells(run, P)
    assert _verdicts(run)["V4"].passed
    cut = _cell(cs, "cut", "inside", "outside")
    assert cut.delivered == 0 and cut.late == cut.pairs


def test_v3_catches_an_unhealthy_baseline(tmp_path, scn, topo) -> None:
    def flaky(phase, _origin, receiver, _t):
        return None if phase == "baseline" and receiver == "outside-1" else 100.0

    assert not _verdicts(load_run(write_run(tmp_path / "r", scn, topo, flaky)))["V3"].passed


def test_v2_catches_a_late_shaper(tmp_path, scn, topo) -> None:
    v = _verdicts(load_run(write_run(tmp_path / "r", scn, topo, shaper_late_ms=900)))["V2"]
    assert not v.passed and "off schedule" in v.detail


def test_v6_catches_a_saturated_host(tmp_path, scn, topo) -> None:
    assert not _verdicts(load_run(write_run(tmp_path / "r", scn, topo, cpu_busy=0.97)))["V6"].passed


def test_v1_catches_a_restarted_pod(tmp_path, scn, topo) -> None:
    v = _verdicts(load_run(write_run(tmp_path / "r", scn, topo, restarts={"inside-2": 1})))["V1"]
    assert not v.passed and "1 restarted" in v.detail


def test_v5_catches_a_publisher_that_fell_behind(tmp_path, scn, topo) -> None:
    path = write_run(tmp_path / "r", scn, topo)
    lines = (path / "publishes.csv").read_text().splitlines()
    header = lines[0].split(",")
    sent = header.index("sent_ms")
    for i in range(1, len(lines), 20):  # every 20th publish goes out 400 ms late
        cols = lines[i].split(",")
        cols[sent] = str(int(cols[sent]) + 400)
        lines[i] = ",".join(cols)
    (path / "publishes.csv").write_text("\n".join(lines) + "\n")
    v = _verdicts(load_run(path))["V5"]
    assert not v.passed and "lateness p99" in v.detail


def test_v7_catches_logs_that_disagree_with_the_publisher(tmp_path, scn, topo) -> None:
    v = _verdicts(load_run(write_run(tmp_path / "r", scn, topo, drop_sent_line="inside-1")))["V7"]
    assert not v.passed and "disagree" in v.detail


def test_v7_catches_a_missing_log(tmp_path, scn, topo) -> None:
    path = write_run(tmp_path / "r", scn, topo)
    (path / "logs" / "outside-2.node.log.gz").unlink()
    v = _verdicts(load_run(path))["V7"]
    assert not v.passed and "missing" in v.detail


def test_summary_is_serialisable_and_names_every_phase(tmp_path, scn, topo) -> None:
    import json

    summary = summarise(load_run(write_run(tmp_path / "r", scn, topo)), P)
    json.dumps(summary)
    assert [p["name"] for p in summary["phases"]] == ["baseline", "cut", "bridge", "half", "healed"]
    assert [b["open_nodes"] for b in summary["borders"]] == [4, 0, 1, 2, 4]
