import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  getFilms, getTagKeys, getTagValues, getPlays, patchPlay, postExport, streamUrl, thumbUrl,
  getPresets, savePreset, deletePreset, getSourceTypes, getLibraryFilms, registerFilm,
  deleteFilm, importFilm, importPbp, findSchedule, startAlign, startDetect, startVerify, getJob, getJobs, getExportSizes, startReel,
  getConfig, saveConfig, findNflGames, importNflPbp, matchPlays,
} from './api.js'
import { PAD_LABELS, padKind, useGamepad } from './gamepad.js'

// Native folder picker (desktop app only); returns a path or null.
const hasFolderPicker = () => typeof window !== 'undefined' && window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder
async function pickFolder() {
  if (!hasFolderPicker()) return null
  try { return await window.pywebview.api.pick_folder() } catch { return null }
}
import TagPass from './TagPass.jsx'
import Help from './Help.jsx'
import { getTheme, setTheme } from './theme.js'
import { switchLibrary } from './api.js'

const OPS = ['=', '!=', '>=', '<=', '>', '<', 'exists']
const emptyForm = { preds: [], film: '', source: '', minConf: '', confirmedOnly: false }
const SOURCE_LABELS = {
  hudl_clip: 'Hudl clips (pre-cut)', hudl_game: 'Hudl game film', broadcast: 'TV broadcast',
  all22: 'All-22 (NFL / NCAA)', drone: 'Drone (DJI)',
}
const sourceLabel = (s) => SOURCE_LABELS[s] || s

function fmt(t) {
  if (t === null || t === undefined) return '—'
  const s = Math.max(0, t)
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
  const p = (n, w = 2) => String(n).padStart(w, '0')
  return `${p(h)}:${p(m)}:${sec.toFixed(1).padStart(4, '0')}`
}
const ddText = (p) => {
  const d = p.tags.down, dist = p.tags.distance
  if (d && dist) return `${d} & ${dist}`
  if (p.tags.play_type) return p.tags.play_type
  return p.play_no != null ? `Play ${p.play_no}` : 'Play'
}

// -- filter <-> preset shape (shared with the CLI) --------------------------
function predToWhere(p) { return p.op === 'exists' ? `${p.key} exists` : `${p.key}${p.op}${p.value}` }
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
    source: f.source || '', minConf: f.min_confidence != null ? String(f.min_confidence) : '',
    confirmedOnly: !!f.confirmed_only,
  }
}
function formToQuery(form, filmId) {
  const f = formToFilter(form)
  return {
    where: f.where, film: f.film || filmId || undefined, source: f.source || undefined,
    minConfidence: f.min_confidence, confirmedOnly: f.confirmed_only,
  }
}

// -- icons ------------------------------------------------------------------
const I = {
  scissors: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="8.5" y1="7.5" x2="20" y2="16"/><line x1="8.5" y1="16.5" x2="20" y2="8"/></svg>,
  scan: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M7 20h10"/><path d="M8 9l3 2.5L8 14"/><line x1="13" y1="14" x2="16" y2="14"/></svg>,
  data: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/></svg>,
  reel: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.4"/><circle cx="12" cy="6" r="1.4"/><circle cx="12" cy="18" r="1.4"/><circle cx="6" cy="12" r="1.4"/><circle cx="18" cy="12" r="1.4"/></svg>,
  film: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><line x1="12" y1="11" x2="12" y2="16"/><line x1="9.5" y1="13.5" x2="14.5" y2="13.5"/></svg>,
  pad: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="2" y="7" width="20" height="10" rx="5"/><line x1="7" y1="12" x2="9" y2="12"/><line x1="8" y1="11" x2="8" y2="13"/><circle cx="16" cy="11" r="1"/><circle cx="18" cy="13" r="1"/></svg>,
  play: <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>,
  check: <svg viewBox="0 0 24 24"><path d="M5 12l4 4 10-10" fill="none" stroke="currentColor" strokeWidth="2.4"/></svg>,
  up: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3v10m0 0l-3.5-3.5M12 13l3.5-3.5M5 17v2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2" fill="none" stroke="currentColor" strokeWidth="1.7"/></svg>,
}

// ==========================================================================
export default function App() {
  const [films, setFilms] = useState([])
  const [filmId, setFilmId] = useState('')            // active film context ('' = all)
  const [view, setView] = useState('home')
  const [tagKeys, setTagKeys] = useState([])
  const [sizes, setSizes] = useState([])
  const [presets, setPresets] = useState([])
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [theme, setThemeState] = useState(getTheme())
  const flipTheme = (t) => setThemeState(setTheme(t))

  const flash = (m) => { setToast(m); window.clearTimeout(flash._t); flash._t = window.setTimeout(() => setToast(''), 3500) }
  const refreshFilms = () => getFilms().then(setFilms).catch((e) => setError(e.message))
  const refreshPresets = () => getPresets().then(setPresets).catch(() => {})

  useEffect(() => {
    refreshFilms(); refreshPresets()
    getTagKeys().then(setTagKeys).catch(() => {})
    getExportSizes().then(setSizes).catch(() => {})
  }, [])

  const onDataChanged = async () => {
    await refreshFilms()
    getTagKeys().then(setTagKeys).catch(() => {})
  }

  const totalPlays = films.reduce((n, f) => n + (f.plays || 0), 0)
  const activeFilm = films.find((f) => String(f.id) === String(filmId))

  const nav = (v) => { setError(''); setView(v) }

  return (
    <div className="app">
      <header className="topbar">
        <button className="home-btn" onClick={() => nav('home')} title="Home">
          <img src="/logo.png" alt="" /><b>Pigskin Cutter</b>
        </button>
        {view !== 'home' && <span className="crumb">/ <b>{titleFor(view)}</b></span>}
        <span className="spacer" />
        {view !== 'home' && (
          <select className="film-sel" value={filmId} onChange={(e) => setFilmId(e.target.value)}>
            <option value="">All films</option>
            {films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
          </select>
        )}
        <span className="stat">{films.length} film{films.length !== 1 ? 's' : ''} · {totalPlays} plays</span>
        <button className="gear" title={theme === 'light' ? 'Switch to dark' : 'Switch to light'} aria-label="Toggle theme"
          onClick={() => flipTheme(theme === 'light' ? 'dark' : 'light')}>
          {theme === 'light'
            ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
            : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>}
        </button>
        <button className="gear" title="Settings" onClick={() => nav('settings')} aria-label="Settings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 8 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H2a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 3.6 8a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 8 3.6a1.65 1.65 0 0 0 1-1.51V2a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 20.4 8c.14.31.22.65.22 1a1.65 1.65 0 0 0 1.51 1H22a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>
      </header>

      {error && <div className="err-banner">{error}</div>}

      <div className="body">
        {view === 'home' && <Home nav={nav} />}
        {view === 'plays' && (
          <PlaysScreen films={films} filmId={filmId} tagKeys={tagKeys} presets={presets} sizes={sizes}
            refreshPresets={refreshPresets} setError={setError} flash={flash} nav={nav} />
        )}
        {view === 'data' && <DataGrab films={films} filmId={filmId} onChanged={onDataChanged} flash={flash} nav={nav} />}
        {view === 'detect' && <AutoDetect films={films} filmId={filmId} onChanged={onDataChanged} flash={flash} nav={nav} />}
        {view === 'library' && <FilmLibrary films={films} onChanged={onDataChanged} flash={flash} nav={nav} />}
        {view === 'tag' && <div className="screen wide"><TagPass films={films} onTagged={onDataChanged} /></div>}
        {view === 'settings' && <Settings nav={nav} flash={flash} setError={setError} theme={theme} flipTheme={flipTheme} />}
        {view === 'help' && <Help />}
      </div>

      {toast && <div className="toast good">{toast}</div>}
    </div>
  )
}
function titleFor(v) {
  return { plays: 'Clip Cutter', data: 'Data Grab', detect: 'Auto Detect',
    library: 'Film Library', tag: 'Tag Pass', settings: 'Settings', help: 'Coach’s Guide' }[v] || ''
}

// -- SETTINGS ---------------------------------------------------------------
function FolderField({ label, value, onChange, placeholder, hint }) {
  const native = hasFolderPicker()
  return (
    <div style={{ marginBottom: 16 }}>
      <label className="fld">{label}</label>
      <div className="row" style={{ gap: 8 }}>
        <input className="inp" value={value || ''}
          placeholder={native ? 'Click Browse to choose a folder…' : placeholder}
          readOnly={native} onChange={native ? undefined : (e) => onChange(e.target.value)}
          onClick={native ? async () => { const p = await pickFolder(); if (p) onChange(p) } : undefined}
          style={{ flex: 1, cursor: native ? 'pointer' : 'text' }} />
        <button className="btn" onClick={async () => { const p = await pickFolder(); if (p) onChange(p) }} disabled={!native}>Browse…</button>
        {value && <button className="btn ghost sm" onClick={() => onChange('')} title="Clear">×</button>}
      </div>
      {hint && <div className="hint2">{hint}</div>}
    </div>
  )
}

function ThemeSwitch({ theme, onChange }) {
  const light = theme === 'light'
  return (
    <div className="theme-switch">
      <span className={!light ? 'on' : ''}>Dark</span>
      <button role="switch" aria-checked={light} className={'sw' + (light ? ' light' : '')}
        onClick={() => onChange(light ? 'dark' : 'light')} aria-label="Toggle light mode">
        <span className="knob" />
      </button>
      <span className={light ? 'on' : ''}>Light</span>
    </div>
  )
}

function Settings({ nav, flash, setError, theme, flipTheme }) {
  const [cfg, setCfg] = useState(null)
  const [clips, setClips] = useState('')
  const [reels, setReels] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    getConfig().then((c) => { setCfg(c); setClips(c.clips_dir || ''); setReels(c.reels_dir || '') }).catch((e) => setError(e.message))
  }, [])
  const save = async () => {
    setBusy(true); setError('')
    try { await saveConfig({ clips_dir: clips, reels_dir: reels }); flash('Settings saved') }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const switchLib = async () => {
    const p = await pickFolder()
    if (!p) return
    if (!window.confirm(`Open this folder as your library?\n\n${p}\n\nAn empty folder starts a fresh library. The app will reload.`)) return
    setError('')
    try { await switchLibrary(p); window.location.reload() }
    catch (e) { setError(e.message) }
  }
  const library = cfg && (cfg.library || null)
  return (
    <div className="screen">
      <div className="scr-bar"><span className="back" onClick={() => nav('home')}>‹ Home</span><h2>Settings</h2></div>
      <div className="form-card">
        <h4 style={{ margin: '0 0 4px' }}>Where things are saved</h4>
        <p className="hint3">Set these once and they fill in automatically. You can still pick a different folder at export time.</p>
        <FolderField label="Default folder for clips" value={clips} onChange={setClips}
          placeholder="e.g. C:\Coaching\Cutups" hint="Where “Cut clips” saves by default. Leave blank to type it each time." />
        <FolderField label="Default folder for reels" value={reels} onChange={setReels}
          placeholder="(inside your library: …\Pigskin Cutter\reels)" hint="Where highlight reels are saved. Blank uses a “reels” folder inside your library." />
        <button className="btn primary" style={{ marginTop: 6 }} disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save settings'}</button>
        {!hasFolderPicker() && <div className="hint2" style={{ marginTop: 8 }}>Tip: in the desktop app a “Browse…” button lets you pick folders without typing.</div>}
      </div>
      <div className="form-card">
        <h4 style={{ margin: '0 0 4px' }}>Your film library</h4>
        <p className="hint3">Your games and index live here. Films you add are copied inside this folder so everything stays together.</p>
        <div className="row" style={{ gap: 8 }}>
          <input className="inp" value={library || ''} readOnly style={{ flex: 1, opacity: 0.85 }} />
          <button className="btn" disabled={!hasFolderPicker()} onClick={switchLib}>Switch…</button>
        </div>
        <div className="hint2">Pick another library folder to open it — or an empty folder to start a fresh one. The app reloads into it.</div>
      </div>
      <div className="form-card">
        <h4 style={{ margin: '0 0 4px' }}>Appearance</h4>
        <p className="hint3">Prefer a lighter look? Flip it here. Your choice is remembered.</p>
        <ThemeSwitch theme={theme} onChange={flipTheme} />
      </div>
    </div>
  )
}

// -- HOME -------------------------------------------------------------------
function Home({ nav }) {
  const cards = [
    ['plays', 'MANUAL', I.scissors, 'Clip Cutter', 'Find the plays you want, watch and trim them, and export clean clips — in any social size.'],
    ['detect', 'AUTO-DETECT', I.scan, 'Auto Detect', 'Find every play automatically — from the broadcast game clock or scene cuts on All-22 film.'],
    ['data', 'DATA', I.data, 'Data Grab', 'Pull official NFL & college play-by-play and line it up with your film.'],
    ['plays', 'REEL', I.reel, 'Build Reel', 'Stitch chosen plays into one highlight reel with labels — vertical for Reels/TikTok.'],
    ['library', 'LIBRARY', I.film, 'Film Library', 'Add a game — browse or drag & drop — and manage your film.'],
  ]
  return (
    <div className="home">
      <div className="brand">
        <img src="/logo.png" alt="Pigskin Cutter" />
        <div className="tag">Choose your workflow</div>
        <div className="sub">Everything runs on your computer. No accounts, no upload, no waiting.</div>
      </div>
      <div className="cards">
        {cards.map(([v, lbl, ic, h, p], i) => (
          <button className="card" key={i} onClick={() => nav(v)}>
            <span className="lbl">{lbl}</span>
            <span className="ic">{ic}</span>
            <h3>{h}</h3><p>{p}</p>
          </button>
        ))}
      </div>
      <div className="home-foot">
        <a onClick={() => nav('tag')}>Tag a game by hand</a>
        <a onClick={() => nav('help')}>Coach&rsquo;s guide</a>
      </div>
    </div>
  )
}

// -- PLAYS (Clip Cutter + grid + presets + export + reel) -------------------
function PlaysScreen({ films, filmId, tagKeys, presets, sizes, refreshPresets, setError, flash, nav }) {
  const [form, setForm] = useState(emptyForm)
  const [plays, setPlays] = useState([])
  const [active, setActive] = useState(null)          // play open in preview
  const [selected, setSelected] = useState(() => new Set())
  const [activePreset, setActivePreset] = useState('')
  const [showFilter, setShowFilter] = useState(false)
  const [counts, setCounts] = useState({})            // preset name -> count
  const [reelOpen, setReelOpen] = useState(false)

  const load = async (q) => {
    try { const res = await getPlays(q); setPlays(res.plays); setActive(null); setSelected(new Set()) }
    catch (e) { setError(e.message) }
  }
  useEffect(() => { load(formToQuery(form, filmId)) }, [filmId])

  // preview counts for each preset (cheap enough for a coach's library)
  useEffect(() => {
    let alive = true
    ;(async () => {
      const c = {}
      for (const p of presets) {
        try { const r = await getPlays({ ...queryFromPreset(p), film: filmId || undefined }); c[p.name] = r.count } catch { /* ignore */ }
      }
      if (alive) setCounts(c)
    })()
    return () => { alive = false }
  }, [presets, filmId])

  const applyPreset = (p) => {
    setActivePreset(p ? p.name : '')
    const f = p ? filterToForm(p.filter) : emptyForm
    setForm(f); load(formToQuery(f, filmId))
  }
  const applyForm = () => { setActivePreset(''); load(formToQuery(form, filmId)) }
  const applyVerified = () => {
    setActivePreset('__verified')
    const f = { preds: [{ key: 'verify', op: '=', value: 'match' }], film: '', source: '', minConf: '', confirmedOnly: false }
    setForm(f); load(formToQuery(f, filmId))
  }
  const anyVerified = plays.some((p) => p.tags.verify)

  const toggleSel = (id) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const clearSel = () => setSelected(new Set())
  const selectAll = () => setSelected(new Set(plays.map((p) => p.id)))

  const onPlayChange = (u) => {
    setPlays((ps) => ps.map((p) => (p.id === u.id ? { ...p, ...u } : p)))
    setActive((a) => (a && a.id === u.id ? { ...a, ...u } : a))
  }
  const savePresetNow = async () => {
    const name = window.prompt('Save this filter as a preset named:')
    if (!name) return
    try { await savePreset({ name: name.trim(), filter: formToFilter(form) }); await refreshPresets(); flash('Preset saved') }
    catch (e) { setError(e.message) }
  }

  const filterQuery = formToQuery(form, filmId)
  return (
    <div className="screen wide">
      <div className="scr-bar">
        <span className="back" onClick={() => nav('home')}>‹ Home</span>
        <h2>Clip Cutter <span className="count">· {plays.length} play{plays.length !== 1 ? 's' : ''}</span></h2>
        <div className="right">
          <button className="btn ghost sm" onClick={() => setShowFilter((v) => !v)}>{showFilter ? 'Hide filter' : 'Advanced filter'}</button>
        </div>
      </div>

      <div className="presets">
        <span className="plabel">Suggested cuts</span>
        <span className={'chip' + (activePreset === '' ? ' on' : '')} onClick={() => applyPreset(null)}>All plays</span>
        {anyVerified && <span className={'chip' + (activePreset === '__verified' ? ' on' : '')} onClick={applyVerified} title="Only plays whose down & distance matched the video">✓ Verified only</span>}
        {presets.map((p) => (
          <span key={p.name} className={'chip' + (activePreset === p.name ? ' on' : '')} onClick={() => applyPreset(p)}>
            {p.name}{counts[p.name] != null && <span className="n">{counts[p.name]}</span>}
          </span>
        ))}
      </div>

      <div className="plays-layout">
        <div>
          {showFilter && (
            <div className="side-panel">
              <h3>Filter</h3>
              <FilterBuilder form={form} setForm={setForm} tagKeys={tagKeys} films={films} onApply={applyForm} />
              <button className="btn ghost sm" style={{ marginTop: 8 }} onClick={savePresetNow}>Save as preset</button>
            </div>
          )}
          <div className="side-panel">
            <h3>Export clips</h3>
            <ExportPanel filter={filterQuery} count={plays.length} sizes={sizes} flash={flash} setError={setError} />
          </div>
        </div>

        <div>
          <div className="sheet">
            {plays.length === 0 && (
              <div className="sheet-empty">
                <div style={{ fontSize: 15, color: 'var(--muted)' }}>No plays here yet.</div>
                <div className="hint2">Get plays onto this film, then come back to cut and export them:</div>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 12, flexWrap: 'wrap' }}>
                  <button className="btn" onClick={() => nav('tag')}>✋ Mark plays by hand</button>
                  <button className="btn" onClick={() => nav('detect')}>⚡ Auto Detect</button>
                  <button className="btn" onClick={() => nav('data')}>📋 Data Grab</button>
                </div>
                <div className="hint2" style={{ marginTop: 10 }}>…or pick a different film, or the “All plays” chip above.</div>
              </div>
            )}
            {plays.map((p) => (
              <PlayCard key={p.id} p={p} selected={selected.has(p.id)} active={active?.id === p.id}
                onOpen={() => setActive(p)} onToggle={() => toggleSel(p.id)} />
            ))}
          </div>
          {selected.size > 0 && (
            <div className="selbar">
              <span className="s"><b>{selected.size}</b> selected</span>
              <div className="right">
                <button className="btn ghost sm" onClick={selectAll}>Select all</button>
                <button className="btn ghost sm" onClick={clearSel}>Clear</button>
                <button className="btn primary" onClick={() => setReelOpen(true)}>Build reel from selection</button>
              </div>
            </div>
          )}
        </div>

        <div className="preview-col">
          <div className="side-panel">
            <Preview play={active} onChange={onPlayChange} />
          </div>
        </div>
      </div>

      {reelOpen && (
        <ReelModal sizes={sizes} playIds={[...selected]} onClose={() => setReelOpen(false)} flash={flash} setError={setError} />
      )}
    </div>
  )
}

function PlayCard({ p, selected, active, onOpen, onToggle }) {
  const [imgOk, setImgOk] = useState(true)
  const timed = p.t_start != null && p.t_end != null
  const vf = p.tags.verify
  const badge = vf === 'match' ? ['good', 'VERIFIED']
    : vf === 'mismatch' ? ['low', 'REVIEW']
    : vf === 'unread' ? ['neutral', 'UNCHECKED']
    : (p.source === 'pbp' || p.source === 'ocr' || p.source === 'detected')
      ? (p.confidence < 0.8 ? ['low', 'CHECK'] : ['mach', p.source === 'ocr' ? 'OCR' : 'AUTO'])
      : ['good', 'MATCHED']
  const dur = timed ? (p.t_end - p.t_start).toFixed(1) + 's' : null
  return (
    <div className={'play' + (selected ? ' sel' : '') + (active ? ' active' : '')} onClick={onOpen}>
      <div className="thumb">
        {timed && imgOk
          ? <img src={thumbUrl(p.id)} alt="" loading="lazy" onError={() => setImgOk(false)} />
          : <span className="ph">{I.play}</span>}
        {dur && <span className="dur">{dur}</span>}
      </div>
      <div className="check" onClick={(e) => { e.stopPropagation(); onToggle() }}>{I.check}</div>
      <div className="meta" onClick={(e) => { e.stopPropagation(); onToggle() }}>
        <span className="no">#{p.play_no ?? '—'}</span>
        <span className="dd">{ddText(p)}</span>
        <span className={'badge ' + badge[0]}>{badge[1]}</span>
      </div>
    </div>
  )
}

function FilterBuilder({ form, setForm, tagKeys, films, onApply }) {
  const [vals, setVals] = useState({})
  const add = () => setForm((f) => ({ ...f, preds: [...f.preds, { key: tagKeys[0] || '', op: '=', value: '' }] }))
  const upd = (i, patch) => setForm((f) => ({ ...f, preds: f.preds.map((x, j) => (j === i ? { ...x, ...patch } : x)) }))
  const rm = (i) => setForm((f) => ({ ...f, preds: f.preds.filter((_, j) => j !== i) }))
  const loadVals = async (k) => { if (!k || vals[k]) return; try { const vv = await getTagValues(k); setVals((v) => ({ ...v, [k]: vv })) } catch { /* */ } }
  return (
    <>
      {form.preds.map((p, i) => (
        <div className="pred" key={i}>
          <select value={p.key} onChange={(e) => { upd(i, { key: e.target.value }); loadVals(e.target.value) }}>
            {!tagKeys.includes(p.key) && p.key ? <option value={p.key}>{p.key}</option> : null}
            {tagKeys.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <select value={p.op} onChange={(e) => upd(i, { op: e.target.value })} style={{ flex: '0 0 auto', width: '3.6rem' }}>
            {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          {p.op !== 'exists' && (
            <input list={`v${i}`} value={p.value} placeholder="value"
              onFocus={() => loadVals(p.key)} onChange={(e) => upd(i, { value: e.target.value })} />
          )}
          <datalist id={`v${i}`}>{(vals[p.key] || []).map((v) => <option key={v} value={v} />)}</datalist>
          <button className="x" onClick={() => rm(i)}>×</button>
        </div>
      ))}
      <button className="btn ghost sm" onClick={add}>+ condition</button>
      <div className="meta-row">
        <label>Source
          <select className="inp" value={form.source} onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}>
            <option value="">any</option>{['hudl', 'tagged', 'detected', 'ocr', 'pbp'].map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label>Min confidence
          <input className="inp" type="number" step="0.1" min="0" max="1" style={{ width: '4.5rem' }}
            value={form.minConf} onChange={(e) => setForm((f) => ({ ...f, minConf: e.target.value }))} />
        </label>
        <label className="chk"><input type="checkbox" checked={form.confirmedOnly}
          onChange={(e) => setForm((f) => ({ ...f, confirmedOnly: e.target.checked }))} /> confirmed only</label>
      </div>
      <button className="btn primary" style={{ width: '100%' }} onClick={onApply}>Apply filter</button>
    </>
  )
}

function Preview({ play, onChange }) {
  const v = useRef(null)
  useEffect(() => {
    const el = v.current
    if (el && play && play.t_start != null) {
      const seek = () => { el.currentTime = play.t_start }
      el.readyState >= 1 ? seek() : el.addEventListener('loadedmetadata', seek, { once: true })
    }
  }, [play?.id])

  // gamepad control for review + trim. Guards inside so it's safe with no play
  // selected (the hook must be called unconditionally, before the early return).
  const nudge = async (field, d) => { if (play) onChange(await patchPlay(play.id, { [field]: Math.max(0, (play[field] ?? 0) + d) })) }
  const toHead = async (field) => { if (play && v.current) onChange(await patchPlay(play.id, { [field]: v.current.currentTime })) }
  const seekBy = (d) => { const el = v.current; if (el) el.currentTime = Math.max(0, el.currentTime + d) }
  const togglePlay = () => { const el = v.current; if (el) (el.paused ? el.play() : el.pause()) }
  const pad = useGamepad({
    START: togglePlay,
    LB: () => seekBy(-1), RB: () => seekBy(1),
    DLEFT: () => seekBy(-5), DRIGHT: () => seekBy(5),
    A: () => toHead('t_start'), B: () => toHead('t_end'),
    X: () => nudge('t_end', -0.1), Y: () => nudge('t_end', 0.1),
  })

  if (!play) return (
    <div className="pv-empty">
      Click a play to watch and trim it.
      <div className="pad-hint">{pad ? `🎮 ${PAD_LABELS[padKind(pad)].name} controller connected` : '🎮 Have a controller? Press any button to enable it.'}</div>
    </div>
  )
  const L = pad && PAD_LABELS[padKind(pad)]
  return (
    <div className="preview">
      <video ref={v} src={streamUrl(play.film_id)} controls preload="metadata" />
      <div className="pv-body">
        <h3>Play {play.play_no ?? play.id} · {ddText(play)}</h3>
        <div className="nudge">
          <div className="row"><span className="k">start {fmt(play.t_start)}</span>
            {[-0.5, -0.1, 0.1, 0.5].map((d) => <button className="btn sm" key={d} onClick={() => nudge('t_start', d)}>{d > 0 ? '+' : ''}{d}</button>)}
            <button className="btn sm" onClick={() => toHead('t_start')}>= here</button></div>
          <div className="row"><span className="k">end {fmt(play.t_end)}</span>
            {[-0.5, -0.1, 0.1, 0.5].map((d) => <button className="btn sm" key={d} onClick={() => nudge('t_end', d)}>{d > 0 ? '+' : ''}{d}</button>)}
            <button className="btn sm" onClick={() => toHead('t_end')}>= here</button></div>
        </div>
        {L ? (
          <div className="pad-legend">
            <div className="pad-legend-head">🎮 {L.name} controller</div>
            <div className="pad-legend-grid">
              {[[L.START, 'Play / pause'], [`${L.LB} / ${L.RB}`, 'Seek 1s'], ['D-pad ← →', 'Seek 5s'],
                [L.A, 'Set start here'], [L.B, 'Set end here'], [`${L.X} / ${L.Y}`, 'Trim end ∓0.1']].map(([btn, act]) => (
                <div className="pad-legend-row" key={act}><span className="pad-btn">{btn}</span><span className="pad-act">{act}</span></div>
              ))}
            </div>
          </div>
        ) : (
          <div className="pad-hint">🎮 Have a controller? Press any button to enable gamepad trimming.</div>
        )}
        <div className="tags">{Object.entries(play.tags).slice(0, 12).map(([k, val]) => <span className="tag" key={k}>{k} <b>{val}</b></span>)}</div>
      </div>
    </div>
  )
}

function ExportPanel({ filter, count, sizes, flash, setError }) {
  const [out, setOut] = useState('')
  const [size, setSize] = useState('source')
  const [logo, setLogo] = useState('')
  const [pos, setPos] = useState('bottom-right')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  // pre-fill the output folder from the saved default (Settings)
  useEffect(() => { getConfig().then((c) => { if (c.clips_dir) setOut((o) => o || c.clips_dir) }).catch(() => {}) }, [])
  const run = async (dry) => {
    setBusy(true); setResult(null); setError('')
    try {
      const body = { ...filter, out, dry_run: dry, size: size === 'source' ? null : size }
      if (logo) { body.logo = logo; body.logo_position = pos }
      const r = await postExport(body); setResult(r)
      if (!dry) flash(`Exported ${r.count} clip${r.count !== 1 ? 's' : ''}`)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="export">
      <div className="row" style={{ gap: 8 }}>
        <input className="inp" value={out}
          placeholder={hasFolderPicker() ? 'Click Browse to choose a folder…' : 'output folder (e.g. C:\\cutups)'}
          readOnly={hasFolderPicker()} onChange={hasFolderPicker() ? undefined : (e) => setOut(e.target.value)}
          onClick={hasFolderPicker() ? async () => { const p = await pickFolder(); if (p) setOut(p) } : undefined}
          style={{ flex: 1, cursor: hasFolderPicker() ? 'pointer' : 'text' }} />
        {hasFolderPicker() && <button className="btn" onClick={async () => { const p = await pickFolder(); if (p) setOut(p) }}>Browse…</button>}
      </div>
      <label className="fld">Size / platform</label>
      <select className="inp full" value={size} onChange={(e) => setSize(e.target.value)}>
        {sizes.map((s) => <option key={s.key} value={s.key}>{s.label} — {s.platform}</option>)}
      </select>
      <label className="fld">Logo / watermark (optional)</label>
      <div className="row">
        <input className="inp" style={{ flex: 2 }} placeholder="logo image path" value={logo} onChange={(e) => setLogo(e.target.value)} />
        <select className="inp" style={{ flex: 1 }} value={pos} disabled={!logo} onChange={(e) => setPos(e.target.value)}>
          <option value="bottom-right">BR</option><option value="bottom-left">BL</option>
          <option value="top-right">TR</option><option value="top-left">TL</option><option value="center">center</option>
        </select>
      </div>
      {(logo || size !== 'source') && <div className="hint">Re-encodes each clip (slower than a plain cut).</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn" disabled={busy || !out} onClick={() => run(true)}>Dry run</button>
        <button className="btn primary" disabled={busy || !out} onClick={() => run(false)}>Cut {count} clip{count !== 1 ? 's' : ''}</button>
      </div>
      {result && (
        <div className="result">{result.dry_run ? 'Dry run' : 'Done'}: {result.count} clip(s)
          {result.skipped ? `, ${result.skipped} untimed skipped` : ''}{result.failed ? `, ${result.failed} failed` : ''}
          <ul>{result.clips.slice(0, 10).map((c, i) => <li key={i}>{c.output} ({c.mode})</li>)}</ul>
        </div>
      )}
    </div>
  )
}

function ReelModal({ sizes, playIds, onClose, flash, setError }) {
  const [title, setTitle] = useState('')
  const [label, setLabel] = useState(true)
  const [size, setSize] = useState('landscape_720')
  const [job, setJob] = useState(null)
  const poll = useRef(null)
  useEffect(() => () => clearInterval(poll.current), [])
  const start = async () => {
    setError('')
    try {
      const j = await startReel({ play_ids: playIds, title: title || null, label, size })
      setJob(j)
      poll.current = setInterval(async () => {
        try { const u = await getJob(j.id); setJob(u); if (u.status !== 'running') { clearInterval(poll.current); if (u.status === 'done') flash('Reel ready: ' + (u.output || '')) } }
        catch { clearInterval(poll.current) }
      }, 1500)
    } catch (e) { setError(e.message) }
  }
  const running = job && job.status === 'running'
  return (
    <div className="toast" style={{ width: 'min(440px, 92vw)', bottom: 20 }} onClick={(e) => e.stopPropagation()}>
      <b>Build reel · {playIds.length} plays</b>
      <label className="fld">Title slate (optional)</label>
      <input className="inp full" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. 3rd Down Stops" />
      <label className="fld">Size</label>
      <select className="inp full" value={size} onChange={(e) => setSize(e.target.value)}>
        {sizes.filter((s) => s.key !== 'source').map((s) => <option key={s.key} value={s.key}>{s.label} — {s.platform}</option>)}
      </select>
      <label className="chk" style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '10px 0', fontSize: 13 }}>
        <input type="checkbox" checked={label} onChange={(e) => setLabel(e.target.checked)} /> Burn play labels (down &amp; distance)
      </label>
      {job && <div className={'job' + (job.status === 'failed' ? ' bad' : '')}>
        {job.message}
        {running && job.total > 0 && <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.round(100 * job.done / job.total)}%` }} /></div>}
      </div>}
      <div className="row" style={{ marginTop: 10, gap: 8, display: 'flex' }}>
        <button className="btn" onClick={onClose}>{job && job.status === 'done' ? 'Close' : 'Cancel'}</button>
        <button className="btn primary" disabled={running} onClick={start}>{running ? 'Building…' : 'Build reel'}</button>
      </div>
    </div>
  )
}

// -- DATA GRAB (PBP) --------------------------------------------------------
function DataGrab({ films, filmId, onChanged, flash, nav }) {
  const [film, setFilm] = useState(filmId || '')
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  // find-a-game
  const [league, setLeague] = useState('college')
  const [site, setSite] = useState('')
  const [team, setTeam] = useState('')
  const [season, setSeason] = useState('2024')
  const [games, setGames] = useState(null)
  const [finding, setFinding] = useState(false)
  const [nflGame, setNflGame] = useState('')
  const [nflJob, setNflJob] = useState(null)
  const poll = useRef(null)
  useEffect(() => () => clearInterval(poll.current), [])

  const isNfl = league === 'nfl'
  const picked = isNfl ? nflGame : source
  const switchLeague = (l) => {
    setLeague(l); setGames(null); setResult(null); setError('')
    setNflGame(''); setSource(''); setNflJob(null)
  }

  const find = async () => {
    setFinding(true); setError(''); setGames(null)
    try {
      setGames(isNfl ? await findNflGames(Number(season), team)
                     : await findSchedule(site, Number(season)))
    } catch (e) { setError(e.message) } finally { setFinding(false) }
  }
  const run = async (dry) => {
    setBusy(true); setResult(null); setError('')
    try {
      const r = await importPbp({ film_id: Number(film), source, dry_run: dry })
      setResult(r); if (!dry) { onChanged(); flash(`Imported ${r.imported} plays`) }
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  // The NFL import is a job: the first game of a season downloads the season file.
  const runNfl = async () => {
    setBusy(true); setResult(null); setError(''); setNflJob(null)
    try {
      const started = await importNflPbp({ film_id: Number(film), game_id: nflGame })
      setNflJob(started)
      clearInterval(poll.current)
      poll.current = setInterval(async () => {
        try {
          const u = await getJob(started.id)
          setNflJob(u)
          if (u.status !== 'running') {
            clearInterval(poll.current); setBusy(false)
            if (u.status === 'done') { onChanged(); flash(u.message) }
          }
        } catch { clearInterval(poll.current); setBusy(false) }
      }, 2000)
    } catch (e) { setError(e.message); setBusy(false) }
  }
  return (
    <div className="screen">
      <div className="scr-bar"><span className="back" onClick={() => nav('home')}>‹ Home</span>
        <h2>Data Grab <span className="count">· {isNfl ? 'NFL' : 'college'} play-by-play</span></h2></div>
      <div className="steps">
        <Step n="1" h="Find your game" hint="Pick the league, then find the game — no link to hunt down.">
          <div className="presets" style={{ marginBottom: 10 }}>
            <span className={'chip' + (league === 'college' ? ' on' : '')} onClick={() => switchLeague('college')}>College</span>
            <span className={'chip' + (isNfl ? ' on' : '')} onClick={() => switchLeague('nfl')}>NFL</span>
          </div>

          {!isNfl ? (
            <>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <input className="inp" style={{ flex: 2, minWidth: 200 }} value={site} onChange={(e) => setSite(e.target.value)}
                  placeholder="school website, e.g. minesathletics.com" onKeyDown={(e) => e.key === 'Enter' && site && find()} />
                <input className="inp" style={{ width: 90 }} value={season} onChange={(e) => setSeason(e.target.value)} placeholder="season" />
                <button className="btn" disabled={finding || !site} onClick={find}>{finding ? 'Finding…' : 'Find games'}</button>
              </div>
              <div className="hint2">Works for most <b>college</b> programs (their sites run on the Sidearm platform). Not high-school sites — for those, paste the box-score link below if you have one.</div>
            </>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <input className="inp" style={{ flex: 1, minWidth: 140 }} value={team} onChange={(e) => setTeam(e.target.value.toUpperCase())}
                  placeholder="team, e.g. KC (blank = every game)" onKeyDown={(e) => e.key === 'Enter' && find()} />
                <input className="inp" style={{ width: 90 }} value={season} onChange={(e) => setSeason(e.target.value)} placeholder="season" />
                <button className="btn" disabled={finding} onClick={find}>{finding ? 'Finding…' : 'Find games'}</button>
              </div>
              <div className="hint2">Every NFL game since 1999, from the public <b>nflverse</b> data set. Use the team's abbreviation (KC, PHI, SF). Each NFL play carries its own game clock, so these line up on broadcast film more tightly than college does.</div>
            </>
          )}

          {games && games.length > 0 && (
            <div className="presets" style={{ marginTop: 12 }}>
              {games.map((g) => (isNfl ? (
                <span key={g.game_id} className={'chip' + (nflGame === g.game_id ? ' on' : '')} onClick={() => setNflGame(g.game_id)}>
                  {g.label}
                </span>
              ) : (
                <span key={g.box_id} className={'chip' + (source === g.url ? ' on' : '')} onClick={() => setSource(g.url)}>
                  vs {g.opponent}
                </span>
              )))}
            </div>
          )}
          {games && games.length === 0 && <div className="hint2">No games found — check the season{isNfl ? ' and the team abbreviation.' : '. This school’s site may not be a supported (Sidearm) one; if so, paste a box-score link below.'}</div>}
          {!isNfl && <>
            <label className="fld">or paste a box-score link</label>
            <input className="inp" style={{ width: '100%' }} value={source} onChange={(e) => setSource(e.target.value)}
              placeholder="https://…athletics.com/…/boxscore/24148" />
          </>}
        </Step>
        <Step n="2" h="Attach it to a film" hint="The plays line up on this film's timeline once imported.">
          <select className="inp" value={film} onChange={(e) => setFilm(e.target.value)}>
            <option value="">select film…</option>{films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
          </select>
        </Step>
        <Step n="3" h="Preview, then import" hint={isNfl
          ? 'The first game of a season downloads it (about 18 MB, once) — later games are instant.'
          : 'Preview shows the counts without changing anything.'}>
          <div style={{ display: 'flex', gap: 10 }}>
            {!isNfl && <button className="btn" disabled={busy || !film || !source} onClick={() => run(true)}>Preview</button>}
            <button className="btn primary" disabled={busy || !film || !picked}
              onClick={() => (isNfl ? runNfl() : run(false))}>
              {busy ? 'Working…' : 'Import play-by-play'}
            </button>
          </div>
          {nflJob && <div className={'job' + (nflJob.status === 'failed' ? ' bad' : '')}>
            {nflJob.message}
            {nflJob.status === 'running' && nflJob.phase === 'downloading' &&
              <div className="hint2">Large one-time download — leave this open.</div>}
          </div>}
        </Step>
      </div>
      {error && <div className="error" style={{ maxWidth: 720 }}>{error}</div>}
      {result && (
        <div className="result" style={{ maxWidth: 720 }}>
          {result.dry_run ? 'Preview' : 'Imported'}: {result.count ?? result.imported} plays — {Object.entries(result.possession || {}).map(([t, n]) => `${t}: ${n}`).join(', ')}
          {(result.warnings || []).map((w, i) => <div className="hint" key={i}>{w}</div>)}
          <div className="hint2">Plays land with no cut times yet — use <b>Auto Detect</b> to line them up on the video.</div>
        </div>
      )}
    </div>
  )
}

// -- AUTO DETECT (align; scene-detect coming) -------------------------------
function AutoDetect({ films, filmId, onChanged, flash, nav }) {
  const [film, setFilm] = useState(filmId || '')
  const [film2, setFilm2] = useState(filmId || '')
  const [film3, setFilm3] = useState(filmId || '')
  const [film4, setFilm4] = useState(filmId || '')
  const [sens, setSens] = useState('0.4')
  const [skip, setSkip] = useState('0')
  const [noSpecial, setNoSpecial] = useState(false)
  const [match, setMatch] = useState(null)
  const [matching, setMatching] = useState(false)
  const [job, setJob] = useState(null)      // clock job
  const [job2, setJob2] = useState(null)    // scene job
  const [jobV, setJobV] = useState(null)    // verify job
  const [error, setError] = useState('')
  const polls = useRef({})
  useEffect(() => () => Object.values(polls.current).forEach(clearInterval), [])

  const watch = (id, setter) => {
    clearInterval(polls.current[id])
    polls.current[id] = setInterval(async () => {
      try {
        const u = await getJob(id); setter(u)
        if (u.status !== 'running') { clearInterval(polls.current[id]); if (u.status === 'done') { onChanged(); flash(u.message) } }
      } catch { clearInterval(polls.current[id]) }
    }, 2000)
  }
  const runJob = (starter, setter) => {
    setError(''); setter(null)
    starter().then((j) => { setter(j); watch(j.id, setter) }).catch((e) => setError(e.message))
  }
  // Reconnect to a job still running from a previous visit, so its progress
  // reappears instead of looking like nothing happened.
  useEffect(() => {
    getJobs().then((all) => {
      const r = all.find((j) => j.status === 'running')
      if (!r) return
      if (r.kind === 'detect') { setJob2(r); watch(r.id, setJob2) }
      else if (r.kind === 'verify') { setJobV(r); watch(r.id, setJobV) }
      else if (r.kind === 'align') { setJob(r); watch(r.id, setJob) }
    }).catch(() => {})
  }, [])
  // Matching is a plain request (no scanning) — preview first, then apply.
  const runMatch = async (dry) => {
    setMatching(true); setError('')
    if (dry) setMatch(null)
    try {
      const r = await matchPlays({
        film_id: Number(film4), offset: Number(skip) || 0,
        skip_special: noSpecial, dry_run: dry,
      })
      setMatch(r)
      if (!dry) { onChanged(); flash(`Matched ${r.applied} plays`) }
    } catch (e) { setError(e.message); setMatch(null) } finally { setMatching(false) }
  }
  // Re-preview whenever the knobs change, so the buttons never apply a stale pairing.
  useEffect(() => { setMatch(null) }, [film4, skip, noSpecial])

  const running = [job, job2, jobV].some((j) => j && j.status === 'running')
  return (
    <div className="screen">
      <div className="scr-bar"><span className="back" onClick={() => nav('home')}>‹ Home</span><h2>Auto Detect <span className="count">· find plays automatically</span></h2></div>

      <div className="form-card">
        <h4 style={{ margin: '0 0 6px' }}>Broadcast — read the game clock</h4>
        <p className="hint3">Reads the on-screen game clock and lines your imported play-by-play up with the video. Needs the play-by-play imported first (Data Grab) and a visible clock. Takes several minutes.</p>
        <div style={{ display: 'flex', gap: 10 }}>
          <select className="inp" style={{ flex: 1 }} value={film} disabled={running} onChange={(e) => setFilm(e.target.value)}>
            <option value="">select film…</option>{films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
          </select>
          <button className="btn primary" disabled={!film || running} onClick={() => runJob(() => startAlign({ film_id: Number(film) }), setJob)}>{job && job.status === 'running' ? 'Scanning…' : 'Auto-align'}</button>
        </div>
        {job && <div className={'job' + (job.status === 'failed' ? ' bad' : '')}>
          <b>{job.phase}</b> — {job.message}
          {job.status === 'running' && job.total > 0 && <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(100, Math.round(100 * job.frames / job.total))}%` }} /></div>}
          {job.status === 'running' && <div>{Math.round(job.frames)}s of {Math.round(job.total)}s of film scanned · {job.samples} clock reads</div>}
        </div>}
      </div>

      <div className="form-card">
        <h4 style={{ margin: '0 0 6px' }}>All-22 &amp; coaches film — detect scene cuts</h4>
        <p className="hint3">On All-22 and end-zone film each play is its own camera cut — no game clock needed. This splits the film at those cuts into individual plays. Lower the sensitivity if it misses cuts; raise it if it finds too many.</p>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <select className="inp" style={{ flex: 1 }} value={film2} disabled={running} onChange={(e) => setFilm2(e.target.value)}>
            <option value="">select film…</option>{films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
          </select>
          <label style={{ fontSize: 12, color: 'var(--dim)' }}>sensitivity
            <select className="inp" style={{ marginLeft: 6 }} value={sens} disabled={running} onChange={(e) => setSens(e.target.value)}>
              <option value="0.3">high</option><option value="0.4">medium</option><option value="0.5">low</option>
            </select>
          </label>
          <button className="btn primary" disabled={!film2 || running} onClick={() => runJob(() => startDetect({ film_id: Number(film2), threshold: Number(sens) }), setJob2)}>{job2 && job2.status === 'running' ? 'Scanning…' : 'Detect plays'}</button>
        </div>
        {job2 && <div className={'job' + (job2.status === 'failed' ? ' bad' : '')}>
          {job2.message}
          {job2.status === 'running' && <div>{job2.processed}s of film scanned…</div>}
        </div>}
      </div>

      <div className="form-card">
        <h4 style={{ margin: '0 0 6px' }}>All-22 — give the detected plays their play data</h4>
        <p className="hint3">Scene detect finds <i>where</i> each play is; the play-by-play knows <i>what</i> each play was. Both are in game order, so this pairs them up — the 1st cut is the 1st play, and so on. Import the play-by-play in Data Grab first, then run this.</p>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <select className="inp" style={{ flex: 1, minWidth: 160 }} value={film4} disabled={running || matching} onChange={(e) => setFilm4(e.target.value)}>
            <option value="">select film…</option>{films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
          </select>
          <label style={{ fontSize: 12, color: 'var(--dim)' }}>skip first
            <input className="inp" type="number" style={{ marginLeft: 6, width: 64 }} value={skip}
              disabled={running || matching} onChange={(e) => setSkip(e.target.value)} />
          </label>
          <label style={{ fontSize: 12, color: 'var(--dim)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={noSpecial} disabled={running || matching}
              onChange={(e) => setNoSpecial(e.target.checked)} />
            no kicks/punts
          </label>
          <button className="btn" disabled={!film4 || running || matching} onClick={() => runMatch(true)}>Preview</button>
          <button className="btn primary" disabled={!film4 || running || matching || !match} onClick={() => runMatch(false)}>Match them up</button>
        </div>
        {match && <div className={'job' + (match.clean ? '' : ' bad')}>
          <b>{match.summary}</b>
          {!match.clean && <div className="hint2">The counts differ, so everything after the first missing play is shifted. If the preview is off by a constant, raise <b>skip first</b>; if the film omits kicks and punts, tick the box.</div>}
          {match.preview && match.preview.length > 0 && (
            <table className="mini"><tbody>
              {match.preview.map((p, i) => (
                <tr key={i}>
                  <td>{Math.floor(p.t_start / 60)}:{String(Math.floor(p.t_start % 60)).padStart(2, '0')}</td>
                  <td>play {p.play_no}</td>
                  <td>{p.down ? `${p.down} & ${p.distance ?? '-'}` : '—'}</td>
                  <td>{p.play_type || '—'}</td>
                  <td>{p.result || ''}</td>
                </tr>
              ))}
            </tbody></table>
          )}
        </div>}
      </div>

      <div className="form-card">
        <h4 style={{ margin: '0 0 6px' }}>Check the alignment against the video</h4>
        <p className="hint3">Auto-align places plays approximately. This reads each placed play's down &amp; distance off the video and compares it to the play-by-play, so every play in the grid is marked <b>Verified</b>, <b>Review</b>, or <b>Unchecked</b> — you cut the verified ones with confidence and eyeball the rest.</p>
        <div style={{ display: 'flex', gap: 10 }}>
          <select className="inp" style={{ flex: 1 }} value={film3} disabled={running} onChange={(e) => setFilm3(e.target.value)}>
            <option value="">select film…</option>{films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
          </select>
          <button className="btn primary" disabled={!film3 || running} onClick={() => runJob(() => startVerify({ film_id: Number(film3) }), setJobV)}>{jobV && jobV.status === 'running' ? 'Checking…' : 'Verify plays'}</button>
        </div>
        {jobV && <div className={'job' + (jobV.status === 'failed' ? ' bad' : '')}>
          {jobV.message}
          {jobV.status === 'running' && jobV.total > 0 && <>
            <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.round(100 * jobV.done / jobV.total)}%` }} /></div>
            <div>{jobV.done} of {jobV.total} checked · <span style={{ color: 'var(--teal)' }}>{jobV.match} verified</span> · <span style={{ color: 'var(--amber)' }}>{jobV.mismatch} review</span> · {jobV.unread} unread</div>
          </>}
        </div>}
      </div>
      {error && <div className="error" style={{ maxWidth: 720 }}>{error}</div>}
    </div>
  )
}

// -- FILM LIBRARY -----------------------------------------------------------
function FilmLibrary({ films, onChanged, flash, nav }) {
  const [available, setAvailable] = useState([])
  const [sourceTypes, setSourceTypes] = useState(Object.keys(SOURCE_LABELS))
  const [path, setPath] = useState('')
  const [label, setLabel] = useState('')
  const [stype, setStype] = useState('broadcast')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [hot, setHot] = useState(false)
  const [job, setJob] = useState(null)
  const poll = useRef(null)
  const hasNative = typeof window !== 'undefined' && window.pywebview && window.pywebview.api && window.pywebview.api.pick_film

  const refresh = () => getLibraryFilms().then(setAvailable).catch(() => {})
  useEffect(() => { refresh(); getSourceTypes().then(setSourceTypes).catch(() => {}) }, [films])
  useEffect(() => () => clearInterval(poll.current), [])
  // A dropped film's real path arrives from the desktop app via this event
  // (the webview hides it from a normal drop). See desktop._install_drag_drop.
  useEffect(() => {
    const onDrop = (e) => { setHot(false); if (e.detail) setPath(e.detail) }
    window.addEventListener('pkfilmdrop', onDrop)
    return () => window.removeEventListener('pkfilmdrop', onDrop)
  }, [])

  const isAbsolute = (p) => /^([a-zA-Z]:[\\/]|\\\\|\/)/.test(p)

  const add = async () => {
    setBusy(true); setError(''); setJob(null)
    try {
      if (isAbsolute(path)) {
        // A film from elsewhere on disk: copy it into the library (background job).
        const j = await importFilm({ src: path, label: label || null, source_type: stype })
        setJob(j)
        poll.current = setInterval(async () => {
          try {
            const u = await getJob(j.id); setJob(u)
            if (u.status !== 'running') {
              clearInterval(poll.current); setBusy(false)
              if (u.status === 'done') { setPath(''); setLabel(''); onChanged(); flash('Film added') }
              else setError(u.message)
            }
          } catch { clearInterval(poll.current); setBusy(false) }
        }, 700)
      } else {
        await registerFilm({ path, label: label || null, source_type: stype })
        setPath(''); setLabel(''); onChanged(); flash('Film added'); setBusy(false)
      }
    } catch (e) { setError(e.message); setBusy(false) }
  }
  const remove = async (id) => {
    if (!window.confirm('Remove this film and its plays from the index? (The file stays on disk.)')) return
    try { await deleteFilm(id); onChanged() } catch (e) { setError(e.message) }
  }
  const browse = async () => {
    if (!hasNative) return
    try { const picked = await window.pywebview.api.pick_film(); if (picked) setPath(picked) } catch (e) { setError(String(e)) }
  }
  // The real dropped path can't be read from the browser drop event (security);
  // the desktop app delivers it via the 'pkfilmdrop' event handled above. Here we
  // just accept the drag and clear the hover state.
  const onDrop = (e) => { e.preventDefault(); setHot(false) }

  return (
    <div className="screen">
      <div className="scr-bar"><span className="back" onClick={() => nav('home')}>‹ Home</span><h2>Film Library <span className="count">· {films.length} film{films.length !== 1 ? 's' : ''}</span></h2></div>
      <div className="form-card">
        <h4 style={{ margin: '0 0 10px' }}>Add a film</h4>
        <div className={'dropzone' + (hot ? ' hot' : '')} onDragOver={(e) => { e.preventDefault(); setHot(true) }}
          onDragLeave={() => setHot(false)} onDrop={onDrop} onClick={hasNative ? browse : undefined}>
          {I.up}
          <div>{hasNative ? 'Click to browse, or drag a film here' : 'Drag a film file here'}</div>
          <div className="hint2">A film from anywhere is copied into your library so everything stays together.</div>
        </div>
        <label className="fld">Film file</label>
        <div className="row" style={{ gap: 8 }}>
          <input className="inp" value={path}
            placeholder={hasNative ? 'Click Browse to choose a film…' : 'e.g. 2026/mines-vs-csc.mp4'}
            readOnly={hasNative} onChange={hasNative ? undefined : (e) => setPath(e.target.value)}
            onClick={hasNative ? browse : undefined}
            style={{ flex: 1, cursor: hasNative ? 'pointer' : 'text' }} />
          {hasNative
            ? <button className="btn" onClick={browse}>Browse…</button>
            : <select className="inp" value="" onChange={(e) => e.target.value && setPath(e.target.value)}>
                <option value="">choose…</option>{available.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>}
        </div>
        <div className="grid2" style={{ marginTop: 10 }}>
          <div><label className="fld">Label</label><input className="inp full" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="CSC @ Mines" /></div>
          <div><label className="fld">Type</label>
            <select className="inp full" value={stype} onChange={(e) => setStype(e.target.value)}>
              {sourceTypes.map((s) => <option key={s} value={s}>{sourceLabel(s)}</option>)}
            </select></div>
        </div>
        <button className="btn primary" style={{ marginTop: 12 }} disabled={busy || !path} onClick={add}>
          {busy ? 'Adding…' : 'Add film'}
        </button>
        <span className="hint2">A film from outside your library is copied in. Probes fps · codec · interlace · duration.</span>
        {job && <div className={'job' + (job.status === 'failed' ? ' bad' : '')}>
          {job.message}
          {job.status === 'running' && job.total > 0 && <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.round(100 * job.done / job.total)}%` }} /></div>}
        </div>}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="form-card">
        <h4 style={{ margin: '0 0 6px' }}>Your film</h4>
        {films.length === 0 && <div className="hint2">No films yet — add one above.</div>}
        {films.map((f) => (
          <div className="film-row" key={f.id}>
            <div style={{ flex: 1 }}>
              <div className="fname">{f.label || f.path}</div>
              <div className="fmeta">{sourceLabel(f.source_type)} · {f.plays} plays{f.fps ? ` · ${Math.round(f.fps)}fps` : ''}{f.interlaced === 1 ? ' · interlaced' : ''}<span className="fpath"> · {f.path}</span></div>
            </div>
            <button className="btn ghost sm" onClick={() => remove(f.id)}>Remove</button>
          </div>
        ))}
      </div>
    </div>
  )
}

// -- small shared bits ------------------------------------------------------
function Step({ n, h, hint, children }) {
  return <div className="step"><div className="num">{n}</div><div><h4>{h}</h4><p className="hint3">{hint}</p>{children}</div></div>
}
function queryFromPreset(p) {
  const f = p.filter || {}
  return { where: f.where || [], source: f.source || undefined, minConfidence: f.min_confidence, confirmedOnly: f.confirmed_only }
}
