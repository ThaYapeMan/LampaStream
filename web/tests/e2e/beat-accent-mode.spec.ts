import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('live beat accent modes preserve block geometry and measured tempo', async ({ page }, info) => {
  let coupling = {id:'c', name:'Room', analyser_id:'a', player_id:'p', energy_profile_id:'e', beat_accent_mode:'onset'}
  let profile = {id:'e', name:'Spectrum RGB', agc_max_gain:64, onset_gain_floor:.3}
  const changes: unknown[] = []
  await setupPreview(page, () => ({ beat_accent_mode:'onset', tempo_bpm:145, agc_gain:64, agc_max_gain:64 }))
  await page.route('**/api/couplings/c', async route => {
    const body = route.request().postDataJSON(); changes.push(body)
    coupling = {...coupling, ...body}; await route.fulfill({json:coupling})
  })
  await page.route('**/api/energy-profiles/e', async route => {
    const body = route.request().postDataJSON(); changes.push(body)
    profile = {...profile, ...body}; await route.fulfill({json:profile})
  })
  await page.getByLabel('Editor mode').selectOption('expert')
  const group = page.getByRole('radiogroup', {name:'Beat accent'})
  await expect(group).toBeVisible()
  const baseline = await page.getByTestId('light-timing').evaluate(el => ({height:el.getBoundingClientRect().height, width:el.getBoundingClientRect().width}))
  for (const mode of ['Off', 'Onset', 'Tracker']) {
    await group.getByRole('radio', {name:mode, exact:true}).click()
    await expect(group.getByRole('radio', {name:mode, exact:true})).toHaveAttribute('aria-checked','true')
    await expect(page.getByTestId('track-block')).toContainText('measured 145 BPM')
    expect(await page.getByTestId('light-timing').evaluate(el => ({height:el.getBoundingClientRect().height, width:el.getBoundingClientRect().width}))).toEqual(baseline)
    await page.getByTestId('light-timing').screenshot({path:info.outputPath(`beat-accent-${mode.toLowerCase()}-1400.png`)})
  }
  await expect(page.getByText('AGC 64.0× (capped)', {exact:true})).toBeVisible()
  await page.getByRole('button', {name:'Increase AGC ceiling'}).click()
  await expect.poll(() => changes.at(-1)).toEqual({agc_max_gain:72})
  await page.getByRole('button', {name:'Increase Trigger floor at ceiling'}).click()
  await expect.poll(() => changes.at(-1)).toEqual({onset_gain_floor:.35})
  expect(changes.slice(0,3)).toEqual([{beat_accent_mode:'off'}, {beat_accent_mode:'onset'}, {beat_accent_mode:'tracker'}])
})
