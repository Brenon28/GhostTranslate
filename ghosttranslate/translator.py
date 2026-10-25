import os
import re
import sys
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Легковесное ядро v3.0: прямой CTranslate2 + SentencePiece (БЕЗ torch и argostranslate!)
# ВАЖНО: импортируется ДО winocr/winrt — иначе конфликт статических символов
# protobuf в winrt-runtime 3.x и sentencepiece вызывает access violation.
try:
    import ctranslate2
    import sentencepiece as spm
    HAS_NATIVE_CT2 = True
except ImportError:
    HAS_NATIVE_CT2 = False

from .config import APP_VERSION, BASE_DIR, LRU_MAX_SIZE
from .diagnostics import log_event
from .game_dict import GAME_UI_DICT


# Таблица разворачивания сокращений без апострофов и игрового сленга для SentencePiece.
SLANG_AND_CONTRACTIONS: Dict[str, str] = {
    "dont": "do not",
    "don't": "do not",
    "cant": "cannot",
    "can't": "cannot",
    "wont": "will not",
    "won't": "will not",
    "didnt": "did not",
    "didn't": "did not",
    "doesnt": "does not",
    "doesn't": "does not",
    "isnt": "is not",
    "isn't": "is not",
    "arent": "are not",
    "aren't": "are not",
    "wasnt": "was not",
    "wasn't": "was not",
    "werent": "were not",
    "weren't": "were not",
    "havent": "have not",
    "haven't": "have not",
    "hasnt": "has not",
    "hasn't": "has not",
    "hadnt": "had not",
    "hadn't": "had not",
    "wouldnt": "would not",
    "wouldn't": "would not",
    "couldnt": "could not",
    "couldn't": "could not",
    "shouldnt": "should not",
    "shouldn't": "should not",
    "im": "I am",
    "i'm": "I am",
    "ive": "I have",
    "i've": "I have",
    "i'll": "I will",
    "i'd": "I would",
    "youre": "you are",
    "you're": "you are",
    "theyre": "they are",
    "they're": "they are",
    "we're": "we are",
    "weve": "we have",
    "we've": "we have",
    "lets": "let us",
    "let's": "let us",
    "thats": "that is",
    "that's": "that is",
    "whats": "what is",
    "what's": "what is",
    "ur": "your",
    "pls": "please",
    "plz": "please",
    "thx": "thank you",
    "ty": "thank you",
    "tysm": "thank you",
    "np": "no problem",
    "idk": "I do not know",
    "imo": "in my opinion",
    "imho": "in my opinion",
    "tbh": "to be honest",
    "afaik": "as far as I know",
    "rn": "right now",
    "nvm": "never mind",
    "omw": "on my way",
    "brb": "I will be right back",
    "afk": "away from keyboard",
    "btw": "by the way",
    "bc": "because",
    "cuz": "because",
    "gonna": "going to",
    "wanna": "want to",
    "gotta": "have to",
    "lemme": "let me",
    "gimme": "give me",
    "kinda": "kind of",
    "sorta": "sort of",
}

SLASH_SLANG_REGEX = re.compile(r"(?<![A-Za-z0-9])(w/o|w/)(?![A-Za-z0-9])", re.IGNORECASE)
WORD_TOKEN_REGEX = re.compile(r"\b[A-Za-z]+(?:'[A-Za-z]+)?\b")


def preprocess_english_text(text: str) -> str:
    """Нормализует сокращения без апострофов и игровой сленг перед подачей в SentencePiece."""
    if not text:
        return text

    def _replace_slash(match: re.Match) -> str:
        tok = match.group(1).lower()
        return "without" if tok == "w/o" else "with"

    stage1 = SLASH_SLANG_REGEX.sub(_replace_slash, text)

    def _replace_word(match: re.Match) -> str:
        word = match.group(0)
        # 'ill' только в нижнем регистре разворачивается в 'I will', чтобы не ломать 'Ill'.
        if word == "ill":
            return "I will"
        # Одна буква — это клавиша («Press U», «Press R»), а не слово чата.
        if len(word) < 2:
            return word
        low = word.lower()
        replacement = SLANG_AND_CONTRACTIONS.get(low)
        if replacement is None:
            return word
        if word[0].isupper() and not replacement.startswith("I "):
            return replacement[0].upper() + replacement[1:]
        return replacement

    return WORD_TOKEN_REGEX.sub(_replace_word, stage1)


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
        self._translate_lock = threading.Lock()

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
            accepted = self._accepted_model_dir(cand)
            if accepted:
                return accepted

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
                        accepted = self._accepted_model_dir(target_extract)
                        if accepted:
                            return accepted
                    except Exception as exc:
                        log_event(f"Ошибка распаковки {archive_path}: {exc}", "WARN")
        return None

    @staticmethod
    def _accepted_model_dir(cand: str) -> Optional[str]:
        """Каталог, внутри которого лежат model.bin и sentencepiece.model.

        Архив Argos часто распаковывается во вложенную папку, поэтому одного
        первого подкаталога недостаточно: ищем пару файлов на небольшую глубину.
        """
        if not cand or not os.path.isdir(cand):
            return None

        roots = [cand]
        for dirpath, dirnames, _filenames in os.walk(cand):
            depth = dirpath[len(cand):].count(os.sep)
            if depth >= 3:
                dirnames.clear()
                continue
            roots.append(dirpath)

        seen = set()
        for root in roots:
            if root in seen:
                continue
            seen.add(root)
            model_sub = os.path.join(root, "model") if os.path.isdir(os.path.join(root, "model")) else root
            sp_cand = os.path.join(root, "sentencepiece.model")
            if not os.path.isfile(sp_cand):
                sp_cand = os.path.join(model_sub, "sentencepiece.model")
            if os.path.isfile(os.path.join(model_sub, "model.bin")) and os.path.isfile(sp_cand):
                return root
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
            # SentencePiece открывает путь через узкий API и не видит кириллицу вроде «ПетПроекты».
            # Файл читает Python, в токенизатор отдаются уже байты модели.
            self.sp_processor = spm.SentencePieceProcessor()
            with open(sp_path, "rb") as sp_file:
                loaded = self.sp_processor.LoadFromSerializedProto(sp_file.read())
            if not loaded:
                raise RuntimeError(f"Не удалось прочитать токенизатор: {sp_path}")
            self.model_dir = found_dir
            self.ready = True

            # Прогрев модели в ОЗУ
            _ = self.translate_batch(["System Ready"])
            log_event(f"NativeCT2Translator v{APP_VERSION} (int8, без PyTorch) загружен из {found_dir}")
        except Exception as exc:
            log_event(f"Предупреждение инициализации NativeCT2Translator: {exc}", "WARN")

    def word_score(self, word: str) -> Optional[float]:
        """Лог-вероятность слова на букву по словарю SentencePiece (он общий для EN и RU).

        Настоящее слово режется на 1-2 частых куска, мусор OCR — на много редких.
        None, пока модель не загружена.
        """
        sp = self.sp_processor
        if not self.ready or sp is None or not word:
            return None
        ids = sp.encode(word)
        if not ids:
            return None
        return sum(sp.get_score(i) for i in ids) / len(word)

    def translate_batch(self, texts: List[str]) -> List[Tuple[str, bool]]:
        """
        Пункт 1.3 и 4.1 ТЗ v3.0 + v3.6:
        1. Очищает буллиты и спецсимволы по краям (•·|—*<>[]).
        2. Мгновенно (0 мс) проверяет игровой словарь GAME_UI_DICT.
        3. Если строка в КАПСЕ (text.isupper()), переводит её в .capitalize() перед подачей в CTranslate2,
           а результат возвращает в .upper() для коротких заголовков (<= 3 слов).
        4. Нормализует игровой сленг и пропущенные апострофы через preprocess_english_text.
        5. Переводит оставшиеся фразы единым пакетом через ctranslate2.Translator.translate_batch(beam_size=2).

        Возвращает пары (текст, переведено). False означает, что показан исходный текст:
        модель ещё грузится или перевод упал. Такие строки нельзя класть в кэш.
        """
        if not texts:
            return []

        with self._translate_lock:
            return self._translate_batch_locked(texts)

    def _translate_batch_locked(self, texts: List[str]) -> List[Tuple[str, bool]]:
        results: List[Optional[Tuple[str, bool]]] = [None] * len(texts)
        ct2_indices: List[int] = []
        ct2_inputs: List[str] = []
        ct2_restore_upper: List[bool] = []

        for i, raw_txt in enumerate(texts):
            cleaned = raw_txt.strip(" •·|—*<>[]\t\r\n").strip()
            if not cleaned:
                results[i] = (raw_txt, True)
                continue

            word_count = len(cleaned.split())
            is_upper_source = cleaned.isupper() and any(ch.isalpha() for ch in cleaned)
            low = cleaned.lower()

            # 1. Мгновенный поиск во встроенном игровом словаре GAME_UI_DICT (0 мс)
            if low in GAME_UI_DICT:
                dict_val = GAME_UI_DICT[low]
                results[i] = (dict_val.upper() if (is_upper_source and word_count <= 3) else dict_val, True)
                continue

            # 2. Нормализация КАПСА для нейросети CTranslate2
            norm_input = cleaned.capitalize() if is_upper_source else cleaned
            ct2_indices.append(i)
            ct2_inputs.append(norm_input)
            ct2_restore_upper.append(bool(is_upper_source and word_count <= 3))

        if not ct2_inputs:
            return [r if r is not None else ("", True) for r in results]

        if not self.ready or self.translator is None or self.sp_processor is None:
            for idx_pos, fallback_str, restore_up in zip(ct2_indices, ct2_inputs, ct2_restore_upper):
                results[idx_pos] = (fallback_str.upper() if restore_up else fallback_str, False)
            return [r if r is not None else ("", True) for r in results]

        try:
            preprocessed_inputs = [preprocess_english_text(s) for s in ct2_inputs]
            tokenized_batch = [self.sp_processor.encode(s, out_type=str) for s in preprocessed_inputs]
            ct2_out = self.translator.translate_batch(
                tokenized_batch,
                beam_size=2,
                repetition_penalty=1.15,
                no_repeat_ngram_size=3,
                max_batch_size=32,
            )
            for idx_pos, src, hyp, restore_up in zip(ct2_indices, ct2_inputs, ct2_out, ct2_restore_upper):
                tokens = hyp.hypotheses[0] if hyp.hypotheses else []
                decoded = self.sp_processor.decode(tokens).strip()
                if decoded:
                    results[idx_pos] = (decoded.upper() if restore_up else decoded, True)
                else:
                    results[idx_pos] = (src, False)
        except Exception as exc:
            log_event(f"Ошибка пакетного перевода NativeCT2: {exc}", "WARN")
            for idx_pos, fallback_str in zip(ct2_indices, ct2_inputs):
                results[idx_pos] = (fallback_str, False)

        return [r if r is not None else ("", True) for r in results]


NATIVE_CT2 = NativeCT2Translator()


# ==============================================================================
# LRU-КЭШ НА 2000 ФРАЗ В ОЗУ
# ==============================================================================
class TranslationLRUCache:
    """Читается из потока OCR, пишется из GUI-потока."""

    def __init__(self, capacity: int = LRU_MAX_SIZE):
        self.capacity = capacity
        self.cache: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            if key not in self.cache:
                return None
            self.cache.move_to_end(key)
            return self.cache[key]

    def put(self, key: str, value: str) -> None:
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self.cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self.cache)
