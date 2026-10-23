import sys
import unittest
from pathlib import Path

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.config import MIN_READABLE_FONT_PX
from ghosttranslate.game_dict import translate_ui_pattern
from ghosttranslate.models import OverlayBlock
from ghosttranslate.settings import FontCustomConfig
from ghosttranslate.ui.plaque_layout import PAD_X, layout_blocks

APP = QApplication.instance() or QApplication(sys.argv)
SCREEN = QRect(0, 0, 1920, 1080)

LONG_RU = (
    "плюс ряд небольших багов, например, когда игра зависает после обратного отсчета до следующей "
    "карты, даже если вы попали дальше. Тогда у вас нет другого выбора, кроме как покинуть сервер "
    "и снова заняться сватовством."
)


def block(x, y, w, h, orig, trans, lines=1, font_px=14):
    color = QColor(20, 20, 20)
    return OverlayBlock(
        rect=QRect(x, y, w, h), orig_text=orig, trans_text=trans, bg_color=color, bg_color_right=color,
        fg_color=QColor("#FFFFFF"), lines_merged=lines, is_pending=False, font_px=font_px,
    )


def layouts_by_text(blocks, style="wrap_gradient"):
    return {lay.block.orig_text: lay for lay in layout_blocks(blocks, FontCustomConfig(), style, SCREEN)}


class PlaqueLayoutTests(unittest.TestCase):
    def test_long_paragraph_stays_readable_and_grows_down(self):
        paragraph = block(967, 400, 520, 41, "plus a number of smaller bugs", LONG_RU, lines=2)
        lay = layouts_by_text([paragraph])["plus a number of smaller bugs"]
        self.assertGreaterEqual(lay.font.pixelSize(), MIN_READABLE_FONT_PX)
        self.assertEqual(lay.rect.top(), paragraph.rect.top())
        self.assertGreater(lay.rect.height(), paragraph.rect.height())
        # Текст перевода начинается там же, где начинался английский, а не левее.
        self.assertEqual(lay.text_rect.left(), paragraph.rect.left())

    def test_paragraph_below_moves_under_the_grown_one(self):
        upper = block(967, 400, 520, 41, "upper", LONG_RU, lines=2)
        lower = block(967, 456, 570, 21, "lower", "Я знаю, что люди постоянно пишут об этом.")
        lays = layouts_by_text([upper, lower])
        self.assertGreater(lays["lower"].rect.top(), lays["upper"].rect.bottom())

    def test_buttons_in_one_row_are_not_stacked(self):
        reply = block(1100, 860, 34, 20, "Reply", "Ответить")
        award = block(1176, 860, 40, 20, "Award", "Награда")
        lays = layouts_by_text([reply, award])
        self.assertEqual(lays["Reply"].rect.top(), 860)
        self.assertEqual(lays["Award"].rect.top(), 860)
        self.assertLessEqual(lays["Reply"].rect.right(), award.rect.left() - PAD_X)

    def test_row_of_menu_buttons_does_not_overlap(self):
        back = block(35, 288, 45, 22, "Back", "НАЗАД", font_px=21)
        apply = block(128, 288, 55, 22, "Apply", "ПРИМЕНИТЬ", font_px=21)
        reset = block(232, 288, 151, 22, "Reset to default", "Перезагрузить по умолчанию", font_px=21)
        lays = layouts_by_text([reset, apply, back])
        self.assertLess(lays["Back"].rect.right(), lays["Apply"].rect.left())
        self.assertLess(lays["Apply"].rect.right(), reset.rect.left())
        self.assertGreaterEqual(lays["Apply"].font.pixelSize(), MIN_READABLE_FONT_PX)

    def test_wider_label_does_not_cover_text_on_the_left(self):
        ago = block(1109, 784, 47, 20, "35m ago", "35 минут назад")
        lay = layouts_by_text([ago])["35m ago"]
        self.assertGreaterEqual(lay.rect.left(), ago.rect.left() - PAD_X)
        self.assertGreater(lay.rect.width(), ago.rect.width())

    def test_short_label_inside_its_box_stays_centered(self):
        play = block(100, 70, 120, 24, "PLAY", "ИГРАТЬ", font_px=16)
        lay = layouts_by_text([play])["PLAY"]
        self.assertEqual(lay.rect.center().x(), play.rect.center().x())

    def test_single_line_style_never_wraps(self):
        line = block(10, 10, 200, 20, "orig", "очень длинный перевод " * 20)
        lay = layouts_by_text([line], style="single")["orig"]
        self.assertLessEqual(lay.rect.right(), SCREEN.right())
        self.assertLess(lay.rect.height(), 30)


class UiPatternTests(unittest.TestCase):
    def test_time_ago(self):
        self.assertEqual(translate_ui_pattern("35m ago"), "35 минут назад")
        self.assertEqual(translate_ui_pattern("21h ago"), "21 час назад")
        self.assertEqual(translate_ui_pattern("3mo ago"), "3 месяца назад")
        self.assertEqual(translate_ui_pattern("12d ago"), "12 дней назад")

    def test_counters(self):
        self.assertEqual(translate_ui_pattern("471 upvotes"), "471 голос")
        self.assertEqual(translate_ui_pattern("43 comments"), "43 комментария")
        self.assertEqual(translate_ui_pattern("1,547,917 members"), "1,547,917 участников")
        self.assertEqual(translate_ui_pattern("2 replies"), "2 ответа")
        self.assertIsNone(translate_ui_pattern("Fuck you EA"))


if __name__ == "__main__":
    unittest.main()
