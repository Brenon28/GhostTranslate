import json
import os
import shutil
from dataclasses import dataclass
from typing import Optional, Tuple

from .config import (
    DEFAULT_HOTKEY_SNIP,
    DEFAULT_HOTKEY_TOGGLE,
    DEFAULT_TIMER_SCAN_MODE,
    LEGACY_SETTINGS_FILE_PATH,
    SETTINGS_FILE_PATH,
)
from .diagnostics import log_event
from .hotkeys import parse_hotkey

VALID_TIMER_SCAN_MODES = ("smart_grid", "forced_full")


@dataclass
class FontCustomConfig:
    """Всё, что хранится в settings.json: шрифт плашек, звук, клавиши и место панели."""

    font_family: str = "Segoe UI"
    scale_percent: int = 100
    use_fixed_pt: bool = False
    fixed_pt: int = 14
    is_bold: bool = True
    text_align: str = "auto"  # "auto" | "center" | "left"
    show_capture_border: bool = True
    sound_enabled: bool = True
    # Окна не прячутся от захвата экрана, плашки гаснут на время снимка.
    game_mode: bool = False
    timer_scan_mode: str = DEFAULT_TIMER_SCAN_MODE  # "smart_grid" | "forced_full"
    hotkey_toggle: str = DEFAULT_HOTKEY_TOGGLE
    hotkey_snip: str = DEFAULT_HOTKEY_SNIP
    # Середина верхнего края панели в логических координатах Qt; None — по центру основного экрана.
    toolbar_anchor: Optional[Tuple[int, int]] = None
    check_updates: bool = True

    def to_dict(self) -> dict:
        return {
            "font_family": self.font_family,
            "scale_percent": self.scale_percent,
            "use_fixed_pt": self.use_fixed_pt,
            "fixed_pt": self.fixed_pt,
            "is_bold": self.is_bold,
            "text_align": self.text_align,
            "show_capture_border": self.show_capture_border,
            "sound_enabled": self.sound_enabled,
            "game_mode": self.game_mode,
            "timer_scan_mode": self.timer_scan_mode,
            "hotkey_toggle": self.hotkey_toggle,
            "hotkey_snip": self.hotkey_snip,
            "toolbar_anchor": list(self.toolbar_anchor) if self.toolbar_anchor else None,
            "check_updates": self.check_updates,
        }

    @staticmethod
    def _hotkey_or_default(value, default: str) -> str:
        parsed = parse_hotkey(str(value)) if value else None
        return parsed.text if parsed else default

    @staticmethod
    def _timer_scan_mode_or_default(value) -> str:
        text = str(value) if value else DEFAULT_TIMER_SCAN_MODE
        return text if text in VALID_TIMER_SCAN_MODES else DEFAULT_TIMER_SCAN_MODE

    @staticmethod
    def _anchor_or_none(value) -> Optional[Tuple[int, int]]:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                return int(value[0]), int(value[1])
            except (TypeError, ValueError):
                return None
        return None

    @classmethod
    def load(cls) -> "FontCustomConfig":
        _migrate_legacy_settings()
        if os.path.exists(SETTINGS_FILE_PATH):
            try:
                # utf-8-sig: Блокнот Windows 10 сохраняет файл с BOM.
                with open(SETTINGS_FILE_PATH, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                cfg = cls(
                    font_family=str(data.get("font_family", "Segoe UI")),
                    scale_percent=max(60, min(180, int(data.get("scale_percent", 100)))),
                    use_fixed_pt=bool(data.get("use_fixed_pt", False)),
                    fixed_pt=max(8, min(28, int(data.get("fixed_pt", 14)))),
                    is_bold=bool(data.get("is_bold", True)),
                    text_align=str(data.get("text_align", "auto")),
                    show_capture_border=bool(data.get("show_capture_border", True)),
                    sound_enabled=bool(data.get("sound_enabled", True)),
                    game_mode=bool(data.get("game_mode", False)),
                    timer_scan_mode=cls._timer_scan_mode_or_default(data.get("timer_scan_mode")),
                    hotkey_toggle=cls._hotkey_or_default(data.get("hotkey_toggle"), DEFAULT_HOTKEY_TOGGLE),
                    hotkey_snip=cls._hotkey_or_default(data.get("hotkey_snip"), DEFAULT_HOTKEY_SNIP),
                    toolbar_anchor=cls._anchor_or_none(data.get("toolbar_anchor")),
                    check_updates=bool(data.get("check_updates", True)),
                )
                if cfg.hotkey_toggle == cfg.hotkey_snip:
                    cfg.hotkey_toggle, cfg.hotkey_snip = DEFAULT_HOTKEY_TOGGLE, DEFAULT_HOTKEY_SNIP
                return cfg
            except Exception as exc:
                log_event(f"Не удалось прочитать settings.json: {exc}", "WARN")
        return cls()

    def save(self) -> None:
        try:
            with open(SETTINGS_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log_event(f"Не удалось сохранить settings.json: {exc}", "WARN")


def _migrate_legacy_settings() -> None:
    """Версии до переноса хранили settings.json рядом с exe; первый запуск забирает его оттуда."""
    if os.path.normcase(LEGACY_SETTINGS_FILE_PATH) == os.path.normcase(SETTINGS_FILE_PATH):
        return
    if os.path.exists(SETTINGS_FILE_PATH) or not os.path.exists(LEGACY_SETTINGS_FILE_PATH):
        return
    try:
        shutil.copy2(LEGACY_SETTINGS_FILE_PATH, SETTINGS_FILE_PATH)
        log_event(f"settings.json перенесён в {SETTINGS_FILE_PATH}")
    except OSError as exc:
        log_event(f"Не удалось перенести settings.json: {exc}", "WARN")
