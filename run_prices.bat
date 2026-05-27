@echo off
REM ===================================================================
REM Update Prices ETFs - Tarea Programada Windows
REM Frecuencia: cada 30 minutos
REM ===================================================================
cd /d C:\value-signal-local\repo
python update_prices.py
exit /b %ERRORLEVEL%
