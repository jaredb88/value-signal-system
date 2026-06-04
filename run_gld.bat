@echo off
cd /d C:\value-signal-local\repo
python gld_score.py >> logs\update_gld_stdout.log 2>&1
