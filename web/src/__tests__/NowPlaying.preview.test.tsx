import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NowPlaying } from '../pages/NowPlaying'
import type { SocketStatus } from '../hooks/usePreviewSocket'
import { getAnalysers, getCouplings, getVirtualPlayers } from '../lib/api'

vi.mock('../lib/api', async importOriginal => ({
  ...await importOriginal<typeof import('../lib/api')>(),
  getEffects: vi.fn().mockResolvedValue([]),
  getEnergyProfiles: vi.fn().mockResolvedValue([]), getCouplings: vi.fn(), getAnalysers: vi.fn(), getVirtualPlayers: vi.fn(),
  getZoneChannels: vi.fn().mockResolvedValue([{ channel_id: 1, x: .5, y: 0, z: .5 }]),
  activateCoupling: vi.fn(), deactivateCoupling: vi.fn(), restartCouplingCava: vi.fn(),
}))

const status = {
  active_coupling_id: 'c', active_zone_id: 'z', active_energy_profile_id: 'e',
  active_player_type: null,
  sync_master_name: 'Living room', sync_master: 'aa:bb:cc:dd:ee:ff', applied_delay_ms: 1100,
  processes: { squeezelite: true }, bridge_connected: true,
  effect_type: 'spectrum_rgb', onset_method: 'combined',
} as SocketStatus
const props = { colour: { r: 1, g: 0, b: 0 }, channel_colours: [], onset: false, bars: [] }

afterEach(cleanup)
beforeEach(() => {
  vi.mocked(getCouplings).mockResolvedValue([{ id: 'c', name: 'Room', analyser_id: 'a', player_id: 'p' }] as never)
  vi.mocked(getAnalysers).mockResolvedValue([{ id: 'a', name: 'Canonical analyser', bars_source: 'pcm_pipeline', spectrum_backend: 'cavacore', onset_method: 'combined' }] as never)
  vi.mocked(getVirtualPlayers).mockResolvedValue([{ id: 'p', type: 'LMS' }] as never)
})

it('resolves the five technical status rows in order, preserving the preview layout', async () => {
  render(<NowPlaying {...props} status={status} />)
  const dl = screen.getByLabelText('Session status')
  await within(dl).findByText('CAVA Core')
  expect(within(dl).getByText('CAVA Core')).toBeInTheDocument()
  expect(within(dl).getByText('Combined')).toBeInTheDocument()
  expect(within(dl).queryByText('Analyser')).not.toBeInTheDocument()
  expect(within(dl).queryByText('Energy Profile')).not.toBeInTheDocument()
  expect(within(dl).queryByText('Canonical analyser')).not.toBeInTheDocument()
  expect([...dl.querySelectorAll('dt')].map(el => el.textContent)).toEqual([
    'Spectrum engine', 'Beat detection', 'Effect', 'Sync master', 'Delay',
  ])
  expect(within(dl).getByText('Living room')).toBeInTheDocument()
  expect(within(dl).getByText('aa:bb:cc:dd:ee:ff')).toBeInTheDocument()
  expect(within(dl).getByText('1100 ms')).toBeInTheDocument()
  expect(screen.queryByText('Onset method')).not.toBeInTheDocument()
  for (const id of ['colour-preview-size', 'floorplan-preview-size']) {
    expect(screen.getByTestId(id)).toHaveClass('aspect-square', 'w-full')
  }
  expect(screen.getByTestId('live-preview-grid')).toHaveClass('grid-cols-1', 'lg:grid-cols-3')
  expect(screen.getByLabelText('Light floorplan')).toHaveAttribute('viewBox', '0 0 200 200')
  expect(screen.getByText('front')).toBeInTheDocument()
  expect(screen.getByText('Bridge API')).toBeInTheDocument()
  expect(screen.queryByText('Bridge', { exact: true })).not.toBeInTheDocument()
  expect(within(dl).queryByText('Bridge API')).not.toBeInTheDocument()
  expect(screen.getByText('Energy blend').compareDocumentPosition(screen.getByText('Bridge API'))
    & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

it('shows muted placeholders while the analyser is unavailable', async () => {
  vi.mocked(getAnalysers).mockReturnValue(new Promise(() => {}))
  render(<NowPlaying {...props} status={status} />)
  await screen.findByText('squeezelite')
  const names = screen.getByLabelText('Session status').querySelectorAll('dd')
  for (const index of [0, 1]) {
    expect(names[index]).toHaveTextContent('—')
    expect(names[index].firstElementChild).toHaveClass('text-muted-foreground')
  }
})

it('shows squeezelite only for LMS and never an external CAVA process', async () => {
  const view = render(<NowPlaying {...props} status={status} />)
  await screen.findByText('squeezelite') // resolves player type from the entity list
  expect(screen.queryByText('cava', { exact: true })).not.toBeInTheDocument()
  view.rerender(<NowPlaying {...props} status={{ ...status, active_player_type: 'AirPlay' }} />)
  expect(screen.queryByText('squeezelite')).not.toBeInTheDocument()
  expect(screen.queryByText('cava', { exact: true })).not.toBeInTheDocument()
  expect(screen.getByText('AirPlay', { exact: true })).toBeInTheDocument()
})

it('resolves an AirPlay player from configuration when the websocket omits its type', async () => {
  vi.mocked(getVirtualPlayers).mockResolvedValue([{ id: 'p', type: 'AirPlay' }] as never)
  render(<NowPlaying {...props} status={status} />)
  await screen.findByText('AirPlay', { exact: true })
  expect(screen.queryByText('squeezelite')).not.toBeInTheDocument()
  expect(screen.queryByText('cava', { exact: true })).not.toBeInTheDocument()
})

it('keeps follower and latency warnings visible outside the five status rows', async () => {
  render(<NowPlaying {...props} status={{ ...status, follower_warning: 'Not synced', latency_warning: 'No latency data' }} />)
  await waitFor(() => expect(screen.getByText('Not synced')).toBeInTheDocument())
  expect(screen.getByText('No latency data')).toBeInTheDocument()
  expect(screen.getByLabelText('Session status').querySelectorAll('dt')).toHaveLength(5)
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
  expect(within(dl).getByText('n/a')).toHaveClass('text-muted-foreground')
  expect(within(dl).getByText('1100 ms')).toBeInTheDocument()
  await within(dl).findByText('CAVA Core')
})


it('shows raw spectrum, tick comparison, readouts and description from one pair', async () => {
  const bars = [.6,.6,.2,.2,.2,.2,.4,.4,.4,.4]
  const view = render(<NowPlaying {...props} bars={bars} normalised_bars={Array(10).fill(.33)} status={status} />)
  expect(screen.getByTestId('spectrum-legend')).toHaveTextContent('SpectrumNormalised')
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


it.each(['AirPlay', 'Spotify'])('keeps %s read-only even with stale LMS sync metadata', async playerType => {
  render(<NowPlaying {...props} status={{ ...status, active_player_type: playerType,
    follow_target_mac: 'stale-lms-target', track: {
      title: 'Receiver track', artist: 'Artist', position_s: 12, duration_s: 180, playing: true,
    },
  }} />)
  const dl = screen.getByLabelText('Session status')
  await within(dl).findByText('CAVA Core')
  expect(within(dl).getByText('n/a')).toHaveClass('text-muted-foreground')
  expect(within(dl).queryByText('Living room')).not.toBeInTheDocument()
  expect(within(dl).queryByText('aa:bb:cc:dd:ee:ff')).not.toBeInTheDocument()
  expect(screen.queryByTestId('track-controls')).not.toBeInTheDocument()
  for (const name of ['Previous', 'Play', 'Pause', 'Next']) {
    expect(screen.queryByRole('button', { name, exact: true })).not.toBeInTheDocument()
  }
  expect(screen.getByText('Receiver track')).toBeVisible()
  expect(screen.getByRole('progressbar', { name: 'Track position' })).toBeVisible()
})

it('derives Spotify diagnostics only from track presence', async () => {
  const spotify = { ...status, active_player_type: 'Spotify', airplay_receiving: true, track: null }
  const view = render(<NowPlaying {...props} status={spotify} />)
  const diagnostics = within(screen.getByTestId('session-diagnostics'))
  expect(diagnostics.getByText('Waiting for Spotify Connect…')).toHaveClass('bg-secondary')
  expect(diagnostics.queryByText('AirPlay', { exact: true })).not.toBeInTheDocument()
  expect(diagnostics.queryByText('squeezelite')).not.toBeInTheDocument()
  view.rerender(<NowPlaying {...props} status={{ ...spotify, airplay_receiving: false, track: {
    title: 'Paused track', artist: 'Artist', position_s: 12, duration_s: 180, playing: false,
  } }} />)
  // Presence, not track.playing or AirPlay's receiving flag, determines this badge.
  expect(diagnostics.getByText('Playing')).toHaveClass('bg-primary')
  expect(diagnostics.queryByText('Waiting for Spotify Connect…')).not.toBeInTheDocument()
  view.rerender(<NowPlaying {...props} status={spotify} />)
  expect(diagnostics.getByText('Waiting for Spotify Connect…')).toHaveClass('bg-secondary')
  expect(diagnostics.queryByText('Playing')).not.toBeInTheDocument()
  await screen.findByText('CAVA Core')
})

it('resolves Spotify from configuration when the websocket omits its type', async () => {
  vi.mocked(getVirtualPlayers).mockResolvedValue([{ id: 'p', type: 'Spotify' }] as never)
  render(<NowPlaying {...props} status={status} />)
  await screen.findByText('Spotify Connect', { exact: true })
  expect(screen.getByText('Waiting for Spotify Connect…')).toBeVisible()
  expect(screen.queryByTestId('track-controls')).not.toBeInTheDocument()
  expect(within(screen.getByLabelText('Session status')).getByText('n/a')).toBeVisible()
})
