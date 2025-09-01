#!/bin/bash

# Reliable News Scraper Daemon
# This runs every 5 minutes and checks if it should execute the news scraper
# Much more reliable than calendar-based scheduling

SCRIPT_DIR="/Users/adaikkappankrishnan/Documents/NewsScraper"
LOG_FILE="$SCRIPT_DIR/logs/daemon.log"
LAST_RUN_FILE="$SCRIPT_DIR/logs/last_run_timestamp"
TARGET_HOUR=11

log_msg() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" | tee -a "$LOG_FILE"
}

# Get current time components
current_hour=$(date +%H)
current_minute=$(date +%M)
current_day=$(date +%Y-%m-%d)

log_msg "🔄 Daemon check - Hour: $current_hour, Minute: $current_minute"

# Check if we should run (once per day at target hour)
should_run=false

# Read last run info
if [ -f "$LAST_RUN_FILE" ]; then
    last_run_day=$(cat "$LAST_RUN_FILE" 2>/dev/null | head -1)
    last_run_hour=$(cat "$LAST_RUN_FILE" 2>/dev/null | tail -1)
else
    last_run_day=""
    last_run_hour=""
fi

# Logic: Run if it's the target hour and we haven't run today yet
if [ "$current_hour" -eq "$TARGET_HOUR" ]; then
    if [ "$last_run_day" != "$current_day" ]; then
        should_run=true
        log_msg "✅ Should run: Target hour ($TARGET_HOUR) and haven't run today"
    else
        log_msg "⏭️  Already ran today at hour $last_run_hour"
    fi
else
    log_msg "⏱️  Not target hour (current: $current_hour, target: $TARGET_HOUR)"
fi

if [ "$should_run" = true ]; then
    log_msg "🚀 EXECUTING NEWS SCRAPER"
    
    # Record this run
    echo "$current_day" > "$LAST_RUN_FILE"
    echo "$current_hour" >> "$LAST_RUN_FILE"
    
    # Change to script directory
    cd "$SCRIPT_DIR"
    
    # Remove any locks
    rm -f logs/news_scraper.lock
    rm -f logs/last_run_date
    
    # Run the scraper
    log_msg "📰 Starting news scraper execution..."
    bash scripts/daily_auto_run.sh >> "$LOG_FILE" 2>&1
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log_msg "✅ News scraper completed successfully!"
    else
        log_msg "❌ News scraper failed with exit code $exit_code"
    fi
else
    log_msg "💤 No execution needed"
fi

log_msg "🔄 Daemon check complete"
