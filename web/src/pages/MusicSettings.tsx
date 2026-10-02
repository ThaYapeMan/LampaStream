import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { getMusicSettings, updateMusicSettings, getPalettes, getEnergyProfiles, saveGenreRule, updateGenreRule, deleteGenreRule, type MusicSettings as Settings, type GenreRule, type Palette, type EnergyProfile } from '@/lib/api'

const selectStyle = 'min-h-11 w-full rounded-md border border-input bg-background px-3 text-sm'
export function MusicSettings() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [palettes, setPalettes] = useState<Palette[]>([])
  const [profiles, setProfiles] = useState<EnergyProfile[]>([])
  const [mapping, setMapping] = useState<Array<[string, string]>>([])
  const [key, setKey] = useState('')
  const [removeKey, setRemoveKey] = useState(false)
  const [rules, setRules] = useState<GenreRule[]>([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { Promise.all([getMusicSettings(), getPalettes(), getEnergyProfiles()]).then(([s, p, e]) => { setSettings(s); setMapping(Object.entries(s.genre_mapping)); setRules(s.rules); setPalettes(p); setProfiles(e) }).catch(e => setError(String(e))) }, [])
  async function action(fn: () => Promise<void>) { setBusy(true); setError(''); setMessage(''); try { await fn() } catch (e) { setError(e instanceof Error ? e.message : 'Could not save settings') } finally { setBusy(false) } }
  async function save() {
    if (!settings) return
    const raw = mapping.map(([tag]) => tag.trim().toLowerCase())
    if (raw.some(tag => !tag) || new Set(raw).size !== raw.length) throw new Error('Each raw tag needs a unique name')
    const updated = await updateMusicSettings({ lastfm_enabled: settings.lastfm_enabled, genre_mapping: Object.fromEntries(mapping), transition_mode: settings.transition_mode, transition_duration_s: settings.transition_duration_s, ...(key || removeKey ? { lastfm_api_key: key } : {}) })
    setSettings({ ...settings, ...updated }); setKey(''); setRemoveKey(false); setMessage('Music settings saved')
  }
  return <section className="min-w-0 space-y-6"><header><h1 className="text-2xl font-semibold">Music settings</h1><p className="text-sm text-muted-foreground">Let the track guide the colours. Your choices always come first.</p></header>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!settings ? <p role="status">Loading settings…</p> : <>
      <Card><CardHeader><CardTitle>Genre detection</CardTitle></CardHeader><CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">Track tags are used first. If a tag is missing or unrecognised, Last.fm can suggest a genre.</p>
        <label className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" className="h-5 w-5" disabled={busy} checked={settings.lastfm_enabled} onChange={e => { const enabled = e.target.checked; setSettings({ ...settings, lastfm_enabled: enabled }); action(async () => { try { const updated = await updateMusicSettings({ lastfm_enabled: enabled }); setSettings({ ...settings, ...updated }); setMessage(enabled ? 'Last.fm lookup enabled' : 'Last.fm lookup switched off') } catch (error) { setSettings(settings); throw error } }) }} />Look up missing tags with Last.fm</label>
        <p className="text-sm text-muted-foreground">When enabled, artist and track names are sent to Last.fm. When off, nothing is sent.</p>
        <label className="block max-w-lg space-y-2 text-sm">API key<Input type="password" autoComplete="new-password" className="min-h-11" value={key} onChange={e => { setKey(e.target.value); setRemoveKey(false) }} placeholder={settings.api_key_configured ? 'A key is saved. Leave blank to keep it.' : 'Your Last.fm API key'} /></label>
        {settings.api_key_configured && <Button variant="outline" className="min-h-11" onClick={() => { setRemoveKey(true); setKey(''); setMessage('The saved key will be removed when you save') }}>Remove saved key</Button>}
        <p className="text-xs text-muted-foreground">Genre suggestions powered by <a href="https://www.last.fm" className="text-primary underline">Last.fm</a>. <a href="https://www.last.fm/api/tos" className="text-primary underline">API terms</a></p>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Genre rules</CardTitle></CardHeader><CardContent className="space-y-4"><p className="text-sm text-muted-foreground">Applied on track changes. A manual choice on Now Playing takes priority until you clear it.</p>
        {rules.map((rule, i) => <div key={rule.id} className="grid gap-3 rounded-lg border p-4 md:grid-cols-3">
          <label className="space-y-2 text-sm">Genre<select aria-label={`Rule ${i + 1} genre`} className={selectStyle} value={rule.genre} onChange={e => setRules(rules.map((r, j) => i === j ? { ...r, genre: e.target.value } : r))}>{settings.genres.map(g => <option key={g}>{g}</option>)}</select></label>
          <label className="space-y-2 text-sm">Palette<select aria-label={`Rule ${i + 1} palette`} className={selectStyle} value={rule.palette_id} onChange={e => setRules(rules.map((r, j) => i === j ? { ...r, palette_id: e.target.value } : r))}><option value="">Keep current</option><option value="album-art">Album art</option>{palettes.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <label className="space-y-2 text-sm">Energy Profile<select aria-label={`Rule ${i + 1} energy profile`} className={selectStyle} value={rule.energy_profile_id} onChange={e => setRules(rules.map((r, j) => i === j ? { ...r, energy_profile_id: e.target.value } : r))}><option value="">Keep current</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <div className="flex flex-wrap gap-2 md:col-span-3"><Button className="min-h-11" disabled={busy} onClick={() => action(async () => { const body = { genre: rule.genre, palette_id: rule.palette_id, energy_profile_id: rule.energy_profile_id }; const saved = await (rule.id.startsWith('new-') ? saveGenreRule(body) : updateGenreRule(rule.id, body)); setRules([...rules.filter(r => r.id !== rule.id && r.id !== saved.id), saved]); setMessage('Genre rule saved') })}>Save rule</Button><ConfirmDialog title="Delete this genre rule?" description="The track will use your coupling’s normal choices." trigger={<Button variant="ghost" className="min-h-11 text-destructive">Delete rule…</Button>} onConfirm={async () => { if (!rule.id.startsWith('new-')) await deleteGenreRule(rule.id); setRules(rules.filter(r => r.id !== rule.id)) }} /></div>
        </div>)}
        <Button variant="outline" className="min-h-11" onClick={() => { const genre = settings.genres.find(g => !rules.some(r => r.genre === g)); if (genre) setRules([...rules, { id: `new-${Date.now()}`, genre, palette_id: '', energy_profile_id: '' }]) }} disabled={rules.length >= settings.genres.length}>Add rule</Button>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Tag mapping</CardTitle></CardHeader><CardContent className="space-y-3"><p className="text-sm text-muted-foreground">Map a raw track or Last.fm tag to a genre. Tags are matched without regard to case.</p>
        <details><summary className="cursor-pointer py-3 text-sm">Edit tag mapping ({mapping.length} tags)</summary><div className="mt-3 space-y-3">{mapping.map(([tag, genre], i) => <div key={i} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"><Input aria-label={`Raw tag ${i + 1}`} className="min-h-11" value={tag} onChange={e => setMapping(mapping.map((r, j) => i === j ? [e.target.value, genre] : r))} /><select aria-label={`Mapped genre ${i + 1}`} className={selectStyle} value={genre} onChange={e => setMapping(mapping.map((r, j) => i === j ? [tag, e.target.value] : r))}>{settings.genres.map(g => <option key={g}>{g}</option>)}</select><Button variant="ghost" aria-label={`Remove tag ${i + 1}`} className="min-h-11" onClick={() => setMapping(mapping.filter((_, j) => i !== j))}>Remove</Button></div>)}<Button variant="outline" className="min-h-11" onClick={() => setMapping([...mapping, ['', 'other']])}>Add tag</Button></div></details>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Smooth changes</CardTitle></CardHeader><CardContent className="grid gap-5 sm:grid-cols-2">
        <label className="space-y-2 text-sm">Transition<select aria-label="Transition" className={selectStyle} value={settings.transition_mode} onChange={e => setSettings({ ...settings, transition_mode: e.target.value })}><option value="crossfade">Crossfade</option><option value="through-black">Through black</option><option value="through-white">Through white</option></select></label>
        <label className="space-y-2 text-sm">Duration · {settings.transition_duration_s.toFixed(1)} s<input type="range" aria-label="Transition duration" min={0} max={2} step={.1} className="block h-11 w-full" value={settings.transition_duration_s} onChange={e => setSettings({ ...settings, transition_duration_s: Number(e.target.value) })} /></label>
        <p className="text-xs text-muted-foreground sm:col-span-2">For changes of effect, palette and Energy Profile. Set the duration to zero for an immediate change. Rhythm and audio timing stay the same.</p>
      </CardContent></Card>
      <footer className="flex flex-wrap items-center justify-between gap-3"><p role="status" className="text-sm text-muted-foreground">{message}</p><Button className="min-h-11" disabled={busy} onClick={() => action(save)}>{busy ? 'Saving…' : 'Save settings'}</Button></footer>
    </>}
  </section>
}
