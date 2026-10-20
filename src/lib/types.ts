import type { Node, Edge } from '@xyflow/react'
import type { StreamType } from './streams'
import type { Controller } from './controller'

/** A treatment unit (renders one of the SVG assets). */
export type UnitNodeData = {
  unitId: string
  width: number
  height: number
  /** Optional custom name (e.g. "Aeration 1"). */
  name?: string
  /** Engineering attributes (MLSS, volume, …) keyed by AttrDef.key. */
  attributes?: Record<string, string>
  /** Show a small attribute readout (V, MLSS, …) under the unit on the canvas. */
  showAttrs?: boolean
  /** Optional controller for aerated units (re-evaluated each `period_days`). */
  controller?: Controller
}

/** A free, editable text label (e.g. "275 m³"). */
export type TextNodeData = {
  text: string
  fontSize?: number
}

/** A point on a pipe where another pipe taps in (the "middle of an arrow" connection). */
export type JunctionNodeData = Record<string, never>

export type UnitNode = Node<UnitNodeData, 'unit'>
export type TextNode = Node<TextNodeData, 'text'>
export type JunctionNode = Node<JunctionNodeData, 'junction'>
export type AppNode = UnitNode | TextNode | JunctionNode

export type PipeEdgeData = {
  routing: 'straight' | 'step'
  /** Hand-mode depth handle: a point the pipe is routed through (bend centre). Absolute flow
   *  coords; endpoints always stay on the unit port anchors. Undefined = default routing. */
  waypoint?: { x: number; y: number }
  /** Stream flow rate (m³/d). Drives the pipe's line thickness. */
  flow?: number
  /** Optional stream name (e.g. "RAS", "WAS"). */
  name?: string
  /** What the pipe carries — sets its colour (see lib/streams). */
  streamType?: StreamType
  /** Auto-label the pipe with its flow (e.g. "Q = 2000 m³/d") on the canvas. */
  showFlow?: boolean
}
export type AppEdge = Edge<PipeEdgeData, 'pipe'>

/** Diagram-wide display options (persisted with the project). */
export type ProjectSettings = {
  /** Scale line thickness and arrowheads by flow; off = uniform default pipes. */
  scaleByFlow?: boolean
}

/** Shape of a saved/loaded project file. */
export type ProjectFile = {
  version: 1
  nodes: AppNode[]
  edges: AppEdge[]
  viewport?: { x: number; y: number; zoom: number }
  settings?: ProjectSettings
}
