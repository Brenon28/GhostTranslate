#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GhostTranslate v3.0 — Exact Menu Positioning, FontSettingsPopup, Global F8/F9 Hotkeys & Native CT2 Lite Core
Полная сборка v3.0 (с учетом всех улучшений предыдущих версий и ТЗ на легкий инсталлятор без PyTorch):
1. Точное позиционирование горизонтальных игровых меню и перевод КАПСА (Exact Menu Positioning):
   - Извлечение отдельных слов (word-level boxes) в WinOCR и препроцессор _split_bullet_tokens(raw_boxes),
     разрезающий склеенные буллитами токены ("PLAY•EVENT", "STORE | PROFILE") на независимые боксы с пропорциональным QRect.
   - Строгий порог горизонтальной склейки gap_x <= 0.55 * h_avg: составные фразы ("BATTLE PASS") склеиваются,
     а соседние кнопки меню ("PLAY", "EVENT", "LOADOUTS", "BATTLE PASS", "CHALLENGES", "STORE", "PROFILE")
     остаются строго на своих координатах (x, y, w, h) с центрированием Qt.AlignmentFlag.AlignCenter.
   - Встроенный игровой словарь GAME_UI_DICT (160+ терминов, 0 мс) + нормализация КАПСА (.capitalize() перед CT2).
2. Плавающий кастомайзер шрифта FontSettingsPopup (кнопка "Aa Шрифт" на верхней панели):
   - Гарнитура (Segoe UI, Arial, Tahoma, Verdana, Trebuchet MS, Consolas, Impact), масштаб 60%..180%
     или фиксированный кегль 8..28 pt, Bold, выравнивание и показ/скрытие бирюзовой рамки области + сохранение в settings.json.
3. Глобальные клавиши F8 / F9 (без конфликтов с играми) и удаление старой текстовой плашки над рамкой:
   - F8 (VK_F8 = 0x77): Мгновенное Скрыть / Показать оверлей и панель (мини-таблетка "👻 GT [F8]").
   - F9 (VK_F9 = 0x78): Включение режима выделения области (курсор-крестик, выделение обычной ЛКМ без зажатия клавиш).
   - Двойная регистрация: Win32 RegisterHotKey + опрос GetAsyncKeyState (25 мс) + проверка прав Администратора.
4. Легковесное нативное ядро NativeCT2Translator (БЕЗ torch, argostranslate, stanza, spacy и cv2):
   - Прямой вызов ctranslate2.Translator(..., device="cpu", compute_type="int8", inter_threads=4) + sentencepiece.
   - Авто-распаковка модели в ./model_en_ru из кэша Argos (.argosmodel zip) или рабочей папки .exe.
   - Чистый NumPy + QImage вместо opencv-python (small_gray = np.mean(frame[::8, ::8], axis=2)).
"""

import os
import re
import sys
import json
import time
import shutil
import zipfile
import ctypes
import ctypes.wintypes
import asyncio
import logging
import platform
import threading
from pathlib import Path
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass
from collections import OrderedDict, deque
from difflib import SequenceMatcher
from typing import List, Optional, Dict, Tuple

# Аппаратная поддержка High-DPI мониторов (125%, 150%, 200%) до создания QApplication
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

# Явные прототипы Win32-хоткеев: без argtypes ctypes усекает HWND до 32 бит.
try:
    user32.RegisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL
except Exception:
    pass

try:
    import winsound
except ImportError:
    winsound = None

# Легковесное ядро v3.0: прямой CTranslate2 + SentencePiece (БЕЗ torch и argostranslate!)
# ВАЖНО: импортируется ДО winocr/winrt — иначе конфликт статических символов
# protobuf в winrt-runtime 3.x и sentencepiece вызывает access violation.
try:
    import ctranslate2
    import sentencepiece as spm
    HAS_NATIVE_CT2 = True
except ImportError:
    HAS_NATIVE_CT2 = False

# Нативный Windows 10/11 OCR (~54-84 мс на полном экране)
try:
    import winocr
    from PIL import Image
    HAS_WINOCR = True
except ImportError:
    HAS_WINOCR = False
    try:
        from PIL import Image
    except ImportError:
        Image = None

import numpy as np
import mss

import win32gui
import win32con

try:
    from rapidocr_onnxruntime import RapidOCR
    HAS_RAPIDOCR = True
except ImportError:
    RapidOCR = None
    HAS_RAPIDOCR = False

from PyQt6.QtCore import Qt, QTimer, QRect, QRectF, QPoint, QPointF, pyqtSignal, QThread
from PyQt6.QtGui import (
    QPainter,
    QPainterPath,
    QColor,
    QPen,
    QFont,
    QFontMetrics,
    QImage,
    QPixmap,
    QIcon,
    QAction,
    QLinearGradient,
)
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QPushButton,
    QLabel,
    QSlider,
    QCheckBox,
    QPlainTextEdit,
    QSystemTrayIcon,
    QMenu,
)

# ==============================================================================
# КОНСТАНТЫ И КОНФИГУРАЦИЯ (GHOSTTRANSLATE v3.0)
# ==============================================================================
APP_VERSION = "3.0"
TRANSLATION_ENGINE = "native-ct2:int8-lite"
DEFAULT_OCR_BACKEND = "WinOCR"
DEFAULT_RENDER_STYLE = "wrap_gradient"

# Глобальные клавиши F8 / F9 (не перехватываются играми и не конфликтуют с мышью)
VK_LBUTTON = 0x01
VK_ESCAPE = 0x1B
VK_F8 = 0x77  # Скрыть / Показать оверлей и панель (toggle_visibility)
VK_F9 = 0x78  # Начать выделение области захвата (start_snipping_mode)
HOTKEY_ID_F8 = 9008
HOTKEY_ID_F9 = 9009
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
SEQ_MATCH_THRESHOLD = 0.95
LRU_MAX_SIZE = 2000
MAX_BATCH_BLOCKS = 30
MIN_OCR_SCORE = 0.42
FONT_HEIGHT_RATIO = 0.78

# Пункт 1.2 ТЗ v3.0: Строгий порог горизонтальной склейки (0.55 * h_avg) и вертикальной (0.75 * h_avg)
MERGE_HORIZ_FACTOR = 0.55
MERGE_VERT_FACTOR = 0.75

RAPIDOCR_MAX_SIDE = 1400
RAPIDOCR_DOWNSCALE = 0.65

WDA_EXCLUDEFROMCAPTURE = 0x00000011
ENABLE_SOUND_EFFECTS = True
ENABLE_DIAGNOSTIC_LOGS = True


def get_app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_app_base_dir()
LOG_FILE_PATH = os.path.join(BASE_DIR, "ghost_translate.log")
BUNDLE_FILE_PATH = os.path.join(BASE_DIR, "ghost_report_bundle.txt")
SETTINGS_FILE_PATH = os.path.join(BASE_DIR, "settings.json")

LATIN_REGEX = re.compile(r"[a-zA-Z]{2,}")
BULLET_SPLIT_REGEX = re.compile(r"\s*[•·|/»—]+\s*")
HAS_BULLET_REGEX = re.compile(r"[•·|/»—]")

# ==============================================================================
# ПУНКТ 1.3 ТЗ v3.0: ВСТРОЕННЫЙ СЛОВАРЬ ИГРОВЫХ МЕНЮ И ТЕРМИНОВ (160+ СЛОВ, 0 МС)
# ==============================================================================
GAME_UI_DICT: Dict[str, str] = {
    # Горизонтальные вкладки игровых меню (из реальных скриншотов)
    "play": "ИГРАТЬ",
    "event": "СОБЫТИЕ",
    "events": "СОБЫТИЯ",
    "loadout": "СНАРЯЖЕНИЕ",
    "loadouts": "СНАРЯЖЕНИЕ",
    "battle pass": "БОЕВОЙ ПРОПУСК",
    "challenges": "ИСПЫТАНИЯ",
    "challenge": "ИСПЫТАНИЕ",
    "store": "МАГАЗИН",
    "shop": "МАГАЗИН",
    "profile": "ПРОФИЛЬ",
    "career": "КАРЬЕРА",
    "barracks": "КАЗАРМА",
    "armory": "ОРУЖЕЙНАЯ",
    "operators": "ОПЕРАТИВНИКИ",
    "operator": "ОПЕРАТИВНИК",
    "weapons": "ОРУЖИЕ",
    "weapon": "ОРУЖИЕ",
    "heroes": "ГЕРОИ",
    "hero": "ГЕРОЙ",
    "champions": "ЧЕМПИОНЫ",
    "agents": "АГЕНТЫ",
    "custom": "СВОЯ ИГРА",
    "customize": "КАСТОМИЗАЦИЯ",
    "customization": "ПЕРСОНАЛИЗАЦИЯ",
    "locker": "ШКАФЧИК",
    "collection": "КОЛЛЕКЦИЯ",
    "collections": "КОЛЛЕКЦИИ",
    "clans": "КЛАНЫ",
    "clan": "КЛАН",
    "guild": "ГИЛЬДИЯ",
    "social": "СОЦИАЛЬНОЕ",
    "friends": "ДРУЗЬЯ",
    "party": "ГРУППА",
    "squad": "ОТРЯД",
    "leaderboards": "ТАБЛИЦА ЛИДЕРОВ",
    "leaderboard": "ЛИДЕРЫ",
    "rankings": "РЕЙТИНГ",
    "ranked": "РЕЙТИНГОВАЯ",
    "unranked": "БЕЗ РЕЙТИНГА",
    "casual": "ОБЫЧНАЯ ИГРА",
    "competitive": "СОРЕВНОВАТЕЛЬНЫЙ",
    "tournament": "ТУРНИР",
    "tournaments": "ТУРНИРЫ",
    "replays": "ПОВТОРЫ",
    "watch": "ПРОСМОТР",
    "news": "НОВОСТИ",
    "patch notes": "СПИСОК ИЗМЕНЕНИЙ",
    # Системные разделы и настройки
    "settings": "НАСТРОЙКИ",
    "options": "ОПЦИИ",
    "controls": "УПРАВЛЕНИЕ",
    "keybinds": "КЛАВИШИ",
    "graphics": "ГРАФИКА",
    "video": "ВИДЕО",
    "display": "ЭКРАН",
    "audio": "ЗВУК",
    "sound": "ЗВУК",
    "voice chat": "ГОЛОСОВОЙ ЧАТ",
    "interface": "ИНТЕРФЕЙС",
    "gameplay": "ГЕЙМПЛЕЙ",
    "accessibility": "ДОСТУПНОСТЬ",
    "account": "АККАУНТ",
    "network": "СЕТЬ",
    "credits": "АВТОРЫ",
    "help": "ПОМОЩЬ",
    "tutorials": "ОБУЧЕНИЕ",
    "tutorial": "ОБУЧЕНИЕ",
    "training": "ТРЕНИРОВКА",
    "practice": "ПРАКТИКА",
    "shooting range": "СТРЕЛЬБИЩЕ",
    "campaign": "КАМПАНИЯ",
    "story": "СЮЖЕТ",
    "singleplayer": "ОДИНОЧНАЯ ИГРА",
    "multiplayer": "МУЛЬТИПЛЕЕР",
    "co-op": "КООПЕРАТИВ",
    "cooperative": "КООПЕРАТИВ",
    "custom games": "СВОИ ИГРЫ",
    "server browser": "СПИСОК СЕРВЕРОВ",
    "quick play": "БЫСТРАЯ ИГРА",
    "quick match": "БЫСТРЫЙ МАТЧ",
    "find match": "НАЙТИ МАТЧ",
    "matchmaking": "ПОИСК ИГРЫ",
    "searching": "ПОИСК...",
    "ready": "ГОТОВ",
    "not ready": "НЕ ГОТОВ",
    # Кнопки действий
    "start": "СТАРТ",
    "start game": "НАЧАТЬ ИГРУ",
    "continue": "ПРОДОЛЖИТЬ",
    "resume": "ПРОДОЛЖИТЬ",
    "new game": "НОВАЯ ИГРА",
    "load game": "ЗАГРУЗИТЬ ИГРУ",
    "save game": "СОХРАНИТЬ ИГРУ",
    "save": "СОХРАНИТЬ",
    "load": "ЗАГРУЗИТЬ",
    "back": "НАЗАД",
    "return": "ВЕРНУТЬСЯ",
    "close": "ЗАКРЫТЬ",
    "exit": "ВЫХОД",
    "exit to desktop": "ВЫЙТИ НА РАБОЧИЙ СТОЛ",
    "exit game": "ВЫЙТИ ИЗ ИГРЫ",
    "quit": "ВЫЙТИ",
    "quit game": "ВЫЙТИ ИЗ ИГРЫ",
    "apply": "ПРИМЕНИТЬ",
    "confirm": "ПОДТВЕРДИТЬ",
    "accept": "ПРИНЯТЬ",
    "decline": "ОТКЛОНИТЬ",
    "cancel": "ОТМЕНА",
    "reset": "СБРОСИТЬ",
    "default": "ПО УМОЛЧАНИЮ",
    "defaults": "ПО УМОЛЧАНИЮ",
    "select": "ВЫБРАТЬ",
    "equip": "ЭКИПИРОВАТЬ",
    "equipped": "ЭКИПИРОВАНО",
    "unequip": "СНЯТЬ",
    "equip item": "ЭКИПИРОВАТЬ",
    "drop item": "ВЫБРОСИТЬ",
    "upgrade": "УЛУЧШИТЬ",
    "craft": "СОЗДАТЬ",
    "dismantle": "РАЗОБРАТЬ",
    "buy": "КУПИТЬ",
    "purchase": "КУПИТЬ",
    "sell": "ПРОДАТЬ",
    "claim": "ЗАБРАТЬ",
    "claim reward": "ЗАБРАТЬ НАГРАДУ",
    "claim all": "ЗАБРАТЬ ВСЁ",
    "redeem": "АКТИВИРОВАТЬ",
    "unlock": "РАЗБЛОКИРОВАТЬ",
    "locked": "ЗАБЛОКИРОВАНО",
    "unlocked": "ОТКРЫТО",
    "inspect": "ОСМОТРЕТЬ",
    "preview": "ПРЕДПРОСМОТР",
    "next": "ДАЛЕЕ",
    "previous": "НАЗАД",
    "skip": "ПРОПУСТИТЬ",
    "retry": "ПОВТОРИТЬ",
    "respawn": "ВОЗРОДИТЬСЯ",
    "deploy": "ВЫСАДКА",
    "spectate": "НАБЛЮДАТЬ",
    "invite": "ПРИГЛАСИТЬ",
    "join": "ПРИСОЕДИНИТЬСЯ",
    "leave": "ПОКИНУТЬ",
    # RPG и интерфейс
    "inventory": "ИНВЕНТАРЬ",
    "character": "ПЕРСОНАЖ",
    "skills": "НАВЫКИ",
    "abilities": "СПОСОБНОСТИ",
    "talents": "ТАЛАНТЫ",
    "perks": "ПЕРКИ",
    "attributes": "ХАРАКТЕРИСТИКИ",
    "stats": "СТАТИСТИКА",
    "statistics": "СТАТИСТИКА",
    "quests": "ЗАДАНИЯ",
    "quest log": "ЖУРНАЛ ЗАДАНИЙ",
    "missions": "МИССИИ",
    "mission": "МИССИЯ",
    "objectives": "ЦЕЛИ",
    "map": "КАРТА",
    "world map": "КАРТА МИРА",
    "journal": "ЖУРНАЛ",
    "codex": "КОДЕКС",
    "bestiary": "БЕСТИАРИЙ",
    "achievements": "ДОСТИЖЕНИЯ",
    "trophies": "ТРОФЕИ",
    "rewards": "НАГРАДЫ",
    "daily challenges": "ЕЖЕДНЕВНЫЕ ИСПЫТАНИЯ",
    "weekly challenges": "ЕЖЕНЕДЕЛЬНЫЕ ИСПЫТАНИЯ",
    "season pass": "СЕЗОННЫЙ ПРОПУСК",
    "free": "БЕСПЛАТНО",
    "premium": "ПРЕМИУМ",
    "level": "УРОВЕНЬ",
    "rank": "РАНГ",
    "tier": "УРОВЕНЬ",
    "victory": "ПОБЕДА",
    "defeat": "ПОРАЖЕНИЕ",
    "draw": "НИЧЬЯ",
    "clients and partners": "Клиенты и партнеры",
    "contacts": "Контакты",
    "projects": "Проекты",
    "knowledge base": "База знаний",
    "meetings and calls": "Встречи и звонки",
    "create new project": "Создать проект",
    "export report": "Экспорт отчета",
    "active tasks": "Активные задачи",
    "team members": "Участники команды",
    "ai features": "ИИ-функции",
    "view changes": "Посмотреть изменения",
}


# ==============================================================================
# ЖУРНАЛ ДИАГНОСТИКИ, МЕТРИК СКОРОСТИ И СОХРАНЕНИЯ НАСТРОЕК ШРИФТА
# ==============================================================================
LOG_RING_BUFFER: deque = deque(maxlen=400)
BENCHMARK_STATS: Dict[str, List[int]] = {
    "WinOCR": [],
    "RapidOCR": [],
    "NativeCT2": [],
}

logger = logging.getLogger("GhostTranslate")
logger.setLevel(logging.INFO)

if ENABLE_DIAGNOSTIC_LOGS:
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(file_handler)
    except Exception:
        pass


def log_event(message: str, level: str = "INFO") -> None:
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] [{level}] {message}"
    LOG_RING_BUFFER.append(entry)
    if ENABLE_DIAGNOSTIC_LOGS:
        if level == "ERROR":
            logger.error(message)
        elif level == "WARN":
            logger.warning(message)
        else:
            logger.info(message)


def record_benchmark(category: str, elapsed_ms: int) -> None:
    if category in BENCHMARK_STATS:
        BENCHMARK_STATS[category].append(elapsed_ms)
        if len(BENCHMARK_STATS[category]) > 60:
            BENCHMARK_STATS[category].pop(0)


def format_benchmark_summary() -> str:
    parts = []
    for k, vals in BENCHMARK_STATS.items():
        if vals:
            avg_ms = int(sum(vals) / len(vals))
            parts.append(f"{k}: avg {avg_ms} мс ({len(vals)} зам.)")
        else:
            parts.append(f"{k}: нет замеров")
    return " | ".join(parts)


def is_user_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


@dataclass
class FontCustomConfig:
    font_family: str = "Segoe UI"
    scale_percent: int = 100
    use_fixed_pt: bool = False
    fixed_pt: int = 14
    is_bold: bool = True
    text_align: str = "auto"  # "auto" | "center" | "left"
    show_capture_border: bool = True

    def to_dict(self) -> dict:
        return {
            "font_family": self.font_family,
            "scale_percent": self.scale_percent,
            "use_fixed_pt": self.use_fixed_pt,
            "fixed_pt": self.fixed_pt,
            "is_bold": self.is_bold,
            "text_align": self.text_align,
            "show_capture_border": self.show_capture_border,
        }

    @classmethod
    def load(cls) -> "FontCustomConfig":
        if os.path.exists(SETTINGS_FILE_PATH):
            try:
                with open(SETTINGS_FILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls(
                    font_family=str(data.get("font_family", "Segoe UI")),
                    scale_percent=max(60, min(180, int(data.get("scale_percent", 100)))),
                    use_fixed_pt=bool(data.get("use_fixed_pt", False)),
                    fixed_pt=max(8, min(28, int(data.get("fixed_pt", 14)))),
                    is_bold=bool(data.get("is_bold", True)),
                    text_align=str(data.get("text_align", "auto")),
                    show_capture_border=bool(data.get("show_capture_border", True)),
                )
            except Exception as exc:
                log_event(f"Не удалось прочитать settings.json: {exc}", "WARN")
        return cls()

    def save(self) -> None:
        try:
            with open(SETTINGS_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log_event(f"Не удалось сохранить settings.json: {exc}", "WARN")


# ==============================================================================
# ПУНКТ 4 ТЗ v3.0: НАТИВНОЕ ЯДРО NativeCT2Translator (БЕЗ TORCH И ARGOSTRANSLATE)
# ==============================================================================
class NativeCT2Translator:
    """
    Прямой легковесный движок CTranslate2 + SentencePiece (int8, inter_threads=4).
    Не импортирует torch, argostranslate, stanza или spacy!
    Ищет модель в ./model_en_ru рядом с .exe или автоматически распаковывает её
    из существующего кэша ~/.local/share/argos-translate/packages (.argosmodel zip).
    """

    def __init__(self):
        self.translator: Optional["ctranslate2.Translator"] = None
        self.sp_processor: Optional["spm.SentencePieceProcessor"] = None
        self.model_dir: Optional[str] = None
        self.ready: bool = False

    def _locate_or_extract_model_dir(self) -> Optional[str]:
        candidates = [
            os.path.join(BASE_DIR, "model_en_ru"),
            os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "model_en_ru"),
        ]
        # Проверяем стандартную папку распакованных пакетов Argos Translate
        home = str(Path.home())
        argos_pkg_dir = os.path.join(home, ".local", "share", "argos-translate", "packages")
        if os.path.isdir(argos_pkg_dir):
            for entry in os.listdir(argos_pkg_dir):
                full_entry = os.path.join(argos_pkg_dir, entry)
                if os.path.isdir(full_entry) and ("en_ru" in entry.lower() or "translate-en_ru" in entry.lower()):
                    candidates.append(full_entry)
                    candidates.append(os.path.join(full_entry, "model"))

        for cand in candidates:
            if os.path.isdir(cand):
                model_sub = os.path.join(cand, "model") if os.path.isdir(os.path.join(cand, "model")) else cand
                sp_cand = os.path.join(cand, "sentencepiece.model")
                if not os.path.isfile(sp_cand):
                    sp_cand = os.path.join(model_sub, "sentencepiece.model")
                if os.path.isfile(os.path.join(model_sub, "model.bin")) and os.path.isfile(sp_cand):
                    return cand

        # Если рядом лежит архив .argosmodel/.zip — распаковываем без argostranslate
        for root_search in [BASE_DIR, os.path.join(home, ".local", "share", "argos-translate", "downloads")]:
            if not os.path.isdir(root_search):
                continue
            for fname in os.listdir(root_search):
                if ("en_ru" in fname.lower()) and (fname.endswith(".argosmodel") or fname.endswith(".zip")):
                    archive_path = os.path.join(root_search, fname)
                    target_extract = os.path.join(BASE_DIR, "model_en_ru")
                    try:
                        os.makedirs(target_extract, exist_ok=True)
                        with zipfile.ZipFile(archive_path, "r") as zf:
                            zf.extractall(target_extract)
                        log_event(f"Модель EN->RU распакована напрямую из {archive_path} в {target_extract}")
                        for sub in os.listdir(target_extract):
                            sub_path = os.path.join(target_extract, sub)
                            if os.path.isdir(sub_path):
                                return sub_path
                        return target_extract
                    except Exception as exc:
                        log_event(f"Ошибка распаковки {archive_path}: {exc}", "WARN")
        return None

    def initialize(self) -> None:
        if not HAS_NATIVE_CT2:
            log_event("ctranslate2 / sentencepiece не установлены -> активен быстрый словарь GAME_UI_DICT", "WARN")
            return
        try:
            found_dir = self._locate_or_extract_model_dir()
            if not found_dir:
                log_event(
                    "Папка модели ./model_en_ru не найдена -> активен встроенный словарь GAME_UI_DICT (160+ фраз)",
                    "WARN",
                )
                return

            ct2_dir = os.path.join(found_dir, "model") if os.path.isdir(os.path.join(found_dir, "model")) else found_dir
            sp_path = os.path.join(found_dir, "sentencepiece.model")
            if not os.path.isfile(sp_path):
                sp_path = os.path.join(ct2_dir, "sentencepiece.model")

            self.translator = ctranslate2.Translator(
                ct2_dir,
                device="cpu",
                compute_type="int8",
                inter_threads=4,
            )
            self.sp_processor = spm.SentencePieceProcessor(model_file=sp_path)
            self.model_dir = found_dir
            self.ready = True

            # Прогрев модели в ОЗУ
            _ = self.translate_batch(["System Ready"])
            log_event(f"NativeCT2Translator v3.0 (int8, без PyTorch) загружен из {found_dir}")
        except Exception as exc:
            log_event(f"Предупреждение инициализации NativeCT2Translator: {exc}", "WARN")

    def translate_batch(self, texts: List[str]) -> List[str]:
        """
        Пункт 1.3 и 4.1 ТЗ v3.0:
        1. Очищает буллиты и спецсимволы по краям (•·|—*<>[]).
        2. Мгновенно (0 мс) проверяет игровой словарь GAME_UI_DICT (160+ терминов).
        3. Если строка в КАПСЕ (text.isupper()), переводит её в .capitalize() перед подачей в CTranslate2,
           а результат возвращает в .upper() для коротких заголовков (<= 3 слов).
        4. Переводит оставшиеся фразы единым пакетом через ctranslate2.Translator.translate_batch(beam_size=1).
        """
        if not texts:
            return []

        results: List[Optional[str]] = [None] * len(texts)
        ct2_indices: List[int] = []
        ct2_inputs: List[str] = []
        ct2_restore_upper: List[bool] = []

        for i, raw_txt in enumerate(texts):
            cleaned = raw_txt.strip(" •·|—*<>[]\t\r\n").strip()
            if not cleaned:
                results[i] = raw_txt
                continue

            word_count = len(cleaned.split())
            is_upper_source = cleaned.isupper() and any(ch.isalpha() for ch in cleaned)
            low = cleaned.lower()

            # 1. Мгновенный поиск во встроенном игровом словаре GAME_UI_DICT (0 мс)
            if low in GAME_UI_DICT:
                dict_val = GAME_UI_DICT[low]
                results[i] = dict_val.upper() if (is_upper_source and word_count <= 3) else dict_val
                continue

            # 2. Нормализация КАПСА для нейросети CTranslate2
            norm_input = cleaned.capitalize() if is_upper_source else cleaned
            ct2_indices.append(i)
            ct2_inputs.append(norm_input)
            ct2_restore_upper.append(bool(is_upper_source and word_count <= 3))

        if not ct2_inputs:
            return [r if r is not None else "" for r in results]

        if not self.ready or self.translator is None or self.sp_processor is None:
            for idx_pos, fallback_str, restore_up in zip(ct2_indices, ct2_inputs, ct2_restore_upper):
                results[idx_pos] = fallback_str.upper() if restore_up else fallback_str
            return [r if r is not None else "" for r in results]

        try:
            tokenized_batch = [self.sp_processor.encode(s, out_type=str) for s in ct2_inputs]
            ct2_out = self.translator.translate_batch(
                tokenized_batch,
                beam_size=1,
                max_batch_size=32,
            )
            for idx_pos, hyp, restore_up in zip(ct2_indices, ct2_out, ct2_restore_upper):
                tokens = hyp.hypotheses[0] if hyp.hypotheses else []
                decoded = self.sp_processor.decode(tokens).strip()
                if not decoded:
                    decoded = ct2_inputs[ct2_indices.index(idx_pos)]
                results[idx_pos] = decoded.upper() if restore_up else decoded
        except Exception as exc:
            log_event(f"Ошибка пакетного перевода NativeCT2: {exc}", "WARN")
            for idx_pos, fallback_str in zip(ct2_indices, ct2_inputs):
                results[idx_pos] = fallback_str

        return [r if r is not None else "" for r in results]


_NATIVE_CT2 = NativeCT2Translator()


# ==============================================================================
# ТРЕХНОТНЫЙ ГАРМОНИЧЕСКИЙ ЗВУК ВКЛЮЧЕНИЯ И ЗВУК ВЫКЛЮЧЕНИЯ
# ==============================================================================
def play_startup_sound() -> None:
    if not ENABLE_SOUND_EFFECTS or winsound is None:
        return

    def _beep():
        try:
            winsound.Beep(523, 55)  # C5
            winsound.Beep(659, 55)  # E5
            winsound.Beep(987, 90)  # B5
        except Exception:
            pass

    threading.Thread(target=_beep, daemon=True).start()


def play_shutdown_sound_sync() -> None:
    if not ENABLE_SOUND_EFFECTS or winsound is None:
        return
    try:
        winsound.Beep(784, 60)  # G5
        winsound.Beep(587, 60)  # D5
        winsound.Beep(392, 95)  # G4
    except Exception:
        pass


# ==============================================================================
# СТРУКТУРЫ ДАННЫХ РАСПОЗНАННЫХ СЛОВ И КЛАСТЕРИЗОВАННЫХ БЛОКОВ
# ==============================================================================
@dataclass
class RawWordBox:
    x1: int
    y1: int
    x2: int
    y2: int
    text: str
    score: float
    lines_merged: int = 1
    split_from_bullet: bool = False

    @property
    def width(self) -> int:
        return max(1, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return float(max(1, self.y2 - self.y1))

    @property
    def area(self) -> int:
        return self.width * int(self.height)


@dataclass
class OverlayBlock:
    rect: QRect
    orig_text: str
    trans_text: str
    bg_color: QColor
    bg_color_right: QColor
    fg_color: QColor
    lines_merged: int = 1
    is_pending: bool = True


# ==============================================================================
# LRU-КЭШ НА 2000 ФРАЗ В ОЗУ
# ==============================================================================
class TranslationLRUCache:
    def __init__(self, capacity: int = LRU_MAX_SIZE):
        self.capacity = capacity
        self.cache: OrderedDict[str, str] = OrderedDict()

    def get(self, key: str) -> Optional[str]:
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: str) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def clear(self) -> None:
        self.cache.clear()


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


def _merge_ocr_boxes_into_paragraphs(raw_boxes: List[RawWordBox]) -> List[RawWordBox]:
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

    sorted_words = sorted(split_boxes, key=lambda b: (b.y1, b.x1))
    line_clusters: List[List[RawWordBox]] = []

    for word in sorted_words:
        if not word.text or not word.text.strip():
            continue
        placed_in_line = False
        if not word.split_from_bullet:
            for line in reversed(line_clusters):
                lx1 = min(w.x1 for w in line)
                ly1 = min(w.y1 for w in line)
                lx2 = max(w.x2 for w in line)
                ly2 = max(w.y2 for w in line)
                lh = float(max(1, ly2 - ly1))
                wh = word.height
                h_avg = (lh + wh) / 2.0

                overlap_y = max(0, min(ly2, word.y2) - max(ly1, word.y1))
                horiz_gap = word.x1 - lx2
                height_ratio = max(lh, wh) / max(1.0, min(lh, wh))

                if (
                    overlap_y > 0.50 * h_avg
                    and -6 <= horiz_gap <= MERGE_HORIZ_FACTOR * h_avg
                    and height_ratio <= 1.40
                ):
                    line.append(word)
                    placed_in_line = True
                    break
        if not placed_in_line:
            line_clusters.append([word])

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


# ==============================================================================
# ЧИСТЫЙ NUMPY + QIMAGE БЕЗ OPENCV-PYTHON (cv2)
# ==============================================================================
def compute_small_gray_numpy(img_bgra: np.ndarray) -> np.ndarray:
    """
    Пункт 4.2 ТЗ v3.0: Сверхбыстрое уменьшение кадра для Watchdog 150ms на чистом NumPy
    без импорта тяжелого opencv-python (cv2):
    small_gray = np.mean(frame[::8, ::8, :3], axis=2)
    """
    return np.mean(img_bgra[::8, ::8, :3], axis=2).astype(np.float32)


def downscale_bgr_via_qimage(img_bgra: np.ndarray, scale: float) -> np.ndarray:
    """
    Масштабирование кадра для RapidOCR через встроенный QImage (без cv2).
    """
    h_orig, w_orig = img_bgra.shape[:2]
    new_w = max(64, int(round(w_orig * scale)))
    new_h = max(64, int(round(h_orig * scale)))
    try:
        contiguous = np.ascontiguousarray(img_bgra)
        qimg = QImage(
            contiguous.data,
            w_orig,
            h_orig,
            w_orig * 4,
            QImage.Format.Format_ARGB32,
        )
        scaled_qimg = qimg.scaled(
            new_w,
            new_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).convertToFormat(QImage.Format.Format_ARGB32)
        ptr = scaled_qimg.bits()
        ptr.setsize(new_h * new_w * 4)
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((new_h, new_w, 4)).copy()
        return arr[:, :, :3]
    except Exception:
        row_idx = np.linspace(0, h_orig - 1, new_h).astype(int)
        col_idx = np.linspace(0, w_orig - 1, new_w).astype(int)
        return img_bgra[np.ix_(row_idx, col_idx)][:, :, :3]


def sample_word_background_and_fg(
    img_bgra: np.ndarray, x1: int, y1: int, x2: int, y2: int
) -> Tuple[QColor, QColor, QColor]:
    h_img, w_img = img_bgra.shape[:2]
    if h_img == 0 or w_img == 0:
        fallback_bg = QColor(20, 22, 28, 240)
        return fallback_bg, fallback_bg, QColor("#FFFFFF")

    x1_c = max(0, min(w_img - 1, x1))
    x2_c = max(x1_c + 1, min(w_img, x2))
    y1_c = max(0, min(h_img - 1, y1))
    y2_c = max(y1_c + 1, min(h_img, y2))

    crop = img_bgra[y1_c:y2_c, x1_c:x2_c, :3]  # BGR
    if crop.size == 0:
        fallback_bg = QColor(20, 22, 28, 240)
        return fallback_bg, fallback_bg, QColor("#FFFFFF")

    ch, cw = crop.shape[:2]
    bw = min(2, ch, cw)
    if bw > 0:
        border_pixels = [
            crop[:bw, :, :].reshape(-1, 3),
            crop[-bw:, :, :].reshape(-1, 3),
            crop[:, :bw, :].reshape(-1, 3),
            crop[:, -bw:, :].reshape(-1, 3),
        ]
        samples = np.concatenate(border_pixels, axis=0)
    else:
        samples = crop.reshape(-1, 3)

    if samples.size == 0:
        fallback_bg = QColor(20, 22, 28, 240)
        return fallback_bg, fallback_bg, QColor("#FFFFFF")

    med_bgr = np.median(samples, axis=0)
    b, g, r = int(med_bgr[0]), int(med_bgr[1]), int(med_bgr[2])

    mid_x = max(1, cw // 2)
    right_crop = crop[:, mid_x:, :]
    if right_crop.size > 0:
        med_right = np.median(right_crop.reshape(-1, 3), axis=0)
        br, gr, rr = int(med_right[0]), int(med_right[1]), int(med_right[2])
    else:
        br, gr, rr = b, g, r

    bg_left = QColor(r, g, b, 245)
    bg_right = QColor(rr, gr, br, 245)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    fg_color = QColor("#111111") if luminance > 140 else QColor("#FFFFFF")
    return bg_left, bg_right, fg_color


# ==============================================================================
# ПОТОК РАСПОЗНАВАНИЯ С РАЗБИЕНИЕМ БУЛЛИТОВ И EXACT MENU POSITIONING
# ==============================================================================
class OcrWorkerThread(QThread):
    blocks_ready = pyqtSignal(list, str, int)

    def __init__(
        self,
        ocr_engine,
        ocr_backend: str,
        img_bgra: np.ndarray,
        lru_cache: TranslationLRUCache,
        job_id: int,
        dpi_scale: float = 1.0,
        offset_x: int = 0,
        offset_y: int = 0,
    ):
        super().__init__()
        self.ocr_engine = ocr_engine
        self.ocr_backend = ocr_backend
        self.img_bgra = img_bgra
        self.lru_cache = lru_cache
        self.job_id = job_id
        self.dpi_scale = max(1.0, dpi_scale)
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.applied_scale = 1.0

    def _run_winocr(self) -> List[RawWordBox]:
        """
        Пункт 1.1 ТЗ v3.0: В WinOCR обязательно извлекаем именно отдельные слова (for word in line.words),
        а не целую строку line целиком!
        """
        img_rgb = self.img_bgra[:, :, :3][:, :, ::-1]
        pil_img = Image.fromarray(img_rgb)

        async def _recognize():
            return await winocr.recognize_pil(pil_img, "en")

        res = asyncio.run(_recognize())
        raw_boxes: List[RawWordBox] = []
        for line in getattr(res, "lines", []):
            for word in getattr(line, "words", []):
                txt = getattr(word, "text", "").strip()
                rect = getattr(word, "bounding_rect", None)
                if not txt or rect is None:
                    continue
                x1 = int(rect.x)
                y1 = int(rect.y)
                x2 = int(rect.x + rect.width)
                y2 = int(rect.y + rect.height)
                raw_boxes.append(RawWordBox(x1=x1, y1=y1, x2=x2, y2=y2, text=txt, score=0.95))
        return raw_boxes

    def _run_rapidocr(self) -> List[RawWordBox]:
        if self.ocr_engine is None:
            return []
        h_orig, w_orig = self.img_bgra.shape[:2]
        scale = 1.0

        if max(w_orig, h_orig) > RAPIDOCR_MAX_SIDE:
            scale = RAPIDOCR_DOWNSCALE
            self.applied_scale = scale
            img_input = downscale_bgr_via_qimage(self.img_bgra, scale)
        else:
            img_input = self.img_bgra[:, :, :3]

        ocr_result, _ = self.ocr_engine(
            img_input,
            use_det=True,
            use_cls=False,
            use_rec=True,
            box_thresh=0.35,
            unclip_ratio=1.8,
        )
        raw_boxes: List[RawWordBox] = []
        if not ocr_result:
            return raw_boxes

        inv_scale = 1.0 / scale
        for item in ocr_result:
            box, text, score = item[0], item[1].strip(), float(item[2])
            if score < MIN_OCR_SCORE or not text:
                continue
            xs = [pt[0] * inv_scale for pt in box]
            ys = [pt[1] * inv_scale for pt in box]
            raw_boxes.append(
                RawWordBox(
                    x1=int(round(min(xs))),
                    y1=int(round(min(ys))),
                    x2=int(round(max(xs))),
                    y2=int(round(max(ys))),
                    text=text,
                    score=score,
                )
            )
        return raw_boxes

    def run(self):
        t0 = time.perf_counter()
        used_backend = self.ocr_backend
        try:
            if self.ocr_backend == "WinOCR":
                if HAS_WINOCR:
                    raw_boxes = self._run_winocr()
                else:
                    log_event("winocr не установлен -> авто-откат на RapidOCR", "WARN")
                    used_backend = "RapidOCR"
                    raw_boxes = self._run_rapidocr()
            else:
                raw_boxes = self._run_rapidocr()
        except Exception as exc:
            log_event(f"Ошибка OCR ({used_backend}, job #{self.job_id}): {exc}", "ERROR")
            self.blocks_ready.emit([], "", self.job_id)
            return

        if not raw_boxes:
            self.blocks_ready.emit([], "", self.job_id)
            return

        # Пункт 1.1 и 1.2 ТЗ v3.0: Разбиение буллитов + Exact Menu Positioning
        paragraph_boxes = _merge_ocr_boxes_into_paragraphs(raw_boxes)

        valid_paragraphs: List[RawWordBox] = []
        skipped_noise_or_ru = 0
        for pb in paragraph_boxes:
            if not is_valid_english_box(pb.text):
                skipped_noise_or_ru += 1
                continue
            valid_paragraphs.append(pb)

        if len(valid_paragraphs) > MAX_BATCH_BLOCKS:
            valid_paragraphs.sort(key=lambda b: b.area, reverse=True)
            valid_paragraphs = valid_paragraphs[:MAX_BATCH_BLOCKS]
            valid_paragraphs.sort(key=lambda b: (b.y1, b.x1))

        blocks: List[OverlayBlock] = []
        orig_lines: List[str] = []

        for mb in valid_paragraphs:
            bg_left, bg_right, fg_color = sample_word_background_and_fg(
                self.img_bgra, mb.x1, mb.y1, mb.x2, mb.y2
            )

            lx = self.offset_x + int(round(mb.x1 / self.dpi_scale))
            ly = self.offset_y + int(round(mb.y1 / self.dpi_scale))
            lw = max(16, int(round((mb.x2 - mb.x1) / self.dpi_scale)))
            lh = max(14, int(round((mb.y2 - mb.y1) / self.dpi_scale)))

            # Проверяем LRU-кэш или мгновенный словарь GAME_UI_DICT (0 мс)
            cleaned_key = mb.text.strip(" •·|—*<>[]").strip()
            low_key = cleaned_key.lower()
            cached = self.lru_cache.get(mb.text)
            if cached is None and low_key in GAME_UI_DICT:
                dict_val = GAME_UI_DICT[low_key]
                cached = dict_val.upper() if (cleaned_key.isupper() and len(cleaned_key.split()) <= 3) else dict_val
                self.lru_cache.put(mb.text, cached)

            blocks.append(
                OverlayBlock(
                    rect=QRect(lx, ly, lw, lh),
                    orig_text=mb.text,
                    trans_text=cached if cached else mb.text,
                    bg_color=bg_left,
                    bg_color_right=bg_right,
                    fg_color=fg_color,
                    lines_merged=mb.lines_merged,
                    is_pending=(cached is None),
                )
            )
            orig_lines.append(mb.text)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        record_benchmark(used_backend, elapsed_ms)
        scale_info = f" scale={self.applied_scale:.2f}" if self.applied_scale < 1.0 else ""
        log_event(
            f"[OCR_BENCHMARK] backend={used_backend}{scale_info} job=#{self.job_id} time={elapsed_ms} мс | "
            f"слов={len(raw_boxes)} -> блоков={len(blocks)} (отсечено мусора/RU={skipped_noise_or_ru})"
        )
        self.blocks_ready.emit(blocks, "\n".join(orig_lines), self.job_id)


# ==============================================================================
# ПАКЕТНЫЙ ПОТОК ПЕРЕВОДА НАТИВНОГО ЯДРА CTRANSLATE2 (NativeCT2TranslationWorker)
# ==============================================================================
class NativeCT2TranslationWorker(QThread):
    batch_translated = pyqtSignal(list, int)
    batch_finished = pyqtSignal(int)

    def __init__(self, pending_map: Dict[int, str], job_id: int):
        super().__init__()
        self.pending_map = pending_map
        self.job_id = job_id
        self._abort = False

    def stop(self):
        self._abort = True

    def run(self):
        if not self.pending_map or self._abort:
            self.batch_finished.emit(self.job_id)
            return

        t0 = time.perf_counter()
        indices = list(self.pending_map.keys())
        orig_texts = [self.pending_map[i] for i in indices]

        translated_texts = _NATIVE_CT2.translate_batch(orig_texts)
        if self._abort:
            self.batch_finished.emit(self.job_id)
            return

        pairs: List[Tuple[int, str, str]] = []
        for idx, orig_str, tr_str in zip(indices, orig_texts, translated_texts):
            pairs.append((idx, orig_str, tr_str))

        elapsed_ms = max(1, int((time.perf_counter() - t0) * 1000))
        record_benchmark("NativeCT2", elapsed_ms)
        log_event(
            f"[TRANSLATE_BENCHMARK] engine={TRANSLATION_ENGINE} job=#{self.job_id} time={elapsed_ms} мс | "
            f"пакет={len(pairs)} блоков"
        )
        self.batch_translated.emit(pairs, self.job_id)
        self.batch_finished.emit(self.job_id)


# ==============================================================================
# ПУНКТ 2 ТЗ v3.0: ПЛАВАЮЩИЙ ПОПАП НАСТРОЙКИ ШРИФТА (FontSettingsPopup "Aa Шрифт")
# ==============================================================================
class FontSettingsPopup(QWidget):
    settings_changed = pyqtSignal()

    def __init__(self, font_cfg: FontCustomConfig, parent=None):
        super().__init__(parent)
        self.font_cfg = font_cfg
        self.setWindowTitle("GhostTranslate v3.0 — Настройка шрифта Aa")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget(self)
        card.setObjectName("FontPopupCard")
        card.setStyleSheet(
            """
            QWidget#FontPopupCard {
                background-color: rgba(13, 17, 26, 248);
                border: 1px solid rgba(0, 229, 255, 0.65);
                border-radius: 10px;
            }
            QLabel {
                color: #D8DEE9;
                font-family: "Segoe UI";
                font-size: 12px;
            }
            QComboBox, QPushButton {
                background-color: #171E2E;
                color: #D8DEE9;
                border: 1px solid #263147;
                border-radius: 5px;
                padding: 4px 8px;
                font-family: "Segoe UI";
                font-size: 12px;
            }
            QComboBox:hover, QPushButton:hover {
                border-color: #00E5FF;
                color: #00E5FF;
            }
            QCheckBox {
                color: #D8DEE9;
                font-family: "Segoe UI";
                font-size: 12px;
                spacing: 6px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Заголовок попапа
        hdr = QHBoxLayout()
        title = QLabel("Aa Настройка шрифта и рамки (v3.0)", card)
        title.setStyleSheet("color: #00E5FF; font-weight: 700; font-size: 12px;")
        btn_close = QPushButton("✕", card)
        btn_close.setFixedWidth(26)
        btn_close.clicked.connect(self.hide)
        hdr.addWidget(title)
        hdr.addStretch(1)
        hdr.addWidget(btn_close)
        layout.addLayout(hdr)

        # 1. Выбор гарнитуры
        row_fam = QHBoxLayout()
        row_fam.addWidget(QLabel("Гарнитура:", card))
        self.combo_family = QComboBox(card)
        self.combo_family.addItems(FONT_FAMILIES)
        self.combo_family.setCurrentText(self.font_cfg.font_family)
        self.combo_family.currentTextChanged.connect(self._on_family_changed)
        row_fam.addWidget(self.combo_family, 1)
        layout.addLayout(row_fam)

        # 2. Масштаб размера (60% .. 180%) с кнопками - / +
        row_scale = QHBoxLayout()
        self.lbl_scale = QLabel(f"Масштаб: {self.font_cfg.scale_percent}%", card)
        btn_minus = QPushButton("−10%", card)
        btn_plus = QPushButton("+10%", card)
        btn_minus.clicked.connect(lambda: self._step_scale(-10))
        btn_plus.clicked.connect(lambda: self._step_scale(10))
        row_scale.addWidget(self.lbl_scale)
        row_scale.addStretch(1)
        row_scale.addWidget(btn_minus)
        row_scale.addWidget(btn_plus)
        layout.addLayout(row_scale)

        self.slider_scale = QSlider(Qt.Orientation.Horizontal, card)
        self.slider_scale.setRange(60, 180)
        self.slider_scale.setSingleStep(10)
        self.slider_scale.setPageStep(10)
        self.slider_scale.setValue(self.font_cfg.scale_percent)
        self.slider_scale.valueChanged.connect(self._on_scale_slider)
        layout.addWidget(self.slider_scale)

        # 3. Фиксированный размер (8 pt .. 28 pt)
        row_fixed = QHBoxLayout()
        self.chk_fixed = QCheckBox("Фиксированный размер (pt):", card)
        self.chk_fixed.setChecked(self.font_cfg.use_fixed_pt)
        self.chk_fixed.toggled.connect(self._on_fixed_toggled)
        self.combo_pt = QComboBox(card)
        for pt_val in range(8, 29, 2):
            self.combo_pt.addItem(f"{pt_val} pt", pt_val)
        idx_pt = max(0, (self.font_cfg.fixed_pt - 8) // 2)
        self.combo_pt.setCurrentIndex(idx_pt)
        self.combo_pt.currentIndexChanged.connect(self._on_fixed_pt_changed)
        row_fixed.addWidget(self.chk_fixed)
        row_fixed.addWidget(self.combo_pt)
        layout.addLayout(row_fixed)

        # 4. Выравнивание текста внутри плашек
        row_align = QHBoxLayout()
        row_align.addWidget(QLabel("Выравнивание:", card))
        self.combo_align = QComboBox(card)
        self.combo_align.addItem("Авто (Кнопки — Центр, Абзацы — Слева)", "auto")
        self.combo_align.addItem("Всегда по центру (AlignCenter)", "center")
        self.combo_align.addItem("Всегда по левому краю (AlignLeft)", "left")
        align_map = {"auto": 0, "center": 1, "left": 2}
        self.combo_align.setCurrentIndex(align_map.get(self.font_cfg.text_align, 0))
        self.combo_align.currentIndexChanged.connect(self._on_align_changed)
        row_align.addWidget(self.combo_align, 1)
        layout.addLayout(row_align)

        # 5. Чекбоксы Жирный шрифт (Bold) и Показ бирюзовой рамки захвата
        self.chk_bold = QCheckBox("Жирный шрифт (Bold)", card)
        self.chk_bold.setChecked(self.font_cfg.is_bold)
        self.chk_bold.toggled.connect(self._on_bold_toggled)
        layout.addWidget(self.chk_bold)

        self.chk_border = QCheckBox("Показывать бирюзовую рамку выделенной зоны", card)
        self.chk_border.setChecked(self.font_cfg.show_capture_border)
        self.chk_border.toggled.connect(self._on_border_toggled)
        layout.addWidget(self.chk_border)

        outer.addWidget(card)
        self.adjustSize()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    def _emit_and_save(self):
        self.font_cfg.save()
        self.settings_changed.emit()

    def _on_family_changed(self, fam: str):
        self.font_cfg.font_family = fam
        self._emit_and_save()

    def _step_scale(self, delta: int):
        next_val = max(60, min(180, self.font_cfg.scale_percent + delta))
        self.slider_scale.setValue(next_val)

    def _on_scale_slider(self, val: int):
        snapped = int(round(val / 10.0) * 10)
        self.font_cfg.scale_percent = max(60, min(180, snapped))
        self.lbl_scale.setText(f"Масштаб: {self.font_cfg.scale_percent}%")
        self._emit_and_save()

    def _on_fixed_toggled(self, checked: bool):
        self.font_cfg.use_fixed_pt = checked
        self._emit_and_save()

    def _on_fixed_pt_changed(self, _idx: int):
        val = self.combo_pt.currentData()
        if val is not None:
            self.font_cfg.fixed_pt = int(val)
            self._emit_and_save()

    def _on_align_changed(self, _idx: int):
        val = self.combo_align.currentData()
        if val:
            self.font_cfg.text_align = str(val)
            self._emit_and_save()

    def _on_bold_toggled(self, checked: bool):
        self.font_cfg.is_bold = checked
        self._emit_and_save()

    def _on_border_toggled(self, checked: bool):
        self.font_cfg.show_capture_border = checked
        self._emit_and_save()


# ==============================================================================
# МОДАЛЬНОЕ ОКНО ЖИВЫХ ЛОГОВ И БЕНЧМАРКА (LogViewerDialog v3.0)
# ==============================================================================
class LogViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GhostTranslate v3.0 — Журнал работы и бенчмарк")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(760, 440)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #0D111A;
                color: #D8DEE9;
            }
            QLabel {
                color: #00E5FF;
                font-family: "Consolas", monospace;
                font-size: 12px;
                font-weight: 600;
            }
            QPlainTextEdit {
                background-color: #080B10;
                color: #D8DEE9;
                border: 1px solid #1E2638;
                border-radius: 6px;
                font-family: "Consolas", monospace;
                font-size: 11px;
                padding: 8px;
            }
            QPushButton {
                background-color: #171E2E;
                color: #D8DEE9;
                border: 1px solid #263147;
                border-radius: 5px;
                padding: 5px 12px;
                font-family: "Segoe UI";
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                border-color: #00E5FF;
                color: #00E5FF;
            }
            """
        )

        layout = QVBoxLayout(self)
        self.stats_label = QLabel("", self)
        layout.addWidget(self.stats_label)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        btn_row = QHBoxLayout()
        self.btn_copy = QPushButton("Скопировать отчет в буфер", self)
        self.btn_bundle = QPushButton("Сохранить бандл (ghost_report_bundle.txt)", self)
        self.btn_clear = QPushButton("Очистить журнал", self)
        btn_row.addWidget(self.btn_copy)
        btn_row.addWidget(self.btn_bundle)
        btn_row.addWidget(self.btn_clear)
        layout.addLayout(btn_row)

        self.btn_clear.clicked.connect(self._on_clear)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass
        self.refresh_view()

    def refresh_view(self):
        self.stats_label.setText(f"Сводка скорости v3.0: {format_benchmark_summary()}")
        self.text_edit.setPlainText("\n".join(LOG_RING_BUFFER))
        sb = self.text_edit.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _on_clear(self):
        LOG_RING_BUFFER.clear()
        for k in BENCHMARK_STATS:
            BENCHMARK_STATS[k].clear()
        log_event("Журнал и метрики бенчмарка очищены пользователем")
        self.refresh_view()


# ==============================================================================
# ОКНО ВЫДЕЛЕНИЯ ОБЛАСТИ ПО КЛАВИШЕ F9 (Обычной ЛКМ без зажатия модификаторов)
# ==============================================================================
class SnippingRubberBand(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(0, 229, 255, 235))
        pen.setWidthF(1.8)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(138, 92, 245, 38))
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))


# ==============================================================================
# ПУНКТ 3.2 ТЗ v3.0: МИНИ-ТАБЛЕТКА МАЯЧОК MiniRestorePill ("👻 GT [F8]")
# ==============================================================================
class MiniRestorePill(QWidget):
    restore_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GhostTranslate Mini Pill v3.0")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.btn = QPushButton("👻 GT [F8]", self)
        self.btn.setToolTip("Нажмите F8 или кликните сюда, чтобы вернуть панель и перевод")
        self.btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(15, 17, 23, 215);
                color: #00E5FF;
                border: 1px solid rgba(0, 229, 255, 0.60);
                border-radius: 11px;
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 700;
                padding: 3px 10px;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.22);
                border-color: #00E5FF;
                color: #FFFFFF;
            }
            """
        )
        self.btn.clicked.connect(self.restore_clicked.emit)
        layout.addWidget(self.btn)
        self.adjustSize()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass
        screen_geom = QApplication.primaryScreen().geometry()
        self.move(screen_geom.width() - self.width() - 18, 12)


# ==============================================================================
# ПЛАВАЮЩАЯ ПАНЕЛЬ FLOATING TOOLBAR v3.0 (С КНОПКОЙ "Aa Шрифт" И ХОТКЕЯМИ F8/F9)
# ==============================================================================
class FloatingToolbar(QWidget):
    fullscreen_clicked = pyqtSignal()
    region_snip_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    ocr_backend_toggled = pyqtSignal(str)
    render_style_changed = pyqtSignal(str)
    font_popup_toggled = pyqtSignal()
    timer_changed = pyqtSignal(str)
    hide_toggle_clicked = pyqtSignal()
    logs_clicked = pyqtSignal()
    exit_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GhostTranslate Toolbar v3.0")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._drag_offset: Optional[QPoint] = None
        self.is_collapsed = False
        self.current_ocr = DEFAULT_OCR_BACKEND
        self.current_style = DEFAULT_RENDER_STYLE

        self.collapse_timer = QTimer(self)
        self.collapse_timer.setSingleShot(True)
        self.collapse_timer.timeout.connect(self._collapse_to_edge)

        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 4)
        layout.setSpacing(0)

        self.setStyleSheet(
            """
            QWidget#ExpandedBar {
                background-color: rgba(15, 17, 23, 244);
                border: 1px solid rgba(0, 229, 255, 0.55);
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QWidget#CollapsedTab {
                background-color: rgba(15, 17, 23, 185);
                border: 1px solid rgba(0, 229, 255, 0.45);
                border-top: none;
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QPushButton, QComboBox {
                background-color: rgba(255, 255, 255, 0.07);
                color: #D8DEE9;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 5px;
                font-family: "Segoe UI";
                font-size: 12px;
                font-weight: 500;
                padding: 3px 8px;
                min-height: 22px;
            }
            QPushButton:hover, QComboBox:hover {
                border-color: #00E5FF;
                color: #00E5FF;
            }
            QPushButton#PrimaryBtn {
                background-color: #00E5FF;
                color: #0B0E14;
                border-color: #00E5FF;
                font-weight: 600;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #33ECFF;
            }
            QPushButton#SwitchBtn {
                background-color: rgba(0, 229, 255, 0.12);
                color: #00E5FF;
                border: 1px solid rgba(0, 229, 255, 0.40);
                font-weight: 600;
            }
            QPushButton#FontBtn {
                background-color: rgba(138, 92, 245, 0.18);
                color: #C4B5FD;
                border: 1px solid rgba(138, 92, 245, 0.55);
                font-weight: 600;
            }
            QPushButton#FontBtn:hover {
                border-color: #00E5FF;
                color: #FFFFFF;
            }
            QPushButton#StopBtnActive {
                background-color: rgba(255, 82, 82, 0.22);
                color: #FF5252;
                border: 1px solid #FF5252;
                font-weight: 600;
            }
            QPushButton#StopBtnActive:hover {
                background-color: #FF5252;
                color: #FFFFFF;
            }
            QPushButton#CloseBtn {
                background-color: rgba(239, 68, 68, 0.18);
                color: #F87171;
                border: 1px solid rgba(239, 68, 68, 0.45);
                font-weight: 700;
                padding: 3px 7px;
            }
            QPushButton#CloseBtn:hover {
                background-color: #EF4444;
                color: #FFFFFF;
            }
            """
        )

        self.collapsed_widget = QWidget(self)
        self.collapsed_widget.setObjectName("CollapsedTab")
        col_layout = QHBoxLayout(self.collapsed_widget)
        col_layout.setContentsMargins(14, 2, 14, 3)
        col_lbl = QLabel("GhostTranslate v3.0 · F8: Скрыть · F9: Область", self.collapsed_widget)
        col_lbl.setStyleSheet("color: #00E5FF; font-size: 10px; font-weight: 600;")
        col_layout.addWidget(col_lbl)
        self.collapsed_widget.hide()

        self.expanded_widget = QWidget(self)
        self.expanded_widget.setObjectName("ExpandedBar")
        c_layout = QHBoxLayout(self.expanded_widget)
        c_layout.setContentsMargins(10, 5, 10, 5)
        c_layout.setSpacing(5)

        title_lbl = QLabel("GhostTranslate v3.0", self.expanded_widget)
        title_lbl.setStyleSheet("color: #00E5FF; font-weight: 700; font-size: 12px; padding-right: 2px;")
        c_layout.addWidget(title_lbl)

        self.btn_fullscreen = QPushButton("Весь экран", self.expanded_widget)
        self.btn_fullscreen.setObjectName("PrimaryBtn")
        self.btn_fullscreen.setToolTip("Перевести весь экран в 1 клик")
        self.btn_fullscreen.clicked.connect(self.fullscreen_clicked.emit)
        c_layout.addWidget(self.btn_fullscreen)

        self.btn_region = QPushButton("Область [F9]", self.expanded_widget)
        self.btn_region.setToolTip("Нажмите F9 или кнопку, затем выделите зону обычной ЛКМ")
        self.btn_region.clicked.connect(self.region_snip_clicked.emit)
        c_layout.addWidget(self.btn_region)

        self.btn_stop = QPushButton("Стоп", self.expanded_widget)
        self.btn_stop.setToolTip("Остановить таймер, прервать перевод и очистить плашки")
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        c_layout.addWidget(self.btn_stop)

        self.btn_ocr_toggle = QPushButton(f"OCR: {self.current_ocr}", self.expanded_widget)
        self.btn_ocr_toggle.setObjectName("SwitchBtn")
        self.btn_ocr_toggle.setToolTip("Переключить движок распознавания: WinOCR (пословный) <-> RapidOCR")
        self.btn_ocr_toggle.clicked.connect(self._on_toggle_ocr)
        c_layout.addWidget(self.btn_ocr_toggle)

        self.style_combo = QComboBox(self.expanded_widget)
        self.style_combo.setToolTip("Выбор одного из 6 визуальных режимов отрисовки плашек")
        for _, label in PLAQUE_STYLES:
            self.style_combo.addItem(label)
        default_label = STYLE_ID_TO_LABEL.get(self.current_style, PLAQUE_STYLES[0][1])
        self.style_combo.setCurrentText(default_label)
        self.style_combo.currentTextChanged.connect(self._on_style_combo_changed)
        c_layout.addWidget(self.style_combo)

        # Пункт 2.1 ТЗ v3.0: Кнопка «Aa Шрифт» для открытия FontSettingsPopup
        self.btn_font = QPushButton("Aa Шрифт", self.expanded_widget)
        self.btn_font.setObjectName("FontBtn")
        self.btn_font.setToolTip("Открыть плашку настройки шрифта (гарнитура, масштаб 60%–180%, Bold, рамка)")
        self.btn_font.clicked.connect(self.font_popup_toggled.emit)
        c_layout.addWidget(self.btn_font)

        self.timer_combo = QComboBox(self.expanded_widget)
        self.timer_combo.addItems(TIMER_OPTIONS)
        self.timer_combo.currentTextChanged.connect(self.timer_changed.emit)
        c_layout.addWidget(self.timer_combo)

        self.btn_clear = QPushButton("Скрыть [F8]", self.expanded_widget)
        self.btn_clear.setToolTip("Скрыть / Показать панель и плашки (Глобальная клавиша F8)")
        self.btn_clear.clicked.connect(self.hide_toggle_clicked.emit)
        c_layout.addWidget(self.btn_clear)

        self.btn_logs = QPushButton("Логи", self.expanded_widget)
        self.btn_logs.setToolTip("Открыть живое окно логов и замеров скорости")
        self.btn_logs.clicked.connect(self.logs_clicked.emit)
        c_layout.addWidget(self.btn_logs)

        self.btn_close = QPushButton("[X]", self.expanded_widget)
        self.btn_close.setObjectName("CloseBtn")
        self.btn_close.setToolTip("Полное закрытие программы и выгрузка процесса")
        self.btn_close.clicked.connect(self.exit_clicked.emit)
        c_layout.addWidget(self.btn_close)

        layout.addWidget(self.collapsed_widget)
        layout.addWidget(self.expanded_widget)
        self._recenter_at_top()

    def _on_toggle_ocr(self):
        self.current_ocr = "RapidOCR" if self.current_ocr == "WinOCR" else "WinOCR"
        self.btn_ocr_toggle.setText(f"OCR: {self.current_ocr}")
        self._recenter_at_top()
        self.ocr_backend_toggled.emit(self.current_ocr)

    def _on_style_combo_changed(self, label_text: str):
        style_id = STYLE_LABEL_TO_ID.get(label_text, "wrap_gradient")
        self.current_style = style_id
        self.render_style_changed.emit(style_id)

    def set_stop_active(self, active: bool):
        self.btn_stop.setObjectName("StopBtnActive" if active else "")
        self.btn_stop.style().unpolish(self.btn_stop)
        self.btn_stop.style().polish(self.btn_stop)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    def _recenter_at_top(self):
        self.adjustSize()
        screen_geom = QApplication.primaryScreen().geometry()
        self.move((screen_geom.width() - self.width()) // 2, 0)

    def _collapse_to_edge(self):
        if self.style_combo.view().isVisible() or self.timer_combo.view().isVisible():
            return
        self.is_collapsed = True
        self.expanded_widget.hide()
        self.collapsed_widget.show()
        self._recenter_at_top()

    def _expand_from_edge(self):
        self.collapse_timer.stop()
        if self.is_collapsed:
            self.is_collapsed = False
            self.collapsed_widget.hide()
            self.expanded_widget.show()
            self._recenter_at_top()

    def enterEvent(self, event):
        self._expand_from_edge()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.collapse_timer.start(650)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None


# ==============================================================================
# ПРОЗРАЧНОЕ AR-ПОЛОТНО v3.0 (EXACT MENU POSITIONING, F8/F9 HOTKEYS, FONT POPUP)
# ==============================================================================
class GhostARCanvasWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GhostTranslate AR Canvas v3.0")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        screen_rect = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_rect)

        self.overlay_blocks: List[OverlayBlock] = []
        self.active_region_rect: Optional[QRect] = None
        self.ocr_backend: str = DEFAULT_OCR_BACKEND
        self.plaque_render_mode: str = DEFAULT_RENDER_STYLE
        self.font_cfg: FontCustomConfig = FontCustomConfig.load()
        self.job_id: int = 0
        self.monitor_interval_ms: int = 0

        self.pipeline_busy: bool = False
        self.pending_rescan: bool = False
        self.is_hidden: bool = False

        self.sct = mss.mss()
        self._last_grab_warn_ts: float = 0.0
        self.ocr_engine = RapidOCR() if HAS_RAPIDOCR else None
        self.lru_cache = TranslationLRUCache(LRU_MAX_SIZE)

        threading.Thread(target=_NATIVE_CT2.initialize, daemon=True).start()

        self.prev_small_gray: Optional[np.ndarray] = None
        self.last_translated_small_gray: Optional[np.ndarray] = None
        self.prev_ocr_signature: str = ""

        self.ocr_thread: Optional[OcrWorkerThread] = None
        self.trans_thread: Optional[NativeCT2TranslationWorker] = None

        self.monitor_timer = QTimer(self)
        self.monitor_timer.setSingleShot(True)
        self.monitor_timer.timeout.connect(self.on_auto_monitor_tick)

        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.setInterval(150)
        self.watchdog_timer.timeout.connect(self.on_watchdog_tick)

        self.snip_band = SnippingRubberBand()
        self.snip_origin = QPoint(0, 0)
        self.manual_snip_armed = False
        self._is_selecting_region = False

        # Пункт 3.2 ТЗ v3.0: Мини-таблетка маячок при скрытии по F8
        self.mini_pill = MiniRestorePill()
        self.mini_pill.restore_clicked.connect(self.toggle_visibility)

        # Пункт 2 ТЗ v3.0: Плавающий попап настройки шрифта Aa
        self.font_popup = FontSettingsPopup(self.font_cfg)
        self.font_popup.settings_changed.connect(self._on_font_settings_updated)

        self.log_dialog = LogViewerDialog(self)
        self.log_dialog.btn_copy.clicked.connect(self.export_and_copy_logs)
        self.log_dialog.btn_bundle.clicked.connect(self.save_diagnostic_bundle)

        self.toolbar = FloatingToolbar()
        self.toolbar.fullscreen_clicked.connect(self.capture_full_screen)
        self.toolbar.region_snip_clicked.connect(self.start_snipping_mode)
        self.toolbar.stop_clicked.connect(self.stop_translation_and_clear)
        self.toolbar.ocr_backend_toggled.connect(self.set_ocr_backend)
        self.toolbar.render_style_changed.connect(self.set_render_style)
        self.toolbar.font_popup_toggled.connect(self.toggle_font_popup)
        self.toolbar.timer_changed.connect(self.set_timer_interval)
        self.toolbar.hide_toggle_clicked.connect(self.toggle_visibility)
        self.toolbar.logs_clicked.connect(self.show_logs_modal)
        self.toolbar.exit_clicked.connect(self.emergency_shutdown)
        self.toolbar.show()

        self._init_tray_icon()
        self._register_global_f8_f9_hotkeys()
        self._init_win32_input_poller()

        admin_status = "ДА (Оверлей поверх игр активен)" if is_user_admin() else "НЕТ (Рекомендуется запуск от Админа)"
        log_event(
            f"GhostTranslate v3.0 запущен (Движок={TRANSLATION_ENGINE}, OCR={self.ocr_backend}, "
            f"Хоткеи=F8/F9, Админ={admin_status})"
        )
        play_startup_sound()

    def _init_tray_icon(self):
        pix = QPixmap(16, 16)
        pix.fill(QColor("#00E5FF"))
        self.tray = QSystemTrayIcon(QIcon(pix), self)
        self.tray.setToolTip("GhostTranslate AR v3.0 (F8: Скрыть/Показать · F9: Область)")
        menu = QMenu()
        act_full = QAction("Перевести весь экран", self)
        act_full.triggered.connect(self.capture_full_screen)
        act_snip = QAction("Выделить область (F9)", self)
        act_snip.triggered.connect(self.start_snipping_mode)
        act_toggle = QAction("Скрыть / Показать (F8)", self)
        act_toggle.triggered.connect(self.toggle_visibility)
        act_font = QAction("Настройка шрифта (Aa Шрифт)", self)
        act_font.triggered.connect(self.toggle_font_popup)
        act_stop = QAction("Стоп и очистить", self)
        act_stop.triggered.connect(self.stop_translation_and_clear)
        act_logs = QAction("Открыть журнал и бенчмарк", self)
        act_logs.triggered.connect(self.show_logs_modal)
        act_exit = QAction("Полный выход [X]", self)
        act_exit.triggered.connect(self.emergency_shutdown)
        menu.addAction(act_full)
        menu.addAction(act_snip)
        menu.addAction(act_toggle)
        menu.addAction(act_font)
        menu.addAction(act_stop)
        menu.addAction(act_logs)
        menu.addSeparator()
        menu.addAction(act_exit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def toggle_font_popup(self):
        if self.font_popup.isVisible():
            self.font_popup.hide()
        else:
            tb_geom = self.toolbar.geometry()
            x = tb_geom.x() + max(0, (tb_geom.width() - self.font_popup.width()) // 2)
            y = tb_geom.bottom() + 6
            self.font_popup.move(x, y)
            self.font_popup.show()
            self.font_popup.raise_()

    def _on_font_settings_updated(self):
        # Пункт 2.2 ТЗ v3.0: Мгновенное живое превью на текущих плашках без повторного OCR
        self.update()

    def _dpi_ratio(self) -> float:
        screen = self.screen() or QApplication.primaryScreen()
        return float(screen.devicePixelRatio()) if screen else 1.0

    def _phys_to_log(self, x: int, y: int) -> QPoint:
        r = self._dpi_ratio()
        return QPoint(int(round(x / r)), int(round(y / r)))

    def _active_capture_mss_region(self) -> Dict[str, int]:
        r = self._dpi_ratio()
        target_rect = self.active_region_rect if self.active_region_rect is not None else self.geometry()
        return {
            "left": int(round(target_rect.x() * r)),
            "top": int(round(target_rect.y() * r)),
            "width": max(20, int(round(target_rect.width() * r))),
            "height": max(20, int(round(target_rect.height() * r))),
        }

    def showEvent(self, event):
        super().showEvent(event)
        self._enable_click_through()

    def _enable_click_through(self):
        hwnd = int(self.winId())
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(
            hwnd,
            win32con.GWL_EXSTYLE,
            ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT,
        )
        try:
            user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception as exc:
            log_event(f"Не удалось применить WDA_EXCLUDEFROMCAPTURE: {exc}", "WARN")

    # --------------------------------------------------------------------------
    # PAINTEVENT v3.0: ЧИСТАЯ БИРЮЗОВАЯ РАМКА БЕЗ ТЕКСТОВОЙ ПЛАШКИ + EXACT MENU ALIGN
    # --------------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Пункт 3.1 ТЗ v3.0: Текст-подсказка над бирюзовой рамкой полностью удален!
        # Осталась только аккуратная тонкая бирюзовая рамка зоны захвата (отключаемая в FontSettingsPopup).
        if self.active_region_rect is not None and self.font_cfg.show_capture_border:
            pen = QPen(QColor(0, 229, 255, 130))
            pen.setWidthF(1.3)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.active_region_rect.adjusted(1, 1, -1, -1))

        style_mode = self.plaque_render_mode
        weight = QFont.Weight.Bold if self.font_cfg.is_bold else QFont.Weight.Medium

        for block in self.overlay_blocks:
            r = block.rect
            if block.is_pending:
                painter.setPen(QPen(QColor(168, 85, 247, 190), 1.0))
                painter.setBrush(QColor(138, 92, 245, 95))
                painter.drawRoundedRect(QRectF(r), 4.0, 4.0)
                continue

            single_line_h = max(12, int(r.height() / max(1, block.lines_merged)))
            auto_font_px = max(10, int(single_line_h * FONT_HEIGHT_RATIO))
            if self.font_cfg.use_fixed_pt:
                font_px = max(9, min(46, int(round(self.font_cfg.fixed_pt * 1.333))))
            else:
                scale_mult = max(0.6, min(1.8, self.font_cfg.scale_percent / 100.0))
                font_px = max(8, min(48, int(round(auto_font_px * scale_mult))))

            font = QFont(self.font_cfg.font_family, -1, weight)
            font.setPixelSize(font_px)
            fm = QFontMetrics(font)
            text_w = fm.horizontalAdvance(block.trans_text)

            draw_rect = QRect(r)
            use_word_wrap = False

            allow_wrap_in_mode = style_mode in ("wrap_gradient", "dark_glass", "cyber_neon", "high_contrast")
            if allow_wrap_in_mode and (
                block.lines_merged >= 2 or (text_w > r.width() * 1.35 and len(block.trans_text.split()) >= 3)
            ):
                use_word_wrap = True
                draw_rect.setWidth(max(r.width() + 10, int(r.width() * 1.12)))
                if not self.font_cfg.use_fixed_pt:
                    est_lines = max(2, int(round(text_w / max(40, draw_rect.width() - 12))) + 1)
                    max_font_by_h = max(10, int((draw_rect.height() - 6) / max(1.8, est_lines * 1.18)))
                    font_px = min(font_px, max(10, int(max_font_by_h * (self.font_cfg.scale_percent / 100.0))))
                    font.setPixelSize(font_px)
                req_h = int(2 * font_px * 1.24) + 8
                if req_h > draw_rect.height():
                    draw_rect.setHeight(min(int(r.height() * 1.35) + 12, req_h))
            elif text_w > r.width() - 6 and not self.font_cfg.use_fixed_pt:
                expanded_w = int(r.width() * 1.12)
                if text_w <= expanded_w - 6:
                    draw_rect.setWidth(text_w + 8)
                else:
                    draw_rect.setWidth(expanded_w)
                    ratio = max(0.55, (expanded_w - 6) / max(1, text_w))
                    font_px = max(8, int(font_px * ratio))
                    font.setPixelSize(font_px)

            if style_mode == "outline_only":
                painter.setFont(font)
                fm_outline = QFontMetrics(font)
                text_path = QPainterPath()
                baseline_y = draw_rect.y() + (draw_rect.height() + fm_outline.ascent() - fm_outline.descent()) // 2
                text_path.addText(float(draw_rect.x() + 2), float(baseline_y), font, block.trans_text)

                outline_pen = QPen(
                    QColor(0, 0, 0, 245),
                    2.5,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
                painter.strokePath(text_path, outline_pen)
                painter.fillPath(text_path, QColor("#FFFFFF"))
                continue

            radius = 4.0
            text_color = block.fg_color

            if style_mode == "wrap_gradient":
                painter.setPen(Qt.PenStyle.NoPen)
                grad = QLinearGradient(
                    QPointF(draw_rect.left(), draw_rect.top()),
                    QPointF(draw_rect.right(), draw_rect.top()),
                )
                grad.setColorAt(0.0, block.bg_color)
                grad.setColorAt(1.0, block.bg_color_right)
                painter.setBrush(grad)
            elif style_mode == "single":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(block.bg_color)
            elif style_mode == "dark_glass":
                painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
                painter.setBrush(QColor(12, 15, 22, 215))
                radius = 6.0
                text_color = QColor("#ECEFF4")
            elif style_mode == "cyber_neon":
                painter.setPen(QPen(QColor("#00E5FF"), 1.5))
                painter.setBrush(QColor(10, 14, 20, 230))
                radius = 4.0
                text_color = QColor("#00E5FF")
            elif style_mode == "high_contrast":
                painter.setPen(QPen(QColor(255, 214, 0, 110), 1.0))
                painter.setBrush(QColor("#111318"))
                radius = 8.0
                text_color = QColor("#FFD600")

            painter.drawRoundedRect(QRectF(draw_rect), radius, radius)

            painter.setFont(font)
            painter.setPen(text_color)

            # Пункт 1.2 и 2.1 ТЗ v3.0: Кнопки меню центрируются (AlignCenter), абзацы — по левому краю
            if self.font_cfg.text_align == "center":
                horiz_flag = Qt.AlignmentFlag.AlignCenter
            elif self.font_cfg.text_align == "left":
                horiz_flag = Qt.AlignmentFlag.AlignLeft
            else:
                is_short_ui_button = (block.lines_merged == 1 and len(block.orig_text.split()) <= 2)
                horiz_flag = Qt.AlignmentFlag.AlignCenter if is_short_ui_button else Qt.AlignmentFlag.AlignLeft

            flags = Qt.AlignmentFlag.AlignVCenter | horiz_flag
            if use_word_wrap:
                flags |= Qt.TextFlag.TextWordWrap
            painter.drawText(draw_rect.adjusted(4, 2, -4, -2), flags, block.trans_text)

    def safe_grab_screen(self, region: Optional[Dict[str, int]] = None) -> Optional[np.ndarray]:
        target = region if region is not None else self._active_capture_mss_region()
        try:
            shot = self.sct.grab(target)
            arr = np.array(shot)
            if arr is None or arr.size == 0:
                return None
            return arr
        except Exception as exc:
            now = time.monotonic()
            if now - self._last_grab_warn_ts >= 5.0:
                self._last_grab_warn_ts = now
                log_event(
                    f"Экран временно недоступен (Secure Desktop / UAC: {exc}), пропуск кадра",
                    "WARN",
                )
            try:
                self.sct = mss.mss()
            except Exception:
                pass
            return None

    # --------------------------------------------------------------------------
    # ПУНКТ 3.2 ТЗ v3.0: F8 — СКРЫТЬ / ПОКАЗАТЬ ОВЕРЛЕЙ И ПАНЕЛЬ ("👻 GT [F8]")
    # --------------------------------------------------------------------------
    def toggle_visibility(self):
        self.is_hidden = not self.is_hidden
        if self.is_hidden:
            self.monitor_timer.stop()
            self.watchdog_timer.stop()
            self.snip_band.hide()
            self.font_popup.hide()
            self.toolbar.hide()
            self.hide()
            self.mini_pill.show()
            self.mini_pill.raise_()
            log_event("Оверлей и панель скрыты (Клавиша F8) -> показан маячок 👻 GT [F8]")
        else:
            self.mini_pill.hide()
            self.show()
            self._enable_click_through()
            self.toolbar.show()
            self.toolbar.raise_()
            self.repaint()
            if self.monitor_interval_ms > 0:
                self._schedule_next_monitor_tick()
                if self.overlay_blocks:
                    self.watchdog_timer.start()
            log_event("Оверлей и панель раскрыты обратно (Клавиша F8)")

    def clear_all_plaques(self):
        self.overlay_blocks.clear()
        self.watchdog_timer.stop()
        self.repaint()

    def set_ocr_backend(self, backend: str):
        self.ocr_backend = backend
        self.prev_ocr_signature = ""
        log_event(f"[SWITCH] Движок OCR переключен на: {backend}")
        if self.overlay_blocks and not self.pipeline_busy:
            self._trigger_capture_pipeline(check_static=False)

    def set_render_style(self, style_id: str):
        self.plaque_render_mode = style_id
        log_event(f"[RENDER_STYLE] Стиль отрисовки плашек переключен на: {style_id}")
        self.repaint()

    def set_timer_interval(self, mode_text: str):
        self.monitor_timer.stop()
        if mode_text == "Ручной":
            self.monitor_interval_ms = 0
            self.watchdog_timer.stop()
            self.toolbar.set_stop_active(False)
            log_event("Режим таймера переключен в 'Ручной' (Watchdog 150ms отключен)")
            return
        sec = float(mode_text.replace("s", ""))
        self.monitor_interval_ms = int(sec * 1000)
        self.toolbar.set_stop_active(True)
        log_event(f"Включен SingleShot авто-мониторинг с интервалом {mode_text}")
        if self.overlay_blocks:
            self.watchdog_timer.start()
        self._schedule_next_monitor_tick()

    def _schedule_next_monitor_tick(self):
        if self.monitor_interval_ms > 0 and not self.is_hidden and not self.pipeline_busy:
            self.monitor_timer.start(self.monitor_interval_ms)

    def stop_translation_and_clear(self):
        self.job_id += 1
        self.pipeline_busy = False
        self.pending_rescan = False
        self.monitor_interval_ms = 0
        self.monitor_timer.stop()
        self.watchdog_timer.stop()
        self.toolbar.timer_combo.blockSignals(True)
        self.toolbar.timer_combo.setCurrentText("Ручной")
        self.toolbar.timer_combo.blockSignals(False)
        self.toolbar.set_stop_active(False)

        if self.trans_thread and self.trans_thread.isRunning():
            self.trans_thread.stop()

        self.prev_ocr_signature = ""
        self.active_region_rect = None
        self.clear_all_plaques()
        log_event(f"Остановка перевода и полная очистка экрана (job_id={self.job_id})")

    def build_diagnostic_report(self) -> str:
        report_lines = [
            "=== GhostTranslate v3.0 Diagnostic Report ===",
            f"OS: {platform.system()} {platform.release()} ({platform.version()}) | Admin={is_user_admin()}",
            f"DPI Scale: {self._dpi_ratio():.2f}x | WDA_EXCLUDEFROMCAPTURE: Active",
            f"Translation Engine: {TRANSLATION_ENGINE} (GAME_UI_DICT={len(GAME_UI_DICT)} words, MAX_BATCH_BLOCKS={MAX_BATCH_BLOCKS})",
            f"Active OCR Backend: {self.ocr_backend} (HAS_WINOCR={HAS_WINOCR}, RapidOCR downscale={RAPIDOCR_DOWNSCALE})",
            f"Font Settings: {self.font_cfg.to_dict()}",
            f"Global Hotkeys: F8 (0x77 Hide/Restore) | F9 (0x78 Region Snip)",
            f"Benchmark Summary: {format_benchmark_summary()}",
            f"LRU Cache Size: {len(self.lru_cache.cache)}/{LRU_MAX_SIZE} | Active Blocks: {len(self.overlay_blocks)}",
            "--- Recent Events ---",
            *list(LOG_RING_BUFFER),
        ]
        return "\n".join(report_lines)

    def show_logs_modal(self):
        self.log_dialog.refresh_view()
        self.log_dialog.show()
        self.log_dialog.raise_()

    def export_and_copy_logs(self):
        report_text = self.build_diagnostic_report()
        QApplication.clipboard().setText(report_text)
        log_event("Отчет v3.0 скопирован в буфер обмена")
        if self.log_dialog.isVisible():
            self.log_dialog.refresh_view()

    def save_diagnostic_bundle(self):
        report_text = self.build_diagnostic_report()
        try:
            with open(BUNDLE_FILE_PATH, "w", encoding="utf-8") as f:
                f.write(report_text)
            log_event(f"Диагностический бандл сохранен в {BUNDLE_FILE_PATH}")
            os.startfile(BUNDLE_FILE_PATH)
        except Exception as exc:
            log_event(f"Ошибка сохранения бандла: {exc}", "ERROR")
        if self.log_dialog.isVisible():
            self.log_dialog.refresh_view()

    # --------------------------------------------------------------------------
    # ПУНКТ 3.2 ТЗ v3.0: F9 — СТАРТ РЕЖИМА ВЫДЕЛЕНИЯ ОБЛАСТИ ОБЫЧНОЙ ЛКМ
    # --------------------------------------------------------------------------
    def start_snipping_mode(self):
        if self.is_hidden:
            self.toggle_visibility()
        self.manual_snip_armed = True
        self.setCursor(Qt.CursorShape.CrossCursor)
        log_event("Режим выделения области активирован (F9): выделите рамку обычной ЛКМ")

    def capture_full_screen(self):
        self.active_region_rect = None
        self.prev_ocr_signature = ""
        self.clear_all_plaques()
        self._trigger_capture_pipeline(check_static=False)

    def on_auto_monitor_tick(self):
        if self.monitor_interval_ms <= 0 or self.is_hidden:
            return
        self._trigger_capture_pipeline(check_static=True)

    def on_watchdog_tick(self):
        if (
            self.monitor_interval_ms <= 0
            or self.is_hidden
            or not self.overlay_blocks
            or self.last_translated_small_gray is None
        ):
            self.watchdog_timer.stop()
            return
        if self.pipeline_busy:
            return

        img_bgra = self.safe_grab_screen()
        if img_bgra is None:
            return

        small_gray = compute_small_gray_numpy(img_bgra)
        if small_gray.shape != self.last_translated_small_gray.shape:
            self.last_translated_small_gray = small_gray
            return
        diff = float(np.mean(np.abs(small_gray - self.last_translated_small_gray)))
        if diff > WATCHDOG_DIFF_THRESHOLD:
            log_event(
                f"Watchdog 150ms (NumPy): смена экрана (diff={diff:.2f} > {WATCHDOG_DIFF_THRESHOLD}), пересканирование"
            )
            self.prev_ocr_signature = ""
            self.clear_all_plaques()
            self._trigger_capture_pipeline(check_static=False)

    def _merge_with_persistent_blocks(self, new_blocks: List[OverlayBlock]) -> List[OverlayBlock]:
        if not self.overlay_blocks:
            return new_blocks

        for nb in new_blocks:
            if not nb.is_pending:
                continue
            for ob in self.overlay_blocks:
                if ob.is_pending:
                    continue
                if (
                    abs(nb.rect.x() - ob.rect.x()) <= 28
                    and abs(nb.rect.y() - ob.rect.y()) <= 22
                    and SequenceMatcher(None, nb.orig_text, ob.orig_text).ratio() >= 0.88
                ):
                    nb.trans_text = ob.trans_text
                    nb.is_pending = False
                    self.lru_cache.put(nb.orig_text, ob.trans_text)
                    break
        return new_blocks

    def _trigger_capture_pipeline(self, check_static: bool = False):
        if self.is_hidden:
            return
        if self.pipeline_busy or (self.ocr_thread and self.ocr_thread.isRunning()):
            self.pending_rescan = True
            return

        img_bgra = self.safe_grab_screen()
        if img_bgra is None:
            self._schedule_next_monitor_tick()
            return

        small_gray = compute_small_gray_numpy(img_bgra)

        if (
            check_static
            and self.prev_small_gray is not None
            and small_gray.shape == self.prev_small_gray.shape
        ):
            diff = float(np.mean(np.abs(small_gray - self.prev_small_gray)))
            if diff < PIXEL_DIFF_THRESHOLD:
                self._schedule_next_monitor_tick()
                return

        self.pipeline_busy = True
        self.pending_rescan = False
        self.prev_small_gray = small_gray
        self.last_translated_small_gray = small_gray
        self._check_seq_on_complete = check_static

        self.job_id += 1
        current_job = self.job_id
        self.toolbar.set_stop_active(True)

        offset_x = self.active_region_rect.x() if self.active_region_rect is not None else 0
        offset_y = self.active_region_rect.y() if self.active_region_rect is not None else 0

        self.ocr_thread = OcrWorkerThread(
            self.ocr_engine,
            self.ocr_backend,
            img_bgra,
            self.lru_cache,
            job_id=current_job,
            dpi_scale=self._dpi_ratio(),
            offset_x=offset_x,
            offset_y=offset_y,
        )
        self.ocr_thread.blocks_ready.connect(self._on_ocr_blocks_ready)
        self.ocr_thread.start()

    def _finish_pipeline_cycle(self):
        self.pipeline_busy = False
        if self.monitor_interval_ms == 0:
            self.watchdog_timer.stop()
            self.toolbar.set_stop_active(False)
        else:
            if self.overlay_blocks and not self.is_hidden:
                self.watchdog_timer.start()
            self._schedule_next_monitor_tick()

        if self.pending_rescan and not self.is_hidden and self.monitor_interval_ms > 0:
            self.pending_rescan = False
            QTimer.singleShot(40, lambda: self._trigger_capture_pipeline(check_static=False))

    def _on_ocr_blocks_ready(self, blocks: List[OverlayBlock], signature: str, job_id: int):
        if job_id != self.job_id:
            self.pipeline_busy = False
            return

        if not blocks:
            self.clear_all_plaques()
            self._finish_pipeline_cycle()
            return

        if getattr(self, "_check_seq_on_complete", False) and self.prev_ocr_signature:
            ratio = SequenceMatcher(None, signature, self.prev_ocr_signature).ratio()
            if ratio > SEQ_MATCH_THRESHOLD:
                self._finish_pipeline_cycle()
                return

        self.prev_ocr_signature = signature
        self.overlay_blocks = self._merge_with_persistent_blocks(blocks)
        self.repaint()
        if self.log_dialog.isVisible():
            self.log_dialog.refresh_view()

        pending_map: Dict[int, str] = {}
        for idx, b in enumerate(self.overlay_blocks):
            if b.is_pending:
                pending_map[idx] = b.orig_text

        if not pending_map:
            self._finish_pipeline_cycle()
            return

        if self.trans_thread and self.trans_thread.isRunning():
            self.trans_thread.stop()

        self.trans_thread = NativeCT2TranslationWorker(pending_map, job_id=self.job_id)
        self.trans_thread.batch_translated.connect(self._on_batch_translated)
        self.trans_thread.batch_finished.connect(self._on_batch_finished)
        self.trans_thread.start()

    def _on_batch_translated(self, pairs: List[Tuple[int, str, str]], job_id: int):
        if job_id != self.job_id:
            return
        for idx, orig_text, trans_text in pairs:
            self.lru_cache.put(orig_text, trans_text)
            if 0 <= idx < len(self.overlay_blocks):
                self.overlay_blocks[idx].trans_text = trans_text
                self.overlay_blocks[idx].is_pending = False
        self.repaint()

    def _on_batch_finished(self, job_id: int):
        if job_id == self.job_id:
            self._finish_pipeline_cycle()
        if self.log_dialog.isVisible():
            self.log_dialog.refresh_view()

    # --------------------------------------------------------------------------
    # ПУНКТ 3.2 И 3.3 ТЗ v3.0: РЕГИСТРАЦИЯ F8 / F9 (RegisterHotKey + GetAsyncKeyState 25 мс)
    # --------------------------------------------------------------------------
    def _register_global_f8_f9_hotkeys(self):
        try:
            hwnd = int(self.winId())
            user32.RegisterHotKey(hwnd, HOTKEY_ID_F8, 0, VK_F8)
            user32.RegisterHotKey(hwnd, HOTKEY_ID_F9, 0, VK_F9)
        except Exception as exc:
            log_event(f"Примечание RegisterHotKey F8/F9 (активен поллер GetAsyncKeyState): {exc}", "INFO")

    def nativeEvent(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    if msg.wParam == HOTKEY_ID_F8:
                        self.toggle_visibility()
                        return True, 0
                    elif msg.wParam == HOTKEY_ID_F9:
                        self.start_snipping_mode()
                        return True, 0
        except Exception:
            pass
        # ВАЖНО: не вызываем super().nativeEvent() — в PyQt6/Qt 6.11 базовый
        # QWidget::nativeEvent возвращает значение, на котором падает QtCore
        # (0xC000041D access violation в QtCore.pyd при показе окна).
        return False, 0

    def _init_win32_input_poller(self):
        self._prev_f8_down = False
        self._prev_f9_down = False
        self._prev_lmb_down = False
        self._prev_esc_down = False

        self.input_poller = QTimer(self)
        self.input_poller.setInterval(25)
        self.input_poller.timeout.connect(self._poll_win32_input)
        self.input_poller.start()

    def _get_cursor_pos(self) -> Tuple[int, int]:
        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)

    def _poll_win32_input(self):
        f8_down = bool(user32.GetAsyncKeyState(VK_F8) & 0x8000)
        f9_down = bool(user32.GetAsyncKeyState(VK_F9) & 0x8000)
        lmb_down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        esc_down = bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)

        # 1. Клавиша F8 (0x77) -> Скрыть / Показать оверлей и панель (edge-trigger)
        if f8_down and not self._prev_f8_down:
            self.toggle_visibility()
            self._prev_f8_down = f8_down
            return

        # 2. Клавиша F9 (0x78) -> Начать выделение области захвата (edge-trigger)
        if f9_down and not self._prev_f9_down:
            self.start_snipping_mode()
            self._prev_f9_down = f9_down
            return

        # 3. Клавиша ESC -> Отмена режима выделения области
        if esc_down and not self._prev_esc_down and (self.manual_snip_armed or self._is_selecting_region):
            self.manual_snip_armed = False
            self._is_selecting_region = False
            self.snip_band.hide()
            self.unsetCursor()

        # 4. После нажатия F9 (или кнопки «Область [F9]») выделение идет обычной ЛКМ без удержания клавиш
        cx, cy = self._get_cursor_pos()
        if self.manual_snip_armed and lmb_down and not self._prev_lmb_down and not self._is_selecting_region:
            self.manual_snip_armed = False
            self._is_selecting_region = True
            self._on_snip_start(cx, cy)
        elif self._is_selecting_region and lmb_down:
            self._on_snip_move(cx, cy)
        elif self._is_selecting_region and not lmb_down:
            self._is_selecting_region = False
            self.unsetCursor()
            self._on_snip_end(cx, cy)

        self._prev_f8_down = f8_down
        self._prev_f9_down = f9_down
        self._prev_lmb_down = lmb_down
        self._prev_esc_down = esc_down

    def _on_snip_start(self, phys_x: int, phys_y: int):
        self.snip_origin = self._phys_to_log(phys_x, phys_y)
        self.snip_band.setGeometry(QRect(self.snip_origin, self.snip_origin))
        self.snip_band.show()
        self.snip_band.raise_()
        self.snip_band.repaint()

    def _on_snip_move(self, phys_x: int, phys_y: int):
        curr = self._phys_to_log(phys_x, phys_y)
        rect = QRect(self.snip_origin, curr).normalized()
        self.snip_band.setGeometry(rect)
        self.snip_band.repaint()

    def _on_snip_end(self, phys_x: int, phys_y: int):
        self.snip_band.hide()
        curr = self._phys_to_log(phys_x, phys_y)
        rect = QRect(self.snip_origin, curr).normalized()
        if rect.width() > 40 and rect.height() > 40:
            self.active_region_rect = rect
            self.prev_ocr_signature = ""
            self.clear_all_plaques()
            log_event(
                f"Выделена новая область [F9]: x={rect.x()}, y={rect.y()}, w={rect.width()}, h={rect.height()}"
            )
            self._trigger_capture_pipeline(check_static=False)

    def emergency_shutdown(self):
        log_event("Полное завершение работы GhostTranslate v3.0 (Кнопка [X])")
        play_shutdown_sound_sync()
        try:
            hwnd = int(self.winId())
            user32.UnregisterHotKey(hwnd, HOTKEY_ID_F8)
            user32.UnregisterHotKey(hwnd, HOTKEY_ID_F9)
            self.monitor_timer.stop()
            self.watchdog_timer.stop()
            self.input_poller.stop()
            self.snip_band.hide()
            self.font_popup.hide()
            self.mini_pill.hide()
            if self.trans_thread and self.trans_thread.isRunning():
                self.trans_thread.stop()
            self.sct.close()
        except Exception:
            pass
        os._exit(0)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    canvas = GhostARCanvasWindow()
    canvas.show()
    sys.exit(app.exec())
