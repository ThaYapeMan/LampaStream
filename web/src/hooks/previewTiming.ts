export type Band = 'all' | 'bass' | 'mid' | 'treble'
export const bands: Band[] = ['all', 'bass', 'mid', 'treble']
export type Colour = { r: number; g: number; b: number }
export interface PreviewEventMessage {
  type: 'event'
  audible_monotonic: number
  events: { id: unknown; audible_monotonic: number; peaks: Record<Band, number>; bands: string[];
    channel_colours?: Colour[]; channel_accent_lifts?: number[]; accent_value?: number }[]
  event_count: number
  hold_s: number
  release_s: number
  policy: 'restart' | 'ignore_during_hold' | 'add_with_clamp'
  channel_colours: Colour[]
  channel_accent_lifts: number[]
  accent_value: number
}

export class PreviewClock {
  private samples: number[] = []
  offset: number | null = null
  rtt: number | null = null
  pong(clientMs: number, serverSeconds: number, receivedMs: number) {
    const rtt = receivedMs - clientMs
    if (!Number.isFinite(rtt) || rtt < 0 || rtt > 2000 || !Number.isFinite(serverSeconds)) return
    this.samples.push(serverSeconds * 1000 - (clientMs + receivedMs) / 2)
    this.samples = this.samples.slice(-7)
    const sorted = [...this.samples].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    this.offset = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
    this.rtt = rtt
  }
}

type Scheduled = { time: number; peaks: Record<Band, number>; message: PreviewEventMessage }
export function envelope(peak: number, age: number, hold: number, release: number) {
  return age < 0 ? 0 : peak * Math.exp(-Math.max(0, age - hold) / Math.max(.000001, release))
}

export class PreviewScheduler {
  private queue: Scheduled[] = []
  private seen = new Set<string>()
  private active = new Map<Band, { time: number; peak: number; hold: number; release: number }>()
  private last: Scheduled | null = null
  residuals: number[] = []
  enqueue(message: PreviewEventMessage, nowMs: number, offset: number | null) {
    for (const event of message.events) {
      const id = JSON.stringify(event.id)
      if (this.seen.has(id)) continue
      this.seen.add(id)
      if (this.seen.size > 1000) this.seen.delete(this.seen.values().next().value!)
      this.queue.push({ time: offset === null ? nowMs : event.audible_monotonic * 1000 - offset,
        peaks: event.peaks, message: { ...message, ...event } })
    }
    this.queue.sort((a, b) => a.time - b.time)
    this.queue = this.queue.slice(-256)
  }
  sample(nowMs: number) {
    while (this.queue.length && this.queue[0].time <= nowMs) {
      const event = this.queue.shift()!
      this.last = event
      this.residuals.push(nowMs - event.time)
      this.residuals = this.residuals.slice(-100)
      for (const band of bands) {
        if (!event.peaks[band]) continue
        const previous = this.active.get(band)
        const age = previous ? (event.time - previous.time) / 1000 : Infinity
        if (event.message.policy === 'ignore_during_hold' && previous && age < previous.hold) continue
        const extra = event.message.policy === 'add_with_clamp' && previous
          ? envelope(previous.peak, age, previous.hold, previous.release) : 0
        this.active.set(band, { time: event.time, peak: Math.min(1, event.peaks[band] + extra),
          hold: event.message.hold_s, release: event.message.release_s })
      }
    }
    const values = Object.fromEntries(bands.map(band => {
      const active = this.active.get(band)
      return [band, active ? envelope(active.peak, (nowMs - active.time) / 1000, active.hold, active.release) : 0]
    })) as Record<Band, number>
    const age = this.last ? (nowMs - this.last.time) / 1000 : Infinity
    const message = this.last?.message
    const decay = message ? envelope(1, age, message.hold_s, message.release_s) : 0
    return { values, age, colours: message && age < message.hold_s ? message.channel_colours : null,
      lifts: message?.channel_accent_lifts.map(value => value * decay) ?? [],
      accent: (message?.accent_value ?? 0) * decay }
  }
}
