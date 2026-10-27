import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('preview outlines follow the envelope and each channel accent lift', async ({ page }) => {
  const socket = await setupPreview(page)
  const frame = page.getByTestId('floorplan-frame')
  const dot = page.getByTestId('floorplan-channel-1')
  const send = (data: Record<string, unknown>) => socket().send(JSON.stringify({
    type: 'frame', colour: { r: 0, g: 0, b: 0 }, ...data,
  }))
  send({ onset: true, onset_envelope: .8, channel_accent_lifts: [.6] })
  await expect(frame).toHaveAttribute('stroke', 'white')
  await expect(dot).toHaveAttribute('stroke', 'white')
  await expect(dot).toHaveAttribute('stroke-opacity', '0.6')
  send({ onset: false, onset_envelope: .7, channel_accent_lifts: [.2] })
  await expect(frame).toHaveAttribute('stroke', 'white')
  await expect(dot).toHaveAttribute('stroke-opacity', '0.2')
  send({ onset: false, onset_envelope: .5, channel_accent_lifts: [0] })
  await expect(frame).toHaveAttribute('stroke', 'currentColor')
  await expect(dot).toHaveAttribute('stroke-width', '0')
  // Legacy event-based socket payloads retain the compatibility flag fallback.
  send({ onset: true })
  await expect(frame).toHaveAttribute('stroke', 'white')
})


test('future event outlines wait for audible time and timing shows offset and RTT', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-27T12:00:00Z') })
  await page.clock.pauseAt(new Date('2026-10-27T12:00:01Z'))
  const socket = await setupPreview(page, () => ({}), true)
  await expect(page.getByTestId('preview-clock')).toContainText('offset 9000.0 ms · RTT 0.0 ms')
  const now = await page.evaluate(() => performance.now())
  await page.evaluate(() => {
    const target = document.querySelector('[data-testid="floorplan-frame"]')!
    ;(window as unknown as { activation: number | null }).activation = null
    new MutationObserver(() => {
      if (target.getAttribute('stroke') === 'white')
        (window as unknown as { activation: number | null }).activation ??= performance.now()
    }).observe(target, { attributes: true })
  })
  const target = now + 500
  socket().send(JSON.stringify({ type: 'event', audible_monotonic: (target + 9000) / 1000,
    events: [{ id: ['future', 'bass', 1], audible_monotonic: (target + 9000) / 1000,
      peaks: { all: 1, bass: 1, mid: 0, treble: 0 }, bands: ['bass'] }],
    event_count: 1, hold_s: .08, release_s: .25, policy: 'restart',
    channel_colours: [{ r: 65535, g: 0, b: 0 }], channel_accent_lifts: [.6], accent_value: .35 }))
  await page.clock.runFor(499)
  await expect(page.getByTestId('floorplan-frame')).toHaveAttribute('stroke', 'currentColor')
  await page.clock.runFor(17)
  await expect(page.getByTestId('floorplan-frame')).toHaveAttribute('stroke', 'white')
  await expect(page.getByTestId('floorplan-channel-1')).toHaveAttribute('stroke-opacity', '0.6')
  const activation = await page.evaluate(() => (window as unknown as { activation: number }).activation)
  expect(activation - target).toBeGreaterThanOrEqual(0)
  expect(activation - target).toBeLessThanOrEqual(17)
  console.log(`Playwright scheduled activation minus audible: ${activation - target} ms`)
})
