// Use isolated_backend.py with PIN_LOCK_SECONDS=5, PIN_RATE_LIMIT=30,
// PAYMENT_DAILY_LIMIT=25.00 and RISK_BLOCK_AMOUNT=20.00. No development writes.
import { createRequire } from 'node:module'
import process from 'node:process'
import assert from 'node:assert/strict'
import path from 'node:path'
import { mkdir } from 'node:fs/promises'
import { configurePin, approvePayment, demoPin } from './security-helpers.mjs'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const output = path.resolve(process.env.PAYFLOW_SCREENSHOTS || './qa-output')
await mkdir(output, { recursive: true })
const api = 'http://127.0.0.1:18016'
const browser = await chromium.launch({ headless: true })
const a = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage()
const b = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage()
const password = 'Security-QA-Learning-2026!'
const errors = [], posted = []
const auth = new Map()
let lost = false
const nav = (page, name) => page.getByRole('navigation').getByRole('button', { name, exact: true }).click()
const text = (page, value) => page.getByText(value, { exact: true }).first().waitFor({ state: 'visible' })
const shot = (page, name) => page.screenshot({ path: path.join(output, name+'.png'), fullPage: true })
async function user(page, name) {
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', async route => {
    const req = route.request()
    if (['POST','PATCH','DELETE'].includes(req.method()) && !req.url().startsWith(api+'/')) {
      await route.abort(); throw new Error('Non-isolated QA write blocked')
    }
    if (req.url().startsWith(api+'/')) auth.set(page, req.headers().authorization || auth.get(page))
    if (page === a && req.url().endsWith('/payments/transfer')) {
      posted.push({ key: req.headers()['idempotency-key'], body: req.postData(), grant: req.headers()['payment-authorization'] })
      if (JSON.parse(req.postData()).amount === '12.30' && !lost) {
        lost = true
        const committed = await route.fetch()
        assert.equal(committed.status(), 201)
        await route.abort('failed'); return
      }
    }
    await route.continue()
  })
  const email = `${name.toLowerCase().replaceAll(' ','-')}-${Date.now()}@example.com`
  await page.goto('http://127.0.0.1:5173')
  await page.getByRole('button', { name: 'Create account', exact: true }).click()
  await page.getByLabel('Full name', { exact: true }).fill(name)
  await page.getByLabel('Email address', { exact: true }).fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByLabel('Confirm password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Create your account', exact: true }).click()
  await text(page, 'Account created. Sign in to continue.')
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in to PayFlow' }).click()
  await configurePin(page, password)
  await page.getByLabel('Demo bank').selectOption('Grove Demo Bank')
  const created = page.waitForResponse(r => r.url().endsWith('/accounts') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create demo account', exact: true }).click()
  return { email, account: await (await created).json() }
}
async function review(upi, amount) {
  await nav(a, 'Send Money')
  const edit = a.getByRole('button', { name: 'Edit payment', exact: true })
  if (await edit.isVisible()) await edit.click()
  const verify = a.getByRole('button', { name: 'Verify recipient', exact: true })
  if (await verify.isVisible()) {
    await a.getByLabel('Recipient UPI ID').fill(upi)
    await verify.click()
  }
  await a.getByLabel('Amount · INR').fill(amount)
  await a.getByRole('button', { name: 'Review payment', exact: true }).click()
  await a.getByRole('button', { name: `Confirm and send ₹${amount}` }).click()
  await a.getByRole('dialog', { name: 'Authorize simulated payment' }).waitFor()
}
async function get(page, route) {
  assert.ok(route.startsWith('/'))
  const response = await page.request.get(api+route, { headers: { Authorization: auth.get(page) } })
  assert.equal(response.status(), 200)
  return response.json()
}
try {
  const alice = await user(a, 'Security Alice'), bob = await user(b, 'Security Bob')
  await a.getByRole('button', { name: 'Add ₹1,000 demo funds' }).click()
  await text(a, 'Simulated funds added successfully.')
  await review(bob.account.upi_id, '20.00')
  assert.equal(posted.length, 0)
  await approvePayment(a)
  await a.getByText(/Payment blocked by a demo security rule: LARGE_PAYMENT/).waitFor()
  assert.equal((await get(a, '/payments/history')).items.filter(p => p.type === 'TRANSFER').length, 0)
  await shot(a, 'security-risk-block')

  await review(bob.account.upi_id, '12.30')
  const dialog = a.getByRole('dialog', { name: 'Authorize simulated payment' })
  for (let index=0; index<5; index++) {
    await dialog.getByLabel('Payment PIN', { exact: true }).fill('135790')
    const response = a.waitForResponse(r => r.url().endsWith('/security/payment-authorizations') && r.request().method() === 'POST')
    await dialog.getByRole('button', { name: 'Verify PIN and pay' }).click()
    assert.equal((await response).status(), index === 4 ? 423 : 400)
    await dialog.getByRole('alert').waitFor()
    assert.equal(await dialog.getByLabel('Payment PIN', { exact: true }).inputValue(), '')
  }
  await dialog.getByText(/Payment PIN is temporarily locked/).waitFor()
  await shot(a, 'security-pin-lockout')
  await dialog.getByRole('button', { name: 'Open Security Settings' }).click()
  await a.getByText(/Payment PIN temporarily locked until/).waitFor()
  await a.waitForTimeout(5200) // Deliberately short QA-only lockout; production default remains 900 s.
  await a.getByRole('button', { name: 'Refresh security' }).click()
  await a.getByRole('form', { name: 'Change Payment PIN' }).getByLabel('Current payment PIN').waitFor()
  assert.equal(await a.getByLabel('Current payment PIN').isEnabled(), true)

  await review(bob.account.upi_id, '12.30')
  await approvePayment(a)
  await text(a, 'Keep this payment request.')
  const stored = await a.evaluate(() => Object.entries(sessionStorage).find(([key]) => key.startsWith('payflow.pending.'))?.[1])
  assert.ok(stored)
  assert.ok(!stored.includes(demoPin) && !stored.includes('135790'))
  for (const entry of posted) if (entry.grant) assert.ok(!stored.includes(entry.grant))
  await a.reload()
  await a.getByLabel('Email address', { exact: true }).fill(alice.email)
  await a.getByLabel('Password', { exact: true }).fill(password)
  await a.getByRole('button', { name: 'Sign in to PayFlow' }).click()
  await a.getByRole('button', { name: 'Retry same request' }).click()
  await text(a, 'Simulated payment completed.')
  const attempts = posted.filter(p => JSON.parse(p.body).amount === '12.30')
  assert.equal(attempts.length, 2)
  assert.equal(attempts[0].key, attempts[1].key)
  assert.equal(attempts[0].body, attempts[1].body)
  assert.ok(attempts[0].grant && !attempts[1].grant)

  await review(bob.account.upi_id, '15.00')
  await approvePayment(a)
  await a.getByText('Payment limit exceeded. Daily limits reset at 00:00 UTC.', { exact: true }).waitFor()
  await shot(a, 'security-daily-limit')
  await nav(a, 'Security Settings')
  await a.getByLabel('Current payment PIN').fill(demoPin)
  await a.getByLabel('New payment PIN').fill('579248')
  await a.getByLabel('Confirm payment PIN').fill('579248')
  await a.getByRole('button', { name: 'Change PIN', exact: true }).click()
  await a.getByText(/Payment PIN changed. Earlier payment authorizations are invalid/).waitFor()
  await review(bob.account.upi_id, '1.00')
  const changed = a.getByRole('dialog', { name: 'Authorize simulated payment' })
  await changed.getByLabel('Payment PIN', { exact: true }).fill(demoPin)
  await changed.getByRole('button', { name: 'Verify PIN and pay' }).click()
  await changed.getByText('Incorrect payment PIN.', { exact: true }).waitFor()
  await approvePayment(a, '579248')
  await text(a, 'Simulated payment completed.')
  assert.equal((await get(a, '/accounts'))[0].balance, '986.70')
  assert.equal((await get(b, '/accounts'))[0].balance, '13.30')
  const security = await get(a, '/security/status')
  assert.equal(security.daily_amount_used, '13.30'); assert.equal(security.daily_count_used, 2)
  const events = await get(a, '/security/events?limit=50'), others = await get(b, '/security/events?limit=50')
  for (const type of ['PIN_CHANGED','PIN_LOCKED','PAYMENT_BLOCKED','RISK_RULE_TRIGGERED']) assert.ok(events.items.some(e => e.event_type === type))
  assert.ok(!others.items.some(e => events.items.some(mine => mine.id === e.id)))

  await nav(a, 'Security Settings')
  await a.getByRole('heading', { name: 'Your security activity' }).waitFor()
  for (const width of [320,390,768,1024,1440]) {
    await a.setViewportSize({ width, height: 900 })
    assert.ok(await a.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Security overflow at ${width}`)
  }
  await a.setViewportSize({ width: 390, height: 844 }); await shot(a, 'security-settings-mobile')
  await nav(a, 'Send Money')
  await review(bob.account.upi_id, '1.00')
  for (let index=0; index<8; index++) {
    await a.keyboard.press('Tab')
    assert.ok(await a.evaluate(() => !!document.activeElement.closest('dialog[open]')))
  }
  await shot(a, 'security-pin-mobile')
  await a.getByRole('dialog').getByRole('button', { name: 'Go back', exact: true }).click()
  for (const page of [a,b]) { await page.getByRole('button', { name: 'Log out', exact: true }).last().click(); await page.getByRole('button', { name: 'Sign in to PayFlow' }).waitFor() }
  assert.deepEqual(errors, [])
  console.log('Security browser passed: two users; password-authenticated PIN setup; five failures/lockout/recovery; risk and daily blocks; PIN change; masked/cleared inputs; lost committed response, reload/login and original-key headerless replay; balances/UTC usage/history; private audit; five widths; keyboard dialog containment; logout; no page errors. QA-only thresholds: 5 s lockout, PIN rate 30/min, daily INR 25, risk amount INR 20.')
} catch (error) {
  await shot(a, 'security-browser-failure')
  throw error
} finally { await browser.close() }
