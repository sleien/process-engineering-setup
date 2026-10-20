// Data export for a solved simulation: CSV (full series, or a single time slice) and JSON.
// Kept separate from the UI so the format is unit-testable and reusable.

import { downloadText } from './download'
import type { SimResult } from './sim'

export type LocationMeta = { key: string; label: string }

function num(v: unknown): string {
  if (v == null) return ''
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? String(n) : ''
}

function baseName(result: SimResult): string {
  const d = new Date()
  const p = (x: number) => String(x).padStart(2, '0')
  return `wwtp-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** Long-format CSV: one row per (time, location, state) with its value. */
export function exportSeriesCsv(result: SimResult, locations: LocationMeta[]): void {
  const lines = ['t_days,location,state,value']
  const n = result.t_days.length
  for (let i = 0; i < n; i++) {
    const t = result.t_days[i]
    for (const loc of locations) {
      const series = result.series[loc.key]
      if (!series) continue
      for (const s of result.states) {
        const v = num(series[s]?.[i])
        if (v === '') continue
        lines.push(`${t},"${loc.label}",${s},${v}`)
      }
    }
  }
  downloadText(lines.join('\n'), `${baseName(result)}-series.csv`, 'text/csv')
}

/** A single time slice: rows = states, columns = locations. `idx` indexes into `t_days`. */
export function exportSnapshotCsv(
  result: SimResult,
  locations: LocationMeta[],
  idx: number,
): void {
  const header = ['state', ...locations.map((l) => `\"${l.label}\"`).join(',')]
  const rows = result.states.map((s) => {
    const cells = locations.map((l) => num(result.series[l.key]?.[s]?.[idx]))
    return [s, ...cells].join(',')
  })
  const t = result.t_days[idx]
  downloadText(
    [header, ...rows].join('\n'),
    `${baseName(result)}-t${String(t)}.csv`,
    'text/csv',
  )
}

/** The full result object, pretty-printed. */
export function exportJson(result: SimResult): void {
  downloadText(JSON.stringify(result, null, 2), `${baseName(result)}.json`, 'application/json')
}
