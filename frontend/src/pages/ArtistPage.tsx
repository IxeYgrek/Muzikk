import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Star, UserRound } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'

import { AlbumGrid, AlbumGridSkeleton } from '../components/AlbumCard'
import { useToast } from '../components/Toast'
import { Button, Card, Chip } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { useAlbumRequest } from '../lib/hooks'
import type { ArtistDetail, WatchedArtist } from '../lib/types'

export function ArtistPage() {
  const { mbid = '' } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const { request, pendingId } = useAlbumRequest()

  const artistQuery = useQuery({
    queryKey: ['artist', mbid],
    queryFn: () => api<ArtistDetail>(`/artists/${mbid}`),
    enabled: Boolean(mbid),
  })

  const watchlistQuery = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => api<WatchedArtist[]>('/watchlist'),
  })

  const artist = artistQuery.data?.artist
  const watched = watchlistQuery.data?.find((row) => row.artist_mbid === mbid)

  const toggleFollow = useMutation({
    mutationFn: async () => {
      if (watched) {
        await api(`/watchlist/${watched.id}`, { method: 'DELETE' })
        return
      }
      await api('/watchlist', {
        method: 'POST',
        body: { artist_mbid: mbid, artist_name: artist?.name ?? '' },
      })
    },
    onSuccess: () => {
      notify(watched ? t('watchlist.unfollow') : t('album.followingArtist'), 'success')
      void queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    },
    onError: (error) =>
      notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error'),
  })

  return (
    <div className="space-y-8">
      <button type="button" onClick={() => navigate(-1)} className="btn btn-ghost btn-sm -ml-2">
        <ArrowLeft className="size-4" />
        {t('common.back')}
      </button>

      <Card className="flex flex-wrap items-center gap-5 p-5">
        <div className="grid size-20 shrink-0 place-items-center rounded-full bg-brand-600/15 text-brand-300">
          <UserRound className="size-9" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-3xl font-bold text-ink-100">
            {artist?.name ?? '…'}
          </h1>
          {artist?.disambiguation && (
            <p className="mt-0.5 text-sm text-ink-400">{artist.disambiguation}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {artist?.type && <Chip>{artist.type}</Chip>}
            {artist?.country && <Chip>{artist.country}</Chip>}
            {artist?.in_library && <Chip tone="success">{t('nav.library')}</Chip>}
            {artist?.genres.slice(0, 6).map((genre) => (
              <Chip key={genre}>{genre}</Chip>
            ))}
          </div>
        </div>
        <Button
          variant={watched ? 'secondary' : 'primary'}
          loading={toggleFollow.isPending}
          onClick={() => toggleFollow.mutate()}
        >
          <Star className={watched ? 'size-4 fill-current' : 'size-4'} />
          {watched ? t('watchlist.unfollow') : t('album.followArtist')}
        </Button>
      </Card>

      {artistQuery.isLoading ? (
        <AlbumGridSkeleton />
      ) : (
        <AlbumGrid
          albums={artistQuery.data?.release_groups ?? []}
          onRequest={(album, isUpgrade) => request(album, isUpgrade)}
          pendingId={pendingId}
          emptyTitle={t('home.noResults')}
        />
      )}
    </div>
  )
}
