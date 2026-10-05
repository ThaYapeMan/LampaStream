import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NowPlaying } from '../pages/NowPlaying'
import type { SocketStatus } from '../hooks/usePreviewSocket'
import { getAnalysers, getCouplings, getVirtualPlayers, getEffects, getEnergyProfiles } from '../lib/api'

vi.mock('../lib/api', async importOriginal => ({
  ...await importOriginal<typeof import('../lib/api')>(),
  getEffects: vi.fn().mockResolvedValue([]),
  getEnergyProfiles: vi.fn().mockResolvedValue([]), getCouplings: vi.fn(), getAnalysers: vi.fn(), getVirtualPlayers: vi.fn(),
  getZoneChannels: vi.fn().mockResolvedValue([{ channel_id: 1, x: .5, y: 0, z: .5 }]),
  takeLights: vi.fn().mockResolvedValue({}), activateCoupling: vi.fn(), deactivateCoupling: vi.fn(), restartCouplingCava: vi.fn(),
}))

const status = {
  active_coupling_id: 'c', active_zone_id: 'z', active_energy_profile_id: 'e',
  active_player_type: null,
  sync_master_name: 'Living room', sync_master: 'aa:bb:cc:dd:ee:ff', applied_delay_ms: 1100,
  processes: { lms_player: true }, bridge_connected: true,
  effect_type: 'spectrum_rgb', onset_method: 'combined',
} as SocketStatus
const props = { colour: { r: 1, g: 0, b: 0 }, channel_colours: [], onset: false, bars: [] }

afterEach(cleanup)
beforeEach(() => {
  vi.mocked(getCouplings).mockResolvedValue([{ id: 'c', name: 'Room', analyser_id: 'a', player_id: 'p' }] as never)
  vi.mocked(getAnalysers).mockResolvedValue([{ id: 'a', name: 'Canonical analyser', band_normalise: true, bars_source: 'pcm_pipeline', spectrum_backend: 'cavacore', onset_method: 'combined' }] as never)
  vi.mocked(getVirtualPlayers).mockResolvedValue([{ id: 'p', type: 'LMS' }] as never)
})

it('groups analysis rows, names the effect, and uses quiet header status', async () => {
  vi.mocked(getEffects).mockResolvedValueOnce([{id:'fx', name:'Spectrum RGB', effect_type:'spectrum_rgb'}] as never)
  vi.mocked(getEnergyProfiles).mockResolvedValueOnce([{id:'e', name:'Room energy', high_energy_effect_id:'fx'}] as never)
  render(<NowPlaying {...props} status={status} />)
  const dl = screen.getByLabelText('Session status')
  await within(dl).findByText('CAVA Core')
  expect(within(dl).getByText('CAVA Core')).toBeInTheDocument()
  expect(within(dl).getByText('Combined')).toBeInTheDocument()
  expect(within(dl).queryByText('Analyser')).not.toBeInTheDocument()
  expect(within(dl).queryByText('Energy Profile')).not.toBeInTheDocument()
  expect(within(dl).queryByText('Canonical analyser')).not.toBeInTheDocument()
  expect([...dl.querySelectorAll('dt')].map(el => el.textContent)).toEqual([
    'Spectrum engine', 'Beat detection', 'Effect', 'Energy profile',
  ])
  expect(within(dl).queryByText('Sync master')).not.toBeInTheDocument()
  expect(within(dl).queryByText('Delay')).not.toBeInTheDocument()
  expect(within(dl).queryByText('1100 ms')).not.toBeInTheDocument()
  expect(screen.queryByText('Onset method')).not.toBeInTheDocument()
  expect(screen.getByTestId('colour-preview-size')).toHaveClass('h-4', 'w-4')
  expect(screen.getByTestId('live-preview-grid')).toHaveClass('grid-cols-1', 'lg:grid-cols-[minmax(0,11fr)_minmax(0,9fr)]')
  expect(screen.getByLabelText('Light floorplan')).toHaveAttribute('viewBox', '0 0 200 120')
  expect(screen.getByText('front')).toBeInTheDocument()
  expect(await within(dl).findByText('Spectrum RGB')).toHaveAttribute('title', 'spectrum_rgb')
  expect(within(dl).getByText('Room energy')).toBeInTheDocument()
  expect(within(dl).getByRole('link', {name:'Open Energy Profile ›'})).toHaveAttribute('href', '#energy-profiles/e')
  const session = screen.getByTestId('session-diagnostics')
  expect(within(session).getByText('Bridge connected')).toBeVisible()
  expect(within(session).getByText('LMS player running')).toBeVisible()
  expect(within(session).queryByRole('button')).not.toBeInTheDocument()
  expect(session.querySelectorAll('.bg-green-500')).toHaveLength(2)
  expect(screen.queryByText('Session', {exact:true})).not.toBeInTheDocument()

})

it('shows muted placeholders while the analyser is unavailable', async () => {
  vi.mocked(getAnalysers).mockReturnValue(new Promise(() => {}))
  render(<NowPlaying {...props} status={status} />)
  await screen.findByText('LMS player running')
  const names = screen.getByLabelText('Session status').querySelectorAll('dd')
  for (const index of [0, 1]) {
    expect(names[index]).toHaveTextContent('—')
    expect(names[index].firstElementChild).toHaveClass('text-muted-foreground')
  }
})

it('shows LMS player only for LMS and never an external CAVA process', async () => {
  const view = render(<NowPlaying {...props} status={status} />)
  await screen.findByText('LMS player running') // resolves player type from the entity list
  expect(screen.queryByText('cava', { exact: true })).not.toBeInTheDocument()
  view.rerender(<NowPlaying {...props} status={{ ...status, active_player_type: 'AirPlay' }} />)
  expect(screen.queryByText('LMS player running')).not.toBeInTheDocument()
  expect(screen.queryByText('cava', { exact: true })).not.toBeInTheDocument()
  expect(screen.getByText('AirPlay —', { exact: true })).toBeInTheDocument()
})

it('resolves an AirPlay player from configuration when the websocket omits its type', async () => {
  vi.mocked(getVirtualPlayers).mockResolvedValue([{ id: 'p', type: 'AirPlay' }] as never)
  render(<NowPlaying {...props} status={status} />)
  await screen.findByText('AirPlay —', { exact: true })
  expect(screen.queryByText('LMS player running')).not.toBeInTheDocument()
  expect(screen.queryByText('cava', { exact: true })).not.toBeInTheDocument()
})

it('keeps follower and latency warnings visible outside the three status rows', async () => {
  render(<NowPlaying {...props} status={{ ...status, follower_warning: 'Not synced', latency_warning: 'No latency data' }} />)
  await waitFor(() => expect(screen.getByText('Not synced')).toBeInTheDocument())
  expect(screen.getByText('No latency data')).toBeInTheDocument()
  expect(screen.getByLabelText('Session status').querySelectorAll('dt')).toHaveLength(4)
})


it('takes spectrum and beat detection from the analyser', async () => {
  vi.mocked(getAnalysers).mockResolvedValue([{
    id: 'a', name: 'Custom label', spectrum_backend: 'v2', onset_method: 'superflux',
  }] as never)
  render(<NowPlaying {...props} status={status} />)
  const dl = screen.getByLabelText('Session status')
  await within(dl).findByText('V2')
  expect(within(dl).getByText('SuperFlux')).toBeInTheDocument()
  expect(within(dl).queryByText('Combined')).not.toBeInTheDocument()
})


it('only exposes transport for LMS with a live follow target; AirPlay sync is n/a', async () => {
  const view = render(<NowPlaying {...props} status={{ ...status,
    active_player_type: 'LMS', follow_target_mac: 'aa:bb:cc:dd:ee:ff',
    follow_target_name: 'Living room',
  }} />)
  expect(screen.getByRole('group', { name: 'Controls the followed player (Living room)' })).toBeInTheDocument()
  view.rerender(<NowPlaying {...props} status={{ ...status, active_player_type: 'LMS', follow_target_mac: null }} />)
  expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  view.rerender(<NowPlaying {...props} status={{ ...status,
    active_player_type: 'AirPlay', follow_target_mac: 'stale',
  }} />)
  expect(screen.queryByRole('button', { name: 'Previous' })).not.toBeInTheDocument()
  const dl = screen.getByLabelText('Session status')
  expect(within(dl).queryByText('Sync master')).not.toBeInTheDocument()
  expect(within(dl).queryByText('1100 ms')).not.toBeInTheDocument()
  await within(dl).findByText('CAVA Core')
})


it('shows raw spectrum, tick comparison, readouts and description from one pair', async () => {
  const bars = [.6,.6,.2,.2,.2,.2,.4,.4,.4,.4]
  const view = render(<NowPlaying {...props} bars={bars} normalised_bars={Array(10).fill(.33)} status={status} />)
  await waitFor(() => expect(screen.getByTestId('spectrum-legend')).toHaveTextContent('RawNormalised'))
  expect(screen.getAllByTestId('spectrum-tick')).toHaveLength(10)
  expect(screen.getAllByTestId('spectrum-raw')[0]).toHaveStyle({ height: '60%' })
  expect(screen.getAllByTestId('spectrum-tick')[0].querySelector('line')).toHaveAttribute('y1', '67%')
  expect(screen.getAllByTestId('spectrum-tick')[0].querySelector('line')).toHaveAttribute('stroke-width', '5')
  expect(screen.getByRole('img', { name: /Spectrum bass 0.60.*normalised 0.33, 0.33, 0.33/ })).toBeInTheDocument()
  expect(screen.getAllByText('· 0.33')).toHaveLength(3)
  view.rerender(<NowPlaying {...props} bars={bars} status={status} />)
  expect(screen.queryByTestId('spectrum-legend')).not.toBeInTheDocument()
  expect(screen.queryByTestId('spectrum-tick')).not.toBeInTheDocument()
  await screen.findByText('CAVA Core')
})

it('fetches both effect links and displays a naturally converged Off blend as 100%', async () => {
  const api = await import('../lib/api')
  const onOpenEffect = vi.fn()
  vi.mocked(api.getEnergyProfiles).mockResolvedValueOnce([{ id: 'e', name: 'Trigger', energy_source: 'off', high_energy_effect_id: 'high', low_energy_effect_id: 'low' }] as never)
  vi.mocked(api.getEffects).mockResolvedValueOnce([{ id: 'high', name: 'High bands' }, { id: 'low', name: 'Low glow' }] as never)
  render(<NowPlaying {...props} status={status} mix={1 - 0.9 ** 200} onOpenEffect={onOpenEffect} />)
  const high = await screen.findByRole('link', { name: 'High bands' })
  high.click()
  expect(onOpenEffect).toHaveBeenCalledWith('high')
  expect(screen.getByRole('link', { name: 'Low glow' })).toBeVisible()
  expect(within(screen.getByTestId('energy-blend')).getByText('100%')).toBeVisible()
})

it.each(['reconnecting', 'failed'] as const)('warns about %s output and clears on recovery', async state => {
  const view = render(<NowPlaying {...props} status={{ ...status, bridge_connected: false,
    output_status: { state, reason: 'Light connection dropped' } }} />)
  expect(screen.getByTestId('lights-row')).toHaveTextContent(
    state === 'reconnecting' ? 'Reconnecting the lights' : 'Light output unavailable')
  expect(screen.getByTestId('lights-row')).toHaveTextContent('Light connection dropped')
  view.rerender(<NowPlaying {...props} status={{ ...status,
    output_status: { state: 'streaming', reason: null } }} />)
  expect(screen.getByTestId('lights-row')).toHaveTextContent('Following the music')
  await screen.findByText('CAVA Core')
})


it('released output explains ownership and explicitly takes lights', async () => {
  const api = await import('../lib/api')
  render(<NowPlaying {...props} status={{ ...status, bridge_connected: false,
    output_status: { state: 'released', reason: 'Stopped from the Hue app or another controller' } }} />)
  expect(screen.getByTestId('lights-row')).toHaveTextContent('Released')
  const button = screen.getByRole('button', { name: 'Take lights' })
  button.click()
  await waitFor(() => expect(api.takeLights).toHaveBeenCalledWith('c'))
  await screen.findByText('CAVA Core')
})


it.each([{}, {manual_energy_profile_id:'e'}, {manual_palette_id:'palette'}])('shows manual choice only for coupling overrides %j', async override => {
  vi.mocked(getCouplings).mockResolvedValueOnce([{id:'c', analyser_id:'a', player_id:'p', ...override}] as never)
  render(<NowPlaying {...props} status={status} />)
  await screen.findByText('CAVA Core')
  expect(!!screen.queryByText('Manual choice active')).toBe(Object.keys(override).length > 0)
})

it('draws the white outline only on the floorplan frame during onset', async () => {
  const view = render(<NowPlaying {...props} status={status} />)
  await screen.findByLabelText('Light floorplan')
  expect(screen.getByTestId('floorplan-frame')).toHaveAttribute('stroke', 'currentColor')
  view.rerender(<NowPlaying {...props} status={status} onset />)
  expect(screen.getByTestId('floorplan-frame')).toHaveAttribute('stroke', 'white')
  expect(screen.getByTestId('colour-preview-size')).not.toHaveClass('outline-white')
  view.rerender(<NowPlaying {...props} status={status} onset={false} />)
  expect(screen.getByTestId('floorplan-frame')).toHaveAttribute('stroke', 'currentColor')
})

it('uses warning dots for disconnected and stopped status', async () => {
  render(<NowPlaying {...props} status={{...status, bridge_connected:false, processes:{lms_player:false}}} />)
  const session = screen.getByTestId('session-diagnostics')
  expect(within(session).getByText('Bridge disconnected')).toBeVisible()
  expect(await within(session).findByText('LMS player stopped')).toBeVisible()
  expect(session.querySelectorAll('.bg-amber-500')).toHaveLength(2)
  expect(within(session).queryByRole('button')).not.toBeInTheDocument()
})

it.each([NaN, Infinity, null])('uses unavailable readouts for non-finite or missing energy %s', async value => {
  render(<NowPlaying {...props} status={status} sustained_energy={value} loudness_momentary_lufs={value} />)
  expect(screen.getByTestId('sustained-energy')).toHaveTextContent('—')
  expect(screen.getByTestId('momentary-loudness')).toHaveTextContent('— LUFS')
  expect(screen.getByTestId('sustained-energy')).toHaveClass('tabular-nums')
  await screen.findByText('CAVA Core')
})

it('reflects live manual-choice updates without changing Track colours or refetching', async () => {
  const view = render(<NowPlaying {...props} status={{...status, music:{manual:true, raw_tags:[], source:'Track tag', genre:'other'} as never}} />)
  expect(screen.getByText('Manual choice active')).toBeVisible()
  view.rerender(<NowPlaying {...props} status={{...status, music:{manual:false, raw_tags:[], source:'Track tag', genre:'other'} as never}} />)
  expect(screen.queryByText('Manual choice active')).not.toBeInTheDocument()
  await screen.findByText('CAVA Core')
})
