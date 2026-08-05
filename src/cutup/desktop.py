"""Native desktop window for the local app (a real window, not a browser tab).

The engine is still FastAPI on localhost; this just wraps it in an OS window via
pywebview (Edge WebView2 on Windows, WKWebView on macOS, WebKitGTK on Linux) so a
coach sees one application window with no address bar and no stray terminal.

Everything here degrades gracefully: if pywebview or a system webview is missing,
callers fall back to opening the default browser, so the app always runs.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from urllib.request import urlopen

WINDOW_TITLE = "Pigskin Cutter"
_BRANDING = Path(__file__).parent / "data" / "branding"


def find_app_icon() -> str | None:
    """Bundled window/app icon, if one shipped. .ico first (Windows), then .png."""
    for name in ("app.ico", "app.png"):
        p = _BRANDING / name
        if p.exists():
            return str(p)
    return None


def native_window_available() -> bool:
    """True only if pywebview imports AND a real webview backend is present."""
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


def wait_until_serving(port: int, timeout: float = 15.0) -> bool:
    """Poll the local server until it answers, so the window opens to a ready page."""
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.15)
    return False


def run_window(url: str, on_close=None) -> None:
    """Open the app in a native window and block until the user closes it.

    Must run on the main thread (GUI requirement). ``on_close`` fires after the
    window closes so the caller can stop the server and release the lock.
    """
    import webview

    webview.create_window(WINDOW_TITLE, url, width=1280, height=860, min_size=(900, 600))
    try:
        webview.start(icon=find_app_icon())
    except TypeError:
        # older pywebview without the icon kwarg
        webview.start()
    finally:
        if on_close is not None:
            on_close()


def serve_in_thread(app, port: int):
    """Start uvicorn in a background daemon thread (GUI owns the main thread).

    Returns the ``uvicorn.Server``; set ``server.should_exit = True`` to stop it.
    Signal handlers are disabled because they can only be installed on the main
    thread, which the window occupies.
    """
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # main thread runs the window
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server
