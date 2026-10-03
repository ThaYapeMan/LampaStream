import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { LightTiming } from '@/components/LightTiming'
import { createPlayerLatency, updatePlayerLatency, type PlayerLatency } from '@/lib/api'
import type { SocketStatus } from '@/hooks/usePreviewSocket'
vi.mock('@/lib/api', () => ({ createPlayerLatency: vi.fn(), updatePlayerLatency: vi.fn() }))
const entry: PlayerLatency = { player_mac: 'aa', name: 'Study', strategy: 'auto', fixed_delay_ms: 2000, trim_ms: 0, measured_delay_ms: 2243, measured_at: 100, status: { strategy: 'auto', state: 'stable', applied_delay_ms: 2243, median_residual_ms: 2243, player_delay_ms: 0, trim_ms: 0, sample_count: 7, precision_ms: 48, last_sample_time: 100, reason: null, samples: [2210, 2268, 2243].map((residual_ms, i) => ({ residual_ms, timestamp: 98 + i })) } }
const status = (e: PlayerLatency | null = entry) => ({ follow_target_mac: 'aa', follow_target_name: 'Study', applied_delay_ms: 2243, light_timing: e, track: { playing: false } } as SocketStatus)
beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); vi.mocked(updatePlayerLatency).mockResolvedValue(entry); vi.mocked(createPlayerLatency).mockResolvedValue(entry) })
afterEach(cleanup)
it.each([
  ['stable', 'In sync', /Lights wait this long/], ['measuring', 'Measuring', /The lights keep the last good delay/], ['idle', 'Paused', /Measuring resumes when playback starts/], ['not measurable (sync group)', 'Can’t measure', /Manual — fixed player/],
])('shows auto %s with icon, wording and Details closed', (state, label, text) => {
  render(<LightTiming status={status({ ...entry, status: { ...entry.status!, state } })} />)
  expect(screen.getByText(label).querySelector('svg')).toBeInTheDocument()
  expect(screen.getByText(text)).toBeVisible()
  expect(screen.getByText('Details').closest('details')).not.toHaveAttribute('open')
  if (state === 'stable') { expect(screen.getByRole('img', { name: /Last 3 measurements, median 2243.*precision ±48/ })).toBeVisible(); expect(screen.getByText('Steady to within ±48 ms')).toBeVisible() }
  if (state === 'measuring') expect(screen.getByRole('img', { name: '7 of 7 measurements' })).toBeVisible()
})
it.each([['fixed', 'Fixed', /A fixed delay/], ['none', 'No delay', /without a delay/], ['missing', 'Not set up', /has not been set up/]])('offers auto for %s', async (strategy, label, text) => {
  render(<LightTiming status={status(strategy === 'missing' ? null : { ...entry, strategy })} />)
  expect(screen.getAllByText(label)[0].querySelector('svg')).toBeInTheDocument()
  expect(screen.getByText(text)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Measure automatically' }))
  await screen.findByText('Saved · measuring automatically')
  if (strategy === 'missing') expect(createPlayerLatency).toHaveBeenCalledWith({ player_mac: 'aa', name: 'Study', strategy: 'auto' })
  else expect(updatePlayerLatency).toHaveBeenCalledWith('aa', { strategy: 'auto' })
})
it('persists collapse, keeps applied delay visible and opens settings', () => {
  const onOpenLatency = vi.fn()
  const view = render(<LightTiming status={status()} onOpenLatency={onOpenLatency} />)
  const button = screen.getByRole('button', { name: 'Light timing' })
  fireEvent.click(button)
  expect(button).toHaveAttribute('aria-expanded', 'false')
  expect(document.getElementById(button.getAttribute('aria-controls')!)).not.toBeVisible()
  expect(screen.getByText('2.24 s')).toBeVisible()
  expect(localStorage.getItem('lightTimingOpen')).toBe('0')
  view.unmount(); render(<LightTiming status={status()} onOpenLatency={onOpenLatency} />)
  expect(screen.getByRole('button', { name: 'Light timing' })).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByRole('link', { name: 'Player settings' })).toHaveAttribute('href', '/players?player=aa')
  fireEvent.click(screen.getByRole('link', { name: 'Player settings' })); expect(onOpenLatency).toHaveBeenCalled()
})
it('defaults open when storage throws and tolerates writing failure', () => {
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error('blocked') })
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('blocked') })
  render(<LightTiming status={status()} />)
  const button = screen.getByRole('button', { name: 'Light timing' })
  expect(button).toHaveAttribute('aria-expanded', 'true'); fireEvent.click(button)
  expect(button).toHaveAttribute('aria-expanded', 'false'); get.mockRestore(); set.mockRestore()
})
it('steps immediately by 10 ms, saves, confirms and holds optimistic trim against stale snapshots', async () => {
  let resolve!: (value: PlayerLatency) => void
  vi.mocked(updatePlayerLatency).mockImplementationOnce(() => new Promise(r => { resolve = r }))
  const view = render(<LightTiming status={status()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Lights 10 milliseconds earlier' }))
  expect(screen.getByLabelText('Fine-tune by ear')).toHaveTextContent('-10 ms')
  resolve(entry)
  await screen.findByText('Saved · lights earlier by 10 ms')
  view.rerender(<LightTiming status={status({ ...entry })} />)
  expect(screen.getByLabelText('Fine-tune by ear')).toHaveTextContent('-10 ms')
  fireEvent.click(screen.getByRole('button', { name: 'Lights 10 milliseconds earlier' }))
  await screen.findByText('Saved · lights earlier by 20 ms')
  expect(updatePlayerLatency).toHaveBeenLastCalledWith('aa', { trim_ms: -20 })
  fireEvent.click(screen.getByRole('button', { name: 'Lights 10 milliseconds later' }))
  await screen.findByText('Saved · lights earlier by 10 ms')
})
it.each([-1000, 1000])('enforces the %s ms limit', async trim_ms => {
  render(<LightTiming status={status({ ...entry, trim_ms })} />)
  expect(screen.getByRole('button', { name: trim_ms < 0 ? 'Lights 10 milliseconds earlier' : 'Lights 10 milliseconds later' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: trim_ms < 0 ? 'Lights 10 milliseconds later' : 'Lights 10 milliseconds earlier' }))
  await waitFor(() => expect(updatePlayerLatency).toHaveBeenCalledWith('aa', { trim_ms: trim_ms < 0 ? -990 : 990 }))
})
it('reports save errors and restores the previous trim', async () => {
  vi.mocked(updatePlayerLatency).mockRejectedValueOnce(Error('Save failed'))
  render(<LightTiming status={status()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Lights 10 milliseconds later' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Save failed')
  expect(screen.getByLabelText('Fine-tune by ear')).toHaveTextContent('0 ms')
})
it.each([
  ['stable', 'auto', 'In sync', /Lights follow measured audio play times/],
  ['measuring', 'auto', 'Measuring', /The lights keep the last good delay/],
  ['idle', 'auto', 'Paused', /Measuring resumes when playback starts/],
  ['idle', 'fixed', 'Fixed', /A fixed delay/],
  ['not measurable', 'auto', 'Can’t measure', /Audio delivery stalled/],
])('shows AirPlay %s/%s and processing breakdown', (state, strategy, label, wording) => {
  const airplay = { ...entry, strategy, status: { ...entry.status!, state, source: 'airplay' as const,
    early_delivery_ms: 500, median_processing_ms: 125, reason: 'Audio delivery stalled',
    samples: [120, 125, 130].map((processing_ms, i) => ({ processing_ms, timestamp: 98 + i })) } }
  render(<LightTiming status={{ ...status(airplay), active_player_type: 'AirPlay',
    timing_player_mac: 'aa', timing_player_name: 'AirPlay receiver', follow_target_mac: null }} />)
  expect(screen.getByText(label).querySelector('svg')).toBeInTheDocument()
  expect(screen.getByText(wording)).toBeVisible()
  fireEvent.click(screen.getByText('Details'))
  expect(screen.getByText('Measured early arrival (p5)')).toBeInTheDocument()
  expect(screen.getByText('Processing (P)')).toBeInTheDocument()
  expect(screen.queryByText('Player Delay (set in LMS)')).not.toBeInTheDocument()
  if (state === 'stable') expect(screen.getByRole('img', { name: /Last 3 measurements, median 125/ })).toBeVisible()
})
it('fine-tunes the AirPlay virtual player and switches Fixed to Auto', async () => {
  const e = { ...entry, player_mac: 'airplay', status: { ...entry.status!, source: 'airplay' as const } }
  const view = render(<LightTiming status={{ ...status(e), active_player_type: 'AirPlay',
    timing_player_mac: 'airplay', timing_player_name: 'AirPlay receiver' }} />)
  fireEvent.click(screen.getByRole('button', { name: 'Lights 10 milliseconds earlier' }))
  await screen.findByText('Saved · lights earlier by 10 ms')
  expect(updatePlayerLatency).toHaveBeenCalledWith('airplay', { trim_ms: -10 })
  view.rerender(<LightTiming status={{ ...status({ ...e, strategy: 'fixed' }), active_player_type: 'AirPlay',
    timing_player_mac: 'airplay', timing_player_name: 'AirPlay receiver' }} />)
  fireEvent.click(screen.getByRole('button', { name: 'Measure automatically' }))
  await screen.findByText('Saved · measuring automatically')
  expect(updatePlayerLatency).toHaveBeenCalledWith('airplay', { strategy: 'auto' })
})

it.each([false, true])('shows honest AirPlay lag and recovery in Players view=%s', (playersView) => {
  const e: PlayerLatency = { ...entry, trim_ms: 0, status: { ...entry.status!,
    source: 'airplay', state: 'lagging', early_delivery_ms: 0, median_processing_ms: 125,
    lag_ms: 125, applied_delay_ms: 0,
    safety_message: 'Early delivery was too much for this sender and has been switched off' } }
  render(<LightTiming playersView={playersView} status={{ ...status(e), active_player_type: 'AirPlay', applied_delay_ms: 0 }} />)
  expect(screen.getByText('Lights are about 125 ms behind the sound')).toBeVisible()
  expect(screen.getByText('Lights behind')).toBeVisible()
  expect(screen.queryByText('In sync')).not.toBeInTheDocument()
  expect(screen.getByText('Early delivery was too much for this sender and has been switched off')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Lights 10 milliseconds earlier' })).toBeDisabled()
})

it('shows the recovery message even before a latency entry exists', () => {
  render(<LightTiming status={{ ...status(null), active_player_type: 'AirPlay',
    latency_warning: 'Early delivery was too much for this sender and has been switched off' }} />)
  expect(screen.getByText('Early delivery was too much for this sender and has been switched off')).toBeVisible()
})

it.each([
  ['early tap', 'stable', 500, 0, 'Lights on time'],
  ['early tap', 'lagging', 20, 78, 'Lights about 78 ms behind'],
  ['pipe fallback', 'lagging', 0, 98, 'Lights about 98 ms behind'],
] as const)('shows measured %s timing and Details', (source, state, lead, lag, wording) => {
  render(<LightTiming status={{ ...status(), active_player_type: 'AirPlay', light_timing: {
    ...entry, status: { ...entry.status!, source: 'airplay', audio_source: source, state,
      early_delivery_ms: lead, lead_p5_ms: lead, lead_p50_ms: lead + 10,
      median_processing_ms: 98, lag_ms: lag, tap_drop_count: 7 },
  } }} />)
  expect(screen.getByText(wording)).toBeVisible()
  fireEvent.click(screen.getByText('Details'))
  expect(screen.getByText(`Source: ${source} · Tap dropped records: 7`)).toBeVisible()
  if (source === 'early tap') expect(screen.getByText(`Audio arrives about ${lead + 10} ms early (p5 ${lead} ms)`)).toBeVisible()
  else expect(screen.getByText('Audio arrives at playout time')).toBeVisible()
  const earlier = screen.getByRole('button', { name: 'Lights 10 milliseconds earlier' })
  if (lead <= 98) expect(earlier).toBeDisabled()
  else expect(earlier).toBeEnabled()
})
it.each([
  ['scheduled', null, 'Head start 486 ms · processing 19 ms · fine-tune +0 ms'],
  ['fallback', 'Not enough head start, using delay instead', 'Not enough head start, using delay instead'],
  ['unavailable', 'Head start needs sync-group mode', 'Head start needs sync-group mode'],
] as const)('shows LMS %s timing in the existing card', (state, reason, text) => {
  render(<LightTiming status={{ ...status(), lms_timing: { state, reason, lead_p5_ms: 486, median_processing_ms: 19 } }} />)
  expect(screen.getByTestId('lms-timing')).toHaveTextContent(text)
  if (state === 'scheduled') expect(screen.getByText('Scheduled · LMS head start')).toBeVisible()
})
