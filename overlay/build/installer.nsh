; Jimmy's setup and uninstaller, on top of electron-builder's assisted NSIS installer (D61).
; Per user: no admin, no UAC. The user picks the folder (any drive); the welcome and the
; folder page say plainly what lands on C: (a few KB) and what goes where they choose.

!macro customWelcomePage
  !define MUI_WELCOMEPAGE_TITLE "Hi, I'm Jimmy."
  !define MUI_WELCOMEPAGE_TEXT "Your ambient assistant for Windows: I remember what you see and hear on this PC, answer when you ask, and do the clicking for you.$\r$\n$\r$\nThis setup puts the app (about 350 MB) in a folder you choose, on any drive. The first time I start, I'll ask where to keep your data and download what this PC needs: my own Python, the pieces I'm made of and a speech model (2 to 11 GB, your choice).$\r$\n$\r$\nNo administrator rights are needed."
  !insertmacro MUI_PAGE_WELCOME
  !define MUI_DIRECTORYPAGE_TEXT_TOP "Choose where Jimmy itself goes (about 350 MB). Any drive is fine. On first start you'll pick a second folder, for your data and Jimmy's own Python and models (2 to 11 GB): it can be on another drive.$\r$\n$\r$\nOnly this stays on C:, whatever you choose: a tiny file that remembers where your data is, the shortcuts, and the uninstall entry."
!macroend

!include FileFunc.nsh

!macro customInstall
  ; Everything else happens in Jimmy's own onboarding, where it can show progress.
  ; D64: an update Jimmy started itself (overlay/updater.cjs) asks to be started again. Not
  ; electron-builder's --force-run: that goes through ExecShellAsUser (Explorer), which did
  ; nothing on the clean-machine test. A plain Exec, as the user running this setup.
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "--jimmy-restart" $R1
  ${ifNot} ${Errors}
    Exec '"$INSTDIR\Jimmy.exe"'
  ${endIf}
!macroend

!macro customUnInstall
  ; Stop Jimmy first, or its Python would keep files open (an update too: its files get replaced).
  ; D64: its Python too, which runs from <data>\runtime, not from here.
  nsExec::Exec `powershell.exe -NoProfile -NonInteractive -Command "$$d = Get-Content -LiteralPath (Join-Path $$env:APPDATA 'Jimmy\data-path.txt') -ErrorAction SilentlyContinue | Select-Object -First 1; Get-Process | Where-Object { $$_.Path -like '$INSTDIR\*' -or ($$d -and $$_.Path -like ($$d.Trim() + '\runtime\*')) } | Stop-Process -Force"`
  Sleep 800
  ; An update runs the old uninstaller first: then Jimmy's Python, cache and the pointer to the
  ; user's data must stay, or the update would undo the setup (found in the D61 upgrade test).
  ${ifNot} ${isUpdated}
    ; What Jimmy made on first run beside itself: Electron's cache, the log.
    RMDir /r "$INSTDIR\userdata"
    Delete "$INSTDIR\setup.log"
    ClearErrors
    FileOpen $0 "$APPDATA\Jimmy\data-path.txt" r
    IfErrors done_data
    FileRead $0 $1
    FileClose $0
    StrCmp $1 "" done_data
    ; Jimmy's Python, local AI and download cache, in the data folder: always (they can be
    ; downloaded again).
    RMDir /r "$1\runtime"
    RMDir /r "$1\ollama"
    RMDir /r "$1\cache"
    ; Your data: only if you say so (a silent uninstall keeps it).
    MessageBox MB_YESNO|MB_ICONQUESTION "Also delete everything Jimmy kept?$\r$\n$\r$\n$1$\r$\n$\r$\nCaptures, screenshots, models and settings. Choose No to keep them for a reinstall." /SD IDNO IDNO done_data
    RMDir /r "$1"
    done_data:
    RMDir /r "$APPDATA\Jimmy"
  ${endIf}
!macroend
