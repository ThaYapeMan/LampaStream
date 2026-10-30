import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TrackProgress } from '@/components/TrackProgress'

describe('track tempo', () => {
  it.each([true, false])('shows rounded tempo with locked=%s', locked => {
    render(<TrackProgress track={null} connected tempoBpm={127.8} tempoLocked={locked} />)
    const tempo = screen.getByTestId('track-tempo')
    expect(tempo).toHaveTextContent('128 BPM')
    expect(tempo).toHaveClass('ml-auto', 'text-right')
    expect(tempo).toHaveClass(locked ? 'text-foreground' : 'text-muted-foreground')
  })
  it.each([null, undefined, 0])('hides missing tempo %s', bpm => {
    render(<TrackProgress track={null} connected tempoBpm={bpm} />)
    expect(screen.queryByTestId('track-tempo')).toBeNull()
  })
})
