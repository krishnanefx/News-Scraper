# 🗞️ Daily News Scraper for Obsidian

An automated news aggregation script that fetches world news from curated RSS feeds, analyzes it with NLP models, and writes organized, interlinked notes into your Obsidian vault.

## ✨ Features

### 🧠 AI Analysis
- **Apple Silicon GPU acceleration** – Uses PyTorch MPS when available (falls back to CPU)
- **Sentiment analysis** – DistilBERT (`distilbert-base-uncased-finetuned-sst-2-english`)
- **Auto-summarization** – BART (`facebook/bart-large-cnn`)
- **Entity extraction** – spaCy (`en_core_web_sm`) for people, organizations, places and events
- **Topic tracking & bias analysis** – Topic categorization, multi-perspective bias notes and source reliability tracking

### 📰 News Curation
- **RSS-first** – 15 curated feeds; NewsAPI is only used to top up when RSS returns too few articles
- **Quality filtering** – Readability scoring, anti-clickbait/promotional filtering and deduplication (including across days)
- **Regional quotas** – Balances coverage across Africa, Middle East, Asia, Europe and the US
- **Daily cap** – Up to 30 articles per day by default

### 🔗 Obsidian Organization
- **Cross-day linking** – Connects related stories that share entities
- **Entity notes** – Profiles for people, organizations and locations
- **Topic & timeline notes** – Tracks ongoing events and topic histories, plus a Topics MOC
- **Coverage gap analysis & daily dashboard**
- **Personalized recommendations** – Based on a locally stored interest profile

### 🤖 Smart Scheduling
- **Daily 5 AM runs** via a macOS LaunchAgent
- **Internet awareness** – Waits for connectivity before running
- **Missed-day catch-up** – Runs for missed days once internet is restored
- **Persistent state** – Tracked in `scheduler_state.json`; skips days whose note already exists

## 📁 Project Structure

```
News-Scraper/
├── news_scraper.py        # Main application (scraper, analysis, scheduler, CLI)
├── requirements.txt       # Python dependencies
├── setup_automation.sh    # Installs the macOS LaunchAgent (5 AM daily)
├── test_scheduler.sh      # Tests connectivity check, state handling, next-run time
└── README.md
```

Generated at runtime (git-ignored): `scheduler_state.json`, `auto_run.log`, `auto_run_error.log`.

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- An Obsidian vault
- macOS for the LaunchAgent automation (the script itself is cross-platform)

### Installation

```bash
git clone https://github.com/krishnanefx/News-Scraper.git
cd News-Scraper
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### Configure

Set your vault's News folder (the default in the code is the author's own iCloud path):

```bash
export OBSIDIAN_VAULT_PATH="$HOME/path/to/vault/News"
```

or pass `--vault-path` on each run.

### Run

```bash
python news_scraper.py                         # today
python news_scraper.py --date "03 09 2025"     # DD MM YYYY (YYYY-MM-DD also accepted)
python news_scraper.py --vault-path "/path/to/vault/News"
python news_scraper.py --health                # dependency/config health check
python news_scraper.py --stats                 # performance statistics
python news_scraper.py --schedule              # wait for 5 AM daily, with catch-up
python news_scraper.py --monitor               # continuous internet monitoring mode
```

## ⚙️ Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `OBSIDIAN_VAULT_PATH` | author's iCloud vault path | Output folder |
| `NEWSAPI_KEY` | none (optional) | NewsAPI key for supplementary articles |
| `NEWSAPI_URL` | `https://newsapi.org/v2/top-headlines` | NewsAPI endpoint |
| `RSS_FEEDS` | 15 built-in feeds | Comma-separated feed URLs to override the list |
| `REGIONAL_QUOTAS` | `Africa:3,Middle East:4,Asia:8,Europe:8,US:7` | Articles per region |
| `MAX_ARTICLES_PER_DAY` | `30` | Daily cap |
| `READABILITY_THRESHOLD` | `30` | Minimum readability score |
| `ENABLE_FULL_TEXT_EXTRACTION` | `true` | Fetch full article text (newspaper3k) |
| `ENABLE_SENTIMENT_ANALYSIS` | `true` | Load sentiment model |
| `ENABLE_TOPIC_MODELING` | `true` | Topic categorization |
| `ENABLE_AUTO_SUMMARIZATION` | `true` | Load summarization model |

## 🤖 Automation (macOS)

```bash
./setup_automation.sh
```

This writes `~/Library/LaunchAgents/com.newsscraper.daily.plist`, which runs `news_scraper.py --schedule` at 5 AM daily (and at load), logging to `auto_run.log` / `auto_run_error.log` in the repo folder.

```bash
launchctl list | grep newsscraper                                   # status
launchctl unload ~/Library/LaunchAgents/com.newsscraper.daily.plist # stop
launchctl load   ~/Library/LaunchAgents/com.newsscraper.daily.plist # start
tail -f auto_run.log auto_run_error.log                             # logs
```

Test the scheduler logic:

```bash
./test_scheduler.sh
```

On Linux you can instead add a cron entry, e.g. `0 5 * * * cd /path/to/News-Scraper && python3 news_scraper.py`.

## 📊 News Sources

**Global:** BBC World, Reuters Top News, The Guardian World, NPR News, Deutsche Welle World, Washington Post World
**Asia:** Channel News Asia, Straits Times World, South China Morning Post, Times of India, The Hindu International
**Other:** Al Jazeera, France24 English, Newsweek, CNN Space

## 📁 Output Structure

```
News/
├── 30 08 2025.md             # Daily note (DD MM YYYY)
├── dashboard-30 08 2025.md   # Daily dashboard
├── stories/                  # Individual story notes
├── entities/                 # Entity profiles
├── topics/                   # Topic notes + Topics MOC
├── timelines/                # Event timelines
└── *.json                    # Tracker state (events, source reliability, duplicates, user profile, …)
```

## 🛠️ Troubleshooting

- **`spaCy model not found`** – `python -m spacy download en_core_web_sm`
- **Note not created** – A daily note for that date already exists; delete it to re-run
- **Missed days not catching up** – Inspect `scheduler_state.json`
- **Check connectivity detection:**
  ```bash
  python -c "from news_scraper import SmartScheduler, NewsScraper, NewsConfig; s = SmartScheduler(NewsScraper(NewsConfig())); print('Internet:', s.check_internet_connection())"
  ```

## 🙏 Acknowledgments

- [newspaper3k](https://github.com/codelucas/newspaper) for article extraction
- [spaCy](https://spacy.io/) for NLP
- [Hugging Face Transformers](https://huggingface.co/transformers/) for sentiment and summarization
- [feedparser](https://github.com/kurtmckee/feedparser) for RSS
- Designed for [Obsidian](https://obsidian.md/)

Please respect the terms of service of the news sources and APIs you use.

## License

MIT. See [LICENSE](LICENSE).
