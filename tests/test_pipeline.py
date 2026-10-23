import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtGui import QColor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.controller import GhostTranslateController
from ghosttranslate.models import OverlayBlock
from ghosttranslate.translator import NativeCT2Translator, TranslationLRUCache


def block(text, pending=True):
    color = QColor(0, 0, 0)
    return OverlayBlock(
        rect=QRect(0, 0, 100, 20),
        orig_text=text,
        trans_text=text,
        bg_color=color,
        bg_color_right=color,
        fg_color=color,
        is_pending=pending,
    )


class TranslatorFallbackTests(unittest.TestCase):
    def test_not_ready_model_marks_text_as_untranslated(self):
        translator = NativeCT2Translator()
        result = translator.translate_batch(["Open the inventory", "SETTINGS"])
        self.assertEqual(result, [("Open the inventory", False), ("НАСТРОЙКИ", True)])


class BatchResultTests(unittest.TestCase):
    def make_controller(self, blocks):
        return SimpleNamespace(
            job_id=7,
            overlay_blocks=blocks,
            lru_cache=TranslationLRUCache(),
            _refresh_overlays=mock.Mock(),
        )

    def test_untranslated_text_is_not_cached(self):
        ctrl = self.make_controller([block("Open the inventory"), block("Close")])
        pairs = [(0, "Open the inventory", "Open the inventory", False), (1, "Close", "Закрыть", True)]
        GhostTranslateController._on_batch_translated(ctrl, pairs, 7)

        self.assertIsNone(ctrl.lru_cache.get("Open the inventory"))
        self.assertEqual(ctrl.lru_cache.get("Close"), "Закрыть")
        self.assertTrue(ctrl.overlay_blocks[0].is_fallback)
        self.assertFalse(ctrl.overlay_blocks[1].is_fallback)

    def test_stale_job_is_ignored(self):
        ctrl = self.make_controller([block("Close")])
        GhostTranslateController._on_batch_translated(ctrl, [(0, "Close", "Закрыть", True)], 6)
        self.assertTrue(ctrl.overlay_blocks[0].is_pending)
        self.assertIsNone(ctrl.lru_cache.get("Close"))


class PendingRescanTests(unittest.TestCase):
    def test_manual_request_during_translation_is_not_lost(self):
        ctrl = SimpleNamespace(
            pipeline_busy=True,
            monitor_interval_ms=0,
            watchdog=mock.Mock(),
            _arm_watchdog=mock.Mock(),
            toolbar=mock.Mock(),
            overlay_blocks=[],
            is_hidden=False,
            pending_rescan=True,
            _retranslate_when_idle=False,
            _schedule_next_monitor_tick=mock.Mock(),
            _retranslate_fallback_blocks=mock.Mock(),
        )
        with mock.patch.object(QTimer, "singleShot") as single_shot:
            GhostTranslateController._finish_pipeline_cycle(ctrl)

        self.assertFalse(ctrl.pipeline_busy)
        self.assertFalse(ctrl.pending_rescan)
        single_shot.assert_called_once()


if __name__ == "__main__":
    unittest.main()
