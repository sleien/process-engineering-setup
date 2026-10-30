import { useEffect, useRef, useState, type ReactNode } from 'react'

export type MenuItem =
  | {
      label: string
      onClick: () => void
      title?: string
      /** Shortcut or short hint shown right-aligned in the row. */
      hint?: string
      /** Renders a check mark — for on/off settings kept in a menu. */
      checked?: boolean
      danger?: boolean
      disabled?: boolean
    }
  | 'separator'

type Props = {
  /** Button content (icon + label). */
  label: ReactNode
  title?: string
  items: MenuItem[]
  /** Open the list towards the left edge of the button instead of the right. */
  alignRight?: boolean
  className?: string
}

/** A button that drops down a short list of actions. Closes on pick, outside click or Esc. */
export default function Menu({ label, title, items, alignRight, className }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className={`menu${className ? ` ${className}` : ''}`} ref={ref}>
      <button
        type="button"
        className={`menu-button${open ? ' open' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={title}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
        <span className="menu-caret" aria-hidden>▾</span>
      </button>
      {open && (
        <div className={`menu-list${alignRight ? ' right' : ''}`} role="menu">
          {items.map((it, i) =>
            it === 'separator' ? (
              <div key={`sep-${i}`} className="menu-sep" role="separator" />
            ) : (
              <button
                key={it.label}
                type="button"
                role={it.checked === undefined ? 'menuitem' : 'menuitemcheckbox'}
                aria-checked={it.checked}
                className={`menu-item${it.danger ? ' danger' : ''}`}
                disabled={it.disabled}
                title={it.title}
                onClick={() => {
                  setOpen(false)
                  it.onClick()
                }}
              >
                <span className="menu-check" aria-hidden>
                  {it.checked ? '✓' : ''}
                </span>
                <span className="menu-label">{it.label}</span>
                {it.hint && <span className="menu-hint">{it.hint}</span>}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  )
}
