/**
 * Production uvicorn (no --reload). Port: env PORT, default 3002.
 * Interpreter: env PYTHON, else `python` on Windows and `python3` elsewhere.
 * Run from repo root: node scripts/run-uvicorn-prod.mjs
 */
import { spawn } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const port = process.env.PORT || '3002'
const python =
  process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3')

const child = spawn(
  python,
  ['-m', 'uvicorn', 'server.api:app', '--host', '0.0.0.0', '--port', port],
  { cwd: root, stdio: 'inherit', shell: process.platform === 'win32' }
)

child.on('exit', (code) => process.exit(code ?? 1))
