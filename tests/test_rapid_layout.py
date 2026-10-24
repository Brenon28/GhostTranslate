import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.ocr.layout import merge_ocr_boxes_into_paragraphs
from ghosttranslate.ocr.rapid_layout import rapidocr_items_to_word_boxes, rapidocr_to_word_boxes


def _quad(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _char_quads(text, x1, y1, x2, y2):
    chars, quads = [], []
    span = max(1, len(text))
    width = x2 - x1
    for index, char in enumerate(text):
        cx1 = x1 + width * index / span
        cx2 = x1 + width * (index + 1) / span
        chars.append(char)
        quads.append(_quad(cx1, y1, cx2, y2))
    return chars, quads


def ocr_line(words, score=0.95):
    """Слова одной строки RapidOCR: (текст, x1, y1, x2, y2) — рамки символов, не глифов."""
    chars, quads, parts = [], [], []
    for index, (text, x1, y1, x2, y2) in enumerate(words):
        if index:
            prev = words[index - 1]
            chars.append(" ")
            quads.append(_quad(prev[3], y1, x1, y2))
            parts.append(" ")
        word_chars, word_quads = _char_quads(text, x1, y1, x2, y2)
        chars.extend(word_chars)
        quads.extend(word_quads)
        parts.append(text)
    text = "".join(parts)
    xs1 = [word[1] for word in words]
    ys1 = [word[2] for word in words]
    xs2 = [word[3] for word in words]
    ys2 = [word[4] for word in words]
    # Рамка детектора выше рамок символов: так unclip раздувает строку.
    line = _quad(min(xs1) - 4, min(ys1) - 8, max(xs2) + 4, max(ys2) + 8)
    return [line, text, score, quads, chars, [score] * len(chars)]


class RapidWordTests(unittest.TestCase):
    def test_characters_become_words_with_line_ids(self):
        items = [
            ocr_line([("open", 10, 10, 40, 23), ("the", 46, 10, 70, 23)]),
            ocr_line([("door", 10, 30, 48, 43)], score=0.8),
        ]
        words = rapidocr_items_to_word_boxes(items, inv_scale=2)
        self.assertEqual([(word.text, word.line_id) for word in words], [
            ("open", 0), ("the", 0), ("door", 1),
        ])
        self.assertEqual(words[0].score, 0.95)
        self.assertEqual(words[2].score, 0.8)
        self.assertEqual(words[0].x1, 20)
        self.assertEqual(words[0].y1, 20)
        self.assertEqual(words[1].x1, 92)
        self.assertLess(words[0].x2, words[1].x1)

    def test_missing_space_splits_on_character_gap(self):
        def line(gap):
            chars = list("externalfactors")
            quads = []
            cursor = 10
            for char in chars:
                if char == "f":
                    cursor += gap
                quads.append(_quad(cursor, 10, cursor + 8, 24))
                cursor += 8
            text = "".join(chars)
            return [_quad(6, 2, cursor + 4, 32), text, 0.9, quads, chars, [0.9] * len(chars)]

        words = rapidocr_items_to_word_boxes([line(12)])
        self.assertEqual([word.text for word in words], ["external", "factors"])
        paragraphs = merge_ocr_boxes_into_paragraphs(words)
        self.assertEqual([item.text for item in paragraphs], ["external factors"])
        self.assertEqual(
            [word.text for word in rapidocr_items_to_word_boxes([line(4)])],
            ["externalfactors"],
        )

    def test_wide_gap_splits_menu_items(self):
        words = rapidocr_items_to_word_boxes([
            ocr_line([("PLAY", 10, 20, 50, 34), ("EVENT", 140, 20, 200, 34)]),
        ])
        texts = sorted(item.text for item in merge_ocr_boxes_into_paragraphs(words))
        self.assertEqual(texts, ["EVENT", "PLAY"])

    def test_phantom_last_character_beyond_line_is_dropped(self):
        # Реальный кадр Reddit: строка до x=1118, «.» после «matter» тянется до 1267,
        # в правую колонку, и плашка накрывала её текст.
        item = ocr_line([("No", 1040, 10, 1060, 24), ("matter", 1070, 10, 1114, 24)])
        item[1] += "."
        item[3].append(_quad(item[0][1][0], 2, 1267, 32))
        item[4].append(".")
        words = rapidocr_items_to_word_boxes([item])
        self.assertEqual([word.text for word in words], ["No", "matter"])
        self.assertLessEqual(max(word.x2 for word in words), item[0][1][0])

    def test_last_character_is_clipped_to_line(self):
        item = ocr_line([("row", 10, 10, 40, 24)])
        item[3][-1] = _quad(30, 10, 50, 24)
        words = rapidocr_items_to_word_boxes([item])
        self.assertEqual([word.text for word in words], ["row"])
        self.assertEqual(words[0].x2, 44)

    def test_missing_character_boxes_keep_the_line(self):
        item = [_quad(5, 6, 80, 30), "  Advance Receipts  ", 0.7]
        words = rapidocr_items_to_word_boxes([item])
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0].text, "Advance Receipts")
        self.assertEqual(words[0].line_id, 0)
        self.assertEqual((words[0].x1, words[0].y1, words[0].x2, words[0].y2), (5, 6, 80, 30))

    def test_inflated_lines_merge_into_paragraph_after_ink_trim(self):
        # Рамки строк перекрываются на 12 px; после поджима до чернил строки стоят друг под другом.
        image = np.full((80, 200, 3), 255, np.uint8)
        image[18:31, 10:70] = 0
        image[18:31, 80:130] = 0
        image[40:53, 10:60] = 0
        image[40:53, 70:130] = 0
        items = [
            ocr_line([("playing", 10, 0, 70, 40), ("games", 80, 0, 130, 40)]),
            ocr_line([("every", 10, 28, 60, 68), ("night", 70, 28, 130, 68)]),
        ]
        raw = rapidocr_items_to_word_boxes(items)
        self.assertLess(raw[2].y1 - raw[0].y2, -4)

        words = rapidocr_to_word_boxes(items, image)
        self.assertEqual((words[0].y1, words[0].y2), (18, 31))
        self.assertLessEqual(max(word.y2 for word in words if word.line_id == 0),
                             min(word.y1 for word in words if word.line_id == 1))
        paragraphs = merge_ocr_boxes_into_paragraphs(words)
        self.assertEqual(len(paragraphs), 1)
        self.assertEqual(paragraphs[0].lines_merged, 2)
        self.assertEqual(paragraphs[0].text, "playing games every night")
        self.assertAlmostEqual(paragraphs[0].font_px, 14, delta=2)

    def test_line_without_character_boxes_merges_after_ink_trim(self):
        image = np.full((80, 160, 3), 255, np.uint8)
        image[18:31, 10:140] = 0
        image[40:53, 10:140] = 0
        items = [
            [_quad(10, 0, 140, 40), "playing games", 0.9],
            [_quad(10, 28, 140, 68), "every night", 0.9],
        ]
        paragraphs = merge_ocr_boxes_into_paragraphs(rapidocr_to_word_boxes(items, image))
        self.assertEqual(len(paragraphs), 1)
        self.assertEqual(paragraphs[0].lines_merged, 2)
        self.assertAlmostEqual(paragraphs[0].font_px, 14, delta=2)


if __name__ == "__main__":
    unittest.main()
