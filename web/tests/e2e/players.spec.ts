import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('Players groups timings, selects AirPlay, switches Auto and stacks on phones', async ({
  page
}) => {
  await setupPreview(page)
  let strategy = 'fixed'
  const entries = () => [
    {
      player_mac: 'study',
      name: 'Study (Sonos)',
      strategy: 'auto',
      trim_ms: 0,
      measured_delay_ms: 2240,
      fixed_delay_ms: 0,
      status: { strategy: 'auto', state: 'stable', applied_delay_ms: 2240, sample_count: 7 }
    },
    {
      player_mac: 'air',
      name: 'AirPlay',
      strategy,
      trim_ms: 0,
      fixed_delay_ms: 380,
      measured_delay_ms: 380,
      status: { source: 'airplay', strategy, state: strategy === 'auto' ? 'measuring' : 'idle', applied_delay_ms: 380, early_delivery_ms: 500, sample_count: 1 }
    },
    {
      player_mac: 'port',
      name: 'Sonos Port',
      strategy: 'fixed',
      trim_ms: 0,
      fixed_delay_ms: 1100
    }
  ]
  await page.route('**/api/virtual-players', (route) =>
    route.fulfill({
      json: [
        {
          id: 'p',
          type: 'LMS',
          player_name: 'LampaStream LMS',
          player_mac: 'lms',
          follow_player_mac: 'study',
          follow_mode: 'manual',
          lms_host: 'lms.local',
          lms_port: 9000
        },
        {
          id: 'airplay',
          type: 'AirPlay',
          player_name: 'LampaStream',
          player_mac: 'air'
        }
      ]
    })
  )
  await page.route('**/api/player-latencies', (route) =>
    route.fulfill({ json: entries() })
  )
  await page.route('**/api/player-latencies/air', (route) => {
    strategy = route.request().postDataJSON().strategy
    return route.fulfill({ json: entries()[1] })
  })
  await page.getByRole('button', { name: 'Players', exact: true }).click()
  await expect(
    page.getByRole('group', { name: 'Other timings', exact: true })
  ).toContainText('Sonos Port')
  const measurements: Record<string, unknown> = {}
  const lms = page.getByRole('option', { name: /LampaStream LMS/ })
  const air = page.getByRole('option', { name: /Joins your AirPlay groups/ })
  async function measure(label: string) {
    const values = await page.locator('[data-player-icon]').evaluateAll(elements => elements.map(el => ({
      type: el.getAttribute('data-player-icon'), colour: getComputedStyle(el).color,
      background: getComputedStyle(el).backgroundColor, tileBackground: getComputedStyle(el.parentElement!).backgroundColor,
      width: getComputedStyle(el).width
    })))
    for (const value of values) {
      expect(value.colour).toBe('rgb(230, 232, 235)')
      expect(value.tileBackground).toBe('rgb(44, 49, 58)')
      if (value.type === 'LMS') expect(value.background).toBe(value.colour)
    }
    measurements[label] = values
  }
  expect(await page.evaluate(() => CSS.supports('mask-image', 'url("test.png")') && CSS.supports('-webkit-mask-image', 'url("test.png")') && CSS.supports('mask-mode', 'alpha'))).toBe(true)
  await page.mouse.move(0, 0)
  await measure('LMS selected / AirPlay normal / LMS detail')
  await air.hover()
  await measure('AirPlay hover')
  await air.click()
  await measure('LMS normal / AirPlay selected / AirPlay detail')
  await lms.hover()
  await measure('LMS hover')
  console.log('PLAYER_ICON_COLOURS', JSON.stringify(measurements))

  await expect(
    page.getByText('AirPlay 2 receiver', { exact: true })
  ).toBeVisible()
  await page.getByRole('button', { name: 'Auto', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Auto', exact: true })
  ).toHaveAttribute('aria-pressed', 'true')
  expect(strategy).toBe('auto')
  await page.mouse.move(0, 0)
  const selectedColour = await page.getByRole('button', { name: 'Add player', exact: true }).evaluate(el => getComputedStyle(el).backgroundColor)
  await expect.poll(() => page.getByRole('button', { name: 'Auto', exact: true }).evaluate(el => getComputedStyle(el).backgroundColor)).toBe(selectedColour)

  await page.screenshot({ path: '/tmp/players-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  const list = await page.getByRole('listbox').boundingBox()
  const timing = await page.getByTestId('light-timing').boundingBox()
  expect(timing!.y).toBeGreaterThan(list!.y + list!.height)
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
  await page.screenshot({ path: '/tmp/players-phone.png', fullPage: true })
})
for (const route of ['/latency', '/virtual-players'])
  test(`${route} redirects to Players`, async ({ page }) => {
    await setupPreview(page)
    await page.goto(route)
    await expect(page).toHaveURL(/\/players$/)
    await expect(
      page.getByRole('heading', { name: 'Players', exact: true })
    ).toBeVisible()
  })
