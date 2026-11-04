import { describe, expect, it } from 'vitest'
import QRCode from 'qrcode'
import { BinaryBitmap, HybridBinarizer, QRCodeReader, RGBLuminanceSource } from '@zxing/library'
import { createQrPayload, MAX_QR_PAYLOAD_LENGTH, parseQrPayload } from './qrPayload'

describe('PayFlow QR format', () => {
  it('encodes only a version and public recipient ID', () => {
    const payload = createQrPayload('alex-123abc@payflow')
    expect(payload).toBe('payflow://pay?v=1&upi=alex-123abc%40payflow')
    expect(Array.from(new URL(payload).searchParams.keys())).toEqual(['v', 'upi'])
    expect(parseQrPayload(payload)).toBe('alex-123abc@payflow')
  })

  it('round-trips an actual generated QR matrix through the real ZXing decoder', () => {
    const payload = createQrPayload('recipient-123abc@payflow')
    const { modules } = QRCode.create(payload, { errorCorrectionLevel: 'M' })
    const scale = 6
    const size = (modules.size + 8) * scale
    const pixels = new Uint8ClampedArray(size * size).fill(255)
    for (let y = 0; y < modules.size; y++) for (let x = 0; x < modules.size; x++) {
      if (!modules.get(y, x)) continue
      for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) {
        pixels[((y + 4) * scale + dy) * size + (x + 4) * scale + dx] = 0
      }
    }
    const bitmap = new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(pixels, size, size)))
    expect(new QRCodeReader().decode(bitmap).getText()).toBe(payload)
  })

  it.each([
    'https://attacker.example/pay', 'upi://pay?pa=name@bank', 'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>', '', 'payflow://pay',
    'payflow://pay?v=1&upi=alex@payflow', 'payflow://pay?v=1&upi=Alex%40payflow',
    'payflow://pay?v=1&upi=alex%40other', 'payflow://pay?v=1&upi=alex%2540payflow',
    'payflow://pay?v=1&upi=%61lex%40payflow', 'payflow://pay?upi=alex%40payflow&v=1',
    'payflow://pay?v=1&upi=alex%40payflow&amount=125.50',
    'payflow://pay?v=1&upi=alex%40payflow&name=Trusted',
    'payflow://pay?v=1&upi=alex%40payflow&v=1',
    'payflow://pay?v=1&upi=alex%40payflow&upi=other%40payflow',
    'payflow://user@pay?v=1&upi=alex%40payflow',
    'payflow://pay/?v=1&upi=alex%40payflow', 'payflow://pay:80?v=1&upi=alex%40payflow',
    'payflow://pay?v=1&upi=alex%40payflow#fragment',
    ' payflow://pay?v=1&upi=alex%40payflow',
    'payflow://pay?v=1&upi=alex%40payflow\n',
  ])('rejects noncanonical or unsafe content: %s', (value) => {
    expect(() => parseQrPayload(value)).toThrow()
  })

  it.each(['0', '2', '01', '999'])('rejects unsupported version %s', (version) => {
    expect(() => parseQrPayload(`payflow://pay?v=${version}&upi=alex%40payflow`)).toThrow(/version/)
  })

  it('rejects oversized contents before parsing and rejects self-payments', () => {
    expect(() => parseQrPayload('x'.repeat(MAX_QR_PAYLOAD_LENGTH + 1))).toThrow(/large/)
    expect(() => parseQrPayload(createQrPayload('self@payflow'), 'self@payflow')).toThrow(/yourself/)
    expect(() => createQrPayload('not-an-id')).toThrow()
    expect(() => createQrPayload('UPPER@payflow')).toThrow()
  })
})
