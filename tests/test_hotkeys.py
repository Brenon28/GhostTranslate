import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghosttranslate.hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    VK_CONTROL,
    VK_MENU,
    VK_SHIFT,
    is_hotkey_down,
    parse_hotkey,
)


class ParseHotkeyTests(unittest.TestCase):
    def test_function_keys_need_no_modifiers(self):
        hk = parse_hotkey("F8")
        self.assertEqual((hk.modifiers, hk.vk, hk.text), (0, 0x77, "F8"))
        self.assertEqual(parse_hotkey("F12").vk, 0x7B)

    def test_combination_is_normalized(self):
        hk = parse_hotkey("Shift+Ctrl+t")
        self.assertEqual(hk.modifiers, MOD_CONTROL | MOD_SHIFT)
        self.assertEqual(hk.vk, ord("T"))
        self.assertEqual(hk.text, "Ctrl+Shift+T")

    def test_alt_with_digit(self):
        hk = parse_hotkey("Alt+1")
        self.assertEqual((hk.modifiers, hk.vk), (MOD_ALT, ord("1")))

    def test_rejects_keys_that_would_break_typing(self):
        for text in ("", "T", "Shift+T", "Ctrl+", "Hyper+F8", "Ctrl+Ё"):
            self.assertIsNone(parse_hotkey(text), text)


class HotkeyDownTests(unittest.TestCase):
    def test_all_modifiers_must_be_held(self):
        hk = parse_hotkey("Ctrl+Alt+T")
        self.assertTrue(is_hotkey_down(hk, lambda vk: vk in (ord("T"), VK_CONTROL, VK_MENU)))
        self.assertFalse(is_hotkey_down(hk, lambda vk: vk in (ord("T"), VK_CONTROL)))
        self.assertFalse(is_hotkey_down(hk, lambda vk: vk in (VK_CONTROL, VK_MENU)))

    def test_plain_function_key_ignores_modifiers(self):
        hk = parse_hotkey("F9")
        self.assertTrue(is_hotkey_down(hk, lambda vk: vk in (0x78, VK_SHIFT)))


if __name__ == "__main__":
    unittest.main()
