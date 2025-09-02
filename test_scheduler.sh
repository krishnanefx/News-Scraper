#!/bin/bash
# Test script for the smart scheduler functionality

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/news_scraper.py"
PYTHON_PATH=$(which python3)

echo "🧪 Testing Smart Scheduler Functionality"
echo "========================================"

# Test 1: Check internet connectivity
echo ""
echo "1. Testing internet connectivity..."
"$PYTHON_PATH" -c "
import sys
sys.path.append('$SCRIPT_DIR')
from news_scraper import SmartScheduler, NewsScraper, NewsConfig

config = NewsConfig()
scraper = NewsScraper(config)
scheduler = SmartScheduler(scraper)

if scheduler.check_internet_connection():
    print('✅ Internet connection available')
else:
    print('❌ No internet connection')
"

# Test 2: Check scheduler state management
echo ""
echo "2. Testing scheduler state management..."
"$PYTHON_PATH" -c "
import sys
sys.path.append('$SCRIPT_DIR')
from news_scraper import SmartScheduler, NewsScraper, NewsConfig
from datetime import datetime, timedelta

config = NewsConfig()
scraper = NewsScraper(config)
scheduler = SmartScheduler(scraper)

# Test adding missed days
test_date = datetime.now() - timedelta(days=1)
scheduler.add_missed_day(test_date)
print(f'✅ Added missed day: {test_date.date()}')

# Check state
missed_count = len(scheduler.state.missed_days or [])
print(f'📊 Current missed days: {missed_count}')

# Test removing missed day
scheduler.remove_missed_day(test_date)
missed_count = len(scheduler.state.missed_days or [])
print(f'📊 After removal, missed days: {missed_count}')
"

# Test 3: Check next run time calculation
echo ""
echo "3. Testing next run time calculation..."
"$PYTHON_PATH" -c "
import sys
sys.path.append('$SCRIPT_DIR')
from news_scraper import SmartScheduler, NewsScraper, NewsConfig

config = NewsConfig()
scraper = NewsScraper(config)
scheduler = SmartScheduler(scraper)

next_run = scheduler.get_next_run_time()
print(f'🕐 Next scheduled run: {next_run.strftime(\"%Y-%m-%d %H:%M:%S\")}')
"

echo ""
echo "✅ All tests completed!"
echo ""
echo "📋 To set up automated scheduling:"
echo "   ./setup_automation.sh"
echo ""
echo "📋 Manual testing commands:"
echo "   # Test scheduled mode (will wait for 5 AM)"
echo "   python news_scraper.py --schedule"
echo ""
echo "   # Test monitoring mode (continuous checking)"
echo "   python news_scraper.py --monitor"
echo ""
echo "   # Test specific date"
echo "   python news_scraper.py --date '03 09 2025'"
