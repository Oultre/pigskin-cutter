import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  getFilms, getTagKeys, getTagValues, getPlays, patchPlay, postExport, streamUrl,
  getPresets, savePreset, deletePreset, exportPresets, importPresets,
  getSourceTypes, getLibraryFilms, registerFilm, deleteFilm, importPbp,
  startAlign, getJob,
} from './api.js'
import TagPass from './TagPass.jsx'
import Help from './Help.jsx'

const OPS = ['=', '!=', '>=', '<=', '>', '<', 'exists']
const emptyForm = { preds: [], film: '', source: '', minConf: '', confirmedOnly: false }

const SOURCE_LABELS = {
  hudl_clip: 'Hudl clips (pre-cut)',
  hudl_game: 'Hudl game film',
  broadcast: 'TV broadcast',
  all22: 'All-22 (NFL / NCAA)',
  drone: 'Drone (DJI)',
}
const sourceLabel = (s) => SOURCE_LABELS[s] || s

function fmt(t) {
  if (t === null || t === undefined) return '—'
  const s = Math.max(0, t)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const p = (n, w = 2) => String(n).padStart(w, '0')
  return `${p(h)}:${p(m)}:${sec.toFixed(1).padStart(4, '0')}`
}

// -- filter <-> preset conversions (canonical filter shape shared with the CLI)

function predToWhere(p) {
  if (p.op === 'exists') return `${p.key} exists`
  return `${p.key}${p.op}${p.value}`
}
function whereToPred(w) {
  const ex = w.match(/^(.+?)\s+exists\s*$/i)
  if (ex) return { key: ex[1].trim(), op: 'exists', value: '' }
  const m = w.match(/^(.+?)(>=|<=|!=|=|>|<)(.+)$/)
  if (m) return { key: m[1].trim(), op: m[2], value: m[3].trim() }
  return { key: w.trim(), op: '=', value: '' }
}
function formToFilter(form) {
  return {
    where: form.preds.filter((p) => p.key && (p.op === 'exists' || p.value !== '')).map(predToWhere),
    film: form.film ? Number(form.film) : null,
    source: form.source || null,
    min_confidence: form.minConf !== '' ? Number(form.minConf) : null,
    confirmed_only: form.confirmedOnly,
  }
}
function filterToForm(f) {
  return {
    preds: (f.where || []).map(whereToPred),
    film: f.film != null ? String(f.film) : '',
    source: f.source || '',
    minConf: f.min_confidence != null ? String(f.min_confidence) : '',
    confirmedOnly: !!f.confirmed_only,
  }
}
function formToQuery(form) {
  const f = formToFilter(form)
  return {
    where: f.where,
    film: f.film || undefined,
    source: f.source || undefined,
    minConfidence: f.min_confidence,
    confirmedOnly: f.confirmed_only,
  }
}

// -- Presets ----------------------------------------------------------------

function PresetBar({ presets, onLoad, onSave, onDelete, onExport, onImport }) {
  const [name, setName] = useState('')
  const [sel, setSel] = useState('')
  const fileRef = useRef(null)

  const pickFile = () => fileRef.current && fileRef.current.click()
  const onFile = async (e) => {
    const file = e.target.files[0]
    e.target.value = ''            // allow re-importing the same file
    if (!file) return
    try {
      onImport(JSON.parse(await file.text()))
    } catch (err) { onImport(null, 'Could not read that file: ' + err.message) }
  }

  return (
    <div className="panel presets">
      <h2>Presets</h2>
      <div className="row">
        <select value={sel} onChange={(e) => { setSel(e.target.value); if (e.target.value) onLoad(e.target.value) }}>
          <option value="">load preset…</option>
          {presets.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
        </select>
        <button className="x" disabled={!sel} onClick={() => { onDelete(sel); setSel('') }}>delete</button>
      </div>
      <div className="row">
        <input placeholder="save current filter as…" value={name} onChange={(e) => setName(e.target.value)} />
        <button disabled={!name.trim()} onClick={() => { onSave(name.trim()); setName('') }}>Save</button>
      </div>
      <div className="row">
        <button onClick={pickFile}>Import…</button>
        <button disabled={!presets.length} onClick={onExport}>Export</button>
        <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={onFile} />
      </div>
    </div>
  )
}

// -- Filter builder (controlled by App-owned form state) --------------------

function FilterBuilder({ form, setForm, tagKeys, films, onApply }) {
  const [valueOptions, setValueOptions] = useState({})
  const preds = form.preds

  const addPred = () =>
    setForm((f) => ({ ...f, preds: [...f.preds, { key: tagKeys[0] || '', op: '=', value: '' }] }))
  const update = (i, patch) =>
    setForm((f) => ({ ...f, preds: f.preds.map((x, j) => (j === i ? { ...x, ...patch } : x)) }))
  const remove = (i) =>
    setForm((f) => ({ ...f, preds: f.preds.filter((_, j) => j !== i) }))

  const loadValues = async (key) => {
    if (!key || valueOptions[key]) return
    try {
      const vals = await getTagValues(key)
      setValueOptions((v) => ({ ...v, [key]: vals }))
    } catch { /* ignore */ }
  }

  return (
    <div className="panel filter">
      <h2>Filter</h2>
      {preds.map((p, i) => (
        <div className="pred" key={i}>
          <select value={p.key} onChange={(e) => { update(i, { key: e.target.value }); loadValues(e.target.value) }}>
            {!tagKeys.includes(p.key) && p.key ? <option value={p.key}>{p.key}</option> : null}
            {tagKeys.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <select value={p.op} onChange={(e) => update(i, { op: e.target.value })}>
            {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          {p.op !== 'exists' && (
            <>
              <input list={`vals-${i}`} value={p.value}
                onChange={(e) => update(i, { value: e.target.value })}
                onFocus={() => loadValues(p.key)} placeholder="value" />
              <datalist id={`vals-${i}`}>
                {(valueOptions[p.key] || []).map((v) => <option key={v} value={v} />)}
              </datalist>
            </>
          )}
          <button className="x" onClick={() => remove(i)}>×</button>
        </div>
      ))}
      <button onClick={addPred}>+ condition</button>

      <div className="meta">
        <label>Film
          <select value={form.film} onChange={(e) => setForm((f) => ({ ...f, film: e.target.value }))}>
            <option value="">any</option>
            {films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
          </select>
        </label>
        <label>Source
          <select value={form.source} onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}>
            <option value="">any</option>
            {['hudl', 'tagged', 'detected', 'ocr'].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>Min conf
          <input type="number" step="0.1" min="0" max="1" value={form.minConf}
            onChange={(e) => setForm((f) => ({ ...f, minConf: e.target.value }))} style={{ width: '4em' }} />
        </label>
        <label className="chk">
          <input type="checkbox" checked={form.confirmedOnly}
            onChange={(e) => setForm((f) => ({ ...f, confirmedOnly: e.target.checked }))} /> confirmed only
        </label>
      </div>
      <button className="primary" onClick={onApply}>Apply</button>
    </div>
  )
}

// -- Play grid --------------------------------------------------------------

function PlayGrid({ plays, selectedId, onSelect }) {
  const keys = useMemo(() => {
    const s = new Set()
    plays.forEach((p) => Object.keys(p.tags).forEach((k) => s.add(k)))
    return Array.from(s).sort()
  }, [plays])

  return (
    <div className="grid-wrap">
      <table className="grid">
        <thead>
          <tr>
            <th>#</th><th>start</th><th>end</th><th>src</th><th>conf</th>
            {keys.map((k) => <th key={k}>{k}</th>)}
          </tr>
        </thead>
        <tbody>
          {plays.map((p) => (
            <tr key={p.id} className={p.id === selectedId ? 'sel' : ''} onClick={() => onSelect(p)}>
              <td>{p.play_no ?? '—'}</td>
              <td>{fmt(p.t_start)}</td>
              <td>{fmt(p.t_end)}</td>
              <td>{p.source}</td>
              <td className={p.confidence < 1 ? 'lowconf' : ''}>{p.confidence.toFixed(2)}</td>
              {keys.map((k) => <td key={k}>{p.tags[k] ?? ''}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// -- Preview + nudge --------------------------------------------------------

function Preview({ play, onChange }) {
  const videoRef = useRef(null)

  useEffect(() => {
    const v = videoRef.current
    if (v && play && play.t_start != null) {
      const seek = () => { v.currentTime = play.t_start }
      if (v.readyState >= 1) seek()
      else v.addEventListener('loadedmetadata', seek, { once: true })
    }
  }, [play?.id])

  if (!play) return <div className="panel preview empty">Select a play to preview.</div>

  const nudge = async (field, delta) => {
    const next = (play[field] ?? 0) + delta
    const updated = await patchPlay(play.id, { [field]: Math.max(0, next) })
    onChange(updated)
  }
  const setToPlayhead = async (field) => {
    const v = videoRef.current
    if (!v) return
    const updated = await patchPlay(play.id, { [field]: v.currentTime })
    onChange(updated)
  }

  return (
    <div className="panel preview">
      <h2>Play {play.play_no ?? play.id}</h2>
      <video ref={videoRef} src={streamUrl(play.film_id)} controls preload="metadata" />
      <div className="nudge">
        <div className="row">
          <span>start {fmt(play.t_start)}</span>
          <button onClick={() => nudge('t_start', -0.5)}>-0.5</button>
          <button onClick={() => nudge('t_start', -0.1)}>-0.1</button>
          <button onClick={() => nudge('t_start', 0.1)}>+0.1</button>
          <button onClick={() => nudge('t_start', 0.5)}>+0.5</button>
          <button onClick={() => setToPlayhead('t_start')}>= playhead</button>
        </div>
        <div className="row">
          <span>end {fmt(play.t_end)}</span>
          <button onClick={() => nudge('t_end', -0.5)}>-0.5</button>
          <button onClick={() => nudge('t_end', -0.1)}>-0.1</button>
          <button onClick={() => nudge('t_end', 0.1)}>+0.1</button>
          <button onClick={() => nudge('t_end', 0.5)}>+0.5</button>
          <button onClick={() => setToPlayhead('t_end')}>= playhead</button>
        </div>
      </div>
      <div className="tags">
        {Object.entries(play.tags).map(([k, v]) => (
          <span className="tag" key={k}>{k}={v}</span>
        ))}
      </div>
    </div>
  )
}

// -- Export -----------------------------------------------------------------

function ExportPanel({ filter, count }) {
  const [out, setOut] = useState('')
  const [logo, setLogo] = useState('')
  const [pos, setPos] = useState('bottom-right')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = async (dry) => {
    setError(''); setBusy(true); setResult(null)
    const branding = logo ? { logo, logo_position: pos } : {}
    try {
      setResult(await postExport({ ...filter, out, dry_run: dry, ...branding }))
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="panel export">
      <h2>Export ({count} plays)</h2>
      <input placeholder="output folder" value={out} onChange={(e) => setOut(e.target.value)} />
      <div className="row">
        <input placeholder="logo image (optional)" value={logo} onChange={(e) => setLogo(e.target.value)} style={{ flex: 2 }} />
        <select value={pos} onChange={(e) => setPos(e.target.value)} disabled={!logo} style={{ flex: 1 }}>
          <option value="bottom-right">BR</option>
          <option value="bottom-left">BL</option>
          <option value="top-right">TR</option>
          <option value="top-left">TL</option>
          <option value="center">center</option>
        </select>
      </div>
      {logo && <div className="hint">Branding re-encodes clips (slower than a plain cut).</div>}
      <div className="row">
        <button onClick={() => run(true)} disabled={busy || !out}>Dry run</button>
        <button className="primary" onClick={() => run(false)} disabled={busy || !out}>Cut clips</button>
      </div>
      {error && <div className="error">{error}</div>}
      {result && (
        <div className="result">
          <div>{result.dry_run ? 'Dry run' : 'Done'}: {result.count} clip(s)
            {result.skipped ? `, ${result.skipped} untimed skipped` : ''}
            {result.failed ? `, ${result.failed} failed` : ''}</div>
          <ul>
            {result.clips.slice(0, 12).map((c, i) => (
              <li key={i}>{c.output} &larr; {c.in}–{c.out} ({c.mode})</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// -- Film library / import --------------------------------------------------

function PbpImport({ films, onChanged }) {
  const [filmId, setFilmId] = useState('')
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const run = async (dry) => {
    setError(''); setBusy(true); setResult(null)
    try {
      const r = await importPbp({ film_id: Number(filmId), source, dry_run: dry })
      setResult(r)
      if (!dry) onChanged()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="film-add">
      <h2>Import play-by-play</h2>
      <label>Attach to film</label>
      <select value={filmId} onChange={(e) => setFilmId(e.target.value)} style={{ width: '100%', marginBottom: '0.4rem' }}>
        <option value="">select film…</option>
        {films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
      </select>
      <label>Box-score URL or saved .html path</label>
      <input value={source} onChange={(e) => setSource(e.target.value)}
        placeholder="https://…/boxscore/25444" style={{ width: '100%' }} />
      <div className="row" style={{ marginTop: '0.6rem' }}>
        <button onClick={() => run(true)} disabled={busy || !filmId || !source}>Preview</button>
        <button className="primary" onClick={() => run(false)} disabled={busy || !filmId || !source}>Import</button>
      </div>
      <span className="hint2">Fetched once and cached. Plays land with no cut times (aligned later).</span>
      {error && <div className="error">{error}</div>}
      {result && (
        <div className="result" style={{ marginTop: '0.5rem', fontSize: '0.82rem' }}>
          {result.dry_run ? 'Preview' : 'Imported'}: {result.count ?? result.imported} plays
          {' — '}{Object.entries(result.possession || {}).map(([t, n]) => `${t}: ${n}`).join(', ')}
          {(result.warnings || []).map((w, i) => <div key={i} className="hint">{w}</div>)}
        </div>
      )}
    </div>
  )
}

function AlignPanel({ films, onChanged }) {
  const [filmId, setFilmId] = useState('')
  const [job, setJob] = useState(null)
  const [error, setError] = useState('')
  const pollRef = useRef(null)

  useEffect(() => () => clearInterval(pollRef.current), [])

  const poll = (id) => {
    pollRef.current = setInterval(async () => {
      try {
        const j = await getJob(id)
        setJob(j)
        if (j.status !== 'running') {
          clearInterval(pollRef.current)
          if (j.status === 'done') onChanged()
        }
      } catch { clearInterval(pollRef.current) }
    }, 2000)
  }

  const start = async () => {
    setError(''); setJob(null)
    try {
      const j = await startAlign({ film_id: Number(filmId) })
      setJob(j); poll(j.id)
    } catch (e) { setError(e.message) }
  }

  const running = job && job.status === 'running'
  return (
    <div className="film-add">
      <h2>Auto-align a broadcast game</h2>
      <p className="hint2" style={{ margin: '0 0 0.5rem' }}>
        Reads the on-screen game clock and lines the play-by-play up with the video — no tagging.
        Needs the play-by-play imported first, and a visible clock in the picture. Takes several minutes.
      </p>
      <div className="row">
        <select value={filmId} onChange={(e) => setFilmId(e.target.value)} style={{ flex: 1 }} disabled={running}>
          <option value="">select film…</option>
          {films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
        </select>
        <button className="primary" onClick={start} disabled={!filmId || running}>
          {running ? 'Running…' : 'Auto-align'}
        </button>
      </div>
      {job && (
        <div className={'result ' + (job.status === 'failed' ? 'error' : '')} style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
          <div><b>{job.phase}</b> — {job.message}</div>
          {job.status === 'running' && <div>{job.frames} frames read, {job.samples} clock reads</div>}
          {job.status === 'done' && <div>Placed {job.placed} plays. They're timed now — filter and export them on the Plays tab.</div>}
        </div>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  )
}

function FilmLibrary({ films, onChanged }) {
  const [available, setAvailable] = useState([])
  const [sourceTypes, setSourceTypes] = useState(Object.keys(SOURCE_LABELS))
  const [path, setPath] = useState('')
  const [label, setLabel] = useState('')
  const [stype, setStype] = useState('broadcast')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refreshAvailable = () => getLibraryFilms().then(setAvailable).catch(() => {})
  useEffect(() => {
    refreshAvailable()
    getSourceTypes().then(setSourceTypes).catch(() => {})
  }, [films])

  const add = async () => {
    setError(''); setBusy(true)
    try {
      await registerFilm({ path, label: label || null, source_type: stype })
      setPath(''); setLabel('')
      onChanged()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const remove = async (id) => {
    if (!window.confirm('Remove this film and its plays from the index? (The file stays on disk.)')) return
    try { await deleteFilm(id); onChanged() } catch (e) { setError(e.message) }
  }

  return (
    <div className="films-view">
      <div className="film-add">
        <h2>Add film</h2>
        <label>File in library folder</label>
        <div className="row">
          <input value={path} onChange={(e) => setPath(e.target.value)}
            placeholder="e.g. 2026/mines-vs-csc.mp4" style={{ flex: 1 }} />
          <select value="" onChange={(e) => e.target.value && setPath(e.target.value)} style={{ width: '9rem' }}>
            <option value="">browse…</option>
            {available.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <div className="row">
          <div style={{ flex: 1 }}>
            <label>Label</label>
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="CSC @ Mines" style={{ width: '100%' }} />
          </div>
          <div style={{ flex: 1 }}>
            <label>Source type</label>
            <select value={stype} onChange={(e) => setStype(e.target.value)} style={{ width: '100%' }}>
              {sourceTypes.map((s) => <option key={s} value={s}>{sourceLabel(s)}</option>)}
            </select>
          </div>
        </div>
        <button className="primary" onClick={add} disabled={busy || !path}>Register film</button>
        <span className="hint2">Probes fps · codec · interlace · duration. The file must be inside the library folder.</span>
        {error && <div className="error">{error}</div>}
      </div>

      <PbpImport films={films} onChanged={onChanged} />
      <AlignPanel films={films} onChanged={onChanged} />

      <div className="film-list">
        <h2>Films in library ({films.length})</h2>
        {films.length === 0 && <div className="empty">No films yet. Add one above.</div>}
        {films.map((f) => (
          <div className="film-row" key={f.id}>
            <div>
              <div className="fname">{f.label || f.path}</div>
              <div className="fmeta">
                {sourceLabel(f.source_type)} · {f.plays} plays
                {f.fps ? ` · ${Math.round(f.fps)}fps` : ''}
                {f.interlaced === 1 ? ' · interlaced' : ''}
                <span className="fpath"> · {f.path}</span>
              </div>
            </div>
            <button className="x" onClick={() => remove(f.id)}>remove</button>
          </div>
        ))}
      </div>
    </div>
  )
}

// -- App --------------------------------------------------------------------

export default function App() {
  const [films, setFilms] = useState([])
  const [tagKeys, setTagKeys] = useState([])
  const [form, setForm] = useState(emptyForm)
  const [filter, setFilter] = useState({ where: [] })
  const [plays, setPlays] = useState([])
  const [selected, setSelected] = useState(null)
  const [presets, setPresets] = useState([])
  const [view, setView] = useState('plays')
  const [error, setError] = useState('')

  const refreshPresets = () => getPresets().then(setPresets).catch(() => {})
  const refreshFilms = () => getFilms().then(setFilms).catch((e) => setError(e.message))

  useEffect(() => {
    refreshFilms()
    getTagKeys().then(setTagKeys).catch(() => {})
    getPlays({ where: [] }).then((res) => setPlays(res.plays)).catch(() => {})
    refreshPresets()
  }, [])

  // After a film is added/removed, refresh films + tag keys + the play grid.
  const onFilmsChanged = async () => {
    await refreshFilms()
    getTagKeys().then(setTagKeys).catch(() => {})
    try { setPlays((await getPlays(filter)).plays) } catch { /* ignore */ }
  }

  const applyForm = async (f) => {
    const q = formToQuery(f); setFilter(q); setError('')
    try {
      const res = await getPlays(q)
      setPlays(res.plays)
      setSelected(null)
    } catch (e) { setError(e.message) }
  }

  const loadPreset = async (name) => {
    const p = presets.find((x) => x.name === name)
    if (!p) return
    const nf = filterToForm(p.filter)
    setForm(nf)
    await applyForm(nf)
  }
  const savePresetNow = async (name) => {
    try { await savePreset({ name, filter: formToFilter(form) }); await refreshPresets() }
    catch (e) { setError(e.message) }
  }
  const deletePresetNow = async (name) => {
    try { await deletePreset(name); await refreshPresets() }
    catch (e) { setError(e.message) }
  }
  const exportPresetsNow = async () => {
    try {
      const pack = await exportPresets()
      const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'cutup-presets.json'; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { setError(e.message) }
  }
  const importPresetsNow = async (data, errMsg) => {
    if (errMsg) { setError(errMsg); return }
    const list = Array.isArray(data) ? data : (data && data.presets) || []
    try { await importPresets(list); await refreshPresets() }
    catch (e) { setError(e.message) }
  }

  const onPlayChange = (updated) => {
    setPlays((ps) => ps.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)))
    setSelected((s) => (s && s.id === updated.id ? { ...s, ...updated } : s))
  }

  return (
    <div className="app">
      <header>
        <h1>Pigskin Cutter</h1>
        <nav>
          <button className={view === 'plays' ? 'active' : ''} onClick={() => setView('plays')}>Plays</button>
          <button className={view === 'films' ? 'active' : ''} onClick={() => setView('films')}>Films</button>
          <button className={view === 'tag' ? 'active' : ''} onClick={() => setView('tag')}>Tag pass</button>
          <button className={view === 'help' ? 'active' : ''} onClick={() => setView('help')}>Help</button>
        </nav>
        <span className="films">{films.length} film(s), {films.reduce((n, f) => n + (f.plays || 0), 0)} plays</span>
      </header>
      {error && <div className="error banner">{error}</div>}
      {view === 'films' ? (
        <FilmLibrary films={films} onChanged={onFilmsChanged} />
      ) : view === 'tag' ? (
        <TagPass films={films} onTagged={onFilmsChanged} />
      ) : view === 'help' ? (
        <Help />
      ) : (
      <div className="cols">
        <aside>
          <PresetBar presets={presets} onLoad={loadPreset} onSave={savePresetNow} onDelete={deletePresetNow}
            onExport={exportPresetsNow} onImport={importPresetsNow} />
          <FilterBuilder form={form} setForm={setForm} tagKeys={tagKeys} films={films}
            onApply={() => applyForm(form)} />
          <ExportPanel filter={filter} count={plays.length} />
        </aside>
        <main>
          <PlayGrid plays={plays} selectedId={selected?.id} onSelect={setSelected} />
        </main>
        <section className="right">
          <Preview play={selected} onChange={onPlayChange} />
        </section>
      </div>
      )}
    </div>
  )
}
