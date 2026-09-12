"""Where the app lives and which ffmpeg it uses – differs between source checkout and packaged .exe."""
from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Folder the app runs from: next to the .exe when packaged, else the project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def configs_dir() -> Path:
    return app_dir() / "configs"


def ffmpeg() -> str:
    """A bundled ffmpeg next to the app wins over the one on PATH."""
    local = app_dir() / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    return str(local) if local.is_file() else "ffmpeg"
