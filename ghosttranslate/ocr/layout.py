"""Склейка слов OCR в строки, абзацы и пункты меню."""

import re
from typing import Callable, Dict, List, Optional, Tuple

from ..config import (
    JUSTIFIED_GAP_FACTOR,
    JUSTIFIED_GAP_SPREAD,
    MERGE_HORIZ_FACTOR,
    MERGE_LINE_GAP_FACTOR,
    MERGE_VERT_FACTOR,
)
from ..models import RawWordBox


LATIN_REGEX = re.compile(r"[a-zA-Z]{2,}")
# «/» внутри слова — это «EA/DICE» или «r/Battlefield6», а не разделитель меню.
BULLET_SPLIT_REGEX = re.compile(r"\s*[•·|»—]+\s*")
HAS_BULLET_REGEX = re.compile(r"[•·|»—]")
# Ники, сабреддиты, ссылки и имена вроде «Battlefield6»: перевод их только портит.
IDENTIFIER_REGEX = re.compile(
    r"(?:[rRuU]/\S+|[@#]\S+|\S*_\S*|https?://\S+|www\.\S+|\S+\.(?:com|net|org|io|gg|tv|ru|pl)\b\S*"
    r"|(?=[^\s]*\d)(?=[^\s]*[A-Za-z])[A-Za-z0-9]+)"
)


# Начало пункта списка или оглавления: «Note 15:», «STATEMENT II», «ANNEX IV», «Table 3.», «1.», «a)».
# Число без точки или двоеточия («Over 50 people») меткой не считается: так начинается обычная строка.
# OCR разрывает номер пробелом («Note 1 1 :») и читает «III» как «Ill». Одиночная «I» и «Ill» —
# метка только после слова капсом: «Then I went» и «Feeling Ill» — обычные строки абзаца.
# Время в начале строки («07:39», «[07:39]», «07:39:12») — новое сообщение чата игры или мессенджера.
LIST_LABEL_REGEX = re.compile(
    r"^(?:[A-Z][A-Za-z]{2,}\s+\d{1,2}(?:\s?\d)?\s*[.:]"
    r"|[A-Z]{3,}\s+(?:[IVXL]{1,5}|Il{1,2})\b"
    r"|[A-Z][A-Za-z]{2,}\s+(?:II|III|IV|VI{0,3}|IX|XI{0,3})\b"
    r"|(?:\d{1,3}|[a-z])[.)](?=\s)"
    r"|[\[(]?\d{1,2}:\d{2}(?::\d{2})?[\])]?(?=\s|$))"
)
# Подпись и её значение в одной строке (метка оглавления и название) стоят дальше обычного пробела.
ROW_JOIN_GAP_FACTOR = 1.5


def starts_list_item(text: str) -> bool:
    return LIST_LABEL_REGEX.match(text.strip()) is not None


def _is_caps_heading(text: str) -> bool:
    """Заголовок капсом («NOTES TO THE FINANCIAL STATEMENTS») не продолжает строку обычного текста."""
    letters = [ch for ch in text if ch.isalpha()]
    return len(text.split()) >= 2 and len(letters) >= 4 and all(ch.isupper() for ch in letters)


def _is_bare_list_label(words: List[RawWordBox]) -> bool:
    """«STATEMENT II» или «Note 15:» без названия: название стоит справа через отступ."""
    text = " ".join(word.text for word in words).strip() + " "
    match = LIST_LABEL_REGEX.match(text)
    return match is not None and not text[match.end():].strip(" .:-–—")


PSEUDO_ICON_PREFIX_REGEX = re.compile(r"^[@©®¤§°•·]+\s*(?=\d)")
CONFUSABLE_U_PREFIX_REGEX = re.compile(
    r"\b(?:(?:Ll|II|lI)(?=[bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ][a-zA-Z]{2,})"
    r"|Il(?=[bcdfghjkmnpqrstvwxzBCDFGHJKMNPQRSTVWXZ][a-zA-Z]{2,}))"
)
TRAILING_TIMECODE_REGEX = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*$")
BOT_TAG_LINE_REGEX = re.compile(
    r"^(?:@\S+|\S+(?:\s+\S+){0,2})\s+\[?(?:BOT|APP|ГОТ)\]?\s*$",
    re.IGNORECASE,
)
DISCORD_MENTION_ONLY_REGEX = re.compile(
    r"^@[A-Za-z0-9_.\-]+(?:\s+[A-Z][A-Za-z0-9_.\-]*)*(?:\s*\([^)]+\))?\s*$"
)


def normalize_ocr_confusables(text: str) -> str:
    """Исправляет типичные опечатки OCR на пиксельных шрифтах ('Llpgrades' -> 'Upgrades') и значки перед числами."""
    if not text:
        return text
    cleaned = PSEUDO_ICON_PREFIX_REGEX.sub("", text.strip())
    return CONFUSABLE_U_PREFIX_REGEX.sub("U", cleaned)


def is_identifier_token(token: str) -> bool:
    core = token.strip(".,:;!?()[]\"'«»")
    return bool(core) and IDENTIFIER_REGEX.fullmatch(core) is not None


def is_chat_metadata_line(text: str) -> bool:
    """Шапка сообщения Discord/чата: '17 [d1s] k1r1to 20:51', 'Serega [D1S] 22:02', '@Username', 'Mee6 BOT'."""
    stripped = text.strip()
    if not stripped:
        return False
    if BOT_TAG_LINE_REGEX.match(stripped) or DISCORD_MENTION_ONLY_REGEX.match(stripped):
        return True
    time_match = TRAILING_TIMECODE_REGEX.search(stripped)
    if time_match:
        prefix = stripped[: time_match.start()].strip()
        tokens = prefix.split()
        if 1 <= len(tokens) <= 4 and all(len(tok) <= 20 for tok in tokens):
            return True
    return False


def is_valid_english_box(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return False
    if is_chat_metadata_line(text):
        return False
    if all(is_identifier_token(token) for token in text.split()):
        return False
    # «Ресурс: Wood» проверяется по значению; абзац, кончающийся двоеточием, — целиком.
    after_colon = text.split(":", 1)[-1].strip() if ":" in text else ""
    payload = after_colon if len(after_colon) >= 2 else text.strip()
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
# Апостроф внутри — имена из игр: «Зул'джан».
RUSSIAN_WORD_REGEX = re.compile(r"[а-яё]+(?:['’-][а-яё]+)*")
CASE_FLIP_REGEX = re.compile(r"[a-z][A-Z]")
# «3mo», «24h», «1.2k», «2nd»: число с единицей — обычный английский текст, а не мусор OCR.
NUMBER_WITH_UNIT_REGEX = re.compile(r"\d+(?:[.,]\d+)?(?:[a-zA-Z]{1,3})")
# «x1», «x10» в «Barricade x1» — множитель количества, а не мусор OCR.
MULTIPLIER_TOKEN_REGEX = re.compile(r"[xX]\d+")
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
    if NUMBER_WITH_UNIT_REGEX.fullmatch(core) or MULTIPLIER_TOKEN_REGEX.fullmatch(core):
        return False
    if any(ch.isdigit() for ch in core):
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
        if word.text == ru_word.text and not any(ch.isalpha() for ch in word.text):
            # Время, числа и знаки оба OCR читают одинаково: язык строки по ним не понять.
            decisions.append((word, line_idx, False))
            continue
        is_russian = russian_reading_wins(word.text, ru_word.text, score)
        decisions.append((word, line_idx, is_russian))
        russian, total = line_votes.get(line_idx, (0, 0))
        line_votes[line_idx] = (russian + int(is_russian), total + 1)

    kept: List[RawWordBox] = []
    dropped = 0
    for word, line_idx, is_russian in decisions:
        if line_idx is not None and not is_russian:
            russian, total = line_votes.get(line_idx, (0, 0))
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
    separator_line: Optional[int] = None
    for box in raw_word_boxes:
        raw_txt = (box.text or "").strip()
        if not raw_txt:
            continue
        cleaned = raw_txt.strip("•·|/»— ").strip()
        if not cleaned:
            # Разделитель отдельным словом: слово после него начинает новый пункт меню.
            if box.line_id is not None:
                separator_line = box.line_id
            continue
        if separator_line is not None and box.line_id == separator_line:
            box.break_before = True
        separator_line = None

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
                    break_before=box.break_before or idx > 0,
                    line_id=box.line_id,
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


# Доли кегля, которые занимает рамка слова: «are» — только высота строчных, «lobbies» — с верхним
# выносным элементом, «playing» — с обоими. Без этого строка «- bot lobbies» казалась мельче соседних.
ASCENDER_CHARS = frozenset("bdfhklABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
MID_ASCENDER_CHARS = frozenset("tij")
DESCENDER_CHARS = frozenset("gjpqy")
X_HEIGHT_SHARE = 0.5
MID_ASCENDER_SHARE = 0.62
ASCENDER_SHARE = 0.72
DESCENDER_SHARE = 0.21


def word_height_share(text: str) -> Optional[float]:
    letters = [ch for ch in text if ch.isascii() and ch.isalnum()]
    if not letters:
        return None
    if any(ch in ASCENDER_CHARS for ch in letters):
        top = ASCENDER_SHARE
    elif any(ch in MID_ASCENDER_CHARS for ch in letters):
        top = MID_ASCENDER_SHARE
    else:
        top = X_HEIGHT_SHARE
    bottom = DESCENDER_SHARE if any(ch in DESCENDER_CHARS for ch in letters) else 0.0
    return top + bottom


def estimate_font_px(words: List[RawWordBox]) -> float:
    """Кегль текста по рамкам слов: медиана, чтобы одно криво обрезанное слово не сбивало размер.

    Однобуквенные слова не учитываются, если есть другие: так OCR читает значки
    у кнопок («a Award», «D Reply»), и рамка значка в разы выше строчной «a».
    """
    measured = [word for word in words if len(word.text.strip()) > 1] or words
    estimates = []
    for word in measured:
        share = word_height_share(word.text)
        if share is not None and word.height >= 3:
            estimates.append(word.height / share)
    if not estimates:
        return max(word.height for word in words) if words else 0.0
    estimates.sort()
    return estimates[(len(estimates) - 1) // 2]


def _split_ocr_line(line: List[RawWordBox]) -> List[List[RawWordBox]]:
    """Строка WinOCR рвётся только там, где стоят отдельные пункты меню.

    Порог считается от кегля всей строки, а не от рамок соседних слов: рамка «as» или «on»
    ниже рамки «Bots,» почти вдвое, а рамка «Other» ниже кегля на четверть,
    и по ним обычный пробел выглядел бы разрывом.
    """
    line = sorted(line, key=lambda word: word.x1)
    unit = max(max(word.height for word in line), estimate_font_px(line))
    gaps = sorted(b.x1 - a.x2 for a, b in zip(line, line[1:]) if b.x1 > a.x2)
    usual_gap = gaps[(len(gaps) - 1) // 2] if gaps else 0

    def is_word_space(gap: int) -> bool:
        if gap < -unit:
            return False
        if gap <= MERGE_LINE_GAP_FACTOR * unit:
            return True
        return gap <= JUSTIFIED_GAP_FACTOR * unit and gap <= JUSTIFIED_GAP_SPREAD * usual_gap

    groups: List[List[RawWordBox]] = []
    current: List[RawWordBox] = [line[0]]
    for word in line[1:]:
        prev = current[-1]
        blocked = prev.split_from_bullet or word.split_from_bullet or word.break_before
        gap = word.x1 - prev.x2
        # «STATEMENT II — Statement of...»: тире после метки пункта не разделитель меню.
        if 0 <= gap <= ROW_JOIN_GAP_FACTOR * unit and _is_bare_list_label(current):
            current.append(word)
        elif (not blocked) and is_word_space(gap):
            current.append(word)
        else:
            groups.append(current)
            current = [word]
    groups.append(current)
    return groups


def _cluster_words_into_lines(words: List[RawWordBox]) -> List[List[RawWordBox]]:
    """Склеивает слова одной строки независимо от порядка, в котором их вернул OCR.

    Слова с номером строки OCR группируются по нему. Для остальных строка угадывается
    по перекрытию по высоте: левое слово с y на пиксель больше не должно отрываться.
    """
    usable = [word for word in words if word.text and word.text.strip()]
    ocr_lines: Dict[int, List[RawWordBox]] = {}
    loose: List[RawWordBox] = []
    for word in usable:
        if word.line_id is None:
            loose.append(word)
        else:
            ocr_lines.setdefault(word.line_id, []).append(word)
    groups: List[List[RawWordBox]] = []
    for line in ocr_lines.values():
        groups.extend(_split_ocr_line(line))
    return _join_row_neighbours(groups) + _cluster_loose_words(loose)


def _join_row_neighbours(groups: List[List[RawWordBox]]) -> List[List[RawWordBox]]:
    """Склеивает части одной строки экрана, которые WinOCR вернул разными строками.

    В оглавлении «Note 15:» и «Advance Receipts» приходят отдельно, хотя между ними обычный пробел.
    Части, разделённые широким промежутком или разделителем меню, остаются отдельными. Разделитель
    вплотную к слову («Note 6.•Inventories») — это прочитанное как «•» двоеточие: у пункта меню
    разделитель стоит с пробелами по бокам.
    """
    groups = sorted(groups, key=lambda g: min(w.x1 for w in g))
    joined: List[List[RawWordBox]] = []
    for group in groups:
        first = min(group, key=lambda w: w.x1)
        target = None
        for candidate in joined:
            last = max(candidate, key=lambda w: w.x2)
            if last.line_id == first.line_id or not _boxes_share_text_line(last, first):
                continue
            unit = max(last.height, first.height, estimate_font_px(candidate))
            gap = first.x1 - last.x2
            if first.break_before or first.split_from_bullet:
                max_gap = 0.5 * unit
            elif _is_bare_list_label(candidate):
                max_gap = ROW_JOIN_GAP_FACTOR * unit
            else:
                max_gap = MERGE_LINE_GAP_FACTOR * unit
            if 0 <= gap <= max_gap:
                target = candidate
                break
        if target is None:
            joined.append(list(group))
        else:
            target.extend(group)
    return joined


def _cluster_loose_words(usable: List[RawWordBox]) -> List[List[RawWordBox]]:
    if not usable:
        return []
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


CHAT_TIME_REGEX = re.compile(r"^[\[(]?\d{1,2}:\d{2}(?::\d{2})?[\])]?$")
CHAT_TAG_REGEX = re.compile(r"^[\[(][A-Za-zА-Яа-яЁё0-9_\-]{1,16}[\])]:?$")
NON_CHAT_COLON_WORDS = frozenset(
    {"note", "table", "figure", "fig", "chapter", "section", "statement", "annex", "part", "item", "step"}
)
NICK_TOKEN_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{1,15}$")


def _looks_like_player_nick(prefix: str) -> bool:
    """Ник без шапки чата: цифра, подчёркивание или заглавная в середине (Player1, Sniper_X, DarkKnight).

    Обычное слово интерфейса («Warning», «HP») сюда не попадает.
    """
    name = prefix.strip("[]()")
    if not name or name.lower() in NON_CHAT_COLON_WORDS or not NICK_TOKEN_REGEX.match(name):
        return False
    if any(ch.isdigit() for ch in name) or "_" in name or "-" in name:
        return True
    return any(name[i].isupper() and any(ch.islower() for ch in name[:i]) for i in range(1, len(name)))


def _split_glued_colon_box(box: RawWordBox) -> Optional[RawWordBox]:
    """Отрезает ник до двоеточия внутри одного слова ('Player1:hello') со сдвигом x1 вправо."""
    raw = box.text.strip()
    if ":" not in raw:
        return None
    prefix, rest = raw.split(":", 1)
    msg = rest.strip()
    if not msg:
        return None
    total_len = max(1, len(raw))
    prefix_len = len(prefix) + 1
    shift_px = int(round((prefix_len / float(total_len)) * max(1, box.width)))
    new_x1 = min(box.x2 - 4, box.x1 + max(1, shift_px))
    return RawWordBox(
        x1=new_x1,
        y1=box.y1,
        x2=box.x2,
        y2=box.y2,
        text=msg,
        score=box.score,
        lines_merged=box.lines_merged,
        font_px=box.font_px,
        split_from_bullet=box.split_from_bullet,
        break_before=True,
        line_id=box.line_id,
    )


def _strip_chat_line_header(line_words: List[RawWordBox]) -> List[RawWordBox]:
    """Отрезает шапку строки игрового чата (таймкод, тег канала и ник с двоеточием).

    Возвращает слова самого сообщения со сдвинутым вправо x1, чтобы оригинальный
    ник и время оставались открытыми на экране, а в перевод уходила только суть.
    """
    if not line_words:
        return []

    n = len(line_words)
    idx = 0
    while idx < min(n, 3):
        tok = line_words[idx].text.strip()
        if CHAT_TIME_REGEX.match(tok):
            idx += 1
            continue
        if CHAT_TAG_REGEX.match(tok) and not tok.endswith(":"):
            idx += 1
            continue
        break

    remaining: Optional[List[RawWordBox]] = None

    if idx > 0:
        colon_pos = None
        for j in range(idx, min(n, idx + 2)):
            tok = line_words[j].text.strip()
            if ":" in tok and not CHAT_TIME_REGEX.match(tok):
                colon_pos = j
                break
        if colon_pos is not None:
            tok = line_words[colon_pos].text.strip()
            if tok.endswith(":"):
                remaining = list(line_words[colon_pos + 1 :])
            else:
                tail_box = _split_glued_colon_box(line_words[colon_pos])
                if tail_box is not None:
                    remaining = [tail_box, *line_words[colon_pos + 1 :]]
        else:
            remaining = list(line_words[idx:])
    else:
        first_tok = line_words[0].text.strip()
        full_line_text = " ".join(w.text.strip() for w in line_words if w.text.strip())
        if (
            first_tok.startswith("@")
            and len(first_tok) > 1
            and any(ch.isalpha() for ch in first_tok)
            and n >= 2
            and not is_chat_metadata_line(full_line_text)
        ):
            remaining = list(line_words[1:])
        elif ":" in first_tok and not CHAT_TIME_REGEX.match(first_tok):
            prefix, rest = first_tok.split(":", 1)
            if _looks_like_player_nick(prefix):
                if not rest.strip():
                    if n >= 2:
                        remaining = list(line_words[1:])
                else:
                    tail_box = _split_glued_colon_box(line_words[0])
                    if tail_box is not None:
                        remaining = [tail_box, *line_words[1:]]

    if remaining and any(any(ch.isalpha() for ch in w.text) for w in remaining):
        return remaining
    return line_words


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
        stripped_line = _strip_chat_line_header(line)
        header_stripped = (
            len(stripped_line) != len(line)
            or (stripped_line and stripped_line[0].x1 != line[0].x1)
        )
        line = stripped_line
        if not line:
            continue
        line_text = normalize_ocr_confusables(
            " ".join(w.text.strip() for w in line if w.text.strip())
        )
        if not line_text:
            continue
        merged_lines.append(
            RawWordBox(
                x1=min(w.x1 for w in line),
                y1=min(w.y1 for w in line),
                x2=max(w.x2 for w in line),
                y2=max(w.y2 for w in line),
                text=line_text,
                score=min(w.score for w in line),
                lines_merged=1,
                font_px=estimate_font_px(line),
                break_before=header_stripped,
            )
        )

    # Шаг 2: Вертикальная склейка ТОЛЬКО для плотных текстовых абзацев (не для одиночных КАПС-кнопок)
    merged_lines.sort(key=lambda b: (b.y1, b.x1))
    para_clusters: List[List[RawWordBox]] = []

    def _is_dense_paragraph_line(lb: RawWordBox) -> bool:
        has_lower = any(ch.islower() for ch in lb.text)
        word_cnt = len(lb.text.split())
        return has_lower or word_cnt >= 3

    def _covers_foreign_line(para: List[RawWordBox], line_box: RawWordBox) -> bool:
        """Рамка абзаца с новой строкой накрыла бы строку, которая в абзац не входит.

        Так в оглавлении названия разделов склеивались через метку «STATEMENT II» в той же строке,
        и её плашка оказывалась внутри плашки абзаца.
        """
        x1 = min(min(l.x1 for l in para), line_box.x1)
        y1 = min(min(l.y1 for l in para), line_box.y1)
        x2 = max(max(l.x2 for l in para), line_box.x2)
        y2 = max(max(l.y2 for l in para), line_box.y2)
        for other in merged_lines:
            if other is line_box or any(other is l for l in para):
                continue
            if min(x2, other.x2) - max(x1, other.x1) > 2 and min(y2, other.y2) - max(y1, other.y1) > 2:
                return True
        return False

    for line_box in merged_lines:
        placed_in_para = False
        # Пункт списка или новое сообщение чата со срезанной шапкой начинает свой блок.
        if (
            _is_dense_paragraph_line(line_box)
            and not starts_list_item(line_box.text)
            and not line_box.break_before
        ):
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

                # Рамки RapidOCR строк с обводкой (чат игры) перекрываются на треть строки:
                # поджать их до букв нельзя, обводка соседних строк сливается.
                if (
                    -max(4.0, 0.35 * h_avg) <= v_gap < MERGE_VERT_FACTOR * h_avg
                    and height_ratio <= 1.35
                    and _is_caps_heading(last_line.text) == _is_caps_heading(line_box.text)
                    and (horiz_overlap > 0 or left_aligned or center_aligned)
                    and not _covers_foreign_line(para, line_box)
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
        sizes = sorted(l.font_px for l in para)
        final_paragraphs.append(
            RawWordBox(
                x1=min(l.x1 for l in para),
                y1=min(l.y1 for l in para),
                x2=max(l.x2 for l in para),
                y2=max(l.y2 for l in para),
                text=full_text,
                score=min(l.score for l in para),
                lines_merged=len(para),
                font_px=sizes[len(sizes) // 2],
            )
        )

    return final_paragraphs
