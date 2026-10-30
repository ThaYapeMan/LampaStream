import { PreviewClock, PreviewScheduler, type PreviewEventMessage } from './previewTiming'
import type { AccentFeatures } from '@/lib/api'
import type { PlayerLatency } from '@/lib/api'
import { useEffect, useRef, useState } from 'react'

export interface TrackPosition {
  title: string | null
  artist: string | null
  position_s: number | null
  duration_s: number | null
  playing: boolean
}

export interface SocketStatus extends AccentFeatures {
  preview_clock?: { offset_ms: number | null; epoch_offset_ms?: number | null; rtt_ms: number | null }
  music?: import('@/lib/api').MusicStatus | null
  timing_player_mac?: string | null
  timing_player_name?: string | null
  lms_timing?: { state: string; reason?: string | null; audio_source?: string;
    head_start_ms?: number; speaker_output_delay_ms?: number; lead_p5_ms?: number | null;
    lead_p50_ms?: number | null; median_processing_ms?: number | null; tap_drop_count?: number; synced_player_name?: string | null; precision_ms?: number | null;
    sample_count?: number; last_sample_time?: number | null; median_residual_ms?: number | null;
    samples?: { residual_ms: number; timestamp: number }[] } | null
  light_timing?: PlayerLatency | null
  follow_target_mac?: string | null
  follow_target_name?: string | null
  track?: TrackPosition | null
  version: string | null
  active_coupling_id: string | null
  active_coupling_name: string | null
  active_player_type: string | null
  active_zone_id: string | null
  active_energy_profile_id: string | null
  follow_mode?: "manual" | "sync_group" | null
  sync_master: string | null
  sync_master_name: string | null
  applied_delay_ms: number
  latency_warning: string | null
  processes: { lms_player: boolean }
  output_status?: { state: "streaming" | "reconnecting" | "failed" | "released"; reason: string | null; release_kind?: "explicit" | "external" | "idle" } | null
  bridge_connected: boolean
  effect_type: string | null
  follower_warning: string | null
  onset_method: string | null
  lower_cutoff_freq: number | null
  higher_cutoff_freq: number | null
  bass_hz: number | null
  mid_hz: number | null
  airplay_receiving: boolean | null
}

export interface PreviewState extends AccentFeatures {
  colour: { r: number; g: number; b: number }
  channel_colours: Array<{ r: number; g: number; b: number }>
  onset: boolean
  outlinePulse?: number
  onset_bass: boolean
  onset_mid: boolean
  onset_treble: boolean
  mix: number
  energy: number
  sustained_energy?: number | null
  last_energy_input?: number
  loudness_momentary_lufs: number | null
  loudness_short_term_lufs: number | null
  normalised_bars?: number[]
  bars: number[]
  status: SocketStatus | null
  connected: boolean
  reconnectAttempt: number
}

const INITIAL_STATE: PreviewState = {
  colour: { r: 0, g: 0, b: 0 },
  channel_colours: [],
  onset: false,
  onset_bass: false,
  onset_mid: false,
  onset_treble: false,
  mix: 0,
  energy: 0,
  last_energy_input: 0,
  loudness_momentary_lufs: null,
  loudness_short_term_lufs: null,
  bars: [],
  status: null,
  connected: false,
  reconnectAttempt: 0,
}

export function usePreviewSocket(): PreviewState {
  const [state, setState] = useState<PreviewState>(INITIAL_STATE)
  const onsetTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const bassTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const midTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const trebleTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let attempt = 0
    let stopped = false
    let clock = new PreviewClock()
    let scheduler = new PreviewScheduler()
    let eventMode = false
    let pingTimer: ReturnType<typeof setInterval> | null = null
    let animation = 0
    let continuous: PreviewState['channel_colours'] = []
    function animate(now: number) {
      if (eventMode) {
        const sample = scheduler.sample(now)
        const channels = sample.colours?.map(c => ({ r: c.r / 65535, g: c.g / 65535, b: c.b / 65535 })) ?? continuous
        const features: AccentFeatures = {
          onset_envelope: sample.values.all, onset_envelope_bass: sample.values.bass,
          onset_envelope_mid: sample.values.mid, onset_envelope_treble: sample.values.treble,
          channel_accent_lifts: sample.lifts, accent_value: sample.accent,
          onset_age_s: Number.isFinite(sample.age) ? sample.age : null,
        }
        setState(s => ({ ...s, ...features, outlinePulse: sample.pulse, channel_colours: channels, colour: channels[0] ?? s.colour,
          onset: sample.values.all > .5, onset_bass: sample.values.bass > .5,
          onset_mid: sample.values.mid > .5, onset_treble: sample.values.treble > .5,
          status: s.status ? { ...s.status, ...features } : null }))
      }
      animation = requestAnimationFrame(animate)
    }
    animation = requestAnimationFrame(animate)

    const ping = () => ws?.send(JSON.stringify({ type: 'ping', client_ms: performance.now() }))

    function connect() {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
      ws = new WebSocket(`${proto}//${location.host}/ws/preview`)

      ws.onopen = () => {
        attempt = 0
        clock = new PreviewClock()
        scheduler = new PreviewScheduler()
        eventMode = false
        ping()
        if (pingTimer) clearInterval(pingTimer)
        pingTimer = setInterval(ping, 2000)
        setState((s) => ({ ...s, connected: true, reconnectAttempt: 0,
          status: s.status ? { ...s.status, preview_clock: { offset_ms: null, rtt_ms: null } } : null }))
      }

      ws.onclose = () => {
        if (pingTimer) clearInterval(pingTimer)
        eventMode = false
        setState((s) => ({ ...s, connected: false, reconnectAttempt: attempt, loudness_momentary_lufs: null, loudness_short_term_lufs: null }))
        if (!stopped) {
          // Exponential backoff: 250 ms → 500 → 1 s → 2 s → 4 s, cap at 5 s.
          const delay = Math.min(250 * Math.pow(2, attempt), 5000)
          attempt++
          reconnectTimer = setTimeout(connect, delay)
        }
      }

      ws.onerror = () => {
        ws?.close()
      }

      ws.onmessage = (event: MessageEvent) => {
        const msg = JSON.parse(event.data as string) as Record<string, unknown>

        if (msg.type === 'pong') {
          clock.pong(msg.client_ms as number, msg.server_monotonic as number, performance.now())
          setState(s => ({ ...s, status: s.status ? { ...s.status,
            preview_clock: { offset_ms: clock.residual, epoch_offset_ms: clock.offset, rtt_ms: clock.rtt } } : null }))
        } else if (msg.type === 'preview_reset') {
          clock = new PreviewClock()
          ping()
          setState(s => ({ ...s, status: s.status ? { ...s.status,
            preview_clock: { offset_ms: null, rtt_ms: null } } : null }))
          scheduler = new PreviewScheduler()
          eventMode = true
        } else if (msg.type === 'event') {
          eventMode = true
          scheduler.enqueue(msg as unknown as PreviewEventMessage, performance.now(), clock.offset)
          if (clock.offset === null) { cancelAnimationFrame(animation); animate(performance.now()) }
        } else if (msg.type === 'frame') {
          const c = msg.colour as { r: number; g: number; b: number }
          // Values arrive as 16-bit (0–65535); normalise to 0–1 for CSS.
          const colour = { r: c.r / 65535, g: c.g / 65535, b: c.b / 65535 }
          const raw_channels = (msg.channel_colours as Array<{ r: number; g: number; b: number }>) ?? []
          const channel_colours = raw_channels.map((ch) => ({
            r: ch.r / 65535,
            g: ch.g / 65535,
            b: ch.b / 65535,
          }))
          continuous = channel_colours
          const onset = !eventMode && msg.onset as boolean
          const onset_bass = !eventMode && ((msg.onset_bass as boolean) ?? false)
          const onset_mid = !eventMode && ((msg.onset_mid as boolean) ?? false)
          const onset_treble = !eventMode && ((msg.onset_treble as boolean) ?? false)
          const mix = (msg.mix as number) ?? 0
          const energy = (msg.energy as number) ?? 0

          const rhythm: AccentFeatures = {
            tempo_bpm: msg.tempo_bpm as number | null,
            tempo_alt_bpm: msg.tempo_alt_bpm as number | null,
            tempo_locked: msg.tempo_locked as boolean,
            tempo_confidence: msg.tempo_confidence as number,
            beat_phase: msg.beat_phase as number,
            beat_events_per_second: msg.beat_events_per_second as number,
            texture_events_per_second: msg.texture_events_per_second as number,
            agc_gain: msg.agc_gain as number,
            trigger_ratio: msg.trigger_ratio as number,
            beat_grid: msg.beat_grid as AccentFeatures['beat_grid'],
          }
          const accentFeatures: AccentFeatures = {
            audible_monotonic: (msg.audible_monotonic as number | null) ?? null,
            channel_accent_lifts: msg.channel_accent_lifts as number[] | undefined,
            onset_events: msg.onset_events as AccentFeatures['onset_events'],
            onset_envelope: msg.onset_envelope as number | undefined,
            onset_envelope_bass: (msg.onset_envelope_bass as number) ?? 0,
            onset_envelope_mid: (msg.onset_envelope_mid as number) ?? 0,
            onset_envelope_treble: (msg.onset_envelope_treble as number) ?? 0,
            onset_count_since_render: (msg.onset_count_since_render as number) ?? 0,
            onset_age_s: (msg.onset_age_s as number | null) ?? null,
            accent_value: (msg.accent_value as number) ?? 0,
            capabilities: msg.capabilities as AccentFeatures['capabilities'],
          }
          setState((s) => ({
            ...s,
            ...(!eventMode ? accentFeatures : {}),
            status: s.status ? { ...s.status, ...rhythm, ...(!eventMode ? accentFeatures : {}) } : null,
            colour: eventMode ? s.colour : colour,
            channel_colours: eventMode ? s.channel_colours : channel_colours,
            onset: onset || s.onset,
            onset_bass: onset_bass || s.onset_bass,
            onset_mid: onset_mid || s.onset_mid,
            onset_treble: onset_treble || s.onset_treble,
            mix,
            energy,
            sustained_energy: (msg.sustained_energy as number | null) ?? null,
            last_energy_input: (msg.last_energy_input as number) ?? 0,
            loudness_momentary_lufs: (msg.loudness_momentary_lufs as number | null) ?? null,
            loudness_short_term_lufs: (msg.loudness_short_term_lufs as number | null) ?? null,
          }))

          if (onset) {
            if (onsetTimer.current) clearTimeout(onsetTimer.current)
            onsetTimer.current = setTimeout(
              () => setState((s) => ({ ...s, onset: false })),
              80
            )
          }
          if (onset_bass) {
            if (bassTimer.current) clearTimeout(bassTimer.current)
            bassTimer.current = setTimeout(
              () => setState((s) => ({ ...s, onset_bass: false })),
              80
            )
          }
          if (onset_mid) {
            if (midTimer.current) clearTimeout(midTimer.current)
            midTimer.current = setTimeout(
              () => setState((s) => ({ ...s, onset_mid: false })),
              80
            )
          }
          if (onset_treble) {
            if (trebleTimer.current) clearTimeout(trebleTimer.current)
            trebleTimer.current = setTimeout(
              () => setState((s) => ({ ...s, onset_treble: false })),
              80
            )
          }
        } else if (msg.type === 'spectrum') {
          setState((s) => ({ ...s, bars: msg.bars as number[], normalised_bars: msg.normalised_bars as number[] | undefined }))
        } else if (msg.type === 'status') {
          const { type: _ignored, ...fields } = msg
          setState((s) => ({ ...s, status: { ...s.status, ...fields,
            preview_clock: { offset_ms: clock.residual, epoch_offset_ms: clock.offset, rtt_ms: clock.rtt } } as unknown as SocketStatus }))
        }
      }
    }

    connect()

    return () => {
      stopped = true
      cancelAnimationFrame(animation)
      if (pingTimer) clearInterval(pingTimer)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (onsetTimer.current) clearTimeout(onsetTimer.current)
      if (bassTimer.current) clearTimeout(bassTimer.current)
      if (midTimer.current) clearTimeout(midTimer.current)
      if (trebleTimer.current) clearTimeout(trebleTimer.current)
      ws?.close()
    }
  }, [])

  return state
}
