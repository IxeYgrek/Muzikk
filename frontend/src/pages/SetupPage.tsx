import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  CheckCircle2,
  FolderTree,
  HardDrive,
  Library,
  Plug,
  Server,
  UserCog,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate } from 'react-router-dom'

import { LanguageSwitch } from '../components/LanguageSwitch'
import { Logo } from '../components/Logo'
import { Alert, Button, Card, Field, Input, Spinner } from '../components/ui'
import { currentLanguage } from '../i18n'
import { ApiError, api } from '../lib/api'
import type { Health, JellyfinLibrary, Mode, TestResult } from '../lib/types'

/**
 * First run wizard.
 *
 * Step zero is the only choice that cannot be undone afterwards, so it is
 * asked plainly and on its own: either Jellyfin owns the accounts and the
 * music library, or Muzikk does.
 */
export function SetupPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [step, setStep] = useState(0)
  const [mode, setMode] = useState<Mode | null>(null)
  const [url, setUrl] = useState('http://jellyfin:8096')
  const [apiKey, setApiKey] = useState('')
  const [musicDir, setMusicDir] = useState('/music')
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => api<Health>('/health'),
  })

  const librariesQuery = useQuery({
    queryKey: ['setup', 'libraries'],
    queryFn: () => api<JellyfinLibrary[]>('/setup/libraries'),
    enabled: step === 2 && mode === 'jellyfin',
  })

  useEffect(() => {
    const libraries = librariesQuery.data
    if (libraries && selected.length === 0) {
      setSelected(libraries.map((library) => library.id))
    }
  }, [librariesQuery.data, selected.length])

  if (health && !health.setup_required && step < 3) {
    return <Navigate to="/login" replace />
  }

  async function chooseMode(value: Mode) {
    setError(null)
    setBusy(true)
    try {
      await api('/setup/mode', { method: 'POST', body: { mode: value } })
      setMode(value)
      setStep(1)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('errors.generic'))
    } finally {
      setBusy(false)
    }
  }

  async function connect() {
    setError(null)
    setBusy(true)
    try {
      const result = await api<TestResult>('/setup/jellyfin', {
        method: 'POST',
        body: { url: url.trim(), api_key: apiKey.trim() },
      })
      if (!result.ok) {
        setError(result.message)
        return
      }
      setStep(2)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('errors.generic'))
    } finally {
      setBusy(false)
    }
  }

  async function finish(body: Record<string, unknown>) {
    setError(null)
    setBusy(true)
    try {
      await api('/setup/finish', { method: 'POST', body: { ...body, language: currentLanguage() } })
      setStep(3)
      await queryClient.invalidateQueries({ queryKey: ['health'] })
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('errors.generic'))
    } finally {
      setBusy(false)
    }
  }

  const passwordsMatch = password.length > 0 && password === confirm
  const localReady = username.trim().length >= 3 && passwordsMatch && musicDir.trim().length > 0

  return (
    <div className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-2xl">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Logo size="lg" showWordmark={false} />
          <h1 className="font-display text-3xl font-bold text-ink-100">{t('setup.title')}</h1>
          <p className="max-w-lg text-sm text-ink-400">{t('setup.subtitle')}</p>
          <LanguageSwitch className="mt-1 w-40" />
        </div>

        <div className="mb-6 flex items-center gap-2">
          {[0, 1, 2].map((index) => (
            <div
              key={index}
              className={clsx(
                'h-1 flex-1 rounded-full transition-colors',
                step > index || (step === index && index === 0)
                  ? 'gradient-surface'
                  : 'bg-ink-700',
              )}
            />
          ))}
        </div>

        <Card className="p-6">
          {step === 0 && (
            <div className="space-y-5">
              <header className="flex items-start gap-3">
                <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-600/15 text-brand-300">
                  <Server className="size-5" />
                </div>
                <div>
                  <h2 className="font-display text-lg text-ink-100">{t('setup.modeTitle')}</h2>
                  <p className="hint mt-1">{t('setup.modeDesc')}</p>
                </div>
              </header>

              <div className="grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void chooseMode('jellyfin')}
                  className="flex flex-col gap-2 rounded-xl border border-ink-600/50 p-4 text-left transition-colors hover:border-brand-500/60 hover:bg-brand-600/10 disabled:opacity-50"
                >
                  <Plug className="size-5 text-brand-300" />
                  <span className="text-sm font-medium text-ink-100">
                    {t('setup.modeJellyfin')}
                  </span>
                  <span className="hint">{t('setup.modeJellyfinDesc')}</span>
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void chooseMode('local')}
                  className="flex flex-col gap-2 rounded-xl border border-ink-600/50 p-4 text-left transition-colors hover:border-brand-500/60 hover:bg-brand-600/10 disabled:opacity-50"
                >
                  <HardDrive className="size-5 text-brand-300" />
                  <span className="text-sm font-medium text-ink-100">{t('setup.modeLocal')}</span>
                  <span className="hint">{t('setup.modeLocalDesc')}</span>
                </button>
              </div>

              <Alert tone="warning">{t('setup.modeWarning')}</Alert>
              {error && <Alert tone="error">{error}</Alert>}
            </div>
          )}

          {step === 1 && mode === 'jellyfin' && (
            <div className="space-y-5">
              <header className="flex items-start gap-3">
                <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-600/15 text-brand-300">
                  <Plug className="size-5" />
                </div>
                <div>
                  <h2 className="font-display text-lg text-ink-100">{t('setup.jellyfinTitle')}</h2>
                  <p className="hint mt-1">{t('setup.jellyfinDesc')}</p>
                </div>
              </header>

              <Field label={t('setup.url')}>
                <Input
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="http://jellyfin:8096"
                  autoFocus
                />
              </Field>
              <Field label={t('setup.apiKey')}>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  autoComplete="off"
                />
              </Field>

              {error && <Alert tone="error">{error}</Alert>}

              <Button
                variant="primary"
                className="w-full"
                loading={busy}
                disabled={!url.trim() || !apiKey.trim()}
                onClick={connect}
              >
                {t('setup.connect')}
              </Button>
            </div>
          )}

          {step === 1 && mode === 'local' && (
            <div className="space-y-5">
              <header className="flex items-start gap-3">
                <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-600/15 text-brand-300">
                  <UserCog className="size-5" />
                </div>
                <div>
                  <h2 className="font-display text-lg text-ink-100">{t('setup.adminTitle')}</h2>
                  <p className="hint mt-1">{t('setup.adminDesc')}</p>
                </div>
              </header>

              <Field label={t('auth.username')} hint={t('setup.usernameHint')}>
                <Input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  autoFocus
                />
              </Field>
              <Field label={t('setup.displayName')} hint={t('setup.displayNameHint')}>
                <Input
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  autoComplete="name"
                />
              </Field>
              <Field label={t('auth.password')} hint={t('setup.passwordHint')}>
                <Input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="new-password"
                />
              </Field>
              <Field label={t('setup.passwordConfirm')}>
                <Input
                  type="password"
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  autoComplete="new-password"
                />
              </Field>
              {confirm.length > 0 && !passwordsMatch && (
                <Alert tone="warning">{t('setup.passwordMismatch')}</Alert>
              )}

              <Field
                label={
                  <span className="inline-flex items-center gap-1.5">
                    <FolderTree className="size-3.5" />
                    {t('setup.musicDir')}
                  </span>
                }
                hint={t('setup.musicDirLocalHint')}
              >
                <Input value={musicDir} onChange={(event) => setMusicDir(event.target.value)} />
              </Field>

              {error && <Alert tone="error">{error}</Alert>}

              <Button
                variant="primary"
                className="w-full"
                loading={busy}
                disabled={!localReady}
                onClick={() =>
                  void finish({
                    username: username.trim(),
                    password,
                    name: displayName.trim(),
                    music_dir: musicDir.trim(),
                  })
                }
              >
                {busy ? t('setup.finishing') : t('setup.finish')}
              </Button>
            </div>
          )}

          {step === 2 && mode === 'jellyfin' && (
            <div className="space-y-5">
              <header className="flex items-start gap-3">
                <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-600/15 text-brand-300">
                  <Library className="size-5" />
                </div>
                <div>
                  <h2 className="font-display text-lg text-ink-100">{t('setup.librariesTitle')}</h2>
                  <p className="hint mt-1">{t('setup.librariesDesc')}</p>
                </div>
              </header>

              {librariesQuery.isLoading && <Spinner />}

              {librariesQuery.data && librariesQuery.data.length === 0 && (
                <Alert tone="warning">{t('setup.noLibraries')}</Alert>
              )}

              <div className="space-y-2">
                {(librariesQuery.data ?? []).map((library) => {
                  const checked = selected.includes(library.id)
                  return (
                    <button
                      key={library.id}
                      type="button"
                      onClick={() =>
                        setSelected((current) =>
                          checked
                            ? current.filter((id) => id !== library.id)
                            : [...current, library.id],
                        )
                      }
                      className={clsx(
                        'flex w-full items-center gap-3 rounded-xl border px-3.5 py-3 text-left transition-colors',
                        checked
                          ? 'border-brand-500/60 bg-brand-600/10'
                          : 'border-ink-600/50 hover:border-ink-500',
                      )}
                    >
                      <CheckCircle2
                        className={clsx('size-5 shrink-0', checked ? 'text-brand-400' : 'text-ink-600')}
                      />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-ink-100">{library.name}</div>
                        <div className="hint truncate">{library.locations.join(', ')}</div>
                      </div>
                    </button>
                  )
                })}
              </div>

              <Field
                label={
                  <span className="inline-flex items-center gap-1.5">
                    <FolderTree className="size-3.5" />
                    {t('setup.musicDir')}
                  </span>
                }
                hint={t('setup.musicDirHint')}
              >
                <Input value={musicDir} onChange={(event) => setMusicDir(event.target.value)} />
              </Field>

              {error && <Alert tone="error">{error}</Alert>}

              <div className="flex gap-2">
                <Button onClick={() => setStep(1)} disabled={busy}>
                  {t('common.back')}
                </Button>
                <Button
                  variant="primary"
                  className="flex-1"
                  loading={busy}
                  onClick={() =>
                    void finish({ music_library_ids: selected, music_dir: musicDir.trim() })
                  }
                >
                  {busy ? t('setup.finishing') : t('setup.finish')}
                </Button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="flex flex-col items-center gap-4 py-6 text-center">
              <CheckCircle2 className="size-12 text-emerald-400" />
              <h2 className="font-display text-xl text-ink-100">{t('setup.successTitle')}</h2>
              <p className="max-w-md text-sm text-ink-400">
                {mode === 'local' ? t('setup.successLocalDesc') : t('setup.successDesc')}
              </p>
              <Link to="/login" className="btn btn-primary">
                {t('setup.goToLogin')}
              </Link>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
