import type { Controller, CtrlRule, CtrlTarget } from '../lib/controller'
import {
  CTRL_OPS,
  MEASURES,
  TARGETS,
  defaultController,
  isTank,
  measureUnit,
  readControllers,
  targetsFor,
} from '../lib/controller'

export type TankRef = { id: string; label: string }

type Props = {
  node: {
    id: string
    data: { unitId: string; attributes?: Record<string, string>; controllers?: Controller[]; controller?: unknown }
  }
  /** Every tank on the canvas a rule can measure in. */
  tanks: TankRef[]
  onPatchNode: (id: string, patch: Record<string, unknown>) => void
}

/** Controllers on one unit — one per setting it changes, each a short rule list.
 *  Stored as `data.controllers` (see src/lib/controller.ts). */
export default function ControllerEditor({ node, tanks, onPatchNode }: Props) {
  const ctrls = readControllers(node.data)
  const offered = targetsFor(node.data.unitId)
  const free = offered.filter((t) => !ctrls.some((c) => c.target === t))
  const ownTank = isTank(node.data.unitId)
  // A rule on a tank measures in that tank unless told otherwise; elsewhere (a clarifier)
  // it starts on the first tank of the plant.
  const defaultAt = ownTank ? node.id : tanks[0]?.id

  // Writing the list also drops the older single `controller`, which it now contains.
  const save = (next: Controller[]) =>
    onPatchNode(node.id, { controllers: next.length ? next : undefined, controller: undefined })
  const patch = (i: number, c: Controller) => save(ctrls.map((x, j) => (j === i ? c : x)))
  const patchRule = (i: number, k: number, r: Partial<CtrlRule>) =>
    patch(i, { ...ctrls[i], rules: ctrls[i].rules.map((x, j) => (j === k ? { ...x, ...r } : x)) })

  const baseText = (target: CtrlTarget) =>
    target === 'kLa'
      ? `the unit's kLa (${(node.data.attributes?.kLa ?? '').trim() || 'default'})`
      : target === 'Q'
        ? `the influent's flow field (${(node.data.attributes?.Q ?? '').trim() || 'default'})`
        : 'the flow the model sizes'

  return (
    <section className="ctrl-editor">
      <div className="ctrl-head">
        <span className="ctrl-title">Controllers</span>
        {free.length > 0 && (
          <select
            className="ctrl-add"
            value=""
            onChange={(e) => {
              const t = e.target.value as CtrlTarget
              if (t) save([...ctrls, defaultController(t, defaultAt)])
            }}
            aria-label="Add a controller"
          >
            <option value="">+ Add…</option>
            {free.map((t) => (
              <option key={t} value={t}>{TARGETS[t].label}</option>
            ))}
          </select>
        )}
      </div>
      {ctrls.length === 0 && (
        <div className="ctrl-hint">
          Set {offered.map((t) => TARGETS[t].label.toLowerCase()).join(', ')} from what is
          measured in any tank — e.g. waste more sludge when a tank’s MLSS climbs.
        </div>
      )}
      {ctrls.map((c, i) => {
        const t = TARGETS[c.target]
        return (
          <div className="ctrl-card" key={c.target}>
            <div className="ctrl-card-head">
              <strong>{t.label}</strong>
              <label className="ctrl-sub" title="How often the rules are checked, in days of simulated time">
                every
                <input
                  className="ctrl-period"
                  type="number"
                  min={1}
                  max={1440}
                  step={1}
                  value={Math.round(c.period_days * 1440 * 10) / 10}
                  onChange={(e) => {
                    const v = Number(e.target.value)
                    if (Number.isFinite(v) && v > 0) patch(i, { ...c, period_days: v / 1440 })
                  }}
                />
                min
              </label>
              <button
                className="ctrl-del"
                onClick={() => save(ctrls.filter((_, j) => j !== i))}
                aria-label={`Remove the ${t.label} controller`}
                title="Remove this controller"
              >
                ✕
              </button>
            </div>
            <div className="ctrl-rows">
              {c.rules.map((r, k) => (
                <div className="ctrl-rule" key={k}>
                  <div className="ctrl-line">
                    <span className="ctrl-kw">if</span>
                    <select
                      className="ctrl-when"
                      value={r.when}
                      onChange={(e) => patchRule(i, k, { when: e.target.value as CtrlRule['when'] })}
                      aria-label="Measured value"
                    >
                      {MEASURES.map((m) => (
                        <option key={m.value} value={m.value}>{m.label}</option>
                      ))}
                    </select>
                    {r.when !== 't' && (
                      <>
                        <span className="ctrl-kw">in</span>
                        <select
                          className="ctrl-at"
                          title={tanks.find((x) => x.id === (r.at ?? node.id))?.label}
                          value={r.at ?? (ownTank ? node.id : '')}
                          onChange={(e) => patchRule(i, k, { at: e.target.value || undefined })}
                          aria-label="Tank measured in"
                        >
                          {!ownTank && !r.at && <option value="">choose a tank…</option>}
                          {r.at && !tanks.some((x) => x.id === r.at) && (
                            <option value={r.at}>(deleted unit)</option>
                          )}
                          {tanks.map((x) => (
                            <option key={x.id} value={x.id}>
                              {x.label}{x.id === node.id ? ' (this)' : ''}
                            </option>
                          ))}
                        </select>
                      </>
                    )}
                  </div>
                  <div className="ctrl-line">
                    <select
                      className="ctrl-op"
                      value={r.op}
                      onChange={(e) => patchRule(i, k, { op: e.target.value as CtrlRule['op'] })}
                      aria-label="Comparison"
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
                        if (Number.isFinite(v)) patchRule(i, k, { value: v })
                      }}
                      aria-label="Threshold"
                    />
                    <span className="ctrl-kw ctrl-unit">{measureUnit(r.when)}</span>
                  </div>
                  <div className="ctrl-line">
                    <span className="ctrl-kw">→ set</span>
                    <input
                      className="ctrl-set"
                      type="number"
                      min={0}
                      value={Number.isFinite(r.set) ? r.set : 0}
                      onChange={(e) => {
                        const v = Number(e.target.value)
                        if (Number.isFinite(v) && v >= 0) patchRule(i, k, { set: v })
                      }}
                      aria-label={`${t.label} to set`}
                    />
                    <span className="ctrl-kw ctrl-unit">{t.unit}</span>
                    <button
                      className="ctrl-del"
                      onClick={() => patch(i, { ...c, rules: c.rules.filter((_, j) => j !== k) })}
                      aria-label={`Remove rule ${k + 1}`}
                      disabled={c.rules.length === 1}
                      title={c.rules.length === 1 ? 'A controller needs at least one rule' : 'Remove this rule'}
                    >
                      ✕
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <div className="ctrl-actions">
              <button
                className="btn-add"
                onClick={() => {
                  const last = c.rules[c.rules.length - 1]
                  patch(i, { ...c, rules: [...c.rules, { ...last }] })
                }}
              >
                + rule
              </button>
              <span className="ctrl-hint">First match wins.</span>
            </div>
            <label className="ctrl-otherwise">
              <span className="ctrl-kw">otherwise</span>
              <select
                value={c.otherwise ?? 'base'}
                onChange={(e) => patch(i, { ...c, otherwise: e.target.value === 'hold' ? 'hold' : undefined })}
                title="What the controller does when no rule matches"
              >
                <option value="base">use {baseText(c.target)}</option>
                <option value="hold">keep the last setting (hysteresis)</option>
              </select>
            </label>
          </div>
        )
      })}
    </section>
  )
}
