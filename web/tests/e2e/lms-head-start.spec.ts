import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

for (const theme of ['light', 'dark'] as const) for (const width of [1400, 390]) {
  test(`LMS editor and scheduled/fallback/follow timing in ${theme} at ${width}px`, async ({ page }) => {
    const timing = { state: 'scheduled', audio_source: 'LMS head start', reason: null, lead_p5_ms: 486, median_processing_ms: 19,
      synced_player_name: 'Radio Red', precision_ms: 1.2, sample_count: 211, last_sample_time: 123,
      median_residual_ms: .1, samples: [{ residual_ms: .1, timestamp: 123 }] }
    const entry = { player_mac: 'speaker', name: 'Radio', strategy: 'auto', trim_ms: 0, fixed_delay_ms: 0,
      status: { state: 'not measurable (sync group)', strategy: 'auto', applied_delay_ms: 467, sample_count: 0 } }
    const socket = await setupPreview(page, () => ({ follow_mode: 'sync_group', timing_player_mac: 'speaker',
      timing_player_name: 'Radio', light_timing: entry, lms_timing: timing }))
    await page.setViewportSize({ width, height: 1100 })
    await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click()
    let player = { id: 'p', type: 'LMS', player_name: 'LampaStream', player_mac: '02:ff:01:02:03:04',
      lms_host: 'lms.local', lms_port: 3483, follow_mode: 'sync_group', follow_player_mac: '', head_start_ms: 500, speaker_output_delay_ms: 0 }
    await page.route('**/api/virtual-players', route => route.fulfill({ json: [player] }))
    await page.route('**/api/player-latencies', route => route.fulfill({ json: [entry] }))
    await page.route('**/api/virtual-players/p', route => {
      player = { ...player, ...route.request().postDataJSON() }
      return route.fulfill({ json: player })
    })
    await page.goto('/players')
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('spinbutton', { name: 'Head start', exact: true })).toHaveValue('500')
    await expect(dialog.getByRole('spinbutton', { name: 'Speaker output delay', exact: true })).toHaveValue('0')
    await dialog.getByRole('button', { name: 'Increase Head start' }).click()
    await dialog.getByRole('button', { name: 'Increase Speaker output delay' }).click()
    await page.screenshot({ path: `test-results/lms-head-start-${theme}-${width}.png`, fullPage: true })
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(player.head_start_ms).toBe(510)
    expect(player.speaker_output_delay_ms).toBe(1)
    await page.goto('/now-playing')
    await expect(page.getByText('Scheduled · LMS head start')).toBeVisible()
    await expect(page.getByTestId('lms-timing')).toHaveText('Head start 486 ms · processing 19 ms · fine-tune +0 ms')
    const update = (state: string, reason: string) => socket().send(JSON.stringify({ type: 'status', active_coupling_id: 'c',
      active_player_type: 'LMS', follow_mode: state === 'unavailable' ? 'manual' : 'sync_group', processes: {},
      timing_player_mac: 'speaker', light_timing: entry, lms_timing: { ...timing, state, reason } }))
    await expect(page.getByText('Steady to within ±1.2 ms')).toBeVisible()
    await expect(page.getByText(/211 measurements/)).toBeVisible()
    await expect(page.getByText('Lights follow measured LMS play times for Radio Red.')).toBeVisible()
    update('waiting', 'Waiting for the virtual player in LMS')
    await expect(page.getByTestId('lms-timing')).toHaveText('Waiting for the virtual player in LMS')
    update('unsynced', 'Not synced with a speaker yet: sync it in LMS')
    await expect(page.getByTestId('lms-timing')).toHaveText('Not synced with a speaker yet: sync it in LMS')
    update('fallback', 'Not enough head start, using delay instead')
    await expect(page.getByTestId('lms-timing')).toHaveText('Not enough head start, using delay instead')
    update('unavailable', 'Head start needs sync-group mode')
    await expect(page.getByTestId('lms-timing')).toHaveText('Head start needs sync-group mode')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}
