import io
import threading
import wave
from typing import Sequence, Tuple

import numpy as np

try:
    import winsound
except ImportError:
    winsound = None


SAMPLE_RATE = 44100


# ==============================================================================
# МЯГКИЙ ЗВОН ВКЛЮЧЕНИЯ И ВЫКЛЮЧЕНИЯ
# ==============================================================================
def render_chime(
    notes: Sequence[Tuple[float, float]],
    duration_s: float,
    volume: float = 0.2,
    decay_s: float = 0.22,
) -> bytes:
    """WAV 16 бит моно. notes — пары (частота Гц, начало в секундах).

    winsound.Beep даёт прямоугольную волну без огибающей, отсюда резкий писк.
    Здесь синус с мягкой атакой и экспоненциальным затуханием, как у колокольчика.
    """
    t = np.arange(int(SAMPLE_RATE * duration_s)) / SAMPLE_RATE
    signal = np.zeros_like(t)
    for freq, start in notes:
        local = t - start
        active = local >= 0
        lt = local[active]
        envelope = (1.0 - np.exp(-lt / 0.008)) * np.exp(-lt / decay_s)
        tone = (
            np.sin(2 * np.pi * freq * lt)
            + 0.22 * np.sin(2 * np.pi * 2 * freq * lt) * np.exp(-lt / 0.09)
            + 0.06 * np.sin(2 * np.pi * 3 * freq * lt) * np.exp(-lt / 0.05)
        )
        signal[active] += envelope * tone

    fade = min(len(signal), int(SAMPLE_RATE * 0.06))
    if fade:
        signal[-fade:] *= np.linspace(1.0, 0.0, fade)
    peak = float(np.max(np.abs(signal))) or 1.0
    pcm = (signal / peak * volume * 32767).astype("<i2")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _play_wav(data: bytes) -> None:
    # SND_ASYNC вместе с SND_MEMORY winsound не поддерживает, поэтому вызов блокирующий.
    try:
        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception:
        pass


def play_startup_sound() -> None:
    """Восходящая квинта ре — ля."""
    if winsound is None:
        return
    data = render_chime([(587.33, 0.0), (880.0, 0.11)], duration_s=0.75)
    threading.Thread(target=_play_wav, args=(data,), daemon=True).start()


def play_shutdown_sound_sync() -> None:
    """Нисходящая квинта ля — ре, короче и тише: процесс ждёт её окончания перед выходом."""
    if winsound is None:
        return
    _play_wav(render_chime([(880.0, 0.0), (587.33, 0.09)], duration_s=0.5, volume=0.16, decay_s=0.15))
