"""Local web GUI: pick a project, drag samples onto hitsound slots, convert, switch EDIT/LISTEN, preview.

Runs on the standard library only (http.server) and binds to 127.0.0.1. Every message the GUI shows
travels as a translatable (key, params) pair and is rendered in the language the page asks for.
"""
from __future__ import annotations

import json
import threading
import tomllib
import webbrowser
from collections import Counter, defaultdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import install
from ..config import Config, load_config, save_config
from ..convert import ConversionResult, convert, slot_filename
from ..export import content_id, describe, export
from ..i18n import msg, render
from ..osufile import Beatmap
from ..paths import app_dir, configs_dir
from ..project import create_config, find_configs
from ..routing import BANKS, SOUNDS, Router, parse_slot
from ..samples import SampleDir, resolve_events

STATIC = Path(__file__).with_name("static")
_SOUND_ORDER = {s: i for i, s in enumerate(SOUNDS)}


def summarize(result: ConversionResult, cfg: Config, notes: list[tuple]) -> dict:
    """Numbers and messages of one conversion; messages stay translatable."""
    files = result.files
    registry = json.loads((cfg.output_dir / "samples.json").read_text(encoding="utf-8"))
    usage = Counter(c.placement.index for c in result.chords)
    messages = [m for m, _ in result.warnings.items()]
    messages += [msg("no_route", name=name, slot=cfg.fallback.slot) for name in sorted(result.unmatched)]
    messages += notes
    return {
        "indices": len(result.indices),
        "index_limit": cfg.last_index - cfg.first_index + 1,
        "over_limit": bool(result.last_index and result.last_index > cfg.last_index),
        "wavs": len(files),
        "distinct": len({content_id(c) for c in files.values()}),
        "slides": len(registry["slider_slides"]),
        "combinations": result.combinations,
        "moved": sum(c.chosen.spread for c in result.chords),
        "limited": sum(c.limited for c in result.chords),
        "off_role": sum(c.off_role for c in result.chords),
        "fill": f"{describe(result.fill)} ({result.fill_bank}-hitnormal)",
        "messages": messages,
        "index_table": [
            {
                "index": idx.number,
                "objects": usage[idx.number],
                "slots": [
                    {"file": slot_filename(b, s, idx.number), "content": describe(c),
                     "fill": (b, s) == (result.fill_bank, "hitnormal")}
                    for (b, s), c in sorted(idx.slots.items(), key=lambda kv: (_SOUND_ORDER[kv[0][1]], kv[0][0]))
                ],
            }
            for idx in result.indices
        ],
    }


class Project:
    """One config file; every write goes through here. Methods return translatable messages."""

    SETTINGS = {"mix": {"bank_mode", "volume_mode", "on_clip", "duplicates", "silent_bank"},
                "fill": {"sample", "bank", "gain_db"}}

    def __init__(self, config_path: str | Path):
        self.path = Path(config_path).expanduser().resolve()
        self.summary: dict | None = None

    def _raw(self) -> dict:
        return tomllib.loads(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def _usage(cfg: Config) -> dict[str, dict]:
        events, _ = resolve_events(Beatmap(cfg.beatmap), SampleDir(cfg.sample_dir))
        usage = defaultdict(lambda: {"count": 0, "volumes": set()})
        for e in events:
            usage[e.file]["count"] += 1
            usage[e.file]["volumes"].add(e.volume)
        return usage

    def state(self, lang: str) -> dict:
        cfg = load_config(self.path)
        router = Router(cfg.routes, cfg.fallback)
        samples = []
        for name, use in sorted(self._usage(cfg).items(), key=lambda kv: -kv[1]["count"]):
            r = router.route(name)
            samples.append({
                "file": name,
                "count": use["count"],
                "volumes": sorted(use["volumes"]),
                "route": {"slot": r.slot, "priority": r.priority, "lock": r.lock, "anchor": r.anchor,
                          "overflow": "-".join(r.overflow) if r.overflow else "", "gain_db": r.gain_db,
                          "fallback": r is cfg.fallback},
            })
        bm = Beatmap(cfg.beatmap)
        meta = lambda key: bm.get("Metadata", key)
        summary = None
        if self.summary is not None:
            summary = {**self.summary, "messages": [render(m, lang) for m in self.summary["messages"]]}
        return {
            "config": str(self.path),
            "title": f"{meta('Artist')} – {meta('Title')} [{meta('Version')}]",
            "banks": list(BANKS),
            "sounds": list(SOUNDS),
            "fallback": cfg.fallback.slot,
            "samples": samples,
            "settings": {
                "mix": {"bank_mode": cfg.bank_mode, "volume_mode": cfg.volume_mode, "on_clip": cfg.on_clip,
                        "duplicates": cfg.duplicates, "silent_bank": cfg.silent_bank},
                "fill": {"sample": cfg.fill_sample, "bank": cfg.fill_bank, "gain_db": cfg.fill_gain_db},
            },
            "mode": install.status(cfg),
            "summary": summary,
        }

    def _save(self, raw: dict) -> None:
        notes = {name: f"{use['count']}x" for name, use in self._usage(load_config(self.path)).items()}
        save_config(self.path, raw, notes)

    def save_routes(self, samples: list[dict]) -> list[tuple]:
        """Every routed sample gets its own explicit route; samples in the pool use the fallback slot."""
        routes = []
        for s in samples:
            r = s["route"]
            if r.get("fallback"):
                continue
            parse_slot(r["slot"])
            route = {"match": s["file"], "slot": r["slot"], "priority": int(r.get("priority") or 0)}
            if r.get("lock"):
                route["lock"] = True
            if r.get("anchor"):
                route["anchor"] = True
            if r.get("overflow"):
                parse_slot(r["overflow"])
                route["overflow"] = r["overflow"]
            if float(r.get("gain_db") or 0):
                route["gain_db"] = float(r["gain_db"])
            routes.append(route)
        raw = self._raw()
        raw["route"] = routes
        self._save(raw)
        return [msg("routes_saved")]

    def save_settings(self, changes: dict) -> list[tuple]:
        raw = self._raw()
        for section, values in changes.items():
            for key, value in values.items():
                if key not in self.SETTINGS.get(section, ()):
                    raise ValueError(f"Unknown setting {section}.{key}")
                raw.setdefault(section, {})[key] = float(value) if key == "gain_db" else value
        self._save(raw)
        return [msg("settings_saved")]

    def convert(self) -> list[tuple]:
        cfg = load_config(self.path)
        result = convert(cfg)
        _, notes = export(result, cfg)
        self.summary = s = summarize(result, cfg, notes)
        messages = [msg("converted", indices=s["indices"], wavs=s["wavs"], slides=s["slides"])]
        if s["over_limit"]:
            messages.append(msg("over_limit"))
        return messages

    def set_mode(self, mode: str) -> list[tuple]:
        if mode == "listen":
            messages = self.convert()
            r = install.listen(load_config(self.path))
            messages.append(msg("listen", installed=r["installed"], copied=r["copied"], removed=r["removed"]))
            if r["adopted"]:
                messages.append(msg("adopted", adopted=r["adopted"]))
        elif mode == "edit":
            r = install.edit(load_config(self.path))
            messages = [msg("edit", removed=r["removed"])]
            if r["unknown"]:
                messages.append(msg("edit_unknown", unknown=len(r["unknown"])))
        else:
            raise ValueError(f"Unknown mode {mode!r}")
        if r["backed_up"]:
            messages.append(msg("backed_up", count=len(r["backed_up"]), folder=r["backup_dir"]))
        return messages + [msg("reload_hint")]


class App:
    """The GUI session: which project is open, and the start screen when none is."""

    def __init__(self, config_path: str | Path | None = None):
        self.lock = threading.RLock()
        self.project: Project | None = None
        if config_path:
            self.open(config_path)

    def open(self, path: str | Path) -> list[tuple]:
        project = Project(path)
        project.state("en")  # fails here if the config or the beatmap is broken
        self.project = project
        return [msg("opened", name=project.path.name)]

    def create(self, beatmap: str | Path) -> list[tuple]:
        path = create_config(beatmap)
        self.open(path)
        return [msg("created", name=path.name, beatmap=Path(beatmap).name)]

    def current(self) -> Project:
        if self.project is None:
            raise ValueError(render(msg("no_project"), "en"))
        return self.project

    def state(self, lang: str) -> dict:
        with self.lock:
            return {
                "project": self.project.state(lang) if self.project else None,
                "projects": [{"path": str(p), "name": p.name} for p in find_configs()],
                "configs_dir": str(configs_dir()),
                "app_dir": str(app_dir()),
            }


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                      ".css": "text/css; charset=utf-8", ".wav": "audio/wav", ".ogg": "audio/ogg", ".mp3": "audio/mpeg"}

    def __init__(self, *args, app: App, **kwargs):
        self.app = app
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, format, *args):  # keep the console quiet
        pass

    @staticmethod
    def _lang(query: str) -> str:
        wanted = parse_qs(query).get("lang", ["en"])[0]
        return wanted if wanted in ("en", "de") else "en"

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/api/state":
                return self._json(self.app.state(self._lang(url.query)))
            for prefix, folder in (("/audio/source/", "sample_dir"), ("/audio/export/", "output_dir")):
                if url.path.startswith(prefix):
                    cfg = load_config(self.app.current().path)
                    return self._audio(getattr(cfg, folder), unquote(url.path[len(prefix):]))
        except Exception as e:
            return self._json({"error": str(e)}, 500)
        if url.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        lang = self._lang(url.query)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            with self.app.lock:
                if url.path == "/api/open":
                    messages = self.app.open(body["path"])
                elif url.path == "/api/create":
                    messages = self.app.create(body["beatmap"])
                elif url.path == "/api/routes":
                    messages = self.app.current().save_routes(body["samples"])
                elif url.path == "/api/settings":
                    messages = self.app.current().save_settings(body)
                elif url.path == "/api/convert":
                    messages = self.app.current().convert()
                elif url.path == "/api/mode":
                    messages = self.app.current().set_mode(body.get("mode"))
                else:
                    return self._json({"error": f"Unknown call {url.path}"}, 404)
            self._json({"message": " ".join(render(m, lang) for m in messages), "state": self.app.state(lang)})
        except Exception as e:
            self._json({"error": str(e)}, 400)

    def _json(self, data: dict, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _audio(self, directory: Path, name: str) -> None:
        real = SampleDir(directory).find(name) if "/" not in name and "\\" not in name else None
        if real is None:
            return self._json({"error": f"{name} not found"}, 404)
        data = (Path(directory) / real).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", self.extensions_map.get(Path(real).suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def _serve(app: App, port: int) -> ThreadingHTTPServer:
    """Bind to the wanted port, or the next free one if something else already listens there."""
    for candidate in range(port, port + 20):
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), partial(Handler, app=app))
        except OSError as e:
            print(f"Port {candidate} is busy ({e.strerror or e}), trying {candidate + 1} ...")
    raise SystemExit(f"No free port between {port} and {port + 19}")


def run(config_path: str | Path | None = None, port: int = 8765, open_browser: bool = True) -> None:
    configs_dir().mkdir(parents=True, exist_ok=True)
    app = App(config_path)
    server = _serve(app, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"GUI: {url}\nLeave this window open while you work; Ctrl+C stops the GUI.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
