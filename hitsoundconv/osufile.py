"""Minimal reader/writer for .osu beatmap files (only what hitsounding needs)."""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from pathlib import Path

SECTION_RE = re.compile(r"^\[(.+)\]$")

SAMPLE_SET_IDS = {"normal": 1, "soft": 2, "drum": 3}
SAMPLE_SET_NAMES = {v: k for k, v in SAMPLE_SET_IDS.items()}

# [General] and [Editor] write "Key: Value", the other key/value sections "Key:Value".
_SPACED_SECTIONS = ("General", "Editor")


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(value)


@dataclass
class TimingPoint:
    time: float
    beat_length: float
    meter: int = 4
    sample_set: int = 0
    sample_index: int = 0
    volume: int = 100
    uninherited: bool = True
    effects: int = 0

    @classmethod
    def parse(cls, line: str) -> TimingPoint:
        p = [s.strip() for s in line.split(",")]
        tp = cls(float(p[0]), float(p[1]))
        if len(p) > 2:
            tp.meter = int(p[2])
        if len(p) > 3:
            tp.sample_set = int(p[3])
        if len(p) > 4:
            tp.sample_index = int(p[4])
        if len(p) > 5:
            tp.volume = int(p[5])
        if len(p) > 6:
            tp.uninherited = p[6] == "1"
        if len(p) > 7:
            tp.effects = int(p[7])
        return tp

    def to_line(self) -> str:
        return ",".join([
            _num(self.time), _num(self.beat_length), str(self.meter), str(self.sample_set),
            str(self.sample_index), str(self.volume), "1" if self.uninherited else "0", str(self.effects),
        ])


@dataclass
class HitSample:
    """normalSet:additionSet:index:volume:filename – 0 means "inherit from the timing point"."""
    normal_set: int = 0
    addition_set: int = 0
    index: int = 0
    volume: int = 0
    filename: str = ""

    @classmethod
    def parse(cls, text: str) -> HitSample:
        if not text.strip():
            return cls()
        p = text.split(":", 4)
        p += [""] * (5 - len(p))

        def num(s: str) -> int:
            return int(s) if s.strip() else 0

        return cls(num(p[0]), num(p[1]), num(p[2]), num(p[3]), p[4].strip())


@dataclass
class HitObject:
    x: int
    y: int
    time: int
    type: int
    hit_sound: int
    sample: HitSample = field(default_factory=HitSample)
    end_time: int | None = None
    raw: str = ""

    @classmethod
    def parse(cls, line: str) -> HitObject:
        p = line.split(",")
        obj = cls(int(float(p[0])), int(float(p[1])), int(float(p[2])), int(p[3]), int(p[4]), raw=line)
        if obj.type & 128:  # osu!mania hold note: endTime:hitSample
            end, _, sample = ",".join(p[5:]).partition(":")
            obj.end_time = int(float(end))
            obj.sample = HitSample.parse(sample)
        elif obj.type & 8:  # spinner
            obj.end_time = int(float(p[5]))
            obj.sample = HitSample.parse(",".join(p[6:]))
        elif obj.type & 2:  # slider: the head plays edgeSounds[0] with edgeSets[0]
            obj.sample = HitSample.parse(",".join(p[10:]))
            if len(p) > 8 and p[8]:
                obj.hit_sound = int(p[8].split("|")[0])
            if len(p) > 9 and p[9]:
                normal, _, addition = p[9].split("|")[0].partition(":")
                obj.sample.normal_set = int(normal or 0)
                obj.sample.addition_set = int(addition or 0)
        else:  # circle / mania note
            obj.sample = HitSample.parse(",".join(p[5:]))
        return obj


class Beatmap:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.header = "osu file format v14"
        self.sections: dict[str, list[str]] = {}
        current = None
        for line in self.path.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            match = SECTION_RE.match(stripped)
            if match:
                current = match.group(1)
                self.sections[current] = []
            elif current is None:
                if stripped:
                    self.header = stripped
            else:
                self.sections[current].append(line.rstrip())

        # Stable sort keeps file order for equal times, so the later point wins like in osu!.
        self.timing_points = sorted((TimingPoint.parse(l) for l in self.lines("TimingPoints")), key=lambda tp: tp.time)
        self._tp_times = [tp.time for tp in self.timing_points]
        self._red = [tp for tp in self.timing_points if tp.uninherited] or self.timing_points[:1]
        self._red_times = [tp.time for tp in self._red]
        self.hit_objects = sorted((HitObject.parse(l) for l in self.lines("HitObjects")), key=lambda o: o.time)

    def lines(self, section: str) -> list[str]:
        return [l.strip() for l in self.sections.get(section, []) if l.strip() and not l.strip().startswith("//")]

    def get(self, section: str, key: str, default: str = "") -> str:
        for line in self.sections.get(section, []):
            k, sep, v = line.partition(":")
            if sep and k.strip() == key:
                return v.strip()
        return default

    def set(self, section: str, key: str, value: str) -> None:
        lines = self.sections.setdefault(section, [])
        entry = f"{key}: {value}" if section in _SPACED_SECTIONS else f"{key}:{value}"
        for i, line in enumerate(lines):
            k, sep, _ = line.partition(":")
            if sep and k.strip() == key:
                lines[i] = entry
                return
        pos = len(lines)
        while pos and not lines[pos - 1].strip():
            pos -= 1
        lines.insert(pos, entry)

    @property
    def default_sample_set(self) -> int:
        return SAMPLE_SET_IDS.get(self.get("General", "SampleSet", "Normal").lower(), 1)

    def timing_point_at(self, time: float) -> TimingPoint:
        i = bisect.bisect_right(self._tp_times, time) - 1
        return self.timing_points[max(i, 0)]

    def red_point_at(self, time: float) -> TimingPoint:
        i = bisect.bisect_right(self._red_times, time) - 1
        return self._red[max(i, 0)]

    def dump(self) -> str:
        out = [self.header, ""]
        for name, lines in self.sections.items():
            out.append(f"[{name}]")
            if name == "TimingPoints":
                out.extend(tp.to_line() for tp in self.timing_points)
            elif name == "HitObjects":
                out.extend(o.raw for o in self.hit_objects)
            else:
                body = list(lines)
                while body and not body[-1].strip():
                    body.pop()
                out.extend(body)
            out.append("")
        return "\n".join(out)
