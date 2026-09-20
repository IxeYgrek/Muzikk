import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpCircle, Disc3, Play, RefreshCw, Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { AlbumCover } from '../components/AlbumCard'
import { useToast } from '../components/Toast'
import { TrackResults } from '../components/TrackResults'
import {
  Button,
  Card,
  CenteredSpinner,
  EmptyState,
  Select,
  StatCard,
  Tabs,
} from '../components/ui'
import { ApiError, api } from '../lib/api'
import { canRequestUpgrade, useAuth } from '../lib/auth'
import { useAlbumRequest, useDebounced, useLocalMode } from '../lib/hooks'
import { usePlayer } from '../lib/player'
import type { LibraryAlbum, LibraryResponse, TrackSearchResponse } from '../lib/types'

const PAGE_SIZE = 60

type LibraryStats = {
  albums: number
  lossless_albums: number
  lossy_albums: number
  tracks: number
  artists: number
}

export function LibraryPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const localMode = useLocalMode()
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const { request, requestByMbid, pendingId } = useAlbumRequest()
  const player = usePlayer()

  const [mode, setMode] = useState<'albums' | 'tracks'>('albums')
  const [text, setText] = useState('')
  const [genre, setGenre] = useState('')
  const [year, setYear] = useState('')
  const [quality, setQuality] = useState('')
  const [sort, setSort] = useState('recent')
  const search = useDebounced(text.trim(), 400)

  const stats = useQuery({
    queryKey: ['library', 'stats'],
    queryFn: () => api<LibraryStats>('/library/stats'),
  })
  const genres = useQuery({
    queryKey: ['library', 'genres'],
    queryFn: () => api<string[]>('/library/genres'),
    staleTime: 5 * 60_000,
  })
  const years = useQuery({
    queryKey: ['library', 'years'],
    queryFn: () => api<number[]>('/library/years'),
    staleTime: 5 * 60_000,
  })

  const albums = useInfiniteQuery({
    queryKey: ['library', 'albums', search, genre, year, quality, sort],
    enabled: mode === 'albums',
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<LibraryResponse>('/library/albums', {
        query: {
          q: search || undefined,
          genre: genre || undefined,
          year: year || undefined,
          quality: quality || undefined,
          sort,
          limit: PAGE_SIZE,
          offset: pageParam,
        },
      }),
    getNextPageParam: (lastPage) => {
      const next = lastPage.offset + PAGE_SIZE
      return next < lastPage.count ? next : undefined
    },
  })

  const tracks = useQuery({
    queryKey: ['library', 'tracks', search],
    enabled: mode === 'tracks' && search.length >= 2,
    queryFn: () =>
      api<TrackSearchResponse>('/tracks/search', {
        query: { q: search, scope: 'library', limit: 60 },
      }),
  })

  const sync = useMutation({
    mutationFn: () => api<Record<string, number>>('/library/sync', { method: 'POST' }),
    onSuccess: (result) => {
      notify(`${result.albums ?? 0} ${t('library.albums')}`, 'success')
      void queryClient.invalidateQueries({ queryKey: ['library'] })
    },
    onError: (error) =>
      notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error'),
  })

  const items = albums.data?.pages.flatMap((page) => page.items) ?? []
  const total = albums.data?.pages[0]?.count ?? 0

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold text-ink-100">{t('library.title')}</h1>
          <p className="mt-1 text-sm text-ink-400">
            {t(localMode ? 'library.subtitleLocal' : 'library.subtitle')}
          </p>
        </div>
        {user?.is_admin && (
          <Button onClick={() => sync.mutate()} loading={sync.isPending}>
            <RefreshCw className="size-4" />
            {sync.isPending ? t('library.syncing') : t('library.sync')}
          </Button>
        )}
      </header>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label={t('library.albums')}
          value={stats.data?.albums ?? '—'}
          icon={<Disc3 className="size-5" />}
        />
        <StatCard
          label={t('library.lossless')}
          value={stats.data?.lossless_albums ?? '—'}
          hint={
            stats.data && stats.data.albums > 0
              ? `${Math.round((stats.data.lossless_albums / stats.data.albums) * 100)} % ${t('library.losslessShare')}`
              : undefined
          }
          tone="success"
          icon={<ArrowUpCircle className="size-5" />}
        />
        <StatCard
          label={t('library.artists')}
          value={stats.data?.artists ?? '—'}
          tone="muted"
          icon={<Disc3 className="size-5" />}
        />
      </div>

      <Tabs
        active={mode}
        onChange={(id) => setMode(id as 'albums' | 'tracks')}
        tabs={[
          { id: 'albums', label: t('library.tabAlbums') },
          { id: 'tracks', label: t('library.tabTracks') },
        ]}
      />

      <Card className="flex flex-wrap items-center gap-2 p-3">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-500" />
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={
              mode === 'tracks' ? t('library.trackPlaceholder') : t('library.searchPlaceholder')
            }
            className="field pl-9"
          />
        </div>
        {mode === 'albums' && (
          <>
            <Select
              value={genre}
              onChange={(event) => setGenre(event.target.value)}
              className="w-auto"
            >
              <option value="">{t('library.allGenres')}</option>
              {(genres.data ?? []).map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
            <Select
              value={year}
              onChange={(event) => setYear(event.target.value)}
              className="w-auto"
            >
              <option value="">{t('library.allYears')}</option>
              {(years.data ?? []).map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
            <Select
              value={quality}
              onChange={(event) => setQuality(event.target.value)}
              className="w-auto"
            >
              <option value="">{t('library.allQualities')}</option>
              <option value="lossless">{t('library.lossless')}</option>
              <option value="lossy">{t('library.lossy')}</option>
            </Select>
            <Select value={sort} onChange={(event) => setSort(event.target.value)} className="w-auto">
              <option value="recent">{t('library.sortRecent')}</option>
              <option value="artist">{t('library.sortArtist')}</option>
              <option value="album">{t('library.sortAlbum')}</option>
              <option value="year">{t('library.sortYear')}</option>
            </Select>
          </>
        )}
      </Card>

      {mode === 'tracks' ? (
        search.length < 2 ? (
          <EmptyState
            icon={<Search className="size-10" />}
            title={t('library.trackEmpty')}
            hint={t('library.trackEmptyHint')}
          />
        ) : tracks.isLoading ? (
          <CenteredSpinner label={t('common.loading')} />
        ) : (
          <TrackResults
            tracks={tracks.data?.items ?? []}
            emptyTitle={t('library.trackNoResults')}
            onRequestAlbum={requestByMbid}
            pendingId={pendingId}
          />
        )
      ) : items.length === 0 && !albums.isLoading ? (
        <EmptyState
          icon={<Disc3 className="size-10" />}
          title={t('library.empty')}
          hint={t('library.emptyHint')}
        />
      ) : (
        <>
          <p className="text-xs text-ink-500">
            {total} {t('library.albums')}
          </p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {items.map((album) => (
              <LibraryTile
                key={album.id}
                album={album}
                onPlay={() => void player.playAlbum(album.jellyfin_id)}
                onUpgrade={
                  canRequestUpgrade(user)
                    ? () =>
                        album.release_group_mbid &&
                        request({ release_group_mbid: album.release_group_mbid }, true)
                    : undefined
                }
                upgrading={pendingId === album.release_group_mbid}
              />
            ))}
          </div>
          {albums.hasNextPage && (
            <div className="flex justify-center">
              <Button
                onClick={() => void albums.fetchNextPage()}
                loading={albums.isFetchingNextPage}
              >
                {t('common.loadMore')}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function LibraryTile({
  album,
  onPlay,
  onUpgrade,
  upgrading,
}: {
  album: LibraryAlbum
  onPlay: () => void
  onUpgrade?: () => void
  upgrading: boolean
}) {
  const { t } = useTranslation()
  const canUpgrade = Boolean(onUpgrade) && !album.is_lossless && Boolean(album.release_group_mbid)

  const cover = (
    <AlbumCover
      url={`/api/images/jellyfin/${album.jellyfin_id}`}
      alt={album.name}
      className="aspect-square w-full rounded-2xl ring-1 ring-ink-600/40 transition-all duration-300 group-hover:ring-brand-500/60"
    />
  )

  // Always the library page, even when a MusicBrainz identifier is present.
  // Jellyfin often stores a recording or artist MBID on a folder of leftovers
  // ("[standalone recordings]"): the catalogue route would 404, while this
  // page still has the files and the play button.
  const target = `/library/albums/${album.jellyfin_id}`

  return (
    <div className="group relative flex flex-col">
      <div className="relative">
        <Link to={target} className="block">
          {cover}
        </Link>

        <div className="absolute left-2 top-2 flex gap-1">
          <span
            className={
              album.is_lossless
                ? 'rounded-full bg-emerald-500/90 px-1.5 py-0.5 text-[0.6rem] font-bold uppercase text-ink-950'
                : 'rounded-full bg-ink-900/85 px-1.5 py-0.5 text-[0.6rem] font-bold uppercase text-ink-300'
            }
          >
            {album.formats[0] ?? (album.is_lossless ? 'flac' : 'lossy')}
          </span>
        </div>

        <div className="absolute bottom-2 right-2 flex gap-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {canUpgrade && (
            <button
              type="button"
              onClick={() => onUpgrade?.()}
              disabled={upgrading}
              title={t('album.upgrade')}
              className="grid size-8 place-items-center rounded-full bg-amber-500 text-ink-950"
            >
              <ArrowUpCircle className="size-4" />
            </button>
          )}
          <button
            type="button"
            onClick={onPlay}
            title={t('player.playAlbum')}
            className="grid size-9 place-items-center rounded-full gradient-surface text-white shadow-lg transition-transform hover:scale-105"
          >
            <Play className="size-4" />
          </button>
        </div>
      </div>

      <div className="mt-2 min-w-0 px-0.5">
        <Link
          to={target}
          className="block truncate text-sm font-semibold text-ink-100 hover:text-brand-200"
          title={album.name}
        >
          {album.name}
        </Link>
        <div className="flex items-center gap-1.5 truncate text-xs text-ink-400">
          <span className="truncate">{album.album_artist}</span>
          {album.year && <span className="shrink-0 text-ink-500">· {album.year}</span>}
        </div>
      </div>
    </div>
  )
}
