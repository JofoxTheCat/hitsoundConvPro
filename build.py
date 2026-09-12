"""Builds the Windows release: a folder with hitsoundConvPro.exe + files, zipped for a GitHub release.

    python build.py                # both variants
    python build.py --plain        # only the small one (needs ffmpeg on PATH)
    python build.py --with-ffmpeg  # only the self-contained one
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

NAME = "hitsoundConvPro"
VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
EXTRAS = ("README.md", "sliderslidermute.wav")

# A double-clicked .exe takes its error message with it when the window closes; this keeps it open.
LAUNCHER = """@echo off
cd /d "%~dp0"
"%~dp0{name}.exe" gui
echo.
echo The GUI has stopped. Press a key to close this window.
pause >nul
"""

START_TEXT = r"""hitsoundConvPro {version}

IMPORTANT: unpack this folder first. Started from inside the .zip the app closes immediately,
because Windows does not extract the _internal folder next to the .exe.

Double-click "Start GUI.bat" (keeps the window open and shows errors) or {name}.exe directly:
both open the interface in your browser. There you create a project from an osu!mania difficulty
or open an existing config.

Configs live in the "configs" folder next to this file, exports in "export".

{ffmpeg}

Command line (same folder):
  {name}.exe analyze "<path to the mania diff>.osu"
  {name}.exe init-config "<path to the mania diff>.osu"
  {name}.exe convert configs\<name>.toml
  {name}.exe verify configs\<name>.toml --skin "<skin folder>" --music
  {name}.exe mode configs\<name>.toml listen | edit
  {name}.exe gui [configs\<name>.toml]

If the window closes right away: crash.log next to the .exe holds the reason.
More in README.md.
"""
FFMPEG_BUNDLED = "ffmpeg.exe is included - nothing else to install."
FFMPEG_MISSING = ("ffmpeg is required and NOT included: install ffmpeg (on PATH)\n"
                  "or drop an ffmpeg.exe next to this file.")


def _run_pyinstaller(work: Path, staging: Path) -> Path:
    static = ROOT / "hitsoundconv" / "gui" / "static"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
                    "--name", NAME, "--distpath", str(staging), "--workpath", str(work),
                    "--specpath", str(work), "--add-data", f"{static}{os.pathsep}hitsoundconv/gui/static",
                    str(ROOT / "app.py")], check=True)
    return staging / NAME


def _ffmpeg() -> Path:
    found = shutil.which("ffmpeg")
    if not found:
        raise SystemExit("ffmpeg not found on PATH - the bundled build needs it to copy along")
    return Path(found)


def build(with_ffmpeg: bool) -> Path:
    label = f"{NAME}-{VERSION}-win64" + ("-with-ffmpeg" if with_ffmpeg else "")
    print(f"\n=== {label}")
    ffmpeg_exe = _ffmpeg() if with_ffmpeg else None  # fail before the long build
    staging = DIST / "_staging"
    shutil.rmtree(staging, ignore_errors=True)
    app = _run_pyinstaller(ROOT / "build" / label, staging)

    target = DIST / label
    if target.exists():  # a leftover folder would make shutil.move nest the build inside it
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(app), str(target))
    if not (target / f'{NAME}.exe').is_file():
        raise SystemExit(f'Build broken: {target / NAME}.exe is missing')
    shutil.rmtree(staging, ignore_errors=True)

    (target / "configs").mkdir(exist_ok=True)
    for name in EXTRAS:
        shutil.copy(ROOT / name, target / name)
    if ffmpeg_exe:
        shutil.copy(ffmpeg_exe, target / "ffmpeg.exe")
    (target / "Start GUI.bat").write_text(LAUNCHER.format(name=NAME), encoding="ascii")
    (target / "START.txt").write_text(
        START_TEXT.format(version=VERSION, name=NAME, ffmpeg=FFMPEG_BUNDLED if with_ffmpeg else FFMPEG_MISSING),
        encoding="utf-8")

    archive = DIST / f"{label}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(target.rglob("*")):
            if file.is_file():
                zf.write(file, Path(label) / file.relative_to(target))
    print(f"{target}\n{archive}  ({archive.stat().st_size / 1e6:.0f} MB)")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plain", action="store_true", help="nur der Build ohne ffmpeg")
    parser.add_argument("--with-ffmpeg", action="store_true", help="nur der Build mit ffmpeg")
    args = parser.parse_args()
    variants = [False] if args.plain else [True] if args.with_ffmpeg else [False, True]
    for with_ffmpeg in variants:
        build(with_ffmpeg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
