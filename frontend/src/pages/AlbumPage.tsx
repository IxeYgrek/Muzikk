import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ArrowLeft,
  ArrowUpCircle,
  BadgeCheck,
  Disc3,
  Download,
  Headphones,
  Heart,
  Info,
  ListPlus,
  Play,
  Star,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { AddToPlaylistModal, type PlaylistTarget } from '../components/AddToPlaylist'
import { AlbumCover } from '../components/AlbumCard'
import { MusicBrainzLinks } from '../components/MusicBrainzLinks'
import { ReleasePicker } from '../components/ReleasePicker'
import { StatusBadge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import { Alert, Button, Card, CenteredSpinner, Chip, EmptyState, Spinner } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { canRequestUpgrade, useAuth } from '../lib/auth'
import { formatDuration } from '../lib/format'
import { useAlbumRequest, useLocalMode, usePreview } from '../lib/hooks'
import { usePlayer } from '../lib/player'
import type { AlbumDetail, PlayableTrack, WatchedArtist } from '../lib/types'

/** Loose key used to pair a MusicBrainz title with the file on disk. */
function titleKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '')
}

export function AlbumPage() {
  const { mbid = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const releaseParam = searchParams.get('release')
  const { t } = useTranslation()
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const { request, pendingId } = useAlbumRequest()
  const { playPreview, previewLoading } = usePreview()
  const player = usePlayer()
  const localMode = useLocalMode()
  const [playlistTarget, setPlaylistTarget] = useState<PlaylistTarget | null>(null)

  const albumQuery = useQuery({
    queryKey: ['album', mbid, releaseParam],
    queryFn: () =>
      api<AlbumDetail>(`/albums/${mbid}`, {
        query: { release: releaseParam ?? undefined },
      }),
    enabled: Boolean(mbid),
  })

  const watchlistQuery = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => api<WatchedArtist[]>('/watchlist'),
  })

  const album = albumQuery.data
  const watched = album?.artist_mbid
    ? watchlistQuery.data?.find((row) => row.artist_mbid === album.artist_mbid)
    : undefined

  // Owned albums get their real files listed, so every row can start there
  // instead of forcing the listener to skip forward.
  const libraryId = album?.ownership.jellyfin_id ?? null
  const playableQuery = useQuery({
    queryKey: ['playable', libraryId],
    queryFn: () => api<PlayableTrack[]>(`/play/album/${libraryId}`),
    enabled: Boolean(libraryId),
    staleTime: 5 * 60 * 1000,
  })

  const playable = playableQuery.data ?? []
  const playableIndex = useMemo(() => {
    const byNumber = new Map<string, number>()
    const byTitle = new Map<string, number>()
    playable.forEach((track, position) => {
      byNumber.set(`${track.disc ?? 1}-${track.track ?? 0}`, position)
      const key = titleKey(track.title)
      if (key && !byTitle.has(key)) byTitle.set(key, position)
    })
    return { byNumber, byTitle }
  }, [playable])

  // An extract carries no identifier, so the row it belongs to is recognised
  // by its title, which is all the lookup was given in the first place.
  const currentPreview = player.current?.preview ? player.current : null

  const findPlayable = (disc: number, position: number, title: string): number => {
    const byNumber = playableIndex.byNumber.get(`${disc}-${position}`)
    if (byNumber !== undefined) return byNumber
    return playableIndex.byTitle.get(titleKey(title)) ?? -1
  }

  const follow = useMutation({
    mutationFn: () =>
      api('/watchlist', {
        method: 'POST',
        body: { artist_mbid: album?.artist_mbid, artist_name: album?.artist },
      }),
    onSuccess: () => {
      notify(t('album.followingArtist'), 'success')
      void queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    },
    onError: (error) => notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error'),
  })

  const wishlist = useMutation({
    mutationFn: () =>
      api('/wishlist', {
        method: 'POST',
        body: {
          release_group_mbid: album?.release_group_mbid,
          artist_name: album?.artist,
          album_title: album?.title,
          artist_mbid: album?.artist_mbid,
          year: album?.year,
        },
      }),
    onSuccess: () => {
      notify(t('album.addedToWishlist'), 'success')
      void queryClient.invalidateQueries({ queryKey: ['wishlist'] })
    },
    onError: (error) => notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error'),
  })

  if (albumQuery.isLoading) return <CenteredSpinner label={t('common.loading')} />

  if (albumQuery.isError || !album) {
    return (
      <EmptyState
        icon={<Disc3 className="size-10" />}
        title={t('errors.generic')}
        hint={albumQuery.error instanceof ApiError ? albumQuery.error.message : undefined}
        action={
          <Button onClick={() => navigate(-1)}>
            <ArrowLeft className="size-4" />
            {t('common.back')}
          </Button>
        }
      />
    )
  }

  const owned = album.ownership.status === 'owned'
  const probable = album.ownership.status === 'probable'
  const upgradable = album.ownership.upgradable && canRequestUpgrade(user)
  const busy = Boolean(album.request_status) && album.request_status !== 'failed'
  const selected = album.selected_release
  const discs = [...new Set(album.tracks.map((track) => track.disc))].sort((a, b) => a - b)

  return (
    <div className="space-y-8">
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="btn btn-ghost btn-sm -ml-2"
      >
        <ArrowLeft className="size-4" />
        {t('common.back')}
      </button>

      <div className="grid gap-8 lg:grid-cols-[18rem_1fr] xl:grid-cols-[22rem_1fr]">
        <div className="space-y-4">
          <AlbumCover
            url={album.cover_url}
            alt={album.title}
            size={1200}
            className="aspect-square rounded-2xl shadow-[var(--shadow-card)] ring-1 ring-ink-600/40"
          />

          <div className="space-y-2">
            {owned ? (
              <Alert tone="success" className="flex items-center gap-2">
                <BadgeCheck className="size-4 shrink-0" />
                {t('album.owned')}
                {album.ownership.formats.length > 0 && (
                  <span className="ml-auto text-xs uppercase opacity-70">
                    {album.ownership.formats.join(', ')}
                  </span>
                )}
              </Alert>
            ) : probable ? (
              <Alert tone="info" className="flex items-center gap-2">
                <BadgeCheck className="size-4 shrink-0" />
                {t('album.probable')}
              </Alert>
            ) : null}

            {album.request_status && (
              <div className="flex items-center gap-2">
                <StatusBadge status={album.request_status} />
                {album.request_id && (
                  <Link
                    to={`/requests/${album.request_id}`}
                    className="text-xs text-brand-300 hover:underline"
                  >
                    {t('album.viewRequest')}
                  </Link>
                )}
              </div>
            )}

            {album.ownership.jellyfin_id && (
              <>
                <Button
                  variant="primary"
                  className="w-full"
                  onClick={() => void player.playAlbum(album.ownership.jellyfin_id!)}
                >
                  <Play className="size-4" />
                  {t('player.playAlbum')}
                </Button>
                {!localMode && (
                  <Button
                    className="w-full"
                    onClick={() =>
                      setPlaylistTarget({
                        label: `${album.artist} — ${album.title}`,
                        albumId: album.ownership.jellyfin_id ?? undefined,
                      })
                    }
                  >
                    <ListPlus className="size-4" />
                    {t('playlists.addTo')}
                  </Button>
                )}
              </>
            )}

            {upgradable ? (
              <Button
                variant="primary"
                className="w-full"
                loading={pendingId === album.release_group_mbid}
                disabled={busy}
                onClick={() => request(album, true, selected?.release_mbid)}
              >
                <ArrowUpCircle className="size-4" />
                {t('album.upgrade')}
              </Button>
            ) : !owned ? (
              <Button
                variant="primary"
                className="w-full"
                loading={pendingId === album.release_group_mbid}
                disabled={busy}
                onClick={() => request(album, false, selected?.release_mbid)}
              >
                <Download className="size-4" />
                {t('album.request')}
              </Button>
            ) : null}

            <div className="grid grid-cols-2 gap-2">
              <Button
                size="sm"
                onClick={() => wishlist.mutate()}
                loading={wishlist.isPending}
                disabled={owned}
              >
                <Heart className="size-3.5" />
                {t('album.addToWishlist')}
              </Button>
              <Button
                size="sm"
                onClick={() => follow.mutate()}
                loading={follow.isPending}
                disabled={!album.artist_mbid || Boolean(watched)}
              >
                <Star className={clsx('size-3.5', watched && 'fill-current')} />
                {watched ? t('album.followingArtist') : t('album.followArtist')}
              </Button>
            </div>

            <p className="hint flex items-start gap-1.5 pt-1">
              <Info className="mt-0.5 size-3.5 shrink-0" />
              {t('album.albumOnly')}
            </p>
            <MusicBrainzLinks
              groupMbid={album.release_group_mbid}
              releaseMbid={selected?.release_mbid}
            />
          </div>
        </div>

        <div className="min-w-0 space-y-6">
          <header className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              {album.primary_type && <Chip tone="brand">{album.primary_type}</Chip>}
              {album.secondary_types.map((type) => (
                <Chip key={type}>{type}</Chip>
              ))}
              {album.year && <Chip>{album.year}</Chip>}
            </div>

            <h1 className="font-display text-3xl font-bold leading-tight text-ink-100 sm:text-4xl">
              {album.title}
            </h1>

            {album.artist_mbid ? (
              <Link
                to={`/artists/${album.artist_mbid}`}
                className="inline-block text-lg text-brand-300 hover:underline"
              >
                {album.artist}
              </Link>
            ) : (
              <div className="text-lg text-ink-300">{album.artist}</div>
            )}

            {album.genres.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {album.genres.slice(0, 10).map((genre) => (
                  <Chip key={genre}>{genre}</Chip>
                ))}
              </div>
            )}
          </header>

          {selected && (
            <Card className="p-4">
              <div className="grid flex-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
                <Detail label={t('album.edition')} value={selected.title} />
                <Detail label={t('album.released')} value={selected.date} />
                <Detail label={t('album.format')} value={selected.formats.join(', ')} />
                <Detail label={t('album.label')} value={selected.label} />
                <Detail label={t('album.country')} value={selected.country} />
                <Detail
                  label={t('common.tracks')}
                  value={selected.track_count ? String(selected.track_count) : null}
                />
              </div>

              {!owned && album.releases.length > 0 && (
                <div className="mt-4 border-t border-ink-600/40 pt-4">
                  <ReleasePicker
                    releases={album.releases}
                    selectedMbid={selected.release_mbid}
                    onSelect={(mbid) => setSearchParams({ release: mbid })}
                  />
                </div>
              )}
            </Card>
          )}

          <section>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-3">
              <h2 className="font-display text-lg text-ink-100">{t('album.tracklist')}</h2>
              <span className="hint">
                {playable.length > 0 ? t('album.playTrackHint') : t('album.previewHint')}
              </span>
            </div>
            {album.tracks.length === 0 ? (
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
                    {album.tracks
                      .filter((track) => track.disc === disc)
                      .map((track) => {
                        const target = findPlayable(track.disc, track.position, track.title)
                        const owned = target >= 0
                        const isCurrent = owned
                          ? player.current?.jellyfin_id === playable[target]?.jellyfin_id
                          : titleKey(currentPreview?.title ?? '') === titleKey(track.title)
                        const waiting = !owned && previewLoading === track.title
                        const activate = () => {
                          if (owned) {
                            player.playTracks(playable, target)
                            return
                          }
                          void playPreview({
                            title: track.title,
                            artist: track.artist || album.artist,
                            album: album.title,
                            coverUrl: album.cover_url,
                          })
                        }
                        return (
                          <div
                            key={`${track.disc}-${track.position}-${track.title}`}
                            role="button"
                            tabIndex={0}
                            onClick={activate}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                activate()
                              }
                            }}
                            title={owned ? undefined : t('player.playPreview')}
                            className={clsx(
                              'group flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm transition-colors',
                              'hover:bg-ink-700/25',
                              isCurrent && 'bg-brand-600/15',
                            )}
                          >
                            <span
                              className={clsx(
                                'w-6 shrink-0 text-right tabular-nums',
                                isCurrent ? 'text-brand-300' : 'text-ink-500',
                              )}
                            >
                              {waiting ? (
                                <Spinner className="ml-auto size-3.5" />
                              ) : (
                                <>
                                  {owned ? (
                                    <Play className="ml-auto hidden size-3.5 fill-current group-hover:block" />
                                  ) : (
                                    <Headphones className="ml-auto hidden size-3.5 group-hover:block" />
                                  )}
                                  <span className="group-hover:hidden">{track.position}</span>
                                </>
                              )}
                            </span>
                            <span
                              className={clsx(
                                'min-w-0 flex-1 truncate',
                                isCurrent ? 'text-brand-200' : 'text-ink-100',
                              )}
                            >
                              {track.title}
                            </span>
                            {track.artist && (
                              <span className="hidden max-w-40 truncate text-xs text-ink-400 sm:block">
                                {track.artist}
                              </span>
                            )}
                            <span className="shrink-0 tabular-nums text-xs text-ink-400">
                              {formatDuration(track.length_ms)}
                            </span>
                            {/* Kept the same width whether the button is there
                                or not, so the durations stay aligned. */}
                            <span className="grid size-7 shrink-0 place-items-center">
                              {owned && !localMode && playable[target].jellyfin_id && (
                                <button
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    setPlaylistTarget({
                                      label: [track.artist || album.artist, track.title]
                                        .filter(Boolean)
                                        .join(' — '),
                                      trackIds: [playable[target].jellyfin_id],
                                    })
                                  }}
                                  title={t('playlists.addTo')}
                                  aria-label={t('playlists.addTo')}
                                  className="rounded-lg p-1.5 text-ink-400 opacity-0 transition-opacity hover:bg-ink-700/60 hover:text-ink-100 focus-visible:opacity-100 group-hover:opacity-100"
                                >
                                  <ListPlus className="size-3.5" />
                                </button>
                              )}
                            </span>
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

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null
  return (
    <div className="min-w-0">
      <div className="text-[0.7rem] font-semibold uppercase tracking-wide text-ink-500">{label}</div>
      <div className="truncate text-ink-200" title={value}>
        {value}
      </div>
    </div>
  )
}
