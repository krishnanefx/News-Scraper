# Quick Setup Guide

## 1. Install Dependencies
```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

## 2. Set NewsAPI Key (Optional)
```bash
export NEWSAPI_KEY="your_api_key_here"
```

## 3. Run Once to Test
```bash
python news_scraper.py --vault-path "/path/to/your/obsidian/vault/News"
```

## 4. Set Up Automation (macOS)
```bash
cp com.newsscraper.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.newsscraper.daily.plist
```

## 5. Verify Setup
- Check that daily notes are created in your Obsidian vault
- Verify automation is scheduled with `launchctl list | grep newsscraper`
- Monitor logs in `auto_run.log` and `launchd_output.log` after automation runs

## Troubleshooting
- Ensure Python 3.8+ is installed
- Check Obsidian vault path exists
- Verify internet connection for news fetching
- For automation issues, check `launchd_error.log`
