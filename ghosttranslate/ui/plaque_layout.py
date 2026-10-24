"""Где и каким шрифтом рисовать перевод: плашка не меньше оригинала и не мельче читаемого."""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QFont, QFontMetrics

from ..config import FONT_HEIGHT_RATIO, MIN_READABLE_FONT_PX
from ..models import OverlayBlock
from ..settings import FontCustomConfig

WRAP_STYLES = ("wrap_gradient", "dark_glass", "cyber_neon", "high_contrast")
PAD_X = 4
PAD_Y = 1
# Шрифт абзаца ужимается не больше чем до этой доли, остальное — рост плашки вниз.
MAX_SHRINK = 0.88
STACK_GAP_PX = 2


@dataclass
class PlaqueLayout:
    block: OverlayBlock
    rect: QRect
    font: QFont
    flags: int
    text: str
    # Сдвиг текста вверх в плашке, сжатой до шага строк: буквы стоят ниже центра строки шрифта.
    text_shift: int = 0

    @property
    def text_rect(self) -> QRect:
        return self.rect.adjusted(PAD_X, PAD_Y - self.text_shift, -PAD_X, -PAD_Y - self.text_shift)

    def move_down(self, dy: int) -> None:
        self.rect.translate(0, dy)


def _base_font_px(block: OverlayBlock, font_cfg: FontCustomConfig) -> int:
    if font_cfg.use_fixed_pt:
        return max(9, min(46, int(round(font_cfg.fixed_pt * 1.333))))
    source_px = block.font_px or 0.8 * block.rect.height() / max(1, block.lines_merged)
    scale_mult = max(0.6, min(1.8, font_cfg.scale_percent / 100.0))
    return max(10, min(48, int(round(source_px * FONT_HEIGHT_RATIO * scale_mult))))


def _make_font(font_cfg: FontCustomConfig, px: int) -> QFont:
    weight = QFont.Weight.Bold if font_cfg.is_bold else QFont.Weight.Medium
    font = QFont(font_cfg.font_family, -1, weight)
    font.setPixelSize(px)
    return font


def _is_centered(block: OverlayBlock, font_cfg: FontCustomConfig) -> bool:
    if font_cfg.text_align == "center":
        return True
    if font_cfg.text_align == "left":
        return False
    return block.lines_merged == 1 and len(block.orig_text.split()) <= 2


def _wrapped_height(font: QFont, width: int, text: str) -> int:
    bound = QFontMetrics(font).boundingRect(QRect(0, 0, max(1, width), 100000), int(Qt.TextFlag.TextWordWrap), text)
    return bound.height()


def wrap_lines(font: QFont, text: str, width: int) -> List[str]:
    """Перенос по словам для контурного стиля: он рисует текст путём, и drawText ему не подходит."""
    fm = QFontMetrics(font)
    lines: List[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and fm.horizontalAdvance(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [text]


def _fit_in_slot(
    text: str,
    font_cfg: FontCustomConfig,
    base_px: int,
    floor_px: int,
    slot_h: int,
    src_inner_w: int,
    room_w: int,
    paragraph: bool,
) -> Optional[Tuple[QFont, bool, int]]:
    """Кегль, при котором перевод не выходит за полосу до следующей строки текста.

    Строка чата или списка: сперва в ширину оригинала с лёгким ужатием, потом шире,
    до соседнего текста или края, и мельче, вплоть до MIN_READABLE_FONT_PX. Абзац
    переносится в своей ширине. None — не влезает и при самом мелком читаемом кегле.
    """
    inner_h = slot_h - 2 * PAD_Y
    if paragraph:
        # Без полей: две строки по 12 px занимают 32 px при шаге строк чата около 17 px,
        # а нижний край строки шрифта — это хвосты букв, а не сами буквы.
        for px in range(base_px, MIN_READABLE_FONT_PX - 1, -1):
            font = _make_font(font_cfg, px)
            if _wrapped_height(font, src_inner_w, text) <= slot_h:
                return font, True, src_inner_w
        return None
    for limit_w, lowest_px in ((src_inner_w, floor_px), (room_w, MIN_READABLE_FONT_PX)):
        for px in range(base_px, lowest_px - 1, -1):
            font = _make_font(font_cfg, px)
            fm = QFontMetrics(font)
            if fm.horizontalAdvance(text) <= limit_w and fm.tightBoundingRect(text).height() <= inner_h:
                return font, False, max(src_inner_w, fm.horizontalAdvance(text))
    return None


def layout_plaque(
    block: OverlayBlock,
    font_cfg: FontCustomConfig,
    style_mode: str,
    bounds: QRect,
    right_limit: Optional[int] = None,
    left_limit: Optional[int] = None,
    slot_h: Optional[int] = None,
) -> PlaqueLayout:
    """Плашка закрывает оригинал целиком; перевод начинается там же, где начинался текст.

    Если сразу под текстом другая строка (slot_h), плашка подбирает кегль под свою полосу:
    в чате и списке выросшая вниз плашка сдвигала бы все строки ниже.
    Иначе не влезающий перевод сначала чуть ужимается. Подпись в одну строку затем занимает
    свободное место до соседнего текста и только потом переносится; абзац растёт вниз.
    Шрифт мельче MIN_READABLE_FONT_PX не берётся: прежде длинный абзац ужимался до 8 px.
    """
    src = block.rect
    text = block.trans_text
    centered = _is_centered(block, font_cfg)
    can_wrap = style_mode in WRAP_STYLES
    base_px = _base_font_px(block, font_cfg)
    floor_px = base_px if font_cfg.use_fixed_pt else min(base_px, max(MIN_READABLE_FONT_PX, int(base_px * MAX_SHRINK)))
    right_edge = bounds.right() if right_limit is None else min(bounds.right(), right_limit)
    left_edge = bounds.left() if left_limit is None else max(bounds.left(), left_limit)
    src_inner_w = max(8, src.width())
    start_x = left_edge if font_cfg.text_align == "center" else src.left() - PAD_X
    room_w = max(src_inner_w, right_edge - start_x - 2 * PAD_X)

    fitted = None
    if slot_h is not None and not font_cfg.use_fixed_pt:
        paragraph = block.lines_merged >= 2
        fitted = _fit_in_slot(text, font_cfg, base_px, floor_px, slot_h, src_inner_w, room_w, paragraph)
    if fitted is not None:
        font, wrap, width = fitted
        if not wrap:
            # Высоту до шага строк поджимает _fit_to_row: она же ставит буквы по центру.
            text_h = QFontMetrics(font).height()
            flags = int(Qt.AlignmentFlag.AlignVCenter)
            return _place(block, font, flags, text, width, text_h, centered, font_cfg, left_edge, right_edge)
        flags = int(Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap) | int(Qt.TextFlag.TextDontClip)
        lay = _place(block, font, flags, text, width, _wrapped_height(font, width, text), centered,
                     font_cfg, left_edge, right_edge)
        if lay.rect.height() > slot_h:
            lay.rect.setHeight(slot_h)
        return lay

    font = _make_font(font_cfg, base_px)
    text_w = QFontMetrics(font).horizontalAdvance(text)
    # Абзац в несколько строк переносится в любом стиле: в одну строку он обрезался бы на первой фразе.
    wrap = block.lines_merged >= 2
    wrap_w = src_inner_w

    if not wrap and text_w > src_inner_w:
        # Подпись в одну строку: сперва кегль чуть меньше, потом шире, и только потом перенос.
        for px in range(base_px, floor_px - 1, -1):
            font = _make_font(font_cfg, px)
            text_w = QFontMetrics(font).horizontalAdvance(text)
            if text_w <= src_inner_w:
                break
        fit_w = right_edge - left_edge - 2 * PAD_X
        if text_w > room_w and can_wrap and len(text.split()) >= 3:
            wrap = True
            wrap_w = room_w
            font = _make_font(font_cfg, base_px)
        elif text_w > fit_w and not font_cfg.use_fixed_pt:
            # Кнопка зажата соседями с двух сторон: мельче, но читаемо, вместо наезда на них.
            for px in range(floor_px - 1, MIN_READABLE_FONT_PX - 1, -1):
                font = _make_font(font_cfg, px)
                text_w = QFontMetrics(font).horizontalAdvance(text)
                if text_w <= fit_w:
                    break

    flags = int(Qt.AlignmentFlag.AlignVCenter)
    if wrap:
        width = wrap_w
        for px in range(base_px, floor_px - 1, -1):
            font = _make_font(font_cfg, px)
            if _wrapped_height(font, width, text) <= src.height() - 2 * PAD_Y:
                break
        text_h = _wrapped_height(font, width, text)
        flags = int(Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap)
    else:
        text_w = QFontMetrics(font).horizontalAdvance(text)
        width = max(src_inner_w, text_w)
        text_h = QFontMetrics(font).height()
        if not can_wrap and width > room_w:
            width = room_w
            text = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, width)
    return _place(block, font, flags, text, width, text_h, centered, font_cfg, left_edge, right_edge)


def _place(
    block: OverlayBlock,
    font: QFont,
    flags: int,
    text: str,
    width: int,
    text_h: int,
    centered: bool,
    font_cfg: FontCustomConfig,
    left_edge: int,
    right_edge: int,
) -> PlaqueLayout:
    src = block.rect
    src_inner_w = max(8, src.width())
    if centered and font_cfg.text_align != "center" and width > src_inner_w:
        # Перевод кнопки шире оригинала: рост в обе стороны закрыл бы текст слева (ник у времени).
        centered = False
    flags |= int(Qt.AlignmentFlag.AlignHCenter if centered else Qt.AlignmentFlag.AlignLeft)
    rect_w = width + 2 * PAD_X
    rect_h = max(src.height(), text_h + 2 * PAD_Y)

    if centered:
        rect = QRect(0, 0, rect_w, rect_h)
        rect.moveCenter(src.center())
        rect.moveTop(src.top())
    else:
        rect = QRect(src.left() - PAD_X, src.top(), rect_w, rect_h)
    if rect.right() > right_edge:
        rect.moveRight(right_edge)
    if rect.left() < left_edge:
        rect.moveLeft(left_edge)
    return PlaqueLayout(block=block, rect=rect, font=font, flags=flags, text=text)


def _same_row(a: QRect, b: QRect) -> bool:
    overlap = min(a.bottom(), b.bottom()) - max(a.top(), b.top())
    return overlap > 0.5 * min(a.height(), b.height())


def _neighbour_limits(block: OverlayBlock, blocks: List[OverlayBlock]) -> Tuple[Optional[int], Optional[int]]:
    """Ближайший текст слева и справа в той же строке: плашка не наезжает на ник рядом со временем."""
    src = block.rect
    left: Optional[int] = None
    right: Optional[int] = None
    for other in blocks:
        o = other.rect
        if other is block or not _same_row(src, o):
            continue
        if o.left() > src.right():
            edge = o.left() - PAD_X - 2
            right = edge if right is None else min(right, edge)
        elif o.right() < src.left():
            edge = o.right() + PAD_X + 2
            left = edge if left is None else max(left, edge)
    return left, right


def _band_right_limit(block: OverlayBlock, blocks: List[OverlayBlock], band_h: int) -> Optional[int]:
    """Плашка, вписанная в свою полосу, растёт вправо и не должна закрыть текст правой
    колонки, который стоит чуть ниже и соседом по строке не считается («4mo ago» у поста)."""
    src = block.rect
    top, bottom = src.top(), src.top() + band_h
    limit: Optional[int] = None
    for other in blocks:
        o = other.rect
        if other is block or o.left() <= src.right():
            continue
        if min(bottom, o.bottom()) - max(top, o.top()) > 2:
            edge = o.left() - PAD_X - 2
            limit = edge if limit is None else min(limit, edge)
    return limit


def _slot_height(block: OverlayBlock, blocks: List[OverlayBlock]) -> Optional[int]:
    """От верха текста до следующей строки под ним в той же колонке; None — под ним пусто.

    Рамки OCR соседних строк чата перекрываются на пару пикселей, поэтому слот бывает
    чуть ниже самой рамки. Сильно меньше — это уже не строка ниже, а соседняя колонка.
    """
    src = block.rect
    slot: Optional[int] = None
    for other in blocks:
        o = other.rect
        if other is block or o.top() <= src.top() + src.height() // 2:
            continue
        if min(src.right(), o.right()) < max(src.left(), o.left()):
            continue
        gap = o.top() - src.top()
        slot = gap if slot is None else min(slot, gap)
    if slot is None or slot < 0.6 * src.height():
        return None
    return slot


def _row_room(lay: PlaqueLayout, blocks: List[OverlayBlock]) -> Optional[int]:
    """Высота до ближайшего текста под плашкой: в оглавлении и списках это шаг строк."""
    src = lay.block.rect
    room: Optional[int] = None
    for other in blocks:
        o = other.rect
        if other is lay.block or o.top() <= src.top() + src.height() // 2:
            continue
        if min(lay.rect.right(), o.right()) < max(lay.rect.left(), o.left()):
            continue
        gap = o.top() - src.top()
        room = gap if room is None else min(room, gap)
    if room is None or room < 0.7 * src.height():
        return None
    return room


def _fit_to_row(lay: PlaqueLayout, room: int, font_cfg: FontCustomConfig) -> None:
    """Однострочная плашка выше шага строк сдвигала бы вниз каждую следующую строку списка.

    Строка шрифта на треть выше самих букв, поэтому плашка сжимается до шага строк, буквы
    ставятся по её центру, а кегль уменьшается, только если не влезают и сами буквы.
    """
    font = lay.font
    ink = QFontMetrics(font).tightBoundingRect(lay.text)
    if not font_cfg.use_fixed_pt:
        px = font.pixelSize()
        while ink.height() > room - 2 * PAD_Y and px > MIN_READABLE_FONT_PX:
            px -= 1
            font = _make_font(font_cfg, px)
            ink = QFontMetrics(font).tightBoundingRect(lay.text)
    fm = QFontMetrics(font)
    inner_h = room - 2 * PAD_Y
    qt_baseline = (inner_h - fm.height()) / 2 + fm.ascent()
    ink_baseline = (inner_h - ink.height()) / 2 - ink.top()
    lay.font = font
    lay.rect.setHeight(room)
    lay.text_shift = int(round(qt_baseline - ink_baseline))


def _stacks_over(lower: QRect, upper: QRect) -> bool:
    """Нижняя плашка налезает на верхнюю, стоящую над ней в той же колонке."""
    overlap_w = min(lower.right(), upper.right()) - max(lower.left(), upper.left())
    overlap_h = min(lower.bottom(), upper.bottom()) - max(lower.top(), upper.top())
    return overlap_h > 0 and overlap_w > 0.3 * min(lower.width(), upper.width())


def layout_blocks(
    blocks: List[OverlayBlock],
    font_cfg: FontCustomConfig,
    style_mode: str,
    bounds: QRect,
) -> List[PlaqueLayout]:
    """Раскладка всех плашек кадра сверху вниз.

    Выросший вниз перевод не закрывает следующий абзац: плашки ниже сдвигаются
    под него, как строки при переносе текста. Плашки одной строки не трогаются.
    Строка раскладывается слева направо: перевод соседа слева бывает шире его оригинала.
    """
    layouts: List[PlaqueLayout] = []
    for block in sorted(blocks, key=lambda b: b.rect.left()):
        if block.is_pending:
            layouts.append(
                PlaqueLayout(block=block, rect=QRect(block.rect), font=_make_font(font_cfg, 12), flags=0, text="")
            )
            continue
        left_limit, right_limit = _neighbour_limits(block, blocks)
        for lay in layouts:
            if lay.block.rect.right() < block.rect.left() and _same_row(lay.block.rect, block.rect):
                edge = lay.rect.right() + 2
                left_limit = edge if left_limit is None else max(left_limit, edge)
        slot_h = _slot_height(block, blocks)
        if slot_h is not None:
            band_limit = _band_right_limit(block, blocks, slot_h)
            if band_limit is not None:
                right_limit = band_limit if right_limit is None else min(right_limit, band_limit)
        lay = layout_plaque(block, font_cfg, style_mode, bounds, right_limit, left_limit, slot_h)
        if not lay.flags & int(Qt.TextFlag.TextWordWrap):
            room = slot_h if slot_h is not None else _row_room(lay, blocks)
            if room is not None and lay.rect.height() > room:
                _fit_to_row(lay, room, font_cfg)
        layouts.append(lay)

    layouts.sort(key=lambda lay: (lay.block.rect.top(), lay.block.rect.left()))
    placed: List[PlaqueLayout] = []
    for lay in layouts:
        for _ in range(len(placed) + 1):
            blocker = next(
                (
                    other
                    for other in placed
                    if other.block.rect.top() < lay.block.rect.top() - 2
                    and not _same_row(other.block.rect, lay.block.rect)
                    and _stacks_over(lay.rect, other.rect)
                ),
                None,
            )
            if blocker is None:
                break
            lay.move_down(blocker.rect.bottom() + STACK_GAP_PX - lay.rect.top() + 1)
        placed.append(lay)
    return placed
