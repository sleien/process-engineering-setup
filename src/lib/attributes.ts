// Editable engineering attributes per unit type, shown in the Properties panel.
// Values are stored as strings in node.data.attributes (free text so users can enter
// numbers, ranges, or notes); they are persisted in the saved project.

/** `group` sorts a field in the Properties panel: no group = read by the simulation,
 *  `cycle` = an SBR's phase clock, `composition` = an influent's ASM1 load, `ph` = what
 *  the pH estimate of a tank assumes, `design` =
 *  carried on the drawing but not read by the simulation (e.g. a clarifier's depth). */
export type AttrGroup = 'cycle' | 'composition' | 'ph' | 'design'
export type AttrDef = { key: string; label: string; unit?: string; group?: AttrGroup }

// What the simulation reads from every tank: its volume and the MLSS it starts from.
// ASM1 has no pH; the simulation estimates it from the alkalinity and the dissolved CO2 a
// tank states, and can start a tank at a given pH (it sets the alkalinity that pH means).
const PH_ESTIMATE: AttrDef[] = [
  { key: 'pH0', label: 'Initial pH', group: 'ph' },
  { key: 'CO2', label: 'Dissolved CO₂', unit: 'mmol/L', group: 'ph' },
]
const TANK: AttrDef[] = [
  { key: 'V', label: 'Volume', unit: 'm³' },
  { key: 'MLSS', label: 'MLSS (initial)', unit: 'g/m³' },
  ...PH_ESTIMATE,
]
// Carried on the drawing only: the simulation runs at 20 °C and sets aeration by kLa.
const TANK_DESIGN: AttrDef[] = [
  { key: 'DO', label: 'DO setpoint', unit: 'mg/L', group: 'design' },
  { key: 'T', label: 'Temperature', unit: '°C', group: 'design' },
]
// A plain tank's sludge age is set by the clarifier loop it sits in, not by the tank.
const REACTOR: AttrDef[] = [
  ...TANK,
  ...TANK_DESIGN,
  { key: 'SRT', label: 'SRT', unit: 'd', group: 'design' },
]
// Units that keep their own solids run at their own sludge age.
const SELF_RETAINING: AttrDef[] = [
  ...TANK,
  { key: 'SRT', label: 'SRT', unit: 'd' },
]
const KLA: AttrDef = { key: 'kLa', label: 'kLa', unit: '1/d' }
const F_NS: AttrDef = { key: 'f_ns', label: 'Non-settleable fraction', unit: '-' }

// The main soluble/particulate load of an influent stream (ASM1 state names → UI labels).
// Empty values are left to the backend, which fills the rest from the BSM1 default.
const INFLUENT_COMPOSITION: AttrDef[] = [
  { key: 'S_S',  label: 'Soluble COD (S_S)',   unit: 'mg COD/L' },
  { key: 'S_NH', label: 'Ammonium (S_NH)',     unit: 'mg N/L' },
  { key: 'S_NO', label: 'Nitrate (S_NO)',      unit: 'mg N/L' },
  { key: 'S_ND', label: 'Biodegradable N (S_ND)', unit: 'mg N/L' },
  { key: 'X_BH', label: 'Heterotrophs (X_BH)', unit: 'mg COD/L' },
  { key: 'X_S',  label: 'Particulate COD (X_S)', unit: 'mg COD/L' },
  { key: 'S_ALK', label: 'Alkalinity (S_ALK)', unit: 'mmol/L' },
  { key: 'X_I',  label: 'Inert particulate COD (X_I)', unit: 'mg COD/L' },
  { key: 'X_ND', label: 'Particulate organic N (X_ND)', unit: 'mg N/L' },
].map((d) => ({ ...d, group: 'composition' as const }))

const ATTRS: Record<string, AttrDef[]> = {
  influent: [
    { key: 'Q', label: 'Flow rate', unit: 'm³/d' },
    ...INFLUENT_COMPOSITION,
  ],
  screen: [{ key: 'spacing', label: 'Bar spacing', unit: 'mm', group: 'design' }],
  // Drawn, but the water passes straight through it in the simulation.
  equalization_basin: [
    { key: 'V', label: 'Volume', unit: 'm³', group: 'design' },
    { key: 'HRT', label: 'HRT', unit: 'h', group: 'design' },
  ],
  CSTR: REACTOR,
  empty_CSTR: TANK,
  anoxic_CSTR: REACTOR,
  aerated_CSTR: [...TANK, KLA, ...REACTOR.slice(TANK.length)],
  aerated_CSTR_off: [...TANK, KLA, ...REACTOR.slice(TANK.length)],
  switch_CSTR: [...TANK, KLA, ...REACTOR.slice(TANK.length)],
  // An SBR is simulated as a continuously fed tank whose aeration follows the cycle
  // clock; `offset` staggers one SBR against its neighbours so a parallel bank accepts
  // flow without pulsing in unison. The phases default to 1.5/3.5/0.75/1.65 h.
  sbr: [...SELF_RETAINING, { key: 'kLa', label: 'kLa (react phase)', unit: '1/d' }, F_NS,
        { key: 'cycle', label: 'Cycle time', unit: 'h', group: 'cycle' },
        { key: 'fill', label: 'Fill', unit: 'h', group: 'cycle' },
        { key: 'react', label: 'React', unit: 'h', group: 'cycle' },
        { key: 'settle', label: 'Settle', unit: 'h', group: 'cycle' },
        { key: 'decant', label: 'Decant', unit: 'h', group: 'cycle' },
        { key: 'offset', label: 'Stagger', unit: 'h', group: 'cycle' },
        ...TANK_DESIGN],
  // The simulation models a trickling filter as a mixed tank that keeps its solids: the
  // model reads `V`, `MLSS` (the biomass it holds), `SRT` and `recirc` (the internal
  // return as a multiple of throughput). `kLa` is the natural-draft ventilation — left
  // empty it defaults to 240 1/d, not to zero. `area` is a design value carried on the
  // drawing.
  trickling_filter: [
    { key: 'V', label: 'Volume', unit: 'm³' },
    { key: 'MLSS', label: 'Biofilm solids', unit: 'g/m³' },
    { key: 'SRT', label: 'Biofilm age (SRT)', unit: 'd' },
    { key: 'recirc', label: 'Recirculation ratio' },
    { key: 'kLa', label: 'kLa (natural draft)', unit: '1/d' },
    F_NS,
    ...PH_ESTIMATE,
    { key: 'area', label: 'Specific surface', unit: 'm²/m³', group: 'design' },
  ],
  MBR: [...SELF_RETAINING, KLA, F_NS,
        { key: 'flux', label: 'Permeate flux', unit: 'm³/m²·d', group: 'design' },
        ...TANK_DESIGN],
  MBBR: [...SELF_RETAINING, KLA,
         { key: 'fill', label: 'Carrier fill', unit: '%', group: 'design' },
         ...TANK_DESIGN],
  MABR: [...SELF_RETAINING, KLA,
         { key: 'blanket', label: 'Membrane area', unit: 'm²', group: 'design' },
         { key: 'air', label: 'Air flow', unit: 'Nm³/h', group: 'design' },
         ...TANK_DESIGN],
  // A settler with no return: `removal` is the share of incoming suspended solids it
  // takes out, `Qu` the sludge drawn off to waste (default 1 % of the flow through it).
  primary_clarifier: [
    { key: 'removal', label: 'TSS removal', unit: '-' },
    { key: 'Qu', label: 'Sludge underflow', unit: 'm³/d' },
    { key: 'A', label: 'Surface area', unit: 'm²', group: 'design' },
  ],
  // The simulator sizes the waste for the sludge age: give `SRT` and it computes the WAS
  // that holds it. A `Q_was` is used as given only when no SRT is set, and the run
  // reports the sludge age it produces — which is how a too-high waste shows up.
  clarifier: [
    { key: 'Qr', label: 'Recycle (RAS) flow', unit: 'm³/d' },
    { key: 'SRT', label: 'Sludge age (SRT)', unit: 'd' },
    { key: 'Q_was', label: 'WAS flow, if no SRT', unit: 'm³/d' },
    F_NS,
    { key: 'A', label: 'Surface area', unit: 'm²', group: 'design' },
    { key: 'depth', label: 'Side water depth', unit: 'm', group: 'design' },
    { key: 'SOR', label: 'Overflow rate', unit: 'm/h', group: 'design' },
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
  cycle: '7.4', react: '3.5', settle: '0.75', decant: '1.65', offset: '0',
  S_S: '69.5', S_NH: '31.56', S_NO: '0', S_ND: '6.95',
  X_BH: '28.17', X_S: '202.32', S_ALK: '7', X_I: '51.2', X_ND: '10.59',
  pH0: '7.08', CO2: '1',
  S_O: '0.5', S_I: '30', X_P: '0', S_N2: '0',
}

// A few keys mean different things on different units — `fill` is a carrier fill
// percentage on an MBBR and the fill *phase* of an SBR cycle. These win over the table
// above for the unit they're listed under.
const UNIT_VALUE_DEFAULTS: Record<string, Record<string, string>> = {
  sbr: { fill: '1.5', kLa: '420', MLSS: '4200', SRT: '15', f_ns: '0.002' },
  trickling_filter: { MLSS: '2500', SRT: '25', f_ns: '0.01', kLa: '240' },
  clarifier: { SRT: '15' },
  primary_clarifier: { removal: '0.5', Qu: '20' },
}

/** Placeholder for an attribute input: the default magnitude + unit, e.g. "500 m³". */
export function attrPlaceholder(def: AttrDef, unitId: string): string {
  const base = UNIT_VALUE_DEFAULTS[unitId]?.[def.key] ?? VALUE_DEFAULTS[def.key]
  if (base == null) return ''
  return def.unit ? `${base} ${def.unit}` : base
}

// The readout under a unit on the canvas stays short enough not to run into its
// neighbours: simulation inputs first, at most this many lines, the rest counted.
const READOUT_MAX_LINES = 4
const READOUT_MAX_CHARS = 18
const GROUP_RANK: Record<string, number> = { '': 0, cycle: 1, ph: 2, design: 3, composition: 4 }

/** A value short enough for one readout line: a sampled profile becomes its length, a long
 *  formula is cut with an ellipsis. */
function compactValue(raw: string): { text: string; profile: boolean } {
  const v = raw.trim()
  if (v.startsWith('[')) {
    try {
      const arr = JSON.parse(v)
      if (Array.isArray(arr)) return { text: `profile (${arr.length} pts)`, profile: true }
    } catch {
      /* not JSON — fall through to plain text */
    }
  }
  return {
    text: v.length > READOUT_MAX_CHARS ? `${v.slice(0, READOUT_MAX_CHARS - 1)}…` : v,
    profile: false,
  }
}

/** Compact "key = value unit" lines for the attributes that have a value set — used for the
 *  on-canvas readout under a unit and for the SVG export. */
export function attrReadout(
  unitId: string,
  attributes?: Record<string, string>,
): { key: string; text: string }[] {
  const vals = attributes ?? {}
  const set = getUnitAttrs(unitId)
    .filter((d) => (vals[d.key] ?? '').trim() !== '')
    .sort((a, b) => GROUP_RANK[a.group ?? ''] - GROUP_RANK[b.group ?? ''])
  const room = set.length > READOUT_MAX_LINES ? READOUT_MAX_LINES - 1 : READOUT_MAX_LINES
  const lines = set.slice(0, room).map((d) => {
    const v = compactValue(vals[d.key]!)
    const unit = d.unit && d.unit !== '-' && !v.profile ? ` ${d.unit}` : ''
    return { key: d.key, text: `${d.key} = ${v.text}${unit}` }
  })
  const hidden = set.length - room
  if (hidden > 0) lines.push({ key: '__more', text: `+${hidden} more` })
  return lines
}
