import { useState } from 'react'
import { Button } from '@/components/ui/button'

const LIMIT = 4 * 1024 * 1024

async function failure(response: Response): Promise<string> {
  const body = await response.json().catch(() => null)
  // Only server-generated diagnostics are shown; never render the uploaded JSON.
  return typeof body?.detail?.message === 'string'
    ? body.detail.message : `Backup operation failed (${response.status}).`
}

export function Backup() {
  const [file, setFile] = useState<File | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function exportConfig() {
    setBusy(true); setError(''); setMessage('')
    try {
      const response = await fetch('/api/backup/export', { cache: 'no-store' })
      if (!response.ok) throw new Error(await failure(response))
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      // Filename is generated locally; credentials never influence it.
      link.download = `lampastream-backup-${new Date().toISOString().replace(/:/g, '')}.zip`
      document.body.appendChild(link)
      link.click(); link.remove()
      const revoke = URL.revokeObjectURL.bind(URL)
      setTimeout(() => revoke(url), 1000)
      setMessage('Backup downloaded. Keep the file secure; it contains controller credentials.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Export failed.')
    } finally { setBusy(false) }
  }

  async function restoreConfig() {
    if (!file || !confirmed) return
    setBusy(true); setError(''); setMessage('')
    try {
      const full = file.name.toLowerCase().endsWith('.zip')
      const limit = full ? 64 * 1024 ** 3 : LIMIT
      if (file.size > limit) throw new Error(`Backup exceeds the ${full ? '64 GiB' : '4 MiB'} limit.`)
      const response = await fetch(full ? '/api/backup/import' : '/api/config/import', {
        method: 'POST', headers: { 'Content-Type': full ? 'application/zip' : 'application/json' }, body: file,
        cache: 'no-store',
      })
      if (!response.ok) throw new Error(await failure(response))
      setConfirmed(false)
      setMessage('Configuration restored. No service restart is required. Activate a restored Coupling when ready.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Restore failed.')
    } finally { setBusy(false) }
  }

  return (
    <section className="space-y-5">
      <h2 className="text-xl font-semibold">Backup and restore</h2>
      <p>Downloads all LampaStream configuration, including player settings, Hue Bridge pairing credentials,
        zones, analysers, energy profiles, effects, couplings, player latencies, beat grids and track metadata.</p>
      <p className="font-medium">Keep this file secure. It contains credentials that may grant access
        to paired lighting controllers. LampaStream has no authentication; use a trusted network only.</p>
      <Button onClick={exportConfig} disabled={busy}>Export LampaStream configuration</Button>
      <hr />
      <h3 className="font-semibold">Restore LampaStream configuration</h3>
      <p>A ZIP restore replaces configuration and grids and creates safety backups on the server.
        A JSON backup restores configuration only.
        Deactivate the current Coupling first and wait for teardown to finish. Playback is not restored.</p>
      <label className="block space-y-2">
        <span>Backup ZIP or JSON file (ZIP: maximum 64 GiB; JSON: maximum 4 MiB)</span>
        <input type="file" accept=".zip,.json,application/zip,application/json" disabled={busy}
          onChange={e => { setFile(e.target.files?.[0] ?? null); setConfirmed(false); setError(''); setMessage('') }} />
      </label>
      {file && <p>Selected file: {file.name}</p>}
      <label className="flex gap-2 items-start">
        <input type="checkbox" checked={confirmed} disabled={busy || !file}
          onChange={e => setConfirmed(e.target.checked)} />
        <span>I understand that restoring this backup replaces all current LampaStream configuration.</span>
      </label>
      <Button onClick={restoreConfig} disabled={busy || !file || !confirmed}>Restore configuration</Button>
      {busy && <p role="status">Working…</p>}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </section>
  )
}
