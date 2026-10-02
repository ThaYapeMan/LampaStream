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
      active_player_type: 'LMS', effect_type: 'spectrum_rgb',
      sync_master_name: 'Living room', sync_master: 'aa:bb:cc:dd:ee:ff', applied_delay_ms: 1100,
      processes: { lms_player: true }, bridge_connected: true }))
    ws.send(JSON.stringify({ type: 'frame', colour: { r: 32000, g: 9000, b: 22000 },
      channel_colours: [{ r: 32000, g: 9000, b: 22000 }, { r: 5000, g: 18000, b: 32000 }],
      onset: false, mix: .4, loudness_momentary_lufs: -18.4 }))
  })
  await page.goto('/')
  const status = page.getByLabel('Session status')
  await expect(status.locator('dt')).toHaveText([
    'Spectrum engine', 'Beat detection', 'Effect',
  ])
  await expect(status.locator('dd')).toHaveText([
    'CAVA Core', 'Combined', 'spectrum_rgb',
  ])
  await expect(page.getByLabel('Light floorplan')).toBeVisible()
  const colour = await page.getByTestId('colour-preview-size').boundingBox()
  const floorplan = await page.getByTestId('floorplan-preview-size').boundingBox()
  const heading = await page.getByRole('heading', { name: 'Status', exact: true }).boundingBox()
  expect(Math.abs(colour!.y - floorplan!.y)).toBeLessThanOrEqual(1)
  expect(Math.abs(colour!.y - heading!.y)).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('now-playing-technical-status-1400.png'), fullPage: true })
})

test('output warning follows failure and recovery in standard mode', async ({ page }) => {
  const socket = await setupPreview(page)
  const update = (state: string, reason: string | null) => socket().send(JSON.stringify({ type: 'status',
    active_coupling_id: 'c', active_player_type: 'LMS', processes: { lms_player: true },
    bridge_connected: state === 'streaming', output_status: { state, reason } }))
  update('reconnecting', 'Light connection dropped')
  await expect(page.getByTestId('output-warning')).toHaveText('Reconnecting the lights · Light connection dropped')
  update('failed', 'Could not reconnect the lights; retrying')
  await expect(page.getByTestId('output-warning')).toContainText('Light output unavailable')
  update('streaming', null)
  await expect(page.getByTestId('output-warning')).toHaveCount(0)
})
