import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TrackProgress } from '@/components/TrackProgress'

const beatport = { provider: 'beatport', label: 'Beatport' }
const songbpm = { provider: 'songbpm', label: 'SongBPM' }

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
    render(<TrackProgress track={null} connected tempoBpm={128} beatSource="grid" providerRows={rows} />)
    expect(screen.getByTestId('track-information').firstElementChild).toHaveTextContent(info)
    expect(screen.getByTestId('track-information-source')).toHaveTextContent(`source: ${source}`)
  })
})
