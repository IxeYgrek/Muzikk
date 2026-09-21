import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Download, ListMusic, ListPlus, Play, Plus, Trash2, Upload, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AlbumCover } from '../components/AlbumCard'
import { useToast } from '../components/Toast'
import { Button, Card, CenteredSpinner, EmptyState, Modal, Select } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatClock } from '../lib/format'
import { usePlayer } from '../lib/player'
import type {
  Playlist,
  PlaylistAccount,
  PlaylistBackup,
  PlaylistImportReport,
  PlaylistTrack,
} from '../lib/types'

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export function PlaylistsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const { notify } = useToast()
  const queryClient = useQueryClient()
  const player = usePlayer()
  const fileRef = useRef<HTMLInputElement>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [importing, setImporting] = useState(false)
  const [targetUserId, setTargetUserId] = useState('')
  const [pendingFile, setPendingFile] = useState<PlaylistBackup | null>(null)
  const [report, setReport] = useState<PlaylistImportReport | null>(null)

  const playlists = useQuery({
    queryKey: ['playlists'],
    queryFn: () => api<Playlist[]>('/playlists'),
  })

  const tracks = useQuery({
    queryKey: ['playlists', openId],
    queryFn: () => api<PlaylistTrack[]>(`/playlists/${openId}`),
    enabled: Boolean(openId),
  })

  const accounts = useQuery({
    queryKey: ['playlists', 'accounts'],
    queryFn: () => api<PlaylistAccount[]>('/playlists/accounts'),
    enabled: Boolean(user?.is_admin && (importing || pendingFile)),
  })

  const fail = (error: unknown) =>
    notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error')

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['playlists'] })
  }

  const create = useMutation({
    mutationFn: () => api('/playlists', { method: 'POST', body: { name, track_ids: [] } }),
    onSuccess: () => {
      setCreating(false)
      setName('')
      refresh()
    },
    onError: fail,
  })

  const removeTrack = useMutation({
    mutationFn: (entryId: string) =>
      api(`/playlists/${openId}/items`, { method: 'DELETE', query: { entry_ids: entryId } }),
    onSuccess: refresh,
    onError: fail,
  })

  const destroy = useMutation({
    mutationFn: (playlistId: string) => api(`/playlists/${playlistId}`, { method: 'DELETE' }),
    onSuccess: () => {
      setOpenId(null)
      refresh()
    },
    onError: fail,
  })

  const toggle = (playlistId: string) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(playlistId)) next.delete(playlistId)
      else next.add(playlistId)
      return next
    })
  }

  const exportPlaylists = async () => {
    try {
      const ids = [...selected].join(',')
      const payload = await api<PlaylistBackup>('/playlists/export', {
        query: { ids: ids || undefined },
      })
      const stamp = new Date().toISOString().slice(0, 10)
      downloadJson(`muzikk-playlists-${stamp}.json`, payload)
    } catch (error) {
      fail(error)
    }
  }

  const readBackup = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as PlaylistBackup
      if (!parsed || !Array.isArray(parsed.playlists)) {
        notify(t('errors.generic'), 'error')
        return
      }
      setPendingFile(parsed)
      setImporting(true)
    } catch {
      notify(t('errors.generic'), 'error')
    }
  }

  const runImport = useMutation({
    mutationFn: () =>
      api<PlaylistImportReport>('/playlists/import', {
        method: 'POST',
        body: {
          ...(pendingFile ?? { version: 1, playlists: [] }),
          target_user_id: targetUserId || undefined,
        },
      }),
    onSuccess: (result) => {
      setImporting(false)
      setPendingFile(null)
      setTargetUserId('')
      setReport(result)
      refresh()
      const playlistsCount = result.playlists.length
      const tracksCount = result.playlists.reduce((sum, row) => sum + row.added, 0)
      const missing = result.playlists.reduce((sum, row) => sum + row.missing.length, 0)
      notify(t('playlists.imported', { playlists: playlistsCount, tracks: tracksCount }), 'success')
      if (missing) notify(t('playlists.importedMissing', { count: missing }), 'error')
    },
    onError: fail,
  })

  const rows = playlists.data ?? []
  const opened = rows.find((playlist) => playlist.id === openId)

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold text-ink-100">{t('playlists.title')}</h1>
          <p className="mt-1 text-sm text-ink-400">{t('playlists.subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => void exportPlaylists()} disabled={rows.length === 0}>
            <Download className="size-3.5" />
            {selected.size ? t('playlists.exportSelected') : t('playlists.exportAll')}
          </Button>
          <Button size="sm" onClick={() => fileRef.current?.click()}>
            <Upload className="size-3.5" />
            {t('playlists.import')}
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              event.target.value = ''
              if (file) void readBackup(file)
            }}
          />
          <Button size="sm" variant="primary" onClick={() => setCreating(true)}>
            <Plus className="size-3.5" />
            {t('playlists.create')}
          </Button>
        </div>
      </header>

      {playlists.isLoading ? (
        <CenteredSpinner />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<ListMusic className="size-10" />}
          title={t('playlists.empty')}
          hint={t('playlists.emptyHint')}
        />
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((playlist) => (
            <Card
              key={playlist.id}
              className="flex items-center gap-3 p-3 transition-colors hover:border-brand-500/30"
            >
              <label className="shrink-0" title={t('playlists.select')}>
                <input
                  type="checkbox"
                  checked={selected.has(playlist.id)}
                  onChange={() => toggle(playlist.id)}
                  className="size-4 accent-brand-500"
                />
              </label>
              <button type="button" onClick={() => setOpenId(playlist.id)} className="shrink-0">
                <AlbumCover
                  url={playlist.cover_url}
                  alt={playlist.name}
                  size={250}
                  className="size-12 rounded-lg"
                />
              </button>
              <button
                type="button"
                onClick={() => setOpenId(playlist.id)}
                className="min-w-0 flex-1 text-left"
              >
                <div className="truncate font-medium text-ink-100">{playlist.name}</div>
                <div className="hint">{t('playlists.tracks', { count: playlist.track_count })}</div>
              </button>
              <Button
                size="sm"
                variant="ghost"
                title={t('playlists.play')}
                onClick={async () => {
                  try {
                    const queue = await api<PlaylistTrack[]>(`/playlists/${playlist.id}`)
                    if (!queue.length) {
                      notify(t('playlists.nothingToPlay'), 'error')
                      return
                    }
                    player.playTracks(queue)
                  } catch (error) {
                    fail(error)
                  }
                }}
              >
                <Play className="size-3.5" />
              </Button>
            </Card>
          ))}
        </div>
      )}

      {creating && (
        <Modal open onClose={() => setCreating(false)} title={t('playlists.create')}>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className="label" htmlFor="playlist-name">
                {t('playlists.newName')}
              </label>
              <input
                id="playlist-name"
                className="field"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t('playlists.newPlaceholder')}
              />
            </div>
            <Button
              variant="primary"
              disabled={!name.trim()}
              loading={create.isPending}
              onClick={() => create.mutate()}
            >
              <ListPlus className="size-3.5" />
              {t('playlists.create')}
            </Button>
          </div>
        </Modal>
      )}

      {importing && pendingFile && (
        <Modal
          open
          onClose={() => {
            setImporting(false)
            setPendingFile(null)
          }}
          title={t('playlists.import')}
        >
          <div className="space-y-4">
            <p className="text-sm text-ink-300">
              {t('playlists.tracks', {
                count: pendingFile.playlists.reduce((sum, row) => sum + row.tracks.length, 0),
              })}
              {' · '}
              {pendingFile.playlists.length}
            </p>
            {user?.is_admin && (
              <div>
                <label className="label" htmlFor="playlist-target">
                  {t('playlists.importTarget')}
                </label>
                <Select
                  id="playlist-target"
                  value={targetUserId}
                  onChange={(event) => setTargetUserId(event.target.value)}
                >
                  <option value="">{t('playlists.importOwn')}</option>
                  {(accounts.data ?? []).map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <Button
              variant="primary"
              loading={runImport.isPending}
              onClick={() => runImport.mutate()}
            >
              {runImport.isPending ? t('playlists.importing') : t('playlists.import')}
            </Button>
          </div>
        </Modal>
      )}

      {report && (
        <Modal open onClose={() => setReport(null)} wide title={t('playlists.import')}>
          <ul className="space-y-3">
            {report.playlists.map((row, index) => (
              <li key={`${row.playlist_id}-${index}`} className="text-sm">
                <div className="font-medium text-ink-100">{row.name || t('playlists.title')}</div>
                <div className="hint">
                  {row.added
                    ? t('playlists.tracks', { count: row.added })
                    : t('playlists.importedNone')}
                  {row.missing.length
                    ? ` · ${t('playlists.importedMissing', { count: row.missing.length })}`
                    : ''}
                </div>
                {row.missing.length > 0 && (
                  <ul className="mt-1 space-y-0.5 text-xs text-accent-300">
                    {row.missing.map((track, position) => (
                      <li key={`${track.title}-${position}`}>
                        {[track.artist, track.album, track.title].filter(Boolean).join(' · ') ||
                          track.reason}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </Modal>
      )}

      {openId && (
        <Modal open onClose={() => setOpenId(null)} wide title={opened?.name ?? t('playlists.title')}>
          {tracks.isLoading ? (
            <CenteredSpinner />
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  disabled={!(tracks.data ?? []).length}
                  onClick={() => player.playTracks(tracks.data ?? [])}
                >
                  <Play className="size-3.5" />
                  {t('playlists.play')}
                </Button>
                {opened?.can_delete && (
                  <Button
                    size="sm"
                    variant="danger"
                    loading={destroy.isPending}
                    onClick={() => {
                      if (!window.confirm(t('playlists.confirmDelete'))) return
                      destroy.mutate(opened.id)
                    }}
                  >
                    <Trash2 className="size-3.5" />
                    {t('playlists.delete')}
                  </Button>
                )}
              </div>

              {(tracks.data ?? []).length === 0 ? (
                <EmptyState
                  icon={<ListMusic className="size-10" />}
                  title={t('playlists.noTracks')}
                />
              ) : (
                <ol className="space-y-1">
                  {(tracks.data ?? []).map((track, position) => (
                    <li
                      key={track.playlist_item_id || `${track.jellyfin_id}-${position}`}
                      className={clsx(
                        'flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm',
                        'hover:bg-ink-700/30',
                      )}
                    >
                      <button
                        type="button"
                        className="w-6 shrink-0 text-right tabular-nums text-ink-500 hover:text-brand-300"
                        onClick={() => player.playTracks(tracks.data ?? [], position)}
                        title={t('playlists.play')}
                      >
                        {position + 1}
                      </button>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-ink-100">{track.title}</div>
                        <div className="hint truncate">
                          {track.artist}
                          {track.album ? ` · ${track.album}` : ''}
                        </div>
                      </div>
                      <span className="shrink-0 tabular-nums text-ink-400">
                        {track.duration ? formatClock(track.duration) : '—'}
                      </span>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={!track.playlist_item_id || removeTrack.isPending}
                        title={t('playlists.remove')}
                        onClick={() => removeTrack.mutate(track.playlist_item_id)}
                      >
                        <X className="size-3.5" />
                      </Button>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </Modal>
      )}
    </div>
  )
}
