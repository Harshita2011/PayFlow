// Managed runs retain only redacted diagnostics and synthetic-account screenshots.
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'

export const UI_URL = process.env.PAYFLOW_E2E_FRONTEND_URL || 'http://127.0.0.1:5173'
const registry = []
const trace = []

export async function launchBrowser(chromium) {
  const browser = await chromium.launch({ headless: true })
  if (process.env.PAYFLOW_E2E_MANAGED !== '1') return browser
  const close = browser.close.bind(browser)
  registry.push({ browser, close })
  browser.close = async () => {} // The scenario supervisor captures failures before final cleanup.
  const newContext = browser.newContext.bind(browser)
  browser.newContext = async (...args) => {
    const context = await newContext(...args)
    context.on('page', page => {
      page.on('response', response => {
        if (trace.length >= 2000) return
        const url = new URL(response.url())
        if (!['127.0.0.1', 'localhost'].includes(url.hostname)) return
        trace.push({ at: Date.now(), method: response.request().method(), status: response.status(),
          route: url.pathname.replace(/[a-f0-9]{8}-[a-f0-9-]{27,}/gi, ':id').replace(/\/\d+(?=\/|$)/g, '/:id') })
      })
    })
    return context
  }
  return browser
}

export async function finishScenario(failed) {
  const output = path.resolve(process.env.PAYFLOW_SCREENSHOTS || './test-artifacts/e2e')
  await mkdir(output, { recursive: true })
  await writeFile(path.join(output, 'redacted-trace.json'), JSON.stringify({ failed, requests: trace }, null, 2))
  let index = 0
  for (const { browser, close } of registry) {
    if (failed) for (const context of browser.contexts()) for (const page of context.pages()) {
      if (!page.isClosed()) await page.screenshot({ path: path.join(output, `failure-${index++}.png`),
        fullPage: true, mask: [page.locator('input')] }).catch(() => {})
    }
    await close()
  }
}
