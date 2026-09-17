import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { CheckCircle2, FolderTree, Library, Plug } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate } from 'react-router-dom'

import { Logo } from '../components/Logo'
import { Alert, Button, Card, Field, Input, Spinner } from '../components/ui'
import { ApiError, api } from '../lib/api'
import type { Health, JellyfinLibrary, TestResult } from '../lib/types'

export function SetupPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [step, setStep] = useState(1)
  const [url, setUrl] = useState('http://jellyfin:8096')
  const [apiKey, setApiKey] = useState('')
  const [musicDir, setMusicDir] = useState('/music')
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
    enabled: step === 2,
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

  async function finish() {
    setError(null)
    setBusy(true)
    try {
      await api('/setup/finish', {
        method: 'POST',
        body: { music_library_ids: selected, music_dir: musicDir.trim() },
      })
      setStep(3)
      await queryClient.invalidateQueries({ queryKey: ['health'] })
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('errors.generic'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-2xl">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Logo size="lg" showWordmark={false} />
          <h1 className="font-display text-3xl font-bold text-ink-100">{t('setup.title')}</h1>
          <p className="max-w-lg text-sm text-ink-400">{t('setup.subtitle')}</p>
        </div>

        <div className="mb-6 flex items-center gap-2">
          {[1, 2].map((index) => (
            <div
              key={index}
              className={clsx(
                'h-1 flex-1 rounded-full transition-colors',
                step >= index ? 'gradient-surface' : 'bg-ink-700',
              )}
            />
          ))}
        </div>

        <Card className="p-6">
          {step === 1 && (
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

          {step === 2 && (
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
                <Button variant="primary" className="flex-1" loading={busy} onClick={finish}>
                  {busy ? t('setup.finishing') : t('setup.finish')}
                </Button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="flex flex-col items-center gap-4 py-6 text-center">
              <CheckCircle2 className="size-12 text-emerald-400" />
              <h2 className="font-display text-xl text-ink-100">{t('setup.successTitle')}</h2>
              <p className="max-w-md text-sm text-ink-400">{t('setup.successDesc')}</p>
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
