from .base import Plugin
import time
import requests
from requests.exceptions import RequestException
import logging


logger = logging.getLogger("loki.plugins.bettercap")

class BettercapPlugin(Plugin):
    def __init__(self, config=None):
        super().__init__(config or {})
        cfg = self.config if isinstance(self.config, dict) else {}
        self.enabled = bool(cfg.get("enabled", False))
        self.api_host = "127.0.0.1"
        self.api_port = 8081
        self._last_error_log = 0
        self._error_backoff = 1
        self._max_backoff = 60
        self._error_count = 0
        self.state = {
            "ap_count": 0,
            "client_count": 0,
            "last_http_status": 0,
            "error_count": 0,
            "last_update": 0.0,
        }

    def on_start(self, loki):
        cfg = self.config if isinstance(self.config, dict) else {}
        host = cfg.get("host")
        port = cfg.get("port")
        if host:
            self.api_host = host
        if port:
            self.api_port = int(port)
        logger.info(
            "[Bettercap] enabled=%s using API http://%s:%s/api/wifi/networks",
            self.enabled,
            self.api_host,
            self.api_port,
        )

    def on_tick(self, state):
        if not self.enabled:
            return
        url = f"http://{self.api_host}:{self.api_port}/api/wifi/networks"
        headers = {"Accept": "application/json"}
        try:
            r = requests.get(url, headers=headers, timeout=3)
            self.state["last_http_status"] = r.status_code
            self.state["last_update"] = time.time()
            if r.status_code == 200:
                data = r.json()
                aps = data.get("networks", [])
                ap_count = len(aps)
                client_count = 0
                for network in aps:
                    clients = network.get("clients", [])
                    if isinstance(clients, list):
                        client_count += len(clients)
                self.state["ap_count"] = ap_count
                self.state["client_count"] = client_count
                logger.info("[Bettercap] %d APs detected (%d clients)", ap_count, client_count)
                self._error_backoff = 1
            elif r.status_code == 405:
                self._error_count += 1
                self.state["error_count"] = self._error_count
                now = time.time()
                if now - self._last_error_log > 30:
                    logger.warning(
                        "[Bettercap] API returned 405 Method Not Allowed for %s. Try OPTIONS or check API docs.",
                        url,
                    )
                    self._last_error_log = now
                self._error_backoff = min(self._error_backoff * 2, self._max_backoff)
            else:
                self._error_count += 1
                self.state["error_count"] = self._error_count
                now = time.time()
                if now - self._last_error_log > 10:
                    logger.warning("[Bettercap] API error: HTTP %s", r.status_code)
                    self._last_error_log = now
        except RequestException as e:
            self._error_count += 1
            self.state["error_count"] = self._error_count
            self.state["last_update"] = time.time()
            now = time.time()
            if now - self._last_error_log > min(self._error_backoff, self._max_backoff):
                logger.warning("[Bettercap] error: %s", e)
                self._last_error_log = now
                self._error_backoff = min(self._error_backoff * 2, self._max_backoff)


Plugin = BettercapPlugin
