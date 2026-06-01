import { getSmoothStepPath, getStraightPath, Position } from '@xyflow/react'
import type { XY } from './geometry'

const isVertical = (p: Position) => p === Position.Top || p === Position.Bottom

/** Drop consecutive points that sit on top of each other (within `eps`). */
function dedupe(pts: XY[], eps = 0.5): XY[] {
  const out: XY[] = []
  for (const p of pts) {
    const last = out[out.length - 1]
    if (!last || Math.hypot(p.x - last.x, p.y - last.y) > eps) out.push(p)
  }
  return out
}

/** "M … L … L …" through a list of points, dropping any zero-length repeats. */
function polyline(pts: XY[]): string {
  return dedupe(pts)
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x},${p.y}`)
    .join(' ')
}

/** Pull every coordinate pair out of a path `d` (commands here only take x,y pairs), deduped —
 *  with `borderRadius: 0` a smooth-step path is a pure corner polyline, so this recovers it. */
function pointsFromPath(d: string): XY[] {
  const nums = d.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? []
  const pts: XY[] = []
  for (let i = 0; i + 1 < nums.length; i += 2) pts.push({ x: nums[i], y: nums[i + 1] })
  return dedupe(pts)
}

/** Corner points when a pipe is routed through a Hand-mode waypoint (orthogonal: leave/enter
 *  each port perpendicular and turn at the waypoint). */
function waypointStepPoints(opts: {
  a: XY
  b: XY
  waypoint: XY
  sourcePosition: Position
  targetPosition: Position
}): XY[] {
  const { a, b, waypoint, sourcePosition, targetPosition } = opts
  const sc = isVertical(sourcePosition) ? { x: a.x, y: waypoint.y } : { x: waypoint.x, y: a.y }
  const tc = isVertical(targetPosition) ? { x: b.x, y: waypoint.y } : { x: waypoint.x, y: b.y }
  return [a, sc, waypoint, tc, b]
}

/**
 * The ordered points a pipe actually passes through — the single source of truth for its shape,
 * shared by the drawn path (pipePath), the SVG exporter, and hit-testing (geometry) so tapping
 * or branching off an *orthogonal* pipe lands on the visible line, not the straight chord between
 * its endpoints.
 */
export function pipePoints(opts: {
  a: XY
  b: XY
  waypoint?: XY | null
  routing: 'straight' | 'step'
  sourcePosition: Position
  targetPosition: Position
}): XY[] {
  const { a, b, waypoint, routing, sourcePosition, targetPosition } = opts
  if (waypoint) {
    return routing === 'step' ? dedupe(waypointStepPoints({ a, b, waypoint, sourcePosition, targetPosition })) : [a, waypoint, b]
  }
  if (routing === 'step') {
    const [d] = getSmoothStepPath({
      sourceX: a.x,
      sourceY: a.y,
      targetX: b.x,
      targetY: b.y,
      sourcePosition,
      targetPosition,
      borderRadius: 0,
    })
    return pointsFromPath(d)
  }
  return [a, b]
}

/**
 * One source of truth for a pipe's drawn shape, shared by the on-screen edge (PipeEdge) and
 * the SVG exporter so they always match.
 *
 * A pipe runs from anchor `a` to anchor `b`. An optional `waypoint` is the point the "depth
 * handle" was dragged to (Hand mode), and the pipe is routed *through* it: for orthogonal pipes
 * it leaves/enters each end perpendicular to its port and turns at the waypoint — so a recycle
 * line pulled down runs along the bottom (a clean U). For straight pipes it simply bends the
 * line through the point. With no waypoint the pipe routes exactly as before.
 *
 * Returns the path `d` plus `cx`/`cy`: when a waypoint is set this is the waypoint itself (so
 * the depth handle sits on it and tracks the drag); otherwise it's the path's natural centre
 * (the handle's starting spot, and the flow-label anchor).
 */
export function pipePath(opts: {
  a: XY
  b: XY
  waypoint?: XY | null
  routing: 'straight' | 'step'
  sourcePosition: Position
  targetPosition: Position
}): { d: string; cx: number; cy: number } {
  const { a, b, waypoint, routing, sourcePosition, targetPosition } = opts

  if (waypoint) {
    if (routing === 'step') {
      // Leave the source and enter the target perpendicular to their ports, turning at the
      // waypoint. Same-side ports (e.g. a bottom→bottom recycle) collapse to a clean U at the
      // waypoint's depth; mixed sides make a stair through it.
      return {
        d: polyline(waypointStepPoints({ a, b, waypoint, sourcePosition, targetPosition })),
        cx: waypoint.x,
        cy: waypoint.y,
      }
    }
    return {
      d: `M ${a.x},${a.y} L ${waypoint.x},${waypoint.y} L ${b.x},${b.y}`,
      cx: waypoint.x,
      cy: waypoint.y,
    }
  }

  if (routing === 'step') {
    const [d, cx, cy] = getSmoothStepPath({
      sourceX: a.x,
      sourceY: a.y,
      targetX: b.x,
      targetY: b.y,
      sourcePosition,
      targetPosition,
      borderRadius: 0,
    })
    return { d, cx, cy }
  }

  const [d, cx, cy] = getStraightPath({ sourceX: a.x, sourceY: a.y, targetX: b.x, targetY: b.y })
  return { d, cx, cy }
}
