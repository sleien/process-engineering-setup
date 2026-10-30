import { UNITS, type UnitDef } from '../units/manifest'

// The palette in the order water meets the units: what comes in and is screened, the
// suspended-growth tanks, the units that hold their biomass on media or behind a membrane,
// the settlers, and where water and sludge leave. A unit added to the manifest but not
// listed here still shows up, under "Other".
const GROUPS: { title: string; ids: string[] }[] = [
  { title: 'Inflow & pretreatment', ids: ['influent', 'screen', 'equalization_basin'] },
  {
    title: 'Activated sludge',
    ids: ['CSTR', 'empty_CSTR', 'anoxic_CSTR', 'aerated_CSTR', 'aerated_CSTR_off', 'switch_CSTR', 'sbr'],
  },
  { title: 'Biofilm & membrane', ids: ['trickling_filter', 'MBR', 'MBBR', 'MABR'] },
  { title: 'Clarification', ids: ['primary_clarifier', 'clarifier'] },
  { title: 'Outlets', ids: ['effluent', 'sludge'] },
]

function grouped(): { title: string; units: UnitDef[] }[] {
  const byId = new Map(UNITS.map((u) => [u.id, u]))
  const listed = new Set(GROUPS.flatMap((g) => g.ids))
  const out = GROUPS.map((g) => ({
    title: g.title,
    units: g.ids.map((id) => byId.get(id)).filter((u): u is UnitDef => u != null),
  }))
  const other = UNITS.filter((u) => !listed.has(u.id))
  if (other.length) out.push({ title: 'Other', units: other })
  return out.filter((g) => g.units.length > 0)
}

const SECTIONS = grouped()

export default function Palette() {
  return (
    <aside className="palette">
      <div className="palette-head">
        <div className="palette-title">Units</div>
        <div className="palette-hint">Drag onto the canvas</div>
      </div>
      {SECTIONS.map((g) => (
        <details key={g.title} className="palette-group" open>
          <summary className="palette-group-title">
            {g.title}
            <span className="palette-group-count">{g.units.length}</span>
          </summary>
          <div className="palette-list">
            {g.units.map((u) => (
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
        </details>
      ))}
    </aside>
  )
}
