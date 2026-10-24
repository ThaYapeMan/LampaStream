import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

for (const theme of ['light', 'dark']) {
  test(`option B player icon geometry in ${theme}`, async ({ page }) => {
    await setupPreview(page)
    let longNames = false
    const longName = 'piCorePlayer ' + 'long room name '.repeat(30)
    await page.route('**/api/virtual-players', route => route.fulfill({ json: [
      { id: 'p', type: 'LMS', player_name: 'LampaStream LMS', player_mac: 'local', lms_host: 'fixture.invalid', lms_port: 9000, follow_player_mac: '', follow_mode: 'manual' },
      { id: 'air', type: 'AirPlay', player_name: 'AirPlay', player_mac: 'air' },
    ] }))
    await page.route('**/api/lms/players?**', route => route.fulfill({ json: [
      { playerid: 'sonos', name: 'Study (Sonos)', modelname: 'YeneY' },
      { playerid: 'radio', name: 'Radio Red', model: 'baby' },
      { playerid: 'pi', name: 'piCorePlayer', modelname: 'SqueezeLite-pCP', firmware: '8.5-pCP' },
    ] }))
    await page.route('**/api/player-latencies', route => route.fulfill({ json: [
      ['sonos', 'Study (Sonos)'], ['radio', 'Radio Red'], ['pi', 'piCorePlayer'], ['unknown', 'Generic speaker'],
    ].map(([player_mac, name]) => ({ player_mac, name: longNames && player_mac === 'pi' ? longName : name, strategy: 'fixed', fixed_delay_ms: 1000, trim_ms: 0 })) }))
    await page.getByRole('button', { name: 'Players', exact: true }).click()
    await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const sonos = page.getByRole('option', { name: /Study \(Sonos\)/ })
    await expect(sonos.locator('[data-player-icon="Sonos"]')).toBeVisible()
    await sonos.click()
    const measurements = []
    for (const [name, kind] of [['LampaStream LMS', 'LMS'], ['Joins your AirPlay groups', 'AirPlay'], ['Study \\(Sonos\\)', 'Sonos'], ['Radio Red', 'Radio'], ['piCorePlayer', 'RaspberryPi'], ['Generic speaker', 'Speaker']]) {
      const row = page.getByRole('option', { name: new RegExp(name) })
      const glyph = row.locator(`[data-player-icon="${kind}"]`)
      await expect(glyph).toBeVisible()
      if (!['AirPlay', 'Speaker'].includes(kind)) {
        const mask = await glyph.evaluate(el => ({ image: getComputedStyle(el).maskImage, fill: getComputedStyle(el).backgroundColor, colour: getComputedStyle(el).color }))
        expect(mask.image).not.toBe('none')
        expect(mask.fill).toBe(mask.colour)
      }
      const box = await glyph.boundingBox()
      const tile = await glyph.locator('..').boundingBox()
      expect([box!.width, box!.height, tile!.width, tile!.height]).toEqual([30, 30, 40, 40])
      expect(box!.x + box!.width / 2).toBe(tile!.x + tile!.width / 2)
      expect(box!.y + box!.height / 2).toBe(tile!.y + tile!.height / 2)
      const alignment = await row.evaluate(el => {
        const [tile, text, pill] = Array.from(el.children).map(child => child.getBoundingClientRect())
        const style = getComputedStyle(el)
        return { height: el.getBoundingClientRect().height, padding: [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft],
          gap: text.x - tile.right, textCentre: text.y + text.height / 2, pillCentre: pill.y + pill.height / 2, tileCentre: tile.y + tile.height / 2 }
      })
      expect(alignment.height).toBe(64)
      expect(alignment.padding).toEqual(['12px', '16px', '12px', '16px'])
      expect(alignment.gap).toBe(12)
      expect(alignment.textCentre).toBe(alignment.tileCentre)
      expect(alignment.pillCentre).toBe(alignment.tileCentre)
      await row.click()
      const detail = page.locator(`[data-player-icon="${kind}"]`).last()
      const detailBox = await detail.boundingBox()
      const detailTile = await detail.locator('..').boundingBox()
      expect([detailBox!.width, detailBox!.height, detailTile!.width, detailTile!.height]).toEqual([40, 40, 56, 56])
      expect(detailBox!.x + detailBox!.width / 2).toBe(detailTile!.x + detailTile!.width / 2)
      expect(detailBox!.y + detailBox!.height / 2).toBe(detailTile!.y + detailTile!.height / 2)
      const header = await detail.locator('..').evaluate(el => {
        const tile = el.getBoundingClientRect()
        const text = el.nextElementSibling!.getBoundingClientRect()
        return { tileCentre: tile.y + tile.height / 2, textCentre: text.y + text.height / 2, gap: text.x - tile.right,
          height: el.parentElement!.getBoundingClientRect().height, radius: getComputedStyle(el).borderRadius }
      })
      expect(header.textCentre).toBe(header.tileCentre)
      expect(header.gap).toBe(12)
      expect(header.height).toBe(56)
      expect(header.radius).toBe('10px')
      measurements.push({ kind, rowHeight: alignment.height, headerHeight: header.height, list: [box!.width, box!.height], listTile: [tile!.width, tile!.height], detail: [detailBox!.width, detailBox!.height], detailTile: [detailTile!.width, detailTile!.height] })
    }
    await page.getByRole('option', { name: /LampaStream LMS/ }).click()
    await expect(page.locator('[data-player-icon="LMS"]').last()).toBeVisible()
    await page.screenshot({ path: `../docs/designs/players-icons-b-lms-${theme}.png`, fullPage: true })
    await sonos.click()
    await page.screenshot({ path: `../docs/designs/players-icons-b-${theme}.png`, fullPage: true })
    console.log(theme, JSON.stringify(measurements))
    longNames = true
    await page.reload()
    const longRow = page.getByRole('option', { name: /piCorePlayer long room name/ })
    await expect(longRow).toBeVisible()
    for (const width of [1400, 390]) {
      await page.setViewportSize({ width, height: 1100 })
      const truncation = await longRow.locator('.truncate').first().evaluate(el => ({
        clipped: el.scrollWidth > el.clientWidth, overflow: getComputedStyle(el).overflow,
        ellipsis: getComputedStyle(el).textOverflow, whiteSpace: getComputedStyle(el).whiteSpace
      }))
      expect(truncation).toEqual({ clipped: true, overflow: 'hidden', ellipsis: 'ellipsis', whiteSpace: 'nowrap' })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    }
  })
}
