import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Activity,
  Disc3,
  Compass,
  Inbox,
  Languages,
  ListMusic,
  LogOut,
  Menu,
  Search,
  Settings,
  Star,
  Tags,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { currentLanguage, setLanguage } from '../i18n'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { usePlayer } from '../lib/player'
import type { Stats } from '../lib/types'
import { Logo } from './Logo'
import { Player } from './Player'

type NavItem = {
  to: string
  label: string
  icon: ReactNode
  adminOnly?: boolean
  badge?: number
}

export function Layout() {
  const { t } = useTranslation()
  const { user, signOut } = useAuth()
  const location = useLocation()
  const player = usePlayer()
  const [open, setOpen] = useState(false)

  const { data: stats } = useQuery({
    queryKey: ['activity', 'stats'],
    queryFn: () => api<Stats>('/activity/stats'),
    refetchInterval: 30_000,
  })

  useEffect(() => setOpen(false), [location.pathname])

  const items: NavItem[] = [
    { to: '/', label: t('nav.home'), icon: <Search className="size-[18px]" /> },
    { to: '/library', label: t('nav.library'), icon: <Disc3 className="size-[18px]" /> },
    { to: '/playlists', label: t('nav.playlists'), icon: <ListMusic className="size-[18px]" /> },
    { to: '/discover', label: t('nav.discover'), icon: <Compass className="size-[18px]" /> },
    {
      to: '/requests',
      label: t('nav.requests'),
      icon: <Inbox className="size-[18px]" />,
      badge:
        (stats?.requests_to_validate ?? 0) + (user?.is_admin ? (stats?.requests_pending ?? 0) : 0),
    },
    {
      to: '/activity',
      label: t('nav.activity'),
      icon: <Activity className="size-[18px]" />,
      badge: stats?.requests_active,
    },
    {
      to: '/watchlist',
      label: t('nav.watchlist'),
      icon: <Star className="size-[18px]" />,
      badge: stats?.watchlist_missing,
    },
    {
      to: '/metadata',
      label: t('nav.metadata'),
      icon: <Tags className="size-[18px]" />,
      adminOnly: true,
    },
    {
      to: '/admin',
      label: t('nav.admin'),
      icon: <Settings className="size-[18px]" />,
      adminOnly: true,
    },
  ].filter((item) => !item.adminOnly || user?.is_admin)

  const language = currentLanguage()

  const nav = (
    <nav className="flex flex-1 flex-col gap-1 px-3">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          className={({ isActive }) =>
            clsx(
              'group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all',
              isActive
                ? 'bg-brand-600/20 text-ink-50 shadow-[inset_0_0_0_1px_rgba(139,92,246,0.35)]'
                : 'text-ink-400 hover:bg-ink-700/40 hover:text-ink-100',
            )
          }
        >
          {item.icon}
          <span className="flex-1 truncate">{item.label}</span>
          {Boolean(item.badge) && (
            <span className="rounded-full bg-accent-600 px-1.5 py-0.5 text-[0.65rem] font-bold text-white">
              {item.badge}
            </span>
          )}
        </NavLink>
      ))}
    </nav>
  )

  const footer = (
    <div className="space-y-3 border-t border-ink-700/60 p-3">
      <div className="flex items-center gap-1 rounded-xl bg-ink-800/60 p-1">
        <Languages className="ml-1.5 size-3.5 shrink-0 text-ink-500" />
        {(['fr', 'en'] as const).map((code) => (
          <button
            key={code}
            type="button"
            onClick={() => setLanguage(code)}
            className={clsx(
              'flex-1 rounded-lg px-2 py-1 text-xs font-semibold uppercase transition-colors',
              language === code ? 'bg-brand-600/30 text-ink-50' : 'text-ink-400 hover:text-ink-100',
            )}
          >
            {code}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2.5 px-1">
        <div className="grid size-9 shrink-0 place-items-center rounded-full gradient-surface text-sm font-bold text-white">
          {(user?.name ?? '?').slice(0, 1).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink-100">{user?.name}</div>
          {user?.is_admin && (
            <div className="text-[0.68rem] uppercase tracking-wide text-brand-300">
              {t('admin.userAdmin')}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={signOut}
          title={t('nav.logout')}
          className="rounded-lg p-2 text-ink-400 transition-colors hover:bg-ink-700/50 hover:text-accent-300"
        >
          <LogOut className="size-4" />
        </button>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-ink-950">
      <div className="pointer-events-none fixed inset-0 -z-10 opacity-70">
        <div className="absolute -left-40 -top-40 size-[32rem] rounded-full bg-brand-600/20 blur-[140px]" />
        <div className="absolute -bottom-52 right-0 size-[28rem] rounded-full bg-accent-600/15 blur-[150px]" />
      </div>

      {/* desktop rail */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-ink-700/50 bg-ink-900/60 backdrop-blur-xl lg:flex">
        <div className="px-5 py-6">
          <NavLink to="/">
            <Logo />
          </NavLink>
        </div>
        {nav}
        {footer}
      </aside>

      {/* mobile header */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-ink-700/50 bg-ink-900/80 px-4 py-3 backdrop-blur-xl lg:hidden">
        <NavLink to="/">
          <Logo size="sm" />
        </NavLink>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-lg p-2 text-ink-300 hover:bg-ink-700/50"
          aria-label={t('nav.menu')}
        >
          <Menu className="size-5" />
        </button>
      </header>

      {/* mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-ink-950/80 backdrop-blur-sm"
            onClick={() => setOpen(false)}
            role="presentation"
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col border-r border-ink-700/50 bg-ink-900">
            <div className="flex items-center justify-between px-5 py-5">
              <Logo size="sm" />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-lg p-2 text-ink-400 hover:bg-ink-700/50"
                aria-label={t('common.close')}
              >
                <X className="size-4" />
              </button>
            </div>
            {nav}
            {footer}
          </aside>
        </div>
      )}

      <main className="lg:pl-64">
        {/* Bottom padding keeps the last row reachable above the player bar. */}
        <div
          className={clsx(
            'mx-auto w-full max-w-[100rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8',
            player.current && 'pb-28 lg:pb-28',
          )}
        >
          <Outlet />
        </div>
      </main>

      <Player />
    </div>
  )
}
