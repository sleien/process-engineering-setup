// One-command dev server for the WWTP Designer + PeePyPoo simulation.
//
//   npm run server
//     - builds the React app (→ dist/)
//     - starts the Python backend (uvicorn) which SERVES dist/ AND the /api/simulate
//       endpoint on http://localhost:8080
//
// Open http://localhost:8080 in one browser tab: UI + simulation, one port, one process.
//
// Flags:
//   --no-build   skip the frontend build and serve whatever is already in dist/
//   --port N     change the port (default 8080)
//   --host H     bind host (default 127.0.0.1)

import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(fileURLToPath(import.meta.url))
const argv = process.argv.slice(2)
const flag = (name) => argv.includes(name)
const value = (name, dflt) => {
  const i = argv.indexOf(name)
  return i !== -1 && argv[i + 1] ? argv[i + 1] : dflt
}

const PORT = value('--port', '8080')
const HOST = value('--host', '127.0.0.1')
const VENV = path.join(root, 'server', '.venv')

function run(cmd, args, opts = {}) {
  const p = spawn(cmd, args, { cwd: root, stdio: 'inherit', ...opts })
  return p
}

function fail(msg) {
  console.error('\n' + msg + '\n')
  process.exit(1)
}

// 1. Ensure the Python environment exists.
const uvicornBin = path.join(VENV, (process.platform === 'win32' ? 'Scripts' : 'bin'), 'uvicorn')
if (!existsSync(uvicornBin)) {
  fail(
    'The Python environment is missing (server/.venv).\n' +
      `Create it with:\n  python3 -m venv server/.venv\n` +
      `  server/.venv/bin/pip install peepypoo fastapi "uvicorn[standard]"\n` +
      '(see the "Simulation" section of the README)',
  )
}

// 2. Build the frontend unless asked to skip.
if (!flag('--no-build')) {
  const node = process.platform === 'win32' ? 'npm.cmd' : 'npm'
  console.log('▶ Building frontend (dist/) …')
  const build = spawnSync(node, ['run', 'build'], { cwd: root, stdio: 'inherit' })
  if (build.status !== 0) {
    fail('Frontend build failed. Fix the errors above, then run `npm run server -- --no-build`.')
  }
} else {
  if (!existsSync(path.join(root, 'dist', 'index.html'))) {
    fail('dist/ was not found and --no-build was given. Run `npm run build` first, or drop --no-build.')
  }
  console.log('▶ Skipping build (serving existing dist/).')
}

// 3. Start uvicorn, serving dist/ + /api/simulate. Ctrl+C here stops everything.
console.log(`▶ Starting server → http://localhost:${PORT}`)
console.log('  (first /api/simulate call compiles the simulation engine and can take a few minutes)\n')
const uv = run(uvicornBin, ['server.app:app', '--host', HOST, '--port', PORT, '--log-level', 'warning'])
uv.on('exit', (code) => process.exit(code ?? 0))
// Forward SIGINT/SIGTERM to uvicorn for a clean shutdown.
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => uv.kill(sig))
