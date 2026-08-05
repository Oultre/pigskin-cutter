# Installing Pigskin Cutter

One file, nothing to install. Because it's a free tool (not bought from an app
store), your computer will warn you the first time you open it — that's normal,
and the steps below get you past it. You only do this once.

---

## Windows

1. Download **PigskinCutter-windows.exe**.
2. Double-click it. Windows may show a blue **"Windows protected your PC"** box.
3. Click **More info**, then **Run anyway**.
4. A small black window opens and says *"Pigskin Cutter is running at http://…"*,
   and your web browser opens the app. **Leave the black window open** while you
   work — closing it stops the app.

## Mac

1. Download **PigskinCutter-macos**.
2. **Right-click** (or Control-click) it and choose **Open** — don't just
   double-click the first time.
3. A box says the app is from an unidentified developer. Click **Open**.
4. A Terminal window opens with *"Pigskin Cutter is running at http://…"* and your
   browser opens the app. **Leave the Terminal window open** while you work.

*(After the first time, you can just double-click it like any app.)*

## Linux

1. Download **PigskinCutter-linux**.
2. Make it runnable: `chmod +x PigskinCutter-linux`, then run `./PigskinCutter-linux`.
3. Your browser opens the app. Leave the terminal open while you work.

---

## First run

- The app creates a folder called **Pigskin Cutter** in your **Documents** — that's
  your library, where your games and clips live. You can put your film there.
- ffmpeg (the video engine) is built in — you don't install anything else.

## If something goes wrong

Open the app from a terminal and run it with **diagnostics** to get a report you
can paste to whoever set this up for you:

```
PigskinCutter diagnostics
```

That prints versions, the video engine location, and your computer's video
hardware — enough to sort out most issues. Common ones:

- **"Failed to fetch" in the browser** — the app window got closed. Re-open the app.
- **It won't open at all** — re-do the "Run anyway" / right-click-Open step above.
- **The app says a port is in use** — something else is using it; the app usually
  picks another automatically, but you can also close other apps and retry.

That's it. Everything runs on your computer; nothing is uploaded anywhere.
