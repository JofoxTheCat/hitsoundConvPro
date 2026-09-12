"""Core conversion: mania sample events -> osu!std hitsound slots packed into custom indices.

osu!std plays per hit object exactly one custom index, and from it:
  <normalSet>-hitnormal<i>                 (always)
  <additionSet>-hitwhistle/finish/clap<i>  (any combination, all from the same additionSet)
Each chord (all samples on one timestamp) is split into those 4 channels according to the
role config. Samples sharing a channel are mixed into one file, relative volumes baked in.
Chords whose channel contents don't contradict each other share an index; the packer picks
the index where the fewest new files are needed.

Fill: every greenline points to the fill bank, and <fill bank>-hitnormal<i> holds the same fill
sound in every index. Chord objects carry their own sample sets; std objects the mania chart has no
sound for (extra slider heads, ends, circles) inherit the greenline and play the fill sound – no
extra greenlines needed.
"""
from __future__ import annotations

import bisect
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from .audio import AudioCache
from .config import Config
from .i18n import msg
from .osufile import Beatmap
from .routing import BANKS, SOUNDS, Route, Router
from .samples import SampleDir, SampleEvent, resolve_events, sound_points

Content = tuple[tuple[str, float], ...]  # sorted (file, gain) pairs; () = silence
CLIP = 1.0001


def slot_filename(bank: str, sound: str, index: int, ext: str = ".wav") -> str:
    return f"{bank}-{sound}{index if index > 1 else ''}{ext}"


@dataclass(frozen=True)
class Requirement:
    normal_bank: str | None  # None: nothing routed to hitnormal -> needs a silent hitnormal
    normal: Content
    addition_bank: str | None
    additions: tuple[tuple[str, Content], ...]  # (sound, content) in SOUNDS order
    normal_locked: bool = False     # a route with lock=true forbids moving to another bank
    additions_locked: bool = False


@dataclass(frozen=True)
class Option:
    """One way to play a chord: object volume + what the files must contain."""
    volume: int
    req: Requirement
    limited: bool  # had to be turned down to avoid clipping
    spread: bool = False  # samples were moved to another slot to avoid clipping


@dataclass(frozen=True)
class Placement:
    index: int
    normal_bank: str
    addition_bank: str | None


@dataclass
class Chord:
    time: int
    events: list[SampleEvent]
    options: tuple[Option, ...]  # preferred first
    needs_fill: bool = True      # a target object without a mania sound follows this timestamp
    chosen: Option | None = None
    placement: Placement | None = None

    @property
    def volume(self) -> int:
        return self.chosen.volume

    @property
    def req(self) -> Requirement:
        return self.chosen.req

    @property
    def limited(self) -> bool:
        return self.chosen.limited

    @property
    def off_role(self) -> bool:
        """Landed in a different bank than the role config asked for."""
        r, p = self.req, self.placement
        return bool((r.normal and p.normal_bank != r.normal_bank) or (r.additions and p.addition_bank != r.addition_bank))


@dataclass
class SampleIndex:
    number: int
    slots: dict[tuple[str, str], Content] = field(default_factory=dict)


@dataclass
class ConversionResult:
    beatmap: Beatmap
    events: list[SampleEvent]
    chords: list[Chord]
    indices: list[SampleIndex]
    warnings: Counter
    unmatched: set[str]
    audio: AudioCache
    fill_bank: str
    fill: Content = ()                   # what std objects without a mania sound play
    gap_points: list[int] | None = None  # sound points of the target diffs without a mania timestamp
    ext: str = ".wav"                    # extension of the generated samples

    @property
    def last_index(self) -> int | None:
        return self.indices[-1].number if self.indices else None

    @property
    def combinations(self) -> int:
        return len({c.req for c in self.chords})

    @property
    def files(self) -> dict[str, Content]:
        return {slot_filename(b, s, idx.number, self.ext): c
                for idx in self.indices for (b, s), c in idx.slots.items()}


def group_events(events: list[SampleEvent], tolerance_ms: int) -> list[tuple[int, list[SampleEvent]]]:
    chords: list[tuple[int, list[SampleEvent]]] = []
    for e in sorted(events, key=lambda e: e.time):
        if chords and e.time - chords[-1][0] <= tolerance_ms:
            chords[-1][1].append(e)
        else:
            chords.append((e.time, [e]))
    return chords


def loudest_per_file(events: list[SampleEvent]) -> list[SampleEvent]:
    """The same sample several times on one timestamp plays once, at the loudest of its volumes."""
    best: dict[str, SampleEvent] = {}
    for e in events:
        key = e.file.lower()
        if key not in best or e.volume > best[key].volume:
            best[key] = e
    return list(best.values())


def _quantize(gain: float, step_db: float) -> float:
    if step_db > 0:
        gain = 10 ** (round(20 * math.log10(gain) / step_db) * step_db / 20)
    return round(gain, 4)


def _content(items: list[tuple[str, float]], scale: float, step_db: float) -> Content:
    merged: dict[str, float] = defaultdict(float)
    for name, amp in items:
        merged[name] += amp  # duplicates="sum": the same file twice on one tick plays twice as loud
    return tuple(sorted((name, _quantize(amp / scale, step_db)) for name, amp in merged.items() if amp > 0))


def _clamp_volume(v: float) -> int:
    return max(5, min(100, round(v)))


def _lead(routes: list[Route]) -> Route:
    """The route that decides a channel's bank: anchors first, then priority."""
    return max(routes, key=lambda r: (r.anchor, r.rank))


def build_chord(time: int, events: list[SampleEvent], router: Router, audio: AudioCache, step_db: float,
                volume_mode: str = "relative", on_clip: str = "roles", duplicates: str = "loudest") -> Chord | None:
    played = loudest_per_file(events) if duplicates == "loudest" else events
    items = [(r, e.file, e.volume / 100 * 10 ** (r.gain_db / 20)) for e in played if e.volume > 0 for r in [router.route(e.file)]]
    if not items:
        return None
    own = [r for r, _, _ in items]  # every sample's role
    anchor = max((r for r in own if r.anchor), key=lambda r: r.rank, default=None)
    # Kick focus: an anchor sample pulls every other (unlocked) sample of the chord into its own slot,
    # so the object plays one mixed file – and with beatmap hitsounds off just that slot's skin sample.
    # `slots` holds the route each sample currently plays through.
    start = [replace(r, bank=anchor.bank, sound=anchor.sound) if anchor and not (r.lock or r.anchor) else r for r in own]

    def channel(slots: list[Route], sound: str, scale: float) -> Content:
        return _content([(f, a) for (_, f, a), s in zip(items, slots) if s.sound == sound], scale, step_db)

    def layout(slots: list[Route], volume: int, headroom: float = 1.0) -> tuple[Requirement, float]:
        scale = volume / 100 * headroom
        normal = [s for s in slots if s.sound == "hitnormal"]
        additions = [s for s in slots if s.sound != "hitnormal"]
        # Only one hitnormal plays and all additions share one bank: the most important sample decides.
        req = Requirement(
            normal_bank=_lead(normal).bank if normal else None,
            normal=channel(slots, "hitnormal", scale),
            addition_bank=_lead(additions).bank if additions else None,
            additions=tuple((s, channel(slots, s, scale)) for s in SOUNDS[1:] if any(x.sound == s for x in slots)),
            normal_locked=any(s.lock for s in normal),
            additions_locked=any(s.lock for s in additions),
        )
        return req, max(audio.peak(c) for c in (req.normal, *(c for _, c in req.additions)))

    def escape(k: int, slots: list[Route]) -> Route | None:
        """Where sample k may go when its channel clips: a pulled-in sample back to its own role,
        a sample already in its role to its overflow slot."""
        r = own[k]
        if slots[k].sound != r.sound:
            return r
        if r.overflow and r.overflow[1] != slots[k].sound:
            return replace(r, bank=r.overflow[0], sound=r.overflow[1])
        return None

    def relieve(slots: list[Route], volume: int) -> list[Route] | None:
        """A channel would clip: move its least important samples out, each at most once. The targets
        are role or overflow slots, so the result still sounds sensible with skin hitsounds."""
        slots, moved = list(slots), set()
        for sound in SOUNDS:
            while audio.peak(channel(slots, sound, volume / 100)) > CLIP:
                movable = [k for k, s in enumerate(slots) if s.sound == sound and k not in moved
                           and not (own[k].anchor or own[k].lock) and escape(k, slots)]
                if not movable:
                    break
                k = min(movable, key=lambda k: (own[k].rank, items[k][2]))
                slots[k] = escape(k, slots)
                moved.add(k)
        return slots if moved else None

    def spread(slots: list[Route], volume: int) -> list[Route] | None:
        """Split clipping channels: move part of their samples into additions this chord doesn't use.
        Whistle first, finish last – with beatmap hitsounds off a stray skin finish (crash) is the most jarring."""
        slots = list(slots)
        free = [s for s in ("hitwhistle", "hitclap", "hitfinish") if all(x.sound != s for x in slots)]
        moved = False
        for sound in SOUNDS:
            members = [k for k, s in enumerate(slots) if s.sound == sound and not own[k].lock]
            if not free or len(members) < 2 or audio.peak(channel(slots, sound, volume / 100)) <= CLIP:
                continue
            target = free.pop(0)
            kept = away = 0.0
            for k in sorted(members, key=lambda k: -items[k][2]):  # largest first, balance the two halves
                if kept <= away:
                    kept += items[k][2]
                else:
                    away += items[k][2]
                    slots[k] = replace(slots[k], sound=target)
            moved = True
        return slots if moved else None

    def option(base_volume: int) -> Option:
        slots, volume = start, base_volume
        req, peak = layout(slots, volume)
        if peak > CLIP:  # a mix would clip: raise the object volume and turn the files down instead
            volume = max(volume, _clamp_volume(math.ceil(volume * peak)))
            req, peak = layout(slots, volume)
        moved_any = False
        for mover, allowed in ((relieve, on_clip != "limit"), (spread, on_clip == "spread" and anchor is None)):
            if peak > CLIP and allowed and (moved := mover(slots, volume)):
                slots, moved_any = moved, True
                req, peak = layout(slots, volume)
                calm, calm_peak = layout(slots, base_volume)  # moving may have made the raise unnecessary
                if calm_peak <= CLIP:
                    volume, req, peak = base_volume, calm, calm_peak
        limited = peak > CLIP
        if limited:
            req, _ = layout(slots, volume, peak)
        return Option(volume, req, limited, moved_any)

    # relative: the loudest sample sets the object volume, the rest is baked in relative to it
    # absolute: object volume 100, every file carries its own volume (reuses better across chords)
    relative = _clamp_volume(max(a for *_, a in items) * 100)
    # grid: several ways to write the same loudness (V x gain stays constant), so the packer can reuse
    # a file that already exists instead of creating a new one. The sound is the same either way.
    grid = list(range(max(5, -(-relative // 5) * 5), 101, 5)) or [100]
    volumes = {"relative": [relative], "absolute": [100], "auto": [relative, 100],
               "grid": [relative, *grid]}[volume_mode]
    return Chord(time, events, tuple(dict.fromkeys(option(v) for v in volumes)))


def _bank_order(preferred: str, flexible: bool) -> list[str]:
    return [preferred] + [b for b in BANKS if b != preferred] if flexible else [preferred]


def _fit_normal(req: Requirement, idx: SampleIndex, flexible: bool, silent_bank: str, fill_bank: str | None) -> str | None:
    if req.normal:
        # The fill bank's hitnormal is reserved for the fill sound; a role in that bank may move elsewhere.
        flex = (flexible and not req.normal_locked) or req.normal_bank == fill_bank
        for bank in _bank_order(req.normal_bank, flex):
            if idx.slots.get((bank, "hitnormal")) in (None, req.normal):
                return bank
        return None
    # Silent hitnormal: with beatmap hitsounds off this bank's skin hitnormal plays, so keep it in one bank.
    for want in ((), None):  # reuse an existing silent file before claiming a free slot
        for bank in _bank_order(silent_bank, flexible):
            if bank != fill_bank and idx.slots.get((bank, "hitnormal"), None) == want:
                return bank
    return None


def _fit(req: Requirement, idx: SampleIndex, flexible: bool, silent_bank: str,
         fill_bank: str | None) -> tuple[str, str | None] | None:
    """(hitnormal bank, addition bank) if `req` can live in `idx`, else None."""
    banks = _bank_order(req.addition_bank, flexible and not req.additions_locked) if req.additions else [None]
    for addition_bank in banks:
        if any(idx.slots.get((addition_bank, s)) not in (None, c) for s, c in req.additions):
            continue
        if normal_bank := _fit_normal(req, idx, flexible, silent_bank, fill_bank):
            return normal_bank, addition_bank
    return None


def _new_files(req: Requirement, idx: SampleIndex, banks: tuple[str, str | None]) -> int:
    normal_bank, addition_bank = banks
    slots = [(normal_bank, "hitnormal")] + [(addition_bank, s) for s, _ in req.additions]
    return sum(idx.slots.get(slot) is None for slot in slots)


def _claim(idx: SampleIndex, req: Requirement, banks: tuple[str, str | None]) -> None:
    normal_bank, addition_bank = banks
    idx.slots[(normal_bank, "hitnormal")] = req.normal
    for sound, content in req.additions:
        idx.slots[(addition_bank, sound)] = content


def _pack_once(chords: list[Chord], first_index: int, flexible_banks: bool, silent_bank: str,
               fill: tuple[str, Content] | None) -> list[SampleIndex]:
    """Most demanding and most frequent chords first; each goes where it needs the fewest new files.

    Role banks are tried first; other banks (if allowed) only when the role banks fit nowhere.
    A new index is opened only when nothing fits. The fill bank's hitnormal is only claimed in
    indices that hold a timestamp which actually needs the fill, so the bank stays usable elsewhere.
    """
    fill_bank, fill_content = fill if fill else (None, None)
    fill_slot = (fill_bank, "hitnormal")
    groups: dict[tuple, list[Chord]] = defaultdict(list)
    for c in chords:
        groups[(c.options, bool(fill) and c.needs_fill)].append(c)

    def demand(key: tuple) -> int:
        req = key[0][0].req
        return len(req.additions) + (1 if req.normal else 0)

    def best_in(idx: SampleIndex, options: tuple[Option, ...], wants_fill: bool, flexible: bool):
        """Cheapest option for this index, or None. While a timestamp that needs the fill is being
        fitted the fill slot counts as taken, so no content can claim it and be overwritten later."""
        if wants_fill and idx.slots.get(fill_slot, fill_content) != fill_content:
            return None
        reserve = wants_fill and fill_slot not in idx.slots
        if reserve:
            idx.slots[fill_slot] = fill_content
        try:
            found = None
            for option in options:
                if banks := _fit(option.req, idx, flexible, silent_bank, fill_bank):
                    cost = _new_files(option.req, idx, banks) + reserve
                    if found is None or cost < found[0]:
                        found = (cost, option, banks)
            return found
        finally:
            if reserve:
                del idx.slots[fill_slot]

    indices: list[SampleIndex] = []
    for key in sorted(groups, key=lambda k: (demand(k), len(groups[k])), reverse=True):
        options, wants_fill = key
        best = None
        for flexible in ((False, True) if flexible_banks else (False,)):
            for idx in indices:
                if (found := best_in(idx, options, wants_fill, flexible)) and (best is None or found[0] < best[0]):
                    best = (found[0], idx, found[1], found[2])
            if best:
                break
        if best is None:
            idx = SampleIndex(first_index + len(indices))
            indices.append(idx)
            if wants_fill:
                idx.slots[fill_slot] = fill_content
            banks = (_fit(options[0].req, idx, False, silent_bank, fill_bank)
                     or _fit(options[0].req, idx, True, silent_bank, fill_bank))
            best = (0, idx, options[0], banks)
        _, idx, option, banks = best
        if wants_fill:
            idx.slots[fill_slot] = fill_content
        _claim(idx, option.req, banks)
        for c in groups[key]:
            c.chosen = option
            c.placement = Placement(idx.number, *banks)
    return indices


def pack(chords: list[Chord], first_index: int, flexible_banks: bool, silent_bank: str = "soft",
         fill: tuple[str, Content] | None = None, attempts: int = 1, seed: int = 0) -> list[SampleIndex]:
    """Pack the chords into indices, trying several orderings and keeping the smallest result.

    Which order wins changes nothing about the sound - only how many files and indices it takes.
    """
    best = None
    rng = random.Random(seed)
    for attempt in range(max(1, attempts)):
        order = chords if attempt == 0 else rng.sample(chords, len(chords))
        indices = _pack_once(order, first_index, flexible_banks, silent_bank, fill)
        score = (len(indices), sum(len(i.slots) for i in indices))
        if best is None or score < best[0]:
            best = (score, indices, [(c, c.chosen, c.placement) for c in chords])
    for c, chosen, placement in best[2]:  # restore the winning assignment
        c.chosen, c.placement = chosen, placement
    return best[1]


def merge_similar(chords: list[Chord], tolerance_db: float) -> None:
    """Let contents of the same samples share one file when their gains differ by less than the
    tolerance. The most used content wins, so the difference stays below the tolerance everywhere."""
    if tolerance_db <= 0:
        return
    counts: Counter = Counter()
    for c in chords:
        for option in c.options:
            for content in (option.req.normal, *(x for _, x in option.req.additions)):
                if content:
                    counts[content] += 1

    representatives: dict[tuple, list[Content]] = defaultdict(list)
    mapping: dict[Content, Content] = {}
    for content, _ in counts.most_common():
        key = tuple(name for name, _ in content)
        for rep in representatives[key]:
            if all(abs(20 * math.log10(gain / other)) <= tolerance_db
                   for (_, gain), (_, other) in zip(content, rep)):
                mapping[content] = rep
                break
        else:
            representatives[key].append(content)

    def merged(option: Option) -> Option:
        req = option.req
        return replace(option, req=replace(
            req,
            normal=mapping.get(req.normal, req.normal),
            additions=tuple((sound, mapping.get(c, c)) for sound, c in req.additions)))

    for c in chords:
        c.options = tuple(dict.fromkeys(merged(o) for o in c.options))


def pick_fill(cfg: Config, events: list[SampleEvent], router: Router, warnings: Counter) -> Content:
    """What std objects without a mania sound play (at the previous timestamp's volume).
    auto = the most frequent sample routed to hitnormal (anchors excluded), else the most frequent sample."""
    if cfg.fill_sample == "none" or not events:
        return ()
    counts = Counter(e.file for e in events)
    if cfg.fill_sample == "auto":
        normal = [f for f, _ in counts.most_common() if (r := router.route(f)).sound == "hitnormal" and not r.anchor]
        name = normal[0] if normal else counts.most_common(1)[0][0]
    else:
        name = SampleDir(cfg.sample_dir).find(cfg.fill_sample)
        if name is None:
            warnings[msg("fill_missing", name=cfg.fill_sample)] += 1
            return ()
    return ((name, _quantize(10 ** (cfg.fill_gain_db / 20), cfg.gain_step_db)),)


def find_gap_points(targets: list[Path], chord_times: list[int], tolerance_ms: int) -> list[int]:
    """Sound points (circles, slider heads/repeats/tails, spinner ends) of the target std diffs
    that don't coincide with a mania timestamp."""
    def near(t: int) -> bool:
        i = bisect.bisect_left(chord_times, t - tolerance_ms)
        return i < len(chord_times) and chord_times[i] <= t + tolerance_ms

    return sorted({t for path in targets for t, _ in sound_points(Beatmap(path)) if not near(t)})


def mark_fill_needs(chords: list[Chord], gap_points: list[int] | None) -> None:
    """Without target diffs every timestamp keeps the fill; with them only those an object without a
    mania sound follows - the other indices can use the fill bank for real samples."""
    if gap_points is None:
        return
    times = [c.time for c in chords]
    for n, c in enumerate(chords):
        following = times[n + 1] if n + 1 < len(times) else math.inf
        i = bisect.bisect_right(gap_points, c.time)
        c.needs_fill = i < len(gap_points) and gap_points[i] < following


def convert(cfg: Config) -> ConversionResult:
    bm = Beatmap(cfg.beatmap)
    events, warnings = resolve_events(bm, SampleDir(cfg.sample_dir))
    audio = AudioCache(cfg.sample_dir, cfg.sample_rate)
    router = Router(cfg.routes, cfg.fallback)
    chords = [
        chord for time, group in group_events(events, cfg.group_tolerance_ms)
        if (chord := build_chord(time, group, router, audio, cfg.gain_step_db, cfg.volume_mode, cfg.on_clip, cfg.duplicates))
    ]
    fill = pick_fill(cfg, events, router, warnings)
    gap_points = find_gap_points(cfg.targets, [c.time for c in chords], cfg.group_tolerance_ms) if cfg.targets else None
    mark_fill_needs(chords, gap_points)
    merge_similar(chords, cfg.merge_tolerance_db)
    indices = pack(chords, cfg.first_index, cfg.bank_mode == "prefer", cfg.silent_bank, (cfg.fill_bank, fill),
                   attempts=cfg.pack_attempts)
    return ConversionResult(bm, events, chords, indices, warnings, router.unmatched, audio, cfg.fill_bank, fill,
                            gap_points, ".wav" if cfg.sample_format == "wav" else ".ogg")
