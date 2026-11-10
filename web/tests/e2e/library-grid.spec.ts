import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('library grid keeps the track layout and exposes timing diagnostics', async ({ page }) => {
  const socket = await setupPreview(page, () => ({
    track: { title: 'Just A Little Bit More (Extended Mix)', artist: 'Mau P',
      position_s: 208, duration_s: 381.222, playing: true },
    beat_source: 'grid', tempo_bpm: 128, tempo_locked: true, grid_confidence: .94,
    grid_tempo: 128, grid_cache: 'hit', grid_fetch_state: 'ready',
  }))
  await expect(page.getByTestId('track-tempo')).toHaveText('grid 128 BPM')
  const disclosure = page.getByRole('button', { name: 'Light timing', exact: true })
  if (await disclosure.getAttribute('aria-expanded') === 'false') await disclosure.click()
  await page.getByText('Details', { exact: true }).click()
  await expect(page.getByText('Grid confidence', { exact: true })).toBeVisible()
  await expect(page.getByText('94%', { exact: true })).toBeVisible()
  await page.screenshot({ path: '../.test-cache/grid-01/now-playing-grid.png', fullPage: true })
  socket().send(JSON.stringify({ type: 'frame', beat_source: 'tracker', tempo_bpm: 128,
    grid_confidence: null, grid_dropped_reason: 'audio contradicts grid',
    colour: { r: 0, g: 0, b: 0 }, channel_colours: [] }))
  await expect(page.getByTestId('track-tempo')).toHaveText('measured 128 BPM')
  await expect(page.getByText('audio contradicts grid', { exact: true })).toBeVisible()
})

test('Onset keeps the file grid tempo while diagnostics name the onset source', async ({ page }) => {
  await setupPreview(page, () => ({ beat_accent_mode: 'onset', beat_source: 'onset',
    grid_tempo: 127.95, grid_confidence: .89, provisional: true, tempo_bpm: null }))
  await expect(page.getByTestId('track-tempo')).toHaveText('grid 128 BPM')
  const disclosure = page.getByRole('button', { name: 'Light timing', exact: true })
  if (await disclosure.getAttribute('aria-expanded') === 'false') await disclosure.click()
  await page.getByText('Details', { exact: true }).click()
  const diagnostics = page.getByTestId('light-timing').locator('dl')
  await expect(diagnostics.getByText('onset', { exact: true })).toBeVisible()
})

for (const width of [1920, 1400, 1024]) {
  test(`desktop header contains version and appearance at ${width}px while scrolling`, async ({ page }) => {
    await setupPreview(page, () => ({ version: '0.2.0+grid-sb2' }))
    await page.setViewportSize({ width, height: 1000 })
    const header = page.locator('header')
    await expect(header.getByText('0.2.0+grid-sb2', { exact: true })).toBeVisible()
    await expect(header.getByRole('group', { name: 'Appearance' })).toBeVisible()
    const before = await header.boundingBox()
    await page.getByTestId('spectrum-panel').scrollIntoViewIfNeeded()
    expect((await header.boundingBox())?.y).toBe(before?.y)
    await page.evaluate(() => window.scrollTo(0, 0))
    if (width !== 1024) {
      await page.screenshot({ path: `../.test-cache/grid-01-sendback-2/header-${width}.png`,
        clip: { x: 0, y: 0, width: 1000, height: 160 } })
    }
    await page.setViewportSize({ width: 900, height: 1000 })
    await expect(header.getByRole('group', { name: 'Appearance' })).toHaveCount(0)
    await expect(page.locator('nav').getByRole('group', { name: 'Appearance' })).toBeVisible()
  })
}
