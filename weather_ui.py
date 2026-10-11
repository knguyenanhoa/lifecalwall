"""
weather_ui.py — Standalone "Open Weather" quick-view window.

A lightweight companion to the settings window: it draws *only* the weather
widget, filling the whole preview, and lets you type a location to re-render
the forecast for that place. It's meant as a fast way to peek at the weather
somewhere without touching your wallpaper's saved settings — nothing here is
persisted. Temperature unit and the rain-chance display can be toggled too.

Launched by the tray's "Open Weather" item as its own process (it needs its
own Cocoa main thread for tkinter), the same way the settings window is.
"""

import logging
import threading
import tkinter as tk
from dataclasses import replace
from datetime import date
from typing import Optional

from PIL import Image, ImageTk

from config import Settings, load_settings
from renderer import render_weather_only

log = logging.getLogger("lifecal.weather_ui")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PREVIEW_W = 620
PREVIEW_H = 420
WINDOW_TITLE = "Life Calendar — Weather"

# Catppuccin-ish palette, matching the settings window.
BG = "#1e1e2e"
LABEL_FG = "#cdd6f4"
ENTRY_BG = "#313244"
ENTRY_FG = "#cdd6f4"
BTN_BG = "#89b4fa"
BTN_FG = "#1e1e2e"
HINT_FG = "#7f849c"


class WeatherWindow:
    """
    Tkinter window that previews only the weather widget for a typed location.

    Starts from the user's saved weather settings (location, unit, rain style)
    so it opens showing their current place, but edits here are not saved —
    this is a throwaway lookup view.
    """

    def __init__(self):
        self._settings = load_settings()
        self._preview_job: Optional[str] = None   # after() debounce handle
        self._preview_img_ref: Optional[ImageTk.PhotoImage] = None  # keep ref alive

        self._root = tk.Tk()
        self._root.title(WINDOW_TITLE)
        self._root.resizable(False, False)

        self._build_ui()
        self._schedule_preview()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = self._root
        root.configure(bg=BG)
        PAD = 12

        frm = tk.Frame(root, bg=BG, padx=PAD, pady=PAD)
        frm.pack(fill="both", expand=True)

        tk.Label(
            frm, text="Weather", bg=BG, fg=BTN_BG,
            font=("Helvetica", 16, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, PAD))

        # ---- Location ---------------------------------------------------
        tk.Label(frm, text="Location:", bg=BG, fg=LABEL_FG).grid(
            row=1, column=0, sticky="w", pady=4,
        )
        self._location_var = tk.StringVar(value=self._settings.weather_location)
        location_entry = tk.Entry(
            frm, textvariable=self._location_var, width=24,
            bg=ENTRY_BG, fg=ENTRY_FG, insertbackground=ENTRY_FG,
            relief="flat", bd=4,
        )
        location_entry.grid(row=1, column=1, sticky="w", pady=4, padx=(8, 0))
        # Re-render as the user types (debounced). Enter forces it immediately.
        self._location_var.trace_add("write", lambda *_: self._schedule_preview())
        location_entry.bind("<Return>", lambda _e: self._render_preview())
        tk.Label(
            frm, text="blank → Ho Chi Minh City", bg=BG, fg=HINT_FG,
            font=("Helvetica", 9),
        ).grid(row=1, column=2, sticky="w", padx=(6, 0))

        # ---- Temperature unit -------------------------------------------
        tk.Label(frm, text="Temperature unit:", bg=BG, fg=LABEL_FG).grid(
            row=2, column=0, sticky="w", pady=4,
        )
        self._fahrenheit_var = tk.BooleanVar(value=self._settings.weather_fahrenheit)
        unit_frame = tk.Frame(frm, bg=BG)
        unit_frame.grid(row=2, column=1, columnspan=2, sticky="w", pady=4, padx=(8, 0))
        radio_style = {"bg": BG, "fg": LABEL_FG, "activebackground": BG,
                       "selectcolor": ENTRY_BG, "relief": "flat"}
        tk.Radiobutton(
            unit_frame, text="°C", variable=self._fahrenheit_var, value=False,
            command=self._schedule_preview, **radio_style,
        ).pack(side="left")
        tk.Radiobutton(
            unit_frame, text="°F", variable=self._fahrenheit_var, value=True,
            command=self._schedule_preview, **radio_style,
        ).pack(side="left", padx=(10, 0))

        # ---- Rain display -----------------------------------------------
        tk.Label(frm, text="Rain chance:", bg=BG, fg=LABEL_FG).grid(
            row=3, column=0, sticky="w", pady=4,
        )
        self._rain_as_pie_var = tk.BooleanVar(value=self._settings.weather_rain_as_pie)
        rain_frame = tk.Frame(frm, bg=BG)
        rain_frame.grid(row=3, column=1, columnspan=2, sticky="w", pady=4, padx=(8, 0))
        tk.Radiobutton(
            rain_frame, text="Pie chart", variable=self._rain_as_pie_var, value=True,
            command=self._schedule_preview, **radio_style,
        ).pack(side="left")
        tk.Radiobutton(
            rain_frame, text="Percentage", variable=self._rain_as_pie_var, value=False,
            command=self._schedule_preview, **radio_style,
        ).pack(side="left", padx=(10, 0))

        # ---- Separator --------------------------------------------------
        tk.Frame(frm, bg="#45475a", height=1).grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(PAD, PAD // 2),
        )

        # ---- Preview (weather widget fills the whole canvas) ------------
        self._status = tk.Label(frm, text="", bg=BG, fg=HINT_FG,
                                font=("Helvetica", 10))
        self._status.grid(row=5, column=0, columnspan=3, sticky="w", pady=(0, 4))

        self._preview_canvas = tk.Canvas(
            frm, width=PREVIEW_W, height=PREVIEW_H,
            bg="#000000", highlightthickness=0,
        )
        self._preview_canvas.grid(row=6, column=0, columnspan=3, pady=(0, PAD))

        # ---- Buttons ----------------------------------------------------
        btn_frame = tk.Frame(frm, bg=BG)
        btn_frame.grid(row=7, column=0, columnspan=3, sticky="e")
        tk.Button(
            btn_frame, text="Refresh", command=self._render_preview,
            bg=BTN_BG, fg=BTN_FG, activebackground="#74c7ec",
            relief="flat", padx=16, pady=6, cursor="hand2",
            font=("Helvetica", 10, "bold"),
        ).pack(side="right", padx=(8, 0))
        tk.Button(
            btn_frame, text="Close", command=self._root.destroy,
            bg=ENTRY_BG, fg=LABEL_FG, activebackground="#45475a",
            relief="flat", padx=16, pady=6, cursor="hand2",
        ).pack(side="right")

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _settings_from_ui(self) -> Settings:
        """
        A throwaway Settings for the preview: start from the user's saved
        settings so the widget renders in the app's current theme, then
        override just the weather inputs edited in this window.
        """
        settings = replace(
            self._settings,
            show_weather=True,
            weather_location=self._location_var.get().strip(),
            weather_fahrenheit=self._fahrenheit_var.get(),
            weather_rain_as_pie=self._rain_as_pie_var.get(),
            # A typed place name is authoritative; never reuse stale coordinates.
            weather_latitude=None,
            weather_longitude=None,
        )
        return settings

    def _schedule_preview(self) -> None:
        """Debounce: render 500 ms after the last change (geocoding is slow)."""
        if self._preview_job is not None:
            self._root.after_cancel(self._preview_job)
        self._preview_job = self._root.after(500, self._render_preview)

    def _render_preview(self) -> None:
        self._preview_job = None
        settings = self._settings_from_ui()
        place = settings.weather_location or "Ho Chi Minh City"
        self._status.config(text=f"Loading weather for {place}…")

        # Fetch + render off the UI thread; geocoding and the forecast call can
        # each take a moment and must not freeze the window.
        def _work():
            try:
                img = render_weather_only(settings, PREVIEW_W, PREVIEW_H)
                self._root.after(0, lambda: self._show(img, place))
            except Exception:
                log.exception("Weather preview render failed")
                self._root.after(0, lambda: self._status.config(
                    text="Could not load weather. Check the location or your connection."))

        threading.Thread(target=_work, daemon=True).start()

    def _show(self, img: Image.Image, place: str) -> None:
        photo = ImageTk.PhotoImage(img)
        self._preview_img_ref = photo  # prevent GC
        self._preview_canvas.create_image(0, 0, anchor="nw", image=photo)
        self._status.config(text=f"Showing weather for {place}")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._root.mainloop()


def open_weather() -> None:
    """Open the weather quick-view window. Blocks until closed."""
    WeatherWindow().run()


if __name__ == "__main__":
    open_weather()
