// Built-asset/CSP smoke, restricted to the label-verified local Compose project.
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { configurePin } from './security-helpers.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const python = process.env.PAYFLOW_PYTHON || path.join(root, 'backend/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const base = execFileSync(python, ['-c', "import sys; sys.path.insert(0,'tools'); from compose_guard import base_url; print(base_url())"], { cwd: root, encoding: 'utf8', windowsHide: true }).trim()
assert.ok(/^http:\/\/127\.0\.0\.1:\d+$/.test(base))
const output = path.join(root, 'test-artifacts', 'compose-ui')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', () => errors.push('pageerror'))
page.on('console', message => { if (message.type() === 'error') errors.push('console-error') })
await page.route('**/*', async route => {
  if (['POST', 'PATCH', 'DELETE'].includes(route.request().method()) && !route.request().url().startsWith(base + '/api/')) {
    await route.abort(); throw new Error('Non-Compose browser write blocked')
  }
  await route.continue()
})
try {
  await page.goto(base)
  await page.getByRole('button', { name: 'Create account', exact: true }).click()
  const password = randomBytes(24).toString('hex')
  await page.getByLabel('Full name', { exact: true }).fill('Container Browser Fixture')
  await page.getByLabel('Email address', { exact: true }).fill(`container-${Date.now()}@example.com`)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByLabel('Confirm password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Create your account', exact: true }).click()
  await page.getByText('Account created. Sign in to continue.', { exact: true }).waitFor()
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in to PayFlow', exact: true }).click()
  await configurePin(page, password)
  await page.getByLabel('Demo bank').selectOption('Grove Demo Bank')
  await page.getByRole('button', { name: 'Create demo account', exact: true }).click()
  await page.getByRole('article', { name: 'Simulated bank account' }).waitFor()
  await page.getByRole('button', { name: 'Add ₹1,000 demo funds' }).click()
  await page.getByText('Simulated funds added successfully.', { exact: true }).waitFor()
  await page.getByRole('navigation').getByRole('button', { name: 'My QR', exact: true }).click()
  await page.getByRole('img', { name: 'Your PayFlow sandbox payment QR code' }).waitFor()
  for (const width of [320, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  }
  assert.deepEqual(errors, [])
  await page.screenshot({ path: path.join(output, 'built-qr.png'), fullPage: true, mask: [page.locator('input')] })
  await page.getByRole('button', { name: 'Log out', exact: true }).last().click()
  await page.getByRole('button', { name: 'Sign in to PayFlow', exact: true }).waitFor()
  console.log('Built Compose UI passed: proxy, headers/CSP, registration/login/PIN/account/funding, QR generation, five widths, logout and no browser errors.')
} catch (error) {
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true, mask: [page.locator('input')] })
  console.error(error instanceof Error ? error.name : 'Compose browser failure')
  process.exitCode = 1
} finally { await browser.close() }
