import tempfile
import unittest
from pathlib import Path

from dragon.state import DragonConfig, DragonStateStore


class DragonStateStoreTests(unittest.TestCase):
    def test_state_persists_across_loads(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "dragon_state.json"
            cfg = DragonConfig({"state_path": str(state_path), "persist": True})
            store = DragonStateStore(state_path, persist=True)

            state = store.load(cfg)
            result = state.interact("care")
            store.save(state)

            state2 = store.load(cfg)
            self.assertEqual(state2.xp, result["xp"])
            self.assertEqual(state2.interactions, 1)

    def test_no_persist_mode_does_not_write_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "dragon_state.json"
            cfg = DragonConfig({"state_path": str(state_path), "persist": False})
            store = DragonStateStore(state_path, persist=False)

            state = store.load(cfg)
            state.interact("talk")
            store.save(state)

            self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
