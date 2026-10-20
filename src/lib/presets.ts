// Simulation presets: a named duration (plus optional influent overrides) that can be
// re-applied with one click, saved under a name, and shared as JSON.
//
// The active settings (simulation duration) live in the browser, separate from the project
// file, the same way the stream-colour palette does (see lib/persist.ts).

/** Simulation settings currently in effect. All fields optional; the backend fills the rest. */
export type SimSettings = {
  /**
   * Simulation duration in days (0.5 .. 90). `'auto'` (or omitted) means the backend picks the
   * duration from the reactor volumes — the app's real default.
   */
  time_days?: number | 'auto'
  /** Influent flow override in m³/d. */
  influent_flow?: number
  /** Per-state influent overrides (name → value, mg/L). */
  influent_overrides?: Record<string, number>
}

/** A saved, named simulation preset. */
export type Preset = {
  name: string
  settings: SimSettings
  /** ISO timestamp of when the preset was last saved (export/import provenance). */
  savedAt?: string
}

export const TIME_DAYS_MIN = 0.5
export const TIME_DAYS_MAX = 90

const STORE_KEY = 'wwtp-designer:presets'

type PresetStore = {
  settings: SimSettings
  presets: Preset[]
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Clamp a stored/entered duration into the range the backend accepts. Out-of-range/invalid → auto. */
export function clampTimeDays(v: number): number | 'auto' {
  if (!Number.isFinite(v) || v <= 0) return 'auto'
  return Math.min(TIME_DAYS_MAX, Math.max(TIME_DAYS_MIN, v))
}

/** Parse the (optional) duration field of a settings object: a number or `'auto'` (backend default). */
export function parseTimeDays(v: unknown): number | 'auto' | undefined {
  if (v === 'auto') return 'auto'
  if (typeof v === 'number') {
    const c = clampTimeDays(v)
    return c === 'auto' ? undefined : c
  }
  return undefined
}

/** Sanitize one settings object out of untrusted data. Null if nothing usable was stored. */
export function parseSettings(v: unknown): SimSettings | null {
  if (!isRecord(v)) return null
  const out: SimSettings = {}
  const td = parseTimeDays(v.time_days)
  if (td !== undefined) out.time_days = td
  if (typeof v.influent_flow === 'number' && Number.isFinite(v.influent_flow) && v.influent_flow > 0) {
    out.influent_flow = v.influent_flow
  }
  if (isRecord(v.influent_overrides)) {
    const ov: Record<string, number> = {}
    for (const [k, val] of Object.entries(v.influent_overrides)) {
      if (typeof val === 'number' && Number.isFinite(val)) ov[k] = val
    }
    if (Object.keys(ov).length) out.influent_overrides = ov
  }
  return Object.keys(out).length ? out : null
}

/** Sanitize one preset. Null if the name or settings are unusable. */
export function parsePreset(v: unknown): Preset | null {
  if (!isRecord(v) || typeof v.name !== 'string' || !v.name.trim()) return null
  const settings = parseSettings(v.settings) ?? (isRecord(v) ? parseSettings(v) : null)
  if (!settings && !isRecord(v.settings)) return null
  const out: Preset = { name: v.name.trim(), settings: settings ?? {} }
  if (typeof v.savedAt === 'string') out.savedAt = v.savedAt
  return out
}

/** Parse any presets JSON (an array, a single preset, or a store shape) into a clean list. */
export function parsePresets(text: string): Preset[] | null {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return null
  }
  const list: unknown[] = Array.isArray(raw)
    ? raw
    : isRecord(raw) && Array.isArray(raw.presets)
      ? raw.presets
      : [raw]
  const seen = new Set<string>()
  const out: Preset[] = []
  for (const item of list) {
    const p = parsePreset(item)
    if (p && !seen.has(p.name)) {
      seen.add(p.name)
      out.push(p)
    }
  }
  return out.length ? out : null
}

export function loadSettings(): SimSettings {
  try {
    const s = localStorage.getItem(STORE_KEY)
    if (!s) return { time_days: 'auto' }
    const store = JSON.parse(s) as Record<string, unknown>
    const settings = parseSettings(store?.settings) ?? {}
    const out: SimSettings = { time_days: 'auto', ...settings }
    return out
  } catch {
    return { time_days: 'auto' }
  }
}

export function loadPresets(): Preset[] {
  try {
    const s = localStorage.getItem(STORE_KEY)
    if (!s) return []
    const store = JSON.parse(s) as Record<string, unknown>
    if (!Array.isArray(store?.presets)) return []
    const presets: Preset[] = []
    const seen = new Set<string>()
    for (const item of store.presets) {
      const p = parsePreset(item)
      if (p && !seen.has(p.name)) {
        seen.add(p.name)
        presets.push(p)
      }
    }
    return presets
  } catch {
    return []
  }
}

export function saveStore(settings: SimSettings, presets: Preset[]): void {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({ settings, presets }))
  } catch {
    /* ignore quota / private mode */
  }
}

/** Replace-or-append a preset with this name, returning the updated list. */
export function upsertPreset(presets: Preset[], preset: Preset): Preset[] {
  const i = presets.findIndex((p) => p.name === preset.name)
  if (i === -1) return [...presets, preset]
  const next = presets.slice()
  next[i] = preset
  return next
}

/**
 * Apply a preset's settings on top of the current ones. A preset field set to `'auto'` or
 * `undefined` clears the current value (that is how a preset turns an override back off).
 */
export function applyPresetToSettings(settings: SimSettings, preset: Preset): SimSettings {
  const next: SimSettings = { ...settings }
  for (const key of Object.keys(preset.settings) as (keyof SimSettings)[]) {
    const v: unknown = preset.settings[key]
    if (v === undefined || v === 'auto') delete next[key]
    else {
      switch (key) {
        case 'time_days':
          next.time_days = v as number | 'auto'
          break
        case 'influent_flow':
          next.influent_flow = v as number
          break
        case 'influent_overrides':
          next.influent_overrides = v as Record<string, number>
          break
      }
    }
  }
  return next
}

/** Human-readable duration for list rows, e.g. "30 d" or "auto". */
export function formatTimeDays(v: number | 'auto' | undefined): string {
  if (v == null || v === 'auto') return 'auto'
  return `${v % 1 === 0 ? v : v.toFixed(1)} d`
}
