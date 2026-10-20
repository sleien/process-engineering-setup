// Editable engineering attributes per unit type, shown in the Properties panel.
// Values are stored as strings in node.data.attributes (free text so users can enter
// numbers, ranges, or notes); they are persisted in the saved project.

export type AttrDef = { key: string; label: string; unit?: string }

const REACTOR: AttrDef[] = [
  { key: 'V', label: 'Volume', unit: 'm³' },
  { key: 'MLSS', label: 'MLSS', unit: 'g/m³' },
  { key: 'DO', label: 'DO', unit: 'mg/L' },
  { key: 'SRT', label: 'SRT', unit: 'd' },
  { key: 'T', label: 'Temperature', unit: '°C' },
]

// The main soluble/particulate load of an influent stream (ASM1 state names → UI labels).
// Empty values are left to the backend, which fills the rest from the BSM1 default.
const INFLUENT_COMPOSITION: AttrDef[] = [
  { key: 'S_S',  label: 'Soluble COD (S_S)',   unit: 'mg COD/L' },
  { key: 'S_NH', label: 'Ammonium (S_NH)',     unit: 'mg N/L' },
  { key: 'S_NO', label: 'Nitrate (S_NO)',      unit: 'mg N/L' },
  { key: 'S_ND', label: 'Biodegradable N (S_ND)', unit: 'mg N/L' },
  { key: 'X_BH', label: 'Heterotrophs (X_BH)', unit: 'mg VSS/L' },
  { key: 'X_S',  label: 'Particulate COD (X_S)', unit: 'mg COD/L' },
  { key: 'S_ALK', label: 'Alkalinity (S_ALK)', unit: 'mg CaCO₃/L' },
  { key: 'X_I',  label: 'Inert solids (X_I)',  unit: 'mg VSS/L' },
  { key: 'X_ND', label: 'Inert N (X_ND)',      unit: 'mg N/L' },
]

const ATTRS: Record<string, AttrDef[]> = {
  influent: [
    { key: 'Q', label: 'Flow rate', unit: 'm³/d' },
    ...INFLUENT_COMPOSITION,
  ],
  screen: [{ key: 'spacing', label: 'Bar spacing', unit: 'mm' }],
  equalization_basin: [
    { key: 'V', label: 'Volume', unit: 'm³' },
    { key: 'HRT', label: 'HRT', unit: 'h' },
  ],
  CSTR: REACTOR,
  empty_CSTR: [
    { key: 'V', label: 'Volume', unit: 'm³' },
    { key: 'MLSS', label: 'MLSS', unit: 'g/m³' },
  ],
  anoxic_CSTR: REACTOR,
  aerated_CSTR: [...REACTOR, { key: 'kLa', label: 'kLa', unit: '1/d' }],
  aerated_CSTR_off: [...REACTOR, { key: 'kLa', label: 'kLa', unit: '1/d' }],
  switch_CSTR: REACTOR,
  sbr: [...REACTOR, { key: 'cycle', label: 'Cycle time', unit: 'h' }],
  trickling_filter: [
    { key: 'V', label: 'Volume', unit: 'm³' },
    { key: 'area', label: 'Specific surface', unit: 'm²/m³' },
    { key: 'recirc', label: 'Recirculation ratio' },
  ],
  MBR: [...REACTOR, { key: 'kLa', label: 'kLa', unit: '1/d' },
                { key: 'flux', label: 'Permeate flux', unit: 'm³/m²·d' }],
  MBBR: [...REACTOR, { key: 'fill', label: 'Carrier fill', unit: '%' },
                 { key: 'kLa', label: 'kLa', unit: '1/d' }],
  MABR: [...REACTOR, { key: 'blanket', label: 'Blanket surface', unit: 'm²' },
                 { key: 'air', label: 'Air flow', unit: 'Nm³/h' },
                 { key: 'kLa', label: 'kLa', unit: '1/d' }],
  clarifier: [
    { key: 'A', label: 'Surface area', unit: 'm²' },
    { key: 'depth', label: 'Side water depth', unit: 'm' },
    { key: 'SOR', label: 'Overflow rate', unit: 'm/h' },
    { key: 'Qr', label: 'Recycle (RAS) flow', unit: 'm³/d' },
    { key: 'Q_was', label: 'Waste sludge (WAS) flow', unit: 'm³/d' },
    { key: 'f_ns', label: 'Non-settleable solids fraction', unit: '-' },
  ],
}

export function getUnitAttrs(unitId: string): AttrDef[] {
  return ATTRS[unitId] ?? [{ key: 'V', label: 'Volume', unit: 'm³' }]
}

// Plausible magnitudes for a mid-size (~2,000 m³/d) activated-sludge plant, shown as
// input placeholders when a field is empty — "around what the value should be".
// Composition keys mirror the engine's BSM1 stabilisation feed (server/simulate.py).
const VALUE_DEFAULTS: Record<string, string> = {
  Q: '2000',
  V: '500', HRT: '12',
  MLSS: '3500', DO: '2', SRT: '10', T: '20',
  kLa: '300', flux: '10', fill: '35', blanket: '1000', air: '3000',
  A: '400', depth: '3', SOR: '1', Qr: '2000', Q_was: '120', f_ns: '0.02',
  spacing: '15',
  area: '100', recirc: '2',
  cycle: '8',
  S_S: '69.5', S_NH: '31.56', S_NO: '0', S_ND: '6.95',
  X_BH: '28.17', X_S: '202.32', S_ALK: '5250', X_I: '51.2', X_ND: '10.59',
  S_O: '0.5', S_I: '30', X_P: '0', S_N2: '0',
}

/** Placeholder for an attribute input: the default magnitude + unit, e.g. "500 m³". */
export function attrPlaceholder(def: AttrDef, unitId: string): string {
  void unitId
  const base = VALUE_DEFAULTS[def.key]
  if (base == null) return ''
  return def.unit ? `${base} ${def.unit}` : base
}

/** Compact "key = value unit" lines for the attributes that have a value set — used for the
 *  on-canvas readout under a unit and for the SVG export. */
export function attrReadout(
  unitId: string,
  attributes?: Record<string, string>,
): { key: string; text: string }[] {
  const vals = attributes ?? {}
  return getUnitAttrs(unitId)
    .filter((d) => (vals[d.key] ?? '').trim() !== '')
    .map((d) => ({ key: d.key, text: `${d.key} = ${vals[d.key]!.trim()}${d.unit ? ` ${d.unit}` : ''}` }))
}
