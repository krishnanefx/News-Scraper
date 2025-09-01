#!/bin/bash

# Daily News Scraper Automation Script
# This script runs the news scraper with robust error handling and multiple fallbacks
# Updated to always use the latest code from this directory

# Configuration - Automatically detect current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PARENT_DIR/logs/auto_run.log"
VAULT_PATH="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/News"
LOCK_FILE="$PARENT_DIR/logs/news_scraper.lock"

# Set to "true" to enable sleep after completion (macOS only)
ENABLE_SLEEP=false

# Function to log with timestamp
log_message() {
    echo "$(date): $1" >> "$LOG_FILE"
}

# Function to check if already running
check_lock() {
    if [ -f "$LOCK_FILE" ]; then
        local pid=$(cat "$LOCK_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            log_message "🔒 Script already running with PID $pid, exiting"
            exit 0
        else
            log_message "🧹 Removing stale lock file"
            rm -f "$LOCK_FILE"
        fi
    fi
}

# Function to create lock
create_lock() {
    echo $$ > "$LOCK_FILE"
    log_message "🔒 Created lock file with PID $$"
}

# Function to remove lock
remove_lock() {
    rm -f "$LOCK_FILE"
    log_message "🔓 Removed lock file"
}

# Function to check if we should run (once per day)
should_run() {
    local today=$(date +%Y-%m-%d)
    local last_run_file="$PARENT_DIR/logs/last_run_date"
    
    if [ -f "$last_run_file" ]; then
        local last_run=$(cat "$last_run_file")
        if [ "$last_run" = "$today" ]; then
            log_message "⏭️  Already ran today ($today), skipping"
            return 1
        fi
    fi
    
    echo "$today" > "$last_run_file"
    log_message "✅ Scheduled to run for $today"
    return 0
}

# Trap to ensure lock is removed on exit
trap remove_lock EXIT

# Start execution
log_message "🚀 Starting automated news scraper run"
log_message "📂 Working directory: $PARENT_DIR"
log_message "📝 Script: $0"

# Check if we should run
if ! should_run; then
    exit 0
fi

# Check for existing process
check_lock
create_lock

# Ensure we're in the correct directory
cd "$PARENT_DIR"
log_message "📁 Changed to directory: $(pwd)"

# Check if main script exists
if [ ! -f "news_scraper.py" ]; then
    log_message "❌ news_scraper.py not found in $PARENT_DIR"
    exit 1
fi

log_message "🔧 Script last modified: $(stat -f "%Sm" "news_scraper.py")"

# Set environment variables for optimal performance
export PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0
export TRANSFORMERS_CACHE="$HOME/.cache/huggingface/transformers"
export TOKENIZERS_PARALLELISM=false

log_message "📰 Running news scraper..."

# Try multiple Python executables in order of preference
python_found=false
exit_code=1

# Try conda first
if command -v conda >/dev/null 2>&1; then
    log_message "🐍 Trying conda environment"
    if source ~/opt/anaconda3/etc/profile.d/conda.sh 2>/dev/null; then
        if conda activate base 2>/dev/null; then
            log_message "✅ Conda environment activated"
            python news_scraper.py --vault-path "$VAULT_PATH" >> "$LOG_FILE" 2>&1
            exit_code=$?
            python_found=true
        fi
    fi
fi

# Try system python3 if conda failed
if [ "$python_found" = false ] && command -v python3 >/dev/null 2>&1; then
    log_message "🐍 Trying system python3"
    python3 news_scraper.py --vault-path "$VAULT_PATH" >> "$LOG_FILE" 2>&1
    exit_code=$?
    python_found=true
fi

# Try system python if python3 failed
if [ "$python_found" = false ] && command -v python >/dev/null 2>&1; then
    log_message "🐍 Trying system python"
    python news_scraper.py --vault-path "$VAULT_PATH" >> "$LOG_FILE" 2>&1
    exit_code=$?
    python_found=true
fi

# Check if any Python was found
if [ "$python_found" = false ]; then
    log_message "❌ No Python interpreter found"
    exit 1
fi

# Check if successful
if [ $exit_code -eq 0 ]; then
    log_message "✅ News scraper completed successfully"
else
    log_message "❌ News scraper failed with exit code $exit_code"
    log_message "Will try again tomorrow..."
fi

# Wait for file operations
sleep 10

# Optional: Put computer to sleep (macOS only, requires admin privileges)
if [ "$ENABLE_SLEEP" = "true" ] && command -v pmset >/dev/null 2>&1; then
    log_message "😴 Putting computer to sleep..."
    pmset sleepnow
else
    log_message "🏁 Automation complete (sleep disabled)"
fi

exit $exit_code

