import { useEffect, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getMetadataProviders, updateMetadataProvider, type MetadataProvider } from '@/lib/api'

const pauseDate = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})

export function providerLookupText(provider: Pick<MetadataProvider, 'lookup' | 'http_status' | 'paused_until'>) {
  const status = provider.lookup?.status
  const nextTry = provider.paused_until == null ? '' :
    ` — next try ${pauseDate.format(new Date(provider.paused_until * 1000)).replace(',', '')}`
  switch (status) {
    case 'ready': return 'Lookup: found'
    case 'empty':
    case 'not_found': return 'Lookup: this track is not known there'
    case 'ambiguous':
    case 'octave_ambiguous': return 'Lookup: several possible matches, none chosen'
    case 'credentials_not_configured': return 'Not set up: no access token'
    case 'authentication_failed': return 'The website does not accept the access token'
    case 'blocked': {
      const http = provider.http_status == null ? '' : ` (HTTP ${provider.http_status})`
      return `Refused by the website${http}${nextTry}`
    }
    case 'rate_limited': return `Asked too often${nextTry}`
    case 'timeout':
    case 'connect_timeout':
    case 'read_timeout':
    case 'write_timeout':
    case 'pool_timeout':
    case 'network_error':
    case 'http_error':
    case 'failed': return 'The website did not answer'
    case 'unreadable': return "The website's answer could not be read"
    case 'pending': return 'Lookup in progress'
    default: return ''
  }
}

export function MetadataProviders({ initial }: { initial: MetadataProvider[] }) {
  const [providers, setProviders] = useState(initial)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    const timer = setInterval(() => {
      if (pending.current) return
      void getMetadataProviders().then(rows => {
        if (alive && !pending.current) setProviders(rows)
      }).catch(() => { /* Keep the last known settings during a disconnect. */ })
    }, 3000)
    return () => { alive = false; clearInterval(timer) }
  }, [])
  async function update(name: string, body: { enabled?: boolean; consent?: boolean }) {
    if (pending.current) return
    pending.current = true
    const before = providers.find(item => item.name === name)
    setProviders(items => items.map(item => item.name === name ? { ...item, ...body,
      status: body.enabled === undefined ? item.status : body.enabled ? 'active' : 'disabled' } : item))
    setBusy(true); setError('')
    try {
      const result = await updateMetadataProvider(name, body)
      setProviders(items => items.map(item => item.name === name ? result : item))
    } catch (e) {
      if (before) setProviders(items => items.map(item => item.name === name ? before : item))
      setError(e instanceof Error ? e.message : 'Could not save provider')
    } finally { pending.current = false; setBusy(false) }
  }
  return <Card data-testid="metadata-providers"><CardHeader><CardTitle>Tempo metadata providers</CardTitle></CardHeader><CardContent className="space-y-4">
    <p className="text-sm text-muted-foreground">Disabled providers keep their stored results. Obsolete providers are never queried; their results remain available below active providers.</p>
    {providers.map(provider => <section key={provider.name} aria-label={`Provider ${provider.name}`} className="space-y-2 rounded-lg border p-3">
      <label className="flex min-h-11 items-center gap-3 text-sm">
        <input type="checkbox" checked={provider.enabled} disabled={busy || !provider.toggleable}
          onChange={e => void update(provider.name, { enabled: e.target.checked })} />
        <span>{provider.display_label || provider.name}</span><span className="ml-auto text-muted-foreground">{provider.status}</span>
      </label>
      <p className="text-xs text-muted-foreground">{provider.lookup && <span>{providerLookupText(provider)} · </span>}{provider.capabilities.join(', ')} · {provider.leaves_lan ? 'Enabling consents to sending artist and title to this service for display-only values' : 'Local'}{provider.always_enabled ? ' · Always enabled' : ''}{provider.test_only ? ' · Test harness only' : ''}</p>
      {provider.redistributable && <label className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" checked={provider.consent} disabled={busy}
        onChange={e => void update(provider.name, { consent: e.target.checked })} />Allow sharing {provider.name} results in a future grid export</label>}
    </section>)}
    <p className="text-xs text-muted-foreground">Sharing consent is off by default. Nothing is uploaded by these controls. External services remain off until you enable them. SongBPM and Beatport values are personal reference values and are never shared.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </CardContent></Card>
}
