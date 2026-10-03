import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('Release and Take lights round trip keeps every state the same height', async ({ page }) => {
  const socket = await setupPreview(page)
  const update = (state: string, reason: string | null) => socket().send(JSON.stringify({ type: 'status', active_coupling_id: 'c', processes: {}, output_status: { state, reason } }))
  await page.route('**/api/couplings/c/release-lights', async route => {
    await route.fulfill({ json: {} }); update('released', 'You released the lights')
  })
  await page.route('**/api/couplings/c/take-lights', async route => {
    await route.fulfill({ json: {} }); update('streaming', null)
  })
  update('streaming', null)
  const row = page.getByTestId('lights-row')
  await expect(row).toContainText('Following the music')
  const height = (await row.boundingBox())!.height
  await page.getByRole('button', { name: 'Release lights' }).click()
  await expect(row).toContainText('Released · You released the lights')
  expect((await row.boundingBox())!.height).toBe(height)
  await page.getByRole('button', { name: 'Take lights' }).click()
  await expect(row).toContainText('Following the music')
  update('reconnecting', 'Connecting the lights')
  await expect(row).toContainText('Reconnecting the lights')
  expect((await row.boundingBox())!.height).toBe(height)
  await expect(page.getByRole('button', { name: 'Release lights' })).toBeEnabled()
  for (const width of [1400, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    for (const state of ['streaming', 'released', 'reconnecting', 'failed']) {
      update(state, state === 'streaming' ? null : 'Reason')
      await expect(row).toContainText(state === 'streaming' ? 'Following the music' : state === 'released' ? 'Released' : state === 'reconnecting' ? 'Reconnecting the lights' : 'Light output unavailable')
      expect((await row.boundingBox())!.height).toBe(height)
    }
  }
})

test('Appearance persists and System follows changes', async ({ page }) => {
  await setupPreview(page)
  const html = page.locator('html')
  await page.getByRole('button', { name: 'Dark', exact: true }).click()
  await expect(html).toHaveAttribute('data-theme', 'dark')
  await page.reload()
  await expect(html).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('button', { name: 'Light', exact: true }).click()
  await expect(html).toHaveAttribute('data-theme', 'light')
  await page.reload()
  await expect(html).toHaveAttribute('data-theme', 'light')
  await page.getByRole('button', { name: 'System', exact: true }).click()
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(html).toHaveAttribute('data-theme', 'dark')
  await page.emulateMedia({ colorScheme: 'light' })
  await expect(html).toHaveAttribute('data-theme', 'light')
})

const routes = ['now-playing', 'couplings', 'analysers', 'palettes', 'music-settings', 'effects', 'energy-profiles', 'zones', 'players', 'backup']
for (const theme of ['light', 'dark'] as const) for (const width of [1400, 390]) {
  test(`all routes have readable text in ${theme} at ${width}px`, async ({ page }) => {
    test.setTimeout(60000)
    await setupPreview(page, () => ({ bridge_connected: true, output_status: { state: 'streaming', reason: null } }))
    await page.route('**/api/music-settings', route => route.fulfill({ json: { lastfm_enabled: false, api_key_configured: false, genre_mapping: { house: 'house' }, genres: ['house', 'other'], rules: [], transition_mode: 'crossfade', transition_duration_s: .7 } }))
    await page.route('**/api/effects', route => route.fulfill({ json: [{ id: 'fx', name: 'Spectrum', effect_type: 'spectrum_rgb', palette_id: 'warm', band_colours: ['#ff0000', '#00ff00', '#0000ff'] }] }))
    await page.route('**/api/palettes', route => route.fulfill({ json: [{ id: 'warm', name: 'Warm', stops: [{ colour: '#ff0000', position: 0 }, { colour: '#0000ff', position: 100 }] }] }))
    await page.route('**/api/palettes/preview', route => route.fulfill({ json: Array(65).fill({ r: 1, g: .1, b: .2 }) }))
    await page.setViewportSize({ width, height: 1100 })
    await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click()
    const allFailures: string[] = []
    for (const route of routes) {
      await page.goto(`/${route}`)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await expect(page.locator('main')).not.toBeEmpty()
      await page.waitForTimeout(250)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), route).toBe(true)
      const failures = await page.evaluate(() => {
        const rgb = (s: string) => (s.match(/[\d.]+/g) || []).map(Number)
        const lum = (c: number[]) => c.slice(0, 3).map(x => { const v = x / 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4 }).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0)
        const blend = (a: number[], b: number[]) => { const alpha = a[3] ?? 1; return [0, 1, 2].map(i => a[i] * alpha + b[i] * (1 - alpha)) }
        const errors: string[] = []
        for (const el of document.querySelectorAll<HTMLElement>('body *')) {
          if (!Array.from(el.childNodes).some(n => n.nodeType === Node.TEXT_NODE && n.textContent?.trim()) && !el.matches('select, textarea, input[type=text], input[type=password], input[type=number]')) continue
          const box = el.getBoundingClientRect(); const css = getComputedStyle(el)
          if (!box.width || !box.height || css.visibility === 'hidden' || el.closest('[aria-hidden="true"]') || el.closest(':disabled, [aria-disabled="true"]')) continue
          const chain: Element[] = []; let parent: Element | null = el
          while (parent) { chain.unshift(parent); parent = parent.parentElement }
          let bg = [255, 255, 255]
          for (const node of chain) bg = blend(rgb(getComputedStyle(node).backgroundColor), bg)
          const ink = rgb(el instanceof SVGElement ? css.fill : css.color)
          ink[3] = (ink[3] ?? 1) * chain.reduce((a, node) => a * Number(getComputedStyle(node).opacity), 1) * (el instanceof SVGElement ? Number(css.fillOpacity) : 1)
          const fg = blend(ink, bg); const a = lum(fg), b = lum(bg)
          const ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05)
          const large = parseFloat(css.fontSize) >= 24 || (parseFloat(css.fontSize) >= 18.66 && parseInt(css.fontWeight) >= 700)
          if (ratio < (large ? 3 : 4.5) - .01) errors.push(`${el.textContent?.trim().slice(0, 70)}: ${ratio.toFixed(2)} (${css.color} on ${bg.map(Math.round)})`)
        }
        return errors
      })
      allFailures.push(...failures.map(failure => `${route}: ${failure}`))
      if (route === 'now-playing') await page.screenshot({ path: `test-results/now-playing-${theme}-${width}.png`, fullPage: true })
    }
    expect(allFailures, `${theme} ${width}`).toEqual([])
  })
}
