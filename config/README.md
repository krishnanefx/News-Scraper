# Example Configuration

This directory contains configuration files for the News Scraper automation.

## Files

### `com.newsscraper.daemon.plist`
The main LaunchAgent configuration file that runs the smart daemon every 5 minutes.
- **Recommended**: Use this for reliable automation
- **Schedule**: Every 5 minutes (but only executes once daily)
- **Method**: Interval-based (more reliable than calendar)

### `com.newsscraper.daily.plist` *(Deprecated)*
Legacy calendar-based LaunchAgent configuration.
- **Status**: Deprecated due to reliability issues
- **Issues**: Missed executions during system sleep/wake
- **Replacement**: Use the daemon version instead

## Installation

The setup script automatically installs the correct configuration:

```bash
bash setup.sh
```

## Manual Installation

If you need to install manually:

```bash
# Copy the daemon configuration
cp config/com.newsscraper.daemon.plist ~/Library/LaunchAgents/

# Load the LaunchAgent
launchctl load ~/Library/LaunchAgents/com.newsscraper.daemon.plist

# Verify it's running
launchctl list | grep newsscraper
```

## Customization

To change the execution schedule, edit `TARGET_HOUR` in `scripts/news_daemon.sh`:

```bash
TARGET_HOUR=5  # Change to desired hour (0-23)
```
