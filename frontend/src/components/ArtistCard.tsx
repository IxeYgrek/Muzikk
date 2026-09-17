import { BadgeCheck, Star, UserRound } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { Artist } from '../lib/types'
import { EmptyState } from './ui'

export function ArtistTile({ artist }: { artist: Artist }) {
  const { t } = useTranslation()
  const subtitle = [artist.disambiguation, artist.type, artist.country].filter(Boolean).join(' · ')

  return (
    <Link
      to={`/artists/${artist.mbid}`}
      className="glass flex items-center gap-4 rounded-2xl p-4 transition-all duration-300 hover:ring-1 hover:ring-brand-500/60 hover:shadow-[var(--shadow-glow)]"
    >
      <div className="grid size-14 shrink-0 place-items-center rounded-full bg-brand-600/15 text-brand-300">
        <UserRound className="size-7" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate font-semibold text-ink-100" title={artist.name}>
            {artist.name}
          </span>
          {artist.in_library && (
            <BadgeCheck className="size-4 shrink-0 text-emerald-400" aria-label={t('nav.library')} />
          )}
          {artist.watched && (
            <Star
              className="size-4 shrink-0 fill-current text-amber-400"
              aria-label={t('album.followingArtist')}
            />
          )}
        </div>
        {subtitle && <p className="truncate text-xs text-ink-400">{subtitle}</p>}
        {artist.genres.length > 0 && (
          <p className="mt-1 truncate text-xs text-ink-500">{artist.genres.slice(0, 4).join(', ')}</p>
        )}
      </div>
    </Link>
  )
}

export function ArtistGrid({ artists, emptyTitle }: { artists: Artist[]; emptyTitle?: string }) {
  if (artists.length === 0 && emptyTitle) {
    return <EmptyState icon={<UserRound className="size-10" />} title={emptyTitle} />
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {artists.map((artist) => (
        <ArtistTile key={artist.mbid} artist={artist} />
      ))}
    </div>
  )
}

export function ArtistGridSkeleton({ count = 9 }: { count?: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="skeleton h-[5.5rem] rounded-2xl" />
      ))}
    </div>
  )
}
