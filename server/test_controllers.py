"""Tests for the controller parser — pure Python, no PeePyPoo.

Run with:  server/.venv/bin/python server/test_controllers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.controllers import parse_controllers  # noqa: E402


def rule(**kw):
    return {"when": "S_O", "op": ">", "value": 2.0, "set": 100, **kw}


def test_legacy_controller_is_a_kla_controller():
    parsed = parse_controllers({"controller": {"period_days": 0.1, "rules": [rule()]}})
    assert [pc.target for pc in parsed] == ["kLa"]
    assert parsed[0].rules[0].at == ""       # measures in its own tank
    assert not parsed[0].hold


def test_list_with_other_targets_and_remote_tanks():
    data = {"controllers": [
        {"target": "Q_was", "period_days": 0.2,
         "rules": [rule(when="MLSS", value=4000, set=120, at="tank-1"),
                   rule(when="MLSS", op="<", value=3000, set=40, at="tank-1")]},
        {"target": "Qr", "rules": [rule(when="t", op="<", value=5, set=1500)]},
    ]}
    parsed = parse_controllers(data)
    assert [pc.target for pc in parsed] == ["Q_was", "Qr"]
    was_rules = parsed[0].rules
    assert was_rules[0].at == "tank-1" and was_rules[0].when == "MLSS"
    assert parsed[1].period == 0.1           # default period


def test_cod_n_is_measurable():
    parsed = parse_controllers({"controllers": [
        {"target": "kLa", "rules": [rule(when="COD/N", value=8)]}]})
    assert parsed[0].rules[0].when == "COD/N"


def test_ph_switch_with_hysteresis_on_an_influent():
    """The pH-fed reactor: feed on below 6.20, off above 6.25, unchanged in between."""
    parsed = parse_controllers({"controllers": [{
        "target": "Q", "period_days": 1 / 720, "otherwise": "hold",
        "rules": [rule(at="cstr", when="pH", op="<", value=6.20, set=0.2),
                  rule(at="cstr", when="pH", op=">", value=6.25, set=0)]}]})
    pc = parsed[0]
    assert pc.target == "Q" and pc.hold and abs(pc.period - 1 / 720) < 1e-12
    assert [r.when for r in pc.rules] == ["pH", "pH"]


def test_ph_estimate_inverts():
    from server.controllers import alkalinity_for_ph, ph_from_alkalinity, pk1
    assert abs(pk1(20.0) - 6.381) < 0.002
    alk = alkalinity_for_ph(6.2, 1.0)
    assert abs(alk - 0.659) < 0.005
    assert abs(ph_from_alkalinity(alk, 1.0) - 6.2) < 1e-9


def test_two_controllers_on_one_target_are_refused():
    data = {"controllers": [{"target": "kLa", "rules": [rule()]}],
            "controller": {"rules": [rule()]}}
    try:
        parse_controllers(data)
    except ValueError as e:
        assert "two controllers" in str(e)
    else:
        raise AssertionError("expected a ValueError")


def test_unknown_target_and_measure_are_refused():
    for bad in ({"target": "pH", "rules": [rule()]},
                {"target": "kLa", "rules": [rule(when="conductivity")]},
                {"target": "Q_was", "rules": [rule(set=-1)]},
                {"target": "Q", "otherwise": "maybe", "rules": [rule()]},
                {"target": "Q", "period_days": -1, "rules": [rule()]}):
        try:
            parse_controllers({"controllers": [bad]})
        except ValueError:
            continue
        raise AssertionError(f"expected a ValueError for {bad}")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:
            failures += 1
            print(f"FAIL {name}: {e!r}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
