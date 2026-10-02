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
  await expect(card.getByText('Lights follow measured audio play times for the AirPlay group.')).toBeVisible()
  await card.getByText('Details', { exact: true }).click()
  await expect(card.getByText('Measured early arrival (p5)')).toBeVisible()
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

test('receiver defaults show measured lag and one-shot recovery on both timing views', async ({ page }) => {
  const entry = { player_mac: 'airplay', name: 'AirPlay receiver', strategy: 'auto', fixed_delay_ms: 0,
    trim_ms: 0, measured_delay_ms: 0, status: { source: 'airplay', state: 'lagging', strategy: 'auto',
      applied_delay_ms: 0, early_delivery_ms: 0, median_processing_ms: 125, lag_ms: 125,
      sample_count: 7, precision_ms: 3, samples: [],
      safety_message: 'Early delivery was too much for this sender and has been switched off' } }
  const socket = await setupPreview(page)
  await page.route('**/api/player-latencies', route => route.fulfill({ json: [entry] }))
  await page.route('**/api/virtual-players', route => route.fulfill({ json: [
    { id: 'ap', type: 'AirPlay', player_mac: 'airplay', player_name: 'AirPlay receiver' },
  ] }))
  socket().send(JSON.stringify({ type: 'status', active_player_type: 'AirPlay', active_coupling_id: 'c',
    processes: {}, applied_delay_ms: 0, airplay_receiving: true, timing_player_mac: 'airplay',
    timing_player_name: 'AirPlay receiver', light_timing: entry, track: { playing: true } }))
  for (const playersView of [false, true]) {
    if (playersView) await page.getByRole('link', { name: 'Player settings' }).click()
    const card = page.getByTestId('light-timing')
    await expect(card.getByText('Lights are about 125 ms behind the sound')).toBeVisible()
    await expect(card.getByText('Lights behind', { exact: true })).toBeVisible()
    await expect(card.getByText('In sync', { exact: true })).toHaveCount(0)
    await expect(card.getByText('Early delivery was too much for this sender and has been switched off')).toBeVisible()
    await expect(card.getByRole('button', { name: 'Lights 10 milliseconds earlier' })).toBeDisabled()
  }
})

for (const stopBetween of [false, true]) {
  test(`Go switches LMS → AirPlay → LMS → AirPlay, stop between=${stopBetween}`, async ({ page }) => {
    const socket = await setupPreview(page)
    const activations: string[] = []
    const status = (id: string | null, playing: boolean) => ({ type: 'status', active_coupling_id: id,
      active_player_type: id === 'ap' ? 'AirPlay' : 'LMS', processes: { lms_player: id === 'c' },
      airplay_receiving: id === 'ap' && playing, applied_delay_ms: 0,
      track: id ? { playing, title: id === 'ap' ? 'AirPlay audio' : 'LMS audio' } : null })
    await page.route('**/api/couplings', route => route.fulfill({ json: [
      { id: 'c', name: 'LMS Room', player_id: 'p', analyser_id: 'a' },
      { id: 'ap', name: 'Zitkamer AirPlay', player_id: 'ap', analyser_id: 'a' },
    ] }))
    await page.route('**/api/virtual-players', route => route.fulfill({ json: [
      { id: 'p', type: 'LMS' }, { id: 'ap', type: 'AirPlay' },
    ] }))
    await page.route('**/api/couplings/*/activate', route => {
      const id = new URL(route.request().url()).pathname.split('/').at(-2)!
      activations.push(id)
      socket().send(JSON.stringify(status(id, true)))
      return route.fulfill({ json: { active_id: id, warnings: [] } })
    })
    await page.route('**/api/couplings/deactivate', route => {
      socket().send(JSON.stringify(status(null, false)))
      return route.fulfill({ json: { active_id: null } })
    })
    await page.reload()
    const card = page.getByRole('heading', { name: 'Active coupling', exact: true }).locator('..').locator('..')
    for (const [id, name] of [['ap', 'Zitkamer AirPlay'], ['c', 'LMS Room'], ['ap', 'Zitkamer AirPlay']]) {
      if (stopBetween) {
        await card.getByRole('button', { name: 'Stop', exact: true }).click()
        await expect(card.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
      }
      await card.locator('select').selectOption(id)
      await card.getByRole('button', { name: 'Go', exact: true }).click()
      await expect(card.locator('select option:checked')).toHaveText(name)
      await expect(card.getByRole('button', { name: 'Go', exact: true })).toBeDisabled()
      if (id === 'ap') await expect(page.getByTestId('track-block')).toContainText('AirPlay audio')
      else await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
      // A paused sender must not prevent the next Go either.
      socket().send(JSON.stringify(status(id, false)))
    }
    expect(activations).toEqual(['ap', 'c', 'ap'])
  })
}

test('early tap timing, measured lead, fallback and recovery use the existing card', async ({ page }) => {
  const socket = await setupPreview(page)
  const send = (source: string, lead: number, state: string) => socket().send(JSON.stringify({
    type: 'status', active_coupling_id: 'c', active_player_type: 'AirPlay', processes: {},
    timing_player_mac: 'airplay', timing_player_name: 'Room', applied_delay_ms: Math.max(0, lead - 98),
    light_timing: { player_mac: 'airplay', name: 'Room', strategy: 'auto', trim_ms: 0,
      fixed_delay_ms: 0, status: { source: 'airplay', audio_source: source, strategy: 'auto', state,
        applied_delay_ms: Math.max(0, lead - 98), early_delivery_ms: lead, lead_p5_ms: lead,
        lead_p50_ms: lead + 10, median_processing_ms: 98, lag_ms: Math.max(0, 98 - lead),
        tap_drop_count: 3, sample_count: 7, precision_ms: 2, samples: [] } },
  }))
  const card = page.getByTestId('light-timing')
  send('early tap', 150, 'stable')
  await expect(card.getByText('Lights on time', { exact: true })).toBeVisible()
  await card.getByText('Details', { exact: true }).click()
  await expect(card.getByText('Audio arrives about 160 ms early (p5 150 ms)')).toBeVisible()
  await expect(card.getByText('Source: early tap · Tap dropped records: 3')).toBeVisible()
  await expect(card.getByRole('button', { name: 'Lights 10 milliseconds earlier' })).toBeEnabled()
  send('early tap', 20, 'lagging')
  await expect(card.getByText('Lights about 78 ms behind')).toBeVisible()
  await expect(card.getByRole('button', { name: 'Lights 10 milliseconds earlier' })).toBeDisabled()
  send('pipe fallback', 0, 'lagging')
  await expect(card.getByText('Lights about 98 ms behind')).toBeVisible()
  await expect(card.getByText('Source: pipe fallback · Tap dropped records: 3')).toBeVisible()
  send('early tap', 500, 'stable')
  await expect(card.getByText('Lights on time', { exact: true })).toBeVisible()
})
