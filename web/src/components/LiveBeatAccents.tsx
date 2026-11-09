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
  const values = () => ({ agc_max_gain:String(profile?.agc_max_gain ?? 64), tracker_gain_floor:String(profile?.tracker_gain_floor ?? .3), onset_relative_k:String(profile?.onset_relative_k ?? 2), onset_reference_window_s:String(profile?.onset_reference_window_s ?? 3), onset_refractory_ms:String(profile?.onset_refractory_ms ?? 120), onset_full_k:String(profile?.onset_full_k ?? 3) })
  const [draft, setDraft] = useState(values)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => { clearTimeout(timer.current); setDraft(values()) }, [profile])
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
    const valid = value.trim() && Number.isFinite(number) && (
      field === 'agc_max_gain' ? number >= 8 : field === 'tracker_gain_floor' ? number >= 0 && number <= 1
      : field === 'onset_refractory_ms' ? number >= 60 && number <= 200
      : field === 'onset_reference_window_s' ? number > 0 : number > 1)
    if (!valid || (field === 'onset_full_k' && number < Number(draft.onset_relative_k))) {
      setError('Require gain ≥8, k >1, window >0, refractory 60–200 ms and full ratio ≥ onset ratio'); return
    }
    if (profile && number !== Number(values()[field])) {
      const body: Partial<EnergyProfile> = { [field]: number }
      if (field === 'onset_relative_k' && number > (profile.onset_full_k ?? 3)) body.onset_full_k = number+1
      void save(async () => onProfile(await updateEnergyProfile(profile.id, body)))
    }
  }
  const fields = [
    ['agc_max_gain','AGC ceiling','×',8],
    ['onset_relative_k','Onset ratio','×',.1],
    ['onset_reference_window_s','Window','s',.5],
    ['onset_refractory_ms','Refractory','ms',10],
    ['onset_full_k','Full ratio','×',.1],
    ['tracker_gain_floor','Tracker floor','',.05],
  ] as const

  return <section aria-label="Live accents" className="space-y-2">
    <div className="flex min-h-11 flex-wrap items-center gap-3">
      <span className="text-sm text-muted-foreground">Beat accent</span>
      <SegmentedControl fit label="Beat accent" value={coupling?.beat_accent_mode ?? 'onset'}
        options={[{value:'off', label:'Off'}, {value:'onset', label:'Onset'}, {value:'tracker', label:'Tracker'}]}
        disabled={!coupling} pending={busy}
        onChange={value => void save(async () => onCoupling(await updateCoupling(coupling!.id, { beat_accent_mode: value as Coupling['beat_accent_mode'] })))} />
      <span className="text-xs text-muted-foreground">{coupling?.name ?? 'No active coupling'}</span>
    </div>
    <div className="flex min-h-12 flex-wrap items-center gap-3">
      {fields.map(([field,label,unit,step]) => <CompactEnergyNumber key={field}
        label={label} unit={unit} value={draft[field]} step={step}
        disabled={!coupling || !profile || busy} invalid={!!error}
        onChange={value => { clearTimeout(timer.current); setDraft(d => ({...d, [field]:value})) }}
        onCommit={() => commit(field, draft[field])}
        onStep={value => { clearTimeout(timer.current); setDraft(d => ({...d, [field]:value})); timer.current = setTimeout(() => commit(field, value), 250) }} />)}
    </div>
    <p className="min-h-4 text-xs text-muted-foreground">Energy Profile · {profile?.name ?? '—'}</p>
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </section>
}
