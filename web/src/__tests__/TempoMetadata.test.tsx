import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { OwnerTempo } from '../components/OwnerTempo'
import { MetadataProviders } from '../components/MetadataProviders'
import { correctTempo, getTempoMetadata, updateMetadataProvider, type MetadataProvider, type TempoMetadata } from '../lib/api'

vi.mock('../lib/api', () => ({ correctTempo: vi.fn(), getTempoMetadata: vi.fn(), updateMetadataProvider: vi.fn() }))
const state: TempoMetadata = { identity: 'fp:recording', confirmed: true, tempo: 128, phase_offset_s: 0, reason: null, resolved_tempo: null }
afterEach(() => { cleanup(); vi.restoreAllMocks() })
beforeEach(() => {
  vi.mocked(getTempoMetadata).mockResolvedValue(state)
  vi.mocked(correctTempo).mockClear().mockResolvedValue({ ...state, resolved_tempo: { provider: 'owner', fields: { tempo: 128 }, confidence: 1, redistributable: false } })
})
it('saves octave and phase corrections with the recording identity', async () => {
  render(<OwnerTempo active />)
  const button = await screen.findByRole('button', { name: 'Double tempo' })
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.click(button)
  await waitFor(() => expect(correctTempo).toHaveBeenCalledWith(expect.objectContaining({ identity: 'fp:recording', action: 'double' })))
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Phase +20 ms' }))
  await waitFor(() => expect(correctTempo).toHaveBeenCalledWith(expect.objectContaining({ action: 'nudge', nudge_ms: 20 })))
  expect(screen.queryByRole('button', { name: 'Back to automatic' })).not.toBeInTheDocument()
})
it('derives tap tempo locally and refuses unconfirmed identities', async () => {
  let now = 1000
  vi.spyOn(performance, 'now').mockImplementation(() => now)
  const view = render(<OwnerTempo active />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Tap tempo' })).toBeEnabled())
  for (let i = 0; i < 3; i++) { now = 1000 + i * 500; fireEvent.click(screen.getByRole('button', { name: /^Tap tempo/ })) }
  await waitFor(() => expect(correctTempo).toHaveBeenCalledWith(expect.objectContaining({ action: 'tap', tempo: 120 })))
  view.unmount()
  vi.mocked(getTempoMetadata).mockResolvedValue({ ...state, confirmed: false, reason: 'Waiting for audio fingerprint' })
  render(<OwnerTempo active />)
  expect(await screen.findByText('Waiting for audio fingerprint')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Half tempo' })).toBeDisabled()
})
it('uses generic provider toggles and consent without altering cached results', async () => {
  const base: MetadataProvider = { name: 'catalogue', capabilities: ['tempo'], lookup_keys: ['artist+title'], rate_limit: 1, ttl: 60, redistributable: true, requires_credentials: false, enabled: false, status: 'disabled', consent: false, leaves_lan: true, always_enabled: false, test_only: false, toggleable: true }
  vi.mocked(updateMetadataProvider).mockResolvedValue({ ...base, enabled: true, status: 'active' })
  render(<MetadataProviders initial={[base]} />)
  const row = screen.getByRole('region', { name: 'Provider catalogue' })
  fireEvent.click(within(row).getByRole('checkbox', { name: /catalogue.*disabled/ }))
  await waitFor(() => expect(updateMetadataProvider).toHaveBeenCalledWith('catalogue', { enabled: true }))
  await waitFor(() => expect(within(row).getByText('active')).toBeVisible())
  fireEvent.click(within(row).getByRole('checkbox', { name: /Allow sharing/ }))
  await waitFor(() => expect(updateMetadataProvider).toHaveBeenCalledWith('catalogue', { consent: true }))
})
