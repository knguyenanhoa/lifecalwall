"""
settings_ui.py — Settings window for the life calendar wallpaper.

Opens a small tkinter window that lets the user:
  • Set / edit their birthday
  • Choose a theme
  • Adjust the update interval
  • Preview the calendar at thumbnail scale
  • Apply changes (re-render + set wallpaper) immediately
"""

import threading
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk
from typing import Callable, Optional

from PIL import Image, ImageTk

from config import THEMES, Settings, get_theme, load_settings, save_settings
from renderer import render

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PREVIEW_W = 540
PREVIEW_H = 300
WINDOW_TITLE = "Life Calendar — Settings"


# ---------------------------------------------------------------------------
# Settings window
# ---------------------------------------------------------------------------

class SettingsWindow:
    """
    Tkinter settings window.

    Parameters
    ----------
    on_apply : callable, optional
        Called with the updated Settings object when the user clicks Apply.
        Runs in the main thread.
    """

    def __init__(self, on_apply: Optional[Callable[[Settings], None]] = None):
        self._on_apply = on_apply
        self._settings = load_settings()
        self._preview_job: Optional[str] = None  # after() handle

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
        root.configure(bg="#1e1e2e")

        PAD = 12
        LABEL_FG = "#cdd6f4"
        ENTRY_BG = "#313244"
        ENTRY_FG = "#cdd6f4"
        BTN_BG   = "#89b4fa"
        BTN_FG   = "#1e1e2e"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground=ENTRY_BG,
            background=ENTRY_BG,
            foreground=ENTRY_FG,
            selectbackground=ENTRY_BG,
            selectforeground=ENTRY_FG,
        )

        # ---- Main frame ------------------------------------------------
        frm = tk.Frame(root, bg="#1e1e2e", padx=PAD, pady=PAD)
        frm.pack(fill="both", expand=True)

        # ---- Title label -----------------------------------------------
        tk.Label(
            frm, text="Life Calendar", bg="#1e1e2e", fg="#89b4fa",
            font=("Helvetica", 16, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, PAD))

        # ---- Birthday --------------------------------------------------
        tk.Label(frm, text="Birthday (YYYY-MM-DD):", bg="#1e1e2e", fg=LABEL_FG).grid(
            row=1, column=0, sticky="w", pady=4,
        )
        self._birthday_var = tk.StringVar(value=self._settings.birthday)
        birthday_entry = tk.Entry(
            frm, textvariable=self._birthday_var, width=14,
            bg=ENTRY_BG, fg=ENTRY_FG, insertbackground=ENTRY_FG,
            relief="flat", bd=4,
        )
        birthday_entry.grid(row=1, column=1, sticky="w", pady=4, padx=(8, 0))
        self._birthday_var.trace_add("write", lambda *_: self._schedule_preview())

        # Birthday validation hint
        self._bday_hint = tk.Label(frm, text="", bg="#1e1e2e", fg="#f38ba8", font=("Helvetica", 9))
        self._bday_hint.grid(row=1, column=2, sticky="w", padx=(6, 0))

        # ---- Theme -------------------------------------------------------
        tk.Label(frm, text="Theme:", bg="#1e1e2e", fg=LABEL_FG).grid(
            row=2, column=0, sticky="w", pady=4,
        )
        self._theme_var = tk.StringVar(value=self._settings.theme)
        theme_combo = ttk.Combobox(
            frm, textvariable=self._theme_var,
            values=list(THEMES.keys()), state="readonly", width=12,
        )
        theme_combo.grid(row=2, column=1, sticky="w", pady=4, padx=(8, 0))
        # Explicitly set the displayed value — on some macOS Tk builds the
        # textvariable alone does not update the visible text until interaction.
        theme_combo.set(self._settings.theme)
        self._theme_var.trace_add("write", lambda *_: self._schedule_preview())

        # ---- Update interval -------------------------------------------
        tk.Label(frm, text="Update interval (min):", bg="#1e1e2e", fg=LABEL_FG).grid(
            row=3, column=0, sticky="w", pady=4,
        )
        self._interval_var = tk.IntVar(value=self._settings.update_interval_seconds // 60)
        interval_spin = tk.Spinbox(
            frm, from_=1, to=1440, textvariable=self._interval_var, width=6,
            bg=ENTRY_BG, fg=ENTRY_FG, buttonbackground=ENTRY_BG,
            insertbackground=ENTRY_FG, relief="flat",
        )
        interval_spin.grid(row=3, column=1, sticky="w", pady=4, padx=(8, 0))

        # ---- Show labels toggles ----------------------------------------
        self._show_year_var  = tk.BooleanVar(value=self._settings.show_year_labels)
        self._show_week_var  = tk.BooleanVar(value=self._settings.show_week_labels)

        chk_style = {"bg": "#1e1e2e", "fg": LABEL_FG, "activebackground": "#1e1e2e",
                     "selectcolor": ENTRY_BG, "relief": "flat"}
        tk.Checkbutton(
            frm, text="Show year labels", variable=self._show_year_var,
            command=self._schedule_preview, **chk_style,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=2)
        tk.Checkbutton(
            frm, text="Show week labels", variable=self._show_week_var,
            command=self._schedule_preview, **chk_style,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=2)

        # ---- Separator --------------------------------------------------
        tk.Frame(frm, bg="#45475a", height=1).grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(PAD, PAD // 2),
        )

        # ---- Preview canvas ---------------------------------------------
        tk.Label(frm, text="Preview:", bg="#1e1e2e", fg=LABEL_FG).grid(
            row=7, column=0, sticky="nw", pady=(0, 4),
        )
        self._preview_canvas = tk.Canvas(
            frm, width=PREVIEW_W, height=PREVIEW_H,
            bg="#000000", highlightthickness=0,
        )
        self._preview_canvas.grid(
            row=8, column=0, columnspan=3, pady=(0, PAD),
        )
        self._preview_img_ref: Optional[ImageTk.PhotoImage] = None  # keep ref alive

        # ---- Buttons ----------------------------------------------------
        btn_frame = tk.Frame(frm, bg="#1e1e2e")
        btn_frame.grid(row=9, column=0, columnspan=3, sticky="e")

        tk.Button(
            btn_frame, text="Apply", command=self._on_apply_click,
            bg=BTN_BG, fg=BTN_FG, activebackground="#74c7ec",
            relief="flat", padx=16, pady=6, cursor="hand2",
            font=("Helvetica", 10, "bold"),
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_frame, text="Cancel", command=self._root.destroy,
            bg=ENTRY_BG, fg=LABEL_FG, activebackground="#45475a",
            relief="flat", padx=16, pady=6, cursor="hand2",
        ).pack(side="right")

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _schedule_preview(self) -> None:
        """Debounce: render preview 400 ms after the last change."""
        if self._preview_job is not None:
            self._root.after_cancel(self._preview_job)
        self._preview_job = self._root.after(400, self._render_preview)

    def _render_preview(self) -> None:
        self._preview_job = None
        settings = self._build_settings_from_ui()
        if settings is None:
            return

        # Render in a background thread to keep the UI responsive
        def _do_render():
            try:
                # Render at a small fixed size for speed
                preview_settings = Settings(**{
                    **settings.__dict__,
                    "canvas_width": PREVIEW_W,
                    "canvas_height": PREVIEW_H,
                    "padding_top": 20,
                    "padding_bottom": 20,
                    "padding_left": 20,
                    "padding_right": 20,
                    "cell_gap": 1,
                })
                img = render(preview_settings)
                self._root.after(0, lambda: self._update_preview_canvas(img))
            except Exception:
                pass  # silently ignore render errors in preview

        threading.Thread(target=_do_render, daemon=True).start()

    def _update_preview_canvas(self, img: Image.Image) -> None:
        photo = ImageTk.PhotoImage(img)
        self._preview_img_ref = photo  # prevent GC
        self._preview_canvas.create_image(0, 0, anchor="nw", image=photo)

    # ------------------------------------------------------------------
    # Validation & building settings from UI
    # ------------------------------------------------------------------

    def _build_settings_from_ui(self, show_errors: bool = False) -> Optional[Settings]:
        """Read UI values, validate, and return a Settings object or None."""
        birthday_str = self._birthday_var.get().strip()

        # Validate birthday
        if birthday_str:
            try:
                date.fromisoformat(birthday_str)
                self._bday_hint.config(text="")
            except ValueError:
                self._bday_hint.config(text="⚠ use YYYY-MM-DD")
                if show_errors:
                    messagebox.showerror(
                        "Invalid date",
                        "Birthday must be in YYYY-MM-DD format (e.g. 1990-05-15).",
                        parent=self._root,
                    )
                return None
        else:
            self._bday_hint.config(text="")

        interval_min = self._interval_var.get()
        if interval_min < 1:
            interval_min = 1

        return Settings(
            birthday=birthday_str,
            theme=self._theme_var.get(),
            update_interval_seconds=interval_min * 60,
            canvas_width=self._settings.canvas_width,
            canvas_height=self._settings.canvas_height,
            padding_top=self._settings.padding_top,
            padding_bottom=self._settings.padding_bottom,
            padding_left=self._settings.padding_left,
            padding_right=self._settings.padding_right,
            cell_gap=self._settings.cell_gap,
            show_year_labels=self._show_year_var.get(),
            show_week_labels=self._show_week_var.get(),
        )

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_apply_click(self) -> None:
        settings = self._build_settings_from_ui(show_errors=True)
        if settings is None:
            return

        save_settings(settings)
        self._settings = settings

        if self._on_apply:
            self._on_apply(settings)

        messagebox.showinfo(
            "Applied",
            "Settings saved. Wallpaper will update shortly.",
            parent=self._root,
        )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the tkinter main loop (blocks until the window is closed)."""
        self._root.mainloop()


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------

def open_settings(on_apply: Optional[Callable[[Settings], None]] = None) -> None:
    """Open the settings window. Blocks until closed."""
    win = SettingsWindow(on_apply=on_apply)
    win.run()


if __name__ == "__main__":
    # When launched as a subprocess from the tray (or directly by the user),
    # saving config is sufficient — the main process's config watcher will
    # pick up the change and trigger a re-render automatically.
    def _apply_and_close(settings):
        pass  # save_settings already called by SettingsWindow; nothing else needed

    open_settings(on_apply=_apply_and_close)
