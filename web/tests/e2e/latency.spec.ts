import { test, expect } from '@playwright/test'
test('Auto status, trim and fallback; LMS editor has no ALSA device', async ({page}) => {
  let fallback = false
  let savedTrim: number | undefined
  await page.route('**/api/**', route => {
    if (route.request().method() === 'PATCH') {
      savedTrim = route.request().postDataJSON().trim_ms
      return route.fulfill({json:{}})
    }
    if (new URL(route.request().url()).pathname === '/api/player-latencies') return route.fulfill({json:[{
      player_mac:'02:00:00:00:00:02', name:'Room', strategy:'auto', fixed_delay_ms:500,
      trim_ms:50, measured_delay_ms:1000, measured_at:123,
      status:{strategy:fallback ? 'fixed':'auto', applied_delay_ms:fallback ? 500:1050,
        median_residual_ms:900, player_delay_ms:100, trim_ms:50, sample_count:7,
        precision_ms:15, last_sample_time:123,
        state:fallback ? 'not measurable (sync group)':'stable',
        reason:fallback ? 'LMS reports a shared group position; using Fixed delay':null},
    }]})
    return route.fulfill({json:[]})
  })
  await page.routeWebSocket('**/ws/preview', ws => {
    ws.send(JSON.stringify({type:'status', sync_master:'02:00:00:00:00:02',
      sync_master_name:'Room', follow_mode:'manual', processes:{}}))
  })
  await page.goto('/')
  await page.getByRole('button', {name:'Players', exact:true}).click()
  await expect(page.getByRole('listbox', { name: 'Players', exact: true }).getByRole('option', { selected: true })).toContainText('Room')
  await expect(page.getByTestId('light-timing').getByText('In sync', {exact:true})).toBeVisible()
  await page.getByRole('button', {name:'Edit', exact:true}).click()
  await expect(page.getByText('Manual trim')).toBeVisible()
  await expect(page.getByText('Fixed delay (sync-group fallback)')).toBeVisible()
  await page.getByRole('dialog').getByRole('slider').nth(1).focus()
  await page.keyboard.press('ArrowRight')
  await page.getByRole('button', {name:'Save', exact:true}).click()
  await expect.poll(() => savedTrim).toBe(60)
  fallback = true
  await expect(page.getByText(/LMS reports one shared position/)).toBeVisible()
  await page.getByRole('button', {name:'Players', exact:true}).click()
  await page.getByRole('button', {name:'Add player', exact:true}).click()
  await expect(page.getByText('Player name', {exact:true})).toBeVisible()
  await expect(page.getByText('ALSA device', {exact:true})).toHaveCount(0)
})
