#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Точка входа GhostTranslate. Её запускают run_ghost.bat и сборка PyInstaller."""

import os

# OpenBLAS внутри numpy при импорте резервирует буфер на каждое ядро: около 500 МБ
# выделенной памяти на 16 потоках. Матричная математика программе не нужна.
# Переменная действует, только если задана до первого импорта numpy.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from ghosttranslate.app import main  # noqa: E402

if __name__ == "__main__":
    main()
