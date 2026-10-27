import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { usePreviewSocket } from '../hooks/usePreviewSocket'

class Socket {
  static current: Socket
  onopen = () => {}
  onclose = () => {}
  onmessage = (_event: { data: string }) => {}
  sent: { type: string; client_ms: number }[] = []
  constructor() { Socket.current = this }
  send(data: string) { this.sent.push(JSON.parse(data)) }
  close() {}
  receive(message: unknown) { this.onmessage({ data: JSON.stringify(message) }) }
}
const event = (audible: number) => ({ type: 'event', audible_monotonic: audible,
  events: [{ id: ['event', 'bass', 1], audible_monotonic: audible,
    peaks: { all: 1, bass: 1, mid: 0, treble: 0 }, bands: ['bass'] }],
  event_count: 1, hold_s: .08, release_s: .25, policy: 'restart',
  channel_colours: [{ r: 65535, g: 0, b: 0 }], channel_accent_lifts: [.6], accent_value: .35 })

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })

it('pings on connection and every two seconds, schedules outlines and holds event colours over frames', () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance', 'requestAnimationFrame', 'cancelAnimationFrame'] })
  vi.stubGlobal('WebSocket', Socket)
  const { result } = renderHook(usePreviewSocket)
  const socket = Socket.current
  act(() => socket.onopen())
  expect(socket.sent).toEqual([{ type: 'ping', client_ms: 0 }])
  act(() => socket.receive({ type: 'pong', client_ms: 0, server_monotonic: 9 }))
  act(() => socket.receive({ type: 'status', active_coupling_id: 'test' }))
  act(() => socket.receive(event(9.5)))
  // Periodic snapshots cannot activate a scheduled event early.
  act(() => socket.receive({ type: 'frame', colour: { r: 0, g: 65535, b: 0 },
    channel_colours: [{ r: 0, g: 65535, b: 0 }], onset: true, onset_envelope: 1 }))
  act(() => vi.advanceTimersByTime(499))
  expect(result.current.onset_envelope).toBe(0)
  act(() => vi.advanceTimersByTime(17))
  expect(result.current.onset_envelope).toBe(1)
  expect(result.current.channel_colours[0]).toEqual({ r: 1, g: 0, b: 0 })
  expect(result.current.status?.onset_envelope).toBe(1)
  expect(result.current.status?.preview_clock).toEqual({ offset_ms: 9000, rtt_ms: 0 })
  act(() => vi.advanceTimersByTime(100))
  expect(result.current.channel_colours[0]).toEqual({ r: 0, g: 1, b: 0 })
  act(() => vi.advanceTimersByTime(1384))
  expect(socket.sent).toHaveLength(2)
  expect(socket.sent[1]).toEqual({ type: 'ping', client_ms: 2000 })
})

it('draws immediately while unsynchronised and cancels future events on reset', () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance', 'requestAnimationFrame', 'cancelAnimationFrame'] })
  vi.stubGlobal('WebSocket', Socket)
  const { result } = renderHook(usePreviewSocket)
  const socket = Socket.current
  act(() => socket.onopen())
  act(() => socket.receive(event(900)))
  expect(result.current.onset_envelope).toBe(1)
  expect(result.current.status?.preview_clock?.offset_ms).toBeUndefined()
  act(() => socket.receive({ type: 'preview_reset' }))
  act(() => vi.advanceTimersByTime(17))
  expect(result.current.onset_envelope).toBe(0)
})
