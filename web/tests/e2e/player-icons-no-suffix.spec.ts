import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

const discoveries = [
  { playerid: 'study', name: 'Study', modelname: 'YeneY' },
  { playerid: 'mbr', name: 'MBR', modelname: 'yeney' },
  { playerid: 'port', name: 'Sonos Port', modelname: 'YENEY' },
]

for (const theme of ['light', 'dark']) {
  test(`suffix-free Sonos list, Follow picker and timing alias in ${theme}`, async ({ page }, info) => {
    await setupPreview(page, () => ({
      follow_target_mac: 'study', follow_target_name: 'Study', timing_player_name: 'Favourite room', applied_delay_ms: 1000,
      light_timing: { player_mac: 'study', name: 'Favourite room', strategy: 'auto', trim_ms: 0,
        status: { state: 'stable', sample_count: 7, precision_ms: 10, samples: [] } },
    }))
    await page.route('**/api/virtual-players', route => route.fulfill({ json: [{
      id: 'p', type: 'LMS', player_name: 'LampaStream LMS', player_mac: 'local',
      lms_host: 'fixture.invalid', lms_port: 9000, follow_player_mac: '', follow_mode: 'manual',
    }] }))
    await page.route('**/api/lms/players?**', route => route.fulfill({ json: discoveries }))
    await page.route('**/api/player-latencies', route => route.fulfill({ json: discoveries.map(player => ({
      player_mac: player.playerid, name: player.name, strategy: 'fixed', fixed_delay_ms: 1000, trim_ms: 0,
    })) }))
    await page.reload()
    await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const diagram = page.getByTestId('timing-diagram')
    await expect(diagram).toContainText('Favourite room')
    await expect(diagram.locator('[data-player-icon="Sonos"]')).toBeVisible()
    const timingBox = await diagram.locator('[data-player-icon="Sonos"]').boundingBox()
    expect([timingBox!.width, timingBox!.height]).toEqual([32, 32])

    await page.getByRole('button', { name: 'Players', exact: true }).click()
    for (const player of discoveries) {
      const row = page.getByRole('option', { name: new RegExp('^' + player.name) })
      const glyph = row.locator('[data-player-icon="Sonos"]')
      await expect(glyph).toBeVisible()
      const box = await glyph.boundingBox(), tile = await glyph.locator('..').boundingBox()
      expect([box!.width, box!.height, tile!.width, tile!.height]).toEqual([30, 30, 40, 40])
      expect(await glyph.evaluate(el => getComputedStyle(el).backgroundColor === getComputedStyle(el).color)).toBe(true)
      await row.click()
      const header = page.locator('[data-player-icon="Sonos"]').last()
      const detail = await header.boundingBox(), detailTile = await header.locator('..').boundingBox()
      expect([detail!.width, detail!.height, detailTile!.width, detailTile!.height]).toEqual([40, 40, 56, 56])
    }
    await page.getByRole('option', { name: /LampaStream LMS/ }).click()
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    await page.getByRole('button', { name: 'Discover', exact: true }).click()
    await page.getByRole('combobox').filter({ hasText: 'None — track mirroring disabled' }).click()
    for (const player of discoveries) {
      const option = page.getByRole('option', { name: `${player.name} (${player.playerid})`, exact: true })
      const glyph = option.locator('[data-player-icon="Sonos"]')
      await expect(glyph).toBeVisible()
      const box = await glyph.boundingBox()
      expect([box!.width, box!.height]).toEqual([17, 17])
    }
    await page.screenshot({ path: info.outputPath(`player-icons-no-suffix-${theme}.png`), fullPage: true })
  })
}
