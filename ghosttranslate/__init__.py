"""GhostTranslate v3.0 — Exact Menu Positioning, FontSettingsPopup, Global F8/F9 Hotkeys & Native CT2 Lite Core
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
3. Глобальные клавиши (по умолчанию F8 / F9, меняются в «Aa Шрифт») и удаление старой текстовой плашки над рамкой:
   - F8: Мгновенное Скрыть / Показать оверлей и панель (мини-таблетка "👻 GT [F8]").
   - F9: Включение режима выделения области (курсор-крестик, выделение обычной ЛКМ без зажатия клавиш).
   - Win32 RegisterHotKey, а если сочетание занято — опрос GetAsyncKeyState (25 мс).
4. Легковесное нативное ядро NativeCT2Translator (БЕЗ torch, argostranslate, stanza, spacy и cv2):
   - Прямой вызов ctranslate2.Translator(..., device="cpu", compute_type="int8", inter_threads=4) + sentencepiece.
   - Авто-распаковка модели в ./model_en_ru из кэша Argos (.argosmodel zip) или рабочей папки .exe.
   - Чистый NumPy + QImage вместо opencv-python (small_gray = np.mean(frame[::8, ::8], axis=2)).
"""
