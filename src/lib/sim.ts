// Client for the PeePyPoo simulation backend (see server/).
//
// The backend turns the diagram (unit nodes + pipe edges) into an activated-sludge model
// (ASM1 in each CSTR, Aeration on aerated units) and returns the simulated time series.
//
// In production the app is served by FastAPI on the same origin, so a relative path works.
// During Vite dev, /api/* is proxied to :8080 (see vite.config.ts).

import type { AppEdge, AppNode } from './types'

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
  }
}

type Payload = {
  units: object[]
  edges: object[]
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
}): Payload {
  return {
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
