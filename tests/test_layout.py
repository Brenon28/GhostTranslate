import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.models import RawWordBox
from ghosttranslate.ocr.layout import (
    drop_words_over_russian,
    estimate_font_px,
    is_clean_russian_word,
    is_valid_english_box,
    looks_like_garbled_latin,
    merge_ocr_boxes_into_paragraphs,
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


def ocr_line(line_id, y, items):
    """Слова одной строки WinOCR: (x, ширина, высота, текст); низ рамок разный, как у реального OCR."""
    return [
        RawWordBox(x1=x, y1=y + (13 - h if h < 13 else 0), x2=x + w, y2=y + 13 if h <= 13 else y + h,
                   text=text, score=0.95, line_id=line_id)
        for x, w, h, text in items
    ]


class OcrLineTests(unittest.TestCase):
    def test_short_words_do_not_break_a_web_line(self):
        # С реальной страницы Reddit: у «as» рамка 7 px, у «Bots,» 13 px, пробел 4-6 px.
        words = ocr_line(0, 923, [(1039, 29, 13, "Bots,"), (1073, 13, 7, "as"), (1090, 35, 10, "actual"),
                                  (1131, 41, 10, "human"), (1177, 42, 13, "players")])
        texts = [item.text for item in merge_ocr_boxes_into_paragraphs(words)]
        self.assertEqual(texts, ["Bots, as actual human players"])

    def test_wide_gap_inside_ocr_line_splits_menu_items(self):
        words = ocr_line(0, 70, [(42, 68, 13, "PLAY"), (242, 87, 13, "EVENT"), (462, 70, 13, "BATTLE"),
                                 (538, 50, 13, "PASS")])
        texts = sorted(item.text for item in merge_ocr_boxes_into_paragraphs(words))
        self.assertEqual(texts, ["BATTLE PASS", "EVENT", "PLAY"])

    def test_standalone_separator_splits_items(self):
        words = ocr_line(0, 70, [(10, 50, 13, "STORE"), (64, 3, 13, "|"), (71, 60, 13, "PROFILE")])
        texts = sorted(item.text for item in merge_ocr_boxes_into_paragraphs(words))
        self.assertEqual(texts, ["PROFILE", "STORE"])

    def test_slash_inside_word_is_not_a_menu_separator(self):
        words = ocr_line(0, 128, [(967, 60, 20, "Wake"), (1031, 30, 20, "up,"), (1065, 99, 20, "EA/DICE")])
        texts = [item.text for item in merge_ocr_boxes_into_paragraphs(words)]
        self.assertEqual(texts, ["Wake up, EA/DICE"])

    def test_paragraph_lines_merge_and_keep_font_size(self):
        words = ocr_line(0, 196, [(967, 2, 10, "I"), (975, 25, 10, "like"), (1004, 72, 13, "playing")])
        words += ocr_line(1, 216, [(967, 50, 10, "addressed"), (1021, 15, 13, "by"), (1040, 33, 10, "DICE")])
        paragraphs = merge_ocr_boxes_into_paragraphs(words)
        self.assertEqual(len(paragraphs), 1)
        self.assertEqual(paragraphs[0].lines_merged, 2)
        self.assertAlmostEqual(paragraphs[0].font_px, 14, delta=1.5)

    def test_justified_line_stays_together(self):
        # PDF с выравниванием по ширине: все пробелы строки растянуты до 22 px при кегле 18.
        words = ocr_line(0, 950, [(552, 27, 13, "with"), (601, 25, 13, "the"), (648, 110, 13, "organizational"),
                                  (780, 96, 13, "arrangements,"), (898, 25, 13, "the")])
        texts = [item.text for item in merge_ocr_boxes_into_paragraphs(words)]
        self.assertEqual(texts, ["with the organizational arrangements, the"])

    def test_contents_rows_stay_separate_items(self):
        # Оглавление PDF: WinOCR отдаёт номер и название пункта разными строками через обычный пробел.
        words = []
        for row, (label, title) in enumerate([("15:", "Advance Receipts"), ("16:", "Borrowings"),
                                              ("17:", "Provisions")]):
            y = 762 + 18 * row
            words += ocr_line(2 * row, y, [(189, 32, 13, "Note"), (226, 20, 13, label)])
            x = 252
            items = []
            for word in title.split():
                items.append((x, 9 * len(word), 13, word))
                x += 9 * len(word) + 5
            words += ocr_line(2 * row + 1, y, items)
        texts = sorted(item.text for item in merge_ocr_boxes_into_paragraphs(words))
        self.assertEqual(texts, ["Note 15: Advance Receipts", "Note 16: Borrowings", "Note 17: Provisions"])

    def test_dash_after_item_label_is_not_a_menu_separator(self):
        words = ocr_line(0, 420, [(110, 94, 13, "STATEMENT"), (210, 7, 13, "II"), (222, 10, 3, "—"),
                                  (236, 71, 13, "Statement"), (312, 13, 13, "of"), (330, 61, 13, "Financial"),
                                  (398, 88, 13, "Performance")])
        texts = [item.text for item in merge_ocr_boxes_into_paragraphs(words)]
        self.assertEqual(texts, ["STATEMENT II Statement of Financial Performance"])

    def test_caps_heading_does_not_continue_a_line(self):
        words = ocr_line(0, 472, [(110, 109, 13, "STATEMENT"), (225, 30, 13, "V:"), (260, 72, 13, "Statement"),
                                  (337, 15, 13, "of"), (357, 90, 13, "Comparison")])
        words += ocr_line(1, 490, [(110, 60, 13, "NOTES"), (175, 25, 13, "TO"), (205, 35, 13, "THE"),
                                   (245, 90, 13, "FINANCIAL")])
        texts = sorted(item.text for item in merge_ocr_boxes_into_paragraphs(words))
        self.assertEqual(texts, ["NOTES TO THE FINANCIAL", "STATEMENT V: Statement of Comparison"])

    def test_sentence_starting_with_pronoun_i_continues_the_paragraph(self):
        words = ocr_line(0, 196, [(967, 40, 13, "When"), (1012, 60, 10, "playing"), (1077, 25, 13, "the")])
        words += ocr_line(1, 216, [(967, 38, 13, "Then"), (1010, 4, 13, "I"), (1019, 36, 13, "went")])
        paragraphs = merge_ocr_boxes_into_paragraphs(words)
        self.assertEqual([p.text for p in paragraphs], ["When playing the Then I went"])


class FontEstimateTests(unittest.TestCase):
    def test_line_without_tall_letters_is_not_smaller(self):
        # «- bot lobbies» и «game hangs» набраны одним кеглем 14 px, хотя рамки у них 10 и 13 px.
        lobbies = ocr_line(0, 0, [(0, 5, 1, "-"), (10, 20, 10, "bot"), (35, 43, 10, "lobbies")])
        hangs = ocr_line(1, 0, [(0, 35, 10, "game"), (40, 37, 13, "hangs")])
        self.assertAlmostEqual(estimate_font_px(lobbies), 14, delta=1)
        self.assertAlmostEqual(estimate_font_px(hangs), 14, delta=1)

    def test_icon_read_as_letter_is_ignored(self):
        award = ocr_line(0, 0, [(0, 12, 18, "a"), (20, 35, 10, "Award")])
        self.assertAlmostEqual(estimate_font_px(award), 14, delta=1)


class EnglishBoxFilterTests(unittest.TestCase):
    def test_paragraph_ending_with_colon_is_kept(self):
        self.assertTrue(is_valid_english_box("issues do not get addressed by DICE or even acknowledged:"))
        self.assertFalse(is_valid_english_box("Ресурс: Дерево"))

    def test_nicknames_and_links_are_not_translated(self):
        for text in ("r/Battlefield6", "u/VOLBANKER", "_Steven_Seagal_", "T4Abyss", "reddit.com/r/test"):
            self.assertFalse(is_valid_english_box(text), text)
        self.assertTrue(is_valid_english_box("Search in r/Battlefield6"))

    def test_number_with_unit_is_not_ocr_garbage(self):
        for text in ("3mo", "24h", "1.2k"):
            self.assertFalse(looks_like_garbled_latin(text), text)


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
