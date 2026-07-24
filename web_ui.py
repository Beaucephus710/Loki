"""Local-only web interface for inspecting and editing Loki's TOML settings."""

from __future__ import annotations

import html
import ipaddress
import os
import secrets
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 and earlier
    tomllib = None

_SECRET_NAMES = {"api_key", "password", "secret", "token"}


def _is_secret(path: tuple[str, ...]) -> bool:
    return any(part.lower() in _SECRET_NAMES for part in path)


def _flatten_settings(data: dict, prefix: tuple[str, ...] = ()):
    for key, value in data.items():
        path = prefix + (key,)
        if isinstance(value, dict):
            yield from _flatten_settings(value, path)
        elif not _is_secret(path):
            yield path, value


def _parse_value(value: str, current):
    if isinstance(current, bool):
        return value.lower() == "true"
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, list):
        return tomllib.loads("value = " + value)["value"]
    return value


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return f'"{value.replace("\\", "\\\\").replace("\"", "\\\"")}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return str(value)


def _dump_toml(data: dict) -> str:
    lines = []

    def write_table(table: dict, path: tuple[str, ...] = ()) -> None:
        if path:
            lines.append(f"[{'.'.join(path)}]")
        for key, value in table.items():
            if not isinstance(value, dict):
                lines.append(f"{key} = {_toml_value(value)}")
        for key, value in table.items():
            if isinstance(value, dict):
                if lines:
                    lines.append("")
                write_table(value, path + (key,))

    write_table(data)
    return "\n".join(lines) + "\n"


def _set_value(data: dict, path: tuple[str, ...], value) -> None:
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


class ConfigWebUI:
    """Serve a CSRF-protected configuration editor on a loopback address."""

    def __init__(self, config_path: str | Path, host: str = "127.0.0.1", port: int = 8080):
        if host != "127.0.0.1":
            raise ValueError("web UI must bind to 127.0.0.1")
        self.config_path = Path(config_path)
        self.host = host
        self.port = port
        self.csrf_token = secrets.token_urlsafe(32)
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def _load(self) -> dict:
        if tomllib is None:
            raise RuntimeError("Python 3.11 or later is required for the local web UI")
        with self.config_path.open("rb") as config_file:
            return tomllib.load(config_file)

    def _save(self, data: dict) -> None:
        fd, temporary_path = tempfile.mkstemp(
            dir=self.config_path.parent, prefix=f".{self.config_path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                temporary.write(_dump_toml(data))
            os.replace(temporary_path, self.config_path)
        except Exception:
            os.unlink(temporary_path)
            raise

    def _page(self, message: str = "") -> str:
        rows = []
        for path, value in _flatten_settings(self._load()):
            field = ".".join(path)
            escaped_field = html.escape(field, quote=True)
            if isinstance(value, bool):
                control = (
                    f'<select name="{escaped_field}"><option value="true"'
                    f'{" selected" if value else ""}>true</option><option value="false"'
                    f'{" selected" if not value else ""}>false</option></select>'
                )
            else:
                control = f'<input name="{escaped_field}" value="{html.escape(str(value), quote=True)}">'
            rows.append(f"<tr><th>{escaped_field}</th><td>{control}</td></tr>")
        notice = f"<p class=\"notice\">{html.escape(message)}</p>" if message else ""
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Loki configuration</title>
<style>body{{font-family:sans-serif;max-width:900px;margin:2rem auto}}table{{border-collapse:collapse;width:100%}}th,td{{padding:.5rem;border-bottom:1px solid #ddd;text-align:left}}input{{width:100%;box-sizing:border-box}}.notice{{color:#075}}</style>
</head><body><h1>Loki configuration</h1>
<p>Changes are saved to {html.escape(str(self.config_path))}. Restart Loki to apply them. Secrets are deliberately excluded; configure the WPA-SEC key with <code>LOKI_WPA_SEC_API_KEY</code>.</p>
{notice}<form method="post"><input type="hidden" name="csrf_token" value="{self.csrf_token}"><table>{''.join(rows)}</table><p><button type="submit">Save configuration</button></p></form></body></html>"""

    def _handler(self):
        ui = self

        class Handler(BaseHTTPRequestHandler):
            def _is_loopback(self) -> bool:
                return ipaddress.ip_address(self.client_address[0]).is_loopback

            def do_GET(self):
                if not self._is_loopback() or self.path != "/":
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(ui._page().encode())

            def do_POST(self):
                if not self._is_loopback() or self.path != "/":
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
                if form.get("csrf_token", [""])[0] != ui.csrf_token:
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                data = ui._load()
                try:
                    for path, current in _flatten_settings(data):
                        field = ".".join(path)
                        if field in form:
                            _set_value(data, path, _parse_value(form[field][0], current))
                    ui._save(data)
                except (ValueError, TypeError, RuntimeError) as error:
                    self.send_response(HTTPStatus.BAD_REQUEST)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(ui._page(f"Configuration was not saved: {error}").encode())
                    return
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.end_headers()

            def log_message(self, format, *args):
                return

        return Handler

    def start(self) -> None:
        self.server = ThreadingHTTPServer((self.host, self.port), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
