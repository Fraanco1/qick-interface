@echo off
rem Runs the QICK Analyzer on the Windows lab PC and starts it again 10 s after it stops (board off at boot,
rem a crash). Started at boot by the "QICK Analyzer" scheduled task (install_task.ps1). Output: data\server.log
cd /d "%~dp0..\.."
if not exist data mkdir data
:loop
echo ==== %date% %time% starting >> data\server.log
.venv\Scripts\python.exe -m qick_interface --host 0.0.0.0 --port 8090 >> data\server.log 2>&1
echo ==== %date% %time% stopped (exit %errorlevel%), restarting in 10 s >> data\server.log
timeout /t 10 /nobreak > nul
goto loop
