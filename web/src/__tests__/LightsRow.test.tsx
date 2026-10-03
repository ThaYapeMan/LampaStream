import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { LightsRow } from '@/components/LightsRow'
import { releaseLights, takeLights } from '@/lib/api'
vi.mock('@/lib/api', () => ({ releaseLights: vi.fn(), takeLights: vi.fn() }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
it.each(['streaming', 'released', 'reconnecting', 'failed'] as const)('shows %s with a constant row height and action', state => {
  render(<LightsRow couplingId="c" output={{ state, reason: 'Reason' }} />)
  expect(screen.getByTestId('lights-row')).toHaveClass('h-20')
  expect(screen.getByRole('button', { name: state === 'released' ? 'Take lights' : 'Release lights' })).toHaveClass('min-h-11')
  expect(screen.getByRole('status')).toHaveTextContent(state === 'streaming' ? 'Following the music' : state === 'released' ? 'Released · Reason' : state === 'reconnecting' ? 'Reconnecting the lights' : 'Light output unavailable')
})
it('prevents repeated release and shows an inline error', async () => {
  let reject!: (error: Error) => void
  vi.mocked(releaseLights).mockImplementation(() => new Promise((_, no) => { reject = no }))
  render(<LightsRow couplingId="c" output={{ state: 'streaming', reason: null }} />)
  fireEvent.click(screen.getByRole('button', { name: 'Release lights' }))
  expect(screen.getByRole('button', { name: 'Releasing…' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Releasing…' }))
  expect(releaseLights).toHaveBeenCalledTimes(1)
  reject(Error('Request failed'))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Request failed'))
  expect(screen.getByRole('button', { name: 'Release lights' })).toBeEnabled()
})
it('takes released lights explicitly', async () => {
  render(<LightsRow couplingId="c" output={{ state: 'released', reason: 'You released the lights' }} />)
  fireEvent.click(screen.getByRole('button', { name: 'Take lights' }))
  await waitFor(() => expect(takeLights).toHaveBeenCalledWith('c'))
})
