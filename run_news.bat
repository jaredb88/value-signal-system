@echo off
REM Tarea programada: actualiza noticias del watchlist (Google News RSS)
REM Frecuencia: cada 2 horas
REM Hace git pull antes y git commit + push despues si hay cambios

cd /d C:\value-signal-local\repo
"C:\Users\max\AppData\Local\Programs\Python\Python314\python.exe" news_fetcher.py
