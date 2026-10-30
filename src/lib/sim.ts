// Client for the PeePyPoo simulation backend (see server/).
//
// The backend turns the diagram (unit nodes + pipe edges) into an activated-sludge model
// (ASM1 in each CSTR, Aeration on aerated units) and returns the simulated time series.
//
// In production the app is served by FastAPI on the same origin, so a relative path works.
// During Vite dev, /api/* is proxied to :8080 (see vite.config.ts).

import type { AppEdge, AppNode, ProjectFile } from './types'

export type ReactorRef = {
  index: number
  label: string
  unitId: string
  aeration: boolean
  /** kLa when constant (1/d). `null` when time-varying — see `kLa_report`. */
  kLa: number | null
  volume_m3: number
  /** New: temperature (°C) applied to the reactor (currently fixed at 20). */
  temperature_c?: number
  /** New: set when kLa is time-varying — carries description + sine/list data. */
  kLa_report?: TimeValueDetail
  /** Static flow through this reactor (m³/d), from the resolved flow plan. */
  throughput_m3_per_d?: number
  /** Where this reactor's outflow goes (empty label "Effluent / sink" = out of plant). */
  feeds?: StreamRef[]
  /** What arrives here — upstream reactors and influents. */
  fed_by?: (StreamRef & { kind: 'reactor' | 'influent' | 'bypass' })[]
  /** Set on an SBR: the fill/react/settle/decant clock driving its aeration. */
  cycle?: CycleInfo | null
  /** Set on a unit carrying a controlled bypass branch. */
  bypass?: BypassInfo | null
  /** Set on a unit that keeps its own solids (SBR, MBR). */
  retention?: RetentionInfo | null
  /** Set on a primary / intermediate clarifier: what it takes out of the line. */
  settler?: SettlerInfo | null
  /** The controllers that set something on this unit. */
  controllers?: ControllerInfo[]
}

/** A controller as the backend wired it (see server/controllers.py `summarize`). */
export type ControllerInfo = {
  /** The unit it sits on. */
  on: string
  target: 'kLa' | 'Q_was' | 'Qr' | 'Qu'
  target_text: string
  unit: string
  period_days: number
  default: string
  as_text: string
}

/** What one controller set over the run, as a step series. */
export type ControlSeries = {
  on: string
  target: string
  label: string
  unit: string
  /** How many times the setting changed. */
  changes: number
  t_days: number[]
  values: number[]
}

export type SettlerInfo = {
  /** Share of the incoming suspended solids removed (0–1). */
  removal: number
  underflow_m3_per_d: number
  f_ns: number
  as_text: string
}

export type StreamRef = {
  id: string
  label: string
  flow_m3_per_d: number
}

export type CycleInfo = {
  cycle_h: number
  phases_h: { fill: number; react: number; settle: number; decant: number }
  offset_h: number
  kLa_react: number
  as_text: string
}

export type BypassInfo = {
  around: string
  measured_at: string
  when: string
  op: string
  value: number
  flow_m3_per_d: number
  base_flow_m3_per_d: number
  period_days: number
  as_text: string
}

export type RetentionInfo = {
  internal_return_m3_per_d: number
  /** Fixed waste flow, sized for the unit's sludge age. */
  waste_m3_per_d: number
  /** The sludge age the unit actually runs at (d). */
  srt_d: number
  /** The sludge age asked for; differs from `srt_d` only when it cannot be reached. */
  srt_target_d: number
  f_ns: number
  as_text: string
}

export type TopologyInfo = {
  reactor_count: number
  street_count: number
  /** Each parallel branch, as the reactor labels along it. */
  streets: string[][]
  terminals: string[]
  sources: string[]
}

export type ClarifierInfo = {
  name: string
  f_ns: number
  ras_m3_per_d: number
  /** Fixed waste flow (m³/d). */
  was_m3_per_d: number
  /** The sludge age the loop runs at (d). */
  srt_d: number
  /** The sludge age asked for, when one was (null when the WAS was set directly). */
  srt_target_d: number | null
  /** Where the waste came from: the clarifier's SRT, its Q_was, or the default SRT. */
  srt_source: 'SRT' | 'Q_was' | 'default'
  loop_volume_m3: number
  fed_by?: string
  returns_to?: string
  /** Controllers on the clarifier's pumps, if any. */
  controllers?: ControllerInfo[]
  control_note: string
}

export type TimeValueDetail = {
  value_at_0: number
  value_at_end: number
  time_dependent: boolean
  description: string
  values?: number[]
  sine?: { offset: number; amp: number; omega: number; phase: number }
}

export type InfluentInfo = {
  label: string
  into_reactor: string
  into_reactor_index: number
  into_reactor_id: string
  /** A feed may be split across several reactors; `into_reactor*` is the first of these. */
  into_reactors?: { label: string; index: number; id: string }[]
  /** Flow in m³/d **at t=0** — backward-compatible with the previous constant-only shape. */
  flow_m3_per_d: number
  /** Concentration at t=0 (mg/L) per state — backward-compatible. */
  composition: Record<string, number>
  composition_source: 'default (BSM1 stabilisation)' | 'user-supplied'
  synthetic: boolean
  /** NEW: names of attributes that vary over time (e.g. ["flow", "S_NH"]). Empty =
   *  fully constant. */
  time_varying?: string[]
  /** NEW: per-attribute detail (list / sinusoid) for the time-varying ones. */
  time_varying_detail?: Record<string, TimeValueDetail>
}

export type SimResult = {
  /** Time axis in days. */
  t_days: number[]
  /** ASM1 state names present in the result (S_S, S_O, S_NH, S_NO, X_BH, …). */
  states: string[]
  /** series[<reactor | 'eff'>][state] = values aligned (by index, after resampling) with a
   *  shared time grid of the same length as the largest series.
   *
   *  NEW: `total_influent_flow` is a `number[]` of the total influent flow (m³/d)
   *  over time when any influent is time-varying; the UI can plot this alongside
   *  concentrations. */
  series: Record<string, { [state: string]: number[] }>
  reactors: ReactorRef[]
  warnings: string[]
  t_end_days: number
  elapsed_s: number
  /** NEW: total influent flow (m³/d) sampled over time — present when any influent is
   *  time-varying; `null`/absent for an all-constant plant. */
  total_influent_flow?: number[] | null
  /** What each controller set over the run. */
  controls?: ControlSeries[]
  /** Id of this run in the server's history (absent when it could not be saved). */
  history_id?: string | null
  /** Where the plant feed enters and the effluent leaves — echoed back for the UI to show
   *  and edit. */
  setup: {
    /** Every influent used by the model, in train order. There is normally one but a
     *  diagram can have several (multiple Influent units, or side-feeds). */
    influents: InfluentInfo[]
    /** Sum of all influent flows **at t=0** in m³/d. */
    total_flow_m3_per_d: number
    effluent: {
      from_reactor: string
      from_reactor_id: string
    }
    /** The resolved flow graph: parallel streets, where flow enters and where it leaves. */
    topology?: TopologyInfo
    /** Present only when a Clarifier unit is on the canvas (RAS/WAS + MLSS control). */
    clarifier?: ClarifierInfo | null
    /** Every controller in the plant. */
    controllers?: ControllerInfo[]
  }
}

type Payload = {
  units: object[]
  edges: object[]
  /** The whole diagram, kept in the run history so the run can be restored. */
  project?: ProjectFile
  time_days?: number
  /** Optional user override for the influent flow (m³/d). */
  influent_flow?: number
  /** Optional per-state overrides (name → value) applied to the default BSM1 influent composition. */
  influent_overrides?: Record<string, number>
}

function payloadFromGraph(nodes: AppNode[], edges: AppEdge[], opts: {
  time_days?: number
  influent_flow?: number
  influent_overrides?: Record<string, number>
  project?: ProjectFile
}): Payload {
  return {
    ...(opts.project ? { project: opts.project } : {}),
    units: nodes
      .filter((n) => n.type === 'unit')
      .map((n) => ({ id: n.id, type: 'unit', data: n.data as Record<string, unknown> })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, data: (e.data as Record<string, unknown>) ?? {} })),
    ...(opts.time_days != null ? { time_days: opts.time_days } : {}),
    ...(opts.influent_flow != null ? { influent_flow: opts.influent_flow } : {}),
    ...(opts.influent_overrides && Object.keys(opts.influent_overrides).length
      ? { influent_overrides: opts.influent_overrides }
      : {}),
  }
}

export class SimError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message)
  }
}

/** POST the diagram to /api/simulate and return the solved result.
 *
 *  The very first call can take several minutes (Julia precompile); `timeoutMs` should be
 *  generous. Default is 15 min so the cold start can't abort a legitimate long run.
 */
export async function simulate(
  nodes: AppNode[],
  edges: AppEdge[],
  opts: {
    time_days?: number
    timeoutMs?: number
    signal?: AbortSignal
    influent_flow?: number
    influent_overrides?: Record<string, number>
    project?: ProjectFile
  } = {},
): Promise<SimResult> {
  const { timeoutMs = 15 * 60_000 } = opts
  const controller = new AbortController()
  const onAbort = () => controller.abort()
  opts.signal?.addEventListener('abort', onAbort, { once: true })
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch('/api/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payloadFromGraph(nodes, edges, opts)),
      signal: controller.signal,
    })
    const text = await res.text()
    if (!res.ok) {
      let detail = text
      try {
        const parsed = JSON.parse(text)
        detail = parsed.detail ?? text
      } catch {
        /* keep raw body */
      }
      throw new SimError(detail, res.status)
    }
    return JSON.parse(text)
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      if (opts.signal?.aborted) throw opts.signal.reason ?? new SimError('Simulation cancelled')
      throw new SimError('The simulation did not finish in time. This is usually the one-off Julia startup — try again.')
    }
    throw e
  } finally {
    window.clearTimeout(timer)
    opts.signal?.removeEventListener('abort', onAbort)
  }
}


// ---- Python export (server/export_python.py) -------------------------------------------

/** A standalone Python script that runs this diagram's simulation on another machine. */
export async function exportPythonScript(
  nodes: AppNode[],
  edges: AppEdge[],
  opts: {
    time_days?: number
    influent_flow?: number
    influent_overrides?: Record<string, number>
    name?: string
  } = {},
): Promise<{ filename: string; text: string }> {
  const res = await fetch('/api/export/python', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payloadFromGraph(nodes, edges, opts), label: opts.name ?? 'plant' }),
  })
  const text = await res.text()
  if (!res.ok) {
    let detail = text
    try {
      detail = JSON.parse(text).detail ?? text
    } catch {
      /* keep raw body */
    }
    throw new SimError(typeof detail === 'string' ? detail : JSON.stringify(detail), res.status)
  }
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? 'plant.py'
  return { filename, text }
}

// ---- Run history (server/history.py) ------------------------------------------------

export type HistoryMeta = {
  id: string
  /** ISO timestamp, local time of the server. */
  created: string
  label: string
  status: 'ok' | 'failed'
  elapsed_s: number
  t_end_days: number | null
  units: number
  reactors: string[]
  warnings: number
  controllers: number
  error: string
  /** Effluent means over the last tenth of the run (mg/L). */
  effluent: Partial<Record<'COD' | 'NH4' | 'NO3' | 'TN' | 'TSS' | 'O2', number>>
}

export type HistoryRecord = {
  meta: HistoryMeta
  project: ProjectFile | null
  request: { time_days?: number | null; influent_flow?: number | null; influent_overrides?: Record<string, number> }
  result: SimResult | null
  error: string | null
}

async function historyCall<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/history${path}`, init)
  const text = await res.text()
  if (!res.ok) {
    let detail = text
    try {
      detail = JSON.parse(text).detail ?? text
    } catch {
      /* keep raw body */
    }
    throw new SimError(detail, res.status)
  }
  return JSON.parse(text) as T
}

export function listHistory(): Promise<{ runs: HistoryMeta[]; max_runs: number }> {
  return historyCall('')
}

export function getHistoryRun(id: string): Promise<HistoryRecord> {
  return historyCall(`/${encodeURIComponent(id)}`)
}

export function renameHistoryRun(id: string, label: string): Promise<HistoryMeta> {
  return historyCall(`/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label }),
  })
}

export function deleteHistoryRun(id: string): Promise<{ ok: boolean }> {
  return historyCall(`/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
