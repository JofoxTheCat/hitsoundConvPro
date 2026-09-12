"""Role config: which osu!std slot (bank + hitsound) each source sample belongs to."""
from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch

BANKS = ("normal", "soft", "drum")
SOUNDS = ("hitnormal", "hitwhistle", "hitfinish", "hitclap")


def parse_slot(slot: str) -> tuple[str, str]:
    bank, _, sound = slot.strip().lower().partition("-")
    if bank not in BANKS or sound not in SOUNDS:
        raise ValueError(f"Invalid slot '{slot}' - expected e.g. 'normal-hitnormal' or 'soft-hitclap'")
    return bank, sound


@dataclass(frozen=True)
class Route:
    pattern: str
    bank: str
    sound: str
    priority: int = 0
    gain_db: float = 0.0
    order: int = 0  # position in the config; breaks priority ties (earlier wins)
    lock: bool = False  # never move this sample to another bank or slot to save indices / avoid clipping
    anchor: bool = False  # when this sample plays, every other sample of the timestamp is mixed into its slot
    overflow: tuple[str, str] | None = None  # (bank, sound) to move to when its slot's mix would clip

    @property
    def slot(self) -> str:
        return f"{self.bank}-{self.sound}"

    @property
    def rank(self) -> tuple[int, int]:
        return self.priority, -self.order


class Router:
    def __init__(self, routes: list[Route], fallback: Route):
        self.routes = routes
        self.fallback = fallback
        self.unmatched: set[str] = set()

    def route(self, file: str) -> Route:
        name = file.lower()
        for r in self.routes:
            if fnmatch(name, r.pattern.lower()):
                return r
        self.unmatched.add(file)
        return self.fallback


# Guesses for `init-config`: (substrings, slot, priority, lock). First hit wins.
_GUESSES = (
    (("kick", "bassdrum"), "normal-hitnormal", 100, True),
    (("snare", "clap", "rim"), "soft-hitclap", 80, False),
    (("crash", "cymbal", "finish", "splash", "ride"), "soft-hitfinish", 60, False),
    (("hihat", "hi-hat", "hat", "shaker", "tick", "whistle"), "soft-hitwhistle", 40, False),
)
_OSU_NAME_RE = re.compile(r"^(normal|soft|drum)-(hitnormal|hitwhistle|hitfinish|hitclap)\d*\.\w+$", re.I)


def guess_slot(file: str) -> tuple[str, int, bool, bool]:
    """(slot, priority, confident, lock) for a sample file name."""
    if m := _OSU_NAME_RE.match(file):
        slot = f"{m.group(1).lower()}-{m.group(2).lower()}"
        priority = {"hitnormal": 100, "hitclap": 80, "hitfinish": 60, "hitwhistle": 40}[m.group(2).lower()]
        return slot, priority, True, False
    name = file.lower()
    for keys, slot, priority, lock in _GUESSES:
        if any(k in name for k in keys):
            return slot, priority, True, lock
    return "soft-hitwhistle", 10, False, False
