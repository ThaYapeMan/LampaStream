import { test, expect } from '@playwright/test'
import { setupPreview, geometry } from './preview-fixture'

for (const theme of ['light', 'dark']) for (const kind of ['Sonos', 'LMS']) {
  test(`bare timing glyphs ${kind} ${theme}`, async ({ page }) => {
    const name = kind === 'Sonos' ? 'Study (Sonos)' : 'LampaStream LMS'
    const status = (name: string) => ({ follow_target_mac: 'fixture', follow_target_name: name,
      light_timing: { player_mac: 'fixture', name, strategy: 'auto', trim_ms: 0,
        status: { state: 'stable', sample_count: 7, precision_ms: 12, samples: [] } } })
    let fixtureName = name
    await setupPreview(page, () => status(fixtureName))
    await page.route('**/api/virtual-players', route => route.fulfill({ json: [{ id: 'p', type: 'LMS', lms_host: 'fixture.invalid' }] }))
    await page.route('**/api/lms/players?**', route => route.fulfill({ json: [
      { playerid: 'fixture', name, modelname: kind === 'Sonos' ? 'YeneY' : 'LampaStream' },
    ] }))
    await page.reload()
    await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click()
    const card = page.getByTestId('light-timing'), diagram = page.getByTestId('timing-diagram')
    await expect(diagram.locator('[data-player-icon]')).toHaveAttribute('data-player-icon', kind)
    const measurements = await diagram.evaluate(el => {
      const bulb = el.querySelector('svg')!, player = el.querySelector('[data-player-icon]')!
      const line = el.children[1], dot = line.querySelector('i')!
      const box = (node: Element) => { const r = node.getBoundingClientRect(); return { width: r.width, height: r.height, centre: r.y + r.height / 2 } }
      const tiles = Array.from(el.querySelectorAll('*')).filter(node => {
        const s = getComputedStyle(node)
        return s.borderStyle === 'solid' && parseFloat(s.borderWidth) > 0 || node.classList.contains('bg-secondary') || parseFloat(s.paddingTop) > 0
      }).length
      return { bulb: box(bulb), player: box(player), line: box(line), dot: box(dot), tiles,
        foreground: getComputedStyle(bulb).color, playerColour: getComputedStyle(player).color }
    })
    expect([measurements.bulb.width, measurements.bulb.height, measurements.player.width, measurements.player.height]).toEqual([32, 32, 32, 32])
    for (const item of [measurements.line, measurements.dot, measurements.player]) expect(item.centre).toBe(measurements.bulb.centre)
    expect(measurements.tiles).toBe(0)
    expect(measurements.foreground).toBe(measurements.playerColour)
    const currentHeight = (await card.boundingBox())!.height, currentGeometry = await geometry(page)
    // Recreate the old tile dimensions to check the surrounding page geometry.
    const original = await diagram.evaluate(el => {
      const saved = { html: el.innerHTML, classes: el.className }
      el.className = 'flex items-center gap-3 text-xs text-muted-foreground'
      el.querySelector('svg')!.setAttribute('class', 'h-9 w-9 rounded-lg border bg-secondary p-2')
      el.children[1].classList.remove('mt-[15px]')
      const player = el.querySelector('[data-player-icon]')! as HTMLElement
      player.style.width = '18px'; player.style.height = '18px'
      const tile = document.createElement('span')
      tile.className = 'grid h-9 w-9 place-items-center rounded-lg border bg-secondary p-2'
      player.replaceWith(tile); tile.append(player)
      return saved
    })
    const previousHeight = (await card.boundingBox())!.height
    expect(Math.abs(previousHeight - currentHeight)).toBeLessThanOrEqual(4)
    expect(await geometry(page)).toEqual(currentGeometry)
    await diagram.evaluate((el, saved) => { el.innerHTML = saved.html; el.className = saved.classes }, original)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const path = `../docs/designs/light-timing-icons${kind === 'LMS' ? '-lms' : ''}-${theme}.png`
    await card.screenshot({ path })
    console.log(JSON.stringify({ theme, kind, screenshot: path, cardHeight: currentHeight, previousHeight, heightDelta: currentHeight - previousHeight, ...measurements }))
    const longName = name + ' long room name'.repeat(30)
    fixtureName = longName
    await page.reload()
    for (const width of [1400, 390]) {
      await page.setViewportSize({ width, height: 1100 })
      await expect(diagram.locator('.truncate')).toHaveText(longName)
      expect(await diagram.locator('.truncate').evaluate(el => el.scrollWidth > el.clientWidth && getComputedStyle(el).textOverflow === 'ellipsis')).toBe(true)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    }
  })
}
