"""Dragon growth and animation plugin for Loki."""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("loki.dragon")

try:
    from plugins.base import Plugin
except Exception:
    class Plugin:  # type: ignore[no-redef]
        def __init__(self, config=None):
            self.config = config

        def on_start(self, loki):
            pass

        def on_tick(self, state):
            pass

        def on_stop(self):
            pass


def _resolve_dragon_config(config) -> dict:
    if not isinstance(config, dict):
        return {}

    dragon_cfg = dict(config.get("dragon", {}) or {})
    plugin_cfg = config.get("plugin")
    if not isinstance(plugin_cfg, dict):
        plugin_cfg = config

    if "enabled" in plugin_cfg:
        dragon_cfg["enabled"] = bool(plugin_cfg["enabled"])

    animation_cfg = dict(dragon_cfg.get("animation", {}) or {})
    if "style" in plugin_cfg:
        animation_cfg["style"] = plugin_cfg["style"]
    if "speed" in plugin_cfg:
        try:
            speed = float(plugin_cfg["speed"])
            if speed > 0 and animation_cfg.get("fps"):
                animation_cfg["fps"] = max(1, int(float(animation_cfg["fps"]) * speed))
        except (TypeError, ValueError):
            pass
    if animation_cfg:
        dragon_cfg["animation"] = animation_cfg

    return dragon_cfg


def _get_display(dragon_anim_cfg: dict):
    try:
        from display import init_display

        class _MinimalConfig:
            def __init__(self, d):
                self._d = d

            def display(self):
                return self._d

        disp_cfg: dict = {}
        if dragon_anim_cfg.get("width"):
            disp_cfg["width"] = dragon_anim_cfg["width"]
        if dragon_anim_cfg.get("height"):
            disp_cfg["height"] = dragon_anim_cfg["height"]

        return init_display(_MinimalConfig(disp_cfg))
    except Exception as exc:
        logger.debug("Display not available: %s", exc)
        return None


class LokiAnimationPlugin(Plugin):
    def __init__(self, config=None):
        super().__init__(config)
        self._dragon_cfg = None
        self._state = None
        self._store = None
        self._animator = None
        self._display = None
        self._thread: threading.Thread | None = None
        self._stop_flag = False
        self._lock = threading.Lock()
        self._frame_index = 0

    def on_start(self, loki) -> None:
        try:
            dragon_raw = _resolve_dragon_config(self.config)

            if not dragon_raw.get("enabled", True):
                logger.info("[LokiAnimation] disabled in config; skipping start")
                return

            from dragon.state import DragonConfig, DragonStateStore
            from dragon.animation import DragonAnimator

            self._dragon_cfg = DragonConfig(dragon_raw)
            self._store = DragonStateStore(self._dragon_cfg.state_path, persist=self._dragon_cfg.persist)
            self._state = self._store.load(self._dragon_cfg)

            anim_cfg = dragon_raw.get("animation", {})
            self._animator = DragonAnimator(anim_cfg)

            self._display = _get_display(anim_cfg)

            fps = self._animator.fps
            interval = 1.0 / fps

            self._stop_flag = False
            self._thread = threading.Thread(
                target=self._render_loop,
                args=(interval,),
                daemon=True,
                name="dragon-render",
            )
            self._thread.start()

            logger.info(
                "[LokiAnimation] started - stage=%s level=%d XP=%d",
                self._state.stage,
                self._state.level,
                self._state.xp,
            )
        except Exception:
            logger.exception("[LokiAnimation] on_start failed")

    def on_tick(self, shared_state) -> None:
        return None

    def on_stop(self) -> None:
        self._stop_flag = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        with self._lock:
            if self._store and self._state:
                try:
                    self._store.save(self._state)
                except Exception:
                    logger.exception("[LokiAnimation] failed to save state on stop")

        logger.info("[LokiAnimation] stopped")

    def interact(self, kind: str) -> dict | None:
        with self._lock:
            if self._state is None:
                logger.warning("[LokiAnimation] interact called before on_start")
                return None
            result = self._state.interact(kind)

        if self._store:
            try:
                self._store.save(self._state)
            except Exception:
                logger.exception("[LokiAnimation] failed to save state after interact")

        logger.debug("[LokiAnimation] interact=%s result=%s", kind, result)
        return result

    @property
    def state(self) -> dict | None:
        with self._lock:
            if self._state is None:
                return None
            return {
                "stage": self._state.stage,
                "level": self._state.level,
                "xp": self._state.xp,
                "mood": self._state.mood_name,
                "title": self._state.title,
                "interactions": self._state.interactions,
            }

    def _render_loop(self, interval: float) -> None:
        while not self._stop_flag:
            t0 = time.monotonic()
            try:
                with self._lock:
                    state = self._state
                    frame = self._frame_index
                    self._frame_index += 1

                if state is not None and self._animator is not None:
                    img = self._animator.render(state, frame)
                    if self._display is not None and getattr(self._display, "fb", None) is not None:
                        self._display.draw_frame(img)
            except Exception:
                logger.exception("[LokiAnimation] render loop error")

            elapsed = time.monotonic() - t0
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)


Plugin = LokiAnimationPlugin
