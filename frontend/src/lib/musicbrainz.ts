/** Website used for “open on MusicBrainz” links, never the API URL. */
export function musicBrainzUrl(
  kind: 'release-group' | 'release',
  mbid: string,
  base = 'https://musicbrainz.org',
): string {
  const root = base.replace(/\/+$/, '') || 'https://musicbrainz.org'
  return `${root}/${kind}/${mbid}`
}
