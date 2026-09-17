import { useInfiniteQuery } from '@tanstack/react-query'
import { ArrowLeft, Tag } from 'lucide-react'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'

import { AlbumGrid, AlbumGridSkeleton } from '../components/AlbumCard'
import { Button, Card, Chip } from '../components/ui'
import { api } from '../lib/api'
import { useAlbumRequest } from '../lib/hooks'
import type { AlbumCard as AlbumCardType, LabelDetail } from '../lib/types'

const PAGE_SIZE = 100

export function LabelPage() {
  const { mbid = '' } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { request, pendingId } = useAlbumRequest()

  const catalogue = useInfiniteQuery({
    queryKey: ['label', mbid],
    enabled: Boolean(mbid),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<LabelDetail>(`/labels/${mbid}`, { query: { limit: PAGE_SIZE, offset: pageParam } }),
    getNextPageParam: (lastPage) => {
      const next = lastPage.offset + PAGE_SIZE
      return next < lastPage.count ? next : undefined
    },
  })

  const label = catalogue.data?.pages[0]?.label
  const editions = catalogue.data?.pages[0]?.count ?? 0

  // Pagination walks editions, so the same album can come back on a later page.
  const albums = useMemo(() => {
    const seen = new Map<string, AlbumCardType>()
    for (const page of catalogue.data?.pages ?? []) {
      for (const album of page.release_groups) {
        if (!seen.has(album.release_group_mbid)) seen.set(album.release_group_mbid, album)
      }
    }
    return [...seen.values()]
  }, [catalogue.data])

  const subtitle = [label?.disambiguation, label?.area || label?.country].filter(Boolean).join(' · ')

  return (
    <div className="space-y-8">
      <button type="button" onClick={() => navigate(-1)} className="btn btn-ghost btn-sm -ml-2">
        <ArrowLeft className="size-4" />
        {t('common.back')}
      </button>

      <Card className="flex flex-wrap items-center gap-5 p-5">
        <div className="grid size-20 shrink-0 place-items-center rounded-2xl bg-brand-600/15 text-brand-300">
          <Tag className="size-9" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-3xl font-bold text-ink-100">{label?.name ?? '…'}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-ink-400">{subtitle}</p>}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {label?.type && <Chip>{label.type}</Chip>}
            {label?.label_code && <Chip>{`LC ${label.label_code}`}</Chip>}
            {editions > 0 && <Chip tone="muted">{t('label.editions', { count: editions })}</Chip>}
            {label?.genres.slice(0, 6).map((genre) => (
              <Chip key={genre}>{genre}</Chip>
            ))}
          </div>
        </div>
      </Card>

      {catalogue.isLoading ? (
        <AlbumGridSkeleton />
      ) : (
        <div className="space-y-6">
          <AlbumGrid
            albums={albums}
            onRequest={(album, isUpgrade) => request(album, isUpgrade)}
            pendingId={pendingId}
            emptyTitle={t('label.noAlbums')}
          />

          {catalogue.hasNextPage && (
            <div className="flex justify-center">
              <Button
                onClick={() => void catalogue.fetchNextPage()}
                loading={catalogue.isFetchingNextPage}
              >
                {t('common.loadMore')}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
