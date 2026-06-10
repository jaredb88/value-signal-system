@echo off
cd /d C:\value-signal-local\repo
python news_chile.py >> logs\update_news_chile_stdout.log 2>&1
