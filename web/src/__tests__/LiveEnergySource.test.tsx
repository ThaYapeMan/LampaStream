import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { LiveEnergySource } from '../components/LiveEnergySource'
import { EnergySourceControls } from '../components/EnergyBlendEditor'
import { updateEnergyProfile, type EnergyProfile } from '../lib/api'
vi.mock('../lib/api', async original => ({ ...await original<typeof import('../lib/api')>(), updateEnergyProfile: vi.fn() }))
const initial = { id:'e', name:'Spectrum RGB', energy_source:'sustained', lufs_floor:-30, lufs_ceiling:-8, adaptation_tau_s:60 } as EnergyProfile
function Harness() {
  const [profile, setProfile] = useState(initial)
  return <LiveEnergySource expertMode profile={profile} active onUpdated={setProfile} />
}
afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  let persisted = initial
  vi.mocked(updateEnergyProfile).mockImplementation(async (_id, body) => { persisted = {...persisted, ...body}; return persisted })
})
it('applies modes immediately, commits validated numbers only on blur/Enter, and avoids double PATCH', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  const group = screen.getByRole('radiogroup', { name:'Energy source' })
  expect(within(group).getAllByRole('radio')).toHaveLength(4)
  await user.click(screen.getByRole('radio', {name:'Fixed loudness'}))
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenCalledWith('e', {energy_source:'loudness_fixed'}))
  const floor = screen.getByRole('spinbutton', {name:'Floor'})
  await user.clear(floor); await user.type(floor, '-25')
  expect(updateEnergyProfile).toHaveBeenCalledTimes(1)
  await user.keyboard('{Enter}')
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenCalledTimes(2))
  expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {lufs_floor:-25})
  await user.click(floor); await user.clear(floor); await user.type(floor, '-5'); await user.tab()
  expect(screen.getByRole('alert')).toHaveTextContent('lufs_floor must be below lufs_ceiling')
  expect(updateEnergyProfile).toHaveBeenCalledTimes(2)
  await user.click(screen.getByRole('radio', {name:'Adaptive loudness'}))
  await screen.findByRole('spinbutton', {name:'Adaptation'})
  expect(screen.queryByRole('spinbutton', {name:'Floor'})).not.toBeInTheDocument()
  await user.click(screen.getByRole('radio', {name:'Sustained'}))
  await waitFor(() => expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument())
})
it('uses the same validation messages and labels as the profile editor', () => {
  const props = { source:'loudness_fixed', floor:'-5', ceiling:'-8', tau:'60', onChange:vi.fn() }
  const { rerender } = render(<EnergySourceControls {...props} />)
  const message = screen.getByRole('alert').textContent
  expect(screen.getByRole('button', {name:/Fixed loudness/})).toHaveAttribute('aria-pressed','true')
  rerender(<EnergySourceControls {...props} compact />)
  expect(screen.getByRole('alert').textContent).toBe(message)
  expect(screen.getByRole('radio', {name:'Fixed loudness'})).toHaveAttribute('aria-checked','true')
  rerender(<EnergySourceControls {...props} floor="" compact />)
  expect(screen.getByRole('alert')).toHaveTextContent('Energy source settings must be finite')
})
it('keeps all segments visible but disabled without an active coupling', () => {
  render(<LiveEnergySource expertMode active={false} onUpdated={vi.fn()} />)
  expect(screen.getByText('No active coupling')).toBeInTheDocument()
  for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled()
  expect(screen.queryByText('Open profile')).not.toBeInTheDocument()
})
it('supports arrow-key selection and shows server failure without changing persisted selection', async () => {
  const user = userEvent.setup()
  vi.mocked(updateEnergyProfile).mockRejectedValue(new Error('Connection failed'))
  render(<Harness />)
  screen.getByRole('radio', {name:'Sustained'}).focus()
  await user.keyboard('{ArrowRight}')
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection failed')
  expect(updateEnergyProfile).toHaveBeenCalledWith('e', {energy_source:'loudness_fixed'})
  expect(screen.getByRole('radio', {name:'Sustained'})).toHaveAttribute('aria-checked','true')
})

it('keeps the parameter row for sustained and disabled states', async () => {
  const user = userEvent.setup()
  const view = render(<Harness />)
  expect(screen.getByTestId('energy-parameters')).toHaveClass('h-7')
  expect(screen.getByText('No parameters for this source')).toBeVisible()
  await user.click(screen.getByRole('radio', {name:'Fixed loudness'}))
  expect(await screen.findByRole('spinbutton', {name:'Floor'})).toBeVisible()
  expect(screen.getByTestId('energy-parameters')).toHaveClass('h-7')
  view.rerender(<LiveEnergySource expertMode active={false} onUpdated={vi.fn()} />)
  expect(screen.getByTestId('energy-parameters')).toHaveTextContent('No active coupling')
  expect(screen.getByTestId('energy-parameters')).toHaveClass('h-7')
})
it('steps floor/ceiling by 1 and adaptation by 5; keyboard Shift multiplies by 5', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  await user.click(screen.getByRole('radio', {name:'Fixed loudness'}))
  const floor = await screen.findByRole('spinbutton', {name:'Floor'})
  await user.click(screen.getByRole('button', {name:'Increase Floor'}))
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {lufs_floor:-29}))
  expect(updateEnergyProfile).toHaveBeenCalledTimes(2)
  await user.click(floor); await user.keyboard('{ArrowUp}')
  expect(floor).toHaveValue(-28)
  expect(updateEnergyProfile).toHaveBeenCalledTimes(2)
  await user.keyboard('{Enter}')
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {lufs_floor:-28}))
  await user.click(floor); await user.keyboard('{Shift>}{ArrowUp}{/Shift}{Enter}')
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {lufs_floor:-23}))
  await user.click(screen.getByRole('button', {name:'Decrease Ceiling'}))
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {lufs_ceiling:-9}))
  await user.click(screen.getByRole('radio', {name:'Adaptive loudness'}))
  await user.click(await screen.findByRole('button', {name:'Increase Adaptation'}))
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {adaptation_tau_s:65}))
  const tau = screen.getByRole('spinbutton', {name:'Adaptation'})
  await user.click(tau); await user.keyboard('{Shift>}{ArrowDown}{/Shift}{Enter}')
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {adaptation_tau_s:40}))
})
it('coalesces rapid stepper clicks and still rejects an invalid stepped window', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  await user.click(screen.getByRole('radio', {name:'Fixed loudness'}))
  const up = await screen.findByRole('button', {name:'Increase Floor'})
  await user.dblClick(up)
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenCalledTimes(2))
  expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {lufs_floor:-28})
  const floor = screen.getByRole('spinbutton', {name:'Floor'})
  await user.clear(floor); await user.type(floor, '-9'); await user.keyboard('{Enter}')
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenCalledTimes(3))
  await user.click(up)
  expect(screen.getByRole('alert')).toHaveTextContent('lufs_floor must be below lufs_ceiling')
  await new Promise(resolve => setTimeout(resolve, 300))
  expect(updateEnergyProfile).toHaveBeenCalledTimes(3)
})


it('hides source controls and manual fields in Standard mode', () => {
  render(<LiveEnergySource expertMode={false} profile={{...initial, energy_source:'peak_envelope', peak_envelope_auto:false}} active onUpdated={vi.fn()} />)
  expect(screen.queryByLabelText('Energy source settings')).not.toBeInTheDocument()
  expect(screen.queryByTestId('field-peak-attack')).not.toBeInTheDocument()
  expect(screen.queryByTestId('field-peak-release')).not.toBeInTheDocument()
  expect(screen.getByText('Open profile')).toBeVisible()
})

it('patches peak Auto/Manual and validates attack and release before committing', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  await user.click(screen.getByRole('radio', {name:'Peak envelope'}))
  expect(await screen.findByRole('button', {name:'Auto', exact:true})).toHaveAttribute('aria-pressed', 'true')
  expect(screen.queryByTestId('field-peak-attack')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', {name:'Manual', exact:true}))
  const attack = await screen.findByLabelText('Attack (s)')
  expect(attack).toHaveValue(.05)
  expect(screen.getByLabelText('Release (s)')).toHaveValue(2)
  await user.clear(attack); await user.type(attack, '2'); await user.tab()
  expect(screen.getByRole('alert')).toHaveTextContent('peak_attack_s must be below peak_release_s')
  expect(updateEnergyProfile).toHaveBeenCalledTimes(2)
  await user.clear(attack); await user.type(attack, '0.1'); await user.keyboard('{Enter}')
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {peak_attack_s:.1}))
  await user.click(screen.getByRole('button', {name:'Auto', exact:true}))
  await waitFor(() => expect(screen.queryByTestId('field-peak-attack')).not.toBeInTheDocument())
  expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {peak_envelope_auto:true})
})

it('persists reshape independently of Auto/Manual and validates its compact field', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  expect(screen.queryByRole('checkbox', {name:'Reshape'})).not.toBeInTheDocument()
  await user.click(screen.getByRole('radio', {name:'Peak envelope'}))
  await user.click(await screen.findByRole('checkbox', {name:'Reshape'}))
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {peak_reshape_enabled:true}))
  const power = await screen.findByRole('spinbutton', {name:'Reshape power'})
  expect(power).toHaveValue(.4)
  await user.clear(power); await user.type(power, '0.8'); await user.keyboard('{Enter}')
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {peak_reshape_power:.8}))
  await user.click(screen.getByRole('button', {name:'Manual'}))
  expect(screen.getByRole('checkbox', {name:'Reshape'})).toBeChecked()
  expect(power).toHaveValue(.8)
  const calls = vi.mocked(updateEnergyProfile).mock.calls.length
  await user.clear(power); await user.type(power, '0'); await user.tab()
  expect(screen.getByRole('alert')).toHaveTextContent('peak_reshape_power')
  expect(updateEnergyProfile).toHaveBeenCalledTimes(calls)
  await user.click(screen.getByRole('checkbox', {name:'Reshape'}))
  await waitFor(() => expect(updateEnergyProfile).toHaveBeenLastCalledWith('e', {peak_reshape_enabled:false}))
  expect(screen.queryByRole('spinbutton', {name:'Reshape power'})).not.toBeInTheDocument()
})

it('hides enabled reshape in Standard mode', () => {
  render(<LiveEnergySource active profile={{...initial, energy_source:'peak_envelope', peak_reshape_enabled:true}} onUpdated={vi.fn()} />)
  expect(screen.queryByRole('checkbox', {name:'Reshape'})).not.toBeInTheDocument()
  expect(screen.queryByRole('spinbutton', {name:'Reshape power'})).not.toBeInTheDocument()
})

it.each([
  [true, false], [true, true], [false, false], [false, true],
])('reserves two compact peak rows for Auto=%s and Reshape=%s', (auto, reshape) => {
  render(<LiveEnergySource expertMode active profile={{...initial,
    energy_source:'peak_envelope', peak_envelope_auto:auto, peak_reshape_enabled:reshape,
  }} onUpdated={vi.fn()} />)
  expect(screen.queryByTestId('energy-parameters')).not.toBeInTheDocument()
  const mode = screen.getByRole('group', {name:'Peak envelope mode'})
  const agcRow = mode.parentElement!
  const reshapeRow = screen.getByRole('group', {name:'Reshape settings'})
  expect(agcRow).toHaveClass('flex', 'h-7', 'items-center')
  expect(agcRow).not.toHaveClass('flex-wrap')
  expect(reshapeRow).toHaveClass('flex', 'h-9', 'items-center', 'border-t', 'pt-2')
  expect(reshapeRow).not.toHaveClass('space-y-2')
  expect(agcRow.nextElementSibling).toBe(reshapeRow)
  expect(reshapeRow.nextElementSibling).toBeNull()
  expect(screen.queryByText('Auto: 0.05 s attack · 2 s release')).not.toBeInTheDocument()
  if (auto) {
    expect(screen.getAllByText('Self-calibrating with preset attack and release.')).toHaveLength(1)
    expect(within(agcRow).getByText('Self-calibrating with preset attack and release.')).toBeVisible()
    expect(screen.queryByTestId('field-peak-attack')).not.toBeInTheDocument()
  } else {
    expect(screen.queryByText('Self-calibrating with preset attack and release.')).not.toBeInTheDocument()
    for (const field of ['field-peak-attack', 'field-peak-release']) {
      const input = screen.getByTestId(field)
      expect(input.closest('div')!.parentElement).toBe(agcRow)
      expect(within(agcRow).getByTestId(field)).toBeVisible()
    }
  }
  expect(screen.getByRole('checkbox', {name:'Reshape'}).parentElement!.parentElement).toBe(reshapeRow)
  if (reshape) {
    const input = screen.getByTestId('field-peak-reshape-power')
    expect(input.closest('div')!.parentElement).toBe(reshapeRow)
    expect(input).toHaveValue(.4)
  } else {
    expect(screen.queryByTestId('field-peak-reshape-power')).not.toBeInTheDocument()
  }
})
