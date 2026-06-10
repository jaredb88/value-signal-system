@echo off
cd /d C:\value-signal-local\repo
python news_gld.py >> logs\update_news_gld_stdout.log 2>&1
