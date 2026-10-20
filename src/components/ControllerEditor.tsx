import type { Controller, CtrlRule } from '../lib/controller'
import {
  CTRL_OPS,
  defaultController,
  stateLabel,
  whenOptions,
} from '../lib/controller'

type Props = {
  node: { id: string; data: { unitId: string; kLa?: unknown; attributes?: Record<string, string>; controller?: Controller } }
  onPatchNode: (id: string, patch: Record<string, unknown>) => void
}

/** Visual controller editor — one rule per row, first match wins.
 *  Stored on the node as `data.controller` (see src/lib/controller.ts). */
export default function ControllerEditor({ node, onPatchNode }: Props) {
  const ctrl = node.data.controller
  const has = typeof ctrl === 'object' && ctrl && Array.isArray(ctrl.rules) && ctrl.rules.length > 0
  const kLaHint = (node.data.attributes?.kLa ?? '').toString().trim() || 'constant 300'

  const setCtrl = (c: Controller) => onPatchNode(node.id, { controller: c })

  const base = has ? (ctrl as Controller) : defaultController()
  const rules = has ? (ctrl as Controller).rules : base.rules
  const period = has ? (ctrl as Controller).period_days : base.period_days

  const patchRule = (i: number, patch: Partial<CtrlRule>) => {
    if (!has) return
    const next = (ctrl as Controller).rules.slice()
    next[i] = { ...next[i], ...patch }
    setCtrl({ ...(ctrl as Controller), rules: next })
  }
  const addRule = () => setCtrl({ ...(ctrl as Controller || base), rules: [...(ctrl as Controller || base).rules, { when: 'S_O', op: '>', value: 2, set: 100 }] })
  const removeRule = (i: number) => setCtrl({ ...(ctrl as Controller), rules: (ctrl as Controller).rules.filter((_, j) => j !== i) })

  const toggle = (enabled: boolean) => {
    if (enabled) {
      onPatchNode(node.id, { controller: base })
    } else {
      onPatchNode(node.id, { controller: undefined })
    }
  }

  const rows = has ? (ctrl as Controller).rules : []
  const preview = has
    ? (ctrl as Controller).rules.map(ruleTextLocal).join('; ')
    : ''

  return (
    <section className="ctrl-editor">
      <div className="ctrl-head">
        <label className="ctrl-enable">
          <input
            type="checkbox"
            checked={has}
            onChange={(e) => toggle(e.target.checked)}
          />
          <span>Controller</span>
        </label>
        <span className="ctrl-sub" title="How often the rules re-evaluate, in days of simulated time">
          period
        </span>
        <input
          className="ctrl-period"
          type="number"
          min={1 / 96}
          max={1}
          step={0.05}
          disabled={!has}
          value={period.toFixed(2)}
          onChange={(e) => {
            const v = Number(e.target.value)
            if (!Number.isFinite(v) || v <= 0) return
            setCtrl({ ...(ctrl as Controller), period_days: Math.min(1, Math.max(1 / 96, v)) })
          }}
        />
      </div>
      <div className="ctrl-hint">
        First matching rule sets <code>kLa</code>; nothing matching → the unit’s kLa field
        (<code>{kLaHint || 'default'}</code>). Time-based rules use <code>t</code> (days).
      </div>
      {has && (
        <div className="ctrl-rows">
          {rows.map((r, i) => (
            <div className="ctrl-row" key={i}>
              <span className="ctrl-kw">if</span>
              <select
                className="ctrl-when"
                value={r.when}
                onChange={(e) => patchRule(i, { when: e.target.value as CtrlRule['when'] })}
                title={stateLabel(r.when)}
              >
                {whenOptions().map((w) => (
                  <option key={w.value} value={w.value}>
                    {w.value === 't' ? 'time t' : w.value}
                  </option>
                ))}
              </select>
              <select
                className="ctrl-op"
                value={r.op}
                onChange={(e) => patchRule(i, { op: e.target.value as CtrlRule['op'] })}
              >
                {CTRL_OPS.map((op) => (
                  <option key={op} value={op}>{op}</option>
                ))}
              </select>
              <input
                className="ctrl-val"
                type="number"
                value={Number.isFinite(r.value) ? r.value : 0}
                onChange={(e) => {
                  const v = Number(e.target.value)
                  if (Number.isFinite(v)) patchRule(i, { value: v })
                }}
              />
              <span className="ctrl-kw">→</span>
              <span className="ctrl-kw">kLa</span>
              <input
                className="ctrl-set"
                type="number"
                min={0}
                value={Number.isFinite(r.set) ? r.set : 0}
                onChange={(e) => {
                  const v = Number(e.target.value)
                  if (Number.isFinite(v) && v >= 0) patchRule(i, { set: v })
                }}
              />
              <button
                className="ctrl-del"
                onClick={() => removeRule(i)}
                aria-label={`Remove rule ${i + 1}`}
              >
                ✕
              </button>
            </div>
          ))}
          <div className="ctrl-actions">
            <button className="btn-add" onClick={addRule}>
              + rule
            </button>
            {preview && <div className="ctrl-preview">{preview}{' '}<span className="dim">/ default {kLaHint || 'kLa field'}</span></div>}
          </div>
        </div>
      )}
    </section>
  )
}

function ruleTextLocal(r: CtrlRule): string {
  const lhs = r.when === 't' ? 'time' : r.when
  return `if ${lhs} ${r.op} ${r.value} → kLa=${r.set}`
}
