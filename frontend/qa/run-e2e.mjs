// Starts only owned processes on dedicated ports; never targets the development API.
import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdir, open } from 'node:fs/promises'
import net from 'node:net'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.dirname(frontend)
const python = process.env.PAYFLOW_PYTHON || path.join(root, 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const key = randomBytes(32).toString('hex')
const base = 'http://127.0.0.1:18016'
const common = { ...process.env, PAYFLOW_ENV: 'test', PAYFLOW_E2E_KEY: key,
  JWT_SECRET_KEY: randomBytes(32).toString('hex'),
  PAYFLOW_E2E_FRONTEND_URL: 'http://127.0.0.1:5180', VITE_API_BASE_URL: base,
  CORS_ALLOWED_ORIGINS: 'http://127.0.0.1:5180', PAYFLOW_E2E_MANAGED: '1', LOG_LEVEL: 'WARNING' }
const output = path.join(root, 'test-artifacts', 'e2e')
await mkdir(output, { recursive: true })

async function free(port) {
  await new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', () => reject(new Error(`Dedicated E2E port ${port} is already occupied; no process was stopped.`)))
    server.listen(port, '127.0.0.1', () => server.close(resolve))
  })
}
async function waitFor(url, child) {
  const until = Date.now() + 120000
  while (Date.now() < until) {
    if (child.exitCode !== null) throw new Error('Owned E2E service exited before readiness')
    try { const response = await fetch(url, { headers: { 'X-QA-Key': key }, signal: AbortSignal.timeout(2000) }); if (response.ok) return } catch { /* Bounded readiness retry only, no payment retry. */ }
    await new Promise(resolve => setTimeout(resolve, 300))
  }
  throw new Error('Timed out waiting for the isolated E2E service')
}
async function stopped(child, timeout = 25000) {
  if (child.exitCode !== null) return child.exitCode
  return await Promise.race([new Promise(resolve => child.once('exit', resolve)),
    new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('Owned E2E process did not stop')), timeout); timer.unref() })])
}
async function stage(name, scenarios, extra = {}) {
  const logs = await open(path.join(output, `${name}-server.log`), 'w')
  const backend = spawn(python, ['-B', path.join(frontend, 'qa', 'isolated_backend.py')],
    { cwd: root, env: { ...common, ...extra }, stdio: ['ignore', logs.fd, logs.fd], windowsHide: true })
  backend.on('error', () => {})
  try {
    await waitFor(base + '/__qa/ready', backend)
    for (const scenario of scenarios) {
      const child = spawn(process.execPath, [path.join(frontend, 'qa', 'run-scenario.mjs'), scenario], {
        cwd: frontend, env: { ...common, PAYFLOW_SCREENSHOTS: path.join(output, scenario.replace('.mjs', '')) },
        stdio: 'inherit', windowsHide: true,
      })
      const code = await stopped(child, 300000)
      if (code !== 0) throw new Error(`Isolated browser scenario failed: ${scenario}`)
    }
    await waitFor(base + '/__qa/drained', backend)
  } finally {
    try {
      await fetch(base + '/__qa/stop', { method: 'POST', headers: { 'X-QA-Key': key }, signal: AbortSignal.timeout(5000) })
      if (await stopped(backend) !== 0) throw new Error('E2E reconciliation/data-preservation check failed')
    } finally { await logs.close() }
  }
}

await free(5180); await free(18016)
const viteLogs = await open(path.join(output, 'vite.log'), 'w')
const vite = spawn(process.execPath, [path.join(frontend, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5180', '--strictPort'],
  { cwd: frontend, env: common, stdio: ['ignore', viteLogs.fd, viteLogs.fd], windowsHide: true })
try {
  await waitFor(common.PAYFLOW_E2E_FRONTEND_URL, vite)
  await stage('regression', ['phase6-browser.mjs', 'phase7-browser.mjs', 'phase8-browser.mjs', 'phase9-browser.mjs'])
  await stage('security', ['security-browser.mjs'], { PIN_LOCK_SECONDS: '5', PIN_RATE_LIMIT: '30', PAYMENT_DAILY_LIMIT: '25.00', RISK_BLOCK_AMOUNT: '20.00' })
  console.log('E2E passed: five isolated scenarios, real worker, reconciliation and development-data comparisons.')
} finally {
  vite.kill('SIGTERM'); await stopped(vite); await viteLogs.close()
}
