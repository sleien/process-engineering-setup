"""Parse attribute values into something the PeePyPoo model can drive over time.

Three supported forms (for Influent `Q`, composition states, reactor `kLa`, …):

  1. A number                → constant, e.g.  2000
  2. A JSON list of numbers  → a linear (piecewise/staged) profile across the run,
                              e.g.  [1500, 800, 2500]   (first at t=0, last at t_end)
  3. A sinusoid              → the standard diurnal/seasonal pattern, e.g.
                              1500 + 500*sin(2*pi*t/24)   (daily cycle)
                               80  *sin(2*pi*t/365)       (annual cycle)
                               1200 + 200*sin(t*0.5 + 1.2)

Why these three only
--------------------

PeePyPoo drives a `TimeVaryingFunction` by *symbolically differentiating* the
expression at model-build time — every call back into us receives a Julia
`Symbolics.Num`, not a number. So:

  * C-extension functions (the whole `math` module) raise on symbolic input;
  * `float()` / `int()` coercion of the argument fails too;
  * only *pure-Python arithmetic* (+ − × ÷ ** , `min`/`max`) and the pure-Python
    `sin` here survive both the symbolic build and the numeric solve.

Those are exactly the operations used by the three forms above: constants are
numbers, linear profiles are built from `min`/`max` ramps, and sinusoids from the
pure-Python `sin`. That covers the realistic WWTP time variation (constant,
staged/linear profiles, diurnal and seasonal cycles); anything else is rejected
with a clear message instead of failing mid-solve.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable


class TimeValueError(Exception):
    """Raised when an attribute value is not a number, a list, or a valid sinusoid."""


_PI = 3.141592653589793
_MAX_T_DAYS = 90.0


# ---- pure-Python trig (works on both Symbolics.Num and floats) ----------------
# sin/cos via 2^5 halvings + 40-term Taylor, folded back with the double-angle
# identity — pure arithmetic only, so it's valid symbolically and numerically.

def _taylor_sin(x: Any, n: int) -> Any:
    s, term, sign = x, x, -1
    for k in range(1, n):
        term = term * x * x / ((2 * k) * (2 * k + 1))
        s = s + sign * term
        sign = -sign
    return s


def _taylor_cos(x: Any, n: int) -> Any:
    s, term, sign = 1, 1, -1
    for k in range(1, n):
        term = term * x * x / ((2 * k - 1) * (2 * k))
        s = s + sign * term
        sign = -sign
    return s


def _sc(x: Any) -> tuple[Any, Any]:
    y = x
    for _ in range(5):
        y = y / 2
    s, c = _taylor_sin(y, 40), _taylor_cos(y, 40)
    for _ in range(5):
        s, c = 2 * s * c, c * c - s * s
    return s, c


def sin(x: Any) -> Any:
    return _sc(x)[0]


def cos(x: Any) -> Any:
    return _sc(x)[1]


def tan(x: Any) -> Any:
    return sin(x) / cos(x)


# ---- the three TimeValue kinds --------------------------------------------------

class TimeValue:
    """Parsed attribute: ``const`` | ``list`` (linear profile) | ``sine``."""

    def __init__(self, kind: str, const: float | None = None,
                 values: list[float] | None = None, sine: dict | None = None):
        self.kind = kind
        self.const = const
        self.values = values
        self.sine = sine

    @property
    def is_constant(self) -> bool:
        return self.kind == "const"

    @property
    def time_dependent(self) -> bool:
        return self.kind != "const"

    def describe(self) -> str:
        if self.kind == "const":
            return f"constant {self.const:g}"
        if self.kind == "list":
            return ("linear profile: ["
                    + ", ".join(f"{v:g}" for v in (self.values or [])) + "]")
        s = self.sine or {}
        return (f"sinusoid {s.get('offset', 0):g} + {s.get('amp', 0):g}·sin("
                f"{s.get('omega', 0):g}·t"
                + (f" + {s['phase']:g}" if s.get('phase') else "") + ")")

    # -- numeric value at a concrete time (float) — for reports & UI preview --
    def value_at(self, t: float, t_end: float = _MAX_T_DAYS) -> float:
        return float(self._fn_at(float(t), float(t_end)))

    def _fn_at(self, t: float, t_end: float = _MAX_T_DAYS) -> float:
        if self.kind == "const":
            return float(self.const or 0.0)
        if self.kind == "list" and self.values is not None:
            p = self.values
            n = len(p)
            if n == 1:
                return float(p[0])
            T = max(t_end, 1e-9)
            # same min/max ramps as the model function (no int/float on t needed)
            k = [T * i / (n - 1) for i in range(n)]
            v = float(p[0])
            for i in range(1, n):
                denom = (k[i] - k[i - 1]) or 1.0
                ramp = min(max((t - k[i - 1]) / denom, 0.0), 1.0)
                v += (float(p[i]) - float(p[i - 1])) * ramp
            if t >= T:
                return float(p[-1])
            return v
        s = self.sine or {}
        return float(s.get("offset", 0.0) + s.get("amp", 0.0)
                     * math.sin(s.get("omega", 0.0) * t + s.get("phase", 0.0)))

    # -- a Python closure f(x) the model drives with (symbol-safe operations) --
    def to_function(self, t_end: float) -> Callable[[float], float] | float:
        if self.kind == "const":
            return self.const if self.const is not None else 0.0

        if self.kind == "list":
            p = [float(v) for v in (self.values or [])]
            n = len(p)
            T = float(t_end)
            if n == 0:
                return 0.0
            if n == 1:
                return p[0]
            k = [T * i / (n - 1) for i in range(n)]

            def f(x):
                v = p[0]
                for i in range(1, n):
                    ramp = min(max(((x - k[i - 1]) / (k[i] - k[i - 1])), 0.0), 1.0)
                    v = v + (p[i] - p[i - 1]) * ramp
                return v
            return f

        s = self.sine or {}
        off, amp, om, ph = (float(s.get("offset", 0.0)), float(s.get("amp", 0.0)),
                            float(s.get("omega", 0.0)), float(s.get("phase", 0.0)))

        def f(x):
            return off + amp * sin(om * x + ph)
        return f


# ---- sinusoid parser -----------------------------------------------------------
# OFFSET + AMP*sin(OMEGA*t ± PHASE), OMEGA a number or 2*pi/PERIOD.
_SINE_RE = re.compile(
    r"""^\s*
        (?:(?P<off0>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*\+\s*)?           # OFFSET +
        (?P<amp>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*\*\s*sin\s*\(\s*       # AMP*sin(
        (?:
            (?P<om>\d*\.?\d+(?:[eE][-+]?\d+)?)\s*\*?\s*t
            |
            2\s*\*\s*pi\s*\*\s*t\s*/\s*(?P<per>\d*\.?\d+(?:[eE][-+]?\d+)?)
            |
            t\s*/\s*(?P<invper>\d*\.?\d+(?:[eE][-+]?\d+)?)
        )
        (?:\s*[-+]\s*(?P<ph>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?))?           # ± PHASE
        \s*\)
        (?:\s*\+\s*(?P<off1>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?))?           # + OFFSET
        \s*$""",
    re.VERBOSE,
)


def _num(x: str | None) -> float | None:
    return float(x) if x is not None else None


def _parse_sine(s: str) -> dict:
    m = _SINE_RE.match(s)
    if not m:
        raise TimeValueError(
            "Not a supported sinusoid. Expected the shape  OFFSET + AMP*sin(Omega*t ± PHASE), "
            "e.g.  1500 + 500*sin(2*pi*t/24)  or  80*sin(2*pi*t/365)."
        )
    amp = _num(m.group("amp"))
    if amp is None:
        raise TimeValueError("Sinusoid amplitude is required (the number before sin()).")
    if m.group("per") is not None:
        omega = 2 * _PI / float(m.group("per"))
    elif m.group("invper") is not None:
        omega = 1.0 / float(m.group("invper"))
    else:
        g = (m.group("om") or "1").strip().rstrip("t").strip()
        omega = float(g) if g else 1.0
    offset = _num(m.group("off0"))
    if offset is None:
        offset = _num(m.group("off1")) or 0.0
    if omega == 0:
        raise TimeValueError("Sinusoid angular frequency is zero (no variation over time).")
    return {"offset": float(offset), "amp": float(amp), "omega": float(omega),
            "phase": float(_num(m.group("ph")) or 0.0)}


# ---- public parser -------------------------------------------------------------

def parse_time_value(raw: Any) -> TimeValue:
    """Parse one attribute value. Raises TimeValueError on unsupported input."""
    if raw is None:
        raise TimeValueError(
            "Value is empty. Give a number, a list like [1, 2, 3], or a sinusoid "
            "like 1500 + 500*sin(2*pi*t/24).")
    if isinstance(raw, bool):
        raise TimeValueError("Booleans are not allowed here.")
    if isinstance(raw, (int, float)):
        return TimeValue("const", const=float(raw))
    if isinstance(raw, (list, tuple)):
        vals: list[float] = []
        for v in raw:
            try:
                vals.append(float(v))
            except (TypeError, ValueError) as e:
                raise TimeValueError("List items must be numbers, e.g. [1500, 2000, 1200].") from e
        if not vals:
            raise TimeValueError("List must contain at least one number.")
        return TimeValue("list", values=vals)

    if not isinstance(raw, str):
        raise TimeValueError("Value must be a number, a list, or a sinusoid formula.")

    s = raw.strip()
    if not s:
        raise TimeValueError("Value is empty.")

    # 1) JSON list of numbers
    if s.startswith("[") and s.endswith("]"):
        import json
        try:
            items = json.loads(s)
        except json.JSONDecodeError as e:
            raise TimeValueError("List must be JSON numbers, e.g. [1500, 2000, 1200].") from e
        if (not isinstance(items, list) or not items or
                not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in items)):
            raise TimeValueError("List must contain at least one number, e.g. [1500, 2000, 1200].")
        return TimeValue("list", values=[float(v) for v in items])

    # 2) plain number
    if re.fullmatch(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s):
        return TimeValue("const", const=float(s))

    # 3) sinusoid
    if "sin" in s:
        return TimeValue("sine", sine=_parse_sine(s))

    raise TimeValueError(
        "Unsupported value. Use a number, a list like [1500, 2000, 1200], or a sinusoid "
        "like 1500 + 500*sin(2*pi*t/24).")
