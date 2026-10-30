import { useEffect, useState } from 'react'
import type { AppEdge, AppNode } from '../lib/types'
import { attrPlaceholder, getUnitAttrs, type AttrDef, type AttrGroup } from '../lib/attributes'
import { getUnit } from '../units/manifest'
import { STREAMS, streamColor } from '../lib/streams'
import ControllerEditor, { type TankRef } from './ControllerEditor'
import { targetsFor } from '../lib/controller'
import { ENGINE_DEFAULT_INFLUENT } from '../lib/states'

// Field groups below the simulation inputs, in panel order. The design data starts folded:
// it is what the drawing carries, and the simulation does not read it.
const GROUPS: { id: AttrGroup; title: string; open: boolean; note?: string }[] = [
  { id: 'cycle', title: 'SBR cycle', open: true },
  {
    id: 'composition',
    title: 'Composition',
    open: false,
    note: 'Empty fields take the built-in BSM1 feed (shown as placeholders).',
  },
  {
    id: 'ph',
    title: 'pH estimate',
    open: false,
    note: 'ASM1 has no pH. It is estimated from the alkalinity: pH = 6.38 + log₁₀(S_ALK / CO₂) at 20 °C, with the dissolved CO₂ given here. An initial pH starts the tank at the alkalinity it means.',
  },
  {
    id: 'design',
    title: 'Design data',
    open: false,
    note: 'Shown on the drawing; the simulation does not read these.',
  },
]

type Props = {
  node?: AppNode
  edge?: AppEdge
  /** Every tank on the canvas, for controllers that measure somewhere else. */
  tanks: TankRef[]
  onPatchNode: (id: string, patch: Record<string, unknown>) => void
  onPatchEdge: (id: string, patch: Record<string, unknown>) => void
}

export default function Inspector({ node, edge, tanks, onPatchNode, onPatchEdge }: Props) {
  // Local mirror for the numeric flow field so decimals type smoothly.
  const [flowText, setFlowText] = useState('')
  useEffect(() => {
    setFlowText(edge?.data?.flow != null ? String(edge.data.flow) : '')
  }, [edge?.id, edge?.data?.flow])

  let body: React.ReactNode

  if (node && node.type === 'unit') {
    const unit = getUnit(node.data.unitId)
    const attrs = getUnitAttrs(node.data.unitId)
    const values = node.data.attributes ?? {}
    const row = (a: AttrDef) => {
      const dflt =
        node.data.unitId === 'influent' && a.key in ENGINE_DEFAULT_INFLUENT
          ? `${ENGINE_DEFAULT_INFLUENT[a.key]}${a.unit ? ` ${a.unit}` : ''}`
          : attrPlaceholder(a, node.data.unitId)
      return (
        <label className="insp-row" key={a.key}>
          <span className="insp-row-label">
            {a.label}
            {a.unit && a.unit !== '-' && <small>{a.unit}</small>}
          </span>
          <input
            inputMode="decimal"
            value={values[a.key] ?? ''}
            placeholder={dflt}
            title={values[a.key] || undefined}
            onChange={(e) =>
              onPatchNode(node.id, { attributes: { ...values, [a.key]: e.target.value } })
            }
          />
        </label>
      )
    }
    const main = attrs.filter((a) => !a.group)
    body = (
      <>
        <div className="insp-title">{unit?.label ?? 'Unit'}</div>
        <label className="insp-field">
          <span>Name</span>
          <input
            value={node.data.name ?? ''}
            placeholder="e.g. Aeration 1"
            onChange={(e) => onPatchNode(node.id, { name: e.target.value })}
          />
        </label>
        {main.length > 0 && (
          <section className="insp-section">
            <div className="insp-section-title">Simulation</div>
            {main.map(row)}
          </section>
        )}
        {GROUPS.map((g) => {
          const fields = attrs.filter((a) => a.group === g.id)
          if (!fields.length) return null
          const filled = fields.filter((a) => (values[a.key] ?? '').trim() !== '').length
          return (
            <details className="insp-group" key={g.id} open={g.open}>
              <summary className="insp-section-title">
                {g.title}
                <span className="insp-group-count">
                  {filled ? `${filled}/${fields.length} set` : fields.length}
                </span>
              </summary>
              {g.note && <div className="insp-group-note">{g.note}</div>}
              {fields.map(row)}
            </details>
          )
        })}
        {targetsFor(node.data.unitId).length > 0 && (
          <ControllerEditor node={node} tanks={tanks} onPatchNode={onPatchNode} />
        )}
        <label className="insp-check">
          <input
            type="checkbox"
            checked={!!node.data.showAttrs}
            onChange={(e) => onPatchNode(node.id, { showAttrs: e.target.checked })}
          />
          <span>Show values on canvas</span>
        </label>
        <details className="insp-help">
          <summary>Value formats</summary>
          <div>
            <code>2000</code> constant<br />
            <code>[1500, 800, 2500]</code> linear profile across the run<br />
            <code>1500 + 500*sin(2*pi*t/24)</code> pattern in time <code>t</code> (days)
          </div>
        </details>
      </>
    )
  } else if (node && node.type === 'text') {
    body = <div className="insp-hint">Text label — double-click it on the canvas to edit.</div>
  } else if (node && node.type === 'junction') {
    body = <div className="insp-hint">Junction (a pipe split / tap point).</div>
  } else if (edge) {
    body = (
      <>
        <div className="insp-title">Pipe / stream</div>
        <div className="insp-field">
          <span>Carries</span>
          <div className="stream-row">
            <span className="stream-swatch" style={{ background: streamColor(edge.data?.streamType) }} />
            <select
              value={edge.data?.streamType ?? 'process'}
              onChange={(e) => onPatchEdge(edge.id, { streamType: e.target.value })}
            >
              {STREAMS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <label className="insp-field">
          <span>Name</span>
          <input
            value={edge.data?.name ?? ''}
            placeholder="e.g. RAS, WAS"
            onChange={(e) => onPatchEdge(edge.id, { name: e.target.value })}
          />
        </label>
        <label className="insp-field">
          <span>Flow [m³/d]</span>
          <input
            inputMode="decimal"
            value={flowText}
            placeholder="e.g. 1200"
            onChange={(e) => {
              const v = e.target.value
              setFlowText(v)
              const n = v.trim() === '' ? undefined : Number(v)
              onPatchEdge(edge.id, { flow: n != null && isFinite(n) ? n : undefined })
            }}
          />
        </label>
        <label className="insp-check">
          <input
            type="checkbox"
            checked={!!edge.data?.showFlow}
            onChange={(e) => onPatchEdge(edge.id, { showFlow: e.target.checked })}
          />
          <span>Label flow on canvas</span>
        </label>
        <div className="insp-hint">
          The colour shows what the pipe carries. When “Scale by flow” is on, line thickness scales with
          flow, relative to the largest flow in the diagram.
        </div>
      </>
    )
  } else {
    body = <div className="insp-hint">Select a unit or a pipe to edit its properties.</div>
  }

  return (
    <aside className="inspector">
      <div className="inspector-head">Properties</div>
      <div className="inspector-body">{body}</div>
    </aside>
  )
}
