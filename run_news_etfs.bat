@echo off
cd /d C:\value-signal-local\repo
python news_etfs.py >> logs\update_news_etfs_stdout.log 2>&1
