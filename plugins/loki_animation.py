"""Dragon growth and animation plugin for Loki.

Conforms to the repository plugin pattern (``Plugin``, ``on_start``,
``on_tick``, ``on_stop``).

Configuration is read from the ``[dragon]`` section of ``config.toml``.
The plugin renders dragon animation frames in a background thread and sends
them to ``LokiDisplay.draw_frame()`` when a framebuffer display is available.
If no framebuffer is present the plugin runs silently without crashing.

External code can trigger interactions (award XP) by calling::

    plugin.interact("talk")   # or care / play / feed / rest

This is safe to call from any thread.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_dragon_config() -> dict:
    """Load the ``[dragon]`` section from config.toml.  Returns ``{}`` on
    any error so the plugin always starts gracefully."""
    try:
        import toml
        cfg_path = Path(__file__).resolve().parent.parent / "config.toml"
        data = toml.load(cfg_path)
        return data.get("dragon", {})
    except Exception as exc:
        logger.debug("Could not load dragon config: %s", exc)
        return {}


def _get_display(dragon_anim_cfg: dict):
    """Return a LokiDisplay instance, or ``None`` if unavailable."""
    try:
        from display import init_display

        class _MinimalConfig:
            """Thin wrapper so init_display can call config.display()."""
            def __init__(self, d):
                self._d = d

            def display(self):
                return self._d

        # Map [dragon.animation] width/height into the display config dict so the
        # display opens with matching dimensions when first initialised.
        disp_cfg: dict = {}
        if dragon_anim_cfg.get("width"):
            disp_cfg["width"] = dragon_anim_cfg["width"]
        if dragon_anim_cfg.get("height"):
            disp_cfg["height"] = dragon_anim_cfg["height"]

        return init_display(_MinimalConfig(disp_cfg))
    except Exception as exc:
        logger.debug("Display not available: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class LokiAnimationPlugin(Plugin):
    """Dragon growth and animation plugin.

    Lifecycle:
      - ``on_start`` — load/create dragon state, start background render loop
      - ``on_tick``  — expose state snapshot for other plugins
      - ``on_stop``  — stop render loop and persist state
    """

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

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def on_start(self, loki) -> None:
        try:
            dragon_raw = _load_dragon_config()

            if not dragon_raw.get("enabled", True):
                logger.info("[LokiAnimation] disabled in config; skipping start")
                return

            from dragon.state import DragonConfig, DragonStateStore
            from dragon.animation import DragonAnimator

            self._dragon_cfg = DragonConfig(dragon_raw)
            self._store = DragonStateStore(
                self._dragon_cfg.state_path,
                persist=self._dragon_cfg.persist,
            )
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
                "[LokiAnimation] started — stage=%s level=%d XP=%d",
                self._state.stage,
                self._state.level,
                self._state.xp,
            )
        except Exception:
            logger.exception("[LokiAnimation] on_start failed")

    def on_tick(self, shared_state) -> None:
        """No-op: state is exposed via the ``state`` property."""

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

    # ------------------------------------------------------------------
    # Public interaction API
    # ------------------------------------------------------------------

    def interact(self, kind: str) -> dict | None:
        """Award XP and mood for *kind* interaction.  Thread-safe.

        Valid values: ``"care"``, ``"talk"``, ``"play"``, ``"feed"``, ``"rest"``.

        Returns the result dict from :meth:`DragonState.interact`, or
        ``None`` if the plugin has not started yet.
        """
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

    # ------------------------------------------------------------------
    # State snapshot (exposed to main loop via shared_state)
    # ------------------------------------------------------------------

    @property
    def state(self) -> dict | None:
        """Return a JSON-serialisable snapshot of the dragon state."""
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

    # ------------------------------------------------------------------
    # Render loop (background thread)
    # ------------------------------------------------------------------

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
                    # LokiDisplay.fb is None when the framebuffer could not be
                    # opened (headless mode).  We use getattr() with a default
                    # here because DisplayFallback (main.py) does not expose fb,
                    # so the check is intentionally safe for both display types.
                    if self._display is not None and getattr(self._display, "fb", None) is not None:
                        self._display.draw_frame(img)
            except Exception:
                logger.exception("[LokiAnimation] render loop error")

            elapsed = time.monotonic() - t0
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)


# The main plugin loader expects the name ``Plugin``
Plugin = LokiAnimationPlugin  # type: ignore[misc]
