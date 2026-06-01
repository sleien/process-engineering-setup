import { useEffect, useRef, useState } from 'react'
import { STREAMS, type StreamColors, type StreamDef, type StreamType } from '../lib/streams'

type Props = {
  open: boolean
  colors: StreamColors
  onChange: (id: StreamType, color: string) => void
  onReset: () => void
  onDownload: () => void
  onUpload: (file: File) => void
  onClose: () => void
}

/** One editable colour row: a native colour picker plus a hex field (free typing, commits on a
 *  valid #rrggbb, snaps back to the canonical value on blur). */
function ColorRow({ def, value, onChange }: { def: StreamDef; value: string; onChange: (c: string) => void }) {
  const [text, setText] = useState(value)
  useEffect(() => setText(value), [value])
  return (
    <div className="color-row">
      <span className="color-label">{def.label}</span>
      <input
        type="color"
        className="color-swatch-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        title={`Pick ${def.label} colour`}
      />
      <input
        className="color-hex"
        value={text}
        spellCheck={false}
        aria-label={`${def.label} hex colour`}
        onChange={(e) => {
          const v = e.target.value
          setText(v)
          if (/^#[0-9a-fA-F]{6}$/.test(v)) onChange(v)
        }}
        onBlur={() => setText(value)}
      />
    </div>
  )
}

/** Modal for editing the stream-colour palette (persisted in the browser, download/uploadable). */
export default function ColorSettings({ open, colors, onChange, onReset, onDownload, onUpload, onClose }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-label="Stream colours" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span>Stream colours</span>
          <button className="modal-x" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-body">
          {STREAMS.map((s) => (
            <ColorRow key={s.id} def={s} value={colors[s.id]} onChange={(c) => onChange(s.id, c)} />
          ))}
        </div>
        <div className="modal-foot">
          <button onClick={onReset} title="Restore the default colours">
            Reset
          </button>
          <div className="modal-foot-spacer" />
          <button onClick={onDownload} title="Download these colours as a file">
            Download
          </button>
          <button onClick={() => fileRef.current?.click()} title="Upload a colours file">
            Upload
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
            if (f) onUpload(f)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}
