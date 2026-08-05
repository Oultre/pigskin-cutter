import React from 'react'

// Coach-facing help. Plain language, no jargon. Kept in sync with docs/USER_GUIDE.md.

function Kbd({ children }) {
  return <span className="kbd">{children}</span>
}

export default function Help() {
  return (
    <div className="help">
      <h1>Pigskin Cutter — Coach's guide</h1>
      <p className="lead">
        This turns your game film into short clips of just the plays you care about — third
        and longs, red zone, a certain formation, whatever you want — so you're not scrubbing
        through hours of tape. Here's how, in plain English. You can't break anything by
        clicking around, so feel free to explore.
      </p>

      <section>
        <h2>The three tabs at the top</h2>
        <ul>
          <li><b>Plays</b> — find the plays you want and make clips. This is where you'll spend most of your time.</li>
          <li><b>Films</b> — the games loaded into the app.</li>
          <li><b>Tag pass</b> — mark up a game yourself by watching it and hitting a key at each snap.</li>
        </ul>
      </section>

      <section>
        <h2>Finding the plays you want</h2>
        <p>On the <b>Plays</b> tab, the left side is your search. Think of it like the filters on a Hudl breakdown.</p>
        <ol>
          <li>Click <b>+ condition</b> to add a rule — for example <i>down is 3</i>, then another for <i>distance is 6 or more</i>.</li>
          <li>You can also limit it to one game, or to only the plays a person confirmed (not a computer guess).</li>
          <li>Click <b>Apply</b>. The middle of the screen fills with the matching plays.</li>
        </ol>
        <p className="tip">Every play remembers where it came from. Plays a computer guessed show a
          faded confidence number — tick <b>confirmed only</b> if you want to leave those out.</p>
      </section>

      <section>
        <h2>Presets — your saved searches</h2>
        <p>Built a search you'll use again? Save it as a <b>preset</b> so it's one click next time.</p>
        <ul>
          <li>Type a name in "save current filter as…" and hit <b>Save</b>.</li>
          <li>Pick a saved one from the <b>load preset</b> dropdown any time.</li>
          <li><b>Import</b> / <b>Export</b> let you share a set of searches with another coach, or move them to your other computer.</li>
        </ul>
      </section>

      <section>
        <h2>Watching a play and fixing the trim</h2>
        <p>Click any play in the middle list to open it on the right.</p>
        <ul>
          <li>The video jumps to that play. Play it, scrub it, take a look.</li>
          <li>If a clip starts a hair too early or late, use the <b>start</b> and <b>end</b> nudge
            buttons (−0.5, −0.1, +0.1, +0.5) or <b>= playhead</b> to set the point to wherever the video is paused.</li>
          <li>Your changes are saved as you go.</li>
        </ul>
      </section>

      <section>
        <h2>Making your clips</h2>
        <p>Down in the <b>Export</b> box on the left:</p>
        <ol>
          <li>Put in an <b>output folder</b> — where the clips should be saved on your computer.</li>
          <li>Optional: add a <b>logo</b> image to stamp your school's mark on each clip (this makes clips a bit slower to create, since each one gets re-made).</li>
          <li>Click <b>Dry run</b> first to see exactly what it will make — nothing is written yet.</li>
          <li>Happy with it? Click <b>Cut clips</b>. Your clips appear in that folder.</li>
        </ol>
        <p className="tip">Nothing is ever changed on your original film. Clips are brand-new files.</p>
      </section>

      <section>
        <h2>Tagging a game yourself (Tag pass)</h2>
        <p>No breakdown for a game? Watch it once and mark the plays. Pick the film at the top,
          then use these while the video plays. You can use a keyboard <i>or</i> an Xbox-style controller.</p>
        <div className="keys">
          <div><Kbd>Space</Kbd> play / pause</div>
          <div><Kbd>←</Kbd> <Kbd>→</Kbd> jump back / forward 1 second (hold <Kbd>Shift</Kbd> for 5)</div>
          <div><Kbd>,</Kbd> <Kbd>.</Kbd> step one frame</div>
          <div><Kbd>I</Kbd> mark the start of a play &nbsp; <Kbd>O</Kbd> mark the end</div>
          <div><Kbd>1</Kbd>–<Kbd>4</Kbd> set the down &nbsp; <Kbd>L</Kbd> <Kbd>M</Kbd> <Kbd>R</Kbd> set the hash</div>
          <div><Kbd>Enter</Kbd> save the play and move on &nbsp; <Kbd>Z</Kbd> undo the last one &nbsp; <Kbd>Esc</Kbd> clear</div>
        </div>
        <p>Controller: <b>A</b> mark start, <b>B</b> mark end, <b>X</b> save, <b>Y</b> clear, the bumpers
          scrub, the D-pad sets the down, <b>Start</b> plays/pauses. A little "gamepad ✓" shows when a controller is connected.</p>
        <p className="tip">Fill in distance/formation and any other boxes as you go — they save with the play.</p>
      </section>

      <section>
        <h2>Films and play-by-play</h2>
        <p>On the <b>Films</b> tab you can add a game and see what's loaded. For a TV-broadcast game,
          the <b>Import play-by-play</b> box can pull the official play list from the athletics website —
          paste the game's box-score link and it fills in every play's down, distance, and result for you.</p>
        <p className="tip">If a lot of the setup looks unfamiliar, that's fine — whoever set this up for
          you usually handles loading the film. Your job is the fun part: finding and cutting the plays.</p>
      </section>

      <section>
        <h2>A few common questions</h2>
        <dl>
          <dt>The play list is empty.</dt>
          <dd>Click <b>Apply</b> in the search on the left — with no conditions it shows every play.</dd>
          <dt>A clip won't export.</dt>
          <dd>A play with no start/end time can't be cut yet (it needs trimming or a tag pass). Those are skipped and the app tells you how many.</dd>
          <dt>Everything looks broken / "Failed to fetch".</dt>
          <dd>The app's engine probably isn't running. Whoever set it up can restart it — nothing you did caused it.</dd>
          <dt>Can I hurt my film?</dt>
          <dd>No. The app only ever reads your film and makes new clip files. Your originals are never touched.</dd>
        </dl>
      </section>

      <p className="footer-note">Questions or something acting up? Send a note to whoever set this up for you —
        and mention what you clicked right before it happened. That's usually enough to sort it out fast.</p>
    </div>
  )
}
