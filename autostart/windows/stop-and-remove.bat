@echo off
chcp 65001 >nul
echo === إيقاف وإزالة حلقة المدير ===
schtasks /End /TN "Abdulrahman AI OS - Manager Loop" >nul 2>&1
wmic process where "CommandLine like '%%manager.py --loop%%'" delete >nul 2>&1
schtasks /Delete /TN "Abdulrahman AI OS - Manager Loop" /F >nul 2>&1
echo ✅ أُوقفت المهمة وأُزيلت من بدء التشغيل
pause
