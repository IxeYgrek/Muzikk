import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  Download,
  FileAudio,
  ScanSearch,
  Search,
  Sparkles,
  Tags,
  XCircle,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ReactNode } from 'react'

import { Chip } from './ui'
import type { RequestStatus } from '../lib/types'

type Tone = 'brand' | 'success' | 'warning' | 'danger' | 'muted'

const MAP: Record<string, { tone: Tone; icon: ReactNode }> = {
  pending: { tone: 'warning', icon: <Clock className="size-3" /> },
  approved: { tone: 'brand', icon: <Clock className="size-3" /> },
  searching: { tone: 'brand', icon: <Search className="size-3" /> },
  matched: { tone: 'brand', icon: <Sparkles className="size-3" /> },
  downloading: { tone: 'brand', icon: <Download className="size-3" /> },
  verifying: { tone: 'brand', icon: <FileAudio className="size-3" /> },
  tagging: { tone: 'brand', icon: <Tags className="size-3" /> },
  importing: { tone: 'brand', icon: <Tags className="size-3" /> },
  awaiting_validation: { tone: 'warning', icon: <ScanSearch className="size-3" /> },
  imported: { tone: 'success', icon: <CheckCircle2 className="size-3" /> },
  failed: { tone: 'danger', icon: <AlertTriangle className="size-3" /> },
  rejected: { tone: 'danger', icon: <XCircle className="size-3" /> },
  cancelled: { tone: 'muted', icon: <Ban className="size-3" /> },
}

export function StatusBadge({
  status,
  className,
}: {
  status: RequestStatus | string
  className?: string
}) {
  const { t } = useTranslation()
  const config = MAP[status] ?? { tone: 'muted' as Tone, icon: null }
  return (
    <Chip tone={config.tone} className={className}>
      {config.icon}
      {t(`status.${status}`, status)}
    </Chip>
  )
}

export const ACTIVE_STATUSES = new Set([
  'searching',
  'matched',
  'downloading',
  'verifying',
  'tagging',
  'importing',
])

/** Stages with no percentage to report: the bar must not pretend otherwise. */
export const INDETERMINATE_STATUSES = new Set(['pending', 'approved', 'searching', 'matched'])
