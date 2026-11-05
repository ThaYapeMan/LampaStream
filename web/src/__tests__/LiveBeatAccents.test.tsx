import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LiveBeatAccents } from '@/components/LiveBeatAccents'
import { updateCoupling, updateEnergyProfile, type Coupling, type EnergyProfile } from '@/lib/api'
vi.mock('@/lib/api', () => ({updateCoupling:vi.fn(), updateEnergyProfile:vi.fn(), ENERGY_SOURCE_OPTIONS:[]}))
const coupling = {id:'c', name:'Living room', beat_accent_mode:'onset'} as Coupling
const profile = {id:'e', name:'Evening', agc_max_gain:64, onset_gain_floor:.3} as EnergyProfile

describe('LiveBeatAccents', () => {
  it('disables the mode and parameters without an active coupling', () => {
    render(<LiveBeatAccents onCoupling={vi.fn()} onProfile={vi.fn()} />)
    for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled()
    for (const input of screen.getAllByRole('spinbutton')) expect(input).toBeDisabled()
  })
  it('patches the coupling live, supports keyboard navigation and reports scope', async () => {
    const onCoupling = vi.fn()
    vi.mocked(updateCoupling).mockResolvedValue({...coupling, beat_accent_mode:'tracker'})
    render(<LiveBeatAccents coupling={coupling} profile={profile} onCoupling={onCoupling} onProfile={vi.fn()} />)
    expect(screen.getByText('Living room')).toBeVisible()
    fireEvent.keyDown(screen.getByRole('radio', {name:'Onset'}), {key:'ArrowRight'})
    await waitFor(() => expect(updateCoupling).toHaveBeenCalledWith('c', {beat_accent_mode:'tracker'}))
    expect(onCoupling).toHaveBeenCalled()
  })
  it('validates parameters and patches the Energy Profile', async () => {
    vi.mocked(updateEnergyProfile).mockResolvedValue({...profile, agc_max_gain:72})
    const onProfile = vi.fn()
    render(<LiveBeatAccents coupling={coupling} profile={profile} onCoupling={vi.fn()} onProfile={onProfile} />)
    const ceiling = screen.getByRole('spinbutton', {name:'AGC ceiling'})
    fireEvent.change(ceiling, {target:{value:'7'}}); fireEvent.blur(ceiling)
    expect(screen.getByRole('alert')).toBeVisible()
    fireEvent.change(ceiling, {target:{value:'72'}}); fireEvent.blur(ceiling)
    await waitFor(() => expect(updateEnergyProfile).toHaveBeenCalledWith('e', {agc_max_gain:72}))
    expect(onProfile).toHaveBeenCalled()
  })
})
