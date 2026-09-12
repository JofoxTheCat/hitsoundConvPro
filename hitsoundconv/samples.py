"""Resolve which audio files a beatmap actually plays, following osu!'s sample rules."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .i18n import msg
from .osufile import SAMPLE_SET_NAMES, Beatmap

ADDITIONS = ((2, "hitwhistle"), (4, "hitfinish"), (8, "hitclap"))
AUDIO_EXTS = (".wav", ".ogg", ".mp3")


@dataclass(frozen=True)
class SampleEvent:
    time: int
    file: str    # file name inside the sample directory
    volume: int  # osu! volume percentage


class SampleDir:
    """Case-insensitive view of the files in a beatmap folder."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.files = {p.name.lower(): p.name for p in self.path.iterdir() if p.is_file()} if self.path.is_dir() else {}

    def find(self, name: str) -> str | None:
        return self.files.get(name.lower())

    def find_stem(self, stem: str) -> str | None:
        for ext in AUDIO_EXTS:
            if hit := self.find(stem + ext):
                return hit
        return None


def sample_stem(bank: int, sound: str, index: int) -> str:
    """normal-hitclap / soft-hitwhistle7 – index 1 has no suffix."""
    return f"{SAMPLE_SET_NAMES[bank]}-{sound}{index if index > 1 else ''}"


def _slide_duration(bm: Beatmap, obj) -> tuple[int, float]:
    """(slides, duration of one slide in ms) of a slider."""
    p = obj.raw.split(",")
    slides, length = int(p[6]), float(p[7])
    multiplier = float(bm.get("Difficulty", "SliderMultiplier", "1.4") or 1.4)
    tp = bm.timing_point_at(obj.time)
    velocity = 1.0 if tp.uninherited else -100 / tp.beat_length
    return slides, length / (multiplier * 100 * velocity) * bm.red_point_at(obj.time).beat_length


def slider_spans(bm: Beatmap) -> list[tuple[int, int]]:
    """(start, end) of every slider body."""
    spans = []
    for obj in bm.hit_objects:
        if obj.type & 2:
            slides, duration = _slide_duration(bm, obj)
            spans.append((obj.time, round(obj.time + slides * duration)))
    return spans


def sound_points(bm: Beatmap) -> list[tuple[int, str]]:
    """(time, kind) for every point of a std map that plays a hitsound:
    circles, slider heads/repeats/tails and spinner ends."""
    points = []
    for obj in bm.hit_objects:
        if obj.type & 2:
            slides, duration = _slide_duration(bm, obj)
            points += [(round(obj.time + k * duration), "head" if k == 0 else "tail" if k == slides else "repeat")
                       for k in range(slides + 1)]
        elif obj.type & 8:
            points.append((obj.end_time, "spinner"))
        else:
            points.append((obj.time, "circle"))
    return sorted(points)


def resolve_events(bm: Beatmap, sample_dir: SampleDir, skin: bool = False) -> tuple[list[SampleEvent], Counter]:
    """Every sample file each hit object plays, with its effective volume.
    skin=True: like osu! with beatmap hitsounds off – custom indices and filenames are ignored."""
    events: list[SampleEvent] = []
    warnings: Counter = Counter()
    default_set = bm.default_sample_set
    for obj in bm.hit_objects:
        tp = bm.timing_point_at(obj.time)
        s = obj.sample
        volume = s.volume or tp.volume
        if s.filename and not skin:  # a filename replaces hitnormal and all additions
            if name := sample_dir.find(s.filename):
                events.append(SampleEvent(obj.time, name, volume))
            else:
                warnings[msg("missing_file", name=s.filename)] += 1
            continue

        normal_set = s.normal_set or tp.sample_set or default_set
        addition_set = s.addition_set or normal_set
        index = 1 if skin else s.index or tp.sample_index
        sounds = [(normal_set, "hitnormal")] + [(addition_set, n) for bit, n in ADDITIONS if obj.hit_sound & bit]
        for bank, sound in sounds:
            stem = sample_stem(bank, sound, index)
            if index == 0:
                warnings[msg("skin_default", name=stem)] += 1
            elif name := sample_dir.find_stem(stem):
                events.append(SampleEvent(obj.time, name, volume))
            else:
                warnings[msg("missing_sample", name=stem)] += 1
    return events, warnings
