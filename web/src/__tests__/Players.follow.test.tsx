import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Players } from '../pages/Players'
import { updateVirtualPlayer, createVirtualPlayer, getVirtualPlayers, PLAYER_TYPES } from '../lib/api'

vi.mock('../lib/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../lib/api')>(),
  getVirtualPlayers: vi.fn().mockResolvedValue([{
    id: 'managed', type: 'LMS', player_name: 'LampaStream', lms_host: 'lms.local',
    lms_port: 3483, player_mac: 'aa:bb:cc:dd:ee:01',
    follow_player_mac: 'aa:bb:cc:dd:ee:02',
  }]),
  createVirtualPlayer: vi.fn().mockResolvedValue(undefined),
  updateVirtualPlayer: vi.fn().mockResolvedValue(undefined),
  getCouplings: vi.fn().mockResolvedValue([]),
  listLmsPlayers: vi.fn().mockResolvedValue([
    { playerid: '11:22:33:44:55:66', name: 'Sonos Living Room' },
  ]),
}))

describe('Follow player discovery', () => {
  const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
  beforeAll(() => {
    // Radix scrolls the focused option; jsdom has no layout/scroll implementation.
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
  })
  afterAll(() => {
    if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll)
    else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
  })

  it('retains the saved target omitted by discovery while offering external targets', async () => {
    const user = userEvent.setup()
    render(<Players />)
    await user.click(await screen.findByRole('button', { name: 'Edit', exact: true }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Discover', exact: true }))
    const follow = within(dialog).getAllByRole('combobox').find(
      element => element.textContent === 'aa:bb:cc:dd:ee:02',
    )!
    expect(follow).toHaveTextContent('aa:bb:cc:dd:ee:02')
    // Open with the keyboard; jsdom does not implement pointer capture.
    fireEvent.keyDown(follow, { key: 'ArrowDown' })
    expect(await screen.findByRole('option', { name: 'Sonos Living Room (11:22:33:44:55:66)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'aa:bb:cc:dd:ee:02' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('option', { name: /aa:bb:cc:dd:ee:01/ })).not.toBeInTheDocument()
  })
  it('switches to passive sync-group mode and saves without losing the manual MAC', async () => {
    const user = userEvent.setup()
    render(<Players />)
    await user.click(await screen.findByRole('button', { name: 'Edit', exact: true }))
    const mode = screen.getByRole('combobox', { name: 'Follow mode' })
    expect(mode).toHaveTextContent('Manual')
    fireEvent.keyDown(mode, { key: 'ArrowDown' })
    await user.click(await screen.findByRole('option', { name: 'Automatic — LMS sync group' }))
    expect(screen.queryByRole('button', { name: 'Discover', exact: true })).not.toBeInTheDocument()
    expect(screen.getByText(/never changes its membership or sends playback commands/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save', exact: true }))
    expect(updateVirtualPlayer).toHaveBeenCalledWith('managed', expect.objectContaining({
      follow_mode: 'sync_group', follow_player_mac: 'aa:bb:cc:dd:ee:02',
    }))
  })

  it('offers Spotify and creates a receiver without an LMS host', async () => {
    expect(PLAYER_TYPES).toContainEqual({ value: 'Spotify', label: 'Spotify Connect (go-librespot)' })
    const user = userEvent.setup()
    render(<Players />)
    await user.click(await screen.findByRole('button', { name: /New virtual player/i }))
    const dialog = within(screen.getByRole('dialog'))
    expect(dialog.getByText('LMS host')).toBeVisible()
    fireEvent.keyDown(dialog.getAllByRole('combobox')[0], { key: 'ArrowDown' })
    await user.click(await screen.findByRole('option', { name: 'Spotify Connect (go-librespot)' }))
    for (const label of ['LMS host', 'LMS port', 'ALSA device', 'Follow mode', 'Follow player']) {
      expect(dialog.queryByText(label, { exact: true })).not.toBeInTheDocument()
    }
    expect(dialog.getByText(/Spotify Connect device picker.*restarts the go-librespot receiver/)).toBeVisible()
    expect(dialog.getByText('Silent Spotify Connect destination for analysis.')).toBeVisible()
    expect(dialog.queryByText(/alongside your real speaker/)).not.toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: 'Save', exact: true }))
    expect(createVirtualPlayer).toHaveBeenCalledWith(expect.objectContaining({ type: 'Spotify', lms_host: '' }))
  })

  it('edits a saved Spotify receiver using the same receiver-only form', async () => {
    vi.mocked(getVirtualPlayers).mockResolvedValueOnce([{
      id: 'spotify', type: 'Spotify', player_name: 'Spotify room', display_name: 'Room',
      lms_host: '', lms_port: 9000, player_mac: '', alsa_device: '', follow_player_mac: '', follow_mode: 'manual',
    }])
    const user = userEvent.setup()
    render(<Players />)
    await user.click(await screen.findByRole('button', { name: 'Edit', exact: true }))
    const dialog = within(screen.getByRole('dialog'))
    expect(dialog.getByText('Spotify Connect (go-librespot)')).toBeVisible()
    expect(dialog.queryByText('LMS host')).not.toBeInTheDocument()
    await user.clear(dialog.getByDisplayValue('Room'))
    await user.type(dialog.getByDisplayValue(''), 'New room')
    await user.click(dialog.getByRole('button', { name: 'Save', exact: true }))
    expect(updateVirtualPlayer).toHaveBeenCalledWith('spotify', expect.objectContaining({ display_name: 'New room' }))
  })

})
