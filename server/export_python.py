"""Export a diagram as a standalone Python script that runs its simulation anywhere.

The script carries everything it needs except PeePyPoo itself:

* the plant — the same units, pipes and run settings the app would send to
  ``/api/simulate``, written out as a Python literal at the top so it can be read and
  edited;
* the model adapter of this server (``timeseries``, ``topology``, ``controllers`` and
  ``simulate``), embedded verbatim. The script therefore builds and solves exactly the model
  the app builds — a generated, hand-flattened PeePyPoo program would be a second
  implementation, and the two would drift.

On the other machine it needs Python 3.11+ and ``pip install peepypoo==1.0.4``; the first
run installs Julia and its packages. It writes the same result object the app receives
(``result.json``), the time series as CSV, and prints the effluent.
"""

from __future__ import annotations

import base64
import pprint
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any

_SERVER = Path(__file__).resolve().parent
# Embedded in dependency order: each module only imports the ones before it.
ADAPTER_MODULES = ["timeseries", "topology", "controllers", "simulate"]
PEEPYPOO_VERSION = "1.0.4"


def _pack(text: str) -> str:
    """Compress and base64 a module source, wrapped at 100 columns for the script."""
    raw = base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode("ascii")
    return "\n".join(raw[i:i + 100] for i in range(0, len(raw), 100))


def python_script(
    units: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    time_days: float | None,
    influent_flow: float | None,
    influent_overrides: dict[str, float] | None,
    app_version: str,
    name: str = "plant",
) -> str:
    """The text of the standalone script for one diagram and its run settings."""
    plant = {"units": units, "edges": edges}
    settings = {
        "time_days": time_days,
        "influent_flow": influent_flow,
        "influent_overrides": influent_overrides or {},
    }
    modules = {m: _pack((_SERVER / f"{m}.py").read_text(encoding="utf-8"))
               for m in ADAPTER_MODULES}
    module_lines = ",\n".join(f'    "{m}": """\n{src}\n"""' for m, src in modules.items())
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    reactors = [u for u in units if (u.get("data") or {}).get("unitId") not in
                ("influent", "effluent", "sludge", "screen", "equalization_basin", "junction")]

    return f'''#!/usr/bin/env python3
"""{name} — simulation exported from WWTP Designer v{app_version} on {stamp}.

Runs the same model the app runs: the diagram below, built into a PeePyPoo / ASM1 model by
the app's own adapter (embedded at the end of this file) and solved with PeePyPoo.
{len(units)} units ({len(reactors)} reactors and settlers), {len(edges)} pipes.

Setup on the machine that runs it (Python 3.11 or newer):

    python3 -m venv .venv
    .venv/bin/pip install peepypoo=={PEEPYPOO_VERSION}

The first run installs Julia and the packages PeePyPoo needs — several minutes, once.

Run:

    .venv/bin/python {name}.py                    # the run settings below
    .venv/bin/python {name}.py --days 30          # another horizon
    .venv/bin/python {name}.py --out results/run1 # where the results go

It writes

    <out>/result.json   everything the app's results window shows (series, reactors,
                        controller outputs, warnings, setup) — the /api/simulate answer
    <out>/series.csv    one row per time, location and state

and prints the effluent at the end of the run. Change the plant by editing PLANT (each
unit's "attributes" are the fields of the app's properties panel) or SETTINGS.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import sys
import time
import types
import zlib
from pathlib import Path

# ---- The plant: the units and pipes as the app sends them to its simulator ------------

PLANT = {pprint.pformat(plant, width=100, sort_dicts=False)}

# ---- Run settings (the app's "Run settings") --------------------------------------------
# time_days: simulated days (None = the app's automatic rule); influent_flow: overrides the
# flow of a plant without an Influent unit; influent_overrides: replaces states of the first
# influent's composition.

SETTINGS = {pprint.pformat(settings, width=100, sort_dicts=False)}


def load_adapter():
    """Install the embedded adapter as a package and return its ``simulate`` module."""
    package = "wwtp_designer_adapter"
    pkg = types.ModuleType(package)
    pkg.__path__ = []
    sys.modules[package] = pkg
    for name in {ADAPTER_MODULES!r}:
        source = zlib.decompress(base64.b64decode("".join(_ADAPTER[name].split()))).decode()
        module = types.ModuleType(f"{{package}}.{{name}}")
        module.__package__ = package
        module.__file__ = f"<{{package}}/{{name}}.py>"
        sys.modules[module.__name__] = module
        setattr(pkg, name, module)
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    return sys.modules[f"{{package}}.simulate"]


def write_series_csv(result: dict, path: Path) -> None:
    labels = {{f"r{{r['index']}}": r["label"] for r in result["reactors"]}}
    labels["eff"] = "Effluent"
    t = result["t_days"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_days", "location", "state", "value"])
        for key, block in result["series"].items():
            for state, values in block.items():
                for ti, v in zip(t, values):
                    w.writerow([ti, labels.get(key, key), state, v])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=SETTINGS["time_days"],
                    help="simulated days (default: the exported run settings)")
    ap.add_argument("--out", type=Path, default=Path("{name}_results"),
                    help="directory for result.json and series.csv")
    args = ap.parse_args()

    sim = load_adapter()
    print(f"Simulating {{len(PLANT['units'])}} units for "
          f"{{args.days if args.days else 'the automatic'}} days …", flush=True)
    t0 = time.time()
    try:
        result = sim.build(
            PLANT["units"], PLANT["edges"],
            time_days=args.days,
            influent_flow=SETTINGS["influent_flow"],
            influent_overrides=SETTINGS["influent_overrides"] or None,
        )
    except sim.SimError as e:
        print(f"The simulation failed: {{e}}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "result.json").write_text(json.dumps(result), encoding="utf-8")
    write_series_csv(result, args.out / "series.csv")

    eff = result["series"].get("eff", {{}})
    print(f"Solved in {{time.time() - t0:.0f}} s, {{result['t_end_days']}} d simulated.")
    print("Effluent at the end (mg/L):  " + "  ".join(
        f"{{s}} {{eff[s][-1]:.2f}}" for s in ("S_NH", "S_NO", "S_S", "S_O") if s in eff))
    for w in result["warnings"]:
        print(" -", w)
    print(f"Results in {{args.out}}/")
    return 0


# ---- The app's model adapter (server/{{timeseries,topology,controllers,simulate}}.py) -----
# Compressed so this file stays one piece; decoded and run by load_adapter() above.

_ADAPTER = {{
{module_lines}
}}

if __name__ == "__main__":
    sys.exit(main())
'''
