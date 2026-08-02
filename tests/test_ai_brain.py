import json
import tempfile
import types
import unittest
from pathlib import Path

import main
from plugins.ai_brain import A2CBrainPlugin


class _DummyPlugin:
    def __init__(self, config=None):
        self.config = config or {}


class PluginLoaderTests(unittest.TestCase):
    def test_instantiate_plugins_skips_base_and_disabled(self):
        modules = {
            "base": types.SimpleNamespace(Plugin=_DummyPlugin),
            "ai_brain": types.SimpleNamespace(Plugin=_DummyPlugin),
            "scan": types.SimpleNamespace(Plugin=_DummyPlugin),
        }
        config = {
            "plugins": {
                "ai_brain": {"enabled": True},
                "scan": {"enabled": False},
            }
        }

        instances = main.instantiate_plugins(modules, config)

        self.assertIn("ai_brain", instances)
        self.assertNotIn("scan", instances)
        self.assertNotIn("base", instances)


class A2CBrainPluginTests(unittest.TestCase):
    def test_inference_mode_emits_action_state(self):
        plugin = A2CBrainPlugin({"enabled": True, "learning": False, "decision_interval": 0})
        plugin.on_start(None)
        plugin.on_tick({})

        self.assertIn(plugin.state["current_action"], plugin.ACTIONS)
        self.assertEqual(plugin.state["steps"], 1)

    def test_learning_mode_persists_model_state(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "a2c_state.json"
            plugin = A2CBrainPlugin(
                {
                    "enabled": True,
                    "learning": True,
                    "decision_interval": 0,
                    "save_every_steps": 1,
                    "state_path": str(state_path),
                }
            )
            plugin.on_start(None)

            plugin.on_tick(
                {
                    "bettercap": {
                        "ap_count": 1,
                        "client_count": 0,
                        "error_count": 0,
                        "last_http_status": 200,
                    }
                }
            )
            plugin.on_tick(
                {
                    "bettercap": {
                        "ap_count": 3,
                        "client_count": 2,
                        "error_count": 0,
                        "last_http_status": 200,
                    }
                }
            )
            plugin.on_stop()

            self.assertTrue(state_path.exists())
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("actor_weights", payload)
            self.assertIn("critic_weights", payload)
            self.assertGreaterEqual(payload.get("total_steps", 0), 2)


if __name__ == "__main__":
    unittest.main()
