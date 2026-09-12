"""Messages that reach the user in more than one place (report, CLI, GUI) – in English and German.

Warnings and notes travel as (key, params) so every surface can render them in its own language.
"""
from __future__ import annotations

TEXTS = {
    "missing_file": {
        "en": "Missing file: {name}",
        "de": "Datei fehlt: {name}",
    },
    "skin_default": {
        "en": "Skin default sample (index 0), cannot be mixed: {name}",
        "de": "Skin-Standardsample (Index 0), nicht mischbar: {name}",
    },
    "missing_sample": {
        "en": "Sample missing, osu! falls back to the skin default: {name}",
        "de": "Sample fehlt, osu! nimmt dann den Skin-Standard: {name}",
    },
    "fill_missing": {
        "en": "Fill sample {name} not found – objects without a mania sound stay silent",
        "de": "Fill-Sample {name} nicht gefunden – Objekte ohne Mania-Sound bleiben stumm",
    },
    "mute_missing": {
        "en": "{name} not found – silent sliderslides were generated instead",
        "de": "{name} nicht gefunden – stumme sliderslides wurden selbst erzeugt",
    },
    "mapset_old": {
        "en": "The mapset holds {total} files from an earlier export: {replaced} will be replaced when copying, "
              "{stale} are no longer part of it and should be deleted first.",
        "de": "Im Mapset liegen {total} Dateien aus einem früheren Export: {replaced} werden beim Kopieren ersetzt, "
              "{stale} gehören nicht mehr dazu und sollten vorher gelöscht werden.",
    },
    "mapset_stale": {
        "en": "No longer needed: {names}",
        "de": "Nicht mehr benötigt: {names}",
    },
    "no_route": {
        "en": "No role for {name} – it uses the fallback slot {slot}",
        "de": "Keine Route für {name} – liegt auf dem Fallback-Slot {slot}",
    },
    "opened": {
        "en": "{name} opened",
        "de": "{name} geöffnet",
    },
    "created": {
        "en": "{name} created from {beatmap} – please check the roles",
        "de": "{name} aus {beatmap} angelegt – Routen bitte prüfen",
    },
    "routes_saved": {
        "en": "Roles saved",
        "de": "Routen gespeichert",
    },
    "settings_saved": {
        "en": "Settings saved",
        "de": "Einstellungen gespeichert",
    },
    "converted": {
        "en": "{indices} indices, {wavs} WAVs + {slides} sliderslides.",
        "de": "{indices} Indizes, {wavs} WAVs + {slides} sliderslides.",
    },
    "over_limit": {
        "en": "Index limit exceeded!",
        "de": "Index-Limit überschritten!",
    },
    "listen": {
        "en": "LISTEN: {installed} files in the mapset ({copied} copied, {removed} outdated removed).",
        "de": "LISTEN: {installed} Dateien im Mapset ({copied} kopiert, {removed} veraltete entfernt).",
    },
    "adopted": {
        "en": "{adopted} were already there byte-identical and now count as installed.",
        "de": "{adopted} lagen schon identisch dort und zählen jetzt als installiert.",
    },
    "edit": {
        "en": "EDIT: {removed} installed files removed – the mapset holds only the source samples.",
        "de": "EDIT: {removed} installierte Dateien entfernt – im Mapset liegen nur noch die Quell-Samples.",
    },
    "edit_unknown": {
        "en": "{unknown} files look like an old export copied by hand and were left alone.",
        "de": "{unknown} Dateien sehen nach einem alten, von Hand kopierten Export aus und blieben liegen.",
    },
    "backed_up": {
        "en": "{count} foreign or changed files were moved to {folder}.",
        "de": "{count} fremde oder geänderte Dateien wurden nach {folder} verschoben.",
    },
    "reload_hint": {
        "en": "In osu!: press F5 in song select.",
        "de": "In osu!: Songauswahl mit F5 neu laden.",
    },
    "no_project": {
        "en": "No project open",
        "de": "Kein Projekt geöffnet",
    },
}


def msg(key: str, **params) -> tuple[str, tuple]:
    """A message that can still be rendered in any language (and used as a dict key)."""
    return key, tuple(sorted(params.items()))


def render(message: tuple[str, tuple], lang: str = "en") -> str:
    key, params = message
    texts = TEXTS.get(key)
    if texts is None:
        return key
    return texts.get(lang, texts["en"]).format(**dict(params))
