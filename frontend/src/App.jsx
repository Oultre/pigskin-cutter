import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  getFilms, getTagKeys, getTagValues, getPlays, patchPlay, postExport, streamUrl,
  getPresets, savePreset, deletePreset,
} from './api.js'

const OPS = ['=', '!=', '>=', '<=', '>', '<', 'exists']
const emptyForm = { preds: [], film: '', source: '', minConf: '', confirmedOnly: false }

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

function PresetBar({ presets, onLoad, onSave, onDelete }) {
  const [name, setName] = useState('')
  const [sel, setSel] = useState('')
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
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = async (dry) => {
    setError(''); setBusy(true); setResult(null)
    try {
      setResult(await postExport({ ...filter, out, dry_run: dry }))
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="panel export">
      <h2>Export ({count} plays)</h2>
      <input placeholder="output folder" value={out} onChange={(e) => setOut(e.target.value)} />
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

// -- App --------------------------------------------------------------------

export default function App() {
  const [films, setFilms] = useState([])
  const [tagKeys, setTagKeys] = useState([])
  const [form, setForm] = useState(emptyForm)
  const [filter, setFilter] = useState({ where: [] })
  const [plays, setPlays] = useState([])
  const [selected, setSelected] = useState(null)
  const [presets, setPresets] = useState([])
  const [error, setError] = useState('')

  const refreshPresets = () => getPresets().then(setPresets).catch(() => {})

  useEffect(() => {
    getFilms().then(setFilms).catch((e) => setError(e.message))
    getTagKeys().then(setTagKeys).catch(() => {})
    getPlays({ where: [] }).then((res) => setPlays(res.plays)).catch(() => {})
    refreshPresets()
  }, [])

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

  const onPlayChange = (updated) => {
    setPlays((ps) => ps.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)))
    setSelected((s) => (s && s.id === updated.id ? { ...s, ...updated } : s))
  }

  return (
    <div className="app">
      <header>
        <h1>gridiron-cutup</h1>
        <span className="films">{films.length} film(s), {films.reduce((n, f) => n + (f.plays || 0), 0)} plays</span>
      </header>
      {error && <div className="error banner">{error}</div>}
      <div className="cols">
        <aside>
          <PresetBar presets={presets} onLoad={loadPreset} onSave={savePresetNow} onDelete={deletePresetNow} />
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
    </div>
  )
}
