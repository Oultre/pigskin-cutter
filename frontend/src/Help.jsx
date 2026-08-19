import React from 'react'

// Coach-facing help. Plain language, no jargon. Matches the workflow-launcher UI.
// Kept in sync with docs/USER_GUIDE.md.

function Kbd({ children }) { return <span className="kbd">{children}</span> }

export default function Help() {
  return (
    <div className="help">
      <h1>Pigskin Cutter — Coach&rsquo;s guide</h1>
      <p className="lead">
        This turns your game film into short clips of just the plays you care about — third
        and longs, red zone, a certain formation, whatever you want — so you&rsquo;re not scrubbing
        through hours of tape. Here&rsquo;s how, in plain English. You can&rsquo;t break anything by
        clicking around, so explore.
      </p>

      <section>
        <h2>The home screen: pick what you&rsquo;re doing</h2>
        <p>When the app opens you get five big buttons. Click one to start; the logo up top
          always brings you back home.</p>
        <ul>
          <li><b>Clip Cutter</b> — find plays and make clips. This is where you&rsquo;ll spend most of your time.</li>
          <li><b>Auto Detect</b> — let the app find the plays for you on a broadcast game.</li>
          <li><b>Data Grab</b> — pull the official play-by-play for a college game.</li>
          <li><b>Build Reel</b> — string a bunch of plays into one highlight video.</li>
          <li><b>Film Library</b> — add a game and see what&rsquo;s loaded.</li>
        </ul>
      </section>

      <section>
        <h2>Clip Cutter — finding and cutting plays</h2>
        <p>Every play shows as a little thumbnail, like a contact sheet. Along the top is a row of
          <b> Suggested cuts</b> — one-click filters like <i>3rd &amp; Long</i>, <i>Explosive</i>,
          <i> Touchdowns</i>, <i>Red Zone</i>. Click one and the grid shows just those plays, with a count.</p>
        <ul>
          <li>Want something more specific? Click <b>Advanced filter</b> and add rules like
            <i> down is 3</i> and <i>distance is 7 or more</i>, then <b>Apply</b>. Save it as your own
            suggested cut with <b>Save as preset</b>.</li>
          <li>Click any play to <b>watch and trim</b> it on the right. If a clip starts a hair early
            or late, use the <b>start</b> / <b>end</b> nudge buttons, or <b>= here</b> to set the point to
            wherever the video is paused. Changes save as you go.</li>
        </ul>
        <p className="tip">Each play remembers where it came from. A play a computer guessed shows an
          <b> OCR</b> or <b>CHECK</b> badge instead of <b>MATCHED</b> — tick <b>confirmed only</b> in the
          filter to leave the guesses out.</p>
      </section>

      <section>
        <h2>Making your clips (and sizing them for social)</h2>
        <p>In the <b>Export clips</b> box on the left:</p>
        <ol>
          <li>Put in an <b>output folder</b> — where the clips should be saved.</li>
          <li>Pick a <b>size</b>. Leave it on <i>Original</i> for Hudl, or choose a social size:
            widescreen for YouTube/Hudl/X, square for an Instagram feed, or <b>Vertical</b> for
            Reels, TikTok, Shorts and Snapchat.</li>
          <li>Optional: add a <b>logo</b> to stamp your school&rsquo;s mark on each clip.</li>
          <li>Click <b>Dry run</b> to see exactly what it will make — nothing is written yet. Happy?
            Click <b>Cut clips</b>.</li>
        </ol>
        <p className="tip">Your original film is never changed. Clips are brand-new files.</p>
      </section>

      <section>
        <h2>Build Reel — one highlight video</h2>
        <p>In Clip Cutter, click the little circle on each play you want (a checkmark appears), then
          hit <b>Build reel from selection</b>. Give it a title, pick a size (go <b>Vertical</b> for
          a phone), and it stitches those plays into a single video with the down &amp; distance burned
          on each one. It saves into a <b>reels</b> folder in your library.</p>
      </section>

      <section>
        <h2>Auto Detect — let the app find the plays</h2>
        <p>Auto Detect has three boxes, and which one you use depends on your film.</p>
        <ol>
          <li><b>Broadcast — read the game clock.</b> For a <b>TV broadcast</b> game, this reads the
            on-screen game clock and lines your play-by-play up with the video — no tagging. It needs the
            play-by-play imported first (see Data Grab) and a visible clock in the picture. Takes several
            minutes.</li>
          <li><b>All-22 &amp; coaches film — detect scene cuts.</b> On All-22 and end-zone film every play is
            its own camera cut, so no game clock is needed — this splits the film at those cuts into plays.
            If it misses cuts, set <b>sensitivity</b> to high; if it finds too many, set it to low.</li>
          <li><b>Check the alignment against the video.</b> Auto-align only places plays <i>approximately</i>.
            This reads each placed play&rsquo;s down &amp; distance back off the video and compares it to the
            play-by-play, marking every play <b>Verified</b>, <b>Review</b>, or <b>Unchecked</b>.</li>
        </ol>
        <p className="tip">Run the check after an auto-align, then use <b>✓ Verified only</b> in Clip Cutter —
          cut those with confidence and eyeball the rest.</p>
      </section>

      <section>
        <h2>Data Grab — official play-by-play</h2>
        <p><b>Data Grab</b> pulls the official play list for a game so you don&rsquo;t have to chart it.
          Type a college&rsquo;s athletics website (like <i>minesathletics.com</i>) and the season, click
          <b> Find games</b>, and pick your game from the list — it fills in every play&rsquo;s down,
          distance, and result. (No link to hunt down.)</p>
        <p className="tip">This works for most <b>college</b> teams — their athletics sites all run on
          the same platform (Sidearm). It does <b>not</b> work for high-school or pro sites. If your
          school isn&rsquo;t found, you can still paste a box-score link directly.</p>
        <p>The plays come in without cut times — run <b>Auto Detect</b> to line them up on the video.</p>
      </section>

      <section>
        <h2>Film Library — adding a game</h2>
        <p>Click <b>Add film</b>, then <b>Browse</b> to your game file (or drag it onto the window).
          If the film lives somewhere else on your computer, the app copies it into your library for
          you — you&rsquo;ll see a progress bar. Pick the film type (broadcast, All-22, Hudl, drone) and
          click <b>Add film</b>.</p>
      </section>

      <section>
        <h2>Tagging a game yourself (Tag a game by hand)</h2>
        <p>No breakdown or play-by-play for a game? Watch it once and mark the plays. From the home
          screen click <b>Tag a game by hand</b>, pick the film, and use these while it plays. Prefer a
          game controller? See <b>Using a game controller</b> below.</p>
        <div className="keys">
          <div><Kbd>Space</Kbd> play / pause</div>
          <div><Kbd>&larr;</Kbd> <Kbd>&rarr;</Kbd> jump back / forward 1 second (hold <Kbd>Shift</Kbd> for 5)</div>
          <div><Kbd>,</Kbd> <Kbd>.</Kbd> step one frame</div>
          <div><Kbd>I</Kbd> mark the start of a play &nbsp; <Kbd>O</Kbd> mark the end</div>
          <div><Kbd>1</Kbd>&ndash;<Kbd>4</Kbd> set the down &nbsp; <Kbd>L</Kbd> <Kbd>M</Kbd> <Kbd>R</Kbd> set the hash</div>
          <div><Kbd>Enter</Kbd> save and move on &nbsp; <Kbd>Z</Kbd> undo &nbsp; <Kbd>Esc</Kbd> clear</div>
        </div>
      </section>

      <section>
        <h2>Using a game controller</h2>
        <p>An <b>Xbox</b> or <b>PlayStation 5</b> controller works in two places — <b>Tag a game by hand</b>
          and the <b>watch and trim</b> panel in Clip Cutter. Plug it in (USB or Bluetooth) and
          <b> press any button</b> — the app can&rsquo;t see a controller until you do, which is why it says
          &ldquo;press a button to connect&rdquo; until then. Once it wakes up, a <b>button guide appears on screen</b>
          with the right labels for your controller — ✕ ○ ▢ △ for a PlayStation pad, A B X Y for an Xbox one.
          No controller connected, no guide.</p>
        <p>In <b>Tag a game by hand</b> (Xbox labels; PlayStation in parentheses):</p>
        <div className="keys">
          <div><Kbd>A</Kbd> (<Kbd>✕</Kbd>) mark start &nbsp; <Kbd>B</Kbd> (<Kbd>○</Kbd>) mark end</div>
          <div><Kbd>X</Kbd> (<Kbd>▢</Kbd>) save and move on &nbsp; <Kbd>Y</Kbd> (<Kbd>△</Kbd>) clear</div>
          <div><Kbd>LB</Kbd> <Kbd>RB</Kbd> (<Kbd>L1</Kbd> <Kbd>R1</Kbd>) jump 1 second</div>
          <div>D-pad <Kbd>&larr;</Kbd> <Kbd>&rarr;</Kbd> jump 5 seconds &nbsp; D-pad <Kbd>&uarr;</Kbd> <Kbd>&darr;</Kbd> set the down</div>
          <div><Kbd>Start</Kbd> (<Kbd>Options</Kbd>) play / pause &nbsp; <Kbd>Back</Kbd> (<Kbd>Create</Kbd>) undo</div>
        </div>
        <p>In the <b>Clip Cutter</b> preview, for scrubbing and trimming:</p>
        <div className="keys">
          <div><Kbd>Start</Kbd> (<Kbd>Options</Kbd>) play / pause</div>
          <div><Kbd>LB</Kbd> <Kbd>RB</Kbd> (<Kbd>L1</Kbd> <Kbd>R1</Kbd>) jump 1 second &nbsp; D-pad <Kbd>&larr;</Kbd> <Kbd>&rarr;</Kbd> jump 5 seconds</div>
          <div><Kbd>A</Kbd> (<Kbd>✕</Kbd>) set start here &nbsp; <Kbd>B</Kbd> (<Kbd>○</Kbd>) set end here</div>
          <div><Kbd>X</Kbd> / <Kbd>Y</Kbd> (<Kbd>▢</Kbd> / <Kbd>△</Kbd>) trim the tail by a tenth of a second</div>
        </div>
        <p className="tip">Each screen wakes the controller separately — if you switch screens and the guide
          is missing, just press a button again.</p>
      </section>

      <section>
        <h2>Settings</h2>
        <p>The gear up top, next to the light/dark switch.</p>
        <ul>
          <li><b>Where things are saved</b> — set a default folder for clips and for reels once, and they
            fill in every time. You can still pick something else at export.</li>
          <li><b>Your film library</b> — the folder holding your games and index. <b>Switch…</b> opens a
            different library, or point it at an empty folder to start a fresh one.</li>
          <li><b>Appearance</b> — the app starts dark; flip it to light here and it remembers.</li>
        </ul>
      </section>

      <section>
        <h2>A few common questions</h2>
        <dl>
          <dt>The play grid is empty.</dt>
          <dd>Click <b>All plays</b> at the top of Clip Cutter, or pick a different film from the box in the top-right.</dd>
          <dt>A clip won&rsquo;t export.</dt>
          <dd>A play with no start/end time can&rsquo;t be cut yet (it needs trimming or a tag pass). Those are skipped and the app tells you how many.</dd>
          <dt>Can I hurt my film?</dt>
          <dd>No. The app only ever reads your film and makes new clip files. Your originals are never touched.</dd>
        </dl>
      </section>

      <p className="footer-note">Questions or something acting up? Send a note to whoever set this up for you —
        and mention what you clicked right before it happened. That&rsquo;s usually enough to sort it out fast.</p>
    </div>
  )
}
