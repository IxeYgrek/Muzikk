import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useToast } from '../components/Toast'
import { ApiError, api } from './api'
import { usePlayer } from './player'
import type { AlbumCard, AlbumRequest, Health, Mode, PlayableTrack } from './types'

/**
 * Whether this installation runs without Jellyfin.
 *
 * The mode is decided once by the first run wizard and cannot change, so the
 * answer is cached for the session and shared with the check `App` already
 * makes on startup.
 */
export function useMode(): Mode {
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: () => api<Health>('/health'),
    staleTime: Number.POSITIVE_INFINITY,
  })
  return data?.mode ?? 'jellyfin'
}

export function useLocalMode(): boolean {
  return useMode() === 'local'
}

/** MusicBrainz.org (or the optional browse_url) used for catalogue links. */
export function useMusicBrainzBrowseUrl(): string {
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: () => api<Health>('/health'),
    staleTime: Number.POSITIVE_INFINITY,
  })
  return data?.musicbrainz_browse_url || 'https://musicbrainz.org'
}

/** Debounce any fast-changing value (search inputs mostly). */
export function useDebounced<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export function useLocalStorage<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key)
      return raw ? (JSON.parse(raw) as T) : initial
    } catch {
      return initial
    }
  })

  const update = useCallback(
    (next: T) => {
      setValue(next)
      try {
        window.localStorage.setItem(key, JSON.stringify(next))
      } catch {
        /* private browsing */
      }
    },
    [key],
  )

  return [value, update]
}

type PreviewInput = { title: string; artist?: string; album?: string; coverUrl?: string | null }

/**
 * Play a thirty second extract of a track the library does not hold.
 *
 * The extract is looked up when asked for, not when the list is drawn: a
 * tracklist of twenty rows would otherwise fire twenty lookups at Deezer for
 * the one row somebody was curious about.
 */
export function usePreview() {
  const player = usePlayer()
  const { notify } = useToast()
  const { t } = useTranslation()
  const [loadingTitle, setLoadingTitle] = useState<string | null>(null)

  const playPreview = useCallback(
    async (input: PreviewInput) => {
      setLoadingTitle(input.title)
      try {
        const track = await api<PlayableTrack>('/play/preview', {
          query: {
            title: input.title,
            artist: input.artist ?? '',
            album: input.album ?? '',
            cover_url: input.coverUrl ?? '',
          },
        })
        player.playTracks([track])
      } catch (error) {
        notify(
          error instanceof ApiError && error.status !== 404
            ? error.message
            : t('player.noPreview'),
          'error',
        )
      } finally {
        setLoadingTitle(null)
      }
    },
    [notify, player, t],
  )

  return { playPreview, previewLoading: loadingTitle }
}

type RequestInput = {
  release_group_mbid: string
  release_mbid?: string | null
  is_upgrade?: boolean
  /** Set to ask for one track rather than the album holding it. */
  recording_mbid?: string | null
}

type CardPatch = { release_group_mbid: string; request_status: string; request_id: number }

/**
 * Flag the requested album inside the cached payloads.
 *
 * Refetching instead would be simpler, but the discovery lists draw random
 * artists: the whole grid would change under the reader who just clicked.
 */
function patchCards(data: unknown, patch: CardPatch): unknown {
  if (Array.isArray(data)) {
    let changed = false
    const next = data.map((item) => {
      const patched = patchCards(item, patch)
      changed = changed || patched !== item
      return patched
    })
    return changed ? next : data
  }
  if (!data || typeof data !== 'object') return data

  const record = data as Record<string, unknown>
  if (record.release_group_mbid === patch.release_group_mbid && 'request_status' in record) {
    return { ...record, request_status: patch.request_status, request_id: patch.request_id }
  }
  for (const key of ['items', 'pages', 'release_groups']) {
    if (key in record) {
      const patched = patchCards(record[key], patch)
      if (patched !== record[key]) return { ...record, [key]: patched }
    }
  }
  return data
}

/** Shared "request this album" mutation with toasts and cache invalidation. */
export function useAlbumRequest() {
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const { t } = useTranslation()
  const [pendingId, setPendingId] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (input: RequestInput) =>
      api<AlbumRequest>('/requests', { method: 'POST', body: input }),
    onSuccess: (created) => {
      notify(
        created.status === 'pending' ? t('requests.createdPending') : t('requests.created'),
        'success',
      )
      const patch: CardPatch = {
        release_group_mbid: created.release_group_mbid,
        request_status: created.status,
        request_id: created.id,
      }
      queryClient.setQueriesData({ queryKey: ['discover'] }, (data) => patchCards(data, patch))
      void queryClient.invalidateQueries({ queryKey: ['requests'] })
      void queryClient.invalidateQueries({ queryKey: ['albums'] })
      void queryClient.invalidateQueries({ queryKey: ['album'] })
      void queryClient.invalidateQueries({ queryKey: ['activity'] })
      void queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    },
    onError: (error) => {
      notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error')
    },
    onSettled: () => setPendingId(null),
  })

  const request = useCallback(
    (album: Pick<AlbumCard, 'release_group_mbid'>, isUpgrade = false, releaseMbid?: string | null) => {
      setPendingId(album.release_group_mbid)
      mutation.mutate({
        release_group_mbid: album.release_group_mbid,
        release_mbid: releaseMbid ?? null,
        is_upgrade: isUpgrade,
      })
    },
    [mutation],
  )

  /** Same request, from a track hit that only carries a release group. */
  const requestByMbid = useCallback(
    (releaseGroupMbid: string) => {
      setPendingId(releaseGroupMbid)
      mutation.mutate({ release_group_mbid: releaseGroupMbid })
    },
    [mutation],
  )

  /**
   * One track instead of the album. The album still travels with it: that is
   * where the file gets filed, and the server needs it to tag the download.
   */
  const requestTrack = useCallback(
    (recordingMbid: string, releaseGroupMbid: string, releaseMbid?: string | null) => {
      setPendingId(recordingMbid)
      mutation.mutate({
        release_group_mbid: releaseGroupMbid,
        release_mbid: releaseMbid ?? null,
        recording_mbid: recordingMbid,
      })
    },
    [mutation],
  )

  return { request, requestByMbid, requestTrack, pendingId, isPending: mutation.isPending }
}
