"""Builds the release for the platform it runs on: a folder with the app + its files, archived.

    python build.py                # both variants
    python build.py --plain        # only the small one (needs ffmpeg on PATH)
    python build.py --with-ffmpeg  # only the self-contained one

PyInstaller cannot cross-compile, so a Linux build has to run on Linux - see .github/workflows/release.yml.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

NAME = "hitsoundConvPro"
VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
EXTRAS = ("README.md", "sliderslidermute.wav")

WINDOWS = sys.platform == "win32"
PLATFORM = {"win32": "win64", "linux": "linux64", "darwin": "macos"}.get(sys.platform, sys.platform)
EXE = f"{NAME}.exe" if WINDOWS else NAME
FFMPEG = "ffmpeg.exe" if WINDOWS else "ffmpeg"
LAUNCHER = "Start GUI.bat" if WINDOWS else "start-gui.sh"

LAUNCHER_TEXT = {
    # a double-clicked .exe takes its error message with it when the window closes; this keeps it open
    True: '@echo off\r\ncd /d "%~dp0"\r\n"%~dp0{exe}" gui\r\necho.\r\n'
          'echo The GUI has stopped. Press a key to close this window.\r\npause >nul\r\n',
    False: '#!/bin/sh\ncd "$(dirname "$0")"\n./{exe} gui\n',
}[WINDOWS]

START_TEXT = r"""hitsoundConvPro {version}

IMPORTANT: unpack this folder first. Started from inside the archive the app closes immediately,
because the _internal folder next to the executable is missing.

{how_to_start}
There you create a project from an osu!mania difficulty or open an existing config.

Configs live in the "configs" folder next to this file, exports in "export".

{ffmpeg}

Command line (same folder):
  {run} analyze "<path to the mania diff>.osu"
  {run} init-config "<path to the mania diff>.osu"
  {run} convert configs{sep}<name>.toml
  {run} verify configs{sep}<name>.toml --skin "<skin folder>" --music
  {run} mode configs{sep}<name>.toml listen | edit
  {run} gui [configs{sep}<name>.toml]

If the window closes right away: crash.log next to the executable holds the reason.
ffmpeg is a separate project under its own license (https://ffmpeg.org/legal.html).
More in README.md.
"""
HOW_TO_START = {
    True: 'Double-click "Start GUI.bat" (keeps the window open and shows errors) or {exe} directly:\n'
          'both open the interface in your browser.',
    False: 'Run ./start-gui.sh or ./{exe} in a terminal: the interface opens in your browser.',
}[WINDOWS]
FFMPEG_BUNDLED = "ffmpeg is included - nothing else to install."
FFMPEG_MISSING = ("ffmpeg is required and NOT included: install it (on PATH)\n"
                  "or drop an ffmpeg binary next to this file.")


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


def _archive(target: Path, label: str) -> Path:
    """zip on Windows, tar.gz elsewhere - zip would drop the executable bit."""
    if WINDOWS:
        path = DIST / f"{label}.zip"
        path.unlink(missing_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(target.rglob("*")):
                if file.is_file():
                    archive.write(file, Path(label) / file.relative_to(target))
    else:
        path = DIST / f"{label}.tar.gz"
        path.unlink(missing_ok=True)
        with tarfile.open(path, "w:gz") as archive:
            archive.add(target, arcname=label)
    return path


def build(with_ffmpeg: bool) -> Path:
    label = f"{NAME}-{VERSION}-{PLATFORM}" + ("-with-ffmpeg" if with_ffmpeg else "")
    print(f"\n=== {label}")
    ffmpeg_binary = _ffmpeg() if with_ffmpeg else None  # fail before the long build
    staging = DIST / "_staging"
    shutil.rmtree(staging, ignore_errors=True)
    app = _run_pyinstaller(ROOT / "build" / label, staging)

    target = DIST / label
    if target.exists():  # a leftover folder would make shutil.move nest the build inside it
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(app), str(target))
    shutil.rmtree(staging, ignore_errors=True)
    if not (target / EXE).is_file():
        raise SystemExit(f"Build broken: {target / EXE} is missing")

    (target / "configs").mkdir(exist_ok=True)
    for name in EXTRAS:
        shutil.copy(ROOT / name, target / name)
    if ffmpeg_binary:
        shutil.copy(ffmpeg_binary, target / FFMPEG)
        os.chmod(target / FFMPEG, 0o755)
    launcher = target / LAUNCHER
    launcher.write_text(LAUNCHER_TEXT.format(exe=EXE), encoding="ascii", newline="")
    os.chmod(launcher, 0o755)
    (target / "START.txt").write_text(
        START_TEXT.format(version=VERSION, run=f".\\{EXE}" if WINDOWS else f"./{EXE}", sep="\\" if WINDOWS else "/",
                          how_to_start=HOW_TO_START.format(exe=EXE),
                          ffmpeg=FFMPEG_BUNDLED if with_ffmpeg else FFMPEG_MISSING),
        encoding="utf-8")

    archive = _archive(target, label)
    print(f"{target}\n{archive}  ({archive.stat().st_size / 1e6:.0f} MB)")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plain", action="store_true", help="only the build without ffmpeg")
    parser.add_argument("--with-ffmpeg", action="store_true", help="only the build with ffmpeg")
    args = parser.parse_args()
    variants = [False] if args.plain else [True] if args.with_ffmpeg else [False, True]
    for with_ffmpeg in variants:
        build(with_ffmpeg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
