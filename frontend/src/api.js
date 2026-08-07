// Thin fetch wrappers over the FastAPI backend. Errors from the engine come back
// as { error } with status 400; surface that message rather than a generic one.

async function j(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || body.detail || res.statusText)
  }
  return res.json()
}

export const getDiagnostics = () => fetch('/api/diagnostics').then(j)
export const getFilms = () => fetch('/api/films').then(j)
export const getSourceTypes = () => fetch('/api/source-types').then(j)
export const getConfig = () => fetch('/api/config').then(j)
export const getLibraryFilms = () => fetch('/api/library-films').then(j)
export const registerFilm = (body) =>
  fetch('/api/films', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)
export const deleteFilm = (id) =>
  fetch('/api/films/' + id, { method: 'DELETE' }).then(j)
export const importFilm = (body) =>
  fetch('/api/films/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)
export const importPbp = (body) =>
  fetch('/api/pbp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)
export const startAlign = (body) =>
  fetch('/api/align', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)
export const startDetect = (body) =>
  fetch('/api/detect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)
export const getJob = (id) => fetch('/api/jobs/' + id).then(j)
export const getTagKeys = () => fetch('/api/tag-keys').then(j)
export const getTagValues = (key) =>
  fetch('/api/tag-values?key=' + encodeURIComponent(key)).then(j)

export function getPlays({ where = [], film, source, minConfidence, confirmedOnly }) {
  const q = new URLSearchParams()
  where.forEach((w) => q.append('where', w))
  if (film) q.append('film', film)
  if (source) q.append('source', source)
  if (minConfidence !== undefined && minConfidence !== '' && minConfidence !== null)
    q.append('min_confidence', minConfidence)
  if (confirmedOnly) q.append('confirmed_only', 'true')
  return fetch('/api/plays?' + q.toString()).then(j)
}

export const patchPlay = (id, body) =>
  fetch('/api/plays/' + id, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)

export const createPlay = (body) =>
  fetch('/api/plays', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)

export const deletePlay = (id) =>
  fetch('/api/plays/' + id, { method: 'DELETE' }).then(j)

export const postExport = (body) =>
  fetch('/api/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)

export const streamUrl = (filmId) => '/api/film/' + filmId + '/stream'
export const thumbUrl = (playId) => '/api/play/' + playId + '/thumb'

export const getExportSizes = () => fetch('/api/export-sizes').then(j)
export const seedPresets = () => fetch('/api/presets/seed', { method: 'POST' }).then(j)
export const startReel = (body) =>
  fetch('/api/reel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)

export const getPresets = () => fetch('/api/presets').then(j)
export const savePreset = (body) =>
  fetch('/api/presets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(j)
export const deletePreset = (name) =>
  fetch('/api/presets/' + encodeURIComponent(name), { method: 'DELETE' }).then(j)
export const exportPresets = () => fetch('/api/presets/export').then(j)
export const importPresets = (presets, overwrite = true) =>
  fetch('/api/presets/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ presets, overwrite }),
  }).then(j)
