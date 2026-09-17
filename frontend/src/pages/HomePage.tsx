import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Activity, Clock, Disc3, Search, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { AlbumGrid, AlbumGridSkeleton } from '../components/AlbumCard'
import { LocalImportCard } from '../components/LocalImport'
import { ArtistGrid, ArtistGridSkeleton } from '../components/ArtistCard'
import { LabelGrid, LabelGridSkeleton } from '../components/LabelCard'
import { TrackResults } from '../components/TrackResults'
import { Button, CenteredSpinner, EmptyState, StatCard, Tabs } from '../components/ui'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import { useAlbumRequest, useDebounced } from '../lib/hooks'
import type { Artist, Label, SearchResponse, Stats, TrackSearchResponse } from '../lib/types'

const PAGE_SIZE = 36
const ARTIST_TAB = 'artist'
const TRACK_TAB = 'track'
const LABEL_TAB = 'label'

export function HomePage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  // The tab is either what to look for, or which kind of album to keep.
  const [type, setType] = useState('')
  const query = useDebounced(text.trim(), 400)
  const { request, requestByMbid, pendingId } = useAlbumRequest()
  const searchingArtists = type === ARTIST_TAB
  const searchingTracks = type === TRACK_TAB
  const searchingLabels = type === LABEL_TAB
  const searchingAlbums = !searchingArtists && !searchingTracks && !searchingLabels

  const { data: stats } = useQuery({
    queryKey: ['activity', 'stats'],
    queryFn: () => api<Stats>('/activity/stats'),
  })

  const search = useInfiniteQuery({
    queryKey: ['albums', 'search', query, type],
    enabled: query.length >= 2 && searchingAlbums,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<SearchResponse>('/albums/search', {
        query: {
          q: query,
          limit: PAGE_SIZE,
          offset: pageParam,
          primary_type: type || undefined,
        },
      }),
    getNextPageParam: (lastPage) => {
      const next = lastPage.offset + PAGE_SIZE
      return next < lastPage.count ? next : undefined
    },
  })

  const artistSearch = useQuery({
    queryKey: ['artists', 'search', query],
    enabled: query.length >= 2 && searchingArtists,
    queryFn: () => api<Artist[]>('/artists/search', { query: { q: query, limit: 30 } }),
  })

  const trackSearch = useQuery({
    queryKey: ['tracks', 'search', query],
    enabled: query.length >= 2 && searchingTracks,
    queryFn: () => api<TrackSearchResponse>('/tracks/search', { query: { q: query, limit: 40 } }),
  })

  const labelSearch = useQuery({
    queryKey: ['labels', 'search', query],
    enabled: query.length >= 2 && searchingLabels,
    queryFn: () => api<Label[]>('/labels/search', { query: { q: query, limit: 30 } }),
  })

  const albums = search.data?.pages.flatMap((page) => page.items) ?? []
  const loading = searchingArtists
    ? artistSearch.isLoading
    : searchingTracks
      ? trackSearch.isLoading
      : searchingLabels
        ? labelSearch.isLoading
        : search.isLoading

  const placeholder = searchingArtists
    ? t('home.placeholderArtist')
    : searchingTracks
      ? t('home.placeholderTrack')
      : searchingLabels
        ? t('home.placeholderLabel')
        : t('home.placeholder')

  function skeleton() {
    if (searchingArtists) return <ArtistGridSkeleton />
    if (searchingLabels) return <LabelGridSkeleton />
    if (searchingTracks) return <CenteredSpinner label={t('common.loading')} />
    return <AlbumGridSkeleton />
  }

  function results() {
    if (searchingArtists) {
      return <ArtistGrid artists={artistSearch.data ?? []} emptyTitle={t('home.noResults')} />
    }
    if (searchingLabels) {
      return <LabelGrid labels={labelSearch.data ?? []} emptyTitle={t('home.noResults')} />
    }
    if (searchingTracks) {
      return (
        <TrackResults
          tracks={trackSearch.data?.items ?? []}
          emptyTitle={t('home.noResults')}
          emptyHint={t('tracks.searchHint')}
          onRequestAlbum={requestByMbid}
          pendingId={pendingId}
        />
      )
    }
    return (
      <div className="space-y-6">
        <AlbumGrid
          albums={albums}
          onRequest={(album, isUpgrade) => request(album, isUpgrade)}
          pendingId={pendingId}
          emptyTitle={t('home.noResults')}
        />

        {search.hasNextPage && (
          <div className="flex justify-center">
            <Button onClick={() => void search.fetchNextPage()} loading={search.isFetchingNextPage}>
              {t('common.loadMore')}
            </Button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <header className="space-y-5">
        <div>
          <h1 className="font-display text-3xl font-bold text-ink-100">{t('home.title')}</h1>
          <p className="mt-1 text-sm text-ink-400">{t('home.subtitle')}</p>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-ink-500" />
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={placeholder}
            autoFocus
            className="field h-14 rounded-2xl pl-12 text-base"
          />
        </div>

        <Tabs
          active={type}
          onChange={setType}
          tabs={[
            { id: '', label: t('home.typeAll') },
            { id: 'album', label: t('home.typeAlbum') },
            { id: 'ep', label: t('home.typeEp') },
            { id: 'single', label: t('home.typeSingle') },
            { id: ARTIST_TAB, label: t('home.typeArtist') },
            { id: TRACK_TAB, label: t('home.typeTrack') },
            { id: LABEL_TAB, label: t('home.typeLabel') },
          ]}
        />
      </header>

      {query.length < 2 ? (
        <div className="space-y-8">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label={t('home.albums')}
              value={stats?.library_albums ?? '—'}
              hint={`${stats?.library_lossless ?? 0} ${t('library.losslessShare')}`}
              icon={<Disc3 className="size-5" />}
            />
            <StatCard
              label={t('home.active')}
              value={stats?.requests_active ?? '—'}
              icon={<Activity className="size-5" />}
              tone="brand"
            />
            <StatCard
              label={t('home.pending')}
              value={stats?.requests_pending ?? '—'}
              icon={<Clock className="size-5" />}
              tone="muted"
            />
            <StatCard
              label={t('home.failed')}
              value={stats?.requests_failed ?? '—'}
              icon={<TriangleAlert className="size-5" />}
              tone="accent"
            />
          </div>

          <EmptyState
            icon={<Search className="size-10" />}
            title={t('home.empty')}
            hint={t('home.emptyHint')}
            action={
              <Button variant="primary" onClick={() => navigate('/discover')}>
                {t('discover.title')}
              </Button>
            }
          />

          {user?.can_import && <LocalImportCard />}
        </div>
      ) : loading ? (
        skeleton()
      ) : (
        results()
      )}
    </div>
  )
}
