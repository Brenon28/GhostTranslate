@echo off
chcp 65001 >nul
echo ============================================================================
echo   Сборка легкого дистрибутива GhostTranslate v3.1 (Без PyTorch и Stanza!)
echo ============================================================================

echo [1/4] Завершение запущенных экземпляров GhostTranslate...
taskkill /F /IM GhostTranslate.exe /T >nul 2>&1

echo [2/4] Компиляция dist\GhostTranslate\GhostTranslate.exe через PyInstaller...
pyinstaller --noconfirm --onedir --windowed --uac-admin --name GhostTranslate ^
  --exclude-module torch ^
  --exclude-module torchvision ^
  --exclude-module torchaudio ^
  --exclude-module argostranslate ^
  --exclude-module stanza ^
  --exclude-module spacy ^
  --exclude-module cv2 ^
  --exclude-module matplotlib ^
  --exclude-module pandas ^
  main.py

echo [3/4] Копирование компактной модели перевода model_en_ru (~110 МБ) в dist\GhostTranslate\model_en_ru...
if exist "model_en_ru" (
    xcopy /E /I /Y "model_en_ru" "dist\GhostTranslate\model_en_ru" >nul
    echo Папка model_en_ru успешно скопирована!
) else (
    echo [ВНИМАНИЕ] Папка model_en_ru не найдена в текущей директории.
    echo При первом запуске GhostTranslate автоматически распакует её из кэша Argos или словаря GAME_UI_DICT.
)

echo [4/4] Готово! Исполняемый файл собран: dist\GhostTranslate\GhostTranslate.exe
echo Теперь вы можете запустить Inno Setup со скриптом installer.iss для создания GhostTranslate_v3.1_Setup.exe (~245 МБ).
pause
