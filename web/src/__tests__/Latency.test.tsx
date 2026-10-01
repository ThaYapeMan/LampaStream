import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LatencyEditorDialog } from '../pages/Latency'
import { Players } from '../pages/Players'
import * as api from '../lib/api'
vi.mock('../lib/api', async (original) => ({
  ...await original<typeof import('../lib/api')>(),
  getPlayerLatencies: vi.fn(), createPlayerLatency: vi.fn(), updatePlayerLatency: vi.fn(),
  getVirtualPlayers: vi.fn().mockResolvedValue([]), getCouplings: vi.fn().mockResolvedValue([]),
  getLmsPlayers: vi.fn().mockResolvedValue([]), discoverLms: vi.fn().mockResolvedValue([]),
}))
const entry: api.PlayerLatency = {
  player_mac: '02:00:00:00:00:02', name: 'Room', strategy: 'auto', fixed_delay_ms: 500,
  trim_ms: 50, measured_delay_ms: 1000, measured_at: 123,
  status: { strategy: 'auto', applied_delay_ms: 1050, median_residual_ms: 900,
    player_delay_ms: 100, trim_ms: 50, sample_count: 7, precision_ms: 15,
    last_sample_time: 123, state: 'stable', reason: null },
}
beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {configurable:true, value:vi.fn()})
  vi.clearAllMocks(); vi.mocked(api.getPlayerLatencies).mockResolvedValue([entry]) })
afterEach(() => {cleanup(); Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView")})
it('edits Auto timing and saves manual trim', async () => {
  render(<LatencyEditorDialog open entry={entry} onClose={() => {}} onSave={() => {}} />)
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByText('Manual trim')).toBeVisible()
  fireEvent.keyDown(within(dialog).getAllByRole('slider')[1], {key:'ArrowRight'})
  await userEvent.click(within(dialog).getByRole('button', {name:'Save', exact:true}))
  expect(api.updatePlayerLatency).toHaveBeenCalledWith(entry.player_mac,
    {name:'Room', strategy:'auto', fixed_delay_ms:500, trim_ms:60})
})
it('offers None, Fixed and Auto', async () => {
  render(<LatencyEditorDialog open onClose={() => {}} onSave={() => {}} />)
  fireEvent.keyDown(within(screen.getByRole('dialog')).getByRole('combobox'), {key:'ArrowDown'})
  expect(screen.getByRole('option', {name:'None'})).toBeVisible()
  expect(screen.getByRole('option', {name:'Fixed'})).toBeVisible()
  await userEvent.click(screen.getByRole('option', {name:'Auto'}))
  expect(screen.getByText('Manual trim')).toBeVisible()
})
it('has no obsolete ALSA control in the LMS editor', async () => {
  render(<Players />)
  await userEvent.click(await screen.findByRole('button', {name:'Add player', exact:true}))
  expect(screen.queryByText('ALSA device')).not.toBeInTheDocument()
  expect(screen.getByText('Player name')).toBeVisible()
})
it('offers AirPlay Auto with its fixed fallback', async () => {
  vi.mocked(api.getPlayerLatencies).mockResolvedValue([{ ...entry,
    status: { ...entry.status!, source: 'airplay', early_delivery_ms: 500, median_processing_ms: 125 } }])
  render(<LatencyEditorDialog open entry={entry} airplay onClose={() => {}} onSave={() => {}} />)
  fireEvent.keyDown(within(screen.getByRole('dialog')).getByRole('combobox'), { key: 'ArrowDown' })
  expect(screen.getByRole('option', { name: 'Auto' })).toBeVisible()
  expect(screen.getByText('Fixed delay (fallback)')).toBeVisible()
})
