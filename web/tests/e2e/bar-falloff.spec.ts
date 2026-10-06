import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

for (const theme of ['light', 'dark'] as const) for (const width of [1400, 390]) {
  test(`bar falloff response in ${theme} at ${width}px`, async ({ page }) => {
    await setupPreview(page, () => ({ lower_cutoff_freq: 50, higher_cutoff_freq: 12000, bass_hz: 250, mid_hz: 2000 }))
    let saved = .6
    await page.route('**/api/analysers', route => route.fulfill({ json: [{ id: 'a', name: 'Response', spectrum_backend: 'v2', bar_falloff_s: saved }] }))
    const requests: unknown[] = []
    await page.route('**/api/couplings/c/restart-cava', async route => {
      const body = route.request().postDataJSON(); requests.push(body); saved = body.bar_falloff_s
      await route.fulfill({ json: { ok: true } })
    })
    await page.reload(); await page.setViewportSize({ width, height: 1100 })
    await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click()
    const card = page.getByTestId('spectrum-panel'), disclosure = card.getByRole('button', { name: /Frequency range and bands/ })
    await expect(disclosure).toContainText('falloff 0.60 s'); await disclosure.click()
    const input = card.getByTestId('bar-falloff-seconds'), slider = card.getByRole('slider', { name: 'Bar falloff' })
    await expect(input).toHaveValue('0.60'); await slider.focus(); await page.keyboard.press('ArrowLeft')
    await expect(input).toHaveValue('0.59')
    await card.getByTestId('reset-cutoffs').click(); await expect(input).toHaveValue('0.60')
    await card.getByTestId('restore-defaults-cutoffs').click(); await expect(input).toHaveValue('0.30')
    await input.fill('0.10'); await input.press('Tab'); await expect(slider).toHaveAttribute('aria-valuenow', '0.1')
    expect((await input.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    for (const id of ['apply-cutoffs', 'reset-cutoffs', 'restore-defaults-cutoffs'])
      expect((await card.getByTestId(id).boundingBox())!.height).toBeGreaterThanOrEqual(44)
    expect((await card.getByTestId('bar-falloff-slider').boundingBox())!.height).toBeGreaterThanOrEqual(44)
    expect(await card.evaluate(el => {
      const bounds = el.getBoundingClientRect()
      return [...el.querySelectorAll('input, button, [data-testid="bar-falloff-slider"]')]
        .filter(child => child.getBoundingClientRect().width > 0)
        .every(child => { const box = child.getBoundingClientRect(); return box.left >= bounds.left && box.right <= bounds.right })
    })).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/bar-falloff-${theme}-${width}.png`, fullPage: true })
    await card.getByTestId('apply-cutoffs').click(); await expect(card.getByText('Applied.', { exact: true })).toBeVisible()
    expect(requests).toEqual([{ bar_falloff_s: .1 }]); await expect(card.getByTestId('reset-cutoffs')).toBeDisabled()
    await disclosure.click(); await expect(disclosure).toContainText('falloff 0.10 s')
    await page.reload(); await expect(disclosure).toContainText('falloff 0.10 s')
  })
}

test('CAVA Core shows saved falloff with a disabled response control', async ({ page }) => {
  await setupPreview(page)
  await page.route('**/api/analysers', route => route.fulfill({ json: [{ id: 'a', spectrum_backend: 'cavacore', bar_falloff_s: .8 }] }))
  await page.reload(); await page.getByRole('button', { name: /Frequency range and bands/ }).click()
  await expect(page.getByTestId('bar-falloff-seconds')).toBeDisabled()
  await expect(page.getByTestId('bar-falloff-seconds')).toHaveValue('0.80')
  await expect(page.getByRole('slider', { name: 'Bar falloff' })).toHaveAttribute('data-disabled')
  await expect(page.getByText('V2 only; CAVA Core uses its own bar falloff.')).toBeVisible()
  await page.getByTestId('restore-defaults-cutoffs').click()
  await expect(page.getByTestId('bar-falloff-seconds')).toHaveValue('0.30')
  await expect(page.getByTestId('apply-cutoffs')).toBeEnabled()
})
