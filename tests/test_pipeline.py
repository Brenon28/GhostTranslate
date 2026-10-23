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


class GameModeGrabTests(unittest.TestCase):
    """Игровой режим: плашки гаснут, снимок откладывается, после снимка плашки возвращаются."""

    def make_controller(self, game_mode=True):
        screen = object()
        return SimpleNamespace(
            is_hidden=False,
            snip_overlays=[],
            pipeline_busy=False,
            ocr_thread=None,
            pending_rescan=False,
            target_screen=screen,
            font_cfg=SimpleNamespace(game_mode=game_mode),
            capture_veiled=False,
            _grab_scheduled=False,
            _grab_check_static=True,
            _grab_generation=3,
            _capture_target=mock.Mock(return_value=(screen, QRect(0, 0, 100, 100))),
            _refresh_overlays=mock.Mock(),
            _grab_and_start=mock.Mock(),
            _schedule_next_monitor_tick=mock.Mock(),
        )

    def test_game_mode_veils_plaques_before_grab(self):
        ctrl = self.make_controller()
        with mock.patch.object(QTimer, "singleShot") as single_shot:
            GhostTranslateController._trigger_capture_pipeline(ctrl, True)
        self.assertTrue(ctrl.capture_veiled)
        self.assertTrue(ctrl._grab_scheduled)
        ctrl._refresh_overlays.assert_called_once()
        ctrl._grab_and_start.assert_not_called()
        single_shot.assert_called_once()

    def test_normal_mode_grabs_at_once(self):
        ctrl = self.make_controller(game_mode=False)
        GhostTranslateController._trigger_capture_pipeline(ctrl, True)
        ctrl._grab_and_start.assert_called_once_with(True)
        self.assertFalse(ctrl.capture_veiled)

    def test_manual_request_while_waiting_skips_static_check(self):
        ctrl = self.make_controller()
        ctrl._grab_scheduled = True
        GhostTranslateController._trigger_capture_pipeline(ctrl, False)
        self.assertFalse(ctrl._grab_check_static)
        ctrl._grab_and_start.assert_not_called()

    def test_stale_scheduled_grab_is_dropped(self):
        ctrl = self.make_controller()
        ctrl._grab_scheduled = True
        GhostTranslateController._grab_after_veil(ctrl, 2)
        ctrl._grab_and_start.assert_not_called()

    def test_busy_pipeline_restores_plaques_and_queues_rescan(self):
        ctrl = self.make_controller()
        ctrl._grab_scheduled = True
        ctrl.capture_veiled = True
        ctrl.pipeline_busy = True
        GhostTranslateController._grab_after_veil(ctrl, 3)
        self.assertFalse(ctrl.capture_veiled)
        self.assertTrue(ctrl.pending_rescan)
        ctrl._grab_and_start.assert_not_called()

    def test_grab_unveils_and_masks_visible_panels(self):
        frame = mock.Mock()
        visible, hidden = mock.Mock(), mock.Mock()
        visible.isVisible.return_value = True
        hidden.isVisible.return_value = False
        ctrl = SimpleNamespace(
            capture_veiled=True,
            safe_grab_screen=mock.Mock(return_value=frame),
            _refresh_overlays=mock.Mock(),
            toolbar=visible,
            font_popup=hidden,
            log_dialog=hidden,
        )
        region = {"left": 0, "top": 0, "width": 100, "height": 100}
        with mock.patch("ghosttranslate.controller.native_window_rect", return_value=(1, 2, 3, 4)), \
                mock.patch("ghosttranslate.controller.mask_native_rects") as mask:
            result = GhostTranslateController._grab_own_screen_frame(ctrl, region)
        self.assertIs(result, frame)
        self.assertFalse(ctrl.capture_veiled)
        ctrl._refresh_overlays.assert_called_once()
        mask.assert_called_once_with(frame, region, [(1, 2, 3, 4)])


if __name__ == "__main__":
    unittest.main()
