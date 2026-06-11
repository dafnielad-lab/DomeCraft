@echo off
cd /d "%~dp0"
echo ==========================================
echo   Dome Points Console Launcher
echo ==========================================
echo.
echo Starting Streamlit server...
streamlit run Dome_Points_Console.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Streamlit failed to start.
    echo Attempting to install missing requirements...
    pip install -r requirements.txt
    echo.
    echo Retrying...
    streamlit run Dome_Points_Console.py
)
pause
