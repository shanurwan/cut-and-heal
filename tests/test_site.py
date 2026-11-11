from __future__ import annotations

import json

from cutandheal.site import write_site_data

from .synth import write_run


def test_site_data_draws_valid_runs_and_only_lists_withdrawn_ones(tmp_path, scn, topo) -> None:
    good = write_run(tmp_path / "a", scn, topo)
    leaky = write_run(tmp_path / "b", scn, topo, respect_borders=False)
    out = write_site_data([good, leaky], tmp_path / "site" / "data.json", "https://example.invalid/run")
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["name"] == scn.name
    assert [p["name"] for p in data["pods"]] == sorted(
        (p.name for p in topo.pods), key=lambda n: (n.split("-")[0], int(n.split("-")[1]))
    )
    assert [ph["name"] for ph in data["phases"]] == [ph.name for ph in scn.timeline]
    assert data["phases"][0]["start_s"] == 0

    drawn, withdrawn = data["runs"]
    assert drawn["valid"] and not withdrawn["valid"]
    assert [f["rule"] for f in withdrawn["failed"]] == ["V4"]
    assert "messages" not in withdrawn, "a withdrawn run contributes nothing to draw"

    msgs = drawn["messages"]
    n = len(msgs["t_s"])
    assert n > 0 and all(len(msgs[k][r]) == n for k in ("delivered", "of", "p50_ms") for r in data["regions"])
    assert all(0 <= i < len(data["pods"]) for i in msgs["origin"])
    for region in data["regions"]:
        assert all(d <= of for d, of in zip(msgs["delivered"][region], msgs["of"][region], strict=True))

    # While the border has no open node, nothing published on one side is delivered on the other.
    border_id, border = next(iter(data["borders"].items()))
    shut = [ph for ph in data["phases"] if ph["open_nodes"][border_id] == 0]
    assert shut
    gated = border["gated"]
    other = next(r for r in border["between"] if r != gated)
    for t, origin, crossed in zip(msgs["t_s"], msgs["origin"], msgs["delivered"][other], strict=True):
        if data["pods"][origin]["region"] == gated and any(ph["start_s"] + 1 < t < ph["end_s"] - 11 for ph in shut):
            assert crossed == 0
    assert all(len(drawn["open"][ph["name"]]) == ph["open_nodes"][border_id] for ph in data["phases"])
