"""Константы, пути и параметры распознавания."""

import os
import sys
from typing import Dict, List, Tuple


# ==============================================================================
# КОНСТАНТЫ И КОНФИГУРАЦИЯ (GHOSTTRANSLATE v3.0)
# ==============================================================================
APP_VERSION = "3.3"
TRANSLATION_ENGINE = "native-ct2:int8-lite"
DEFAULT_OCR_BACKEND = "WinOCR"
DEFAULT_RENDER_STYLE = "wrap_gradient"

# Глобальные клавиши. Пользователь меняет их в «Aa Шрифт», если игра сама использует F8/F9:
# RegisterHotKey забирает нажатие целиком, и игра его не получает.
DEFAULT_HOTKEY_TOGGLE = "F8"  # Скрыть / Показать оверлей и панель (toggle_visibility)
DEFAULT_HOTKEY_SNIP = "F9"  # Начать выделение области захвата (start_snipping_mode)
VK_ESCAPE = 0x1B
HOTKEY_ID_TOGGLE = 9008
HOTKEY_ID_SNIP = 9009
WM_HOTKEY = 0x0312

PLAQUE_STYLES: List[Tuple[str, str]] = [
    ("wrap_gradient", "1. Wrap + Градиент (AR Стандарт)"),
    ("single", "2. 1-Строка (Авто-сжатие)"),
    ("outline_only", "3. Subtitles Outline (Без фона — контур)"),
    ("dark_glass", "4. Dark Glass HUD (Темное стекло)"),
    ("cyber_neon", "5. Cyber Neon (Киберпанк / Игровой)"),
    ("high_contrast", "6. High-Contrast Pill (Желтый/Черный)"),
]
STYLE_LABEL_TO_ID: Dict[str, str] = {label: sid for sid, label in PLAQUE_STYLES}
STYLE_ID_TO_LABEL: Dict[str, str] = {sid: label for sid, label in PLAQUE_STYLES}

FONT_FAMILIES = [
    "Segoe UI",
    "Arial",
    "Tahoma",
    "Verdana",
    "Trebuchet MS",
    "Consolas",
    "Impact",
]

TIMER_OPTIONS = ["Ручной", "0.5s", "1.0s", "1.5s", "2.0s", "3.0s", "5.0s", "10.0s", "15.0s", "30.0s"]

PIXEL_DIFF_THRESHOLD = 3
WATCHDOG_DIFF_THRESHOLD = 14
WATCHDOG_INTERVAL_MS = 150
WATCHDOG_PADDING_PX = 6
SEQ_MATCH_THRESHOLD = 0.95
LRU_MAX_SIZE = 2000
# Перевод идёт порциями: первые плашки появляются после первой порции, остальные следом.
TRANSLATE_CHUNK_BLOCKS = 16
# Предел на кадр: экран кода или чата даёт сотни строк, и перевод всех занял бы секунды.
MAX_BLOCKS_PER_FRAME = 150
MIN_OCR_SCORE = 0.42
# Кегль перевода к оценённому кеглю оригинала (models.RawWordBox.font_px).
FONT_HEIGHT_RATIO = 1.0
# Мельче этого перевод не ужимается: длинный русский текст лучше растянуть вниз.
MIN_READABLE_FONT_PX = 12

# Пункт 1.2 ТЗ v3.0: Строгий порог горизонтальной склейки (0.55 * h_avg) и вертикальной (0.75 * h_avg)
MERGE_HORIZ_FACTOR = 0.55
MERGE_VERT_FACTOR = 0.75
# Строку WinOCR режет только пробел шире кегля строки: так стоят кнопки меню, а не слова фразы.
MERGE_LINE_GAP_FACTOR = 1.0
# Выравнивание по ширине (PDF, Word) растягивает пробелы до 1-2 кеглей, но одинаково по всей строке.
# Такой пробел не разрыв, пока он не шире JUSTIFIED_GAP_SPREAD обычных пробелов этой строки.
JUSTIFIED_GAP_FACTOR = 2.0
JUSTIFIED_GAP_SPREAD = 1.6

# Кадр для WinOCR увеличивается: на мелком тексте сайтов без этого пропадают слова.
WINOCR_UPSCALE = 1.5

# Кадр длиннее этой стороны уменьшается перед RapidOCR пропорционально.
# Порог совпадает с max_side_len движка. Раньше сторона больше 1400 ужималась
# в 0.65: текст 14 px становился девятипиксельным, и слова слипались.
RAPIDOCR_MAX_SIDE = 2000
# Пиксель внутри рамки RapidOCR — чернила, если сумма |BGR - фон| не меньше порога.
# Детектор раздувает рамку (unclip), и кегль по её высоте выходит около 36 px вместо 14.
RAPIDOCR_INK_THRESHOLD = 60
# Пробел, которого нет в тексте строки. Между рамками символов одного слова зазор
# обычно 0–4 px, между словами на выравнивании по ширине — от 8 px.
RAPIDOCR_WORD_GAP_PX = 8
# Потоков ONNX Runtime на кадр. На 16-поточном процессоре шесть потоков занимают около
# 5 ядер, четыре — около 3.5 и на 30% медленнее; остальное достаётся игре и браузеру.
RAPIDOCR_THREADS = max(1, min(4, (os.cpu_count() or 2) // 2))
RAPIDOCR_REC_MODEL_FILE = "en_PP-OCRv4_rec_mobile.onnx"

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
# Игровой режим: плашки гаснут перед снимком, DWM показывает пустой оверлей через 1-3 кадра.
CAPTURE_VEIL_SETTLE_MS = 80
ENABLE_DIAGNOSTIC_LOGS = True


def get_app_base_dir() -> str:
    """Папка рядом с exe или корень проекта: там лежит model_en_ru."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_user_data_dir(base_dir: str) -> str:
    """settings.json и журнал.

    Установщик кладёт exe в Program Files, куда без прав администратора писать нельзя,
    а при удалении программы файлы там остаются. Поэтому сборка пишет в
    %LOCALAPPDATA%\\GhostTranslate, а запуск из исходников — в корень проекта.
    """
    if not getattr(sys, "frozen", False):
        return base_dir
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(root, "GhostTranslate")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return base_dir
    return path


BASE_DIR = get_app_base_dir()
DATA_DIR = get_user_data_dir(BASE_DIR)
LOG_FILE_PATH = os.path.join(DATA_DIR, "ghost_translate.log")
BUNDLE_FILE_PATH = os.path.join(DATA_DIR, "ghost_report_bundle.txt")
SETTINGS_FILE_PATH = os.path.join(DATA_DIR, "settings.json")
LEGACY_SETTINGS_FILE_PATH = os.path.join(BASE_DIR, "settings.json")
# Английская модель распознавания (95 символов) вместо китайской (6625): на 20% быстрее
# и не склеивает слова в заголовках PDF. Нет файла — RapidOCR берёт свою китайскую.
RAPIDOCR_REC_MODEL_PATH = os.path.join(BASE_DIR, "rapidocr_models", RAPIDOCR_REC_MODEL_FILE)
