import { configurePin, approvePayment } from './security-helpers.mjs'
// Optional browser harness. Requires Playwright externally; never targets the development API.
import { createRequire } from 'node:module'
import { Buffer } from 'node:buffer'
import process from 'node:process'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const output = path.resolve(process.env.PAYFLOW_SCREENSHOTS || './qa-output')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const errors = []
const password = 'Learning-Phase6-Only!'
const nav = (page, name) => page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name, exact: true }).click()
const shot = (page, name) => page.screenshot({ path: path.join(output, name + '.png'), fullPage: true })

async function waitText(page, value) {
  await page.getByText(value, { exact: true }).first().waitFor({ state: 'visible' })
}
async function createUser(page, name, bank) {
  page.on('pageerror', (error) => errors.push(error.message))
  // Guard this script against accidentally creating persistent development payments.
  await page.route('**/*', async (route) => {
    const request = route.request()
    if (['POST', 'PATCH', 'DELETE'].includes(request.method()) && /\/(register|login|accounts|contacts|payment-requests|splits|security|demo\/fund|payments\/)/.test(request.url())) {
      if (!request.url().startsWith('http://127.0.0.1:18016/')) {
        await route.abort()
        throw new Error('QA must use isolated API :18016; request blocked before sending')
      }
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
  await waitText(page, 'Account created. Sign in to continue.')
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in to PayFlow' }).click()
  await configurePin(page, password)
  await page.getByLabel('Demo bank').selectOption(bank)
  await page.getByRole('button', { name: 'Create demo account', exact: true }).click()
  await page.getByRole('article', { name: 'Simulated bank account' }).waitFor()
  return page.locator('.account-details dd').last().textContent()
}
async function assertLayout(page, width) {
  await page.setViewportSize({ width, height: 900 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `No overflow at ${width}px`)
}
try {
  const aContext = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['clipboard-read', 'clipboard-write'] })
  const bContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  const a = await aContext.newPage()
  const b = await bContext.newPage()
  const aUpi = await createUser(a, 'Asha Browser', 'Grove Demo Bank')
  await shot(a, 'phase6-desktop-home')
  await nav(a, 'My QR')
  const image = a.getByRole('img', { name: 'Your PayFlow sandbox payment QR code' })
  await image.waitFor()
  const png = Buffer.from((await image.getAttribute('src')).split(',')[1], 'base64')
  await a.getByRole('button', { name: 'Copy UPI ID', exact: true }).click()
  assert.equal(await a.evaluate(() => navigator.clipboard.readText()), aUpi)
  const downloadEvent = a.waitForEvent('download')
  await a.getByRole('link', { name: 'Download QR as PNG' }).click()
  const download = await downloadEvent
  const chunks = []
  for await (const chunk of await download.createReadStream()) chunks.push(chunk)
  assert.ok(Buffer.concat(chunks).equals(png))
  await shot(a, 'phase6-my-qr')

  await createUser(b, 'Ravi Browser', 'Orbit Demo Bank')
  await b.getByRole('button', { name: 'Add ₹1,000 demo funds' }).click()
  await waitText(b, 'Simulated funds added successfully.')
  await waitText(b, '₹1,000.00')
  await shot(b, 'phase6-mobile-home')
  for (const width of [320, 390, 768, 1024, 1440]) await assertLayout(b, width)
  await b.setViewportSize({ width: 390, height: 844 })

  let transferRequests = 0
  b.on('request', (request) => { if (request.url().endsWith('/payments/transfer')) transferRequests += 1 })
  await nav(b, 'Send Money')
  assert.equal(await b.getByLabel('Amount · INR').count(), 0)
  await b.getByLabel('Recipient UPI ID').fill(aUpi)
  await b.getByRole('button', { name: 'Verify recipient', exact: true }).click()
  await waitText(b, 'Verified recipient: Asha Browser')
  await b.getByLabel('Amount · INR').fill('30000')
  await b.getByRole('button', { name: 'Review payment' }).click()
  const warning = b.getByText('Insufficient simulated funds. Available balance: ₹1,000.00.', { exact: true })
  await warning.waitFor()
  assert.equal(await warning.evaluate((element) => getComputedStyle(element).color), 'rgb(185, 28, 28)')
  assert.equal(transferRequests, 0)
  await b.getByLabel('Amount · INR').fill('12.30')
  await b.getByLabel('Note · optional').fill('Direct UI check')
  await b.getByRole('button', { name: 'Review payment' }).click()
  await b.getByRole('button', { name: 'Confirm and send ₹12.30' }).waitFor()
  assert.equal(transferRequests, 0)
  await shot(b, 'phase6-mobile-confirm')
  await b.getByRole('button', { name: 'Confirm and send ₹12.30' }).click()
  await approvePayment(b)
  await waitText(b, 'Simulated payment completed.')
  assert.equal(transferRequests, 1)

  await nav(b, 'Scan QR')
  const dialog = b.getByRole('dialog', { name: 'Scan a PayFlow QR' })
  await dialog.waitFor()
  await shot(b, 'phase6-mobile-scan')
  await dialog.getByLabel('Upload QR Image').setInputFiles({ name: 'asha-payflow.png', mimeType: 'image/png', buffer: png })
  await waitText(b, 'Verified recipient: Asha Browser')
  assert.equal(transferRequests, 1)
  await b.getByLabel('Amount · INR').fill('125.50')
  await b.getByRole('button', { name: 'Review payment' }).click()
  assert.equal(transferRequests, 1)
  // Simulate a committed transfer whose HTTP response is lost. Retry must replay its original key.
  let lost = false
  const keys = []
  await b.route('**/payments/transfer', async (route) => {
    keys.push(route.request().headers()['idempotency-key'])
    if (!lost) { lost = true; const response = await route.fetch(); assert.equal(response.status(), 201); await route.abort('failed') }
    else await route.continue()
  })
  await b.getByRole('button', { name: 'Confirm and send ₹125.50' }).click()
  await approvePayment(b)
  await waitText(b, 'Keep this payment request.')
  await nav(b, 'Transactions')
  await nav(b, 'Home')
  await b.getByRole('button', { name: 'Retry same request' }).click()
  await waitText(b, 'Simulated payment completed.')
  assert.equal(keys.length, 2)
  assert.equal(keys[0], keys[1])
  await waitText(b, '₹862.20')
  const receipt = b.getByRole('article', { name: 'Payment receipt' })
  assert.match(await receipt.textContent(), /Transaction ID/)
  await shot(b, 'phase6-mobile-receipt')
  await nav(b, 'Transactions')
  await b.getByLabel('Show transactions').selectOption('OUTGOING')
  assert.equal(await b.locator('.history-list li').count(), 2)
  await shot(b, 'phase6-mobile-history')
  await nav(a, 'Home')
  await a.getByRole('button', { name: 'Refresh accounts' }).click()
  await waitText(a, '₹137.80')
  await nav(a, 'Transactions')
  await a.getByRole('button', { name: 'Refresh history' }).click()
  await a.getByLabel('Show transactions').selectOption('INCOMING')
  await a.locator('.history-list li').nth(1).waitFor()
  await a.locator('.history-list button').first().click()
  await a.getByRole('article', { name: 'Payment receipt' }).waitFor()
  await shot(a, 'phase6-desktop-history')

  // A browser-native blank camera stream verifies track cleanup without physical hardware.
  await b.evaluate(() => {
    window.qaTracks = []
    navigator.mediaDevices.getUserMedia = async () => {
      const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480
      canvas.getContext('2d').fillRect(0, 0, 640, 480)
      const stream = canvas.captureStream(10)
      window.qaCanvas = canvas
      window.qaTracks.push(...stream.getTracks())
      return stream
    }
  })
  await nav(b, 'Scan QR')
  await b.getByRole('button', { name: 'Start camera' }).click()
  await b.waitForFunction(() => window.qaTracks.length > 0)
  for (let i = 0; i < 8; i++) {
    await b.keyboard.press(i % 2 ? 'Shift+Tab' : 'Tab')
    assert.equal(await b.evaluate(() => document.querySelector('dialog').contains(document.activeElement)), true)
  }
  await b.keyboard.press('Escape')
  await b.waitForFunction(() => window.qaTracks.every((track) => track.readyState === 'ended'))
  await b.evaluate(() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError') } })
  await nav(b, 'Scan QR')
  await b.getByRole('button', { name: 'Start camera' }).click()
  await waitText(b, 'Camera permission was denied. Allow access in your browser or upload a QR image.')
  await b.getByRole('button', { name: 'Close QR scanner' }).click()
  await b.emulateMedia({ reducedMotion: 'reduce' })
  assert.equal(await b.locator('.primary-button').first().evaluate((element) => getComputedStyle(element).transitionDuration), '0s')
  await nav(b, 'Profile')
  await waitText(b, 'Ravi Browser')
  await b.getByRole('button', { name: 'Log out' }).click()
  await b.getByRole('form', { name: 'Sign in' }).waitFor()
  assert.equal(await b.getByRole('dialog').count(), 0)
  await a.getByRole('button', { name: 'Log out' }).click()
  await a.getByRole('form', { name: 'Sign in' }).waitFor()
  await shot(a, 'phase6-login')
  assert.deepEqual(errors, [])
  console.log('PASS: registration/login, account creation, funding, direct transfer, real PNG upload/QR transfer, original-key uncertain retry, balances, histories/receipts, copy/download, mobile 320/390/tablet768/desktop1024/1440, red warning, reduced motion, keyboard modal containment, camera denial/cleanup and logout. No browser errors.')
} finally {
  await browser.close()
}
