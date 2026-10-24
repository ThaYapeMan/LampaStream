import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor
} from '@testing-library/react'
import { Players } from '@/pages/Players'
import lyrionAsset from '@/assets/lyrion-icon.svg'
import { buildPlayerRows } from '@/components/PlayersDetail'
import { readRoute } from '@/App'
import * as api from '@/lib/api'
import type { SocketStatus } from '@/hooks/usePreviewSocket'
vi.mock('@/lib/api', async (original) => ({
  ...(await original<typeof api>()),
  getVirtualPlayers: vi.fn(),
  listLmsPlayers: vi.fn().mockResolvedValue([]),
  getPlayerLatencies: vi.fn(),
  getCouplings: vi.fn().mockResolvedValue([]),
  createPlayerLatency: vi.fn(),
  updateVirtualPlayer: vi.fn(),
  updatePlayerLatency: vi.fn(),
  deletePlayerLatency: vi.fn(),
  deleteVirtualPlayer: vi.fn()
}))
const lms = {
  id: 'lms',
  type: 'LMS',
  player_name: 'LampaStream LMS',
  display_name: '',
  player_mac: '01',
  lms_host: 'lms.local',
  lms_port: 9000,
  follow_player_mac: 'study',
  follow_mode: 'manual'
} as api.VirtualPlayer
const airplay = {
  ...lms,
  id: 'airplay',
  type: 'AirPlay',
  player_name: 'LampaStream',
  player_mac: 'air',
  follow_player_mac: ''
}
const timing = (
  mac: string,
  name: string,
  strategy = 'auto',
  state = 'stable'
): api.PlayerLatency => ({
  player_mac: mac,
  name,
  strategy,
  fixed_delay_ms: 1100,
  trim_ms: 0,
  measured_delay_ms: 2240,
  measured_at: 1,
  status: {
    state,
    strategy,
    applied_delay_ms:
      strategy === 'none' ? 0 : strategy === 'fixed' ? 1100 : 2240,
    median_residual_ms: 2240,
    player_delay_ms: 0,
    trim_ms: 0,
    sample_count: 7,
    precision_ms: 20,
    last_sample_time: 1,
    reason: null
  }
})
let players: api.VirtualPlayer[], entries: api.PlayerLatency[]
beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
  players = [lms, airplay]
  entries = [
    timing('study', 'Study (Sonos)'),
    timing('air', 'AirPlay', 'fixed'),
    timing('port', 'Sonos Port', 'fixed')
  ]
  vi.mocked(api.getVirtualPlayers).mockImplementation(async () => [...players])
  vi.mocked(api.getPlayerLatencies).mockImplementation(async () => [...entries])
  vi.mocked(api.updatePlayerLatency).mockImplementation(async (mac, patch) => {
    const e = entries.find((e) => e.player_mac === mac)!
    Object.assign(e, patch)
    e.status = undefined
    return { ...e }
  })
  vi.mocked(api.createPlayerLatency).mockImplementation(async (input) => {
    const e = { ...timing(input.player_mac, input.name || ''), ...input }
    entries.push(e)
    return e
  })
  vi.mocked(api.deleteVirtualPlayer).mockImplementation(async (id) => {
    players = players.filter((p) => p.id !== id)
  })
  vi.mocked(api.deletePlayerLatency).mockImplementation(async (mac) => {
    entries = entries.filter((e) => e.player_mac !== mac)
  })
})
afterEach(cleanup)
it('groups by followed MAC, preserving timings after removal and resolving live sync groups', () => {
  expect(
    buildPlayerRows(players, entries, null)
      .filter((r) => r.group === 'Other timings')
      .map((r) => r.name)
  ).toEqual(['Sonos Port'])
  expect(
    buildPlayerRows([airplay], entries, null)
      .filter((r) => r.group === 'Other timings')
      .map((r) => r.name)
  ).toEqual(['Study (Sonos)', 'Sonos Port'])
  expect(
    buildPlayerRows(
      [{ ...lms, follow_mode: 'sync_group' }],
      entries,
      { timing_player_mac: 'port' } as SocketStatus,
      'lms'
    )
      .filter((r) => r.group === 'Other timings')
      .map((r) => r.mac)
  ).not.toContain('port')
})
it.each([
  ['auto', 'stable', 'In sync, 2.24 seconds'],
  ['auto', 'measuring', 'Measuring, 2.24 seconds'],
  ['auto', 'idle', 'Idle, 2.24 seconds'],
  ['fixed', 'stable', 'Fixed, 1.10 seconds'],
  ['none', 'stable', 'No delay, 0.00 seconds']
])(
  'shows row text and applied chip for %s / %s',
  async (strategy, state, chip) => {
    entries[0] = timing('study', 'Study (Sonos)', strategy, state)
    render(<Players />)
    const row = await screen.findByRole('option', { name: /LampaStream LMS/ })
    expect(row).toHaveTextContent('Follows Study (Sonos)')
    expect(within(row).getByLabelText(chip)).toBeVisible()
    expect(
      screen.getByRole('option', { name: /Joins your AirPlay groups/ })
    ).toBeVisible()
    expect(
      screen.getByRole('option', { name: /Sonos Port/ })
    ).toHaveTextContent('Not followed right now')
  }
)
it('defaults to first player, navigates by keyboard and persists selection', async () => {
  const view = render(<Players />)
  const first = await screen.findByRole('option', { selected: true })
  expect(first).toHaveTextContent('LampaStream LMS')
  fireEvent.keyDown(first, { key: 'ArrowDown' })
  expect(screen.getByRole('option', { selected: true })).toHaveTextContent(
    'Joins your AirPlay groups'
  )
  expect(screen.getAllByTestId('light-timing')).toHaveLength(1)
  expect(localStorage.getItem('lampastream.selectedPlayer')).toBe('airplay')
  expect(document.activeElement).toBe(
    screen.getByRole('option', { selected: true })
  )
  view.unmount()
  render(<Players />)
  expect(
    await screen.findByRole('option', { selected: true })
  ).toHaveTextContent('Joins your AirPlay groups')
  fireEvent.keyDown(screen.getByRole('option', { selected: true }), {
    key: 'ArrowUp'
  })
  expect(screen.getByRole('option', { selected: true })).toHaveTextContent(
    'LampaStream LMS'
  )
})
it('switches strategies and fine-tunes the existing entry', async () => {
  render(<Players />)
  await screen.findByRole('option', { selected: true })
  fireEvent.click(
    screen.getByRole('button', { name: 'Lights 10 milliseconds earlier' })
  )
  await waitFor(() =>
    expect(api.updatePlayerLatency).toHaveBeenCalledWith('study', {
      trim_ms: -10
    })
  )
  fireEvent.click(screen.getByRole('button', { name: 'Fixed', exact: true }))
  await waitFor(() =>
    expect(api.updatePlayerLatency).toHaveBeenCalledWith('study', {
      strategy: 'fixed'
    })
  )
  await waitFor(() =>
    expect(
      screen.queryByRole('button', { name: 'Lights 10 milliseconds later' })
    ).not.toBeInTheDocument()
  )
  fireEvent.click(screen.getByRole('button', { name: 'None', exact: true }))
  await waitFor(() =>
    expect(api.updatePlayerLatency).toHaveBeenCalledWith('study', {
      strategy: 'none'
    })
  )
  fireEvent.click(screen.getByRole('button', { name: 'Auto', exact: true }))
  await waitFor(() =>
    expect(api.updatePlayerLatency).toHaveBeenCalledWith('study', {
      strategy: 'auto'
    })
  )
})
it('creates Auto when the followed player has no saved timing', async () => {
  entries = entries.filter((e) => e.player_mac !== 'study')
  render(<Players />)
  fireEvent.click(
    await screen.findByRole('button', { name: 'Measure automatically' })
  )
  await waitFor(() =>
    expect(api.createPlayerLatency).toHaveBeenCalledWith({
      player_mac: 'study',
      name: 'study',
      strategy: 'auto'
    })
  )
})
it.each([
  ['lms', 'Delete virtual player'],
  ['timing:port', 'Remove latency entry']
])(
  'confirms deletion of %s and only removes its own entity',
  async (id, title) => {
    render(<Players selectedPlayer={id} />)
    await screen.findByRole('option', { selected: true })
    fireEvent.click(screen.getByRole('button', { name: 'Delete…' }))
    expect(screen.getByRole('dialog')).toHaveTextContent(title)
    expect(api.deleteVirtualPlayer).not.toHaveBeenCalled()
    expect(api.deletePlayerLatency).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel', exact: true }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete…' }))
    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm', exact: true })
    )
    if (id === 'lms') {
      await waitFor(() =>
        expect(api.deleteVirtualPlayer).toHaveBeenCalledWith('lms')
      )
      expect(api.deletePlayerLatency).not.toHaveBeenCalled()
      expect(
        await screen.findByRole('option', {
          name: /Study.*Not followed right now/
        })
      ).toBeVisible()
    } else {
      await waitFor(() =>
        expect(api.deletePlayerLatency).toHaveBeenCalledWith('port')
      )
      expect(api.deleteVirtualPlayer).not.toHaveBeenCalled()
    }
  }
)
it.each([
  ['lms', 'Edit virtual player'],
  ['timing:port', 'Edit latency entry']
])('opens the existing editor for %s', async (id, title) => {
  render(<Players selectedPlayer={id} />)
  await screen.findByRole('option', { selected: true })
  fireEvent.click(screen.getByRole('button', { name: 'Edit', exact: true }))
  expect(screen.getByRole('dialog')).toHaveTextContent(title)
})
it.each([
  '/latency?player=air',
  '/virtual-players?player=air',
  '/#latency?player=air'
])('redirects %s while retaining the player', (url) => {
  window.history.replaceState(null, '', url)
  expect(readRoute()).toEqual({ tab: 'players', player: 'air' })
  expect(window.location.pathname).toBe('/players')
  expect(window.location.search).toBe('?player=air')
})
it('selects the MAC from a Now Playing settings deep link', async () => {
  render(<Players selectedPlayer="air" />)
  expect(
    await screen.findByRole('option', { selected: true })
  ).toHaveTextContent('Joins your AirPlay groups')
})

it('keeps selection usable when browser storage is unavailable', async () => {
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error('blocked') })
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('blocked') })
  try {
    render(<Players />)
    const first = await screen.findByRole('option', { selected: true })
    fireEvent.keyDown(first, { key: 'ArrowDown' })
    expect(screen.getByRole('option', { selected: true })).toHaveTextContent('Joins your AirPlay groups')
  } finally { get.mockRestore(); set.mockRestore() }
})

it('renders the decorative LMS alpha mask in currentColor without an image', async () => {
  render(<Players />)
  const row = await screen.findByRole('option', { name: /LampaStream LMS/ })
  const icon = row.querySelector('[data-player-icon="LMS"]') as HTMLElement
  expect(row.querySelector('img')).toBeNull()
  expect(icon.parentElement).toHaveAttribute('aria-hidden', 'true')
  expect(icon.parentElement).toHaveClass('text-foreground', 'bg-secondary', 'border')
  expect(icon.style.backgroundColor).toBe('currentcolor')
  expect(icon.style.maskImage).toMatch(/^url\(/)
  expect(icon.style.webkitMaskImage).toBe(icon.style.maskImage)
  expect(icon.style.maskMode).toBe('alpha')
  expect(icon.style.maskSize).toBe('contain')
  expect(icon.style.maskRepeat).toBe('no-repeat')
  expect(icon.style.maskPosition).toBe('center')
  expect(icon.style.width).toBe('30px')
  expect(icon.parentElement).toHaveClass('h-10', 'w-10')
  const icons = document.querySelectorAll('[data-player-icon="LMS"]')
  expect((icons[1] as HTMLElement).style.width).toBe('40px')
  expect(icons[1].parentElement).toHaveClass('h-14', 'w-14')
})

it('edits and saves the two LMS timing fields with steppers', async () => {
  vi.mocked(api.updateVirtualPlayer).mockResolvedValue(lms)
  render(<Players selectedPlayer="lms" />)
  await screen.findByRole('option', { selected: true })
  fireEvent.click(screen.getByRole('button', { name: 'Edit', exact: true }))
  expect(screen.getByRole('spinbutton', { name: 'Head start', exact: true })).toHaveValue(500)
  fireEvent.click(screen.getByRole('button', { name: 'Increase Head start' }))
  fireEvent.click(screen.getByRole('button', { name: 'Decrease Speaker output delay' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }))
  await waitFor(() => expect(api.updateVirtualPlayer).toHaveBeenCalledWith('lms', expect.objectContaining({ head_start_ms: 510, speaker_output_delay_ms: -1 })))
})


it('renders model icons in the Players list and the selected detail header', async () => {
  players = [{ ...lms, follow_player_mac: '' }, airplay]
  entries = [timing('sonos', 'Sonos Study'), timing('radio', 'Radio Red'), timing('pi', 'piCorePlayer'), timing('unknown', 'Unknown')]
  vi.mocked(api.listLmsPlayers).mockResolvedValue([
    { playerid: 'sonos', name: 'Study (Sonos)', modelname: 'YeneY' },
    { playerid: 'radio', name: 'Radio Red', model: 'baby' },
    { playerid: 'pi', name: 'piCorePlayer', modelname: 'SqueezeLite-pCP' },
  ])
  render(<Players />)
  for (const [name, kind] of [['LampaStream LMS', 'LMS'], ['Joins your AirPlay groups', 'AirPlay'], ['Sonos Study', 'Sonos'], ['Radio Red', 'Radio'], ['piCorePlayer', 'RaspberryPi'], ['Unknown', 'Speaker']]) {
    const row = await screen.findByRole('option', { name: new RegExp(name.replace(/[()]/g, '\\$&')) })
    await waitFor(() => expect(row.querySelector(`[data-player-icon="${kind}"]`)).not.toBeNull())
    if (!['AirPlay', 'Speaker'].includes(kind)) {
      expect((row.querySelector(`[data-player-icon="${kind}"]`) as HTMLElement).style.maskImage).toMatch(/^url\(/)
    }
    fireEvent.click(row)
    expect(document.querySelectorAll(`[data-player-icon="${kind}"]`).length).toBeGreaterThanOrEqual(2)
  }
})

it('uses the supplied Lyrion waveform in both managed LMS player locations', async () => {
  render(<Players />)
  await screen.findByRole('option', { name: /LampaStream LMS/ })
  const logo = document.querySelector('[data-player-icon="LMS"]') as HTMLElement
  expect(logo.style.maskImage).toBe(`url("${lyrionAsset}")`)
  expect(logo.style.width).toBe('30px')
  expect(document.querySelectorAll('[data-player-icon="LMS"]')).toHaveLength(2)
})
