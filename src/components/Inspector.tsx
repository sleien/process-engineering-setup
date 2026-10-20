import { useEffect, useState } from 'react'
import type { AppEdge, AppNode } from '../lib/types'
import { attrPlaceholder, getUnitAttrs } from '../lib/attributes'
import { getUnit } from '../units/manifest'
import { STREAMS, streamColor } from '../lib/streams'
import ControllerEditor from './ControllerEditor'
import { isAeratedUnit } from '../lib/controller'
import { ENGINE_DEFAULT_INFLUENT } from '../lib/states'

type Props = {
  node?: AppNode
  edge?: AppEdge
  onPatchNode: (id: string, patch: Record<string, unknown>) => void
  onPatchEdge: (id: string, patch: Record<string, unknown>) => void
}

export default function Inspector({ node, edge, onPatchNode, onPatchEdge }: Props) {
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
    body = (
      <>
        <div className="insp-title">{unit?.label ?? 'Unit'}</div>
        <div className="insp-hint insp-hint-time">
        Any numeric field accepts three forms:<br/>
        <code>2000</code> constant &nbsp;·&nbsp;
        <code>[1500, 800, 2500]</code> linear profile across the run &nbsp;·&nbsp;
        <code>1500 + 500*sin(2*pi*t/24)</code> diurnal pattern
        </div>
        <label className="insp-field">
          <span>Name</span>
          <input
            value={node.data.name ?? ''}
            placeholder="e.g. Aeration 1"
            onChange={(e) => onPatchNode(node.id, { name: e.target.value })}
          />
        </label>
        {attrs.map((a) => {
          const dflt =
            node.data.unitId === 'influent' && a.key in ENGINE_DEFAULT_INFLUENT
              ? `${ENGINE_DEFAULT_INFLUENT[a.key]}${a.unit ? ` ${a.unit}` : ''}`
              : attrPlaceholder(a, node.data.unitId)
          return (
            <label className="insp-field" key={a.key}>
              <span>
                {a.label}
                {a.unit ? ` [${a.unit}]` : ''}
              </span>
              <input
                inputMode="decimal"
                value={values[a.key] ?? ''}
                placeholder={dflt}
                onChange={(e) =>
                  onPatchNode(node.id, { attributes: { ...values, [a.key]: e.target.value } })
                }
              />
            </label>
          )
        })}
        {isAeratedUnit(node.data.unitId) && (
          <ControllerEditor node={node} onPatchNode={onPatchNode} />
        )}
        <label className="insp-check">
          <input
            type="checkbox"
            checked={!!node.data.showAttrs}
            onChange={(e) => onPatchNode(node.id, { showAttrs: e.target.checked })}
          />
          <span>Show values on canvas</span>
        </label>
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
