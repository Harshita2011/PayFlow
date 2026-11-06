import { finishScenario } from './browser-support.mjs'
import process from 'node:process'

let failed = false
try {
  const allowed = ['phase6-browser.mjs', 'phase7-browser.mjs', 'phase8-browser.mjs', 'phase9-browser.mjs', 'security-browser.mjs']
  if (!allowed.includes(process.argv[2])) throw new Error('Unsupported isolated scenario')
  await import(`./${process.argv[2]}`)
} catch (error) {
  failed = true
  console.error('Browser scenario failed:', process.argv[2], error instanceof Error ? error.name : 'UnknownError')
} finally {
  await finishScenario(failed)
}
process.exitCode = failed ? 1 : 0
