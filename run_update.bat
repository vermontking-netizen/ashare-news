@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
python fetch_news.py >> logs\update.log 2>&1
