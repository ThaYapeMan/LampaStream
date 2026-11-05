import { useEffect, useRef, useState } from 'react'
import { updateCoupling, updateEnergyProfile, type Coupling, type EnergyProfile } from '@/lib/api'
import { CompactEnergyNumber } from './EnergyBlendEditor'
import { SegmentedControl } from './SegmentedControl'

export function LiveBeatAccents({ coupling, profile, onCoupling, onProfile }: {
  coupling?: Coupling; profile?: EnergyProfile
  onCoupling: (value: Coupling) => void; onProfile: (value: EnergyProfile) => void
}) {
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState({ agc_max_gain: String(profile?.agc_max_gain ?? 64), onset_gain_floor: String(profile?.onset_gain_floor ?? .3) })
  const timer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => { clearTimeout(timer.current); setDraft({ agc_max_gain: String(profile?.agc_max_gain ?? 64), onset_gain_floor: String(profile?.onset_gain_floor ?? .3) }) }, [profile])
  useEffect(() => () => clearTimeout(timer.current), [])
  async function save(action: () => Promise<void>) {
    if (pending.current || !coupling) return
    pending.current = true; setBusy(true); setError('')
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : 'Could not save accents') }
    finally { pending.current = false; setBusy(false) }
  }
  function commit(field: keyof typeof draft, value: string) {
    clearTimeout(timer.current)
    const number = Number(value)
    if (!value.trim() || !Number.isFinite(number) || (field === 'agc_max_gain' ? number < 8 : number < 0 || number > 1)) {
      setError('AGC ceiling must be at least 8; trigger floor must be 0–1'); return
    }
    if (profile && number !== (profile[field] ?? (field === 'agc_max_gain' ? 64 : .3)))
      void save(async () => onProfile(await updateEnergyProfile(profile.id, { [field]: number })))
  }
  return <section aria-label="Live accents" className="space-y-2">
    <div className="flex min-h-11 flex-wrap items-center gap-3">
      <span className="text-sm text-muted-foreground">Beat accent</span>
      <SegmentedControl fit label="Beat accent" value={coupling?.beat_accent_mode ?? 'onset'}
        options={[{value:'off', label:'Off'}, {value:'onset', label:'Onset'}, {value:'tracker', label:'Tracker'}]}
        disabled={!coupling} pending={busy}
        onChange={value => void save(async () => onCoupling(await updateCoupling(coupling!.id, { beat_accent_mode: value as Coupling['beat_accent_mode'] })))} />
      <span className="text-xs text-muted-foreground">{coupling?.name ?? 'No active coupling'}</span>
    </div>
    <div className="flex min-h-6 flex-wrap items-center gap-5">
      {(['agc_max_gain', 'onset_gain_floor'] as const).map(field => <CompactEnergyNumber key={field}
        label={field === 'agc_max_gain' ? 'AGC ceiling' : 'Trigger floor at ceiling'} unit={field === 'agc_max_gain' ? '×' : ''}
        value={draft[field]} step={field === 'agc_max_gain' ? 8 : .05} disabled={!coupling || !profile || busy} invalid={!!error}
        onChange={value => { clearTimeout(timer.current); setDraft(d => ({...d, [field]:value})) }}
        onCommit={() => commit(field, draft[field])}
        onStep={value => { clearTimeout(timer.current); setDraft(d => ({...d, [field]:value})); timer.current = setTimeout(() => commit(field, value), 250) }} />)}
    </div>
    <p className="min-h-4 text-xs text-muted-foreground">Energy Profile · {profile?.name ?? '—'}</p>
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </section>
}
