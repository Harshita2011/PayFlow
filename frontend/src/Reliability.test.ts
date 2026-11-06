import { afterEach, expect, it, vi } from 'vitest'
import { apiRequest } from './api'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('bounds a stalled request and reports an uncertain payment outcome', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn((_url, options: RequestInit) => new Promise((_resolve,reject) => {
    options.signal!.addEventListener('abort', () => reject(new DOMException('Aborted','AbortError')))
  })))
  const pending = apiRequest('/payments/transfer', { method:'POST' })
  const assertion = expect(pending).rejects.toMatchObject({ status:0, message:expect.stringContaining('recover the original request') })
  await vi.advanceTimersByTimeAsync(10001)
  await assertion
})

it('does not interpret an interrupted successful response body as a committed receipt', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok:true, status:201, json:async () => { throw new Error('connection lost') } }))
  await expect(apiRequest('/payments/transfer')).rejects.toMatchObject({ status:0, message:expect.stringContaining('keep the original request') })
})

it('honors caller cancellation without retrying a POST', async () => {
  const controller = new AbortController()
  const fetchMock = vi.fn((_url, options: RequestInit) => new Promise((_resolve,reject) => {
    options.signal!.addEventListener('abort', () => reject(new DOMException('Aborted','AbortError')))
  }))
  vi.stubGlobal('fetch', fetchMock)
  const pending = apiRequest('/payments/transfer',{ method:'POST',signal:controller.signal })
  controller.abort()
  await expect(pending).rejects.toMatchObject({ status:0 })
  expect(fetchMock).toHaveBeenCalledTimes(1)
})
