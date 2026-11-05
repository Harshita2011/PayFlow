import { configurePin, approvePayment } from './security-helpers.mjs'
// Real UI checks with isolated_backend.py; all writes are blocked outside :18016.
import { createRequire } from 'node:module'
import process from 'node:process'
import { Buffer } from 'node:buffer'
import assert from 'node:assert/strict'
import path from 'node:path'
import { mkdir } from 'node:fs/promises'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const output = path.resolve(process.env.PAYFLOW_SCREENSHOTS || './qa-output')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const errors = []
const password = 'Phase8-Learning-Only!'
const nav = (page, name) => page.getByRole('navigation').getByRole('button', { name, exact: true }).click()
const text = (page, value) => page.getByText(value, { exact: true }).first().waitFor({ state: 'visible' })
const shot = (page, name, fullPage = true) => page.screenshot({ path: path.join(output, name + '.png'), fullPage })
async function feature(page, name) {
  await nav(page, 'Home')
  await page.locator('.secondary-actions').getByRole('button', { name, exact: true }).click()
}
async function user(page, name, bank) {
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/*', async (route) => {
    if (['POST','PATCH','DELETE'].includes(route.request().method()) && !route.request().url().startsWith('http://127.0.0.1:18016/')) {
      await route.abort(); throw new Error('QA attempted a non-isolated write')
    }
    await route.continue()
  })
  await page.goto('http://127.0.0.1:5173')
  await page.getByRole('button', { name: 'Create account', exact: true }).click()
  await page.getByLabel('Full name', { exact: true }).fill(name)
  await page.getByLabel('Email address', { exact: true }).fill(`${name.toLowerCase().replaceAll(' ', '-')}-${Date.now()}@example.com`)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByLabel('Confirm password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Create your account', exact: true }).click()
  await text(page, 'Account created. Sign in to continue.')
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in to PayFlow' }).click()
  await configurePin(page, password)
  await page.getByLabel('Demo bank').selectOption(bank)
  const response = page.waitForResponse((result) => result.url().endsWith('/accounts') && result.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create demo account', exact: true }).click()
  const account = await (await response).json()
  await page.getByRole('article', { name: 'Simulated bank account' }).waitFor()
  await page.getByRole('button', { name: 'Add ₹1,000 demo funds' }).click()
  await text(page, 'Simulated funds added successfully.')
  return account
}
async function saveContact(page, person, displayName) {
  await nav(page, 'Contacts')
  // Wait for the preceding save to release its disabled fieldset before filling.
  await page.locator('form[aria-label="Find PayFlow user"] fieldset:not([disabled])').waitFor()
  await page.getByLabel('UPI ID to find').fill(person.upi_id)
  const verified = page.waitForResponse(result => result.url().endsWith('/payments/resolve') && result.request().method() === 'POST')
  await page.getByRole('button', { name: 'Verify user', exact: true }).click()
  const response = await verified
  assert.equal(response.status(), 200, `Recipient verification failed: ${await response.text()}`)
  await text(page, `Verified: ${displayName}`)
  await page.getByRole('button', { name: 'Add to saved contacts' }).click()
  await text(page, 'Contact saved to your personal address book.')
}
async function createExpense(page, title, total, participants, includeCreator = true) {
  await nav(page, 'Split Expenses')
  for (const person of participants) await page.getByLabel('Add saved contact').selectOption(person.upi_id)
  await page.getByLabel('Expense title', { exact: true }).fill(title)
  await page.getByLabel('Total expense · INR').fill(total)
  await page.getByLabel('Include my own share').setChecked(includeCreator)
  await page.getByLabel('This is an externally paid expense record, not a verified PayFlow bill payment.').check()
  await shot(page, 'phase8-split-preview')
  await page.getByRole('button', { name: 'Review split', exact: true }).click()
  await page.getByRole('button', { name: 'Confirm and create split' }).click()
  await text(page, 'Split created. No money moved.')
  await page.getByRole('region', { name: 'Split details' }).getByRole('heading', { name: title, exact: true }).waitFor()
}
async function bankBalance(page, bank, expected) {
  const card = page.getByRole('article', { name: 'Simulated bank account' }).filter({ has: page.getByText(bank, { exact: true }) })
  await card.getByText(expected, { exact: true }).waitFor()
}
try {
  const a = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage()
  const b = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage()
  const c = await (await browser.newContext({ viewport: { width: 768, height: 1000 } })).newPage()
  const original = await user(a, 'Phase8 Asha', 'Grove Demo Bank')
  const ravi = await user(b, 'Phase8 Ravi', 'Orbit Demo Bank')
  const eva = await user(c, 'Phase8 Eva', 'River Demo Bank')
  await nav(a, 'My QR')
  const qr = a.getByRole('img', { name: 'Your PayFlow sandbox payment QR code' })
  await qr.waitFor()
  const oldQr = Buffer.from((await qr.getAttribute('src')).split(',')[1], 'base64')
  await nav(a, 'My Bank Accounts')
  await a.getByRole('form', { name: 'Add simulated bank account' }).getByLabel('Demo bank').selectOption('Orbit Demo Bank')
  const addedEvent = a.waitForResponse((result) => result.url().endsWith('/accounts') && result.request().method() === 'POST')
  await a.getByRole('button', { name: 'Add demo account', exact: true }).click()
  const added = await (await addedEvent).json()
  await a.getByRole('button', { name: 'Set as primary account', exact: true }).click()
  await text(a, 'Primary account updated. Existing UPI destinations are unchanged.')
  await bankBalance(a, 'Grove Demo Bank', '₹1,000.00')
  await bankBalance(a, 'Orbit Demo Bank', '₹0.00')
  await shot(a, 'phase8-multiple-accounts')

  await nav(a, 'Transfer to Self')
  await a.getByLabel('From bank account').selectOption(String(original.id))
  await a.getByLabel('To bank account').selectOption(String(added.id))
  await a.getByLabel('Self transfer amount · INR').fill('700.00')
  let sends = 0
  const keys = []
  a.on('request', (request) => { if (request.url().endsWith('/payments/self-transfer')) sends += 1 })
  await a.getByRole('button', { name: 'Review self transfer', exact: true }).click()
  assert.equal(sends, 0)
  await shot(a, 'phase8-self-review')
  let lost = false
  await a.route('**/payments/self-transfer', async (route) => {
    assert.ok(route.request().url().startsWith('http://127.0.0.1:18016/'))
    keys.push(route.request().headers()['idempotency-key'])
    if (!lost) { lost = true; const response = await route.fetch(); assert.equal(response.status(), 201); await route.abort('failed') }
    else await route.continue()
  })
  await a.getByRole('button', { name: 'Confirm self transfer' }).click()
  await approvePayment(a)
  await text(a, 'Keep this payment request.')
  await nav(a, 'Home')
  assert.equal(await a.getByLabel('Source account').isDisabled(), true)
  await a.getByRole('button', { name: 'Retry same request' }).click()
  await text(a, 'Simulated self-transfer completed.')
  assert.equal(keys.length, 2); assert.equal(keys[0], keys[1])
  await nav(a, 'My Bank Accounts')
  await bankBalance(a, 'Grove Demo Bank', '₹300.00')
  await bankBalance(a, 'Orbit Demo Bank', '₹700.00')
  await nav(a, 'Transactions')
  await a.getByLabel('Show transactions').selectOption('SELF')
  assert.equal(await a.locator('.history-list li').count(), 1)
  await text(a, 'SELF TRANSFER · SUCCESS')

  await saveContact(a, ravi, 'Phase8 Ravi')
  await saveContact(a, eva, 'Phase8 Eva')
  await createExpense(a, 'Three-person dinner', '100.00', [ravi,eva])
  let detail = a.getByRole('region', { name: 'Split details' })
  await detail.getByText('₹33.34', { exact: true }).first().waitFor()
  await detail.getByText('₹66.66', { exact: true }).waitFor()
  await shot(a, 'phase8-split-open')
  // Switch the creator's primary: the already-created split stays pinned to Orbit.
  await nav(a, 'My Bank Accounts')
  await a.getByRole('button', { name: 'Set as primary account', exact: true }).click()
  await text(a, 'Primary account updated. Existing UPI destinations are unchanged.')
  await feature(b, 'My Splits')
  await b.getByRole('button', { name: /Three-person dinner.*3 people/ }).click()
  await b.getByRole('button', { name: 'Pay my share' }).click()
  const confirmation = b.getByRole('dialog', { name: 'Confirm split contribution' })
  await confirmation.waitFor()
  assert.ok((await confirmation.textContent()).includes(added.upi_id))
  await shot(b, 'phase8-mobile-share-confirmation', false)
  await confirmation.getByRole('button', { name: 'Confirm and pay share' }).click()
  await approvePayment(b)
  await text(b, 'Simulated payment completed.')
  // The third participant pays from Requests: same obligation, same engine.
  await nav(c, 'Requests')
  await c.getByRole('button', { name: 'Pay request' }).click()
  await c.getByRole('dialog').getByRole('button', { name: 'Confirm and pay request' }).click()
  await approvePayment(c)
  await text(c, 'Simulated payment completed.')
  await nav(a, 'My Splits')
  await a.getByRole('button', { name: /Three-person dinner.*3 people/ }).click()
  detail = a.getByRole('region', { name: 'Split details' })
  await detail.getByText('SETTLED', { exact: true }).waitFor()
  await detail.getByText('₹0.00', { exact: true }).waitFor()
  assert.equal(await detail.getByRole('button', { name: 'Cancel unpaid split' }).count(), 0)
  await shot(a, 'phase8-split-settled')
  await nav(a, 'My Bank Accounts')
  await a.getByRole('button', { name: 'Refresh accounts' }).click()
  await bankBalance(a, 'Grove Demo Bank', '₹300.00')
  await bankBalance(a, 'Orbit Demo Bank', '₹766.66')

  await createExpense(a, 'Renewable contribution', '20.00', [ravi], false)
  await nav(b, 'Profile')
  await b.getByRole('button', { name: 'Money Requests', exact: true }).click()
  await b.getByRole('button', { name: 'Decline request' }).click()
  await b.getByRole('dialog').getByRole('button', { name: 'Confirm decline' }).click()
  await text(b, 'DECLINED')
  await nav(a, 'My Splits')
  await a.getByRole('button', { name: /Renewable contribution.*1 people/ }).click()
  await a.getByRole('button', { name: 'Renew unpaid request' }).click()
  await text(a, 'Unpaid contribution request renewed. The previous request cannot be paid.')
  await createExpense(a, 'Cancelled example', '10.00', [ravi])
  await a.getByRole('button', { name: 'Cancel unpaid split' }).click()
  await a.getByRole('dialog').getByRole('button', { name: 'Confirm split cancellation' }).click()
  await text(a, 'Split cancelled. No payments were erased or refunded.')
  await a.getByRole('region', { name: 'Split details' }).getByText('CANCELLED', { exact: true }).first().waitFor()

  // Set Orbit primary again, then scan Asha's ORIGINAL Grove QR from before account linking.
  await nav(a, 'My Bank Accounts')
  await a.getByRole('button', { name: 'Set as primary account', exact: true }).click()
  await text(a, 'Primary account updated. Existing UPI destinations are unchanged.')
  await nav(b, 'Scan QR')
  await b.getByRole('dialog').getByLabel('Upload QR Image').setInputFiles({ name: 'old-asha.png', mimeType: 'image/png', buffer: oldQr })
  await text(b, 'Verified recipient: Phase8 Asha')
  await b.getByLabel('Amount · INR').fill('1.00')
  await b.getByRole('button', { name: 'Review payment' }).click()
  await b.getByRole('button', { name: 'Confirm and send ₹1.00' }).click()
  await approvePayment(b)
  await text(b, 'Simulated payment completed.')
  await nav(a, 'My Bank Accounts')
  await a.getByRole('button', { name: 'Refresh accounts' }).click()
  await bankBalance(a, 'Grove Demo Bank', '₹301.00')
  await bankBalance(a, 'Orbit Demo Bank', '₹766.66')
  await nav(b, 'Home')
  await bankBalance(b, 'Orbit Demo Bank', '₹965.67')
  await feature(b, 'My Splits')
  await b.getByRole('button', { name: /Three-person dinner.*3 people/ }).click()
  for (const width of [320,390,768,1024,1440]) {
    await b.setViewportSize({ width, height: 900 })
    assert.equal(await b.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `No overflow at ${width}`)
  }
  await b.setViewportSize({ width: 390, height: 844 })
  await shot(b, 'phase8-mobile-split-details')
  for (const page of [a,b,c]) { await page.getByRole('button', { name: 'Log out' }).click(); await page.getByRole('form', { name: 'Sign in' }).waitFor() }
  assert.deepEqual(errors, [])
  console.log('PASS: three real UI users; multiple accounts/primary switches; self-transfer lost-response same-key recovery and total conservation; equal paise split; split-screen and Requests-screen contributions to one settlement; pinned destination after primary switch; decline/renew/cancel; original PNG QR still routes to original account; all balances/history; 320/390/768/1024/1440 layouts; logout; no browser errors.')
} finally { await browser.close() }
