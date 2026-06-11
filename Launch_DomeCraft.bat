@echo off
cd /d "%~dp0"
echo ==========================================
echo   DomeCraft Launcher
echo ==========================================
echo.
echo Starting Streamlit server...
streamlit run DomeCraft.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Streamlit failed to start.
    echo Attempting to install missing requirements...
    pip install -r requirements.txt
    echo.
    echo Retrying...
    streamlit run DomeCraft.py
)
pause
