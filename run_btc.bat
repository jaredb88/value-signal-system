@echo off
cd /d C:\value-signal-local\repo
python btc_score.py >> logs\btc_task.log 2>&1
