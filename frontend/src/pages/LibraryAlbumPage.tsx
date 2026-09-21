import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, Disc3, ListPlus, Play, Search, Wand2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { AddToPlaylistModal, type PlaylistTarget } from '../components/AddToPlaylist'
import { AlbumCover } from '../components/AlbumCard'
import { MusicBrainzLinks } from '../components/MusicBrainzLinks'
import { Alert, Button, Card, CenteredSpinner, Chip, EmptyState } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatClock } from '../lib/format'
import { useLocalMode } from '../lib/hooks'
import { usePlayer } from '../lib/player'
import type { LibraryAlbum, LibraryAlbumDetail } from '../lib/types'

/**
 * MusicBrainz wraps special-purpose artists in brackets. A folder filed
 * under one of those names is a pile of leftovers, not an album: there is
 * no release group behind it, even when the index stored some other MBID.
 */
function hasCataloguePage(album: LibraryAlbum): boolean {
  if (!album.release_group_mbid) return false
  const artist = album.album_artist.trim()
  return !(artist.startsWith('[') && artist.endsWith(']'))
}

/**
 * An album of the library seen from the library itself.
 *
 * The catalogue page needs a MusicBrainz release group; a folder of untagged
 * files has none, and this is where it lands so every sleeve in the grid can
 * be clicked.
 */
export function LibraryAlbumPage() {
  const { jellyfinId = '' } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const player = usePlayer()
  const { user } = useAuth()
  const localMode = useLocalMode()
  const [playlistTarget, setPlaylistTarget] = useState<PlaylistTarget | null>(null)

  const detail = useQuery({
    queryKey: ['library', 'album', jellyfinId],
    queryFn: () => api<LibraryAlbumDetail>(`/library/albums/${jellyfinId}`),
    enabled: Boolean(jellyfinId),
  })

  if (detail.isLoading) return <CenteredSpinner label={t('common.loading')} />

  if (detail.isError || !detail.data) {
    return (
      <EmptyState
        icon={<Disc3 className="size-10" />}
        title={t('library.albumNotFound')}
        hint={detail.error instanceof ApiError ? detail.error.message : undefined}
        action={
          <Button onClick={() => navigate(-1)}>
            <ArrowLeft className="size-4" />
            {t('common.back')}
          </Button>
        }
      />
    )
  }

  const { album, tracks, tracks_error: tracksError } = detail.data
  const discs = [...new Set(tracks.map((track) => track.disc ?? 1))].sort((a, b) => a - b)

  return (
    <div className="space-y-8">
      <button type="button" onClick={() => navigate(-1)} className="btn btn-ghost btn-sm -ml-2">
        <ArrowLeft className="size-4" />
        {t('common.back')}
      </button>

      <div className="grid gap-8 lg:grid-cols-[18rem_1fr] xl:grid-cols-[22rem_1fr]">
        <div className="space-y-4">
          <AlbumCover
            url={`/api/images/jellyfin/${album.jellyfin_id}`}
            alt={album.name}
            size={1200}
            className="aspect-square rounded-2xl shadow-[var(--shadow-card)] ring-1 ring-ink-600/40"
          />

          <Button className="w-full" onClick={() => void player.playAlbum(album.jellyfin_id)}>
            <Play className="size-4" />
            {t('player.playAlbum')}
          </Button>
          {!localMode && (
            <Button
              variant="secondary"
              className="w-full"
              onClick={() =>
                setPlaylistTarget({
                  label: `${album.album_artist} — ${album.name}`,
                  albumId: album.jellyfin_id,
                })
              }
            >
              <ListPlus className="size-4" />
              {t('playlists.addTo')}
            </Button>
          )}

          {hasCataloguePage(album) ? (
            <>
              <Link
                to={`/albums/${album.release_group_mbid}`}
                className="btn btn-ghost w-full justify-center"
              >
                <Search className="size-4" />
                {t('library.openCatalogue')}
              </Link>
              <MusicBrainzLinks
                groupMbid={album.release_group_mbid ?? ''}
                releaseMbid={album.release_mbid}
              />
            </>
          ) : (
            <Alert tone="info" className="space-y-2 text-left">
              <p>{t('library.noMbid')}</p>
              <p className="text-xs opacity-80">{t('library.noMbidHint')}</p>
              {user?.is_admin && (
                <Link to="/metadata" className="btn btn-ghost btn-sm">
                  <Wand2 className="size-3.5" />
                  {t('nav.metadata')}
                </Link>
              )}
            </Alert>
          )}

          {album.path && (
            <p className="hint break-all" title={album.path}>
              {album.path}
            </p>
          )}
        </div>

        <div className="min-w-0 space-y-6">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone={album.is_lossless ? 'success' : 'muted'}>
                {album.formats.join(', ') || (album.is_lossless ? 'flac' : t('library.lossy'))}
              </Chip>
              {album.genres.slice(0, 4).map((genre) => (
                <Chip key={genre}>{genre}</Chip>
              ))}
            </div>
            <h1 className="mt-3 font-display text-3xl font-bold text-ink-100">{album.name}</h1>
            <p className="mt-1 text-lg text-ink-300">
              {album.album_artist}
              {album.year ? ` · ${album.year}` : ''}
            </p>
            {album.label && <p className="mt-1 text-sm text-ink-400">{album.label}</p>}
          </div>

          <section>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-3">
              <h2 className="font-display text-lg text-ink-100">{t('album.tracklist')}</h2>
              {tracks.length > 0 && <span className="hint">{t('album.playTrackHint')}</span>}
            </div>

            {tracksError ? (
              <Alert tone="warning">{tracksError}</Alert>
            ) : tracks.length === 0 ? (
              <Card className="p-6 text-center text-sm text-ink-400">{t('album.noTracks')}</Card>
            ) : (
              <Card className="divide-y divide-ink-700/40 overflow-hidden">
                {discs.map((disc) => (
                  <div key={disc}>
                    {discs.length > 1 && (
                      <div className="bg-ink-800/50 px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-ink-400">
                        {t('album.disc')} {disc}
                      </div>
                    )}
                    {tracks
                      .filter((track) => (track.disc ?? 1) === disc)
                      .map((track, position) => {
                        const isCurrent = player.current?.jellyfin_id === track.jellyfin_id
                        return (
                          <div
                            key={track.jellyfin_id}
                            role="button"
                            tabIndex={0}
                            onClick={() =>
                              void player.playAlbum(album.jellyfin_id, track.jellyfin_id)
                            }
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                void player.playAlbum(album.jellyfin_id, track.jellyfin_id)
                              }
                            }}
                            className={clsx(
                              'group flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm transition-colors hover:bg-ink-700/25',
                              isCurrent && 'bg-brand-600/15',
                            )}
                          >
                            <span
                              className={clsx(
                                'w-6 shrink-0 text-right tabular-nums',
                                isCurrent ? 'text-brand-300' : 'text-ink-500',
                              )}
                            >
                              <Play className="ml-auto hidden size-3.5 fill-current group-hover:block" />
                              <span className="group-hover:hidden">
                                {track.track ?? position + 1}
                              </span>
                            </span>
                            <span
                              className={clsx(
                                'min-w-0 flex-1 truncate',
                                isCurrent ? 'text-brand-200' : 'text-ink-100',
                              )}
                            >
                              {track.title}
                            </span>
                            {track.artist && track.artist !== album.album_artist && (
                              <span className="hidden max-w-40 truncate text-xs text-ink-400 sm:block">
                                {track.artist}
                              </span>
                            )}
                            <span className="shrink-0 tabular-nums text-xs text-ink-400">
                              {track.duration ? formatClock(track.duration) : ''}
                            </span>
                            {!localMode && (
                              <span className="grid size-7 shrink-0 place-items-center">
                                <button
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    setPlaylistTarget({
                                      label: [track.artist || album.album_artist, track.title]
                                        .filter(Boolean)
                                        .join(' — '),
                                      trackIds: [track.jellyfin_id],
                                    })
                                  }}
                                  title={t('playlists.addTo')}
                                  aria-label={t('playlists.addTo')}
                                  className="rounded-lg p-1.5 text-ink-400 opacity-0 transition-opacity hover:bg-ink-700/60 hover:text-ink-100 focus-visible:opacity-100 group-hover:opacity-100"
                                >
                                  <ListPlus className="size-3.5" />
                                </button>
                              </span>
                            )}
                          </div>
                        )
                      })}
                  </div>
                ))}
              </Card>
            )}
          </section>
        </div>
      </div>

      {playlistTarget && (
        <AddToPlaylistModal target={playlistTarget} onClose={() => setPlaylistTarget(null)} />
      )}
    </div>
  )
}
