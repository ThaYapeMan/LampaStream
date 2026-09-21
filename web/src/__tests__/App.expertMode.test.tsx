import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'

vi.mock('../hooks/usePreviewSocket', () => ({usePreviewSocket: () => ({status:null, connected:true})}))
vi.mock('../pages/NowPlaying', () => ({NowPlaying: ({expertMode}: {expertMode:boolean}) => <p>Live mode: {String(expertMode)}</p>}))
vi.mock('../pages/EnergyProfiles', () => ({EnergyProfiles: ({expertMode, onExpertModeChange}: {expertMode:boolean; onExpertModeChange:(v:boolean)=>void}) =>
  <button onClick={() => onExpertModeChange(!expertMode)}>Profile mode: {String(expertMode)}</button>}))
beforeEach(() => localStorage.clear())
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('shares Expert mode across pages and persists it across reloads', async () => {
  const user = userEvent.setup()
  const view = render(<App />)
  expect(screen.getByText('Live mode: false')).toBeVisible()
  await user.selectOptions(screen.getByLabelText('Editor mode'), 'expert')
  expect(screen.getByText('Live mode: true')).toBeVisible()
  expect(localStorage.getItem('lampastream.expertMode')).toBe('true')
  await user.click(screen.getByRole('button', {name:'Energy Profiles', exact:true}))
  await user.click(screen.getByRole('button', {name:'Profile mode: true'}))
  await user.click(screen.getByRole('button', {name:'Now Playing', exact:true}))
  expect(screen.getByText('Live mode: false')).toBeVisible()
  await user.selectOptions(screen.getByLabelText('Editor mode'), 'expert')
  view.unmount()
  render(<App />)
  expect(screen.getByText('Live mode: true')).toBeVisible()
})

it('keeps mode selection usable when browser storage is blocked', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Blocked') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Blocked') })
  const user = userEvent.setup()
  render(<App />)
  await user.selectOptions(screen.getByLabelText('Editor mode'), 'expert')
  expect(screen.getByText('Live mode: true')).toBeVisible()
})
