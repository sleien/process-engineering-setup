// Registry of treatment-unit SVGs.
//
// Each unit is imported twice via Vite:
//   - the default import gives a hashed URL (used for crisp on-screen <img> rendering,
//     which isolates each instance's internal gradient/element ids), and
//   - the `?raw` import gives the SVG source text (inlined, with ids namespaced, for
//     true vector export in lib/exportSvg.ts).
//
// `width`/`height` are the on-canvas pixel size. The source SVGs were all authored at a
// common 96-dpi scale (mm/viewBox ratio is identical across files), so using each file's
// viewBox dimensions directly preserves the intended *relative* sizes between units.

import screenUrl from '../assets/units/screen.svg'
import screenRaw from '../assets/units/screen.svg?raw'
import equalizationUrl from '../assets/units/equalization_basin.svg'
import equalizationRaw from '../assets/units/equalization_basin.svg?raw'
import cstrUrl from '../assets/units/CSTR.svg'
import cstrRaw from '../assets/units/CSTR.svg?raw'
import emptyCstrUrl from '../assets/units/empty_CSTR.svg'
import emptyCstrRaw from '../assets/units/empty_CSTR.svg?raw'
import anoxicUrl from '../assets/units/anoxic_CSTR.svg'
import anoxicRaw from '../assets/units/anoxic_CSTR.svg?raw'
import aeratedUrl from '../assets/units/aerated_CSTR.svg'
import aeratedRaw from '../assets/units/aerated_CSTR.svg?raw'
import aeratedOffUrl from '../assets/units/aerated_CSTR_off.svg'
import aeratedOffRaw from '../assets/units/aerated_CSTR_off.svg?raw'
import switchUrl from '../assets/units/switch_CSTR.svg'
import switchRaw from '../assets/units/switch_CSTR.svg?raw'
import sbrUrl from '../assets/units/sbr.svg'
import sbrRaw from '../assets/units/sbr.svg?raw'
import tricklingUrl from '../assets/units/trickling_filter.svg'
import tricklingRaw from '../assets/units/trickling_filter.svg?raw'
import clarifierUrl from '../assets/units/clarifier.svg'
import clarifierRaw from '../assets/units/clarifier.svg?raw'
import influentUrl from '../assets/units/influent.svg'
import influentRaw from '../assets/units/influent.svg?raw'
import effluentUrl from '../assets/units/effluent.svg'
import effluentRaw from '../assets/units/effluent.svg?raw'
import sludgeUrl from '../assets/units/sludge.svg'
import sludgeRaw from '../assets/units/sludge.svg?raw'
import mbrUrl from '../assets/units/MBR.svg'
import mbrRaw from '../assets/units/MBR.svg?raw'
import mbbrUrl from '../assets/units/MBBR.svg'
import mbbrRaw from '../assets/units/MBBR.svg?raw'
import mabrUrl from '../assets/units/MABR.svg'
import mabrRaw from '../assets/units/MABR.svg?raw'

/**
 * Where the connection ports lock on, as fractions of the node box
 * (0 = top/left edge, 1 = bottom/right edge). Lets the side ports sit on the
 * tank centre for units whose artwork is taller than the tank itself (e.g. the
 * stirrer above an anoxic reactor), so arrows attach to the tank at a consistent
 * height instead of the bounding-box middle. Both default to 0.5 (centre).
 */
export type PortAnchors = {
  /** Vertical position of the left & right ports. */
  side?: number
  /** Horizontal position of the top & bottom ports. */
  ends?: number
}

export type UnitDef = {
  id: string
  label: string
  url: string
  raw: string
  /** Original SVG viewBox, used for the nested <svg> in vector export. */
  viewBox: string
  width: number
  height: number
  /** Optional port-lock anchors; omit for centred ports. */
  ports?: PortAnchors
}

export const UNITS: UnitDef[] = [
  { id: 'influent', label: 'Influent (feed)', url: influentUrl, raw: influentRaw, viewBox: '0 0 75 75', width: 75, height: 75 },
  { id: 'screen', label: 'Screen', url: screenUrl, raw: screenRaw, viewBox: '0 0 52.950982 44.72748', width: 53, height: 45 },
  { id: 'equalization_basin', label: 'Equalization basin', url: equalizationUrl, raw: equalizationRaw, viewBox: '0 0 74.701605 73.665587', width: 75, height: 74 },
  { id: 'CSTR', label: 'CSTR (stirred)', url: cstrUrl, raw: cstrRaw, viewBox: '0 0 160.00807 98.074361', width: 160, height: 98, ports: { side: 0.516 } },
  { id: 'empty_CSTR', label: 'Tank (empty)', url: emptyCstrUrl, raw: emptyCstrRaw, viewBox: '0 0 160.00809 94.988083', width: 160, height: 95 },
  { id: 'anoxic_CSTR', label: 'Anoxic reactor', url: anoxicUrl, raw: anoxicRaw, viewBox: '0 0 160.00807 151.5178', width: 160, height: 152, ports: { side: 0.687 } },
  { id: 'aerated_CSTR', label: 'Aerated reactor', url: aeratedUrl, raw: aeratedRaw, viewBox: '0 0 160.00634 98.066633', width: 160, height: 98, ports: { side: 0.516 } },
  { id: 'aerated_CSTR_off', label: 'Aerated reactor (off)', url: aeratedOffUrl, raw: aeratedOffRaw, viewBox: '0 0 160.00807 98.074361', width: 160, height: 98, ports: { side: 0.516 } },
  { id: 'switch_CSTR', label: 'Switchable reactor', url: switchUrl, raw: switchRaw, viewBox: '0 0 160.00809 151.51778', width: 160, height: 152, ports: { side: 0.687 } },
  { id: 'sbr', label: 'SBR', url: sbrUrl, raw: sbrRaw, viewBox: '0 0 90.089169 57.001833', width: 90, height: 57 },
  { id: 'trickling_filter', label: 'Trickling filter', url: tricklingUrl, raw: tricklingRaw, viewBox: '0 0 84.46463 50.183843', width: 84, height: 50 },
  { id: 'MBR', label: 'Membrane reactor (MBR)', url: mbrUrl, raw: mbrRaw, viewBox: '0 0 253 155', width: 253, height: 155, ports: { side: 0.5 } },
  { id: 'MBBR', label: 'Moving bed (MBBR)', url: mbbrUrl, raw: mbbrRaw, viewBox: '0 0 253 155', width: 253, height: 155, ports: { side: 0.5 } },
  { id: 'MABR', label: 'Moving blanket (MABR)', url: mabrUrl, raw: mabrRaw, viewBox: '0 0 253 155', width: 253, height: 155, ports: { side: 0.5 } },
  { id: 'clarifier', label: 'Clarifier', url: clarifierUrl, raw: clarifierRaw, viewBox: '0 0 74.701605 67.425274', width: 75, height: 67 },
  { id: 'effluent', label: 'Effluent (outfall)', url: effluentUrl, raw: effluentRaw, viewBox: '0 0 75 67', width: 75, height: 67 },
  { id: 'sludge', label: 'Sludge (WAS)', url: sludgeUrl, raw: sludgeRaw, viewBox: '0 0 75 67', width: 75, height: 67 },
]

const UNIT_BY_ID = new Map(UNITS.map((u) => [u.id, u]))

export function getUnit(id: string): UnitDef | undefined {
  return UNIT_BY_ID.get(id)
}

/** Resolved port anchors for a unit (both fractions defaulted to 0.5 = centre). */
export function unitPorts(id: string): Required<PortAnchors> {
  const p = UNIT_BY_ID.get(id)?.ports
  return { side: p?.side ?? 0.5, ends: p?.ends ?? 0.5 }
}
