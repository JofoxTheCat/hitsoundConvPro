import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace

from hitsoundconv import install
from hitsoundconv.config import dump_config


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.mapset, self.out = root / "mapset", root / "export"
        self.mapset.mkdir()
        self.out.mkdir()
        (self.mapset / "kick.wav").write_bytes(b"kick")
        (self.mapset / "map [HITME].osu").write_text("mania")
        (self.out / "soft-hitclap2.wav").write_bytes(b"clap")
        (self.out / "soft-sliderslide2.wav").write_bytes(b"")
        (self.out / "map [hs].osu").write_text("std")
        (self.out / "report.txt").write_text("not installed")
        self.cfg = SimpleNamespace(sample_dir=self.mapset, output_dir=self.out)

    def tearDown(self):
        self.tmp.cleanup()

    def names(self):
        return sorted(p.name for p in self.mapset.iterdir())

    def test_listen_then_edit_restores_the_source_files(self):
        before = self.names()
        self.assertEqual(install.listen(self.cfg)["installed"], 3)
        self.assertEqual(self.names(), sorted(before + ["soft-hitclap2.wav", "soft-sliderslide2.wav", "map [hs].osu"]))
        self.assertEqual(install.status(self.cfg)["mode"], "listen")
        install.edit(self.cfg)
        self.assertEqual(self.names(), before)
        self.assertEqual(install.status(self.cfg)["mode"], "edit")

    def test_foreign_file_is_backed_up_instead_of_overwritten(self):
        (self.mapset / "soft-hitclap2.wav").write_bytes(b"handmade")
        r = install.listen(self.cfg)
        self.assertEqual(r["backed_up"], ["soft-hitclap2.wav"])
        self.assertEqual((Path(r["backup_dir"]) / "soft-hitclap2.wav").read_bytes(), b"handmade")
        self.assertEqual((self.mapset / "soft-hitclap2.wav").read_bytes(), b"clap")

    def test_installed_file_changed_since_is_kept_on_edit(self):
        install.listen(self.cfg)
        (self.mapset / "map [hs].osu").write_text("saved in the osu! editor")
        r = install.edit(self.cfg)
        self.assertEqual(r["backed_up"], ["map [hs].osu"])
        self.assertNotIn("map [hs].osu", self.names())

    def test_files_dropped_from_the_export_are_removed_on_the_next_listen(self):
        install.listen(self.cfg)
        (self.out / "soft-hitclap2.wav").unlink()
        self.assertEqual(install.listen(self.cfg)["removed"], 1)
        self.assertNotIn("soft-hitclap2.wav", self.names())

    def test_edit_leaves_unknown_generated_looking_files_alone_unless_asked(self):
        (self.mapset / "drum-hitclap9.wav").write_bytes(b"old export")
        self.assertEqual(install.edit(self.cfg)["unknown"], ["drum-hitclap9.wav"])
        self.assertIn("drum-hitclap9.wav", self.names())
        r = install.edit(self.cfg, include_unknown=True)
        self.assertEqual(r["backed_up"], ["drum-hitclap9.wav"])
        self.assertNotIn("drum-hitclap9.wav", self.names())


class ConfigDumpTest(unittest.TestCase):
    def test_written_config_reads_back_identically(self):
        data = {
            "input": {"beatmap": "C:\\Songs\\map [HITME].osu", "targets": ["a.osu", "b.osu"]},
            "output": {"dir": "export/x", "mute_slider_slide": True},
            "mix": {"gain_step_db": 0.1, "fallback_slot": "soft-hitwhistle"},
            "fill": {"sample": "auto", "gain_db": 0.0},
            "route": [
                {"match": "kick.wav", "slot": "normal-hitnormal", "priority": 100, "lock": True, "anchor": True},
                {"match": "tick.wav", "slot": "soft-hitnormal", "priority": 40, "overflow": "soft-hitwhistle"},
            ],
        }
        text = dump_config(data, {"kick.wav": "24x"})
        self.assertEqual(tomllib.loads(text), data)
        self.assertIn('match = "kick.wav"   # 24x', text)


if __name__ == "__main__":
    unittest.main()
