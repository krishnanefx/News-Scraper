#!/bin/bash

# Simple cron-based news scraper runner
# Add this to crontab with: 0 5 * * * /Users/adaikkappankrishnan/Documents/NewsScraper/scripts/cron_runner.sh

SCRIPT_DIR="/Users/adaikkappankrishnan/Documents/NewsScraper"
LOG_FILE="$SCRIPT_DIR/logs/cron_run.log"

echo "$(date): 🔄 Cron runner started" >> "$LOG_FILE"

# Change to script directory
cd "$SCRIPT_DIR"

# Run the main automation script
bash "$SCRIPT_DIR/scripts/daily_auto_run.sh" >> "$LOG_FILE" 2>&1

echo "$(date): 🔄 Cron runner finished" >> "$LOG_FILE"
