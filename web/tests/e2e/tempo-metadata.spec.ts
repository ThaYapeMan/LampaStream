import { test, expect } from '@playwright/test'
import { setupPreview } from './preview-fixture'

test('owner corrections keep recording identity and use existing controls', async ({ page }) => {
  const position = { tempo: 128, beat_phase: .63, beat_index: 174, bar_phase: .16, bar_index: 43, confidence: .5, source: 'grid', beats_per_bar: 4, downbeat_measured: false }
  await setupPreview(page, () => ({ beat_position: position, tempo_bpm: 128, tempo_locked: true, tempo_confidence: .5 }))
  let state = { identity: 'fp:recording', confirmed: true, tempo: 128, phase_offset_s: 0, reason: null, resolved_tempo: null as null | { provider: string; fields: { tempo: number; phase_offset_s: number }; confidence: number; redistributable: boolean } }
  await page.route('**/api/tempo-metadata', route => route.fulfill({ json: state }))
  await page.route('**/api/tempo/correction', route => {
    const body = route.request().postDataJSON()
    expect(body.identity).toBe('fp:recording')
    state = { ...state, tempo: body.action === 'half' ? state.tempo / 2 : body.action === 'double' ? state.tempo * 2 : body.tempo ?? state.tempo,
      phase_offset_s: state.phase_offset_s + (body.nudge_ms ?? 0) / 1000 }
    state.resolved_tempo = { provider: 'owner', fields: { tempo: state.tempo, phase_offset_s: state.phase_offset_s }, confidence: 1, redistributable: false }
    return route.fulfill({ json: state })
  })
  await expect(page.getByRole('button', { name: 'Half tempo' })).toBeEnabled()
  await page.getByRole('button', { name: 'Half tempo' }).click()
  await expect(page.getByText(/Saved correction · 64.0 BPM/)).toBeVisible()
  await page.getByRole('button', { name: 'Double tempo' }).click()
  await page.getByRole('button', { name: 'Phase +20 ms' }).click()
  await expect(page.getByText(/phase 20 ms/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Phase +20 ms' })).toBeEnabled()
  await page.mouse.move(1, 1)
  await page.getByRole('region', { name: 'Track correction' }).screenshot({ path: '../.test-cache/beat-02-part-b/owner-controls.png' })
  await page.setViewportSize({ width: 390, height: 1000 })
  await page.mouse.move(1, 1)
  await page.getByRole('region', { name: 'Track correction' }).screenshot({ path: '../.test-cache/beat-02-part-b/owner-controls-phone.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('provider lifecycle and consent use generic checkbox rows', async ({ page }) => {
  await setupPreview(page)
  const base = { capabilities: ['tempo'], lookup_keys: ['fingerprint'], rate_limit: 0, ttl: 86400, requires_credentials: false, leaves_lan: false, consent: false }
  const providers = [
    { ...base, capabilities: ['tempo', 'phase_offset_s'], name: 'owner', enabled: true, status: 'active', always_enabled: true, test_only: false, redistributable: true, toggleable: false },
    { ...base, name: 'local-tags', enabled: true, status: 'active', always_enabled: true, test_only: false, redistributable: true, toggleable: false },
    { ...base, name: 'recorded-fixture', enabled: false, status: 'disabled', always_enabled: false, test_only: true, redistributable: false, toggleable: true },
    { ...base, name: 'songbpm', display_label: 'SongBPM', enabled: false, status: 'disabled', always_enabled: false, test_only: false, redistributable: false, leaves_lan: true, toggleable: true },
    { ...base, name: 'beatport', display_label: 'Beatport', enabled: false, status: 'disabled', always_enabled: false, test_only: false, redistributable: false, leaves_lan: true, toggleable: true },
  ]
  await page.route('**/api/metadata-providers', route => route.fulfill({ json: providers }))
  await page.route('**/api/music-settings', route => route.fulfill({ json: { providers, lastfm_enabled: false, api_key_configured: false, genre_mapping: { house: 'house' }, genres: ['house', 'other'], rules: [], transition_mode: 'crossfade', transition_duration_s: .7 } }))
  await page.route('**/api/metadata-providers/*', route => {
    const name = new URL(route.request().url()).pathname.split('/').pop()!
    const row = providers.find(item => item.name === name)!
    const body = route.request().postDataJSON()
    Object.assign(row, body)
    if ('enabled' in body) row.status = row.enabled ? 'active' : 'disabled'
    return route.fulfill({ json: row })
  })
  await page.getByRole('button', { name: 'Music settings', exact: true }).click()
  const owner = page.getByRole('region', { name: 'Provider owner' })
  await expect(owner.getByLabel(/Allow sharing owner/)).not.toBeChecked()
  await owner.getByLabel(/Allow sharing owner/).check()
  const recorded = page.getByRole('region', { name: 'Provider recorded-fixture' })
  await recorded.getByRole('checkbox').check()
  await expect(recorded.getByText('active', { exact: true })).toBeVisible()
  await recorded.getByRole('checkbox').uncheck()
  await expect(recorded.getByText('disabled', { exact: true })).toBeVisible()
  const songbpm = page.getByRole('region', { name: 'Provider songbpm' })
  await expect(songbpm.getByRole('checkbox')).toBeEnabled()
  await songbpm.getByRole('checkbox').check()
  await expect(songbpm.getByText('active', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Provider beatport' }).getByRole('checkbox')).not.toBeChecked()
  await page.getByTestId('metadata-providers').screenshot({ path: '../.test-cache/beat-02-part-b-sendback-1/provider-settings.png' })
})


test('provider references stay beside measured tempo without replacing it', async ({ page }) => {
  await setupPreview(page, () => ({ tempo_bpm: 143, tempo_locked: true,
    music: { genre: 'other', source: '', raw_tags: [], palette_id: '', energy_profile_id: '', manual: false,
      tempo_metadata: { identity: 'hint:recording', confirmed: false, tempo: 142,
        phase_offset_s: 0, reason: null, resolved_tempo: null,
        provider_rows: [{ provider: 'songbpm', label: 'SongBPM', fields: { tempo: 142 }, fetched_at: 1000, status: 'ready' },
          { provider: 'beatport', label: 'Beatport', fields: { tempo: 144 }, fetched_at: 1000, status: 'ready' }] } } }))
  await expect(page.getByTestId('track-tempo')).toHaveText('measured 143 BPM · SongBPM 142 · Beatport 144')
  await page.getByTestId('track-tempo').screenshot({ path: '../.test-cache/beat-02-part-b-sendback-1/provider-label.png' })
})
