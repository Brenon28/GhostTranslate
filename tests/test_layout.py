import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.models import RawWordBox
from ghosttranslate.ocr.layout import (
    _strip_chat_line_header,
    drop_words_over_russian,
    estimate_font_px,
    is_clean_russian_word,
    is_valid_english_box,
    looks_like_garbled_latin,
    merge_ocr_boxes_into_paragraphs,
    normalize_ocr_confusables,
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

    def test_chat_messages_split_on_timestamp_and_keep_their_wrap(self):
        # Чат WoW: шаг строк 17 px; шапка (время, тег, ник) отрезается, а перенос строки сохраняется.
        words = ocr_line(0, 151, [(58, 40, 13, "07:39"), (102, 25, 13, "[R]"), (131, 60, 13, "[Fist]:"),
                                  (195, 50, 13, "seems"), (250, 30, 13, "like")])
        words += ocr_line(1, 168, [(58, 40, 13, "07:39"), (102, 25, 13, "[R]"), (131, 60, 13, "[Shuurly]:"),
                                   (195, 30, 13, "still"), (230, 30, 13, "too"), (265, 30, 13, "less")])
        words += ocr_line(2, 185, [(72, 40, 13, "about"), (117, 50, 13, "feared"), (172, 40, 13, "peeps")])
        words += ocr_line(3, 202, [(58, 40, 13, "[07:40]"), (102, 50, 13, "Sorry"), (157, 40, 13, "guys")])
        paras = sorted(merge_ocr_boxes_into_paragraphs(words), key=lambda p: p.y1)
        texts = [p.text for p in paras]
        self.assertEqual(texts, [
            "seems like",
            "still too less about feared peeps",
            "Sorry guys",
        ])
        self.assertEqual(paras[0].x1, 195)
        self.assertEqual(paras[2].x1, 102)

    def test_strip_chat_line_header_variants(self):
        # 1. [07:39] [Squad] Player_One: need ammo at B
        line1 = ocr_line(
            0, 100,
            [(10, 45, 13, "[07:39]"), (60, 50, 13, "[Squad]"), (115, 75, 13, "Player_One:"),
             (195, 35, 13, "need"), (235, 40, 13, "ammo"), (280, 20, 13, "at"), (305, 15, 13, "B")],
        )
        res1 = _strip_chat_line_header(line1)
        self.assertEqual([w.text for w in res1], ["need", "ammo", "at", "B"])
        self.assertEqual(res1[0].x1, 195)

        # 2. 07:39 DarkKnight: hello
        line2 = ocr_line(0, 120, [(10, 40, 13, "07:39"), (55, 80, 13, "DarkKnight:"), (140, 40, 13, "hello")])
        res2 = _strip_chat_line_header(line2)
        self.assertEqual([w.text for w in res2], ["hello"])
        self.assertEqual(res2[0].x1, 140)

        # 3. [All] Sniper_X: gg wp
        line3 = ocr_line(
            0, 140,
            [(10, 35, 13, "[All]"), (50, 65, 13, "Sniper_X:"), (120, 20, 13, "gg"), (145, 25, 13, "wp")],
        )
        res3 = _strip_chat_line_header(line3)
        self.assertEqual([w.text for w in res3], ["gg", "wp"])
        self.assertEqual(res3[0].x1, 120)

        # 4. Склеенное двоеточие без пробела: Player1:hello world
        line4 = ocr_line(0, 160, [(100, 130, 13, "Player1:hello"), (236, 45, 13, "world")])
        res4 = _strip_chat_line_header(line4)
        self.assertEqual([w.text for w in res4], ["hello", "world"])
        self.assertGreater(res4[0].x1, 160)
        self.assertLess(res4[0].x1, 200)

        # Подпись интерфейса не ник: «Warning: low health» остаётся целиком.
        line5 = ocr_line(0, 180, [(40, 70, 13, "Warning:"), (120, 30, 13, "low"), (155, 50, 13, "health")])
        res5 = _strip_chat_line_header(line5)
        self.assertEqual([w.text for w in res5], ["Warning:", "low", "health"])

        # Ответ в Discord с обращением @Nick в начале строки: @Nick срезается, остаётся сообщение.
        line6 = ocr_line(0, 200, [(40, 45, 13, "@Nick"), (92, 40, 13, "hello"), (138, 45, 13, "there")])
        res6 = _strip_chat_line_header(line6)
        self.assertEqual([w.text for w in res6], ["hello", "there"])
        self.assertEqual(res6[0].x1, 92)
        paras6 = merge_ocr_boxes_into_paragraphs(line6)
        self.assertEqual([p.text for p in paras6], ["hello there"])

    def test_overlapping_rapidocr_lines_still_form_a_paragraph(self):
        # Рамки RapidOCR у текста с обводкой: 22 px при шаге строк 16 px.
        words = [box(57, 81, 60, 22, "still"), box(122, 81, 40, 22, "still"), box(167, 81, 40, 22, "less"),
                 box(72, 97, 50, 22, "about"), box(127, 97, 55, 22, "feared")]
        words[1].text = "too"
        texts = [p.text for p in merge_ocr_boxes_into_paragraphs(words)]
        self.assertEqual(texts, ["still too less about feared"])

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

    def test_discord_chat_headers_are_filtered_out(self):
        for header in (
            "17 [d1s] k1r1to 20:51",
            "Serega [D1S] 22:02",
            "@Dr. Mysterion (Loki Enthusiast)",
            "Mee6 BOT",
            "Helper ГОТ",
        ):
            self.assertFalse(is_valid_english_box(header), header)

    def test_number_with_unit_is_not_ocr_garbage(self):
        for text in ("3mo", "24h", "1.2k", "x1", "x10"):
            self.assertFalse(looks_like_garbled_latin(text), text)


# Оценки SentencePiece модели EN-RU для слов с реального экрана (лог-вероятность на букву).
WORD_SCORES = {
    "name": -2.25, "пате": -4.66,
    "errors": -1.95, "еггог": -6.0,
    "moxho": -5.87, "можно": -1.62,
    "ece": -6.11, "все": -2.42,
    "plan": -2.38, "тап": -6.16,
    "oner": -3.32, "олег": -4.29,
    "kpviyvit": -6.0, "кричит": -2.5,
    "mto": -5.5, "что": -1.8,
}


class RussianFilterTests(unittest.TestCase):
    def test_reading_with_digits_or_latin_is_not_russian(self):
        for text in ("уат1", "Јдтоге", "еггог5", "Start"):
            self.assertFalse(is_clean_russian_word(text), text)
        self.assertTrue(is_clean_russian_word("«правки»,"))

    def test_typical_english_ocr_garbage(self):
        for text in ("6ar'-1", "cnpaBhTb", "nanKa", "HyxeH,"):
            self.assertTrue(looks_like_garbled_latin(text), text)
        for text in ("Settings", "IDE", "on-demand", "README", "Can't", "I'll", "don't", "deadpool's", "x1"):
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

    def test_timestamp_does_not_outvote_russian_chat_line(self):
        # Строка крика NPC в чате WoW: «07:39 Зул'джан кричит: Вы не остановите то, что грядет.»
        en_ru = [("07:39", "07:39"), ("3yn'AMaH", "Зул'джан"), ("KPVIYVIT:", "кричит:"), ("Bbl", "Вы"),
                 ("He", "не"), ("OCTaHOBMTe", "остановите"), ("TO,", "то,"), ("MTO", "что"), ("rpqaeT.", "грядет.")]
        english, russian = [], []
        for i, (en, ru) in enumerate(en_ru):
            english.append(box(10 + 60 * i, 10, 50, 14, en))
            russian.append(box(10 + 60 * i, 10, 50, 14, ru))
        badge = box(10, 60, 10, 14, "2")
        kept, _ = drop_words_over_russian(english + [badge], [russian, [box(10, 60, 10, 14, "2")]], WORD_SCORES.get)
        self.assertEqual([w.text for w in kept], ["2"])

    def test_english_message_after_russian_nickname_stays(self):
        # Русский OCR Windows читает латиницу латиницей: одинаковое прочтение — голос за английский.
        en_ru = [("07:39", "07:39"), ("[Xo3eby", "[Хозевул-ВечнаяПесня]"), ("-BeyHaa", "[Хозевул-ВечнаяПесня]"),
                 ("someone", "someone"), ("didn't", "didn't"), ("know", "know"), ("how", "how")]
        english, russian = [], []
        for i, (en, ru) in enumerate(en_ru):
            english.append(box(10 + 60 * i, 10, 50, 14, en))
            russian.append(box(10 + 60 * i, 10, 50, 14, ru))
        kept, _ = drop_words_over_russian(english, [russian], WORD_SCORES.get)
        self.assertEqual([w.text for w in kept], ["07:39", "someone", "didn't", "know", "how"])

    def test_without_russian_ocr_nothing_is_dropped(self):
        english = [box(10, 10, 60, 20, "Open")]
        self.assertEqual(drop_words_over_russian(english, []), (english, 0))


if __name__ == "__main__":
    unittest.main()
