import { memo } from 'react'
import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from '@xyflow/react'
import type { AppEdge } from '../lib/types'
import { edgeWidth, useFlowDisplay } from '../lib/flow'
import { streamColor } from '../lib/streams'
import { pipePath } from '../lib/pipePath'
import { useHandMode } from './handModeContext'

const ACCENT = '#2563eb'

function PipeEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
  selected,
}: EdgeProps<AppEdge>) {
  const routing = data?.routing ?? 'step'
  const waypoint = data?.waypoint
  const { d: path, cx: labelX, cy: labelY } = pipePath({
    a: { x: sourceX, y: sourceY },
    b: { x: targetX, y: targetY },
    waypoint,
    routing,
    sourcePosition,
    targetPosition,
  })

  const { maxFlow, scaleByFlow } = useFlowDisplay()
  const width = edgeWidth(data?.flow, maxFlow, scaleByFlow)
  const color = streamColor(data?.streamType)
  const flow = data?.flow
  const showFlow = !!data?.showFlow && typeof flow === 'number' && isFinite(flow)

  // The depth handle: drag it (in Hand mode) to route the pipe — e.g. pull a recycle line down
  // to run along the bottom. App's hand-drag handler reads the data-edge-id and updates the
  // edge's waypoint. Only shown while Hand mode is active.
  const handMode = useHandMode()
  const showHandle = handMode

  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: selected ? ACCENT : color,
          strokeWidth: selected ? Math.max(width, 2.6) : width,
        }}
      />
      {showFlow && (
        <EdgeLabelRenderer>
          <div
            className="pipe-flow-label nodrag nopan"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              color,
            }}
          >
            {`Q = ${flow} m³/d`}
          </div>
        </EdgeLabelRenderer>
      )}
      {showHandle && (
        <EdgeLabelRenderer>
          <div
            className={`pipe-depth-handle nodrag nopan${waypoint ? ' set' : ''}`}
            data-edge-id={id}
            title="Drag to move this pipe (set its depth)"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          />
        </EdgeLabelRenderer>
      )}
    </>
  )
}

export default memo(PipeEdgeComponent)
