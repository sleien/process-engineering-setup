import { useEffect, useRef, useState } from 'react'
import { APP_VERSION, fetchServerVersion, type ServerVersion } from '../lib/version'

/**
 * Always-visible version chip. Shows `vX.Y.Z` and a short status note. The colour / note tell
 * you which half is out of date and whether the backend actually has the washout fix:
 *   - red   → backend offline (you're not even testing the fixed backend)
 *   - amber → backend up but a different version, or it predates the recirc/washout fix
 *   - green → frontend + backend agree and the recirc fix is present
 *
 * Frontend alone can't have the washout fix — the **backend** (`server/`) is what builds the
 * simulation model — so the chip tracks the server's own reported version rather than ours.
 */
function VersionBadge() {
  const [srv, setSrv] = useState<ServerVersion | null>(null)
  useEffect(() => {
    let alive = true
    void fetchServerVersion().then((v) => alive && setSrv(v))
    return () => { alive = false }
  }, [])

  const ok = srv?.ok === true
  const version = ok ? (srv!.version ?? '—') : 'offline'
  const mismatch = ok && version !== APP_VERSION
  const hasFix = ok && (srv!.features ?? []).includes('recirc-wired')
  const note = !ok ? 'backend offline' : !hasFix ? 'no washout fix' : mismatch ? 'version mismatch' : 'recirc fix on'
  const hint = {
    'backend offline': 'Backend not reachable. Are you running `npm run server`? The washout fix lives in the backend (server/), so an offline one can never give you the fixed result.',
    'no washout fix': 'This backend predates the recirculation + MLSS/SRT control. Restart `npm run server` (or reload from the latest code) to get the washout fix.',
    'version mismatch': 'Frontend and backend versions differ — rebuild/restart to line them up.',
    'recirc fix on': 'Frontend and backend are current and the recirculation + MLSS/SRT (washout) fix is active.',
  }[note]
  const title = `Frontend v${APP_VERSION} · backend v${version}\n${hint}`
  const cls = !ok ? 'verchip verchip-bad' : !hasFix || mismatch ? 'verchip verchip-warn' : 'verchip verchip-ok'
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
  onSave: () => void
  onOpen: (file: File) => void
  onExportSvg: () => void
  onExportPng: () => void
  onFit: () => void
  onClear: () => void
  onSimulate: () => void
  simulating: boolean
}

export default function Toolbar(props: ToolbarProps) {
  const fileRef = useRef<HTMLInputElement>(null)

  return (
    <header className="toolbar">
      <span className="brand">WWTP&nbsp;Designer</span>
      <VersionBadge />
      <div className="toolbar-group">
        <button onClick={props.onUndo} disabled={!props.canUndo} title="Undo (Ctrl/Cmd+Z)">
          ↶&nbsp;Undo
        </button>
        <button onClick={props.onRedo} disabled={!props.canRedo} title="Redo (Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y)">
          ↷&nbsp;Redo
        </button>
        <button onClick={props.onAddText} title="Add a text label">
          + Text
        </button>
        <button onClick={() => props.onSetRouting('straight')} title="Straight routing for selected pipes">
          Straight
        </button>
        <button onClick={() => props.onSetRouting('step')} title="Orthogonal routing for selected pipes">
          Orthogonal
        </button>
        <button
          className={props.handMode ? 'active' : undefined}
          aria-pressed={props.handMode}
          onClick={() => props.onHandMode(!props.handMode)}
          title="Hand mode: drag a pipe to route it (e.g. pull a recycle line down). Units stay movable."
        >
          ✋&nbsp;Hand
        </button>
        <label
          className="toolbar-toggle"
          title="Scale line thickness and arrowheads by flow. Off = uniform default pipes."
        >
          <input
            type="checkbox"
            checked={props.scaleByFlow}
            onChange={(e) => props.onScaleByFlow(e.target.checked)}
          />
          Scale&nbsp;by&nbsp;flow
        </label>
        <button
          onClick={() => props.onAlign('h')}
          title="Align selected units on one horizontal line (straightens horizontal arrows). Aligns all units if nothing is selected."
        >
          Align&nbsp;⬌
        </button>
        <button
          onClick={() => props.onAlign('v')}
          title="Align selected units on one vertical line (straightens vertical arrows)"
        >
          Align&nbsp;⬍
        </button>
        <button onClick={props.onDelete} title="Delete selection (Del / Backspace)">
          Delete
        </button>
        <button
          className="primary simulate"
          disabled={props.simulating}
          onClick={props.onSimulate}
          title="Simulate the reactor train with the PeePyPoo / ASM1 engine (draw reactors left→right)"
        >
          {props.simulating ? 'Simulating…' : '▶ Simulate'}
        </button>
      </div>
      <div className="toolbar-spacer" />
      <div className="toolbar-group">
        <button onClick={props.onOpenColors} title="Edit stream colours (saved in your browser, download/uploadable)">
          🎨&nbsp;Colors
        </button>
        <button onClick={props.onOpenPresets} title="Simulation duration and presets (saved in your browser, import/exportable)">
          ⏱&nbsp;Presets
        </button>
        <button onClick={props.onFit} title="Fit diagram to view">
          Fit
        </button>
        <button onClick={props.onSave} title="Download project as JSON">
          Save
        </button>
        <button onClick={() => fileRef.current?.click()} title="Open a saved project">
          Open
        </button>
        <button onClick={props.onExportSvg} title="Export vector SVG">
          Export SVG
        </button>
        <button onClick={props.onExportPng} title="Export PNG image">
          Export PNG
        </button>
        <button className="danger" onClick={props.onClear} title="Clear the diagram">
          Clear
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
