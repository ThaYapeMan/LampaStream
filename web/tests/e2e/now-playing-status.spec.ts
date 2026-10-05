import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('technical session status at 1400px', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1400, height: 1100 })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    const data: Record<string, unknown> = {
      '/api/couplings': [{ id: 'c', name: 'Living room', analyser_id: 'a', player_id: 'p' }],
      '/api/analysers': [{ id: 'a', name: 'Custom analyser name', bars_source: 'pcm_pipeline',
        spectrum_backend: 'cavacore', onset_method: 'combined' }],
      '/api/effects': [{id:'fx', name:'Spectrum RGB', effect_type:'spectrum_rgb'}],
      '/api/energy-profiles': [{id:'e', name:'Room energy', high_energy_effect_id:'fx'}],
      '/api/virtual-players': [{ id: 'p', type: 'LMS' }],
      '/api/zones/z/channels': [
        { channel_id: 1, x: -.6, y: 0, z: -.6 },
        { channel_id: 2, x: .6, y: 0, z: .6 },
      ],
    }
    return route.fulfill({ json: data[path] ?? [] })
  })
  await page.routeWebSocket('**/ws/preview', ws => {
    ws.send(JSON.stringify({ type: 'status', active_coupling_id: 'c', active_zone_id: 'z',
      active_energy_profile_id:'e', active_player_type: 'LMS', effect_type: 'spectrum_rgb',
      sync_master_name: 'Living room', sync_master: 'aa:bb:cc:dd:ee:ff', applied_delay_ms: 1100,
      processes: { lms_player: true }, bridge_connected: true }))
    ws.send(JSON.stringify({ type: 'frame', colour: { r: 32000, g: 9000, b: 22000 },
      channel_colours: [{ r: 32000, g: 9000, b: 22000 }, { r: 5000, g: 18000, b: 32000 }],
      onset: false, mix: .4, loudness_momentary_lufs: -18.4 }))
  })
  await page.goto('/')
  const status = page.getByLabel('Session status')
  await expect(status.locator('dt')).toHaveText([
    'Spectrum engine', 'Beat detection', 'Effect', 'Energy profile',
  ])
  await expect(status.locator('dd')).toHaveText([
    'CAVA Core', 'Combined', 'Spectrum RGB', 'Room energy', 'Open Energy Profile ›',
  ])
  await expect(page.getByLabel('Light floorplan')).toBeVisible()
  const lights = await page.getByRole('region', {name:'Lights preview'}).boundingBox()
  const analysis = await page.getByRole('region', {name:'Analysis', exact:true}).boundingBox()
  expect(Math.abs(lights!.y - analysis!.y)).toBeLessThanOrEqual(1)
  expect(lights!.width / analysis!.width).toBeCloseTo(11/9, 1)
  await expect(page.getByTestId('session-diagnostics').getByRole('button')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('now-playing-technical-status-1400.png'), fullPage: true })
})

test('output warning follows failure and recovery in standard mode', async ({ page }) => {
  const socket = await setupPreview(page)
  const update = (state: string, reason: string | null) => socket().send(JSON.stringify({ type: 'status',
    active_coupling_id: 'c', active_player_type: 'LMS', processes: { lms_player: true },
    bridge_connected: state === 'streaming', output_status: { state, reason } }))
  update('reconnecting', 'Light connection dropped')
  await expect(page.getByTestId('lights-row')).toContainText('Reconnecting the lights · Light connection dropped')
  update('failed', 'Could not reconnect the lights; retrying')
  await expect(page.getByTestId('lights-row')).toContainText('Light output unavailable')
  update('streaming', null)
  await expect(page.getByTestId('lights-row')).toContainText('Following the music')
})


test('Released respects external control and Take lights explicitly re-acquires', async ({ page }) => {
  const socket = await setupPreview(page)
  let taken = 0
  await page.route('**/api/couplings/c/take-lights', async route => {
    taken++
    await route.fulfill({ json: { state: 'streaming', reason: null } })
    socket().send(JSON.stringify({ type: 'status', active_coupling_id: 'c', processes: {},
      bridge_connected: true, output_status: { state: 'streaming', reason: null } }))
  })
  await page.setViewportSize({ width: 390, height: 844 })
  socket().send(JSON.stringify({ type: 'status', active_coupling_id: 'c', processes: {},
    bridge_connected: false, output_status: { state: 'released', reason: 'Stopped from the Hue app or another controller' } }))
  await expect(page.getByTestId('lights-row')).toContainText('Released')
  expect(taken).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Take lights' }).click()
  await expect(page.getByTestId('lights-row')).toContainText('Following the music')
  expect(taken).toBe(1)
})

for (const theme of ['light', 'dark'] as const) for (const width of [1400, 390]) {
  test(`follow-mode probe keeps live timing in ${theme} at ${width}px`, async ({ page }) => {
    const entry = { player_mac: 'speaker', name: 'Radio', strategy: 'auto', trim_ms: 0,
      fixed_delay_ms: 0, measured_delay_ms: 0,
      status: { strategy: 'auto', state: 'measuring', applied_delay_ms: 3094, sample_count: 3 } }
    const base = { active_coupling_id: 'c', active_player_type: 'LMS', follow_mode: 'manual',
      timing_player_mac: 'speaker', timing_player_name: 'Radio', follow_target_mac: 'speaker',
      follow_target_name: 'Radio', processes: {}, lms_timing: null }
    const socket = await setupPreview(page, () => ({ ...base, applied_delay_ms: 3094, light_timing: entry }))
    await page.setViewportSize({ width, height: 1100 })
    await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click()
    await expect(page.getByText('Measuring', { exact: true })).toBeVisible()
    await expect(page.getByTestId('light-timing').locator('.text-4xl')).toContainText('3.09')
    await expect(page.getByText(/Checking the timing.*3 of 7 measurements/)).toBeVisible()
    await expect(page.getByTestId('lms-timing')).toHaveCount(0)
    socket().send(JSON.stringify({ type: 'status', ...base, applied_delay_ms: 1530,
      light_timing: { ...entry, status: { ...entry.status, state: 'stable', applied_delay_ms: 1530, sample_count: 7 } } }))
    await expect(page.getByText('In sync', { exact: true })).toBeVisible()
    await expect(page.getByTestId('light-timing').locator('.text-4xl')).toContainText('1.53')
    await expect(page.getByTestId('lms-timing')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}

for (const theme of ['light', 'dark'] as const) for (const width of [1400, 390]) {
  test(`approved Live preview layout in ${theme} at ${width}px`, async ({ page }, info) => {
    const socket = await setupPreview(page, () => ({ bridge_connected:true }))
    await page.route('**/api/effects', route => route.fulfill({json:[{id:'fx', name:'Spectrum RGB', effect_type:'spectrum_rgb'}]}))
    await page.route('**/api/energy-profiles', route => route.fulfill({json:[{
      id:'e', name:'Spectrum RGB', energy_source:'sustained', high_energy_effect_id:'fx', low_energy_effect_id:'fx',
    }]}))
    await page.reload()
    await page.setViewportSize({width, height:1100})
    await page.getByRole('button', {name:theme === 'light' ? 'Light' : 'Dark', exact:true}).click()
    await page.getByLabel('Editor mode').selectOption('expert')
    await page.clock.install({time:new Date('2026-10-05T10:00:00Z')})
    await page.clock.pauseAt(new Date('2026-10-05T10:00:01Z'))
    socket().send(JSON.stringify({type:'frame', colour:{r:1000,g:18000,b:24000},
      channel_colours:[{r:1000,g:18000,b:24000}], onset:true, mix:.01, sustained_energy:.21, loudness_momentary_lufs:-10.8}))
    const card = page.getByTestId('live-preview-card')
    await expect(card.getByRole('link', {name:'Open Energy Profile ›'})).toBeVisible()
    await expect(card.getByTestId('floorplan-frame')).toHaveAttribute('stroke','white')
    await expect(card.getByTestId('session-diagnostics').getByRole('button')).toHaveCount(0)
    await expect(card.getByRole('radio')).toHaveCount(4)
    await expect(card.getByRole('radio', {name:'Off'})).toHaveCount(0)
    await expect(card.getByTestId('sustained-energy')).toHaveText('0.21')
    await expect(card.getByTestId('momentary-loudness')).toHaveText('-10.8 LUFS')
    const lights = (await card.getByRole('region', {name:'Lights preview'}).boundingBox())!
    const analysis = (await card.getByRole('region', {name:'Analysis',exact:true}).boundingBox())!
    const segments = await card.getByRole('radio').evaluateAll(elements => elements.map(el => {
      const {x,y,width,height} = el.getBoundingClientRect(); return {x,y,width,height}
    }))
    if (width === 1400) {
      expect(lights.y).toBe(analysis.y)
      expect(lights.width / analysis.width).toBeCloseTo(11/9,1)
      expect(new Set(segments.map(box => box.y)).size).toBe(1)
    } else {
      expect(analysis.y).toBeGreaterThanOrEqual(lights.y+lights.height)
      expect(new Set(segments.map(box => box.y)).size).toBe(2)
    }
    expect(Math.max(...segments.map(box => box.width))-Math.min(...segments.map(box => box.width))).toBeLessThan(1)
    expect(await card.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await card.screenshot({path:info.outputPath(`live-preview-${theme}-${width}.png`)})
    socket().send(JSON.stringify({type:'frame',colour:{r:1000,g:18000,b:24000},onset:false}))
    await page.clock.runFor(100)
    await expect(card.getByTestId('floorplan-frame')).toHaveAttribute('stroke','currentColor')
  })
}
