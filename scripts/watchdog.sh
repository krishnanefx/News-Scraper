#!/bin/bash

# Robust News Scraper Watchdog
# This script ensures the news scraper runs no matter what
# It uses multiple methods: launchd, cron backup, and manual triggers

SCRIPT_DIR="/Users/adaikkappankrishnan/Documents/NewsScraper"
LOG_FILE="$SCRIPT_DIR/logs/watchdog.log"

log_msg() {
    echo "$(date): $1" | tee -a "$LOG_FILE"
}

log_msg "🐕 Watchdog starting"

# 1. Ensure launchd job is loaded
if ! launchctl list | grep -q com.newsscraper.daily; then
    log_msg "🔧 Loading launchd job"
    launchctl load ~/Library/LaunchAgents/com.newsscraper.daily.plist
fi

# 2. Check if we need to run manually (if launchd failed)
today=$(date +%Y-%m-%d)
last_run_file="$SCRIPT_DIR/logs/last_successful_run"

if [ -f "$last_run_file" ]; then
    last_run=$(cat "$last_run_file")
    if [ "$last_run" != "$today" ]; then
        log_msg "🚨 No run detected today, triggering manual run"
        cd "$SCRIPT_DIR"
        bash scripts/daily_auto_run.sh >> "$LOG_FILE" 2>&1
        if [ $? -eq 0 ]; then
            echo "$today" > "$last_run_file"
            log_msg "✅ Manual run successful"
        else
            log_msg "❌ Manual run failed"
        fi
    else
        log_msg "✅ Already ran today"
    fi
else
    log_msg "🏃 First run, executing..."
    cd "$SCRIPT_DIR"
    bash scripts/daily_auto_run.sh >> "$LOG_FILE" 2>&1
    if [ $? -eq 0 ]; then
        echo "$today" > "$last_run_file"
        log_msg "✅ First run successful"
    else
        log_msg "❌ First run failed"
    fi
fi

# 3. Set up cron backup if not exists
if ! crontab -l 2>/dev/null | grep -q "news_scraper"; then
    log_msg "⏰ Setting up cron backup"
    (crontab -l 2>/dev/null; echo "0 5 * * * /Users/adaikkappankrishnan/Documents/NewsScraper/scripts/cron_runner.sh") | crontab -
fi

log_msg "🐕 Watchdog completed"
