// Controller model for aerated units — mirrors server/controllers.py.
//
// A controller is a structured rule list, re-evaluated every `period_days` of
// simulation time. It runs inside the solver (as a discrete callback) on the
// backend, so the frontend only stores and edits the rules.
//
// Rule precedence is first-match-wins; if no rule matches, the unit's
// `kLa` field (a number, a staged list, or a diurnal sine expression) is used.

export const CTRL_OPS = ['<', '<=', '>', '>='] as const
export type CtrlOp = (typeof CTRL_OPS)[number]

export type CtrlWhenState =
  | 'S_I' | 'S_S' | 'X_I' | 'X_S'
  | 'X_BH' | 'X_BA' | 'X_P'
  | 'S_O' | 'S_NO' | 'S_NH' | 'S_ND'
  | 'X_ND' | 'S_ALK' | 'S_N2'

export type CtrlWhen = CtrlWhenState | 't'

export interface CtrlRule {
  when: CtrlWhen
  op: CtrlOp
  value: number
  set: number
}

export interface Controller {
  /** Days of simulated time between re-evaluations (capped [1/96, 1]). */
  period_days: number
  rules: CtrlRule[]
}

export const CTRL_STATE_OPTIONS: { value: CtrlWhenState; label: string }[] = [
  { value: 'S_O',   label: 'Dissolved O₂ (S_O)' },
  { value: 'S_NH',  label: 'Ammonium (S_NH)' },
  { value: 'S_NO',  label: 'Nitrate (S_NO)' },
  { value: 'S_S',   label: 'Soluble COD (S_S)' },
  { value: 'S_ND',  label: 'Biodegradable N (S_ND)' },
  { value: 'X_BH',  label: 'Heterotrophs (X_BH)' },
  { value: 'X_BA',  label: 'Autotrophs (X_BA)' },
  { value: 'X_S',   label: 'Particulate COD (X_S)' },
  { value: 'X_P',   label: 'Particulate P (X_P)' },
  { value: 'S_I',   label: 'Inert soluble (S_I)' },
  { value: 'X_I',   label: 'Inert solids (X_I)' },
  { value: 'X_ND',  label: 'Particulate N (X_ND)' },
  { value: 'S_ALK', label: 'Alkalinity (S_ALK)' },
  { value: 'S_N2',  label: 'Dinitrogen (S_N2)' },
]

export function stateLabel(when: CtrlWhen): string {
  if (when === 't') return 'time [d]'
  return CTRL_STATE_OPTIONS.find((s) => s.value === when)?.label ?? when
}

export function ruleText(r: CtrlRule): string {
  const lhs = r.when === 't' ? 'time [d]' : r.when
  return `if ${lhs} ${r.op} ${trimNum(r.value)} then set kLa = ${trimNum(r.set)}`
}

export function controllerText(c: Controller, base: string): string {
  const head = c.rules.map(ruleText).join('; ')
  return head + `  (period ${trimNum(c.period_days)} d, default ${base})`
}

function trimNum(n: number): string {
  return (Number.isInteger(n) ? n.toFixed(0) : String(n)).trim()
}

export function isFiniteNum(x: unknown): x is number {
  return typeof x === 'number' && Number.isFinite(x)
}

export function isWhenState(x: unknown): x is CtrlWhenState {
  return CTRL_STATE_OPTIONS.some((s) => s.value === x)
}

export function isOp(x: unknown): x is CtrlOp {
  return (CTRL_OPS as readonly string[]).includes(x as string)
}

export function whenOptions(): { value: CtrlWhen; label: string }[] {
  return [{ value: 't', label: 'time [d] (simulation days)' }, ...CTRL_STATE_OPTIONS]
}

export function defaultController(): Controller {
  return {
    period_days: 0.25,
    rules: [{ when: 'S_O', op: '>', value: 2.0, set: 100 }],
  }
}

/**
 * Parse a raw value coming off the node. Returns:
 *   { ok: true, controller } if it validates;
 *   { ok: false, msg }       with a short human-readable error.
 */
export function parseController(raw: unknown):
  { ok: true; controller: Controller } | { ok: false; msg: string } {
  if (raw == null) return { ok: false, msg: 'missing' }
  if (typeof raw !== 'object' || raw === null) {
    return { ok: false, msg: "must be an object with period_days + rules" }
  }
  const c = raw as Record<string, unknown>
  const p = c.period_days
  if (!isFiniteNum(p) || p <= 0) {
    return { ok: false, msg: 'period_days must be a positive number of days' }
  }
  const rulesRaw = c.rules
  if (!Array.isArray(rulesRaw) || rulesRaw.length === 0) {
    return { ok: false, msg: 'rules must be a non-empty list' }
  }
  const rules: CtrlRule[] = []
  for (let i = 0; i < rulesRaw.length; i++) {
    const r = rulesRaw[i] as Record<string, unknown>
    if (typeof r !== 'object' || r === null) return { ok: false, msg: `rule ${i+1} must be an object` }
    const w = r.when
    if (w !== 't' && !isWhenState(w)) return { ok: false, msg: `rule ${i+1}: when must be a state or t` }
    if (!isOp(r.op)) return { ok: false, msg: `rule ${i+1}: op must be <, <=, > or >=` }
    if (!isFiniteNum(r.value)) return { ok: false, msg: `rule ${i+1}: value must be a number` }
    if (!isFiniteNum(r.set) || r.set < 0) return { ok: false, msg: `rule ${i+1}: kLa (set) must be ≥ 0` }
    rules.push({ when: w as CtrlWhen, op: r.op as CtrlOp, value: r.value, set: r.set })
  }
  return { ok: true, controller: { period_days: p, rules } }
}

/** True when a node is an aerated unit (i.e. its kLa is what the controller would steer). */
export function isAeratedUnit(unitId: string): boolean {
  return unitId === 'aerated_CSTR' || unitId === 'aerated_CSTR_off' ||
         unitId === 'MBR' || unitId === 'MBBR' || unitId === 'MABR'
}

/** True when the node has a valid controller (so the UI can show it). */
export function nodeHasController(node: { data: { unitId: string; controller?: unknown } }): boolean {
  if (!isAeratedUnit(node.data.unitId)) return false
  const v = parseController(node.data.controller)
  return v.ok
}
