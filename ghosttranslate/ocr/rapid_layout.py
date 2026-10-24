"""Вывод RapidOCR в том же виде, что слова WinOCR: плотные рамки и номер строки."""

from typing import List, Optional, Sequence, Tuple

import numpy as np

from ..config import RAPIDOCR_INK_THRESHOLD, RAPIDOCR_WORD_GAP_PX
from ..models import RawWordBox


def rapidocr_to_word_boxes(
    items: Optional[Sequence],
    image: Optional[np.ndarray] = None,
    inv_scale: float = 1.0,
) -> List[RawWordBox]:
    """Строки RapidOCR -> слова с line_id.

    При return_word_box каждый символ, включая пробел, приходит со своей рамкой,
    и склейка символов совпадает с текстом строки. По горизонтали слово — это
    объединение рамок его символов. По вертикали рамка символа равна рамке
    детектора, а её раздувает unclip, поэтому при переданном кадре высота
    поджимается до чернил.
    """
    words = rapidocr_items_to_word_boxes(items, inv_scale)
    if image is not None and words:
        tighten_word_boxes_to_ink(image, words)
    return words


def rapidocr_items_to_word_boxes(
    items: Optional[Sequence],
    inv_scale: float = 1.0,
) -> List[RawWordBox]:
    words: List[RawWordBox] = []
    for line_id, item in enumerate(items or []):
        words.extend(_words_from_item(item, line_id, inv_scale))
    return words


def tighten_word_boxes_to_ink(image: np.ndarray, words: List[RawWordBox]) -> None:
    """Поджимает рамку по вертикали до пикселей текста.

    Горизонталь не меняется: промежутки между словами нужны, чтобы строка
    резалась на пункты меню так же, как строка WinOCR.
    """
    if image is None or getattr(image, "ndim", 0) < 2 or not words:
        return
    pixels = image if image.ndim == 2 else image[:, :, :3]
    height, width = pixels.shape[:2]
    for word in words:
        span = _ink_span(pixels, word.x1, word.y1, word.x2, word.y2, height, width)
        if span is None:
            continue
        word.y1, word.y2 = span


def _words_from_item(item, line_id: int, inv_scale: float) -> List[RawWordBox]:
    if not item or len(item) < 3:
        return []
    text = str(item[1] or "")
    try:
        score = float(item[2])
    except (TypeError, ValueError):
        score = 0.0
    boxes = item[3] if len(item) > 4 and isinstance(item[3], (list, tuple)) else None
    chars = item[4] if len(item) > 4 and isinstance(item[4], (list, tuple)) else None
    if boxes and chars and len(boxes) == len(chars) and "".join(str(ch) for ch in chars) == text:
        line_x1, line_x2 = _quad_x_span(item[0], 1.0)
        built = _words_from_chars(chars, boxes, score, line_id, inv_scale, line_x1, line_x2)
        if built:
            return built
    return _line_word(item[0], text, score, line_id, inv_scale)


def _words_from_chars(
    chars,
    boxes,
    score: float,
    line_id: int,
    inv_scale: float,
    line_x1: float,
    line_x2: float,
) -> List[RawWordBox]:
    words: List[RawWordBox] = []
    pieces: List[str] = []
    quads: List = []

    def flush() -> None:
        if not pieces:
            return
        token = "".join(pieces)
        bounds = _union_bounds(quads, inv_scale)
        pieces.clear()
        quads.clear()
        if not token.strip() or bounds is None:
            return
        x1, y1, x2, y2 = bounds
        words.append(
            RawWordBox(
                x1=x1, y1=y1, x2=x2, y2=y2, text=token, score=score, line_id=line_id
            )
        )

    prev_x2 = None
    for char, quad in zip(chars, boxes):
        piece = str(char)
        if piece == "" or piece.isspace():
            flush()
            prev_x2 = None
            continue
        raw_x1, raw_x2 = _quad_x_span(quad, 1.0)
        # Английская модель дописывает в конец строки лишний символ из пустого поля
        # («row .», «matchmaking.e»): его рамка начинается на краю строки и тянется
        # на 100-200 px дальше. Настоящий символ лежит внутри рамки строки.
        if raw_x2 - line_x2 > line_x2 - raw_x1:
            continue
        quad = [(min(max(float(p[0]), line_x1), line_x2), float(p[1])) for p in quad]
        x1, x2 = _quad_x_span(quad, inv_scale)
        # Распознаватель иногда не ставит пробел, но рамки слов при этом расходятся.
        if prev_x2 is not None and x1 - prev_x2 >= RAPIDOCR_WORD_GAP_PX:
            flush()
        pieces.append(piece)
        quads.append(quad)
        prev_x2 = x2
    flush()
    return words


def _quad_x_span(quad, inv_scale: float) -> Tuple[float, float]:
    xs = [float(point[0]) * inv_scale for point in quad]
    return min(xs), max(xs)


def _line_word(quad, text: str, score: float, line_id: int, inv_scale: float) -> List[RawWordBox]:
    token = text.strip()
    bounds = _union_bounds([quad], inv_scale)
    if not token or bounds is None:
        return []
    x1, y1, x2, y2 = bounds
    return [RawWordBox(x1=x1, y1=y1, x2=x2, y2=y2, text=token, score=score, line_id=line_id)]


def _union_bounds(quads, inv_scale: float) -> Optional[Tuple[int, int, int, int]]:
    xs: List[float] = []
    ys: List[float] = []
    for quad in quads:
        if quad is None:
            continue
        for point in quad:
            xs.append(float(point[0]) * inv_scale)
            ys.append(float(point[1]) * inv_scale)
    if not xs:
        return None
    x1, y1 = int(round(min(xs))), int(round(min(ys)))
    x2, y2 = int(round(max(xs))), int(round(max(ys)))
    if x2 <= x1:
        x2 = x1 + 1
    if y2 <= y1:
        y2 = y1 + 1
    return x1, y1, x2, y2


def _ink_span(
    pixels: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    height: int,
    width: int,
) -> Optional[Tuple[int, int]]:
    x1c = max(0, min(width - 1, int(x1)))
    x2c = max(x1c + 1, min(width, int(x2)))
    y1c = max(0, min(height - 1, int(y1)))
    y2c = max(y1c + 1, min(height, int(y2)))
    crop = pixels[y1c:y2c, x1c:x2c]
    if crop.size == 0 or crop.shape[0] < 2:
        return None
    background = np.median(crop.reshape(-1, crop.shape[-1]), axis=0)
    distance = np.abs(crop.astype(np.int16) - background.astype(np.int16)).sum(axis=-1)
    ink_rows = np.flatnonzero(distance.max(axis=1) >= RAPIDOCR_INK_THRESHOLD)
    if ink_rows.size == 0:
        return None
    # Раздутая рамка захватывает чернила соседней строки. У своего текста полоса
    # ближе к центру рамки; точка над «i» от тела буквы отделена одним пикселем
    # и остаётся в той же полосе.
    bands = _ink_bands(ink_rows)
    top, bottom = _band_near_center(bands, crop.shape[0])
    if top == 0 and bottom == crop.shape[0] - 1:
        return None
    new_y1 = y1c + top
    new_y2 = y1c + bottom + 1
    if new_y2 <= new_y1:
        return None
    return new_y1, new_y2


def _ink_bands(ink_rows: np.ndarray) -> List[Tuple[int, int]]:
    bands: List[Tuple[int, int]] = []
    start = prev = int(ink_rows[0])
    for row in ink_rows[1:]:
        row = int(row)
        if row > prev + 2:
            bands.append((start, prev))
            start = row
        prev = row
    bands.append((start, prev))
    return bands


def _band_near_center(bands: List[Tuple[int, int]], crop_height: int) -> Tuple[int, int]:
    center = (crop_height - 1) / 2.0

    def sort_key(band: Tuple[int, int]) -> Tuple[float, int]:
        midpoint = (band[0] + band[1]) / 2.0
        return (abs(midpoint - center), -(band[1] - band[0]))

    return min(bands, key=sort_key)
