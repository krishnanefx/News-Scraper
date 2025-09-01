#!/bin/bash

# Manual trigger for testing the news scraper
# Usage: ./test_trigger.sh

SCRIPT_DIR="/Users/adaikkappankrishnan/Documents/NewsScraper"

echo "🧪 Manual trigger started at $(date)"
echo "📂 Working in: $SCRIPT_DIR"

cd "$SCRIPT_DIR"

# Remove any lock files for testing
rm -f logs/news_scraper.lock
rm -f logs/last_run_date

echo "🚀 Running automation script..."
bash scripts/daily_auto_run.sh

echo "✅ Manual trigger completed at $(date)"
echo "📋 Check logs/auto_run.log for details"
