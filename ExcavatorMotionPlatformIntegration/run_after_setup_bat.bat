@echo off
set "scriptPath=%~dp0"
"%scriptPath%\\.venv\\Scripts\\python.exe" "%scriptPath%\\src\\gui\\gui.py"
echo "Gui.py closed - Press enter to exit this window"
pause