import sys
import unittest
from pathlib import Path

from PyQt6.QtCore import QRect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.models import RawWordBox
from ghosttranslate.ocr.layout import (
    drop_words_over_russian,
    is_clean_russian_word,
    looks_like_garbled_latin,
    merge_ocr_boxes_into_paragraphs,
    place_plaque_around,
    russian_reading_wins,
)


def box(x, y, w, h, text, bullet=False):
    return RawWordBox(x1=x, y1=y, x2=x + w, y2=y + h, text=text, score=0.95, split_from_bullet=bullet)


class LayoutTests(unittest.TestCase):
    def test_jittered_line_stays_together_and_menu_buttons_stay_apart(self):
        words = [
            box(42, 70, 68, 21, "PLAY"),
            box(242, 70, 87, 21, "EVENT"),
            box(462, 70, 100, 21, "BATTLE"),
            box(572, 70, 65, 21, "PASS"),
            box(41, 170, 71, 28, "Open"),
            box(122, 169, 43, 22, "the"),
            box(175, 169, 133, 29, "inventory"),
        ]
        texts = [item.text for item in merge_ocr_boxes_into_paragraphs(words)]
        self.assertIn("Open the inventory", texts)
        self.assertIn("PLAY", texts)
        self.assertIn("EVENT", texts)
        self.assertIn("BATTLE PASS", texts)
        self.assertNotIn("Open", texts)
        self.assertNotIn("the inventory", texts)

    def test_bullet_split_does_not_glue_menu_items(self):
        texts = sorted(item.text for item in merge_ocr_boxes_into_paragraphs([box(10, 10, 220, 24, "PLAY•EVENT")]))
        self.assertEqual(texts, ["EVENT", "PLAY"])

    def test_wider_plaque_keeps_the_source_center(self):
        anchor = QRect(100, 80, 40, 20)
        placed = place_plaque_around(anchor, 80, 24)
        self.assertEqual(placed.center(), anchor.center())
        self.assertEqual(placed.width(), 80)
        self.assertLess(placed.left(), anchor.left())


# Оценки SentencePiece модели EN-RU для слов с реального экрана (лог-вероятность на букву).
WORD_SCORES = {
    "name": -2.25, "пате": -4.66,
    "errors": -1.95, "еггог": -6.0,
    "moxho": -5.87, "можно": -1.62,
    "ece": -6.11, "все": -2.42,
    "plan": -2.38, "тап": -6.16,
    "oner": -3.32, "олег": -4.29,
}


class RussianFilterTests(unittest.TestCase):
    def test_reading_with_digits_or_latin_is_not_russian(self):
        for text in ("уат1", "Јдтоге", "еггог5", "Start"):
            self.assertFalse(is_clean_russian_word(text), text)
        self.assertTrue(is_clean_russian_word("«правки»,"))

    def test_typical_english_ocr_garbage(self):
        for text in ("6ar'-1", "cnpaBhTb", "nanKa", "HyxeH,"):
            self.assertTrue(looks_like_garbled_latin(text), text)
        for text in ("Settings", "IDE", "on-demand", "README"):
            self.assertFalse(looks_like_garbled_latin(text), text)

    def test_english_word_read_as_cyrillic_stays(self):
        self.assertFalse(russian_reading_wins("name", "пате", WORD_SCORES.get))
        self.assertFalse(russian_reading_wins("Plan", "Тап", WORD_SCORES.get))

    def test_russian_word_read_as_latin_goes(self):
        self.assertTrue(russian_reading_wins("MOXHO", "можно", WORD_SCORES.get))
        self.assertTrue(russian_reading_wins("ece", "все", WORD_SCORES.get))
        self.assertTrue(russian_reading_wins("nanKa", "Папка", None))

    def test_mostly_russian_line_takes_its_short_leftovers(self):
        english = [box(10, 10, 60, 20, "MOXHO"), box(80, 10, 30, 20, "ece"), box(120, 10, 40, 20, "Oner"),
                   box(10, 60, 50, 20, "name"), box(70, 60, 60, 20, "errors")]
        russian_lines = [
            [box(9, 9, 62, 22, "можно"), box(79, 9, 32, 22, "все"), box(119, 9, 42, 22, "Олег")],
            [box(9, 59, 52, 22, "пате"), box(69, 59, 62, 22, "еггог")],
        ]
        kept, dropped = drop_words_over_russian(english, russian_lines, WORD_SCORES.get)
        self.assertEqual([w.text for w in kept], ["name", "errors"])
        self.assertEqual(dropped, 3)

    def test_without_russian_ocr_nothing_is_dropped(self):
        english = [box(10, 10, 60, 20, "Open")]
        self.assertEqual(drop_words_over_russian(english, []), (english, 0))


if __name__ == "__main__":
    unittest.main()
