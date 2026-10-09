@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Bitte Python 3.11 oder neuer von python.org installieren.
    pause
    exit /b 1
  )
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)
if not exist ".venv\stream-installed-native-v1" (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
  echo ready>".venv\stream-installed-native-v1"
)
".venv\Scripts\python.exe" -m stream_player
exit /b
:failed
echo Einrichtung fehlgeschlagen. Bitte Internetverbindung und Python pruefen.
pause
exit /b 1
