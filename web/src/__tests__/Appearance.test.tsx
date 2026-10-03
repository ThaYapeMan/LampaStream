import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Appearance } from '@/components/Appearance'
let change: () => void
let dark = false
beforeEach(() => {
  localStorage.clear(); dark = false
  vi.stubGlobal('matchMedia', () => ({ get matches() { return dark }, addEventListener: (_: string, fn: () => void) => { change = fn }, removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('persists Light and Dark and restores the choice', () => {
  const view = render(<Appearance />)
  fireEvent.click(screen.getByRole('button', { name: 'Dark' }))
  expect(localStorage.getItem('lampastream.appearance')).toBe('dark')
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  expect(document.documentElement).toHaveClass('dark')
  view.unmount(); render(<Appearance />)
  expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Light' }))
  expect(document.documentElement).toHaveAttribute('data-theme', 'light')
})
it('System follows live media changes', () => {
  render(<Appearance />)
  dark = true; change()
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  dark = false; change()
  expect(document.documentElement).toHaveAttribute('data-theme', 'light')
})
it('storage failures fall back to System', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error('blocked') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('blocked') })
  render(<Appearance />)
  fireEvent.click(screen.getByRole('button', { name: 'Dark' }))
  expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'true')
  expect(document.documentElement).toHaveAttribute('data-theme', 'light')
})
it('an invalid stored choice and a failed write both fall back to System', () => {
  localStorage.setItem('lampastream.appearance', 'invalid')
  const view = render(<Appearance />)
  expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'true')
  view.unmount()
  localStorage.setItem('lampastream.appearance', 'dark')
  render(<Appearance />)
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('read only') })
  fireEvent.click(screen.getByRole('button', { name: 'Light' }))
  expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'true')
  expect(document.documentElement).toHaveAttribute('data-theme', 'light')
})
