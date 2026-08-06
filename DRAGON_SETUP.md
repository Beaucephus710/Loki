# DRAGON SETUP — Loki Dragon Growth System

Loki starts as an egg at level 0 and grows into a hatchling, juvenile, and adult
dragon through positive interactions (`care`, `talk`, `play`, `feed`, `rest`).
All growth thresholds, mood values, and animation parameters are editable in
`config.toml` — no code changes required.

---

## Raspberry Pi Setup (Trixie 64-bit, headless)

```bash
sudo apt update
sudo apt install -y python3-pil python3-toml git

git clone https://github.com/Beaucephus710/Loki.git
cd Loki
```

---

## Quick-start Commands

**Show current status and save a PNG preview:**
```bash
python3 -m dragon.demo --status
```

**Apply one or more interactions:**
```bash
python3 -m dragon.demo --care talk
python3 -m dragon.demo --care care play feed
```

**Apply interactions and record an animated GIF:**
```bash
python3 -m dragon.demo --care talk --gif loki.gif
```

**Run without touching the state file (safe for testing):**
```bash
python3 -m dragon.demo --status --no-persist
python3 -m dragon.demo --care play --gif preview.gif --no-persist
```

All commands write a PNG preview to `loki_preview.png` in the current directory.

---

## Config reference (`config.toml`)

All dragon settings live under the `[dragon]` family of sections.

### `[dragon]` — top-level switches

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Set to `false` to disable the dragon system entirely |
| `state_path` | `~/.local/share/loki/dragon_state.json` | Where Loki's persistent state is stored |
| `persist` | `true` | Set to `false` to disable state persistence |

### `[dragon.xp]` — growth speed

Change these to control how quickly Loki grows or slow it down:

| Key | Default | Description |
|-----|---------|-------------|
| `hatchling` | `5` | XP required to hatch from the egg |
| `juvenile` | `25` | XP required to become a juvenile dragon |
| `adult` | `75` | XP required to reach full adulthood |
| `care` | `2` | XP per `care` interaction |
| `talk` | `1` | XP per `talk` interaction |
| `play` | `2` | XP per `play` interaction |
| `feed` | `1` | XP per `feed` interaction |
| `rest` | `1` | XP per `rest` interaction |

**Example — make Loki hatch after only 3 interactions:**
```toml
[dragon.xp]
hatchling = 3
juvenile  = 10
adult     = 30
```

### `[dragon.mood]` — mood and decay

| Key | Default | Description |
|-----|---------|-------------|
| `happy` | `80` | Mood score threshold for "happy" state |
| `content` | `55` | Mood score threshold for "content" state |
| `sleepy` | `30` | Mood score threshold for "sleepy" state |
| `care`–`rest` | 5/3/6/4/2 | Mood delta per interaction type |
| `decay_after_hours` | `0.25` | Idle hours before decay begins |
| `decay_hunger_per_hour` | `4` | Hunger points added per hour away |
| `decay_energy_per_hour` | `3` | Energy points lost per hour away |
| `decay_mood_per_hour` | `2` | Mood points lost per hour away |

### `[dragon.animation]` — display settings

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Set to `false` to suppress rendering |
| `width` | `480` | Frame width in pixels |
| `height` | `320` | Frame height in pixels |
| `fps` | `10` | Target frames per second |
| `background` | `[12, 18, 38]` | Background colour as `[R, G, B]` |
| `style` | `"default"` | Visual style (`"default"` is the only built-in style) |

### `[plugins.display]` — framebuffer pixel format

For physical SPI TFT displays on Raspberry Pi, add:

```toml
[plugins.display]
pixel_format = "RGB565"   # 16-bit packed format required by most Pi TFT screens
```

The default is `"RGB"` (24-bit, good for headless/preview use).

---

## Resetting Loki's state

Delete the state file to start over from an egg:

```bash
rm ~/.local/share/loki/dragon_state.json
```

Or set `persist = false` in `[dragon]` to disable persistence entirely.

---

## Framebuffer rendering

When a framebuffer is available (e.g. `/dev/fb1`), the `loki_animation` plugin
sends rendered frames to `LokiDisplay.draw_frame()` at the configured FPS.
When no framebuffer is present the plugin runs silently and only the PNG/GIF
preview workflows are active.

Add the plugin to your enabled list in `config.toml` to activate it in the
main loop:

```toml
[plugins.loki_animation]
enabled = true
```

---

## Triggering interactions from other code

```python
# Example: award XP from a Loki action
plugin = plugins["loki_animation"]  # from the main loop plugin dict
result = plugin.interact("talk")    # or care / play / feed / rest
print(result)
# {'interaction': 'talk', 'stage_before': 'egg', 'stage_after': 'egg',
#  'level': 0, 'xp': 3, 'mood': 'content'}
```

---

## Running tests

Tests use only the Python standard library (no Pillow or hardware required):

```bash
python3 -m unittest discover -s tests
```
