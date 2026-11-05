// Explicit UI steps shared by browser regressions; no backend policy bypass.
export const demoPin = '482951'
export async function approvePayment(page, pin = demoPin) {
  const dialog = page.getByRole('dialog', { name: 'Authorize simulated payment' })
  await dialog.waitFor()
  await dialog.getByLabel('Payment PIN', { exact: true }).fill(pin)
  await dialog.getByRole('button', { name: 'Verify PIN and pay' }).click()
  await dialog.waitFor({ state: 'hidden' })
}

export async function configurePin(page, password) {
  await page.getByRole('navigation').getByRole('button', { name: 'Home', exact: true }).click()
  await page.locator('.secondary-actions').getByRole('button', { name: 'Security Settings', exact: true }).click()
  const form = page.getByRole('form', { name: 'Set Payment PIN' })
  await form.waitFor()
  await form.getByLabel('Account password', { exact: true }).fill(password)
  await form.getByLabel('New payment PIN', { exact: true }).fill(demoPin)
  await form.getByLabel('Confirm payment PIN', { exact: true }).fill(demoPin)
  await form.getByRole('button', { name: 'Set PIN', exact: true }).click()
  await page.getByText('Payment PIN configured.', { exact: true }).waitFor()
  await page.getByRole('navigation').getByRole('button', { name: 'Home', exact: true }).click()
}
