import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

import { Layout } from './components/Layout'
import { LogoMark } from './components/Logo'
import { api } from './lib/api'
import { useAuth } from './lib/auth'
import type { Health } from './lib/types'
import { ActivityPage } from './pages/ActivityPage'
import { AdminPage } from './pages/AdminPage'
import { AlbumPage } from './pages/AlbumPage'
import { ArtistPage } from './pages/ArtistPage'
import { DiscoverPage } from './pages/DiscoverPage'
import { HomePage } from './pages/HomePage'
import { LabelPage } from './pages/LabelPage'
import { LibraryAlbumPage } from './pages/LibraryAlbumPage'
import { LibraryPage } from './pages/LibraryPage'
import { LoginPage } from './pages/LoginPage'
import { MetadataPage } from './pages/MetadataPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { PlaylistsPage } from './pages/PlaylistsPage'
import { RequestsPage } from './pages/RequestsPage'
import { SetupPage } from './pages/SetupPage'
import { WatchlistPage } from './pages/WatchlistPage'

function Splash() {
  return (
    <div className="grid min-h-screen place-items-center bg-ink-950">
      <LogoMark className="size-16 animate-pulse" />
    </div>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth()
  const location = useLocation()

  if (!ready) return <Splash />
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  return <>{children}</>
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (!user?.is_admin) return <Navigate to="/" replace />
  return <>{children}</>
}

export function App() {
  const location = useLocation()

  const { data: health, isLoading } = useQuery({
    queryKey: ['health'],
    queryFn: () => api<Health>('/health'),
    staleTime: 60_000,
  })

  if (isLoading) return <Splash />

  if (health?.setup_required && location.pathname !== '/setup') {
    return <Navigate to="/setup" replace />
  }

  return (
    <Routes>
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />
        <Route path="albums/:mbid" element={<AlbumPage />} />
        <Route path="artists/:mbid" element={<ArtistPage />} />
        <Route path="labels/:mbid" element={<LabelPage />} />
        <Route path="library" element={<LibraryPage />} />
        <Route path="library/albums/:jellyfinId" element={<LibraryAlbumPage />} />
        <Route path="playlists" element={<PlaylistsPage />} />
        <Route path="discover" element={<DiscoverPage />} />
        <Route path="requests" element={<RequestsPage />} />
        <Route path="requests/:id" element={<RequestsPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="watchlist" element={<WatchlistPage />} />
        <Route
          path="metadata"
          element={
            <RequireAdmin>
              <MetadataPage />
            </RequireAdmin>
          }
        />
        <Route
          path="admin"
          element={
            <RequireAdmin>
              <AdminPage />
            </RequireAdmin>
          }
        />
        <Route
          path="admin/:section"
          element={
            <RequireAdmin>
              <AdminPage />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
