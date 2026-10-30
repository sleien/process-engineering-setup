#!/usr/bin/env python3
"""Generate ``examples/sumo-parallel-sbr.wwtp.json``.

The plant is the one in ``SUMO_examples/Dynamic_Decanting_COD_Bypass_Flow_Min_Threshold_Fixed.sumo``,
whose stored steady state is the acceptance target in ``examples/sumo_reference.json``.
The flowsheet below is read from the pipes in that project's ``sumoproject.plant``:

    municipal ─ screen ─┬─ (switch, pumped 3000) ─┐
                        │                         ├─ VKB ─┬─ TF 1+2 ─ TF 3+4 ─┐
    industrial ─ screen ┼─────────────────────────┘       └── COD bypass ─────┤
                        └─ (switch overflow) ───────────────── equalisation ──┴─ ZKB ─┐
                                                                                      │
                          ┌─ SBR street A (A1 + A2) ─┐                                │
                     ZKB ─┤                          ├─ aeration unit ─ effluent ◄────┘
                          └─ SBR street B (B1 + B2) ─┘

Both feeds meet ahead of the primary clarifier (VKB) and run through the two trickling
filters **in series**; the part of the municipal flow the switch does not pump, and the
COD bypass, go around the filters and meet their outflow ahead of the intermediate
clarifier (ZKB), which feeds two parallel SBR streets. That raw municipal overflow is what
gives the SBRs the carbon to denitrify the nitrate the filters make.

An earlier version of this generator followed a hand drawing of the plant instead, with
two parallel filter streets (municipal → filters 1+2 → SBR A, industrial → filters 3+4 →
SBR B) and no clarifiers. It matched Sumo only while the filters were modelled without
oxygen; once they were ventilated, street A received nitrified water with no carbon left
and the effluent TN went to 25.6 mg/L against Sumo's 6.6.

Sizing notes (why the numbers are not the Sumo nameplate numbers)
-----------------------------------------------------------------

A ``FlowPump`` in PeePyPoo holds a *fixed* flow, so every branch that is pumped has to
stay below what actually arrives at that split — at all times, not on average. Two things
follow:

* the industrial feed is given a **base load** between its weekly pulses instead of going
  to zero, which is also what a real industrial connection does; and
* the pumped side of each split is the **smaller** share, so the branch that closes the
  mass balance absorbs the swing — the municipal switch pumps its 3000 m³/d and the
  overflow takes the diurnal swing, exactly as in Sumo.

Sumo steers two of the splits with controllers this model does not reproduce one to one:
a PID moves the municipal switch to hold COD/N = 3 in the filter feed, and the COD bypass
is switched on flow thresholds. Here the switch is held at Sumo's 3000 m³/d target, and
the bypass runs at Sumo's normal 250 m³/d with a load-dependent step to 500 (see the
``bypass`` on the first filter).

This script exists because the ASM1 fractionation of the Sumo total-COD/TKN influents has
to be *computed*, not typed.

The industrial feed
-------------------

Sumo drives the industrial connection as a sharp weekly pulse: a base load for about seven
days, then roughly six hours at ~6000 m³/d. The attribute language has constants, linear
profiles and sinusoids but no modulo, so that shape is written here as a **sampled
profile** — the adapter hands it to the backend as a (values, times) pair and it is
interpolated there, which is why a profile this long is affordable.

A sampled profile is stretched across whatever horizon the run uses, so **simulate this
project with 21 days** or the pulses land on the wrong days. Set ``INDUSTRIAL_PULSE =
False`` for a weekly sinusoid of the same mean instead, which carries no such constraint
(and no shock either).

Run it from the repo root:  python3 examples/build_sumo_parallel.py
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

OUT = Path(__file__).resolve().parent / "sumo-parallel-sbr.wwtp.json"
REF = Path(__file__).resolve().parent / "sumo_reference.json"

# The run this example is built for. Three industrial pulses fit in it, and the final
# week is the one the acceptance rule in sumo_reference.json reads.
T_END_DAYS = 21.0
SAMPLE_DT = 0.125                      # resolution of the sampled influent profile (d)

# ---------------------------------------------------------------------------
# Influent fractionation: Sumo reports TCOD / TKN / TP, ASM1 wants its 14 states.


def fractionate(
    tcod: float, tkn: float, f_snh: float, *,
    f_si: float, f_ss: float, f_xi: float, f_xs: float, f_xbh: float,
    s_alk: float = 7.0,
) -> dict[str, float]:
    """Split a total COD / TKN pair into ASM1 states.

    The COD fractions are the usual municipal split (soluble inert, readily biodegradable,
    particulate inert, slowly biodegradable, active heterotrophs) and must sum to 1. The
    nitrogen left after ammonium and the N bound in the biomass (i_XB = 0.086 g N/g COD)
    is organic N, split 30 % soluble / 70 % particulate.
    """
    assert abs(f_si + f_ss + f_xi + f_xs + f_xbh - 1.0) < 1e-9, "COD fractions must sum to 1"
    x_bh = f_xbh * tcod
    s_nh = f_snh * tkn
    org_n = max(0.0, tkn - s_nh - 0.086 * x_bh)
    return {
        "S_I": round(f_si * tcod, 2),
        "S_S": round(f_ss * tcod, 2),
        "X_I": round(f_xi * tcod, 2),
        "X_S": round(f_xs * tcod, 2),
        "X_BH": round(x_bh, 2),
        "X_BA": 0.0,
        "X_P": 0.0,
        "S_O": 0.0,
        "S_NO": 0.0,
        "S_NH": round(s_nh, 2),
        "S_ND": round(0.30 * org_n, 2),
        "X_ND": round(0.70 * org_n, 2),
        "S_ALK": s_alk,
        "S_N2": 0.0,
    }


# Municipal: Sumo gives TCOD 538.72, TKN 42.25, fSNHx/TKN 0.5543.
# The soluble inert fraction is what survives to the effluent untouched, so it sets the
# floor on effluent COD; 2.5 % of TCOD puts that floor under the 41 mg/L Sumo target.
MUNICIPAL = fractionate(538.72, 42.25, 0.5543,
                        f_si=0.025, f_ss=0.225, f_xi=0.13, f_xs=0.58, f_xbh=0.04)
# Industrial: TCOD 1392, TKN 27.7, and fSCOD/TCOD = 0 — the whole load is particulate, so
# there is no soluble inert and no readily biodegradable COD at the inlet at all.
INDUSTRIAL = fractionate(1392.0, 27.7, 0.30,
                         f_si=0.0, f_ss=0.0, f_xi=0.10, f_xs=0.88, f_xbh=0.02)


INDUSTRIAL_PULSE = True      # True → sampled rectangular pulse, False → weekly sinusoid
PULSE_SAMPLE_DT = 0.125      # d — fine enough to place a 6 h pulse


def industrial_flow() -> str | list[float]:
    """The industrial feed: a weekly sinusoid, or the sampled pulse when asked for.

    The pulse is the default and is the faithful shape. **A sampled profile is stretched
    across whatever horizon the run uses**, so with ``INDUSTRIAL_PULSE`` on, simulate this
    project with ``time_days = 21`` or the pulses land on the wrong days. The sinusoid
    carries the same weekly mean and has no such constraint.
    """
    if not INDUSTRIAL_PULSE:
        amp = Q_IND_PEAK_SIN - Q_IND_BASE
        return f"{Q_IND_BASE:g}+{amp:g}*sin(2*pi*t/7)"
    n = int(round(T_END_DAYS / PULSE_SAMPLE_DT)) + 1
    return [Q_IND_PEAK if 3.0 <= (i * PULSE_SAMPLE_DT) % 7.0 < 3.25 else Q_IND_BASE
            for i in range(n)]


def _tss(feed: dict[str, float]) -> float:
    """Suspended solids (g/m³) of an ASM1 composition."""
    return COD_TO_TSS * sum(feed[s] for s in ("X_I", "X_S", "X_BH", "X_BA", "X_P"))


def industrial_mean_flow() -> float:
    """The industrial feed's time-mean, which is what the backend sizes branches with."""
    q = industrial_flow()
    return Q_IND_BASE if isinstance(q, str) else sum(q) / len(q)


def underflows() -> tuple[float, float]:
    """Sludge drawn off the VKB and the ZKB (m³/d), from the solids each removes.

    The ZKB sees the raw municipal overflow plus what the VKB lets through; the solids the
    filters slough are left out, because the filters keep and waste their own (f_ns 0.01
    of a few g/L adds well under 10 % to the ZKB load).
    """
    q_ind = industrial_mean_flow()
    q_vkb = Q_SWITCH + q_ind
    tss_vkb = (Q_SWITCH * _tss(MUNICIPAL) + q_ind * _tss(INDUSTRIAL)) / q_vkb
    qu_vkb = VKB_REMOVAL * q_vkb * tss_vkb / VKB_X_SLUDGE
    carry = (1.0 - VKB_REMOVAL) * q_vkb * tss_vkb
    q_over = Q_MUNI - Q_SWITCH
    solids_zkb = q_over * _tss(MUNICIPAL) + carry
    qu_zkb = ZKB_REMOVAL * solids_zkb / ZKB_X_SLUDGE
    return round(qu_vkb, 1), round(qu_zkb, 1)


# ---------------------------------------------------------------------------
# The drawing


def unit(nid: str, unit_id: str, name: str, x: int, y: int,
         attrs: dict | None = None, extra: dict | None = None,
         w: int = 110, h: int = 90) -> dict:
    data: dict = {"unitId": unit_id, "width": w, "height": h, "name": name,
                  "attributes": {k: (v if isinstance(v, str) else json.dumps(v)
                                     if isinstance(v, list) else str(v))
                                 for k, v in (attrs or {}).items()},
                  "showAttrs": True}
    data.update(extra or {})
    return {"id": nid, "type": "unit", "position": {"x": x, "y": y}, "data": data}


def pipe(eid: str, src: str, dst: str, flow: float | None = None,
         stream: str = "process", routing: str = "step",
         src_handle: str = "right", dst_handle: str = "left",
         name: str | None = None) -> dict:
    data: dict = {"routing": routing, "streamType": stream, "showFlow": flow is not None}
    if flow is not None:
        data["flow"] = flow
    if name:
        data["name"] = name
    return {"id": eid, "type": "pipe", "source": src, "sourceHandle": src_handle,
            "target": dst, "targetHandle": dst_handle, "data": data}


def text(tid: str, x: int, y: int, body: str, size: int = 13) -> dict:
    # Text nodes keep their line breaks and do not wrap, so a note is broken into lines
    # here — one long line makes "Fit" zoom out until the plant is too small to read.
    return {"id": tid, "type": "text", "position": {"x": x, "y": y},
            "data": {"text": textwrap.fill(body, 100), "fontSize": size}}


# Flows. The municipal feed carries the diurnal 6928 m³/d, the industrial feed its weekly
# pattern.
Q_MUNI = 6928.0          # municipal daily mean (diurnal, ±1300)
Q_MUNI_AMP = 1300.0
Q_IND_BASE = 1500.0      # industrial mean (and the base load between pulses)
Q_IND_PEAK = 6000.0      # the sampled pulse's level, when INDUSTRIAL_PULSE is on
Q_IND_PEAK_SIN = 2700.0  # the weekly sinusoid's peak (mean ± 1200)
Q_SWITCH = 3000.0        # municipal switch: pumped to the VKB (Sumo Qpumped_target)
Q_BYPASS_BASE = 250.0    # COD bypass around the filters, normal operation (Sumo MVbelow)
Q_BYPASS = 500.0         # ... while the first filter is overloaded with soluble COD
BYPASS_S_S = 5.0         # g/m³ readily biodegradable COD in filter 1+2 that trips it
Q_SPLIT_A = 4000.0       # pumped share of the ZKB outflow to street A (B takes the rest)
SBR_V_STREET = 4110.0    # total SBR volume per street (the Sumo plant's A and B)
SBR_SRT = 15.0
SBR_MLSS = 4200.0
SBR_KLA = 420.0
# Ammonia-based aeration, as in Sumo's SBRs: aerate to a 1.5 mg/L DO setpoint while NH4 is
# above 1.5 mg/L, stop once it is below. The cycle still allows aeration only in the react
# phase; inside it, the rules below decide (first match wins, else SBR_KLA). Without the
# NH4 switch the tanks aerate the whole react phase, nitrify everything and denitrify only
# in fill/settle/decant — 11.6 mg/L nitrate left in the effluent.
SBR_CONTROLLER = {"period_days": 0.01, "rules": [
    {"when": "S_NH", "op": "<", "value": 1.5, "set": 0},
    {"when": "S_O", "op": ">", "value": 1.8, "set": 60},
    {"when": "S_O", "op": "<", "value": 1.2, "set": 600},
]}
# Fraction of the SBR solids that does not settle and leaves with the decant. With no final
# clarifier this is what sets the effluent TSS: decant TSS ~ f_ns * 0.75 * MLSS. Sumo does
# not state it, so it is calibrated on the reference's 22 mg/L effluent TSS: 0.018 gave
# 15.3 mg/L once the SBRs ran on this flowsheet, so 0.018 * 22.24 / 15.3 = 0.026.
SBR_FNS = 0.026
TF_V = 3500.0            # 500 m² × 7.0 m, per the reference
TF_FILM = 2500.0         # biomass the filter holds (g/m³ of reactor volume)
TF_SRT = 25.0            # biofilm age — a nitrifying filter runs long
TF_RECIRC = 1.0          # internal return as a multiple of throughput
TF_FNS = 0.01            # solids the filter sloughs into its own outflow
# The filters carry no kLa: the backend's natural-draft default (240 1/d) applies, which
# holds a filter like these near the ~4 mg/L DO Sumo's filters run at.

# Primary (VKB) and intermediate (ZKB) clarifier, from the Sumo parameters: the share of
# incoming TSS each sends to its sludge (fXTSS_sludge) and the sludge concentration it
# thickens to (XTSS_sludge_target). The underflow follows from the solids it removes.
VKB_REMOVAL = 0.88
VKB_X_SLUDGE = 32611.0   # g TSS/m³
ZKB_REMOVAL = 0.42
ZKB_X_SLUDGE = 30838.0
COD_TO_TSS = 0.75        # g TSS per g particulate COD
POLISH_V = 250.0
POLISH_MLSS = 3000.0

# Cycle from sumo_reference.json: fill 1.5 / react 3.5 / settle 0.75 / decant 1.65 h.
CYCLE = {"cycle": 7.4, "fill": 1.5, "react": 3.5, "settle": 0.75, "decant": 1.65}

# How many SBR tanks to draw per street.
#
# The real plant has four (A1, A2, B1, B2), two per street. One per street is the default
# here because every settling unit carries an internal return loop, and the backend's
# `structural_simplify` grows sharply with the number of loops in one system: four SBRs
# plus two filters is six loops. With one per street, a tank stands for that
# street's SBR pair — the same 4110 m³ and the same cycle, with the A/B stagger that is
# what makes the bank accept flow continuously. Set this to 2 to draw all four; the
# staggers and the flow split follow, and the build takes considerably longer.
SBRS_PER_STREET = 1
# Stagger between consecutive tanks, as a fraction of the cycle.
STAGGER_FRACTION = 0.5


def sbr(nid: str, name: str, x: int, y: int, offset: float, volume: float) -> dict:
    return unit(nid, "sbr", name, x, y, {
        "V": volume, "MLSS": SBR_MLSS, "DO": 1.5, "SRT": SBR_SRT, "kLa": SBR_KLA,
        "f_ns": SBR_FNS, **CYCLE, "offset": round(offset, 3),
    }, extra={"controllers": [{"target": "kLa", **SBR_CONTROLLER}]})


def sbr_bank(street: str, x: int, y0: int, dy: int, street_index: int,
             volume_total: float) -> list[dict]:
    """One street's SBR tanks, staggered against each other and against the other street."""
    n = SBRS_PER_STREET
    step = CYCLE["cycle"] * STAGGER_FRACTION / max(1, n)
    base = street_index * CYCLE["cycle"] * STAGGER_FRACTION / 2.0
    return [
        sbr(f"sbr-{street.lower()}{i + 1}",
            f"SBR {street}{i + 1}" if n > 1 else f"SBR street {street}",
            x, y0 + i * dy, base + i * step, volume_total / n)
        for i in range(n)
    ]


def street_pipes(source: str, street: str, q_street: float, q_pumped: float) -> list[dict]:
    """Feed a street's SBR tanks and take their decant to the polishing stage.

    With more than one tank the split is `q_pumped` to every tank but the first; the first
    takes the rest of the street's flow.
    """
    ids = [f"sbr-{street}{i + 1}" for i in range(SBRS_PER_STREET)]
    free = q_street - q_pumped * (len(ids) - 1)
    out: list[dict] = []
    for i, nid in enumerate(ids):
        q = free if i == 0 else q_pumped
        out.append(pipe(f"e-{source}-{nid}", source, nid, round(q, 1)))
        out.append(pipe(f"e-{nid}-polish", nid, "polish", round(q, 1)))
    return out


def build() -> dict:
    nodes = [
        unit("influent-munc", "influent", "Municipal influent", 0, 60,
             {"Q": f"{Q_MUNI:g}+{Q_MUNI_AMP:g}*sin(2*pi*t/1)", **MUNICIPAL}, w=75, h=75),
        unit("influent-ind", "influent", "Industrial influent", 0, 520,
             {"Q": industrial_flow(), **INDUSTRIAL}, w=75, h=75),

        unit("screen-munc", "screen", "Coarse screen (municipal)", 160, 60,
             {"spacing": 20}, w=80, h=90),
        unit("screen-ind", "screen", "Coarse screen (industrial)", 160, 520,
             {"spacing": 20}, w=80, h=90),

        # Primary clarifier: both feeds meet here. Sumo removes 88 % of the TSS in it,
        # which takes most of the industrial load (all of it particulate) out before the
        # filters.
        unit("vkb", "primary_clarifier", "VKB (primary clarifier)", 300, 300,
             {"removal": VKB_REMOVAL, "Qu": QU_VKB}, w=75, h=67),

        # The two filter pairs run in series. The first carries the COD bypass: Sumo's
        # side pump right after the VKB, whose diverted flow skips both filters and
        # rejoins ahead of the ZKB. Its normal 250 m³/d steps up to 500 m³/d while the
        # first filter is overloaded with readily biodegradable COD. (Measured as S_S in
        # the filter, not as total COD/N there: the filter's own biomass puts that ratio
        # above 20 at all times, so a COD/N > 3 rule would never switch off.)
        unit("tf-1", "trickling_filter", "Trickling filters 1 + 2", 440, 280,
             {"V": TF_V, "MLSS": TF_FILM, "SRT": TF_SRT, "recirc": TF_RECIRC,
              "f_ns": TF_FNS, "area": 500},
             extra={"bypass": {
                 "when": "S_S", "op": ">", "value": BYPASS_S_S,
                 "flow": Q_BYPASS, "base_flow": Q_BYPASS_BASE,
                 # Slow enough not to chatter: diverting flow is a load-shifting move,
                 # not a trim, and every change re-initialises the DAE.
                 "period_days": 0.1, "rejoin_at": "zkb",
             }},
             w=130, h=120),
        unit("tf-2", "trickling_filter", "Trickling filters 3 + 4", 620, 280,
             {"V": TF_V, "MLSS": TF_FILM, "SRT": TF_SRT, "recirc": TF_RECIRC,
              "f_ns": TF_FNS, "area": 500},
             w=130, h=120),

        unit("eq", "equalization_basin", "Equalization basin", 800, 90,
             {"V": 1000}, w=110, h=80),
        unit("zkb", "primary_clarifier", "ZKB (intermediate clarifier)", 840, 300,
             {"removal": ZKB_REMOVAL, "Qu": QU_ZKB}, w=75, h=67),

        *sbr_bank("A", 1000, 140, 180, 0, SBR_V_STREET),
        *sbr_bank("B", 1000, 460, 180, 1, SBR_V_STREET),

        # Polishing: a small aerated CSTR held at the Sumo plant's 2.0 mg/L DO setpoint by
        # a two-rule bang-bang controller on the aeration.
        unit("polish", "aerated_CSTR", "Polishing aeration", 1200, 300,
             {"V": POLISH_V, "MLSS": POLISH_MLSS, "DO": 2, "kLa": 250},
             # Two things about this controller matter for whether the model solves at
             # all, and both were found the hard way:
             #
             #  * a **deadband** around the 2.0 mg/L setpoint rather than a single
             #    threshold — two rules flipping at the same value chatter, switching on
             #    every tick and restarting the stiff solver each time (8 s against 0.1 s
             #    on a single aerated tank over three weeks);
             #  * a **period under the tank's residence time** — this tank holds 250 m3
             #    and passes 8588 m3/d, so it empties every 42 min. At the 0.05 d (72 min)
             #    period used at first, the controller ran open loop for more than a
             #    residence time and the solve aborted at t = 2 d, retcode Unstable.
             #    0.005 d solves the full 21 d.
             extra={"controllers": [{"target": "kLa", "period_days": 0.005, "rules": [
                 {"when": "S_O", "op": ">", "value": 2.5, "set": 60},
                 {"when": "S_O", "op": "<", "value": 1.5, "set": 600},
             ]}]}),

        # No final clarifier: the Sumo plant has none. The SBRs decant clarified water,
        # the polishing tank aerates it, and what the effluent carries in solids is what
        # does not settle in the SBRs (their f_ns). An earlier version of this example added
        # a final clarifier, which stripped exactly those solids — and with them two thirds
        # of the effluent COD the reference reports.
        unit("effluent", "effluent", "Treated effluent", 1370, 310, w=75, h=75),
        unit("sludge-was", "sludge", "Waste sludge", 840, 720, w=75, h=75),

        text("note-topology", 160, 820,
             "Sumo flowsheet: municipal and industrial feed meet at the primary clarifier "
             "(VKB) and pass trickling filters 1+2 and 3+4 in series; the municipal "
             f"overflow (everything above the switch's {Q_SWITCH:g} m³/d) and the COD "
             "bypass go around them to the intermediate clarifier (ZKB), which feeds two "
             f"parallel SBR streets. Every SBR runs the same {CYCLE['cycle']:g} h cycle, "
             "staggered against the other street.", 14),
        text("note-bypass", 160, 900,
             f"COD bypass: {Q_BYPASS_BASE:g} m³/d around both filters to the ZKB, "
             f"{Q_BYPASS:g} m³/d while readily biodegradable COD in filters 1+2 exceeds "
             f"{BYPASS_S_S:g} mg/L. Filters ventilated by natural draft (backend default "
             "kLa).", 14),
        text("note-run", 160, 960,
             f"Run this project with a {T_END_DAYS:g} day horizon: the industrial feed is "
             "a sampled weekly pulse stretched across the simulated window, so a shorter "
             "run moves the pulses.", 14),
    ]

    q_ind = industrial_mean_flow()
    q_total = Q_MUNI + q_ind
    q_zkb_out = q_total - QU_VKB - QU_ZKB

    edges = [
        pipe("e-munc-screen", "influent-munc", "screen-munc", Q_MUNI, "influent"),
        pipe("e-ind-screen", "influent-ind", "screen-ind", round(q_ind, 1), "influent"),
        # The municipal switch: a side pump sends Q_SWITCH to the VKB, the overflow goes
        # around the biology's first stage.
        pipe("e-switch", "screen-munc", "vkb", Q_SWITCH, name="Municipal switch"),
        pipe("e-overflow", "screen-munc", "eq", round(Q_MUNI - Q_SWITCH, 1),
             src_handle="top", dst_handle="left", name="Overflow"),
        pipe("e-ind-vkb", "screen-ind", "vkb", round(q_ind, 1)),
        pipe("e-vkb-tf1", "vkb", "tf-1", round(Q_SWITCH + q_ind - QU_VKB, 1)),
        pipe("e-tf1-tf2", "tf-1", "tf-2", round(Q_SWITCH + q_ind - QU_VKB, 1)),
        pipe("e-tf2-eq", "tf-2", "eq", round(Q_SWITCH + q_ind - QU_VKB, 1)),
        pipe("e-eq-zkb", "eq", "zkb", round(q_total - QU_VKB, 1)),

        *street_pipes("zkb", "a", Q_SPLIT_A, Q_SPLIT_A / max(1, SBRS_PER_STREET)),
        *street_pipes("zkb", "b", q_zkb_out - Q_SPLIT_A,
                      (q_zkb_out - Q_SPLIT_A) / max(1, SBRS_PER_STREET)),

        pipe("e-polish-eff", "polish", "effluent", round(q_zkb_out, 1), "effluent"),
        # Drawn for completeness: the clarifiers' underflows and the SBRs' waste leave
        # through the model's own sludge pumps, so these lines carry no flow of their own.
        pipe("e-vkb-sludge", "vkb", "sludge-was", None, "sludge",
             src_handle="bottom", dst_handle="left", name="Primary sludge"),
        pipe("e-zkb-sludge", "zkb", "sludge-was", None, "sludge",
             src_handle="bottom", dst_handle="top", name="Intermediate sludge"),
        pipe("e-was", "sbr-b1", "sludge-was", None, "sludge",
             src_handle="bottom", dst_handle="right", name="WAS"),
    ]

    return {"version": 1, "nodes": nodes, "edges": edges,
            "viewport": {"x": 40, "y": 20, "zoom": 0.55},
            "settings": {"scaleByFlow": True}}


QU_VKB, QU_ZKB = underflows()


if __name__ == "__main__":
    project = build()
    OUT.write_text(json.dumps(project, indent=1) + "\n")
    ref = json.loads(REF.read_text())
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")
    print(f"  {len(project['nodes'])} nodes, {len(project['edges'])} edges")
    print(f"  municipal ASM1 feed: {MUNICIPAL}")
    print(f"  industrial ASM1 feed: {INDUSTRIAL}")
    print(f"  underflows: VKB {QU_VKB} m³/d, ZKB {QU_ZKB} m³/d")
    print(f"  acceptance targets:  {ref['effluent_target']}")
