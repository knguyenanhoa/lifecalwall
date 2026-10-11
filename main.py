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

from config import (
    CONFIG_FILE,
    DATA_DIR,
    SETTINGS_SCRIPT,
    WEATHER_SCRIPT,
    Settings,
    load_settings,
    save_settings,
)
from renderer import render
from wallpaper import cleanup_old_wallpapers, render_and_set

# ---------------------------------------------------------------------------
# Logging — rotating file handler, managed entirely within this process.
# Max 500 KB per file, keeps 3 backups → ~2 MB cap total.
# Stops automatically when the process exits; no external tools needed.
# ---------------------------------------------------------------------------

LOG_DIR      = os.path.join(DATA_DIR, "logs")
LOG_MAX_BYTES   = 500_000   # 500 KB per file
LOG_BACKUP_COUNT = 3        # keep stderr.log + stderr.log.1 + .2 + .3


def _setup_logging() -> None:
    """
    Configure the root logger with:
      - A RotatingFileHandler → ~/.lifecal/logs/lifecal.log
      - A StreamHandler → stderr (visible when running manually in a terminal)

    The RotatingFileHandler rolls over at LOG_MAX_BYTES and keeps
    LOG_BACKUP_COUNT old files, so the total log footprint is bounded at
    (LOG_BACKUP_COUNT + 1) * LOG_MAX_BYTES ≈ 2 MB.
    """
    import logging.handlers

    os.makedirs(LOG_DIR, exist_ok=True)

    fmt     = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root    = logging.getLogger()
    root.setLevel(logging.INFO)

    # Rotating file
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "lifecal.log"),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console (useful when running manually; silenced by launchd redirection)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


log = logging.getLogger("lifecal")

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

_current_settings: Optional[Settings] = None


# ---------------------------------------------------------------------------
# Shared periodic driver
# ---------------------------------------------------------------------------
#
# The rumps menu-bar app and the tkinter fallback both need the same recurring
# work: watch the config file for edits, re-render when the minute rolls over
# (to keep the live clock current), and sweep stale wallpaper files hourly.
# The two frontends differ only in *how* they schedule the tick (a Cocoa
# rumps.Timer vs. a background thread loop), so the tick body itself lives here
# once and both call it.

class _TickState:
    """Mutable bookkeeping carried between periodic ticks."""

    def __init__(self) -> None:
        self.last_minute: int = -1
        self.last_config_mtime: float = 0.0
        self.last_cleanup_hour: int = -1

    def force_render_next_tick(self) -> None:
        """Reset the minute tracker so the next tick re-renders unconditionally."""
        self.last_minute = -1


def run_periodic_checks(state: _TickState) -> None:
    """
    Run one periodic tick against *state*: reload settings if the config file
    changed, re-render on a minute rollover, and clean up stale wallpapers
    hourly. Shared by both the rumps and tkinter run loops.
    """
    global _current_settings

    # Reload settings when the config file changes on disk. The first observed
    # mtime only seeds the baseline (no reload) so an edit made before startup
    # isn't mistaken for a live change.
    try:
        if os.path.exists(CONFIG_FILE):
            mtime = os.path.getmtime(CONFIG_FILE)
            if mtime != state.last_config_mtime and state.last_config_mtime != 0.0:
                log.info("Config changed on disk — reloading.")
                _current_settings = load_settings()
            state.last_config_mtime = mtime
    except OSError:
        pass

    now = datetime.now()
    current_minute = now.hour * 60 + now.minute
    if current_minute != state.last_minute:
        do_render()
        state.last_minute = current_minute

    if now.hour != state.last_cleanup_hour:
        cleanup_old_wallpapers()
        state.last_cleanup_hour = now.hour


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

    class LifeCalApp(rumps.App):

        def __init__(self):
            super().__init__("🗓", quit_button=None)

            self._paused = False
            self._pause_item = rumps.MenuItem("Pause Updates", callback=self._toggle_pause)

            self.menu = [
                rumps.MenuItem("Open Settings", callback=self.open_settings),
                rumps.MenuItem("Open Weather",  callback=self.open_weather),
                None,
                rumps.MenuItem("Render Now",    callback=self.render_now),
                self._pause_item,
                rumps.MenuItem("Restart",       callback=self._restart),
                None,
                rumps.MenuItem("Quit",          callback=self.quit_app),
            ]

            # State for the periodic tick (minute rollover, config watch, cleanup)
            self._tick_state = _TickState()

            # Register NSWorkspace notification observers so we can
            # re-render immediately on screen wake and Space switch.
            self._observers = []
            self._register_system_observers()

            # Sweep away any wallpaper images orphaned by a previous run.
            cleanup_old_wallpapers()

            # Kick off an immediate render on startup
            self._do_tick(None)

            # Timer fires every 15 s:
            #   - checks if a minute has rolled over (re-render for live clock)
            #   - checks if config file changed (re-render for new settings)
            self._timer = rumps.Timer(self._do_tick, 15)
            self._timer.start()

        # ------------------------------------------------------------------

        def _register_system_observers(self) -> None:
            """
            Subscribe to two NSWorkspace notifications:

            NSWorkspaceScreensDidWakeNotification
                Fired when the display wakes from sleep.  We re-render so the
                wallpaper is fresh and the live clock is correct.

            NSWorkspaceActiveSpaceDidChangeNotification
                Fired whenever the user switches to a different Mission Control
                Space / desktop.  We re-render so every Space shows the
                current wallpaper (macOS resets the wallpaper per-space on
                wake and space-switch in some configurations).
            """
            try:
                from AppKit import NSWorkspace                    # type: ignore
                from Foundation import NSNotificationCenter       # type: ignore

                ws_nc = NSWorkspace.sharedWorkspace().notificationCenter()

                for notification_name in (
                    "NSWorkspaceScreensDidWakeNotification",
                    "NSWorkspaceActiveSpaceDidChangeNotification",
                ):
                    observer = ws_nc.addObserverForName_object_queue_usingBlock_(
                        notification_name,
                        None,   # observe from any object
                        None,   # deliver on the posting thread (main run loop)
                        self._on_system_event,
                    )
                    self._observers.append((ws_nc, observer))
                    log.info("Registered observer for %s", notification_name)

            except Exception as exc:
                log.warning("Could not register system observers: %s", exc)

        def _on_system_event(self, notification) -> None:
            """Called on screen wake or Space switch — trigger an immediate render."""
            if self._paused:
                return
            name = getattr(notification, "name", lambda: str(notification))
            name = name() if callable(name) else str(name)
            log.info("System event: %s — re-rendering.", name)
            # Reset the minute tracker so _do_tick also fires a render on the
            # next tick even if the minute hasn't changed.
            self._tick_state.force_render_next_tick()
            do_render()

        def _deregister_system_observers(self) -> None:
            for nc, observer in self._observers:
                try:
                    nc.removeObserver_(observer)
                except Exception:
                    pass
            self._observers.clear()

        # ------------------------------------------------------------------

        def _do_tick(self, _sender) -> None:
            if self._paused:
                return
            run_periodic_checks(self._tick_state)

        # ------------------------------------------------------------------

        def open_settings(self, _sender) -> None:
            # Launch settings_ui.py as its own process — it needs its own
            # Cocoa main thread to run tkinter.
            subprocess.Popen(
                [sys.executable, SETTINGS_SCRIPT],
                close_fds=True,
            )

        def open_weather(self, _sender) -> None:
            # Launch the weather quick-view in its own process, same as settings.
            subprocess.Popen(
                [sys.executable, WEATHER_SCRIPT],
                close_fds=True,
            )

        def render_now(self, _sender) -> None:
            do_render()

        def _toggle_pause(self, sender) -> None:
            """Pause or resume automatic wallpaper updates."""
            self._paused = not self._paused
            if self._paused:
                self._timer.stop()
                sender.title = "Resume Updates"
                self.title = "🗓⏸"
                log.info("Updates paused.")
            else:
                self._timer.start()
                sender.title = "Pause Updates"
                self.title = "🗓"
                self._tick_state.force_render_next_tick()  # force immediate re-render
                log.info("Updates resumed.")

        def _restart(self, _sender) -> None:
            """Restart the entire process by re-executing ourselves."""
            log.info("Restarting…")
            self._deregister_system_observers()
            # Re-exec the current process with the same arguments
            os.execv(sys.executable, [sys.executable] + sys.argv)

        def quit_app(self, _sender) -> None:
            self._deregister_system_observers()
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

    # Sweep away any wallpaper images orphaned by a previous run.
    cleanup_old_wallpapers()

    # ---- Periodic render thread ----------------------------------------
    def _update_loop():
        tick_state = _TickState()
        while not stop_event.is_set():
            run_periodic_checks(tick_state)
            # Wake near the top of the next minute (capped at 15 s) so the live
            # clock stays close to accurate without busy-waiting.
            secs = 60 - datetime.now().second
            time.sleep(min(secs, 15))

    t = threading.Thread(target=_update_loop, name="update-loop", daemon=True)
    t.start()

    # ---- tkinter UI ----------------------------------------------------
    root = tk.Tk()
    root.title("Life Calendar")
    root.withdraw()

    def open_settings_cmd():
        subprocess.Popen([sys.executable, SETTINGS_SCRIPT], close_fds=True)

    def open_weather_cmd():
        subprocess.Popen([sys.executable, WEATHER_SCRIPT], close_fds=True)

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
            ("Open Weather",  open_weather_cmd),
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
# tkinter availability
# ---------------------------------------------------------------------------

def _require_tkinter() -> None:
    """
    Exit with a helpful message if tkinter is unavailable.

    On Linux (notably Ubuntu/Debian) tkinter is not bundled with Python and
    must be installed separately via the system package manager. Without it
    the app has no way to keep its process alive or show the settings window,
    so fail early with an actionable hint rather than a raw ImportError.
    """
    try:
        import tkinter  # noqa: F401
        return
    except ImportError:
        pass

    msg = "Tkinter (Python's Tk bindings) is required but not installed."
    if sys.platform.startswith("linux"):
        msg += (
            "\nOn Ubuntu/Debian, install it with:\n"
            "    sudo apt install python3-tk\n"
            "On Fedora:   sudo dnf install python3-tkinter\n"
            "On Arch:     sudo pacman -S tk"
        )
    log.error(msg)
    print(msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    from config import list_theme_names
    parser = argparse.ArgumentParser(description="Life Calendar Wallpaper")
    parser.add_argument("--settings",    action="store_true",
                        help="Open the settings window before starting.")
    parser.add_argument("--render-once", action="store_true",
                        help="Render once and exit.")
    parser.add_argument("--birthday",    metavar="YYYY-MM-DD",
                        help="Set birthday and save to config, then exit.")
    parser.add_argument("--theme",       choices=list_theme_names(),
                        help="Set theme and save to config, then exit.")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _current_settings

    _setup_logging()

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
        # The settings window is a tkinter app; make sure it's available so
        # the subprocess doesn't crash with a bare ImportError.
        _require_tkinter()
        log.info("Opening settings window…")
        # Run settings window synchronously (blocking) before the main loop
        subprocess.run([sys.executable, SETTINGS_SCRIPT])
        _current_settings = load_settings()

    log.info("Life Calendar started. PID=%d", os.getpid())

    # Try rumps first (macOS menu-bar); fall back to tkinter hidden window.
    try:
        import rumps  # type: ignore  # noqa: F401
    except ImportError:
        rumps = None

    if rumps is not None:
        _run_rumps_app()
    else:
        # The Linux/no-rumps path needs tkinter to keep the process alive.
        _require_tkinter()
        _run_tkinter_fallback()

    log.info("Life Calendar exited.")


if __name__ == "__main__":
    main()
