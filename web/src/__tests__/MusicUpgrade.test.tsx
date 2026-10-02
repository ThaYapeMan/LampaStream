import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Palettes } from '@/pages/Palettes'
import { MusicSettings } from '@/pages/MusicSettings'
import { MusicChoices } from '@/components/MusicChoices'
import { PalettePicker } from '@/components/PalettePicker'
import * as api from '@/lib/api'

vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(),
  getPalettes: vi.fn(), savePalette: vi.fn(), duplicatePalette: vi.fn(), deletePalette: vi.fn(), previewPalette: vi.fn(), getZoneChannels: vi.fn(), getMusicSettings: vi.fn(), updateMusicSettings: vi.fn(), getEnergyProfiles: vi.fn(), saveGenreRule: vi.fn(), updateGenreRule: vi.fn(), setMusicOverride: vi.fn(),
}))
const palette = { id: 'warm', name: 'Warm', stops: [{ colour: '#ff0000', position: 0 }, { colour: '#0000ff', position: 100 }] }
const settings: api.MusicSettings = { lastfm_enabled: false, api_key_configured: true, genre_mapping: { house: 'house' }, transition_mode: 'crossfade', transition_duration_s: .7, genres: ['house', 'jazz', 'other'], rules: [] }
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getPalettes).mockResolvedValue([palette])
  vi.mocked(api.getEnergyProfiles).mockResolvedValue([])
  vi.mocked(api.getZoneChannels).mockResolvedValue([{ channel_id: 1, x: 0, y: 0, z: 0 }])
  vi.mocked(api.previewPalette).mockResolvedValue(Array(65).fill({ r: 1, g: 0, b: 0 }))
  vi.mocked(api.savePalette).mockImplementation(async p => ({ ...p, id: p.id || 'created' }))
  vi.mocked(api.duplicatePalette).mockResolvedValue({ ...palette, id: 'copy', name: 'Warm copy' })
  vi.mocked(api.getMusicSettings).mockResolvedValue(settings)
  vi.mocked(api.updateMusicSettings).mockImplementation(async body => ({ ...settings, ...body }))
  vi.mocked(api.saveGenreRule).mockResolvedValue({ id: 'r', genre: 'house', palette_id: 'warm', energy_profile_id: '' })
})
describe('Music colour controls', () => {
  it('creates, adds, moves and removes stops, saves, duplicates and confirms deletion', async () => {
    render(<Palettes zoneId="z" />)
    await screen.findByDisplayValue('Warm')
    fireEvent.click(screen.getByRole('button', { name: 'Add stop' }))
    fireEvent.change(screen.getByLabelText('Colour 2'), { target: { value: '#00ff00' } })
    fireEvent.change(screen.getByLabelText('Position 2'), { target: { value: '60' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save palette' }))
    await waitFor(() => expect(api.savePalette).toHaveBeenCalledWith(expect.objectContaining({ stops: [palette.stops[0], { colour: '#00ff00', position: 60 }, palette.stops[1]] })))
    fireEvent.click(screen.getByRole('button', { name: 'Duplicate' }))
    await screen.findByDisplayValue('Warm copy')
    fireEvent.click(screen.getByRole('button', { name: 'Delete…' }))
    expect(api.deletePalette).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(api.deletePalette).toHaveBeenCalledWith('copy'))
    fireEvent.click(screen.getByRole('button', { name: 'Create palette' }))
    await screen.findByDisplayValue('New palette')
    expect(screen.getAllByLabelText(/^Remove stop/)).toHaveLength(2)
  })
  it('previews the active zone through the shared palette model', async () => {
    render(<Palettes zoneId="z" />)
    await screen.findByLabelText('Light floorplan')
    await waitFor(() => expect(api.previewPalette).toHaveBeenCalledWith(palette, expect.arrayContaining([.5])))
  })
  it('saves privacy immediately, keeps an existing key, and edits transition settings', async () => {
    render(<MusicSettings />)
    await screen.findByLabelText('Look up missing tags with Last.fm')
    fireEvent.click(screen.getByLabelText('Look up missing tags with Last.fm'))
    await waitFor(() => expect(api.updateMusicSettings).toHaveBeenCalledWith({ lastfm_enabled: true }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save settings' })).not.toBeDisabled())
    fireEvent.change(screen.getByLabelText('Transition'), { target: { value: 'through-black' } })
    fireEvent.change(screen.getByLabelText('Transition duration'), { target: { value: '1.2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() => expect(api.updateMusicSettings).toHaveBeenLastCalledWith(expect.objectContaining({ transition_mode: 'through-black', transition_duration_s: 1.2 })))
    expect(vi.mocked(api.updateMusicSettings).mock.lastCall?.[0]).not.toHaveProperty('lastfm_api_key')
  })
  it('creates a genre rule and uses the palette library', async () => {
    render(<MusicSettings />)
    await screen.findByRole('button', { name: 'Add rule' })
    fireEvent.click(screen.getByRole('button', { name: 'Add rule' }))
    fireEvent.change(screen.getByLabelText('Rule 1 palette'), { target: { value: 'warm' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save rule' }))
    await waitFor(() => expect(api.saveGenreRule).toHaveBeenCalledWith({ genre: 'house', palette_id: 'warm', energy_profile_id: '' }))
  })
  it('shows raw genre tags and persists/clears coupling manual choices', async () => {
    render(<MusicChoices profiles={[]} music={{ genre: 'house', raw_tags: ['deep house'], source: 'Track tag', palette_id: 'warm', energy_profile_id: '', manual: false }} />)
    expect(screen.getByText('deep house')).toBeVisible()
    await screen.findByRole('option', { name: 'Warm' })
    fireEvent.change(screen.getByLabelText('Track palette'), { target: { value: 'album-art' } })
    await waitFor(() => expect(api.setMusicOverride).toHaveBeenCalledWith('album-art', ''))
    fireEvent.click(screen.getByRole('button', { name: 'Clear manual choices' }))
    await waitFor(() => expect(api.setMusicOverride).toHaveBeenLastCalledWith('', ''))
  })
  it.each(['Album art: 3 colours', 'Album art: single accent → extended',
    'Album art: monochrome cover → genre palette',
    'Album art: monochrome cover → kept current palette'])('shows the extraction outcome: %s', (outcome) => {
    render(<MusicChoices profiles={[]} music={{ genre: 'house', raw_tags: [], source: 'Track tag', palette_id: 'album-art', energy_profile_id: '', manual: true, album_art_outcome: outcome }} />)
    expect(screen.getByText(outcome)).toBeVisible()
  })
  it('offers shared and album-art palettes and real-time rotation', async () => {
    const change = vi.fn(), rotate = vi.fn()
    render(<PalettePicker value="" rotation={0} onChange={change} onRotation={rotate} />)
    await screen.findByRole('option', { name: 'Warm' })
    fireEvent.change(screen.getByLabelText('Shared palette'), { target: { value: 'warm' } })
    expect(change).toHaveBeenCalledWith('warm', palette)
    fireEvent.change(screen.getByLabelText('Palette rotation'), { target: { value: '.2' } })
    expect(rotate).toHaveBeenCalledWith(.2)
  })
})
