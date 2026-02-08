@echo off
cd /d "%~dp0"
echo Starting HTTP Server...
echo.
echo Server running at: http://localhost:8000
echo Press Ctrl+C to stop the server
echo.
start http://localhost:8000
python -m http.server 8000
pause