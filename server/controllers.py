"""Reactor controllers — "if concentration is X, aerate Y", plus time-based rules.

The frontend stores a small, structured controller on an aerated unit (see
``src/lib/controller.ts``)::

    {
      "period_days": 0.1,                 # how often the controller re-evaluates
      "rules": [
        {"when": "S_O", "op": "<", "value": 1.0, "set": 400},   # concentration rule
        {"when": "S_O", "op": ">", "value": 2.0, "set": 50},
        {"when": "t",   "op": "<", "value": 5.0, "set": 100}     # time-based rule
      ]
    }

Evaluation is first-match-wins, in listed order, every ``period_days`` of simulated
time; when no rule matches the base ``kLa`` (the unit's normal kLa field — a number,
a staged list, or a diurnal sine) is used. That keeps "bang-bang" control, setpoint
rules and SBR-style time scheduling in one tiny language with no syntax to learn.

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

import operator
from dataclasses import dataclass, field
from typing import Any, Iterable

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
_PERIOD_MIN = 1.0 / 96.0     # ~15 min — below this the solver starts to stall on callbacks
_PERIOD_MAX = 1.0            # cap per tick to at most one day
_PERIOD_DEFAULT = 0.1        # ~2.4 h, a good default control interval


@dataclass
class Rule:
    when: str      # a state name in _STATE_NAMES, or _TIME
    op: str        # one of _OPS
    value: float
    set: float

    def as_dict(self) -> dict[str, Any]:
        return {"when": self.when, "op": self.op, "value": self.value, "set": self.set}

    def describe(self) -> str:
        lhs = "time [d]" if self.when == _TIME else self.when
        return f"if {lhs} {self.op} {self.value:g} then kLa = {self.set:g}"


@dataclass
class ControllerSpec:
    """A validated controller for one reactor."""
    reactor_name: str             # the reactor's model name (e.g. "r1")
    base: TimeValue               # kLa to use when no rule matches
    rules: list[Rule] = field(default_factory=list)
    period: float = _PERIOD_DEFAULT


def _finite(x: Any) -> bool:
    try:
        return float(x) == float(x) and abs(float(x)) < 1e300
    except (TypeError, ValueError):
        return False


def parse_controller(
    node_data: dict | None,
    reactor_name: str,
    base: TimeValue,
) -> ControllerSpec | None:
    """Parse + validate a unit's ``data.controller``.

    ``base`` is the kLa to apply when no rule matches — the unit's normal kLa, already
    parsed into a ``TimeValue`` (number / staged list / diurnal sine).

    Returns ``None`` when there is no controller (so the caller keeps the plain kLa
    wiring). Raises ``ValueError`` with a human-readable message when the controller is
    present but malformed — the caller converts that to a ``SimError`` for the UI.
    """
    raw = (node_data or {}).get("controller")
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("must be an object with a 'rules' array.")

    rules_raw = raw.get("rules")
    if rules_raw is None:
        raise ValueError("has no 'rules'. Add at least one rule.")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ValueError("'rules' must be a non-empty list.")

    period = raw.get("period_days", _PERIOD_DEFAULT)
    try:
        period = float(period)
    except (TypeError, ValueError) as e:
        raise ValueError("'period_days' must be a number.") from e
    if not _finite(period) or period <= 0:
        raise ValueError("'period_days' must be a positive number of days.")
    period = min(max(period, _PERIOD_MIN), _PERIOD_MAX)

    rules: list[Rule] = []
    for i, r in enumerate(rules_raw, start=1):
        if not isinstance(r, dict):
            raise ValueError(f"rule {i} must be an object.")
        when = r.get("when")
        if when not in _STATE_NAMES and when != _TIME:
            raise ValueError(f"rule {i}: 'when' must be a state (S_O, S_NH, …) or t.")
        op = r.get("op")
        if op not in _OPS:
            raise ValueError(f"rule {i}: 'op' must be one of <, <=, >, >=.")
        value = r.get("value")
        if not _finite(value):
            raise ValueError(f"rule {i}: 'value' must be a number.")
        setv = r.get("set")
        if not _finite(setv):
            raise ValueError(f"rule {i}: 'set' (the kLa to apply) must be a number.")
        if float(setv) < 0:
            raise ValueError(f"rule {i}: kLa cannot be negative.")
        rules.append(Rule(when=str(when), op=str(op), value=float(value), set=float(setv)))

    return ControllerSpec(reactor_name=reactor_name, base=base, rules=rules, period=period)


# ---------------------------------------------------------------------------

def _state_symbol(system: Any, reactor_name: str, state: str) -> Any:
    """Find the resolved symbol for one reactor's state (e.g. ``r1₊…₊S_O``)."""
    def seg(u: Any) -> str:
        return str(u).split("₊")[-1].split("(")[0]

    for u in system.unknowns:
        if seg(u) == state and str(u).split("₊")[0] == reactor_name:
            return u
    raise ValueError(
        f"Could not find state {state} on reactor {reactor_name} in the simulated model."
    )


def build_controller_callback(
    spec: ControllerSpec,
    system: Any,
    kla_k_param: Any,
    t_end: float,
) -> Any:
    """Build the ``ppp.PeriodicCallback`` that implements ``spec`` on ``system``.

    ``system`` must be the structurally-simplified ODESystem the solver will run (see the
    module docstring). ``kla_k_param`` is the ``k`` parameter of the ``Constant`` block
    wired to the reactor's aeration input.
    """
    import peepypoo as ppp
    from peepypoo import GetIndex, SetIndex, u_modified

    state_gets: dict[str, Any] = {}
    for r in spec.rules:
        if r.when != _TIME and r.when not in state_gets:
            state_gets[r.when] = GetIndex(system, _state_symbol(system, spec.reactor_name, r.when))

    k_set = SetIndex(system, kla_k_param)

    def affect(integrator: Any) -> None:
        t = float(integrator.t)
        val = spec.base.value_at(t, t_end)
        for r in spec.rules:
            if r.when == _TIME:
                left = t
            else:
                left = float(state_gets[r.when](integrator))
            if _OPS[r.op](left, r.value):
                val = r.set
                break
        k_set(integrator, float(val))
        # kLa is a parameter, not a state: the ODE state u is unchanged, so this keeps the
        # integrator from wasting a derivative re-evaluation.
        u_modified(integrator, False)

    return ppp.PeriodicCallback(period=spec.period, affect=affect, initial_affect=True)


def summarize(spec: ControllerSpec) -> dict[str, Any]:
    """A JSON-safe description of what a controller will do each tick (for reports/UI)."""
    return {
        "period_days": spec.period,
        "rules": [r.as_dict() for r in spec.rules],
        "default": "kLa field: " + spec.base.describe(),
        "as_text": "; ".join(r.describe() for r in spec.rules) + (
            "" if spec.rules else " (no rules)") + f" — default {spec.base.describe()}"
    }
