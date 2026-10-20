// Results modal:
//   • Status banner (Ready / Running / Failed)
//   • Setup panel that lists the influents (flow + composition) and the effluent source
//   • Explore view — two complementary modes:
//       – Compare: a state tab strip + a line chart of that state across every tank + effluent
//       – Inspect: a time slider + a full snapshot table (every state × every location at t)
//   • Data export — full series CSV, a single time slice CSV, and the raw JSON
//   • Re-run button — fire another simulation without leaving the modal
//
// The influent editor edits the *first* influent used by the model — the diagram can
// have several (side-feeds), but that's an advanced case. Re-run re-solves with the
// edited values overriding whatever was on the canvas.

import { useEffect, useMemo, useRef, useState } from 'react'
import LineChart, { type LineSeries } from './LineChart'
import { STATE_META, STATE_ORDER } from '../lib/states'
import type { SimResult, InfluentInfo, TimeValueDetail } from '../lib/sim'
import { exportSeriesCsv, exportSnapshotCsv, exportJson, type LocationMeta } from '../lib/resultsExport'

const SERIES_COLORS = ['#2563eb', '#16a34a', '#db2777', '#9333ea', '#ea580c', '#0891b2', '#4d7c0f', '#b45309']
const EFFLUENT_COLOR = '#111827'
const EFFLUENT_LABEL = 'Effluent'

export type SimOverrides = {
  influent_flow?: number
  influent_overrides?: Record<string, number>
}

type Props = {
  open: boolean
  result: SimResult | null
  loading: boolean
  error: string | null
  onClose: () => void
  onReRun: (overrides?: SimOverrides) => void
}

/** Format a concentration for a table cell (robust to tiny / zero / missing values). */
function fmt(v: unknown): string {
  const n = typeof v === 'number' ? v : Number(v)
  if (!Number.isFinite(n)) return '—'
  if (n === 0) return '0'
  if (Math.abs(n) < 0.01) return n.toExponential(1)
  return n.toFixed(2)
}

export default function SimulationResults({ open, result, loading, error, onClose, onReRun }: Props) {
  // Selected state for the compare chart.
  const [state, setState] = useState<string>('')
  // Compare (charts) vs Inspect (snapshot table).
  const [mode, setMode] = useState<'compare' | 'inspect'>('compare')
  // Index into result.t_days for the time slider / snapshot table.
  const [timeIdx, setTimeIdx] = useState(0)
  // Editable influent composition. Seeded from the first influent of the most recent result.
  const [composition, setComposition] = useState<Record<string, number>>({})
  const [showComposition, setShowComposition] = useState(false)
  // Key to re-seed the editor when the result identity changes.
  const seededResult = useRef<SimResult | null>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // States offered to the user (in a sensible order, only those present).
  const available = useMemo(() => {
    if (!result) return []
    const set = new Set(result.states)
    const ordered = STATE_ORDER.filter((s) => set.has(s))
    const extra = result.states.filter((s) => !STATE_ORDER.includes(s))
    return [...ordered, ...extra]
  }, [result])

  // Every location we can read a series for (tanks in train order + the effluent).
  const locations = useMemo<LocationMeta[]>(() => {
    if (!result) return []
    const reactorKeys = Object.keys(result.series)
      .filter((k) => k !== 'eff')
      .sort((a, b) => parseInt(a.slice(1)) - parseInt(b.slice(1)))
    const out: LocationMeta[] = reactorKeys.map((k) => ({
      key: k,
      label: result?.reactors.find((r) => `r${r.index}` === k)?.label ?? k,
    }))
    if (result.series.eff) out.push({ key: 'eff', label: EFFLUENT_LABEL })
    return out
  }, [result])

  const nPts = result?.t_days.length ?? 0

  // On a new result: pick a sensible default state and start the slider at the end (steady state).
  useEffect(() => {
    if (!result) return
    if (!state) setState(available[0] ?? 'S_S')
    setTimeIdx(Math.max(0, result.t_days.length - 1))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, available.length])

  // Re-seed the influent editor when a new result arrives (tracked by result identity).
  useEffect(() => {
    if (!result || seededResult.current === result) return
    seededResult.current = result
    const first = result.setup.influents[0]
    if (first) {
      setComposition({ ...first.composition })
    }
  }, [result])

  // First influent used by the model (the one the editor edits).
  const primary = result?.setup.influents[0] as InfluentInfo | undefined
  const extraInfluents = result ? result.setup.influents.slice(1) : []
  // True when anything (influent flow/composition or a reactor kLa) varies over time.
  const anyTimeVarying =
    (result?.setup.influents.some((i) => (i.time_varying ?? []).length > 0) ?? false) ||
    (result?.reactors.some((r) => r.kLa_report?.time_dependent) ?? false)
  const hasFlowSeries = Boolean(result?.total_influent_flow?.length)

  if (!open) return null

  const tAt = (i: number) => result?.t_days[i] ?? 0
  const valueAt = (key: string, s: string, i: number) => result?.series[key]?.[s]?.[i]

  // chartSeries — all locations for the single selected state (compare mode).
  const chartSeries: LineSeries[] = []
  if (result) {
    locations.forEach((loc, i) => {
      const isEff = loc.key === 'eff'
      chartSeries.push({
        label: loc.label,
        color: isEff ? EFFLUENT_COLOR : SERIES_COLORS[i % SERIES_COLORS.length],
        points: result.series[loc.key][state] ?? [],
      })
    })
  }

  const meta = STATE_META[state]
  const currentT = nPts ? result!.t_days[Math.min(timeIdx, nPts - 1)] : 0

  // Build the override object only for things that actually changed, so a plain
  // "re-run" doesn't clobber the existing setup. Returns undefined when nothing
  // changed — the caller can pass it straight through to `simulate`.
  const collectOverrides = (): SimOverrides | undefined => {
    if (!result || !primary) return undefined
    const ov: SimOverrides = {}
    const diffs: Record<string, number> = {}
    for (const k of Object.keys(composition)) {
      const cur = composition[k]
      if (primary.composition[k] === undefined || primary.composition[k] !== cur) diffs[k] = cur
    }
    if (Object.keys(diffs).length) ov.influent_overrides = diffs
    return Object.keys(ov).length ? ov : undefined
  }
  // `dirty` reuses the same check — the Re-run button enables when there's anything to change.
  const dirty = Boolean(collectOverrides())

  const primarySynthetic = primary?.synthetic === true

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal sim-modal" role="dialog" aria-label="Simulation" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span>Simulation</span>
          <div className="modal-head-actions">
            {result && !loading && !error && (
              <div className="sim-export" role="group" aria-label="Export">
                <button type="button" className="sim-export-btn" onClick={() => exportSeriesCsv(result, locations)} title="Full time series: one row per (time, location, state)">
                  ⤓ CSV (series)
                </button>
                <button type="button" className="sim-export-btn" onClick={() => exportSnapshotCsv(result, locations, Math.min(timeIdx, nPts - 1))} title={`All states and locations at t = ${currentT} d`}>
                  ⤓ CSV (slice)
                </button>
                <button type="button" className="sim-export-btn" onClick={() => exportJson(result)} title="The complete result object">
                  ⤓ JSON
                </button>
              </div>
            )}
            <button className="modal-x" onClick={onClose} aria-label="Close">×</button>
          </div>
        </div>

        <div className="modal-body sim-body">
          {/* Status banner */}
          {loading && (
            <div className="sim-banner sim-banner-busy" role="status">
              <span className="sim-spinner" aria-hidden />
              <div>
                <strong>Running…</strong>
                <div>First run compiles the Julia engine and can take a few minutes.</div>
              </div>
            </div>
          )}
          {!loading && error && (
            <div className="sim-banner sim-banner-error" role="alert">
              <span className="sim-icon" aria-hidden>✕</span>
              <div>
                <strong>Failed</strong>
                <div className="sim-error-msg">{error}</div>
              </div>
            </div>
          )}
          {!loading && !error && result && (
            <div className="sim-banner sim-banner-ok" role="status">
              <span className="sim-icon" aria-hidden>✓</span>
              <div>
                <strong>Ready</strong>
                <div>{result.elapsed_s}s · {result.reactors.length} reactor(s) · t = {result.t_end_days} d</div>
              </div>
            </div>
          )}

          {/* Warnings */}
          {result && result.warnings.length > 0 && (
            <div className="sim-warn">
              {result.warnings.map((w, i) => (
                <div key={i}>• {w}</div>
              ))}
            </div>
          )}

          {/* Setup: influents + effluent */}
          {result && (
            <section className="sim-section">
              <h3 className="sim-section-title">
                <span>Setup</span>
                {dirty && <span className="sim-dirty">unsaved changes</span>}
              </h3>

              <div className="sim-setup-grid">
                <div className="sim-setup-influent">
                  <div className="sim-setup-head">
                    <span className="sim-setup-badge influent">INFLUENT</span>
                    {result.setup.influents.length > 1 && (
                      <span className="sim-setup-count">{result.setup.influents.length} feeds</span>
                    )}
                    {anyTimeVarying && (
                      <span className="sim-setup-count tv" title="Some influent or kLa values change over time">
                        ∿ varies over time
                      </span>
                    )}
                  </div>
                  <div className="sim-setup-flowline">
                    <strong>{primary?.flow_m3_per_d}</strong>
                    <span className="sim-setup-unit">m³/d</span>
                    {primary && <span className="sim-setup-into">→ into {primary.into_reactor}</span>}
                    {result.setup.influents.length > 1 && (
                      <span className="sim-setup-total">
                        total {result.setup.influents.reduce((acc, x) => acc + x.flow_m3_per_d, 0)} m³/d
                      </span>
                    )}
                  </div>
                  <div className="sim-setup-note">
                    {primarySynthetic
                      ? 'Flow and composition come from the Simulation window (no Influent unit on the canvas).'
                      : primary?.composition_source === 'default (BSM1 stabilisation)'
                      ? 'Flow is read from the Influent unit on the canvas; composition is the built-in BSM1 stabilisation feed.'
                      : primary
                      ? 'Flow + composition are read from the Influent unit on the canvas.'
                      : 'No influent configured.'}
                  </div>

                  <button
                    type="button"
                    className="sim-link"
                    aria-expanded={showComposition}
                    onClick={() => setShowComposition((v) => !v)}
                  >
                    {showComposition ? 'Hide' : 'Show'} influent composition
                  </button>
                  {showComposition && (
                    <div className="sim-comp-editor">
                      {available.map((k) => (
                        <div key={k} className="sim-comp-row" title={STATE_META[k]?.label}>
                          <span className="sim-comp-name">
                            <strong>{k}</strong>
                            <small>{STATE_META[k]?.unit}</small>
                          </span>
                          <span className="sim-comp-value">
                            {(primary?.composition[k] ?? 0).toFixed(2)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Additional side-feeds (read-only — edit them on the canvas to change) */}
                  {extraInfluents.length > 0 && (
                    <div className="sim-more-influents">
                      <strong className="sim-more-influents-title">Other feeds</strong>
                      {extraInfluents.map((info, i) => (
                        <div key={i} className="sim-more-influent-row">
                          <span className="sim-more-influent-label">{info.label}</span>
                          <span className="sim-more-influent-flow">
                            {info.flow_m3_per_d} m³/d → {info.into_reactor}
                          </span>
                        </div>
                      ))}
                      <span className="sim-more-influent-hint">
                        Side-feeds are set on the canvas — edit the matching Influent unit to change them.
                      </span>
                    </div>
                  )}
                </div>

                <div className="sim-setup-arrow" aria-hidden>
                  <span>→</span>
                </div>

                <div className="sim-setup-effluent">
                  <div className="sim-setup-head">
                    <span className="sim-setup-badge effluent">EFFLUENT</span>
                  </div>
                  <div className="sim-setup-flowline">
                    <strong>{result.setup.effluent.from_reactor}</strong>
                    <span className="sim-setup-unit">(source reactor)</span>
                  </div>
                  <div className="sim-setup-note">
                    The effluent exits the last reactor in the simulated train.
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* Explore: compare (charts) or inspect (time slider + snapshot table) */}
          {result && !loading && !error && (
            <section className="sim-section">
              <div className="sim-explore-head">
                <h3 className="sim-section-title" style={{ margin: 0 }}>
                  <span>Explore</span>
                </h3>
                <div className="sim-mode" role="tablist" aria-label="View mode">
                  <button
                    role="tab"
                    aria-selected={mode === 'compare'}
                    className={`sim-mode-btn${mode === 'compare' ? ' active' : ''}`}
                    onClick={() => setMode('compare')}
                  >
                    Compare
                  </button>
                  <button
                    role="tab"
                    aria-selected={mode === 'inspect'}
                    className={`sim-mode-btn${mode === 'inspect' ? ' active' : ''}`}
                    onClick={() => setMode('inspect')}
                  >
                    Inspect
                  </button>
                </div>
              </div>

              {/* Time slider — available in both modes */}
              <div className="sim-slider">
                <label className="sim-slider-label" htmlFor="sim-time">
                  Time
                  <span className="sim-slider-t">
                    t = <strong>{currentT.toFixed(2)}</strong> d
                    {result.t_end_days ? <small> / {result.t_end_days} d</small> : null}
                  </span>
                </label>
                <input
                  id="sim-time"
                  className="sim-slider-range"
                  type="range"
                  min={0}
                  max={Math.max(0, nPts - 1)}
                  step={1}
                  value={Math.min(timeIdx, Math.max(0, nPts - 1))}
                  onChange={(e) => setTimeIdx(parseInt(e.target.value, 10))}
                  aria-label="Time (d)"
                />
              </div>

              {mode === 'compare' && state && meta && (
                <>
                  <div className="sim-state-tabs" role="tablist">
                    {available.map((s) => (
                      <button
                        key={s}
                        role="tab"
                        aria-selected={state === s}
                        className={`sim-tab${state === s ? ' active' : ''}`}
                        onClick={() => setState(s)}
                        title={STATE_META[s]?.label ?? s}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                  <div className="sim-chart-title">
                    {meta.label} <small>({meta.unit})</small>
                  </div>
                  <div className="sim-legend">
                    {chartSeries.map((s) => (
                      <span key={s.label} className="sim-legend-item">
                        <i style={{ background: s.color }} />
                        {s.label}
                      </span>
                    ))}
                  </div>
                  <LineChart time={result.t_days} series={chartSeries} unit={meta.unit} />
                </>
              )}

              {mode === 'inspect' && (
                <>
                  <div className="sim-slider-note">
                    Snapshot at <strong>t = {currentT.toFixed(2)} d</strong> — every state in every tank and the
                    effluent. Drag the slider to step through the run.
                  </div>
                  <div className="sim-table-wrap">
                    <table className="sim-table sim-snapshot">
                      <thead>
                        <tr>
                          <th>State</th>
                          {locations.map((loc) => (
                            <th key={loc.key} className="num">
                              {loc.label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {available.map((s) => {
                          const m = STATE_META[s]
                          return (
                            <tr key={s}>
                              <td className="sim-state-cell">
                                <strong>{s}</strong>
                                <span className="sim-state-sub">
                                  {m ? `${m.label} · ${m.unit}` : ''}
                                </span>
                              </td>
                              {locations.map((loc) => {
                                const v = valueAt(loc.key, s, Math.min(timeIdx, nPts - 1))
                                return <td key={loc.key} className="num">{fmt(v)}</td>
                              })}
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </section>
          )}

          {/* Total influent flow over time — only when the plant feed is time-varying */}
          {result && !loading && !error && hasFlowSeries && result.total_influent_flow && (
            <section className="sim-section">
              <h3 className="sim-section-title">Influent flow over time <small>(total, m³/d)</small></h3>
              <div className="sim-legend">
                <span className="sim-legend-item">
                  <i style={{ background: '#0d9488' }} />
                  Total flow
                </span>
              </div>
              <LineChart
                time={result.t_days}
                series={[{ label: 'Total flow', color: '#0d9488', points: result.total_influent_flow }]}
                unit="m³/d"
              />
            </section>
          )}
        </div>

        <div className="modal-foot sim-foot">
          {result && !loading && !error && (
            <button
              className="primary"
              onClick={() => onReRun(collectOverrides())}
              title={dirty
                ? 'Apply the influent edits above and re-run'
                : 'Re-run the simulation with the same setup'}
            >
              ↻ {dirty ? 'Apply & re-run' : 'Re-run'}
            </button>
          )}
          <div className="modal-foot-spacer" />
          <button onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
