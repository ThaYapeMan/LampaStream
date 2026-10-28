import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('Accent mode, amount and advanced controls PATCH and persist; live envelopes display', async ({ page }) => {
  const socket = await setupPreview(page)
  let effect = { id: 'low', name: 'Accent test', effect_type: 'solid', accent_mode: 'lift', accent_amount: .35,
    accent_band_weights: { bass: 1, mid: .6, treble: .4 }, accent_spatial: 'uniform', accent_palette_step: .1 }
  await page.route('**/api/effects', route => route.fulfill({ json: [effect] }))
  await page.route('**/api/energy-profiles', route => route.fulfill({ json: [
    { id: 'e', name: 'Trigger', energy_source: 'off', low_energy_effect_id: 'low', high_energy_effect_id: 'low' },
  ] }))
  await page.route('**/api/effects/low', route => {
    expect(route.request().method()).toBe('PATCH')
    effect = { ...effect, ...route.request().postDataJSON() }
    return route.fulfill({ json: effect })
  })
  await page.reload()
  await expect(page.getByRole('link', { name: 'Accent test', exact: true }).first()).toBeVisible()
  socket().send(JSON.stringify({ type: 'frame', colour: { r: 0, g: 0, b: 0 },
    onset_envelope: .8, onset_envelope_bass: .7, onset_envelope_mid: .4, onset_envelope_treble: .2, accent_value: .28 }))
  await expect(page.getByRole('meter', { name: 'bass envelope', exact: true })).toHaveAttribute('value', '0.7')
  await expect(page.getByTestId('accent-value')).toHaveText('0.28')
  await page.getByRole('link', { name: 'Accent test', exact: true }).first().click()
  await page.getByText('Advanced', { exact: true }).click()
  await page.getByLabel('Accent mode', { exact: true }).selectOption('palette_step')
  await page.getByLabel('Accent palette step', { exact: true }).fill('0.2')
  await page.getByLabel('Accent amount', { exact: true }).fill('0.55')
  await page.getByLabel('Accent spatial', { exact: true }).selectOption('by_band')
  await page.getByLabel('Onset hold', { exact: true }).fill('0.1')
  await page.getByLabel('Accent strength curve', { exact: true }).fill('1.5')
  await page.getByLabel('Onset lead', { exact: true }).fill('0.05')
  await page.getByLabel('Onset maximum age', { exact: true }).fill('0.7')
  await page.getByLabel('Predicted beats', { exact: true }).uncheck()
  const patch = page.waitForRequest(r => r.url().endsWith('/api/effects/low') && r.method() === 'PATCH')
  await page.getByTestId('editor-save').click()
  expect((await patch).postDataJSON()).toMatchObject({ accent_mode: 'palette_step', accent_amount: .55,
    accent_palette_step: .2, accent_spatial: 'by_band', onset_hold_s: .1,
    accent_strength_curve: 1.5, onset_lead_s: .05, onset_max_age_s: .7, beat_predicted: false })
  await page.getByRole('button', { name: 'Now Playing', exact: true }).click()
  await page.getByRole('link', { name: 'Accent test', exact: true }).first().click()
  await page.getByText('Advanced', { exact: true }).click()
  await expect(page.getByLabel('Accent mode', { exact: true })).toHaveValue('palette_step')
  await expect(page.getByLabel('Accent amount', { exact: true })).toHaveValue('0.55')
  await expect(page.getByLabel('Accent palette step', { exact: true })).toHaveValue('0.2')
})
