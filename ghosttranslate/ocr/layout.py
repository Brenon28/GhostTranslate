"""Склейка слов OCR в строки, абзацы и пункты меню."""

import re
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QRect

from ..config import MERGE_HORIZ_FACTOR, MERGE_VERT_FACTOR
from ..models import RawWordBox


LATIN_REGEX = re.compile(r"[a-zA-Z]{2,}")
BULLET_SPLIT_REGEX = re.compile(r"\s*[•·|/»—]+\s*")
HAS_BULLET_REGEX = re.compile(r"[•·|/»—]")


def is_valid_english_box(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return False
    payload = text.split(":", 1)[-1].strip() if ":" in text else text.strip()
    if len(payload) < 2:
        return False

    cyr = len(re.findall(r"[а-яА-ЯёЁ]", payload))
    lat = len(re.findall(r"[a-zA-Z]", payload))

    if cyr > 0 and (lat == 0 or (cyr / float(cyr + lat)) >= 0.35):
        return False

    return lat >= 2 and bool(LATIN_REGEX.search(payload))


# ==============================================================================
# РУССКИЙ ТЕКСТ НА ЭКРАНЕ: ДВА ПРОЧТЕНИЯ ОДНОГО СЛОВА
# ==============================================================================
# Английский OCR Windows читает кириллицу латиницей («Папка» -> «nanKa»), а русский
# читает латиницу кириллицей («name» -> «пате»). По одному прочтению не понять, что на экране,
# поэтому слово сравнивается в обоих.
WORD_EDGE_PUNCT = "'\"«»“”„.,:;!?()[]{}•·_-—…/\\|*"
RUSSIAN_WORD_REGEX = re.compile(r"[а-яё]+(?:-[а-яё]+)*")
CASE_FLIP_REGEX = re.compile(r"[a-z][A-Z]")
# Насколько русское прочтение должно быть правдоподобнее английского (лог-вероятность на букву).
RUSSIAN_SCORE_MARGIN = 0.3
RUSSIAN_LINE_SHARE = 0.5

ScoreFn = Callable[[str], Optional[float]]


def _word_core(text: str) -> str:
    return text.strip(WORD_EDGE_PUNCT)


def is_clean_russian_word(text: str) -> bool:
    """Только русские буквы: «уат1» или «Јдтоге» — это английское слово, прочитанное русским OCR."""
    core = _word_core(text).lower()
    return bool(core) and RUSSIAN_WORD_REGEX.fullmatch(core) is not None


def looks_like_garbled_latin(text: str) -> bool:
    """Так английский OCR пишет русские слова: «6ar'-1», «cnpaBhTb», «nanKa»."""
    core = _word_core(text)
    if not core or not any(ch.isalpha() for ch in core):
        return False
    if any(ch.isdigit() for ch in core) or any(ch in "'\"`" for ch in core):
        return True
    return CASE_FLIP_REGEX.search(core) is not None


def russian_reading_wins(en_text: str, ru_text: str, score: Optional[ScoreFn]) -> bool:
    if not is_clean_russian_word(ru_text):
        return False
    if looks_like_garbled_latin(en_text):
        return True
    ru_core = _word_core(ru_text).lower()
    en_core = _word_core(en_text).lower()
    if score is None or len(ru_core) < 3 or not en_core:
        return False
    ru_score, en_score = score(ru_core), score(en_core)
    if ru_score is None or en_score is None:
        return False
    return ru_score > en_score + RUSSIAN_SCORE_MARGIN


def _overlapping_word(word: RawWordBox, lines: List[List[RawWordBox]], min_overlap: float):
    word_area = max(1, (word.x2 - word.x1) * (word.y2 - word.y1))
    for line_idx, line in enumerate(lines):
        for other in line:
            iw = min(word.x2, other.x2) - max(word.x1, other.x1)
            ih = min(word.y2, other.y2) - max(word.y1, other.y1)
            if iw > 0 and ih > 0 and iw * ih >= min_overlap * word_area:
                return line_idx, other
    return None


def drop_words_over_russian(
    words: List[RawWordBox],
    ru_lines: List[List[RawWordBox]],
    score: Optional[ScoreFn] = None,
    min_overlap: float = 0.5,
) -> Tuple[List[RawWordBox], int]:
    """Убирает слова английского OCR, которые на самом деле русские.

    ru_lines — слова русского OCR по строкам. score — правдоподобие слова для модели
    перевода; без него работают только явные признаки мусора. Если в строке русских слов
    большинство, уходят и её короткие остатки вроде «xe» или «no».
    """
    if not ru_lines:
        return words, 0
    decisions = []
    line_votes: Dict[int, Tuple[int, int]] = {}
    for word in words:
        match = _overlapping_word(word, ru_lines, min_overlap)
        if match is None:
            decisions.append((word, None, False))
            continue
        line_idx, ru_word = match
        is_russian = russian_reading_wins(word.text, ru_word.text, score)
        decisions.append((word, line_idx, is_russian))
        russian, total = line_votes.get(line_idx, (0, 0))
        line_votes[line_idx] = (russian + int(is_russian), total + 1)

    kept: List[RawWordBox] = []
    dropped = 0
    for word, line_idx, is_russian in decisions:
        if line_idx is not None and not is_russian:
            russian, total = line_votes[line_idx]
            is_russian = russian >= 2 and russian >= RUSSIAN_LINE_SHARE * total
        if is_russian:
            dropped += 1
        else:
            kept.append(word)
    return kept, dropped


# ==============================================================================
# ПУНКТ 1.1 И 1.2 ТЗ v3.0: РАЗБИЕНИЕ БУЛЛИТОВ (_split_bullet_tokens) И EXACT MENU PLACE
# ==============================================================================
def _split_bullet_tokens(raw_word_boxes: List[RawWordBox]) -> List[RawWordBox]:
    """
    Пункт 1.1 ТЗ v3.0: Если внутри распознанного слова есть символы разделителей меню
    (•, ·, |, /, », —), например 'PLAY•EVENT' или 'STORE | PROFILE', разрезает строку
    на чистые слова и пропорционально длине слов делит горизонтальный QRect на независимые боксы,
    оставляя зазор на месте буллита и помечая split_from_bullet=True.
    """
    if not raw_word_boxes:
        return []

    split_result: List[RawWordBox] = []
    for box in raw_word_boxes:
        raw_txt = (box.text or "").strip()
        if not raw_txt:
            continue
        cleaned = raw_txt.strip("•·|/»— ").strip()
        if not cleaned:
            continue

        if not HAS_BULLET_REGEX.search(cleaned):
            box.text = cleaned
            split_result.append(box)
            continue

        parts = [p.strip() for p in BULLET_SPLIT_REGEX.split(cleaned) if p.strip()]
        if len(parts) <= 1:
            box.text = parts[0] if parts else cleaned
            split_result.append(box)
            continue

        box_h = max(10, int(box.height))
        total_w = max(len(parts) * 20, box.width)
        bullet_gap_px = max(14, int(round(box_h * 0.85)))
        usable_w = max(len(parts) * 14, total_w - bullet_gap_px * (len(parts) - 1))
        total_chars = max(1, sum(len(p) for p in parts))

        cursor_x = box.x1
        for idx, part in enumerate(parts):
            if idx == len(parts) - 1:
                part_w = max(14, box.x2 - cursor_x)
            else:
                part_w = max(14, int(round((len(part) / float(total_chars)) * usable_w)))
            x1 = cursor_x
            x2 = x1 + part_w
            cursor_x = x2 + bullet_gap_px
            split_result.append(
                RawWordBox(
                    x1=x1,
                    y1=box.y1,
                    x2=x2,
                    y2=box.y2,
                    text=part,
                    score=box.score,
                    lines_merged=1,
                    split_from_bullet=(idx > 0),
                )
            )
    return split_result


def _boxes_share_text_line(a: RawWordBox, b: RawWordBox) -> bool:
    overlap_y = max(0, min(a.y2, b.y2) - max(a.y1, b.y1))
    h_avg = (a.height + b.height) / 2.0
    if h_avg <= 0:
        return False
    height_ratio = max(a.height, b.height) / max(1.0, min(a.height, b.height))
    return overlap_y > 0.50 * h_avg and height_ratio <= 1.40


def _cluster_words_into_lines(words: List[RawWordBox]) -> List[List[RawWordBox]]:
    """Склеивает слова одной строки независимо от порядка, в котором их вернул OCR.

    Раньше слово присоединялось только справа от уже собранной строки. Если у левого
    слова y был на пиксель больше, оно обрабатывалось позже и оставалось отдельной плашкой.
    """
    usable = [word for word in words if word.text and word.text.strip()]
    usable.sort(key=lambda word: ((word.y1 + word.y2) / 2.0, word.x1))
    bands: List[List[RawWordBox]] = []
    for word in usable:
        placed = False
        for band in reversed(bands):
            if any(_boxes_share_text_line(word, other) for other in band):
                band.append(word)
                placed = True
                break
        if not placed:
            bands.append([word])

    groups: List[List[RawWordBox]] = []
    for band in bands:
        band.sort(key=lambda word: word.x1)
        current: List[RawWordBox] = [band[0]]
        for word in band[1:]:
            prev = current[-1]
            gap = word.x1 - prev.x2
            h_avg = (prev.height + word.height) / 2.0
            blocked = prev.split_from_bullet or word.split_from_bullet
            if (not blocked) and -6 <= gap <= MERGE_HORIZ_FACTOR * h_avg:
                current.append(word)
            else:
                groups.append(current)
                current = [word]
        groups.append(current)
    return groups


def place_plaque_around(anchor: QRect, width: int, height: int) -> QRect:
    """Плашка шире перевода остаётся по центру исходного слова, а не уезжает вправо."""
    rect = QRect(0, 0, max(1, int(width)), max(1, int(height)))
    rect.moveCenter(anchor.center())
    return rect


def merge_ocr_boxes_into_paragraphs(raw_boxes: List[RawWordBox]) -> List[RawWordBox]:
    """
    Пункт 1.2 ТЗ v3.0 (Режим Exact Place для игровых меню и карточек):
    1. Сначала вызывает _split_bullet_tokens(raw_boxes), чтобы разделить 'PLAY•EVENT'.
    2. По горизонтали: склеивает слова ТОЛЬКО если gap_x <= 0.55 * h_avg (обычный узкий пробел
       внутри одного составного термина вроде 'BATTLE PASS') и между ними не было буллита.
       Отдельные кнопки горизонтального меню ('PLAY', 'EVENT', 'LOADOUTS', 'BATTLE PASS',
       'CHALLENGES', 'STORE', 'PROFILE') НИКОГДА не склеиваются в одну длинную полосу!
    3. По вертикали (Абзацы): склеивает строки в многострочный абзац ТОЛЬКО если они образуют
       плотный текстовый блок описания (v_gap < 0.75 * h_avg, содержат строчные буквы или >= 3 слов).
       Одиночные КАПС-кнопки интерфейса по вертикали не склеиваются.
    """
    if not raw_boxes:
        return []

    split_boxes = _split_bullet_tokens(raw_boxes)
    if not split_boxes:
        return []

    line_clusters = _cluster_words_into_lines(split_boxes)

    merged_lines: List[RawWordBox] = []
    for line in line_clusters:
        line.sort(key=lambda w: w.x1)
        merged_lines.append(
            RawWordBox(
                x1=min(w.x1 for w in line),
                y1=min(w.y1 for w in line),
                x2=max(w.x2 for w in line),
                y2=max(w.y2 for w in line),
                text=" ".join(w.text.strip() for w in line if w.text.strip()),
                score=min(w.score for w in line),
                lines_merged=1,
            )
        )

    # Шаг 2: Вертикальная склейка ТОЛЬКО для плотных текстовых абзацев (не для одиночных КАПС-кнопок)
    merged_lines.sort(key=lambda b: (b.y1, b.x1))
    para_clusters: List[List[RawWordBox]] = []

    def _is_dense_paragraph_line(lb: RawWordBox) -> bool:
        has_lower = any(ch.islower() for ch in lb.text)
        word_cnt = len(lb.text.split())
        return has_lower or word_cnt >= 3

    for line_box in merged_lines:
        placed_in_para = False
        if _is_dense_paragraph_line(line_box):
            for para in reversed(para_clusters):
                last_line = para[-1]
                if not _is_dense_paragraph_line(last_line):
                    continue
                px1 = min(l.x1 for l in para)
                py1 = min(l.y1 for l in para)
                px2 = max(l.x2 for l in para)
                py2 = max(l.y2 for l in para)

                h1 = last_line.height
                h2 = line_box.height
                h_avg = (h1 + h2) / 2.0
                height_ratio = max(h1, h2) / max(1.0, min(h1, h2))

                v_gap = line_box.y1 - py2
                horiz_overlap = min(px2, line_box.x2) - max(px1, line_box.x1)
                left_aligned = abs(px1 - line_box.x1) <= 24
                center_aligned = abs(((px1 + px2) / 2.0) - ((line_box.x1 + line_box.x2) / 2.0)) <= 32

                if (
                    -4 <= v_gap < MERGE_VERT_FACTOR * h_avg
                    and height_ratio <= 1.35
                    and (horiz_overlap > 0 or left_aligned or center_aligned)
                ):
                    para.append(line_box)
                    placed_in_para = True
                    break
        if not placed_in_para:
            para_clusters.append([line_box])

    final_paragraphs: List[RawWordBox] = []
    for para in para_clusters:
        para.sort(key=lambda l: (l.y1, l.x1))
        full_text = " ".join(l.text.strip() for l in para if l.text.strip())
        final_paragraphs.append(
            RawWordBox(
                x1=min(l.x1 for l in para),
                y1=min(l.y1 for l in para),
                x2=max(l.x2 for l in para),
                y2=max(l.y2 for l in para),
                text=full_text,
                score=min(l.score for l in para),
                lines_merged=len(para),
            )
        )

    return final_paragraphs
