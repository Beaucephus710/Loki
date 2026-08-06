import tempfile
import unittest
from pathlib import Path

from display import LokiDisplay, init_display


class _FakeImage:
    def __init__(self, size, color):
        self.size = size
        self._color = color
        self._pixels = [color for _ in range(size[0] * size[1])]

    def convert(self, mode):
        assert mode == "RGB"
        return self

    def resize(self, size, resample=None):
        return _FakeImage(size, self._color)

    def getpixel(self, position):
        return self._color

    def tobytes(self):
        return bytes([self._color[0], self._color[1], self._color[2]] * (self.size[0] * self.size[1]))


class _FakeConfig:
    def __init__(self, payload):
        self._payload = payload

    def display(self):
        return self._payload


class TestDisplay(unittest.TestCase):
    def test_init_display_falls_back_to_noop_when_framebuffer_missing(self):
        display = init_display(
            _FakeConfig(
                {"width": 64, "height": 48, "pixel_format": "RGB", "framebuffer_path": "/tmp/loki-display-does-not-exist"}
            )
        )
        self.assertIsNone(display.fb)
        self.assertIsNone(display._buffer)
        self.assertFalse(display.draw_frame(_FakeImage((64, 48), (255, 0, 0))))

    def test_draw_frame_writes_to_regular_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            path = tmp.name

        display = None
        try:
            display = LokiDisplay(width=2, height=2, pixel_format="RGB", framebuffer_path=path)
            img = _FakeImage((2, 2), (0, 255, 0))
            self.assertTrue(display.draw_frame(img))
            data = Path(path).read_bytes()
            self.assertGreater(len(data), 0)
        finally:
            display.close()
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
