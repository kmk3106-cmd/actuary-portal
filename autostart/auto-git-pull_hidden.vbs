' Hidden launcher for ActuaryPortal auto-git-pull.
' Runs auto-git-pull.ps1 with no console window (no flash).
' Window style 0 = hidden, bWaitOnReturn = False = fire-and-forget.
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\USER\actuary potal\autostart\auto-git-pull.ps1""", 0, False
