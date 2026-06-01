import { useCallback, useEffect, useReducer, useRef } from 'react'
import type { AppEdge, AppNode } from './types'

type Snapshot = { nodes: AppNode[]; edges: AppEdge[] }

/**
 * A signature of the diagram covering only what a user would want to undo — node positions/data
 * and edge wiring/data (including routing) — and deliberately *not* transient UI flags like
 * selection or dragging, so merely clicking around or hovering never piles up history steps.
 */
function graphKey(s: Snapshot): string {
  const n = s.nodes.map((nd) => ({ i: nd.id, t: nd.type, p: nd.position, d: nd.data }))
  const e = s.edges.map((ed) => ({
    i: ed.id,
    s: ed.source,
    t: ed.target,
    sh: ed.sourceHandle ?? null,
    th: ed.targetHandle ?? null,
    d: ed.data,
  }))
  return JSON.stringify({ n, e })
}

const MAX_STEPS = 100

/**
 * Undo/redo for the node/edge graph. Rather than instrumenting every mutation site, it watches
 * the live state and, a short debounce after it settles, records one history step — so a whole
 * drag, a connect, a delete, an inspector edit, a routing toggle, or a branch each collapse to a
 * single undoable change. `undo`/`redo` flush any pending step first, then swap the graph; the
 * swap itself is flagged so it isn't recorded as new history.
 *
 * Snapshots are taken from the `nodes`/`edges` passed in — the authoritative React state that is
 * actually rendered — not from the React Flow store, which can lag behind for edge `data` changes.
 */
export function useUndoRedo(opts: {
  nodes: AppNode[]
  edges: AppEdge[]
  setNodes: (nodes: AppNode[]) => void
  setEdges: (edges: AppEdge[]) => void
  initial: Snapshot
}) {
  const { nodes, edges, setNodes, setEdges, initial } = opts

  // Always-current view of the live graph (the same arrays we render and watch), so commit and
  // undo/redo snapshot exactly what's on screen.
  const live = useRef<Snapshot>({ nodes, edges })
  live.current = { nodes, edges }

  const hist = useRef<{ past: Snapshot[]; future: Snapshot[]; baseline: Snapshot; baselineKey: string } | null>(null)
  if (hist.current === null) {
    hist.current = { past: [], future: [], baseline: initial, baselineKey: graphKey(initial) }
  }
  // While true, the next state change came from undo/redo itself and must not be recorded.
  const applying = useRef(false)
  // Re-render when the stacks change so canUndo/canRedo (read from the refs) stay current.
  const [, bump] = useReducer((x: number) => x + 1, 0)

  const commit = useCallback(() => {
    const h = hist.current!
    const cur = live.current
    const curKey = graphKey(cur)
    if (curKey === h.baselineKey) return // nothing meaningful changed (e.g. only selection)
    h.past.push(h.baseline)
    if (h.past.length > MAX_STEPS) h.past.shift()
    h.future = []
    h.baseline = cur
    h.baselineKey = curKey
    bump()
  }, [])

  // Debounced recorder: collapse a settled burst of changes into one step.
  useEffect(() => {
    if (applying.current) {
      applying.current = false
      return
    }
    const id = window.setTimeout(commit, 350)
    return () => window.clearTimeout(id)
  }, [nodes, edges, commit])

  const apply = useCallback(
    (snap: Snapshot, key: string) => {
      const h = hist.current!
      h.baseline = snap
      h.baselineKey = key
      applying.current = true
      setNodes(snap.nodes)
      setEdges(snap.edges)
    },
    [setNodes, setEdges],
  )

  const undo = useCallback(() => {
    commit() // flush a not-yet-recorded change so a step is never lost
    const h = hist.current!
    if (h.past.length === 0) return
    h.future.push(live.current)
    const prev = h.past.pop()!
    apply(prev, graphKey(prev))
    bump()
  }, [commit, apply])

  const redo = useCallback(() => {
    commit() // a genuine pending change clears the redo stack (can't redo past a new edit)
    const h = hist.current!
    if (h.future.length === 0) return
    h.past.push(live.current)
    const next = h.future.pop()!
    apply(next, graphKey(next))
    bump()
  }, [commit, apply])

  return { undo, redo, canUndo: hist.current.past.length > 0, canRedo: hist.current.future.length > 0 }
}
