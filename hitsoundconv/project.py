"""Creating and finding project configs."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .config import save_config
from .osufile import Beatmap
from .paths import configs_dir
from .routing import guess_slot
from .samples import SampleDir, resolve_events


def create_config(beatmap: str | Path, output: str | Path | None = None, force: bool = False) -> Path:
    """Write a config with guessed roles for a mania chart and return its path."""
    beatmap = Path(beatmap).expanduser().resolve()
    if not beatmap.is_file() or beatmap.suffix.lower() != ".osu":
        raise ValueError(f"{beatmap} is not an .osu file")
    bm = Beatmap(beatmap)
    if bm.get("General", "Mode", "0") != "3":
        raise ValueError(f"{beatmap.name} is not an osu!mania difficulty - there are no keysounds to read")
    name = "".join(c for c in beatmap.stem.split("[")[-1].rstrip("]") if c.isalnum() or c in " -_").strip() or "hitsounds"
    path = Path(output).expanduser().resolve() if output else configs_dir() / f"{name}.toml"
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists")

    events, _ = resolve_events(bm, SampleDir(beatmap.parent))
    targets = [p for p in sorted(beatmap.parent.glob("*.osu"))
               if p != beatmap and Beatmap(p).get("General", "Mode", "0") == "0"]
    routes, notes = [], {}
    for file, count in Counter(e.file for e in events).most_common():
        slot, priority, confident, kick = guess_slot(file)
        route = {"match": file, "slot": slot, "priority": priority}
        if kick:
            route.update(lock=True, anchor=True)
        elif slot.endswith("-hitnormal"):  # shares hitnormal with the kick -> needs somewhere to go
            route["overflow"] = f"{slot.split('-')[0]}-hitwhistle"
        routes.append(route)
        notes[file] = f"{count}x" + ("" if confident else "  <- guessed, please check")

    # configs live in <app>/configs, the export belongs next to the app
    export_dir = f"../export/{name}" if path.parent == configs_dir() else f"export/{name}"
    save_config(path, {
        "input": {"beatmap": str(beatmap), "targets": [str(p) for p in targets]},
        "output": {"dir": export_dir, "version": bm.get("Metadata", "Version") + " std hitsounds",
                   "first_index": 2, "last_index": 100,
                   "mute_slider_slide": True, "slider_slide_file": "sliderslidermute.wav"},
        "mix": {"group_tolerance_ms": 2, "gain_step_db": 0.1, "sample_rate": 44100, "bank_mode": "prefer",
                "volume_mode": "relative", "on_clip": "roles", "duplicates": "loudest", "silent_bank": "normal",
                "fallback_slot": "soft-hitwhistle"},
        "fill": {"sample": "auto", "bank": "soft", "gain_db": 0.0},
        "route": routes,
    }, notes)
    return path


def find_configs() -> list[Path]:
    """Configs next to the app and in the current folder."""
    found = {}
    for folder in (configs_dir(), Path.cwd(), Path.cwd() / "configs"):
        if folder.is_dir():
            for path in sorted(folder.glob("*.toml")):
                found.setdefault(path.resolve(), None)
    return list(found)
