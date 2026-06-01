import { useRef } from 'react'

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
  onSave: () => void
  onOpen: (file: File) => void
  onExportSvg: () => void
  onExportPng: () => void
  onFit: () => void
  onClear: () => void
}

export default function Toolbar(props: ToolbarProps) {
  const fileRef = useRef<HTMLInputElement>(null)

  return (
    <header className="toolbar">
      <span className="brand">WWTP&nbsp;Designer</span>
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
      </div>
      <div className="toolbar-spacer" />
      <div className="toolbar-group">
        <button onClick={props.onOpenColors} title="Edit stream colours (saved in your browser, download/uploadable)">
          🎨&nbsp;Colors
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
