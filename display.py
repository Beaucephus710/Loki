from PIL import Image, ImageDraw
import time
import logging
import threading

logger = logging.getLogger("loki.display")

# Guard and single shared instance for the framebuffer/display
_fb_opened = False
_display_instance = None
_display_lock = threading.Lock()


def _convert_to_pixel_format(img, pixel_format):
    """
    Convert a PIL RGB image to raw bytes matching the framebuffer pixel format.

    Supported formats:
      "RGB565" (default) – 16bpp, 2 bytes/pixel, little-endian.
                           Required by fbtft SPI TFT drivers on Raspberry Pi.
      "RGB888"           – 24bpp, 3 bytes/pixel.  Use only when the framebuffer
                           is configured for 24-bit colour depth.
    """
    img = img.convert("RGB")
    fmt = (pixel_format or "RGB565").upper()

    if fmt == "RGB888":
        return img.tobytes()

    # RGB565: pack R[7:3] G[7:2] B[7:3] into a 16-bit little-endian word
    try:
        import numpy as np
        arr = np.asarray(img, dtype=np.uint16)
        r = arr[:, :, 0]
        g = arr[:, :, 1]
        b = arr[:, :, 2]
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        return rgb565.astype("<u2").tobytes()
    except ImportError:
        # Pure-Python fallback (slower, no numpy dependency required)
        pixels = list(img.getdata())
        buf = bytearray(len(pixels) * 2)
        for i, (r, g, b) in enumerate(pixels):
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            buf[i * 2] = v & 0xFF
            buf[i * 2 + 1] = (v >> 8) & 0xFF
        return bytes(buf)


class LokiDisplay:
    """
    LokiDisplay opens the framebuffer once and exposes simple drawing helpers.
    """

    def __init__(self, config):
        global _fb_opened, _display_instance
        # If another instance was created while this constructor was queued,
        # reuse it to avoid opening the device twice.
        if _fb_opened and _display_instance is not None:
            logger.debug("LokiDisplay.__init__: reusing existing display instance")
            existing = _display_instance
            self.width = existing.width
            self.height = existing.height
            self.animation = existing.animation
            self.fb_dev = existing.fb_dev
            self.pixel_format = existing.pixel_format
            self.fb = existing.fb
            return

        # Normal initialization (first instance)
        try:
            disp_cfg = config.display() if hasattr(config, "display") else {}
        except Exception:
            disp_cfg = {}
        self.width = disp_cfg.get("width", 480)
        self.height = disp_cfg.get("height", 320)
        self.animation = disp_cfg.get("animation", "boot_sequence")
        self.fb_dev = disp_cfg.get("device", "/dev/fb1") if isinstance(disp_cfg, dict) else "/dev/fb1"
        # pixel_format must match the framebuffer depth configured by the kernel driver.
        # fbtft SPI TFT displays on Raspberry Pi default to 16bpp RGB565.
        self.pixel_format = disp_cfg.get("pixel_format", "RGB565") if isinstance(disp_cfg, dict) else "RGB565"

        try:
            self.fb = open(self.fb_dev, "wb", buffering=0)
            logger.info("Opened framebuffer device %s (%s)", self.fb_dev, self.pixel_format)
        except Exception as e:
            logger.error("Unexpected error opening framebuffer %s: %s", self.fb_dev, e)
            self.fb = None

        _display_instance = self
        _fb_opened = True

    def draw_frame(self, img):
        if not self.fb:
            return
        try:
            raw = _convert_to_pixel_format(img, self.pixel_format)
            self.fb.write(raw)
            self.fb.flush()
        except Exception:
            logger.exception("Error writing frame to framebuffer")

    def boot_animation(self):
        for i in range(60):
            img = Image.new("RGB", (self.width, self.height), (i * 4 % 255, 0, 40))
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "Loki booting...", fill=(255, 255, 255))
            draw.text((10, 40), f"Step {i}", fill=(200, 200, 200))
            self.draw_frame(img)
            time.sleep(0.05)

    def show_plugin_status(self, active_plugins, enabled_plugins):
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), "Loki Plugins", fill=(0, 255, 0))
        y = 40
        for name in enabled_plugins:
            color = (255, 255, 255)
            if name in active_plugins:
                color = (0, 255, 0)
            draw.text((10, y), f"- {name}", fill=color)
            y += 20
        self.draw_frame(img)

    def close(self):
        try:
            if self.fb:
                self.fb.close()
        except Exception:
            logger.exception("Error closing framebuffer")


def init_display(config):
    """
    Return a single shared display instance. Thread-safe: prevents concurrent creation.
    """
    global _fb_opened, _display_instance

    # Fast path
    if _fb_opened and _display_instance is not None:
        logger.debug("Display already initialized; returning existing instance")
        return _display_instance

    # Slow path: ensure only one thread creates the instance
    with _display_lock:
        if _fb_opened and _display_instance is not None:
            logger.debug("Display initialized while waiting for lock; returning existing instance")
            return _display_instance

        disp = LokiDisplay(config)
        _display_instance = disp
        _fb_opened = True
        return _display_instance
