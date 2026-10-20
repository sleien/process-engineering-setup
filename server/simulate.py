"""Translate a WWTP diagram (unit nodes + pipe edges) into a runnable PeePyPoo model.

Conventions
-----------

* An **Influent** is a unit on the canvas (``unitId == 'influent'``). Each carries:
    - ``Q`` attribute in m³/d
    - Any subset of the 14 ASM1 state concentrations (mg/L). Missing states are 0.
  When the user leaves the composition entirely empty (flow only) we fall back to the
  BSM1 stabilisation feed.

* **Time-dependent values.** Any of the influent fields (flow, concentrations) and a
  reactor's ``kLa`` may be:

    - a plain number — constant;
    - a JSON list of numbers — ``[1500, 2000, 1200]`` linearly interpolated across the
      whole simulated window (first value at t=0, last at t_end, clamped outside);
    - a formula in ``t`` (days) — e.g. ``250+100*sin(2*pi*t/24)``. The formula language
      is a small sandbox (see ``server/timeseries.py``): numbers, ``t``, and ``sin cos
      tan asin acos atan sinh cosh tanh exp log log10 log2 sqrt abs floor ceil min max
      pow`` with ``+ - * / // % **``.

  Time-varying values are wired as ``peepypoo.TimeVaryingFunction`` blocks so the solver
  sees a continuous signal.

* Multiple **Influent** units can be drawn; each is connected by an edge to the reactor
  it feeds. A reactor with several sources is wired through a ``FlowUnifier``.

* The **reactor train** is the longest simple path among reactor-type units (CSTR,
  aerated CSTR, anoxic CSTR, SBR, trickling filter, MBR, MBBR, **MABR**, switchable).

* **Aerated** units (aerated_CSTR, switch_CSTR, MBR, MBBR, MABR) add an ``Aeration``
  process; ``aerated_CSTR_off`` is non-aerated.

* **Effluent** is the outflow of the last reactor in the train, through a **perfect
  clarifier** (``IdealClarifier`` with ``f_ns=0``) when the diagram carries a ``clarifier``
  unit: no solids pass to the effluent, and the settleable sludge is split by a
  ``FlowSeparator`` into a **RAS** return (pumped back to the first reactor, flow read from
  the clarifier's ``Qr`` field, SRT is the control target) + a **WAS** waste (free remainder,
  flow from ``Q_was``).

  Because the perfect clarifier itself holds no solids, the solids are retained by the RAS
  loop. A small periodic callback (``PeriodicCallback`` + ``SetIndex``) drives the RAS pump
  to hold the mixed-liquor solids (MLSS, the SRT proxy) at the clarifier's ``MLSS`` target.
  That is what prevents washout — the reactor train runs at a finite, controllable SRT.

* Reactor temperature is the plant-wide static ``Process`` temperature (fixed at 20 °C);
  time-varying temperature is not supported by ASM1's process API yet.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

import peepypoo as ppp

from .controllers import (
    ControllerSpec,
    build_controller_callback,
    parse_controller,
    summarize as summarize_controller,
)
from .timeseries import TimeValue, TimeValueError, parse_time_value


class SimError(Exception):
    """Raised when the diagram cannot be translated into a runnable model."""


# Guards the (not thread-safe) Julia bridge so concurrent requests don't interleave.
_engine_lock = threading.Lock()


UNIT_REACTOR_TYPES = {
    "CSTR", "empty_CSTR", "anoxic_CSTR",
    "aerated_CSTR", "aerated_CSTR_off", "sbr", "trickling_filter",
    "switch_CSTR", "MBR", "MBBR", "MABR",
}
AERATED_TYPES = {"aerated_CSTR", "switch_CSTR", "MBR", "MBBR", "MABR"}
NON_AERATED_TYPES = {"aerated_CSTR_off"}
INFLUENT_TYPE = "influent"
RECYCLE_STREAM_TYPES = {"sludge", "recycle"}

ASM1_STATES = [
    "S_I", "S_S", "X_I", "X_S", "X_BH", "X_BA", "X_P",
    "S_O", "S_NO", "S_NH", "S_ND", "X_ND", "S_ALK", "S_N2",
]

DEFAULT_INFLUENT_FALLBACK = {
    "S_I": 30.0, "S_S": 69.5, "X_I": 51.2, "X_S": 202.32,
    "X_BH": 28.17, "X_BA": 0.0, "X_P": 0.0,
    "S_O": 0.0, "S_NO": 0.0, "S_NH": 31.56, "S_ND": 6.95,
    "X_ND": 10.59, "S_ALK": 7.0, "S_N2": 0.0,
}

DEFAULT_INFLUENT_FLOW_M3D = 2000.0
DEFAULT_KLA_PER_D = 300.0
DEFAULT_VOLUME_M3 = 1000.0
T_MIN_DAYS = 2.0
T_MAX_DAYS = 14.0
REACTOR_TEMPERATURE_C = 20.0
# Defaults used when the clarifier unit is present but the user hasn't filled in its
# fields. The magnitudes are for a mid-size activated-sludge plant (2–10 d SRT is the
# working range). The *target* MLSS defaults to the seed value used for the reactors —
# the control simply holds what the user started with.
DEFAULT_RAS_FLOW_M3D = 2000.0     # Qr — a mid-size RAS multiple of effluent
DEFAULT_WAS_FLOW_M3D = 120.0      # Q_was — a small waste sludge
DEFAULT_SRT_TARGET_D = 8.0        # SRT target (d) — used only for reporting
DEFAULT_MLSS_TARGET_MGL = 3000.0  # MLSS target (mg/L), the control's holding setpoint
CLARIFIER_TYPE = "clarifier"

_RECYLE_NAME_HINTS = ["RAS", "WAS", "recirc", "recycle", "sludge", "waste"]

# Attribute keys a user may enter as a time-dependent expression.
TIME_VARYING_KEYS = {"Q", "kLa"} | set(ASM1_STATES)


def _parse_float(value: Any) -> float | None:
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


def _edge_data(e: dict) -> dict:
    return e.get("data") or {}


def _is_recycle(e: dict) -> bool:
    st = _edge_data(e).get("streamType")
    if st in RECYCLE_STREAM_TYPES:
        return True
    name = str(_edge_data(e).get("name") or "").lower()
    return any(h in name for h in _RECYLE_NAME_HINTS)


def _longest_simple_path(units: list[str], adj: dict[str, list[str]]) -> list[str] | None:
    in_deg = {u: 0 for u in units}
    for u in units:
        for v in adj.get(u, []):
            if v in in_deg:
                in_deg[v] += 1
    sources = [u for u in units if in_deg.get(u, 0) == 0]
    if not sources:
        return None
    best: list[str] = []

    def dfs(node: str, path: list[str]) -> None:
        nonlocal best
        if len(path) > len(best):
            best = list(path)
        for nxt in adj.get(node, []):
            if nxt in path:
                continue
            path.append(nxt)
            dfs(nxt, path)
            path.pop()

    for s in sources:
        dfs(s, [s])
    return best or None


# -- Influent node → (flow TV, per-state TV map, composition source) ------------

def _influent_spec(node: dict) -> tuple[TimeValue, dict[str, TimeValue], str]:
    """Extract the influent's flow + composition, each possibly time-dependent.

    Returns ``(flow, composition, source)`` where source is
    "user-supplied" or "default (BSM1 stabilisation)". TimeValueError propagates
    (the caller converts it to a SimError).
    """
    attrs = (node.get("data") or {}).get("attributes") or node.get("attributes") or {}

    raw_q = attrs.get("Q")
    if raw_q is None or str(raw_q).strip() == "":
        raise SimError("The Influent unit has no Flow rate (Q) set.")
    flow = parse_time_value(raw_q)
    if flow.kind == "const" and flow.const is not None and flow.const <= 0:
        raise SimError(f"Influent flow rate must be positive (got {flow.const:g}).")

    raw_states = {k: v for k, v in attrs.items() if k in ASM1_STATES}
    user_set = any(
        (v is not None and str(v).strip() != "") if isinstance(v, str) else v
        for v in raw_states.values()
    )
    if not user_set:
        composition = {s: TimeValue("const", const=float(DEFAULT_INFLUENT_FALLBACK[s]))
                       for s in ASM1_STATES}
        source = "default (BSM1 stabilisation)"
    else:
        composition = {
            s: parse_time_value(raw_states[s]) if s in raw_states else TimeValue("const", const=0.0)
            for s in ASM1_STATES
        }
        source = "user-supplied"
    return flow, composition, source


def _initial_states(mlss: float | None = None) -> dict[str, float]:
    """Seed the CSTRs with a realistic mixed-liquor state so ASM1 starts away from the
    singular zero-biomass point (with biodegradable substrate present the solver aborts
    on the first step). The seed still converges to the true steady state.

    ``mlss`` (mg/L, a.k.a. g/m³) — when a reactor carries an MLSS attribute it is used to
    size the seed: the particulates (the mixed-liquor suspended solids) are split into a
    plausible heterotroph-dominant mix that sums to MLSS, instead of the ~2500 default.
    """
    mlss = float(mlss) if (mlss is not None and mlss > 0) else 2500.0
    return {
        "S_I": 5.0, "S_S": 50.0,
        "X_I": 0.06 * mlss,      # inert particulate
        "X_S": 0.02 * mlss,      # slowly biodegradable (particulate)
        "X_BH": 0.86 * mlss,     # active heterotrophs dominate MLSS
        "X_BA": 0.022 * mlss,    # active autotrophs
        "X_P": 0.02 * mlss,      # particulate products
        "S_O": 0.5,
        "S_NO": 0.0, "S_NH": 12.0, "S_ND": 3.0,
        "X_ND": 0.01 * mlss,     # particulate biodegradable N
        "S_ALK": 5200.0, "S_N2": 0.0,
    }


def _tv_value_at(tv: TimeValue, t: float) -> float:
    """The numeric value a TimeValue evaluates to at time t (for reports/heuristics)."""
    if tv.kind == "const":
        return float(tv.const or 0.0)
    try:
        v = float(tv.to_function(max(1.0, t))(t))
        return v if math.isfinite(v) else 0.0
    except Exception:
        return 0.0


def _as_ppp_source(tv: TimeValue, t_end: float, name_hint: str) -> Any:
    """TimeValue → constant float or peepypoo.TimeVaryingFunction (pre-validated at t=0)."""
    if tv.kind == "const":
        return float(tv.const or 0.0)
    fn = tv.to_function(t_end)
    try:
        v0 = float(fn(0.0))
    except Exception as e:
        raise SimError(f"Time expression for '{name_hint}' could not be evaluated: {e!r}")
    if not math.isfinite(v0):
        raise SimError(f"Time expression for '{name_hint}' is not finite at t=0.")
    return ppp.TimeVaryingFunction(fn, name=name_hint)


def _build_mlss_callback(
    sysS: Any,
    recirc: dict[str, Any],
    t_end: float,
    read_reactor: str = "r1",
    period_days: float = 0.1,
) -> Any:
    """Build the periodic ``PeriodicCallback`` that holds the mixed-liquor MLSS at target.

    The manipulated variable is the WAS flow (``p_was.k``). In the built topology the RAS
    return is a fixed flow (the ``Qr`` field) and the WAS branch is the sludge side-stream;
    the MLSS of the tanks is set by how much that side-stream wastes, so the control law is a
    proportional actuator around the setpoint:

        Q_was ← Q_was0 · (MLSS_target / MLSS)

    MLSS above target → waste more → MLSS falls; below target → waste less → solids
    accumulate → MLSS recovers. (With a fixed RAS the retention, and hence the reachable
    operating range, is fixed; this actuator steers the waste within it.) The ratio is
    clamped to ``[0.1, 50]`` and the flow to ``[1, 0.5·Q]`` m³/d so the first tick is safe
    even when the plant starts far from the requested MLSS. Treat the held value as "close
    to target", not exact — the reachable point also depends on the fixed RAS split.

    ``read_reactor`` is the reactor whose mixed-liquor MLSS the controller tracks; in a
    perfect-clarifier plant the MLSS of every reactor in the train is essentially the
    same (series-fed, same RAS), so ``r1`` is a fine proxy.
    """
    from peepypoo import GetIndex, SetIndex, u_modified

    SOLID_STATES = ["X_BH", "X_BA", "X_I", "X_S", "X_P", "X_ND"]
    target = float(recirc["mlss_target"])
    was_q0 = float(recirc["was_q0"])
    was_k = recirc["was_k_param"]
    total_q = float(recirc["total_q"])

    def _sym(state: str) -> Any:
        for u in sysS.unknowns:
            tail = str(u).split("₊")[-1].split("(")[0]
            head = str(u).split("₊")[0]
            if tail == state and head == read_reactor:
                return u
        raise SimError(
            f"Could not find state {state} on {read_reactor} to build the MLSS callback."
        )

    gets: dict[str, Any] = {s: GetIndex(sysS, _sym(s)) for s in SOLID_STATES}
    set_was = SetIndex(sysS, was_k)

    def affect(integrator: Any) -> None:
        try:
            mlss = sum(max(0.0, float(gets[s](integrator))) for s in SOLID_STATES)
        except Exception:
            return
        if mlss < 1.0:
            # Avoid divide-by-zero: if the MLSS has collapsed, drive the WAS to its minimum
            # (retain as much solids as possible) rather than zeroing the waste.
            set_was(integrator, max(1.0, was_q0 * 0.1))
            u_modified(integrator, False)
            return
        # Proportional, stabilising law: waste *more* above target, *less* below.
        # (target/mlss would be positive feedback — low MLSS → max waste → washout.)
        ratio = max(0.1, min(50.0, mlss / target))
        q = max(1.0, min(0.5 * total_q, was_q0 * ratio))
        set_was(integrator, q)
        u_modified(integrator, False)

    return ppp.PeriodicCallback(period=period_days, affect=affect, initial_affect=True)


# -- Build the model -------------------------------------------------------------

def _build_model(
    order: list[str],
    reactor_nodes: list[dict],
    raw_nodes_by_id: dict[str, dict],
    influents_by_reactor: dict[str, list[str]],
    t_end: float,
    warnings: list[str],
    synthetic: dict | None,
    clarifier: dict[str, Any] | None,
    total_q: float,
) -> tuple[Any, list[Any], dict[str, dict[str, Any]], list[tuple[Any, Any, ControllerSpec]], dict[str, Any] | None]:
    """Wire the PeePyPoo system.

    Returns ``(model, reactor_objs (r1..rN), ppp_influents, controllers, recirc)`` where:

    * ``ppp_influents`` is keyed by the influent node id (or ``__synthetic__``) and carries the
      meta report;
    * ``controllers`` is a list of ``{reactor, name, k_param, spec, kLa}`` for every aerated
      reactor that has a controller (see ``server/controllers.py``);
    * ``recirc`` is ``None`` when no clarifier unit is on the canvas — otherwise a dict
      ``{clarifier, ras_pump, was_pump, was_k_param, ras_q, was_q0, mlss_target, total_q,
      clarifier_raw}`` that carries the parts the MLSS control callback
      (``_build_mlss_callback``) needs to read/write.
    """
    asm = ppp.Process("ASM1", name="asm1", temperature=REACTOR_TEMPERATURE_C)
    states_od = asm.states()
    init = _initial_states()

    model = ppp.SystemConnection(name="plant")
    model.start_building()

    # ---- Build every Influent ------------------------------------------------
    ppp_influents: dict[str, dict[str, Any]] = {}

    def make_ppp_influent(flow_tv: TimeValue, comp_tvs: dict[str, TimeValue],
                          label: str, node_id: str, synthetic: bool):
        # Use the dict-API form: ``ppp.Influent(comp_dict, states_od, flowrate=…)`` takes a
        # dict of **plain numbers** for constant compositions and only a single
        # ``TimeVaryingFunction`` (for the *flow*) when the flow itself varies in time.
        #
        # Passing *per-state* TimeVaryingFunction blocks — which is what the old code did —
        # compiles in isolation but leaves the plant model **one equation short** when the
        # Influent is wired into a multi-reactor train with a clarifier. The backend
        # (ModelingToolkit/peepypoo) drops a state-allocation equation in that configuration
        # and ``structural_simplify`` then fails with "ExtraVariablesSystemException:
        # unbalanced … potential extra variable: r1₊...₊S_ALK(t)".
        #
        # The dict-API form is the shape that closes — see ``_probe.py`` in this repo (the
        # same pattern as BSM1 references) — and matches every other ``Influent`` usage in
        # the peepypoo examples. Time-varying *compositions* (per-state) are not supported
        # in this form; for that, the user should use the ``kLa``-style block instead (the
        # aeration path already does this).
        comp: dict[str, Any] = {}
        for i, s in enumerate(ASM1_STATES):
            tv = comp_tvs.get(s)
            if tv is None or tv.kind == "const":
                comp[s] = float(tv.const or 0.0) if tv is not None else 0.0
            else:
                # Time-varying (list / sine) concentration — fall back to the value at t=0
                # for the *initial seed* and let ``_as_ppp_source`` wire the time-varying
                # function as the flowrate-equivalent port. (Not expected in practice for
                # WWTP influent — see note above — but we keep the escape hatch.)
                comp[s] = float(tv.value_at(0.0, t_end))
        # Flow is the only thing we expect to be time-varying; wire it the same way as
        # the kLa path (``_as_ppp_source`` returns either a constant float or a
        # ``TimeVaryingFunction``).
        obj = ppp.Influent(
            comp,
            states_od,
            flowrate=_as_ppp_source(flow_tv, t_end, f"q_{node_id}"),
            name=f"inf_{node_id}",
        )
        return {
            "obj": obj,
            "label": label,
            "flow": flow_tv,
            "composition": dict(comp_tvs),
            "source": "user-supplied" if not synthetic else "synthetic (setup panel)",
            "synthetic": synthetic,
        }

    for _rid, infl_ids in influents_by_reactor.items():
        for node_id in infl_ids:
            if node_id in ppp_influents:
                continue
            raw_node = raw_nodes_by_id.get(node_id)
            if raw_node is None:
                continue
            flow_tv, comp_tvs, source = _influent_spec(raw_node)
            label = (raw_node.get("data") or {}).get("name") or "Influent"
            meta = make_ppp_influent(flow_tv, comp_tvs, label, node_id, synthetic=False)
            meta["source"] = source
            ppp_influents[node_id] = meta

    if synthetic is not None:
        flow_tv = parse_time_value(synthetic.get("flow") or DEFAULT_INFLUENT_FLOW_M3D)
        comp_tvs = {s: TimeValue("const", const=float((synthetic.get("composition") or
                  DEFAULT_INFLUENT_FALLBACK)[s] or 0.0)) for s in ASM1_STATES}
        meta = make_ppp_influent(flow_tv, comp_tvs, synthetic.get("label", "Influent (synthetic)"),
                                "__synthetic__", synthetic=True)
        meta["source"] = "synthetic (setup panel)"
        ppp_influents["__synthetic__"] = meta

    # ---- Clarifier + recirculation pumps, created before the loop --------------
    # When a ``clarifier`` unit is on the canvas the last reactor's outflow is sent to a perfect
    # ideal clarifier (f_ns=0, no solids to the effluent). The clarified sludge splits by a
    # FlowSeparator into:
    #   * RAS  — a pump with a *fixed* flowrate (the ``Qr`` field), returned to the first reactor;
    #   * WAS  — a pump (the ``Q_was`` field) to the open sludge sink.
    # The clarifier's effluent port is left open (the plant's water-balance remainder), so both
    # pumps' flows are fixed — the one configuration the peepypoo/ModelingToolkit backend
    # accepts at this scale. The *control* lever is the WAS pump: a periodic callback (built in
    # ``build()``) drives its flow toward ``WAS = WAS0 · (MLSS_target / MLSS)`` — more waste when
    # the MLSS is above target, less when below — which is the SRT lever that keeps the biomass
    # in the loop at the requested mixed-liquor concentration instead of washing it out.
    # Both pumps must exist before the reactor train is built so r1's inlet can carry the RAS.
    p_ras: Any = None
    p_was: Any = None
    q_ras = q_was = mlss_target = 0.0
    f_ns = 0.0
    clar_name = "Clarifier"
    clar_raw = {}
    if clarifier is not None:
        clar_raw = raw_nodes_by_id.get(clarifier.get("node_id")) or clarifier.get("node") or {}
        clar_attrs = (clar_raw.get("data") or {}).get("attributes") or {}
        clar_name = (clar_raw.get("data") or {}).get("name") or "Clarifier"
        q_ras = _parse_float(clar_attrs.get("Qr")) or DEFAULT_RAS_FLOW_M3D
        q_ras = max(1.0, min(q_ras, 5.0 * max(total_q, 1.0)))
        q_was = _parse_float(clar_attrs.get("Q_was")) or DEFAULT_WAS_FLOW_M3D
        q_was = max(1.0, min(q_was, 0.2 * max(total_q, 1.0)))
        mlss_target = _parse_float(clar_attrs.get("MLSS")) or DEFAULT_MLSS_TARGET_MGL
        f_ns = _parse_float(clar_attrs.get("f_ns")) or 0.0
        p_ras = ppp.FlowPump(states_od, flowrate=q_ras, name="ras")
        p_was = ppp.FlowPump(states_od, flowrate=q_was, name="was")

    # ---- Build the reactor train ----------------------------------------------
    react_objs: list[Any] = []
    controllers: list[dict[str, Any]] = []
    for i, uid in enumerate(order, start=1):
        r = next(x for x in reactor_nodes if x["id"] == uid)
        raw_node = raw_nodes_by_id.get(uid) or {}
        node_data = raw_node.get("data") or {}
        attrs = node_data.get("attributes") or {}
        volume = _parse_float(attrs.get("V")) or DEFAULT_VOLUME_M3
        aerated = r["unitId"] in AERATED_TYPES
        if r["unitId"] in NON_AERATED_TYPES:
            aerated = False

        procs: list[Any] = [asm]
        kLa_kind = None
        if aerated:
            raw = attrs.get("kLa")
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                procs.append(ppp.Aeration(name=f"aer{i}"))
                kLa = TimeValue("const", const=DEFAULT_KLA_PER_D)
            else:
                kLa = parse_time_value(raw)
                procs.append(ppp.Aeration(name=f"aer{i}"))
        else:
            kLa = None

        label = r["name"] or f"Reactor {i} ({r['unitId']})"

        # Controller — parse *before* building, so a bad controller fails the run
        # (and the UI gets a 422) instead of silently running with a constant kLa.
        spec: ControllerSpec | None = None
        if aerated and kLa is not None:
            try:
                spec = parse_controller(node_data, reactor_name=f"r{i}", base=kLa)
            except ValueError as e:
                raise SimError(f"Controller on {label}: {e}") from e

        react = ppp.CSTR(volume, procs, initial_states=init, name=f"r{i}")

        sources: list[Any] = []
        if i > 1 and react_objs:
            sources.append(react_objs[-1].outflows(0))
        for infl_id in influents_by_reactor.get(uid, []):
            meta = ppp_influents.get(infl_id)
            if meta is None:
                continue
            sources.append(meta["obj"].outflows(0))
        if i == 1 and "__synthetic__" in ppp_influents:
            sources.append(ppp_influents["__synthetic__"]["obj"].outflows(0))
        # Return-activated-sludge: the RAS return from the clarifier merges in here.
        if i == 1 and p_ras is not None:
            sources.append(p_ras.outflows(0))

        if not sources:
            raise SimError(f"Reactor {r['name'] or r['unitId']} has no inlet at all.")

        if len(sources) == 1:
            model.connect(sources[0], react.inflows(0))
        else:
            uni = ppp.FlowUnifier(states_od, n_in=len(sources), name=f"uni{i}")
            for s_idx, src in enumerate(sources):
                model.connect(src, uni.inflows(s_idx))
            model.connect(uni.outflows(0), react.inflows(0))

        if aerated and kLa is not None:
            if not react.exogenous_input_names:
                raise SimError(f"Aeration on {r['name'] or r['unitId']} has no kLa input port.")
            aero_name = react.exogenous_input_names[0]
            # The aeration rate is always a writable Constant block (its ``k`` parameter is
            # what a controller rewrites each tick). A plain constant kLa keeps k as-is and
            # no controller is needed; otherwise a PeriodicCallback seeds/overrides k.
            base_k = float(kLa.value_at(0.0, t_end))
            if not math.isfinite(base_k):
                raise SimError(f"kLa expression on {r['name'] or r['unitId']} is not finite at t=0.")
            kla_block = ppp.Constant(k=base_k, name=f"kla{i}")
            model.connect(kla_block.output, react.exogenous_inputs(aero_name))
            r["kLaKind"] = kLa            # the (possibly time-varying) base, for the report
            r["label"] = label
            if spec is not None:
                controllers.append(
                    {"reactor": react, "name": label, "k_param": kla_block.parameters[0],
                     "spec": spec, "kLa": kLa},
                )

        react_objs.append(react)

    # ---- Wire the clarifier + sludge split (RAS/WAS) ---------------------------
    # The RAS and WAS pumps both exist (created before the loop) and r1's inlet already
    # carries the RAS return. Here we close the loop:
    #   last reactor → perfect IdealClarifier (f_ns=0, no solids to the effluent)
    #     · effluent → left open (the plant's water-balance remainder — a fixed effluent pump
    #        alongside the two fixed sludge pumps leaves the system one equation short)
    #     · settleable sludge → FlowSeparator →
    #          outflow_0 → RAS pump (fixed ``Qr``) → r1
    #          outflow_1 → WAS pump (initial ``Q_was``) → open sink
    # Both sludge flows are fixed here; the MLSS control callback (built in ``build()``)
    # then drives the WAS pump's flow toward target each tick — the SRT lever that keeps the
    # biomass in the loop at the requested MLSS instead of washing it out.
    recirc: dict[str, Any] | None = None
    if clarifier is not None and p_ras is not None and p_was is not None:
        clarifier_obj = ppp.IdealClarifier(states_od, f_ns=f_ns, name="clar")
        sep = ppp.FlowSeparator(states_od, n_out=2, name="sep")

        model.connect(react_objs[-1].outflows(0), clarifier_obj.inflows(0))
        model.connect(clarifier_obj.sludge, sep.inflows(0))
        model.connect(sep.outflows(0), p_ras.inflows(0))    # RAS → r1 (already merged)
        model.connect(sep.outflows(1), p_was.inflows(0))    # WAS → open sludge sink
        # clarifier_obj.effluent is deliberately left open (free remainder).

        recirc = {
            "clarifier": clarifier_obj,
            "ras_pump": p_ras,
            "was_pump": p_was,
            "was_k_param": p_was.parameters[0],    # the ``k`` the MLSS callback rewrites
            "ras_q": q_ras,                        # fixed RAS flow (m³/d), for reporting
            "was_q0": q_was,                       # initial WAS flow (m³/d), control lever
            "mlss_target": mlss_target,            # control setpoint (mg/L)
            "total_q": float(total_q),
            "clarifier_raw": clar_raw,
        }
        warnings.append(
            f"Clarifier “{clar_name}”: ideal (f_ns={f_ns:.3f}) — no solids to the effluent. "
            f"RAS {q_ras:g} m³/d (fixed); SRT/MLSS held at ≈{mlss_target:g} mg/L by adjusting the "
            f"WAS flow (starts at {q_was:g} m³/d)."
        )

    model.end_building()
    return model, react_objs, ppp_influents, controllers, recirc


# -- Public API ------------------------------------------------------------------

def build(
    units_data: list[dict],
    edges: list[dict],
    time_days: float | None = None,
    influent_flow: float | None = None,
    influent_overrides: dict[str, float] | None = None,
) -> dict:
    """Build the PeePyPoo model and return the solved time series + metadata."""
    with _engine_lock:
        try:
            return _build_locked(units_data, edges, time_days, influent_flow, influent_overrides)
        except TimeValueError as e:
            raise SimError(str(e)) from e


def _build_locked(
    units_data: list[dict],
    edges: list[dict],
    time_days: float | None = None,
    influent_flow: float | None = None,
    influent_overrides: dict[str, float] | None = None,
) -> dict:
    t0 = time.time()

    all_units = [n for n in units_data if n.get("type") == "unit" or not n.get("type")]
    raw_by_id = {str(n["id"]): n for n in all_units}
    reactor_nodes = [
        {
            "id": str(n["id"]),
            "unitId": (n.get("data") or {}).get("unitId"),
            "name": (n.get("data") or {}).get("name") or None,
            "attrs": (n.get("data") or {}).get("attributes") or {},
        }
        for n in all_units
        if (n.get("data") or {}).get("unitId") in UNIT_REACTOR_TYPES
    ]
    influent_node_ids = [
        str(n["id"])
        for n in all_units
        if (n.get("data") or {}).get("unitId") == INFLUENT_TYPE
    ]

    if not reactor_nodes:
        raise SimError(
            "No simmable reactor units on the canvas. "
            "Add at least one CSTR, aerated CSTR, anoxic CSTR, SBR, MABR, MBR, or MBBR."
        )

    adj: dict[str, list[str]] = {r["id"]: [] for r in reactor_nodes}
    for e in edges:
        if _is_recycle(e):
            continue
        s, t = str(e.get("source")), str(e.get("target"))
        if s in adj and t in adj and s != t and t not in adj[s]:
            adj[s].append(t)

    order = _longest_simple_path([r["id"] for r in reactor_nodes], adj)
    if not order:
        raise SimError(
            "Could not find a forward source→sink path through the reactors. "
            "Draw a straight left→right train of reactors to simulate."
        )

    # Detect a clarifier on the canvas: if present, we wire the validated recirculation
    # topology (perfect clarifier + RAS pump + WAS free remainder + MLSS control) at the
    # tail of the reactor train. Otherwise recirc is not available and any recycle-labelled
    # lines on the diagram are still ignored (we warn about that).
    clarifier_node = next((n for n in all_units
                           if (n.get("data") or {}).get("unitId") == CLARIFIER_TYPE), None)
    clarifier_spec = {"node_id": str(clarifier_node["id"]), "node": clarifier_node} \
        if clarifier_node is not None else None

    warnings: list[str] = []
    used = set(order)
    for r in reactor_nodes:
        if r["id"] not in used:
            warnings.append(f"Unit {r['name'] or r['unitId']} is off the main path and not simulated.")
    if any(_is_recycle(e) for e in edges) and clarifier_spec is None:
        warnings.append(
            "Recycle / sludge lines are present but no Clarifier unit is on the canvas, "
            "so they are not modelled. Add a Clarifier next to the last reactor to enable "
            "RAS/WAS and MLSS/SRT control."
        )

    source_id = order[0]
    sink_id = order[-1]

    # ---- Resolve each Influent to the reactor it ultimately feeds ------------
    # An Influent may be wired through pass-through units (junctions, clarifiers,
    # screens, equalization tanks) before reaching a reactor. Walk the forward
    # graph from the inflow to the first reactor in `order`; a dead end (e.g. only
    # an "Effluent" outlet) means that influent is not simulated.
    node_type: dict[str, str] = {
        str(n["id"]): (n.get("data") or {}).get("unitId") or n.get("type") or ""
        for n in all_units
    }
    unit_adj: dict[str, list[str]] = {}
    for e in edges:
        if _is_recycle(e):
            continue
        s, t = str(e.get("source")), str(e.get("target"))
        if s == t:
            continue
        unit_adj.setdefault(s, [])
        if t not in unit_adj[s]:
            unit_adj[s].append(t)

    def _label_of(node_id: str) -> str:
        for r in reactor_nodes:
            if r["id"] == node_id:
                return r["name"] or r["unitId"]
        return node_type.get(node_id) or node_id

    influents_by_reactor: dict[str, list[str]] = {rid: [] for rid in order}
    for node_id in influent_node_ids:
        # BFS over the forward graph, passing through non-reactor units (junctions,
        # clarifiers, screens, …) until we hit a reactor on the main path.
        seen = {node_id}
        queue = [node_id]
        target = None
        while queue and target is None:
            cur = queue.pop(0)
            if node_type.get(cur) in UNIT_REACTOR_TYPES and cur in influents_by_reactor:
                target = cur
                break
            for t in unit_adj.get(cur, []):
                if t not in seen:
                    seen.add(t)
                    queue.append(t)
        if target is None:
            dead_end = ", ".join(_label_of(t) for t in unit_adj.get(node_id, [])) or "nothing"
            warnings.append(
                f"Influent “{_label_of(node_id)}” reaches {dead_end} but no reactor on the "
                f"simulated train — it is not modelled."
            )
            continue
        if node_id not in influents_by_reactor[target]:
            influents_by_reactor[target].append(node_id)

    # If there are no drawn Influent units and the client passed a flow, create one
    # synthetic feed attached to the first reactor.
    synthetic: dict | None = None
    if not influent_node_ids and influent_flow and influent_flow > 0:
        comp = dict(DEFAULT_INFLUENT_FALLBACK)
        if influent_overrides:
            comp.update({k: float(v) for k, v in influent_overrides.items()
                         if k in ASM1_STATES and v is not None})
        synthetic = {"flow": float(influent_flow), "composition": comp,
                     "label": "Influent (synthetic)"}

    # Parse every influent (validates expressions early) and total the flow at t=0.
    parsed_influents: dict[str, dict] = {}
    total_q = 0.0
    connected_ids: list[str] = []
    for rid in order:
        for node_id in influents_by_reactor[rid]:
            if node_id in parsed_influents:
                continue
            raw = raw_by_id.get(node_id)
            if raw is None:
                continue
            flow_tv, comp_tvs, source = _influent_spec(raw)
            parsed_influents[node_id] = {"flow": flow_tv, "composition": comp_tvs, "source": source}
            connected_ids.append(node_id)
    if synthetic is not None:
        parsed_influents["__synthetic__"] = {
            "flow": TimeValue("const", const=float(synthetic["flow"])),
            "composition": {s: TimeValue("const", const=float(synthetic["composition"][s]))
                            for s in ASM1_STATES},
            "source": "synthetic (setup panel)",
        }
        connected_ids.append("__synthetic__")
    for node_id in connected_ids:
        tv = parsed_influents[node_id]["flow"]
        total_q += _tv_value_at(tv, 0.0)
    if total_q <= 0:
        raise SimError(
            "No influent configured. Add an Influent unit to the canvas, set its "
            "flow rate, and connect it to the first reactor — "
            "or pass a flow in the Simulation window's setup panel."
        )

    # Simulation horizon.
    first_volume = (
        _parse_float((next(r for r in reactor_nodes if r["id"] == source_id)["attrs"]).get("V"))
        or DEFAULT_VOLUME_M3
    )
    t_end = time_days or min(T_MAX_DAYS, max(T_MIN_DAYS, 3.0 * first_volume / max(total_q, 1.0)))
    t_end = max(0.5, min(90.0, t_end))

    # ---- Build + solve -------------------------------------------------------
    model, react_objs, ppp_influents, controllers, recirc = _build_model(
        order, reactor_nodes, raw_by_id, influents_by_reactor, t_end, warnings, synthetic,
        clarifier=clarifier_spec, total_q=total_q,
    )

    # Controllers (see server/controllers.py) need peepypoo's index lookups to agree with
    # the system the solver actually runs. ``ODEProblem`` structurally simplifies the model
    # first; peepypoo's ``GetIndex``/``SetIndex`` resolve by name against whatever object
    # they're given — so we simplify ONCE here and drive both the index lookups and the
    # problem from that same object. The solve cost of the internal simplification is not
    # duplicated (double simplifying is a no-op).
    sysS = model.structural_simplify()
    callbacks = [
        build_controller_callback(c["spec"], sysS, c["k_param"], t_end) for c in controllers
    ]
    if recirc is not None:
        callbacks.append(_build_mlss_callback(sysS, recirc, t_end))
    if callbacks:
        prob = ppp.ODEProblem(sysS, (0.0, t_end), callback=ppp.CallbackSet(callbacks))
    else:
        prob = ppp.ODEProblem(sysS, (0.0, t_end))
    sol = prob.solve()

    t_arr = [float(x) for x in sol.t]
    n_pts = len(t_arr)

    def _clean(v: float) -> float:
        # Drop solver artifacts that are not physical: NaN/inf (solver gave up) and
        # negative concentrations (a transient from the stiff solver; the real value is 0).
        v = float(v)
        if v != v or abs(v) >= 1e300:
            return 0.0
        return v if v >= 0.0 else 0.0

    def resample(src: list[float], k: int, clean: bool = True) -> list[float]:
        n = len(src)
        if n == 0:
            return []
        if n <= k:
            return [(_clean(v) if clean else v) for v in src]
        step = (n - 1) / (k - 1)
        return [(_clean(src[int(round(i * step))]) if clean else src[int(round(i * step))]) for i in range(k)]

    # One shared time axis for the whole result. Cap the number of points for very long
    # runs so the payload stays small and the chart stays smooth; resample BOTH the axis
    # and every series to that length so the two are always index-aligned. (Previously the
    # series were fixed to 200 pts while t_days kept all of them — for a 30 d run the chart
    # therefore filled only the first ~2.5 % of its width.)
    k_series = min(n_pts, 1_000) if n_pts > 1_000 else n_pts
    t_out = [round(t, 6) for t in resample(t_arr, k=k_series, clean=False)]
    series: dict[str, dict[str, list[float]]] = {}
    eff: dict[str, list[float]] | None = None

    def _block_of(port: Any) -> dict[str, list[float]]:
        """Read every ASM1 state from an outflow port into a name→resampled-values map."""
        block: dict[str, list[float]] = {}
        for u in port.unknowns:
            name = str(u).split("(")[0].split("₊")[-1].split(".")[-1]
            if name in ("q", "k", "") or name not in ASM1_STATES:
                continue
            try:
                vals = [float(v) for v in sol[u]]
            except Exception:
                continue
            if len(vals) != n_pts:
                continue
            block[name] = resample(vals, k=k_series)
        return block

    for i, react in enumerate(react_objs, start=1):
        series[f"r{i}"] = _block_of(react.outflows(0))
        eff = series[f"r{i}"]
    if eff is not None:
        series["eff"] = eff
    # When the plant has a clarifier, the *clarified* effluent (no solids) is the true plant
    # output the user cares about — report it as ``eff``. The last reactor's outflow still
    # shows up under its rN key for comparison.
    if recirc is not None:
        series["eff"] = _block_of(recirc["clarifier"].effluent)

    # Also return the total influent flow over time so the UI can show "flows" too
    # (re-evaluates the same expressions the model used — cheap and deterministic).
    total_influent_flow: list[float] | None = None
    try:
        acc = [0.0] * n_pts
        for node_id in connected_ids:
            tv = parsed_influents[node_id]["flow"]
            if tv.kind == "const":
                base = float(tv.const or 0.0)
                for idx in range(n_pts):
                    acc[idx] += base
                continue
            fn = tv.to_function(t_end)
            for idx, t in enumerate(t_arr):
                acc[idx] += float(fn(t))
        total_influent_flow = resample(acc, k=k_series)
    except Exception:
        total_influent_flow = None

    warnings = list(dict.fromkeys(warnings))

    # ---- Setup report ---------------------------------------------------------
    influent_reports: list[dict[str, Any]] = []

    def _tv_report(tv: TimeValue, t_end: float) -> dict[str, Any]:
        # Backward-compatible scalar (value at t=0) plus a time-dependence flag. When
        # the value is time-varying we also include a small detail payload so the UI can
        # show "why" it's changing (kind, values or sine description).
        if tv.kind == "const":
            return {"value_at_0": float(tv.const or 0.0),
                    "time_dependent": False,
                    "description": f"constant {tv.const:g}"}
        detail: dict[str, Any] = {
            "value_at_0": _tv_value_at(tv, 0.0),
            "value_at_end": _tv_value_at(tv, t_end),
            "time_dependent": True,
            "description": tv.describe(),
        }
        if tv.kind == "list":
            detail["values"] = list(tv.values or [])
        if tv.kind == "sine" and tv.sine:
            s = tv.sine
            detail["sine"] = {"offset": s.get("offset", 0.0), "amp": s.get("amp", 0.0),
                              "omega": s.get("omega", 0.0), "phase": s.get("phase", 0.0)}
        return detail

    def _comp_report(parsed: dict) -> tuple[dict[str, float], list[str], dict[str, dict[str, Any]]]:
        """(composition values at t=0, list of time-varying states, per-state detail dicts)."""
        comp: dict[str, float] = {}
        tv_fields: list[str] = []
        tv_detail: dict[str, dict[str, Any]] = {}
        for s in ASM1_STATES:
            v = parsed["composition"][s]
            comp[s] = _tv_value_at(v, 0.0)
            if v.kind != "const":
                tv_fields.append(s)
                tv_detail[s] = _tv_report(v, t_end)
        return comp, tv_fields, tv_detail

    def add_report(i: int, uid: str, meta: dict, parsed: dict) -> None:
        react_ref = next(r for r in reactor_nodes if r["id"] == uid)
        into_label = react_ref["name"] or f"Reactor {i} ({react_ref['unitId']})"
        comp, comp_tv, comp_tv_detail = _comp_report(parsed)
        flow_tv = meta["flow"]
        report: dict[str, Any] = {
            "label": meta["label"],
            "into_reactor": into_label,
            "into_reactor_index": i,
            "into_reactor_id": uid,
            "flow_m3_per_d": _tv_value_at(meta["flow"], 0.0),
            "composition": comp,
            "composition_source": parsed["source"],
            "synthetic": bool(meta["synthetic"]),
            # NEW: which fields (flow / some states) are time-dependent, plus details.
            "time_varying": (["flow"] if flow_tv.kind != "const" else []) + comp_tv,
            "time_varying_detail": (
                ({"flow": _tv_report(flow_tv, t_end)} if flow_tv.kind != "const" else {})
                | comp_tv_detail
            ),
        }
        influent_reports.append(report)

    for i, uid in enumerate(order, start=1):
        for node_id in influents_by_reactor[uid]:
            meta = ppp_influents.get(node_id)
            parsed = parsed_influents.get(node_id)
            if meta is None or parsed is None:
                continue
            add_report(i, uid, meta, parsed)
        if i == 1 and "__synthetic__" in ppp_influents:
            add_report(1, order[0], ppp_influents["__synthetic__"], parsed_influents["__synthetic__"])

    sink_ref = next(r for r in reactor_nodes if r["id"] == sink_id)
    sink_label = sink_ref["name"] or f"Reactor {order.index(sink_id)+1} ({sink_ref['unitId']})"

    reactor_report = []
    ctrl_by_label = {c["name"]: c for c in controllers}
    for i, uid in enumerate(order, start=1):
        r = next(x for x in reactor_nodes if x["id"] == uid)
        attrs = r["attrs"]
        volume = _parse_float(attrs.get("V")) or DEFAULT_VOLUME_M3
        aerated = r["unitId"] in AERATED_TYPES
        if r["unitId"] in NON_AERATED_TYPES:
            aerated = False
        kLa_report = None
        if r.get("kLaKind") is not None:
            kLa_report = _tv_report(r["kLaKind"], t_end)
        controller = ctrl_by_label.get(r.get("label"))
        reactor_report.append({
            "index": i,
            "label": r["name"] or f"Reactor {i} ({r['unitId']})",
            "unitId": r["unitId"],
            "aeration": bool(aerated),
            "kLa": (float(r["kLaKind"].const) if r.get("kLaKind") is not None
                    and r["kLaKind"].kind == "const" else None),
            "kLa_report": kLa_report,
            "controller": (summarize_controller(controller["spec"])
                           if controller is not None else None),
            "volume_m3": volume,
            "temperature_c": REACTOR_TEMPERATURE_C,
        })

    return {
        "t_days": t_out,
        "states": list(ASM1_STATES),
        "series": series,
        "reactors": reactor_report,
        "warnings": warnings,
        "t_end_days": t_end,
        "elapsed_s": round(time.time() - t0, 2),
        "total_influent_flow": total_influent_flow,
        "setup": {
            "influents": influent_reports,
            "total_flow_m3_per_d": total_q,
            # `from_reactor` is the last reactor of the simulated train — the effluent
            # *originates* there. When a clarifier is on the canvas the effluent leaves
            # through it instead, which the `clarifier` block below records.
            "effluent": {
                "from_reactor": sink_label,
                "from_reactor_id": sink_id,
            },
            # Only present when a clarifier unit is on the canvas. The MLSS / SRT control
            # info lets the UI show "the plant is held at ~x mg/L MLSS".
            "clarifier": (
                {
                    "name": (recirc["clarifier_raw"].get("data") or {}).get("name")
                    or "Clarifier",
                    "f_ns": _parse_float(((recirc["clarifier_raw"].get("data") or {})
                                   .get("attributes") or {}).get("f_ns")) or 0.0,
                    "target_mlss_mgl": float(recirc["mlss_target"]),
                    "ras_m3_per_d": float(recirc["ras_q"]),
                    "initial_was_m3_per_d": float(recirc["was_q0"]),
                    "control_note": (
                        "Perfect clarifier: no solids to the effluent. RAS is fixed "
                        f"({recirc['ras_q']:g} m³/d); the waste sludge (WAS) is tuned "
                        "each tick to hold the MLSS near the target — that is the SRT "
                        "lever in this plant."
                    ),
                }
                if recirc is not None else None
            ),
        },
    }
