"""Command line: analyze, init-config, convert, verify, mode, gui."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import install
from .audio import AudioCache, load_audio, write_wav
from .config import load_config
from .convert import convert, find_gap_points, group_events, loudest_per_file
from .export import content_id, export, report_text, std_filename
from .i18n import msg, render
from .osufile import Beatmap
from .project import create_config
from .samples import SampleDir, resolve_events, sample_stem


def _load_events(beatmap: Path, sample_dir: Path | None, skin: bool = False):
    bm = Beatmap(beatmap)
    events, warnings = resolve_events(bm, SampleDir(sample_dir or beatmap.parent), skin)
    return bm, events, warnings


def _print_warnings(warnings, prefix: str = "") -> None:
    for warning, count in warnings.items():
        print(f"! {prefix}{render(warning)} ({count}x)")


def cmd_analyze(args) -> int:
    bm, events, warnings = _load_events(Path(args.beatmap), args.sample_dir and Path(args.sample_dir))
    chords = group_events(events, args.tolerance)
    print(f"{bm.path.name}\n{len(bm.hit_objects)} objects, {len(events)} samples, {len(chords)} timestamps\n")

    volumes = defaultdict(set)
    for e in events:
        volumes[e.file].add(e.volume)
    print("Samples:")
    for name, count in Counter(e.file for e in events).most_common():
        print(f"  {count:5}  {name:<32} volumes: {', '.join(map(str, sorted(volumes[name])))}")

    print("\nSimultaneous samples per timestamp:")
    for n, count in sorted(Counter(len(g) for _, g in chords).items()):
        print(f"  {n}: {count}x")

    combos = Counter(" + ".join(sorted(e.file for e in g)) for _, g in chords)
    print(f"\nCombinations ({len(combos)} distinct, top {args.top}):")
    for combo, count in combos.most_common(args.top):
        print(f"  {count:5}  {combo}")
    _print_warnings(warnings)
    return 0


def cmd_init_config(args) -> int:
    try:
        path = create_config(args.beatmap, args.output, args.force)
    except (FileExistsError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    print(f"Config written: {path}")
    return 0


def _convert_and_export(cfg, force: bool = False) -> int:
    result = convert(cfg)
    if len(result.indices) and result.last_index > cfg.last_index:
        print(f"ERROR: {len(result.indices)} indices needed, allowed up to {cfg.last_index}. "
              "Ideas: raise gain_step_db, use fewer distinct volumes, route samples into shared slots.", file=sys.stderr)
        if not force:
            return 2
    osu_path, _ = export(result, cfg)
    print(f"{len(result.chords)} timestamps -> {result.combinations} combinations -> "
          f"{len(result.indices)} indices ({result.indices[0].number}-{result.last_index}), {len(result.files)} WAVs")
    print(f"Export: {osu_path}")
    print(f"Report: {cfg.output_dir / 'report.txt'}")
    return 0


def cmd_convert(args) -> int:
    cfg = load_config(args.config)
    if args.dry_run:
        print(report_text(convert(cfg), cfg))
        return 0
    return _convert_and_export(cfg, args.force)


def cmd_mode(args) -> int:
    """EDIT <-> LISTEN."""
    cfg = load_config(args.config)
    if args.mode is None:
        status = install.status(cfg)
        print(f"Mode: {status['mode'].upper()} - {status['installed']} installed files in {status['mapset']}")
        if status["unknown"]:
            print(f"! {len(status['unknown'])} files in the mapset look like an old export (not installed by mode): "
                  + ", ".join(status["unknown"][:8]) + (" ..." if len(status["unknown"]) > 8 else ""))
        return 0
    if args.mode == "listen":
        if not args.no_convert and (code := _convert_and_export(cfg)):
            return code
        r = install.listen(cfg)
        print(render(msg("listen", installed=r["installed"], copied=r["copied"], removed=r["removed"])))
        if r["adopted"]:
            print("  " + render(msg("adopted", adopted=r["adopted"])))
    else:
        r = install.edit(cfg, include_unknown=args.include_unknown)
        print(render(msg("edit", removed=r["removed"])))
        if r["unknown"]:
            print("! " + render(msg("edit_unknown", unknown=len(r["unknown"])))
                  + " (--include-unknown moves them to the backup)")
    if r["backed_up"]:
        print(render(msg("backed_up", count=len(r["backed_up"]), folder=r["backup_dir"])))
    print(render(msg("reload_hint")))
    return 0


def cmd_gui(args) -> int:
    from .gui.server import run
    run(args.config, args.port, not args.no_browser)
    return 0


def _db(x: float) -> float:
    return 20 * math.log10(x) if x > 0 else -math.inf


def _rms(a: np.ndarray) -> float:
    return float(np.sqrt(np.mean(a ** 2))) if a.size else 0.0


def cmd_verify(args) -> int:
    """Render the mania chart and the exported std diff the way osu! would, and null-test them."""
    cfg = load_config(args.config)
    sr = cfg.sample_rate
    _, ref_events, _ = _load_events(cfg.beatmap, cfg.sample_dir)
    named = Beatmap(cfg.beatmap)
    named.set("Metadata", "Version", cfg.version)
    std_path = cfg.output_dir / std_filename(named)
    if not std_path.exists():
        print(f"{std_path} is missing - run convert first", file=sys.stderr)
        return 1
    if cfg.duplicates == "loudest":  # compare against what the conversion is meant to play
        ref_events = [e for _, group in group_events(ref_events, cfg.group_tolerance_ms) for e in loudest_per_file(group)]
    std, std_events, warnings = _load_events(std_path, cfg.output_dir)
    _print_warnings(warnings)

    out_audio = AudioCache(cfg.output_dir, sr)
    ref = AudioCache(cfg.sample_dir, sr).render(ref_events)
    got = out_audio.render(std_events, len(ref))
    ref = np.pad(ref, ((0, len(got) - len(ref)), (0, 0)))
    diff = got - ref
    print(f"Level original: {_db(_rms(ref)):6.1f} dBFS RMS")
    print(f"Level export:   {_db(_rms(got)):6.1f} dBFS RMS")
    print(f"Difference:     {_db(_rms(diff)) - _db(_rms(ref)):6.1f} dB relative to the original (lower is better)")

    window = sr // 10
    worst = []
    chord_times = [t for t, _ in group_events(ref_events, cfg.group_tolerance_ms)]
    for time in chord_times:
        s = round(time * sr / 1000)
        worst.append((_db(_rms(diff[s:s + window])) - _db(_rms(ref[s:s + window]) or 1e-12), time))
    worst.sort(reverse=True)
    print("Largest differences (100 ms from the timestamp):")
    for error, time in worst[:5]:
        print(f"  {time:>7} ms  {error:6.1f} dB")

    if cfg.targets:  # std objects without a mania sound inherit the greenline and must hear the fill sound
        info = json.loads((cfg.output_dir / "hitsounds.json").read_text(encoding="utf-8"))
        registry = json.loads((cfg.output_dir / "samples.json").read_text(encoding="utf-8"))["files"]
        fill_id = content_id(tuple((s["file"], s["gain"]) for s in info["fill"]["content"]))
        out_dir = SampleDir(cfg.output_dir)
        gaps = [u for u in find_gap_points(cfg.targets, chord_times, cfg.group_tolerance_ms) if u >= chord_times[0]]
        wrong = []
        for u in gaps:
            tp = std.timing_point_at(u)
            name = out_dir.find_stem(sample_stem(tp.sample_set or std.default_sample_set, "hitnormal", tp.sample_index))
            if name is None or registry.get(name) != fill_id:
                wrong.append(u)
        inside = sum(u <= chord_times[-1] for u in gaps)
        print(f"Target diffs: {len(gaps)} sound points without a mania timestamp ({inside} inside the hitsounded range), "
              f"{len(gaps) - len(wrong)} of them play the fill sound"
              + (f", {len(wrong)} something else - e.g. {wrong[:8]}" if wrong else " (all)"))

    music = None
    if args.music:
        audio_file = cfg.beatmap.parent / named.get("General", "AudioFilename")
        music = load_audio(audio_file, sr)[:len(ref)]
        music = np.pad(music, ((0, len(ref) - len(music)), (0, 0))) * (args.music_volume / 100)

    def save(name: str, hitsounds: np.ndarray) -> None:
        mix = hitsounds * (args.effect_volume / 100 if music is not None else 1.0)
        if music is not None:
            mix = mix[:len(music)] + music[:len(mix)]
        write_wav(cfg.output_dir / name, mix / max(1.0, float(np.abs(mix).max())), sr)

    save("verify_mania.wav", ref)
    save("verify_std.wav", got)
    written = ["verify_mania.wav", "verify_std.wav"]
    if args.skin:
        skin_dir = Path(args.skin)
        _, skin_events, skin_warnings = _load_events(std_path, skin_dir, skin=True)
        _print_warnings(skin_warnings, "skin: ")
        save("verify_skin.wav", AudioCache(skin_dir, sr).render(skin_events, len(ref))[:len(ref)])
        written.append("verify_skin.wav")
    print(f"Listen in {cfg.output_dir}: " + ", ".join(written))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hitsoundconv", description="osu!mania hitsounds -> osu!std hitsounds")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="show the samples, volumes and combinations of a chart")
    p.add_argument("beatmap")
    p.add_argument("--sample-dir")
    p.add_argument("--tolerance", type=int, default=2)
    p.add_argument("--top", type=int, default=30)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("init-config", help="create a config with guessed roles for a chart")
    p.add_argument("beatmap")
    p.add_argument("-o", "--output", help="default: configs/<diff name>.toml next to the app")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init_config)

    p = sub.add_parser("convert", help="build the hitsound diff and its samples")
    p.add_argument("config")
    p.add_argument("--dry-run", action="store_true", help="only print the report, write nothing")
    p.add_argument("--force", action="store_true", help="export even when the index limit is exceeded")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("verify", help="render the original and the export and compare them (null test)")
    p.add_argument("config")
    p.add_argument("--skin", help="skin folder: also render how it sounds with beatmap hitsounds off")
    p.add_argument("--music", action="store_true", help="mix the song in")
    p.add_argument("--music-volume", type=int, default=55)
    p.add_argument("--effect-volume", type=int, default=75)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("mode", help="EDIT (mapset with source samples only) <-> LISTEN (export installed); no mode: status")
    p.add_argument("config")
    p.add_argument("mode", nargs="?", choices=["edit", "listen"])
    p.add_argument("--no-convert", action="store_true", help="LISTEN: install the existing export instead of converting again")
    p.add_argument("--include-unknown", action="store_true",
                   help="EDIT: also move old export files that mode did not install into the backup")
    p.set_defaults(func=cmd_mode)

    p = sub.add_parser("gui", help="open the graphical interface in the browser")
    p.add_argument("config", nargs="?", help="default: start screen to pick one")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_gui)

    args = parser.parse_args(argv)
    return args.func(args)
