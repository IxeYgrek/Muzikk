import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ListMusic, ListPlus, Play, Plus, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AlbumCover } from '../components/AlbumCard'
import { useToast } from '../components/Toast'
import { Button, Card, CenteredSpinner, EmptyState, Modal } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { formatClock } from '../lib/format'
import { usePlayer } from '../lib/player'
import type { Playlist, PlaylistTrack } from '../lib/types'

export function PlaylistsPage() {
  const { t } = useTranslation()
  const { notify } = useToast()
  const queryClient = useQueryClient()
  const player = usePlayer()
  const [openId, setOpenId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')

  const playlists = useQuery({
    queryKey: ['playlists'],
    queryFn: () => api<Playlist[]>('/playlists'),
  })

  const tracks = useQuery({
    queryKey: ['playlists', openId],
    queryFn: () => api<PlaylistTrack[]>(`/playlists/${openId}`),
    enabled: Boolean(openId),
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

  const rows = playlists.data ?? []
  const opened = rows.find((playlist) => playlist.id === openId)

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold text-ink-100">{t('playlists.title')}</h1>
          <p className="mt-1 text-sm text-ink-400">{t('playlists.subtitle')}</p>
        </div>
        <Button size="sm" variant="primary" onClick={() => setCreating(true)}>
          <Plus className="size-3.5" />
          {t('playlists.create')}
        </Button>
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
