import type { AppNode, AppEdge } from './types'
import { JUNCTION_SIZE, handlePoint, handlePosition, guessPosition, nodeSize, type XY } from './geometry'
import { pipePath } from './pipePath'
import { getUnit } from '../units/manifest'
import { parseRich } from './textFormat'
import { edgeWidth, maxFlowOf } from './flow'
import { streamColor } from './streams'
import { attrReadout } from './attributes'

const round = (n: number) => Math.round(n * 100) / 100

/** id-safe key for a colour (e.g. "#92400e" → "92400e"). */
const colorId = (color: string) => color.replace('#', '')

const READOUT_FONT = 11
const READOUT_LINE = 13

function escapeXml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * Extract the inner markup of a unit SVG and prefix every id (and url(#…)/href="#…"
 * reference) so that multiple instances embedded in one document never collide — this is
 * what keeps gradient fills (e.g. clarifier.svg) correct when several copies are exported.
 */
function namespaceSvgInner(raw: string, instanceKey: string): string {
  const s = raw.replace(/<\?xml[\s\S]*?\?>/g, '').replace(/<!--[\s\S]*?-->/g, '')
  const openEnd = s.indexOf('>', s.indexOf('<svg'))
  const close = s.lastIndexOf('</svg>')
  let inner = openEnd >= 0 && close >= 0 ? s.slice(openEnd + 1, close) : s

  const prefix = `u${instanceKey}_`
  const ids = new Set<string>()
  const idRe = /\bid="([^"]+)"/g
  let m: RegExpExecArray | null
  while ((m = idRe.exec(inner))) ids.add(m[1])
  for (const id of ids) {
    const esc = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    inner = inner.replace(new RegExp(`id="${esc}"`, 'g'), `id="${prefix}${id}"`)
    inner = inner.replace(new RegExp(`url\\(#${esc}\\)`, 'g'), `url(#${prefix}${id})`)
    inner = inner.replace(new RegExp(`(xlink:href|href)="#${esc}"`, 'g'), `$1="#${prefix}${id}"`)
  }
  return inner
}

/** Path string + the point to anchor a mid-pipe label, for either routing (and the Hand-mode
 *  waypoint). Shares lib/pipePath with the on-screen edge so export matches the canvas. */
function edgeGeometry(e: AppEdge, a: XY, b: XY): { d: string; lx: number; ly: number } {
  const sPos = handlePosition(e.sourceHandle) ?? guessPosition(a, b)
  const tPos = handlePosition(e.targetHandle) ?? guessPosition(b, a)
  const { d, cx, cy } = pipePath({
    a,
    b,
    waypoint: e.data?.waypoint,
    routing: e.data?.routing === 'straight' ? 'straight' : 'step',
    sourcePosition: sPos,
    targetPosition: tPos,
  })
  return { d, lx: cx, ly: cy }
}

/** Every coordinate pair in a path's `d`. All commands we emit (M / L / Q) take x,y pairs, so
 *  pairing the numbers gives the path's points — used to grow the export bounds around pipes. */
function pathCoords(d: string): Array<[number, number]> {
  const nums = d.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? []
  const pts: Array<[number, number]> = []
  for (let i = 0; i + 1 < nums.length; i += 2) pts.push([nums[i], nums[i + 1]])
  return pts
}

/** Serialize the diagram to a self-contained, portable vector SVG string. */
export function serializeToSvg(nodes: AppNode[], edges: AppEdge[], scaleByFlow = true): string {
  const PAD = 40
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    const { w, h } = nodeSize(n)
    minX = Math.min(minX, n.position.x)
    minY = Math.min(minY, n.position.y)
    maxX = Math.max(maxX, n.position.x + w)
    maxY = Math.max(maxY, n.position.y + h)
    // Make room for an on-canvas attribute readout under a unit.
    if (n.type === 'unit' && n.data.showAttrs) {
      const lines = attrReadout(n.data.unitId, n.data.attributes)
      if (lines.length) {
        const wEst = Math.max(...lines.map((l) => l.text.length)) * (READOUT_FONT * 0.58)
        const cx = n.position.x + w / 2
        minX = Math.min(minX, cx - wEst / 2)
        maxX = Math.max(maxX, cx + wEst / 2)
        maxY = Math.max(maxY, n.position.y + h + 6 + lines.length * READOUT_LINE)
      }
    }
  }
  // Pre-compute each pipe's path once (reused for drawing below) and grow the bounds to include
  // it, so a pipe routed beyond the units — e.g. a recycle pulled down with the depth handle —
  // is never clipped on SVG/PNG export.
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const maxFlow = maxFlowOf(edges)
  const edgePaths: Array<{ e: AppEdge; d: string; lx: number; ly: number }> = []
  for (const e of edges) {
    const s = byId.get(e.source)
    const t = byId.get(e.target)
    if (!s || !t) continue
    const geom = edgeGeometry(e, handlePoint(s, e.sourceHandle), handlePoint(t, e.targetHandle))
    edgePaths.push({ e, ...geom })
    for (const [x, y] of pathCoords(geom.d)) {
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }

  if (!isFinite(minX)) {
    minX = 0
    minY = 0
    maxX = 200
    maxY = 120
  }
  minX -= PAD
  minY -= PAD
  maxX += PAD
  maxY += PAD
  const W = Math.round(maxX - minX)
  const H = Math.round(maxY - minY)

  const out: string[] = []
  out.push(
    `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${W}" height="${H}" viewBox="${minX} ${minY} ${W} ${H}">`,
  )

  // One arrowhead marker per stream colour in use (matches the on-screen React Flow arrowhead;
  // scales with stroke width when "scale by flow" is on, otherwise fixed-size).
  const usedColors = new Set<string>([streamColor()])
  for (const e of edges) usedColors.add(streamColor(e.data?.streamType))
  const mUnits = scaleByFlow ? 'strokeWidth' : 'userSpaceOnUse'
  const mSize = scaleByFlow ? 12.5 : 14
  const markers = [...usedColors]
    .map(
      (c) =>
        `<marker id="arrow-${colorId(c)}" viewBox="-10 -10 20 20" refX="0" refY="0" markerWidth="${mSize}" markerHeight="${mSize}" markerUnits="${mUnits}" orient="auto-start-reverse"><polyline points="-5,-4 0,0 -5,4 -5,-4" fill="${c}" stroke="${c}" stroke-linecap="round" stroke-linejoin="round"/></marker>`,
    )
    .join('')
  out.push(`<defs>${markers}</defs>`)
  out.push(`<rect x="${minX}" y="${minY}" width="${W}" height="${H}" fill="#ffffff"/>`)

  // edges below nodes (line thickness + arrowhead scale with flow when enabled)
  const flowLabels: string[] = []
  for (const { e, d, lx, ly } of edgePaths) {
    const color = streamColor(e.data?.streamType)
    const sw = round(edgeWidth(e.data?.flow, maxFlow, scaleByFlow))
    out.push(
      `<path d="${d}" fill="none" stroke="${color}" stroke-width="${sw}" marker-end="url(#arrow-${colorId(color)})"/>`,
    )
    const flow = e.data?.flow
    if (e.data?.showFlow && typeof flow === 'number' && isFinite(flow)) {
      flowLabels.push(
        `<text x="${round(lx)}" y="${round(ly)}" text-anchor="middle" dominant-baseline="central" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="${color}" paint-order="stroke" stroke="#ffffff" stroke-width="3" stroke-linejoin="round">${escapeXml(`Q = ${flow} m³/d`)}</text>`,
      )
    }
  }

  // nodes
  nodes.forEach((n, i) => {
    if (n.type === 'unit') {
      const unit = getUnit(n.data.unitId)
      if (!unit) return
      const inner = namespaceSvgInner(unit.raw, String(i))
      out.push(
        `<svg x="${n.position.x}" y="${n.position.y}" width="${n.data.width}" height="${n.data.height}" viewBox="${unit.viewBox}" preserveAspectRatio="xMidYMid meet" overflow="visible">${inner}</svg>`,
      )
      if (n.data.showAttrs) {
        const lines = attrReadout(n.data.unitId, n.data.attributes)
        const cx = n.position.x + n.data.width / 2
        lines.forEach((line, idx) => {
          const y = n.position.y + n.data.height + READOUT_FONT + idx * READOUT_LINE
          out.push(
            `<text x="${round(cx)}" y="${round(y)}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="${READOUT_FONT}" fill="#0f172a">${escapeXml(line.text)}</text>`,
          )
        })
      }
    } else if (n.type === 'junction') {
      const cx = n.position.x + JUNCTION_SIZE / 2
      const cy = n.position.y + JUNCTION_SIZE / 2
      out.push(`<circle cx="${cx}" cy="${cy}" r="${JUNCTION_SIZE / 2}" fill="#111111"/>`)
    } else if (n.type === 'text') {
      const fs = n.data.fontSize ?? 14
      const x = n.position.x
      const lineHeight = fs * 1.3
      // One <text> per line (keeps sub/sup dy from accumulating across line breaks).
      ;(n.data.text || '').split('\n').forEach((line, idx) => {
        const baseY = n.position.y + fs * 0.9 + idx * lineHeight
        let curDy = 0
        const tspans = parseRich(line)
          .map((seg) => {
            const target = seg.script === 'sup' ? -0.35 * fs : seg.script === 'sub' ? 0.22 * fs : 0
            const dy = round(target - curDy)
            curDy = target
            const size = seg.script ? round(fs * 0.72) : fs
            return `<tspan dy="${dy}" font-size="${size}">${escapeXml(seg.text)}</tspan>`
          })
          .join('')
        out.push(
          `<text x="${x}" y="${round(baseY)}" font-family="Arial, Helvetica, sans-serif" font-size="${fs}" fill="#111111">${tspans}</text>`,
        )
      })
    }
  })

  // flow labels on top of everything so they stay readable
  out.push(...flowLabels)

  out.push('</svg>')
  return out.join('\n')
}

/** Rasterize an SVG string to a PNG Blob (white background, `scale`× resolution). */
export async function svgToPng(svg: string, scale = 2): Promise<Blob> {
  const w = parseFloat(svg.match(/width="([\d.]+)"/)?.[1] ?? '1000')
  const h = parseFloat(svg.match(/height="([\d.]+)"/)?.[1] ?? '1000')
  const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const img = new Image()
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve()
      img.onerror = () => reject(new Error('Failed to render SVG'))
      img.src = url
    })
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.ceil(w * scale))
    canvas.height = Math.max(1, Math.ceil(h * scale))
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.setTransform(scale, 0, 0, scale, 0, 0)
    ctx.drawImage(img, 0, 0)
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('toBlob failed'))), 'image/png'),
    )
  } finally {
    URL.revokeObjectURL(url)
  }
}
