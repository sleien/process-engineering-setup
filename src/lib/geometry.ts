import { Position } from '@xyflow/react'
import type { AppNode, AppEdge } from './types'
import { unitPorts } from '../units/manifest'
import { pipePoints } from './pipePath'

/** On-canvas diameter of a junction dot (px). */
export const JUNCTION_SIZE = 9

export type XY = { x: number; y: number }

/** Outer size of a node in flow coordinates. */
export function nodeSize(n: AppNode): { w: number; h: number } {
  if (n.type === 'unit') return { w: n.data.width, h: n.data.height }
  if (n.type === 'junction') return { w: JUNCTION_SIZE, h: JUNCTION_SIZE }
  return { w: n.measured?.width ?? 90, h: n.measured?.height ?? 24 }
}

/** Flow-space position of a handle by id (matches the handles placed in UnitNode/JunctionNode). */
export function handlePoint(n: AppNode, handleId?: string | null): XY {
  const { w, h } = nodeSize(n)
  const { x, y } = n.position
  // Unit ports lock onto the tank centre (see manifest `ports`); others use the box centre.
  const { side, ends } = n.type === 'unit' ? unitPorts(n.data.unitId) : { side: 0.5, ends: 0.5 }
  switch (handleId) {
    case 'left':
      return { x, y: y + h * side }
    case 'right':
      return { x: x + w, y: y + h * side }
    case 'top':
      return { x: x + w * ends, y }
    case 'bottom':
      return { x: x + w * ends, y: y + h }
    default:
      // junction handle 'c' (or unknown) → node centre
      return { x: x + w / 2, y: y + h / 2 }
  }
}

/**
 * Offset from a node's top-left to the coordinate an align should line up on:
 * for 'h' (one horizontal line) the side-port height, for 'v' (one vertical line) the
 * top/bottom-port x. Units honour their tank-centre anchor (see manifest `ports`), so
 * aligning a stirred/anoxic reactor next to a plain tank lines up the tank bodies — and,
 * since the vessels share a height, their bottoms — rather than the bounding boxes.
 */
export function alignOffset(n: AppNode, axis: 'h' | 'v'): number {
  const p = handlePoint(n, axis === 'h' ? 'left' : 'top')
  return axis === 'h' ? p.y - n.position.y : p.x - n.position.x
}

export function handlePosition(handleId?: string | null): Position | null {
  switch (handleId) {
    case 'left':
      return Position.Left
    case 'right':
      return Position.Right
    case 'top':
      return Position.Top
    case 'bottom':
      return Position.Bottom
    default:
      return null
  }
}

/** Best-guess side for orthogonal routing when a handle has no fixed side (junctions). */
export function guessPosition(from: XY, to: XY): Position {
  const dx = to.x - from.x
  const dy = to.y - from.y
  if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? Position.Right : Position.Left
  return dy >= 0 ? Position.Bottom : Position.Top
}

export type Side = 'left' | 'right' | 'top' | 'bottom'

/** Which side of `from` faces `to` — used to pick the junction handle an edge connects to. */
export function sideTowards(from: XY, to: XY): Side {
  const dx = to.x - from.x
  const dy = to.y - from.y
  if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? 'right' : 'left'
  return dy >= 0 ? 'bottom' : 'top'
}

function clamp01(t: number): number {
  return Math.max(0, Math.min(1, t))
}

/** Closest point on segment a–b to p, plus the distance. */
export function projectOnSegment(p: XY, a: XY, b: XY): { point: XY; dist: number } {
  const abx = b.x - a.x
  const aby = b.y - a.y
  const len2 = abx * abx + aby * aby
  const t = len2 === 0 ? 0 : clamp01(((p.x - a.x) * abx + (p.y - a.y) * aby) / len2)
  const point = { x: a.x + t * abx, y: a.y + t * aby }
  return { point, dist: Math.hypot(p.x - point.x, p.y - point.y) }
}

/** Closest point on a polyline (its nearest segment) to p, plus the distance. */
export function projectOnPolyline(p: XY, pts: XY[]): { point: XY; dist: number } {
  let best = { point: pts[0] ?? p, dist: Infinity }
  for (let i = 0; i < pts.length - 1; i++) {
    const r = projectOnSegment(p, pts[i], pts[i + 1])
    if (r.dist < best.dist) best = r
  }
  return best
}

/** The ordered points an edge is actually drawn through — its real (possibly orthogonal) shape,
 *  matching PipeEdge/the exporter — so tapping or branching lands on the visible line. */
export function edgePolyline(nodes: AppNode[], e: AppEdge): XY[] | null {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const s = byId.get(e.source)
  const t = byId.get(e.target)
  if (!s || !t) return null
  const a = handlePoint(s, e.sourceHandle)
  const b = handlePoint(t, e.targetHandle)
  const sourcePosition = handlePosition(e.sourceHandle) ?? guessPosition(a, b)
  const targetPosition = handlePosition(e.targetHandle) ?? guessPosition(b, a)
  return pipePoints({
    a,
    b,
    waypoint: e.data?.waypoint,
    routing: e.data?.routing === 'straight' ? 'straight' : 'step',
    sourcePosition,
    targetPosition,
  })
}

/** Find the edge whose body passes within `threshold` of point p (for tapping mid-arrow). Walks
 *  each pipe's real drawn polyline, so an orthogonal/stepped pipe is tappable along its bent line. */
export function findEdgeNearPoint(
  nodes: AppNode[],
  edges: AppEdge[],
  p: XY,
  threshold: number,
): { edgeId: string; point: XY } | null {
  let best: { edgeId: string; point: XY } | null = null
  let bestDist = threshold
  for (const e of edges) {
    const pts = edgePolyline(nodes, e)
    if (!pts) continue
    const { point, dist } = projectOnPolyline(p, pts)
    if (dist < bestDist) {
      bestDist = dist
      best = { edgeId: e.id, point }
    }
  }
  return best
}
