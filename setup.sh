#!/bin/bash

# News Scraper Setup Script
# Automated installation and configuration

set -e

echo "🗞️  NEWS SCRAPER SETUP"
echo "====================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    log_error "This setup script is designed for macOS only"
    exit 1
fi

log_info "Setting up News Scraper in: $SCRIPT_DIR"

# Check Python installation
log_info "Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    log_success "Python 3 found: $PYTHON_VERSION"
else
    log_error "Python 3 not found. Please install Python 3.8 or higher"
    exit 1
fi

# Check pip
if command -v pip3 &> /dev/null || command -v pip &> /dev/null; then
    log_success "pip found"
else
    log_error "pip not found. Please install pip"
    exit 1
fi

# Install Python dependencies
log_info "Installing Python dependencies..."
if pip3 install -r "$SCRIPT_DIR/requirements.txt" &> /dev/null; then
    log_success "Dependencies installed successfully"
else
    log_warning "Some dependencies may have failed to install. Continuing..."
fi

# Make scripts executable
log_info "Making scripts executable..."
chmod +x "$SCRIPT_DIR"/scripts/*.sh
log_success "Scripts made executable"

# Create logs directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/logs"
log_success "Logs directory ready"

# Configure vault path
log_info "Configuring Obsidian vault path..."
echo ""
echo "Please enter your Obsidian vault path."
echo "Common locations:"
echo "  - ~/Documents/ObsidianVault"
echo "  - ~/Library/Mobile Documents/iCloud~md~obsidian/Documents/VaultName"
echo ""
read -p "Obsidian vault path: " VAULT_PATH

if [[ -d "$VAULT_PATH" ]]; then
    # Update the vault path in the script
    sed -i.bak "s|VAULT_PATH=\".*\"|VAULT_PATH=\"$VAULT_PATH\"|" "$SCRIPT_DIR/scripts/daily_auto_run.sh"
    log_success "Vault path configured: $VAULT_PATH"
else
    log_warning "Vault path doesn't exist yet: $VAULT_PATH"
    log_warning "Make sure to create it or update the path later"
fi

# Set up automation
log_info "Setting up automation..."

# Remove any existing jobs
launchctl unload ~/Library/LaunchAgents/com.newsscraper.* 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.newsscraper.* 2>/dev/null || true

# Install new daemon
cp "$SCRIPT_DIR/config/com.newsscraper.daemon.plist" ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.newsscraper.daemon.plist

if launchctl list | grep -q com.newsscraper.daemon; then
    log_success "LaunchAgent installed successfully"
else
    log_error "Failed to install LaunchAgent"
    exit 1
fi

# Set up cron backup
log_info "Setting up cron backup..."
(crontab -l 2>/dev/null | grep -v news_daemon; echo "*/5 * * * * $SCRIPT_DIR/scripts/news_daemon.sh") | crontab -
log_success "Cron backup configured"

# Test the system
log_info "Testing the system..."
if bash "$SCRIPT_DIR/scripts/status_monitor.sh" > /dev/null; then
    log_success "System test passed"
else
    log_warning "System test had issues, but continuing..."
fi

echo ""
echo "🎉 SETUP COMPLETE!"
echo "=================="
echo ""
echo "Your News Scraper is now configured and will run automatically."
echo ""
echo "📊 Status: $(bash "$SCRIPT_DIR/scripts/status_monitor.sh" | grep "Daemon is" | head -1)"
echo "⏰ Schedule: Every day at 11:00 AM (configurable)"
echo "📁 Logs: $SCRIPT_DIR/logs/"
echo ""
echo "🔧 NEXT STEPS:"
echo "1. Monitor status: bash scripts/status_monitor.sh"
echo "2. View logs: tail -f logs/daemon.log"
echo "3. Test manually: bash scripts/test_trigger.sh"
echo ""
echo "📚 See README.md for detailed documentation"
echo ""
