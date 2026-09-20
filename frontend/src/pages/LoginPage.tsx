import { useQuery } from '@tanstack/react-query'
import { Server } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { LanguageSwitch } from '../components/LanguageSwitch'
import { Logo } from '../components/Logo'
import { Alert, Button, Card, Field, Input } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { Mode } from '../lib/types'

type ServerInfo = {
  mode: Mode
  jellyfin_configured: boolean
  jellyfin_server_name: string | null
}

export function LoginPage() {
  const { t } = useTranslation()
  const { user, ready, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const { data: server } = useQuery({
    queryKey: ['auth', 'server'],
    queryFn: () => api<ServerInfo>('/auth/server'),
    staleTime: 5 * 60_000,
  })

  if (ready && user) {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from && from !== '/login' ? from : '/'} replace />
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await signIn(username.trim(), password)
      navigate('/', { replace: true })
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('errors.generic'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Logo size="lg" showWordmark={false} />
          <h1 className="font-display text-4xl font-bold gradient-text">Muzikk</h1>
          <p className="text-sm text-ink-400">{t('common.tagline')}</p>
          <LanguageSwitch className="mt-1 w-40" />
        </div>

        <Card className="p-6">
          <h2 className="font-display text-xl text-ink-100">{t('auth.title')}</h2>
          <p className="mt-1 text-sm text-ink-400">
            {server?.mode === 'local' ? t('auth.subtitleLocal') : t('auth.subtitle')}
          </p>

          {server && server.mode !== 'local' && !server.jellyfin_configured ? (
            <div className="mt-5 space-y-4">
              <Alert tone="warning">{t('auth.jellyfinNotConfigured')}</Alert>
              <Link to="/setup" className="btn btn-primary w-full">
                {t('auth.goToSetup')}
              </Link>
            </div>
          ) : (
            <form className="mt-5 space-y-4" onSubmit={submit}>
              <Field label={t('auth.username')}>
                <Input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  autoFocus
                  required
                />
              </Field>
              <Field label={t('auth.password')}>
                <Input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                />
              </Field>

              {error && <Alert tone="error">{error}</Alert>}

              <Button type="submit" variant="primary" className="w-full" loading={busy}>
                {busy ? t('auth.signingIn') : t('auth.signIn')}
              </Button>
            </form>
          )}

          {server?.jellyfin_server_name && (
            <div className="mt-5 flex items-center justify-center gap-1.5 text-xs text-ink-500">
              <Server className="size-3.5" />
              {t('auth.connectedTo')} · {server.jellyfin_server_name}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
