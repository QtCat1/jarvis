@echo off
cd /d "%~dp0"
echo Updating Jarvis...
python -m jarvis --update
echo.
pause
