import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ExternalLink, Link2Off, Radio, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useToast } from '../components/Toast'
import { Alert, Button, Card, CenteredSpinner, Chip } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { LastfmAuthStart, ListeningAccounts } from '../lib/types'

/**
 * The listener's own page: the accounts that decide whose taste the
 * recommendations follow, and where a play is credited. Nothing here is an
 * administrator's business, which is why it does not live in the admin section.
 */
export function AccountPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const { notify } = useToast()
  const queryClient = useQueryClient()

  // Null means "not edited yet", so the stored handle shows without the field
  // refusing to be emptied.
  const [listenbrainzUser, setListenbrainzUser] = useState<string | null>(null)
  const [listenbrainzToken, setListenbrainzToken] = useState('')
  const [pendingAuth, setPendingAuth] = useState<LastfmAuthStart | null>(null)

  const accounts = useQuery({
    queryKey: ['account', 'services'],
    queryFn: () => api<ListeningAccounts>('/account/services'),
  })

  const fail = (error: unknown) =>
    notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error')

  const done = (message: string) => {
    notify(message, 'success')
    void queryClient.invalidateQueries({ queryKey: ['account', 'services'] })
    void queryClient.invalidateQueries({ queryKey: ['discover', 'for-you'] })
  }

  const saveListenBrainz = useMutation({
    mutationFn: () =>
      api<ListeningAccounts>('/account/services', {
        method: 'PUT',
        body: {
          listenbrainz_user: (listenbrainzUser ?? accounts.data?.listenbrainz_user ?? '').trim(),
          listenbrainz_token: listenbrainzToken.trim() || null,
        },
      }),
    onSuccess: () => {
      setListenbrainzToken('')
      setListenbrainzUser(null)
      done(t('account.connected'))
    },
    onError: fail,
  })

  const disconnect = useMutation({
    mutationFn: (service: string) =>
      api<ListeningAccounts>(`/account/services/${service}`, { method: 'DELETE' }),
    onSuccess: () => done(t('account.disconnected')),
    onError: fail,
  })

  const startLastfm = useMutation({
    mutationFn: () => api<LastfmAuthStart>('/account/lastfm/authorize', { method: 'POST' }),
    onSuccess: (result) => {
      setPendingAuth(result)
      window.open(result.url, '_blank', 'noopener,noreferrer')
    },
    onError: fail,
  })

  const finishLastfm = useMutation({
    mutationFn: () =>
      api<ListeningAccounts>('/account/lastfm/finish', {
        method: 'POST',
        body: { token: pendingAuth?.token ?? '' },
      }),
    onSuccess: () => {
      setPendingAuth(null)
      done(t('account.connected'))
    },
    onError: fail,
  })

  if (accounts.isLoading) return <CenteredSpinner label={t('common.loading')} />

  const data = accounts.data
  const nothingEnabled = !data?.listenbrainz_enabled && !data?.lastfm_enabled

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold text-ink-100">{t('account.title')}</h1>
        <p className="mt-1 text-sm text-ink-400">{t('account.subtitle')}</p>
      </header>

      <Card className="flex flex-wrap items-center gap-3 p-4">
        <div className="grid size-11 shrink-0 place-items-center rounded-full gradient-surface text-base font-bold text-white">
          {(user?.name ?? '?').slice(0, 1).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-ink-100">{user?.name}</p>
          <p className="hint">{user?.username ?? user?.jellyfin_user_id}</p>
        </div>
        {user?.is_admin && <Chip tone="brand">{t('admin.userAdmin')}</Chip>}
      </Card>

      {nothingEnabled && (
        <Alert tone="info" className="flex items-start gap-2">
          <Sparkles className="mt-0.5 size-4 shrink-0" />
          {t('account.noneEnabled')}
        </Alert>
      )}

      {data?.listenbrainz_enabled && (
        <Card className="space-y-4 p-5">
          <header className="flex flex-wrap items-center gap-2">
            <Radio className="size-4 text-brand-300" />
            <h2 className="font-display text-lg text-ink-100">ListenBrainz</h2>
            {data.listenbrainz_connected ? (
              <Chip tone="success">
                <Check className="size-3" />
                {data.listenbrainz_user ?? t('account.connectedShort')}
              </Chip>
            ) : (
              <Chip tone="muted">{t('account.notConnected')}</Chip>
            )}
          </header>
          <p className="text-sm text-ink-400">{t('account.listenbrainzHelp')}</p>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="lb-user">
                {t('account.username')}
              </label>
              <input
                id="lb-user"
                className="field"
                value={listenbrainzUser ?? data.listenbrainz_user ?? ''}
                onChange={(event) => setListenbrainzUser(event.target.value)}
                placeholder="listenbrainz"
              />
            </div>
            <div>
              <label className="label" htmlFor="lb-token">
                {t('account.token')}
              </label>
              <input
                id="lb-token"
                className="field"
                type="password"
                autoComplete="off"
                value={listenbrainzToken}
                onChange={(event) => setListenbrainzToken(event.target.value)}
                placeholder={data.listenbrainz_connected ? '••••••••' : ''}
              />
              <p className="hint mt-1">{t('account.tokenHint')}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              loading={saveListenBrainz.isPending}
              onClick={() => saveListenBrainz.mutate()}
            >
              {t('common.save')}
            </Button>
            <a
              className="btn btn-ghost btn-sm"
              href="https://listenbrainz.org/settings/"
              rel="noopener noreferrer"
              target="_blank"
            >
              <ExternalLink className="size-3.5" />
              {t('account.getToken')}
            </a>
            {data.listenbrainz_connected && (
              <Button
                size="sm"
                loading={disconnect.isPending}
                onClick={() => disconnect.mutate('listenbrainz')}
              >
                <Link2Off className="size-3.5" />
                {t('account.disconnect')}
              </Button>
            )}
          </div>
        </Card>
      )}

      {data?.lastfm_enabled && (
        <Card className="space-y-4 p-5">
          <header className="flex flex-wrap items-center gap-2">
            <Radio className="size-4 text-accent-300" />
            <h2 className="font-display text-lg text-ink-100">Last.fm</h2>
            {data.lastfm_connected ? (
              <Chip tone="success">
                <Check className="size-3" />
                {data.lastfm_user ?? t('account.connectedShort')}
              </Chip>
            ) : (
              <Chip tone="muted">{t('account.notConnected')}</Chip>
            )}
          </header>
          <p className="text-sm text-ink-400">{t('account.lastfmHelp')}</p>

          {!data.lastfm_can_authorize && (
            <Alert tone="warning">{t('account.lastfmNoApp')}</Alert>
          )}

          {pendingAuth ? (
            <Alert tone="info" className="space-y-3">
              <p>{t('account.lastfmApprove')}</p>
              <div className="flex flex-wrap gap-2">
                <a
                  className="btn btn-ghost btn-sm"
                  href={pendingAuth.url}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  <ExternalLink className="size-3.5" />
                  {t('account.lastfmOpen')}
                </a>
                <Button
                  variant="primary"
                  size="sm"
                  loading={finishLastfm.isPending}
                  onClick={() => finishLastfm.mutate()}
                >
                  <Check className="size-3.5" />
                  {t('account.lastfmDone')}
                </Button>
                <Button size="sm" onClick={() => setPendingAuth(null)}>
                  {t('common.cancel')}
                </Button>
              </div>
            </Alert>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="primary"
                disabled={!data.lastfm_can_authorize}
                loading={startLastfm.isPending}
                onClick={() => startLastfm.mutate()}
              >
                <ExternalLink className="size-4" />
                {data.lastfm_connected ? t('account.reconnect') : t('account.connect')}
              </Button>
              {data.lastfm_connected && (
                <Button
                  size="sm"
                  loading={disconnect.isPending}
                  onClick={() => disconnect.mutate('lastfm')}
                >
                  <Link2Off className="size-3.5" />
                  {t('account.disconnect')}
                </Button>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
