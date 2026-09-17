import clsx from 'clsx'
import { ArrowUpCircle, BadgeCheck, Disc3, Download, EyeOff, Loader2, Play } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { imageUrl } from '../lib/api'
import { canRequestUpgrade, useAuth } from '../lib/auth'
import { usePlayer } from '../lib/player'
import type { AlbumCard as AlbumCardType } from '../lib/types'
import { StatusBadge } from './StatusBadge'
import { EmptyState } from './ui'

export function AlbumCover({
  url,
  alt,
  className,
  size = 500,
}: {
  url: string | null | undefined
  alt: string
  className?: string
  size?: number
}) {
  // Remembering which URL failed, rather than that one did, lets the same
  // component move on to another album without staying stuck on the fallback.
  // The grid asks for 500 px and the album page for 1200 px: if the small
  // one 404s, try the large one before giving up.
  const [failed, setFailed] = useState<string[]>([])
  const [useLarge, setUseLarge] = useState(false)
  const candidate = imageUrl(url, useLarge ? 1200 : size)
  const source = candidate && !failed.includes(candidate) ? candidate : undefined

  return (
    <div
      className={clsx(
        'relative overflow-hidden bg-ink-800/80',
        className,
      )}
    >
      {source ? (
        <img
          src={source}
          alt={alt}
          loading="lazy"
          decoding="async"
          onError={() => {
            if (source && size !== 1200 && !useLarge) {
              setUseLarge(true)
              return
            }
            if (source) setFailed((seen) => [...seen, source])
          }}
          className="size-full object-cover"
        />
      ) : (
        <div className="grid size-full place-items-center bg-gradient-to-br from-ink-700/70 to-ink-850">
          <Disc3 className="size-1/3 text-ink-600" />
        </div>
      )}
    </div>
  )
}

export function AlbumTile({
  album,
  onRequest,
  onDismiss,
  dismissLabel,
  badge,
  requesting = false,
}: {
  album: AlbumCardType
  onRequest?: (album: AlbumCardType, isUpgrade: boolean) => void
  /** Hide this album from the list it came from, the follow tab so far. */
  onDismiss?: (album: AlbumCardType) => void
  dismissLabel?: string
  badge?: ReactNode
  requesting?: boolean
}) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const player = usePlayer()
  const owned = album.ownership.status === 'owned'
  const probable = album.ownership.status === 'probable'
  const upgradable =
    Boolean(album.ownership.status) && album.ownership.upgradable && canRequestUpgrade(user)
  const busy = Boolean(album.request_status) && album.request_status !== 'failed'
  // Playable as soon as the album was matched in the library, even loosely:
  // the identifier is what the player needs, not a perfect ownership status.
  const playableId = album.ownership.jellyfin_id

  return (
    <div className="group relative flex flex-col">
      <Link
        to={`/albums/${album.release_group_mbid}`}
        className="relative block overflow-hidden rounded-2xl ring-1 ring-ink-600/40 transition-all duration-300 hover:ring-brand-500/60 hover:shadow-[var(--shadow-glow)]"
      >
        <AlbumCover
          url={
            album.ownership.jellyfin_id
              ? `/api/images/jellyfin/${album.ownership.jellyfin_id}`
              : album.cover_url
          }
          alt={`${album.artist} - ${album.title}`}
          className="aspect-square"
        />

        {(badge || onDismiss) && (
          <div className="absolute inset-x-0 top-0 flex items-start justify-between gap-2 p-2">
            {badge ?? <span />}
            {onDismiss && (
              <button
                type="button"
                onClick={(event) => {
                  event.preventDefault()
                  onDismiss(album)
                }}
                title={dismissLabel ?? t('album.ignore')}
                className="grid size-7 shrink-0 place-items-center rounded-full bg-ink-950/75 text-ink-200 opacity-0 transition-opacity hover:text-white group-hover:opacity-100 focus-visible:opacity-100"
              >
                <EyeOff className="size-3.5" />
              </button>
            )}
          </div>
        )}

        <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-ink-950/95 via-ink-950/35 to-transparent p-2.5 pt-10">
          <div className="flex flex-wrap gap-1">
            {owned && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-emerald-500/90 px-1.5 py-0.5 text-[0.65rem] font-semibold text-ink-950"
                title={t('album.owned')}
              >
                <BadgeCheck className="size-3" />
              </span>
            )}
            {probable && !owned && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-emerald-500/40 px-1.5 py-0.5 text-[0.65rem] font-semibold text-emerald-100"
                title={t('album.probable')}
              >
                <BadgeCheck className="size-3" />
              </span>
            )}
            {upgradable && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-amber-500/85 px-1.5 py-0.5 text-[0.65rem] font-semibold text-ink-950"
                title={t('album.upgradable')}
              >
                <ArrowUpCircle className="size-3" />
              </span>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            {onRequest && !owned && (
              <button
                type="button"
                onClick={(event) => {
                  event.preventDefault()
                  onRequest(album, false)
                }}
                disabled={busy || requesting}
                title={t('album.request')}
                className={clsx(
                  'grid size-8 shrink-0 place-items-center rounded-full transition-all',
                  busy
                    ? 'bg-ink-700/80 text-ink-300'
                    : 'gradient-surface text-white opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
                )}
              >
                {requesting ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Download className="size-4" />
                )}
              </button>
            )}

            {onRequest && upgradable && (
              <button
                type="button"
                onClick={(event) => {
                  event.preventDefault()
                  onRequest(album, true)
                }}
                disabled={busy || requesting}
                title={t('album.upgrade')}
                className="grid size-8 shrink-0 place-items-center rounded-full bg-amber-500 text-ink-950 opacity-0 transition-all group-hover:opacity-100 focus-visible:opacity-100"
              >
                <ArrowUpCircle className="size-4" />
              </button>
            )}

            {playableId && (
              <button
                type="button"
                onClick={(event) => {
                  event.preventDefault()
                  void player.playAlbum(playableId)
                }}
                title={t('player.playAlbum')}
                aria-label={t('player.playAlbum')}
                className="grid size-9 shrink-0 place-items-center rounded-full gradient-surface text-white shadow-lg opacity-0 transition-all hover:scale-105 group-hover:opacity-100 focus-visible:opacity-100"
              >
                <Play className="size-4" />
              </button>
            )}
          </div>
        </div>
      </Link>

      <div className="mt-2 min-w-0 px-0.5">
        <Link
          to={`/albums/${album.release_group_mbid}`}
          className="block truncate text-sm font-semibold text-ink-100 hover:text-brand-300"
          title={album.title}
        >
          {album.title}
        </Link>
        <div className="flex items-center gap-1.5 truncate text-xs text-ink-400">
          <span className="truncate" title={album.artist}>
            {album.artist || t('common.unknownArtist')}
          </span>
          {album.year && <span className="shrink-0 text-ink-500">· {album.year}</span>}
        </div>
        {album.request_status && (
          <div className="mt-1.5">
            <StatusBadge status={album.request_status} />
          </div>
        )}
      </div>
    </div>
  )
}

export function AlbumGrid({
  albums,
  onRequest,
  onDismiss,
  dismissLabel,
  badgeFor,
  pendingId,
  emptyTitle,
  emptyHint,
}: {
  albums: AlbumCardType[]
  onRequest?: (album: AlbumCardType, isUpgrade: boolean) => void
  onDismiss?: (album: AlbumCardType) => void
  dismissLabel?: string
  badgeFor?: (album: AlbumCardType) => ReactNode
  pendingId?: string | null
  emptyTitle?: string
  emptyHint?: string
}) {
  if (albums.length === 0 && emptyTitle) {
    return <EmptyState icon={<Disc3 className="size-10" />} title={emptyTitle} hint={emptyHint} />
  }

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
      {albums.map((album) => (
        <AlbumTile
          key={album.release_group_mbid}
          album={album}
          onRequest={onRequest}
          onDismiss={onDismiss}
          dismissLabel={dismissLabel}
          badge={badgeFor?.(album)}
          requesting={pendingId === album.release_group_mbid}
        />
      ))}
    </div>
  )
}

export function AlbumGridSkeleton({ count = 12 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index}>
          <div className="skeleton aspect-square rounded-2xl" />
          <div className="skeleton mt-2 h-3.5 w-3/4 rounded" />
          <div className="skeleton mt-1.5 h-3 w-1/2 rounded" />
        </div>
      ))}
    </div>
  )
}
