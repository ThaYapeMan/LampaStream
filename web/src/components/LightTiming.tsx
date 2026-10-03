import { useEffect, useId, useRef, useState } from 'react'
import { Check, ChevronRight, Clock, Info, Lightbulb, Lock, Pause, Speaker } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { createPlayerLatency, updatePlayerLatency, type PlayerLatency } from '@/lib/api'
import type { SocketStatus } from '@/hooks/usePreviewSocket'

const seconds = (ms: number) => (ms / 1000).toFixed(2)
const signed = (ms: number) => `${ms > 0 ? '+' : ''}${ms} ms`
const time = (stamp: number | null | undefined) => stamp ? new Date(stamp * 1000).toLocaleTimeString('en-GB') : '—'

function Sparkline({ status }: { status: { source?: string; precision_ms?: number | null;
  median_residual_ms?: number | null; median_processing_ms?: number | null;
  samples?: { residual_ms?: number; processing_ms?: number; timestamp: number }[] } }) {
  const samples = status.samples ?? []
  if (!samples.length) return <p className="text-xs text-muted-foreground">Waiting for measurements.</p>
  const median = (status.source === 'lms' ? status.median_residual_ms : status.median_processing_ms ?? status.median_residual_ms) ?? 0, precision = status.precision_ms ?? 0
  const low = Math.min(median - precision, ...samples.map(s => (s.processing_ms ?? s.residual_ms ?? 0))) - 10
  const high = Math.max(median + precision, ...samples.map(s => (s.processing_ms ?? s.residual_ms ?? 0))) + 10
  const y = (v: number) => 36 - (v - low) / (high - low) * 32
  const x = (i: number) => samples.length === 1 ? 150 : 6 + i * 288 / (samples.length - 1)
  return <svg className="h-10 w-full text-primary" viewBox="0 0 300 40" preserveAspectRatio="none" role="img" aria-label={`Last ${samples.length} measurements, median ${median} milliseconds, precision ±${precision} milliseconds`}>
    <rect x="6" width="288" y={y(median + precision)} height={y(median - precision) - y(median + precision)} fill="currentColor" opacity=".15" />
    <line x1="6" x2="294" y1={y(median)} y2={y(median)} className="stroke-muted-foreground" strokeDasharray="3 3" />
    <polyline points={samples.map((s, i) => `${x(i)},${y((s.processing_ms ?? s.residual_ms ?? 0))}`).join(' ')} fill="none" stroke="currentColor" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    {samples.map((s, i) => <circle key={`${s.timestamp}-${i}`} cx={x(i)} cy={y((s.processing_ms ?? s.residual_ms ?? 0))} r="2" fill="currentColor"><title>{`${time(s.timestamp)} · ${(s.processing_ms ?? s.residual_ms ?? 0)} ms`}</title></circle>)}
  </svg>
}

export function lightTimingState(current: PlayerLatency | null | undefined, status: SocketStatus | null, airplay = false) {
  const timing = current?.status
  const group = !airplay && current?.strategy === 'auto' && (status?.follow_mode === 'sync_group' || timing?.state === 'not measurable (sync group)')
  const state = !current ? 'missing' : current.strategy === 'none' ? 'none' : group ? 'group' : timing?.state === 'not measurable' ? 'unavailable' : current.strategy === 'fixed' ? 'fixed' : airplay && (timing?.state === 'lagging' || timing?.state === 'stable' && timing?.early_delivery_ms === 0) ? 'lagging' : timing?.state === 'stable' ? 'stable' : timing?.state === 'measuring' ? 'measuring' : 'idle'
  const applied = state === 'idle' && !airplay ? Math.max(0, (current?.measured_delay_ms ?? 0) + (current?.trim_ms ?? 0)) : status?.applied_delay_ms ?? timing?.applied_delay_ms ?? 0
  return { state, applied } as const
}

export function LightTiming({ status, onOpenLatency, playersView = false, controls, footer }: { status: SocketStatus | null; onOpenLatency?: () => void; playersView?: boolean; controls?: React.ReactNode; footer?: React.ReactNode }) {
  const id = useId()
  const [open, setOpen] = useState(() => { try { return localStorage.getItem('lightTimingOpen') !== '0' } catch { return true } })
  const airplay = status?.active_player_type === 'AirPlay' || status?.light_timing?.status?.source === 'airplay'
  const mac = status?.timing_player_mac || status?.follow_target_mac || status?.sync_master
  const entry = status?.light_timing?.player_mac === mac ? status?.light_timing : null
  const lms = status?.lms_timing
  const name = lms?.synced_player_name || status?.timing_player_name || status?.follow_target_name || status?.sync_master_name || entry?.name || mac || 'the followed player'
  const [override, setOverride] = useState<PlayerLatency | null>(null)
  const [trim, setTrim] = useState(entry?.trim_ms ?? 0)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const pending = useRef(false)
  const desiredTrim = useRef<number | null>(null)
  useEffect(() => { desiredTrim.current = null; setOverride(null); setTrim(entry?.trim_ms ?? 0) }, [mac])
  useEffect(() => {
    if (override && entry?.strategy === override.strategy) setOverride(null)
    if (desiredTrim.current === entry?.trim_ms) desiredTrim.current = null
    if (!pending.current && desiredTrim.current === null) setTrim(entry?.trim_ms ?? 0)
  }, [entry, override])
  useEffect(() => { if (!message) return; const timer = setTimeout(() => setMessage(''), 4000); return () => clearTimeout(timer) }, [message])
  const current = override ?? entry
  const scheduledLms = lms?.state === 'scheduled'
  const timing = scheduledLms ? { ...current?.status, source: 'lms' as const,
    lead_p5_ms: lms.lead_p5_ms, lead_p50_ms: lms.lead_p50_ms,
    precision_ms: lms.precision_ms, sample_count: lms.sample_count ?? 0, samples: lms.samples,
    last_sample_time: lms.last_sample_time, median_residual_ms: lms.median_residual_ms,
    median_processing_ms: lms.median_processing_ms } : current?.status
  const { state: baseState, applied } = lightTimingState(current, status, airplay)
  const state = scheduledLms ? 'stable' : lms?.state === 'waiting' ? 'waiting' : lms?.state === 'unsynced' ? 'group' : baseState
  const safetyMessage = timing?.safety_message || (airplay ? status?.latency_warning : null)
  const group = state === 'group'
  const states = {
    waiting: [Clock, 'Waiting', 'text-blue-700 dark:text-blue-400 bg-blue-400/10'],
    lagging: [Clock, 'Lights behind', 'text-amber-700 dark:text-amber-400 bg-amber-400/10'],
    stable: [Check, airplay && timing?.audio_source === 'early tap' ? 'Lights on time' : 'In sync', 'text-emerald-700 dark:text-emerald-400 bg-emerald-400/10'],
    measuring: [Clock, 'Measuring', 'text-blue-700 dark:text-blue-400 bg-blue-400/10'],
    fixed: [Lock, 'Fixed', 'text-muted-foreground bg-secondary'],
    unavailable: [Info, 'Can’t measure', 'text-amber-700 dark:text-amber-400 bg-amber-400/10'],
    group: [Info, 'Can’t measure', 'text-amber-700 dark:text-amber-400 bg-amber-400/10'],
    idle: [Pause, status?.track?.playing === false ? 'Paused' : 'Idle', 'text-muted-foreground bg-secondary'],
    missing: [Info, 'Not set up', 'text-blue-700 dark:text-blue-400 bg-blue-400/10'],
    none: [Info, 'No delay', 'text-muted-foreground bg-secondary'],
  } as const
  const [Icon, label, colour] = states[state]
  async function measure() {
    if (!mac || busy) return
    setBusy(true); setError('')
    try {
      const saved = current ? await updatePlayerLatency(mac, { strategy: 'auto' }) : await createPlayerLatency({ player_mac: mac, name, strategy: 'auto' })
      setOverride({ ...current, ...saved, strategy: 'auto', status: undefined })
      setMessage('Saved · measuring automatically')
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save') }
    finally { setBusy(false) }
  }
  const measuredHeadroom = Math.max(0, (timing?.lead_p5_ms ?? 0) - (timing?.median_processing_ms ?? 0))
  const minimumTrim = lms?.state === 'scheduled' ? -Math.floor(Math.min(1000, Math.max(0, (lms.lead_p5_ms ?? 0) - (lms.median_processing_ms ?? 0))) / 10) * 10 : airplay && timing?.audio_source ? -Math.floor(Math.min(1000, measuredHeadroom) / 10) * 10 : airplay && timing?.early_delivery_ms === 0 ? 0 : -1000
  const lagText = timing?.audio_source ? `Lights about ${timing.lag_ms ?? Math.round(timing.median_processing_ms ?? 0)} ms behind` : `Lights are about ${timing?.lag_ms ?? Math.round(timing?.median_processing_ms ?? 0)} ms behind the sound`
  const tapDetails = airplay && timing?.audio_source ? <><p className="mt-2 text-xs text-muted-foreground">{timing.audio_source === 'early tap' ? `Audio arrives about ${Math.round(timing.lead_p50_ms ?? 0)} ms early (p5 ${Math.round(timing.lead_p5_ms ?? 0)} ms)` : 'Audio arrives at playout time'}</p><p className="text-xs text-muted-foreground">Source: {timing.audio_source} · Tap dropped records: {timing.tap_drop_count ?? 0}</p></> : null
  async function fineTune(delta: number) {
    if (!mac || !current || busy) return
    const next = Math.max(minimumTrim, Math.min(1000, trim + delta)), previous = trim
    desiredTrim.current = next; setTrim(next); setBusy(true); pending.current = true; setError('')
    try {
      await updatePlayerLatency(mac, { trim_ms: next })
      setMessage(next === 0 ? 'Saved · no fine-tune' : `Saved · lights ${next < 0 ? 'earlier' : 'later'} by ${Math.abs(next)} ms`)
    } catch (e) { desiredTrim.current = null; setTrim(previous); setError(e instanceof Error ? e.message : 'Could not save') }
    finally { pending.current = false; setBusy(false) }
  }
  const lmsLine = lms && <p data-testid="lms-timing" className="text-sm text-muted-foreground">{scheduledLms
    ? `Head start ${lms.lead_p5_ms == null ? '—' : Math.round(lms.lead_p5_ms)} ms · processing ${lms.median_processing_ms == null ? '—' : Math.round(lms.median_processing_ms * 10) / 10} ms · fine-tune ${trim >= 0 ? '+' : ''}${trim} ms`
    : lms.reason}</p>
  if (playersView) {
    const explanation = scheduledLms ? 'Lights follow measured LMS play times.' : state === 'lagging' ? lagText
      : state === 'stable' ? airplay && timing?.audio_source === 'early tap' ? 'Lights on time' : 'Measured automatically and kept up to date.'
      : state === 'fixed' ? 'A fixed delay you set by hand.'
      : state === 'none' ? 'The lights are not delayed.'
      : state === 'measuring' ? `Checking the timing · ${timing?.sample_count ?? 0} of 7 measurements.`
      : state === 'group' ? `LMS reports one shared position. Using your fixed fallback of ${seconds(current?.fixed_delay_ms ?? 0)} s.`
      : state === 'unavailable' ? `${timing?.reason || 'Timing is unavailable'}. Using your fixed fallback.`
      : state === 'missing' ? `Light timing has not been set up for ${name}.`
      : 'Measuring resumes when playback starts.'
    return <Card aria-labelledby={`${id}-title`} data-testid="light-timing">
      <CardHeader className="flex-row flex-wrap items-center gap-3 space-y-0 py-4">
        <h2 id={`${id}-title`} className="text-sm font-semibold">Light timing for {name}</h2>
        <Badge variant="secondary" className={`gap-1 border-0 ${colour}`}><Icon aria-hidden="true" className="h-3 w-3" />{lms?.state === 'scheduled' ? 'Scheduled · LMS head start' : label}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {lmsLine}
        <div className="grid items-center gap-4 sm:grid-cols-[minmax(0,1fr)_auto]">
          <div><div className={`text-4xl font-semibold tabular-nums ${state === 'idle' ? 'text-muted-foreground' : ''}`}>{seconds(applied)}<small className="ml-1 text-xl text-muted-foreground">s</small></div><p className="mt-2 text-sm text-muted-foreground">{explanation}</p>{tapDetails}</div>
          <div className="space-y-3 sm:text-right">{controls}
            {current?.strategy === 'auto' && <div className="space-y-1">
              <label htmlFor={`${id}-trim`} className="block text-xs text-muted-foreground">Fine-tune by ear</label>
              <div className="inline-flex max-w-full items-center overflow-hidden rounded-lg border bg-secondary">
                <Button variant="ghost" size="sm" className="px-2" aria-label="Lights 10 milliseconds earlier" disabled={busy || trim <= minimumTrim} onClick={() => fineTune(-10)}>◀ Earlier</Button>
                <output id={`${id}-trim`} aria-live="polite" className="min-w-14 border-x px-1 text-center font-mono text-xs">{signed(trim)}</output>
                <Button variant="ghost" size="sm" className="px-2" aria-label="Lights 10 milliseconds later" disabled={busy || trim >= 1000} onClick={() => fineTune(10)}>Later ▶</Button>
              </div>
            </div>}
            {!current && <Button size="sm" disabled={busy || !mac} onClick={measure}>Measure automatically</Button>}
          </div>
        </div>
        {safetyMessage && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">{safetyMessage}</p>}
        {footer}
        {message && <p role="status" className="text-xs text-emerald-700 dark:text-emerald-400">{message}</p>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  }
  return <Card aria-labelledby={`${id}-title`} data-testid="light-timing">
    <CardHeader className="flex-row flex-wrap items-center gap-3 space-y-0 py-4">
      <button className="flex items-center gap-1 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-expanded={open} aria-controls={`${id}-body`} onClick={() => { setOpen(!open); try { localStorage.setItem('lightTimingOpen', open ? '0' : '1') } catch { /* Storage may be unavailable. */ } }}>
        <ChevronRight aria-hidden="true" className={`h-4 w-4 text-muted-foreground transition-transform motion-reduce:transition-none ${open ? 'rotate-90' : ''}`} /><h2 id={`${id}-title`} className="text-base font-semibold">Light timing</h2>
      </button>
      <Badge variant="secondary" className={`gap-1 border-0 ${colour}`}><Icon aria-hidden="true" className="h-3 w-3" />{lms?.state === 'scheduled' ? 'Scheduled · LMS head start' : label}</Badge>
      {!open && <span className="font-mono text-sm tabular-nums">{state === 'none' ? 'No delay' : `${seconds(applied)} s`}</span>}
      <a href={`/players?player=${encodeURIComponent(mac ?? '')}`} className="ml-auto text-sm text-primary hover:underline" onClick={e => { if (onOpenLatency) { e.preventDefault(); onOpenLatency() } }}>Player settings</a>
    </CardHeader>
    <CardContent id={`${id}-body`} hidden={!open} className="space-y-4">
      {lmsLine}
      <div className={state === 'stable' ? 'grid gap-5 sm:grid-cols-2 items-center' : 'space-y-3'}>
        <div>
          <div className={`text-4xl font-semibold tabular-nums ${state === 'idle' ? 'text-muted-foreground' : ''}`}>
            {state === 'none' ? 'No delay' : <>{seconds(applied)}<small className="ml-1 text-xl text-muted-foreground">s</small></>}
          </div>
          {state === 'stable' && <p className="mt-2 text-sm text-muted-foreground">{scheduledLms ? <>Lights follow measured LMS play times for {name}.</> : airplay ? <>Lights follow measured audio play times for the AirPlay group.</> : <>Lights wait this long so they match what you hear on <b className="text-foreground">{name}</b>.</>}</p>}
        </div>
        {state === 'stable' && <div className="flex items-center gap-3 text-xs text-muted-foreground" aria-hidden="true">
          <span className="grid justify-items-center gap-1"><Lightbulb className="h-9 w-9 rounded-lg border bg-secondary p-2" />Lights</span>
          <div className="relative flex-1 border-t-2 border-dashed"><span className="absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap font-mono text-foreground">+{seconds(applied)} s →</span><i className="timing-dot" style={{ animationDuration: `${Math.max(.1, applied / 1000)}s` }} /></div>
          <span className="grid max-w-32 justify-items-center gap-1 text-center"><Speaker className="h-9 w-9 rounded-lg border bg-secondary p-2" />{name}</span>
        </div>}
      </div>
      {state === 'lagging' && <p className="text-sm text-muted-foreground">{lagText}</p>}
      {safetyMessage && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">{safetyMessage}</p>}
      {state === 'measuring' && <div className="space-y-3 text-sm text-muted-foreground">
        <div className="flex items-center gap-3"><svg className="h-11 w-11 text-blue-700 dark:text-blue-400" viewBox="0 0 44 44" role="img" aria-label={`${timing?.sample_count ?? 0} of 7 measurements`}><circle cx="22" cy="22" r="18" fill="none" className="stroke-secondary" strokeWidth="4" /><circle cx="22" cy="22" r="18" fill="none" stroke="currentColor" strokeWidth="4" strokeDasharray={`${113 * Math.min(7, timing?.sample_count ?? 0) / 7} 113`} transform="rotate(-90 22 22)" /></svg><span>Checking the timing against {name} · {timing?.sample_count ?? 0} of 7 measurements.</span></div>
        <p>The lights keep the last good delay ({seconds(applied)} s) until the new measurement is steady.</p>
      </div>}
      {state === 'fixed' && <p className="text-sm text-muted-foreground">A fixed delay you set by hand for <b className="text-foreground">{name}</b>. Switch to Auto to have LampaStream measure it and keep it right when the network changes.</p>}
      {state === 'group' && !lms && <div className="space-y-3 text-sm text-muted-foreground"><p>The lights player is in a sync group with {name}, so LMS reports one shared position and there is nothing to compare. Using your fixed fallback of {seconds(current?.fixed_delay_ms ?? 0)} s.</p><p>To measure automatically, set the virtual player's follow mode to <b className="text-foreground">Manual — fixed player</b>.</p></div>}
      {state === 'unavailable' && <p className="text-sm text-muted-foreground">{timing?.reason}. Using your fixed fallback of {seconds(current?.fixed_delay_ms ?? 0)} s.</p>}
      {state === 'idle' && <p className="text-sm text-muted-foreground">Last measured for {name} at {time(current?.measured_at)}. Measuring resumes when playback starts.</p>}
      {state === 'missing' && <p className="text-sm text-muted-foreground">Light timing has not been set up for {name}. Measure automatically to match what you hear.</p>}
      {state === 'none' && <p className="text-sm text-muted-foreground">The lights run without a delay for {name}. Measure automatically to match what you hear.</p>}
      {['fixed', 'missing', 'none'].includes(state) && <Button size="sm" disabled={busy || !mac} onClick={measure}>Measure automatically</Button>}
      {current?.strategy === 'auto' && !group && <div className="grid gap-4 border-t pt-4 sm:grid-cols-[1fr_auto] items-end">
        <div className="space-y-2">{state === 'stable' && timing && <><div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>Steady to within ±{timing.precision_ms ?? '—'} ms</span><span>{timing.sample_count} measurements · {time(timing.last_sample_time)}</span></div><Sparkline status={timing} /></>}</div>
        <div className="space-y-1"><label htmlFor={`${id}-trim`} className="block text-xs text-muted-foreground sm:text-right">Fine-tune by ear</label><div className="inline-flex items-center overflow-hidden rounded-lg border bg-secondary"><Button variant="ghost" size="sm" aria-label="Lights 10 milliseconds earlier" disabled={busy || trim <= minimumTrim} onClick={() => fineTune(-10)}>◀ Earlier</Button><output id={`${id}-trim`} aria-live="polite" className="min-w-20 border-x px-2 text-center font-mono text-sm">{signed(trim)}</output><Button variant="ghost" size="sm" aria-label="Lights 10 milliseconds later" disabled={busy || trim >= 1000} onClick={() => fineTune(10)}>Later ▶</Button></div></div>
      </div>}
      <p role="status" className="min-h-4 text-xs text-emerald-700 dark:text-emerald-400">{message}</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <details className="border-t pt-3 text-sm"><summary className="cursor-pointer text-muted-foreground">Details</summary><dl className="mt-3 grid max-w-sm grid-cols-[1fr_auto] gap-x-4 gap-y-1 [&_dt]:text-muted-foreground [&_dd]:text-right [&_dd]:font-mono">{airplay || scheduledLms ? <><dt>Measured early arrival (p5)</dt><dd>{timing?.lead_p5_ms ?? timing?.early_delivery_ms ?? '—'} ms</dd><dt>Processing (P)</dt><dd>{timing?.median_processing_ms ?? '—'} ms</dd></> : <><dt>Measured difference</dt><dd>{timing?.median_residual_ms ?? '—'} ms</dd><dt>Player Delay (set in LMS)</dt><dd>{timing?.player_delay_ms ?? '—'} ms</dd></>}<dt>Your fine-tune</dt><dd>{signed(trim)}</dd><dt className="border-t pt-2">Applied to the lights</dt><dd className="border-t pt-2">{applied} ms</dd></dl>{tapDetails}<p className="mt-3 text-xs text-muted-foreground">{scheduledLms ? 'Measured from the virtual player’s write clock. Steadiness and measurements describe the current timing fit.' : airplay ? 'Measured from audio receipt to Hue output, excluding the deliberate wait. Fine-tune covers the lamps’ physical response.' : "Measured automatically by comparing both players' positions in LMS. Rechecked every 15 s and after each track change."}</p></details>
    </CardContent>
  </Card>
}
