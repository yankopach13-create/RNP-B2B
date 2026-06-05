@echo off
setlocal

REM Переходим в директорию, где лежит .bat
cd /d "%~dp0"

REM Запуск Streamlit через python из виртуального окружения
".\.venv\Scripts\python.exe" -m streamlit run app.py

pause