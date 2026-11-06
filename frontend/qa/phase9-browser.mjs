import { launchBrowser, UI_URL } from './browser-support.mjs'
import { configurePin, approvePayment } from './security-helpers.mjs'
// Real UI with isolated_backend.py. All non-test writes are blocked.
import { createRequire } from 'node:module'
import process from 'node:process'
import assert from 'node:assert/strict'
import path from 'node:path'
import { mkdir } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const output = path.resolve(process.env.PAYFLOW_SCREENSHOTS || './qa-output')
await mkdir(output, { recursive: true })
const browser = await launchBrowser(chromium)
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
const nav = (name) => page.getByRole('navigation').getByRole('button', { name, exact: true }).click()
const shot = (name) => page.screenshot({ path: path.join(output, name + '.png'), fullPage: true })
const text = (value) => page.getByText(value, { exact: true }).first().waitFor({ state: 'visible' })
let auth
const attempts = { recharge: [], bill: [] }
let loseRecharge = true, loseBill = true
await page.route('**/*', async (route) => {
  const req = route.request(), url = req.url()
  if (['POST', 'PATCH', 'DELETE'].includes(req.method()) && !url.startsWith('http://127.0.0.1:18016/')) {
    await route.abort(); throw new Error('Attempted non-isolated write')
  }
  if (url.startsWith('http://127.0.0.1:18016/')) auth = req.headers().authorization || auth
  const recharge = url.endsWith('/recharge') && req.method() === 'POST'
  const bill = /\/bills\/[^/]+\/pay$/.test(url) && req.method() === 'POST'
  if (recharge || bill) {
    attempts[recharge ? 'recharge' : 'bill'].push({ key: req.headers()['idempotency-key'], body: req.postData() })
    if ((recharge && loseRecharge) || (bill && loseBill)) {
      const response = await route.fetch()
      assert.equal(response.status(), 201)
      if (recharge) loseRecharge = false
      else loseBill = false
      await route.abort('failed'); return
    }
  }
  await route.continue()
})
try {
  await page.goto(UI_URL)
  await page.getByRole('button', { name: 'Create account', exact: true }).click()
  await page.getByLabel('Full name', { exact: true }).fill('Services Learner')
  await page.getByLabel('Email address', { exact: true }).fill(`services-${Date.now()}@example.com`)
  await page.getByLabel('Password', { exact: true }).fill('Phase9-Learning-Only!')
  await page.getByLabel('Confirm password', { exact: true }).fill('Phase9-Learning-Only!')
  await page.getByRole('button', { name: 'Create your account', exact: true }).click()
  await text('Account created. Sign in to continue.')
  await page.getByLabel('Password', { exact: true }).fill('Phase9-Learning-Only!')
  await page.getByRole('button', { name: 'Sign in to PayFlow' }).click()
  await configurePin(page, 'Phase9-Learning-Only!')
  await page.getByLabel('Demo bank').selectOption('Grove Demo Bank')
  await page.getByRole('button', { name: 'Create demo account', exact: true }).click()
  await page.getByRole('button', { name: 'Add ₹1,000 demo funds' }).click()
  await text('Simulated funds added successfully.')
  await nav('My Bank Accounts')
  await page.getByLabel('Demo bank').selectOption('Orbit Demo Bank')
  await page.getByRole('button', { name: 'Add demo account', exact: true }).click()
  await page.getByRole('article', { name: 'Simulated bank account' }).filter({ has: page.getByText('Orbit Demo Bank', { exact: true }) }).waitFor()
  await page.getByRole('button', { name: 'Add ₹1,000 demo funds' }).click()
  await text('Simulated funds added successfully.')
  await nav('Bills & Recharge')
  await page.getByLabel('Demo mobile number').fill('9876543210')
  await page.getByLabel('Fictional operator').selectOption('payflow-mobile')
  await page.getByRole('radio', { name: /Demo Starter/ }).check()
  const options = await page.getByLabel('Source demo bank account').locator('option').allTextContents()
  const grove = options.find((value) => value.startsWith('Grove'))
  await page.getByLabel('Source demo bank account').selectOption({ label: grove })
  await shot('phase9-recharge-desktop')
  await page.getByRole('button', { name: 'Review recharge', exact: true }).click()
  assert.equal(attempts.recharge.length, 0)
  await text('Review simulated recharge')
  await page.getByRole('button', { name: 'Confirm simulated payment', exact: true }).click()
  await approvePayment(page)
  await page.getByRole('button', { name: 'Retry same request' }).click()
  await page.getByRole('article', { name: 'Payment receipt', exact: true }).getByText('SUCCESS', { exact: true }).waitFor()
  assert.deepEqual(attempts.recharge[0], attempts.recharge[1])
  await text('Simulated payment completed.')
  await page.getByRole('button', { name: 'Utility Bills', exact: true }).click()
  await page.getByLabel('Fictional biller').selectOption('electric')
  await page.getByLabel('Demo customer reference').fill('DEMO000001')
  await page.getByRole('button', { name: 'Fetch demo bill', exact: true }).click()
  const details = page.getByRole('article', { name: 'Demo bill details' })
  await details.getByText('UNPAID', { exact: true }).waitFor()
  await page.getByLabel('Biller nickname · optional').fill('Fictional home')
  await page.getByRole('button', { name: 'Save biller and reference' }).click()
  await text('Demo biller saved.')
  const orbit = (await details.getByLabel('Source demo bank account').locator('option').allTextContents()).find((value) => value.startsWith('Orbit'))
  await details.getByLabel('Source demo bank account').selectOption({ label: orbit })
  await page.getByRole('button', { name: 'Review bill payment' }).click()
  assert.equal(attempts.bill.length, 0)
  await shot('phase9-bill-review')
  await page.getByRole('button', { name: 'Confirm simulated payment' }).click()
  await approvePayment(page)
  await page.getByRole('button', { name: 'Retry same request' }).click()
  await page.getByRole('article', { name: 'Payment receipt' }).getByText('SIMULATED BILL PAYMENT', { exact: false }).waitFor()
  assert.deepEqual(attempts.bill[0], attempts.bill[1])
  await text('Simulated payment completed.')
  await page.getByRole('button', { name: 'Saved Billers', exact: true }).click()
  await text('Fictional home')
  await page.getByRole('button', { name: 'Fetch current demo bill' }).click()
  await details.getByText('PAID', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Review bill payment' }).count(), 0)
  await page.getByRole('button', { name: 'Service History', exact: true }).click()
  await text('PayFlow Mobile · Demo Starter')
  await page.getByRole('button', { name: 'View recharge receipt' }).click()
  await page.getByRole('article', { name: 'Payment receipt' }).getByText('SIMULATED RECHARGE', { exact: false }).first().waitFor()
  await page.getByRole('button', { name: 'View bill receipt' }).click()
  await page.getByRole('article', { name: 'Payment receipt' }).getByText('SIMULATED BILL PAYMENT', { exact: false }).waitFor()
  await shot('phase9-history-receipt')
  const response = await page.request.get('http://127.0.0.1:18016/accounts', { headers: { Authorization: auth } })
  const accounts = await response.json()
  const history = await (await page.request.get('http://127.0.0.1:18016/payments/history', { headers: { Authorization: auth } })).json()
  const billPayment = history.items.find((item) => item.type === 'BILL_PAYMENT')
  assert.equal(accounts.find((item) => item.bank_name === 'Grove Demo Bank').balance, '901.00')
  assert.equal(accounts.find((item) => item.bank_name === 'Orbit Demo Bank').balance, (1000 - Number(billPayment.amount)).toFixed(2))
  assert.equal(history.items.filter((item) => item.type === 'MOBILE_RECHARGE').length, 1)
  assert.equal(history.items.filter((item) => item.type === 'BILL_PAYMENT').length, 1)
  for (const width of [320, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow at ${width}`)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await shot('phase9-mobile-history')
  await nav('Home')
  await page.locator('.secondary-actions').getByRole('button', { name: 'Bills & Recharge' }).click()
  await page.getByRole('radio', { name: /Demo Starter/ }).waitFor()
  for (const width of [320, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Recharge overflow at ${width}`)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await shot('phase9-mobile-recharge')
  await nav('Profile')
  await page.getByRole('button', { name: 'Log out', exact: true }).last().click()
  await page.getByRole('button', { name: 'Sign in to PayFlow' }).waitFor()
  assert.deepEqual(errors, [])
  console.log('Phase 9 browser passed: owned source selection, recharge, saved biller, stable paid bill, explicit confirmations, both committed-response retries, receipts, history, mobile navigation, 5 widths, logout; no page errors.')
} catch (error) {
  await shot('phase9-failure')
  throw error
} finally { await browser.close() }
