// Named stream types for pipes. Picking what a pipe *carries* sets its colour automatically,
// so the same colour doesn't have to be chosen by hand every time (sludge = brown, etc.).
//
// Colours are editable at runtime (see the colour settings UI). The *live* palette below is what
// streamColor() returns, so the canvas, the exporter and the inspector all follow edits — and
// because it's a plain module value, non-React consumers (exportSvg, connect) read it too.

export type StreamType = 'process' | 'influent' | 'effluent' | 'sludge' | 'recycle' | 'air'

export type StreamDef = { id: StreamType; label: string; color: string }

/** Factory defaults (also the order shown in the inspector dropdown + colour settings). */
export const STREAMS: StreamDef[] = [
  { id: 'process', label: 'Process (default)', color: '#111827' },
  { id: 'influent', label: 'Influent / inflow', color: '#64748b' },
  { id: 'effluent', label: 'Effluent', color: '#2563eb' },
  { id: 'sludge', label: 'Sludge (RAS/WAS)', color: '#92400e' },
  { id: 'recycle', label: 'Recycle / return', color: '#7c3aed' },
  { id: 'air', label: 'Air', color: '#0891b2' },
]

export const DEFAULT_STREAM: StreamType = 'process'

export type StreamColors = Record<StreamType, string>

export const DEFAULT_STREAM_COLORS: StreamColors = Object.fromEntries(
  STREAMS.map((s) => [s.id, s.color]),
) as StreamColors

// The live, editable palette.
let palette: StreamColors = { ...DEFAULT_STREAM_COLORS }

/** Colour for a stream type id (falls back to the default/process colour). */
export function streamColor(id?: string): string {
  if (id && id in palette) return palette[id as StreamType]
  return palette[DEFAULT_STREAM]
}

export function getStreamColors(): StreamColors {
  return { ...palette }
}

/** Replace the live palette; unknown/invalid keys fall back to the factory defaults. */
export function setStreamColors(next: Partial<StreamColors>): void {
  palette = { ...DEFAULT_STREAM_COLORS, ...sanitizeColors(next) }
}

export function resetStreamColors(): void {
  palette = { ...DEFAULT_STREAM_COLORS }
}

/** Keep only known stream keys with a valid #rrggbb value — used to guard imported files. */
export function sanitizeColors(input: unknown): Partial<StreamColors> {
  const out: Partial<StreamColors> = {}
  if (input && typeof input === 'object') {
    for (const s of STREAMS) {
      const v = (input as Record<string, unknown>)[s.id]
      if (typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v)) out[s.id] = v
    }
  }
  return out
}
