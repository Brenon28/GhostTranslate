@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] Завершение собранного GhostTranslate.exe, если он запущен...
taskkill /F /IM GhostTranslate.exe /T >nul 2>&1

echo [2/2] Запуск GhostTranslate v3.4
echo       F8: скрыть или показать, F9: выделить область
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    py -3.12 main.py
)
