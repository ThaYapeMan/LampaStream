import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { correctTempo, getTempoMetadata, type TempoMetadata } from '@/lib/api'

export function OwnerTempo({ active }: { active: boolean }) {
  const [state, setState] = useState<TempoMetadata | null>(null)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const [error, setError] = useState('')
  const taps = useRef<number[]>([])
  const [count, setCount] = useState(0)
  const identity = useRef<string | null>(null)
  useEffect(() => {
    let cancelled = false
    async function read() {
      if (!active) { setState(null); return }
      try {
        const result = await getTempoMetadata()
        if (cancelled) return
        if (result.identity !== identity.current) {
          taps.current = []; setCount(0); identity.current = result.identity
        }
        setState(result)
      } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : 'Could not read track correction') }
    }
    void read()
    const timer = setInterval(() => void read(), 2000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [active])
  async function save(action: 'half' | 'double' | 'tap' | 'nudge', tempo?: number, nudge_ms?: number) {
    if (!state?.confirmed || !state.identity || pending.current) return
    pending.current = true; setBusy(true); setError('')
    try { setState(await correctTempo({ identity: state.identity, action, tempo, nudge_ms })) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not save correction') }
    finally { pending.current = false; setBusy(false) }
  }
  function tap() {
    const now = performance.now()
    if (taps.current.length && now - taps.current[taps.current.length - 1] > 3000) taps.current = []
    taps.current = [...taps.current, now].slice(-8)
    setCount(taps.current.length)
    if (taps.current.length >= 3) {
      const intervals = taps.current.slice(1).map((t, i) => t - taps.current[i]).sort((a, b) => a - b)
      const bpm = 60000 / intervals[Math.floor(intervals.length / 2)]
      if (bpm >= 20 && bpm <= 400) void save('tap', bpm)
    }
  }
  const disabled = !active || !state?.confirmed || busy
  return <section aria-label="Track correction" className="space-y-2 border-t pt-4">
    <div className="flex min-h-11 flex-wrap items-center gap-2">
      <span className="text-sm text-muted-foreground">Track correction</span>
      <Button variant="outline" className="min-h-11" disabled={disabled || !state?.tempo} onClick={() => void save('half')}>Half tempo</Button>
      <Button variant="outline" className="min-h-11" disabled={disabled || !state?.tempo} onClick={() => void save('double')}>Double tempo</Button>
      <Button variant="outline" className="min-h-11" disabled={disabled} onClick={tap}>Tap tempo{count ? ` (${count})` : ''}</Button>
      <Button variant="outline" className="min-h-11" disabled={disabled} onClick={() => void save('nudge', undefined, -20)}>Phase −20 ms</Button>
      <Button variant="outline" className="min-h-11" disabled={disabled} onClick={() => void save('nudge', undefined, 20)}>Phase +20 ms</Button>
    </div>
    <p className="text-xs text-muted-foreground" role="status">{state?.confirmed
      ? state.resolved_tempo?.provider === 'owner'
        ? `Saved correction · ${state.tempo?.toFixed(1)} BPM · phase ${Math.round(state.phase_offset_s * 1000)} ms`
        : 'Corrections are saved for this audio recording. Audio still confirms accents.'
      : state?.reason ?? 'Activate a coupling to correct this recording.'}</p>
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </section>
}
