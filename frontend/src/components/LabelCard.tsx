import { Tag } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { Label } from '../lib/types'
import { EmptyState } from './ui'

export function LabelTile({ label }: { label: Label }) {
  const subtitle = [label.disambiguation, label.type, label.area || label.country]
    .filter(Boolean)
    .join(' · ')

  return (
    <Link
      to={`/labels/${label.mbid}`}
      className="glass flex items-center gap-4 rounded-2xl p-4 transition-all duration-300 hover:ring-1 hover:ring-brand-500/60 hover:shadow-[var(--shadow-glow)]"
    >
      <div className="grid size-14 shrink-0 place-items-center rounded-2xl bg-brand-600/15 text-brand-300">
        <Tag className="size-6" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate font-semibold text-ink-100" title={label.name}>
            {label.name}
          </span>
          {label.label_code && (
            <span className="shrink-0 text-xs text-ink-500">LC {label.label_code}</span>
          )}
        </div>
        {subtitle && <p className="truncate text-xs text-ink-400">{subtitle}</p>}
        {label.genres.length > 0 && (
          <p className="mt-1 truncate text-xs text-ink-500">{label.genres.slice(0, 4).join(', ')}</p>
        )}
      </div>
    </Link>
  )
}

export function LabelGrid({ labels, emptyTitle }: { labels: Label[]; emptyTitle?: string }) {
  if (labels.length === 0 && emptyTitle) {
    return <EmptyState icon={<Tag className="size-10" />} title={emptyTitle} />
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {labels.map((label) => (
        <LabelTile key={label.mbid} label={label} />
      ))}
    </div>
  )
}

export function LabelGridSkeleton({ count = 9 }: { count?: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="skeleton h-[5.5rem] rounded-2xl" />
      ))}
    </div>
  )
}
