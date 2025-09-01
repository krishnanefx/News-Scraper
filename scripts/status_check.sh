#!/bin/bash

# News Scraper Status Check
# Quick script to verify automation status

echo "🔍 News Scraper Automation Status Check"
echo "========================================"
echo ""

# Check launchd job
echo "📅 Launchd Job Status:"
if launchctl list | grep -q "com.newsscraper.daily"; then
    echo "✅ Launchd job is active (runs daily at the scheduled time)"
    launchctl list | grep "com.newsscraper.daily"
else
    echo "❌ No launchd job found"
fi
echo ""

# Check script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📂 Script Location: $SCRIPT_DIR"
echo "📝 Main script: news_scraper.py"
echo "🤖 Automation script: daily_auto_run.sh"
echo ""

# Check recent runs
LOG_FILE="$SCRIPT_DIR/auto_run.log"
if [ -f "$LOG_FILE" ]; then
    echo "📊 Recent Activity:"
    echo "Last 3 runs:"
    grep "Starting automated news scraper run" "$LOG_FILE" | tail -3
    echo ""
    echo "Latest status:"
    tail -2 "$LOG_FILE"
else
    echo "⚠️ No log file found"
fi
echo ""

# Check Obsidian vault
VAULT_PATH="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/News"
if [ -d "$VAULT_PATH" ]; then
    echo "📁 Obsidian Vault: ✅ Found"
    echo "Recent files:"
    ls -lt "$VAULT_PATH"/*.md 2>/dev/null | head -3
else
    echo "📁 Obsidian Vault: ❌ Not found"
fi
echo ""

# Check for old launch agents
if [ -f "$HOME/Library/LaunchAgents/com.newscraper.daily.plist" ]; then
    echo "⚠️ Old launch agent still exists - should be removed"
else
    echo "✅ No conflicting launch agents"
fi
echo ""

echo "🎯 Summary:"
echo "- Your automation runs from: $SCRIPT_DIR"
echo "- Any code updates you make here will be used automatically"
echo "- Next run: Tomorrow at 5:00 AM"
echo "- Check logs: tail -f '$LOG_FILE'"
