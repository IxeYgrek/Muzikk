import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { RefreshCw, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { AlbumGrid, AlbumGridSkeleton } from '../components/AlbumCard'
import { ArtistGrid } from '../components/ArtistCard'
import { Button, Card, Select, Tabs } from '../components/ui'
import { api } from '../lib/api'
import { useAlbumRequest } from '../lib/hooks'
import type { AlbumCard, RecommendationResponse, SearchResponse } from '../lib/types'

/** Where the suggestions came from, spelled out for the listener. */
function SourceNote({ data }: { data: RecommendationResponse }) {
  const { t } = useTranslation()
  const services = data.sources.filter((name) => name !== 'library')

  return (
    <Card className="flex items-start gap-2.5 p-3.5 text-sm text-ink-300">
      <Sparkles className="mt-0.5 size-4 shrink-0 text-brand-300" />
      <div className="space-y-1">
        {services.length > 0 ? (
          <p>
            {t('discover.forYouFrom', {
              services: services
                .map((name) => (name === 'lastfm' ? 'Last.fm' : 'ListenBrainz'))
                .join(' · '),
            })}
          </p>
        ) : (
          <p>
            {t('discover.forYouFromLibrary')}{' '}
            <Link to="/account" className="text-brand-300 hover:underline">
              {t('discover.forYouConnect')}
            </Link>
          </p>
        )}
        {data.seeds.length > 0 && (
          <p className="hint">{t('discover.forYouArtists', { artists: data.seeds.join(', ') })}</p>
        )}
      </div>
    </Card>
  )
}

export function DiscoverPage() {
  const { t } = useTranslation()
  const { request, pendingId } = useAlbumRequest()
  const [tab, setTab] = useState('new')
  const [months, setMonths] = useState(3)
  const [genre, setGenre] = useState('')
  const [seed, setSeed] = useState(0)

  const genres = useQuery({
    queryKey: ['discover', 'genres'],
    queryFn: () => api<string[]>('/discover/genres'),
    staleTime: 10 * 60_000,
  })

  const newReleases = useQuery({
    queryKey: ['discover', 'new', months],
    queryFn: () =>
      api<SearchResponse>('/discover/new-releases', { query: { months, limit: 48 } }),
    enabled: tab === 'new',
  })

  const byGenre = useQuery({
    queryKey: ['discover', 'genre', genre],
    queryFn: () => api<SearchResponse>(`/discover/genre/${encodeURIComponent(genre)}`, {
      query: { limit: 48 },
    }),
    enabled: tab === 'genre' && Boolean(genre),
  })

  const missing = useQuery({
    queryKey: ['discover', 'missing', seed],
    queryFn: () => api<AlbumCard[]>('/discover/missing', { query: { artists: 5, seed } }),
    enabled: tab === 'missing',
    staleTime: 0,
  })

  // Built from external services, so it is slow enough to be worth keeping.
  const forYou = useQuery({
    queryKey: ['discover', 'for-you'],
    queryFn: () => api<RecommendationResponse>('/discover/for-you'),
    enabled: tab === 'forYou',
    staleTime: 15 * 60_000,
  })

  const loading =
    (tab === 'new' && newReleases.isLoading) ||
    (tab === 'genre' && byGenre.isLoading) ||
    (tab === 'missing' && missing.isFetching) ||
    (tab === 'forYou' && forYou.isLoading)

  const albums =
    tab === 'new'
      ? (newReleases.data?.items ?? [])
      : tab === 'genre'
        ? (byGenre.data?.items ?? [])
        : tab === 'forYou'
          ? (forYou.data?.items ?? [])
          : (missing.data ?? [])

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold text-ink-100">{t('discover.title')}</h1>
        <p className="mt-1 text-sm text-ink-400">{t('discover.subtitle')}</p>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          active={tab}
          onChange={setTab}
          tabs={[
            { id: 'forYou', label: t('discover.forYou') },
            { id: 'new', label: t('discover.newReleases') },
            { id: 'genre', label: t('discover.byGenre') },
            { id: 'missing', label: t('discover.missing') },
          ]}
        />

        {tab === 'new' && (
          <Select
            value={months}
            onChange={(event) => setMonths(Number(event.target.value))}
            className="w-auto"
          >
            {[1, 3, 6, 12].map((value) => (
              <option key={value} value={value}>
                {t('discover.months', { count: value })}
              </option>
            ))}
          </Select>
        )}

        {tab === 'missing' && (
          <Button size="sm" onClick={() => setSeed((value) => value + 1)}>
            <RefreshCw className={clsx('size-3.5', missing.isFetching && 'animate-spin')} />
            {t('discover.shuffle')}
          </Button>
        )}

        {tab === 'forYou' && (
          <Button size="sm" onClick={() => void forYou.refetch()}>
            <RefreshCw className={clsx('size-3.5', forYou.isFetching && 'animate-spin')} />
            {t('common.refresh')}
          </Button>
        )}
      </div>

      {tab === 'genre' && (
        <div className="flex flex-wrap gap-1.5">
          {(genres.data ?? []).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setGenre(value)}
              className={clsx('btn btn-sm', genre === value ? 'btn-primary' : 'btn-secondary')}
            >
              {value}
            </button>
          ))}
        </div>
      )}

      {tab === 'missing' && (
        <Card className="flex items-start gap-2.5 p-3.5 text-sm text-ink-300">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-brand-300" />
          {t('discover.missingDesc')}
        </Card>
      )}

      {tab === 'forYou' && forYou.data && <SourceNote data={forYou.data} />}

      {tab === 'forYou' && (forYou.data?.artists.length ?? 0) > 0 && (
        <section className="space-y-3">
          <h2 className="font-display text-lg text-ink-100">{t('discover.forYouArtistsTitle')}</h2>
          <ArtistGrid artists={forYou.data?.artists ?? []} />
        </section>
      )}

      {tab === 'forYou' && (forYou.data?.items.length ?? 0) > 0 && (
        <h2 className="font-display text-lg text-ink-100">{t('discover.forYouAlbumsTitle')}</h2>
      )}

      {loading ? (
        <AlbumGridSkeleton count={18} />
      ) : (
        <AlbumGrid
          albums={albums}
          onRequest={(album, isUpgrade) => request(album, isUpgrade)}
          pendingId={pendingId}
          emptyTitle={t('home.noResults')}
        />
      )}
    </div>
  )
}
