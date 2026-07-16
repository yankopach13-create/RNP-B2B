@echo off
setlocal

REM Переходим в директорию, где лежит .bat
cd /d "%~dp0"

REM Останавливаем зависший Streamlit (старый код в памяти)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM Запуск Streamlit через python из виртуального окружения
".\.venv\Scripts\python.exe" -m streamlit run app.py

pause
