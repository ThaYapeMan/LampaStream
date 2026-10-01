import { useEffect, useState } from 'react'
import { Speaker } from 'lucide-react'
import { AirPlayReceiverIcon } from '@/components/MediaIcons'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { LatencyEditorDialog } from '@/pages/Latency'
import { lightTimingState, LightTiming } from '@/components/LightTiming'
import {
  createPlayerLatency,
  updatePlayerLatency,
  deletePlayerLatency,
  type VirtualPlayer,
  type PlayerLatency
} from '@/lib/api'
import type { SocketStatus } from '@/hooks/usePreviewSocket'
import lmsIcon from '@/assets/lms-player-icon.png'

export interface PlayerRow {
  id: string
  name: string
  mac: string
  target: string
  player?: VirtualPlayer
  entry?: PlayerLatency
  group: string
  timingStatus: SocketStatus | null
}
export function buildPlayerRows(
  players: VirtualPlayer[],
  entries: PlayerLatency[],
  status: SocketStatus | null,
  activeId?: string
): PlayerRow[] {
  const followed = new Set<string>()
  const rows = players.map((player) => {
    const active = player.id === activeId
    const mac =
      player.type === 'AirPlay'
        ? player.player_mac
        : player.follow_mode === 'sync_group'
          ? active
            ? status?.timing_player_mac || status?.sync_master || ''
            : ''
          : player.follow_player_mac
    if (mac) followed.add(mac.toLowerCase())
    const entry =
      (active && status?.light_timing && status.light_timing.player_mac === mac
        ? status.light_timing
        : null) ||
      entries.find((e) => e.player_mac.toLowerCase() === mac?.toLowerCase())
    const target =
      player.type === 'AirPlay'
        ? 'the AirPlay group'
        : (active &&
          (status?.timing_player_mac ||
            status?.follow_target_mac ||
            status?.sync_master) === mac
            ? status?.timing_player_name ||
              status?.follow_target_name ||
              status?.sync_master_name
            : null) ||
          entry?.name ||
          mac ||
          'No player selected'
    const timingStatus = {
      ...(active ? status : {}),
      active_player_type: player.type,
      follow_mode: player.follow_mode,
      timing_player_mac: mac,
      timing_player_name: target,
      light_timing: entry,
      applied_delay_ms:
        entry?.status?.applied_delay_ms ??
        (entry?.strategy === 'fixed'
          ? entry.fixed_delay_ms
          : entry?.strategy === 'none'
            ? 0
            : Math.max(
                0,
                (entry?.measured_delay_ms ?? 0) + (entry?.trim_ms ?? 0)
              ))
    } as SocketStatus
    return {
      id: player.id,
      name: player.player_name,
      mac: mac || '',
      target,
      player,
      entry,
      group: 'LampaStream players',
      timingStatus
    }
  })
  return [
    ...rows,
    ...entries
      .filter((e) => !followed.has(e.player_mac.toLowerCase()))
      .map((entry) => ({
        id: `timing:${entry.player_mac}`,
        name: entry.name || entry.player_mac,
        mac: entry.player_mac,
        target: entry.name || entry.player_mac,
        entry,
        group: 'Other timings',
        timingStatus: {
          timing_player_mac: entry.player_mac,
          timing_player_name: entry.name,
          light_timing: entry,
          applied_delay_ms:
            entry.status?.applied_delay_ms ??
            (entry.strategy === 'fixed'
              ? entry.fixed_delay_ms
              : entry.strategy === 'none'
                ? 0
                : Math.max(0, (entry.measured_delay_ms ?? 0) + entry.trim_ms))
        } as SocketStatus
      }))
  ]
}
function PlayerIcon({
  row,
  detail = false
}: {
  row: PlayerRow
  detail?: boolean
}) {
  const size = detail ? 22 : 17
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center rounded-lg border bg-secondary ${detail ? 'h-11 w-11' : 'h-8 w-8'}`}
    >
      {row.player?.type === 'LMS' ? (
        <img src={lmsIcon} alt="" width={size} height={size} />
      ) : row.player?.type === 'AirPlay' ? (
        <AirPlayReceiverIcon width={size} height={size} />
      ) : (
        <Speaker size={size} />
      )}
    </span>
  )
}
function TimingCard({
  row,
  onReload,
  onNowPlaying
}: {
  row: PlayerRow
  onReload: () => Promise<void>
  onNowPlaying?: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [optimistic, setOptimistic] = useState<PlayerLatency | null>(null)
  useEffect(() => {
    if (
      optimistic &&
      row.entry?.strategy === optimistic.strategy &&
      row.entry?.trim_ms === optimistic.trim_ms
    )
      setOptimistic(null)
  }, [row.entry, optimistic])
  const entry = optimistic || row.entry
  const timingStatus = {
    ...row.timingStatus,
    light_timing: entry,
    applied_delay_ms:
      entry?.status?.applied_delay_ms ??
      (entry?.strategy === 'fixed'
        ? entry.fixed_delay_ms
        : entry?.strategy === 'none'
          ? 0
          : Math.max(
              0,
              (entry?.measured_delay_ms ?? 0) + (entry?.trim_ms ?? 0)
            ))
  } as SocketStatus
  async function save(patch: { strategy?: string; trim_ms?: number }) {
    setBusy(true)
    setError('')
    try {
      const saved = entry
        ? await updatePlayerLatency(row.mac, patch)
        : await createPlayerLatency({
            player_mac: row.mac,
            name: row.target,
            strategy: patch.strategy ?? 'auto',
            ...patch
          })
      setOptimistic({
        ...entry,
        ...saved,
        ...patch,
        status: undefined
      } as PlayerLatency)
      await onReload()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="players-timing space-y-3">
      <LightTiming
        status={timingStatus}
        playersView
        controls={
          entry && (
            <div
              role="group"
              aria-label="Timing method"
              className="inline-flex rounded-lg border bg-secondary p-1"
            >
              {['Auto', 'Fixed', 'None'].map((label) => (
                <Button
                  key={label}
                  size="sm"
                  variant={
                    entry.strategy === label.toLowerCase() ? 'default' : 'ghost'
                  }
                  aria-pressed={entry.strategy === label.toLowerCase()}
                  disabled={busy || !row.mac}
                  onClick={() => save({ strategy: label.toLowerCase() })}
                >
                  {label}
                </Button>
              ))}
            </div>
          )
        }
        footer={
          <a
            href="/now-playing"
            className="block text-sm text-primary hover:underline"
            onClick={(e) => {
              if (onNowPlaying) {
                e.preventDefault()
                onNowPlaying()
              }
            }}
          >
            Show on Now Playing
          </a>
        }
      />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
export function PlayersDetail({
  rows,
  selected,
  onSelect,
  onEdit,
  onDelete,
  onReload,
  onNowPlaying,
  status,
  activePlayerId
}: {
  rows: PlayerRow[]
  selected?: PlayerRow
  onSelect: (id: string) => void
  onEdit: (p: VirtualPlayer) => void
  onDelete: (id: string) => Promise<void>
  onReload: () => Promise<void>
  onNowPlaying?: () => void
  status: SocketStatus | null
  activePlayerId?: string
}) {
  const [editingTiming, setEditingTiming] = useState(false)
  if (!selected)
    return (
      <p className="text-sm text-muted-foreground">
        No players yet. Add a player to get started.
      </p>
    )
  const player = selected.player
  const active = !!player && player.id === activePlayerId
  const facts = !player
    ? [
        ['Player MAC', selected.mac],
        ['Used when', `a LampaStream player follows ${selected.name}`]
      ]
    : player.type === 'AirPlay'
      ? [
          ['AirPlay name', player.display_name || player.player_name],
          [
            'Early delivery',
            selected.entry?.status?.early_delivery_ms == null
              ? '—'
              : `${(selected.entry.status.early_delivery_ms / 1000).toFixed(2)} s`
          ],
          ['Player MAC', player.player_mac || '—'],
          [
            'Receiver',
            active
              ? `shairport-sync · ${status?.airplay_receiving ? 'receiving' : status?.airplay_receiving === false ? 'ready' : 'unknown'}`
              : 'Inactive'
          ]
        ]
      : [
          ['Player name in LMS', player.display_name || player.player_name],
          ['LMS server', `${player.lms_host} : ${player.lms_port}`],
          ['Player MAC', player.player_mac || '—'],
          [
            'Engine',
            active
              ? `yeney-player · ${status?.processes?.lms_player ? 'running' : 'stopped'}`
              : 'Inactive'
          ]
        ]
  return (
    <div
      className="grid min-w-0 gap-6 lg:grid-cols-[340px_minmax(0,1fr)]"
      data-testid="players-layout"
    >
      <div
        role="listbox"
        aria-label="Players"
        className="min-w-0 self-start overflow-hidden rounded-xl border bg-card"
      >
        {['LampaStream players', 'Other timings'].map((group) => (
          <div role="group" aria-label={group} key={group}>
            <h3 className="px-4 pb-2 pt-4 text-xs font-semibold text-muted-foreground">
              {group}
            </h3>
            {rows
              .filter((r) => r.group === group)
              .map((row) => {
                const { state, applied } = lightTimingState(
                  row.entry,
                  row.timingStatus,
                  row.player?.type === 'AirPlay'
                )
                return (
                  <button
                    key={row.id}
                    role="option"
                    aria-selected={row.id === selected.id}
                    tabIndex={row.id === selected.id ? 0 : -1}
                    className={`flex w-full min-w-0 items-center gap-3 px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${row.id === selected.id ? 'bg-muted' : 'hover:bg-muted/50'}`}
                    onClick={() => onSelect(row.id)}
                    onKeyDown={(e) => {
                      if (
                        !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)
                      )
                        return
                      e.preventDefault()
                      const index = rows.findIndex((r) => r.id === row.id)
                      const next =
                        e.key === 'Home'
                          ? 0
                          : e.key === 'End'
                            ? rows.length - 1
                            : Math.max(
                                0,
                                Math.min(
                                  rows.length - 1,
                                  index + (e.key === 'ArrowDown' ? 1 : -1)
                                )
                              )
                      onSelect(rows[next].id)
                      const box = e.currentTarget.closest('[role="listbox"]')
                      ;(
                        box?.querySelectorAll('[role="option"]')[
                          next
                        ] as HTMLElement
                      )?.focus()
                    }}
                  >
                    <PlayerIcon row={row} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {row.name}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {row.player
                          ? row.player.type === 'AirPlay'
                            ? 'Joins your AirPlay groups'
                            : `Follows ${row.target}`
                          : 'Not followed right now'}
                      </span>
                    </span>
                    <span
                      aria-label={`${state === 'stable' ? 'In sync' : state === 'measuring' ? 'Measuring' : state === 'fixed' ? 'Fixed' : state === 'none' ? 'No delay' : 'Idle'}, ${(applied / 1000).toFixed(2)} seconds`}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-secondary px-2 py-1 font-mono text-xs"
                    >
                      <span
                        aria-hidden="true"
                        className={`h-1.5 w-1.5 rounded-full ${state === 'stable' ? 'bg-emerald-400' : state === 'measuring' ? 'bg-blue-400' : 'bg-muted-foreground'}`}
                      />
                      {(applied / 1000).toFixed(2)} s
                    </span>
                  </button>
                )
              })}
          </div>
        ))}
      </div>
      <div className="min-w-0 space-y-4">
        <Card>
          <CardContent className="space-y-4 pt-5">
            <div className="flex items-center gap-3">
              <PlayerIcon row={selected} detail />
              <div className="min-w-0">
                <h3 className="break-words text-lg font-semibold">
                  {selected.name}
                </h3>
                <p className="text-sm text-muted-foreground">
                  {player
                    ? player.type === 'AirPlay'
                      ? 'AirPlay 2 receiver'
                      : 'LMS · yeney-player'
                    : 'Saved timing'}
                </p>
              </div>
              {active && (
                <Badge
                  className="ml-auto"
                  aria-label="In use by active coupling"
                >
                  In use
                </Badge>
              )}
            </div>
            <p className="break-words text-sm text-muted-foreground">
              {player ? (
                <>
                  <b className="text-foreground">{selected.name}</b> → follows →{' '}
                  <b className="text-foreground">{selected.target}</b> ·{' '}
                  {player.type === 'AirPlay'
                    ? 'AirPlay group timing'
                    : player.follow_mode === 'sync_group'
                      ? 'Automatic — LMS sync group'
                      : 'Manual — fixed player'}
                </>
              ) : (
                `No LampaStream player follows ${selected.name} at the moment. This timing is kept for when one does.`
              )}
            </p>
          </CardContent>
        </Card>
        <TimingCard
          key={`timing-card:${selected.id}`}
          row={selected}
          onReload={onReload}
          onNowPlaying={onNowPlaying}
        />
        <Card aria-label="Details">
          <CardContent className="pt-5">
            <h3 className="mb-4 text-sm font-semibold">Details</h3>
            <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] gap-x-4 gap-y-3 text-sm">
              {facts.map(([label, value]) => (
                <div className="contents" key={label}>
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="break-words text-right">{value}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-5 flex items-center justify-between border-t pt-4">
              <ConfirmDialog
                trigger={
                  <Button
                    variant="ghost"
                    className="text-destructive hover:text-destructive"
                  >
                    Delete…
                  </Button>
                }
                title={
                  player ? 'Delete virtual player' : 'Remove latency entry'
                }
                description={
                  player
                    ? `Delete ${selected.name}? Saved timings will be kept under Other timings.`
                    : `Remove the saved timing for ${selected.name}?`
                }
                onConfirm={async () => {
                  if (player) await onDelete(player.id)
                  else {
                    await deletePlayerLatency(selected.mac)
                    await onReload()
                  }
                }}
              />
              <Button
                variant="outline"
                onClick={() =>
                  player ? onEdit(player) : setEditingTiming(true)
                }
              >
                Edit
              </Button>
            </div>
          </CardContent>
        </Card>
        <LatencyEditorDialog
          key={`timing-editor:${selected.id}`}
          open={editingTiming}
          entry={selected.entry}
          airplay={
            player?.type === 'AirPlay' ||
            selected.entry?.status?.source === 'airplay'
          }
          onClose={() => setEditingTiming(false)}
          onSave={async () => {
            setEditingTiming(false)
            await onReload()
          }}
        />
      </div>
    </div>
  )
}
