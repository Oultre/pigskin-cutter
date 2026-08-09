// Shared gamepad plumbing for the Tag Pass and Clip Cutter screens.
//
// The browser reports Xbox and PlayStation pads on the same "standard" mapping,
// so the button *indices* are identical; only the face labels differ. We show
// PlayStation glyphs for a DualSense/DualShock (id reports "DualSense", Sony
// vendor 054c) and Xbox letters for everything else.
import { useEffect, useRef, useState } from 'react'

// Standard-mapping button indices.
export const BTN = { A: 0, B: 1, X: 2, Y: 3, LB: 4, RB: 5, BACK: 8, START: 9, DUP: 12, DDOWN: 13, DLEFT: 14, DRIGHT: 15 }

export const PAD_LABELS = {
  ps:   { A: '✕', B: '○', X: '▢', Y: '△', LB: 'L1', RB: 'R1', START: 'Options', BACK: 'Create', name: 'PlayStation' },
  xbox: { A: 'A', B: 'B', X: 'X', Y: 'Y', LB: 'LB', RB: 'RB', START: 'Start',   BACK: 'Back',   name: 'Xbox' },
}

export const padKind = (id) => (id && /dualsense|dualshock|playstation|sony|054c|0ce6|09cc/i.test(id)) ? 'ps' : 'xbox'
export const padLabels = (id) => PAD_LABELS[padKind(id)]

// Poll gamepad 0 and fire a handler on each button's rising edge. `handlers` is
// { <BTN name>: fn }. The latest handlers are read via a ref so callbacks always
// see fresh component state without re-binding the loop. Returns the connected
// pad id (or null) so the caller can show a "connected" indicator and a legend.
export function useGamepad(handlers) {
  const [pad, setPad] = useState(null)
  const padRef = useRef(null)
  const hRef = useRef(handlers)
  hRef.current = handlers
  useEffect(() => {
    let raf
    const prev = {}
    const poll = () => {
      const gp = navigator.getGamepads && navigator.getGamepads()[0]
      if (gp) {
        if (padRef.current !== gp.id) { padRef.current = gp.id; setPad(gp.id) }
        const h = hRef.current || {}
        for (const name in BTN) {
          const i = BTN[name]
          const p = !!(gp.buttons[i] && gp.buttons[i].pressed)
          const was = prev[i]; prev[i] = p
          if (p && !was && h[name]) h[name]()
        }
      } else if (padRef.current) { padRef.current = null; setPad(null) }
      raf = requestAnimationFrame(poll)
    }
    raf = requestAnimationFrame(poll)
    return () => cancelAnimationFrame(raf)
  }, [])
  return pad
}
