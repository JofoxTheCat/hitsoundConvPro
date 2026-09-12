"""EDIT <-> LISTEN: switch a mapset between only its source samples and the installed hitsound export.

LISTEN copies the generated samples and the hitsound .osu into the mapset and records every file with
its checksum in <export>/installed.json. EDIT removes exactly those files again. Nothing the tool did
not put there is ever deleted: foreign files in the way, and installed files changed since (e.g. the
hitsound diff saved in the editor), are moved to <export>/_mapset_backup/<time>/ instead.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from .export import GENERATED_RE

MANIFEST = "installed.json"


def _digest(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _files(directory: Path) -> dict[str, Path]:
    """Files of a folder by lower-case name (Windows paths are case-insensitive)."""
    return {p.name.lower(): p for p in directory.iterdir() if p.is_file()} if directory.is_dir() else {}


def _load(cfg) -> dict:
    path = Path(cfg.output_dir) / MANIFEST
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"mode": "edit", "files": {}}


def _save(cfg, mode: str, files: dict[str, str]) -> None:
    path = Path(cfg.output_dir) / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"mode": mode, "mapset": str(cfg.sample_dir), "time": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}
    path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")


class _Backup:
    """Where files go that must not be deleted."""

    def __init__(self, cfg):
        self.dir = Path(cfg.output_dir) / "_mapset_backup" / time.strftime("%Y%m%d-%H%M%S")
        self.names: list[str] = []

    def move(self, path: Path) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(self.dir / path.name))
        self.names.append(path.name)

    def report(self, **fields) -> dict:
        return {**fields, "backed_up": self.names, "backup_dir": str(self.dir)}


def _remove_installed(path: Path, recorded: str, backup: _Backup) -> None:
    if _digest(path) == recorded:
        path.unlink()
    else:  # changed since we installed it
        backup.move(path)


def export_files(cfg) -> list[Path]:
    """What LISTEN installs: the generated samples and the hitsound .osu of the export folder."""
    out = Path(cfg.output_dir)
    if not out.is_dir():
        return []
    return sorted(p for p in out.iterdir() if p.is_file() and (GENERATED_RE.match(p.name) or p.suffix.lower() == ".osu"))


def status(cfg) -> dict:
    manifest = _load(cfg)
    present = _files(Path(cfg.sample_dir))
    ours = {name.lower() for name in manifest["files"]}
    return {
        "mode": "listen" if manifest["files"] else "edit",
        "mapset": str(cfg.sample_dir),
        "installed": sum(key in present for key in ours),
        # files that look generated but weren't installed by us, e.g. from copying an export by hand
        "unknown": sorted(p.name for key, p in present.items() if GENERATED_RE.match(p.name) and key not in ours),
    }


def listen(cfg) -> dict:
    files = export_files(cfg)
    if not files:
        raise RuntimeError(f"Nothing in the export folder {cfg.output_dir} - convert first")
    mapset = Path(cfg.sample_dir)
    ours = {name.lower(): digest for name, digest in _load(cfg)["files"].items()}
    present = _files(mapset)
    backup = _Backup(cfg)

    new = {p.name.lower() for p in files}
    removed = 0
    for key, digest in ours.items():  # installed last time, not part of this export any more
        if key not in new and key in present:
            _remove_installed(present[key], digest, backup)
            removed += 1

    installed, copied, adopted = {}, 0, 0
    for src in files:
        key, digest = src.name.lower(), _digest(src)
        target = present.get(key)
        if target is not None and target.exists():
            current = _digest(target)
            if current == digest:  # already there, byte-identical – from now on it counts as installed
                installed[src.name] = digest
                adopted += key not in ours
                continue
            if ours.get(key) != current:  # not ours, or changed since: keep it
                backup.move(target)
            else:
                target.unlink()
        shutil.copyfile(src, mapset / src.name)
        installed[src.name] = digest
        copied += 1
    _save(cfg, "listen", installed)
    return backup.report(mode="listen", installed=len(installed), copied=copied, adopted=adopted, removed=removed)


def edit(cfg, include_unknown: bool = False) -> dict:
    """Remove everything LISTEN installed. include_unknown: also move generated-looking files that
    were not installed by us (e.g. from copying an export by hand) into the backup."""
    manifest = _load(cfg)
    present = _files(Path(cfg.sample_dir))
    backup = _Backup(cfg)
    removed = 0
    for name, digest in manifest["files"].items():
        if (path := present.get(name.lower())) is not None:
            _remove_installed(path, digest, backup)
            removed += 1
    ours = {name.lower() for name in manifest["files"]}
    unknown = [p for key, p in present.items() if GENERATED_RE.match(p.name) and key not in ours]
    if include_unknown:
        for path in unknown:
            backup.move(path)
    _save(cfg, "edit", {})
    return backup.report(mode="edit", removed=removed, unknown=[] if include_unknown else sorted(p.name for p in unknown))
