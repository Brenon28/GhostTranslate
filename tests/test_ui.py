import io
import sys
import unittest
import wave
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.sounds import SAMPLE_RATE, render_chime
from ghosttranslate.ui.toolbar import FloatingToolbar

APP = QApplication.instance() or QApplication(sys.argv)


class ToolbarWidthTests(unittest.TestCase):
    def setUp(self):
        self.toolbar = FloatingToolbar()

    def tearDown(self):
        self.toolbar.deleteLater()

    def test_wide_screen_keeps_one_row(self):
        self.toolbar.fit_to_width(3000)
        self.assertFalse(self.toolbar.is_two_rows)
        self.assertEqual(self.toolbar.row_extra.count(), 0)

    def test_narrow_screen_moves_second_group_down(self):
        # 1280x800 при масштабе 150% даёт 853 логических пикселя.
        single_row = self.toolbar._single_row_width()
        self.toolbar.fit_to_width(853)
        self.assertTrue(self.toolbar.is_two_rows)
        self.toolbar.adjustSize()
        self.assertLessEqual(self.toolbar.width(), 853)
        self.assertLess(self.toolbar.width(), single_row)

    def test_returns_to_one_row(self):
        self.toolbar.fit_to_width(853)
        self.toolbar.fit_to_width(3000)
        self.assertFalse(self.toolbar.is_two_rows)
        self.assertEqual(self.toolbar.row_extra.count(), 0)

    def test_hotkey_labels_follow_settings(self):
        self.toolbar.set_hotkey_labels("Ctrl+Alt+H", "Ctrl+Alt+T")
        self.assertEqual(self.toolbar.btn_region.text(), "Область [Ctrl+Alt+T]")
        self.assertEqual(self.toolbar.btn_clear.text(), "Скрыть [Ctrl+Alt+H]")


class ChimeTests(unittest.TestCase):
    def test_chime_is_soft_and_ends_silent(self):
        data = render_chime([(587.33, 0.0), (880.0, 0.11)], duration_s=0.75, volume=0.2)
        with wave.open(io.BytesIO(data)) as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, SAMPLE_RATE))
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        self.assertLessEqual(int(np.max(np.abs(pcm))), int(0.2 * 32767) + 1)
        self.assertEqual(int(pcm[-1]), 0)
        # Мягкая атака: первые 2 мс почти тишина, без щелчка в начале.
        self.assertLess(int(np.max(np.abs(pcm[: SAMPLE_RATE // 500]))), 3000)


if __name__ == "__main__":
    unittest.main()
