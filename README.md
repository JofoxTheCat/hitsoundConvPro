# hitsoundConvPro

Turns osu!mania hitsounds/keysounds (any number of samples per timestamp, every note with its own file and volume) into an **osu!std hitsound difficulty**.

osu!std allows only **one** custom index per object. From that index it plays:

- `<normalSet>-hitnormal<i>`: always
- `<additionSet>-hitwhistle / hitfinish / hitclap<i>`: any combination, all from the **same** bank

The tool spreads the mania samples over these slots following a **role config** (e.g. kick → `normal-hitnormal`, snare → `soft-hitclap`). Samples that share a slot are mixed into one file with their relative volumes baked in. Timestamps whose slot contents do not contradict each other share an index, and each timestamp goes where it needs the fewest new files.

## Download

Grab a release zip, **unpack it**, then double-click `Start GUI.bat` (keeps the window open and shows errors)
or `hitsoundConvPro.exe`. Running the .exe from inside the zip closes immediately: Windows does not extract
the `_internal` folder next to it. If a window still disappears, `crash.log` next to the .exe holds the reason.

- `hitsoundConvPro-<version>-win64.zip` needs ffmpeg on PATH
- `hitsoundConvPro-<version>-win64-with-ffmpeg.zip` brings its own ffmpeg

## Requirements

- Python ≥ 3.11 with `numpy`, and `ffmpeg` on PATH — or the packaged release, which needs neither.

## Quick start

```bash
python -m hitsoundconv gui                      # start screen: pick or create a project
python -m hitsoundconv gui configs/mymap.toml   # straight into a project
```

The GUI runs locally in the browser (127.0.0.1 only). It is English by default and has an EN/DE switch.

- **Slots**: drag samples onto the 12 slots (3 banks × 4 sounds). The fill slot and the bank used for silence are marked. Samples on the left have no role and use the fallback slot.
- **Details**: click a sample for priority, anchor, lock, overflow slot and gain. ▶ plays it.
- **Settings**: bank/volume mode, clipping behaviour, duplicate handling, silence and fill bank, fill sound.
- **Convert** and the **EDIT/LISTEN** switch sit in the header. The result shows indices, files and warnings, and every generated file can be played back.

Every change is written to the config right away. The GUI writes one explicit role per sample, so glob roles such as `kick*.wav` are expanded; the comments in the config are kept.

## Command line

```bash
python -m hitsoundconv analyze "…\Songs\<mapset>\<map> [HITME].osu"   # samples, volumes, combinations
python -m hitsoundconv init-config "…\<map> [HITME].osu"              # config with guessed roles
python -m hitsoundconv convert configs/mymap.toml --dry-run           # report only
python -m hitsoundconv convert configs/mymap.toml                     # write the export
python -m hitsoundconv verify configs/mymap.toml --skin "…\osu!\Skins\<skin>" --music
python -m hitsoundconv mode configs/mymap.toml listen | edit          # see below
```

The export folder then holds:

- an `.osu` (osu!std, one circle per timestamp, greenlines for index and volume)
- the mixed samples (`soft-hitclap7.wav` …) and silent `…-sliderslide<i>.wav`
- `report.txt` (what every file contains, notes about old files in the mapset)
- `samples.json`: sample registry, every file with a content id; same id = same sound
- `hitsounds.json`: every object, machine readable
- after `verify`: `verify_mania.wav`, `verify_std.wav`, `verify_skin.wav` for A/B listening

The hitsounds travel from the hitsound diff onto the std diffs, e.g. with the Hitsound Copier from [Mapping Tools](https://mappingtools.github.io/). Index and bank of a timestamp can shift with every conversion, so diffs you already copied onto need to be copied again afterwards.

## EDIT ⇄ LISTEN

200 generated files in the mapset get in the way while hitsounding, so there are two modes:

- **LISTEN** converts, then copies the generated samples, the sliderslides and the hitsound diff into the mapset, recording every file with a checksum in `<export>/installed.json`. Files already there byte-identical count as installed from then on. The next LISTEN removes files the new export no longer has.
- **EDIT** removes exactly those files. The mapset keeps your source samples and your own diffs.
- **Only files the tool copied in unchanged are ever deleted.** Foreign files in the way, and installed files you changed since (e.g. the hitsound diff saved in the editor), are moved to `<export>/_mapset_backup/<time>/`.
- Files that look like an old export copied by hand are only touched with `--include-unknown`, and then only into the backup.
- Reload with F5 in osu!'s song select afterwards.

## Objects without a mania sound (fill)

std diffs often have objects where the mania chart plays nothing: slider heads between two mania notes, slider ends, extra circles. Such objects inherit the greenline of the previous timestamp, and without care they would replay its kick or snare.

That is why **every greenline points at the fill bank** (`fill.bank`), whose `hitnormal<i>` holds the same fill sound in every index — by default the most frequent hitnormal sample. The mania timestamps themselves play through their own per-object sample sets. Objects without a counterpart therefore play the fill sound at the volume of the previous timestamp, with no extra greenlines.

Because the sliderslide follows the greenline, silent sliderslides are only needed in the fill bank, at most one per index.

## Config

```toml
[input]
beatmap = "C:/…/map [HITME].osu"
targets = ["C:/…/map [TAKEME].osu"]  # optional: silent sliderslides and the check in verify

[output]
dir = "export/HITME"           # never the Songs folder itself
version = "HITME std hitsounds"
first_index = 2                # index 1 = the unnumbered files, never touched
last_index = 100
format = "auto"                # per file: ogg when it is smaller and close enough, else wav
ogg_quality = "auto"           # smallest quality per file that meets the target below, or 0-10
ogg_target_db = -28.0          # how close an encoded file has to stay to the uncompressed mix
mute_slider_slide = true
slider_slide_file = "sliderslidermute.wav"

[mix]
group_tolerance_ms = 2
gain_step_db = 0.1
merge_tolerance_db = 0.5       # mixes whose gains differ by less than this share one file
pack_attempts = 200            # packing orders to try; never changes the sound
bank_mode = "prefer"           # prefer | strict
volume_mode = "relative"       # relative | absolute | auto
on_clip = "roles"              # roles | spread | limit
duplicates = "loudest"         # loudest | sum
silent_bank = "normal"         # must differ from fill.bank
fallback_slot = "soft-hitwhistle"

[fill]
sample = "auto"                # auto | file name | "none" (silent)
bank = "soft"
gain_db = 0.0

[[route]]
match = "kick*.wav"            # glob, first match wins
slot = "normal-hitnormal"
priority = 100                 # decides the bank when several samples compete for hitnormal or the additions
lock = true                    # never move to another bank, never move away
anchor = true                  # kick focus: everything else on that timestamp is mixed into this slot

[[route]]
match = "tick.wav"
slot = "soft-hitnormal"
priority = 40
overflow = "soft-hitwhistle"   # where it goes if the mix in its own slot would clip
# gain_db = -2                 # make the sample quieter/louder overall
```

| Option | Value | Effect |
|---|---|---|
| `bank_mode` | `prefer` | Role bank, unless another bank in the same index saves a new index. The role (hitnormal/whistle/finish/clap) stays, only the bank changes. |
| | `strict` | Always the role bank. Needs considerably more indices. |
| `volume_mode` | `relative` | The loudest sample sets the greenline volume. Sounds right with skin hitsounds too. |
| | `absolute` | Greenline 100, every file carries its own volume. |
| | `auto` | Per timestamp whichever fits an existing index. |
| `on_clip` | `roles` | If a mix would clip, the least important sample moves away: one pulled into the kick goes back to its role, otherwise into its `overflow` slot. |
| | `spread` | Also splits other mixes onto free additions. Sounds the same, but with skin hitsounds you hear additions that do not fit. |
| | `limit` | Only mix quieter. |
| `duplicates` | `loudest` | The same sample several times on one timestamp plays once, at its loudest volume. |
| | `sum` | All of them play, like in osu!mania. |
| | `grid` | Offers the packer several ways to write the same loudness. Saves files, but raises the greenline volume of many timestamps - with beatmap hitsounds off those hits get louder, which is why it is not the default. |
| `silent_bank` | `normal` | Bank for silent hitnormals. With beatmap hitsounds off you hear that bank's skin hitnormal. |
| `merge_tolerance_db` | `0.5` | Mixes whose gains differ by less than this share one file. Flags and banks stay untouched, so skin players hear no difference. |
| `pack_attempts` | `200` | How many orderings the packer tries. Only the file count changes, never the sound. |
| `format` | `auto` | Per file: Vorbis `.ogg` when it is smaller and close enough, otherwise `.wav`. `ogg` and `wav` force one format. |

## Size of the export

Beatmap uploads have a size limit, so every generated sample is written in whichever format is smaller
while staying close to the uncompressed mix. osu! finds a sample by bank, sound and index, so the two
formats can sit side by side. Measured on a 4-minute map with 896 timestamps (278 generated files):

| Setting | Size | Difference to the uncompressed mix |
|---|---|---|
| `format = "wav"` | 22.2 MB | - |
| `format = "auto"` (default) | 7.6 MB | -30 dB overall |
| `ogg_quality = 6` for everything | 3.6 MB | -17 dB, audible on quiet mixes |

Vorbis spends its bits by absolute loudness, so the quiet mixes of a layered hitsound set suffer first.
Therefore each file gets the smallest quality that still meets `ogg_target_db`, and files that would not
make it - or that would come out larger than their raw data, like the silent ones - stay `.wav`. In the
measurement above that is 241 ogg files and 47 wav files.

Three more things keep the file count down, none of which changes how the map sounds: the packer tries
many orderings and keeps the smallest result, the fill sound is only reserved in indices that actually
sit before an object without a mania sound, and mixes closer than `merge_tolerance_db` share one file.

## With beatmap hitsounds off

Many players (`IgnoreBeatmapSamples`) only hear their skin samples: the bank's hitnormal plus the addition flags, at greenline volume. The conversion is built for that:

- Timestamps with a kick play `normal-hitnormal`, i.e. a normal hit.
- Additions only come from roles and overflow slots (clap = snare/clap …), never at random. `spread` cannot guarantee this.
- Silence lives in one fixed bank (`silent_bank`).

`verify --skin <skin folder> --music` renders exactly that for listening.

## How it works

1. **Resolve** (`samples.py`): every mania note is translated into the files osu! really plays — a filename, or sample set/index/additions following the inheritance rules of the timing points.
2. **Group and route** (`convert.py`): all samples of a timestamp are spread over the 4 channels by the role config. Duplicates count once. Anchor samples (kick) pull everything else into their slot.
3. **Mix** (`audio.py`): samples of a channel are summed with their volumes baked in. If that would clip, samples move to their role or overflow slot first; only then is the timestamp mixed quieter.
4. **Pack** (`convert.py`): every timestamp goes into the index that needs the fewest new files. In every index the fill bank's hitnormal is reserved for the fill sound.
5. **Export** (`export.py`): std `.osu` with greenlines (original timing, SV and kiai are kept), WAVs (16 bit/44.1 kHz), silent sliderslides, registry, report.

## Tests

```bash
python -m unittest discover tests
```

## Building the release

```bash
python build.py                # both variants
python build.py --plain        # small one, needs ffmpeg on PATH
python build.py --with-ffmpeg  # self-contained
```

Produces `dist/hitsoundConvPro-<version>-win64[-with-ffmpeg]/` (a folder with `hitsoundConvPro.exe` plus its files) and the matching `.zip` for a GitHub release. Double-clicking the exe opens the GUI; with arguments it behaves like the CLI.

## Limits / open points

- osu! looks for its own file name per index, so the same sound in different indices needs one copy each. `samples.json` shows which files are identical.
- If an object without a mania sound carries addition flags itself, it plays the additions of the index it inherits.
- The null test in `verify` checks the conversion against the tool's own model. Volume is assumed to be linear.
- Samples with index 0 (skin default) cannot be mixed and are reported.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE). A modified version has to stay free software and carry its
source along.
