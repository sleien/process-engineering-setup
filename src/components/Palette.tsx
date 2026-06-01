import { UNITS } from '../units/manifest'

export default function Palette() {
  return (
    <aside className="palette">
      <div className="palette-title">Units</div>
      <div className="palette-hint">Drag onto the canvas</div>
      <div className="palette-list">
        {UNITS.map((u) => (
          <div
            key={u.id}
            className="palette-item"
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData('application/wwtp-unit', u.id)
              e.dataTransfer.effectAllowed = 'copy'
            }}
            title={u.label}
          >
            <div className="palette-thumb-wrap">
              <img src={u.url} alt={u.label} className="palette-thumb" draggable={false} />
            </div>
            <span className="palette-label">{u.label}</span>
          </div>
        ))}
      </div>
    </aside>
  )
}
