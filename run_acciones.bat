@echo off
REM ===================================================================
REM Update Acciones Chilenas - Tarea Programada Windows
REM Frecuencia: cada 30 minutos
REM ===================================================================

cd /d C:\value-signal-local\repo

REM Ejecutar el wrapper que hace pull + scraper + push
python update_acciones.py

REM Salir con el codigo de retorno de python
exit /b %ERRORLEVEL%
