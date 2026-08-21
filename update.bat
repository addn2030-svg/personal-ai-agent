@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Abdulrahman AI OS v0.3 ===
python engine\import_inbox.py
python engine\manager.py full
if exist "reports\dashboard-latest.html" start "" "reports\dashboard-latest.html"
pause
