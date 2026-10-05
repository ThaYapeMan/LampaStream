import { test, expect } from '@playwright/test'
import { setupPreview, geometry } from './preview-fixture'
type Boxes = Record<string, {x:number; y:number; width:number; height:number}>

test('live energy source patching and unchanged preview geometry', async ({ page }, info) => {
  const socket = await setupPreview(page)
  let profile = { id:'e', name:'Spectrum RGB', energy_source:'sustained', lufs_floor:-30, lufs_ceiling:-8, adaptation_tau_s:60 }
  const patches: unknown[] = []
  await page.route('**/api/energy-profiles/e', async route => {
    const body = route.request().postDataJSON()
    patches.push(body); profile = { ...profile, ...body }
    await new Promise(resolve => setTimeout(resolve, 100))
    return route.fulfill({json:profile})
  })
  await expect(page.getByLabel('Session status').getByText('Spectrum RGB', {exact:true})).toBeVisible()
  const controls = page.getByTestId('live-energy-source')
  await expect(controls.getByRole('radiogroup')).toHaveCount(0)
  const baseline = await geometry(page) as Boxes
  const standardHeight = (await controls.boundingBox())!.height
  await page.getByLabel('Editor mode').selectOption('expert')
  const radios = page.getByRole('radiogroup', {name:'Energy source'}).getByRole('radio')
  const groupBox = (await page.getByRole('radiogroup', {name:'Energy source'}).boundingBox())!
  expect(groupBox.width).toBeGreaterThan(620)
  expect(groupBox.height).toBeLessThanOrEqual(48)
  const widths = await Promise.all([0,1,2,3].map(async i => (await radios.nth(i).boundingBox())!.width))
  expect(Math.max(...widths)-Math.min(...widths)).toBeLessThanOrEqual(.02)
  const boxes = await geometry(page) as Boxes
  for (const key of ['track-block', 'colour-preview-size', 'floorplan-preview-size', 'status'] as const) expect(boxes[key]).toEqual(baseline[key])
  // Expert controls only move the later spectrum card by their added height.
  const controlBox = (await controls.boundingBox())!
  const spectrumTop = () => page.getByTestId('spectrum-panel').evaluate(el => el.getBoundingClientRect().top + window.scrollY)
  const spectrumY = [boxes['spectrum-panel'].y]
  await expect(page.getByTestId('energy-parameters')).toHaveCount(0)
  expect(boxes['spectrum-panel'].x).toBe(baseline['spectrum-panel'].x)
  expect(boxes['spectrum-panel'].width).toBe(baseline['spectrum-panel'].width)
  expect(boxes['spectrum-panel'].height).toBe(baseline['spectrum-panel'].height)
  expect(boxes['spectrum-panel'].y - baseline['spectrum-panel'].y).toBeGreaterThan(0)
  expect(boxes['spectrum-panel'].y - baseline['spectrum-panel'].y).toBeLessThanOrEqual(controlBox.height - standardHeight + 1)
  const blend = (await page.getByTestId('energy-blend').boundingBox())!
  const session = (await page.getByTestId('session-diagnostics').boundingBox())!
  expect(blend.y).toBeGreaterThan(controlBox.y)
  expect(session.y+session.height).toBeLessThanOrEqual(controlBox.y)
  await page.screenshot({path:info.outputPath('energy-sustained-1400.png'), fullPage:true})
  await page.getByRole('radio', {name:'Fixed Loudness'}).click()
  await expect(controls.getByRole('spinbutton', {name:'Floor', exact:true})).toBeVisible()
  await expect(controls.getByRole('spinbutton', {name:'Ceiling', exact:true})).toBeVisible()
  expect(patches).toEqual([{energy_source:'loudness_fixed'}])
  await expect(controls.getByRole('spinbutton')).toHaveCount(2)
  spectrumY.push(await spectrumTop())
  await controls.getByRole('button', {name:'Increase Floor'}).click()
  await expect.poll(() => patches.length).toBe(2)
  expect(patches[1]).toEqual({lufs_floor:-29})
  const floor = controls.getByRole('spinbutton', {name:'Floor', exact:true})
  await expect(floor).toBeEnabled()
  await floor.press('ArrowUp')
  await expect(floor).toHaveValue('-28')
  expect(patches).toHaveLength(2)
  await floor.press('Enter')
  await expect.poll(() => patches.length).toBe(3)
  expect(patches[2]).toEqual({lufs_floor:-28})
  await expect(floor).toBeEnabled()
  await floor.press('Shift+ArrowUp')
  await floor.press('Enter')
  await expect.poll(() => patches.length).toBe(4)
  expect(patches[3]).toEqual({lufs_floor:-23})
  await expect(floor).toBeEnabled()
  socket().send(JSON.stringify({type:'frame', colour:{r:0,g:0,b:0}, last_energy_input:.86, mix:.7, loudness_momentary_lufs:-11}))
  await expect(page.getByTestId('energy-input-marker')).toHaveAttribute('title','Energy input: 86%')
  await page.screenshot({path:info.outputPath('energy-fixed-1400.png'), fullPage:true})
  await page.getByRole('radio', {name:'Adaptive Loudness'}).click()
  await expect(controls.getByRole('spinbutton')).toHaveCount(1)
  await expect(controls.getByRole('spinbutton', {name:'Adaptation', exact:true})).toBeVisible()
  spectrumY.push(await spectrumTop())
  await page.screenshot({path:info.outputPath('energy-adaptive-1400.png'), fullPage:true})
  await page.getByRole('radio', {name:'Sustained'}).click()
  await expect(controls.getByRole('spinbutton')).toHaveCount(0)
  spectrumY.push(await spectrumTop())
  expect(spectrumY.at(-1)).toBe(spectrumY[0])
  await expect(controls.getByText('No parameters for this source')).toHaveCount(0)
  const after = await geometry(page) as Boxes
  for (const key of ['track-block','colour-preview-size','floorplan-preview-size','status'] as const) expect(after[key]).toEqual(boxes[key])
  console.log('ENERGY_MEASUREMENTS',JSON.stringify({groupBox, widths, spectrumY, boxes, controlBox, blend, session, patches}))
  await expect(controls.getByRole('switch', {name:'Energy'})).toBeEnabled()
  await page.getByRole('radio', {name:'Sustained'}).focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('radio', {name:'Fixed Loudness'})).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByRole('radio', {name:'Fixed Loudness'})).toBeFocused()
  await page.getByRole('radio', {name:'Peak Envelope'}).click()
  await expect(controls.getByRole('button', {name:'Auto', exact:true})).toHaveAttribute('aria-pressed', 'true')
  await expect(controls.getByRole('spinbutton')).toHaveCount(0)
  await controls.getByRole('button', {name:'Manual', exact:true}).click()
  await expect(controls.getByRole('spinbutton', {name:'Attack (s)', exact:true})).toBeVisible()
  await expect(controls.getByRole('spinbutton', {name:'Release (s)', exact:true})).toBeVisible()
  await page.getByLabel('Editor mode').selectOption('standard')
  await expect(controls.getByRole('radiogroup')).toHaveCount(0)
  await expect(controls.getByRole('spinbutton')).toHaveCount(0)
  await page.getByLabel('Editor mode').selectOption('expert')
  await page.getByRole('link', {name:'Open Energy Profile ›'}).click()
  await expect(page.getByLabel('Energy source settings')).toBeVisible()
})

test('inactive energy control reserves the same compact rows', async ({page}, info) => {
  const socket = await setupPreview(page)
  await page.getByLabel('Editor mode').selectOption('expert')
  const block = page.getByTestId('live-energy-source')
  const before = (await block.boundingBox())!
  const spectrumY = (await page.getByTestId('spectrum-panel').boundingBox())!.y
  socket().send(JSON.stringify({type:'status', active_coupling_id:null, active_energy_profile_id:null}))
  await expect(block.getByText('No active coupling')).toBeVisible()
  for (const radio of await block.getByRole('radio').all()) await expect(radio).toBeDisabled()
  const after = (await block.boundingBox())!
  expect((await page.getByTestId('spectrum-panel').boundingBox())!.y - after.y - after.height)
    .toBe(spectrumY - before.y - before.height)
  await page.screenshot({path:info.outputPath('energy-inactive-1400.png'), fullPage:true})
})

for (const theme of ['light', 'dark'] as const) {
  test(`source parameters and switch fit on phones in ${theme}`, async ({page}, info) => {
    await setupPreview(page)
    let profile = {id:'e', name:'Spectrum RGB', energy_source:'sustained', lufs_floor:-30,
      lufs_ceiling:-8, adaptation_tau_s:60, peak_envelope_auto:true, peak_reshape_enabled:false}
    await page.route('**/api/energy-profiles/e', route => {
      profile = {...profile, ...route.request().postDataJSON()}
      return route.fulfill({json:profile})
    })
    await page.setViewportSize({width:390,height:844})
    await page.getByRole('button', {name:theme === 'light' ? 'Light' : 'Dark', exact:true}).click()
    await page.getByLabel('Editor mode').selectOption('expert')
    const card = page.getByTestId('live-preview-card')
    const fits = async () => {
      expect(await card.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    }
    await card.getByRole('radio', {name:'Fixed Loudness'}).click()
    await expect(card.getByRole('spinbutton', {name:'Floor',exact:true})).toBeEnabled()
    await fits()
    await card.getByRole('radio', {name:'Adaptive Loudness'}).click()
    await expect(card.getByRole('spinbutton', {name:'Adaptation',exact:true})).toBeEnabled()
    await fits()
    await card.getByRole('radio', {name:'Peak Envelope'}).click()
    await card.getByRole('button', {name:'Manual',exact:true}).click()
    await expect(card.getByRole('spinbutton', {name:'Attack (s)',exact:true})).toBeEnabled()
    await card.getByRole('checkbox', {name:'Reshape'}).click()
    await expect(card.getByRole('checkbox', {name:'Reshape'})).toBeChecked()
    await expect(card.getByRole('spinbutton', {name:'Reshape power',exact:true})).toBeEnabled()
    await fits()
    await card.screenshot({path:info.outputPath(`energy-parameters-mobile-${theme}.png`)})
    const toggle = card.getByRole('switch', {name:'Energy'})
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-checked','false')
    await expect(toggle).toBeEnabled()
    await expect(card.getByRole('spinbutton')).toHaveCount(0)
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-checked','true')
    await expect(card.getByRole('radio', {name:'Peak Envelope'})).toHaveAttribute('aria-checked','true')
    await expect(card.getByRole('spinbutton', {name:'Reshape power',exact:true})).toBeEnabled()
    await fits()
  })
}
