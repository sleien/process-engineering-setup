#!/usr/bin/env python3
"""Generate ``examples/ph-controlled-feed.wwtp.json``.

An aerated CSTR fed a high-strength influent on pH: the feed runs while the pH in the tank
is below 6.20 and stops once it is above 6.25. Nitrification in the tank uses up
alkalinity and pulls the pH down; the influent (alkalinity 209 mmol/L, pH 8.61) brings it
back up. The controller checks every two minutes and holds its last setting between the
two thresholds — that hold is the hysteresis.

The influent analysis
---------------------

    DOC 1159 · TOC 13525 · N_sol 1958 · Cl 1430 · SO4 < 8 · Na 626 · NH4-N 1650 · K 4011
    COD_sol 3935 · COD_tot 70700 (mg/L) · alkalinity 209 mmol/L · pH 8.61

ASM1 wants its own states, so the analysis is fractionated here. What is measured goes in
as measured; what is not is an assumption, stated next to its constant below so it can be
changed in one place:

* ``S_S + S_I = COD_sol`` and ``X_S + X_I + X_BH = COD_tot - COD_sol`` — measured;
  how each is split is assumed (no BOD or respirometry in the analysis).
* ``S_NH = NH4-N`` and ``S_ND = N_sol - NH4-N`` — measured (no nitrate reported, so the
  rest of the soluble N is taken as organic).
* ``X_ND`` — no TKN was measured; the particulate organic N is assumed to be a share of
  the biodegradable particulate COD.
* ``S_ALK = 209`` — measured; ASM1 states alkalinity in mol/m³, which is mmol/L.
* Cl, SO4, Na, K and the influent pH have no ASM1 state; they are carried in the note.

The pH in the tank is estimated from its alkalinity (``server/controllers.py``, "pH"):
pH = pK1 + log10(S_ALK / CO2) with the dissolved CO2 the tank states (``CO2``, mmol/L).
At pH 6.2 and 1 mmol/L CO2 that is 0.66 mmol/L of alkalinity — a thin buffer, which is
why the controller checks every two minutes: at a 15-minute tick the pH in the tank swings
6.15-6.32, at two minutes 6.19-6.26.

Run it from the repo root:  python3 examples/build_ph_controlled.py
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

OUT = Path(__file__).resolve().parent / "ph-controlled-feed.wwtp.json"

# ---- The analysis (mg/L unless noted) -------------------------------------------------
COD_TOT = 70700.0
COD_SOL = 3935.0
NH4_N = 1650.0
N_SOL = 1958.0
ALKALINITY = 209.0       # mmol/L
PH_INFLUENT = 8.61

# ---- Assumptions for the ASM1 fractionation ------------------------------------------
F_SI_OF_SOLUBLE = 0.25   # soluble COD that is not biodegradable
F_XI_OF_PARTICULATE = 0.35   # particulate COD that is inert
F_XBH_OF_PARTICULATE = 0.05  # active heterotrophs carried in
N_OF_XS = 0.03           # g organic N per g biodegradable particulate COD

# ---- The reactor and the feed -------------------------------------------------------
V_TANK = 1.0             # m³ — a pilot tank
Q_ON = 0.2               # m³/d while the feed runs
KLA = 600.0              # 1/d — the strong aeration a 70 g/L COD feed needs
MLSS0 = 3000.0           # g/m³ the tank starts with
CO2 = 1.0                # mmol/L dissolved CO2 the pH estimate assumes
PH0 = 6.30               # starting pH: just above the band, so the feed starts off
PH_ON = 6.20             # feed on below this
PH_OFF = 6.25            # feed off above this
PERIOD_D = 2 / 1440      # check every 2 minutes: the buffer at pH 6.2 is thin


def fractionate() -> dict[str, float]:
    particulate = COD_TOT - COD_SOL
    s_i = F_SI_OF_SOLUBLE * COD_SOL
    x_i = F_XI_OF_PARTICULATE * particulate
    x_bh = F_XBH_OF_PARTICULATE * particulate
    x_s = particulate - x_i - x_bh
    return {
        "S_I": round(s_i, 1),
        "S_S": round(COD_SOL - s_i, 1),
        "X_I": round(x_i, 1),
        "X_S": round(x_s, 1),
        "X_BH": round(x_bh, 1),
        "X_BA": 0.0,
        "X_P": 0.0,
        "S_O": 0.0,
        "S_NO": 0.0,
        "S_NH": NH4_N,
        "S_ND": round(N_SOL - NH4_N, 1),
        "X_ND": round(N_OF_XS * x_s, 1),
        "S_ALK": ALKALINITY,
        "S_N2": 0.0,
    }


def unit(nid: str, unit_id: str, name: str, x: int, y: int, attrs: dict,
         extra: dict | None = None, w: int = 110, h: int = 90) -> dict:
    data = {"unitId": unit_id, "width": w, "height": h, "name": name,
            "attributes": {k: str(v) for k, v in attrs.items()}, "showAttrs": True}
    data.update(extra or {})
    return {"id": nid, "type": "unit", "position": {"x": x, "y": y}, "data": data}


def pipe(eid: str, src: str, dst: str, stream: str = "process") -> dict:
    return {"id": eid, "type": "pipe", "source": src, "sourceHandle": "right",
            "target": dst, "targetHandle": "left",
            "data": {"routing": "step", "streamType": stream, "showFlow": False}}


def text(tid: str, x: int, y: int, body: str) -> dict:
    # No underscores in the body: a text label reads "_" as a subscript.
    return {"id": tid, "type": "text", "position": {"x": x, "y": y},
            "data": {"text": textwrap.fill(body, 96), "fontSize": 13}}


def build() -> dict:
    feed = fractionate()
    controller = {
        "target": "Q",
        "otherwise": "hold",        # between 6.20 and 6.25: keep running, or keep stopped
        "period_days": PERIOD_D,
        "rules": [
            {"at": "cstr", "when": "pH", "op": "<", "value": PH_ON, "set": Q_ON},
            {"at": "cstr", "when": "pH", "op": ">", "value": PH_OFF, "set": 0},
        ],
    }
    nodes = [
        unit("influent", "influent", "High-strength influent", 0, 60,
             {"Q": Q_ON, **feed}, extra={"controllers": [controller]}, w=75, h=75),
        unit("cstr", "aerated_CSTR", "Nitrification CSTR", 220, 50,
             {"V": V_TANK, "MLSS": MLSS0, "kLa": KLA, "CO2": CO2, "pH0": PH0}),
        unit("effluent", "effluent", "Effluent", 440, 60, {}, w=75, h=75),
        text("note-control", 0, 230,
             f"pH-controlled feed: the influent runs at {Q_ON:g} m³/d while the pH in the "
             f"CSTR is below {PH_ON:.2f} and stops once it is above {PH_OFF:.2f}; in "
             "between it keeps doing what it did (hysteresis). The controller checks every "
             "two minutes. pH is estimated from the alkalinity with "
             f"{CO2:g} mmol/L dissolved CO2. Simulate 30 days (Run settings): the band holds "
             "from about day 1, the nitrifiers settle over weeks."),
        text("note-influent", 0, 320,
             "Influent analysis: COD 70700 (soluble 3935), TOC 13525, DOC 1159, NH4-N 1650, "
             "N soluble 1958, alkalinity 209 mmol/L, pH 8.61; Cl 1430, Na 626, K 4011, "
             "SO4 < 8 mg/L (no ASM1 state). The fractionation and its assumptions are in "
             "the generator script next to this example."),
    ]
    edges = [pipe("e-in", "influent", "cstr", "influent"),
             pipe("e-out", "cstr", "effluent", "effluent")]
    return {"version": 1, "nodes": nodes, "edges": edges,
            "viewport": {"x": 60, "y": 60, "zoom": 1.0}, "settings": {"scaleByFlow": False}}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1) + "\n")
    print(f"wrote {OUT.name}")
    print("  ASM1 influent:", fractionate())
