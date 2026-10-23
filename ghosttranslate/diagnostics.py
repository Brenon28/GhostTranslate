import logging
import sys
import time
import traceback
from collections import deque
from logging.handlers import RotatingFileHandler
from typing import Dict, List

from .config import ENABLE_DIAGNOSTIC_LOGS, LOG_FILE_PATH


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


def install_exception_logger() -> None:
    """Ошибка в обработчике сигнала пишется в журнал, а не завершает процесс.

    PyQt6 вызывает qFatal() на необработанном исключении в слоте, если sys.excepthook
    оставлен стандартным, и оверлей пропадает целиком.
    """

    def _hook(exc_type, exc_value, exc_tb):
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip()
        log_event(f"Необработанная ошибка: {details}", "ERROR")

    sys.excepthook = _hook


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
