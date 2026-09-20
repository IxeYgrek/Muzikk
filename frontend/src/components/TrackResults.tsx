import clsx from 'clsx'
import { Check, Disc3, Download, Headphones, ListPlus, Music4, Play } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { formatClock } from '../lib/format'
import { useLocalMode, usePreview } from '../lib/hooks'
import { usePlayer } from '../lib/player'
import type { TrackSearchResult } from '../lib/types'
import { AddToPlaylistModal, type PlaylistTarget } from './AddToPlaylist'
import { AlbumCover } from './AlbumCard'
import { EmptyState, Spinner } from './ui'

/**
 * Track hits, whether they come from the library or from MusicBrainz.
 *
 * A track is never downloadable on its own: the action always targets the album
 * that holds it, which is exactly the point of searching this way.
 */
export function TrackResults({
  tracks,
  emptyTitle,
  emptyHint,
  onRequestAlbum,
  pendingId,
}: {
  tracks: TrackSearchResult[]
  emptyTitle: string
  emptyHint?: string
  onRequestAlbum?: (releaseGroupMbid: string) => void
  pendingId?: string | null
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const player = usePlayer()
  const localMode = useLocalMode()
  const { playPreview, previewLoading } = usePreview()
  const [playlistTarget, setPlaylistTarget] = useState<PlaylistTarget | null>(null)

  if (!tracks.length) {
    return <EmptyState icon={<Music4 className="size-10" />} title={emptyTitle} hint={emptyHint} />
  }

  return (
    <>
      <ul className="glass divide-y divide-ink-700/40 overflow-hidden rounded-2xl">
        {tracks.map((track, index) => {
          const playable = Boolean(track.jellyfin_id && track.album_jellyfin_id)
          // A library track whose album carries no MusicBrainz release group
          // still has somewhere to go: its page inside the library.
          const albumTarget = track.release_group_mbid
            ? `/albums/${track.release_group_mbid}`
            : track.album_jellyfin_id
              ? `/library/albums/${track.album_jellyfin_id}`
              : null
          // An extract has no identifier, so the row it came from is
          // recognised by the title the lookup was given.
          const playing = playable
            ? player.current?.jellyfin_id === track.jellyfin_id
            : Boolean(player.current?.preview) &&
              player.current?.title.toLowerCase() === track.title.toLowerCase()

          return (
            <li
              key={`${track.jellyfin_id ?? track.recording_mbid ?? track.title}-${index}`}
              className={clsx(
                'group flex items-center gap-3 px-3 py-2.5 transition-colors hover:bg-ink-700/25 sm:px-4',
                playing && 'bg-brand-600/10',
              )}
            >
              <div className="relative shrink-0">
                <AlbumCover url={track.cover_url} alt="" size={100} className="size-12 rounded-lg" />
                {playable ? (
                  <button
                    type="button"
                    onClick={() =>
                      void player.playAlbum(track.album_jellyfin_id!, track.jellyfin_id!)
                    }
                    className={clsx(
                      'absolute inset-0 grid place-items-center rounded-lg bg-ink-950/60 transition-opacity',
                      'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
                      playing && 'opacity-100',
                    )}
                    aria-label={t('player.play')}
                  >
                    <Play className="size-5 text-white" />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() =>
                      void playPreview({
                        title: track.title,
                        artist: track.artist,
                        album: track.album,
                        coverUrl: track.cover_url,
                      })
                    }
                    className={clsx(
                      'absolute inset-0 grid place-items-center rounded-lg bg-ink-950/60 transition-opacity',
                      'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
                      previewLoading === track.title && 'opacity-100',
                    )}
                    title={t('player.playPreview')}
                    aria-label={t('player.playPreview')}
                  >
                    {previewLoading === track.title ? (
                      <Spinner className="size-4 text-white" />
                    ) : (
                      <Headphones className="size-5 text-white" />
                    )}
                  </button>
                )}
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span
                    className={clsx(
                      'truncate text-sm font-medium',
                      playing ? 'text-brand-200' : 'text-ink-100',
                    )}
                  >
                    {track.title}
                  </span>
                  {track.owned && <Check className="size-3.5 shrink-0 text-emerald-400" />}
                </div>
                <div className="truncate text-xs text-ink-400">
                  {[track.artist, track.album, track.year || null].filter(Boolean).join(' · ')}
                </div>
              </div>

              <span className="hidden shrink-0 text-xs tabular-nums text-ink-500 sm:block">
                {track.duration ? formatClock(track.duration) : ''}
              </span>

              <div className="flex shrink-0 gap-1">
                {track.jellyfin_id && !localMode && (
                  <button
                    type="button"
                    onClick={() =>
                      setPlaylistTarget({
                        label: [track.artist, track.title].filter(Boolean).join(' — '),
                        trackIds: [track.jellyfin_id!],
                      })
                    }
                    className="btn btn-ghost btn-sm"
                    title={t('playlists.addTo')}
                  >
                    <ListPlus className="size-3.5" />
                  </button>
                )}
                {albumTarget && (
                  <button
                    type="button"
                    onClick={() => navigate(albumTarget)}
                    className="btn btn-ghost btn-sm"
                    title={t('tracks.openAlbum')}
                  >
                    <Disc3 className="size-3.5" />
                    <span className="hidden sm:inline">{t('tracks.album')}</span>
                  </button>
                )}
                {track.release_group_mbid && !track.owned && onRequestAlbum && (
                  <button
                    type="button"
                    onClick={() => onRequestAlbum(track.release_group_mbid!)}
                    disabled={pendingId === track.release_group_mbid}
                    className="btn btn-primary btn-sm"
                    title={t('tracks.requestAlbum')}
                  >
                    <Download className="size-3.5" />
                  </button>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      {playlistTarget && (
        <AddToPlaylistModal target={playlistTarget} onClose={() => setPlaylistTarget(null)} />
      )}
    </>
  )
}
