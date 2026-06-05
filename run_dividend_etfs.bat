@echo off
cd /d C:\value-signal-local\repo
python update_dividend_etfs.py >> logs\dividend_etfs_task.log 2>&1
