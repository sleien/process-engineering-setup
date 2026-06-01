import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { JunctionNode } from '../lib/types'

// A junction is the point where one pipe taps into the middle of another. It has a handle on
// each side so every connecting pipe can meet the dot from the direction it comes from (a
// horizontal pipe passes through the middle; a recycle line can approach from the bottom).
function JunctionNodeComponent({ selected }: NodeProps<JunctionNode>) {
  return (
    <div className={`junction-node${selected ? ' selected' : ''}`}>
      <Handle id="top" type="source" position={Position.Top} className="junction-handle" />
      <Handle id="right" type="source" position={Position.Right} className="junction-handle" />
      <Handle id="bottom" type="source" position={Position.Bottom} className="junction-handle" />
      <Handle id="left" type="source" position={Position.Left} className="junction-handle" />
    </div>
  )
}

export default memo(JunctionNodeComponent)
