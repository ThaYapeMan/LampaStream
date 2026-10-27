import { afterEach, describe, expect, it, vi } from 'vitest'
import { envelope, PreviewClock, PreviewScheduler, type PreviewEventMessage } from '../hooks/previewTiming'

const message = (time = 10, id = 'first'): PreviewEventMessage => ({
  type: 'event', audible_monotonic: time, event_count: 1,
  events: [{ id, audible_monotonic: time, bands: ['bass'], peaks: { all: 1, bass: .8, mid: 0, treble: 0 } }],
  hold_s: .08, release_s: .25, policy: 'restart', channel_colours: [{ r: 30000, g: 0, b: 0 }],
  channel_accent_lifts: [.4], accent_value: .35,
})
afterEach(() => vi.useRealTimers())

describe('audible preview scheduling', () => {
  it('activates on the first animation frame at or after audible time, never early', () => {
    vi.useFakeTimers()
    const scheduler = new PreviewScheduler()
    scheduler.enqueue(message(), 0, 9000)
    let now = 0
    const samples: { time: number; value: number }[] = []
    const timer = setInterval(() => { now += 16; samples.push({ time: now, value: scheduler.sample(now).values.all }) }, 16)
    vi.advanceTimersByTime(1100)
    clearInterval(timer)
    expect(samples.filter(s => s.time < 1000).every(s => s.value === 0)).toBe(true)
    const first = samples.find(s => s.value > 0)!
    expect(first.time).toBeGreaterThanOrEqual(1000)
    expect(first.time).toBeLessThanOrEqual(1016)
    expect(scheduler.residuals).toEqual([8])
    console.log('scheduled activation minus audible: 8 ms (16 ms animation frames); never early')
  })
  it('falls back immediately without an offset and deduplicates events', () => {
    const scheduler = new PreviewScheduler()
    scheduler.enqueue(message(), 123, null)
    scheduler.enqueue(message(), 123, null)
    expect(scheduler.sample(123).values.all).toBe(1)
    expect(scheduler.residuals).toEqual([0])
  })
  it('keeps coalesced events on their individual timestamps', () => {
    const scheduler = new PreviewScheduler()
    const burst = message()
    burst.events.push({ ...burst.events[0], id: 'second', audible_monotonic: 10.004 })
    scheduler.enqueue(burst, 0, 9000)
    scheduler.sample(1000)
    expect(scheduler.residuals).toEqual([0])
    scheduler.sample(1003)
    expect(scheduler.residuals).toEqual([0])
    scheduler.sample(1004)
    expect(scheduler.residuals).toEqual([0, 0])
  })
  it('matches hold and exponential release, and releases event colours after hold', () => {
    const scheduler = new PreviewScheduler()
    scheduler.enqueue(message(), 0, 9000)
    expect(scheduler.sample(1000).colours).toEqual(message().channel_colours)
    expect(scheduler.sample(1079).values.all).toBe(1)
    const tail = scheduler.sample(1330)
    expect(tail.values.all).toBeCloseTo(Math.exp(-1), 12)
    expect(tail.values.bass).toBeCloseTo(.8 * Math.exp(-1), 12)
    expect(tail.lifts[0]).toBeCloseTo(.4 * Math.exp(-1), 12)
    expect(tail.colours).toBeNull()
    expect(envelope(1, -1, .08, .25)).toBe(0)
  })
  it('retains restart, ignore-during-hold and additive envelope policies', () => {
    for (const policy of ['restart', 'ignore_during_hold', 'add_with_clamp'] as const) {
      const scheduler = new PreviewScheduler()
      const first = message(); first.events[0].peaks.all = .6
      scheduler.enqueue(first, 0, 9000); scheduler.sample(1000)
      const second = message(10.04, 'second'); second.policy = policy; second.events[0].peaks.all = .5
      scheduler.enqueue(second, 0, 9000)
      expect(scheduler.sample(1040).values.all).toBe(policy === 'restart' ? .5 : policy === 'ignore_during_hold' ? .6 : 1)
    }
  })
})

it('estimates server minus browser time with midpoint RTT and median jitter filtering', () => {
  const clock = new PreviewClock()
  expect(clock.offset).toBeNull()
  for (const [i, jitter] of [2, -1, 100, 0, -2, 1, 0].entries()) {
    const sent = i * 2000, rtt = 20 + i * 3
    clock.pong(sent, (sent + rtt / 2 + 9000 + jitter) / 1000, sent + rtt)
  }
  expect(clock.offset).toBe(9000)
  expect(clock.rtt).toBe(38)
  clock.pong(20, NaN, 30)
  expect(clock.offset).toBe(9000)
})
