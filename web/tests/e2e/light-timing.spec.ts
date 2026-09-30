import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('Light timing persists folding, fine-tunes and switches Fixed to Auto', async ({ page }) => {
  let strategy = 'auto', trim = 0
  let measuring = false
  const entry = () => ({ player_mac: 'aa', name: 'Study', strategy, fixed_delay_ms: 1100,
    trim_ms: trim, measured_delay_ms: 2243, measured_at: 100,
    status: { state: strategy === 'auto' ? measuring ? 'measuring' : 'stable' : 'idle', strategy,
      applied_delay_ms: 1100, sample_count: 0, samples: [], precision_ms: null } })
  const timingStatus = () => ({ follow_target_mac: 'aa', follow_target_name: 'Study',
    sync_master: 'aa', light_timing: entry() })
  const socket = await setupPreview(page, timingStatus)
  await page.route('**/api/player-latencies/aa', route => {
    const body = route.request().postDataJSON()
    if (body.trim_ms !== undefined) trim = body.trim_ms
    if (body.strategy) { strategy = body.strategy; measuring = true }
    socket().send(JSON.stringify({ type: 'status', active_player_type: 'LMS',
      applied_delay_ms: 1100, processes: {}, ...timingStatus() }))
    return route.fulfill({ json: entry() })
  })
  const disclosure = page.getByRole('button', { name: 'Light timing', exact: true })
  await disclosure.focus(); await page.keyboard.press('Enter')
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  await page.reload()
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByTestId('light-timing').getByText('1.10 s', { exact: true })).toBeVisible()
  await disclosure.click()
  await page.getByRole('button', { name: 'Lights 10 milliseconds earlier' }).click()
  await expect(page.getByText('Saved · lights earlier by 10 ms')).toBeVisible()
  await page.getByRole('button', { name: 'Lights 10 milliseconds earlier' }).click()
  await expect(page.getByLabel('Fine-tune by ear')).toHaveText('-20 ms')
  await expect(page.getByText('Saved · lights earlier by 20 ms')).toBeVisible()
  expect(trim).toBe(-20)
  strategy = 'fixed'
  socket().send(JSON.stringify({ type: 'status', active_player_type: 'LMS',
    applied_delay_ms: 1100, processes: {}, ...timingStatus() }))
  await expect(page.getByTestId('light-timing').getByText('Fixed', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Measure automatically' }).click()
  await expect(page.getByTestId('light-timing').getByText('Measuring', { exact: true })).toBeVisible()
  expect(strategy).toBe('auto')
  await page.getByRole('link', { name: 'Latency settings' }).click()
  await expect(page.getByRole('heading', { name: 'Player latency' })).toBeVisible()
})
