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
import { PlayersDetail, buildPlayerRows } from '@/components/PlayersDetail'
import type { SocketStatus } from '@/hooks/usePreviewSocket'
import { getPlayerLatencies, type PlayerLatency } from '@/lib/api'
import {
  type VirtualPlayer,
  type LmsPlayer,
  PLAYER_TYPES,
  getVirtualPlayers,
  createVirtualPlayer,
  updateVirtualPlayer,
  deleteVirtualPlayer,
  listLmsPlayers,
  type Coupling,
  getCouplings,
} from '@/lib/api'

interface FormState {
  playerType: string
  lms_host: string
  lms_port: string
  player_name: string
  display_name: string
  follow_player_mac: string
  follow_mode: 'manual' | 'sync_group'
}

function defaultForm(player?: VirtualPlayer): FormState {
  return {
    playerType: player?.type ?? 'LMS',
    lms_host: player?.lms_host ?? '',
    lms_port: String(player?.lms_port ?? 9000),
    player_name: player?.player_name ?? 'LampaStream',
    display_name: player?.display_name ?? '',
    follow_player_mac: player?.follow_player_mac ?? '',
    follow_mode: player?.follow_mode ?? 'manual',
  }
}

function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-sm">{label}</Label>
      {children}
    </div>
  )
}

export function Players({ activeCouplingId = null, status = null, selectedPlayer, onSelect, onNowPlaying }: { activeCouplingId?: string | null; status?: SocketStatus | null; selectedPlayer?: string | null; onSelect?: (id: string) => void; onNowPlaying?: () => void }) {
  const [latencies, setLatencies] = useState<PlayerLatency[]>([])
  const [selection, setSelection] = useState(() => { try { return localStorage.getItem('lampastream.selectedPlayer') || '' } catch { return '' } })
  const [couplings, setCouplings] = useState<Coupling[]>([])
  const activeCoupling = couplings.find(c => c.id === activeCouplingId)
  const [players, setPlayers] = useState<VirtualPlayer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingPlayer, setEditingPlayer] = useState<VirtualPlayer | undefined>(undefined)
  const [form, setForm] = useState<FormState>(defaultForm())
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [nameError, setNameError] = useState<string | null>(null)
  const [lmsPlayers, setLmsPlayers] = useState<LmsPlayer[]>([])
  const [discovering, setDiscovering] = useState(false)
  const [discoverError, setDiscoverError] = useState<string | null>(null)

  async function load() {
    try {
      const [data, cs, ls] = await Promise.all([getVirtualPlayers(), getCouplings(), getPlayerLatencies()])
      setLatencies(ls)
      setCouplings(cs)
      setPlayers(data)
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

  function openNew() {
    setEditingPlayer(undefined)
    setForm(defaultForm())
    setLmsPlayers([])
    setSaveError(null)
    setNameError(null)
    setDiscoverError(null)
    setEditorOpen(true)
  }

  function openEdit(player: VirtualPlayer) {
    setEditingPlayer(player)
    setForm(defaultForm(player))
    setLmsPlayers([])
    setSaveError(null)
    setNameError(null)
    setDiscoverError(null)
    setEditorOpen(true)
  }

  function set(key: keyof FormState, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function discoverPlayers() {
    if (!form.lms_host) {
      setDiscoverError('Enter an LMS host first')
      return
    }
    setDiscovering(true)
    setDiscoverError(null)
    try {
      const result = await listLmsPlayers(form.lms_host)
      setLmsPlayers(result)
      if (result.length === 0) setDiscoverError('No players found on this LMS server')
    } catch (e) {
      setDiscoverError(e instanceof Error ? e.message : 'Discovery failed')
    } finally {
      setDiscovering(false)
    }
  }

  const isAirPlay = form.playerType === 'AirPlay'

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    setNameError(null)
    try {
      if (editingPlayer) {
        await updateVirtualPlayer(editingPlayer.id, {
          lms_host: form.lms_host,
          lms_port: parseInt(form.lms_port, 10),
          player_name: form.player_name,
          display_name: form.display_name,
          follow_player_mac: form.follow_player_mac,
          follow_mode: form.follow_mode,
        })
      } else {
        await createVirtualPlayer({
          type: form.playerType,
          lms_host: form.lms_host,
          lms_port: parseInt(form.lms_port, 10),
          player_name: form.player_name,
          display_name: form.display_name,
          follow_player_mac: form.follow_player_mac,
          follow_mode: form.follow_mode,
        })
      }
      setEditorOpen(false)
      await load()
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Save failed'
      if ((e as any).status === 409) {
        setNameError(msg)
      } else {
        setSaveError(msg)
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    await deleteVirtualPlayer(id)
    await load()
  }

  // Build options for the Follow player dropdown. If the current follow_player_mac
  // is not in the discovered list (e.g. discovery hasn't run yet), inject it as a
  // bare MAC so the selection is not lost.
  const followOptions: LmsPlayer[] = [...lmsPlayers]
  if (
    form.follow_player_mac &&
    !lmsPlayers.some((p) => p.playerid === form.follow_player_mac)
  ) {
    followOptions.unshift({ playerid: form.follow_player_mac, name: form.follow_player_mac })
  }

  const rows = buildPlayerRows(players, latencies, status, activeCoupling?.player_id)
  const selected = rows.find(r => r.id === (selectedPlayer || selection) || (!!selectedPlayer && (r.mac === selectedPlayer || r.player?.player_mac === selectedPlayer))) || rows[0]
  useEffect(() => {
    if (!selected) return
    setSelection(selected.id)
    try { localStorage.setItem('lampastream.selectedPlayer', selected.id) }
    catch { /* Storage may be unavailable. */ }
  }, [selected?.id])
  function select(id: string) {
    setSelection(id)
    try { localStorage.setItem('lampastream.selectedPlayer', id) } catch { /* Storage may be unavailable. */ }
    onSelect?.(id)
  }
  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>
  return (
    <div className="space-y-6 min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-2xl font-semibold">Players</h2><p className="mt-1 text-sm text-muted-foreground">The players LampaStream listens through, and how their lights are timed.</p></div>
        <Button size="sm" onClick={openNew}>Add player</Button>
      </div>
      {error && <p role="alert" className="text-destructive text-sm">{error}</p>}
      <PlayersDetail rows={rows} selected={selected} onSelect={select} onEdit={openEdit} onDelete={handleDelete} onReload={load} onNowPlaying={onNowPlaying} status={status} activePlayerId={activeCoupling?.player_id} />

      <Dialog open={editorOpen} onOpenChange={(o) => { if (!o) setEditorOpen(false) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{editingPlayer ? 'Edit virtual player' : 'New virtual player'}</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <FormRow label="Type">
              {editingPlayer ? (
                <p className="text-sm font-mono py-1 text-muted-foreground">
                  {PLAYER_TYPES.find((t) => t.value === editingPlayer.type)?.label ?? editingPlayer.type}
                </p>
              ) : (
                <Select value={form.playerType} onValueChange={(v) => set('playerType', v)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PLAYER_TYPES.map((t) => (
                      <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </FormRow>

            <div className="space-y-1">
              <Label className="text-sm">Advertised name</Label>
              <p className="text-xs text-muted-foreground">
                {isAirPlay
                  ? 'Name shown in the AirPlay menu. Changing this restarts the AirPlay receiver.'
                  : 'Name shown in the LMS player list. Changing this restarts the player.'}
              </p>
              <Input
                value={form.display_name}
                onChange={(e) => set('display_name', e.target.value)}
                placeholder={form.player_name || 'LampaStream'}
              />
            </div>

            {isAirPlay ? (
              <>
                <div className="space-y-1">
                  <Label className="text-sm">Player name</Label>
                  <Input
                    value={form.player_name}
                    onChange={(e) => { set('player_name', e.target.value); setNameError(null) }}
                  />
                  {nameError && <p className="text-xs text-destructive">{nameError}</p>}
                </div>
                <div className="rounded-md border border-muted bg-muted/40 px-4 py-3 text-sm text-muted-foreground space-y-1">
                  <p>
                    <strong className="text-foreground">Silent AirPlay destination for analysis.</strong>
                  </p>
                  <p>
                    Select this player alongside your real speaker in Control Centre to keep audio
                    playing through your speaker while LampaStream analyses the stream.
                  </p>
                </div>
              </>
            ) : (
              <>
                <FormRow label="LMS host">
                  <Input
                    value={form.lms_host}
                    onChange={(e) => set('lms_host', e.target.value)}
                    placeholder="192.168.x.x"
                  />
                </FormRow>
                <FormRow label="LMS port">
                  <Input
                    type="number"
                    value={form.lms_port}
                    onChange={(e) => set('lms_port', e.target.value)}
                  />
                </FormRow>
                <div className="space-y-1">
                  <Label className="text-sm">Player name</Label>
                  <Input
                    value={form.player_name}
                    onChange={(e) => { set('player_name', e.target.value); setNameError(null) }}
                  />
                  {nameError && <p className="text-xs text-destructive">{nameError}</p>}
                </div>
                <FormRow label="Follow mode">
                  <Select value={form.follow_mode} onValueChange={(v) => set('follow_mode', v)}>
                    <SelectTrigger aria-label="Follow mode"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="manual">Manual — fixed player</SelectItem>
                      <SelectItem value="sync_group">Automatic — LMS sync group</SelectItem>
                    </SelectContent>
                  </Select>
                </FormRow>
                {form.follow_mode === 'sync_group' ? (
                  <p className="text-sm text-muted-foreground">
                    Sync LampaStream with a room in LMS. LampaStream observes that group automatically
                    and never changes its membership or sends playback commands.
                    Your manual target is retained when switching modes.
                  </p>
                ) : (
                <div className="space-y-1">
                  <Label className="text-sm">Follow player</Label>
                  <p className="text-xs text-muted-foreground">
                    LampaStream mirrors track changes from this LMS player without joining its sync group.
                  </p>
                  <div className="flex gap-2">
                    <Select
                      value={form.follow_player_mac || '__none__'}
                      onValueChange={(v) => set('follow_player_mac', v === '__none__' ? '' : v)}
                    >
                      <SelectTrigger className="flex-1">
                        <SelectValue placeholder="None — track mirroring disabled" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__">None — track mirroring disabled</SelectItem>
                        {followOptions.map((p) => (
                          <SelectItem key={p.playerid} value={p.playerid}>
                            {p.name !== p.playerid ? `${p.name} (${p.playerid})` : p.playerid}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={discoverPlayers}
                      disabled={discovering}
                    >
                      {discovering ? '…' : 'Discover'}
                    </Button>
                  </div>
                  {discoverError && (
                    <p className="text-xs text-destructive">{discoverError}</p>
                  )}
                </div>
                )}

                {editingPlayer && (
                  <div className="space-y-1">
                    <Label className="text-sm">Player MAC</Label>
                    <p className="text-sm font-mono text-muted-foreground py-1">{editingPlayer.player_mac || '—'}</p>
                    <p className="text-xs text-muted-foreground">MAC identifies the LMS player and cannot be changed.</p>
                  </div>
                )}
              </>
            )}
          </div>

          {saveError && <p className="text-destructive text-sm mt-2">{saveError}</p>}

          <DialogFooter className="mt-4">
            <Button variant="outline" onClick={() => setEditorOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
