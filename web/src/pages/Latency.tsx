import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { SliderField } from '@/components/SliderField'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import {
  type PlayerLatency,
  getPlayerLatencies,
  createPlayerLatency,
  updatePlayerLatency,
  deletePlayerLatency,
} from '@/lib/api'

interface Props {
  syncMaster: string | null
  syncMasterName: string | null
  airplay?: boolean
  followMode?: "manual" | "sync_group" | null
}

interface EntryForm {
  player_mac: string
  name: string
  strategy: string
  fixed_delay_ms: number
  trim_ms: number
}

function defaultForm(prefill?: Partial<EntryForm>): EntryForm {
  return {
    player_mac: prefill?.player_mac ?? '',
    name: prefill?.name ?? '',
    strategy: prefill?.strategy ?? 'fixed',
    fixed_delay_ms: prefill?.fixed_delay_ms ?? 0,
    trim_ms: prefill?.trim_ms ?? 0,
  }
}

interface EditorDialogProps {
  airplay?: boolean
  open: boolean
  entry?: PlayerLatency
  onClose: () => void
  onSave: () => void
  prefill?: Partial<EntryForm>
}

function EditorDialog({ open, entry, onClose, onSave, prefill, airplay }: EditorDialogProps) {
  const isEditing = !!entry
  const [form, setForm] = useState<EntryForm>(() =>
    defaultForm(entry ? { ...entry, name: entry.name ?? '' } : prefill)
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setForm(defaultForm(entry ? { ...entry, name: entry.name ?? '' } : prefill))
      setError(null)
    }
  }, [open, entry, prefill])

  function set<K extends keyof EntryForm>(key: K, value: EntryForm[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      if (isEditing) {
        await updatePlayerLatency(entry.player_mac, {
          name: form.name || undefined,
          strategy: form.strategy,
          fixed_delay_ms: form.fixed_delay_ms,
          trim_ms: form.trim_ms,
        })
      } else {
        await createPlayerLatency({
          player_mac: form.player_mac,
          name: form.name || undefined,
          strategy: form.strategy,
          fixed_delay_ms: form.fixed_delay_ms,
          trim_ms: form.trim_ms,
        })
      }
      onSave()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEditing ? 'Edit latency entry' : 'Add latency entry'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1">
            <Label>Player MAC</Label>
            {isEditing ? (
              <p className="font-mono text-sm text-muted-foreground py-1">{entry.player_mac}</p>
            ) : (
              <Input
                value={form.player_mac}
                onChange={(e) => set('player_mac', e.target.value)}
                placeholder="aa:bb:cc:dd:ee:ff"
              />
            )}
          </div>
          <div className="space-y-1">
            <Label>Name</Label>
            <Input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Sonos Living Room" />
          </div>
          <div className="space-y-1">
            <Label>Strategy</Label>
            <Select value={form.strategy} onValueChange={(v) => set('strategy', v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fixed">Fixed</SelectItem>
                <SelectItem value="none">None</SelectItem>
                <SelectItem value="auto">Auto</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {(form.strategy === 'fixed' || form.strategy === 'auto') && (
            <SliderField
              label={form.strategy === 'auto' ? airplay ? 'Fixed delay (fallback)' : 'Fixed delay (sync-group fallback)' : 'Fixed delay'}
              value={form.fixed_delay_ms}
              min={0}
              max={3000}
              step={50}
              format={(v) => `${v} ms`}
              onChange={(v) => set('fixed_delay_ms', v)}
            />
          )}
          {form.strategy === 'auto' && (
            <SliderField label="Manual trim" value={form.trim_ms}
              min={-1000} max={1000} step={10} format={(v) => `${v} ms`}
              onChange={(v) => set('trim_ms', v)} />
          )}
        </div>
        {error && <p className="text-destructive text-sm mt-2">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function Latency({ syncMaster, syncMasterName, followMode, airplay }: Props) {
  const [latencies, setLatencies] = useState<PlayerLatency[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingEntry, setEditingEntry] = useState<PlayerLatency | undefined>(undefined)
  const [editorPrefill, setEditorPrefill] = useState<Partial<EntryForm> | undefined>(undefined)

  async function load() {
    try {
      const data = await getPlayerLatencies()
      setLatencies(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 2000)
    return () => window.clearInterval(timer)
  }, [])

  async function handleDelete(mac: string) {
    await deletePlayerLatency(mac)
    await load()
  }

  function openNew(prefill?: Partial<EntryForm>) {
    setEditingEntry(undefined)
    setEditorPrefill(prefill)
    setEditorOpen(true)
  }

  function openEdit(entry: PlayerLatency) {
    setEditingEntry(entry)
    setEditorPrefill(undefined)
    setEditorOpen(true)
  }

  async function handleSave() {
    setEditorOpen(false)
    await load()
  }

  const masterInList = syncMaster ? latencies.some((l) => l.player_mac === syncMaster) : false

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Player latency</h2>
        <Button size="sm" onClick={() => openNew()}>Add entry</Button>
      </div>

      {syncMaster && (
        <div className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
          <span>
            {airplay ? 'AirPlay virtual player:' : followMode === 'manual' ? 'Followed player:' : 'Sync master detected:'}{' '}
            <span className="font-medium">{syncMasterName ?? syncMaster}</span>{' '}
            <code className="text-xs font-mono text-muted-foreground">({syncMaster})</code>
          </span>
          {!masterInList && (
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                openNew({ player_mac: syncMaster, name: syncMasterName ?? '' })
              }
            >
              Add entry
            </Button>
          )}
        </div>
      )}

      {error && <p className="text-destructive text-sm">{error}</p>}

      {latencies.length === 0 ? (
        <p className="text-sm text-muted-foreground">No latency entries configured.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>MAC</TableHead>
              <TableHead>Strategy</TableHead>
              <TableHead>Delay</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {latencies.map((l) => (
              <TableRow key={l.player_mac}>
                <TableCell>{l.name ?? <span className="text-muted-foreground">—</span>}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{l.player_mac}</TableCell>
                <TableCell className="text-sm">{l.strategy}</TableCell>
                <TableCell className="text-sm">
                  {l.strategy === 'fixed' ? `${l.fixed_delay_ms} ms` : l.strategy === 'auto' ? (
                    <div className="space-y-1" aria-label="Auto latency status">
                      <p>{l.status?.state ?? 'idle'} · {l.status?.applied_delay_ms ?? Math.max(0, (l.measured_delay_ms ?? 0) + l.trim_ms)} ms</p>
                      <p>Strategy in effect: {l.status?.strategy ?? 'auto'}</p>
                      {l.status?.source === 'airplay' ? <p>Early delivery: {l.status.early_delivery_ms ?? '—'} ms · Processing: {l.status.median_processing_ms ?? '—'} ms</p> : <p>Residual: {l.status?.median_residual_ms ?? '—'} ms · Player Delay: {l.status?.player_delay_ms ?? '—'} ms</p>}
                      <p>Trim: {l.trim_ms} ms · Samples: {l.status?.sample_count ?? 0} · Precision: ±{l.status?.precision_ms ?? '—'} ms</p>
                      <p>Last sample: {l.status?.last_sample_time ? new Date(l.status.last_sample_time * 1000).toLocaleTimeString() : '—'}</p>
                      {l.status?.reason && <p>{l.status.reason}</p>}
                    </div>
                  ) : '—'}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-1">
                    <Button size="sm" variant="ghost" onClick={() => openEdit(l)}>Edit</Button>
                    <ConfirmDialog
                      trigger={
                        <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive">
                          Delete
                        </Button>
                      }
                      title="Remove latency entry"
                      description={`Remove entry for ${l.name ?? l.player_mac}?`}
                      onConfirm={() => handleDelete(l.player_mac)}
                    />
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <EditorDialog
        airplay={airplay || editingEntry?.status?.source === 'airplay'}
        open={editorOpen}
        entry={editingEntry}
        prefill={editorPrefill}
        onClose={() => setEditorOpen(false)}
        onSave={handleSave}
      />
    </div>
  )
}
