// An interactive, dependency-free line chart for simulation results: time (x, days) against
// a value (y) for one or more series, drawn as SVG polylines.
//
// Reading it:   hover for a crosshair with every series' value at that time; click to pick
//               that time (the results window moves its time slider there and marks it).
// Zooming:      drag across a span to zoom into it, ⌘/Ctrl + scroll (or pinch) to zoom
//               around the pointer, the − / + buttons; double-click or Reset to see it all.
//               The y axis always fits what is visible.
// Panning:      Shift + drag.
// Legend:       click a series to hide or show it.
//
// The visible time window can be shared between charts: pass `domain` and
// `onDomainChange` and they zoom together.

import { useEffect, useId, useMemo, useRef, useState } from 'react'

export type LineSeries = {
  label: string
  color: string
  points: number[] // one value per index of `time` (or of this series' own `time`)
  /** The series' own time axis — for series sampled differently from the chart's, like a
   *  controller's step series or a run from the history with another horizon. */
  time?: number[]
}

type Domain = [number, number]

type Props = {
  time: number[]
  series: LineSeries[]
  height?: number
  unit?: string
  /** A time to mark, with every series' value there read out under the chart. */
  markerT?: number | null
  /** Called with the time under the pointer when the chart is clicked (not dragged). */
  onPickTime?: (t: number) => void
  /** Visible time window (null = everything). With `onDomainChange`, charts zoom together. */
  domain?: Domain | null
  onDomainChange?: (d: Domain | null) => void
  /** Draw the clickable legend above the chart (default on). */
  legend?: boolean
}

const W = 720
const PAD_L = 52
const PAD_R = 14
const PAD_T = 14
const PAD_B = 30
const DRAG_PX = 4

/** Index of the first element of a sorted array that is >= x. */
function lowerBound(a: number[], x: number): number {
  let lo = 0
  let hi = a.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (a[mid] < x) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** The series' value at time t, linearly interpolated (a step series is stored with a point
 *  either side of each step, so it stays a step). */
function valueAt(ts: number[], vs: number[], t: number): number | undefined {
  const n = Math.min(ts.length, vs.length)
  if (!n || t < ts[0] || t > ts[n - 1]) return undefined
  const i = lowerBound(ts, t)
  if (i >= n) return vs[n - 1]
  if (ts[i] === t || i === 0) return vs[i]
  const t0 = ts[i - 1]
  const t1 = ts[i]
  const f = t1 > t0 ? (t - t0) / (t1 - t0) : 1
  return vs[i - 1] + f * (vs[i] - vs[i - 1])
}

/** Round tick values: steps of 1, 2 or 5 × 10^k. */
function niceTicks(lo: number, hi: number, count: number): { ticks: number[]; step: number } {
  const span = Math.max(hi - lo, 1e-12)
  const raw = span / Math.max(1, count)
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag
  const ticks: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) ticks.push(+v.toFixed(12))
  return { ticks, step }
}

function decimalsFor(step: number): number {
  return Math.max(0, Math.min(6, -Math.floor(Math.log10(step) + 1e-9)))
}

export function fmtValue(v: number | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1000) return v.toFixed(0)
  if (a >= 100) return v.toFixed(1)
  if (a >= 1) return v.toFixed(2)
  if (a === 0) return '0'
  return v.toPrecision(3)
}

/** "12.354 d · day 12, 08:30" — the clock time matters as soon as you look at an SBR cycle. */
export function fmtTime(t: number): string {
  const day = Math.floor(t)
  const mins = Math.round((t - day) * 24 * 60)
  const hh = String(Math.floor(mins / 60) % 24).padStart(2, '0')
  const mm = String(mins % 60).padStart(2, '0')
  return `${t.toFixed(3)} d · day ${day}, ${hh}:${mm}`
}

export default function LineChart({
  time,
  series,
  height = 260,
  unit = '',
  markerT = null,
  onPickTime,
  domain: domainProp,
  onDomainChange,
  legend = true,
}: Props) {
  const H = height
  const plotW = W - PAD_L - PAD_R
  const plotH = H - PAD_T - PAD_B
  const clipId = `clip-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const svgRef = useRef<SVGSVGElement>(null)

  const [ownDomain, setOwnDomain] = useState<Domain | null>(null)
  const controlled = domainProp !== undefined && onDomainChange !== undefined
  const setDomain = (d: Domain | null) => (controlled ? onDomainChange!(d) : setOwnDomain(d))
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [hoverX, setHoverX] = useState<number | null>(null)
  const [drag, setDrag] = useState<{ x0: number; x1: number; pan: boolean; from: Domain } | null>(null)

  const timeOf = (s: LineSeries) => s.time ?? time
  const shown = useMemo(() => series.filter((s) => !hidden.has(s.label)), [series, hidden])

  // The full time extent, and the window being looked at (kept inside it, never empty).
  const full = useMemo<Domain | null>(() => {
    let a = Infinity
    let b = -Infinity
    for (const s of series) {
      const ts = s.time ?? time
      if (!ts.length) continue
      a = Math.min(a, ts[0])
      b = Math.max(b, ts[ts.length - 1])
    }
    return Number.isFinite(a) && Number.isFinite(b) ? [a, b] : null
  }, [series, time])

  const clampDomain = (d: Domain | null): Domain | null => {
    if (!d || !full) return null
    const fullSpan = Math.max(full[1] - full[0], 1e-9)
    const minSpan = fullSpan / 2000
    let [a, b] = d[0] <= d[1] ? d : [d[1], d[0]]
    if (b - a < minSpan) {
      const c = (a + b) / 2
      a = c - minSpan / 2
      b = c + minSpan / 2
    }
    if (b - a >= fullSpan) return null
    if (a < full[0]) [a, b] = [full[0], full[0] + (b - a)]
    if (b > full[1]) [a, b] = [full[1] - (b - a), full[1]]
    return [a, b]
  }

  const view = clampDomain(controlled ? domainProp ?? null : ownDomain)
  const [x0, x1] = view ?? full ?? [0, 1]
  const zoomed = view !== null

  // The y range of what is visible: points inside the window plus the values at its edges.
  const [lo, hi] = useMemo<[number, number]>(() => {
    let a = Infinity
    let b = -Infinity
    const take = (v: number | undefined) => {
      if (v == null || !Number.isFinite(v)) return
      if (v < a) a = v
      if (v > b) b = v
    }
    for (const s of shown) {
      const ts = timeOf(s)
      const i0 = lowerBound(ts, x0)
      const i1 = lowerBound(ts, x1 + 1e-12)
      for (let i = i0; i < i1 && i < s.points.length; i++) take(s.points[i])
      take(valueAt(ts, s.points, x0))
      take(valueAt(ts, s.points, x1))
    }
    if (!Number.isFinite(a) || !Number.isFinite(b)) return [0, 1]
    if (a === b) return [a - 1, b + 1]
    // Concentrations are physical: never below zero. If the range spans zero, pin the
    // floor at 0 so the graph doesn't dip into a meaningless negative band.
    const floorAtZero = b >= 0 && a < 0
    if (floorAtZero) a = 0
    const span = b - a
    return [a - (floorAtZero ? 0 : span * 0.05), b + span * 0.05]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, x0, x1, time])

  const x = (t: number) => PAD_L + ((t - x0) / Math.max(x1 - x0, 1e-12)) * plotW
  const y = (v: number) => PAD_T + (1 - (v - lo) / (hi - lo)) * plotH
  const tAt = (vx: number) => x0 + ((vx - PAD_L) / plotW) * (x1 - x0)

  // Polylines for the visible window only (plus one point either side, so a line leaves the
  // plot instead of stopping short); the clip path trims the overhang.
  const paths = useMemo(
    () =>
      shown.map((s) => {
        const ts = timeOf(s)
        const i0 = Math.max(0, lowerBound(ts, x0) - 1)
        const i1 = Math.min(Math.min(ts.length, s.points.length), lowerBound(ts, x1) + 1)
        const pts: string[] = []
        for (let i = i0; i < i1; i++) {
          const v = s.points[i]
          if (Number.isFinite(v)) pts.push(`${x(ts[i]).toFixed(1)},${y(v).toFixed(1)}`)
        }
        return { s, d: pts.join(' ') }
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [shown, x0, x1, lo, hi, time],
  )

  // ⌘/Ctrl + wheel (and trackpad pinch, which arrives as ctrl + wheel) zooms around the
  // pointer. It needs a non-passive listener to stop the page from zooming or scrolling;
  // a plain wheel still scrolls the window the chart sits in.
  const zoomAround = useRef<(vx: number, factor: number) => void>(() => {})
  zoomAround.current = (vx: number, factor: number) => {
    const t = Math.min(x1, Math.max(x0, tAt(vx)))
    setDomain(clampDomain([t - (t - x0) * factor, t + (x1 - t) * factor]))
  }
  const hasData = series.length > 0
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const r = el.getBoundingClientRect()
      zoomAround.current(((e.clientX - r.left) * W) / r.width, Math.exp(e.deltaY * 0.002))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [hasData])

  if (series.length === 0 || !full) return null

  const toVx = (clientX: number) => {
    const r = svgRef.current!.getBoundingClientRect()
    return Math.min(W - PAD_R, Math.max(PAD_L, ((clientX - r.left) * W) / r.width))
  }

  const yt = niceTicks(lo, hi, 4)
  const xt = niceTicks(x0, x1, 6)
  const xDec = decimalsFor(xt.step)
  const yDec = decimalsFor(yt.step)

  const hoverT = hoverX != null && !drag ? tAt(hoverX) : null
  const readout = (t: number) =>
    shown.map((s) => ({ s, v: valueAt(timeOf(s), s.points, t) })).filter((r) => r.v !== undefined)
  const hoverRows = hoverT != null ? readout(hoverT) : []
  const markerIn = markerT != null && markerT >= x0 && markerT <= x1
  const markerRows = markerT != null ? readout(markerT) : []

  const zoomBy = (factor: number) => {
    const c = markerIn ? markerT! : (x0 + x1) / 2
    setDomain(clampDomain([c - (c - x0) * factor, c + (x1 - c) * factor]))
  }

  return (
    <div className="lc">
      <div className="lc-bar">
        {legend && (
          <div className="lc-legend">
            {series.map((s) => {
              const off = hidden.has(s.label)
              return (
                <button
                  key={s.label}
                  type="button"
                  className={`lc-legend-item${off ? ' off' : ''}`}
                  onClick={() =>
                    setHidden((h) => {
                      const next = new Set(h)
                      if (off) next.delete(s.label)
                      else next.add(s.label)
                      return next
                    })
                  }
                  title={off ? 'Show this series' : 'Hide this series'}
                >
                  <i style={{ background: s.color }} />
                  {s.label}
                </button>
              )
            })}
          </div>
        )}
        <div className="lc-zoom" role="group" aria-label="Zoom">
          <span className="lc-range" title="Visible time window">
            {x0.toFixed(xDec + 1)}–{x1.toFixed(xDec + 1)} d
          </span>
          <button type="button" onClick={() => zoomBy(2)} disabled={!zoomed} title="Zoom out" aria-label="Zoom out">−</button>
          <button type="button" onClick={() => zoomBy(0.5)} title="Zoom in (around the marked time, else the middle)" aria-label="Zoom in">+</button>
          <button type="button" onClick={() => setDomain(null)} disabled={!zoomed} title="Show the whole run (or double-click the chart)">
            Reset
          </button>
          <span
            className="lc-help"
            title={'Drag across a span to zoom into it\n⌘/Ctrl + scroll or pinch to zoom\nShift + drag to pan\nClick to pick a time\nDouble-click to see everything\nClick a legend entry to hide it'}
          >
            ?
          </span>
        </div>
      </div>

      <div className="lc-plot">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          role="img"
          aria-label="Time series"
          className={drag?.pan ? 'panning' : undefined}
        >
          <defs>
            <clipPath id={clipId}>
              <rect x={PAD_L} y={PAD_T - 2} width={plotW} height={plotH + 4} />
            </clipPath>
          </defs>
          <g stroke="var(--border)" strokeWidth={1}>
            {yt.ticks.map((v) => (
              <line key={v} x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)} />
            ))}
          </g>
          <g fill="var(--muted)" fontSize={11}>
            {yt.ticks.map((v) => (
              <text key={v} x={PAD_L - 6} y={y(v) + 3} textAnchor="end">
                {v.toFixed(yDec)}
              </text>
            ))}
            {xt.ticks.map((v) => (
              <text key={v} x={x(v)} y={H - PAD_B + 16} textAnchor="middle">
                {v.toFixed(xDec)}
              </text>
            ))}
            <text x={W - PAD_R} y={H - 4} textAnchor="end">
              t (d){unit ? ` · ${unit}` : ''}
            </text>
          </g>
          <g clipPath={`url(#${clipId})`}>
            {paths.map(({ s, d }) => (
              <polyline
                key={s.label}
                points={d}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
          </g>

          {markerIn && (
            <g pointerEvents="none">
              <line x1={x(markerT!)} x2={x(markerT!)} y1={PAD_T} y2={PAD_T + plotH} stroke="#0f172a" strokeDasharray="4 3" strokeWidth={1} />
              {markerRows.map(({ s, v }) => (
                <circle key={s.label} cx={x(markerT!)} cy={y(v!)} r={3.5} fill="#fff" stroke={s.color} strokeWidth={2} />
              ))}
            </g>
          )}

          {hoverT != null && (
            <g pointerEvents="none">
              <line x1={hoverX!} x2={hoverX!} y1={PAD_T} y2={PAD_T + plotH} stroke="#94a3b8" strokeWidth={1} />
              {hoverRows.map(({ s, v }) => (
                <circle key={s.label} cx={hoverX!} cy={y(v!)} r={3} fill={s.color} />
              ))}
            </g>
          )}

          {drag && !drag.pan && Math.abs(drag.x1 - drag.x0) > DRAG_PX && (
            <rect
              x={Math.min(drag.x0, drag.x1)}
              y={PAD_T}
              width={Math.abs(drag.x1 - drag.x0)}
              height={plotH}
              fill="var(--accent)"
              fillOpacity={0.12}
              stroke="var(--accent)"
              strokeOpacity={0.5}
              pointerEvents="none"
            />
          )}

          {/* The surface that takes the pointer: hover, click, drag-zoom, shift-drag pan. */}
          <rect
            className="lc-hit"
            x={PAD_L}
            y={PAD_T}
            width={plotW}
            height={plotH}
            fill="transparent"
            onPointerDown={(e) => {
              if (e.button !== 0) return
              e.currentTarget.setPointerCapture(e.pointerId)
              const vx = toVx(e.clientX)
              setDrag({ x0: vx, x1: vx, pan: e.shiftKey, from: [x0, x1] })
            }}
            onPointerMove={(e) => {
              const vx = toVx(e.clientX)
              setHoverX(vx)
              if (!drag) return
              setDrag({ ...drag, x1: vx })
              if (drag.pan) {
                const dt = ((vx - drag.x0) / plotW) * (drag.from[1] - drag.from[0])
                setDomain(clampDomain([drag.from[0] - dt, drag.from[1] - dt]))
              }
            }}
            onPointerUp={(e) => {
              if (!drag) return
              const vx = toVx(e.clientX)
              const moved = Math.abs(vx - drag.x0) > DRAG_PX
              if (!drag.pan && moved) {
                setDomain(clampDomain([tAt(Math.min(drag.x0, vx)), tAt(Math.max(drag.x0, vx))]))
              } else if (!moved && onPickTime) {
                onPickTime(tAt(vx))
              }
              setDrag(null)
            }}
            onPointerLeave={() => {
              if (!drag) setHoverX(null)
            }}
            onDoubleClick={() => setDomain(null)}
          />
        </svg>

        {hoverT != null && hoverRows.length > 0 && (
          <div
            className={`lc-tip${hoverX! > W * 0.62 ? ' left' : ''}`}
            style={{ left: `${(hoverX! / W) * 100}%` }}
          >
            <div className="lc-tip-t">{fmtTime(hoverT)}</div>
            {hoverRows.map(({ s, v }) => (
              <div key={s.label} className="lc-tip-row">
                <i style={{ background: s.color }} />
                <span className="lc-tip-label">{s.label}</span>
                <b>{fmtValue(v)}</b>
              </div>
            ))}
            {unit && <div className="lc-tip-unit">{unit}</div>}
          </div>
        )}
      </div>

      {markerT != null && markerRows.length > 0 && (
        <div className="lc-marker">
          <span className="lc-marker-t">At {fmtTime(markerT)}</span>
          {markerRows.map(({ s, v }) => (
            <span key={s.label} className="lc-marker-item">
              <i style={{ background: s.color }} />
              {s.label} <b>{fmtValue(v)}</b>
            </span>
          ))}
          {unit && <span className="lc-marker-unit">{unit}</span>}
        </div>
      )}
    </div>
  )
}
