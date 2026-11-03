import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import AccountPanel from './AccountPanel'

const banks = ['Grove Demo Bank', 'Orbit Demo Bank', 'River Demo Bank']
const account = {
  id: 3, bank_name: banks[0], masked_account_number: 'SIM •••• •••• •••• 1234',
  upi_id: 'learner-123abc@payflow', balance: '0.00', created_at: '2026-11-03T10:00:00Z',
}
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { 'Content-Type': 'application/json' },
})

function setupFetch(accountHandler: (options?: RequestInit) => Promise<Response>) {
  const mock = vi.fn((url: string, options?: RequestInit) => {
    if (url.includes('/payments/history')) return Promise.resolve(json({ items: [], next_cursor: null }))
    if (url.endsWith('/accounts/banks')) return Promise.resolve(json(banks))
    return accountHandler(options)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

describe('Simulated bank accounts', () => {
  it('loads the empty state and bank choices', async () => {
    const fetchMock = setupFetch(async () => json([]))
    render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    await screen.findByText(/No demo account yet/)
    expect(screen.getAllByRole('option')).toHaveLength(4)
    expect(fetchMock.mock.calls[0][1]?.headers).toEqual({
      'Content-Type': 'application/json', Authorization: 'Bearer test-token',
    })
  })

  it('shows a loading state without premature creation controls', () => {
    setupFetch(() => new Promise(() => {}))
    render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    expect(screen.getByRole('status').textContent).toBe('Loading your account…')
    expect(screen.queryByRole('button', { name: 'Create demo account' })).toBeNull()
  })

  it('displays the masked number, UPI ID and exact decimal string', async () => {
    setupFetch(async () => json([{ ...account, balance: '12345678901234.56' }]))
    render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    await screen.findByRole('article', { name: 'Simulated bank account' })
    expect(screen.getByText('₹12345678901234.56')).toBeTruthy()
    expect(screen.getByText(account.masked_account_number)).toBeTruthy()
    expect(screen.getByText(account.upi_id)).toBeTruthy()
    expect(screen.getByText(/Fictional funds/)).toBeTruthy()
    expect(screen.queryByRole('form', { name: 'Create simulated bank account' })).toBeNull()
  })

  it('creates an account using only the bank selection and displays zero funds', async () => {
    const fetchMock = setupFetch(async (options) => options?.method === 'POST' ? json(account, 201) : json([]))
    render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    await screen.findByLabelText('Demo bank')
    fireEvent.change(screen.getByLabelText('Demo bank'), { target: { value: banks[0] } })
    fireEvent.submit(screen.getByRole('form', { name: 'Create simulated bank account' }))
    await screen.findByText('Your simulated account and UPI ID are ready.')
    expect(screen.getByText('₹0.00')).toBeTruthy()
    const request = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST')!
    expect(JSON.parse(String(request[1]?.body))).toEqual({ bank_name: banks[0] })
    expect(screen.queryByRole('form', { name: 'Create simulated bank account' })).toBeNull()
  })

  it('rejects an empty bank choice before submitting', async () => {
    const fetchMock = setupFetch(async () => json([]))
    render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    await screen.findByRole('form')
    fireEvent.submit(screen.getByRole('form'))
    expect(screen.getByRole('alert').textContent).toContain('Choose a demo bank.')
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0)
  })

  it('disables submissions while creating and prevents duplicate requests', async () => {
    let resolve!: (value: Response) => void
    const fetchMock = setupFetch(async (options) => options?.method === 'POST'
      ? new Promise((done) => { resolve = done }) : json([]))
    render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    await screen.findByLabelText('Demo bank')
    fireEvent.change(screen.getByLabelText('Demo bank'), { target: { value: banks[0] } })
    const form = screen.getByRole('form')
    fireEvent.submit(form)
    expect(screen.getByRole('button', { name: /Creating demo account/ }).closest('fieldset')?.disabled).toBe(true)
    fireEvent.submit(form)
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
    await act(async () => { resolve(json(account, 201)) })
    await screen.findByText(account.upi_id)
  })

  it('handles duplicate creation and lets the user reload an existing account', async () => {
    let alreadyCreated = false
    setupFetch(async (options) => {
      if (options?.method === 'POST') {
        alreadyCreated = true
        return json({ detail: 'You already have a simulated account' }, 409)
      }
      return json(alreadyCreated ? [account] : [])
    })
    render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    await screen.findByLabelText('Demo bank')
    fireEvent.change(screen.getByLabelText('Demo bank'), { target: { value: banks[0] } })
    fireEvent.submit(screen.getByRole('form'))
    expect((await screen.findByRole('alert')).textContent).toContain('You already have a simulated account')
    fireEvent.click(screen.getByRole('button', { name: 'Refresh accounts' }))
    await screen.findByText(account.upi_id)
  })

  it('shows read errors and recovers on refresh', async () => {
    let fail = true
    setupFetch(async () => { if (fail) throw new TypeError('Network failed'); return json([]) })
    render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    expect((await screen.findByRole('alert')).textContent).toContain('Could not reach PayFlow')
    expect(screen.queryByRole('form')).toBeNull()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Refresh accounts' }))
    await screen.findByText(/No demo account yet/)
  })

  it('shows creation failures and reenables the form', async () => {
    setupFetch(async (options) => options?.method === 'POST'
      ? json({ detail: 'Database unavailable' }, 503) : json([]))
    render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    await screen.findByLabelText('Demo bank')
    fireEvent.change(screen.getByLabelText('Demo bank'), { target: { value: banks[0] } })
    fireEvent.submit(screen.getByRole('form'))
    expect((await screen.findByRole('alert')).textContent).toContain('Database unavailable')
    await waitFor(() => expect(screen.getByLabelText('Demo bank').closest('fieldset')?.disabled).toBe(false))
  })

  it('logs out on rejected authorization', async () => {
    const logout = vi.fn()
    setupFetch(async () => json({ detail: 'Invalid or expired access token' }, 401))
    render(<AccountPanel token="test-token" onLogout={logout} />)
    await waitFor(() => expect(logout).toHaveBeenCalledWith('Your session has expired. Please sign in again.'))
  })

  it('ignores a creation response after the component unmounts at logout', async () => {
    let resolve!: (value: Response) => void
    setupFetch(async (options) => options?.method === 'POST'
      ? new Promise((done) => { resolve = done }) : json([]))
    const view = render(<AccountPanel token="test-token" onLogout={vi.fn()} />)
    await screen.findByLabelText('Demo bank')
    fireEvent.change(screen.getByLabelText('Demo bank'), { target: { value: banks[0] } })
    fireEvent.submit(screen.getByRole('form'))
    view.unmount()
    await act(async () => { resolve(json(account, 201)) })
    expect(screen.queryByText(account.upi_id)).toBeNull()
  })
})
