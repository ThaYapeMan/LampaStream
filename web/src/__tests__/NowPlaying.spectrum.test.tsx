import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NowPlaying } from '@/pages/NowPlaying'
import { getAnalysers, getCouplings, restartCouplingCava, updateAnalyser } from '@/lib/api'
import type { SocketStatus } from '@/hooks/usePreviewSocket'

vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(),
  getAnalysers: vi.fn(), getCouplings: vi.fn(), updateAnalyser: vi.fn(), restartCouplingCava: vi.fn(),
  getEffects: vi.fn().mockResolvedValue([]), getEnergyProfiles: vi.fn().mockResolvedValue([]),
  getVirtualPlayers: vi.fn().mockResolvedValue([]), getZoneChannels: vi.fn().mockResolvedValue([]),
}))
const analyser = { id: 'a', name: 'Combined', band_normalise: false }
const status = { processes: { lms_player: true }, bridge_connected: false, active_coupling_id: 'c', active_player_type: 'LMS', effect_type: 'spectrum_rgb',
  lower_cutoff_freq: 50, higher_cutoff_freq: 6623, bass_hz: 240, mid_hz: 2000 } as SocketStatus
const props = { colour: { r: 0, g: 0, b: 0 }, onset: false, bars: Array(10).fill(.2), normalised_bars: Array(10).fill(.33) }
const view = (s = status) => render(<NowPlaying {...props} status={s} />)
const ready = async () => waitFor(() => expect(screen.getByRole('switch', { name: 'Band normaliser' })).toBeEnabled())
beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks()
  vi.mocked(getCouplings).mockResolvedValue([{ id: 'c', name: 'Room', analyser_id: 'a' }] as never)
  vi.mocked(getAnalysers).mockResolvedValue([analyser] as never)
  vi.mocked(updateAnalyser).mockImplementation(async (_, body) => ({ ...analyser, ...body }) as never)
  vi.mocked(restartCouplingCava).mockResolvedValue({ ok: true })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('switches optimistically, prevents repeated presses and shows only enabled overlay values', async () => {
  let resolve!: (value: never) => void
  vi.mocked(updateAnalyser).mockImplementationOnce(() => new Promise(r => { resolve = r }))
  view(); await ready()
  const control = screen.getByRole('switch', { name: 'Band normaliser' })
  expect(control).toHaveAttribute('aria-checked', 'false')
  expect(screen.queryByTestId('spectrum-tick')).not.toBeInTheDocument()
  expect(screen.getByText('Balances bass, mid and treble colours · Analyser "Combined"')).toBeVisible()
  fireEvent.click(control)
  expect(control).toHaveAttribute('aria-checked', 'true'); expect(control).toBeDisabled()
  expect(screen.getAllByTestId('spectrum-tick')).toHaveLength(10)
  expect(screen.getAllByText('· 0.33')).toHaveLength(3)
  fireEvent.click(control)
  expect(updateAnalyser).toHaveBeenCalledTimes(1)
  expect(updateAnalyser).toHaveBeenCalledWith('a', { band_normalise: true })
  resolve({ ...analyser, band_normalise: true } as never)
  await waitFor(() => expect(control).toBeEnabled())
  fireEvent.click(control)
  await waitFor(() => expect(control).toBeEnabled())
  expect(updateAnalyser).toHaveBeenLastCalledWith('a', { band_normalise: false })
  expect(screen.queryByTestId('spectrum-tick')).not.toBeInTheDocument()
  expect(screen.queryByText('· 0.33')).not.toBeInTheDocument()
})
it('reverts a failed switch and reports one inline error', async () => {
  vi.mocked(updateAnalyser).mockRejectedValueOnce(Error('Could not save'))
  view(); await ready(); fireEvent.click(screen.getByRole('switch'))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save')
  expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
  expect(screen.queryByTestId('spectrum-tick')).not.toBeInTheDocument()
})
it('disables the switch without an active session', () => {
  view({ ...status, active_coupling_id: null })
  expect(screen.getByRole('switch')).toBeDisabled()
  expect(screen.getByText('Start a coupling to change this')).toBeVisible()
  fireEvent.click(screen.getByRole('switch')); expect(updateAnalyser).not.toHaveBeenCalled()
})
it('starts collapsed, shows live values, and remembers the disclosure per browser', () => {
  const rendered = view()
  const disclosure = screen.getByRole('button', { name: /Frequency range and bands/ })
  expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  expect(disclosure).toHaveTextContent('50 Hz – 6.6 kHz · 240 Hz · 2 kHz')
  expect(screen.getByTestId('low-cut-hz')).not.toBeVisible()
  rendered.rerender(<NowPlaying {...props} status={{ ...status, lower_cutoff_freq: 100 }} />)
  expect(disclosure).toHaveTextContent('100 Hz – 6.6 kHz')
  fireEvent.click(disclosure)
  expect(screen.getByTestId('low-cut-hz')).toBeVisible()
  expect(localStorage.getItem('lampastream.spectrumTuning')).toBe('1')
  rendered.unmount(); view()
  expect(screen.getByRole('button', { name: /Frequency range and bands/ })).toHaveAttribute('aria-expanded', 'true')
})
it('falls back to collapsed when storage reads fail and tolerates failed writes', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error('blocked') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('blocked') })
  view()
  const disclosure = screen.getByRole('button', { name: /Frequency range and bands/ })
  expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(disclosure); expect(disclosure).toHaveAttribute('aria-expanded', 'true')
})
it('applies all four fields once and shares reset and restore controls', async () => {
  view(); fireEvent.click(screen.getByRole('button', { name: /Frequency range and bands/ }))
  expect(screen.getAllByRole('button', { name: 'Apply', exact: true })).toHaveLength(1)
  for (const [id, value] of [['low-cut-hz', '100'], ['bass-hz', '300']] as const) {
    fireEvent.change(screen.getByTestId(id), { target: { value } }); fireEvent.blur(screen.getByTestId(id))
  }
  fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }))
  await screen.findByText('Applied.')
  expect(restartCouplingCava).toHaveBeenCalledTimes(1)
  expect(restartCouplingCava).toHaveBeenCalledWith('c', { lower_cutoff_freq: 100, higher_cutoff_freq: 6623, bass_hz: 300, mid_hz: 2000 })
  fireEvent.click(screen.getByRole('button', { name: 'Reset to saved' }))
  expect(screen.getByTestId('low-cut-hz')).toHaveValue(50); expect(screen.getByTestId('bass-hz')).toHaveValue(240)
  fireEvent.click(screen.getByRole('button', { name: 'Restore defaults' }))
  expect(screen.getByTestId('high-cut-hz')).toHaveValue(12000); expect(screen.getByTestId('bass-hz')).toHaveValue(250)
})

it('drafts response, applies live, resets to saved, restores 0.30 and updates summary', async () => {
  vi.mocked(getAnalysers).mockResolvedValue([{ ...analyser, spectrum_backend: 'v2', bar_falloff_s: .6 }] as never)
  view(); await ready()
  const disclosure = screen.getByRole('button', { name: /Frequency range and bands/ })
  expect(disclosure).toHaveTextContent('falloff 0.60 s')
  fireEvent.click(disclosure)
  const input = screen.getByTestId('bar-falloff-seconds')
  expect(input).toHaveValue(.6)
  expect((input as HTMLInputElement).value).toBe('0.60')
  fireEvent.change(input, { target: { value: '0.10' } }); fireEvent.blur(input)
  expect(screen.getByRole('slider', { name: 'Bar falloff' })).toHaveAttribute('aria-valuenow', '0.1')
  fireEvent.click(screen.getByTestId('reset-cutoffs')); expect(input).toHaveValue(.6)
  fireEvent.click(screen.getByTestId('restore-defaults-cutoffs')); expect(input).toHaveValue(.3)
  // Reset the frequency drafts; only response should be sent for this Apply.
  fireEvent.click(screen.getByTestId('reset-cutoffs'))
  fireEvent.change(input, { target: { value: '0.10' } }); fireEvent.blur(input)
  fireEvent.click(screen.getByTestId('apply-cutoffs'))
  await screen.findByText('Applied.')
  expect(restartCouplingCava).toHaveBeenCalledWith('c', { bar_falloff_s: .1 })
  expect(screen.getByTestId('reset-cutoffs')).toBeDisabled()
  fireEvent.click(disclosure); expect(disclosure).toHaveTextContent('falloff 0.10 s')
})

it('keeps saved response after a failed Apply and clamps or rejects number drafts', async () => {
  view(); await ready(); fireEvent.click(screen.getByRole('button', { name: /Frequency range and bands/ }))
  const input = screen.getByTestId('bar-falloff-seconds')
  fireEvent.change(input, { target: { value: '4' } }); fireEvent.blur(input); expect(input).toHaveValue(1)
  fireEvent.change(input, { target: { value: '0' } }); fireEvent.blur(input); expect(input).toHaveValue(.05)
  fireEvent.change(input, { target: { value: '' } }); fireEvent.blur(input); expect(input).toHaveValue(.05)
  vi.mocked(restartCouplingCava).mockRejectedValueOnce(Error('Response rejected'))
  fireEvent.click(screen.getByTestId('apply-cutoffs'))
  await screen.findByText('Response rejected')
  fireEvent.click(screen.getByTestId('reset-cutoffs')); expect(input).toHaveValue(.3)
})

it('shows the stored response but disables both controls for CAVA Core', async () => {
  vi.mocked(getAnalysers).mockResolvedValue([{ ...analyser, spectrum_backend: 'cavacore', bar_falloff_s: .8 }] as never)
  view(); await ready(); fireEvent.click(screen.getByRole('button', { name: /Frequency range and bands/ }))
  expect(screen.getByTestId('bar-falloff-seconds')).toHaveValue(.8)
  expect(screen.getByTestId('bar-falloff-seconds')).toBeDisabled()
  expect(screen.getByRole('slider', { name: 'Bar falloff' })).toHaveAttribute('data-disabled')
  expect(screen.getByText('V2 only; CAVA Core uses its own bar falloff.')).toBeVisible()
  expect(screen.getByText('falloff stored for V2')).toBeVisible()
  fireEvent.click(screen.getByTestId('restore-defaults-cutoffs'))
  expect(screen.getByTestId('bar-falloff-seconds')).toHaveValue(.3)
  expect(screen.getByTestId('apply-cutoffs')).toBeEnabled()
})
