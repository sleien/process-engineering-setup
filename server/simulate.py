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

* The plant is a **DAG, not a single chain**. ``server/topology.py`` resolves the drawing
  into a topologically ordered plan of reactor-type units (CSTR, aerated CSTR, anoxic
  CSTR, SBR, trickling filter, MBR, MBBR, **MABR**, switchable), with every inlet, outlet
  and branch flow spelled out. This build then walks that plan once:

    - a reactor with several inlets gets a ``FlowUnifier`` (two parallel streets merging,
      an influent plus the RAS return, a bypass rejoining);
    - a reactor feeding several units gets a ``FlowSeparator`` with a ``FlowPump`` on every
      branch but the largest (PeePyPoo closes the last branch by mass balance);
    - pass-through units drawn in between (screens, equalisation basins, junctions) are
      walked across — they route flow but carry no model of their own.

* An **SBR** unit carries a cycle (fill / react / settle / decant, with an optional
  stagger ``offset``). The reactor is fed continuously — which is what a staggered bank of
  SBRs does in practice — and its **aeration follows the cycle clock**, on through react
  and off otherwise. The tank volume is constant: PeePyPoo's CSTR has no variable-volume
  mode, so fill-and-draw level swings are *not* modelled.

* A unit may carry a **bypass**: a controlled branch that splits off before it and rejoins
  after it, with the diverted flow set by a measured ratio (COD/N) or state. That is the
  "protect nitrification from a COD surge" lever.

* **Aerated** units (aerated_CSTR, switch_CSTR, MBR, MBBR, MABR) add an ``Aeration``
  process; ``aerated_CSTR_off`` is non-aerated. A **trickling filter** is aerated too,
  but by natural draft rather than a blower: it gets the same ``Aeration`` process with
  its own, lower default ``kLa`` (see ``DEFAULT_NATURAL_DRAFT_KLA_PER_D``).

* Units that **keep their own biomass** are built accordingly, because a flow-through CSTR
  at their residence time would wash the nitrifiers out within a day:

    - each is a CSTR followed by an internal ideal clarifier whose sludge returns to the
      same tank, with the waste sized to hold the unit's own ``SRT`` — for an SBR or MBR
      that is what the unit does; for a trickling filter, MBBR or MABR it stands in for
      the fixed film (see ``SELF_RETAINING_TYPES`` for why not a fixed state).

* **Effluent** is the outflow of the terminal reactor, through an ``IdealClarifier`` (its
  ``f_ns`` is the clarifier's non-settleable fraction) when the diagram carries a
  ``clarifier`` unit. The settled sludge is split by a ``FlowSeparator`` into a **RAS**
  return (pumped back to the head of the street that feeds the clarifier, flow from its
  ``Qr`` field) and a **WAS** waste.

  The clarifier itself holds no solids, so the RAS loop retains them, and the WAS flow sets
  the sludge age: it is sized from the loop volume, flows and ``f_ns`` to hold the
  clarifier's ``SRT`` (see ``_waste_for_srt``), or taken from ``Q_was`` when no SRT is
  given. That is what prevents washout — the reactor train runs at a known SRT.

* Reactor temperature is the plant-wide static ``Process`` temperature (fixed at 20 °C).
  Thetis can make it a parameter or a state (``temperature_variability``); this adapter
  does not use that yet.

* **pH** is not an ASM1 state. It is estimated from the alkalinity S_ALK and each tank's
  dissolved CO2 (``controllers.ph_from_alkalinity``), reported as a ``pH`` series per tank,
  and can be measured by a controller.
"""

from __future__ import annotations

import bisect
import math
import threading
import time
from typing import Any

import peepypoo as ppp

from .controllers import (
    DEFAULT_CO2_MMOL_L,
    TARGETS as CONTROL_TARGETS,
    TSS_PER_COD,
    alkalinity_for_ph,
    ph_from_alkalinity,
    ControllerSpec,
    build_bypass_callback,
    build_controller_callback,
    build_cycle_callback,
    chatter_warning,
    describe_bypass,
    describe_cycle,
    forget_index,
    parse_controllers,
    summarize as summarize_controller,
)
from .timeseries import TimeValue, TimeValueError, parse_time_value
from .topology import SETTLER_TYPES, Plan, TopologyError, plan_streets, resolve


class SimError(Exception):
    """Raised when the diagram cannot be translated into a runnable model."""


# Guards the (not thread-safe) Julia bridge so concurrent requests don't interleave.
_engine_lock = threading.Lock()


AERATED_TYPES = {"aerated_CSTR", "switch_CSTR", "MBR", "MBBR", "MABR", "trickling_filter"}
NON_AERATED_TYPES = {"aerated_CSTR_off"}

# A trickling filter has no blower: air moves up or down through the media by natural
# draft, driven by the temperature difference between the air in the filter and outside.
# A well-ventilated filter is not oxygen-limited — Sumo's model of the reference plant
# holds its filters' bulk liquid at ~4 mg/L DO and nitrifies them down to ~0.02 mg/L
# ammonia. Without an Aeration process the tank that stands in for the filter here sat at
# zero oxygen, so it could not nitrify at all and its heterotrophs only grew anoxically on
# whatever nitrate came in.
#
# kLa = 0 is not "natural draft", it is "sealed". The default is calibrated on the reference
# plant's municipal filter (3500 m³, 6928 m³/d, 2500 g/m³ film, SRT 25 d), run alone for
# 30 d at constant load:
#
#     kLa 1/d    tank DO   effluent NH4
#       0         0.00       27.1        (no nitrification — the old behaviour)
#      60         0.07       25.1
#     120         0.79        0.56
#     240         3.99        0.35       ← Sumo's filter bulk: 4.06 mg/L DO, 0.02 NH4
#
# The more lightly N-loaded industrial filter sits at 6.2 mg/L with the same kLa. A unit's
# own ``kLa`` attribute overrides the default (forced ventilation, or a poorly ventilated
# filter).
NATURAL_DRAFT_TYPES = {"trickling_filter"}
DEFAULT_NATURAL_DRAFT_KLA_PER_D = 240.0

# Units that keep their biomass instead of letting the flow carry it away: an SBR settles
# and decants inside the tank, a membrane bioreactor filters, and a moving-bed, membrane-
# aerated or trickling filter grows its biomass on media. Each is modelled as a CSTR
# followed by an *internal* ideal clarifier whose sludge returns to the same tank, with the
# waste flow set so the unit runs at its own SRT (see ``_waste_for_srt``).
#
# This matters more than it looks: as a plain flow-through CSTR these units have a
# hydraulic residence time of well under a day, far below the ~4 d an autotroph population
# needs, so without the retention the nitrifiers wash out inside the first simulated day
# and the effluent ammonia is simply the influent ammonia.
#
# A cheaper-looking alternative — holding the active biomass as a *fixed state*
# (``CSTR(fixed_states=…)``), which is closer to what a fixed film is and costs no
# algebraic loop — does not work here, and the reason is worth recording. A fixed state
# still leaves with the outflow at its fixed concentration, so the unit becomes a *source*
# of solids: a filter held at 2000 mg/L on 6900 m³/d exports fourteen tonnes of biomass a
# day into whatever is downstream, whose own MLSS controller then saturates against its
# waste limit. The retention loop conserves mass; the fixed state does not.
SELF_RETAINING_TYPES = {"sbr", "MBR", "MBBR", "MABR", "trickling_filter"}
DEFAULT_SELF_RETAIN_SRT_D = 15.0   # SRT (d) when the unit has no SRT attribute
DEFAULT_SELF_RETAIN_FNS = 0.0      # non-settleable fraction of the internal separation

# A primary or intermediate clarifier (``topology.SETTLER_TYPES``) is an ideal settler whose
# sludge goes to waste. The user states what it does the way a designer does — the share
# of the incoming suspended solids it removes, and the sludge flow drawn off the bottom —
# and the build turns that into the IdealClarifier's non-settleable fraction (see
# ``_settler_fns``). A primary clarifier typically removes 50–70 % of TSS and draws off
# well under 1 % of the flow as sludge.
DEFAULT_SETTLER_REMOVAL = 0.5
DEFAULT_SETTLER_UNDERFLOW_SHARE = 0.01

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
# fields. The magnitudes are for a mid-size activated-sludge plant.
DEFAULT_RAS_FLOW_M3D = 2000.0     # Qr — a mid-size RAS multiple of effluent
DEFAULT_SRT_D = 15.0              # sludge age when neither SRT nor Q_was is given
DEFAULT_MLSS_TARGET_MGL = 3000.0  # the seed MLSS when a unit gives none

# Below this sludge age the nitrifiers cannot outgrow their own washout. At 20 °C the
# autotroph net growth rate is ~0.5 /d at best (mu_A 0.8 minus decay, times the ammonium
# and oxygen switches), so the hard floor is ~2 d and anything under ~4 d nitrifies only
# partially and fragilely. A unit aerated part of the time — an SBR in its react phase —
# needs proportionally more.
NITRIFICATION_MIN_SRT_D = 4.0
MIN_WASTE_FLOW_M3D = 0.5          # a pump at zero flow leaves the split underdetermined
# The least a controller may set a pump to — "0" in a rule means this. A clarifier whose
# sludge pumps all stop has a sludge concentration of mass over zero flow.
MIN_PUMP_FLOW_M3D = MIN_WASTE_FLOW_M3D

# Output grid. The solver takes whatever steps it needs; these only control what is kept.
SAVE_POINTS_DEFAULT = 1000     # points across the run when nothing finer is needed
SAVE_POINTS_PER_CYCLE = 12     # samples per SBR cycle, so the cycle is visible in the chart
SAVE_POINTS_MAX = 4000         # hard cap on what one run returns

# When the caller does not set a horizon, cover a few sludge ages so the biology has
# settled rather than showing a start-up transient. Capped so a long-SRT biofilm unit
# does not silently turn a quick look into a multi-month run.
SRT_HORIZON_MULTIPLE = 3.0
SRT_HORIZON_MAX_DAYS = 30.0

# How short the solved window may fall of the requested one before the run counts as
# failed. The solver lands on the last saveat point, so a hair of slack is normal.
SOLVE_COVERAGE_TOLERANCE = 0.001

# Below this the callback itself becomes the bottleneck; the solver stops on every tick.
_CONTROL_PERIOD_FLOOR = 1.0 / 2880.0     # 30 seconds of simulated time

# -- Keeping concentrations non-negative ------------------------------------------------
#
# Every unknown the solver integrates is an ASM1 concentration, and none of them can be
# negative. Left to itself the solver does not know that, and it matters more than it
# sounds: when aeration switches off in a tank full of biomass, dissolved oxygen falls from
# ~2.5 mg/L to zero in seconds (heterotroph uptake runs at hundreds of mg/L/h), and a stiff
# solver overshoots below zero. Below -K_OH the Monod switch S_O/(K_OH + S_O) turns
# *positive* again, so uptake carries on with no oxygen and S_O runs away — the parallel
# SBR demo reached -142 mg/L while the solver still reported Success. The same runaway
# turned the ammonium switch on with no oxygen: after 3 days the SBR held 63.6 mg/L of
# nitrate from a feed carrying ~49 mg/L of nitrogen in total.
#
# ``isoutofdomain`` makes the solver reject any step that takes a state below the
# tolerance and retry it smaller. On that demo it also made the solve 3x faster (6.7 s
# against 22.2 s), because the solver stopped chasing the runaway branch.
DOMAIN_NEGATIVE_TOLERANCE = 1e-3   # mg/L — rejects the step; well inside the -K_OH runaway
NEGATIVE_RESULT_LIMIT = 0.05       # mg/L — a reported value below -this fails the run
_OUT_OF_DOMAIN: Any = None


def _out_of_domain() -> Any:
    """The Julia ``isoutofdomain`` predicate: true when any state is below the tolerance.

    Built once through juliacall's public ``Main`` module rather than PeePyPoo's private
    Julia module, so it does not depend on PeePyPoo internals. It runs inside the solver's
    step loop, so it has to be a Julia function — a Python callback there would cross the
    language boundary on every step.
    """
    global _OUT_OF_DOMAIN
    if _OUT_OF_DOMAIN is None:
        import juliacall
        _OUT_OF_DOMAIN = juliacall.Main.seval(
            f"(u, p, t) -> any(x -> x < -{DOMAIN_NEGATIVE_TOLERANCE!r}, u)")
    return _OUT_OF_DOMAIN



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


def _initial_states(mlss: float | None = None, s_alk: float | None = None) -> dict[str, float]:
    """Seed the CSTRs with a realistic mixed-liquor state so ASM1 starts away from the
    singular zero-biomass point (with biodegradable substrate present the solver aborts
    on the first step). The seed still converges to the true steady state.

    ``mlss`` (g TSS/m³) — when a reactor carries an MLSS attribute it is used to size the
    seed: the particulate COD that makes up that much suspended solids is split into a
    plausible heterotroph-dominant mix, instead of the ~2500 g/m³ default.

    The seed used to put MLSS straight into particulate COD, so a tank entered at 3500
    g/m³ started at 2580 g TSS/m³ — out of step with the MLSS a controller measures
    (``controllers.measure_reader``), which converts with the same 0.75 g TSS/g COD.

    ``s_alk`` (mol/m³ = mmol/L) seeds the alkalinity — a tank given a starting pH passes
    the alkalinity that pH means. The default, 5 mmol/L, is a typical mixed liquor. (It
    used to be 5200, which in ASM1's unit is 5.2 mol/L; harmless while nothing read the
    alkalinity, but a pH estimate from it starts at 10.)
    """
    mlss = float(mlss) if (mlss is not None and mlss > 0) else 2500.0
    split = {"X_I": 0.06, "X_S": 0.02, "X_BH": 0.86, "X_BA": 0.022, "X_P": 0.02}
    cod = mlss / TSS_PER_COD / sum(split.values())
    return {
        "S_I": 5.0, "S_S": 50.0,
        "X_I": split["X_I"] * cod,      # inert particulate
        "X_S": split["X_S"] * cod,      # slowly biodegradable (particulate)
        "X_BH": split["X_BH"] * cod,    # active heterotrophs dominate MLSS
        "X_BA": split["X_BA"] * cod,    # active autotrophs
        "X_P": split["X_P"] * cod,      # particulate products
        "S_O": 0.5,
        "S_NO": 0.0, "S_NH": 12.0, "S_ND": 3.0,
        "X_ND": 0.01 * cod,             # particulate biodegradable N
        "S_ALK": 5.0 if s_alk is None else float(s_alk), "S_N2": 0.0,
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


# A sampled profile is handed to the backend as (values, times) and interpolated there, so
# its length costs payload rather than build time. The cap is only here to keep a pasted
# array from becoming a megabyte of JSON.
MAX_PROFILE_POINTS = 2000

_TWO_PI = 2.0 * math.pi


def _as_ppp_source(tv: TimeValue, t_end: float, name_hint: str) -> Any:
    """TimeValue → whatever PeePyPoo should drive this signal with.

    ``Influent`` accepts a constant, a *System* with an output port, a ``(data, times)``
    pair it interpolates, or a plain Python function. The last of those is the expensive
    one: PeePyPoo calls it with a **symbolic** time at build time, so whatever the function
    does is expanded into the model's equations. ``server/timeseries.py`` therefore
    implements ``sin`` as a Taylor series over pure arithmetic — correct, and symbolically
    enormous. Measured on a one-reactor plant, a diurnal influent written that way costs
    ~28 s to simplify and ~26 s to solve, against ~1.5 s and ~2 s for the two forms below.

    So: a sinusoid becomes a native ``Sine`` block, and a sampled profile becomes a
    ``(values, times)`` pair. The Python-function path survives only as a fallback for a
    shape that is neither.
    """
    if tv.kind == "const":
        return float(tv.const or 0.0)

    if tv.kind == "sine" and tv.sine:
        s = tv.sine
        omega = float(s.get("omega") or 0.0)
        return ppp.Sine(
            name=name_hint,
            frequency=omega / _TWO_PI,          # the block takes Hz, we carry rad/day
            amplitude=float(s.get("amp") or 0.0),
            phase=float(s.get("phase") or 0.0),
            offset=float(s.get("offset") or 0.0),
        )

    if tv.kind == "list" and tv.values:
        values = [float(v) for v in tv.values]
        if len(values) > MAX_PROFILE_POINTS:
            raise SimError(
                f"The profile for '{name_hint}' has {len(values)} points; at most "
                f"{MAX_PROFILE_POINTS} are supported."
            )
        if len(values) == 1:
            return values[0]
        # Profile semantics: the first value at t=0, the last at t_end, evenly spaced.
        span = max(float(t_end), 1e-9)
        times = [span * i / (len(values) - 1) for i in range(len(values))]
        return (values, times)

    fn = tv.to_function(t_end)
    try:
        v0 = float(fn(0.0))
    except Exception as e:
        raise SimError(f"Time expression for '{name_hint}' could not be evaluated: {e!r}")
    if not math.isfinite(v0):
        raise SimError(f"Time expression for '{name_hint}' is not finite at t=0.")
    return ppp.TimeVaryingFunction(fn, name=name_hint)


# -- Build the model -------------------------------------------------------------


# -- Sludge age --------------------------------------------------------------------
#
# Every retention loop — a plant clarifier with its RAS, or the internal separation of an
# SBR, MBR or biofilm unit — is run at a *sludge age*, and the waste flow is whatever
# delivers it. This replaced holding a target MLSS by adjusting the waste each tick, for
# a reason that only showed when nitrification was checked:
#
#   * MLSS is the wrong thing to hold. Holding solids at a setpoint lets the sludge age go
#     wherever the load sends it, and a plant that produces more sludge than its tank holds
#     at that setpoint is driven to a short SRT — short enough to wash the nitrifiers out
#     while the heterotrophs, which grow ten times faster, carry on. On the original
#     anoxic/aerated/clarifier example the MLSS controller (with its 520 m3/d starting
#     waste) ran the plant at an SRT of 0.93 d: the autotrophs washed out completely, no
#     nitrate was ever formed, and effluent ammonia sat at 14–21 mg/L. With the waste set
#     for SRT = 15 d the aerated tank came down to 5–7 mg/L.
#   * The waste is drawn from the clarifier *underflow*, which is thickened. Sizing it as
#     V / SRT (wasting mixed liquor) roughly halves the sludge age actually run.
#
# So the waste is computed from the target SRT, the loop volume, the forward flow, the
# RAS flow and the clarifier's non-settleable fraction, with the thickening accounted for.
# It is a constant at nominal flow — no callback, no per-tick re-initialisation — and MLSS
# lands where the load puts it, which is how SRT-controlled plants actually run.


def _srt_for_waste(volume: float, q: float, q_ras: float, f_ns: float, q_was: float) -> float:
    """Sludge age (d) a retention loop runs at for a given waste flow — the inverse of
    ``_waste_for_srt``, for when the user fixed the waste and the SRT is the consequence."""
    q = max(1e-6, float(q))
    q_ras = max(0.0, float(q_ras))
    f = max(0.0, min(1.0, float(f_ns)))
    q_w = max(0.0, float(q_was))
    x_s = ((q + q_ras) - f * (q - q_w)) / max(1e-9, q_ras + q_w)   # underflow / tank
    out = q_w * x_s + (q - q_w) * f
    return float(volume) / out if out > 0 else float("inf")


def _waste_for_srt(
    volume: float, q: float, q_ras: float, f_ns: float, srt: float,
) -> tuple[float, float, str | None]:
    """Waste flow (m3/d) that holds a retention loop at ``srt`` days.

    Returns ``(q_was, achieved_srt, note)``; ``note`` explains when the target cannot be
    met. Derivation, for an ideal clarifier whose effluent carries ``f_ns`` of the inflow
    particulate concentration (``Thetis.IdealClarifier``)::

        solids out = Q_w * X_s + (Q - Q_w) * f_ns * X
        X_s        = X * ((Q + Q_r) - f_ns * (Q - Q_w)) / (Q_r + Q_w)    # clarifier balance
        SRT        = V * X / solids out

        => Q_w = Q_r * (V/SRT - f_ns*Q) / (Q + Q_r*(1 - f_ns) - V/SRT)

    Two limits fall out of it. If ``f_ns*Q >= V/SRT`` the effluent alone removes more
    solids than the target allows — the loop cannot reach that SRT however little it
    wastes, and the best it can do is ``V / (f_ns*Q)``. And the target has to exceed the
    loop's own hydraulic residence time, or no positive waste exists.
    """
    volume = max(1e-6, float(volume))
    q = max(1e-6, float(q))
    q_ras = max(0.0, float(q_ras))
    f = max(0.0, min(1.0, float(f_ns)))
    srt = max(1e-3, float(srt))

    demand = volume / srt                     # solids removal the target asks for, per X
    effluent_loss = f * q                     # what the effluent removes on its own
    denom = q + q_ras * (1.0 - f) - demand

    def srt_for(q_w: float) -> float:
        return _srt_for_waste(volume, q, q_ras, f, q_w)

    if effluent_loss >= demand:
        q_w = MIN_WASTE_FLOW_M3D
        return q_w, srt_for(q_w), (
            f"the effluent alone carries more solids out ({effluent_loss:.1f} m3/d of "
            f"mixed-liquor equivalent at f_ns={f:g}) than an SRT of {srt:g} d allows "
            f"({demand:.1f}). Wasting is at its minimum and the loop runs at "
            f"{srt_for(q_w):.1f} d instead. A longer SRT needs more volume or a better "
            "settling separation (lower f_ns)."
        )
    if denom <= 0:
        q_w = MIN_WASTE_FLOW_M3D
        return q_w, srt_for(q_w), (
            f"an SRT of {srt:g} d is shorter than the loop's hydraulic residence time; "
            f"wasting is at its minimum and the loop runs at {srt_for(q_w):.1f} d."
        )
    q_w = max(MIN_WASTE_FLOW_M3D, q_ras * (demand - effluent_loss) / denom)
    return q_w, srt_for(q_w), None


# Particulate COD (g/m3) above which a tank is carrying more solids than any real
# suspended-growth reactor runs at — roughly 11 g/L as TSS. Reaching it means the tank is
# too small for its load at the sludge age asked for.
IMPLAUSIBLE_SOLIDS_COD = 15000.0
_PARTICULATES = ("X_I", "X_S", "X_BH", "X_BA", "X_P")


def _diagnose_abort(plan: Plan, react_objs: dict[str, Any], sol: Any) -> str | None:
    """Say what the reactors looked like where the solver gave up, if anything stands out.

    The partial solution up to the abort is still there, and it usually names the cause
    better than a list of generic ones: a tank whose solids had climbed past anything a
    real reactor carries, a continuously aerated tank that had run out of oxygen, or a
    state that had already diverged.
    """
    findings: list[str] = []
    for rp in plan.reactors:
        react = react_objs.get(rp.id)
        if react is None or rp.unit_id in SETTLER_TYPES:
            continue
        last: dict[str, float] = {}
        try:
            for u in react.outflows(0).unknowns:
                name = str(u).split("(")[0].split("₊")[-1].split(".")[-1]
                if name in ASM1_STATES:
                    vals = sol[u]
                    if len(vals):
                        last[name] = float(vals[-1])
        except Exception:
            continue
        if not last:
            continue
        bad = [s for s, v in last.items() if v != v or abs(v) > 1e6 or v < -1.0]
        if bad:
            findings.append(f"{rp.label} had already diverged ({', '.join(bad)} at "
                            f"{', '.join(f'{last[s]:.3g}' for s in bad)})")
            continue
        solids = sum(max(0.0, last.get(s, 0.0)) for s in _PARTICULATES)
        if solids > IMPLAUSIBLE_SOLIDS_COD:
            volume = _parse_float(rp.attrs.get("V"))
            vol_note = (f"{volume:g} m³" if volume else
                        f"no volume given, so the {DEFAULT_VOLUME_M3:g} m³ default")
            findings.append(
                f"{rp.label} had accumulated solids of ~{0.75 * solids / 1000:.0f} g/L "
                f"(as TSS) — far beyond what a tank can carry; at its sludge age it is too "
                f"small for its load ({vol_note}). Give it more volume or a shorter SRT"
            )
        continuously_aerated = (rp.unit_id in AERATED_TYPES and rp.cycle is None
                                and rp.unit_id not in NON_AERATED_TYPES)
        if continuously_aerated and last.get("S_O", 1.0) < 0.05:
            findings.append(f"{rp.label} had run out of oxygen (S_O "
                            f"{last.get('S_O', 0.0):.3f} mg/L) — its kLa is too low for "
                            "its load")
    if not findings:
        return None
    return "Where it stopped: " + "; ".join(findings) + "."


def _retention_report(ret: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe description of one unit's internal retention loop, for the setup report."""
    text = (
        f"keeps its own solids: internal clarifier returns {ret['ras_q']:.0f} m³/d, "
        f"wastes {ret['was_q']:.1f} m³/d, giving an SRT of {ret['srt_d']:.1f} d"
    )
    if ret.get("srt_note"):
        text += f" (target {ret['srt_target_d']:g} d not reachable)"
    return {
        "internal_return_m3_per_d": round(ret["ras_q"], 1),
        "waste_m3_per_d": round(ret["was_q"], 2),
        "srt_d": round(ret["srt_d"], 2),
        "srt_target_d": ret["srt_target_d"],
        "f_ns": float(ret["f_ns"]),
        "as_text": text,
    }


def _settler_report(st: dict[str, Any]) -> dict[str, Any]:
    """The report block of a primary / intermediate clarifier."""
    return {
        "removal": round(st["removal"], 3),
        "underflow_m3_per_d": round(st["underflow_m3_per_d"], 1),
        "f_ns": round(st["f_ns"], 4),
        "as_text": (f"removes {st['removal']:.0%} of incoming solids, "
                    f"{st['underflow_m3_per_d']:g} m³/d sludge to waste"),
    }


def _srt_warning(label: str, srt: float, aerated_fraction: float = 1.0) -> str | None:
    """A warning when a loop's sludge age is too short to keep its nitrifiers."""
    need = NITRIFICATION_MIN_SRT_D / max(0.05, min(1.0, aerated_fraction))
    if srt >= need:
        return None
    part = (f" (aerated {aerated_fraction:.0%} of the time, so it needs ~{need:.0f} d)"
            if aerated_fraction < 0.999 else "")
    return (
        f"{label} runs at an SRT of {srt:.1f} d{part} — too short to keep nitrifiers. "
        "Expect effluent ammonia close to the influent value. Set a longer SRT."
    )


# A controller that ticks slower than its tank turns over is not merely sloppy tuning —
# it makes the model unsolvable. Between two ticks the tank runs open loop, and if that
# gap spans more than a residence time the controlled state swings across its whole range
# (dissolved oxygen from zero to saturation and back) before the controller ever looks.
# The stiff solver then chases a square wave through a fast tank and drives its step size
# to floating-point resolution.
#
# Measured on the Sumo example: a 250 m3 polishing tank at 8588 m3/d (42 min residence
# time) with a 0.05 d (72 min) controller aborts at t = 2 d with retcode Unstable.
# Shortening the period to 0.005 d solves the full 21 d in 242 s; enlarging the tank to
# 2000 m3 and leaving the period alone also solves it, in 189 s. Either way the fix is to
# put the control timescale below the hydraulic one.
#
# So the period is clamped rather than left to fail, because the alternative is a run that
# dies two days in with a message about floating-point epsilon.
CONTROL_PERIODS_PER_HRT = 4.0     # ticks per residence time the controller must manage


def _clamp_controller_period(spec: ControllerSpec, tanks: list[Any]) -> str | None:
    """Hold a controller's period below the residence time of the tanks it involves.

    Those are the tanks it measures in, plus the tank it aerates for a kLa controller. A
    controller that ticks slower than such a tank empties runs open loop across more than a
    residence time, and the solve then very likely fails (see the constant's note).
    """
    hrts = []
    for rp in tanks:
        volume = _parse_float(rp.attrs.get("V")) or DEFAULT_VOLUME_M3
        hrts.append((volume / max(1.0, float(rp.throughput)), rp.label))
    if not hrts:
        return None
    hrt, label = min(hrts)
    if hrt <= 0:
        return None
    limit = hrt / CONTROL_PERIODS_PER_HRT
    if spec.period <= limit:
        return None
    was = spec.period
    spec.period = max(_CONTROL_PERIOD_FLOOR, limit)
    return (
        f"the period was {was:g} d but {label} empties every {hrt:g} d "
        f"({hrt * 24 * 60:.0f} min), so the controller would have run open loop across "
        f"more than a residence time and the solve would very likely fail. Shortened to "
        f"{spec.period:g} d. Give the tank more volume, or set a period under "
        f"{limit:g} d yourself, to keep control of this."
    )


def _flow_controller_supply(node: dict, flow_tv: TimeValue, t_end: float) -> float | None:
    """The most a controlled influent can be asked for, or None when it has no controller.

    That is the largest flow any of its rules sets, or its own flow field at its highest
    over the run. Malformed controllers return None here and are reported by the wiring.
    """
    try:
        parsed = [pc for pc in parse_controllers(node.get("data") or {}) if pc.target == "Q"]
    except ValueError:
        return None
    if not parsed:
        return None
    field = max(float(flow_tv.value_at(t_end * i / 200.0, t_end)) for i in range(201))
    return max([field] + [r.set for r in parsed[0].rules] + [MIN_PUMP_FLOW_M3D])


def _control_series(c: dict[str, Any], t_end: float) -> dict[str, Any]:
    """One controller's logged settings as a step series that ends at ``t_end``."""
    spec: ControllerSpec = c["spec"]
    ts: list[float] = []
    vs: list[float] = []
    for t, v in sorted(c["log"]):
        if vs:
            ts.append(round(t, 6))
            vs.append(vs[-1])
        ts.append(round(t, 6))
        vs.append(round(v, 6))
    if vs:
        ts.append(round(t_end, 6))
        vs.append(vs[-1])
    return {
        "on": spec.owner_label,
        "target": spec.target,
        "label": f"{spec.owner_label} — {spec.target_text}",
        "unit": spec.unit,
        "changes": len(c["log"]),
        "t_days": ts,
        "values": vs,
    }


def _const(value: float) -> TimeValue:
    return TimeValue("const", const=float(value))


def _wire_controllers(
    plan: Plan,
    actuators: dict[tuple[str, str], dict[str, Any]],
    clarifier_label: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Match every controller drawn on the canvas to the setting it changes.

    A controller sits on the unit whose setting it changes and may measure in any tank:
    its rules name that tank by node id. The clarifier is not a node of the plan, so it is
    added as an owner here; it has pumps to set but no mixed liquor to measure.
    """
    owners: list[tuple[str, str, str, Any, dict]] = [
        (rp.id, rp.label, rp.model, rp, rp.raw.get("data") or {}) for rp in plan.reactors
    ]
    for node_id, info in plan.influents.items():
        data = (info.get("node") or {}).get("data") or {}
        owners.append((node_id, data.get("name") or "Influent", "", None, data))
    if plan.clarifier is not None:
        node = plan.clarifier.get("node") or {}
        owners.append((str(plan.clarifier["node_id"]), clarifier_label, "", None,
                       node.get("data") or {}))

    wired: list[dict[str, Any]] = []
    for owner_id, owner_label, owner_model, owner_rp, data in owners:
        try:
            parsed = parse_controllers(data)
        except ValueError as e:
            raise SimError(f"Controller on {owner_label}: {e}") from e
        for pc in parsed:
            target, period, rules = pc.target, pc.period, pc.rules
            act = actuators.get((owner_id, target))
            what = CONTROL_TARGETS[target][0]
            if act is None:
                offered = [CONTROL_TARGETS[t][0] for (nid, t) in actuators if nid == owner_id]
                raise SimError(
                    f"Controller on {owner_label} sets the {what}, which this unit does not "
                    "have in the model" + (f" — it offers: {', '.join(offered)}."
                                           if offered else
                                           ", and nothing else a controller could set.")
                )
            tanks: dict[str, Any] = {}
            if target == "kLa" and owner_rp is not None:
                tanks[owner_rp.id] = owner_rp
            for i, r in enumerate(rules, start=1):
                if r.set > act["hi"]:
                    raise SimError(
                        f"Controller on {owner_label}, rule {i}: sets the {what} to "
                        f"{r.set:g}, more than the {act['hi']:g} the model allows there "
                        "(the pump cannot draw more than reaches it)."
                    )
                if r.when == "t":
                    continue
                at = r.at or (owner_id if owner_rp is not None else "")
                tank = plan.by_id(at) if at else None
                if tank is None:
                    raise SimError(
                        f"Controller on {owner_label}, rule {i}: "
                        + ("choose the tank it measures in." if not r.at else
                           f"it measures in a unit that is no longer on the canvas "
                           f"(id {r.at}). Choose the tank again.")
                    )
                if tank.unit_id in SETTLER_TYPES:
                    raise SimError(
                        f"Controller on {owner_label}, rule {i}: it measures in "
                        f"{tank.label}, a clarifier, which holds no mixed liquor. Choose a "
                        "tank."
                    )
                r.at, r.at_model, r.at_label = tank.id, tank.model, tank.label
                tanks[tank.id] = tank
            spec = ControllerSpec(
                reactor_name=owner_model, base=act["base"], rules=rules, period=period,
                target=target, owner_id=owner_id, owner_label=owner_label,
                lo=act["lo"], hi=act["hi"], hold=pc.hold,
            )
            chatter = chatter_warning(spec)
            if chatter:
                warnings.append(f"Controller on {owner_label}: {chatter}")
            # Only aeration needs the tick under the residence time: oxygen swings from zero
            # to saturation within it. A pump controller on MLSS acts on the sludge age —
            # days — and held to the residence time of a tank with a strong return (an
            # hour) it would only toggle the pump forty times as often.
            clamped = (_clamp_controller_period(spec, list(tanks.values()))
                       if target == "kLa" else None)
            if clamped:
                warnings.append(f"Controller on {owner_label}: {clamped}")
            wired.append({
                "spec": spec, "k_param": act["param"],
                "cycle": act.get("cycle") if target == "kLa" else None,
                "name": owner_label, "owner_id": owner_id, "log": [],
            })
    return wired


def _settler_fns(q_in: float, q_under: float, removal: float) -> float:
    """The IdealClarifier ``f_ns`` that removes ``removal`` of the incoming solids.

    The clarified stream carries ``f_ns`` times the incoming particulate concentration on
    ``q_in - q_under``, so the share removed is ``1 - f_ns (q_in - q_under) / q_in``.
    """
    q_eff = max(1e-6, q_in - q_under)
    return max(0.0, min(1.0, (1.0 - removal) * q_in / q_eff))


class _SettlerView:
    """Stands in for a settler where the build and the report read a reactor block.

    Both read ``outflows(0)`` — for a tank that is its contents, for a settler it has to
    be the clarified stream (an IdealClarifier's first outflow is not guaranteed to be).
    """

    def __init__(self, clarifier: Any):
        self.clarifier = clarifier

    def outflows(self, _index: int = 0) -> Any:
        return self.clarifier.effluent


def _resolve_kla(attrs: dict, label: str, t_end: float,
                 default: float = DEFAULT_KLA_PER_D) -> TimeValue:
    """A unit's kLa field as a TimeValue (``default`` when empty)."""
    raw = attrs.get("kLa")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return TimeValue("const", const=default)
    return parse_time_value(raw)


def _build_model(
    plan: Plan,
    t_end: float,
    warnings: list[str],
    synthetic: dict | None,
    total_q: float,
) -> dict[str, Any]:
    """Wire the PeePyPoo system from a resolved :class:`~server.topology.Plan`.

    The plan is a DAG, so the build is a single topological pass: every reactor's inlet
    streams already exist by the time we reach it. Three structures come out of the pass:

    * a **merge** (``FlowUnifier``) wherever a reactor has more than one inlet — a second
      street joining, an influent plus a recycle, a bypass rejoining;
    * a **split** (``FlowSeparator`` + one ``FlowPump`` per branch but the last) wherever a
      reactor feeds more than one downstream unit — the flows come from what the user drew
      on the pipes, scaled to the water actually arriving (see ``topology._static_flows``);
    * a **controlled split** for a reactor carrying a ``bypass`` spec: the stream is divided
      *before* the reactor and the diverted part rejoins at the reactor's downstream merge,
      with a callback steering the pump.

    Returns a dict with the model, the reactor blocks keyed by node id, the influent
    metadata, and the controller/cycle/bypass callback payloads for ``build()`` to attach
    after structural simplification.
    """
    asm = ppp.Process("ASM1", name="asm1", temperature=REACTOR_TEMPERATURE_C)
    states_od = asm.states()

    model = ppp.SystemConnection(name="plant")
    model.start_building()

    # ---- Build every Influent ------------------------------------------------
    ppp_influents: dict[str, dict[str, Any]] = {}
    # (node id, target) → the parameter a controller on that unit may write, the value it
    # falls back to, and the range the build allows (see TARGETS in controllers.py).
    actuators: dict[tuple[str, str], dict[str, Any]] = {}
    # model name → dissolved CO2 (mmol/L) its pH estimate assumes
    co2_by_model: dict[str, float] = {}

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
        # the peepypoo examples.
        comp: dict[str, Any] = {}
        for s in ASM1_STATES:
            tv = comp_tvs.get(s)
            if tv is None or tv.kind == "const":
                comp[s] = float(tv.const or 0.0) if tv is not None else 0.0
            else:
                comp[s] = float(tv.value_at(0.0, t_end))
        obj = ppp.Influent(
            comp,
            states_od,
            flowrate=_as_ppp_source(flow_tv, t_end, f"q_{_safe(node_id)}"),
            name=f"inf_{_safe(node_id)}",
        )
        return {
            "obj": obj,
            "label": label,
            "flow": flow_tv,
            "composition": dict(comp_tvs),
            "source": "user-supplied" if not synthetic else "synthetic (setup panel)",
            "synthetic": synthetic,
            "used": 0,
            # Filled in below when this feed is drawn into more than one reactor: an
            # Influent block has a single outflow, so the split needs its own separator.
            "ports": {},
        }

    def split_influent(meta: dict[str, Any], node_id: str, targets: list[str]) -> None:
        """Give a feed that enters several reactors one outflow port per reactor."""
        if len(targets) < 2:
            return
        shares: list[tuple[str, float]] = []
        for tid in targets:
            rp = plan.by_id(tid)
            q = 0.0
            if rp is not None:
                q = sum(i.flow for i in rp.inlets
                        if i.kind == "influent" and i.node_id == node_id)
            shares.append((tid, q))
        free_idx = max(range(len(shares)), key=lambda i: shares[i][1])
        sep = ppp.FlowSeparator(states_od, n_out=len(shares),
                                name=f"isp_{_safe(node_id)}")
        model.connect(meta["obj"].outflows(0), sep.inflows(0))
        for idx, (tid, q) in enumerate(shares):
            if idx == free_idx:
                meta["ports"][tid] = sep.outflows(idx)
                continue
            pump = ppp.FlowPump(states_od, flowrate=max(1.0, q),
                                name=f"ip_{_safe(node_id)}_{idx}")
            model.connect(sep.outflows(idx), pump.inflows(0))
            meta["ports"][tid] = pump.outflows(0)
            rp = plan.by_id(tid)
            warnings.append(
                f"Feed “{meta['label']}” is split: {max(1.0, q):g} m³/d is pumped to "
                f"{rp.label if rp is not None else tid}."
            )

    for node_id, info in plan.influents.items():
        raw_node = info["node"]
        flow_tv, comp_tvs, source = _influent_spec(raw_node)
        label = (raw_node.get("data") or {}).get("name") or "Influent"
        supply = _flow_controller_supply(raw_node, flow_tv, t_end)
        if supply is None:
            meta = make_ppp_influent(flow_tv, comp_tvs, label, node_id, synthetic=False)
            split_influent(meta, node_id, list(info["targets"]))
        else:
            # A feed a controller turns on and off. The influent delivers the most any
            # rule asks for into a feed tank; a pump draws what the controller sets from it
            # (0 = stopped) and the rest overflows. To the unit downstream that is a feed
            # switched on and off — and a pump's flow is a parameter of the plant, where
            # the controller can write it. (A flow block inside the Influent is not.)
            if len(info["targets"]) > 1:
                raise SimError(
                    f"Controller on {label}: a controlled influent must feed a single unit. "
                    "This one is split, and the split's pumps hold fixed flows that would "
                    "exceed the feed whenever the controller turns it down."
                )
            meta = make_ppp_influent(TimeValue("const", const=supply), comp_tvs, label,
                                     node_id, synthetic=False)
            meta["flow"] = flow_tv
            feed_sep = ppp.FlowSeparator(states_od, n_out=2, name=f"fs_{_safe(node_id)}")
            feed_pump = ppp.FlowPump(states_od, flowrate=float(flow_tv.value_at(0.0, t_end)),
                                     name=f"fp_{_safe(node_id)}")
            model.connect(meta["obj"].outflows(0), feed_sep.inflows(0))
            model.connect(feed_sep.outflows(0), feed_pump.inflows(0))
            # feed_sep.outflows(1) is the overflow, left open like a clarifier's effluent.
            meta["ports"][info["targets"][0]] = feed_pump.outflows(0)
            actuators[(node_id, "Q")] = {
                "param": feed_pump.parameters[0], "base": flow_tv, "lo": 0.0, "hi": supply,
            }
        meta["source"] = source
        meta["controlled"] = supply is not None
        ppp_influents[node_id] = meta

    if synthetic is not None:
        flow_tv = parse_time_value(synthetic.get("flow") or DEFAULT_INFLUENT_FLOW_M3D)
        comp_tvs = {s: TimeValue("const", const=float((synthetic.get("composition") or
                  DEFAULT_INFLUENT_FALLBACK)[s] or 0.0)) for s in ASM1_STATES}
        meta = make_ppp_influent(flow_tv, comp_tvs,
                                 synthetic.get("label", "Influent (synthetic)"),
                                 "synthetic", synthetic=True)
        meta["source"] = "synthetic (setup panel)"
        ppp_influents["__synthetic__"] = meta

    # Where the RAS returns to: the head of the street the clarifier sits at the end of,
    # not the head of the whole plant. On a one-street plant the two are the same; on a
    # plant whose streets merge into a final stage, returning the sludge all the way to
    # the headworks would be a recycle no operator would build. The reactors from there to
    # the clarifier are the loop the sludge age is measured over.
    ras_target = plan.sources[0].id if plan.sources else plan.reactors[0].id
    loop_ids: list[str] = []
    if plan.clarifier_feed:
        for chain in plan_streets(plan.reactors):
            if plan.clarifier_feed in chain:
                ras_target = chain[0]
                loop_ids = chain[:chain.index(plan.clarifier_feed) + 1]
                break
        else:
            ras_target = plan.clarifier_feed
            loop_ids = [plan.clarifier_feed]

    # ---- Clarifier + recirculation pumps, created before the reactors ----------
    # When a ``clarifier`` unit is on the canvas, the reactor feeding it sends its outflow
    # to an ideal clarifier (f_ns from the unit, default 0). The settled sludge splits by a
    # FlowSeparator into:
    #   * RAS — a pump with a fixed flow (the ``Qr`` field) back to the head of the loop;
    #   * WAS — a pump to the open sludge sink, sized for the loop's sludge age.
    # The clarifier's effluent port is left open (the plant's water-balance remainder).
    # Both pumps must exist before the reactors so the head reactor's inlet can carry RAS.
    #
    # The waste comes from, in order: the clarifier's ``SRT`` (the waste is computed to
    # hold it), its ``Q_was`` (taken as given, and the SRT it produces is reported), or a
    # default SRT. Both are fixed flows — see _waste_for_srt for why this is no longer an
    # MLSS controller.
    p_ras: Any = None
    p_was: Any = None
    q_ras = q_was = 0.0
    f_ns = 0.0
    clar_name = "Clarifier"
    clar_raw: dict = {}
    clar_srt = clar_srt_target = 0.0
    clar_srt_source = ""
    loop_volume = 0.0
    if plan.clarifier is not None:
        clar_raw = plan.clarifier.get("node") or {}
        clar_attrs = (clar_raw.get("data") or {}).get("attributes") or {}
        clar_name = (clar_raw.get("data") or {}).get("name") or "Clarifier"
        q_ras = _parse_float(clar_attrs.get("Qr")) or DEFAULT_RAS_FLOW_M3D
        q_ras = max(1.0, min(q_ras, 5.0 * max(total_q, 1.0)))
        f_ns = max(0.0, min(1.0, _parse_float(clar_attrs.get("f_ns")) or 0.0))

        loop = [plan.by_id(i) for i in loop_ids] or [plan.by_id(ras_target)]
        loop = [r for r in loop if r is not None and r.unit_id not in SETTLER_TYPES]
        loop_volume = sum((_parse_float(r.attrs.get("V")) or DEFAULT_VOLUME_M3) for r in loop)
        feed = plan.by_id(plan.clarifier_feed) if plan.clarifier_feed else None
        q_forward = max(1.0, feed.throughput if feed is not None else total_q)

        srt_attr = _parse_float(clar_attrs.get("SRT"))
        was_attr = _parse_float(clar_attrs.get("Q_was"))
        if srt_attr is not None and srt_attr > 0:
            clar_srt_target = max(0.5, min(60.0, srt_attr))
            q_was, clar_srt, note = _waste_for_srt(
                loop_volume, q_forward, q_ras, f_ns, clar_srt_target)
            clar_srt_source = "SRT"
            if note:
                warnings.append(f"Clarifier “{clar_name}”: {note}")
        elif was_attr is not None and was_attr > 0:
            q_was = max(MIN_WASTE_FLOW_M3D, min(was_attr, 0.5 * q_forward))
            if q_was != was_attr:
                warnings.append(
                    f"Clarifier “{clar_name}”: a waste of {was_attr:g} m³/d is more than "
                    f"half the {q_forward:g} m³/d that reaches it; capped at {q_was:g}."
                )
            clar_srt = _srt_for_waste(loop_volume, q_forward, q_ras, f_ns, q_was)
            clar_srt_source = "Q_was"
        else:
            clar_srt_target = DEFAULT_SRT_D
            q_was, clar_srt, note = _waste_for_srt(
                loop_volume, q_forward, q_ras, f_ns, clar_srt_target)
            clar_srt_source = "default"
            if note:
                warnings.append(f"Clarifier “{clar_name}”: {note}")

        aerated_volume = sum(
            (_parse_float(r.attrs.get("V")) or DEFAULT_VOLUME_M3) for r in loop
            if (r.unit_id in AERATED_TYPES or r.cycle is not None)
            and r.unit_id not in NON_AERATED_TYPES
        )
        if aerated_volume > 0:
            short = _srt_warning(f"The loop through “{clar_name}”", clar_srt,
                                 aerated_volume / max(loop_volume, 1e-6))
            if short:
                warnings.append(short + (
                    f" (set by its Q_was of {q_was:g} m³/d — give the clarifier an SRT "
                    "instead to size the waste for you)" if clar_srt_source == "Q_was"
                    else ""))
        p_ras = ppp.FlowPump(states_od, flowrate=q_ras, name="ras")
        p_was = ppp.FlowPump(states_od, flowrate=q_was, name="was")

    # ---- Topological pass over the reactors ------------------------------------
    react_objs: dict[str, Any] = {}
    controllers: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    bypasses: list[dict[str, Any]] = []
    retentions: list[dict[str, Any]] = []
    settlers: dict[str, dict[str, Any]] = {}
    # model name → the states that reactor holds fixed (not unknowns after simplification)
    fixed_by_model: dict[str, dict[str, float]] = {}
    # (upstream reactor id, downstream reactor id) → the outflow port that carries it.
    link_port: dict[tuple[str, str], Any] = {}
    # Extra ports that must be merged into a reactor's inlet (bypass rejoins).
    extra_inlets: dict[str, list[Any]] = {}

    for rp in plan.reactors:
        attrs = rp.attrs
        volume = _parse_float(attrs.get("V")) or DEFAULT_VOLUME_M3
        aerated = rp.unit_id in AERATED_TYPES
        if rp.unit_id in NON_AERATED_TYPES:
            aerated = False
        # An SBR is aerated by its cycle clock even though the palette does not list it
        # among the always-aerated units: the react phase is the aerated one.
        if rp.cycle is not None:
            aerated = True

        procs: list[Any] = [asm]
        kLa: TimeValue | None = None
        if aerated:
            kLa = _resolve_kla(attrs, rp.label, t_end,
                               DEFAULT_NATURAL_DRAFT_KLA_PER_D
                               if rp.unit_id in NATURAL_DRAFT_TYPES else DEFAULT_KLA_PER_D)
            procs.append(ppp.Aeration(name=f"aer{rp.index}"))

        if rp.unit_id in SETTLER_TYPES:
            # A settler holds no biology: an IdealClarifier whose sludge is pumped off to
            # waste, the clarified stream free. Everything around it — merging what
            # arrives, splitting what leaves — is the same code as for a reactor.
            q_in = max(1.0, rp.throughput)
            removal = _parse_float(attrs.get("removal"))
            removal = (DEFAULT_SETTLER_REMOVAL if removal is None
                       else max(0.0, min(0.99, removal)))
            q_under = _parse_float(attrs.get("Qu"))
            q_under = (DEFAULT_SETTLER_UNDERFLOW_SHARE * q_in if q_under is None
                       else max(0.1, min(q_under, 0.5 * q_in)))
            settler_fns = _settler_fns(q_in, q_under, removal)
            react = ppp.IdealClarifier(states_od, f_ns=settler_fns, name=rp.model)
            underflow = ppp.FlowPump(states_od, flowrate=q_under, name=f"uf{rp.index}")
            model.connect(react.sludge, underflow.inflows(0))   # → open sludge sink
            settlers[rp.id] = {"removal": removal, "underflow_m3_per_d": q_under,
                               "f_ns": settler_fns}
            actuators[(rp.id, "Qu")] = {
                "param": underflow.parameters[0], "base": _const(q_under),
                "lo": MIN_PUMP_FLOW_M3D, "hi": 0.5 * q_in,
            }
        else:
            mlss_attr = _parse_float(attrs.get("MLSS"))
            # The pH estimate's assumptions for this tank (see controllers.py, "pH").
            co2 = _parse_float(attrs.get("CO2"))
            co2_by_model[rp.model] = co2 if co2 and co2 > 0 else DEFAULT_CO2_MMOL_L
            ph0 = _parse_float(attrs.get("pH0"))
            init = _initial_states(
                mlss_attr,
                alkalinity_for_ph(ph0, co2_by_model[rp.model]) if ph0 else None)
            react = ppp.CSTR(volume, procs, initial_states=init, name=rp.model)
        # No reactor holds a state fixed today; the map is kept so a controller or a
        # bypass ratio can still read a state that is not an unknown of the simplified
        # system if one ever does (see ``controllers._state_reader``).
        fixed_by_model[rp.model] = {}

        # ---- solids retention inside the unit (SBR / MBR) --------------------------
        # These units settle or filter their own biomass back. Build the return pump here,
        # *before* the inlet is merged, so the returned sludge is one of the streams the
        # unifier sees; the clarifier itself is wired after the reactor.
        self_retaining = rp.unit_id in SELF_RETAINING_TYPES
        own_ras: Any = None
        own_was: Any = None
        own_srt = own_srt_target = 0.0
        own_srt_note: str | None = None
        own_fns = DEFAULT_SELF_RETAIN_FNS
        if self_retaining:
            own_srt_target = max(0.5, min(60.0, _parse_float(attrs.get("SRT"))
                                          or DEFAULT_SELF_RETAIN_SRT_D))
            q_through = max(1.0, rp.throughput)
            # Internal return. A trickling filter states it as a recirculation ratio; the
            # settling units get one turnover of their own throughput unless told otherwise.
            ratio = _parse_float(attrs.get("recirc"))
            own_ras_q = _parse_float(attrs.get("Qr")) or (
                q_through * (ratio if ratio and ratio > 0 else 1.0)
            )
            own_ras_q = max(1.0, min(own_ras_q, 10.0 * q_through))
            fns_attr = _parse_float(attrs.get("f_ns"))
            own_fns = DEFAULT_SELF_RETAIN_FNS if fns_attr is None else max(0.0, min(1.0, fns_attr))
            # The waste that holds this unit at its SRT, with the thickening of its own
            # internal separation accounted for (see _waste_for_srt).
            own_was_q, own_srt, own_srt_note = _waste_for_srt(
                volume, q_through, own_ras_q, own_fns, own_srt_target)
            own_ras = ppp.FlowPump(states_od, flowrate=own_ras_q, name=f"ras{rp.index}")
            own_was = ppp.FlowPump(states_od, flowrate=own_was_q, name=f"was{rp.index}")
            if own_srt_note:
                warnings.append(f"{rp.label}: {own_srt_note}")
            aerated_share = (rp.cycle.react_h / rp.cycle.cycle_h
                             if rp.cycle is not None and rp.cycle.cycle_h > 0 else 1.0)
            if aerated:
                short = _srt_warning(rp.label, own_srt, aerated_share)
                if short:
                    warnings.append(short)

        # ---- inlet: gather every stream arriving here, merge when more than one ----
        sources: list[Any] = []
        for inl in rp.inlets:
            if inl.kind == "reactor":
                port = link_port.get((inl.node_id, rp.id))
                if port is None:
                    raise SimError(
                        f"Internal wiring error: no outlet from "
                        f"{inl.node_id} to {rp.label}."
                    )
                sources.append(port)
            elif inl.kind == "influent":
                meta = ppp_influents.get(inl.node_id)
                if meta is not None:
                    meta["used"] += 1
                    sources.append(meta["ports"].get(rp.id)
                                   or meta["obj"].outflows(0))
        sources.extend(extra_inlets.get(rp.id, []))
        if rp.id == ras_target and "__synthetic__" in ppp_influents:
            ppp_influents["__synthetic__"]["used"] += 1
            sources.append(ppp_influents["__synthetic__"]["obj"].outflows(0))
        if rp.id == ras_target and p_ras is not None:
            sources.append(p_ras.outflows(0))

        if not sources:
            raise SimError(f"Reactor {rp.label} has no inlet at all.")

        # Merge what arrives from outside the unit. The unit's *own* sludge return is
        # merged further down, after the bypass split — a bypass diverts the incoming
        # stream, never the sludge the unit just returned to itself.
        if len(sources) == 1:
            inlet_port = sources[0]
        else:
            uni = ppp.FlowUnifier(states_od, n_in=len(sources), name=f"uin{rp.index}")
            for s_idx, src in enumerate(sources):
                model.connect(src, uni.inflows(s_idx))
            inlet_port = uni.outflows(0)

        # ---- controlled bypass *around* this reactor -------------------------------
        if rp.bypass is not None:
            downstream = [o for o in rp.outlets if o.kind == "reactor"]
            rejoin_id = next((o.node_id for o in downstream
                              if o.node_id == rp.bypass.rejoin_at), None)
            if rejoin_id is None and rp.bypass.rejoin_at:
                # A rejoin further down the line skips several units at once — a bypass
                # around a whole filter train. Any node built after this one will do: it
                # merges its extra inlets when its turn comes, and an edge from an earlier
                # node to a later one cannot close a cycle in a topological order.
                target = plan.by_id(rp.bypass.rejoin_at)
                if target is not None and target.index > rp.index:
                    rejoin_id = target.id
                else:
                    warnings.append(
                        f"Bypass around {rp.label}: rejoin point "
                        f"“{rp.bypass.rejoin_at}” is not a unit downstream of it."
                    )
            if rejoin_id is None and downstream:
                # No explicit rejoin point: the diverted stream goes to the branch that
                # carries the most flow, which is the one that can absorb it.
                rejoin_id = max(downstream, key=lambda o: o.flow).node_id
                if len(downstream) > 1:
                    rj = plan.by_id(rejoin_id)
                    warnings.append(
                        f"Bypass around {rp.label} rejoins at "
                        f"{rj.label if rj is not None else rejoin_id} (the largest "
                        "downstream branch). Set 'rejoin_at' on the bypass to choose "
                        "another one."
                    )
            if rejoin_id is None:
                warnings.append(
                    f"Bypass on {rp.label} has no downstream reactor to rejoin at — "
                    "the bypass is not wired."
                )
                rp.bypass = None
            else:
                bp_pump = ppp.FlowPump(states_od, flowrate=max(0.0, rp.bypass.base_flow),
                                       name=f"bp{rp.index}")
                bp_sep = ppp.FlowSeparator(states_od, n_out=2, name=f"bsp{rp.index}")
                model.connect(inlet_port, bp_sep.inflows(0))
                model.connect(bp_sep.outflows(1), bp_pump.inflows(0))
                inlet_port = bp_sep.outflows(0)      # the free branch → the reactor
                extra_inlets.setdefault(rejoin_id, []).append(bp_pump.outflows(0))
                measure_from = rp.bypass.measure_from or rp.id
                measure_rp = plan.by_id(measure_from) or rp
                bypasses.append({
                    "spec": rp.bypass,
                    "pump_k_param": bp_pump.parameters[0],
                    "measure_reactor": measure_rp.model,
                    "measure_unit_id": measure_rp.unit_id,
                    "measure_label": measure_rp.label,
                    "around": rp.label,
                })

        # ---- the unit's own sludge return joins last --------------------------------
        if own_ras is not None:
            ras_uni = ppp.FlowUnifier(states_od, n_in=2, name=f"rin{rp.index}")
            model.connect(inlet_port, ras_uni.inflows(0))
            model.connect(own_ras.outflows(0), ras_uni.inflows(1))
            inlet_port = ras_uni.outflows(0)

        model.connect(inlet_port, react.inflows(0))

        # ---- aeration ---------------------------------------------------------------
        if aerated and kLa is not None:
            if not react.exogenous_input_names:
                raise SimError(f"Aeration on {rp.label} has no kLa input port.")
            aero_name = react.exogenous_input_names[0]
            base_k = float(kLa.value_at(0.0, t_end))
            if not math.isfinite(base_k):
                raise SimError(f"kLa expression on {rp.label} is not finite at t=0.")
            start_k = base_k
            if rp.cycle is not None:
                # The cycle clock owns k from the first phase boundary onward; the block's
                # own initial value has to be the phase t=0 actually falls in, because the
                # clock's first callback does not fire until that boundary.
                rp.cycle.kla_react = base_k
                rp.cycle.kla_idle = 0.0
                phase0 = (-rp.cycle.offset_h) % rp.cycle.cycle_h
                in_react = (rp.cycle.fill_h <= phase0
                            < rp.cycle.fill_h + rp.cycle.react_h)
                start_k = base_k if in_react else 0.0
            kla_block = ppp.Constant(k=start_k, name=f"kla{rp.index}")
            model.connect(kla_block.output, react.exogenous_inputs(aero_name))
            rp.attrs = attrs
            setattr(rp, "_kla_tv", kLa)
            if rp.cycle is not None:
                cycles.append({
                    "cycle": rp.cycle, "k_param": kla_block.parameters[0],
                    "kla_react": base_k, "name": rp.label, "reactor": rp.model,
                })
            # On an SBR a kLa controller runs inside the react phase only: the cycle clock
            # still switches the aeration on and off at the phase edges, and the
            # controller decides within the window (see build_controller_callback).
            actuators[(rp.id, "kLa")] = {
                "param": kla_block.parameters[0], "base": kLa, "lo": 0.0,
                "hi": float("inf"), "cycle": rp.cycle,
            }

        if rp.id in settlers:
            react_objs[rp.id] = _SettlerView(react)
            out_port = react.effluent
        else:
            react_objs[rp.id] = react
            out_port = react.outflows(0)

        # ---- close the internal retention loop -------------------------------------
        # CSTR → ideal clarifier; the clarified stream is what leaves the unit, the sludge
        # splits into the internal return and the waste (both fixed — the waste is sized for
        # the unit's SRT above). The clarifier's effluent is the free branch of the unit's
        # water balance.
        if self_retaining and own_ras is not None and own_was is not None:
            inner = ppp.IdealClarifier(states_od, f_ns=own_fns, name=f"set{rp.index}")
            inner_sep = ppp.FlowSeparator(states_od, n_out=2, name=f"ssp{rp.index}")
            model.connect(react.outflows(0), inner.inflows(0))
            model.connect(inner.sludge, inner_sep.inflows(0))
            model.connect(inner_sep.outflows(0), own_ras.inflows(0))
            model.connect(inner_sep.outflows(1), own_was.inflows(0))
            out_port = inner.effluent
            actuators[(rp.id, "Q_was")] = {
                "param": own_was.parameters[0], "base": _const(own_was_q),
                "lo": MIN_PUMP_FLOW_M3D, "hi": 0.5 * q_through,
            }
            actuators[(rp.id, "Qr")] = {
                "param": own_ras.parameters[0], "base": _const(own_ras_q),
                "lo": MIN_PUMP_FLOW_M3D, "hi": 10.0 * q_through,
            }
            retentions.append({
                "node_id": rp.id,
                "label": rp.label,
                "ras_q": own_ras_q,
                "was_q": own_was_q,
                "srt_target_d": own_srt_target,
                "srt_d": own_srt,
                "srt_note": own_srt_note,
                "f_ns": own_fns,
            })

        # ---- outlet: one port, or a separator with a pump on every branch but one ----
        out_links = [o for o in rp.outlets if o.kind == "reactor"]
        sinks = [o for o in rp.outlets if o.kind == "sink"]
        feeds_clarifier = (plan.clarifier is not None and plan.clarifier_feed == rp.id)
        n_out = len(out_links) + (1 if (sinks or feeds_clarifier) else 0)

        if n_out <= 1:
            if out_links:
                link_port[(rp.id, out_links[0].node_id)] = out_port
            else:
                link_port[(rp.id, "")] = out_port
            continue

        # Several branches leave this reactor. PeePyPoo needs the flow on all but one of
        # them (the last closes by mass balance), so the branch with the *largest* flow is
        # left free and every other one gets a fixed pump.
        branches: list[tuple[str, float]] = [(o.node_id, o.flow) for o in out_links]
        if sinks or feeds_clarifier:
            branches.append(("", sum(o.flow for o in sinks)))
        free_idx = max(range(len(branches)), key=lambda i: branches[i][1])
        sep = ppp.FlowSeparator(states_od, n_out=len(branches), name=f"sep{rp.index}")
        model.connect(out_port, sep.inflows(0))
        for b_idx, (target, flow) in enumerate(branches):
            if b_idx == free_idx:
                link_port[(rp.id, target)] = sep.outflows(b_idx)
                continue
            q = max(1.0, float(flow))
            pump = ppp.FlowPump(states_od, flowrate=q,
                                name=f"sp{rp.index}_{b_idx}")
            model.connect(sep.outflows(b_idx), pump.inflows(0))
            link_port[(rp.id, target)] = pump.outflows(0)
            if target:
                warnings.append(
                    f"Split at {rp.label}: {q:g} m³/d is pumped to "
                    f"{(plan.by_id(target).label if plan.by_id(target) else target)}."
                )

    # ---- Clarifier + sludge split (RAS/WAS) -------------------------------------
    recirc: dict[str, Any] | None = None
    if plan.clarifier is not None and p_ras is not None and p_was is not None:
        feed_id = plan.clarifier_feed or (plan.terminals[-1].id if plan.terminals
                                          else plan.reactors[-1].id)
        feed_port = link_port.get((feed_id, "")) or react_objs[feed_id].outflows(0)
        clarifier_obj = ppp.IdealClarifier(states_od, f_ns=f_ns, name="clar")
        sep = ppp.FlowSeparator(states_od, n_out=2, name="sep_sludge")

        model.connect(feed_port, clarifier_obj.inflows(0))
        model.connect(clarifier_obj.sludge, sep.inflows(0))
        model.connect(sep.outflows(0), p_ras.inflows(0))    # RAS → head reactor
        model.connect(sep.outflows(1), p_was.inflows(0))    # WAS → open sludge sink
        # clarifier_obj.effluent is deliberately left open (free remainder).

        clar_id = str(plan.clarifier["node_id"])
        actuators[(clar_id, "Q_was")] = {
            "param": p_was.parameters[0], "base": _const(q_was),
            "lo": MIN_PUMP_FLOW_M3D, "hi": 0.5 * q_forward,
        }
        actuators[(clar_id, "Qr")] = {
            "param": p_ras.parameters[0], "base": _const(q_ras),
            "lo": MIN_PUMP_FLOW_M3D, "hi": 5.0 * max(total_q, 1.0),
        }
        recirc = {
            "clarifier": clarifier_obj,
            "ras_pump": p_ras,
            "was_pump": p_was,
            "ras_q": q_ras,
            "was_q": q_was,
            "srt_d": clar_srt,
            "srt_target_d": clar_srt_target,
            "srt_source": clar_srt_source,
            "loop_volume_m3": loop_volume,
            "total_q": float(total_q),
            "clarifier_raw": clar_raw,
            "feed_reactor": feed_id,
            "ras_into": ras_target,
        }
        into = plan.by_id(ras_target).label if plan.by_id(ras_target) else ras_target
        how = {
            "SRT": f"sized for its SRT of {clar_srt_target:g} d",
            "Q_was": "as set on the clarifier",
            "default": f"sized for the default SRT of {clar_srt_target:g} d",
        }[clar_srt_source]
        warnings.append(
            f"Clarifier “{clar_name}”: f_ns={f_ns:.3f}. RAS {q_ras:g} m³/d returns to "
            f"{into}; WAS {q_was:.1f} m³/d ({how}) gives the {loop_volume:g} m³ loop an "
            f"SRT of {clar_srt:.1f} d."
        )

    controllers = _wire_controllers(
        plan, actuators,
        ((plan.clarifier.get("node") or {}).get("data") or {}).get("name") or "Clarifier"
        if plan.clarifier is not None else "", warnings)

    for node_id, meta in ppp_influents.items():
        if meta["used"] == 0:
            raise SimError(
                f"Influent “{meta['label']}” is built but reaches no reactor — "
                "connect it to a reactor (directly or through a screen/basin)."
            )

    model.end_building()
    return {
        "model": model,
        "reactors": react_objs,
        "influents": ppp_influents,
        "controllers": controllers,
        "cycles": cycles,
        "bypasses": bypasses,
        "retentions": retentions,
        "settlers": settlers,
        "co2_by_model": co2_by_model,
        "fixed_by_model": fixed_by_model,
        "recirc": recirc,
        "link_port": link_port,
    }


def _safe(node_id: str) -> str:
    """A node id reduced to something usable as a PeePyPoo/Julia block name."""
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in str(node_id))
    return out or "x"


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
            return _build_locked(units_data, edges, time_days, influent_flow,
                                 influent_overrides)
        except TimeValueError as e:
            raise SimError(str(e)) from e
        except TopologyError as e:
            raise SimError(str(e)) from e


def _build_locked(
    units_data: list[dict],
    edges: list[dict],
    time_days: float | None = None,
    influent_flow: float | None = None,
    influent_overrides: dict[str, float] | None = None,
) -> dict:
    t0 = time.time()

    plan = resolve(units_data, edges)
    warnings: list[str] = list(plan.warnings)

    # If there are no drawn Influent units and the client passed a flow, create one
    # synthetic feed attached to the head reactor.
    synthetic: dict | None = None
    if not plan.influents and influent_flow and influent_flow > 0:
        comp = dict(DEFAULT_INFLUENT_FALLBACK)
        if influent_overrides:
            comp.update({k: float(v) for k, v in influent_overrides.items()
                         if k in ASM1_STATES and v is not None})
        synthetic = {"flow": float(influent_flow), "composition": comp,
                     "label": "Influent (synthetic)"}

    # Parse every influent (validates expressions early) and total the flow at t=0.
    parsed_influents: dict[str, dict] = {}
    total_q = 0.0
    for node_id, info in plan.influents.items():
        flow_tv, comp_tvs, source = _influent_spec(info["node"])
        parsed_influents[node_id] = {"flow": flow_tv, "composition": comp_tvs,
                                     "source": source}
        total_q += _tv_value_at(flow_tv, 0.0)
    if synthetic is not None:
        parsed_influents["__synthetic__"] = {
            "flow": TimeValue("const", const=float(synthetic["flow"])),
            "composition": {s: TimeValue("const", const=float(synthetic["composition"][s]))
                            for s in ASM1_STATES},
            "source": "synthetic (setup panel)",
        }
        total_q += float(synthetic["flow"])
    if total_q <= 0:
        raise SimError(
            "No influent configured. Add an Influent unit to the canvas, set its "
            "flow rate, and connect it to a reactor — "
            "or pass a flow in the Simulation window's setup panel."
        )

    # Simulation horizon. Default to a few turnovers of the head reactor, but never less
    # than a handful of SBR cycles when the plant has one (a cycle the run does not see
    # repeat a few times tells the user nothing).
    tanks = [r for r in plan.reactors if r.unit_id not in SETTLER_TYPES] or plan.reactors
    head = next((r for r in plan.sources if r.unit_id not in SETTLER_TYPES), tanks[0])
    first_volume = _parse_float(head.attrs.get("V")) or DEFAULT_VOLUME_M3
    t_end = time_days or min(T_MAX_DAYS, max(T_MIN_DAYS,
                                             3.0 * first_volume / max(total_q, 1.0)))
    if time_days is None:
        cycle_days = [r.cycle.cycle_d for r in plan.reactors if r.cycle is not None]
        if cycle_days:
            t_end = max(t_end, 10.0 * max(cycle_days))
        # The hydraulic residence time says how fast the *water* turns over; the sludge
        # age says how fast the *biology* does, and it is the slower of the two by one to
        # two orders of magnitude. A plant held at 12 d SRT cannot be anywhere near steady
        # state after the 2.5 d a volume-over-flow rule suggests — the nitrifiers are
        # still growing in from their seed, and the run shows a start-up transient that
        # reads as "no nitrification". So the horizon covers a few sludge ages.
        srts = [
            max(0.5, min(60.0, _parse_float(r.attrs.get("SRT")) or DEFAULT_SELF_RETAIN_SRT_D))
            for r in plan.reactors if r.unit_id in SELF_RETAINING_TYPES
        ]
        if plan.clarifier is not None:
            clar_attrs = (plan.clarifier.get("node", {}).get("data") or {}).get("attributes") or {}
            srts.append(max(0.5, min(60.0, _parse_float(clar_attrs.get("SRT"))
                                     or DEFAULT_SELF_RETAIN_SRT_D)))
        if srts:
            t_end = max(t_end, min(SRT_HORIZON_MAX_DAYS,
                                   SRT_HORIZON_MULTIPLE * max(srts)))
    t_end = max(0.5, min(90.0, t_end))

    # ---- Build + solve -------------------------------------------------------
    built = _build_model(plan, t_end, warnings, synthetic, total_q=total_q)
    model = built["model"]
    react_objs = built["reactors"]
    ppp_influents = built["influents"]
    controllers = built["controllers"]
    recirc = built["recirc"]

    # Controllers need peepypoo's index lookups to agree with the system the solver runs.
    # ``ODEProblem`` structurally simplifies first, and ``GetIndex``/``SetIndex`` resolve by
    # name against whatever object they are given — so we simplify ONCE here and drive both
    # the index lookups and the problem from that same object.
    sysS = model.structural_simplify()
    fixed_by_model = built["fixed_by_model"]
    callbacks = [
        cb
        for c in controllers
        for cb in build_controller_callback(c["spec"], sysS, c["k_param"], t_end,
                                            fixed_by_model, cycle=c.get("cycle"),
                                            log=c["log"], co2_by_model=built["co2_by_model"])
    ]
    for cy in built["cycles"]:
        callbacks.append(
            build_cycle_callback(sysS, cy["k_param"], cy["cycle"], cy["kla_react"], t_end)
        )
    for bp in built["bypasses"]:
        try:
            callbacks.append(
                build_bypass_callback(bp["spec"], sysS, bp["pump_k_param"],
                                      bp["measure_reactor"],
                                      fixed_by_model.get(bp["measure_reactor"]))
            )
        except ValueError as e:
            raise SimError(f"Bypass around {bp['around']}: {e}") from e
    # No callbacks for the retention loops: their waste flows are fixed, sized for each
    # loop's sludge age when the model was built (see _waste_for_srt).
    if callbacks:
        prob = ppp.ODEProblem(sysS, (0.0, t_end), callback=ppp.CallbackSet(callbacks))
    else:
        prob = ppp.ODEProblem(sysS, (0.0, t_end))

    # Save on a fixed grid instead of at every accepted step. Left to itself the solver
    # keeps every step *and* the dense interpolant for each one; on a three-week run of a
    # plant with a few hundred states that is gigabytes of output for a chart that is
    # resampled down to a thousand points anyway. The grid is fine enough to resolve the
    # shortest SBR cycle (a dozen samples per cycle) and is capped so the payload stays
    # bounded however long the run is.
    cycle_days = [r.cycle.cycle_d for r in plan.reactors if r.cycle is not None]
    step = t_end / (SAVE_POINTS_DEFAULT - 1)
    if cycle_days:
        step = min(step, min(cycle_days) / SAVE_POINTS_PER_CYCLE)
    n_save = min(SAVE_POINTS_MAX, max(2, int(round(t_end / max(step, 1e-9))) + 1))
    saveat = [t_end * i / (n_save - 1) for i in range(n_save)]
    try:
        sol = prob.solve(saveat=saveat, dense=False, isoutofdomain=_out_of_domain())
    finally:
        # The server builds a new system per request; without this the cached symbol
        # tables would accumulate for the life of the process.
        forget_index(sysS)

    t_arr = [float(x) for x in sol.t]
    n_pts = len(t_arr)

    # ---- Did the solver actually get to the end? --------------------------------
    # It may not have: a stiff model can drive the step size below floating-point
    # resolution and give up part-way, and DifferentialEquations reports that through the
    # return code rather than by raising. Everything downstream — the charts, the final
    # effluent table, the comparison against a reference — reads whatever came back and
    # presents it as a finished run. A plant that diverged on day two would be reported as
    # a clean three-week result, which is worse than no result at all. So this is a hard
    # error, not a warning.
    reached = t_arr[-1] if t_arr else 0.0
    try:
        ok = bool(sol.successful())
    except Exception:
        ok = True                       # can't tell — fall back to the coverage check
    try:
        retcode = str(sol.retcode)
    except Exception:
        retcode = "unknown"
    if not ok or reached < t_end * (1.0 - SOLVE_COVERAGE_TOLERANCE):
        diagnosis = _diagnose_abort(plan, react_objs, sol)
        raise SimError(
            f"The solver stopped at t = {reached:.3f} d of the requested {t_end:g} d "
            f"(return code: {retcode}). The results up to that point are not reported, "
            "because a partial run shown as a finished one is worse than no run. "
            + (diagnosis or
               "Nothing in the reactors stood out where it stopped; the usual causes are a "
               "hard on/off aeration switch that drives dissolved oxygen to exactly zero, a "
               "tank whose residence time is far shorter than everything around it, or a "
               "pumped branch asking for more flow than arrives at its split.")
        )

    def _clean(v: float) -> float:
        # Round-off just below zero (the solver keeps states above -DOMAIN_NEGATIVE_TOLERANCE,
        # and interpolating to the output grid can dip a hair further) is shown as zero.
        # Anything meaningfully negative is not cleaned here — it is caught below and fails
        # the run, because clipping it is exactly how a corrupt solution once passed as a
        # finished one.
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
        return [(_clean(src[int(round(i * step))]) if clean else src[int(round(i * step))])
                for i in range(k)]

    k_series = min(n_pts, 1_000) if n_pts > 1_000 else n_pts
    t_out = [round(t, 6) for t in resample(t_arr, k=k_series, clean=False)]
    series: dict[str, dict[str, list[float]]] = {}

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
            lowest = min(vals)
            if lowest < negative_seen[0]:
                negative_seen[0] = lowest
                negative_seen[1] = name
            block[name] = resample(vals, k=k_series)
        return block

    # Lowest raw value read into any reported series, and which state it was.
    negative_seen: list[Any] = [0.0, ""]

    # A reactor's own series is its *tank contents* — the mixed liquor, which is what a
    # user wants to see for a reactor (MLSS, whether it nitrifies). For a unit that keeps
    # its solids that is not what leaves it: the decant of an SBR or the permeate of an MBR
    # is the clarified stream after its internal separation.
    for rp in plan.reactors:
        series[rp.model] = _block_of(react_objs[rp.id].outflows(0))

    # The plant effluent: the clarified stream when a clarifier is on the canvas, otherwise
    # the stream that actually leaves the terminal reactor for the sink. With several
    # terminals (parallel streets that never re-merge) the largest one is reported and the
    # others stay available under their own rN key.
    #
    # The second case must read the unit's *outlet port*, not its tank. Reading the tank
    # was harmless while every terminal was a plain flow-through CSTR, whose outflow equals
    # its contents. Once units keep their own solids it reported mixed liquor as effluent —
    # an MABR plant came out at 2490 mg/L COD and 1850 mg/L TSS.
    terminals = plan.terminals or [plan.reactors[-1]]
    eff_reactor = max(terminals, key=lambda r: r.throughput)
    if recirc is not None:
        series["eff"] = _block_of(recirc["clarifier"].effluent)
        eff_label = (((recirc["clarifier_raw"].get("data") or {}).get("name"))
                     or "Clarifier")
        eff_from_id = recirc["feed_reactor"]
    else:
        outlet = built["link_port"].get((eff_reactor.id, ""))
        outlet_block = _block_of(outlet) if outlet is not None else {}
        if outlet_block:
            series["eff"] = outlet_block
        else:
            # Never quietly: falling back to the tank is exactly the error this replaced.
            series["eff"] = series[eff_reactor.model]
            if eff_reactor.unit_id in SELF_RETAINING_TYPES:
                warnings.append(
                    f"Could not read the clarified outlet of {eff_reactor.label}; the "
                    "effluent shown is its tank contents (mixed liquor), which overstates "
                    "effluent solids and COD."
                )
        eff_label = eff_reactor.label
        eff_from_id = eff_reactor.id
    if len(terminals) > 1 and recirc is None:
        warnings.append(
            "Several streets end without re-merging ("
            + ", ".join(r.label for r in terminals)
            + f") — the effluent is reported from {eff_reactor.label}."
        )

    # pH, estimated from the alkalinity (controllers.py, "pH") — ASM1 has no pH of its own.
    # Each tank uses the CO2 it states; the effluent the CO2 of the unit it leaves.
    co2_map = built["co2_by_model"]

    def with_ph(blk: dict[str, list[float]], model: str) -> None:
        if blk and "S_ALK" in blk and "pH" not in blk:
            co2 = co2_map.get(model, DEFAULT_CO2_MMOL_L)
            blk["pH"] = [round(ph_from_alkalinity(v, co2), 4) for v in blk["S_ALK"]]

    for rp in plan.reactors:
        with_ph(series.get(rp.model) or {}, rp.model)
    eff_src = plan.by_id(eff_from_id)
    with_ph(series.get("eff") or {}, eff_src.model if eff_src is not None else "")

    # A concentration that went meaningfully negative means the solution left the physical
    # domain somewhere the solver's domain check did not catch it. Fail rather than clip.
    if negative_seen[0] < -NEGATIVE_RESULT_LIMIT:
        raise SimError(
            f"The solution went negative ({negative_seen[1]} reached "
            f"{negative_seen[0]:.3g} mg/L), so it is not physical and is not reported. "
            "This happens when a tank's oxygen (or another state) is driven to zero faster "
            "than the solver can follow — typically a hard aeration switch in a tank with a "
            "lot of biomass."
        )

    # Total influent flow over time so the UI can chart "flows" too.
    total_influent_flow: list[float] | None = None
    try:
        acc = [0.0] * n_pts
        # A controlled feed runs at whatever its controller set, not at its flow field.
        set_by_ctrl = {c["owner_id"]: sorted(c["log"]) for c in controllers
                       if c["spec"].target == "Q" and c["log"]}
        for node_id, parsed in parsed_influents.items():
            log_q = set_by_ctrl.get(node_id)
            if log_q:
                times = [t for t, _ in log_q]
                for idx, t in enumerate(t_arr):
                    j = bisect.bisect_right(times, float(t)) - 1
                    acc[idx] += log_q[max(j, 0)][1]
                continue
            tv = parsed["flow"]
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
    def _tv_report(tv: TimeValue, t_end: float) -> dict[str, Any]:
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

    influent_reports: list[dict[str, Any]] = []
    for node_id, meta in ppp_influents.items():
        parsed = parsed_influents.get(node_id)
        if parsed is None:
            continue
        if node_id == "__synthetic__":
            targets = [plan.sources[0] if plan.sources else plan.reactors[0]]
        else:
            targets = [plan.by_id(t) for t in plan.influents[node_id]["targets"]]
            targets = [t for t in targets if t is not None]
        comp, comp_tv, comp_tv_detail = _comp_report(parsed)
        flow_tv = meta["flow"]
        first = targets[0] if targets else plan.reactors[0]
        influent_reports.append({
            "label": meta["label"],
            "into_reactor": first.label,
            "into_reactor_index": first.index,
            "into_reactor_id": first.id,
            # A feed may be split across several reactors (two parallel streets fed from
            # one headworks) — the full list is here, the scalar fields above stay for
            # older clients.
            "into_reactors": [{"label": t.label, "index": t.index, "id": t.id}
                              for t in targets],
            "flow_m3_per_d": _tv_value_at(flow_tv, 0.0),
            "composition": comp,
            "composition_source": parsed["source"],
            "synthetic": bool(meta["synthetic"]),
            "time_varying": (["flow"] if flow_tv.kind != "const" else []) + comp_tv,
            "time_varying_detail": (
                ({"flow": _tv_report(flow_tv, t_end)} if flow_tv.kind != "const" else {})
                | comp_tv_detail
            ),
        })

    retention_by_id = {r["node_id"]: r for r in built["retentions"]}
    settler_by_id = built["settlers"]
    ctrl_by_owner: dict[str, list[dict[str, Any]]] = {}
    for c in controllers:
        ctrl_by_owner.setdefault(c["owner_id"], []).append(c)
    cycle_by_label = {c["name"]: c for c in built["cycles"]}
    bypass_by_label = {b["around"]: b for b in built["bypasses"]}
    reactor_report = []
    for rp in plan.reactors:
        aerated = rp.unit_id in AERATED_TYPES or rp.cycle is not None
        if rp.unit_id in NON_AERATED_TYPES:
            aerated = False
        kla_tv = getattr(rp, "_kla_tv", None)
        cycle = cycle_by_label.get(rp.label)
        bypass = bypass_by_label.get(rp.label)
        reactor_report.append({
            "index": rp.index,
            "label": rp.label,
            "unitId": rp.unit_id,
            "aeration": bool(aerated),
            "kLa": (float(kla_tv.const) if kla_tv is not None and kla_tv.kind == "const"
                    else None),
            "kLa_report": (_tv_report(kla_tv, t_end) if kla_tv is not None else None),
            "controllers": [summarize_controller(c["spec"])
                            for c in ctrl_by_owner.get(rp.id, [])],
            "cycle": (describe_cycle(cycle["cycle"], cycle["kla_react"])
                      if cycle is not None else None),
            "bypass": (describe_bypass(bypass["spec"], bypass["around"],
                                       bypass["measure_label"])
                       if bypass is not None else None),
            "volume_m3": (0.0 if rp.id in settler_by_id
                          else (_parse_float(rp.attrs.get("V")) or DEFAULT_VOLUME_M3)),
            "temperature_c": REACTOR_TEMPERATURE_C,
            # Units that keep their own solids (SBR, MBR, MBBR, MABR, trickling filter)
            # run an internal clarifier + return loop at their own SRT.
            "retention": (_retention_report(retention_by_id[rp.id])
                          if rp.id in retention_by_id else None),
            # A primary / intermediate clarifier: what it takes out of the line.
            "settler": (_settler_report(settler_by_id[rp.id])
                        if rp.id in settler_by_id else None),
            "throughput_m3_per_d": round(rp.throughput, 1),
            # The DAG, as the model wired it — this is what makes parallel streets and
            # side streams legible in the UI.
            "feeds": [
                {"id": o.node_id,
                 "label": (plan.by_id(o.node_id).label if o.node_id and plan.by_id(o.node_id)
                           else "Effluent / sink"),
                 "flow_m3_per_d": round(o.flow, 1)}
                for o in rp.outlets
            ],
            "fed_by": [
                {"id": i.node_id,
                 "kind": i.kind,
                 "label": (plan.by_id(i.node_id).label if i.kind == "reactor"
                           and plan.by_id(i.node_id)
                           else ((plan.influents.get(i.node_id, {}).get("node", {})
                                  .get("data") or {}).get("name") or "Influent")),
                 "flow_m3_per_d": round(i.flow, 1)}
                for i in rp.inlets
            ],
        })

    streets = plan_streets(plan.reactors)
    clar_ctrls = (ctrl_by_owner.get(str(plan.clarifier["node_id"]), [])
                  if plan.clarifier is not None else [])
    clar_controlled = {c["spec"].target for c in clar_ctrls}

    return {
        "t_days": t_out,
        "states": list(ASM1_STATES) + ["pH"],
        "series": series,
        "reactors": reactor_report,
        "warnings": warnings,
        "t_end_days": t_end,
        "elapsed_s": round(time.time() - t0, 2),
        "total_influent_flow": total_influent_flow,
        # What each controller set over the run, as a step series (one point either side of
        # every change), so the UI can chart the actuator next to what it measured.
        "controls": [_control_series(c, t_end) for c in controllers if c["log"]],
        "setup": {
            "controllers": [summarize_controller(c["spec"]) for c in controllers],
            "influents": influent_reports,
            "total_flow_m3_per_d": total_q,
            "effluent": {
                "from_reactor": eff_label,
                "from_reactor_id": eff_from_id,
            },
            # The resolved topology — parallel streets, merges and splits.
            "topology": {
                "reactor_count": len(plan.reactors),
                "street_count": len(streets),
                "streets": [
                    [(plan.by_id(rid).label if plan.by_id(rid) else rid) for rid in chain]
                    for chain in streets
                ],
                "terminals": [t.label for t in terminals],
                "sources": [s.label for s in plan.sources],
            },
            "clarifier": (
                {
                    "name": (recirc["clarifier_raw"].get("data") or {}).get("name")
                    or "Clarifier",
                    "f_ns": _parse_float(((recirc["clarifier_raw"].get("data") or {})
                                   .get("attributes") or {}).get("f_ns")) or 0.0,
                    "ras_m3_per_d": float(recirc["ras_q"]),
                    "was_m3_per_d": round(float(recirc["was_q"]), 2),
                    "srt_d": round(float(recirc["srt_d"]), 2),
                    "srt_target_d": float(recirc["srt_target_d"]) or None,
                    "srt_source": recirc["srt_source"],
                    "loop_volume_m3": float(recirc["loop_volume_m3"]),
                    "fed_by": (plan.by_id(recirc["feed_reactor"]).label
                               if plan.by_id(recirc["feed_reactor"]) else ""),
                    "returns_to": (plan.by_id(recirc["ras_into"]).label
                                   if plan.by_id(recirc["ras_into"]) else ""),
                    "controllers": [summarize_controller(c["spec"]) for c in clar_ctrls],
                    "control_note": (
                        f"RAS {recirc['ras_q']:g} m³/d and WAS {recirc['was_q']:.1f} m³/d, "
                        f"both fixed. The {recirc['loop_volume_m3']:g} m³ loop runs at an "
                        f"SRT of {recirc['srt_d']:.1f} d; the mixed-liquor solids settle "
                        "wherever the load puts them at that sludge age."
                        if not clar_controlled else
                        f"RAS {recirc['ras_q']:g} m³/d and WAS {recirc['was_q']:.1f} m³/d "
                        f"to start; a controller then sets the "
                        + " and the ".join(CONTROL_TARGETS[t][0] for t in sorted(clar_controlled))
                        + f". The SRT of {recirc['srt_d']:.1f} d holds for the starting "
                        "flows only."
                    ),
                }
                if recirc is not None else None
            ),
        },
    }
