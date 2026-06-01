import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type OnConnect,
  type OnConnectEnd,
  type OnConnectStart,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import Canvas from './components/Canvas'
import Palette from './components/Palette'
import Toolbar from './components/Toolbar'
import Inspector from './components/Inspector'
import ColorSettings from './components/ColorSettings'
import { FlowContext, maxFlowOf } from './lib/flow'
import type { AppEdge, AppNode, ProjectFile } from './lib/types'
import {
  streamColor,
  getStreamColors,
  setStreamColors,
  resetStreamColors,
  DEFAULT_STREAM_COLORS,
  type StreamColors,
  type StreamType,
} from './lib/streams'
import { getUnit } from './units/manifest'
import {
  createJunctionNode,
  createPipeEdge,
  defaultPipeMarker,
  healJunctions,
  makeId,
  pipeMarker,
  splitEdgeWithJunction,
} from './lib/connect'
import {
  JUNCTION_SIZE,
  alignOffset,
  edgePolyline,
  findEdgeNearPoint,
  handlePoint,
  nodeSize,
  projectOnPolyline,
  projectOnSegment,
  sideTowards,
  type Side,
  type XY,
} from './lib/geometry'
import { HandModeContext } from './edges/handModeContext'
import { useUndoRedo } from './lib/useUndoRedo'
import { serializeToSvg, svgToPng } from './lib/exportSvg'
import { downloadBlob, downloadText } from './lib/download'
import {
  clearAutosave,
  loadAutosave,
  loadColors,
  makeProject,
  parseColors,
  parseProject,
  saveAutosave,
  saveColors,
} from './lib/persist'

type DropTarget =
  | { kind: 'unit'; nodeId: string; handle: string | null }
  | { kind: 'edge'; edgeId: string }
  | { kind: 'empty' }

/** Hit-test what is under the cursor when releasing a branch drag (sees through preview els). */
function getDropTarget(x: number, y: number, excludeNodeIds: string[], excludeEdgeIds: string[]): DropTarget {
  for (const el of document.elementsFromPoint(x, y)) {
    const nodeEl = el.closest('.react-flow__node')
    if (nodeEl) {
      const id = nodeEl.getAttribute('data-id') ?? ''
      if (excludeNodeIds.includes(id)) continue
      if (nodeEl.classList.contains('react-flow__node-unit')) {
        const handleEl =
          (el.closest('.react-flow__handle') as Element | null) ??
          (el.classList.contains('react-flow__handle') ? el : null)
        const m = handleEl?.className.match(/handle-(top|right|bottom|left)/)
        return { kind: 'unit', nodeId: id, handle: m ? m[1] : null }
      }
      continue
    }
    const edgeEl = el.closest('.react-flow__edge')
    if (edgeEl) {
      const eid = edgeEl.getAttribute('data-id') ?? ''
      if (excludeEdgeIds.includes(eid)) continue
      return { kind: 'edge', edgeId: eid }
    }
  }
  return { kind: 'empty' }
}

function Editor() {
  const rf = useReactFlow<AppNode, AppEdge>()

  // Restore the last autosaved diagram on first render.
  const initial = useRef<ProjectFile | null>(null)
  if (initial.current === null) {
    initial.current = loadAutosave() ?? { version: 1, nodes: [], edges: [] }
  }

  const [nodes, setNodes, onNodesChange] = useNodesState<AppNode>(initial.current.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<AppEdge>(initial.current.edges)
  // Diagram-wide: scale line thickness + arrowheads by flow (off = uniform default pipes).
  const [scaleByFlow, setScaleByFlow] = useState<boolean>(initial.current.settings?.scaleByFlow ?? true)
  // Hand mode: drag a pipe to route it (set its depth handle). Units stay draggable.
  const [handMode, setHandMode] = useState(false)
  const handModeRef = useRef(handMode)
  handModeRef.current = handMode

  // Editable stream-colour palette (persisted in the browser; download/uploadable). Push any
  // saved palette into the streams module before first paint so the canvas + exports use it.
  const initialColors = useRef<StreamColors | null>(null)
  if (initialColors.current === null) {
    initialColors.current = loadColors() ?? getStreamColors()
    setStreamColors(initialColors.current)
  }
  const [streamColors, setColorsState] = useState<StreamColors>(initialColors.current)
  const [colorsOpen, setColorsOpen] = useState(false)

  useEffect(() => {
    if (initial.current?.viewport) rf.setViewport(initial.current.viewport)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Debounced autosave to localStorage.
  useEffect(() => {
    const id = window.setTimeout(() => {
      saveAutosave(makeProject(nodes, edges, rf.getViewport(), { scaleByFlow }))
    }, 600)
    return () => window.clearTimeout(id)
  }, [nodes, edges, scaleByFlow, rf])

  // Undo / redo (Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y) over the node/edge graph.
  const { undo, redo, canUndo, canRedo } = useUndoRedo({
    nodes,
    edges,
    setNodes,
    setEdges,
    initial: { nodes: initial.current.nodes, edges: initial.current.edges },
  })

  // --- Connecting ---------------------------------------------------------

  const onConnect = useCallback<OnConnect>(
    (c: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...c,
            id: makeId(),
            type: 'pipe',
            markerEnd: defaultPipeMarker,
            data: { routing: 'step' },
          } as AppEdge,
          eds,
        ),
      )
    },
    [setEdges],
  )

  const connectStart = useRef<{ nodeId: string | null; handleId: string | null; handleType: string | null } | null>(
    null,
  )
  const onConnectStart = useCallback<OnConnectStart>((_, params) => {
    connectStart.current = {
      nodeId: params.nodeId ?? null,
      handleId: params.handleId ?? null,
      handleType: params.handleType ?? null,
    }
  }, [])

  // If a connection is released over the *body of another pipe*, tap into it: drop a junction
  // on that pipe, split it, and connect the dragged pipe to the junction.
  const onConnectEnd = useCallback<OnConnectEnd>(
    (event, connectionState) => {
      const start = connectStart.current
      connectStart.current = null

      // A normal handle-to-handle connection is already handled by onConnect.
      if (connectionState?.isValid) return

      const fromNodeId = connectionState?.fromNode?.id ?? start?.nodeId
      const fromHandleId = connectionState?.fromHandle?.id ?? start?.handleId
      const fromType = connectionState?.fromHandle?.type ?? start?.handleType
      if (!fromNodeId) return

      const isTouch = 'changedTouches' in event
      const cx = isTouch ? (event as TouchEvent).changedTouches[0].clientX : (event as MouseEvent).clientX
      const cy = isTouch ? (event as TouchEvent).changedTouches[0].clientY : (event as MouseEvent).clientY
      const point = rf.screenToFlowPosition({ x: cx, y: cy })
      const zoom = rf.getViewport().zoom || 1

      const nodes = rf.getNodes()
      const hit = findEdgeNearPoint(nodes, rf.getEdges(), point, 24 / zoom)
      if (!hit) return

      // Pick which side of the junction the tapped pipe meets: keep a vertical exit (e.g. a
      // recycle leaving a clarifier's bottom) vertical so it routes cleanly under the tanks,
      // otherwise face the dragged-from point.
      const fromNode = nodes.find((n) => n.id === fromNodeId)
      const fromPoint = fromNode ? handlePoint(fromNode, fromHandleId) : hit.point
      let tapSide: Side
      if (fromHandleId === 'bottom') tapSide = 'bottom'
      else if (fromHandleId === 'top') tapSide = 'top'
      else tapSide = sideTowards(hit.point, fromPoint)

      const junctionId = makeId()
      setNodes((nds) => [...nds, createJunctionNode(hit.point, junctionId)])
      setEdges((eds) => {
        const fromTarget = fromType === 'target'
        return [
          ...splitEdgeWithJunction(nodes, eds, hit.edgeId, junctionId, hit.point),
          createPipeEdge({
            source: fromTarget ? junctionId : fromNodeId,
            target: fromTarget ? fromNodeId : junctionId,
            sourceHandle: fromTarget ? tapSide : fromHandleId,
            targetHandle: fromTarget ? fromHandleId : tapSide,
          }),
        ]
      })
    },
    [rf, setNodes, setEdges],
  )

  // Double-clicking a pipe inserts a junction you can then drag a new pipe from.
  const onEdgeDoubleClick = useCallback(
    (event: React.MouseEvent, edge: AppEdge) => {
      const point = rf.screenToFlowPosition({ x: event.clientX, y: event.clientY })
      const nodes = rf.getNodes()
      const junctionId = makeId()
      setNodes((nds) => [...nds, createJunctionNode(point, junctionId)])
      setEdges((eds) => splitEdgeWithJunction(nodes, eds, edge.id, junctionId, point))
    },
    [rf, setNodes, setEdges],
  )

  // --- Branch a new pipe off an existing pipe (drag from an arrow), e.g. sludge wastage ---
  const branchRef = useRef<{
    edgeId: string
    startClient: { x: number; y: number }
    started: boolean
    junctionId?: string
    tempId?: string
    branchEdgeId?: string
  } | null>(null)

  useEffect(() => {
    // Pressing on a pipe arms a potential branch; a drag past threshold starts it.
    const onDown = (e: MouseEvent) => {
      if (e.button !== 0) return
      if (handModeRef.current) return // in Hand mode a pipe-press routes the pipe instead (see below)
      const edgeEl = (e.target as Element | null)?.closest?.('.react-flow__edge')
      if (!edgeEl || edgeEl.classList.contains('branch-preview')) return
      const edgeId = edgeEl.getAttribute('data-id')
      if (edgeId) branchRef.current = { edgeId, startClient: { x: e.clientX, y: e.clientY }, started: false }
    }

    const onMove = (e: MouseEvent) => {
      const b = branchRef.current
      if (!b) return
      if (!b.started) {
        if (Math.hypot(e.clientX - b.startClient.x, e.clientY - b.startClient.y) < 6) return
        b.started = true
        const nodes = rf.getNodes()
        const edge = rf.getEdges().find((ed) => ed.id === b.edgeId)
        let startFlow = rf.screenToFlowPosition(b.startClient)
        if (edge) {
          // Drop the junction onto the pipe's *real* drawn line (orthogonal pipes bend, so this
          // is not the straight chord between the ports) — the branch then leaves from exactly
          // where the user pressed, e.g. a WAS line tapping the clarifier's bottom recycle run.
          const poly = edgePolyline(nodes, edge)
          if (poly) startFlow = projectOnPolyline(startFlow, poly).point
        }
        const cursorFlow = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
        const junctionId = makeId()
        const tempId = makeId()
        const branchEdgeId = makeId()
        b.junctionId = junctionId
        b.tempId = tempId
        b.branchEdgeId = branchEdgeId
        setNodes((nds) => [
          ...nds,
          createJunctionNode(startFlow, junctionId),
          { ...createJunctionNode(cursorFlow, tempId), className: 'branch-preview' },
        ])
        setEdges((eds) => [
          ...splitEdgeWithJunction(nodes, eds, b.edgeId, junctionId, startFlow),
          {
            ...createPipeEdge({
              id: branchEdgeId,
              source: junctionId,
              target: tempId,
              sourceHandle: sideTowards(startFlow, cursorFlow),
              targetHandle: sideTowards(cursorFlow, startFlow),
            }),
            className: 'branch-preview',
          },
        ])
      } else if (b.tempId) {
        const cursorFlow = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
        const tempId = b.tempId
        setNodes((nds) =>
          nds.map((n) =>
            n.id === tempId
              ? { ...n, position: { x: cursorFlow.x - JUNCTION_SIZE / 2, y: cursorFlow.y - JUNCTION_SIZE / 2 } }
              : n,
          ),
        )
      }
    }

    const onUp = (e: MouseEvent) => {
      const b = branchRef.current
      branchRef.current = null
      if (!b || !b.started || !b.junctionId || !b.tempId || !b.branchEdgeId) return
      const { junctionId, tempId, branchEdgeId } = b
      const nodes = rf.getNodes()
      const jNode = nodes.find((n) => n.id === junctionId)
      const jCenter = jNode
        ? { x: jNode.position.x + JUNCTION_SIZE / 2, y: jNode.position.y + JUNCTION_SIZE / 2 }
        : rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
      const cursorFlow = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
      const target = getDropTarget(e.clientX, e.clientY, [tempId, junctionId], [branchEdgeId])

      if (target.kind === 'unit') {
        const tgt = nodes.find((n) => n.id === target.nodeId)
        const tc = tgt
          ? (() => {
              const { w, h } = nodeSize(tgt)
              return { x: tgt.position.x + w / 2, y: tgt.position.y + h / 2 }
            })()
          : cursorFlow
        const targetHandle = target.handle ?? sideTowards(tc, jCenter)
        const sourceHandle = sideTowards(jCenter, tc)
        setNodes((nds) => nds.filter((n) => n.id !== tempId))
        setEdges((eds) =>
          eds.map((ed) =>
            ed.id === branchEdgeId
              ? { ...ed, className: undefined, target: target.nodeId, targetHandle, sourceHandle }
              : ed,
          ),
        )
      } else if (target.kind === 'edge') {
        const j2 = makeId()
        setNodes((nds) => [...nds.filter((n) => n.id !== tempId), createJunctionNode(cursorFlow, j2)])
        setEdges((eds) =>
          splitEdgeWithJunction(nodes, eds, target.edgeId, j2, cursorFlow).map((ed) =>
            ed.id === branchEdgeId
              ? {
                  ...ed,
                  className: undefined,
                  target: j2,
                  targetHandle: sideTowards(cursorFlow, jCenter),
                  sourceHandle: sideTowards(jCenter, cursorFlow),
                }
              : ed,
          ),
        )
      } else {
        // released on empty canvas → keep the dot as an open outlet (label it, e.g. "WAS")
        setNodes((nds) => nds.map((n) => (n.id === tempId ? { ...n, className: undefined } : n)))
        setEdges((eds) =>
          eds.map((ed) =>
            ed.id === branchEdgeId
              ? {
                  ...ed,
                  className: undefined,
                  sourceHandle: sideTowards(jCenter, cursorFlow),
                  targetHandle: sideTowards(cursorFlow, jCenter),
                }
              : ed,
          ),
        )
      }
    }

    document.addEventListener('mousedown', onDown, true)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      document.removeEventListener('mousedown', onDown, true)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [rf, setNodes, setEdges])

  // --- Hand mode: drag a pipe to route it (set its single depth handle) ---
  // Pressing a pipe (or its depth dot) and dragging moves the pipe's waypoint to the cursor,
  // snapped to the 8px grid and to the endpoint anchors — so e.g. a recycle line's bottom run
  // lines up under the ports. Endpoints never move; they stay on the unit anchors. Dropping the
  // handle back on the straight line between the anchors clears the bend.
  useEffect(() => {
    if (!handMode) return
    let dragEdgeId: string | null = null
    let startClient = { x: 0, y: 0 }
    let moved = false

    const anchors = (edge: AppEdge): { a: XY | null; b: XY | null } => {
      const byId = new Map(rf.getNodes().map((n) => [n.id, n]))
      const s = byId.get(edge.source)
      const t = byId.get(edge.target)
      return { a: s ? handlePoint(s, edge.sourceHandle) : null, b: t ? handlePoint(t, edge.targetHandle) : null }
    }

    const snapPoint = (p: XY, edge: AppEdge): XY => {
      const { a, b } = anchors(edge)
      const SNAP = 9 / (rf.getViewport().zoom || 1)
      let x = Math.round(p.x / 8) * 8
      let y = Math.round(p.y / 8) * 8
      for (const ax of [a?.x, b?.x]) if (ax != null && Math.abs(p.x - ax) < SNAP) x = ax
      for (const ay of [a?.y, b?.y]) if (ay != null && Math.abs(p.y - ay) < SNAP) y = ay
      return { x, y }
    }

    const setWaypoint = (edgeId: string, wp: XY | undefined) =>
      setEdges((eds) =>
        eds.map((e) =>
          e.id === edgeId ? { ...e, data: { ...(e.data ?? { routing: 'step' as const }), waypoint: wp } } : e,
        ),
      )

    const onDown = (e: MouseEvent) => {
      if (e.button !== 0) return
      const el = e.target as Element | null
      const handle = el?.closest?.('.pipe-depth-handle')
      const edgeEl = handle ? null : el?.closest?.('.react-flow__edge')
      const id =
        handle?.getAttribute('data-edge-id') ??
        (edgeEl && !edgeEl.classList.contains('branch-preview') ? edgeEl.getAttribute('data-id') : null)
      if (!id) return
      dragEdgeId = id
      startClient = { x: e.clientX, y: e.clientY }
      moved = false
    }

    const onMove = (e: MouseEvent) => {
      if (!dragEdgeId) return
      if (!moved && Math.hypot(e.clientX - startClient.x, e.clientY - startClient.y) < 4) return
      moved = true
      const edge = rf.getEdges().find((ed) => ed.id === dragEdgeId)
      if (!edge) return
      setWaypoint(dragEdgeId, snapPoint(rf.screenToFlowPosition({ x: e.clientX, y: e.clientY }), edge))
    }

    const onUp = () => {
      if (dragEdgeId && moved) {
        const edge = rf.getEdges().find((ed) => ed.id === dragEdgeId)
        const wp = edge?.data?.waypoint
        if (edge && wp) {
          const { a, b } = anchors(edge)
          if (a && b && projectOnSegment(wp, a, b).dist < 6) setWaypoint(dragEdgeId, undefined)
        }
      }
      dragEdgeId = null
    }

    document.addEventListener('mousedown', onDown, true)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      document.removeEventListener('mousedown', onDown, true)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [handMode, rf, setEdges])

  // --- Palette drag & drop ------------------------------------------------

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const unitId = e.dataTransfer.getData('application/wwtp-unit')
      const unit = unitId ? getUnit(unitId) : undefined
      if (!unit) return
      const p = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
      const node: AppNode = {
        id: makeId(),
        type: 'unit',
        position: { x: p.x - unit.width / 2, y: p.y - unit.height / 2 },
        data: { unitId: unit.id, width: unit.width, height: unit.height },
      }
      setNodes((nds) => [...nds, node])
    },
    [rf, setNodes],
  )

  // --- Toolbar actions ----------------------------------------------------

  const addText = useCallback(() => {
    const p = rf.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
    const node: AppNode = { id: makeId(), type: 'text', position: p, data: { text: 'New label' } }
    setNodes((nds) => [...nds, node])
  }, [rf, setNodes])

  const deleteSelection = useCallback(() => {
    const ns = rf.getNodes()
    const es = rf.getEdges()
    const selNodeIds = new Set(ns.filter((n) => n.selected).map((n) => n.id))
    const selJunctions = ns.filter((n) => n.selected && n.type === 'junction').map((n) => n.id)
    let nextEdges = healJunctions(es, selJunctions)
    nextEdges = nextEdges.filter(
      (e) => !selNodeIds.has(e.source) && !selNodeIds.has(e.target) && !e.selected,
    )
    setEdges(nextEdges)
    setNodes(ns.filter((n) => !n.selected))
  }, [rf, setNodes, setEdges])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const ae = document.activeElement as HTMLElement | null
      const inField = !!ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.isContentEditable)

      // Undo / redo. While typing in a field, leave Ctrl/Cmd+Z etc. to the browser's text editor.
      if ((e.metaKey || e.ctrlKey) && !inField) {
        const k = e.key.toLowerCase()
        if (k === 'z' && !e.shiftKey) {
          e.preventDefault()
          undo()
          return
        }
        if (k === 'y' || (k === 'z' && e.shiftKey)) {
          e.preventDefault()
          redo()
          return
        }
      }

      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      if (inField) return
      e.preventDefault()
      deleteSelection()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [deleteSelection, undo, redo])

  // Line up nodes so the arrows between them are straight: 'h' puts them on one horizontal
  // line, 'v' on one vertical line. Alignment is on each node's port anchor (the tank centre
  // for reactors), not its bounding box, so a stirred/anoxic reactor lines up tank-to-tank
  // with a plain tank. Acts on the current selection, or on all units if nothing is selected.
  const alignNodes = useCallback(
    (axis: 'h' | 'v') => {
      const all = rf.getNodes()
      const selected = all.filter((n) => n.selected)
      const targets = selected.length >= 2 ? selected : all.filter((n) => n.type === 'unit')
      if (targets.length < 2) return
      const ids = new Set(targets.map((n) => n.id))

      // Pull any junction sitting on the through-line between two (or more) aligned units onto
      // the line too, so the pipe running through it stays straight. This includes a *tap*
      // junction that also has a branch (e.g. a recycle leaving it) — only its branch bends.
      // Recycle corners (with at most one aligned-unit neighbour) are left where they are.
      const byId = new Map(all.map((n) => [n.id, n]))
      const edgesNow = rf.getEdges()
      const moveIds = new Set(ids)
      for (const j of all) {
        if (j.type !== 'junction' || ids.has(j.id)) continue
        const incident = edgesNow.filter((e) => e.source === j.id || e.target === j.id)
        const neighbors = incident.map((e) => (e.source === j.id ? e.target : e.source))
        const unitNeighbors = neighbors.filter((nid) => ids.has(nid) && byId.get(nid)?.type === 'unit')
        if (unitNeighbors.length >= 2) moveIds.add(j.id)
      }

      if (axis === 'h') {
        const avgY = targets.reduce((s, n) => s + n.position.y + alignOffset(n, 'h'), 0) / targets.length
        setNodes((nds) =>
          nds.map((n) => (moveIds.has(n.id) ? { ...n, position: { ...n.position, y: avgY - alignOffset(n, 'h') } } : n)),
        )
      } else {
        const avgX = targets.reduce((s, n) => s + n.position.x + alignOffset(n, 'v'), 0) / targets.length
        setNodes((nds) =>
          nds.map((n) => (moveIds.has(n.id) ? { ...n, position: { ...n.position, x: avgX - alignOffset(n, 'v') } } : n)),
        )
      }
    },
    [rf, setNodes],
  )

  const setRouting = useCallback(
    (routing: 'straight' | 'step') => {
      setEdges((eds) =>
        eds.map((e) => (e.selected ? { ...e, data: { ...(e.data ?? { routing }), routing } } : e)),
      )
    },
    [setEdges],
  )

  const save = useCallback(() => {
    const obj = rf.toObject()
    const project = makeProject(obj.nodes, obj.edges, obj.viewport, { scaleByFlow })
    downloadText(JSON.stringify(project, null, 2), 'plant.wwtp.json', 'application/json')
  }, [rf, scaleByFlow])

  const open = useCallback(
    (file: File) => {
      const reader = new FileReader()
      reader.onload = () => {
        const p = parseProject(String(reader.result))
        if (!p) {
          window.alert('That file is not a valid WWTP project.')
          return
        }
        setNodes(p.nodes)
        setEdges(p.edges)
        if (p.settings?.scaleByFlow != null) setScaleByFlow(p.settings.scaleByFlow)
        window.setTimeout(() => rf.fitView({ padding: 0.3 }), 0)
      }
      reader.readAsText(file)
    },
    [rf, setNodes, setEdges],
  )

  const exportSvg = useCallback(() => {
    downloadText(serializeToSvg(rf.getNodes(), rf.getEdges(), scaleByFlow), 'plant.svg', 'image/svg+xml')
  }, [rf, scaleByFlow])

  const exportPng = useCallback(async () => {
    const blob = await svgToPng(serializeToSvg(rf.getNodes(), rf.getEdges(), scaleByFlow), 2)
    downloadBlob(blob, 'plant.png')
  }, [rf, scaleByFlow])

  const clear = useCallback(() => {
    if (!window.confirm('Clear the whole diagram? (You can still undo with Ctrl/Cmd+Z.)')) return
    setNodes([])
    setEdges([])
    clearAutosave()
  }, [setNodes, setEdges])

  const fit = useCallback(() => rf.fitView({ padding: 0.3 }), [rf])

  // --- Stream colours (editable palette, saved in the browser) ------------
  const applyColors = useCallback((next: StreamColors) => {
    setStreamColors(next) // live module palette — canvas, exporter and connect read this
    setColorsState({ ...getStreamColors() }) // React state — drives re-render + autosave
  }, [])
  const setStreamColor = useCallback(
    (id: StreamType, color: string) => applyColors({ ...getStreamColors(), [id]: color }),
    [applyColors],
  )
  const resetColors = useCallback(() => {
    resetStreamColors()
    setColorsState({ ...getStreamColors() })
  }, [])
  const downloadColors = useCallback(() => {
    downloadText(JSON.stringify(getStreamColors(), null, 2), 'wwtp-colors.json', 'application/json')
  }, [])
  const uploadColors = useCallback(
    (file: File) => {
      const reader = new FileReader()
      reader.onload = () => {
        const parsed = parseColors(String(reader.result))
        if (!parsed) {
          window.alert('That file is not a valid WWTP colours file.')
          return
        }
        applyColors(parsed)
      }
      reader.readAsText(file)
    },
    [applyColors],
  )
  useEffect(() => {
    saveColors(streamColors)
  }, [streamColors])

  // Patch a node's / edge's data (shallow merge). Used by the Properties panel.
  const patchNode = useCallback(
    (id: string, patch: Record<string, unknown>) => {
      setNodes((nds) => nds.map((n) => (n.id === id ? ({ ...n, data: { ...n.data, ...patch } } as AppNode) : n)))
    },
    [setNodes],
  )
  const patchEdge = useCallback(
    (id: string, patch: Record<string, unknown>) => {
      setEdges((eds) => eds.map((e) => (e.id === id ? ({ ...e, data: { ...e.data, ...patch } } as AppEdge) : e)))
    },
    [setEdges],
  )

  // Flow scale for pipe thickness, and the currently selected element for the panel.
  const maxFlow = useMemo(() => maxFlowOf(edges), [edges])
  const flowValue = useMemo(() => ({ maxFlow, scaleByFlow }), [maxFlow, scaleByFlow])

  // Derive each edge's arrowhead from what it carries (colour) and the global scale setting,
  // so the marker is never stored stale on the edge. Selected pipes get the accent colour.
  const displayEdges = useMemo(
    () =>
      edges.map((e) => ({
        ...e,
        markerEnd: pipeMarker(e.selected ? '#2563eb' : streamColor(e.data?.streamType), scaleByFlow),
      })),
    // streamColors: recompute (and re-render edges) when the palette is edited.
    [edges, scaleByFlow, streamColors],
  )

  const selectedNodes = nodes.filter((n) => n.selected)
  const selectedEdges = edges.filter((e) => e.selected)
  const selNode = selectedNodes.length === 1 ? selectedNodes[0] : undefined
  const selEdge = !selNode && selectedEdges.length === 1 ? selectedEdges[0] : undefined

  return (
    <div className="app">
      <Toolbar
        onAddText={addText}
        onUndo={undo}
        onRedo={redo}
        canUndo={canUndo}
        canRedo={canRedo}
        onDelete={deleteSelection}
        onAlign={alignNodes}
        onSetRouting={setRouting}
        handMode={handMode}
        onHandMode={setHandMode}
        scaleByFlow={scaleByFlow}
        onScaleByFlow={setScaleByFlow}
        onOpenColors={() => setColorsOpen(true)}
        onSave={save}
        onOpen={open}
        onExportSvg={exportSvg}
        onExportPng={exportPng}
        onFit={fit}
        onClear={clear}
      />
      <div className="body">
        <Palette />
        <FlowContext.Provider value={flowValue}>
          <HandModeContext.Provider value={handMode}>
            <Canvas
              nodes={nodes}
              edges={displayEdges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onConnectStart={onConnectStart}
              onConnectEnd={onConnectEnd}
              onEdgeDoubleClick={onEdgeDoubleClick}
              onDrop={onDrop}
              onDragOver={onDragOver}
              handMode={handMode}
            />
          </HandModeContext.Provider>
        </FlowContext.Provider>
        <Inspector node={selNode} edge={selEdge} onPatchNode={patchNode} onPatchEdge={patchEdge} />
      </div>
      <ColorSettings
        open={colorsOpen}
        colors={streamColors}
        onChange={setStreamColor}
        onReset={resetColors}
        onDownload={downloadColors}
        onUpload={uploadColors}
        onClose={() => setColorsOpen(false)}
      />
    </div>
  )
}

export default function App() {
  return (
    <ReactFlowProvider>
      <Editor />
    </ReactFlowProvider>
  )
}
