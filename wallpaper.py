"""
wallpaper.py — Save a Pillow image to disk and set it as the desktop wallpaper.

Supports:
  - macOS  : via PyObjC (NSWorkspace) — no special permissions required
  - Linux  : tries gsettings (GNOME), xfconf-query (XFCE), feh, swaybg

macOS caching note
------------------
macOS caches wallpaper images keyed by file path. Overwriting the same file
does NOT cause a visual refresh — the OS serves the cached bitmap. The only
reliable fix is to give NSWorkspace a path it has never seen before on every
call. We do this by writing each render to a uniquely-named temp file inside
~/.lifecal/, then deleting the previous one after the new path is applied.
"""

import os
import platform
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

WALLPAPER_DIR = os.path.expanduser("~/.lifecal")

# Tracks the path that is currently set as the wallpaper so we can delete
# it after the next render replaces it.
_current_wallpaper_path: str = ""


def save_image(img: Image.Image) -> str:
    """
    Write *img* to a fresh unique path inside ~/.lifecal/ and return it.
    Each call produces a different filename so macOS cannot serve a cached copy.
    """
    os.makedirs(WALLPAPER_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=WALLPAPER_DIR, suffix=".png", prefix="wp_")
    try:
        os.close(fd)
        img.save(path, "PNG")
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def set_wallpaper(image_path: str) -> None:
    """Set *image_path* as the desktop wallpaper, then clean up the old file."""
    global _current_wallpaper_path

    system   = platform.system()
    abs_path = str(Path(image_path).resolve())
    old_path = _current_wallpaper_path

    if system == "Darwin":
        _set_wallpaper_macos(abs_path)
    elif system == "Linux":
        _set_wallpaper_linux(abs_path)
    else:
        raise RuntimeError(f"Unsupported platform: {system}")

    # New path is live — record it and delete the previous file
    _current_wallpaper_path = abs_path
    if old_path and old_path != abs_path:
        try:
            os.unlink(old_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

def _set_wallpaper_macos(path: str) -> None:
    try:
        _set_wallpaper_macos_pyobjc(path)
    except ImportError:
        _set_wallpaper_macos_osascript(path)


def _set_wallpaper_macos_pyobjc(path: str) -> None:
    """
    Set wallpaper via NSWorkspace — no special permissions required.
    Each call receives a brand-new file path so the OS cache is always bypassed.
    """
    from AppKit import NSWorkspace, NSScreen  # type: ignore
    from Foundation import NSURL              # type: ignore

    url     = NSURL.fileURLWithPath_(path)
    ws      = NSWorkspace.sharedWorkspace()
    options: dict = {}

    for screen in NSScreen.screens():
        success, error_ref = ws.setDesktopImageURL_forScreen_options_error_(
            url, screen, options, None
        )
        if not success:
            err_str = str(error_ref) if error_ref else "unknown error"
            raise RuntimeError(f"NSWorkspace failed to set wallpaper: {err_str}")


def _set_wallpaper_macos_osascript(path: str) -> None:
    """Fallback: AppleScript (requires Automation / System Events permission)."""
    script = f'''
tell application "System Events"
    set theFile to POSIX file "{path}"
    repeat with aDesktop in desktops
        set picture of aDesktop to theFile
    end repeat
end tell
'''
    try:
        subprocess.run(["osascript", "-e", script],
                       check=True, capture_output=True, text=True, timeout=15)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"osascript failed:\n{exc.stderr.strip()}"
        ) from exc
    except FileNotFoundError:
        raise RuntimeError("osascript not found")


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------

def _set_wallpaper_linux(path: str) -> None:
    errors = []

    if _cmd_exists("gsettings"):
        try:
            uri = f"file://{path}"
            subprocess.run(["gsettings", "set",
                            "org.gnome.desktop.background", "picture-uri", uri],
                           check=True, capture_output=True, text=True, timeout=10)
            subprocess.run(["gsettings", "set",
                            "org.gnome.desktop.background", "picture-uri-dark", uri],
                           check=False, capture_output=True, text=True, timeout=10)
            return
        except subprocess.CalledProcessError as exc:
            errors.append(f"gsettings: {exc.stderr.strip()}")

    if _cmd_exists("xfconf-query"):
        try:
            import re
            result = subprocess.run(
                ["xfconf-query", "--channel", "xfce4-desktop", "--list", "--verbose"],
                capture_output=True, text=True, timeout=10)
            props = re.findall(
                r"(/backdrop/screen\d+/monitor\S+/workspace\d+/last-image)",
                result.stdout) or ["/backdrop/screen0/monitor0/workspace0/last-image"]
            for prop in props:
                subprocess.run(["xfconf-query", "--channel", "xfce4-desktop",
                                "--property", prop, "--set", path],
                               check=True, capture_output=True, text=True, timeout=10)
            return
        except subprocess.CalledProcessError as exc:
            errors.append(f"xfconf-query: {exc.stderr.strip()}")

    if _cmd_exists("feh"):
        try:
            subprocess.run(["feh", "--bg-scale", path],
                           check=True, capture_output=True, text=True, timeout=10)
            return
        except subprocess.CalledProcessError as exc:
            errors.append(f"feh: {exc.stderr.strip()}")

    if _cmd_exists("swaybg"):
        subprocess.run(["pkill", "swaybg"], capture_output=True)
        try:
            subprocess.Popen(["swaybg", "-i", path, "-m", "fill"],
                             start_new_session=True)
            return
        except OSError as exc:
            errors.append(f"swaybg: {exc}")

    raise RuntimeError(
        "Could not set wallpaper. Tried: gsettings, xfconf-query, feh, swaybg.\n"
        + "\n".join(errors)
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _cmd_exists(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


def render_and_set(img: Image.Image) -> str:
    """Save *img* with a fresh unique path and set it as the wallpaper."""
    path = save_image(img)
    set_wallpaper(path)
    return path
