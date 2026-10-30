"""Tests for the graph resolution — pure Python, no PeePyPoo, so they run in a second.

Run with:  server/.venv/bin/python -m pytest server/test_topology.py -q
(or plain:  server/.venv/bin/python server/test_topology.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.topology import TopologyError, plan_streets, resolve  # noqa: E402


def unit(nid, unit_id, name="", **attrs):
    return {"id": nid, "type": "unit",
            "data": {"unitId": unit_id, "name": name,
                     "attributes": {k: str(v) for k, v in attrs.items()}}}


def pipe(src, dst, flow=None, stream=None, name=None):
    data = {}
    if flow is not None:
        data["flow"] = flow
    if stream:
        data["streamType"] = stream
    if name:
        data["name"] = name
    return {"source": src, "target": dst, "data": data}


def test_chain():
    nodes = [unit("i", "influent", "Feed", Q=1000),
             unit("a", "anoxic_CSTR", "Anoxic", V=500),
             unit("b", "aerated_CSTR", "Aerated", V=1000),
             unit("e", "effluent", "Effluent")]
    plan = resolve(nodes, [pipe("i", "a"), pipe("a", "b"), pipe("b", "e")])
    assert [r.model for r in plan.reactors] == ["r1", "r2"]
    assert [r.label for r in plan.reactors] == ["Anoxic", "Aerated"]
    assert plan.reactors[0].throughput == 1000
    assert plan.reactors[1].throughput == 1000
    assert [t.label for t in plan.terminals] == ["Aerated"]


def test_parallel_streets_merge():
    """One feed, split by the drawn pipe flows, two streets, one merge."""
    nodes = [unit("i", "influent", "Feed", Q=4000),
             unit("a", "aerated_CSTR", "A", V=1000),
             unit("b", "aerated_CSTR", "B", V=1000),
             unit("m", "aerated_CSTR", "Mix", V=500),
             unit("e", "effluent", "Effluent")]
    edges = [pipe("i", "a", 2500), pipe("i", "b", 1500),
             pipe("a", "m", 2500), pipe("b", "m", 1500), pipe("m", "e", 4000)]
    plan = resolve(nodes, edges)
    by = {r.label: r for r in plan.reactors}
    assert by["A"].throughput == 2500
    assert by["B"].throughput == 1500
    assert by["Mix"].throughput == 4000
    assert len([i for i in by["Mix"].inlets if i.kind == "reactor"]) == 2
    # "Mix" is downstream of both, so it must be built last.
    assert by["Mix"].index == 3


def test_split_from_a_reactor():
    nodes = [unit("i", "influent", "Feed", Q=3000),
             unit("h", "aerated_CSTR", "Head", V=1000),
             unit("a", "aerated_CSTR", "A", V=500),
             unit("b", "aerated_CSTR", "B", V=500),
             unit("e", "effluent", "Effluent")]
    edges = [pipe("i", "h", 3000), pipe("h", "a", 2000), pipe("h", "b", 1000),
             pipe("a", "e"), pipe("b", "e")]
    plan = resolve(nodes, edges)
    head = plan.by_id("h")
    assert sorted(round(o.flow) for o in head.outlets) == [1000, 2000]
    assert {r.label for r in plan.terminals} == {"A", "B"}


def test_passthrough_units_are_walked_across():
    """A screen and an equalisation basin route flow but carry no model."""
    nodes = [unit("i", "influent", "Feed", Q=1000),
             unit("s", "screen", "Screen", spacing=20),
             unit("q", "equalization_basin", "Basin", V=500),
             unit("a", "aerated_CSTR", "Aerated", V=1000),
             unit("e", "effluent", "Effluent")]
    edges = [pipe("i", "s"), pipe("s", "q"), pipe("q", "a"), pipe("a", "e")]
    plan = resolve(nodes, edges)
    assert len(plan.reactors) == 1
    assert plan.reactors[0].inlets[0].kind == "influent"
    assert plan.reactors[0].throughput == 1000


def test_recycle_lines_are_not_forward_flow():
    """A sludge line back to the head must not make the graph cyclic."""
    nodes = [unit("i", "influent", "Feed", Q=1000),
             unit("a", "anoxic_CSTR", "Anoxic", V=500),
             unit("b", "aerated_CSTR", "Aerated", V=1000),
             unit("c", "clarifier", "Clarifier", Qr=1000, Q_was=50),
             unit("e", "effluent", "Effluent")]
    edges = [pipe("i", "a"), pipe("a", "b"), pipe("b", "c"), pipe("c", "e"),
             pipe("c", "a", stream="sludge", name="RAS")]
    plan = resolve(nodes, edges)
    assert [r.label for r in plan.reactors] == ["Anoxic", "Aerated"]
    assert plan.clarifier is not None
    assert plan.clarifier_feed == "b"


def test_influent_flow_may_be_time_varying():
    """A sinusoid or a sampled profile still gives a number to size branches with."""
    nodes = [unit("i", "influent", "Feed", Q="2000+500*sin(2*pi*t/1)"),
             unit("j", "influent", "Pulse", Q="[100, 100, 900, 100]"),
             unit("a", "aerated_CSTR", "A", V=1000),
             unit("e", "effluent", "Effluent")]
    edges = [pipe("i", "a"), pipe("j", "a"), pipe("a", "e")]
    plan = resolve(nodes, edges)
    # sinusoid → its offset, sampled profile → its mean
    assert round(plan.reactors[0].throughput) == 2000 + 300


def test_sbr_cycle_and_bypass_are_read():
    nodes = [unit("i", "influent", "Feed", Q=1000),
             unit("f", "trickling_filter", "Filter", V=1000),
             unit("s", "sbr", "SBR", V=800, cycle=7.4, fill=1.5, react=3.5,
                  settle=0.75, decant=1.65, offset=1.85),
             unit("e", "effluent", "Effluent")]
    nodes[1]["data"]["bypass"] = {"when": "COD/N", "op": ">", "value": 3.0,
                                  "flow": 200, "base_flow": 10}
    plan = resolve(nodes, [pipe("i", "f"), pipe("f", "s"), pipe("s", "e")])
    sbr = plan.by_id("s")
    assert sbr.cycle is not None
    assert (sbr.cycle.cycle_h, sbr.cycle.react_h, sbr.cycle.offset_h) == (7.4, 3.5, 1.85)
    flt = plan.by_id("f")
    assert flt.bypass is not None and flt.bypass.flow == 200


def test_settler_is_a_plan_node():
    """A primary clarifier sits in the plan like a reactor, so a feed can split into it
    and a side stream can merge downstream of it — the Sumo plant's municipal overflow."""
    nodes = [unit("m", "influent", "Municipal", Q=7000),
             unit("i", "influent", "Industrial", Q=1500),
             unit("p", "primary_clarifier", "Primary", removal=0.88),
             unit("f", "trickling_filter", "Filter", V=3500),
             unit("z", "primary_clarifier", "Intermediate", removal=0.42),
             unit("e", "effluent", "Effluent")]
    edges = [pipe("m", "p", 3000), pipe("m", "z", 4000), pipe("i", "p"),
             pipe("p", "f"), pipe("f", "z"), pipe("z", "e")]
    plan = resolve(nodes, edges)
    assert [r.id for r in plan.reactors] == ["p", "f", "z"]
    assert round(plan.by_id("p").throughput) == 4500
    assert round(plan.by_id("z").throughput) == 8500
    assert {i.node_id for i in plan.by_id("z").inlets} == {"m", "f"}


def test_split_behind_a_screen_uses_the_typed_flows():
    """The split happens at the screen, so its out-edges size the branches — not the
    single edge from the feed into the screen."""
    nodes = [unit("i", "influent", "Feed", Q=7000),
             unit("s", "screen", "Screen"),
             unit("a", "aerated_CSTR", "Main", V=1000),
             unit("b", "aerated_CSTR", "Overflow", V=1000),
             unit("e", "effluent", "Effluent")]
    edges = [pipe("i", "s", 7000), pipe("s", "a", 3000), pipe("s", "b", 4000),
             pipe("a", "e"), pipe("b", "e")]
    plan = resolve(nodes, edges)
    assert round(plan.by_id("a").throughput) == 3000
    assert round(plan.by_id("b").throughput) == 4000


def test_no_reactor_is_an_error():
    nodes = [unit("i", "influent", "Feed", Q=1000), unit("e", "effluent", "Effluent")]
    try:
        resolve(nodes, [pipe("i", "e")])
    except TopologyError as e:
        assert "reactor" in str(e)
    else:
        raise AssertionError("expected a TopologyError")


def test_streets_are_the_parallel_branches():
    nodes = [unit("i", "influent", "Feed", Q=4000),
             unit("a1", "aerated_CSTR", "A1", V=500),
             unit("a2", "aerated_CSTR", "A2", V=500),
             unit("b1", "aerated_CSTR", "B1", V=500),
             unit("m", "aerated_CSTR", "Mix", V=500),
             unit("e", "effluent", "Effluent")]
    edges = [pipe("i", "a1", 2500), pipe("i", "b1", 1500),
             pipe("a1", "a2", 2500), pipe("a2", "m", 2500),
             pipe("b1", "m", 1500), pipe("m", "e")]
    plan = resolve(nodes, edges)
    streets = plan_streets(plan.reactors)
    assert ["a1", "a2"] in streets      # the two-reactor street stays one chain
    assert ["b1"] in streets
    assert ["m"] in streets             # the merge starts its own chain


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
