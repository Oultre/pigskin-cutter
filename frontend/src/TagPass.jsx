import React, { useEffect, useRef, useState } from 'react'
import { streamUrl, createPlay, deletePlay } from './api.js'

function fmt(t) {
  if (t === null || t === undefined) return '—'
  const s = Math.max(0, t)
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${sec.toFixed(1).padStart(4, '0')}`
}

// Fields captured per play. down/hash have quick-keys; the rest are typed.
const FIELD_KEYS = ['down', 'distance', 'hash', 'off_form', 'play_type']

// Xbox / standard-mapping button indices
const BTN = { A: 0, B: 1, X: 2, Y: 3, LB: 4, RB: 5, BACK: 8, START: 9, DUP: 12, DDOWN: 13, DLEFT: 14, DRIGHT: 15 }

export default function TagPass({ films, onTagged }) {
  const [filmId, setFilmId] = useState(films[0]?.id ? String(films[0].id) : '')
  const [markIn, setMarkIn] = useState(null)
  const [markOut, setMarkOut] = useState(null)
  const [fields, setFields] = useState({})
  const [count, setCount] = useState(0)
  const [msg, setMsg] = useState('Pick a film and start marking plays.')
  const [pad, setPad] = useState(null)

  const videoRef = useRef(null)
  const lastIdRef = useRef(null)
  const padRef = useRef(null)
  // mirror latest state so the (once-bound) keyboard/gamepad loops read fresh values
  const s = useRef({})
  s.current = { markIn, markOut, fields, filmId }

  const fps = films.find((f) => String(f.id) === String(filmId))?.fps || 30

  const flash = (m) => setMsg(m)
  const setField = (k, v) => setFields((f) => ({ ...f, [k]: v }))
  const seek = (d) => {
    const v = videoRef.current
    if (v) v.currentTime = Math.max(0, Math.min(v.duration || 1e9, v.currentTime + d))
  }
  const togglePlay = () => { const v = videoRef.current; if (v) (v.paused ? v.play() : v.pause()) }
  const doIn = () => { const v = videoRef.current; if (v) { setMarkIn(v.currentTime); flash('in @ ' + fmt(v.currentTime)) } }
  const doOut = () => { const v = videoRef.current; if (v) { setMarkOut(v.currentTime); flash('out @ ' + fmt(v.currentTime)) } }
  const clearMarks = () => { setMarkIn(null); setMarkOut(null); setFields({}); flash('cleared') }
  const bumpDown = (d) => setFields((f) => {
    const nx = Math.min(4, Math.max(1, (Number(f.down) || 0) + d))
    return { ...f, down: String(nx) }
  })

  const save = async () => {
    const { markIn: mi, markOut: mo, fields: fl, filmId: fid } = s.current
    if (!fid) { flash('pick a film first'); return }
    if (mi == null || mo == null || mo <= mi) { flash('need in < out'); return }
    const tags = Object.fromEntries(Object.entries(fl).filter(([, v]) => v !== '' && v != null))
    try {
      const p = await createPlay({ film_id: Number(fid), t_start: mi, t_end: mo, tags })
      lastIdRef.current = p.id
      setCount((c) => c + 1); setMarkIn(null); setMarkOut(null); setFields({})
      const v = videoRef.current; if (v) v.currentTime = mo
      flash('saved play #' + p.play_no)
      onTagged && onTagged()
    } catch (e) { flash(e.message) }
  }
  const undo = async () => {
    if (!lastIdRef.current) { flash('nothing to undo'); return }
    try {
      await deletePlay(lastIdRef.current)
      lastIdRef.current = null; setCount((c) => Math.max(0, c - 1)); flash('undid last play')
      onTagged && onTagged()
    } catch (e) { flash(e.message) }
  }

  // keyboard (bound once; handlers read refs / functional setState so stay fresh)
  useEffect(() => {
    const onKey = (e) => {
      const t = e.target
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return
      const k = e.key
      if (k === ' ') { e.preventDefault(); togglePlay() }
      else if (k === 'ArrowLeft') { e.preventDefault(); seek(e.shiftKey ? -5 : -1) }
      else if (k === 'ArrowRight') { e.preventDefault(); seek(e.shiftKey ? 5 : 1) }
      else if (k === ',') seek(-1 / fps)
      else if (k === '.') seek(1 / fps)
      else if (k === 'i' || k === 'I') doIn()
      else if (k === 'o' || k === 'O') doOut()
      else if (k === '1' || k === '2' || k === '3' || k === '4') setField('down', k)
      else if (k === 'l' || k === 'L') setField('hash', 'L')
      else if (k === 'm' || k === 'M') setField('hash', 'M')
      else if (k === 'r' || k === 'R') setField('hash', 'R')
      else if (k === 'Enter') { e.preventDefault(); save() }
      else if (k === 'z' || k === 'Z') undo()
      else if (k === 'Escape') clearMarks()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fps])

  // gamepad polling
  useEffect(() => {
    let raf
    const prev = {}
    const poll = () => {
      const gp = navigator.getGamepads && navigator.getGamepads()[0]
      if (gp) {
        if (padRef.current !== gp.id) { padRef.current = gp.id; setPad(gp.id) }
        const edge = (i) => {
          const p = !!(gp.buttons[i] && gp.buttons[i].pressed)
          const was = prev[i]; prev[i] = p; return p && !was
        }
        if (edge(BTN.A)) doIn()
        if (edge(BTN.B)) doOut()
        if (edge(BTN.X)) save()
        if (edge(BTN.Y)) clearMarks()
        if (edge(BTN.LB)) seek(-1)
        if (edge(BTN.RB)) seek(1)
        if (edge(BTN.START)) togglePlay()
        if (edge(BTN.BACK)) undo()
        if (edge(BTN.DUP)) bumpDown(1)
        if (edge(BTN.DDOWN)) bumpDown(-1)
        if (edge(BTN.DLEFT)) seek(-5)
        if (edge(BTN.DRIGHT)) seek(5)
      } else if (padRef.current) { padRef.current = null; setPad(null) }
      raf = requestAnimationFrame(poll)
    }
    raf = requestAnimationFrame(poll)
    return () => cancelAnimationFrame(raf)
  }, [])

  const pendingDur = (markIn != null && markOut != null) ? Math.max(0, markOut - markIn) : null

  return (
    <div className="tag-view">
      <div className="tag-main">
        <div className="tag-bar">
          <select value={filmId} onChange={(e) => { setFilmId(e.target.value); clearMarks() }}>
            <option value="">select film…</option>
            {films.map((f) => <option key={f.id} value={f.id}>{f.label || f.path}</option>)}
          </select>
          <span className="tag-count">{count} tagged this pass</span>
          <span className={'pad ' + (pad ? 'on' : '')}>{pad ? 'gamepad ✓' : 'no gamepad'}</span>
        </div>
        {filmId
          ? <video key={filmId} ref={videoRef} src={streamUrl(filmId)} controls preload="metadata" />
          : <div className="tag-empty">Select a film to begin.</div>}
        <div className="tag-msg">{msg}</div>
      </div>

      <div className="tag-side">
        <div className="marks">
          <div><span>in</span><b>{fmt(markIn)}</b><button onClick={doIn}>set (I)</button></div>
          <div><span>out</span><b>{fmt(markOut)}</b><button onClick={doOut}>set (O)</button></div>
          <div><span>clip</span><b>{pendingDur != null ? pendingDur.toFixed(1) + 's' : '—'}</b></div>
        </div>

        <div className="chart">
          <div className="frow">
            <label>down</label>
            <div className="downs">
              {[1, 2, 3, 4].map((n) => (
                <button key={n} className={fields.down === String(n) ? 'sel' : ''}
                  onClick={() => setField('down', String(n))}>{n}</button>
              ))}
            </div>
          </div>
          <div className="frow">
            <label>distance</label>
            <input value={fields.distance || ''} onChange={(e) => setField('distance', e.target.value)} />
          </div>
          <div className="frow">
            <label>hash</label>
            <div className="downs">
              {['L', 'M', 'R'].map((h) => (
                <button key={h} className={fields.hash === h ? 'sel' : ''}
                  onClick={() => setField('hash', h)}>{h}</button>
              ))}
            </div>
          </div>
          <div className="frow">
            <label>formation</label>
            <input value={fields.off_form || ''} onChange={(e) => setField('off_form', e.target.value)} />
          </div>
          <div className="frow">
            <label>play type</label>
            <input value={fields.play_type || ''} onChange={(e) => setField('play_type', e.target.value)} />
          </div>
        </div>

        <div className="tag-actions">
          <button className="primary" onClick={save}>Save + next (Enter)</button>
          <button onClick={undo}>Undo (Z)</button>
          <button onClick={clearMarks}>Clear (Esc)</button>
        </div>

        <details className="legend">
          <summary>Shortcuts</summary>
          <div>Space play/pause · ←/→ seek 1s (Shift 5s) · ,/. frame</div>
          <div>I mark in · O mark out · 1–4 down · L/M/R hash</div>
          <div>Enter save+next · Z undo · Esc clear</div>
          <div>Pad: A in · B out · X save · Y clear · LB/RB seek · D-pad ↑↓ down · Start play</div>
        </details>
      </div>
    </div>
  )
}
