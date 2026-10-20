# WWTP Designer

A small React + TypeScript web app for drawing wastewater-treatment process-flow diagrams
from a palette of unit SVGs — units connected by arrows, with recycle/branch lines and text
labels, exportable to vector SVG / PNG.

## Run

```bash
npm install      # first time only
npm run dev      # start the dev server → http://localhost:5173
```

Other scripts: `npm run build` (production build to `dist/`), `npm run preview` (serve the
build), `npm run typecheck` (TypeScript check, no emit).

With the simulation backend set up (see [Simulation](#simulation-peepypoo--asm1)) you can also
run one server that serves both the UI and the simulator on a single port:

```bash
npm run server   # builds dist/ then serves UI + /api/simulate on http://localhost:8080
```

## How to use

- **Add a unit** — drag any item from the left **Units** palette onto the canvas.
- **Connect units** — hover a unit to reveal its four blue ports, then drag from a port to a
  port on another unit. The arrow stays attached when you move either unit.
- **Tap into the middle of an arrow** (e.g. a recycle line returning to the influent):
  drag a new arrow from a port and **drop it onto an existing arrow** — a junction dot is
  inserted there and the arrow connects to it. You can also **double-click an arrow** to drop a
  junction. Deleting a pass-through junction re-joins the line. Hit-testing follows each pipe's
  **visible line**, so you can tap an **Orthogonal** pipe along its bent run, not just the straight
  chord between its ends.
- **Branch an arrow off an arrow** (e.g. sludge wastage): **press on a pipe and drag away from
  it**. A junction is dropped where you started and a new arrow follows the cursor — release it
  on a unit, on another pipe, or on empty canvas to leave an open outlet dot (label it "WAS").
  This works along a pipe's **visible line**, including an **Orthogonal** pipe's bent run — so you
  can branch a WAS line straight off the sludge recycle running under a clarifier, and the junction
  sits exactly where you pressed.
- **Text labels** — click **+ Text**, then double-click to edit. Labels support LaTeX-style
  scripts: `^` = superscript, `_` = subscript, with `{}` to group several characters —
  e.g. `m^3` → m³, `X_s`, `k_{s,xy}`, `Q_{RAS}`. (Enter commits, Esc cancels, Shift+Enter = newline.)
- **Pipe routing** — new pipes are **Orthogonal** by default (good for recycle lines that run
  along the bottom); select an arrow and choose **Straight** or **Orthogonal** to change it.
- **Hand mode (route pipes)** — click **✋ Hand** in the toolbar, then drag any pipe to move it
  — e.g. pull a **sludge recirculation** line down so it runs along the bottom. While Hand mode
  is on, each pipe shows a round **depth handle** you grab (hidden otherwise). The pipe's ends
  stay locked to the unit **port anchors**, and the handle snaps to the grid and to those anchors
  so the line stays aligned (with **Orthogonal** routing this gives a clean flat-bottom run).
  Drag the handle back onto the straight line to clear the bend. Units stay movable while Hand
  mode is on.
- **Align** — select two or more units and click **Align ⬌** (one horizontal line, straightens
  horizontal arrows) or **Align ⬍** (one vertical line). Units line up by their **port anchor**
  (the tank centre — see below), so a stirred or anoxic reactor sits tank-to-tank with a plain
  tank and their bottoms come level, instead of aligning the taller bounding box. With nothing
  selected, aligns all units.
- **Properties panel (right)** — select a **unit** to edit its name and engineering attributes
  (MLSS, volume, DO, SRT, kLa, … — the set varies by unit type), or a **pipe** to set what it
  **carries**, its **flow**, and stream name. Values are saved with the project.
- **Show attribute values on the canvas** — tick *Show values on canvas* for a selected unit to
  print a small readout of its set attributes (e.g. `V = 500 m³`, `MLSS = 3500 g/m³`) under it.
- **Stream colours** — a pipe's *Carries* dropdown (Influent, Effluent, Sludge (RAS/WAS), Recycle,
  Air, or plain Process) sets its colour automatically, so you don't pick a colour each time.
  Click **🎨 Colors** in the toolbar to edit the palette: each stream gets a colour picker / hex
  field, changes apply live to the canvas and exports, and the palette is **saved in your browser**.
  **Download** it to a small JSON file to share or back up, **Upload** to restore, or **Reset** to
  the defaults.
- **Auto flow labels** — tick *Label flow on canvas* for a pipe to print its flow (e.g.
  `Q = 2000 m³/d`) at the pipe's midpoint.

- **Simulate** — once the simulation backend is running, draw a reactor train left→right
  (e.g. anoxic reactor → aerated reactor), set volumes (and `kLa` on aerated units) in the
  properties panel, give an *Influent* pipe a flow, then click **▶ Simulate**. A panel opens
  with the simulated concentration per reactor and the final effluent, switchable per
   compound (COD, O₂, N, biomass, …). See [Simulation](#simulation-peepypoo--asm1).
 - **Control aeration** — select an aerated unit and tick **Controller** in the
   Properties panel to add rules of the shape *if S_O > 2 then kLa = 100* (state or
   time → comparison, then a kLa). Re-evaluated on a schedule (period, in days),
   first matching rule wins, and the unit's normal kLa is the fallback when nothing
   matches. See [Controllers](#controllers-doing-if-concentration-is-x-aerate-y).
- **Flow-based pipe thickness** — with **Scale by flow** on (toolbar), a pipe's line width *and*
  arrowhead scale with its flow (∝ √flow, relative to the largest flow in the diagram); pipes with
  no flow keep a default width. Turn it off for uniform, fixed-size pipes and arrowheads.
- **Delete** — select anything and press Delete/Backspace (or the **Delete** button).
- **Undo / Redo** — **Ctrl/Cmd+Z** undoes, **Ctrl/Cmd+Shift+Z** or **Ctrl/Cmd+Y** redoes (or use the
  **↶ Undo** / **↷ Redo** toolbar buttons). Each settled edit — adding, moving, connecting,
  branching, deleting, routing/properties changes — is one step. (While typing in a text field,
  the shortcuts fall through to the field's own text undo.)
- **Save / Open** — **Save** downloads a `.wwtp.json` project; **Open** loads one back. Your
  work also autosaves to the browser and is restored on reload.
- **Export** — **Export SVG** produces a clean, portable vector file (opens correctly in
  Inkscape/Illustrator); **Export PNG** produces a 2× raster image.

## Project layout

```
src/
  App.tsx                 controller: state, all editor actions, connection handlers
  components/
    Canvas.tsx            <ReactFlow> wrapper (background, controls, minimap)
    Palette.tsx           draggable unit thumbnails
    Toolbar.tsx           top action bar
  nodes/                  UnitNode, TextNode, JunctionNode
  edges/PipeEdge.tsx      straight/orthogonal arrow with arrowhead
  lib/
    types.ts              node/edge/project types
    connect.ts            edge + junction creation, edge splitting, junction healing
    geometry.ts           handle positions, nearest-edge hit testing (along the visible polyline)
    pipePath.ts           one source of truth for a pipe's drawn shape + its polyline points
    useUndoRedo.ts        debounced node/edge history hook (Ctrl/Cmd+Z / +Y)
    streams.ts            named stream types (influent/effluent/sludge/…) → pipe colours
    attributes.ts         per-unit engineering attribute defs + on-canvas readout
    flow.ts               flow → pipe thickness, "scale by flow" context
    exportSvg.ts          graph → portable SVG (+ SVG → PNG)
    persist.ts            JSON save/load + localStorage autosave
    download.ts           file-download helpers
  units/manifest.ts       registry of the 11 unit SVGs (label, size, viewBox)
  assets/units/*.svg      the unit artwork
```

## Adding a new unit type

Drop the `.svg` into `src/assets/units/`, then add an entry to `UNITS` in
`src/units/manifest.ts` (import its URL and `?raw` source, set `label`, `viewBox`, and on-canvas
`width`/`height`). It appears in the palette automatically.

If the artwork is taller (or wider) than the vessel itself — e.g. a reactor with a stirrer
drawn above the tank — give it a `ports` anchor so arrows lock onto the tank, not the
bounding-box middle: `ports: { side }` sets where the left/right ports sit vertically and
`ports: { ends }` where the top/bottom ports sit horizontally, each a fraction `0`–`1` of the
box (default `0.5`). For example the anoxic reactor uses `ports: { side: 0.687 }` so its inlet/
outlet sit at the tank centre. Both the on-screen handles and the exported geometry honour it.

## Simulation (PeePyPoo + ASM1)

The canvas can drive a real mechanistic simulation. A Python backend
([`server/`](server/)) translates your diagram into a model with
[PeePyPoo](https://datinfo.gitlab.io/PeePyPoo/) (which solves ODEs in Julia via Thetis) and
returns the concentration time series. Each reactor is modelled as **ASM1**; aerated units get
an added aeration process driven by their `kLa`.

It is a **single server**: the same FastAPI app that exposes `/api/simulate` also serves the
built React app, so one port gives you UI + simulation.

### Setup (one time)

You need **Python 3.11+**. Create the venv and install the dependencies — on the first import
`peepypoo` downloads and compiles the Julia engine (several minutes, one-off):

```bash
python3.11 -m venv server/.venv          # or any 3.11+ interpreter
server/.venv/bin/pip install -r server/requirements.txt
```

### Run

Option A — **one server, one port** (recommended):

```bash
npm run server      # builds dist/, then serves http://localhost:8080 (UI + API)
```

Option B — Vite dev server + API:

```bash
server/.venv/bin/uvicorn server.app:app --port 8080   # backend (term 1)
npm run dev                                            # UI on :5173, proxies /api → :8080 (term 2)
```

### Using it

1. Draw a forward train of reactors left→right (e.g. `Anoxic reactor → Aerated reactor`). The
   simulator takes the **longest straight path** through your reactors and ignores branches.
   **You can wire anything in front of the first reactor** — junctions, screens, equalisation
   basins, clarifiers — e.g. `Influent → Clarifier → Anoxic → Aerated`. The simulator walks
   the influent across those pass-through units to the first reactor it reaches. (Pass-through
   units are not themselves modelled as reactors yet.)
2. In the right-hand **Properties** panel, set each reactor's **Volume** (m³), and **kLa** (1/d)
   for aerated units.
3. Add an **Influent** pipe into the first reactor and set its **flow** (m³/d) — *or* set the
   flow / composition later, inside the Simulation window (see step 5).
4. Click **▶ Simulate**.
5. A **Simulation** window opens with:
   - a **status banner** (Running… / Ready / Failed),
   - a **Setup** panel that tells you where the plant feed enters and where the effluent
     leaves, with an **Influent flow** edit and an expandable **Influent composition** editor,
   - time-series **charts** (reactor by reactor + effluent) for any compound (COD, O₂, N,
     biomass, …),
   - a **Final effluent** table,
   - **Apply & re-run** (or **Re-run**) to re-fire without re-drawing.

The first run takes a while (Julia warm-start); afterwards each run is typically 3–120 s
depending on the model and time horizon.

### Scope & limitations (v1)

- **Recirculation** — when the train ends on a **Clarifier** unit, the simulator now models an
  activated-sludge loop: a *perfect* (ideal, `f_ns = 0`) clarifier sends no solids to the
  effluent, splits the settleable sludge by a `FlowSeparator` into **RAS** (return, fixed at the
  clarifier's `Qr` field, pumped back to the first reactor) and **WAS** (waste, initial `Q_was`).
  A periodic callback drives the WAS flow toward `WAS₀ · (MLSS_target / MLSS)` so the plant holds
  its mixed-liquor solids near the clarifier's `MLSS` target — that's the SRT lever and what
  prevents the reactor from washing its biomass out. **RAS/WAS are wired only when a Clarifier
  unit is present**; bare recycle loops with no clarifier are still not modelled (they warn).
  - The steady MLSS is "close to target", not exact: with a *fixed* RAS the retention (and hence
    the reachable operating range) is fixed, and the WAS actuator steers within it. It also does
    not yet do a proper clarifier settling/underflow model — `f_ns` is read but the ideal
    clarifier is perfect by design.
- Influent composition is the standard BSM1 stabilisation feed; you can't (yet) edit individual
  influent concentrations.
- The simulation is single-user: a solve blocks the server's single worker thread for its
  duration (this is what keeps the non-thread-safe Julia engine happy).

> ### Known bug (peepypoo / ModelingToolkit side)
>
> **Do not build the `Influent` with a per-state `TimeVaryingFunction` (the block-API).**
>
> `server/simulate.py` must feed the influent as a **dict of plain constants** plus a single
> (scalar or time-varying) `flowrate`. If you instead pass `TimeVaryingFunction` blocks
> per-state in the `sources` dict, the model compiles *in isolation* but, once wired into a
> multi-reactor recirculation loop, it is left **one equation under-determined**:
> `structural_simplify()` then aborts with
> `ExtraVariablesSystemException: The system is unbalanced … potential extra variable:
> r1₊reactor₊states₊S_…`. This is a peepypoo / `ModelingToolkit` state-selection limitation, not a
> mistake in how the plant is wired (a minimal standalone model with the block-API form and the
> same loop reproduces it).
>
> The dict-of-constants form closes cleanly (it's what `server/_probe.py` and the peepypoo
> examples use) and is what this project relies on. A related trap in our own code:
> `_as_ppp_source` used to have its `return TimeVaryingFunction(…)` inside the `except:` block, so
> it silently returned `None` for a time-varying flow — that is *also* one missing equation and a
> very hard 500 to debug; if `Influent` gets `flowrate=None` the flow equation disappears and you
> see exactly the "unbalanced / extra variable" error above.

### Files

- `server/simulate.py` — diagram → PeePyPoo model + solve (the adapter).
- `server/app.py` — FastAPI app: `/api/simulate`, `/api/health`, static `dist/`.
- `server/requirements.txt` — Python deps.
- `src/lib/sim.ts` — frontend API client.
- `src/components/SimulationResults.tsx` + `LineChart.tsx` — results UI.
- `serve.mjs` — the `npm run server` one-command launcher.

### Controllers (doing "if concentration is X, aerate Y")

Select any **aerated** unit (aerated CSTR, MBR, MBBR or MABR) and tick **Controller** in the
Properties panel. Each rule is one line:

```
if  S_O  >  2.0   then set kLa = 100
if  S_O  <  0.5   then set kLa = 500     (first match wins)
if  time   <  1.0 then set kLa = 150     (time-based: t in days)
```

* **When** is any ASM1 state (`S_O`, `S_NH`, `S_NO`, …) or **time t** (days).
* **Op** is one of `<`, `<=`, `>`, `>=`.
* **Then** is a kLa (1/d).
* **Period** in days is how often the controller re-evaluates (default 0.25 d). The first
  matching rule wins; if none matches, the unit's own `kLa` field (a number, staged list or
  diurnal sine) is used.
* Time-based rules let you schedule aeration (e.g. night-time kLa, SBR-style phases,
  a startup ramp) without hand-drawing a time series.

Mechanically this is a **discrete periodic callback** on the solver (PeePyPoo's
`PeriodicCallback` driven by `GetIndex`/`SetIndex`), fired against the structurally-simplified
system the solver actually runs. It reads states live inside the solve and rewrites the
aeration `kLa` parameter. That's the only place in the stack where "if X then Y" can live,
because PeePyPoo's ODE body is built symbolically — control flow doesn't survive symbolic
build time.

Files: `server/controllers.py` (model + validator + callback builder),
`src/lib/controller.ts` (shared types + parse/serialize), `src/components/ControllerEditor.tsx`.

## Notes

- Built on [React Flow](https://reactflow.dev) (`@xyflow/react`).
- Units render on-screen as `<img>` (isolates each SVG's internal ids); the SVG exporter inlines
  them with per-instance id prefixes so gradient fills never collide between copies.
- Drawing tools (connections) are not type-checked against process rules; the **simulation** is a
  separate, explicit step over the reactor train (see [Simulation](#simulation-peepypoo--asm1)).
