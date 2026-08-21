@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
echo === Abdulrahman AI OS — تثبيت بدء التشغيل التلقائي ===
schtasks /Create /TN "Abdulrahman AI OS - Manager Loop" /SC ONLOGON /TR "wscript.exe \"%CD%\autostart\windows\loop.vbs\"" /RL LIMITED /F
if %errorlevel% neq 0 (
  echo ❌ فشل إنشاء المهمة — شغّل الملف "كمسؤول" أو أنشئها يدويًا من Task Scheduler
  pause & exit /b 1
)
echo ✅ أُنشئت مهمة "Abdulrahman AI OS - Manager Loop" (تعمل عند كل تسجيل دخول)
echo 🚀 تشغيل فوري الآن دون إعادة تشغيل...
schtasks /Run /TN "Abdulrahman AI OS - Manager Loop"
echo.
echo 📖 التحقق أنه حي:
echo    type logs\manager-loop.log
echo    (نبض يومي في data\audit.jsonl — الحدث manager_loop_alive)
pause
