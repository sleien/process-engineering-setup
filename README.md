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

## Notes

- Built on [React Flow](https://reactflow.dev) (`@xyflow/react`).
- Units render on-screen as `<img>` (isolates each SVG's internal ids); the SVG exporter inlines
  them with per-instance id prefixes so gradient fills never collide between copies.
- This is a pure drawing tool — connections are not type-checked against process rules.
