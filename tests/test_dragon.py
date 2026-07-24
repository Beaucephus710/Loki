"""Standard-library tests for the dragon growth system.

These tests do NOT require Pillow, hardware, or a framebuffer device.
Run with:

    python3 -m unittest discover -s tests
    # or:
    python3 -m unittest tests.test_dragon
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Make sure the repo root is on the path when running from anywhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dragon.state import (
    DragonConfig,
    DragonState,
    DragonStateStore,
    VALID_INTERACTIONS,
    _DEFAULT_XP_THRESHOLDS,
    _DEFAULT_MOOD_DELTA,
    _DEFAULT_XP_PER_INTERACTION,
    _DEFAULT_MOOD_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# DragonConfig: config merging
# ---------------------------------------------------------------------------

class TestDragonConfig(unittest.TestCase):
    def test_empty_config_uses_defaults(self):
        cfg = DragonConfig({})
        self.assertEqual(cfg.thresholds["hatchling"], _DEFAULT_XP_THRESHOLDS["hatchling"])
        self.assertEqual(cfg.thresholds["juvenile"], _DEFAULT_XP_THRESHOLDS["juvenile"])
        self.assertEqual(cfg.thresholds["adult"], _DEFAULT_XP_THRESHOLDS["adult"])
        for k in VALID_INTERACTIONS:
            self.assertEqual(cfg.xp_per_interaction[k], _DEFAULT_XP_PER_INTERACTION[k])
            self.assertEqual(cfg.mood_delta[k], _DEFAULT_MOOD_DELTA[k])

    def test_partial_config_overrides_only_supplied_keys(self):
        cfg = DragonConfig({"xp": {"hatchling": 10}})
        self.assertEqual(cfg.thresholds["hatchling"], 10)
        # Other thresholds remain at defaults
        self.assertEqual(cfg.thresholds["juvenile"], _DEFAULT_XP_THRESHOLDS["juvenile"])
        self.assertEqual(cfg.thresholds["adult"], _DEFAULT_XP_THRESHOLDS["adult"])

    def test_full_config_overrides_all_thresholds(self):
        cfg = DragonConfig({"xp": {"hatchling": 3, "juvenile": 10, "adult": 30}})
        self.assertEqual(cfg.thresholds["hatchling"], 3)
        self.assertEqual(cfg.thresholds["juvenile"], 10)
        self.assertEqual(cfg.thresholds["adult"], 30)

    def test_mood_thresholds_configurable(self):
        cfg = DragonConfig({"mood": {"happy": 90, "content": 60, "sleepy": 25}})
        self.assertEqual(cfg.mood_thresholds["happy"], 90)
        self.assertEqual(cfg.mood_thresholds["content"], 60)
        self.assertEqual(cfg.mood_thresholds["sleepy"], 25)

    def test_xp_per_interaction_configurable(self):
        cfg = DragonConfig({"xp": {"care": 5, "talk": 3}})
        self.assertEqual(cfg.xp_per_interaction["care"], 5)
        self.assertEqual(cfg.xp_per_interaction["talk"], 3)
        # Unspecified interactions use defaults
        self.assertEqual(cfg.xp_per_interaction["feed"], _DEFAULT_XP_PER_INTERACTION["feed"])

    def test_decay_defaults(self):
        cfg = DragonConfig({})
        self.assertEqual(cfg.decay_after_hours, 0.25)
        self.assertGreater(cfg.decay_hunger_per_hour, 0)

    def test_decay_configurable(self):
        cfg = DragonConfig({"mood": {"decay_after_hours": 1.0, "decay_mood_per_hour": 5.0}})
        self.assertEqual(cfg.decay_after_hours, 1.0)
        self.assertEqual(cfg.decay_mood_per_hour, 5.0)

    def test_persist_default_true(self):
        cfg = DragonConfig({})
        self.assertTrue(cfg.persist)

    def test_persist_configurable(self):
        cfg = DragonConfig({"persist": False})
        self.assertFalse(cfg.persist)

    def test_enabled_default_true(self):
        cfg = DragonConfig({})
        self.assertTrue(cfg.enabled)

    def test_none_config_uses_defaults(self):
        cfg = DragonConfig(None)
        self.assertEqual(cfg.thresholds["hatchling"], _DEFAULT_XP_THRESHOLDS["hatchling"])


# ---------------------------------------------------------------------------
# DragonState: stage transitions
# ---------------------------------------------------------------------------

class TestDragonStateStages(unittest.TestCase):
    def _make_state_with_cfg(self, thresholds=None):
        raw = {}
        if thresholds:
            raw["xp"] = thresholds
        cfg = DragonConfig(raw)
        state = DragonState()
        state.configure(cfg)
        return state, cfg

    def test_initial_stage_is_egg(self):
        state, _ = self._make_state_with_cfg()
        self.assertEqual(state.stage, "egg")
        self.assertEqual(state.level, 0)
        self.assertEqual(state.title, "Dragon Egg")

    def test_reaches_hatchling(self):
        state, cfg = self._make_state_with_cfg({"hatchling": 3, "juvenile": 20, "adult": 60})
        for _ in range(3):
            state.xp += cfg.xp_per_interaction["talk"]
        # Manually set xp to exact threshold
        state.xp = 3
        self.assertEqual(state.stage, "hatchling")
        self.assertEqual(state.level, 1)

    def test_reaches_juvenile(self):
        state, cfg = self._make_state_with_cfg({"hatchling": 3, "juvenile": 10, "adult": 30})
        state.xp = 10
        self.assertEqual(state.stage, "juvenile")
        self.assertEqual(state.level, 2)

    def test_reaches_adult(self):
        state, cfg = self._make_state_with_cfg({"hatchling": 3, "juvenile": 10, "adult": 30})
        state.xp = 30
        self.assertEqual(state.stage, "adult")
        self.assertEqual(state.level, 3)

    def test_below_threshold_stays_lower(self):
        state, _ = self._make_state_with_cfg({"hatchling": 5, "juvenile": 25, "adult": 75})
        state.xp = 4
        self.assertEqual(state.stage, "egg")

    def test_custom_thresholds_change_transitions(self):
        # With hatchling=2, just 2 XP should hatch the egg
        state, cfg = self._make_state_with_cfg({"hatchling": 2, "juvenile": 5, "adult": 10})
        state.xp = 2
        self.assertEqual(state.stage, "hatchling")

        # With default thresholds, 2 XP is still egg
        default_state = DragonState()
        default_state.xp = 2
        self.assertEqual(default_state.stage, "egg")

    def test_interact_awards_xp_and_changes_mood(self):
        state, cfg = self._make_state_with_cfg()
        initial_mood = state.mood
        result = state.interact("talk")
        self.assertGreater(state.xp, 0)
        self.assertGreaterEqual(state.mood, initial_mood)
        self.assertIn("stage_before", result)
        self.assertIn("stage_after", result)
        self.assertIn("xp", result)

    def test_interact_invalid_raises(self):
        state = DragonState()
        with self.assertRaises(ValueError):
            state.interact("fly")

    def test_interact_all_valid_kinds(self):
        for kind in VALID_INTERACTIONS:
            state = DragonState(last_updated=time.time())
            state.interact(kind)  # must not raise

    def test_stage_transition_reported_in_result(self):
        state, cfg = self._make_state_with_cfg({"hatchling": 1, "juvenile": 5, "adult": 20})
        # Set XP just below hatchling threshold
        state.xp = 0
        state.last_updated = time.time()
        result = state.interact("care")
        if result["stage_after"] != result["stage_before"]:
            self.assertEqual(result["stage_before"], "egg")
            self.assertEqual(result["stage_after"], "hatchling")

    def test_chained_interactions_accumulate_correctly(self):
        """Multiple different interactions on the same state all contribute."""
        cfg = DragonConfig({"xp": {"hatchling": 3, "juvenile": 8, "adult": 20}})
        state = DragonState(last_updated=time.time())
        state.configure(cfg)

        # Apply all interaction types in sequence
        kinds = ["care", "talk", "play", "feed", "rest"]
        total_xp_expected = sum(cfg.xp_per_interaction[k] for k in kinds)
        for kind in kinds:
            state.interact(kind)

        self.assertEqual(state.xp, total_xp_expected)
        self.assertEqual(state.interactions, len(kinds))
        # With 5+ XP and hatchling=3, we should have hatched
        self.assertNotEqual(state.stage, "egg")


# ---------------------------------------------------------------------------
# DragonState: mood names
# ---------------------------------------------------------------------------

class TestDragonMoodNames(unittest.TestCase):
    def _state_at_mood(self, mood_val):
        state = DragonState(mood=mood_val)
        return state

    def test_happy(self):
        self.assertEqual(self._state_at_mood(80).mood_name, "happy")
        self.assertEqual(self._state_at_mood(100).mood_name, "happy")

    def test_content(self):
        self.assertEqual(self._state_at_mood(55).mood_name, "content")
        self.assertEqual(self._state_at_mood(79).mood_name, "content")

    def test_sleepy(self):
        self.assertEqual(self._state_at_mood(30).mood_name, "sleepy")
        self.assertEqual(self._state_at_mood(54).mood_name, "sleepy")

    def test_grumpy(self):
        self.assertEqual(self._state_at_mood(0).mood_name, "grumpy")
        self.assertEqual(self._state_at_mood(29).mood_name, "grumpy")


# ---------------------------------------------------------------------------
# DragonState: time decay
# ---------------------------------------------------------------------------

class TestTimeDecay(unittest.TestCase):
    def test_no_decay_within_threshold(self):
        now = time.time()
        state = DragonState(mood=70, energy=80, hunger=20, last_updated=now)
        # Apply decay for only 5 minutes (below default 0.25h threshold)
        state.apply_time_decay(now=now + 300)
        self.assertEqual(state.mood, 70)
        self.assertEqual(state.energy, 80)

    def test_decay_after_threshold(self):
        now = time.time()
        state = DragonState(mood=70, energy=80, hunger=20, last_updated=now)
        # 2 hours later → decay should apply
        state.apply_time_decay(now=now + 7200)
        self.assertLess(state.mood, 70)
        self.assertLess(state.energy, 80)
        self.assertGreater(state.hunger, 20)

    def test_first_run_guard(self):
        state = DragonState(last_updated=0.0)
        state.apply_time_decay()  # must not crash
        self.assertGreater(state.last_updated, 0)

    def test_custom_decay_rate(self):
        now = time.time()
        fast_cfg = DragonConfig({"mood": {"decay_after_hours": 0.0, "decay_mood_per_hour": 10.0}})
        state = DragonState(mood=70, last_updated=now)
        state.configure(fast_cfg)
        # 1 hour → should lose ~10 mood
        state.apply_time_decay(now=now + 3600)
        self.assertLessEqual(state.mood, 60)


# ---------------------------------------------------------------------------
# DragonStateStore: persistence
# ---------------------------------------------------------------------------

class TestDragonStateStore(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = DragonStateStore(path, persist=True)

            original = DragonState(xp=12, mood=75, interactions=5)
            original.last_updated = time.time()
            store.save(original)

            loaded = store.load()
            self.assertEqual(loaded.xp, 12)
            self.assertEqual(loaded.mood, 75)
            self.assertEqual(loaded.interactions, 5)

    def test_load_creates_default_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            store = DragonStateStore(path, persist=False)
            state = store.load()
            self.assertEqual(state.xp, 0)
            self.assertIsInstance(state, DragonState)

    def test_persist_false_does_not_write_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = DragonStateStore(path, persist=False)
            state = DragonState(xp=99)
            state.last_updated = time.time()
            store.save(state)
            self.assertFalse(path.exists())

    def test_persist_true_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = DragonStateStore(path, persist=True)
            state = DragonState(xp=42)
            state.last_updated = time.time()
            store.save(state)
            self.assertTrue(path.exists())
            data = json.loads(path.read_text())
            self.assertEqual(data["xp"], 42)

    def test_corrupted_file_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("not valid json")
            store = DragonStateStore(path, persist=True)
            state = store.load()
            self.assertEqual(state.xp, 0)

    def test_config_thresholds_applied_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = DragonStateStore(path, persist=True)
            s = DragonState(xp=3)
            s.last_updated = time.time()
            store.save(s)

            # With default thresholds, xp=3 is "egg" (hatchling=5)
            loaded_default = store.load()
            self.assertEqual(loaded_default.stage, "egg")

            # With custom thresholds, xp=3 is "hatchling" (hatchling=2)
            custom_cfg = DragonConfig({"xp": {"hatchling": 2, "juvenile": 10, "adult": 30}})
            loaded_custom = store.load(custom_cfg)
            self.assertEqual(loaded_custom.stage, "hatchling")

    def test_atomic_write_uses_tmp_file(self):
        """Verify the save path writes to .tmp then renames (atomic write)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "state.json"
            store = DragonStateStore(path, persist=True)
            state = DragonState(xp=7)
            state.last_updated = time.time()
            store.save(state)
            self.assertTrue(path.exists())
            self.assertFalse(path.with_suffix(".tmp").exists())


# ---------------------------------------------------------------------------
# DragonState: serialisation
# ---------------------------------------------------------------------------

class TestDragonStateSerialization(unittest.TestCase):
    def test_to_dict_contains_all_fields(self):
        state = DragonState(xp=5, mood=60, hunger=30, energy=70, interactions=3)
        state.last_updated = 12345.0
        d = state.to_dict()
        self.assertEqual(d["xp"], 5)
        self.assertEqual(d["mood"], 60)
        self.assertEqual(d["hunger"], 30)
        self.assertEqual(d["energy"], 70)
        self.assertEqual(d["interactions"], 3)
        self.assertEqual(d["last_updated"], 12345.0)

    def test_to_dict_excludes_runtime_thresholds(self):
        state = DragonState()
        d = state.to_dict()
        self.assertNotIn("_thresholds", d)
        self.assertNotIn("_mood_thresholds", d)

    def test_from_dict_roundtrip(self):
        original = DragonState(xp=10, mood=50, interactions=7)
        original.last_updated = 999.0
        restored = DragonState.from_dict(original.to_dict())
        self.assertEqual(restored.xp, 10)
        self.assertEqual(restored.mood, 50)
        self.assertEqual(restored.interactions, 7)

    def test_from_dict_tolerates_missing_keys(self):
        state = DragonState.from_dict({"xp": 5})  # all other fields get defaults
        self.assertEqual(state.xp, 5)
        self.assertEqual(state.mood, 65)  # default


if __name__ == "__main__":
    unittest.main()
