// A minimal, dependency-free line chart for simulation results.
// Renders time (x, days) vs a value (y) for one or more series as SVG polylines.

export type LineSeries = {
  label: string
  color: string
  points: number[] // one value per index of `time`
}

type Props = {
  time: number[]
  series: LineSeries[]
  height?: number
  unit?: string
}

export default function LineChart({ time, series, height = 260, unit = '' }: Props) {
  const W = 720
  const H = height
  const padL = 52
  const padR = 14
  const padT = 14
  const padB = 30

  const n = time.length
  if (n === 0 || series.length === 0) return null

  // Flat, finite values across all series (skip non-finite) to get shared axes.
  let lo = Infinity
  let hi = -Infinity
  for (const s of series) {
    for (const v of s.points) {
      if (!Number.isFinite(v)) continue
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
    lo = 0
    hi = 1
  }
  if (lo === hi) {
    lo -= 1
    hi += 1
  }
  // Concentrations are physical: never below zero. If the range spans zero, pin the
  // axis floor at 0 so the graph doesn't dip into a meaningless negative band (then
  // re-pad only upward, so the floor stays at 0).
  const floorAtZero = hi >= 0 && lo < 0
  if (floorAtZero) lo = 0
  const span = hi - lo
  lo -= floorAtZero ? 0 : span * 0.05
  hi += span * 0.05

  const x0 = time[0]
  const x1 = time[n - 1]
  const x = (t: number) => padL + ((t - x0) / Math.max(x1 - x0, 1e-9)) * (W - padL - padR)
  const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB)

  const toPath = (values: number[]) =>
    values
      .map((v, i) => (Number.isFinite(v) ? `${x(time[i]).toFixed(1)},${y(v).toFixed(1)}` : null))
      .filter(Boolean)
      .join(' ')

  // y ticks: five nice-ish values.
  const ticks = 4
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => lo + ((hi - lo) * i) / ticks)
  const xTicks = 6
  const xTickVals = Array.from({ length: xTicks + 1 }, (_, i) => x0 + ((x1 - x0) * i) / xTicks)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Time series">
      <g stroke="var(--border)" strokeWidth={1}>
        {yTicks.map((v, i) => (
          <line key={i} x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} />
        ))}
      </g>
      <g fill="var(--muted)" fontSize={11}>
        {yTicks.map((v, i) => (
          <text key={i} x={padL - 6} y={y(v) + 3} textAnchor="end">
            {Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)}
          </text>
        ))}
        {xTickVals.map((v, i) => (
          <text key={i} x={x(v)} y={H - padB + 16} textAnchor="middle">
            {v.toFixed(1)}
          </text>
        ))}
        <text x={W - padR} y={H - 4} textAnchor="end">
          t (d){unit ? ` · ${unit}` : ''}
        </text>
      </g>
      {series.map((s) => (
        <polyline
          key={s.label}
          points={toPath(s.points)}
          fill="none"
          stroke={s.color}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ))}
    </svg>
  )
}
