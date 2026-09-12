"""Writes the osu!std hitsound difficulty, the mixed samples, a sample registry and a report."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from .audio import silence, write_audio
from .config import Config
from .convert import Content, ConversionResult, slot_filename
from .i18n import msg, render
from .osufile import SAMPLE_SET_IDS, Beatmap, HitObject, TimingPoint
from .paths import app_dir
from .samples import SampleDir, slider_spans

GENERATED_RE = re.compile(r"^(normal|soft|drum)-(hitnormal|hitwhistle|hitfinish|hitclap|sliderslide)\d+\.(wav|ogg)$", re.I)
ADDITION_BITS = {"hitwhistle": 2, "hitfinish": 4, "hitclap": 8}
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
_SOUND_ORDER = {"hitnormal": 0, "hitwhistle": 1, "hitfinish": 2, "hitclap": 3}


def describe(content: Content) -> str:
    if not content:
        return "[silent]"
    return " + ".join(f"{name} ({20 * math.log10(gain):+.1f} dB)" for name, gain in content)


def content_id(content: Content) -> str:
    return hashlib.sha1(repr(content).encode()).hexdigest()[:10] if content else "silent"


def merge_timing(original: list[TimingPoint], wanted: list[tuple[int, int, int, int]]) -> list[TimingPoint]:
    """Keep all original points (timing, SV, kiai) and add greenlines where the sample state must change.

    wanted: (time, sampleSet, index, volume), sorted by time.
    """
    out: list[TimingPoint] = []
    state = None
    sv, meter, kiai = -100.0, 4, 0
    i = 0
    for time, sample_set, index, volume in wanted:
        while i < len(original) and original[i].time <= time:
            tp = original[i]
            out.append(tp)
            i += 1
            state = (tp.sample_set, tp.sample_index, tp.volume)
            if tp.uninherited:
                sv, meter = -100.0, tp.meter
            else:
                sv = tp.beat_length
            kiai = tp.effects & 1
        if state != (sample_set, index, volume):
            out.append(TimingPoint(time, sv, meter, sample_set, index, volume, False, kiai))
            state = (sample_set, index, volume)
    out.extend(original[i:])
    return out


def build_std_beatmap(result: ConversionResult, cfg: Config) -> Beatmap:
    bm = Beatmap(result.beatmap.path)
    bm.set("General", "Mode", "0")
    bm.set("General", "StackLeniency", "0")  # every circle sits on the same spot; stacking would push them offscreen
    bm.set("Metadata", "Version", cfg.version)
    bm.set("Metadata", "BeatmapID", "0")
    if float(bm.get("Difficulty", "CircleSize", "4") or 4) > 10:  # mania key count, invalid for std
        bm.set("Difficulty", "CircleSize", "4")

    # Greenlines always use the fill bank; the objects carry their own sample sets.
    greenline_set = SAMPLE_SET_IDS[result.fill_bank]
    lines, wanted = [], []
    for n, chord in enumerate(result.chords):
        req, place = chord.req, chord.placement
        hit_sound = sum(ADDITION_BITS[s] for s, _ in req.additions)
        normal_set = SAMPLE_SET_IDS[place.normal_bank]
        addition_set = SAMPLE_SET_IDS[place.addition_bank] if req.additions else 0
        lines.append(f"256,192,{chord.time},{5 if n == 0 else 1},{hit_sound},{normal_set}:{addition_set}:0:0:")
        wanted.append((chord.time, greenline_set, place.index, chord.volume))
    bm.timing_points = merge_timing(bm.timing_points, wanted)
    bm.hit_objects = [HitObject.parse(l) for l in lines]
    return bm


def std_filename(bm: Beatmap) -> str:
    meta = lambda key: bm.get("Metadata", key)
    return ILLEGAL_CHARS.sub("", f"{meta('Artist')} - {meta('Title')} ({meta('Creator')}) [{meta('Version')}].osu")


def slide_slots(result: ConversionResult, cfg: Config) -> set[tuple[str, int]]:
    """(bank, index) pairs whose <bank>-sliderslide<index> a slider body can pick up.
    The slide follows the greenline, which always points to the fill bank."""
    times = [c.time for c in result.chords]
    indices = [c.placement.index for c in result.chords]
    if not cfg.targets:
        return {(result.fill_bank, i) for i in set(indices)}
    active = set()
    for path in cfg.targets:
        for start, end in slider_spans(Beatmap(path)):
            lo = bisect.bisect_right(times, start + cfg.group_tolerance_ms) - 1  # greenline active at the head
            hi = bisect.bisect_right(times, end)
            active |= set(indices[max(lo, 0):hi])
    return {(result.fill_bank, i) for i in active}


def find_mute_file(cfg: Config) -> Path | None:
    p = Path(cfg.slider_slide_file)
    candidates = [p] if p.is_absolute() else [cfg.path.parent / p, Path.cwd() / p, app_dir() / p, cfg.sample_dir / p]
    return next((c for c in candidates if c.is_file()), None)


def sample_registry(written: dict[str, Content], slides: list[str]) -> dict:
    """Every generated file with a content id; files sharing an id sound identical."""
    contents: dict[str, Content] = {}
    files: dict[str, str] = {}
    for name, content in sorted(written.items()):
        files[name] = cid = content_id(content)
        contents[cid] = content
    by_id = defaultdict(list)
    for name, cid in files.items():
        by_id[cid].append(name)
    return {
        "files": files,
        "contents": {
            cid: {"samples": [{"file": f, "gain": g} for f, g in contents[cid]], "files": by_id[cid]}
            for cid in sorted(by_id, key=lambda c: -len(by_id[c]))
        },
        "slider_slides": slides,
    }


def mapset_notes(written: dict[str, Content], cfg: Config, slides: list[str]) -> list[str]:
    """What copying the export into the mapset would do to files from an earlier export."""
    old = [name for name in SampleDir(cfg.sample_dir).files.values() if GENERATED_RE.match(name)]
    if not old:
        return []
    new = {name.lower() for name in [*written, *slides]}
    stale = sorted(name for name in old if name.lower() not in new)
    notes = [msg("mapset_old", total=len(old), replaced=len(old) - len(stale), stale=len(stale))]
    if stale:
        notes.append(msg("mapset_stale", names=", ".join(stale[:12]) + (" …" if len(stale) > 12 else "")))
    return notes


def export(result: ConversionResult, cfg: Config) -> tuple[Path, list[str]]:
    """Returns (path of the .osu, warnings)."""
    out = cfg.output_dir
    out.mkdir(parents=True, exist_ok=True)
    for f in out.iterdir():  # stale samples from an earlier run
        if f.is_file() and GENERATED_RE.match(f.name):
            f.unlink()

    notes = []
    files: dict[str, Content] = {}  # what really landed on disk, per file name
    for name, content in sorted(result.files.items()):
        audio = result.audio.mix(content) if content else silence(cfg.sample_rate)
        written = write_audio(out / name, audio, cfg.sample_rate, cfg.ogg_quality, cfg.ogg_target_db,
                              cfg.sample_format)
        files[written.name] = content

    slides = []
    if cfg.mute_slider_slide:
        mute = find_mute_file(cfg)
        if mute is None:
            notes.append(msg("mute_missing", name=cfg.slider_slide_file))
        for bank, index in sorted(slide_slots(result, cfg)):
            name = f"{bank}-sliderslide{index}{mute.suffix if mute else '.wav'}"
            if mute:
                shutil.copyfile(mute, out / name)
            else:
                write_audio(out / name, silence(cfg.sample_rate), cfg.sample_rate, cfg.ogg_quality,
                            cfg.ogg_target_db)
            slides.append(name)
    notes += mapset_notes(files, cfg, slides)

    bm = build_std_beatmap(result, cfg)
    osu_path = out / std_filename(bm)
    osu_path.write_text(bm.dump(), encoding="utf-8")

    registry = sample_registry(files, slides)
    (out / "samples.json").write_text(json.dumps(registry, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "report.txt").write_text(report_text(result, cfg, notes, slides, files), encoding="utf-8")
    (out / "hitsounds.json").write_text(json.dumps(report_json(result), indent=1, ensure_ascii=False), encoding="utf-8")
    return osu_path, notes


def report_text(result: ConversionResult, cfg: Config, notes: list[tuple] | None = None, slides: list[str] = (),
                written: dict[str, Content] | None = None) -> str:
    usage = Counter(c.placement.index for c in result.chords)
    files = written if written is not None else result.files
    distinct = len({content_id(c) for c in files.values()})
    lines = [
        "hitsoundConvPro - export report",
        f"Source:        {cfg.beatmap.name}",
        f"Samples from:  {cfg.sample_dir}",
        f"Modes:         bank_mode={cfg.bank_mode}, volume_mode={cfg.volume_mode}, on_clip={cfg.on_clip}, "
        f"duplicates={cfg.duplicates}, gain_step_db={cfg.gain_step_db}, silent_bank={cfg.silent_bank}",
        f"Timestamps:    {len(result.chords)}   (from {len(result.events)} samples)",
        f"Combinations:  {result.combinations} distinct",
        f"Other bank:    {sum(c.off_role for c in result.chords)} objects are not in their role's bank (saves indices)",
        f"Indices:       {len(result.indices)}"
        + (f"   ({result.indices[0].number}-{result.last_index}, limit {cfg.last_index})" if result.indices else ""),
        f"Files:         {len(files)} hitsound samples ({sum(n.lower().endswith('.ogg') for n in files)} ogg, "
        f"{distinct} distinct sounds, {sum(not c for c in files.values())} of them silent) "
        f"+ {len(slides)} silent sliderslides",
        f"Fill:          objects without a mania sound play {describe(result.fill)} "
        f"through {result.fill_bank}-hitnormal<i>, at the previous timestamp's volume",
    ]
    if result.gap_points is not None and result.chords:
        last = result.chords[-1].time
        lines.append(f"Target diffs:  {sum(t <= last for t in result.gap_points)} sound points without a mania "
                     f"timestamp inside the hitsounded range (up to {last} ms) in "
                     + ", ".join(p.name for p in cfg.targets))
    lines.append("")

    if spread := sum(c.chosen.spread for c in result.chords):
        lines.append(f"~ {spread} timestamps: a clipping mix was split across slots (sounds the same).")
    if limited := sum(c.limited for c in result.chords):
        lines.append(f"! {limited} timestamps had to be mixed quieter - they would clip even at volume 100.")
    for warning, count in result.warnings.items():
        lines.append(f"! {render(warning, 'en')}  ({count}x)")
    for name in sorted(result.unmatched):
        lines.append(f"! {render(msg('no_route', name=name, slot=cfg.fallback.slot), 'en')}")
    for note in notes or []:
        lines.append(f"! {render(note, 'en')}")
    lines.append("")

    for idx in result.indices:
        lines.append(f"Index {idx.number}  ({usage[idx.number]} objects)")
        for (bank, sound), content in sorted(idx.slots.items(), key=lambda kv: (_SOUND_ORDER[kv[0][1]], kv[0][0])):
            fill = "   (fill)" if (bank, sound) == (result.fill_bank, "hitnormal") else ""
            lines.append(f"  {slot_filename(bank, sound, idx.number, result.ext):<24} {describe(content)}{fill}")
        lines.append("")
    return "\n".join(lines)


def report_json(result: ConversionResult) -> dict:
    """Machine-readable result, meant for the upcoming GUI."""
    def content(c: Content) -> list[dict]:
        return [{"file": name, "gain": gain} for name, gain in c]

    return {
        "fill": {"bank": result.fill_bank, "content": content(result.fill)},
        "gap_points": result.gap_points,
        "indices": [
            {"index": idx.number, "slots": {f"{b}-{s}": content(c) for (b, s), c in sorted(idx.slots.items())}}
            for idx in result.indices
        ],
        "objects": [
            {
                "time": c.time,
                "volume": c.volume,
                "index": c.placement.index,
                "normal_bank": c.placement.normal_bank,
                "addition_bank": c.placement.addition_bank if c.req.additions else None,
                "additions": [s for s, _ in c.req.additions],
                "limited": c.limited,
                "spread": c.chosen.spread,
                "sources": [{"file": e.file, "volume": e.volume} for e in c.events],
            }
            for c in result.chords
        ],
    }
