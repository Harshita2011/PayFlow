import { expect, it } from 'vitest'
import { validateApiBase } from './apiConfiguration'

it('supports the isolated same-origin Docker proxy', () => {
  expect(validateApiBase('/api')).toBe('/api')
})
it('preserves local developer API origins', () => {
  expect(validateApiBase('http://localhost:8001/')).toBe('http://localhost:8001')
})
it('requires an external HTTPS API for hosted frontend builds', () => {
  expect(validateApiBase('https://api.example.com', true)).toBe('https://api.example.com')
  for (const value of ['/api', 'http://localhost:8001', 'https://localhost:8001']) expect(() => validateApiBase(value, true)).toThrow()
})
it('rejects insecure external URLs and non-HTTP protocols', () => {
  for (const value of ['http://api.example.com', 'javascript:alert(1)', '//api.example.com']) expect(() => validateApiBase(value)).toThrow()
})
it('prevents credentials and tokens being baked into API URLs', () => {
  for (const value of ['https://user:password@api.example.com', 'https://api.example.com?token=example', 'https://api.example.com#token']) expect(() => validateApiBase(value)).toThrow()
})
