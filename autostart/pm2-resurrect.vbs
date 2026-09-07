' actuary-portal — PM2 resurrect on Windows logon
'   Run by Startup folder via wscript (hidden). Resurrects dump.pm2 apps
'   (actuary-portal Node server + actuary-bot Telegram) after login.
'
'   Why cmd /c wrap:
'     WshShell.Run on a .cmd file directly fails with 80070002 on some
'     Windows configurations (CreateProcess does not route .cmd through
'     cmd.exe automatically when quoting is non-trivial). Explicit
'     "cmd.exe /c <path>" makes it work reliably.
'
'   To verify: double-click this file. Success = silent (no popup),
'   then check `pm2 status` to see actuary-portal and actuary-bot online.

Set sh = CreateObject("WScript.Shell")
sh.Run "cmd.exe /c ""C:\Users\USER\AppData\Roaming\npm\pm2.cmd"" resurrect", 0, False
