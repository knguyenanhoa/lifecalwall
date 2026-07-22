#!/usr/bin/env python3
"""
main.py — Life Calendar Wallpaper

Entry point. Runs as a background process that:
  1. Renders the life calendar and sets it as the desktop wallpaper.
  2. Re-renders every minute (so the live timestamp stays current).
  3. Watches for config-file changes and re-renders immediately.
  4. Shows a menu-bar icon (🗓) via rumps so the user can open
     Settings or Quit without touching the terminal.

Usage
-----
    python main.py                 # start normally
    python main.py --settings      # open settings window then start
    python main.py --render-once   # render once and exit (useful for testing)
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime
from typing import Optional

from config import CONFIG_FILE, Settings, load_settings, save_settings
from renderer import render
from wallpaper import render_and_set

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("lifecal")

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

_current_settings: Optional[Settings] = None


# ---------------------------------------------------------------------------
# Core render
# ---------------------------------------------------------------------------

def do_render(settings: Optional[Settings] = None) -> None:
    """Render the calendar and apply it as the wallpaper."""
    s = settings or _current_settings or load_settings()
    log.info("Rendering calendar (theme=%s, birthday=%s)…",
             s.theme, s.birthday or "not set")
    try:
        img = render(s)
        path = render_and_set(img)
        log.info("Wallpaper updated → %s", path)
    except Exception as exc:
        log.error("Render failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# rumps app  (macOS menu-bar, runs the Cocoa event loop on the main thread)
# ---------------------------------------------------------------------------

def _run_rumps_app() -> None:
    """
    Build and run the rumps menu-bar application.

    All periodic work (rendering, config watching) is driven by
    rumps.Timer callbacks which fire on the Cocoa main run loop —
    this avoids the Python 3.14 GIL-starvation bug that occurs when
    background threads try to acquire the GIL while Cocoa owns the
    main thread.
    """
    import rumps  # type: ignore

    # Suppress the default Dock icon; we only want the menu-bar icon.
    try:
        from AppKit import NSApp, NSApplicationActivationPolicyAccessory  # type: ignore
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

    SETTINGS_SCRIPT = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "settings_ui.py"
    )

    class LifeCalApp(rumps.App):

        def __init__(self):
            super().__init__("🗓", quit_button=None)
            self.menu = [
                rumps.MenuItem("Open Settings", callback=self.open_settings),
                rumps.MenuItem("Render Now",    callback=self.render_now),
                None,
                rumps.MenuItem("Quit",          callback=self.quit_app),
            ]

            # State for the minute-tick timer
            self._last_minute: int = -1
            self._last_config_mtime: float = 0.0

            # Kick off an immediate render on startup
            self._do_tick(None)

            # Timer fires every 15 s:
            #   - checks if a minute has rolled over (re-render for live clock)
            #   - checks if config file changed (re-render for new settings)
            self._timer = rumps.Timer(self._do_tick, 15)
            self._timer.start()

        # ------------------------------------------------------------------

        def _do_tick(self, _sender) -> None:
            global _current_settings

            # Check config file for changes
            try:
                if os.path.exists(CONFIG_FILE):
                    mtime = os.path.getmtime(CONFIG_FILE)
                    if mtime != self._last_config_mtime and self._last_config_mtime != 0.0:
                        log.info("Config changed on disk — reloading.")
                        _current_settings = load_settings()
                    self._last_config_mtime = mtime
            except OSError:
                pass

            # Re-render when the minute rolls over
            now = datetime.now()
            current_minute = now.hour * 60 + now.minute
            if current_minute != self._last_minute:
                do_render()
                self._last_minute = current_minute

        # ------------------------------------------------------------------

        def open_settings(self, _sender) -> None:
            # Launch settings_ui.py as its own process — it needs its own
            # Cocoa main thread to run tkinter.
            subprocess.Popen(
                [sys.executable, SETTINGS_SCRIPT],
                close_fds=True,
            )

        def render_now(self, _sender) -> None:
            do_render()

        def quit_app(self, _sender) -> None:
            rumps.quit_application()

    LifeCalApp().run()


# ---------------------------------------------------------------------------
# Fallback: tkinter hidden window (non-rumps / Linux)
# ---------------------------------------------------------------------------

def _run_tkinter_fallback() -> None:
    """
    Hidden tkinter root — keeps the process alive on Linux or when
    rumps is not installed.  Shows a status window from the Dock.
    """
    import threading
    import time
    import tkinter as tk

    stop_event = threading.Event()

    # ---- Periodic render thread ----------------------------------------
    def _update_loop():
        last_minute = -1
        last_mtime: float = 0.0
        global _current_settings
        while not stop_event.is_set():
            # Config watcher
            try:
                if os.path.exists(CONFIG_FILE):
                    mtime = os.path.getmtime(CONFIG_FILE)
                    if mtime != last_mtime and last_mtime != 0.0:
                        log.info("Config changed — reloading.")
                        _current_settings = load_settings()
                    last_mtime = mtime
            except OSError:
                pass

            # Minute tick
            now = datetime.now()
            current_minute = now.hour * 60 + now.minute
            if current_minute != last_minute:
                do_render()
                last_minute = current_minute

            secs = 60 - datetime.now().second
            time.sleep(min(secs, 15))

    t = threading.Thread(target=_update_loop, name="update-loop", daemon=True)
    t.start()

    # ---- tkinter UI ----------------------------------------------------
    root = tk.Tk()
    root.title("Life Calendar")
    root.withdraw()

    def open_settings_cmd():
        SETTINGS_SCRIPT = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "settings_ui.py"
        )
        subprocess.Popen([sys.executable, SETTINGS_SCRIPT], close_fds=True)

    def show_status():
        win = tk.Toplevel(root)
        win.title("Life Calendar")
        win.resizable(False, False)
        win.configure(bg="#1e1e2e")
        tk.Label(
            win, text="Life Calendar is running.",
            bg="#1e1e2e", fg="#cdd6f4", font=("Helvetica", 13),
            padx=20, pady=10,
        ).pack()
        btn_frame = tk.Frame(win, bg="#1e1e2e", pady=10)
        btn_frame.pack()
        for label, cmd in [
            ("Open Settings", open_settings_cmd),
            ("Render Now",    do_render),
            ("Quit",          lambda: (stop_event.set(), root.destroy())),
        ]:
            tk.Button(
                btn_frame, text=label, command=cmd,
                bg="#313244", fg="#cdd6f4", relief="flat",
                padx=12, pady=6, cursor="hand2",
            ).pack(side="left", padx=6)

    try:
        root.createcommand("::tk::mac::ReopenApplication", show_status)
    except Exception:
        pass

    root.after(200, show_status)
    root.mainloop()
    stop_event.set()


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

def _handle_signal(signum, _frame):
    log.info("Received signal %d — shutting down.", signum)
    sys.exit(0)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    from config import THEMES
    parser = argparse.ArgumentParser(description="Life Calendar Wallpaper")
    parser.add_argument("--settings",    action="store_true",
                        help="Open the settings window before starting.")
    parser.add_argument("--render-once", action="store_true",
                        help="Render once and exit.")
    parser.add_argument("--birthday",    metavar="YYYY-MM-DD",
                        help="Set birthday and save to config, then exit.")
    parser.add_argument("--theme",       choices=list(THEMES.keys()),
                        help="Set theme and save to config, then exit.")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _current_settings

    args = _parse_args()

    # One-shot CLI overrides
    if args.birthday or args.theme:
        s = load_settings()
        if args.birthday:
            s.birthday = args.birthday
        if args.theme:
            s.theme = args.theme
        save_settings(s)
        log.info("Settings updated.")
        if not args.render_once:
            return

    _current_settings = load_settings()

    if args.render_once:
        do_render()
        return

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)

    # Open settings window first if requested or no birthday is set
    if args.settings or not _current_settings.birthday:
        log.info("Opening settings window…")
        SETTINGS_SCRIPT = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "settings_ui.py"
        )
        # Run settings window synchronously (blocking) before the main loop
        subprocess.run([sys.executable, SETTINGS_SCRIPT])
        _current_settings = load_settings()

    log.info("Life Calendar started. PID=%d", os.getpid())

    # Try rumps first (macOS menu-bar); fall back to tkinter hidden window
    try:
        import rumps  # type: ignore  # noqa: F401
        _run_rumps_app()
    except ImportError:
        _run_tkinter_fallback()

    log.info("Life Calendar exited.")


if __name__ == "__main__":
    main()
