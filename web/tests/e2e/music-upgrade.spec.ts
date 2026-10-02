import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

const warm = { id: 'warm', name: 'Warm', stops: [{ colour: '#ff0000', position: 0 }, { colour: '#0000ff', position: 100 }] }
async function setup(page: import('@playwright/test').Page) {
  const socket = await setupPreview(page, () => ({ music: { genre: 'house', source: 'Track tag', raw_tags: ['deep house'], palette_id: 'warm', energy_profile_id: '', manual: false } }))
  let palettes = [warm]
  const settings = { lastfm_enabled: false, api_key_configured: false, genre_mapping: { 'deep house': 'house' }, genres: ['house', 'jazz', 'other'], rules: [], transition_mode: 'crossfade', transition_duration_s: .7 }
  await page.route('**/api/palettes**', route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path.endsWith('/preview')) return route.fulfill({ json: Array(65).fill({ r: 1, g: .1, b: .2 }) })
    if (method === 'GET') return route.fulfill({ json: palettes })
    if (method === 'POST' || method === 'PUT') {
      const body = route.request().postDataJSON()
      const palette = { ...body, id: path === '/api/palettes' ? 'new' : path.split('/').pop() }
      palettes = [...palettes.filter(p => p.id !== palette.id), palette]
      return route.fulfill({ json: palette })
    }
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/music-settings', route => {
    if (route.request().method() === 'PATCH') Object.assign(settings, route.request().postDataJSON())
    return route.fulfill({ json: settings })
  })
  await page.route('**/api/genre-rules', route => route.fulfill({ json: { ...route.request().postDataJSON(), id: 'r' } }))
  await page.route('**/api/music/override', route => route.fulfill({ json: route.request().postDataJSON() }))
  socket().send(JSON.stringify({ type: 'frame', sustained_energy: .63, mix: .4, colour: { r: 0, g: 0, b: 0 }, bars: [], onset: false }))
  return socket
}

test('palette editor creates and moves stops with the active floor-plan preview', async ({ page }) => {
  await setup(page)
  await page.getByRole('button', { name: 'Palettes', exact: true }).click()
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Warm')
  await page.getByRole('button', { name: 'Create palette' }).click()
  await page.getByLabel('Name', { exact: true }).fill('My palette')
  await page.getByRole('button', { name: 'Add stop' }).click()
  await page.getByLabel('Position 2').press('ArrowRight')
  await page.getByRole('button', { name: 'Save palette' }).click()
  await expect(page.getByText('Palette saved')).toBeVisible()
  await expect(page.getByLabel('Light floorplan')).toBeVisible()
})

test('genre privacy, rules and transition controls work in the existing visual language', async ({ page }) => {
  await setup(page)
  await page.getByRole('button', { name: 'Music settings', exact: true }).click()
  await page.getByLabel('Look up missing tags with Last.fm').check()
  await expect(page.getByText('Last.fm lookup enabled')).toBeVisible()
  await page.getByLabel('Look up missing tags with Last.fm').uncheck()
  await page.getByRole('button', { name: 'Add rule' }).click()
  await page.getByLabel('Rule 1 palette').selectOption('warm')
  await page.getByRole('button', { name: 'Save rule' }).click()
  await expect(page.getByText('Genre rule saved')).toBeVisible()
  await page.getByLabel('Transition', { exact: true }).selectOption('through-white')
  await page.getByRole('button', { name: 'Save settings' }).click()
  await expect(page.getByText('Music settings saved')).toBeVisible()
})

test('Now Playing additions and both new pages fit on phones in light and dark mode', async ({ page }) => {
  const socket = await setup(page)
  await expect(page.getByTestId('sustained-energy')).toHaveText('Sustained 0.63')
  await expect(page.getByTestId('track-colours').getByText('deep house')).toBeVisible()
  await page.getByLabel('Track palette').selectOption('album-art')
  await expect(page.getByRole('button', { name: 'Clear manual choices' })).toBeVisible()
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    await page.setViewportSize({ width: 390, height: 844 })
    for (const name of ['Palettes', 'Music settings', 'Now Playing']) {
      await page.getByRole('button', { name, exact: true }).click()
      if (name === 'Now Playing') socket().send(JSON.stringify({ type: 'status', active_coupling_id: 'c', active_player_type: 'LMS', processes: {}, music: { genre: 'house', source: 'Track tag', raw_tags: ['deep house'], palette_id: '', energy_profile_id: '', manual: false } }))
      if (name === 'Now Playing') await expect(page.getByTestId('track-colours')).toBeVisible()
      else await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      expect(await page.evaluate(() => [...document.querySelectorAll('main section')].every(el => el.scrollWidth <= el.clientWidth + 1))).toBe(true)
      const background = await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor)
      expect(background).toBe(scheme === 'light' ? 'rgb(246, 247, 249)' : 'rgb(22, 24, 29)')
    }
  }
})
