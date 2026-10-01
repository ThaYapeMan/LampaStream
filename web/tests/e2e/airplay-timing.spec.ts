import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('AirPlay timing states, fine-tune, Auto and Latency processing status', async ({ page }) => {
  let state = 'stable', strategy = 'auto', trim = 0
  const entry = () => ({ player_mac: 'airplay', name: 'AirPlay receiver', strategy,
    fixed_delay_ms: 200, trim_ms: trim, measured_delay_ms: 375, measured_at: 100,
    status: { source: 'airplay', state, strategy, applied_delay_ms: 375, early_delivery_ms: 500,
      median_processing_ms: 125, sample_count: 7, precision_ms: 5, samples: [],
      reason: state === 'not measurable' ? 'Audio delivery stalled' : null } })
  const socket = await setupPreview(page)
  const send = () => socket().send(JSON.stringify({ type: 'status', active_player_type: 'AirPlay',
    active_coupling_id: 'c', processes: {}, applied_delay_ms: 375, airplay_receiving: true,
    timing_player_mac: 'airplay', timing_player_name: 'AirPlay receiver', light_timing: entry(),
    track: { playing: false } }))
  await page.route('**/api/player-latencies', route => route.fulfill({ json: [entry()] }))
  await page.route('**/api/player-latencies/airplay', route => {
    const body = route.request().postDataJSON()
    if (body.trim_ms !== undefined) trim = body.trim_ms
    if (body.strategy) { strategy = body.strategy; state = 'measuring' }
    send()
    return route.fulfill({ json: entry() })
  })
  send()
  const card = page.getByTestId('light-timing')
  await expect(card.getByText('In sync', { exact: true })).toBeVisible()
  await expect(card.getByText('Lights wait M−P so they land on the beat for the AirPlay group.')).toBeVisible()
  await card.getByText('Details', { exact: true }).click()
  await expect(card.getByText('Early delivery (M)')).toBeVisible()
  await expect(card.getByText('Processing (P)')).toBeVisible()
  await card.getByRole('button', { name: 'Lights 10 milliseconds earlier' }).click()
  await expect(card.getByText('Saved · lights earlier by 10 ms')).toBeVisible()
  for (const [next, label] of [['measuring', 'Measuring'], ['idle', 'Paused'], ['not measurable', 'Can’t measure']]) {
    state = next; send()
    await expect(card.getByText(label, { exact: true })).toBeVisible()
  }
  await expect(card.getByText(/Audio delivery stalled/)).toBeVisible()
  strategy = 'fixed'; state = 'idle'; send()
  await expect(card.getByText('Fixed', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: 'Measure automatically' }).click()
  await expect(card.getByText('Measuring', { exact: true })).toBeVisible()
  expect(strategy).toBe('auto')
  await card.getByRole('link', { name: 'Player settings' }).click()
  await expect(page.getByRole('heading', { name: 'Players', exact: true })).toBeVisible()
  await expect(page.getByRole('listbox', { name: 'Players', exact: true }).getByRole('option', { selected: true })).toContainText('AirPlay receiver')
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(page.getByText('Fixed delay (fallback)')).toBeVisible()
})
