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
