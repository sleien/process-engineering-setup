import { useEffect, useState } from 'react'
import type { AppEdge, AppNode } from '../lib/types'
import { getUnitAttrs } from '../lib/attributes'
import { getUnit } from '../units/manifest'
import { STREAMS, streamColor } from '../lib/streams'

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
        <label className="insp-field">
          <span>Name</span>
          <input
            value={node.data.name ?? ''}
            placeholder="e.g. Aeration 1"
            onChange={(e) => onPatchNode(node.id, { name: e.target.value })}
          />
        </label>
        {attrs.map((a) => (
          <label className="insp-field" key={a.key}>
            <span>
              {a.label}
              {a.unit ? ` [${a.unit}]` : ''}
            </span>
            <input
              inputMode="decimal"
              value={values[a.key] ?? ''}
              onChange={(e) =>
                onPatchNode(node.id, { attributes: { ...values, [a.key]: e.target.value } })
              }
            />
          </label>
        ))}
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
