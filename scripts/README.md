# Scripts Directory

This directory contains all automation and utility scripts for the News Scraper.

## Core Scripts

### `news_daemon.sh` 🎯
**Main automation daemon** - The heart of the system
- Runs every 5 minutes via LaunchAgent
- Intelligently decides when to execute (target hour only)
- Prevents duplicate runs with timestamp tracking
- **Usage**: Automatically executed by LaunchAgent

### `daily_auto_run.sh` 🚀
**Core execution script** - Does the actual work
- Downloads and processes news articles
- Handles multiple Python environments (conda → python3 → python)
- Comprehensive error handling and logging
- **Usage**: Called by daemon or manual triggers

### `setup.sh` ⚙️
**One-command setup** - Configures everything automatically
- Installs dependencies
- Sets up LaunchAgent and cron backup
- Configures Obsidian vault path
- **Usage**: `bash setup.sh`

## Utility Scripts

### `status_monitor.sh` 📊
**System status checker** - Shows current state
- LaunchAgent status
- Recent execution history
- Last run information
- **Usage**: `bash scripts/status_monitor.sh`

### `test_trigger.sh` 🧪
**Manual testing** - Force execution for testing
- Bypasses daily run limit
- Useful for debugging and verification
- **Usage**: `bash scripts/test_trigger.sh`

### `watchdog.sh` 🐕
**Setup and monitoring** - Ensures system is working
- Sets up all automation components
- Triggers manual runs if needed
- **Usage**: `bash scripts/watchdog.sh`

## Backup Scripts

### `cron_runner.sh` ⏰
**Cron backup** - Alternative scheduling method
- Runs via cron every 5 minutes
- Backup in case LaunchAgent fails
- **Usage**: Automatically via cron

### Legacy Scripts
- `manage_schedule.sh` - Old schedule management (deprecated)
- `status_check.sh` - Basic status checking (use status_monitor.sh instead)

## Quick Reference

```bash
# Check system status
bash scripts/status_monitor.sh

# Test the system
bash scripts/test_trigger.sh

# Set up everything
bash setup.sh

# View daemon activity
tail -f logs/daemon.log

# View execution logs
tail -f logs/auto_run.log
```

## File Permissions

All scripts are automatically made executable during setup. If needed manually:

```bash
chmod +x scripts/*.sh
```
