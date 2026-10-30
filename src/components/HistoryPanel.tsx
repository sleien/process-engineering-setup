// Simulation history: every run the server solved (server/history.py), newest first.
//
//   • the list — when, name (click to rename), outcome, horizon, solve time, effluent;
//   • per run — open its results, put its diagram back on the canvas, or delete it;
//   • compare — tick two or more runs to overlay their effluent and line up their figures.

import { useEffect, useMemo, useState } from 'react'
import LineChart, { type LineSeries } from './LineChart'
import {
  deleteHistoryRun,
  getHistoryRun,
  listHistory,
  renameHistoryRun,
  type HistoryMeta,
  type HistoryRecord,
} from '../lib/sim'

const COLORS = ['#2563eb', '#16a34a', '#db2777', '#9333ea', '#ea580c', '#0891b2', '#4d7c0f', '#b45309']
const MAX_COMPARE = COLORS.length

// What the comparison chart can show — effluent quantities, the derived ones computed
// from the ASM1 states the same way server/history.py computes the list's figures.
const COD = ['S_I', 'S_S', 'X_I', 'X_S', 'X_BH', 'X_BA', 'X_P']
const SOLIDS = ['X_I', 'X_S', 'X_BH', 'X_BA', 'X_P']
const QUANTITIES: { key: 'COD' | 'NH4' | 'NO3' | 'TN' | 'TSS' | 'O2'; label: string; unit: string }[] = [
  { key: 'TN', label: 'Total N', unit: 'mg N/L' },
  { key: 'NH4', label: 'Ammonium', unit: 'mg N/L' },
  { key: 'NO3', label: 'Nitrate', unit: 'mg N/L' },
  { key: 'COD', label: 'Total COD', unit: 'mg/L' },
  { key: 'TSS', label: 'TSS', unit: 'mg/L' },
  { key: 'O2', label: 'Dissolved O₂', unit: 'mg/L' },
]

function effluentSeries(rec: HistoryRecord, key: (typeof QUANTITIES)[number]['key']): number[] {
  const eff = rec.result?.series?.eff ?? {}
  const n = rec.result?.t_days.length ?? 0
  const g = (s: string) => eff[s] ?? new Array(n).fill(0)
  const sum = (states: string[]) => {
    const cols = states.map(g)
    return Array.from({ length: n }, (_, i) => cols.reduce((a, c) => a + (c[i] ?? 0), 0))
  }
  switch (key) {
    case 'NH4': return g('S_NH')
    case 'NO3': return g('S_NO')
    case 'O2': return g('S_O')
    case 'COD': return sum(COD)
    case 'TSS': return sum(SOLIDS).map((v) => 0.75 * v)
    case 'TN': {
      const [nh, no, nd, xnd, bh, ba, xp] = ['S_NH', 'S_NO', 'S_ND', 'X_ND', 'X_BH', 'X_BA', 'X_P'].map(g)
      return Array.from({ length: n }, (_, i) =>
        nh[i] + no[i] + nd[i] + xnd[i] + 0.086 * (bh[i] + ba[i]) + 0.06 * xp[i])
    }
  }
}

function when(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** The name a run goes by: its label, else what it simulated. */
export function runName(m: HistoryMeta): string {
  if (m.label) return m.label
  if (m.reactors.length) {
    const head = m.reactors.slice(0, 3).join(', ')
    return m.reactors.length > 3 ? `${head} +${m.reactors.length - 3}` : head
  }
  return `${m.units} unit(s)`
}

function fmt(v: number | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)
}

type Props = {
  open: boolean
  /** The run the results window shows, to mark it in the list. */
  currentId?: string | null
  onClose: () => void
  onOpenRun: (rec: HistoryRecord) => void
  onRestoreRun: (rec: HistoryRecord) => void
}

export default function HistoryPanel({ open, currentId, onClose, onOpenRun, onRestoreRun }: Props) {
  const [runs, setRuns] = useState<HistoryMeta[]>([])
  const [maxRuns, setMaxRuns] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const [compare, setCompare] = useState<HistoryRecord[] | null>(null)
  const [quantity, setQuantity] = useState<(typeof QUANTITIES)[number]['key']>('TN')
  const [busy, setBusy] = useState<string | null>(null)

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await listHistory()
      setRuns(r.runs)
      setMaxRuns(r.max_runs)
      setPicked((p) => p.filter((id) => r.runs.some((m) => m.id === id)))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the history — is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    void refresh()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !editing && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const withRecord = async (id: string, fn: (rec: HistoryRecord) => void) => {
    setBusy(id)
    setError(null)
    try {
      fn(await getHistoryRun(id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load that run.')
    } finally {
      setBusy(null)
    }
  }

  const rename = async (id: string, text: string) => {
    setEditing(null)
    try {
      const meta = await renameHistoryRun(id, text)
      setRuns((rs) => rs.map((r) => (r.id === id ? meta : r)))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not rename the run.')
    }
  }

  const remove = async (m: HistoryMeta) => {
    if (!window.confirm(`Delete the run “${runName(m)}” from ${when(m.created)}? This cannot be undone.`)) return
    try {
      await deleteHistoryRun(m.id)
      setRuns((rs) => rs.filter((r) => r.id !== m.id))
      setPicked((p) => p.filter((id) => id !== m.id))
      setCompare((c) => (c ? c.filter((r) => r.meta.id !== m.id) : c))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete the run.')
    }
  }

  const startCompare = async () => {
    setBusy('compare')
    setError(null)
    try {
      const recs = await Promise.all(picked.map((id) => getHistoryRun(id)))
      setCompare(recs.filter((r) => r.result))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the runs to compare.')
    } finally {
      setBusy(null)
    }
  }

  const q = QUANTITIES.find((x) => x.key === quantity)!
  const compareSeries: LineSeries[] = useMemo(
    () =>
      (compare ?? []).map((rec, i) => ({
        label: `${runName(rec.meta)} · ${when(rec.meta.created)}`,
        color: COLORS[i % COLORS.length],
        time: rec.result!.t_days,
        points: effluentSeries(rec, quantity),
      })),
    [compare, quantity],
  )

  if (!open) return null
  const okPicked = picked.filter((id) => runs.find((r) => r.id === id)?.status === 'ok')

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal sim-modal sim-modal-full history-modal" role="dialog" aria-label="Simulation history" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="sim-head-title">
            Simulation history
            <span className="sim-pill">{runs.length}{maxRuns ? ` of ${maxRuns} kept` : ''}</span>
          </span>
          <div className="modal-head-actions">
            <button className="sim-link" onClick={() => void refresh()} disabled={loading}>
              {loading ? 'Loading…' : '↻ Refresh'}
            </button>
            <button className="modal-x" onClick={onClose} aria-label="Close">×</button>
          </div>
        </div>

        <div className="modal-body sim-body">
          {error && <div className="sim-banner sim-banner-error" role="alert"><div>{error}</div></div>}

          {compare && compare.length > 0 && (
            <section className="sim-section">
              <div className="sim-explore-head">
                <h3 className="sim-section-title" style={{ margin: 0 }}>Compare effluent</h3>
                <button className="sim-link" onClick={() => setCompare(null)}>Close comparison</button>
              </div>
              <div className="sim-state-tabs" role="tablist">
                {QUANTITIES.map((x) => (
                  <button key={x.key} role="tab" aria-selected={x.key === quantity}
                    className={`sim-tab${x.key === quantity ? ' active' : ''}`} onClick={() => setQuantity(x.key)}>
                    {x.label}
                  </button>
                ))}
              </div>
              <div className="sim-chart-title">Effluent {q.label} <small>({q.unit})</small></div>
              <LineChart time={[]} series={compareSeries} unit={q.unit} />
              <div className="sim-table-wrap">
                <table className="sim-table history-compare">
                  <thead>
                    <tr>
                      <th>Effluent, last tenth of the run</th>
                      {compare.map((rec, i) => (
                        <th key={rec.meta.id} className="num">
                          <i className="history-swatch" style={{ background: COLORS[i % COLORS.length] }} />
                          {runName(rec.meta)}
                          <small className="history-th-when">{when(rec.meta.created)}</small>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {QUANTITIES.map((x) => (
                      <tr key={x.key}>
                        <td>{x.label} <small className="dim">{x.unit}</small></td>
                        {compare.map((rec) => <td key={rec.meta.id} className="num">{fmt(rec.meta.effluent[x.key])}</td>)}
                      </tr>
                    ))}
                    <tr>
                      <td>Simulated <small className="dim">d</small></td>
                      {compare.map((rec) => <td key={rec.meta.id} className="num">{fmt(rec.meta.t_end_days ?? undefined)}</td>)}
                    </tr>
                    <tr>
                      <td>Solve time <small className="dim">s</small></td>
                      {compare.map((rec) => <td key={rec.meta.id} className="num">{fmt(rec.meta.elapsed_s)}</td>)}
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <div className="history-bar">
            <span className="sim-setup-note">
              {picked.length
                ? `${picked.length} selected`
                : 'Every run is kept here. Tick two or more to compare them.'}
            </span>
            <button
              className="history-compare-btn"
              disabled={okPicked.length < 2 || busy === 'compare'}
              onClick={() => void startCompare()}
              title={okPicked.length < 2 ? 'Tick at least two finished runs' : 'Overlay their effluent'}
            >
              {busy === 'compare' ? 'Loading…' : `Compare${okPicked.length >= 2 ? ` (${okPicked.length})` : ''}`}
            </button>
          </div>

          {!loading && runs.length === 0 && !error && (
            <div className="sim-empty">No runs yet — every simulation you start is saved here.</div>
          )}

          {runs.length > 0 && (
            <ul className="history-list">
              {runs.map((m) => {
                const checked = picked.includes(m.id)
                return (
                  <li key={m.id} className={`history-row${m.id === currentId ? ' current' : ''}${m.status === 'failed' ? ' failed' : ''}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={m.status !== 'ok' || (!checked && picked.length >= MAX_COMPARE)}
                      onChange={(e) => setPicked((p) => (e.target.checked ? [...p, m.id] : p.filter((x) => x !== m.id)))}
                      aria-label={`Select ${runName(m)} for comparison`}
                    />
                    <div className="history-main">
                      {editing?.id === m.id ? (
                        <input
                          className="history-name-input"
                          autoFocus
                          value={editing.text}
                          maxLength={120}
                          placeholder={runName({ ...m, label: '' })}
                          onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                          onBlur={() => void rename(m.id, editing.text)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') void rename(m.id, editing.text)
                            if (e.key === 'Escape') setEditing(null)
                          }}
                        />
                      ) : (
                        <button className="history-name" title="Rename" onClick={() => setEditing({ id: m.id, text: m.label })}>
                          {runName(m)}
                        </button>
                      )}
                      <div className="history-sub">
                        {when(m.created)}
                        {m.id === currentId && <span className="history-tag">shown</span>}
                        {m.status === 'failed'
                          ? <span className="history-err" title={m.error}> · failed: {m.error}</span>
                          : <> · {fmt(m.t_end_days ?? undefined)} d in {m.elapsed_s} s
                              {m.controllers > 0 && ` · ${m.controllers} controller(s)`}
                              {m.warnings > 0 && ` · ${m.warnings} message(s)`}</>}
                      </div>
                    </div>
                    {m.status === 'ok' && (
                      <div className="history-eff" title="Effluent, mean over the last tenth of the run (mg/L)">
                        <span>NH₄ <b>{fmt(m.effluent.NH4)}</b></span>
                        <span>NO₃ <b>{fmt(m.effluent.NO3)}</b></span>
                        <span>TN <b>{fmt(m.effluent.TN)}</b></span>
                        <span>COD <b>{fmt(m.effluent.COD)}</b></span>
                      </div>
                    )}
                    <div className="history-actions">
                      {m.status === 'ok' && (
                        <button disabled={busy === m.id} onClick={() => void withRecord(m.id, onOpenRun)} title="Show this run's results">
                          Open
                        </button>
                      )}
                      <button disabled={busy === m.id} onClick={() => void withRecord(m.id, onRestoreRun)} title="Put the diagram this run simulated back on the canvas">
                        Restore
                      </button>
                      <button className="danger" onClick={() => void remove(m)} title="Delete this run" aria-label={`Delete ${runName(m)}`}>
                        ✕
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <div className="modal-foot sim-foot">
          <span className="sim-setup-note">Runs are kept by the server (server/history/); the oldest go once there are {maxRuns || 'too many'}.</span>
          <div className="modal-foot-spacer" />
          <button onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  )
}
