// Single place for the app version and the version-fetch that the toolbar badge uses.
//
// Keep `APP_VERSION` in sync with `server/app.py:API_VERSION`. They are reported *separately*
// on purpose: the **frontend** version only tells you the UI is current, but the **backend**
// is what builds the simulation model (and therefore what has the washout fix). The badge
// shows both and flags which one is out of date, so "I still have washout" can be pinned to
// the backend actually being served.
export const APP_VERSION = '0.2.0'

export type ServerVersion = {
  ok: boolean
  /** 'offline' (no backend), or the backend's reported version string. */
  version?: string
  /** Feature flags the backend reports (e.g. 'recirc-wired', 'mlss-srt-control'). */
  features?: string[]
}

/** Fetch the backend's self-reported version. `ok:false` means the backend is unreachable. */
export async function fetchServerVersion(): Promise<ServerVersion> {
  try {
    const res = await fetch('/api/version', { headers: { accept: 'application/json' } })
    if (!res.ok) return { ok: false }
    const data = (await res.json()) as { version?: string; features?: string[] }
    return { ok: true, version: data.version ?? '', features: data.features ?? [] }
  } catch {
    return { ok: false }
  }
}
