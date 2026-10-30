import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { getUnit, unitPorts } from '../units/manifest'
import { attrReadout } from '../lib/attributes'
import type { UnitNode } from '../lib/types'

function UnitNodeComponent({ data, selected }: NodeProps<UnitNode>) {
  const unit = getUnit(data.unitId)
  const readout = data.showAttrs ? attrReadout(data.unitId, data.attributes) : []
  // Lock the side ports onto the tank centre (not the bounding-box middle) so arrows
  // align across units of different total height — e.g. an anoxic reactor with a stirrer.
  const ports = unitPorts(data.unitId)
  const sideTop = `${ports.side * 100}%`
  const endsLeft = `${ports.ends * 100}%`
  return (
    <div
      className={`unit-node${selected ? ' selected' : ''}`}
      style={{ width: data.width, height: data.height }}
      title={unit?.label}
    >
      {unit ? (
        <img src={unit.url} alt={unit.label} className="unit-img" draggable={false} />
      ) : (
        <div className="unit-missing">?</div>
      )}
      {/* Four ports. ConnectionMode.Loose lets any of them act as source or target.
          Side ports are nudged to the tank centre via `ports.side` (see manifest). */}
      <Handle id="left" type="source" position={Position.Left} className="port" style={{ top: sideTop }} />
      <Handle id="right" type="source" position={Position.Right} className="port" style={{ top: sideTop }} />
      <Handle id="top" type="source" position={Position.Top} className="port" style={{ left: endsLeft }} />
      <Handle id="bottom" type="source" position={Position.Bottom} className="port" style={{ left: endsLeft }} />
      {readout.length > 0 && (
        <div className="unit-readout">
          {readout.map((r) => (
            <div className={`unit-readout-line${r.key === '__more' ? ' more' : ''}`} key={r.key}>
              {r.text}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default memo(UnitNodeComponent)
