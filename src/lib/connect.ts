import { MarkerType, type EdgeMarker } from '@xyflow/react'
import type { AppEdge, AppNode, JunctionNode, PipeEdgeData } from './types'
import { JUNCTION_SIZE, handlePoint, sideTowards, type XY } from './geometry'
import { streamColor } from './streams'

export function makeId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return 'id-' + Math.random().toString(36).slice(2) + Date.now().toString(36)
}

/**
 * Arrowhead marker for a pipe. `scaleByFlow` decides whether the head grows with the line
 * (markerUnits = strokeWidth, matching thick flow-scaled pipes) or stays a fixed size.
 * The actual colour/scale used on screen is derived per render in App (see displayEdges);
 * this default is what newly created edges carry until then.
 */
export function pipeMarker(color: string, scaleByFlow: boolean): EdgeMarker {
  return scaleByFlow
    ? { type: MarkerType.ArrowClosed, color, width: 12.5, height: 12.5 }
    : { type: MarkerType.ArrowClosed, color, width: 14, height: 14, markerUnits: 'userSpaceOnUse' }
}

export const defaultPipeMarker: EdgeMarker = pipeMarker(streamColor(), true)

export function createJunctionNode(point: XY, id: string = makeId()): JunctionNode {
  return {
    id,
    type: 'junction',
    position: { x: point.x - JUNCTION_SIZE / 2, y: point.y - JUNCTION_SIZE / 2 },
    data: {},
  }
}

export function createPipeEdge(params: {
  source: string
  target: string
  sourceHandle?: string | null
  targetHandle?: string | null
  routing?: 'straight' | 'step'
  id?: string
  /** Inherit a parent pipe's stream data (flow, name, colour, …) on split/branch. */
  data?: Partial<PipeEdgeData>
}): AppEdge {
  const routing = params.routing ?? params.data?.routing ?? 'step'
  return {
    id: params.id ?? makeId(),
    source: params.source,
    target: params.target,
    sourceHandle: params.sourceHandle ?? null,
    targetHandle: params.targetHandle ?? null,
    type: 'pipe',
    markerEnd: defaultPipeMarker,
    data: { ...params.data, routing },
  }
}

/**
 * Replace edge A→B with A→junction and junction→B. Each segment meets the junction on the
 * side facing its neighbour, so a horizontal pipe passes straight through the dot's middle.
 */
export function splitEdgeWithJunction(
  nodes: AppNode[],
  edges: AppEdge[],
  edgeId: string,
  junctionId: string,
  junctionPoint: XY,
): AppEdge[] {
  const edge = edges.find((e) => e.id === edgeId)
  if (!edge) return edges
  // Inherit the parent's stream data on both halves, but drop its Hand-mode depth handle: a
  // waypoint belongs to one 2-endpoint pipe and would mis-route both sub-pipes through it.
  const { waypoint: _waypoint, ...data } = edge.data ?? {}
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const a = byId.get(edge.source)
  const b = byId.get(edge.target)
  const aSide = a ? sideTowards(junctionPoint, handlePoint(a, edge.sourceHandle)) : 'left'
  const bSide = b ? sideTowards(junctionPoint, handlePoint(b, edge.targetHandle)) : 'right'
  const a2j = createPipeEdge({
    source: edge.source,
    target: junctionId,
    sourceHandle: edge.sourceHandle,
    targetHandle: aSide,
    data,
  })
  const j2b = createPipeEdge({
    source: junctionId,
    target: edge.target,
    sourceHandle: bSide,
    targetHandle: edge.targetHandle,
    data,
  })
  return [...edges.filter((e) => e.id !== edgeId), a2j, j2b]
}

/**
 * When junctions are deleted, drop their edges; if a junction was a simple pass-through
 * (exactly one edge in and one out), heal the two segments back into a single edge.
 */
export function healJunctions(edges: AppEdge[], removedJunctionIds: string[]): AppEdge[] {
  let result = edges
  for (const jid of removedJunctionIds) {
    const incoming = result.filter((e) => e.target === jid)
    const outgoing = result.filter((e) => e.source === jid)
    result = result.filter((e) => e.source !== jid && e.target !== jid)
    if (incoming.length === 1 && outgoing.length === 1) {
      result = [
        ...result,
        createPipeEdge({
          source: incoming[0].source,
          target: outgoing[0].target,
          sourceHandle: incoming[0].sourceHandle,
          targetHandle: outgoing[0].targetHandle,
          data: incoming[0].data,
        }),
      ]
    }
  }
  return result
}
