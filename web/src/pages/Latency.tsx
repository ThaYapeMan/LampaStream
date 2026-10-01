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
  type PlayerLatency,
  createPlayerLatency,
  updatePlayerLatency,
} from '@/lib/api'

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

export function LatencyEditorDialog({ open, entry, onClose, onSave, prefill, airplay }: EditorDialogProps) {
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
