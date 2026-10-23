@echo off
chcp 65001 >nul
echo [1/2] Завершение старых экземпляров GhostTranslate...
taskkill /F /IM GhostTranslate.exe /T >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1

echo [2/2] Запуск GhostTranslate v3.0 (F8: Скрыть/Раскрыть, F9: Выделить, NativeCT2 Lite Core)...
python main.py
