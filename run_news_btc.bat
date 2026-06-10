@echo off
cd /d C:\value-signal-local\repo
python news_btc.py >> logs\update_news_btc_stdout.log 2>&1
