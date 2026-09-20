import clsx from 'clsx'
import {
  Database,
  Download,
  Headphones,
  Image,
  Layers,
  ListOrdered,
  Music4,
  Radar,
  ScanSearch,
  Server,
  Settings,
  SlidersHorizontal,
  Tags,
  Users,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'

import {
  IndexersPanel,
  JellyfinPanel,
  NamingPanel,
  ProvidersPanel,
  SystemPanel,
  UsersPanel,
} from '../components/admin/panels'
import { SettingsPanel } from '../components/admin/SettingsForm'
import { useLocalMode } from '../lib/hooks'

type SectionId =
  | 'general'
  | 'jellyfin'
  | 'musicbrainz'
  | 'coverart'
  | 'slskd'
  | 'prowlarr'
  | 'indexers'
  | 'qbittorrent'
  | 'quality'
  | 'naming'
  | 'metadata'
  | 'player'
  | 'providers'
  | 'users'
  | 'system'

const SECTIONS: { id: SectionId; icon: ReactNode }[] = [
  { id: 'general', icon: <Settings className="size-4" /> },
  { id: 'jellyfin', icon: <Server className="size-4" /> },
  { id: 'musicbrainz', icon: <Database className="size-4" /> },
  { id: 'coverart', icon: <Image className="size-4" /> },
  { id: 'slskd', icon: <Music4 className="size-4" /> },
  { id: 'prowlarr', icon: <Radar className="size-4" /> },
  { id: 'indexers', icon: <Layers className="size-4" /> },
  { id: 'qbittorrent', icon: <Download className="size-4" /> },
  { id: 'quality', icon: <SlidersHorizontal className="size-4" /> },
  { id: 'naming', icon: <Tags className="size-4" /> },
  { id: 'metadata', icon: <ScanSearch className="size-4" /> },
  { id: 'player', icon: <Headphones className="size-4" /> },
  { id: 'providers', icon: <ListOrdered className="size-4" /> },
  { id: 'users', icon: <Users className="size-4" /> },
  { id: 'system', icon: <Server className="size-4" /> },
]

function panelFor(section: SectionId) {
  switch (section) {
    case 'jellyfin':
      return <JellyfinPanel />
    case 'indexers':
      return <IndexersPanel />
    case 'providers':
      return <ProvidersPanel />
    case 'naming':
      return <NamingPanel />
    case 'users':
      return <UsersPanel />
    case 'system':
      return <SystemPanel />
    case 'musicbrainz':
      return <SettingsPanel section="musicbrainz" testService="musicbrainz" />
    case 'coverart':
      return <SettingsPanel section="coverart" testService="coverart" />
    case 'slskd':
      return <SettingsPanel section="slskd" testService="slskd" />
    case 'prowlarr':
      return <SettingsPanel section="prowlarr" testService="prowlarr" />
    case 'qbittorrent':
      return <SettingsPanel section="qbittorrent" testService="qbittorrent" />
    default:
      return <SettingsPanel section={section} />
  }
}

export function AdminPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { section } = useParams()
  const localMode = useLocalMode()

  // Nothing to configure about a server this installation was never built on.
  const sections = SECTIONS.filter((item) => item.id !== 'jellyfin' || !localMode)
  const active = (sections.find((item) => item.id === section)?.id ?? 'general') as SectionId

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold text-ink-100">{t('admin.title')}</h1>
        <p className="mt-1 text-sm text-ink-400">{t('admin.subtitle')}</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[15rem_1fr]">
        <nav className="flex gap-1.5 overflow-x-auto pb-2 lg:flex-col lg:overflow-visible lg:pb-0">
          {sections.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => navigate(item.id === 'general' ? '/admin' : `/admin/${item.id}`)}
              className={clsx(
                'flex shrink-0 items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors',
                active === item.id
                  ? 'bg-brand-600/20 text-ink-50 shadow-[inset_0_0_0_1px_rgba(139,92,246,0.35)]'
                  : 'text-ink-400 hover:bg-ink-700/40 hover:text-ink-100',
              )}
            >
              {item.icon}
              {t(`admin.sections.${item.id}`)}
            </button>
          ))}
        </nav>

        {/* The key forces a remount: without it React reuses the panel instance
            across sections and the previous section's values leak into the next. */}
        <div key={active} className="min-w-0">
          {panelFor(active)}
        </div>
      </div>
    </div>
  )
}
