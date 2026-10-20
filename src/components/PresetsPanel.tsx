import { useEffect, useRef, useState } from 'react'
import {
  TIME_DAYS_MAX,
  TIME_DAYS_MIN,
  formatTimeDays,
  parsePresets,
  type Preset,
  type SimSettings,
} from '../lib/presets'
import { STATE_META, STATE_ORDER, ENGINE_DEFAULT_INFLUENT, ENGINE_DEFAULT_FLOW_M3D } from '../lib/states'

type Props = {
  open: boolean
  settings: SimSettings
  presets: Preset[]
  /** Base composition (mg/L) used as the placeholder under un-set overrides. */
  baseComposition?: Record<string, number>
  onSettingsChange: (s: SimSettings) => void
  onSavePreset: (name: string) => void
  onApplyPreset: (p: Preset) => void
  onDeletePreset: (name: string) => void
  onImport: (presets: Preset[]) => void
  onExport: () => void
  onClearSettings: () => void
  onClose: () => void
}

function hasAnySetting(s: SimSettings): boolean {
  return s.time_days != null && s.time_days !== 'auto'
    || s.influent_flow != null
    || (s.influent_overrides != null && Object.keys(s.influent_overrides).length > 0)
}

/** Duration control: "auto" checkbox (backend default) or a number of days. */
function DurationRow({
  value,
  onChange,
}: {
  value: number | 'auto' | undefined
  onChange: (v: number | 'auto') => void
}) {
  const auto = value == null || value === 'auto'
  const [text, setText] = useState(auto ? '' : String(value))
  useEffect(() => setText(auto ? '' : String(value)), [value, auto])
  const commit = () => {
    if (auto) return
    const n = Number(text)
    if (Number.isFinite(n) && n >= TIME_DAYS_MIN && n <= TIME_DAYS_MAX) onChange(n)
    else setText(String(value))
  }
  return (
    <div className="presets-row">
      <span className="presets-label">Duration</span>
      <label className="presets-inline" title="Let the engine pick the duration from the reactor volumes">
        <input
          type="checkbox"
          checked={auto}
          onChange={(e) => {
            if (e.target.checked) onChange('auto')
            else {
              const n = Number(text)
              onChange(Number.isFinite(n) && n >= TIME_DAYS_MIN && n <= TIME_DAYS_MAX ? n : TIME_DAYS_MIN)
            }
          }}
        />
        auto
      </label>
      <input
        type="number"
        className="presets-days"
        min={TIME_DAYS_MIN}
        max={TIME_DAYS_MAX}
        step={1}
        disabled={auto}
        value={text}
        spellCheck={false}
        placeholder="days"
        aria-label="Simulation duration in days"
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
      />
      <span className="presets-note">days (0.5 – {TIME_DAYS_MAX})</span>
      {!auto && <span className="presets-badge">override</span>}
    </div>
  )
}

/** Influent flow control: blank = backend default, a number = override. */
function FlowRow({
  value,
  onChange,
}: {
  value: number | undefined
  onChange: (v: number | undefined) => void
}) {
  const [text, setText] = useState(value == null ? '' : String(value))
  useEffect(() => setText(value == null ? '' : String(value)), [value])
  const commit = () => {
    if (text.trim() === '') onChange(undefined)
    else {
      const n = Number(text)
      if (Number.isFinite(n) && n > 0) onChange(n)
      else setText(value == null ? '' : String(value))
    }
  }
  return (
    <div className="presets-row">
      <span className="presets-label">Influent flow</span>
      <input
        type="number"
        className="presets-days"
        min={0}
        step={100}
        value={text}
        spellCheck={false}
        placeholder={`${ENGINE_DEFAULT_FLOW_M3D} (auto)`}
        aria-label="Influent flow override in m³/d"
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
      />
      <span className="presets-note">m³/d (blank = auto)</span>
      {value != null && <span className="presets-badge">override</span>}
    </div>
  )
}

/** One overridable composition row: blank keeps the default, a number overrides it. */
function CompRow({
  k,
  value,
  base,
  onChange,
}: {
  k: string
  value?: number
  base?: number
  onChange: (v: number | undefined) => void
}) {
  const [text, setText] = useState(value == null ? '' : String(value))
  useEffect(() => setText(value == null ? '' : String(value)), [value])
  const placeholder = base != null ? `${base} (default)` : 'default'
  const commit = () => {
    if (text.trim() === '') onChange(undefined)
    else {
      const n = Number(text)
      if (Number.isFinite(n) && n >= 0) onChange(n)
      else setText(value == null ? '' : String(value))
    }
  }
  return (
    <label className="sim-comp-row" title={STATE_META[k]?.label}>
      <span className="sim-comp-name">
        <strong>{k}</strong>
        <small>{STATE_META[k]?.unit}</small>
      </span>
      <input
        type="number"
        min={0}
        step="any"
        value={text}
        placeholder={placeholder}
        spellCheck={false}
        aria-label={`${k} default concentration override`}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
      />
      {value != null && <span className="presets-badge">override</span>}
    </label>
  )
}

/** Modal for the simulation defaults (duration, influent) + named presets (browser-stored, import/exportable). */
export default function PresetsPanel({
  open,
  settings,
  presets,
  baseComposition,
  onSettingsChange,
  onSavePreset,
  onApplyPreset,
  onDeletePreset,
  onImport,
  onExport,
  onClearSettings,
  onClose,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [showComposition, setShowComposition] = useState(false)

  // Composition rows: every ASM1 state with an engine default or an override of its own.
  // The last result's actual composition (if any) wins over the engine defaults for the
  // placeholder, so "what I get if I leave this blank" is honest.
  const base = { ...ENGINE_DEFAULT_INFLUENT, ...baseComposition }
  const compKeys = [
    ...STATE_ORDER.filter((k) => k in (settings.influent_overrides ?? {}) || k in base || ENGINE_DEFAULT_INFLUENT[k] != null),
    ...Object.keys(settings.influent_overrides ?? {}).filter((k) => !STATE_ORDER.includes(k)),
  ]

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const setFlow = (v: number | undefined) => {
    const next = { ...settings }
    if (v == null) delete next.influent_flow
    else next.influent_flow = v
    onSettingsChange(next)
  }
  const setComp = (k: string, v: number | undefined) => {
    const next = { ...settings }
    if (v == null) {
      if (next.influent_overrides) {
        const ov = { ...next.influent_overrides }
        delete ov[k]
        next.influent_overrides = Object.keys(ov).length ? ov : undefined
      }
    } else {
      next.influent_overrides = { ...next.influent_overrides, [k]: v }
    }
    onSettingsChange(next)
  }

  const loadEngineDefaults = () => {
    const next = { ...settings }
    const ov: Record<string, number> = { ...settings.influent_overrides }
    for (const [k, v] of Object.entries(base)) ov[k] = v
    next.influent_overrides = ov
    onSettingsChange(next)
  }
  const clearOverrides = () => {
    const next = { ...settings }
    next.influent_overrides = undefined
    onSettingsChange(next)
  }

  const handleSave = () => {
    if (!newName.trim()) {
      setError('Give the preset a name first.')
      return
    }
    onSavePreset(newName.trim())
    setNewName('')
    setError(null)
  }

  const handleImport = (file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const imported = parsePresets(String(reader.result))
      if (!imported) {
        window.alert('That file is not a valid WWTP presets file.')
        return
      }
      onImport(imported)
    }
    reader.readAsText(file)
  }

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-label="Simulation presets" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span>Simulation</span>
          <button className="modal-x" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-body">
          <DurationRow value={settings.time_days} onChange={(v) => onSettingsChange({ ...settings, time_days: v })} />
          <FlowRow value={settings.influent_flow} onChange={setFlow} />

          <button
            type="button"
            className="sim-link"
            aria-expanded={showComposition}
            onClick={() => setShowComposition((v) => !v)}
          >
            {showComposition ? 'Hide' : 'Edit'} influent composition
            {settings.influent_overrides && Object.keys(settings.influent_overrides).length > 0 && (
              <small>· {Object.keys(settings.influent_overrides).length} override(s)</small>
            )}
          </button>
          {showComposition && (
            <>
              <div className="presets-mini-row">
                <button onClick={loadEngineDefaults} title="Fill every state with the engine's built-in BSM1 values, then edit from there">
                  Use engine defaults
                </button>
                <button onClick={clearOverrides} disabled={!settings.influent_overrides || Object.keys(settings.influent_overrides).length === 0} title="Remove every composition override (back to engine defaults)">
                  Clear overrides
                </button>
              </div>
              <div className="sim-comp-editor" style={{ maxHeight: 260, overflowY: 'auto' }}>
                {compKeys.map((k) => (
                  <CompRow
                    key={k}
                    k={k}
                    value={settings.influent_overrides?.[k]}
                    base={base?.[k]}
                    onChange={(v) => setComp(k, v)}
                  />
                ))}
              </div>
            </>
          )}
          {error && <div className="presets-error">{error}</div>}
          <div className="presets-note" style={{ marginTop: -2 }}>
            Blank fields keep the engine defaults. Overrides apply to every run until changed.
          </div>

          <div className="presets-save">
            <input
              className="presets-name"
              placeholder="New preset name…"
              value={newName}
              spellCheck={false}
              aria-label="New preset name"
              onChange={(e) => {
                setNewName(e.target.value)
                if (error) setError(null)
              }}
              onKeyDown={(e) => e.key === 'Enter' && handleSave()}
            />
            <button onClick={handleSave} title="Save the current defaults under this name">
              Save
            </button>
          </div>

          <div className="presets-list">
            {presets.length === 0 && (
              <div className="presets-empty">
                No presets yet — set the defaults above and save one to re-apply them later.
              </div>
            )}
            {presets.map((p) => (
              <div className="preset-row" key={p.name}>
                <span className="preset-name" title={p.savedAt ?? ''}>
                  {p.name}
                </span>
                <span className="preset-meta">
                  {formatTimeDays(p.settings.time_days)}
                  {p.settings.influent_flow != null ? ` · ${p.settings.influent_flow} m³/d` : ''}
                </span>
                <button className="preset-apply" onClick={() => onApplyPreset(p)} title={`Apply "${p.name}"`}>
                  Apply
                </button>
                <button
                  className="preset-del"
                  onClick={() => onDeletePreset(p.name)}
                  title={`Delete "${p.name}"`}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
        <div className="modal-foot">
          <button
            onClick={onClearSettings}
            disabled={!hasAnySetting(settings)}
            title="Clear all simulation defaults (back to engine defaults)"
          >
            Reset
          </button>
          <span className="modal-foot-spacer" />
          <button onClick={onExport} title="Download the presets as a JSON file">
            Export
          </button>
          <button onClick={() => fileRef.current?.click()} title="Import presets from a JSON file">
            Import
          </button>
          <button className="primary" onClick={onClose}>
            Done
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".json,application/json"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleImport(f)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}
