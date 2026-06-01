import {
  Background,
  BackgroundVariant,
  ConnectionMode,
  Controls,
  MiniMap,
  ReactFlow,
  type DefaultEdgeOptions,
  type EdgeTypes,
  type NodeTypes,
  type OnConnect,
  type OnConnectEnd,
  type OnConnectStart,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react'
import type { AppEdge, AppNode } from '../lib/types'
import UnitNode from '../nodes/UnitNode'
import TextNode from '../nodes/TextNode'
import JunctionNode from '../nodes/JunctionNode'
import PipeEdge from '../edges/PipeEdge'
import { defaultPipeMarker } from '../lib/connect'

// Each component is typed for its specific node/edge; cast the maps to satisfy React Flow's
// general NodeTypes/EdgeTypes (a known TS variance limitation with discriminated node unions).
const nodeTypes = { unit: UnitNode, text: TextNode, junction: JunctionNode } as unknown as NodeTypes
const edgeTypes = { pipe: PipeEdge } as unknown as EdgeTypes

const defaultEdgeOptions: DefaultEdgeOptions = {
  type: 'pipe',
  markerEnd: defaultPipeMarker,
  data: { routing: 'step' as const },
}

function miniMapColor(n: AppNode): string {
  if (n.type === 'junction') return '#111827'
  if (n.type === 'text') return '#e5e7eb'
  return '#93c5fd'
}

export type CanvasProps = {
  nodes: AppNode[]
  edges: AppEdge[]
  onNodesChange: OnNodesChange<AppNode>
  onEdgesChange: OnEdgesChange<AppEdge>
  onConnect: OnConnect
  onConnectStart: OnConnectStart
  onConnectEnd: OnConnectEnd
  onEdgeDoubleClick: (event: React.MouseEvent, edge: AppEdge) => void
  onDrop: (event: React.DragEvent) => void
  onDragOver: (event: React.DragEvent) => void
  handMode: boolean
}

export default function Canvas(props: CanvasProps) {
  return (
    <div
      className={`canvas${props.handMode ? ' hand-mode' : ''}`}
      onDrop={props.onDrop}
      onDragOver={props.onDragOver}
    >
      <ReactFlow<AppNode, AppEdge>
        nodes={props.nodes}
        edges={props.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={props.onNodesChange}
        onEdgesChange={props.onEdgesChange}
        onConnect={props.onConnect}
        onConnectStart={props.onConnectStart}
        onConnectEnd={props.onConnectEnd}
        onEdgeDoubleClick={props.onEdgeDoubleClick}
        isValidConnection={(c) => c.source !== c.target}
        connectionMode={ConnectionMode.Loose}
        defaultEdgeOptions={defaultEdgeOptions}
        deleteKeyCode={null}
        snapToGrid
        snapGrid={[8, 8]}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.1}
        maxZoom={4}
        multiSelectionKeyCode={['Meta', 'Shift', 'Control']}
        connectionRadius={28}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#cbd5e1" />
        <MiniMap pannable zoomable nodeColor={miniMapColor} />
        <Controls />
      </ReactFlow>
    </div>
  )
}
