"""Глобальные клавиши: строка вида «Ctrl+Shift+T» в коды RegisterHotKey и проверка нажатия."""

from dataclasses import dataclass
from typing import Callable, Optional

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C

# Имена модификаторов в PortableText QKeySequence.
_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "meta": MOD_WIN,
    "win": MOD_WIN,
}
_MODIFIER_ORDER = (("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT), ("Meta", MOD_WIN))

_NAMED_KEYS = {
    "space": 0x20,
    "pgup": 0x21,
    "pgdown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "ins": 0x2D,
    "del": 0x2E,
    "pause": 0x13,
    "print": 0x2C,
    "scrolllock": 0x91,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "\\": 0xDC,
}
_NAMED_KEY_LABELS = {
    "space": "Space",
    "pgup": "PgUp",
    "pgdown": "PgDown",
    "end": "End",
    "home": "Home",
    "ins": "Ins",
    "del": "Del",
    "pause": "Pause",
    "print": "Print",
    "scrolllock": "ScrollLock",
}


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    vk: int
    text: str


def _parse_key(name: str) -> Optional[tuple]:
    low = name.lower()
    if low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
        return 0x70 + int(low[1:]) - 1, f"F{int(low[1:])}"
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper()), name.upper()
    if low in _NAMED_KEYS:
        return _NAMED_KEYS[low], _NAMED_KEY_LABELS.get(low, name)
    return None


def parse_hotkey(text: str) -> Optional[Hotkey]:
    """None для пустой строки, неизвестной клавиши и сочетаний без основной клавиши.

    Буква или цифра без Ctrl/Alt/Win тоже отклоняется: такая клавиша пропала бы
    из набора текста во всех программах.
    """
    if not text:
        return None
    parts = text.split("+")
    # «Ctrl++» — сочетание с самой клавишей «+».
    if text.endswith("++"):
        parts = parts[:-2] + ["="]
    *mod_names, key_name = [p.strip() for p in parts]
    if not key_name:
        return None

    modifiers = 0
    for mod_name in mod_names:
        flag = _MODIFIERS.get(mod_name.lower())
        if flag is None:
            return None
        modifiers |= flag

    parsed = _parse_key(key_name)
    if parsed is None:
        return None
    vk, key_label = parsed

    is_function_key = 0x70 <= vk <= 0x87
    is_navigation_key = vk in (0x13, 0x2C, 0x91, 0x21, 0x22, 0x23, 0x24, 0x2D, 0x2E)
    if not (modifiers & (MOD_CONTROL | MOD_ALT | MOD_WIN)) and not (is_function_key or is_navigation_key):
        return None

    label = "+".join([name for name, flag in _MODIFIER_ORDER if modifiers & flag] + [key_label])
    return Hotkey(modifiers=modifiers, vk=vk, text=label)


def is_hotkey_down(hotkey: Hotkey, key_down: Callable[[int], bool]) -> bool:
    """Основная клавиша и все её модификаторы нажаты. key_down — обёртка над GetAsyncKeyState."""
    if not key_down(hotkey.vk):
        return False
    required = (
        (MOD_CONTROL, (VK_CONTROL,)),
        (MOD_ALT, (VK_MENU,)),
        (MOD_SHIFT, (VK_SHIFT,)),
        (MOD_WIN, (VK_LWIN, VK_RWIN)),
    )
    for flag, vks in required:
        if hotkey.modifiers & flag and not any(key_down(vk) for vk in vks):
            return False
    return True
