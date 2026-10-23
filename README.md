# GhostTranslate

Оверлей для Windows 10/11: выделяется область экрана, английский текст распознаётся и перевод рисуется поверх окна. Текущая версия: 3.0.

Весь код приложения лежит в `main.py`. Глобальные клавиши регистрируются через Win32, поэтому процесс нужен с правами администратора.

## Запуск из исходников

Нужен Python 3.12 x64.

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

`run_ghost.bat` делает то же самое системным `python` и перед стартом закрывает уже запущенный GhostTranslate.

## Клавиши

- F8: скрыть или показать оверлей и панель.
- F9: выделить область захвата мышью.
- Кнопка «Aa Шрифт» на панели меняет гарнитуру, размер и выравнивание. Настройки пишутся в `settings.json` рядом с программой и в git не попадают.

## Модель перевода

Полный перевод EN-RU делает CTranslate2 (int8, CPU) и SentencePiece. Веса кладутся рядом с `main.py`:

```text
model_en_ru/
  sentencepiece.model
  model/
    config.json
    model.bin
    shared_vocabulary.json
```

`model.bin` около 204 МБ. В репозиторий он не входит: у GitHub лимит 100 МБ на файл. Если папки нет, остаётся встроенный словарь игровых меню.

Программа сама ищет модель в трёх местах:

1. `model_en_ru` рядом со скриптом или с exe.
2. Уже распакованный кэш `%USERPROFILE%\.local\share\argos-translate\packages` с `en_ru` в имени папки.
3. Архив `*en_ru*.argosmodel` или `*en_ru*.zip` в рабочей папке или в `%USERPROFILE%\.local\share\argos-translate\downloads`. Архив распаковывается в `model_en_ru`.

## Запасной OCR

Основной распознаватель — Windows OCR (`winocr`). RapidOCR необязателен: без него программа работает. Чтобы включить его и собирать exe:

```bat
pip install -r requirements-dev.txt
```

## Сборка

`build_exe.bat` собирает `dist\GhostTranslate\GhostTranslate.exe` через PyInstaller и, если папка есть, копирует туда `model_en_ru`. Скрипт Inno Setup `installer.iss` пакует эту папку в установщик. Каталоги `build\`, `dist\` и `installer_out\` в git не коммитятся.

PyTorch, Argos Translate, Stanza и OpenCV в эту сборку не входят. Перевод идёт прямым вызовом CTranslate2.
