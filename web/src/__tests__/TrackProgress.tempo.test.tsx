import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TrackProgress } from '@/components/TrackProgress'

const beatport = { provider: 'beatport', label: 'Beatport' }
const songbpm = { provider: 'songbpm', label: 'SongBPM' }
const track = { title: 'First track', artist: 'Artist', position_s: 1, duration_s: 200, playing: true }

describe('track tempo and song information', () => {
  it.each([true, false])('shows rounded tempo with locked=%s', locked => {
    render(<TrackProgress track={null} connected tempoBpm={127.8} tempoLocked={locked} />)
    expect(screen.getByTestId('track-information')).toHaveTextContent('measured 128 BPM')
    expect(screen.getByTestId('track-information')).toHaveClass('tabular-nums', 'text-muted-foreground')
    expect(screen.getByTestId('track-tempo').classList.contains('opacity-70')).toBe(!locked)
    expect(screen.queryByTestId('track-information-source')).toBeNull()
  })
  it.each([null, undefined, 0])('hides missing tempo %s', bpm => {
    render(<TrackProgress track={null} connected tempoBpm={bpm} />)
    expect(screen.queryByTestId('track-information')).toBeNull()
  })
  it.each([
    { rows: [{ ...beatport, fields: { tempo: 128, key: 'Gb Maj', genre: 'Dance / Pop' } }],
      info: 'grid 128 BPM · Beatport 128 · G♭ major · Dance / Pop', source: 'Beatport' },
    { rows: [{ ...beatport, fields: { tempo: 128, key: 'F# Min' } }],
      info: 'grid 128 BPM · Beatport 128 · F♯ minor', source: 'Beatport' },
    { rows: [{ ...songbpm, fields: { tempo: 96, key: 'G', match: 'title_duration' } }],
      info: 'grid 128 BPM · SongBPM 96 · G', source: 'SongBPM?' },
    { rows: [{ ...beatport, fields: { genre: 'Pop' } }, { ...songbpm, fields: { key: 'G' } }],
      info: 'grid 128 BPM · G · Pop', source: 'SongBPM, Beatport' },
    { rows: [{ ...beatport, fields: { tempo: 127, key: 'Gb Major' } },
             { ...songbpm, fields: { key: 'F' } }],
      info: 'grid 128 BPM · Beatport 127 · G♭ major', source: 'Beatport' },
  ])('shows $info', ({ rows, info, source }) => {
    render(<TrackProgress track={track} connected tempoBpm={128} beatSource="grid"
      providerRows={rows.map(row => ({ ...row, track }))} />)
    expect(screen.getByTestId('track-information').firstElementChild).toHaveTextContent(info)
    expect(screen.getByTestId('track-information-source')).toHaveTextContent(`source: ${source}`)
  })

  it('clears stale lookup rows on a track change and keeps the grid tempo', () => {
    const first = { ...songbpm, track, fields: { tempo: 129, key: 'G', genre: 'House' } }
    const next = { ...track, title: 'Second track' }
    const second = { ...songbpm, track: next, fields: { tempo: 123, key: 'F', genre: 'Pop' } }
    const view = (current: typeof track, bpm: number, providerRows: (typeof first)[]) => (
      <TrackProgress track={current} connected tempoBpm={bpm} beatSource="grid" providerRows={providerRows} />
    )
    const { rerender } = render(view(track, 128, [first]))
    expect(screen.getByTestId('track-information')).toHaveTextContent('SongBPM 129 · G · House')
    expect(screen.getByTestId('track-information-source')).toHaveTextContent('source: SongBPM')

    rerender(view(next, 124, [first]))
    expect(screen.getByTestId('track-title')).toHaveTextContent('Second track')
    expect(screen.getByTestId('track-information')).toHaveTextContent(/^grid 124 BPM$/)
    expect(screen.queryByTestId('track-information-source')).toBeNull()

    rerender(view(next, 124, [second]))
    expect(screen.getByTestId('track-information')).toHaveTextContent('SongBPM 123 · F · Pop')
    rerender(view({ ...next, position_s: 20 }, 124, [second]))
    expect(screen.getByTestId('track-information')).toHaveTextContent('SongBPM 123 · F · Pop')
    expect(screen.getByTestId('track-information-source')).toHaveTextContent('source: SongBPM')
  })
})
