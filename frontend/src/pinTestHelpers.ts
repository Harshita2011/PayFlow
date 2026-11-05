import { fireEvent, screen, waitFor } from '@testing-library/react'

// Legacy flow tests now explicitly fill the real PIN dialog. Only HTTP is mocked,
// just as the surrounding payment tests mock their transfer endpoint.
export async function approvePin() {
  await screen.findByRole('dialog', { name: 'Authorize simulated payment' })
  const original = globalThis.fetch
  globalThis.fetch = async (input, options) => String(input).endsWith('/security/payment-authorizations')
    ? new Response(JSON.stringify({ authorization_token: 'test-one-payment-grant', expires_at: '2099-01-01T00:00:00Z' }), { status: 201 })
    : original(input, options)
  try {
    fireEvent.change(screen.getByLabelText('Payment PIN', { exact: true }), { target: { value: '482951' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Payment PIN authorization' }))
    await waitFor(() => { if (screen.queryByRole('dialog', { name: 'Authorize simulated payment' })) throw new Error('PIN dialog still open') })
  } finally { globalThis.fetch = original }
}
