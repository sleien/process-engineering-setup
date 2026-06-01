import type { AppNode, AppEdge, ProjectFile } from './types'
import { getStreamColors, sanitizeColors, DEFAULT_STREAM_COLORS, type StreamColors } from './streams'

const KEY = 'wwtp-designer:autosave'
const COLORS_KEY = 'wwtp-designer:colors'

export function makeProject(
  nodes: AppNode[],
  edges: AppEdge[],
  viewport?: ProjectFile['viewport'],
  settings?: ProjectFile['settings'],
): ProjectFile {
  return { version: 1, nodes, edges, viewport, settings }
}

export function parseProject(text: string): ProjectFile | null {
  try {
    const p = JSON.parse(text)
    if (p && p.version === 1 && Array.isArray(p.nodes) && Array.isArray(p.edges)) {
      return { version: 1, nodes: p.nodes, edges: p.edges, viewport: p.viewport, settings: p.settings }
    }
  } catch {
    /* ignore */
  }
  return null
}

export function saveAutosave(p: ProjectFile): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(p))
  } catch {
    /* ignore quota / privacy mode */
  }
}

export function loadAutosave(): ProjectFile | null {
  try {
    const s = localStorage.getItem(KEY)
    return s ? parseProject(s) : null
  } catch {
    return null
  }
}

export function clearAutosave(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}

/** Persist the editable stream-colour palette to the browser (separate from the project). */
export function saveColors(colors: StreamColors): void {
  try {
    localStorage.setItem(COLORS_KEY, JSON.stringify(colors))
  } catch {
    /* ignore quota / privacy mode */
  }
}

/** Load the saved palette, merged over the factory defaults. Null if nothing valid was stored. */
export function loadColors(): StreamColors | null {
  try {
    const s = localStorage.getItem(COLORS_KEY)
    if (!s) return null
    return { ...DEFAULT_STREAM_COLORS, ...sanitizeColors(JSON.parse(s)) }
  } catch {
    return null
  }
}

/** Parse an uploaded colour file into a full palette (defaults fill any gaps). Null if invalid. */
export function parseColors(text: string): StreamColors | null {
  try {
    const parsed = sanitizeColors(JSON.parse(text))
    if (Object.keys(parsed).length === 0) return null
    return { ...getStreamColors(), ...parsed }
  } catch {
    return null
  }
}
