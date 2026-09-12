import unittest

from hitsoundconv.convert import build_chord, pack
from hitsoundconv.export import merge_timing
from hitsoundconv.osufile import HitObject, TimingPoint
from hitsoundconv.routing import Route, Router
from hitsoundconv.samples import SampleEvent


class FakeAudio:
    """Every file peaks at 1.0 at the same instant, so a mix peaks at the sum of its gains."""

    def peak(self, content):
        return sum(g for _, g in content)


def make_router(*routes):
    return Router(
        [Route(pattern, *slot.split("-"), priority, order=i, lock=lock) for i, (pattern, slot, priority, lock) in enumerate(routes)],
        Route("*", "soft", "hitwhistle", -1),
    )


def chord(router, *events, volume_mode="relative", on_clip="spread", duplicates="loudest", time=0):
    return build_chord(time, [SampleEvent(time, f, v) for f, v in events], router, FakeAudio(), 0,
                       volume_mode, on_clip, duplicates)


ROUTER = make_router(
    ("kick*.wav", "normal-hitnormal", 100, False),
    ("snare.wav", "soft-hitclap", 80, False),
    ("tick*.wav", "soft-hitwhistle", 40, False),
)


class ParseTest(unittest.TestCase):
    def test_mania_note_with_filename(self):
        obj = HitObject.parse("14,192,0,5,2,0:0:0:70:soft-hitwhistle.wav")
        self.assertEqual((obj.time, obj.sample.volume, obj.sample.filename), (0, 70, "soft-hitwhistle.wav"))

    def test_mania_hold_note(self):
        obj = HitObject.parse("448,192,1000,128,0,1500:0:0:0:60:kick.wav")
        self.assertEqual((obj.end_time, obj.sample.volume, obj.sample.filename), (1500, 60, "kick.wav"))


class ChordTest(unittest.TestCase):
    def test_relative_volume_is_baked_in(self):
        opt = chord(ROUTER, ("kick.wav", 70), ("snare.wav", 35)).options[0]
        self.assertEqual(opt.volume, 70)
        self.assertEqual(opt.req.normal, (("kick.wav", 1.0),))
        self.assertEqual(opt.req.additions, (("hitclap", (("snare.wav", 0.5),)),))
        self.assertEqual((opt.req.normal_bank, opt.req.addition_bank), ("normal", "soft"))

    def test_no_hitnormal_sample_means_silent_hitnormal(self):
        opt = chord(ROUTER, ("snare.wav", 50)).options[0]
        self.assertEqual((opt.req.normal_bank, opt.req.normal), (None, ()))

    def test_duplicate_sample_plays_once_at_its_loudest(self):
        opt = chord(ROUTER, ("tick.wav", 70), ("tick.wav", 50), ("tick.wav", 20)).options[0]
        self.assertEqual(opt.volume, 70)
        self.assertFalse(opt.limited)
        self.assertEqual(opt.req.additions, (("hitwhistle", (("tick.wav", 1.0),)),))

    def test_clipping_mix_is_spread_onto_free_addition(self):
        opt = chord(ROUTER, ("tick.wav", 70), ("tick.wav", 50), duplicates="sum").options[0]
        self.assertTrue(opt.spread)
        self.assertFalse(opt.limited)
        self.assertEqual(opt.volume, 70)  # once split nothing clips, so the object volume needn't be raised
        # clap before finish: with beatmap hitsounds off a stray skin finish (crash) is the most jarring
        self.assertEqual(opt.req.additions, (("hitwhistle", (("tick.wav", 1.0),)), ("hitclap", (("tick.wav", 0.7143),))))

    def test_clipping_mix_is_limited_when_spread_is_off(self):
        opt = chord(ROUTER, ("tick.wav", 70), ("tick.wav", 50), on_clip="limit", duplicates="sum").options[0]
        self.assertTrue(opt.limited)
        self.assertEqual(opt.req.additions, (("hitwhistle", (("tick.wav", 1.0),)),))


class PackTest(unittest.TestCase):
    def test_compatible_chords_share_an_index(self):
        chords = [chord(ROUTER, ("kick.wav", 70), time=0), chord(ROUTER, ("kick.wav", 70), ("snare.wav", 35), time=100)]
        self.assertEqual(len(pack(chords, 2, flexible_banks=False)), 1)

    def test_other_bank_saves_an_index_unless_locked(self):
        def kicks(router):
            return [chord(router, ("kick.wav", 70), volume_mode="absolute", time=0),
                    chord(router, ("kick.wav", 35), volume_mode="absolute", time=100)]

        self.assertEqual(len(pack(kicks(ROUTER), 2, flexible_banks=False)), 2)
        flexible = kicks(ROUTER)
        self.assertEqual(len(pack(flexible, 2, flexible_banks=True)), 1)
        self.assertEqual({c.placement.normal_bank for c in flexible}, {"normal", "soft"})
        locked = make_router(("kick*.wav", "normal-hitnormal", 100, True))
        self.assertEqual(len(pack(kicks(locked), 2, flexible_banks=True)), 2)


class KickFocusTest(unittest.TestCase):
    def test_anchor_pulls_everything_into_its_slot(self):
        router = make_router(("snare.wav", "soft-hitclap", 80, False), ("tick.wav", "soft-hitwhistle", 40, False))
        router.routes.insert(0, Route("kick*.wav", "normal", "hitnormal", 100, lock=True, anchor=True))
        opt = chord(router, ("kick.wav", 30), ("snare.wav", 15), ("tick.wav", 15)).options[0]
        self.assertEqual(opt.req.additions, ())
        self.assertEqual(opt.req.normal_bank, "normal")
        self.assertEqual(opt.volume, 60)  # raised so the one mixed file doesn't clip
        self.assertEqual(opt.req.normal, (("kick.wav", 0.5), ("snare.wav", 0.25), ("tick.wav", 0.25)))

    def test_clipping_anchor_mix_hands_samples_back_to_their_roles(self):
        router = make_router(("snare.wav", "soft-hitclap", 80, False), ("tick.wav", "soft-hitwhistle", 40, False))
        router.routes.insert(0, Route("kick*.wav", "normal", "hitnormal", 100, lock=True, anchor=True))
        opt = chord(router, ("kick.wav", 60), ("snare.wav", 30), ("tick.wav", 30)).options[0]  # 0.6+0.3+0.3 > 1
        self.assertFalse(opt.limited)
        self.assertEqual(opt.req.normal, (("kick.wav", 0.6), ("snare.wav", 0.3)))  # least important (tick) went back
        self.assertEqual(opt.req.additions, (("hitwhistle", (("tick.wav", 0.3),)),))

    def test_sample_already_in_its_role_moves_to_its_overflow_slot(self):
        router = Router([Route("kick*.wav", "normal", "hitnormal", 100, lock=True, anchor=True),
                         Route("tick.wav", "soft", "hitnormal", 40, order=1, overflow=("soft", "hitwhistle"))],
                        Route("*", "soft", "hitwhistle", -1))
        opt = chord(router, ("kick.wav", 70), ("tick.wav", 85)).options[0]  # kick+tick in one hitnormal would clip
        self.assertFalse(opt.limited)
        self.assertEqual(opt.volume, 85)  # no raise needed once the tick moved out
        self.assertEqual(opt.req.normal, (("kick.wav", 0.8235),))
        self.assertEqual(opt.req.additions, (("hitwhistle", (("tick.wav", 1.0),)),))

    def test_without_anchor_the_roles_apply(self):
        opt = chord(ROUTER, ("snare.wav", 35), ("tick.wav", 35)).options[0]
        self.assertEqual([s for s, _ in opt.req.additions], ["hitwhistle", "hitclap"])


class FillTest(unittest.TestCase):
    def test_silent_hitnormal_stays_in_the_silent_bank(self):
        chords = [chord(ROUTER, ("snare.wav", 50), time=0)]
        pack(chords, 2, flexible_banks=True, silent_bank="soft")
        self.assertEqual(chords[0].placement.normal_bank, "soft")

    def test_fill_bank_holds_the_fill_sound_in_every_index(self):
        router = make_router(("tick.wav", "soft-hitnormal", 40, False), ("snare.wav", "soft-hitclap", 80, False))
        fill = (("tick.wav", 1.0),)
        chords = [chord(router, ("tick.wav", 70), time=0),
                  chord(router, ("tick.wav", 20), ("snare.wav", 70), time=100),
                  chord(router, ("snare.wav", 50), time=200)]
        indices = pack(chords, 2, flexible_banks=True, silent_bank="normal", fill=("soft", fill))
        self.assertTrue(all(idx.slots[("soft", "hitnormal")] == fill for idx in indices))
        self.assertEqual(chords[0].placement.normal_bank, "soft")     # plays exactly the fill sound
        self.assertNotEqual(chords[1].placement.normal_bank, "soft")  # the quieter tick needs its own file
        self.assertNotEqual(chords[2].placement.normal_bank, "soft")  # silence never goes into the fill bank


class TimingTest(unittest.TestCase):
    def test_greenlines_only_where_the_sample_state_changes(self):
        red = TimingPoint(0, 500, sample_set=2, sample_index=1, volume=67)
        out = merge_timing([red], [(0, 1, 2, 70), (100, 1, 2, 70), (200, 1, 3, 70)])
        self.assertEqual([(tp.time, tp.uninherited, tp.sample_index) for tp in out], [(0, True, 1), (0, False, 2), (200, False, 3)])


if __name__ == "__main__":
    unittest.main()
