"""Plant controllers — "if what I measure there is X, set this here to Y".

The frontend stores a list of small, structured controllers on the unit whose setting they
change (see ``src/lib/controller.ts``)::

    "controllers": [
      {
        "target": "Q_was",                  # what this controller sets (see TARGETS)
        "period_days": 0.1,                 # how often it re-evaluates
        "rules": [
          {"at": "tank-1", "when": "MLSS", "op": ">", "value": 4000, "set": 120},
          {"at": "tank-1", "when": "MLSS", "op": "<", "value": 3000, "set": 40},
          {"when": "t", "op": "<", "value": 5.0, "set": 60}         # time-based rule
        ]
      }
    ]

A rule measures in any tank of the plant (``at`` is its node id; without it, the unit the
controller sits on) and sets the controller's ``target`` on the unit it sits on: the kLa
of an aerated unit, the excess-sludge (WAS) or return (RAS) pump of a clarifier or of a
unit that keeps its own solids, or the underflow of a primary clarifier. So "when tank 1
carries more than 4000 g/m³ MLSS, waste 120 m³/d" is a WAS controller on the clarifier
with one rule measured in tank 1.

Evaluation is first-match-wins, in listed order, every ``period_days`` of simulated time;
when no rule matches the target's own setting is used (the unit's kLa field, or the pump
flow the build sized). That keeps bang-bang control, setpoint rules and time scheduling in
one tiny language with no syntax to learn. The older single ``"controller"`` object on an
aerated unit is still read, as a kLa controller measuring its own tank.

Why a periodic discrete callback
--------------------------------

PeePyPoo evaluates its model symbolically at build time; only *continuous, differentiable*
bodies survive. A hard "if S_O < 1 then kLa = 400" is control **flow**, so it cannot be part
of the ODE right-hand side. The supported home for it is a discrete callback fired by the
solver — ``ppp.PeriodicCallback`` — which:

  * reads the live state from the integrator (``GetIndex`` on the solved state vector);
  * rewrites the aeration ``kLa`` parameter in place (``SetIndex`` on the ``Constant``
    block wired to the reactor's aeration input).

Both need to be resolved against the **same, structurally-simplified system the solver
actually runs** — peepypoo's index lookup is name-based and returns stale indices if it is
pointed at the unsimplified model. So the build path simplifies once, and that object
drives the index lookups *and* the ``ODEProblem``.
"""

from __future__ import annotations

import bisect
import math
import operator
from dataclasses import dataclass, field
from typing import Any

from .timeseries import TimeValue

# operators allowed in a rule condition (no "==" — floats don't equal cleanly)
_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}

# states a rule may key on (the 14 ASM1 states) — mirrors ASM1_STATES in simulate.py
_STATE_NAMES = {
    "S_I", "S_S", "X_I", "X_S", "X_BH", "X_BA", "X_P",
    "S_O", "S_NO", "S_NH", "S_ND", "X_ND", "S_ALK", "S_N2",
}

_TIME = "t"  # keyword name for "simulation time in days"
# One minute. A controller on a thin buffer needs it: at pH 6.2 a tank holds ~0.7 mmol/L of
# alkalinity, and a nitrifying tank fed on pH swings 6.15-6.32 at a 15-minute tick against
# 6.19-6.26 at two minutes (the pH-fed example, 10 d in 5 s either way).
_PERIOD_MIN = 1.0 / 1440.0
_PERIOD_MAX = 1.0            # cap per tick to at most one day
_PERIOD_DEFAULT = 0.1        # ~2.4 h, a good default control interval

# Derived measurements a rule may key on besides the 14 states.
MLSS = "MLSS"                # suspended solids, g TSS/m³ (0.75 g TSS per g particulate COD)
COD_N = "COD/N"              # total COD over TKN
PH = "pH"                    # estimated from alkalinity, see ph_from_alkalinity
MEASURES = _STATE_NAMES | {MLSS, COD_N, PH}

# ---- pH -----------------------------------------------------------------------------
# ASM1 has no pH. It carries alkalinity, S_ALK, as mol HCO3-/m³ (= mmol/L), and its
# stoichiometry moves it the way the real processes do: nitrification takes two moles per
# mole of ammonium oxidised, ammonification and denitrification give some back. In the
# carbonate buffer that sets the pH of an activated-sludge tank,
#
#     pH = pK1(T) + log10([HCO3-] / [CO2])
#
# so with the dissolved CO2 known the pH follows from S_ALK. The CO2 is not modelled
# either: it is what respiration produces and aeration strips, and a tank states it as an
# assumption (``CO2``, mmol/L; DEFAULT_CO2_MMOL_L when not given). The estimate is good
# between about pH 5.5 and 8.3, where bicarbonate carries the alkalinity; above that
# carbonate and ammonia take over and it reads high.
DEFAULT_CO2_MMOL_L = 1.0


def pk1(temperature_c: float = 20.0) -> float:
    """First dissociation constant of carbonic acid (Harned & Davis): 6.38 at 20 °C."""
    t = temperature_c + 273.15
    return 3404.71 / t + 0.032786 * t - 14.8435


def ph_from_alkalinity(s_alk: float, co2: float, temperature_c: float = 20.0) -> float:
    """pH of the bicarbonate buffer with ``s_alk`` and ``co2`` in mmol/L."""
    return pk1(temperature_c) + math.log10(max(s_alk, 1e-9) / max(co2, 1e-9))


def alkalinity_for_ph(ph: float, co2: float, temperature_c: float = 20.0) -> float:
    """The S_ALK (mmol/L) that gives ``ph`` with ``co2`` — the inverse of the above."""
    return max(co2, 1e-9) * 10 ** (ph - pk1(temperature_c))

# What a controller can set, with the unit it is stated in. Which ones a unit offers is
# decided by the build (an aerated unit has a kLa, a clarifier has its two pumps, …).
TARGETS = {
    "kLa": ("aeration kLa", "1/d"),
    "Q_was": ("excess sludge (WAS)", "m³/d"),
    "Qr": ("sludge return", "m³/d"),
    "Qu": ("sludge underflow", "m³/d"),
    "Q": ("influent flow", "m³/d"),
}


@dataclass
class Rule:
    when: str      # a state name, MLSS, COD/N, or _TIME
    op: str        # one of _OPS
    value: float
    set: float
    at: str = ""          # node id of the tank it measures in ("" = the controller's own unit)
    at_model: str = ""    # that tank's model name (r1, r2, …), filled in by the build
    at_label: str = ""    # and its name, for messages

    def as_dict(self) -> dict[str, Any]:
        return {"when": self.when, "op": self.op, "value": self.value, "set": self.set,
                "at": self.at, "at_label": self.at_label}

    def describe(self, target: str = "kLa", unit: str = "") -> str:
        if self.when == _TIME:
            lhs = "time [d]"
        else:
            lhs = f"{self.when} in {self.at_label}" if self.at_label else self.when
        return f"if {lhs} {self.op} {self.value:g} then {target} = {self.set:g}{unit}"


@dataclass
class ControllerSpec:
    """A validated controller: what it sets, on which unit, and its rules."""
    reactor_name: str             # model name of the unit it sits on (e.g. "r1")
    base: TimeValue               # value to use when no rule matches
    rules: list[Rule] = field(default_factory=list)
    period: float = _PERIOD_DEFAULT
    target: str = "kLa"
    owner_id: str = ""            # node id of the unit it sits on
    owner_label: str = ""
    lo: float = 0.0               # bounds the build allows the target to take
    hi: float = float("inf")
    # When no rule matches: fall back to ``base`` (False) or keep the last setting (True).
    # Keeping it is what makes two rules a switch with hysteresis — "on below 6.20, off
    # above 6.25" stays on, or off, in between.
    hold: bool = False

    @property
    def target_text(self) -> str:
        return TARGETS.get(self.target, (self.target, ""))[0]

    @property
    def unit(self) -> str:
        return TARGETS.get(self.target, ("", ""))[1]

    @property
    def is_flow(self) -> bool:
        return self.target != "kLa"


def _finite(x: Any) -> bool:
    try:
        return float(x) == float(x) and abs(float(x)) < 1e300
    except (TypeError, ValueError):
        return False


@dataclass
class ParsedController:
    target: str
    period: float
    rules: list[Rule]
    hold: bool = False


def _parse_one(raw: Any, where: str) -> ParsedController:
    """Validate one controller object."""
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be an object with a 'rules' array.")
    target = str(raw.get("target") or "kLa")
    if target not in TARGETS:
        raise ValueError(f"{where}: unknown target {target!r} "
                         f"(one of {', '.join(TARGETS)}).")

    rules_raw = raw.get("rules")
    if rules_raw is None:
        raise ValueError(f"{where} has no 'rules'. Add at least one rule.")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ValueError(f"{where}: 'rules' must be a non-empty list.")

    period = raw.get("period_days", _PERIOD_DEFAULT)
    try:
        period = float(period)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{where}: 'period_days' must be a number.") from e
    if not _finite(period) or period <= 0:
        raise ValueError(f"{where}: 'period_days' must be a positive number of days.")
    period = min(max(period, _PERIOD_MIN), _PERIOD_MAX)

    name = TARGETS[target][0]
    rules: list[Rule] = []
    for i, r in enumerate(rules_raw, start=1):
        if not isinstance(r, dict):
            raise ValueError(f"{where}, rule {i} must be an object.")
        when = r.get("when")
        if when not in MEASURES and when != _TIME:
            raise ValueError(f"{where}, rule {i}: 'when' must be a state (S_O, S_NH, …), "
                             "MLSS, COD/N or t.")
        op = r.get("op")
        if op not in _OPS:
            raise ValueError(f"{where}, rule {i}: 'op' must be one of <, <=, >, >=.")
        value = r.get("value")
        if not _finite(value):
            raise ValueError(f"{where}, rule {i}: 'value' must be a number.")
        setv = r.get("set")
        if not _finite(setv):
            raise ValueError(f"{where}, rule {i}: 'set' (the {name} to apply) must be a "
                             "number.")
        if float(setv) < 0:
            raise ValueError(f"{where}, rule {i}: the {name} cannot be negative.")
        at = r.get("at")
        rules.append(Rule(when=str(when), op=str(op), value=float(value), set=float(setv),
                          at=str(at) if at else ""))
    otherwise = raw.get("otherwise", "base")
    if otherwise not in ("base", "hold"):
        raise ValueError(f"{where}: 'otherwise' must be 'base' or 'hold'.")
    return ParsedController(target=target, period=period, rules=rules,
                            hold=otherwise == "hold")


def parse_controllers(node_data: dict | None) -> list[ParsedController]:
    """Every controller on a unit, validated: ``[(target, period, rules), …]``.

    Reads ``data.controllers`` (a list) and the older ``data.controller`` (one kLa
    controller). Two controllers setting the same target on one unit are refused — which
    of them would win is not something a user should have to guess. Raises ``ValueError``
    with a human-readable message; the caller turns that into a ``SimError``.
    """
    data = node_data or {}
    raws: list[Any] = []
    listed = data.get("controllers")
    if listed:
        if not isinstance(listed, list):
            raise ValueError("'controllers' must be a list.")
        raws.extend(listed)
    legacy = data.get("controller")
    if legacy:
        raws.append({**legacy, "target": "kLa"} if isinstance(legacy, dict) else legacy)
    out: list[ParsedController] = []
    seen: set[str] = set()
    for i, raw in enumerate(raws, start=1):
        pc = _parse_one(raw, f"controller {i}")
        if pc.target in seen:
            raise ValueError(f"two controllers set the {TARGETS[pc.target][0]}; keep one.")
        seen.add(pc.target)
        out.append(pc)
    return out


# Below this, a controller that flips on every tick costs real solve time; above it the
# solver absorbs the switching without noticing.
_CHATTER_PERIOD = 0.05


def chatter_warning(spec: ControllerSpec) -> str | None:
    """A warning when this controller's rules will flip on nearly every tick.

    Two rules on the same measurement that switch at the *same* threshold have no deadband:
    the value sits on the boundary and the controller alternates at every tick, restarting
    the stiff solver each time. Measured on a single aerated tank over three weeks, a
    no-deadband pair at a 0.02 d tick costs 8 s against 0.1 s with a deadband — and the
    plant it describes is not one anybody would build either, since a real controller has
    hysteresis. The rules still run; this only says what it will cost.
    """
    by_measure: dict[tuple[str, str], list[Rule]] = {}
    for r in spec.rules:
        if r.when != _TIME:
            by_measure.setdefault((r.at_model, r.when), []).append(r)
    for (_, state), rs in by_measure.items():
        ups = [r.value for r in rs if r.op in (">", ">=")]
        downs = [r.value for r in rs if r.op in ("<", "<=")]
        if not ups or not downs:
            continue
        if min(ups) <= max(downs) and spec.period < _CHATTER_PERIOD:
            return (
                f"the rules on {state} switch at the same point "
                f"({min(ups):g}) with no deadband, and the period is "
                f"{spec.period:g} d. The controller will flip on nearly every tick and "
                "restart the solver each time. Separate the thresholds (e.g. "
                f"> {max(min(ups), max(downs)) + 0.5:g} and < "
                f"{max(downs) - 0.5:g}) or use a period of at least "
                f"{_CHATTER_PERIOD:g} d."
            )
    return None


# ---------------------------------------------------------------------------

# Resolving a state symbol means matching the *printed* name of an unknown, and printing
# one crosses into Julia to format a symbolic expression — slow enough that doing it per
# lookup dominates everything else. A plant with three retention loops needs ~29 lookups
# (six solids per MLSS actuator, ten states for a COD/N ratio, one per controller rule),
# and scanning the whole unknowns list for each means thousands of those conversions.
#
# So the list is walked **once** per system and cached as {(reactor, state): symbol}.
_INDEX_CACHE: dict[int, dict[tuple[str, str], Any]] = {}


def _unknown_index(system: Any) -> dict[tuple[str, str], Any]:
    """``{(reactor name, state name): symbol}`` for one simplified system, built once."""
    key = id(system)
    cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    index: dict[tuple[str, str], Any] = {}
    for u in system.unknowns:
        text = str(u)
        head = text.split("₊")[0]
        tail = text.split("₊")[-1].split("(")[0]
        index.setdefault((head, tail), u)
    _INDEX_CACHE[key] = index
    return index


def forget_index(system: Any) -> None:
    """Drop a system's cached symbol table (call when the system is no longer used)."""
    _INDEX_CACHE.pop(id(system), None)


def resolve_state_symbol(system: Any, reactor_name: str, state: str) -> Any:
    """Find the resolved symbol for one reactor's state (e.g. ``r1₊…₊S_O``)."""
    found = _unknown_index(system).get((reactor_name, state))
    if found is not None:
        return found
    raise ValueError(
        f"Could not find state {state} on reactor {reactor_name} in the simulated model."
    )


def _state_reader(
    system: Any,
    reactor_name: str,
    state: str,
    fixed: dict[str, float] | None = None,
) -> Any:
    """A ``reader(integrator) -> float`` for one reactor's state.

    A state the reactor *holds fixed* (a biofilm unit's active biomass, say) is not an
    unknown of the simplified system at all, so there is no index to read. Its value is
    known at build time instead, and this returns a reader that hands that number back.
    Without this, any rule or ratio that touches a fixed state — ``COD/N`` on a trickling
    filter reads X_BH and X_BA — would fail to build.
    """
    from peepypoo import GetIndex

    try:
        return GetIndex(system, resolve_state_symbol(system, reactor_name, state))
    except ValueError:
        if fixed is not None and state in fixed:
            value = float(fixed[state])
            return lambda _integrator: value
        raise


# g TSS per g particulate COD — the ASM1/BSM1 conversion, also the one the MLSS seed uses.
TSS_PER_COD = 0.75
_PARTICULATES = ["X_I", "X_S", "X_BH", "X_BA", "X_P"]


# The states a derived measurement is computed from.
_COD_N_STATES = ["S_I", "S_S", "X_I", "X_S", "X_BH", "X_BA", "X_P", "S_NH", "S_ND", "X_ND"]


def _needs(what: str) -> list[str]:
    if what in _STATE_NAMES:
        return [what]
    if what == MLSS:
        return list(_PARTICULATES)
    if what == PH:
        return ["S_ALK"]
    if what.replace(" ", "").upper() in ("COD/N", "CODN", "COD:N"):
        return list(_COD_N_STATES)
    raise ValueError(f"cannot measure {what!r} (an ASM1 state, MLSS, COD/N or pH).")


def _combine(what: str, co2: float) -> Any:
    """``f(values by state) -> measurement`` for one measured quantity."""
    if what in _STATE_NAMES:
        return lambda v: v[what]
    if what == MLSS:
        return lambda v: TSS_PER_COD * sum(max(0.0, v[x]) for x in _PARTICULATES)
    if what == PH:
        return lambda v: ph_from_alkalinity(v["S_ALK"], co2)

    def ratio(v: dict[str, float]) -> float:
        w = {x: max(0.0, v[x]) for x in _COD_N_STATES}
        cod = sum(w[x] for x in _COD_STATES)
        tkn = (w["S_NH"] + w["S_ND"] + w["X_ND"]
               + _I_XB * (w["X_BH"] + w["X_BA"]) + _I_XP * w["X_P"])
        return cod / tkn if tkn > 1e-6 else 0.0
    return ratio


def measure_reader(
    system: Any,
    reactor_name: str,
    what: str,
    fixed: dict[str, float] | None = None,
    co2: float = DEFAULT_CO2_MMOL_L,
) -> Any:
    """``reader(integrator) -> float`` for one measurement in one tank.

    ``what`` is an ASM1 state, ``MLSS`` (suspended solids in g TSS/m³, from the particulate
    COD), ``COD/N`` (total COD over TKN) or ``pH`` (from S_ALK and the tank's ``co2``).
    """
    gets = {x: _state_reader(system, reactor_name, x, fixed) for x in _needs(what)}
    f = _combine(what, co2)
    return lambda integ: float(f({x: float(g(integ)) for x, g in gets.items()}))


def build_controller_callback(
    spec: ControllerSpec,
    system: Any,
    k_param: Any,
    t_end: float,
    fixed_by_model: dict[str, dict[str, float]] | None = None,
    cycle: Any = None,
    log: list[tuple[float, float]] | None = None,
    co2_by_model: dict[str, float] | None = None,
) -> list[Any]:
    """The callbacks that implement ``spec`` on ``system``.

    ``system`` must be the structurally-simplified ODESystem the solver will run (see the
    module docstring). ``k_param`` is the parameter the controller writes: the ``k`` of the
    ``Constant`` block on a reactor's aeration input, the flow of a ``FlowPump``, or the
    flow block of an influent. ``fixed_by_model`` carries, per tank, the states it holds
    fixed; ``co2_by_model`` the dissolved CO2 its pH estimate assumes.

    The rules are checked every ``spec.period`` days (a ``PeriodicCallback``). Switching
    exactly at a threshold crossing (a ``VectorContinuousCallback``) was tried and dropped:
    after such an event the solver re-initialises this DAE whatever ``u_modified`` says —
    the tank's oxygen jumped above saturation and the old pump flow kept running — and
    with re-initialisation switched off (``NoInit``) the step size collapses at the first
    switch. A short period does the job instead (see ``_PERIOD_MIN``).

    ``cycle`` (a ``CycleSpec``) confines a kLa controller to an SBR's react phase: outside
    it the kLa stays at 0, inside it the rules apply.

    ``log`` collects ``(t, value)`` each time the setting changes, so the result can show
    what the controller did.
    """
    import peepypoo as ppp
    from peepypoo import SetIndex, u_modified

    fixed_by_model = fixed_by_model or {}
    co2_by_model = co2_by_model or {}

    def model_of(r: Rule) -> str:
        return r.at_model or spec.reactor_name

    readers: dict[tuple[str, str], Any] = {}
    for r in spec.rules:
        key = (model_of(r), r.when)
        if r.when != _TIME and key not in readers:
            readers[key] = measure_reader(system, key[0], r.when, fixed_by_model.get(key[0]),
                                          co2_by_model.get(key[0], DEFAULT_CO2_MMOL_L))

    k_set = SetIndex(system, k_param)
    in_react = react_phase(cycle) if cycle is not None else None
    last: list[float | None] = [None]

    def write(integrator: Any, t: float, val: float) -> None:
        if val != last[0]:
            k_set(integrator, val)
            if log is not None:
                log.append((t, val))
        last[0] = val
        # The setting is a parameter, not a state: the ODE state u is unchanged, and saying
        # so keeps the solver from re-initialising the DAE, which resets the differential
        # states (see build_bypass_callback).
        u_modified(integrator, False)

    def evaluate(integrator: Any) -> None:
        t = float(integrator.t)
        if in_react is not None and not in_react(t):
            write(integrator, t, 0.0)
            return
        for r in spec.rules:
            left = t if r.when == _TIME else float(readers[(model_of(r), r.when)](integrator))
            if _OPS[r.op](left, r.value):
                write(integrator, t, float(min(spec.hi, max(spec.lo, r.set))))
                return
        if spec.hold and last[0] is not None:
            u_modified(integrator, False)
            return
        write(integrator, t, float(min(spec.hi, max(spec.lo, spec.base.value_at(t, t_end)))))

    return [ppp.PeriodicCallback(period=spec.period, affect=evaluate, initial_affect=True)]


def react_phase(cycle: Any, aerate_fill: bool = False) -> Any:
    """``t (days) -> bool``: whether an SBR's cycle is in its aerated window at ``t``.

    The same window ``build_cycle_callback`` switches on: from the end of fill to the end
    of react, repeating every ``cycle_h`` and shifted by ``offset_h``.
    """
    cycle_h = float(cycle.cycle_h)
    start = 0.0 if aerate_fill else float(cycle.fill_h)
    end = float(cycle.fill_h) + float(cycle.react_h)
    offset_h = float(cycle.offset_h)

    def inside(t: float) -> bool:
        phase = (t * 24.0 - offset_h) % cycle_h
        return start <= phase < end

    return inside


def summarize(spec: ControllerSpec) -> dict[str, Any]:
    """A JSON-safe description of what a controller will do each tick (for reports/UI)."""
    unit = f" {spec.unit}" if spec.unit else ""
    rules = "; ".join(r.describe(spec.target, unit) for r in spec.rules) or "(no rules)"
    return {
        "on": spec.owner_label,
        "target": spec.target,
        "target_text": spec.target_text,
        "unit": spec.unit,
        "period_days": spec.period,
        "rules": [r.as_dict() for r in spec.rules],
        "default": spec.base.describe(),
        "as_text": f"{spec.target_text}: {rules} — otherwise {spec.base.describe()}{unit}",
    }


# ---------------------------------------------------------------------------
# SBR cycle controller — aeration follows fill / react / settle / decant
#
# A real SBR also *fills and draws*, i.e. its volume changes over the cycle. PeePyPoo's
# CSTR has a fixed volume, so what is modelled here is the part of the cycle that drives
# the chemistry: the reactor is fed continuously (which is exactly what the staggered
# parallel SBRs of a real plant achieve — while one settles, its twin accepts the flow)
# and the **aeration follows the cycle clock**: on through the react phase, off through
# fill, settle and decant. Anoxic/anaerobic selector behaviour during fill therefore falls
# out of the model rather than being imposed.
#
# ``offset_h`` staggers one SBR against another, which is what makes a parallel bank of
# them smooth the load instead of pulsing in unison.

def build_cycle_callback(
    system: Any,
    kla_k_param: Any,
    cycle: Any,
    kla_react: float,
    t_end: float,
    kla_idle: float = 0.0,
    aerate_fill: bool = False,
) -> Any:
    """Callback that switches a reactor's kLa with the SBR phase clock.

    ``cycle`` is a ``server.topology.CycleSpec``. The aeration is a square wave: on for the
    react window, off for fill, settle and decant, repeating every ``cycle_h`` hours and
    shifted by ``offset_h``.

    It is a ``PresetTimeCallback`` on the **switch instants**, not a ``PeriodicCallback``
    polling a clock. Both produce the same square wave, but a poll fine enough to place the
    edges of the shortest phase would stop the stiff solver dozens of times per cycle for
    nothing — and each stop after a kLa jump is a restart. Firing twice per cycle is one to
    two orders of magnitude fewer stops over a multi-week run, and it puts each edge at
    exactly the right time instead of within a tick of it.
    """
    import peepypoo as ppp
    from peepypoo import SetIndex, u_modified

    cycle_h = float(cycle.cycle_h)
    if cycle_h <= 0:
        raise ValueError("cycle time must be positive.")
    fill_h = float(cycle.fill_h)
    react_h = float(cycle.react_h)
    offset_h = float(cycle.offset_h)

    react_start = 0.0 if aerate_fill else fill_h
    react_end = fill_h + react_h

    # The switch instants, in days, across the run, each paired with the kLa it switches to.
    on_at = (offset_h + react_start) / 24.0
    off_at = (offset_h + react_end) / 24.0
    step = cycle_h / 24.0
    schedule: list[tuple[float, float]] = []
    k = 0
    while True:
        t_on = on_at + k * step
        t_off = off_at + k * step
        if t_on > t_end and t_off > t_end:
            break
        for t, value in ((t_on, kla_react), (t_off, kla_idle)):
            if 0.0 < t <= t_end:
                schedule.append((t, value))
        k += 1
        if k > 100_000:                     # guard against a pathological cycle time
            break
    schedule.sort()
    times = [t for t, _ in schedule]
    values = [v for _, v in schedule]

    k_set = SetIndex(system, kla_k_param)

    def affect(integrator: Any) -> None:
        # The callback only ever fires at a scheduled instant, so the kLa to set is the one
        # scheduled *nearest* to where the solver landed.
        #
        # It used to look the instant up by float equality and, failing that, recompute the
        # phase from the clock. The solver does not land bit-exactly on the instant, and the
        # recomputed phase then sits right on a boundary, where a rounding error of 1e-12
        # puts it on either side: with the Sumo plant's 7.4 h cycle and 1.85 h stagger,
        # 47-56 % of the switch-*on* edges came out as "off", so about half the react phases
        # ran with no aeration at all.
        t = float(integrator.t)
        i = bisect.bisect_left(times, t)
        nearest = min((j for j in (i - 1, i) if 0 <= j < len(times)),
                      key=lambda j: abs(times[j] - t))
        k_set(integrator, float(values[nearest]))
        u_modified(integrator, False)

    if not times:
        # The run is shorter than one cycle: hold whatever phase t=0 is in.
        phase = (-offset_h) % cycle_h
        start = kla_react if react_start <= phase < react_end else kla_idle
        return ppp.PeriodicCallback(period=max(t_end, 1e-3),
                                    affect=lambda integ: (k_set(integ, float(start)),
                                                          u_modified(integ, False))[-1],
                                    initial_affect=True)
    return ppp.PresetTimeCallback(times, affect)


def describe_cycle(cycle: Any, kla_react: float) -> dict[str, Any]:
    """JSON-safe summary of an SBR cycle, for the setup report."""
    return {
        "cycle_h": float(cycle.cycle_h),
        "phases_h": {
            "fill": float(cycle.fill_h), "react": float(cycle.react_h),
            "settle": float(cycle.settle_h), "decant": float(cycle.decant_h),
        },
        "offset_h": float(cycle.offset_h),
        "kLa_react": float(kla_react),
        "as_text": (
            f"{cycle.cycle_h:g} h cycle (fill {cycle.fill_h:g} / react {cycle.react_h:g} / "
            f"settle {cycle.settle_h:g} / decant {cycle.decant_h:g} h"
            + (f", staggered +{cycle.offset_h:g} h" if cycle.offset_h else "")
            + f"), aerated at kLa {kla_react:g} 1/d during react"
        ),
    }


# ---------------------------------------------------------------------------
# Bypass controller — a flow split steered by a measured ratio
#
# Same mechanism as the aeration controller, but the manipulated variable is the ``k``
# of a ``FlowPump`` on a branch that routes flow *around* a stage, and the controlled
# variable is a ratio computed from several states (COD/N) rather than a single one.

# ASM1 → total COD is the sum of every COD-carrying state.
_COD_STATES = ["S_I", "S_S", "X_I", "X_S", "X_BH", "X_BA", "X_P"]
# TKN ≈ soluble + particulate organic N + the N bound in biomass and inert products.
# i_XB = 0.086 g N/g COD in biomass, i_XP = 0.06 g N/g COD in particulate products (ASM1).
_I_XB = 0.086
_I_XP = 0.06


def build_bypass_callback(
    spec: Any,
    system: Any,
    pump_k_param: Any,
    measure_reactor: str,
    fixed: dict[str, float] | None = None,
) -> Any:
    """``PeriodicCallback`` that sets a bypass pump's flow from a measured ratio.

    ``spec`` is a ``server.topology.BypassSpec``. ``when`` is either ``"COD/N"`` (the
    total-COD to TKN ratio of the measured reactor, the lever the reference plant uses to
    protect its nitrification from a COD surge) or a plain ASM1 state name. ``fixed``
    carries the states the measured reactor holds fixed — a biofilm unit's active biomass
    is not an unknown of the simplified system, but its value is known.
    """
    import peepypoo as ppp
    from peepypoo import SetIndex, u_modified

    if spec.when not in MEASURES and spec.when.replace(" ", "").upper() not in (
            "COD/N", "CODN", "COD:N"):
        raise ValueError(
            f"bypass 'when' must be COD/N, MLSS or an ASM1 state (got {spec.when!r})."
        )
    measured = measure_reader(system, measure_reactor, spec.when, fixed)
    k_set = SetIndex(system, pump_k_param)
    op = _OPS[spec.op]

    def affect(integrator: Any) -> None:
        try:
            value = measured(integrator)
        except Exception:
            return
        k_set(integrator, float(spec.flow if op(value, spec.value) else spec.base_flow))
        # The state is unchanged — only a parameter was written — and the integrator must
        # be told so. Without this call it re-initialises the system after every tick,
        # and the default re-initialisation does not just settle the algebraic flow
        # variables: it moves the *differential* states back onto a fixed consistent
        # point. Every reactor's concentrations were reset each tick and could never grow
        # beyond one controller period. Measured on the parallel-SBR demo: an inert
        # tracer sat at exactly 212.34 mg/L for 30 days (its true path climbs towards 491),
        # which read as a sludge age of 5.2 d against the 12 d the waste was sized for,
        # and froze the nitrifiers at their seed. With this call the tracer gives the sized
        # 12.00 d exactly, and the solve is 18x faster (3.0 s against 55.7 s). Restricting
        # the re-initialisation to algebraic variables (BrownFullBasicInit) instead fails
        # to initialise at all.
        u_modified(integrator, False)
    return ppp.PeriodicCallback(period=float(spec.period_days), affect=affect,
                                initial_affect=True)


def describe_bypass(spec: Any, around: str, measured_at: str) -> dict[str, Any]:
    """JSON-safe summary of a bypass controller, for the setup report."""
    return {
        "around": around,
        "measured_at": measured_at,
        "when": spec.when,
        "op": spec.op,
        "value": float(spec.value),
        "flow_m3_per_d": float(spec.flow),
        "base_flow_m3_per_d": float(spec.base_flow),
        "period_days": float(spec.period_days),
        "as_text": (
            f"if {spec.when} {spec.op} {spec.value:g} (measured at {measured_at}) then "
            f"route {spec.flow:g} m³/d around {around}, otherwise "
            f"{spec.base_flow:g} m³/d"
        ),
    }
