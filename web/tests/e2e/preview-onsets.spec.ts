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
