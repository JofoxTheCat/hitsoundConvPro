"""Loads and writes the TOML project config."""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .routing import BANKS, Route, parse_slot


@dataclass
class Config:
    path: Path
    beatmap: Path
    sample_dir: Path
    output_dir: Path
    version: str
    routes: list[Route]
    fallback: Route
    first_index: int = 2
    last_index: int = 100
    group_tolerance_ms: int = 2
    gain_step_db: float = 0.1
    sample_rate: int = 44100
    bank_mode: str = "prefer"     # prefer: role bank unless another bank saves an index | strict: always role bank
    volume_mode: str = "relative"  # relative | absolute | auto
    on_clip: str = "roles"        # roles: clipping samples move to their role / overflow slot | spread: also
                                  # split onto free additions | limit: only turn down
    duplicates: str = "loudest"   # same sample several times on one timestamp: loudest: play once | sum: play all
    silent_bank: str = "normal"   # bank for silent hitnormals (heard as skin hitnormal when beatmap hitsounds are off)
    fill_sample: str = "auto"     # what std objects without a mania sound play: auto | file name | none
    fill_bank: str = "soft"       # greenline bank; its hitnormal holds the fill sound in every index
    fill_gain_db: float = 0.0
    targets: list[Path] = field(default_factory=list)  # std diffs the hitsounds are meant for
    mute_slider_slide: bool = True
    slider_slide_file: str = "sliderslidermute.wav"
    sample_format: str = "auto"    # auto: ogg per file when it is smaller and close enough | ogg | wav
    ogg_quality: float | None = None   # None = pick per file so every file meets ogg_target_db
    ogg_target_db: float = -28.0
    merge_tolerance_db: float = 0.5  # contents closer than this share one file
    pack_attempts: int = 200         # packing orders to try; more can mean fewer files, same sound
    extra: dict = field(default_factory=dict)


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent

    def resolve(value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (base / p).resolve()

    inp, out, mix, fill = data.get("input", {}), data.get("output", {}), data.get("mix", {}), data.get("fill", {})
    beatmap = resolve(inp["beatmap"])
    sample_dir = resolve(inp["sample_dir"]) if inp.get("sample_dir") else beatmap.parent

    routes = [
        Route(r["match"], *parse_slot(r["slot"]), int(r.get("priority", 0)), float(r.get("gain_db", 0.0)),
              order=i, lock=bool(r.get("lock", False)), anchor=bool(r.get("anchor", False)),
              overflow=parse_slot(r["overflow"]) if r.get("overflow") else None)
        for i, r in enumerate(data.get("route", []))
    ]
    fallback_slot = data.get("fallback_slot") or mix.get("fallback_slot") or "soft-hitwhistle"
    fallback = Route("*", *parse_slot(fallback_slot), priority=-1, order=len(routes))

    cfg = Config(
        path=path,
        beatmap=beatmap,
        sample_dir=sample_dir,
        output_dir=resolve(out.get("dir", "export")),
        version=out.get("version", "hitsounds"),
        routes=routes,
        fallback=fallback,
        first_index=int(out.get("first_index", 2)),
        last_index=int(out.get("last_index", 100)),
        group_tolerance_ms=int(mix.get("group_tolerance_ms", 2)),
        gain_step_db=float(mix.get("gain_step_db", 0.1)),
        sample_rate=int(mix.get("sample_rate", 44100)),
        bank_mode=mix.get("bank_mode", "prefer"),
        volume_mode=mix.get("volume_mode", "relative"),
        on_clip=mix.get("on_clip", "roles"),
        duplicates=mix.get("duplicates", "loudest"),
        silent_bank=mix.get("silent_bank", "normal"),
        fill_sample=str(fill.get("sample", "auto")),
        fill_bank=fill.get("bank", "soft"),
        fill_gain_db=float(fill.get("gain_db", 0.0)),
        targets=[resolve(t) for t in inp.get("targets", [])],
        mute_slider_slide=bool(out.get("mute_slider_slide", True)),
        slider_slide_file=out.get("slider_slide_file", "sliderslidermute.wav"),
        sample_format=str(out.get("format", "auto")).lower().lstrip("."),
        ogg_quality=(None if str(out.get("ogg_quality", "auto")).lower() == "auto"
                     else float(out.get("ogg_quality"))),
        ogg_target_db=float(out.get("ogg_target_db", -28.0)),
        merge_tolerance_db=float(mix.get("merge_tolerance_db", 0.5)),
        pack_attempts=int(mix.get("pack_attempts", 200)),
        extra=data,
    )
    checks = [
        (cfg.first_index >= 2, "first_index must be >= 2 (index 1 = the unnumbered files such as soft-hitclap.wav)"),
        (cfg.output_dir != cfg.sample_dir, "output.dir must not be the beatmap folder - use a separate export folder"),
        (cfg.bank_mode in ("prefer", "strict"), "mix.bank_mode must be 'prefer' or 'strict'"),
        (cfg.volume_mode in ("auto", "relative", "absolute", "grid"), "mix.volume_mode must be 'auto', 'relative', 'absolute' or 'grid'"),
        (cfg.on_clip in ("roles", "spread", "limit"), "mix.on_clip must be 'roles', 'spread' or 'limit'"),
        (cfg.duplicates in ("loudest", "sum"), "mix.duplicates must be 'loudest' or 'sum'"),
        (cfg.silent_bank in BANKS and cfg.fill_bank in BANKS, f"mix.silent_bank and fill.bank must be one of {BANKS}"),
        (cfg.silent_bank != cfg.fill_bank, "mix.silent_bank and fill.bank must differ"),
        (cfg.sample_format in ("auto", "wav", "ogg"), "output.format must be 'auto', 'ogg' or 'wav'"),
        (cfg.merge_tolerance_db >= 0, "mix.merge_tolerance_db must not be negative"),
        (cfg.pack_attempts >= 1, "mix.pack_attempts must be at least 1"),
    ]
    for ok, message in checks:
        if not ok:
            raise ValueError(message)
    return cfg


# --- writing -----------------------------------------------------------------------------------

_SECTIONS = ("input", "output", "mix", "fill")
_SECTION_NOTES = {
    "fill": ["What std objects without a mania sound play (e.g. slider heads between two mania notes), without extra",
             "greenlines: every greenline points at this bank, whose hitnormal holds the fill sound in every index."],
}
_KEY_NOTES = {
    ("input", "sample_dir"): "default: the folder of the beatmap",
    ("input", "targets"): "std diffs the hitsounds are for (optional): silent sliderslides and the check in verify",
    ("output", "dir"): "export folder, never the Songs folder itself",
    ("output", "first_index"): "index 1 = the unnumbered files (soft-hitclap.wav), never touched",
    ("output", "last_index"): "editor limit",
    ("output", "mute_slider_slide"): "replace sliderslide with a silent file",
    ("output", "slider_slide_file"): "template, looked up next to the config, in the working folder, the app and the mapset",
    ("mix", "group_tolerance_ms"): "samples this close together count as one timestamp",
    ("mix", "gain_step_db"): "baked-in volumes are rounded to this step",
    ("mix", "merge_tolerance_db"): "contents whose gains differ by less than this share one file",
    ("mix", "pack_attempts"): "packing orders to try; more can mean fewer files and never changes the sound",
    ("output", "format"): "auto picks ogg per file when it is smaller and close enough | ogg | wav",
    ("output", "ogg_quality"): '"auto" picks the smallest quality per file, or set 0-10 yourself',
    ("output", "ogg_target_db"): "auto aims for this difference to the uncompressed mix",
    ("mix", "bank_mode"): "prefer: role bank unless another bank saves an index | strict: always the role bank",
    ("mix", "volume_mode"): "relative: greenline volume = loudest sample | absolute | auto",
    ("mix", "on_clip"): "roles: clipping samples move to their role/overflow slot | limit: only mix quieter | spread: also free additions",
    ("mix", "duplicates"): "same sample several times on one timestamp: loudest = once, at its loudest volume | sum",
    ("mix", "silent_bank"): "bank for silent hitnormals - with skin hitsounds you hear that bank's skin hitnormal",
    ("mix", "fallback_slot"): "samples without a matching role end up here",
    ("fill", "sample"): 'auto = most frequent hitnormal sample (anchors excluded) | file name | "none" = silent',
    ("fill", "bank"): "must differ from silent_bank",
    ("fill", "gain_db"): "relative to the volume of the previous timestamp",
}
_ROUTE_HELP = [
    "Roles: the first matching entry wins. slot = <normal|soft|drum>-<hitnormal|hitwhistle|hitfinish|hitclap>",
    "priority decides whose bank is used when several samples land in hitnormal or in the additions",
    "(osu! plays only ONE hitnormal, and all additions of an object share ONE bank).",
    "lock = true: the sample always stays in exactly this slot (no other bank, no moving away).",
    "anchor = true: when this sample plays, everything else on that timestamp is mixed into its slot (kick focus).",
    'overflow = "<bank>-<sound>": where the sample moves when the mix in its own slot would clip.',
    "gain_db (optional) makes a sample louder or quieter overall.",
]
_ROUTE_KEYS = ("match", "slot", "priority", "lock", "anchor", "overflow", "gain_db")


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # JSON strings are valid TOML basic strings
    if isinstance(value, list):
        return "[\n" + "".join(f"  {_toml_value(v)},\n" for v in value) + "]" if value else "[]"
    raise TypeError(f"Cannot write {value!r} as TOML")


def dump_config(data: dict, notes: dict[str, str] | None = None) -> str:
    """TOML text with the standard explanatory comments. notes: extra comment per route match."""
    data = dict(data)
    if "fallback_slot" in data:  # older configs kept it top-level
        data["mix"] = {**data.get("mix", {}), "fallback_slot": data.pop("fallback_slot")}
    notes = notes or {}
    lines = ["# hitsoundConvPro project config"]
    extra = [k for k, v in data.items() if isinstance(v, dict) and k not in _SECTIONS]
    for section in (*_SECTIONS, *extra):
        values = data.get(section)
        if not values:
            continue
        lines += ["", f"[{section}]"] + [f"# {n}" for n in _SECTION_NOTES.get(section, [])]
        for key, value in values.items():
            note = _KEY_NOTES.get((section, key))
            if isinstance(value, list):
                lines += ([f"# {note}"] if note else []) + [f"{key} = {_toml_value(value)}"]
            else:
                lines.append(f"{key} = {_toml_value(value)}" + (f"   # {note}" if note else ""))
    lines += [""] + [f"# {line}" for line in _ROUTE_HELP]
    for route in data.get("route", []):
        lines += ["", "[[route]]"]
        for key in (*_ROUTE_KEYS, *(k for k in route if k not in _ROUTE_KEYS)):
            if key not in route:
                continue
            note = notes.get(route["match"]) if key == "match" else None
            lines.append(f"{key} = {_toml_value(route[key])}" + (f"   # {note}" if note else ""))
    return "\n".join(lines) + "\n"


def save_config(path: str | Path, data: dict, notes: dict[str, str] | None = None) -> None:
    """Write the config - only if it loads cleanly, so a bad edit never breaks the file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dump_config(data, notes), encoding="utf-8")
    try:
        load_config(tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
