#!/bin/bash

# News Scraper Status Monitor
# Shows current status and recent activity

SCRIPT_DIR="/Users/adaikkappankrishnan/Documents/NewsScraper"

echo "🗞️  NEWS SCRAPER STATUS MONITOR"
echo "=================================="
echo "📅 Current Time: $(date)"
echo ""

# Check LaunchAgent status
echo "🔧 LAUNCHD STATUS:"
if launchctl list | grep -q com.newsscraper.daemon; then
    echo "✅ Daemon is loaded and running"
    launchctl list | grep newsscraper
else
    echo "❌ Daemon not loaded"
fi
echo ""

# Check cron status
echo "⏰ CRON STATUS:"
if crontab -l 2>/dev/null | grep -q news_daemon; then
    echo "✅ Cron backup is active"
    crontab -l | grep news_daemon
else
    echo "❌ No cron backup found"
fi
echo ""

# Check last run
echo "📊 LAST RUN INFO:"
if [ -f "$SCRIPT_DIR/logs/last_run_timestamp" ]; then
    echo "📅 Last run day: $(head -1 "$SCRIPT_DIR/logs/last_run_timestamp")"
    echo "🕐 Last run hour: $(tail -1 "$SCRIPT_DIR/logs/last_run_timestamp")"
else
    echo "❓ No run timestamp found"
fi
echo ""

# Show recent daemon activity
echo "📋 RECENT DAEMON ACTIVITY:"
if [ -f "$SCRIPT_DIR/logs/daemon.log" ]; then
    tail -5 "$SCRIPT_DIR/logs/daemon.log"
else
    echo "❓ No daemon log found"
fi
echo ""

# Show recent automation activity
echo "📋 RECENT AUTOMATION ACTIVITY:"
if [ -f "$SCRIPT_DIR/logs/auto_run.log" ]; then
    tail -3 "$SCRIPT_DIR/logs/auto_run.log"
else
    echo "❓ No automation log found"
fi
