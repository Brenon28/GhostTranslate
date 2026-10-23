import sys
import unittest
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QRect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.screens import crop_to_region, mask_native_rects, native_capture_region, screen_native_rect


# Так Qt 6 отдаёт мониторы этой машины при масштабе 150% на основном и 125% на левом:
# угол в физических пикселях, размер в логических.
PRIMARY_150 = QRect(0, 0, 2293, 960)
LEFT_125 = QRect(-1920, 140, 1536, 864)


class ScreenMathTests(unittest.TestCase):
    def test_native_rect_keeps_screen_origin(self):
        self.assertEqual(screen_native_rect(LEFT_125, 1.25), QRect(-1920, 140, 1920, 1080))
        self.assertEqual(screen_native_rect(PRIMARY_150, 1.5), QRect(0, 0, 3440, 1440))

    def test_full_secondary_screen_maps_to_its_physical_pixels(self):
        local = QRect(0, 0, LEFT_125.width(), LEFT_125.height())
        region = native_capture_region(LEFT_125, 1.25, local)
        self.assertEqual(region, {"left": -1920, "top": 140, "width": 1920, "height": 1080})

    def test_region_inside_secondary_screen(self):
        region = native_capture_region(LEFT_125, 1.25, QRect(100, 40, 400, 300))
        self.assertEqual(region, {"left": -1795, "top": 190, "width": 500, "height": 375})

    def test_region_is_clamped_to_screen(self):
        region = native_capture_region(PRIMARY_150, 1.5, QRect(2200, 900, 400, 400))
        self.assertEqual(region["left"] + region["width"], 3440)
        self.assertEqual(region["top"] + region["height"], 1440)

    def test_unscaled_screen_is_identity(self):
        geo = QRect(0, 0, 3440, 1440)
        region = native_capture_region(geo, 1.0, QRect(10, 20, 300, 200))
        self.assertEqual(region, {"left": 10, "top": 20, "width": 300, "height": 200})


class WatchdogCropTests(unittest.TestCase):
    """Эталон watchdog вырезается из кадра конвейера в тех же пикселях, что потом снимает поток."""

    def setUp(self):
        self.frame_region = {"left": -1920, "top": 140, "width": 400, "height": 300}
        self.frame = np.arange(300 * 400 * 4, dtype=np.uint32).astype(np.uint8).reshape(300, 400, 4)

    def test_crop_matches_offset_inside_frame(self):
        region = {"left": -1900, "top": 150, "width": 50, "height": 40}
        crop = crop_to_region(self.frame, self.frame_region, region)
        self.assertEqual(crop.shape, (40, 50, 4))
        self.assertTrue(np.array_equal(crop, self.frame[10:50, 20:70]))

    def test_region_outside_frame_gives_none(self):
        region = {"left": -1930, "top": 150, "width": 50, "height": 40}
        self.assertIsNone(crop_to_region(self.frame, self.frame_region, region))
        region = {"left": -1600, "top": 400, "width": 50, "height": 60}
        self.assertIsNone(crop_to_region(self.frame, self.frame_region, region))


class OwnWindowMaskTests(unittest.TestCase):
    """Игровой режим: панель попадает в снимок и закрашивается ровным цветом."""

    def setUp(self):
        self.frame_region = {"left": -1920, "top": 140, "width": 400, "height": 300}
        rng = np.random.default_rng(0)
        self.frame = rng.integers(0, 256, size=(300, 400, 4), dtype=np.uint8)

    def test_window_area_becomes_flat_and_rest_is_untouched(self):
        original = self.frame.copy()
        mask_native_rects(self.frame, self.frame_region, [(-1900, 150, -1850, 190)])
        patch = self.frame[10:50, 20:70]
        self.assertTrue((patch == patch[0, 0]).all())
        self.assertTrue(np.array_equal(self.frame[:, 70:], original[:, 70:]))
        self.assertTrue(np.array_equal(self.frame[50:], original[50:]))

    def test_window_partly_outside_frame_is_clipped(self):
        original = self.frame.copy()
        mask_native_rects(self.frame, self.frame_region, [(-2000, 100, -1910, 145), (0, 0, 50, 50)])
        self.assertTrue((self.frame[:5, :10] == self.frame[0, 0]).all())
        self.assertTrue(np.array_equal(self.frame[5:], original[5:]))
        self.assertTrue(np.array_equal(self.frame[:, 10:], original[:, 10:]))


if __name__ == "__main__":
    unittest.main()
