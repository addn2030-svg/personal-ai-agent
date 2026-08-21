' Abdulrahman AI OS — تشغيل حلقة المدير في الخلفية دون نافذة
' يعمل عبر Task Scheduler عند تسجيل الدخول (راجع install-autostart.bat)
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
Set shell = CreateObject("WScript.Shell")
If Not fso.FolderExists(root & "\logs") Then fso.CreateFolder(root & "\logs")
shell.CurrentDirectory = root
' نافذة مخفية (0) — السجل في logs\manager-loop.log
shell.Run "cmd /c python -u engine\manager.py --loop >> logs\manager-loop.log 2>&1", 0, False
