import { useEffect, useRef, useState } from 'react'
import { APP_VERSION, fetchServerVersion, type ServerVersion } from '../lib/version'
import Menu from './Menu'

/**
 * Always-visible version chip. Shows `vX.Y.Z` and a short status note. The colour / note tell
 * you which half is out of date and whether the backend has sludge-age (SRT) control:
 *   - amber → still asking, backend up but a different version, or an older backend
 *   - red   → backend offline
 *   - green → frontend + backend agree and SRT control is present
 *
 * The frontend alone can't change simulation behaviour — the **backend** (`server/`) builds
 * the model — so the chip tracks the server's own reported version rather than ours.
 */
function VersionBadge() {
  const [srv, setSrv] = useState<ServerVersion | null>(null)
  useEffect(() => {
    let alive = true
    void fetchServerVersion().then((v) => alive && setSrv(v))
    return () => { alive = false }
  }, [])

  // Until the request answers, say so rather than "offline". A solve blocks the server's
  // event loop for its whole duration, so a reload during a long run leaves this request
  // pending for minutes — reporting that as "not reachable" sends people restarting a server
  // that is only busy.
  const pending = srv === null
  const ok = srv?.ok === true
  const version = pending ? '…' : ok ? (srv!.version ?? '—') : 'offline'
  const mismatch = ok && version !== APP_VERSION
  const hasFix = ok && (srv!.features ?? []).includes('srt-control')
  const note = pending ? 'checking' : !ok ? 'backend offline' : !hasFix ? 'old backend' : mismatch ? 'version mismatch' : 'up to date'
  const hint = {
    'checking': 'Asking the backend for its version. If this stays, the backend is probably busy with a simulation, which blocks it until the solve finishes.',
    'backend offline': 'Backend not reachable. Are you running `npm run server`? The simulation is built by the backend (server/), so without it nothing can be simulated.',
    'old backend': 'This backend predates sludge-age (SRT) control. Restart `npm run server` from the latest code.',
    'version mismatch': 'Frontend and backend versions differ — rebuild/restart to line them up.',
    'up to date': 'Frontend and backend are current, with sludge-age control, parallel streets and SBR cycles.',
  }[note]
  const title = `Frontend v${APP_VERSION} · backend v${version}\n${hint}`
  const cls = pending ? 'verchip verchip-warn' : !ok ? 'verchip verchip-bad' : !hasFix || mismatch ? 'verchip verchip-warn' : 'verchip verchip-ok'
  return (
    <span className={cls} title={title}>
      <span className="verchip-dot" aria-hidden />
      v{version}
      <span className="verchip-note">{note}</span>
    </span>
  )
}

export type ToolbarProps = {
  onAddText: () => void
  onUndo: () => void
  onRedo: () => void
  canUndo: boolean
  canRedo: boolean
  onDelete: () => void
  onAlign: (axis: 'h' | 'v') => void
  onSetRouting: (r: 'straight' | 'step') => void
  handMode: boolean
  onHandMode: (v: boolean) => void
  scaleByFlow: boolean
  onScaleByFlow: (v: boolean) => void
  onOpenColors: () => void
  onOpenPresets: () => void
  onOpenHistory: () => void
  onSave: () => void
  onOpen: (file: File) => void
  onExportSvg: () => void
  onExportPng: () => void
  onExportPython: () => void
  onFit: () => void
  onClear: () => void
  onSimulate: () => void
  simulating: boolean
  panels: { units: boolean; properties: boolean }
  onTogglePanel: (key: 'units' | 'properties') => void
}

// Toolbar, left to right in the order you use it: the project (file menu), editing, drawing,
// arranging and viewing the diagram — then, apart on the right, the simulation. Rarely used
// commands live in the menus so the bar fits on one row; below ~1100 px the plain buttons
// drop their text and keep the icon (the tooltip still names them), the menus keep theirs.
export default function Toolbar(props: ToolbarProps) {
  const fileRef = useRef<HTMLInputElement>(null)

  return (
    <header className="toolbar">
      <span className="brand" title="WWTP Designer">
        WWTP<span className="brand-rest">&nbsp;Designer</span>
      </span>
      <VersionBadge />

      <div className="toolbar-group">
        <Menu
          label="File"
          title="Open, save, export or clear the project"
          items={[
            { label: 'Open project…', onClick: () => fileRef.current?.click(), title: 'Open a saved .json project' },
            { label: 'Save project', onClick: props.onSave, title: 'Download the project as JSON' },
            'separator',
            { label: 'Export SVG', onClick: props.onExportSvg, title: 'Vector image of the diagram' },
            { label: 'Export PNG', onClick: props.onExportPng, title: 'Raster image of the diagram' },
            { label: 'Export Python script…', onClick: props.onExportPython, title: 'A standalone .py that runs this simulation on another machine (needs Python 3.11+ and peepypoo)' },
            'separator',
            { label: 'Clear diagram', onClick: props.onClear, danger: true, title: 'Remove every unit and pipe' },
          ]}
        />
      </div>

      <div className="toolbar-group" role="group" aria-label="Edit">
        <button className="tb-icon-btn" onClick={props.onUndo} disabled={!props.canUndo} title="Undo (Ctrl/Cmd+Z)" aria-label="Undo">
          ↶
        </button>
        <button className="tb-icon-btn" onClick={props.onRedo} disabled={!props.canRedo} title="Redo (Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y)" aria-label="Redo">
          ↷
        </button>
        <button className="tb-icon-btn" onClick={props.onDelete} title="Delete selection (Del / Backspace)" aria-label="Delete selection">
          ⌫
        </button>
      </div>

      <div className="toolbar-group" role="group" aria-label="Draw">
        <button onClick={props.onAddText} title="Add a text label">
          <span className="tb-icon" aria-hidden>T</span>
          <span className="tb-label">Text</span>
        </button>
        <button
          className={props.handMode ? 'active' : undefined}
          aria-pressed={props.handMode}
          onClick={() => props.onHandMode(!props.handMode)}
          title="Hand mode: drag a pipe to route it (e.g. pull a recycle line down). Units stay movable."
        >
          <span className="tb-icon" aria-hidden>✋</span>
          <span className="tb-label">Hand</span>
        </button>
        <Menu
          label="Arrange"
          title="Align units and set how pipes are routed"
          items={[
            { label: 'Align horizontally', onClick: () => props.onAlign('h'), hint: '⬌', title: 'Put the selected units on one horizontal line (all units if nothing is selected)' },
            { label: 'Align vertically', onClick: () => props.onAlign('v'), hint: '⬍', title: 'Put the selected units on one vertical line' },
            'separator',
            { label: 'Pipes: straight', onClick: () => props.onSetRouting('straight'), title: 'Straight routing for the selected pipes' },
            { label: 'Pipes: orthogonal', onClick: () => props.onSetRouting('step'), title: 'Right-angled routing for the selected pipes' },
          ]}
        />
        <Menu
          label="View"
          alignRight
          title="Fit the diagram, show or hide the side panels, pipe widths and colours"
          items={[
            { label: 'Fit diagram to view', onClick: props.onFit },
            'separator',
            { label: 'Units panel', onClick: () => props.onTogglePanel('units'), checked: props.panels.units, title: 'Show or hide the unit palette on the left' },
            { label: 'Properties panel', onClick: () => props.onTogglePanel('properties'), checked: props.panels.properties, title: 'Show or hide the properties panel on the right' },
            'separator',
            { label: 'Scale pipes by flow', onClick: () => props.onScaleByFlow(!props.scaleByFlow), checked: props.scaleByFlow, title: 'Line thickness and arrowheads follow the flow; off = uniform pipes' },
            { label: 'Stream colours…', onClick: props.onOpenColors, title: 'Edit stream colours (saved in your browser)' },
          ]}
        />
      </div>

      <div className="toolbar-spacer" />

      <div className="toolbar-group" role="group" aria-label="Simulation">
        <button onClick={props.onOpenPresets} title="Simulation duration and presets (saved in your browser, import/exportable)">
          <span className="tb-icon" aria-hidden>⏱</span>
          <span className="tb-label">Run settings</span>
        </button>
        <button onClick={props.onOpenHistory} title="Earlier runs: reopen, compare, or restore their diagram">
          <span className="tb-icon" aria-hidden>🕘</span>
          <span className="tb-label">History</span>
        </button>
        <button
          className="primary simulate"
          disabled={props.simulating}
          onClick={props.onSimulate}
          title="Simulate the plant with the PeePyPoo / ASM1 engine"
        >
          {props.simulating ? 'Simulating…' : '▶ Simulate'}
        </button>
      </div>
      <input
        ref={fileRef}
        type="file"
        accept=".json,application/json"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) props.onOpen(f)
          e.target.value = ''
        }}
      />
    </header>
  )
}
