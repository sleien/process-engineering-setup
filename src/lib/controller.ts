// Plant controllers — mirrors server/controllers.py.
//
// A controller sits on the unit whose setting it changes (its `target`: the kLa of an
// aerated unit, the excess-sludge or return pump of a clarifier or of a unit that keeps its
// own solids, the underflow of a primary clarifier). Its rules measure in any tank of the
// plant — `at` is that tank's node id, absent = the unit the controller sits on — and are
// re-evaluated every `period_days` of simulated time inside the solver. First match wins;
// when none matches, the target keeps its own setting (the kLa field, or the pump flow
// the backend sized).
//
// Stored on the node as `data.controllers` (a list, one per target). The older single
// `data.controller` (a kLa controller on its own tank) is still read.

export const CTRL_OPS = ['<', '<=', '>', '>='] as const
export type CtrlOp = (typeof CTRL_OPS)[number]

export type CtrlWhenState =
  | 'S_I' | 'S_S' | 'X_I' | 'X_S'
  | 'X_BH' | 'X_BA' | 'X_P'
  | 'S_O' | 'S_NO' | 'S_NH' | 'S_ND'
  | 'X_ND' | 'S_ALK' | 'S_N2'

/** What a rule can measure: an ASM1 state, suspended solids, the COD/N ratio, the pH
 *  (estimated from alkalinity), or time. */
export type CtrlWhen = CtrlWhenState | 'MLSS' | 'COD/N' | 'pH' | 't'

export type CtrlTarget = 'kLa' | 'Q_was' | 'Qr' | 'Qu' | 'Q'

export interface CtrlRule {
  /** Node id of the tank measured in; absent = the unit the controller sits on. */
  at?: string
  when: CtrlWhen
  op: CtrlOp
  value: number
  set: number
}

export interface Controller {
  target: CtrlTarget
  /** Days of simulated time between re-evaluations (the backend keeps it in [1/1440, 1]). */
  period_days: number
  rules: CtrlRule[]
  /** When no rule matches: the target's own setting ('base', default) or the last setting
   *  ('hold') — which turns an on-rule and an off-rule into a switch with hysteresis. */
  otherwise?: 'base' | 'hold'
}

export const TARGETS: Record<CtrlTarget, { label: string; unit: string }> = {
  kLa: { label: 'Aeration kLa', unit: '1/d' },
  Q_was: { label: 'Excess sludge (WAS) pump', unit: 'm³/d' },
  Qr: { label: 'Sludge return pump', unit: 'm³/d' },
  Qu: { label: 'Sludge underflow', unit: 'm³/d' },
  Q: { label: 'Influent flow', unit: 'm³/d' },
}

export const MEASURES: { value: CtrlWhen; label: string; unit: string }[] = [
  { value: 'MLSS', label: 'MLSS', unit: 'g/m³' },
  { value: 'pH', label: 'pH (from alkalinity)', unit: '' },
  { value: 'S_O', label: 'Dissolved O₂ (S_O)', unit: 'mg/L' },
  { value: 'S_NH', label: 'Ammonium (S_NH)', unit: 'mg N/L' },
  { value: 'S_NO', label: 'Nitrate (S_NO)', unit: 'mg N/L' },
  { value: 'S_S', label: 'Soluble COD (S_S)', unit: 'mg COD/L' },
  { value: 'COD/N', label: 'COD/N ratio', unit: '-' },
  { value: 'S_ND', label: 'Biodegradable N (S_ND)', unit: 'mg N/L' },
  { value: 'X_BH', label: 'Heterotrophs (X_BH)', unit: 'mg COD/L' },
  { value: 'X_BA', label: 'Autotrophs (X_BA)', unit: 'mg COD/L' },
  { value: 'X_S', label: 'Particulate COD (X_S)', unit: 'mg COD/L' },
  { value: 'X_I', label: 'Inert solids (X_I)', unit: 'mg COD/L' },
  { value: 'X_P', label: 'Particulate products (X_P)', unit: 'mg COD/L' },
  { value: 'X_ND', label: 'Particulate N (X_ND)', unit: 'mg N/L' },
  { value: 'S_I', label: 'Inert soluble (S_I)', unit: 'mg COD/L' },
  { value: 'S_ALK', label: 'Alkalinity (S_ALK)', unit: '' },
  { value: 'S_N2', label: 'Dinitrogen (S_N2)', unit: 'mg N/L' },
  { value: 't', label: 'Time', unit: 'd' },
]

const AERATED = ['aerated_CSTR', 'aerated_CSTR_off', 'switch_CSTR', 'MBR', 'MBBR', 'MABR', 'sbr', 'trickling_filter']
const SELF_RETAINING = ['sbr', 'MBR', 'MBBR', 'MABR', 'trickling_filter']
const TANKS = ['CSTR', 'empty_CSTR', 'anoxic_CSTR', ...AERATED]

/** What a controller on this unit can set, in the order the editor offers them. */
export function targetsFor(unitId: string): CtrlTarget[] {
  const out: CtrlTarget[] = []
  if (AERATED.includes(unitId)) out.push('kLa')
  if (SELF_RETAINING.includes(unitId) || unitId === 'clarifier') out.push('Q_was', 'Qr')
  if (unitId === 'primary_clarifier') out.push('Qu')
  if (unitId === 'influent') out.push('Q')
  return out
}

/** Units that hold mixed liquor a rule can measure in. */
export function isTank(unitId: string): boolean {
  return TANKS.includes(unitId)
}

export function measureUnit(when: CtrlWhen): string {
  return MEASURES.find((m) => m.value === when)?.unit ?? ''
}

/** The controllers on a node, reading the older single kLa `controller` too. */
export function readControllers(data: { controllers?: Controller[]; controller?: unknown }): Controller[] {
  if (Array.isArray(data.controllers)) return data.controllers
  const legacy = data.controller as Omit<Controller, 'target'> | undefined
  if (legacy && Array.isArray(legacy.rules)) return [{ ...legacy, target: 'kLa' }]
  return []
}

/** A starting point for a new controller: something sensible to edit, not a tuned rule. */
export function defaultController(target: CtrlTarget, at?: string): Controller {
  if (target === 'kLa') {
    return { target, period_days: 0.05, rules: [
      { at, when: 'S_O', op: '>', value: 2.5, set: 60 },
      { at, when: 'S_O', op: '<', value: 1.5, set: 400 },
    ] }
  }
  if (target === 'Qu') {
    return { target, period_days: 0.25, rules: [{ when: 't', op: '<', value: 1, set: 20 }] }
  }
  if (target === 'Q') {
    // A feed switched on pH, with hysteresis: on below the lower value, off above the
    // upper, unchanged in between.
    return { target, period_days: 2 / 1440, otherwise: 'hold', rules: [
      { at, when: 'pH', op: '<', value: 6.2, set: 1 },
      { at, when: 'pH', op: '>', value: 6.25, set: 0 },
    ] }
  }
  // A sludge pump: waste (or return) more when the solids climb, less when they fall.
  return { target, period_days: 0.25, rules: [
    { at, when: 'MLSS', op: '>', value: 4000, set: target === 'Q_was' ? 100 : 3000 },
    { at, when: 'MLSS', op: '<', value: 3000, set: target === 'Q_was' ? 20 : 1500 },
  ] }
}
