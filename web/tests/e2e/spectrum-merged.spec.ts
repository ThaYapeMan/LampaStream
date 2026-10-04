import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

for (const theme of ['light', 'dark'] as const) for (const width of [1400, 390]) {
  test(`merged Spectrum controls in ${theme} at ${width}px`, async ({ page }) => {
    const timing = { lower_cutoff_freq: 50, higher_cutoff_freq: 6623, bass_hz: 240, mid_hz: 2000,
      music: { genre: 'other', source: 'Track tag', raw_tags: ['Dance / Pop'], album_art_outcome: 'Album art: 3 colours' } }
    const socket = await setupPreview(page, () => timing)
    const changes: boolean[] = []
    await page.route('**/api/analysers/a', async route => {
      expect(route.request().method()).toBe('PATCH')
      const body = route.request().postDataJSON()
      expect(Object.keys(body)).toEqual(['band_normalise'])
      changes.push(body.band_normalise)
      await route.fulfill({ json: { id: 'a', name: 'Custom analyser name', band_normalise: body.band_normalise } })
    })
    await page.setViewportSize({ width, height: 1100 })
    await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click()
    const card = page.getByTestId('spectrum-panel')
    const control = card.getByRole('switch', { name: 'Band normaliser' })
    const disclosure = card.getByRole('button', { name: /Frequency range and bands/ })
    await expect(control).toHaveAttribute('aria-checked', 'true')
    expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
    await expect(disclosure).toContainText('50 Hz – 6.6 kHz · 240 Hz · 2 kHz')
    await expect(card.getByTestId('low-cut-hz')).not.toBeVisible()
    await control.click()
    await expect(control).toBeEnabled()
    await expect(control).toHaveAttribute('aria-checked', 'false')
    await expect(card.getByTestId('spectrum-tick')).toHaveCount(0)
    await expect(card.getByText('· 0.33')).toHaveCount(0)
    await page.screenshot({ path: `test-results/spectrum-merged-${theme}-${width}-collapsed.png`, fullPage: true })
    await control.click()
    await expect(control).toBeEnabled()
    await expect(card.getByTestId('spectrum-tick')).toHaveCount(10)
    await expect(card.getByText('· 0.33')).toHaveCount(3)
    expect(changes).toEqual([false, true])
    await disclosure.click()
    await expect(card.getByTestId('low-cut-hz')).toBeVisible()
    await expect(card.getByTestId('bass-hz')).toBeVisible()
    await expect(card.getByRole('button', { name: 'Apply', exact: true })).toHaveCount(1)
    await expect(card.getByRole('button', { name: 'Reset to saved' })).toHaveCount(1)
    await expect(card.getByRole('button', { name: 'Restore defaults' })).toHaveCount(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const spectrum = (await card.boundingBox())!, colours = (await page.getByTestId('track-colours').boundingBox())!
    expect(colours.y).toBeGreaterThanOrEqual(spectrum.y + spectrum.height)
    await page.screenshot({ path: `test-results/spectrum-merged-${theme}-${width}-expanded.png`, fullPage: true })
    const applied: Record<string, number> = {}
    await page.route('**/api/couplings/c/restart-cava', async route => {
      Object.assign(applied, route.request().postDataJSON())
      await route.fulfill({ json: { ok: true } })
      socket().send(JSON.stringify({ type: 'status', active_coupling_id: 'c', active_player_type: 'LMS', active_energy_profile_id: 'e', processes: { lms_player: true }, ...timing, ...applied }))
    })
    await card.getByTestId('low-cut-hz').fill('100'); await card.getByTestId('low-cut-hz').press('Tab')
    await card.getByTestId('bass-hz').fill('300'); await card.getByTestId('bass-hz').press('Tab')
    await card.getByRole('button', { name: 'Apply', exact: true }).click()
    await expect(card.getByText('Applied.', { exact: true })).toBeVisible()
    expect(applied).toEqual({ lower_cutoff_freq: 100, higher_cutoff_freq: 6623, bass_hz: 300, mid_hz: 2000 })
    await page.reload()
    await expect(page.getByRole('button', { name: /Frequency range and bands/ })).toHaveAttribute('aria-expanded', 'true')
  })
}

test('normaliser error reverts the switch and stopping disables it', async ({ page }) => {
  const socket = await setupPreview(page)
  let requests = 0
  await page.route('**/api/analysers/a', async route => {
    requests++
    await route.fulfill({ status: 500, json: { detail: 'Could not save normaliser' } })
  })
  const control = page.getByRole('switch', { name: 'Band normaliser' })
  await expect(control).toHaveAttribute('aria-checked', 'true')
  await control.click()
  await expect(page.getByRole('alert')).toHaveText('Could not save normaliser')
  await expect(control).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByTestId('spectrum-tick')).toHaveCount(10)
  socket().send(JSON.stringify({ type: 'status', active_coupling_id: null, processes: {} }))
  await expect(control).toBeDisabled()
  await expect(page.getByText('Start a coupling to change this')).toBeVisible()
  expect(requests).toBe(1)
})
