import asyncio
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import QRect, QThread, pyqtSignal

# translator подтягивает ctranslate2 и sentencepiece; он обязан загрузиться раньше winocr.
from .translator import NATIVE_CT2, TranslationLRUCache

# Нативный Windows 10/11 OCR (~54-84 мс на полном экране)
try:
    import winocr
    from PIL import Image
    from winrt.windows.media.ocr import OcrEngine
    HAS_WINOCR = True
except ImportError:
    HAS_WINOCR = False
    OcrEngine = None
    try:
        from PIL import Image
    except ImportError:
        Image = None

try:
    from rapidocr_onnxruntime import RapidOCR
    HAS_RAPIDOCR = True
except ImportError:
    RapidOCR = None
    HAS_RAPIDOCR = False

from .config import (
    MAX_BLOCKS_PER_FRAME,
    MIN_OCR_SCORE,
    RAPIDOCR_MAX_SIDE,
    RAPIDOCR_REC_MODEL_PATH,
    RAPIDOCR_THREADS,
    TRANSLATE_CHUNK_BLOCKS,
    TRANSLATION_ENGINE,
    WATCHDOG_DIFF_THRESHOLD,
    WATCHDOG_INTERVAL_MS,
    WINOCR_UPSCALE,
)
from .diagnostics import log_event, record_benchmark
from .game_dict import GAME_UI_DICT, translate_ui_pattern
from .models import OverlayBlock, RawWordBox
from .ocr.imaging import compute_small_gray_numpy, downscale_bgr_via_qimage, sample_word_background_and_fg
from .ocr.layout import drop_words_over_russian, is_valid_english_box, merge_ocr_boxes_into_paragraphs
from .ocr.rapid_layout import rapidocr_to_word_boxes
from .screens import open_mss


def _has_ocr_language(prefix: str) -> bool:
    if OcrEngine is None:
        return False
    try:
        return any(
            lang.language_tag.lower().startswith(prefix) for lang in OcrEngine.available_recognizer_languages
        )
    except Exception:
        return False


# Русский пакет OCR ставится вместе с русским языком Windows. Он нужен, чтобы отличить
# русский текст на экране от мусора, который из него делает английский распознаватель.
HAS_RU_WINOCR = _has_ocr_language("ru")


def _winocr_max_side() -> int:
    try:
        return int(OcrEngine.max_image_dimension)
    except Exception:
        return 10000


WINOCR_MAX_SIDE = _winocr_max_side() if OcrEngine is not None else 10000


class LazyRapidOCR:
    """RapidOCR грузит две ONNX-модели около секунды. При старте с WinOCR он не нужен,
    поэтому создаётся в потоке распознавания при первом кадре или в фоне при переключении."""

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if self._engine is None:
                options = {"intra_op_num_threads": RAPIDOCR_THREADS}
                if os.path.isfile(RAPIDOCR_REC_MODEL_PATH):
                    options["rec_model_path"] = RAPIDOCR_REC_MODEL_PATH
                else:
                    log_event(f"Нет {RAPIDOCR_REC_MODEL_PATH} -> китайская модель распознавания RapidOCR", "WARN")
                t0 = time.perf_counter()
                self._engine = RapidOCR(**options)
                log_event(f"RapidOCR загружен за {time.perf_counter() - t0:.2f} с ({RAPIDOCR_THREADS} потоков)")
            return self._engine

    def preload(self):
        threading.Thread(target=self.get, name="RapidOCRPreload", daemon=True).start()


def winocr_upscale_for(width: int, height: int) -> float:
    """Мелкий текст сайтов (10-13 px) WinOCR теряет целыми словами; в 1.5 раза крупнее — читает."""
    longest = max(1, width, height)
    return max(1.0, min(WINOCR_UPSCALE, WINOCR_MAX_SIDE / float(longest)))


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
        self.cyrillic_dropped = 0

    @staticmethod
    def _winocr_lines(res, scale: float = 1.0) -> List[List[RawWordBox]]:
        lines: List[List[RawWordBox]] = []
        for line_id, line in enumerate(getattr(res, "lines", [])):
            boxes: List[RawWordBox] = []
            for word in getattr(line, "words", []):
                txt = getattr(word, "text", "").strip()
                rect = getattr(word, "bounding_rect", None)
                if not txt or rect is None:
                    continue
                x1 = int(round(rect.x / scale))
                y1 = int(round(rect.y / scale))
                x2 = int(round((rect.x + rect.width) / scale))
                y2 = int(round((rect.y + rect.height) / scale))
                boxes.append(RawWordBox(x1=x1, y1=y1, x2=x2, y2=y2, text=txt, score=0.95, line_id=line_id))
            if boxes:
                lines.append(boxes)
        return lines

    def _winocr_image(self) -> Tuple["Image.Image", float]:
        img_rgb = self.img_bgra[:, :, :3][:, :, ::-1]
        pil_img = Image.fromarray(img_rgb)
        scale = winocr_upscale_for(pil_img.width, pil_img.height)
        if scale > 1.0:
            pil_img = pil_img.resize(
                (int(round(pil_img.width * scale)), int(round(pil_img.height * scale))),
                Image.Resampling.BICUBIC,
            )
        return pil_img, scale

    def _russian_lines(self) -> List[List[RawWordBox]]:
        """Русский WinOCR по тому же кадру. RapidOCR с английской моделью читает русские
        надписи игры латиницей («noknAaet penAosyio rpynny»), и по этим строкам их видно."""
        pil_img, scale = self._winocr_image()

        async def _recognize():
            return await winocr.recognize_pil(pil_img, "ru")

        return self._winocr_lines(asyncio.run(_recognize()), scale)

    def _run_winocr(self) -> List[RawWordBox]:
        """
        Пункт 1.1 ТЗ v3.0: В WinOCR обязательно извлекаем именно отдельные слова (for word in line.words),
        а не целую строку line целиком!
        """
        pil_img, scale = self._winocr_image()
        if scale > 1.0:
            self.applied_scale = scale

        async def _recognize():
            if not HAS_RU_WINOCR:
                return await winocr.recognize_pil(pil_img, "en"), None
            # Два распознавателя параллельно: около +20 мс к одному английскому.
            return await asyncio.gather(winocr.recognize_pil(pil_img, "en"), winocr.recognize_pil(pil_img, "ru"))

        en_res, ru_res = asyncio.run(_recognize())
        raw_boxes = [word for line in self._winocr_lines(en_res, scale) for word in line]
        if ru_res is not None:
            raw_boxes, self.cyrillic_dropped = drop_words_over_russian(
                raw_boxes, self._winocr_lines(ru_res, scale), NATIVE_CT2.word_score
            )
        return raw_boxes

    def _run_rapidocr(self) -> List[RawWordBox]:
        if self.ocr_engine is None:
            return []
        h_orig, w_orig = self.img_bgra.shape[:2]
        scale = 1.0
        long_side = max(w_orig, h_orig)
        if long_side > RAPIDOCR_MAX_SIDE:
            scale = RAPIDOCR_MAX_SIDE / float(long_side)
            self.applied_scale = scale
            img_input = downscale_bgr_via_qimage(self.img_bgra, scale)
        else:
            # Срез BGRA -> BGR идёт с шагом 4 байта; на таком массиве ONNX-препроцессинг
            # медленнее в полтора раза (1.9 с против 1.2 с на кадре 1600x1000).
            img_input = np.ascontiguousarray(self.img_bgra[:, :, :3])

        ocr_result, _ = self.ocr_engine.get()(
            img_input,
            use_det=True,
            use_cls=False,
            use_rec=True,
            box_thresh=0.35,
            unclip_ratio=1.8,
            return_word_box=True,
        )
        # Чернила смотрим на исходном кадре: координаты слов уже пересчитаны в него.
        words = rapidocr_to_word_boxes(ocr_result, self.img_bgra, 1.0 / scale)
        words = [word for word in words if word.score >= MIN_OCR_SCORE and word.text]
        if HAS_RU_WINOCR and words:
            # Около 0.1 с к 1-2 с самого RapidOCR.
            words, self.cyrillic_dropped = drop_words_over_russian(
                words, self._russian_lines(), NATIVE_CT2.word_score
            )
        return words

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
        paragraph_boxes = merge_ocr_boxes_into_paragraphs(raw_boxes)

        valid_paragraphs: List[RawWordBox] = []
        skipped_noise_or_ru = 0
        for pb in paragraph_boxes:
            if not is_valid_english_box(pb.text):
                skipped_noise_or_ru += 1
                continue
            valid_paragraphs.append(pb)

        capped_from = 0
        if len(valid_paragraphs) > MAX_BLOCKS_PER_FRAME:
            capped_from = len(valid_paragraphs)
            valid_paragraphs.sort(key=lambda b: b.area, reverse=True)
            valid_paragraphs = valid_paragraphs[:MAX_BLOCKS_PER_FRAME]
        valid_paragraphs.sort(key=lambda b: (b.y1, b.x1))

        blocks: List[OverlayBlock] = []
        orig_lines: List[str] = []

        for mb in valid_paragraphs:
            bg_left, bg_right, fg_color = sample_word_background_and_fg(
                self.img_bgra, mb.x1, mb.y1, mb.x2, mb.y2
            )

            raw_w = max(1, int(round((mb.x2 - mb.x1) / self.dpi_scale)))
            raw_h = max(1, int(round((mb.y2 - mb.y1) / self.dpi_scale)))
            pad_y = 2
            lw = max(16, raw_w)
            lh = max(14, raw_h + pad_y * 2)
            lx = self.offset_x + int(round(mb.x1 / self.dpi_scale)) - (lw - raw_w) // 2
            ly = self.offset_y + int(round(mb.y1 / self.dpi_scale)) - (lh - raw_h) // 2

            # Проверяем LRU-кэш или мгновенный словарь GAME_UI_DICT (0 мс)
            cleaned_key = mb.text.strip(" •·|—*<>[]").strip()
            low_key = cleaned_key.lower()
            cached = self.lru_cache.get(mb.text)
            if cached is None and low_key in GAME_UI_DICT:
                dict_val = GAME_UI_DICT[low_key]
                cached = dict_val.upper() if (cleaned_key.isupper() and len(cleaned_key.split()) <= 3) else dict_val
                self.lru_cache.put(mb.text, cached)
            if cached is None:
                cached = translate_ui_pattern(cleaned_key)

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
                    font_px=int(round(mb.font_px / self.dpi_scale)),
                )
            )
            orig_lines.append(mb.text)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        record_benchmark(used_backend, elapsed_ms)
        scale_info = f" scale={self.applied_scale:.2f}" if self.applied_scale != 1.0 else ""
        cap_info = f", из {capped_from} оставлены крупнейшие" if capped_from else ""
        log_event(
            f"[OCR_BENCHMARK] backend={used_backend}{scale_info} job=#{self.job_id} time={elapsed_ms} мс | "
            f"слов={len(raw_boxes)} -> блоков={len(blocks)}{cap_info} (отсечено мусора/RU={skipped_noise_or_ru}, "
            f"слов поверх кириллицы={self.cyrillic_dropped})"
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
        done = 0
        for start in range(0, len(indices), TRANSLATE_CHUNK_BLOCKS):
            if self._abort:
                break
            chunk = indices[start : start + TRANSLATE_CHUNK_BLOCKS]
            orig_texts = [self.pending_map[i] for i in chunk]
            translated = NATIVE_CT2.translate_batch(orig_texts)
            if self._abort:
                break
            pairs: List[Tuple[int, str, str, bool]] = [
                (idx, orig_str, tr_str, is_final)
                for idx, orig_str, (tr_str, is_final) in zip(chunk, orig_texts, translated)
            ]
            done += len(pairs)
            self.batch_translated.emit(pairs, self.job_id)

        elapsed_ms = max(1, int((time.perf_counter() - t0) * 1000))
        record_benchmark("NativeCT2", elapsed_ms)
        log_event(
            f"[TRANSLATE_BENCHMARK] engine={TRANSLATION_ENGINE} job=#{self.job_id} time={elapsed_ms} мс | "
            f"блоков={done}/{len(indices)}, порциями по {TRANSLATE_CHUNK_BLOCKS}"
        )
        self.batch_finished.emit(self.job_id)


class ModelLoaderThread(QThread):
    loaded = pyqtSignal(bool)

    def run(self):
        NATIVE_CT2.initialize()
        self.loaded.emit(NATIVE_CT2.ready)


# ==============================================================================
# WATCHDOG: СМЕНА КАРТИНКИ ПОД ПЛАШКАМИ, ВНЕ ПОТОКА ИНТЕРФЕЙСА
# ==============================================================================
class FrameWatchdogThread(QThread):
    """Раз в WATCHDOG_INTERVAL_MS снимает область под плашками и сравнивает с кадром перевода.

    Снимок монитора 3440x1440 стоит 20-27 мс, и в потоке интерфейса он подтормаживал
    панель. Здесь снимается только прямоугольник вокруг плашек, в отдельном потоке.
    После срабатывания поток замолкает до следующего arm().
    """

    screen_changed = pyqtSignal(float, int)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._region: Optional[Dict[str, int]] = None
        self._baseline: Optional[np.ndarray] = None
        self._token = 0
        self._stopped = False

    def arm(self, region: Dict[str, int], baseline: np.ndarray, token: int) -> None:
        with self._lock:
            self._region = dict(region)
            self._baseline = baseline
            self._token = token
        self._wake.set()

    def disarm(self) -> None:
        with self._lock:
            self._region = None
            self._baseline = None

    def stop(self) -> None:
        self._stopped = True
        self._wake.set()

    def run(self):
        sct = open_mss()
        try:
            while not self._stopped:
                with self._lock:
                    region, baseline, token = self._region, self._baseline, self._token
                if region is None:
                    self._wake.wait()
                    self._wake.clear()
                    continue
                self.msleep(WATCHDOG_INTERVAL_MS)
                diff = self._measure(sct, region, baseline)
                if diff is None or diff <= WATCHDOG_DIFF_THRESHOLD:
                    continue
                with self._lock:
                    if self._token != token or self._region is None:
                        continue
                    self._region = None
                    self._baseline = None
                self.screen_changed.emit(diff, token)
        finally:
            sct.close()

    @staticmethod
    def _measure(sct, region: Dict[str, int], baseline: np.ndarray) -> Optional[float]:
        try:
            shot = sct.grab(region)
        except Exception:
            return None
        frame = np.frombuffer(shot.raw, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        small_gray = compute_small_gray_numpy(frame)
        if small_gray.shape != baseline.shape:
            return None
        return float(np.mean(np.abs(small_gray - baseline)))
