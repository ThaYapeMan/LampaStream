import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Latency } from '../pages/Latency'
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
it('shows Auto live status and saves manual trim', async () => {
  render(<Latency syncMaster={entry.player_mac} syncMasterName="Room" followMode="manual" />)
  expect(await screen.findByText('Followed player:')).toBeVisible()
  expect(screen.getByText('stable · 1050 ms')).toBeVisible()
  expect(screen.getByText('Residual: 900 ms · Player Delay: 100 ms')).toBeVisible()
  expect(screen.getByText('Trim: 50 ms · Samples: 7 · Precision: ±15 ms')).toBeVisible()
  await userEvent.click(screen.getByRole('button', {name:'Edit'}))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByText('Manual trim')).toBeVisible()
  fireEvent.keyDown(within(dialog).getAllByRole('slider')[1], {key:'ArrowRight'})
  await userEvent.click(within(dialog).getByRole('button', {name:'Save', exact:true}))
  expect(api.updatePlayerLatency).toHaveBeenCalledWith(entry.player_mac,
    {name:'Room', strategy:'auto', fixed_delay_ms:500, trim_ms:60})
})
it('shows sync-group fallback and retains the sync-master label', async () => {
  vi.mocked(api.getPlayerLatencies).mockResolvedValue([{...entry,
    status:{...entry.status!, strategy:'fixed', state:'not measurable (sync group)',
      applied_delay_ms:500, reason:'LMS reports a shared group position; using Fixed delay'}}])
  render(<Latency syncMaster={entry.player_mac} syncMasterName="Room" followMode="sync_group" />)
  expect(await screen.findByText('Sync master detected:')).toBeVisible()
  expect(screen.getByText('Strategy in effect: fixed')).toBeVisible()
  expect(screen.getByText('LMS reports a shared group position; using Fixed delay')).toBeVisible()
})
it('offers None, Fixed and Auto', async () => {
  render(<Latency syncMaster={null} syncMasterName={null} />)
  await screen.findByText('stable · 1050 ms')
  await userEvent.click(screen.getByRole('button', {name:'Add entry', exact:true}))
  fireEvent.keyDown(within(screen.getByRole('dialog')).getByRole('combobox'), {key:'ArrowDown'})
  expect(screen.getByRole('option', {name:'None'})).toBeVisible()
  expect(screen.getByRole('option', {name:'Fixed'})).toBeVisible()
  await userEvent.click(screen.getByRole('option', {name:'Auto'}))
  expect(screen.getByText('Manual trim')).toBeVisible()
})
it('has no obsolete ALSA control in the LMS editor', async () => {
  render(<Players />)
  await userEvent.click(await screen.findByRole('button', {name:'New virtual player', exact:true}))
  expect(screen.queryByText('ALSA device')).not.toBeInTheDocument()
  expect(screen.getByText('Player name')).toBeVisible()
})
