import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ListMusic, Plus } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useToast } from './Toast'
import { Button, CenteredSpinner, EmptyState, Modal } from './ui'
import { ApiError, api } from '../lib/api'
import type { Playlist } from '../lib/types'

/** What is being filed: a whole album, or a handful of tracks. */
export type PlaylistTarget = {
  label: string
  albumId?: string
  trackIds?: string[]
}

export function AddToPlaylistModal({
  target,
  onClose,
}: {
  target: PlaylistTarget
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { notify } = useToast()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')

  const playlists = useQuery({
    queryKey: ['playlists'],
    queryFn: () => api<Playlist[]>('/playlists'),
  })

  const body = { album_id: target.albumId ?? null, track_ids: target.trackIds ?? [] }

  const done = (added: number) => {
    notify(t('playlists.added', { count: added }), 'success')
    void queryClient.invalidateQueries({ queryKey: ['playlists'] })
    onClose()
  }

  const fail = (error: unknown) =>
    notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error')

  const addTo = useMutation({
    mutationFn: (playlistId: string) =>
      api<{ added: number }>(`/playlists/${playlistId}/items`, { method: 'POST', body }),
    onSuccess: (result) => done(result.added),
    onError: fail,
  })

  const create = useMutation({
    mutationFn: () =>
      api<{ added: number }>('/playlists', { method: 'POST', body: { ...body, name } }),
    onSuccess: (result) => done(result.added),
    onError: fail,
  })

  const busy = addTo.isPending || create.isPending

  return (
    <Modal open onClose={onClose} title={t('playlists.addTo')}>
      <div className="space-y-4">
        <p className="text-sm text-ink-300">{target.label}</p>

        {playlists.isLoading ? (
          <CenteredSpinner />
        ) : (playlists.data ?? []).length === 0 ? (
          <EmptyState icon={<ListMusic className="size-10" />} title={t('playlists.empty')} />
        ) : (
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {(playlists.data ?? []).map((playlist) => (
              <button
                key={playlist.id}
                type="button"
                disabled={busy}
                onClick={() => addTo.mutate(playlist.id)}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left hover:bg-ink-700/40 disabled:opacity-50"
              >
                <ListMusic className="size-4 shrink-0 text-ink-500" />
                <span className="min-w-0 flex-1 truncate text-sm text-ink-100">
                  {playlist.name}
                </span>
                <span className="hint shrink-0">
                  {t('playlists.tracks', { count: playlist.track_count })}
                </span>
              </button>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2 border-t border-ink-600/40 pt-4">
          <div className="flex-1">
            <label className="label" htmlFor="new-playlist">
              {t('playlists.newName')}
            </label>
            <input
              id="new-playlist"
              className="field"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t('playlists.newPlaceholder')}
            />
          </div>
          <Button
            variant="primary"
            disabled={!name.trim() || busy}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            <Plus className="size-3.5" />
            {t('playlists.create')}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
