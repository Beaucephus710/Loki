"""Command-line demo and preview tool for Loki's dragon.

Usage examples (run from the repository root)::

    python3 -m dragon.demo --status
    python3 -m dragon.demo --care talk
    python3 -m dragon.demo --care feed rest --gif loki.gif
    python3 -m dragon.demo --care care talk play feed rest --gif loki.gif

``config.toml`` is discovered automatically from the current working directory
or the repository root.  No hard-coded paths.

The PNG preview is always written (default: ``loki_preview.png``).
Pass ``--gif PATH`` to also record a short animated GIF.
Pass ``--no-persist`` to run without touching state files.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _find_config() -> Path | None:
    """Locate config.toml, checking CWD first then the repo root."""
    candidates = [
        Path.cwd() / "config.toml",
        Path(__file__).resolve().parent.parent / "config.toml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_raw_config(config_path: Path | None = None) -> dict:
    """Return the full parsed config dict, or ``{}`` on any error."""
    path = config_path or _find_config()
    if path is None:
        return {}
    try:
        import toml  # already a project dependency
        return toml.load(path)
    except Exception as exc:
        print(f"Warning: could not load config.toml: {exc}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grow and preview Loki the dragon.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--care",
        nargs="+",
        metavar="INTERACTION",
        choices=["care", "talk", "play", "feed", "rest"],
        help="One or more interactions to apply (care talk play feed rest).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current growth status (default when no --care is given).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to config.toml (auto-detected if omitted).",
    )
    parser.add_argument(
        "--png",
        type=Path,
        default=Path("loki_preview.png"),
        metavar="PATH",
        help="Output path for the PNG preview (default: loki_preview.png).",
    )
    parser.add_argument(
        "--gif",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write a short animated GIF to this path.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not read or write the state file (useful for testing).",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    # Load full config and extract [dragon] section
    raw_cfg = _load_raw_config(args.config)
    dragon_raw = raw_cfg.get("dragon", {})

    # State setup
    from dragon.state import DragonConfig, DragonStateStore

    dragon_cfg = DragonConfig(dragon_raw)
    persist = dragon_cfg.persist and not args.no_persist
    store = DragonStateStore(dragon_cfg.state_path, persist=persist)
    state = store.load(dragon_cfg)

    # Apply interactions
    if args.care:
        for kind in args.care:
            result = state.interact(kind)
            store.save(state)
            print(
                f"{kind.title()} recorded: "
                f"XP={result['xp']}, level={result['level']}, mood={result['mood']}."
            )
            if result["stage_before"] != result["stage_after"]:
                print(
                    f"  *** Loki grew: {result['stage_before']} → {result['stage_after']}! ***"
                )

    # Always print status when requested, or when no interactions were applied
    if args.status or not args.care:
        print(
            f"{state.title}: level {state.level}, XP {state.xp}, "
            f"mood {state.mood_name}, interactions {state.interactions}."
        )

    # Render preview
    from dragon.animation import DragonAnimator

    anim_cfg = dragon_raw.get("animation", {})
    animator = DragonAnimator(anim_cfg)

    preview = animator.render(state, frame=0)
    args.png.parent.mkdir(parents=True, exist_ok=True)
    preview.save(args.png)
    print(f"Preview saved to {args.png.resolve()}")

    # Optional animated GIF
    if args.gif:
        frame_count = max(8, animator.fps * 2)  # at least 2 seconds
        frames = [animator.render(state, frame=f) for f in range(frame_count)]
        args.gif.parent.mkdir(parents=True, exist_ok=True)
        duration_ms = max(40, int(1000 / animator.fps))
        frames[0].save(
            args.gif,
            save_all=True,
            append_images=frames[1:],
            duration=duration_ms,
            loop=0,
        )
        print(f"Animation saved to {args.gif.resolve()}")


if __name__ == "__main__":
    main()
