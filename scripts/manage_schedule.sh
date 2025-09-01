#!/bin/bash

# News Scraper LaunchD Management Script
# This script helps manage the automated news scraper schedule

PLIST_NAME="com.newsscraper.daily.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🔧 News Scraper Schedule Manager"
echo "================================"

# Function to show current status
show_status() {
    echo "📊 Current Status:"
    if launchctl list | grep -q "com.newsscraper.daily"; then
        echo "✅ Scheduler is ACTIVE (runs daily at 10:15 AM)"
        echo "📂 Logs location: $PROJECT_DIR/launchd_output.log"
        echo "❌ Error logs: $PROJECT_DIR/launchd_error.log"
    else
        echo "❌ Scheduler is NOT ACTIVE"
    fi
    echo ""
}

# Function to start the scheduler
start_scheduler() {
    echo "🚀 Starting news scraper scheduler..."
    if [ -f "$PLIST_PATH" ]; then
        launchctl load "$PLIST_PATH"
        echo "✅ Scheduler loaded successfully!"
    else
        echo "❌ Plist file not found at $PLIST_PATH"
        echo "Run the setup first."
        return 1
    fi
}

# Function to stop the scheduler
stop_scheduler() {
    echo "🛑 Stopping news scraper scheduler..."
    launchctl unload "$PLIST_PATH" 2>/dev/null
    echo "✅ Scheduler stopped."
}

# Function to restart the scheduler
restart_scheduler() {
    echo "🔄 Restarting news scraper scheduler..."
    stop_scheduler
    sleep 2
    start_scheduler
}

# Function to run manually
run_manual() {
    echo "🏃‍♂️ Running news scraper manually..."
    cd "$PROJECT_DIR"
    /bin/bash "./daily_auto_run.sh"
}

# Function to show logs
show_logs() {
    echo "📋 Recent output logs:"
    echo "====================="
    if [ -f "$PROJECT_DIR/launchd_output.log" ]; then
        tail -20 "$PROJECT_DIR/launchd_output.log"
    else
        echo "No output logs found."
    fi
    
    echo ""
    echo "📋 Recent error logs:"
    echo "===================="
    if [ -f "$PROJECT_DIR/launchd_error.log" ]; then
        tail -10 "$PROJECT_DIR/launchd_error.log"
    else
        echo "No error logs found."
    fi
}

# Function to test at specific time (for testing)
test_time() {
    echo "⏰ Testing scheduler for next minute..."
    NEXT_MINUTE=$(date -v+1M "+%M")
    CURRENT_HOUR=$(date "+%H")
    
    # Create temporary plist for testing
    TEMP_PLIST="$PROJECT_DIR/test_schedule.plist"
    sed "s/<integer>10<\/integer>/<integer>$CURRENT_HOUR<\/integer>/g; s/<integer>15<\/integer>/<integer>$NEXT_MINUTE<\/integer>/g" "$PROJECT_DIR/$PLIST_NAME" > "$TEMP_PLIST"
    
    # Copy to LaunchAgents with test name
    cp "$TEMP_PLIST" "$HOME/Library/LaunchAgents/com.newsscraper.test.plist"
    
    echo "📅 Test scheduled for $(date -v+1M "+%H:%M")"
    echo "🕐 Loading test scheduler..."
    launchctl load "$HOME/Library/LaunchAgents/com.newsscraper.test.plist"
    
    echo "⏳ Waiting for execution..."
    sleep 70
    
    echo "🧹 Cleaning up test scheduler..."
    launchctl unload "$HOME/Library/LaunchAgents/com.newsscraper.test.plist"
    rm "$HOME/Library/LaunchAgents/com.newsscraper.test.plist"
    rm "$TEMP_PLIST"
    
    echo "✅ Test completed. Check logs above."
}

# Main menu
case "${1:-menu}" in
    "status")
        show_status
        ;;
    "start")
        start_scheduler
        show_status
        ;;
    "stop")
        stop_scheduler
        show_status
        ;;
    "restart")
        restart_scheduler
        show_status
        ;;
    "manual")
        run_manual
        ;;
    "logs")
        show_logs
        ;;
    "test")
        test_time
        ;;
    "menu"|*)
        show_status
        echo "🎛️ Available Commands:"
        echo "   ./manage_schedule.sh status   - Show current status"
        echo "   ./manage_schedule.sh start    - Start the scheduler"
        echo "   ./manage_schedule.sh stop     - Stop the scheduler"
        echo "   ./manage_schedule.sh restart  - Restart the scheduler"
        echo "   ./manage_schedule.sh manual   - Run manually now"
        echo "   ./manage_schedule.sh logs     - Show recent logs"
        echo "   ./manage_schedule.sh test     - Test run in next minute"
        echo ""
        echo "⏰ Current schedule: Daily at 10:15 AM"
        echo "📂 Project directory: $PROJECT_DIR"
        ;;
esac
