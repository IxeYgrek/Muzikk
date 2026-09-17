import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Clock,
  Disc3,
  Heart,
  Library,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  Trash2,
  UserRound,
} from 'lucide-react'
import { type ComponentType, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { AlbumGrid } from '../components/AlbumCard'
import { useToast } from '../components/Toast'
import { Button, Card, CenteredSpinner, EmptyState, SectionTitle, Tabs } from '../components/ui'
import { currentLocale } from '../i18n'
import { ApiError, api } from '../lib/api'
import { relativeTime } from '../lib/format'
import { useAlbumRequest, useDebounced } from '../lib/hooks'
import type {
  Artist,
  WatchedArtist,
  WatchedRelease,
  WatchScope,
  WishlistItem,
} from '../lib/types'

/** Which albums of the followed artists the tab is showing. */
type Filter = 'all' | 'new' | 'ignored'

export function WatchlistPage() {
  const { t } = useTranslation()
  const locale = currentLocale()
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const { request, pendingId } = useAlbumRequest()
  const [text, setText] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [artist, setArtist] = useState<string | null>(null)
  const search = useDebounced(text.trim(), 400)

  const watched = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => api<WatchedArtist[]>('/watchlist'),
  })
  const releases = useQuery({
    queryKey: ['watchlist', 'releases', filter, artist],
    queryFn: () =>
      api<WatchedRelease[]>('/watchlist/releases', {
        query: {
          artist_mbid: artist ?? undefined,
          only_new: filter === 'new' ? true : undefined,
          ignored: filter === 'ignored' ? true : undefined,
        },
      }),
  })
  const wishlist = useQuery({
    queryKey: ['wishlist'],
    queryFn: () => api<WishlistItem[]>('/wishlist'),
  })
  const artists = useQuery({
    queryKey: ['artists', 'search', search],
    queryFn: () => api<Artist[]>('/artists/search', { query: { q: search, limit: 8 } }),
    enabled: search.length >= 2,
  })

  const fail = (error: unknown) =>
    notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error')

  const refreshWatchlist = () => {
    void queryClient.invalidateQueries({ queryKey: ['watchlist'] })
  }

  const follow = useMutation({
    mutationFn: (target: Artist) =>
      api('/watchlist', {
        method: 'POST',
        body: { artist_mbid: target.mbid, artist_name: target.name, scope: 'new' },
      }),
    onSuccess: () => {
      setText('')
      refreshWatchlist()
    },
    onError: fail,
  })

  const unfollow = useMutation({
    mutationFn: (id: number) => api(`/watchlist/${id}`, { method: 'DELETE' }),
    onSuccess: refreshWatchlist,
    onError: fail,
  })

  const setScope = useMutation({
    mutationFn: ({ id, scope }: { id: number; scope: WatchScope }) =>
      api(`/watchlist/${id}`, { method: 'PATCH', body: { scope } }),
    onSuccess: () => {
      notify(t('watchlist.scopeSaved'), 'success')
      refreshWatchlist()
    },
    onError: fail,
  })

  const ignore = useMutation({
    mutationFn: ({ id, ignored }: { id: number; ignored: boolean }) =>
      api(`/watchlist/releases/${id}`, { method: 'PATCH', query: { ignored } }),
    onSuccess: refreshWatchlist,
    onError: fail,
  })

  const removeWish = useMutation({
    mutationFn: (id: number) => api(`/wishlist/${id}`, { method: 'DELETE' }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['wishlist'] }),
    onError: fail,
  })

  const checkNow = useMutation({
    mutationFn: () => api('/watchlist/check', { method: 'POST' }),
    onSuccess: () => notify(t('watchlist.checkQueued'), 'success'),
    onError: fail,
  })

  const refreshWishes = useMutation({
    mutationFn: () => api('/wishlist/refresh', { method: 'POST' }),
    onSuccess: () => notify(t('watchlist.wishlistQueued'), 'success'),
    onError: fail,
  })

  const rows = watched.data ?? []
  const found = releases.data ?? []
  const byMbid = new Map(found.map((item) => [item.album.release_group_mbid, item]))

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-display text-3xl font-bold text-ink-100">{t('watchlist.title')}</h1>
        <p className="mt-1 text-sm text-ink-400">{t('watchlist.subtitle')}</p>
      </header>

      <section>
        <SectionTitle
          title={t('watchlist.missing')}
          icon={<Disc3 className="size-5" />}
          actions={
            <Button size="sm" onClick={() => checkNow.mutate()} loading={checkNow.isPending}>
              <RefreshCw className="size-3.5" />
              {t('watchlist.checkNow')}
            </Button>
          }
        />

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Tabs
            active={filter}
            onChange={(value) => setFilter(value as Filter)}
            tabs={[
              { id: 'all', label: t('watchlist.filter.all') },
              { id: 'new', label: t('watchlist.filter.new') },
              { id: 'ignored', label: t('watchlist.filter.ignored') },
            ]}
          />
          {rows.length > 1 && (
            <select
              className="field ml-auto w-auto min-w-48"
              value={artist ?? ''}
              onChange={(event) => setArtist(event.target.value || null)}
            >
              <option value="">{t('watchlist.allArtists')}</option>
              {rows.map((row) => (
                <option key={row.id} value={row.artist_mbid}>
                  {row.artist_name}
                </option>
              ))}
            </select>
          )}
        </div>

        {releases.isLoading ? (
          <CenteredSpinner />
        ) : (
          <AlbumGrid
            albums={found.map((item) => item.album)}
            onRequest={(album, isUpgrade) => request(album, isUpgrade)}
            pendingId={pendingId}
            onDismiss={(album) => {
              const row = byMbid.get(album.release_group_mbid)
              if (row) ignore.mutate({ id: row.id, ignored: !row.ignored })
            }}
            dismissLabel={filter === 'ignored' ? t('watchlist.restore') : t('album.ignore')}
            badgeFor={(album) => {
              const row = byMbid.get(album.release_group_mbid)
              // A single and an album look the same on a grid of sleeves, and
              // a follower deciding what to fetch cares which is which.
              const kind = album.primary_type && album.primary_type !== 'Album'
              return (
                <span className="flex flex-wrap gap-1">
                  {row?.is_new && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-500/90 px-1.5 py-0.5 text-[0.65rem] font-semibold text-white">
                      <Sparkles className="size-3" />
                      {t('watchlist.newRelease')}
                    </span>
                  )}
                  {kind && (
                    <span className="rounded-full bg-ink-950/70 px-1.5 py-0.5 text-[0.65rem] font-semibold text-ink-200">
                      {album.primary_type}
                    </span>
                  )}
                </span>
              )
            }}
            emptyTitle={
              filter === 'ignored' ? t('watchlist.noIgnored') : t('watchlist.nothingMissing')
            }
            emptyHint={filter === 'ignored' ? undefined : t('watchlist.nothingMissingHint')}
          />
        )}
      </section>

      <section>
        <SectionTitle title={t('watchlist.artists')} icon={<Star className="size-5" />} />

        <Card className="mb-4 p-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-500" />
            <input
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={t('watchlist.searchArtist')}
              className="field pl-9"
            />
          </div>

          {artists.data && artists.data.length > 0 && (
            <div className="mt-2 space-y-1">
              {artists.data.map((item) => (
                <div
                  key={item.mbid}
                  className="flex items-center gap-3 rounded-xl px-2.5 py-2 hover:bg-ink-700/30"
                >
                  <UserRound className="size-4 shrink-0 text-ink-500" />
                  <Link
                    to={`/artists/${item.mbid}`}
                    className="min-w-0 flex-1 truncate text-sm text-ink-100 hover:text-brand-300"
                  >
                    {item.name}
                    {item.disambiguation && (
                      <span className="ml-2 text-xs text-ink-500">{item.disambiguation}</span>
                    )}
                  </Link>
                  <Button
                    size="sm"
                    variant={item.watched ? 'ghost' : 'primary'}
                    disabled={item.watched || follow.isPending}
                    onClick={() => follow.mutate(item)}
                  >
                    <Star className="size-3.5" />
                    {item.watched ? t('album.followingArtist') : t('album.followArtist')}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Card>

        {rows.length === 0 ? (
          <EmptyState
            icon={<Star className="size-10" />}
            title={t('watchlist.empty')}
            hint={t('watchlist.emptyHint')}
          />
        ) : (
          <div className="grid gap-2 lg:grid-cols-2">
            {rows.map((row) => (
              <Card key={row.id} className="flex flex-wrap items-center gap-3 p-3">
                <div className="grid size-10 shrink-0 place-items-center rounded-full bg-brand-600/15 text-brand-300">
                  <UserRound className="size-5" />
                </div>
                <Link to={`/artists/${row.artist_mbid}`} className="min-w-32 flex-1">
                  <div className="truncate font-medium text-ink-100">{row.artist_name}</div>
                  <div className="hint truncate">
                    {t('watchlist.missingCount', { count: row.missing })} ·{' '}
                    {row.last_checked_at
                      ? relativeTime(row.last_checked_at, locale)
                      : t('common.never')}
                  </div>
                </Link>
                <ScopePicker
                  scope={row.scope}
                  busy={setScope.isPending}
                  onPick={(scope) => setScope.mutate({ id: row.id, scope })}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => unfollow.mutate(row.id)}
                  title={t('watchlist.unfollow')}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section>
        <SectionTitle
          title={t('watchlist.wishlist')}
          icon={<Heart className="size-5" />}
          actions={
            <Button
              size="sm"
              onClick={() => refreshWishes.mutate()}
              loading={refreshWishes.isPending}
            >
              <RefreshCw className="size-3.5" />
              {t('watchlist.wishlistRefresh')}
            </Button>
          }
        />

        {(wishlist.data ?? []).length === 0 ? (
          <EmptyState
            icon={<Heart className="size-10" />}
            title={t('watchlist.wishlistEmpty')}
            hint={t('watchlist.wishlistHint')}
          />
        ) : (
          <div className="space-y-2">
            {(wishlist.data ?? []).map((item) => (
              <Card key={item.id} className="flex flex-wrap items-center gap-3 p-3">
                <Link to={`/albums/${item.release_group_mbid}`} className="min-w-40 flex-1">
                  <div className="truncate font-semibold text-ink-100">{item.album_title}</div>
                  <div className="truncate text-sm text-ink-400">
                    {item.artist_name}
                    {item.year ? ` · ${item.year}` : ''}
                  </div>
                </Link>
                <Button
                  size="sm"
                  variant="primary"
                  loading={pendingId === item.release_group_mbid}
                  onClick={() => request({ release_group_mbid: item.release_group_mbid })}
                >
                  {t('album.request')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => removeWish.mutate(item.id)}>
                  <Trash2 className="size-3.5" />
                </Button>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

/** New releases only, or everything the library is missing. */
function ScopePicker({
  scope,
  busy,
  onPick,
}: {
  scope: WatchScope
  busy: boolean
  onPick: (scope: WatchScope) => void
}) {
  const { t } = useTranslation()

  type Icon = ComponentType<{ className?: string }>
  const options: { value: WatchScope; label: string; icon: Icon }[] = [
    { value: 'new', label: t('watchlist.scope.new'), icon: Clock },
    { value: 'missing', label: t('watchlist.scope.missing'), icon: Library },
  ]

  return (
    <div className="flex shrink-0 overflow-hidden rounded-xl border border-ink-600/50">
      {options.map((option) => {
        const Icon = option.icon
        const active = scope === option.value
        return (
          <button
            key={option.value}
            type="button"
            disabled={busy || active}
            onClick={() => onPick(option.value)}
            title={t(`watchlist.scopeHint.${option.value}`)}
            className={clsx(
              'flex items-center gap-1.5 px-2.5 py-1.5 text-xs transition-colors',
              active ? 'bg-brand-600/25 text-brand-200' : 'text-ink-400 hover:bg-ink-700/40',
            )}
          >
            <Icon className="size-3.5" />
            <span className="hidden sm:inline">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}
