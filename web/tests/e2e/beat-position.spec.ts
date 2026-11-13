import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('expert musical position stays next to the grid tempo', async ({ page }) => {
  await setupPreview(page, () => ({
    tempo_bpm: 128, tempo_locked: true, tempo_confidence: .5,
    grid_tempo: 128, grid_confidence: .5, beat_source: 'grid',
    beat_position: { tempo: 128, beat_phase: .63, beat_index: 174,
      bar_phase: .16, bar_index: 43, confidence: .5, source: 'grid',
      beats_per_bar: 4, downbeat_measured: false },
  }))
  await page.getByLabel('Editor mode').selectOption('expert')
  const line = page.getByTestId('beat-position')
  await expect(line).toContainText('grid 128 BPM · beat 174 · bar 43.1')
  await line.scrollIntoViewIfNeeded()
  await page.getByTestId('tempo').screenshot({ path: '../.test-cache/beat-02-beat-position/expert-line.png' })
})
