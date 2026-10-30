"""Resolve a drawn diagram into a *flow plan*: a DAG of reactors with explicit
inlets, outlets and per-branch flows.

Why this exists
---------------

The first version of the adapter collapsed any diagram to a single chain — the longest
simple path through the reactor units — and warned about everything else. That cannot
express the two things a real plant drawing is full of:

* **parallel streets** — two (or more) trains fed from the same point that re-merge
  further down (``trickling 1 → SBR A`` and ``trickling 2 → SBR B``, both into a
  polishing stage);
* **side streams** — a branch that leaves the main line and rejoins later (an
  equalisation basin, a bypass around a stage).

Both are plain graph structure, and PeePyPoo models them directly with ``FlowUnifier``
(merge) and ``FlowSeparator`` + ``FlowPump`` (split). What was missing was the *plan*:
which reactor feeds which, and with how much flow on each branch. This module produces
that plan from the canvas nodes/edges, with no PeePyPoo involvement at all — it is pure
graph work, so it can be unit-tested and reasoned about on its own.

The model builder (``server/simulate.py``) then walks the plan in topological order and
wires one PeePyPoo block per reactor.

Flows on branches
-----------------

A ``FlowSeparator`` in PeePyPoo needs the flow rate of all but one of its outlets (the
last one closes by mass balance). So the plan carries a *static* flow estimate for every
edge: influent flows are propagated forward through the graph, honouring the ``flow``
value a user typed on a pipe and splitting evenly where they did not. Those numbers set
the split pumps; the concentrations are whatever the solver computes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# Settlers that take solids out of the line and send them to waste, with no return: a
# primary clarifier ahead of the biology, or an intermediate clarifier between two stages.
# They hold no ASM1 states, but they change what flows on, so the plan carries them as
# nodes like the reactors — that way a feed can split into one, a street can merge into
# one and a bypass can rejoin at one with no special case. (The plant's *final* clarifier
# with its RAS loop is a different thing: ``CLARIFIER_TYPE`` below.)
SETTLER_TYPES = {"primary_clarifier"}

# Unit ids that become a node of the plan: every ASM1 reactor, plus the settlers.
REACTOR_TYPES = {
    "CSTR", "empty_CSTR", "anoxic_CSTR",
    "aerated_CSTR", "aerated_CSTR_off", "sbr", "trickling_filter",
    "switch_CSTR", "MBR", "MBBR", "MABR",
} | SETTLER_TYPES
INFLUENT_TYPE = "influent"
CLARIFIER_TYPE = "clarifier"
# Units that are drawn but carry no model of their own: the flow passes straight through
# them to whatever is next. (A clarifier is a pass-through *for routing*; it also gets a
# real IdealClarifier at the tail of the train — see simulate.py.)
PASSTHROUGH_TYPES = {
    "screen", "equalization_basin", "junction", CLARIFIER_TYPE,
}
# Open ends: flow that leaves the plant.
SINK_TYPES = {"effluent", "sludge"}

RECYCLE_STREAM_TYPES = {"sludge", "recycle"}
_RECYCLE_NAME_HINTS = ["RAS", "WAS", "recirc", "recycle", "sludge", "waste"]


class TopologyError(Exception):
    """The diagram cannot be resolved into a runnable flow plan."""


# ---------------------------------------------------------------------------
# Small helpers over the raw canvas dicts


def _data(node: dict) -> dict:
    return node.get("data") or {}


def _attrs(node: dict) -> dict:
    return _data(node).get("attributes") or {}


def _unit_id(node: dict) -> str:
    return _data(node).get("unitId") or ""


def _edge_data(e: dict) -> dict:
    return e.get("data") or {}


def is_recycle(e: dict) -> bool:
    """A sludge/recycle line — excluded from the forward graph (it closes a loop)."""
    if _edge_data(e).get("streamType") in RECYCLE_STREAM_TYPES:
        return True
    name = str(_edge_data(e).get("name") or "").lower()
    return any(h.lower() in name for h in _RECYCLE_NAME_HINTS)


def nominal_flow(value: Any) -> float | None:
    """A single number to size branch pumps with, from a possibly time-varying field.

    A constant is itself; a sampled profile (JSON list) is its mean, because that is the
    load the plant sees over the run; a sinusoid is its offset. Sizing on the mean rather
    than the peak is deliberate — a ``FlowPump`` holds a *fixed* flow, so a branch sized
    above what usually arrives would starve the branch that closes the mass balance.
    """
    direct = parse_float(value)
    if direct is not None:
        return direct
    try:
        from .timeseries import parse_time_value
        tv = parse_time_value(value)
    except Exception:
        return None
    if tv.kind == "const":
        return float(tv.const or 0.0)
    if tv.kind == "list" and tv.values:
        return sum(float(v) for v in tv.values) / len(tv.values)
    if tv.kind == "sine" and tv.sine:
        return float(tv.sine.get("offset") or 0.0)
    return None


def parse_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# The plan


@dataclass
class Inlet:
    """One stream entering a reactor."""
    kind: str                 # "reactor" | "influent" | "bypass"
    node_id: str              # the upstream reactor / influent node id
    flow: float = 0.0         # static flow estimate (m³/d), for reporting + split pumps


@dataclass
class Outlet:
    """One stream leaving a reactor towards another reactor (or out of the plant)."""
    kind: str                 # "reactor" | "sink"
    node_id: str              # downstream reactor id, or the sink node id ("" if open)
    flow: float = 0.0


@dataclass
class BypassSpec:
    """A controlled branch that routes flow *around* a reactor and rejoins after it."""
    when: str                 # "COD/N" | an ASM1 state name
    op: str                   # "<" | "<=" | ">" | ">="
    value: float              # the setpoint the ratio is compared against
    flow: float               # m³/d diverted while the condition holds
    base_flow: float = 0.0    # m³/d diverted otherwise (default: nothing)
    period_days: float = 0.04
    measure_from: str = ""    # reactor node id whose state is read (default: this one)
    rejoin_at: str = ""       # reactor node id the diverted stream rejoins at


@dataclass
class CycleSpec:
    """An SBR-style timed cycle: aeration follows fill/react/settle/decant phases."""
    cycle_h: float
    fill_h: float
    react_h: float
    settle_h: float
    decant_h: float
    offset_h: float = 0.0
    kla_react: float = 0.0    # filled in by the builder from the unit's kLa
    kla_idle: float = 0.0

    @property
    def cycle_d(self) -> float:
        return self.cycle_h / 24.0


@dataclass
class ReactorPlan:
    id: str
    unit_id: str
    name: str
    attrs: dict
    raw: dict
    index: int = 0                              # 1-based position in the build order
    model: str = ""                             # "r1", "r2", … (the PeePyPoo block name)
    inlets: list[Inlet] = field(default_factory=list)
    outlets: list[Outlet] = field(default_factory=list)
    bypass: BypassSpec | None = None
    cycle: CycleSpec | None = None
    throughput: float = 0.0                     # static flow through this reactor (m³/d)

    @property
    def label(self) -> str:
        return self.name or f"Reactor {self.index} ({self.unit_id})"

    @property
    def is_terminal(self) -> bool:
        return not any(o.kind == "reactor" for o in self.outlets)


@dataclass
class Plan:
    reactors: list[ReactorPlan]
    influents: dict[str, dict]            # influent node id → {"node": raw, "targets": [...]}
    clarifier: dict | None                # {"node_id", "node"} or None
    clarifier_feed: str = ""              # reactor id whose outflow reaches the clarifier
    warnings: list[str] = field(default_factory=list)
    edge_flows: dict[tuple[str, str], float] = field(default_factory=dict)

    def by_id(self, node_id: str) -> ReactorPlan | None:
        for r in self.reactors:
            if r.id == node_id:
                return r
        return None

    @property
    def sources(self) -> list[ReactorPlan]:
        """Reactors with no upstream reactor — where the plant feed enters."""
        return [r for r in self.reactors
                if not any(i.kind == "reactor" for i in r.inlets)]

    @property
    def terminals(self) -> list[ReactorPlan]:
        return [r for r in self.reactors if r.is_terminal]


# ---------------------------------------------------------------------------
# Graph construction


def _forward_graph(nodes: list[dict], edges: list[dict]) -> dict[str, list[tuple[str, float | None]]]:
    """node id → [(successor id, edge flow or None)], recycle lines excluded."""
    known = {str(n["id"]) for n in nodes}
    succ: dict[str, list[tuple[str, float | None]]] = {nid: [] for nid in known}
    for e in edges:
        if is_recycle(e):
            continue
        s, t = str(e.get("source")), str(e.get("target"))
        if s == t or s not in known or t not in known:
            continue
        flow = parse_float(_edge_data(e).get("flow"))
        if any(existing == t for existing, _ in succ[s]):
            continue
        succ[s].append((t, flow))
    return succ


def _contract(
    start: str,
    succ: dict[str, list[tuple[str, float | None]]],
    node_type: dict[str, str],
    stop_at: set[str],
) -> list[tuple[str, float | None]]:
    """Walk forward from ``start`` through pass-through units to the next real nodes.

    Returns ``[(node_id, flow_of_the_first_edge_on_that_branch)]``. A branch that runs
    into a sink (effluent/sludge) or a dead end contributes ``("", flow)`` so the caller
    can still account for the water leaving there.

    The flow reported is the one typed where the branch splits off: on the first edge out
    of ``start``, or — when a pass-through unit further on divides the stream again, like
    a screen feeding both the main line and an overflow — on the edge leaving that unit.
    The first edge alone would hand every branch behind such a unit the whole flow.
    """
    out: list[tuple[str, float | None]] = []
    seen: set[str] = {start}

    def walk(node: str, branch_flow: float | None, first: bool) -> None:
        branches = succ.get(node, [])
        for nxt, flow in branches:
            f = flow if (first or len(branches) > 1) else branch_flow
            if nxt in seen and nxt not in stop_at:
                continue
            if nxt in stop_at:
                out.append((nxt, f))
                continue
            if node_type.get(nxt) in SINK_TYPES:
                out.append(("", f))
                continue
            seen.add(nxt)
            walk(nxt, f, first=False)

    walk(start, None, first=True)
    # Deduplicate, keeping the first (and its flow).
    deduped: list[tuple[str, float | None]] = []
    for nid, f in out:
        if nid and any(nid == x for x, _ in deduped):
            continue
        deduped.append((nid, f))
    return deduped


def _topo_order(ids: list[str], succ: dict[str, list[str]], warnings: list[str]) -> list[str]:
    """Kahn's algorithm; a residual cycle is broken (with a warning) rather than fatal."""
    in_deg = {i: 0 for i in ids}
    for u in ids:
        for v in succ.get(u, []):
            if v in in_deg:
                in_deg[v] += 1
    queue = [i for i in ids if in_deg[i] == 0]
    # Stable order: keep the drawing order among equally-ready nodes.
    queue.sort(key=ids.index)
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for v in succ.get(n, []):
            if v not in in_deg:
                continue
            in_deg[v] -= 1
            if in_deg[v] == 0:
                queue.append(v)
        queue.sort(key=ids.index)
    if len(order) < len(ids):
        rest = [i for i in ids if i not in order]
        warnings.append(
            "The reactor graph contains a forward loop (" +
            ", ".join(rest[:3]) + (", …" if len(rest) > 3 else "") +
            "). The loop-closing links are ignored; mark a recirculation line as "
            "Sludge or Recycle so it is excluded from the forward flow."
        )
        order.extend(rest)
    return order


def _static_flows(plan_reactors: list[ReactorPlan], influent_q: dict[str, float]) -> None:
    """Propagate influent flows forward so every inlet/outlet carries a number.

    Where a user typed a flow on a pipe we keep it; where they did not, the parent's
    throughput is split evenly among the unspecified branches (after subtracting the
    branches that *are* specified). This only has to be good enough to size the split
    pumps and to report "what goes where" — the solver does the real mass balance.
    """
    by_id = {r.id: r for r in plan_reactors}

    for r in plan_reactors:        # plan_reactors is already in topological order
        inflow = 0.0
        for inl in r.inlets:
            if inl.kind == "influent":
                # ``resolve`` already apportioned a feed that enters several reactors;
                # only fill in the ones it could not size.
                if inl.flow <= 0:
                    inl.flow = influent_q.get(inl.node_id, 0.0)
            elif inl.kind == "reactor":
                up = by_id.get(inl.node_id)
                if up is not None:
                    match = next((o for o in up.outlets
                                  if o.kind == "reactor" and o.node_id == r.id), None)
                    if match is not None:
                        inl.flow = match.flow
            inflow += max(0.0, inl.flow)
        r.throughput = inflow

        known = sum(o.flow for o in r.outlets if o.flow > 0)
        unknown = [o for o in r.outlets if o.flow <= 0]
        if unknown:
            rest = max(0.0, inflow - known)
            share = rest / len(unknown) if rest > 0 else 0.0
            for o in unknown:
                o.flow = share
        elif r.outlets and known > 0 and inflow > 0:
            # Scale user-typed branch flows so they add up to what actually arrives;
            # drawings are usually rounded (5200 + 4200 for a 9400 m³/d plant).
            scale = inflow / known
            if abs(scale - 1.0) > 1e-9:
                for o in r.outlets:
                    o.flow *= scale


# ---------------------------------------------------------------------------
# Per-unit specs read off the canvas


_DEFAULT_PHASES = {"fill": 1.5, "react": 3.5, "settle": 0.75, "decant": 1.65}


def _cycle_spec(node: dict) -> CycleSpec | None:
    """An SBR unit's timed cycle, from its attributes (or the explicit ``data.cycle``)."""
    if _unit_id(node) != "sbr":
        return None
    attrs = _attrs(node)
    raw = _data(node).get("cycle") or {}

    def pick(key: str, default: float) -> float:
        v = parse_float(raw.get(key))
        if v is None:
            v = parse_float(attrs.get(key))
        return float(v) if v is not None and v >= 0 else default

    fill = pick("fill", _DEFAULT_PHASES["fill"])
    react = pick("react", _DEFAULT_PHASES["react"])
    settle = pick("settle", _DEFAULT_PHASES["settle"])
    decant = pick("decant", _DEFAULT_PHASES["decant"])
    offset = pick("offset", 0.0)

    total = parse_float(raw.get("cycle")) or parse_float(attrs.get("cycle"))
    phases = fill + react + settle + decant
    if phases <= 0:
        return None
    if total is None or total < phases:
        total = phases
    return CycleSpec(cycle_h=float(total), fill_h=fill, react_h=react,
                     settle_h=settle, decant_h=decant, offset_h=offset)


def _bypass_spec(node: dict) -> BypassSpec | None:
    """A controlled branch around this reactor, from ``data.bypass``."""
    raw = _data(node).get("bypass")
    if not isinstance(raw, dict) or not raw:
        return None
    when = str(raw.get("when") or "COD/N")
    op = str(raw.get("op") or ">")
    if op not in ("<", "<=", ">", ">="):
        raise TopologyError(
            f"Bypass on “{_data(node).get('name') or _unit_id(node)}”: "
            f"'op' must be one of <, <=, >, >= (got {op!r})."
        )
    value = parse_float(raw.get("value"))
    flow = parse_float(raw.get("flow"))
    if value is None or flow is None or flow < 0:
        raise TopologyError(
            f"Bypass on “{_data(node).get('name') or _unit_id(node)}”: "
            "needs a numeric 'value' (the setpoint) and a non-negative 'flow' (m³/d)."
        )
    base = parse_float(raw.get("base_flow")) or 0.0
    period = parse_float(raw.get("period_days")) or 0.04
    return BypassSpec(when=when, op=op, value=float(value), flow=float(flow),
                      base_flow=max(0.0, base), period_days=max(1 / 96.0, min(1.0, period)),
                      measure_from=str(raw.get("measure_from") or ""),
                      rejoin_at=str(raw.get("rejoin_at") or ""))


# ---------------------------------------------------------------------------
# Public entry point


def resolve(units_data: list[dict], edges: list[dict]) -> Plan:
    """Canvas nodes + edges → a topologically ordered :class:`Plan`.

    Raises :class:`TopologyError` when the diagram has no reactor at all or no influent
    reaches one. Everything else is reported through ``plan.warnings``.
    """
    nodes = [n for n in units_data if n.get("type") == "unit" or not n.get("type")]
    raw_by_id = {str(n["id"]): n for n in nodes}
    node_type = {str(n["id"]): _unit_id(n) or str(n.get("type") or "") for n in nodes}

    reactor_ids = [nid for nid, t in node_type.items() if t in REACTOR_TYPES]
    influent_ids = [nid for nid, t in node_type.items() if t == INFLUENT_TYPE]
    if not reactor_ids:
        raise TopologyError(
            "No simmable reactor units on the canvas. "
            "Add at least one CSTR, aerated CSTR, anoxic CSTR, SBR, MABR, MBR, or MBBR."
        )

    warnings: list[str] = []
    succ = _forward_graph(nodes, edges)
    stop_at = set(reactor_ids)

    # Reactor → reactor adjacency, with the flow of the branching edge.
    down: dict[str, list[tuple[str, float | None]]] = {}
    for rid in reactor_ids:
        down[rid] = _contract(rid, succ, node_type, stop_at)

    plain_succ = {rid: [t for t, _ in down[rid] if t] for rid in reactor_ids}
    order = _topo_order(reactor_ids, plain_succ, warnings)

    reactors: list[ReactorPlan] = []
    for i, rid in enumerate(order, start=1):
        raw = raw_by_id[rid]
        rp = ReactorPlan(
            id=rid, unit_id=node_type[rid], name=_data(raw).get("name") or "",
            attrs=_attrs(raw), raw=raw, index=i, model=f"r{i}",
        )
        rp.bypass = _bypass_spec(raw)
        rp.cycle = _cycle_spec(raw)
        reactors.append(rp)

    pos = {r.id: k for k, r in enumerate(reactors)}

    # Outlets (and the matching inlets on the far side).
    for r in reactors:
        for target, flow in down[r.id]:
            if not target:
                r.outlets.append(Outlet(kind="sink", node_id="", flow=flow or 0.0))
                continue
            if pos[target] <= pos[r.id]:
                # Loop-closing edge the topo sort already warned about — drop it.
                continue
            r.outlets.append(Outlet(kind="reactor", node_id=target, flow=flow or 0.0))
            reactors[pos[target]].inlets.append(
                Inlet(kind="reactor", node_id=r.id, flow=flow or 0.0)
            )
        if not r.outlets:
            r.outlets.append(Outlet(kind="sink", node_id="", flow=0.0))

    # Influents → the reactor(s) they reach, through pass-through units.
    influents: dict[str, dict] = {}
    influent_q: dict[str, float] = {}
    for nid in influent_ids:
        raw = raw_by_id[nid]
        q = nominal_flow(_attrs(raw).get("Q")) or 0.0
        targets = [(t, f) for t, f in _contract(nid, succ, node_type, stop_at) if t]
        if not targets:
            warnings.append(
                f"Influent “{_data(raw).get('name') or 'Influent'}” does not reach any "
                "reactor — it is not modelled."
            )
            continue
        influent_q[nid] = q
        influents[nid] = {"node": raw, "targets": [t for t, _ in targets]}
        if len(targets) == 1:
            reactors[pos[targets[0][0]]].inlets.append(
                Inlet(kind="influent", node_id=nid, flow=q)
            )
        else:
            # One influent feeding several reactors: split by the drawn branch flows
            # (falling back to an even split).
            typed = [f for _, f in targets if f and f > 0]
            total_typed = sum(typed)
            for t, f in targets:
                if f and f > 0:
                    share = q * (f / total_typed) if total_typed > 0 else q / len(targets)
                else:
                    share = max(0.0, q - total_typed) / max(1, len(targets) - len(typed))
                reactors[pos[t]].inlets.append(
                    Inlet(kind="influent", node_id=nid, flow=share)
                )

    if not influents:
        warnings.append(
            "No Influent unit reaches a reactor — the flow from the Simulation window's "
            "setup panel is used instead."
        )

    _static_flows(reactors, influent_q)

    for r in reactors:
        if not r.inlets:
            raise TopologyError(
                f"Reactor “{r.label}” has no inlet at all — connect a pipe into it."
            )

    clarifier_node = next((raw_by_id[nid] for nid, t in node_type.items()
                           if t == CLARIFIER_TYPE), None)
    clarifier = ({"node_id": str(clarifier_node["id"]), "node": clarifier_node}
                 if clarifier_node is not None else None)
    clarifier_feed = ""
    if clarifier is not None:
        # Which reactor's outflow actually reaches the clarifier? Walk forward from each
        # reactor, stopping at the next reactor, and see whether the clarifier is on the
        # way. (The clarifier is a pass-through for routing, so the contracted graph has
        # already walked past it — this asks the question the contraction answers away.)
        target = clarifier["node_id"]
        for r in reversed(reactors):
            seen = {r.id}
            queue = [t for t, _ in succ.get(r.id, [])]
            hit = False
            while queue:
                cur = queue.pop(0)
                if cur in seen:
                    continue
                seen.add(cur)
                if cur == target:
                    hit = True
                    break
                if cur in stop_at:          # another reactor — this branch is not ours
                    continue
                queue.extend(t for t, _ in succ.get(cur, []))
            if hit:
                clarifier_feed = r.id
                break
        if not clarifier_feed and reactors:
            clarifier_feed = (reactors and
                              max(reactors, key=lambda r: (r.is_terminal, r.index)).id)
    if any(is_recycle(e) for e in edges) and clarifier is None:
        warnings.append(
            "Recycle / sludge lines are present but no Clarifier unit is on the canvas, "
            "so they are not modelled. Add a Clarifier next to the last reactor to enable "
            "RAS/WAS and MLSS/SRT control."
        )

    splits = sum(1 for r in reactors
                 if len([o for o in r.outlets if o.kind == "reactor"]) > 1)
    merges = sum(1 for r in reactors
                 if len([i for i in r.inlets if i.kind == "reactor"]) > 1)
    streets = plan_streets(reactors)
    if splits or merges or len(streets) > 1:
        warnings.append(
            f"Resolved {len(reactors)} reactors on {len(streets)} branches "
            f"({splits} split{'s' if splits != 1 else ''}, "
            f"{merges} merge{'s' if merges != 1 else ''}) — the branch flows are in the "
            "setup panel."
        )

    return Plan(reactors=reactors, influents=influents, clarifier=clarifier,
                clarifier_feed=clarifier_feed, warnings=warnings)


def plan_streets(reactors: Iterable[ReactorPlan]) -> list[list[str]]:
    """Group the reactors into the parallel streets the plant actually runs.

    A street is a maximal chain that starts where flow enters it on its own — the head of
    the plant, a split, or the far side of a merge — and runs until the chain splits or
    joins another. Two trains fed by two separate headworks are therefore two streets,
    exactly like two trains fed from one split.

    Only used for reporting ("5 reactors on 2 parallel streets") — the build itself works
    straight off the inlets/outlets.
    """
    rs = list(reactors)
    by_id = {r.id: r for r in rs}

    def n_down(r: ReactorPlan) -> int:
        return len([o for o in r.outlets if o.kind == "reactor"])

    def n_up(r: ReactorPlan) -> int:
        return len([i for i in r.inlets if i.kind == "reactor"])

    # A reactor starts a street when it has no single upstream reactor that flows only
    # into it: i.e. it is a head, it is downstream of a split, or it is a merge point.
    heads = [
        r for r in rs
        if n_up(r) != 1 or n_down(by_id[next(i.node_id for i in r.inlets
                                             if i.kind == "reactor")]) > 1
    ]
    streets: list[list[str]] = []
    for h in heads:
        chain = [h.id]
        cur = h
        while n_down(cur) == 1:
            nxt = by_id.get(next(o.node_id for o in cur.outlets if o.kind == "reactor"))
            if nxt is None or n_up(nxt) != 1:
                break
            chain.append(nxt.id)
            cur = nxt
        streets.append(chain)
    return streets
