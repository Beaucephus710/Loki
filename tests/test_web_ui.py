"""Tests for the local configuration web UI helpers."""

import tempfile
import unittest
from urllib.request import urlopen
from pathlib import Path

from web_ui import ConfigWebUI, _flatten_settings, _parse_value


class TestConfigWebUI(unittest.TestCase):
    def test_rejects_non_loopback_host(self):
        with self.assertRaises(ValueError):
            ConfigWebUI("config.toml", host="0.0.0.0")

    def test_hides_secret_fields(self):
        fields = dict(
            _flatten_settings(
                {"plugins": {"wpa_sec": {"api_key": "do-not-display", "enabled": True}}}
            )
        )
        self.assertNotIn(("plugins", "wpa_sec", "api_key"), fields)
        self.assertTrue(fields[("plugins", "wpa_sec", "enabled")])

    def test_parses_existing_value_types(self):
        self.assertTrue(_parse_value("true", False))
        self.assertEqual(_parse_value("12", 1), 12)
        self.assertEqual(_parse_value("[1, 2]", []), [1, 2])

    def test_save_is_reparseable(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text("enabled = true\n")
            ui = ConfigWebUI(config_path)
            ui._save({"enabled": False})
            self.assertEqual(ui._load(), {"enabled": False})

    def test_serves_configuration_on_loopback(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text("enabled = true\n")
            ui = ConfigWebUI(config_path, port=0)
            try:
                ui.start()
                port = ui.server.server_address[1]
                with urlopen(f"http://127.0.0.1:{port}/") as response:
                    page = response.read().decode()
                self.assertIn("Loki configuration", page)
                self.assertIn("csrf_token", page)
            finally:
                ui.stop()


if __name__ == "__main__":
    unittest.main()
