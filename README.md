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

Then open <http://localhost:8080>, choose **File → Open project…** and load
[`examples/parallel-sbr-demo.wwtp.json`](examples/) to get a plant you can simulate right
away. Note that a solve **blocks the server's event loop** for its duration — that is what
keeps the non-thread-safe Julia engine happy — so the page stops responding while a
simulation runs and comes back when it finishes.

## How to use

The toolbar runs left to right in the order you work: **File** (open, save, export, clear),
editing (**↶** undo, **↷** redo, **⌫** delete), drawing (**T Text**, **✋ Hand**,
**Arrange**, **View**), and — apart on the right — the simulation (**⏱ Run settings**,
**▶ Simulate**). In a narrow window the plain buttons shrink to their icon; hover for the name.

- **Add a unit** — drag any item from the left **Units** palette onto the canvas. The palette
  is grouped the way water meets the units (inflow & pretreatment, activated sludge, biofilm &
  membrane, clarification, outlets); click a group's title to fold it.
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
- **Text labels** — click **T Text**, then double-click to edit. Labels support LaTeX-style
  scripts: `^` = superscript, `_` = subscript, with `{}` to group several characters —
  e.g. `m^3` → m³, `X_s`, `k_{s,xy}`, `Q_{RAS}`. (Enter commits, Esc cancels, Shift+Enter = newline.)
- **Pipe routing** — new pipes are **Orthogonal** by default (good for recycle lines that run
  along the bottom); select an arrow and choose **Arrange → Pipes: straight** or
  **Pipes: orthogonal** to change it.
- **Hand mode (route pipes)** — click **✋ Hand** in the toolbar, then drag any pipe to move it
  — e.g. pull a **sludge recirculation** line down so it runs along the bottom. While Hand mode
  is on, each pipe shows a round **depth handle** you grab (hidden otherwise). The pipe's ends
  stay locked to the unit **port anchors**, and the handle snaps to the grid and to those anchors
  so the line stays aligned (with **Orthogonal** routing this gives a clean flat-bottom run).
  Drag the handle back onto the straight line to clear the bend. Units stay movable while Hand
  mode is on.
- **Align** — select two or more units and choose **Arrange → Align horizontally** (one
  horizontal line, straightens horizontal arrows) or **Align vertically** (one vertical line). Units line up by their **port anchor**
  (the tank centre — see below), so a stirred or anoxic reactor sits tank-to-tank with a plain
  tank and their bottoms come level, instead of aligning the taller bounding box. With nothing
  selected, aligns all units.
- **Properties panel (right)** — select a **unit** to edit its name and attributes, or a
  **pipe** to set what it **carries**, its **flow**, and stream name. A unit's fields are
  sorted by what they do: **Simulation** (what the model reads — volume, initial MLSS, SRT,
  kLa, …), then folded groups for an SBR's **cycle**, an influent's **composition**, and
  **Design data** (depth, surface, DO setpoint, temperature — kept on the drawing, not read by
  the simulation). Values are saved with the project. **View → Units panel / Properties
  panel** hides either side panel to give the canvas room.
- **Show attribute values on the canvas** — tick *Show values on canvas* for a selected unit to
  print a small readout of its set attributes (e.g. `V = 500 m³`, `MLSS = 3500 g/m³`) under it.
  The readout shows at most four lines, simulation inputs first, and counts the rest
  (`+5 more`); a sampled profile shows as `profile (169 pts)` and a long formula is cut short.
- **Stream colours** — a pipe's *Carries* dropdown (Influent, Effluent, Sludge (RAS/WAS), Recycle,
  Air, or plain Process) sets its colour automatically, so you don't pick a colour each time.
  Choose **View → Stream colours…** to edit the palette: each stream gets a colour picker / hex
  field, changes apply live to the canvas and exports, and the palette is **saved in your browser**.
  **Download** it to a small JSON file to share or back up, **Upload** to restore, or **Reset** to
  the defaults.
- **Auto flow labels** — tick *Label flow on canvas* for a pipe to print its flow (e.g.
  `Q = 2000 m³/d`) at the pipe's midpoint.

- **Simulate** — once the simulation backend is running, draw a reactor train left→right
  (e.g. anoxic reactor → aerated reactor), set volumes (and `kLa` on aerated units) in the
  properties panel, give an *Influent* pipe a flow, then click **▶ Simulate**. The results
  dialog opens on **Results** — the concentration in every reactor and the effluent, switchable
  per compound (COD, O₂, N, biomass, …) — with the resolved flowsheet under **Plant** and the
  model's notes under **Messages**; **⤓ Export** downloads CSV or JSON. See
  [Simulation](#simulation-peepypoo--asm1).
- **Reading the charts** — hover for a crosshair with every line's value at that time (in days
  and as day + clock time, which is what an SBR cycle needs). **Click** to pick that time: the
  time slider moves there, the chart marks it and lists the values under it — or type a time
  next to the slider. **Drag across** a span to zoom into it, **⌘/Ctrl + scroll** (or pinch)
  to zoom around the pointer, **Shift + drag** to pan, **double-click** or **Reset** to see
  the whole run; the y axis fits what is visible. All charts on the Results tab zoom
  together. Click a legend entry to hide that line.
- **Controllers** — select a unit and use **Controllers → + Add…** in the Properties panel to
  set its kLa or one of its sludge pumps from what is measured in any tank, e.g. *if MLSS in
  Tank 1 > 4000 g/m³ then WAS = 100 m³/d*. Re-evaluated on a schedule (period, in days),
  first matching rule wins, and the unit's own setting is the fallback when nothing
  matches. See [Controllers](#controllers-doing-if-x-is-measured-there-set-y-here).
- **History** — every simulation is kept on the server; reopen a run, compare runs, or put a
  run's diagram back on the canvas. See [Run history](#run-history).
- **Flow-based pipe thickness** — with **View → Scale pipes by flow** on, a pipe's line width *and*
  arrowhead scale with its flow (∝ √flow, relative to the largest flow in the diagram); pipes with
  no flow keep a default width. Turn it off for uniform, fixed-size pipes and arrowheads.
- **Delete** — select anything and press Delete/Backspace (or the **⌫** button).
- **Undo / Redo** — **Ctrl/Cmd+Z** undoes, **Ctrl/Cmd+Shift+Z** or **Ctrl/Cmd+Y** redoes (or use the
  **↶** / **↷** toolbar buttons). Each settled edit — adding, moving, connecting,
  branching, deleting, routing/properties changes — is one step. (While typing in a text field,
  the shortcuts fall through to the field's own text undo.)
- **Save / Open** — **File → Save project** downloads a `.wwtp.json` project; **File → Open
  project…** loads one back. Your
  work also autosaves to the browser and is restored on reload.
- **Export** — **File → Export SVG** produces a clean, portable vector file (opens correctly in
  Inkscape/Illustrator); **File → Export PNG** produces a 2× raster image.
- **Run the simulation elsewhere** — **File → Export Python script…** downloads one `.py`
  that simulates the diagram on any machine with Python 3.11+ and PeePyPoo, without this
  repository. See [Python export](#python-export).

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
returns the concentration time series. Each reactor is modelled as **ASM1** — PeePyPoo's
Thetis engine also ships **ASM3** and loads any other model (ASM2d, say) from CSV files
(states, parameters, rates, stoichiometric and composition matrix), but this adapter uses
ASM1 throughout. Aerated units get
an added aeration process driven by their `kLa`. A trickling filter counts as aerated — by
natural draft — and its `kLa` defaults to 240 1/d instead of the blower default of 300.

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

**Pick a long enough horizon.** If you do not set one, the simulator now covers a few
sludge ages (3 × the longest `SRT`, capped at 30 d) rather than a few hydraulic turnovers.
The water in a tank turns over in hours; the *biomass* turns over in weeks, and the
autotrophs that do the nitrification are the slowest of all. A run that only covers a
couple of hydraulic turnovers shows the plant still starting up — effluent ammonia near the
influent value — which reads like "nitrification is broken" when it only means "ask again
later".

The first run takes a while (Julia warm-start); afterwards a small plant is typically
3–120 s. A plant with several recirculation loops and a multi-week horizon is minutes, not
seconds — see [Scope & limitations](#scope--limitations) for what drives that.

Results are saved on a fixed grid (a thousand points, or enough to show a dozen samples per
SBR cycle) rather than at every solver step, so the payload stays bounded however long the
run is.

### Parallel streets, side streams and SBR cycles

The plant you draw is resolved as a **directed graph**, not a single chain
([`server/topology.py`](server/topology.py)). That means:

- **Parallel streets.** Draw two trains from the same headworks (or from two headworks) and
  merge them again later — each reactor is built separately and the merge becomes a
  `FlowUnifier`. A reactor that feeds several units becomes a `FlowSeparator` with a
  `FlowPump` on every branch but the largest; the flows come from what you typed on the
  pipes, scaled to the water that actually arrives.
- **Side streams.** A branch that leaves the main line and rejoins further down is just
  another path through the graph. Pass-through units drawn along it (screens, equalisation
  basins, junctions) route the flow but carry no model of their own.
- **Units that keep their own biomass.** An **SBR**, **MBR**, **MBBR**, **MABR** and a
  **trickling filter** hold their solids without a separate clarifier, so each is built as
  a CSTR followed by an *internal* ideal clarifier whose sludge returns to the same tank,
  run at the unit's own `SRT` (see below). Without this they wash their nitrifiers out
  inside the first simulated day — their hydraulic residence time is far below the ~4 d an
  autotroph population needs.
- **Trickling filters are ventilated.** A real filter has no blower, but air moves through
  the media by natural draft, so the filter is aerobic and nitrifies. The model gives it an
  aeration process with a default `kLa` of 240 1/d; set `kLa` on the unit to change it
  (forced ventilation, a poorly ventilated filter). With `kLa` 0 the filter is sealed: no
  oxygen, no nitrification. The default is calibrated on the Sumo plant's municipal filter
  run alone at constant load, where it gives 3.99 mg/L DO against Sumo's 4.06 and
  0.35 mg/L NH₄ (27.1 mg/L with no aeration).
- **Primary and intermediate clarifiers.** The **Primary / intermediate clarifier** unit is a
  settler with no return: an ideal clarifier whose sludge is pumped off to waste. Give it
  `removal` (the share of incoming suspended solids it takes out, default 0.5) and `Qu` (the
  sludge flow, default 1 % of what passes through); the build turns those into the
  clarifier's non-settleable fraction. It sits in the plan like a reactor, so a feed can
  split into it, streets can merge at it and a bypass can rejoin at it. The *final*
  clarifier with its RAS loop stays the separate **Clarifier** unit.
- **SBR cycles.** An SBR unit takes `cycle`, `fill`, `react`, `settle`, `decant` (hours) and
  an `offset` stagger. The aeration follows that clock — on through react, off otherwise —
  and the `offset` puts a bank of SBRs out of phase with each other. The tank is fed
  continuously and its **volume is constant**: PeePyPoo's CSTR has no variable-volume mode,
  so fill-and-draw level swings are not modelled. Staggering a parallel bank is what makes
  continuous feeding the right approximation. A [controller](#controllers-doing-if-x-is-measured-there-set-y-here)
  on an SBR works inside the react phase: the cycle decides *when* the tank may aerate, the
  rules decide *whether* and how hard — e.g. ammonia-based aeration that switches off once
  NH₄ is gone, so the rest of the react phase denitrifies.
- **Flow bypass control.** A unit can carry a `data.bypass` spec — a branch that splits off
  before it and rejoins after it, with the diverted flow set by a measured **COD/N** ratio
  (or a single ASM1 state):

  ```json
  { "when": "COD/N", "op": ">", "value": 3.0,
    "flow": 400, "base_flow": 50, "period_days": 0.04, "rejoin_at": "sbr-b1" }
  ```

  That is the "protect nitrification from a COD surge" lever. It uses the same periodic
  callback as the aeration controllers, but writes a `FlowPump`'s flow instead of a `kLa`.
  `rejoin_at` may name any unit further down, not only the next one, so one bypass can skip
  a whole train. The ratio is measured in the tank of the unit the bypass goes around. In a
  unit that keeps its biomass, the biomass counts towards COD and N: in a trickling filter
  that puts COD/N above 20 at all times, so a `COD/N > 3` rule there never switches off.
  Measure a soluble state such as `S_S` instead.

Two worked examples, both in [`examples/`](examples/):

- **[`parallel-sbr-demo.wwtp.json`](examples/)** — start here. The smallest plant that shows
  all four features: three reactors, three recirculation loops.
- **[`sumo-parallel-sbr.wwtp.json`](examples/)** — the full Sumo plant on Sumo's own
  flowsheet, a three-week run (~11 min) with four recirculation loops, two settlers and
  three controllers. See [Sumo comparison](#sumo-comparison) below.

### Sumo comparison

[`SUMO_examples/`](SUMO_examples/) holds a Sumo 4.3 project of a real plant — two
headworks, a primary clarifier, two trickling filters in series, an intermediate clarifier,
four staggered SBRs on two parallel streets, a municipal overflow and a COD bypass around
the filters — and [`examples/sumo_reference.json`](examples/sumo_reference.json) holds the
effluent its stored steady state reports. [`examples/sumo-parallel-sbr.wwtp.json`](examples/)
is the same plant drawn here and simulated with PeePyPoo/ASM1; the generator that produces
it is [`examples/build_sumo_parallel.py`](examples/build_sumo_parallel.py), which computes
the ASM1 fractionation of Sumo's total-COD/TKN feeds and takes the flowsheet from the pipes
in Sumo's `sumoproject.plant`.

The flowsheet matters more than any parameter. An earlier version followed a hand drawing
with two parallel filter streets (municipal → filters 1+2 → SBR A, industrial → filters
3+4 → SBR B) and no clarifiers. It matched Sumo only while the filters had no oxygen. Once
they were ventilated, SBR A received fully nitrified water with no carbon left to
denitrify it, and effluent TN rose from 9.7 to 25.6 mg/L, against Sumo's 6.6. In the real
flowsheet, raw municipal water that bypasses the filters gives the SBRs that carbon.

**Run it with a 21 day horizon** — the industrial feed is a sampled weekly pulse stretched
across the simulated window, so a shorter run moves the pulses.

Three things cannot be reproduced, and saying so is more useful than tuning around them:

- **TP** — ASM1 has no phosphorus. Matching the 3.83 mg P/L target needs ASM2d.
- **Temperature** — the reactor temperature is fixed at 20 °C, against Sumo's 19.56 °C
  (Thetis could take it as a parameter or a state; the adapter does not wire that yet).
- **The SBR's fill-and-draw level swing** — the tank volume is constant, so the cycle drives
  the aeration and not the water level.

See [`examples/README.md`](examples/README.md) for the full comparison and for what the SBR
and trickling-filter approximations do and do not cover.

### Scope & limitations

- A `FlowPump` holds a **fixed** flow, so a pumped branch must stay below what arrives at
  that split *at all times*. Give the pumped side the smaller share and let the free branch
  absorb the swing, or a time-varying feed will drive the free branch negative.
- **A time-varying influent flow is wired as a native block, not as a Python function.** A
  sinusoid becomes a `Sine` block and a sampled profile a `(values, times)` pair the backend
  interpolates. The Python-function path still exists as a fallback, and it is expensive:
  PeePyPoo calls the function with a *symbolic* time at build time, so `sin` written as a
  Taylor series (which is what the attribute language has to do — see
  [`server/timeseries.py`](server/timeseries.py)) gets expanded into the equations. On a
  one-reactor plant that is ~28 s to simplify and ~26 s to solve, against ~1.5 s and ~2 s
  for the block forms.
- **Every recirculation loop costs.** A clarifier's RAS, and the internal return inside each
  SBR or MBR, is an algebraic loop the backend has to tear, and build time grows sharply
  with the number of loops in one system. Measured on an isolated chain: one loop ~20 s to
  simplify, three ~28 s, four ~70 s. A plant with several settling units is minutes of
  build time before the solve even starts.

  Holding a unit's biomass as a *fixed state* instead (`CSTR(fixed_states=…)`) avoids the
  loop and looks tempting for a fixed film — but a fixed state still leaves with the
  outflow at its fixed concentration, so the unit becomes a **source** of solids: a filter
  held at 2000 mg/L on 6900 m³/d exports fourteen tonnes of biomass a day, and whatever is
  downstream saturates its own waste limit trying to hold MLSS. The loop conserves mass;
  the fixed state does not.
- **A run that stops short is an error, not a result.** A stiff model can drive the step
  size below floating-point resolution and give up part-way;
  [DifferentialEquations](https://docs.sciml.ai/DiffEqDocs/stable/) reports that through a
  return code rather than by raising, so the partial solution comes back looking like any
  other. The adapter checks the return code *and* the time actually covered, and refuses
  the run rather than charting two days of a three-week request.
- **Concentrations are held non-negative, and a solver `Success` does not prove they were.**
  When aeration switches off in a tank full of biomass, dissolved oxygen falls from ~2.5 mg/L
  to zero in seconds, and a stiff solver overshoots below zero. Below `-K_OH` the Monod switch
  `S_O/(K_OH + S_O)` turns positive again, so oxygen uptake carries on with no oxygen and
  `S_O` runs away — the parallel-SBR demo reached **−142 mg/L** while the solver reported
  `Success`, and the same runaway switched nitrification on with no oxygen: after 3 days the
  SBR held **63.6 mg/L of nitrate from a feed carrying ~49 mg/L of nitrogen in total**. The solve
  now passes `isoutofdomain`, which rejects any step taking a state below −10⁻³ mg/L and
  retries it smaller; on that demo it was also 3× faster (6.7 s against 22.2 s).
  A reported series that still goes meaningfully negative fails the run instead of being
  clipped to zero — clipping is how the corrupt solution looked clean in the first place.
- **A callback that writes a parameter must tell the integrator the state is unchanged.**
  Every callback here writes a *parameter* (a kLa, a pump flow) and leaves the state alone,
  so each calls `u_modified(integrator, False)`. Leaving that out makes the solver
  re-initialise the system after the callback, and its default re-initialisation does not
  only settle the algebraic flow variables — it moves the **differential** states back onto a
  fixed consistent point. Every reactor was reset each tick and could not grow beyond one
  controller period. On the parallel-SBR demo an inert tracer sat at exactly 212.34 mg/L for 30
  days (its true path climbs towards 491), which reads as a sludge age of 5.2 d against the
  12 d the waste was sized for, and it froze the nitrifiers at their seed — in *every* plant
  that had a flow-writing callback, which before the sludge-age change was every plant with a
  clarifier. With the call, the tracer gives exactly the sized 12.00 d and the solve is 18×
  faster. (An earlier version of this README recommended the opposite, on the strength of a
  timing measurement alone: it was faster *because* the states were being reset.)
- **Recirculation and sludge age** — when the train ends on a **Clarifier** unit, the
  simulator models an activated-sludge loop: an ideal clarifier (its `f_ns` is the fraction of
  the inflow's particulate concentration that stays in the effluent) splits the settled sludge
  by a `FlowSeparator` into **RAS** (fixed at the clarifier's `Qr`, pumped back to the head of
  the street the clarifier sits on) and **WAS** (to the sludge sink). **RAS/WAS are wired only
  when a Clarifier unit is present**; bare recycle loops with no clarifier are not modelled
  (they warn).

  The WAS is sized for a **sludge age**, not adjusted to hold an MLSS. Give the clarifier an
  `SRT` and the waste that holds it is computed from the loop volume, the forward and RAS flows
  and `f_ns` — with the thickening of the underflow accounted for, which roughly doubles the
  sludge age compared with wasting mixed liquor at `V/SRT`. Without an `SRT`, a `Q_was` is
  used as given and the sludge age it produces is reported; with neither, the SRT defaults to
  15 d. Units that keep their own solids (SBR, MBR, MBBR, MABR, trickling filter) are sized the
  same way from their own `SRT`. The `MLSS` field is only the starting value — the solids
  settle wherever the load puts them at that sludge age, which is how SRT-controlled plants
  actually run.

  This replaced an MLSS controller (waste ∝ MLSS / target, re-evaluated each tick), and the
  reason is nitrification. Holding solids at a setpoint lets the sludge age go wherever the
  load sends it, and a plant that produces more sludge than its tank holds at that setpoint
  is driven to a short SRT — short enough to wash out the nitrifiers while the much faster
  heterotrophs carry on. On `ras-recirculation.wwtp.json` the old controller, starting from
  its 520 m³/d waste, ran the plant at an SRT of **0.93 d**: the autotrophs washed out
  completely, no nitrate was ever formed, effluent ammonia sat at 14–21 mg/L. With the waste
  sized for 15 d the aerated tank comes down to 5–7 mg/L.

  The run warns when a loop's sludge age is too short to keep nitrifiers (under ~4 d, scaled
  up for a unit aerated only part of the time), and when a target cannot be reached at all —
  for instance when `f_ns × Q` alone already removes more solids than the SRT allows.
- Influent composition defaults to the standard BSM1 stabilisation feed; set the ASM1 states
  on the Influent unit to override it. The flow may be a constant, a sampled profile (a JSON
  list, interpolated across the whole run) or a sinusoid — **per-state** time variation is
  not supported (see the known bug below).
- ASM1 has no phosphorus and the reactor temperature is fixed at 20 °C, so effluent **TP** and
  temperature cannot be reproduced at all. Matching those needs ASM2d.
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

- `server/topology.py` — drawing → flow plan (the DAG: reactors, inlets, outlets, branch
  flows). Pure graph work, no PeePyPoo — `server/test_topology.py` covers it.
- `server/simulate.py` — flow plan → PeePyPoo model + solve (the adapter).
- `server/controllers.py` — the periodic/preset callbacks: plant controllers (kLa and
  sludge pumps), SBR cycle clock, bypass flow control. (The sludge age needs no callback:
  its waste flow is sized once.)
- `server/history.py` — the run history kept in `server/history/`.
- `server/export_python.py` — the diagram as a standalone Python script.
- `server/app.py` — FastAPI app: `/api/simulate`, `/api/history`, `/api/health`, static `dist/`.
- `server/requirements.txt` — Python deps.
- `src/lib/sim.ts` — frontend API client.
- `src/components/SimulationResults.tsx` + `LineChart.tsx` — results UI.
- `serve.mjs` — the `npm run server` one-command launcher.

Run the pure-Python tests (no Julia) with:

```bash
server/.venv/bin/python server/test_topology.py
```

```bash
server/.venv/bin/python server/test_controllers.py
```

```bash
server/.venv/bin/python server/test_history.py
```

### Controllers (doing "if X is measured there, set Y here")

A controller sits on the unit whose setting it changes, and its rules may measure in **any
tank** of the plant. Select the unit, then **Controllers → + Add…** in the Properties panel:

| On | It can set |
| --- | --- |
| an aerated unit (aerated CSTR, switchable reactor, MBR, MBBR, MABR, SBR, trickling filter) | the aeration **kLa** |
| a unit that keeps its own solids (SBR, MBR, MBBR, MABR, trickling filter) | its **excess sludge (WAS)** pump and its internal **sludge return** |
| the clarifier | the plant's **excess sludge (WAS)** pump and **return sludge (RAS)** pump |
| a primary / intermediate clarifier | its **sludge underflow** |
| an influent | its **flow** — e.g. switched on and off on the pH of the tank it feeds |

Each rule is one line, checked top to bottom every *period* days of simulated time:

```
if  MLSS  in Aerated reactor  >  4200 g/m³   → set  70 m³/d
if  MLSS  in Aerated reactor  >  3800 g/m³   → set  45 m³/d     (first match wins)
if  MLSS  in Aerated reactor  <  3000 g/m³   → set  15 m³/d
```

That is the excess-sludge controller of
[`examples/ras-mlss-controller.wwtp.json`](examples/): it holds the aerated tank at
4100–4200 g/m³, where the fixed waste flow lets it climb to ~5400.

* **Measure** — any ASM1 state (`S_O`, `S_NH`, `S_NO`, …), **MLSS** (suspended solids,
  g TSS/m³ = 0.75 × particulate COD — the same conversion the *MLSS (initial)* field uses),
  the **COD/N** ratio, the **pH** (estimated, see below), or **time** (days). **In** picks
  the tank; a clarifier or an influent holds no mixed liquor, so a rule on one always names
  a tank.
* **Op** is one of `<`, `<=`, `>`, `>=`; **set** is the new kLa (1/d) or pump flow (m³/d).
  A pump cannot be set above what reaches it (the run refuses such a rule and says why),
  and "0" means its minimum of 0.5 m³/d.
* **Otherwise** — when no rule matches, the setting falls back to its own value (the unit's
  `kLa` field, an influent's flow field, or the pump flow the model sized — for the WAS
  pump, the one that holds the SRT), or, with *keep the last setting*, stays where it was.
  Keeping it is what makes an on-rule and an off-rule a **switch with hysteresis**:

  ```
  if  pH  in Nitrification CSTR  <  6.20   → set  0.2 m³/d      (feed on)
  if  pH  in Nitrification CSTR  >  6.25   → set  0   m³/d      (feed off)
  otherwise: keep the last setting
  ```

  That is the influent controller of
  [`examples/ph-controlled-feed.wwtp.json`](examples/): between 6.20 and 6.25 the feed keeps
  running if it was running and stays off if it was off.
* On an **SBR**, a kLa controller works inside the react phase only; the cycle keeps the
  aeration off for fill, settle and decant.
* **Period** — set in minutes (1 min to 1 d). A controller on a thin buffer needs a short
  one: the pH-fed tank swings 6.15–6.32 at a 15-minute tick against 6.19–6.26 at two
  minutes. A kLa controller is held below the residence time of its tank, because oxygen
  swings from zero to saturation within it; a slower tick runs open loop and the solve
  fails. A pump controller on MLSS is not: MLSS moves with the sludge age, so check it once
  or twice a day — held to the residence time of a tank with a strong return (an hour) it
  would toggle the pump forty times as often for nothing.
* **Give a two-sided rule a deadband.** `S_O > 2 → low` paired with `S_O < 2 → high` has no
  hysteresis: the state settles on the threshold and the controller flips at every tick,
  restarting the stiff solver each time. Measured on a single aerated tank over three
  weeks, that is 8 s against 0.1 s for `> 2.5` / `< 1.5`. The simulator warns when it sees
  a pair like that at a short period. The rules hold no memory, so a band with no rule
  falls back to the unit's own setting; if that setting cannot hold the value inside the
  band, give the band its own rule (the staircase above).
* The results window charts **what each controller set** over the run (*Results →
  Controller outputs*) and lists every controller under *Plant*. A controlled influent's
  flow is charted as it ran.

**pH.** ASM1 has no pH; it carries alkalinity, `S_ALK`, in mol HCO₃⁻/m³ (= mmol/L), and its
stoichiometry moves it as the real processes do — nitrification takes two moles per mole
of ammonium oxidised. The simulation estimates the pH of the bicarbonate buffer,

```
pH = pK₁ + log₁₀(S_ALK / CO₂)        pK₁ = 6.38 at 20 °C
```

with the dissolved CO₂ each tank states (*pH estimate → Dissolved CO₂*, default 1 mmol/L —
it is what respiration produces and aeration strips, and the model does not track it).
*Initial pH* starts a tank at the alkalinity that pH means. Every tank and the effluent get
a `pH` series in the results. The estimate holds between about pH 5.5 and 8.3, where
bicarbonate carries the alkalinity; it is an estimate, and since ASM1 does not slow
nitrification at low pH, a pH controller is what keeps the tank from running out of
alkalinity.

A controlled influent is built as a feed tank: the influent delivers the most any rule asks
for, a pump draws what the controller sets (0 = stopped) and the rest overflows. To the
tank it feeds that is a feed switched on and off. It must feed a single unit.

Mechanically this is a **discrete periodic callback** on the solver (PeePyPoo's
`PeriodicCallback` driven by `GetIndex`/`SetIndex`), fired against the structurally-simplified
system the solver actually runs. It reads states live inside the solve and rewrites one
parameter — the `k` of the aeration input, or a `FlowPump`'s flow. That's the only place in
the stack where "if X then Y" can live, because PeePyPoo's ODE body is built symbolically —
control flow doesn't survive symbolic build time.

Projects saved before this stored a single kLa controller as `data.controller`; it is still
read, and becomes `data.controllers` the next time it is edited.

Files: `server/controllers.py` (model, validator, callback builder; tests in
`server/test_controllers.py`), `src/lib/controller.ts` (shared types),
`src/components/ControllerEditor.tsx`.

### Python export

**File → Export Python script…** turns the diagram and the current run settings into a
single script for another machine — a bigger server, a cluster node, a scheduled job:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install peepypoo==1.0.4
```

```bash
.venv/bin/python plant.py --days 30 --out results/run1
```

The first run installs Julia and its packages (several minutes, once). The script writes
`result.json` — the same object `/api/simulate` returns, so series, reactors, controller
outputs, warnings and setup are all there — and `series.csv` (time, location, state,
value), and prints the effluent.

It carries the plant as an editable Python literal (`PLANT`, `SETTINGS`) and this server's
model adapter (`timeseries`, `topology`, `controllers`, `simulate`) embedded and compressed,
so it builds exactly the model the app builds rather than a re-implementation that could
drift. Checked on the excess-sludge example: run from a directory outside the repository
with `python -I`, every series matches the server's own run to the last digit. Generated by
`server/export_python.py`; the API is `POST /api/export/python` with the body of
`/api/simulate`.

### Run history

Every simulation the server runs is kept — the diagram it simulated, the run settings, and
the result or the error. **History** in the toolbar lists them newest first, with solve time,
horizon and the effluent (mean over the last tenth of the run):

* click a run's name to **rename** it;
* **Open** shows its results again — the window says which run it is, and offers
  *Restore this diagram* instead of *Re-run*;
* **Restore** puts the diagram that run simulated back on the canvas (undoable);
* tick two or more and **Compare** overlays their effluent (TN, NH₄, NO₃, COD, TSS, O₂) and
  lines up their figures in a table;
* **✕** deletes a run.

The runs live in `server/history/` (ignored by git), two files each: a small `.meta.json`
for the list and a gzipped record with everything else. The newest 100 are kept; older ones
are removed when a new run is saved. API: `GET /api/history`, `GET/PATCH/DELETE
/api/history/{id}`; `POST /api/simulate` answers with the run's `history_id`.

## Notes

- Built on [React Flow](https://reactflow.dev) (`@xyflow/react`).
- Units render on-screen as `<img>` (isolates each SVG's internal ids); the SVG exporter inlines
  them with per-instance id prefixes so gradient fills never collide between copies.
- Drawing tools (connections) are not type-checked against process rules; the **simulation** is a
  separate, explicit step over the reactor train (see [Simulation](#simulation-peepypoo--asm1)).
