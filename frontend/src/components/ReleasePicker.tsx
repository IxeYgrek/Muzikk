import clsx from 'clsx'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { ReleaseSummary } from '../lib/types'
import { Chip } from './ui'

export function ReleasePicker({
  releases,
  selectedMbid,
  onSelect,
  catalogueHref,
}: {
  releases: ReleaseSummary[]
  selectedMbid?: string | null
  onSelect?: (mbid: string) => void
  /** When set, each edition is a link to the catalogue page for that release. */
  catalogueHref?: (mbid: string) => string
}) {
  const { t } = useTranslation()
  if (!releases.length) return null

  return (
    <div className="space-y-1.5">
      <p className="hint mb-2">{t('album.chooseEdition')}</p>
      {releases.map((release) => {
        const active = release.release_mbid === selectedMbid
        const className = clsx(
          'flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2 text-left text-sm transition-colors',
          active ? 'bg-brand-600/20 text-ink-100' : 'hover:bg-ink-700/40 text-ink-300',
        )
        const body = (
          <>
            <span className="min-w-0 flex-1 truncate font-medium">{release.title}</span>
            {release.date && <span className="text-xs text-ink-400">{release.date}</span>}
            {release.country && <span className="text-xs text-ink-500">{release.country}</span>}
            {release.formats.length > 0 && (
              <span className="text-xs text-ink-500">{release.formats.join('/')}</span>
            )}
            <span className="text-xs text-ink-500">
              {release.track_count} {t('common.tracks')}
            </span>
            {release.is_recommended && <Chip tone="brand">{t('album.recommended')}</Chip>}
          </>
        )
        if (catalogueHref) {
          return (
            <Link
              key={release.release_mbid}
              to={catalogueHref(release.release_mbid)}
              className={className}
            >
              {body}
            </Link>
          )
        }
        return (
          <button
            key={release.release_mbid}
            type="button"
            onClick={() => onSelect?.(release.release_mbid)}
            className={className}
          >
            {body}
          </button>
        )
      })}
    </div>
  )
}
