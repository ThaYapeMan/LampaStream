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
  fireEvent.click(screen.getByRole('link', { name: 'Latency settings' })); expect(onOpenLatency).toHaveBeenCalled()
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
