import { createContext, useContext } from 'react'

export const DEFAULT_PIPE_WIDTH = 1.8
const MIN_WIDTH = 1.5
const MAX_WIDTH = 8

/** Largest flow value among edges (0 if none set). */
export function maxFlowOf(edges: { data?: { flow?: number } }[]): number {
  let m = 0
  for (const e of edges) {
    const f = e.data?.flow
    if (typeof f === 'number' && isFinite(f) && f > m) m = f
  }
  return m
}

/** Pipe stroke width (px). When scaling is on, thickness ∝ √flow (constant-velocity pipe),
 *  relative to the diagram's largest flow; pipes with no flow keep the default width. When
 *  scaling is off, every pipe uses the default width. */
export function edgeWidth(flow: number | undefined, maxFlow: number, scaleByFlow = true): number {
  if (!scaleByFlow) return DEFAULT_PIPE_WIDTH
  if (typeof flow !== 'number' || !isFinite(flow) || flow <= 0 || maxFlow <= 0) return DEFAULT_PIPE_WIDTH
  return MIN_WIDTH + Math.sqrt(flow / maxFlow) * (MAX_WIDTH - MIN_WIDTH)
}

/** Provides the diagram's max flow + whether thickness/arrowheads scale, to each edge. */
export const FlowContext = createContext<{ maxFlow: number; scaleByFlow: boolean }>({
  maxFlow: 0,
  scaleByFlow: true,
})
export const useFlowDisplay = () => useContext(FlowContext)
