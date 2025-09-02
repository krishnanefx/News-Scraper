#!/bin/bash
# Setup script for automated news scraper scheduling on macOS

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/news_scraper.py"
PYTHON_PATH=$(which python3)

# Check if Python is available
if [ -z "$PYTHON_PATH" ]; then
    echo "❌ Python3 not found. Please install Python 3."
    exit 1
fi

# Check if the news scraper script exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "❌ News scraper script not found at $SCRIPT_PATH"
    exit 1
fi

# Create launchd plist file
PLIST_FILE="$HOME/Library/LaunchAgents/com.newsscraper.daily.plist"

cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.newsscraper.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$SCRIPT_PATH</string>
        <string>--schedule</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>5</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/auto_run.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/auto_run_error.log</string>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

echo "✅ Created launchd plist file: $PLIST_FILE"

# Load the launchd job
launchctl unload "$PLIST_FILE" 2>/dev/null
launchctl load "$PLIST_FILE"

if [ $? -eq 0 ]; then
    echo "✅ Successfully loaded launchd job"
    echo "🕐 The news scraper will now run automatically at 5 AM every day"
    echo "📁 Logs will be saved to:"
    echo "   - Output: $SCRIPT_DIR/auto_run.log"
    echo "   - Errors: $SCRIPT_DIR/auto_run_error.log"
else
    echo "❌ Failed to load launchd job"
    exit 1
fi

echo ""
echo "📋 Setup complete! The scraper will:"
echo "   • Run at 5 AM every day"
echo "   • Wait for internet if not connected"
echo "   • Catch up on missed days when internet is restored"
echo "   • Save state in scheduler_state.json"
echo ""
echo "To stop the automated runs:"
echo "   launchctl unload $PLIST_FILE"
echo ""
echo "To check status:"
echo "   launchctl list | grep newsscraper"
