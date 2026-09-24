import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link2, RefreshCw, Sparkles, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { AlbumGrid } from './AlbumCard'
import { ArtistTile } from './ArtistCard'
import { Alert, Button, Card, Chip } from './ui'
import { api } from '../lib/api'
import { currentLocale } from '../i18n'
import type { RecommendationResponse, SuggestedAlbum, SuggestedArtist } from '../lib/types'

/** The artist a suggestion came from, shown on the card as its reason. */
function SeedBadge({ name }: { name: string }) {
  const { t } = useTranslation()
  if (!name) return null
  return (
    <span
      className="max-w-[85%] truncate rounded-full bg-ink-950/80 px-2 py-0.5 text-[0.65rem] font-medium text-ink-200"
      title={t('discover.similarTo', { artist: name })}
    >
      {t('discover.similarTo', { artist: name })}
    </span>
  )
}

function Section({
  title,
  hint,
  count,
  children,
}: {
  title: string
  hint?: string
  count: number
  children: ReactNode
}) {
  if (count === 0) return null
  return (
    <section className="space-y-3">
      <header className="flex flex-wrap items-baseline gap-x-3">
        <h2 className="font-display text-lg text-ink-100">{title}</h2>
        <Chip tone="muted">{count}</Chip>
        {hint && <p className="hint w-full sm:w-auto">{hint}</p>}
      </header>
      {children}
    </section>
  )
}

/**
 * Everything computed for one listener, on three shelves.
 *
 * The split follows the action rather than the taxonomy: an album already owned
 * gets played, one that is missing gets requested. Putting both in one grid is
 * what made the old page confusing, since half the cards behaved differently
 * from the other half.
 */
export function Suggestions({
  data,
  onRequest,
  pendingId,
}: {
  data: RecommendationResponse
  onRequest: (album: SuggestedAlbum, isUpgrade: boolean) => void
  pendingId?: string | null
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const hide = useMutation({
    mutationFn: (id: number) => api(`/discover/for-you/hide/${id}`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['discover', 'for-you'] }),
  })

  const refresh = useMutation({
    mutationFn: () => api('/discover/for-you/refresh', { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['discover', 'for-you'] }),
  })

  const services = data.sources.filter((name) => name !== 'library')
  const empty =
    data.items.length === 0 &&
    data.artists.length === 0 &&
    data.rediscover.length === 0 &&
    data.fresh.length === 0

  const badgeFor = (album: SuggestedAlbum) => <SeedBadge name={album.seed_name} />

  return (
    <div className="space-y-8">
      <Card className="flex flex-wrap items-start gap-3 p-3.5 text-sm text-ink-300">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-brand-300" />
        <div className="min-w-0 flex-1 space-y-1">
          {services.length > 0 ? (
            <p>
              {t('discover.forYouFrom', {
                services: services
                  .map((name) => (name === 'lastfm' ? 'Last.fm' : 'ListenBrainz'))
                  .join(' · '),
              })}
            </p>
          ) : data.available ? (
            <p>
              {t('discover.forYouFromLibrary')}{' '}
              <Link to="/account" className="text-brand-300 hover:underline">
                {t('discover.forYouConnect')}
              </Link>
            </p>
          ) : (
            <p>{t('discover.forYouUnavailable')}</p>
          )}
          {data.computed_at && (
            <p className="hint">
              {t('discover.computedAt', {
                when: new Date(data.computed_at).toLocaleString(currentLocale()),
              })}
            </p>
          )}
        </div>
        <Button size="sm" loading={refresh.isPending} onClick={() => refresh.mutate()}>
          <RefreshCw className={data.running ? 'size-3.5 animate-spin' : 'size-3.5'} />
          {t('common.refresh')}
        </Button>
      </Card>

      {data.running && <Alert tone="info">{t('discover.running')}</Alert>}

      {empty && !data.running && (
        <Alert tone="info">
          {data.connected ? t('discover.emptyConnected') : t('discover.emptyNotConnected')}
        </Alert>
      )}

      <Section
        title={t('discover.artistsTitle')}
        hint={t('discover.artistsHint')}
        count={data.artists.length}
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.artists.map((artist: SuggestedArtist) => (
            <div key={artist.mbid} className="space-y-1">
              <ArtistTile artist={artist} />
              {artist.seed_name && (
                <p className="hint flex items-center gap-1.5 pl-1">
                  <Link2 className="size-3" />
                  {t('discover.similarTo', { artist: artist.seed_name })}
                </p>
              )}
            </div>
          ))}
        </div>
      </Section>

      <Section
        title={t('discover.albumsTitle')}
        hint={t('discover.albumsHint')}
        count={data.items.length}
      >
        <AlbumGrid
          albums={data.items}
          onRequest={(album, isUpgrade) => onRequest(album as SuggestedAlbum, isUpgrade)}
          onDismiss={(album) => hide.mutate((album as SuggestedAlbum).id)}
          dismissLabel={t('discover.hide')}
          badgeFor={(album) => badgeFor(album as SuggestedAlbum)}
          pendingId={pendingId}
        />
      </Section>

      <Section
        title={t('discover.freshTitle')}
        hint={t('discover.freshHint')}
        count={data.fresh.length}
      >
        <AlbumGrid
          albums={data.fresh}
          onRequest={(album, isUpgrade) => onRequest(album as SuggestedAlbum, isUpgrade)}
          onDismiss={(album) => hide.mutate((album as SuggestedAlbum).id)}
          dismissLabel={t('discover.hide')}
          pendingId={pendingId}
        />
      </Section>

      <Section
        title={t('discover.rediscoverTitle')}
        hint={t('discover.rediscoverHint')}
        count={data.rediscover.length}
      >
        {/* No request button: these are already on the shelf. */}
        <AlbumGrid
          albums={data.rediscover}
          onDismiss={(album) => hide.mutate((album as SuggestedAlbum).id)}
          dismissLabel={t('discover.hide')}
        />
      </Section>

      {data.artists.length === 0 && data.items.length === 0 && data.rediscover.length > 0 && (
        <p className="hint flex items-center gap-1.5">
          <UserRound className="size-3.5" />
          {t('discover.onlyRediscover')}
        </p>
      )}
    </div>
  )
}
