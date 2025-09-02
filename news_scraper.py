#!/usr/bin/env python3
"""
Daily News Scraper for Obsidian
Fetches world news, creates daily notes and story notes with entity linking
"""

# Standard library imports
import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict, Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional, Any
from concurrent.futures import ThreadPoolExecutor
import socket
import subprocess
import platform
from urllib.request import urlopen
from urllib.error import URLError

# Third-party imports
import feedparser
import newspaper
import requests
import spacy
import warnings
import yaml
from slugify import slugify
from textstat import flesch_reading_ease

# Suppress specific transformers warnings
warnings.filterwarnings("ignore", message=".*return_all_scores.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*clone.*detach.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*torch.tensor.*", category=UserWarning)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('news_scraper.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Optional AI imports
try:
    from transformers import pipeline
    import torch
    HAS_TRANSFORMERS = True
    HAS_TORCH = True
    logger.info("✅ Transformers imported successfully")
except ImportError as e:
    HAS_TRANSFORMERS = False
    HAS_TORCH = False
    logger.warning(f"⚠️ Transformers not available: {e}")


@dataclass
class SchedulerState:
    """Tracks the state of automated runs"""
    last_run_date: Optional[datetime] = None
    missed_days: Optional[List[datetime]] = None
    is_running: bool = False
    
    def __post_init__(self):
        if self.missed_days is None:
            self.missed_days = []


class SmartScheduler:
    """Smart scheduler that handles automated runs with internet connectivity checking"""
    
    def __init__(self, scraper_instance, state_file: str = "scheduler_state.json"):
        self.scraper = scraper_instance
        self.state_file = Path(state_file)
        self.state = self._load_state()
        self.check_interval = 300  # Check every 5 minutes when waiting for internet
        
    def _load_state(self) -> SchedulerState:
        """Load scheduler state from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    return SchedulerState(
                        last_run_date=datetime.fromisoformat(data.get('last_run_date')) if data.get('last_run_date') else None,
                        missed_days=[datetime.fromisoformat(d) for d in data.get('missed_days', [])],
                        is_running=data.get('is_running', False)
                    )
            except Exception as e:
                logger.warning(f"Error loading scheduler state: {e}")
        
        return SchedulerState()
    
    def _save_state(self):
        """Save scheduler state to file"""
        data = {
            'last_run_date': self.state.last_run_date.isoformat() if self.state.last_run_date else None,
            'missed_days': [d.isoformat() for d in (self.state.missed_days or [])],
            'is_running': self.state.is_running
        }
        
        try:
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving scheduler state: {e}")
    
    def check_internet_connection(self) -> bool:
        """Check if internet connection is available"""
        try:
            # Try to connect to a reliable host
            urlopen('http://www.google.com', timeout=5)
            return True
        except URLError:
            pass
        
        # Fallback: try DNS resolution
        try:
            socket.gethostbyname('www.google.com')
            return True
        except socket.gaierror:
            pass
        
        return False
    
    def get_next_run_time(self) -> datetime:
        """Get the next scheduled run time (5 AM today or tomorrow)"""
        now = datetime.now()
        target_time = now.replace(hour=5, minute=0, second=0, microsecond=0)
        
        # If it's already past 5 AM today, schedule for tomorrow
        if now >= target_time:
            target_time = target_time + timedelta(days=1)
        
        return target_time
    
    def should_run_today(self) -> bool:
        """Check if we should run today (5 AM or catching up missed days)"""
        now = datetime.now()
        today = now.date()
        
        # Check if it's 5 AM
        if now.hour == 5 and now.minute < 30:  # Allow 30-minute window
            return True
        
        # Check if we have missed days to catch up
        return len(self.state.missed_days or []) > 0
    
    def add_missed_day(self, date: datetime):
        """Add a day to the missed days list"""
        if self.state.missed_days is None:
            self.state.missed_days = []
        
        date_only = date.date()
        if date_only not in [d.date() for d in self.state.missed_days]:
            self.state.missed_days.append(date)
            self.state.missed_days.sort()
            self._save_state()
            logger.info(f"Added missed day: {date_only}")
    
    def remove_missed_day(self, date: datetime):
        """Remove a day from the missed days list"""
        if self.state.missed_days is None:
            return
        
        date_only = date.date()
        self.state.missed_days = [d for d in self.state.missed_days if d.date() != date_only]
        self._save_state()
    
    def get_days_to_run(self) -> List[datetime]:
        """Get list of days that need to be run"""
        days_to_run = []
        now = datetime.now()
        
        # Add today's run if it's time
        if now.hour == 5 and now.minute < 30:
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if not self.state.last_run_date or self.state.last_run_date.date() != today.date():
                days_to_run.append(today)
        
        # Add missed days
        if self.state.missed_days:
            days_to_run.extend(self.state.missed_days)
        
        return sorted(days_to_run)
    
    def run_scheduled_scrape(self) -> bool:
        """Run the scheduled scrape for appropriate days"""
        if not self.check_internet_connection():
            logger.info("No internet connection, skipping scheduled run")
            return False
        
        days_to_run = self.get_days_to_run()
        
        if not days_to_run:
            logger.info("No days to run today")
            return True
        
        success = True
        
        for run_date in days_to_run:
            logger.info(f"Running scheduled scrape for {run_date.strftime('%d %m %Y')}")
            
            try:
                # Run the scrape
                scrape_success = self.scraper.run_daily_scrape(run_date)
                
                if scrape_success:
                    # Update state
                    self.state.last_run_date = datetime.now()
                    self.remove_missed_day(run_date)
                    logger.info(f"Successfully completed scrape for {run_date.strftime('%d %m %Y')}")
                else:
                    logger.warning(f"Scrape skipped for {run_date.strftime('%d %m %Y')} (already exists)")
                    self.remove_missed_day(run_date)
                    
            except Exception as e:
                logger.error(f"Error running scrape for {run_date.strftime('%d %m %Y')}: {e}")
                success = False
        
        self._save_state()
        return success
    
    def start_monitoring(self):
        """Start monitoring for scheduled runs"""
        logger.info("Starting smart scheduler monitoring...")
        
        while True:
            try:
                if self.should_run_today():
                    if self.check_internet_connection():
                        logger.info("Internet available, running scheduled scrape")
                        self.run_scheduled_scrape()
                    else:
                        logger.info("No internet connection, will retry later")
                
                # Check for missed days when internet is restored
                if self.check_internet_connection() and self.state.missed_days:
                    logger.info(f"Internet restored, processing {len(self.state.missed_days)} missed days")
                    self.run_scheduled_scrape()
                
                # Sleep until next check
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("Scheduler monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in scheduler monitoring: {e}")
                time.sleep(self.check_interval)
    
    def schedule_daily_runs(self):
        """Schedule daily runs at 5 AM with catch-up for missed days"""
        logger.info("Setting up daily schedule at 5 AM...")
        
        while True:
            try:
                now = datetime.now()
                next_run = self.get_next_run_time()
                wait_seconds = (next_run - now).total_seconds()
                
                if wait_seconds > 0:
                    logger.info(f"Next run scheduled for {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                    time.sleep(min(wait_seconds, self.check_interval))
                else:
                    # It's time to run
                    if self.check_internet_connection():
                        logger.info("Running scheduled daily scrape")
                        self.run_scheduled_scrape()
                    else:
                        # No internet, add to missed days and wait
                        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
                        self.add_missed_day(today)
                        logger.info("No internet connection, added to missed days")
                        
                        # Wait for internet
                        while not self.check_internet_connection():
                            logger.info("Waiting for internet connection...")
                            time.sleep(self.check_interval)
                        
                        logger.info("Internet connection restored, running catch-up")
                        self.run_scheduled_scrape()
                    
                    # Wait until tomorrow
                    time.sleep(24 * 60 * 60)  # 24 hours
                    
            except KeyboardInterrupt:
                logger.info("Daily scheduling stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in daily scheduling: {e}")
                time.sleep(self.check_interval)


@dataclass
class OngoingEvent:
    """Represents an ongoing news event"""
    name: str
    keywords: Set[str]
    entities: Set[str]
    start_date: datetime
    last_updated: datetime
    total_articles: int = 0
    importance_score: float = 0.0


class NewsConfig:
    """Configuration for the news scraper with validation and environment variable support"""
    
    # Class constants for thresholds and limits
    MAX_TITLE_LENGTH = 80
    MIN_ENTITY_LENGTH = 2
    EVENT_SCORE_THRESHOLD = 1.0
    AI_KEYWORD_SCORE_BOOST = 2.0
    ENTITY_SCORE_WEIGHT = 2.0
    MAX_RELATED_STORIES = 5
    SUMMARIZATION_MAX_CHARS = 1024
    
    # Cross-day duplicate detection settings
    DUPLICATE_DETECTION_DAYS = 7
    TITLE_SIMILARITY_THRESHOLD = 0.75
    ENTITY_OVERLAP_THRESHOLD = 0.5
    ENABLE_ADVANCED_DUPLICATE_DETECTION = True
    
    def __init__(self):
        """Initialize configuration with validation"""
        self._load_configuration()
        self._validate_configuration()
    
    def _load_configuration(self):
        """Load configuration from environment variables with defaults"""
        # Obsidian vault path - configurable via environment variable
        default_vault_path = "/Users/adaikkappankrishnan/Library/Mobile Documents/iCloud~md~obsidian/Documents/News"
        vault_path_str = os.getenv('OBSIDIAN_VAULT_PATH', default_vault_path)
        self.vault_path = Path(vault_path_str)
        
        # Create derived paths
        self.output_path = self.vault_path
        self.stories_path = self.vault_path / "stories"
        self.entities_path = self.vault_path / "entities"
        self.topics_path = self.vault_path / "topics"
        self.timelines_path = self.vault_path / "timelines"
        
        # NewsAPI configuration - configurable via environment variables
        self.newsapi_key = os.getenv('NEWSAPI_KEY', "2df1a771b56b4884a01a00ffcd1ab136")
        self.newsapi_url = os.getenv('NEWSAPI_URL', "https://newsapi.org/v2/top-headlines")
        
        # Regional quotas - configurable via environment variable
        regional_quotas_str = os.getenv('REGIONAL_QUOTAS', 'Africa:3,Middle East:4,Asia:8,Europe:8,US:7')
        self.regional_quotas = self._parse_regional_quotas(regional_quotas_str)
        
        # AI/ML features - configurable via environment variables
        self.enable_full_text_extraction = self._str_to_bool(os.getenv('ENABLE_FULL_TEXT_EXTRACTION', 'true'))
        self.enable_sentiment_analysis = self._str_to_bool(os.getenv('ENABLE_SENTIMENT_ANALYSIS', 'true'))
        self.enable_topic_modeling = self._str_to_bool(os.getenv('ENABLE_TOPIC_MODELING', 'true'))
        self.enable_auto_summarization = self._str_to_bool(os.getenv('ENABLE_AUTO_SUMMARIZATION', 'true'))
        
        # Maximum articles per day - configurable
        self.max_articles_per_day = int(os.getenv('MAX_ARTICLES_PER_DAY', '30'))
        
        # Readability threshold - configurable
        self.readability_threshold = float(os.getenv('READABILITY_THRESHOLD', '30'))
        
        # Entity types to extract
        self.entity_types = {'PERSON', 'ORG', 'GPE', 'EVENT', 'WORK_OF_ART'}
        
        # Minimum entity overlap for linking
        self.min_entity_overlap = 1
        
        # Content analysis settings
        self.tracked_topics = {
            "ukraine", "climate", "election", "economy", "health", 
            "china", "russia", "israel", "palestine", "crypto", "space", "technology"
        }
        
        # RSS feeds - can be overridden via environment variable
        default_rss_feeds = [
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://feeds.reuters.com/reuters/topNews",
            "https://feeds.theguardian.com/theguardian/world/rss",
            "https://feeds.npr.org/1001/rss.xml",
            "https://rss.dw.com/rdf/rss-en-world",
            "https://feeds.washingtonpost.com/rss/world",
            "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml",
            "https://www.straitstimes.com/news/world/rss.xml",
            "https://www.scmp.com/rss/4/feed",
            "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
            "https://www.thehindu.com/news/international/feeder/default.rss",
            "https://feeds.a24media.com/aljazeera/en/news/rss.xml",
            "https://www.france24.com/en/rss",
            "https://feeds.feedburner.com/newsweek",
            "https://rss.cnn.com/rss/edition_space.rss",
        ]
        
        rss_feeds_str = os.getenv('RSS_FEEDS')
        if rss_feeds_str:
            self.rss_feeds = [feed.strip() for feed in rss_feeds_str.split(',') if feed.strip()]
        else:
            self.rss_feeds = default_rss_feeds
        
        # Source to region mapping
        self.source_region_map = {
            "cnn": "US", "nbc": "US", "cbs": "US", "abc": "US", "fox": "US", 
            "washingtonpost": "US", "nytimes": "US", "npr": "US", "usatoday": "US",
            "bbc": "Europe", "reuters": "Europe", "theguardian": "Europe", 
            "dw": "Europe", "euronews": "Europe", "france24": "Europe",
            "straitstimes": "Asia", "scmp": "Asia", "japantimes": "Asia", 
            "timesofindia": "Asia", "chinadaily": "Asia", "koreatimes": "Asia",
            "aljazeera": "Middle East", "arabnews": "Middle East", "haaretz": "Middle East",
            "allafrica": "Africa", "dailymaverick": "Africa", "mg": "Africa"
        }
    
    def _parse_regional_quotas(self, quotas_str: str) -> Dict[str, int]:
        """Parse regional quotas from environment variable string"""
        quotas = {}
        try:
            for pair in quotas_str.split(','):
                if ':' in pair:
                    region, quota = pair.split(':', 1)
                    quotas[region.strip()] = int(quota.strip())
        except (ValueError, AttributeError):
            print(f"Warning: Invalid REGIONAL_QUOTAS format: {quotas_str}, using defaults")
            return {
                "Africa": 3, "Middle East": 4, "Asia": 8, "Europe": 8, "US": 7
            }
        return quotas
    
    def _str_to_bool(self, value: str) -> bool:
        """Convert string to boolean"""
        if not value:
            return False
        return value.lower() in ('true', '1', 'yes', 'on')
    
    def _validate_configuration(self):
        """Validate critical configuration settings"""
        errors = []
        
        # Validate vault path
        if not self.vault_path.exists():
            try:
                self.vault_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created vault directory: {self.vault_path}")
            except Exception as e:
                errors.append(f"Cannot create vault directory: {e}")
        
        # Validate NewsAPI key
        if not self.newsapi_key or self.newsapi_key == "YOUR_NEWSAPI_KEY_HERE":
            errors.append("NewsAPI key not configured. Set NEWSAPI_KEY environment variable.")
        
        # Validate RSS feeds
        if not self.rss_feeds:
            errors.append("No RSS feeds configured")
        
        # Validate regional quotas
        if not self.regional_quotas:
            errors.append("No regional quotas configured")
        
        # Validate numeric settings
        if self.max_articles_per_day <= 0:
            errors.append("max_articles_per_day must be positive")
        
        if self.readability_threshold < 0 or self.readability_threshold > 100:
            errors.append("readability_threshold must be between 0 and 100")
        
        if errors:
            error_msg = "Configuration validation errors:\n" + "\n".join(f"  - {error}" for error in errors)
            logger.error(error_msg)
            if any("NewsAPI key" in error for error in errors):
                logger.warning("Note: NewsAPI functionality will be disabled until key is configured")
            else:
                raise ValueError(error_msg)
    
    def get_summary(self) -> str:
        """Get configuration summary for logging"""
        return f"""
Configuration Summary:
- Vault Path: {self.vault_path}
- NewsAPI Key: {'Configured' if self.newsapi_key != 'YOUR_NEWSAPI_KEY_HERE' else 'Not configured'}
- RSS Feeds: {len(self.rss_feeds)} sources
- Regional Quotas: {self.regional_quotas}
- AI Features: Sentiment={self.enable_sentiment_analysis}, Summarization={self.enable_auto_summarization}
- Max Articles/Day: {self.max_articles_per_day}
"""


class EventTracker:
    """Tracks ongoing events and creates timeline notes"""
    
    def __init__(self, config):
        self.config = config
        self.events_file = config.vault_path / "events.json"
        self.ongoing_events: Dict[str, OngoingEvent] = {}
        self.load_events()
        
        # Predefined major events to track
        self.major_events = {
            "ukraine-war": OngoingEvent(
                name="Ukraine War",
                keywords={"ukraine", "russia", "zelensky", "putin", "kyiv", "moscow", "war", "invasion"},
                entities={"Ukraine", "Russia", "Vladimir Putin", "Volodymyr Zelensky"},
                start_date=datetime(2022, 2, 24),
                last_updated=datetime.now()
            ),
            "america": OngoingEvent(
                name="America",
                keywords={"america", "united states", "us", "biden", "trump", "congress", "senate", "house", "washington"},
                entities={"Joe Biden", "Donald Trump", "United States", "Congress"},
                start_date=datetime(2023, 1, 1),
                last_updated=datetime.now()
            ),
            "middle-east": OngoingEvent(
                name="Middle East Conflict",
                keywords={"israel", "palestine", "gaza", "hamas", "west bank", "middle east", "netanyahu", "ceasefire"},
                entities={"Israel", "Palestine", "Gaza", "Hamas", "Benjamin Netanyahu"},
                start_date=datetime(2023, 10, 7),
                last_updated=datetime.now()
            ),
            "climate-crisis": OngoingEvent(
                name="Climate Crisis",
                keywords={"climate", "global warming", "emissions", "renewable", "carbon", "cop"},
                entities={"UN", "Paris Agreement"},
                start_date=datetime(2020, 1, 1),
                last_updated=datetime.now()
            )
        }
        
        # Merge predefined events with loaded events
        for event_id, event in self.major_events.items():
            if event_id not in self.ongoing_events:
                self.ongoing_events[event_id] = event
    
    def load_events(self):
        """Load ongoing events from JSON file"""
        if self.events_file.exists():
            try:
                with open(self.events_file, 'r') as f:
                    data = json.load(f)
                    for event_id, event_data in data.items():
                        self.ongoing_events[event_id] = OngoingEvent(
                            name=event_data['name'],
                            keywords=set(event_data['keywords']),
                            entities=set(event_data['entities']),
                            start_date=datetime.fromisoformat(event_data['start_date']),
                            last_updated=datetime.fromisoformat(event_data['last_updated']),
                            total_articles=event_data.get('total_articles', 0),
                            importance_score=event_data.get('importance_score', 0.0)
                        )
            except Exception as e:
                print(f"Error loading events: {e}")
    
    def save_events(self):
        """Save ongoing events to JSON file"""
        try:
            data = {}
            for event_id, event in self.ongoing_events.items():
                data[event_id] = {
                    'name': event.name,
                    'keywords': list(event.keywords),
                    'entities': list(event.entities),
                    'start_date': event.start_date.isoformat(),
                    'last_updated': event.last_updated.isoformat(),
                    'total_articles': event.total_articles,
                    'importance_score': event.importance_score
                }
            
            with open(self.events_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving events: {e}")
    
    def detect_events(self, articles: List['NewsArticle']) -> Dict[str, List['NewsArticle']]:
        """Detect which articles belong to ongoing events"""
        event_articles = defaultdict(list)
        
        for article in articles:
            # Cache article text processing outside the event loop for efficiency
            article_text = f"{article.title} {article.description} {article.content}".lower()
            article_entities = {entity.lower() for entity in article.entities}
            
            for event_id, event in self.ongoing_events.items():
                score = 0.0
                
                # Check keywords with better matching
                for keyword in event.keywords:
                    keyword_lower = keyword.lower()
                    if keyword_lower in article_text:
                        # Special handling for "AI" as standalone word or in compounds
                        if keyword_lower == "ai" and ("ai " in article_text or " ai" in article_text or "ai-" in article_text or "-ai" in article_text):
                            score += NewsConfig.AI_KEYWORD_SCORE_BOOST  # Higher score for AI keyword
                        elif keyword_lower in article_text:
                            score += 1.0
                
                # Check entities
                for entity in event.entities:
                    if entity.lower() in article_entities:
                        score += NewsConfig.ENTITY_SCORE_WEIGHT  # Entities have higher weight
                
                # If score is above threshold, associate with event
                if score >= NewsConfig.EVENT_SCORE_THRESHOLD:
                    event_articles[event_id].append(article)
                    event.total_articles += 1
                    event.last_updated = datetime.now()
                    event.importance_score = max(event.importance_score, score)
        
        self.save_events()
        return event_articles


class BiasAnalyzer:
    """Analyzes bias and perspective in news articles"""
    
    def __init__(self):
        self.bias_indicators = {
            'emotional_language': [
                'shocking', 'devastating', 'outrageous', 'incredible', 'unbelievable',
                'amazing', 'stunning', 'bizarre', 'ridiculous', 'absurd'
            ],
            'loaded_words': [
                'scandal', 'crisis', 'disaster', 'triumph', 'victory', 'defeat',
                'controversial', 'disputed', 'alleged', 'claimed'
            ],
            'opinion_markers': [
                'obviously', 'clearly', 'undoubtedly', 'certainly', 'definitely',
                'arguably', 'supposedly', 'apparently', 'presumably'
            ],
            'extreme_adjectives': [
                'unprecedented', 'historic', 'massive', 'huge', 'tiny', 'enormous',
                'catastrophic', 'revolutionary', 'groundbreaking'
            ]
        }
        
        self.perspective_patterns = {
            'government': ['officials say', 'according to authorities', 'government sources'],
            'opposition': ['critics argue', 'opponents claim', 'skeptics say'],
            'expert': ['experts believe', 'analysts suggest', 'researchers found'],
            'public': ['public opinion', 'citizens report', 'people say'],
            'corporate': ['company statement', 'corporate response', 'business leaders']
        }
        
    def analyze_bias(self, text: str) -> Dict[str, Any]:
        """Analyze potential bias indicators in text"""
        text_lower = text.lower()
        
        bias_scores = {}
        total_words = len(text.split())
        
        for category, indicators in self.bias_indicators.items():
            count = sum(1 for indicator in indicators if indicator in text_lower)
            bias_scores[category] = {
                'count': count,
                'density': count / total_words if total_words > 0 else 0
            }
        
        # Calculate overall bias score (0-1)
        total_bias_words = sum(score['count'] for score in bias_scores.values())
        overall_bias = min(total_bias_words / max(total_words * 0.1, 1), 1.0)
        
        return {
            'overall_bias_score': overall_bias,
            'bias_breakdown': bias_scores,
            'bias_level': self._categorize_bias(overall_bias)
        }
    
    def analyze_perspectives(self, text: str) -> Dict[str, int]:
        """Identify different perspectives represented in the text"""
        text_lower = text.lower()
        perspectives = {}
        
        for perspective, patterns in self.perspective_patterns.items():
            count = sum(1 for pattern in patterns if pattern in text_lower)
            if count > 0:
                perspectives[perspective] = count
        
        return perspectives
    
    def _categorize_bias(self, score: float) -> str:
        """Categorize bias level based on score"""
        if score < 0.02:
            return "Low"
        elif score < 0.05:
            return "Moderate"
        elif score < 0.1:
            return "High"
        else:
            return "Very High"
    
    def compare_source_bias(self, articles: List['NewsArticle']) -> Dict[str, Dict[str, float]]:
        """Compare bias levels across different sources"""
        source_bias = {}
        
        for article in articles:
            if hasattr(article, 'full_text') and article.full_text:
                text_to_analyze = f"{article.title} {article.summary} {article.full_text[:1000]}"
            else:
                text_to_analyze = f"{article.title} {article.summary}"
            
            bias_analysis = self.analyze_bias(text_to_analyze)
            
            if article.source not in source_bias:
                source_bias[article.source] = []
            
            source_bias[article.source].append(bias_analysis['overall_bias_score'])
        
        # Calculate average bias per source
        source_averages = {}
        for source, scores in source_bias.items():
            if scores:
                avg_bias = sum(scores) / len(scores)
                source_averages[source] = {
                    'average_bias': avg_bias,
                    'article_count': len(scores),
                    'bias_level': self._categorize_bias(avg_bias)
                }
        
        return source_averages


class GeographicEventCluster:
    """Manages geographic event clustering and detection"""
    
    def __init__(self):
        self.location_patterns = {
            # Countries and major regions
            'singapore': ['singapore', 'sg'],
            'malaysia': ['malaysia', 'kuala lumpur', 'kl', 'selangor', 'johor'],
            'indonesia': ['indonesia', 'jakarta', 'bali', 'sumatra', 'java'],
            'thailand': ['thailand', 'bangkok', 'phuket'],
            'philippines': ['philippines', 'manila', 'cebu'],
            'vietnam': ['vietnam', 'ho chi minh', 'hanoi'],
            'china': ['china', 'beijing', 'shanghai', 'guangzhou', 'shenzhen'],
            'japan': ['japan', 'tokyo', 'osaka', 'kyoto'],
            'south korea': ['south korea', 'seoul', 'busan'],
            'india': ['india', 'mumbai', 'delhi', 'bangalore', 'chennai'],
            'usa': ['united states', 'usa', 'america', 'new york', 'california', 'washington dc'],
            'uk': ['united kingdom', 'uk', 'britain', 'london', 'england'],
            'europe': ['europe', 'european union', 'eu'],
            'middle east': ['middle east', 'saudi arabia', 'uae', 'dubai', 'israel', 'iran'],
            'africa': ['africa', 'south africa', 'nigeria', 'kenya', 'egypt'],
            'ukraine': ['ukraine', 'kyiv', 'kiev', 'lviv'],
            'russia': ['russia', 'moscow', 'st petersburg'],
        }
        
        self.event_keywords = {
            'conflict': ['war', 'conflict', 'battle', 'fighting', 'military', 'army', 'invasion', 'attack'],
            'politics': ['election', 'government', 'parliament', 'president', 'minister', 'policy', 'law'],
            'economics': ['economy', 'trade', 'market', 'gdp', 'inflation', 'currency', 'investment'],
            'natural_disaster': ['earthquake', 'tsunami', 'flood', 'hurricane', 'typhoon', 'volcano', 'wildfire'],
            'health': ['pandemic', 'outbreak', 'virus', 'vaccine', 'health', 'hospital', 'disease'],
            'technology': ['tech', 'ai', 'artificial intelligence', 'blockchain', 'cryptocurrency', 'innovation'],
            'climate': ['climate', 'environment', 'carbon', 'renewable', 'sustainability', 'global warming'],
            'social': ['protest', 'demonstration', 'civil rights', 'social media', 'community']
        }
        
        self.event_clusters = {}
        
    def extract_locations(self, text: str) -> List[str]:
        """Extract locations mentioned in the text"""
        text_lower = text.lower()
        found_locations = []
        
        for location, patterns in self.location_patterns.items():
            for pattern in patterns:
                if pattern in text_lower:
                    found_locations.append(location)
                    break
        
        return found_locations
    
    def extract_event_types(self, text: str) -> List[str]:
        """Extract event types from the text"""
        text_lower = text.lower()
        found_events = []
        
        for event_type, keywords in self.event_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    found_events.append(event_type)
                    break
        
        return found_events
    
    def cluster_articles_by_location(self, articles: List['NewsArticle']) -> Dict[str, List['NewsArticle']]:
        """Group articles by geographic locations"""
        location_clusters = {}
        
        for article in articles:
            # Extract locations from title and summary
            text_to_analyze = f"{article.title} {article.summary}"
            locations = self.extract_locations(text_to_analyze)
            
            if not locations:
                locations = ['global']  # Default for articles without clear location
            
            for location in locations:
                if location not in location_clusters:
                    location_clusters[location] = []
                location_clusters[location].append(article)
        
        return location_clusters
    
    def identify_regional_events(self, articles: List['NewsArticle']) -> Dict[str, Dict[str, List['NewsArticle']]]:
        """Identify major events by region and type"""
        regional_events = {}
        
        # First cluster by location
        location_clusters = self.cluster_articles_by_location(articles)
        
        # Then analyze event types within each location
        for location, loc_articles in location_clusters.items():
            if len(loc_articles) < 2:  # Skip locations with only one article
                continue
                
            regional_events[location] = {}
            
            for article in loc_articles:
                text_to_analyze = f"{article.title} {article.summary}"
                event_types = self.extract_event_types(text_to_analyze)
                
                if not event_types:
                    event_types = ['general']
                
                for event_type in event_types:
                    if event_type not in regional_events[location]:
                        regional_events[location][event_type] = []
                    regional_events[location][event_type].append(article)
        
        return regional_events


class SourceReliabilityTracker:
    """Tracks and scores source reliability based on various metrics"""
    
    def __init__(self, config):
        self.config = config
        self.reliability_file = config.vault_path / "source_reliability.json"
        self.source_scores = self.load_source_scores()
        
        # Base reliability scores for known sources
        self.base_scores = {
            # Tier 1: Premium international sources
            "reuters": 0.95, "bbc": 0.95, "ap": 0.94, "npr": 0.92,
            # Tier 2: Major national sources
            "cnn": 0.85, "washingtonpost": 0.88, "nytimes": 0.87, "theguardian": 0.86,
            # Tier 3: Regional/specialized sources
            "dw": 0.83, "straitstimes": 0.81, "scmp": 0.79, "timesofindia": 0.77,
            # Default for unknown sources
            "unknown": 0.70
        }
    
    def load_source_scores(self) -> Dict[str, Dict]:
        """Load source reliability scores from JSON"""
        if self.reliability_file.exists():
            try:
                with open(self.reliability_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def save_source_scores(self):
        """Save source reliability scores to JSON"""
        try:
            with open(self.reliability_file, 'w') as f:
                json.dump(self.source_scores, f, indent=2)
        except Exception as e:
            print(f"Error saving source scores: {e}")
    
    def get_source_reliability_score(self, source: str) -> float:
        """Get reliability score for a source"""
        source_lower = source.lower()
        
        # Check if we have historical data
        if source_lower in self.source_scores:
            data = self.source_scores[source_lower]
            return data.get('calculated_score', self.base_scores.get(source_lower, 0.70))
        
        # Use base score
        for known_source, score in self.base_scores.items():
            if known_source in source_lower:
                return score
        
        return self.base_scores['unknown']
    
    def update_source_metrics(self, article: 'NewsArticle'):
        """Update source metrics based on article quality"""
        source_lower = article.source.lower()
        
        if source_lower not in self.source_scores:
            self.source_scores[source_lower] = {
                'total_articles': 0,
                'successful_extractions': 0,
                'avg_readability': 0.0,
                'unique_stories': 0,
                'calculated_score': self.get_source_reliability_score(article.source)
            }
        
        data = self.source_scores[source_lower]
        data['total_articles'] += 1
        
        # Track successful full text extraction
        if article.full_text and len(article.full_text) > 200:
            data['successful_extractions'] += 1
        
        # Update average readability
        if article.readability_score > 0:
            current_avg = data['avg_readability']
            total = data['total_articles']
            data['avg_readability'] = ((current_avg * (total - 1)) + article.readability_score) / total
        
        # Calculate dynamic score
        extraction_rate = data['successful_extractions'] / data['total_articles']
        readability_bonus = min(data['avg_readability'] / 100, 0.1)  # Up to 10% bonus
        
        base_score = self.get_source_reliability_score(article.source)
        data['calculated_score'] = min(0.99, base_score + readability_bonus - (0.2 * (1 - extraction_rate)))
        
        self.save_source_scores()
    
    def get_top_sources(self, limit: int = 10) -> List[Tuple[str, float]]:
        """Get top sources by reliability score"""
        scored_sources = []
        for source, data in self.source_scores.items():
            if data['total_articles'] >= 5:  # Only sources with sufficient data
                scored_sources.append((source, data['calculated_score']))
        
        return sorted(scored_sources, key=lambda x: x[1], reverse=True)[:limit]


class StoryEvolutionTracker:
    """Tracks how stories evolve over multiple days vs genuine duplicates"""
    
    def __init__(self, config):
        self.config = config
        self.story_threads_file = config.vault_path / "story_threads.json"
        self.story_threads = self._load_story_threads()
        
        # Evolution indicators vs duplicate indicators
        self.evolution_keywords = {
            'development': ['update', 'breaking', 'developing', 'latest', 'new details', 'continues'],
            'escalation': ['escalates', 'worsens', 'intensifies', 'spreads', 'grows'],
            'resolution': ['resolves', 'ends', 'concludes', 'settles', 'finalizes'],
            'reaction': ['responds', 'reacts', 'criticizes', 'supports', 'condemns'],
            'consequences': ['result', 'aftermath', 'impact', 'effect', 'leads to']
        }
        
        self.duplicate_indicators = {
            'republication': ['reports', 'says', 'according to', 'sources say'],
            'recycling': ['recap', 'roundup', 'summary', 'review', 'look back'],
            'aggregation': ['compilation', 'collected', 'gathered', 'combined']
        }
    
    def _load_story_threads(self) -> Dict[str, Dict]:
        """Load existing story threads from disk"""
        if self.story_threads_file.exists():
            try:
                with open(self.story_threads_file, 'r') as f:
                    data = json.load(f)
                    # Convert date strings back to datetime objects
                    for thread_id, thread in data.items():
                        thread['created_date'] = datetime.fromisoformat(thread['created_date'])
                        thread['last_update'] = datetime.fromisoformat(thread['last_update'])
                        for article in thread['articles']:
                            article['published_at'] = datetime.fromisoformat(article['published_at'])
                    return data
            except Exception as e:
                print(f"⚠️ Error loading story threads: {e}")
        return {}
    
    def _save_story_threads(self):
        """Save story threads to disk"""
        try:
            # Convert datetime objects to strings for JSON serialization
            serializable_data = {}
            for thread_id, thread in self.story_threads.items():
                serializable_thread = thread.copy()
                serializable_thread['created_date'] = thread['created_date'].isoformat()
                serializable_thread['last_update'] = thread['last_update'].isoformat()
                serializable_thread['articles'] = []
                for article in thread['articles']:
                    article_data = article.copy()
                    article_data['published_at'] = article['published_at'].isoformat()
                    serializable_thread['articles'].append(article_data)
                serializable_data[thread_id] = serializable_thread
            
            with open(self.story_threads_file, 'w') as f:
                json.dump(serializable_data, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving story threads: {e}")
    
    def analyze_story_relationship(self, article: 'NewsArticle', existing_articles: List['NewsArticle']) -> Dict[str, Any]:
        """Determine if article is evolution, duplicate, or new story"""
        for existing in existing_articles:
            similarity_score = self._calculate_content_similarity(article, existing)
            
            if similarity_score > 0.6:  # High similarity threshold
                relationship_type = self._classify_relationship(article, existing)
                
                return {
                    'type': relationship_type,
                    'related_article': existing,
                    'similarity_score': similarity_score,
                    'confidence': self._calculate_confidence(article, existing, relationship_type)
                }
        
        return {'type': 'new_story', 'similarity_score': 0.0, 'confidence': 1.0}
    
    def _classify_relationship(self, article1: 'NewsArticle', article2: 'NewsArticle') -> str:
        """Classify the relationship between two similar articles"""
        text1 = f"{article1.title} {article1.description}".lower()
        text2 = f"{article2.title} {article2.description}".lower()
        
        # Check for evolution indicators
        evolution_score = 0
        for category, keywords in self.evolution_keywords.items():
            for keyword in keywords:
                if keyword in text1 and keyword not in text2:
                    evolution_score += 1
                elif keyword in text2 and keyword not in text1:
                    evolution_score += 0.5
        
        # Check for duplicate indicators  
        duplicate_score = 0
        for category, keywords in self.duplicate_indicators.items():
            for keyword in keywords:
                if keyword in text1 or keyword in text2:
                    duplicate_score += 1
        
        # Time factor (newer articles more likely to be evolution)
        time_diff = abs((article1.published_at - article2.published_at).total_seconds())
        time_factor = 1.0 if time_diff > 86400 else 0.5  # 24 hours
        
        # Entity change analysis
        entity_change_score = self._analyze_entity_changes(article1, article2)
        
        # Final classification
        total_evolution = (evolution_score * time_factor) + entity_change_score
        
        if total_evolution > duplicate_score and total_evolution > 2:
            return 'evolution'
        elif duplicate_score > total_evolution:
            return 'duplicate'
        else:
            return 'related'
    
    def _analyze_entity_changes(self, article1: 'NewsArticle', article2: 'NewsArticle') -> float:
        """Analyze changes in entities that suggest story evolution"""
        entities1 = set(article1.entities)
        entities2 = set(article2.entities)
        
        new_entities = entities2 - entities1
        common_entities = entities1.intersection(entities2)
        
        if not common_entities:
            return 0.0
        
        # New entities suggest evolution (new people involved, new locations, etc.)
        new_entity_score = len(new_entities) * 0.5
        
        # Check for entities that suggest development
        development_entities = {'investigation', 'trial', 'hearing', 'meeting', 'conference'}
        development_score = len(development_entities.intersection(new_entities)) * 1.0
        
        return new_entity_score + development_score
    
    def _calculate_content_similarity(self, article1: 'NewsArticle', article2: 'NewsArticle') -> float:
        """Calculate content similarity between articles"""
        # Use the existing Jaccard similarity from duplicate detector
        text1_words = set(re.findall(r'\w+', f"{article1.title} {article1.description}".lower()))
        text2_words = set(re.findall(r'\w+', f"{article2.title} {article2.description}".lower()))
        
        if not text1_words or not text2_words:
            return 0.0
        
        intersection = len(text1_words.intersection(text2_words))
        union = len(text1_words.union(text2_words))
        
        return intersection / union if union > 0 else 0.0
    
    def _calculate_confidence(self, article1: 'NewsArticle', article2: 'NewsArticle', relationship_type: str) -> float:
        """Calculate confidence in the relationship classification"""
        # Factors that increase confidence:
        # - Same entities
        # - Same source domain
        # - Time proximity (for evolution)
        # - Clear evolution keywords
        
        confidence = 0.5  # Base confidence
        
        # Entity overlap increases confidence
        entity_overlap = len(article1.entities.intersection(article2.entities))
        confidence += min(entity_overlap * 0.1, 0.3)
        
        # Same source increases confidence for duplicates
        if relationship_type == 'duplicate' and article1.source == article2.source:
            confidence += 0.2
        
        # Time proximity for evolution
        if relationship_type == 'evolution':
            time_diff_hours = abs((article1.published_at - article2.published_at).total_seconds()) / 3600
            if 6 <= time_diff_hours <= 72:  # 6 hours to 3 days is optimal for evolution
                confidence += 0.2
        
        return min(confidence, 1.0)
    
    def track_story_thread(self, article: 'NewsArticle', relationship: Dict[str, Any]) -> Optional[str]:
        """Add article to appropriate story thread"""
        thread_id = None
        
        if relationship['type'] == 'new_story':
            # Create new thread
            thread_id = f"story_{article.hash}_{article.published_at.strftime('%Y%m%d')}"
            self.story_threads[thread_id] = {
                'thread_id': thread_id,
                'primary_entities': list(article.entities)[:5],  # Top 5 entities
                'primary_topic': self._extract_primary_topic(article),
                'created_date': article.published_at,
                'last_update': article.published_at,
                'articles': [self._article_to_dict(article)],
                'status': 'active',
                'evolution_stage': 'initial'
            }
        else:
            # Find existing thread for related article
            thread_id = self._find_thread_for_article(relationship['related_article'])
            
            if thread_id and relationship['type'] == 'evolution':
                # Add to existing thread as evolution
                thread = self.story_threads[thread_id]
                thread['articles'].append(self._article_to_dict(article))
                thread['last_update'] = article.published_at
                thread['evolution_stage'] = self._determine_evolution_stage(thread)
            elif thread_id and relationship['type'] == 'duplicate':
                # Mark as duplicate but don't add to thread
                pass
        
        self._save_story_threads()
        return thread_id
    
    def _extract_primary_topic(self, article: 'NewsArticle') -> str:
        """Extract the primary topic/theme of the article"""
        # Use the most prominent topic or entity
        if article.topics:
            return list(article.topics)[0]
        elif article.entities:
            return list(article.entities)[0]
        else:
            # Extract from title
            title_words = re.findall(r'\w+', article.title.lower())
            # Return first meaningful word (not stop words)
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
            for word in title_words:
                if len(word) > 3 and word not in stop_words:
                    return word.title()
        return "General"
    
    def _find_thread_for_article(self, article: 'NewsArticle') -> Optional[str]:
        """Find which thread an article belongs to"""
        article_dict = self._article_to_dict(article)
        
        for thread_id, thread in self.story_threads.items():
            for thread_article in thread['articles']:
                if (thread_article['hash'] == article_dict['hash'] or
                    thread_article['url'] == article_dict['url']):
                    return thread_id
        return None
    
    def _determine_evolution_stage(self, thread: Dict) -> str:
        """Determine what stage of evolution the story is in"""
        article_count = len(thread['articles'])
        latest_article = max(thread['articles'], key=lambda x: datetime.fromisoformat(x['published_at']))
        
        # Analyze latest article for stage indicators
        latest_text = f"{latest_article['title']} {latest_article['description']}".lower()
        
        if any(word in latest_text for word in ['concluded', 'ended', 'resolved', 'settled']):
            return 'concluded'
        elif any(word in latest_text for word in ['developing', 'breaking', 'ongoing']):
            return 'developing'
        elif article_count > 5:
            return 'mature'
        elif article_count > 2:
            return 'evolving'
        else:
            return 'initial'
    
    def _article_to_dict(self, article: 'NewsArticle') -> Dict:
        """Convert article to dictionary for storage"""
        return {
            'title': article.title,
            'description': article.description,
            'url': article.url,
            'source': article.source,
            'published_at': article.published_at,
            'hash': article.hash,
            'entities': list(article.entities),
            'topics': list(article.topics),
            'sentiment': article.sentiment
        }
    
    def get_active_story_threads(self, days_back: int = 7) -> List[Dict]:
        """Get currently active story threads"""
        cutoff_date = datetime.now() - timedelta(days=days_back)
        active_threads = []
        
        for thread_id, thread in self.story_threads.items():
            if (thread['last_update'] >= cutoff_date and 
                thread['status'] == 'active' and
                len(thread['articles']) > 1):
                active_threads.append(thread)
        
        # Sort by last update (most recent first)
        active_threads.sort(key=lambda x: x['last_update'], reverse=True)
        return active_threads
    
    def get_story_thread_summary(self, thread_id: str) -> Dict[str, Any]:
        """Get a summary of a story thread's evolution"""
        if thread_id not in self.story_threads:
            return {}
        
        thread = self.story_threads[thread_id]
        articles = sorted(thread['articles'], key=lambda x: datetime.fromisoformat(x['published_at']))
        
        return {
            'thread_id': thread_id,
            'primary_topic': thread['primary_topic'],
            'article_count': len(articles),
            'date_range': {
                'start': articles[0]['published_at'],
                'end': articles[-1]['published_at']
            },
            'evolution_stage': thread['evolution_stage'],
            'key_entities': thread['primary_entities'],
            'sources_involved': list(set(article['source'] for article in articles)),
            'sentiment_trend': self._calculate_sentiment_trend(articles)
        }
    
    def _calculate_sentiment_trend(self, articles: List[Dict]) -> Dict[str, Any]:
        """Calculate how sentiment has changed over the story timeline"""
        if len(articles) < 2:
            return {'trend': 'stable', 'change': 0.0}
        
        early_sentiment = sum(article['sentiment']['compound'] for article in articles[:len(articles)//2]) / (len(articles)//2)
        late_sentiment = sum(article['sentiment']['compound'] for article in articles[len(articles)//2:]) / (len(articles) - len(articles)//2)
        
        change = late_sentiment - early_sentiment
        
        if change > 0.1:
            trend = 'improving'
        elif change < -0.1:
            trend = 'worsening'
        else:
            trend = 'stable'
        
        return {'trend': trend, 'change': change}


class CoverageGapAnalyzer:
    """Identifies important topics that aren't getting enough coverage"""
    
    def __init__(self, config):
        self.config = config
        self.coverage_data_file = config.vault_path / "coverage_analysis.json"
        self.coverage_data = self._load_coverage_data()
        
        # Define topic importance indicators
        self.importance_indicators = {
            'breaking_keywords': ['breaking', 'urgent', 'emergency', 'crisis', 'disaster'],
            'government_keywords': ['government', 'parliament', 'congress', 'senate', 'legislation'],
            'economy_keywords': ['economy', 'market', 'financial', 'inflation', 'recession'],
            'health_keywords': ['health', 'pandemic', 'disease', 'medical', 'hospital'],
            'climate_keywords': ['climate', 'environment', 'warming', 'carbon', 'emissions'],
            'social_keywords': ['protest', 'rights', 'justice', 'discrimination', 'equality']
        }
        
        # Define coverage expectations (articles per day)
        self.coverage_expectations = {
            'breaking': 2,      # Major breaking news
            'government': 3,    # Government/political news
            'economy': 2,       # Economic news
            'health': 2,        # Health-related news
            'climate': 1,       # Climate/environment news
            'social': 2,        # Social justice/rights news
            'international': 3, # International news
            'technology': 2,    # Technology news
            'science': 1        # Science news
        }
    
    def _load_coverage_data(self) -> Dict[str, Any]:
        """Load coverage analysis data"""
        if self.coverage_data_file.exists():
            try:
                with open(self.coverage_data_file, 'r') as f:
                    data = json.load(f)
                    # Convert date strings back to datetime objects
                    if 'daily_coverage' in data:
                        for date_str, coverage in data['daily_coverage'].items():
                            for topic in coverage.values():
                                if isinstance(topic, dict) and 'last_article' in topic:
                                    if isinstance(topic['last_article'], str):  # Fixed: Check if it's a string first
                                        topic['last_article'] = datetime.fromisoformat(topic['last_article'])
                    return data
            except Exception as e:
                print(f"⚠️ Error loading coverage data: {e}")
        
        return {
            'daily_coverage': {},
            'topic_trends': {},
            'gap_alerts': [],
            'last_analysis': datetime.now().isoformat()
        }
    
    def _save_coverage_data(self):
        """Save coverage analysis data"""
        try:
            # Convert datetime objects to strings for JSON serialization
            serializable_data = self.coverage_data.copy()
            if 'daily_coverage' in serializable_data:
                for date_str, coverage in serializable_data['daily_coverage'].items():
                    for topic_data in coverage.values():
                        if isinstance(topic_data, dict) and 'last_article' in topic_data:
                            if isinstance(topic_data['last_article'], datetime):
                                topic_data['last_article'] = topic_data['last_article'].isoformat()
            
            serializable_data['last_analysis'] = datetime.now().isoformat()
            
            with open(self.coverage_data_file, 'w') as f:
                json.dump(serializable_data, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving coverage data: {e}")
    
    def analyze_daily_coverage(self, articles: List['NewsArticle'], analysis_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Analyze coverage for a specific day"""
        if analysis_date is None:
            analysis_date = datetime.now()
        
        date_str = analysis_date.strftime('%Y-%m-%d')
        
        # Initialize coverage for this date
        if date_str not in self.coverage_data['daily_coverage']:
            self.coverage_data['daily_coverage'][date_str] = {}
        
        daily_coverage = self.coverage_data['daily_coverage'][date_str]
        
        # Categorize articles by topic
        topic_articles = self._categorize_articles_by_topic(articles)
        
        # Update coverage data
        for topic, topic_articles_list in topic_articles.items():
            daily_coverage[topic] = {
                'count': len(topic_articles_list),
                'articles': [self._article_summary(article) for article in topic_articles_list],
                'last_article': max(article.published_at for article in topic_articles_list) if topic_articles_list else None,
                'sources': list(set(article.source for article in topic_articles_list)),
                'average_sentiment': self._calculate_average_sentiment(topic_articles_list)
            }
        
        # Identify gaps
        gaps = self._identify_coverage_gaps(daily_coverage, analysis_date)
        
        # Update trend data
        self._update_topic_trends(topic_articles, analysis_date)
        
        self._save_coverage_data()
        
        return {
            'date': date_str,
            'coverage_summary': daily_coverage,
            'identified_gaps': gaps,
            'coverage_score': self._calculate_coverage_score(daily_coverage)
        }
    
    def _categorize_articles_by_topic(self, articles: List['NewsArticle']) -> Dict[str, List['NewsArticle']]:
        """Categorize articles by topic/theme"""
        topic_articles = {topic: [] for topic in self.coverage_expectations.keys()}
        topic_articles['other'] = []
        
        for article in articles:
            article_text = f"{article.title} {article.description}".lower()
            article_topics = article.topics if article.topics else set()
            
            assigned = False
            
            # Check importance indicators
            for topic_category, keywords in self.importance_indicators.items():
                base_topic = topic_category.replace('_keywords', '')
                if any(keyword in article_text for keyword in keywords):
                    topic_articles[base_topic].append(article)
                    assigned = True
                    break
            
            # Check article topics/entities
            if not assigned:
                for topic in article_topics:
                    topic_lower = topic.lower()
                    if 'technolog' in topic_lower or 'tech' in topic_lower:
                        topic_articles['technology'].append(article)
                        assigned = True
                        break
                    elif 'science' in topic_lower or 'research' in topic_lower:
                        topic_articles['science'].append(article)
                        assigned = True
                        break
                    elif any(geo in topic_lower for geo in ['international', 'world', 'global']):
                        topic_articles['international'].append(article)
                        assigned = True
                        break
            
            # Check for international news by source or entities
            if not assigned:
                foreign_indicators = ['bbc', 'reuters', 'international', 'china', 'russia', 'europe', 'asia']
                if (any(indicator in article.source.lower() for indicator in foreign_indicators) or
                    any(indicator in article_text for indicator in foreign_indicators)):
                    topic_articles['international'].append(article)
                    assigned = True
            
            if not assigned:
                topic_articles['other'].append(article)
        
        return topic_articles
    
    def _identify_coverage_gaps(self, daily_coverage: Dict[str, Any], analysis_date: datetime) -> List[Dict[str, Any]]:
        """Identify topics with insufficient coverage"""
        gaps = []
        
        for topic, expected_count in self.coverage_expectations.items():
            actual_count = daily_coverage.get(topic, {}).get('count', 0)
            
            if actual_count < expected_count:
                gap_severity = self._calculate_gap_severity(topic, actual_count, expected_count, analysis_date)
                
                gaps.append({
                    'topic': topic,
                    'expected_coverage': expected_count,
                    'actual_coverage': actual_count,
                    'gap_size': expected_count - actual_count,
                    'severity': gap_severity['severity'],
                    'urgency_score': gap_severity['urgency_score'],
                    'last_coverage': self._get_last_coverage_date(topic, analysis_date),
                    'suggested_sources': self._suggest_sources_for_topic(topic)
                })
        
        # Sort by urgency score (highest first)
        gaps.sort(key=lambda x: x['urgency_score'], reverse=True)
        return gaps
    
    def _calculate_gap_severity(self, topic: str, actual: int, expected: int, date: datetime) -> Dict[str, Any]:
        """Calculate the severity of a coverage gap"""
        gap_ratio = (expected - actual) / expected
        
        # Check historical coverage for this topic
        historical_avg = self._get_historical_average(topic, date)
        
        # Urgency factors
        urgency_score = gap_ratio * 10  # Base score
        
        # Topic importance multiplier
        importance_multipliers = {
            'breaking': 2.0,
            'government': 1.5,
            'health': 1.8,
            'economy': 1.6,
            'climate': 1.3,
            'social': 1.4,
            'international': 1.2,
            'technology': 1.0,
            'science': 1.0
        }
        
        urgency_score *= importance_multipliers.get(topic, 1.0)
        
        # Time since last coverage
        days_since_last = self._days_since_last_coverage(topic, date)
        if days_since_last > 2:
            urgency_score *= (1 + (days_since_last - 2) * 0.2)
        
        # Determine severity level
        if urgency_score >= 15:
            severity = 'critical'
        elif urgency_score >= 10:
            severity = 'high'
        elif urgency_score >= 5:
            severity = 'medium'
        else:
            severity = 'low'
        
        return {
            'severity': severity,
            'urgency_score': urgency_score,
            'gap_ratio': gap_ratio,
            'days_since_last': days_since_last
        }
    
    def _get_historical_average(self, topic: str, current_date: datetime, days_back: int = 7) -> float:
        """Get historical average coverage for a topic"""
        total_coverage = 0
        valid_days = 0
        
        for i in range(1, days_back + 1):
            check_date = current_date - timedelta(days=i)
            date_str = check_date.strftime('%Y-%m-%d')
            
            if date_str in self.coverage_data['daily_coverage']:
                coverage = self.coverage_data['daily_coverage'][date_str].get(topic, {}).get('count', 0)
                total_coverage += coverage
                valid_days += 1
        
        return total_coverage / valid_days if valid_days > 0 else 0
    
    def _days_since_last_coverage(self, topic: str, current_date: datetime) -> int:
        """Calculate days since last coverage of a topic"""
        for i in range(1, 30):  # Check up to 30 days back
            check_date = current_date - timedelta(days=i)
            date_str = check_date.strftime('%Y-%m-%d')
            
            if (date_str in self.coverage_data['daily_coverage'] and
                self.coverage_data['daily_coverage'][date_str].get(topic, {}).get('count', 0) > 0):
                return i
        
        return 30  # Max days
    
    def _get_last_coverage_date(self, topic: str, current_date: datetime) -> Optional[str]:
        """Get the date of last coverage for a topic"""
        for i in range(1, 30):
            check_date = current_date - timedelta(days=i)
            date_str = check_date.strftime('%Y-%m-%d')
            
            if (date_str in self.coverage_data['daily_coverage'] and
                self.coverage_data['daily_coverage'][date_str].get(topic, {}).get('count', 0) > 0):
                return date_str
        
        return None
    
    def _suggest_sources_for_topic(self, topic: str) -> List[str]:
        """Suggest sources that typically cover specific topics"""
        source_suggestions = {
            'breaking': ['Reuters', 'AP News', 'BBC News', 'CNN'],
            'government': ['Politico', 'The Hill', 'Washington Post', 'Reuters'],
            'economy': ['Financial Times', 'Wall Street Journal', 'Bloomberg', 'Reuters'],
            'health': ['Health News', 'Medical News Today', 'CDC', 'WHO'],
            'climate': ['Environmental News', 'Climate Central', 'Guardian Environment'],
            'social': ['NPR', 'The Guardian', 'BBC News', 'Associated Press'],
            'international': ['BBC World', 'Reuters World', 'Al Jazeera', 'Foreign Affairs'],
            'technology': ['TechCrunch', 'Ars Technica', 'The Verge', 'Wired'],
            'science': ['Science Daily', 'Nature News', 'Scientific American', 'BBC Science']
        }
        
        return source_suggestions.get(topic, ['Reuters', 'BBC News', 'Associated Press'])
    
    def _update_topic_trends(self, topic_articles: Dict[str, List['NewsArticle']], date: datetime):
        """Update trending analysis for topics"""
        date_str = date.strftime('%Y-%m-%d')
        
        if 'topic_trends' not in self.coverage_data:
            self.coverage_data['topic_trends'] = {}
        
        for topic, articles in topic_articles.items():
            if topic not in self.coverage_data['topic_trends']:
                self.coverage_data['topic_trends'][topic] = {'daily_counts': {}, 'trend_direction': 'stable'}
            
            self.coverage_data['topic_trends'][topic]['daily_counts'][date_str] = len(articles)
            
            # Calculate trend direction (last 7 days)
            recent_counts = []
            for i in range(7):
                check_date = date - timedelta(days=i)
                check_date_str = check_date.strftime('%Y-%m-%d')
                count = self.coverage_data['topic_trends'][topic]['daily_counts'].get(check_date_str, 0)
                recent_counts.append(count)
            
            if len(recent_counts) >= 3:
                early_avg = sum(recent_counts[-3:]) / 3
                late_avg = sum(recent_counts[:3]) / 3
                
                if late_avg > early_avg * 1.2:
                    self.coverage_data['topic_trends'][topic]['trend_direction'] = 'increasing'
                elif late_avg < early_avg * 0.8:
                    self.coverage_data['topic_trends'][topic]['trend_direction'] = 'decreasing'
                else:
                    self.coverage_data['topic_trends'][topic]['trend_direction'] = 'stable'
    
    def _calculate_coverage_score(self, daily_coverage: Dict[str, Any]) -> float:
        """Calculate overall coverage quality score (0-100)"""
        total_expected = sum(self.coverage_expectations.values())
        total_actual = sum(coverage.get('count', 0) for coverage in daily_coverage.values() if coverage)
        
        # Base score from coverage ratio
        coverage_ratio = min(total_actual / total_expected, 1.0) if total_expected > 0 else 0
        base_score = coverage_ratio * 60  # Max 60 points for meeting expectations
        
        # Bonus points for diversity (different sources)
        source_diversity = 0
        total_sources = set()
        for coverage in daily_coverage.values():
            if coverage and 'sources' in coverage:
                total_sources.update(coverage['sources'])
        
        source_diversity = min(len(total_sources) / 10, 1.0) * 20  # Max 20 points for source diversity
        
        # Bonus points for balanced sentiment
        sentiment_balance = 0
        sentiments = []
        for coverage in daily_coverage.values():
            if coverage and 'average_sentiment' in coverage:
                sentiments.append(coverage['average_sentiment'])
        
        if sentiments:
            sentiment_std = (sum((s - sum(sentiments)/len(sentiments))**2 for s in sentiments) / len(sentiments)) ** 0.5 if len(sentiments) > 1 else 0
            sentiment_balance = max(0, 20 - sentiment_std * 20)  # Max 20 points for balanced sentiment
        
        total_score = base_score + source_diversity + sentiment_balance
        return min(total_score, 100)
    
    def _article_summary(self, article: 'NewsArticle') -> Dict[str, Any]:
        """Create a summary of an article for storage"""
        return {
            'title': article.title,
            'source': article.source,
            'published_at': article.published_at.isoformat(),
            'sentiment': article.sentiment['compound'],
            'url': article.url
        }
    
    def _calculate_average_sentiment(self, articles: List['NewsArticle']) -> float:
        """Calculate average sentiment for a list of articles"""
        if not articles:
            return 0.0
        
        sentiments = [article.sentiment['compound'] for article in articles if article.sentiment]
        return sum(sentiments) / len(sentiments) if sentiments else 0.0
    
    def generate_gap_report(self, days_back: int = 7) -> Dict[str, Any]:
        """Generate a comprehensive coverage gap report"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        # Aggregate gaps over the period
        all_gaps = []
        daily_scores = []
        
        for i in range(days_back):
            check_date = start_date + timedelta(days=i)
            date_str = check_date.strftime('%Y-%m-%d')
            
            if date_str in self.coverage_data['daily_coverage']:
                daily_coverage = self.coverage_data['daily_coverage'][date_str]
                gaps = self._identify_coverage_gaps(daily_coverage, check_date)
                all_gaps.extend(gaps)
                
                score = self._calculate_coverage_score(daily_coverage)
                daily_scores.append({'date': date_str, 'score': score})
        
        # Aggregate gap analysis
        topic_gap_summary = {}
        for gap in all_gaps:
            topic = gap['topic']
            if topic not in topic_gap_summary:
                topic_gap_summary[topic] = {
                    'total_gap_days': 0,
                    'average_severity': 0,
                    'max_urgency': 0,
                    'suggested_sources': gap['suggested_sources']
                }
            
            topic_gap_summary[topic]['total_gap_days'] += 1
            topic_gap_summary[topic]['max_urgency'] = max(
                topic_gap_summary[topic]['max_urgency'], 
                gap['urgency_score']
            )
        
        # Calculate average severity for each topic
        for topic in topic_gap_summary:
            topic_gaps = [gap for gap in all_gaps if gap['topic'] == topic]
            if topic_gaps:
                avg_urgency = sum(gap['urgency_score'] for gap in topic_gaps) / len(topic_gaps)
                topic_gap_summary[topic]['average_severity'] = avg_urgency
        
        return {
            'period': {
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
                'days_analyzed': days_back
            },
            'overall_coverage_score': sum(score['score'] for score in daily_scores) / len(daily_scores) if daily_scores else 0,
            'daily_scores': daily_scores,
            'critical_gaps': topic_gap_summary,
            'recommendations': self._generate_coverage_recommendations(topic_gap_summary),
            'trend_analysis': self._analyze_coverage_trends(days_back)
        }
    
    def _generate_coverage_recommendations(self, gap_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate actionable recommendations based on gap analysis"""
        recommendations = []
        
        # Sort topics by severity
        sorted_topics = sorted(gap_summary.items(), 
                             key=lambda x: x[1]['average_severity'], 
                             reverse=True)
        
        for topic, data in sorted_topics[:5]:  # Top 5 most critical
            if data['average_severity'] > 5:
                recommendations.append({
                    'priority': 'high' if data['average_severity'] > 10 else 'medium',
                    'topic': topic,
                    'action': f"Increase {topic} coverage",
                    'details': f"Add {data['total_gap_days']} more articles per week",
                    'suggested_sources': data['suggested_sources'][:3],
                    'urgency_score': data['average_severity']
                })
        
        return recommendations
    
    def _analyze_coverage_trends(self, days_back: int) -> Dict[str, Any]:
        """Analyze coverage trends over the specified period"""
        trends = {}
        
        for topic in self.coverage_expectations.keys():
            if topic in self.coverage_data.get('topic_trends', {}):
                trend_data = self.coverage_data['topic_trends'][topic]
                trends[topic] = {
                    'direction': trend_data.get('trend_direction', 'unknown'),
                    'recent_average': self._get_historical_average(topic, datetime.now(), days_back)
                }
        
        return trends


class EventTimelineBuilder:
    """Automatically builds timelines of complex events from news articles"""
    
    def __init__(self, config):
        self.config = config
        self.timelines_file = config.vault_path / "event_timelines.json"
        self.timelines = self._load_timelines()
        
        # Event detection patterns
        self.event_indicators = {
            'crisis': ['crisis', 'emergency', 'disaster', 'catastrophe', 'outbreak'],
            'investigation': ['investigation', 'probe', 'inquiry', 'examining', 'looking into'],
            'legal': ['trial', 'lawsuit', 'court', 'verdict', 'hearing', 'charges'],
            'political': ['election', 'campaign', 'vote', 'policy', 'legislation'],
            'conflict': ['conflict', 'war', 'fighting', 'violence', 'attack'],
            'economic': ['market', 'stocks', 'economy', 'financial', 'trade']
        }
        
        # Timeline stage keywords
        self.stage_keywords = {
            'initial': ['begins', 'starts', 'emerges', 'breaks out', 'announced'],
            'development': ['develops', 'continues', 'ongoing', 'updates', 'latest'],
            'escalation': ['escalates', 'worsens', 'intensifies', 'spreads'],
            'intervention': ['responds', 'intervenes', 'action taken', 'measures'],
            'resolution': ['resolved', 'concluded', 'ended', 'settled', 'finished'],
            'aftermath': ['aftermath', 'consequences', 'result', 'impact', 'following']
        }
    
    def _load_timelines(self) -> Dict[str, Dict]:
        """Load existing timelines from disk"""
        if self.timelines_file.exists():
            try:
                with open(self.timelines_file, 'r') as f:
                    data = json.load(f)
                    # Convert date strings back to datetime objects
                    for timeline_id, timeline in data.items():
                        timeline['created_date'] = datetime.fromisoformat(timeline['created_date'])
                        timeline['last_update'] = datetime.fromisoformat(timeline['last_update'])
                        for event in timeline['events']:
                            event['timestamp'] = datetime.fromisoformat(event['timestamp'])
                            if 'source_published_at' in event:
                                event['source_published_at'] = datetime.fromisoformat(event['source_published_at'])
                    return data
            except Exception as e:
                print(f"⚠️ Error loading timelines: {e}")
        return {}
    
    def _save_timelines(self):
        """Save timelines to disk"""
        try:
            serializable_data = {}
            for timeline_id, timeline in self.timelines.items():
                serializable_timeline = timeline.copy()
                serializable_timeline['created_date'] = timeline['created_date'].isoformat()
                serializable_timeline['last_update'] = timeline['last_update'].isoformat()
                serializable_timeline['events'] = []
                
                for event in timeline['events']:
                    event_data = event.copy()
                    event_data['timestamp'] = event['timestamp'].isoformat()
                    if 'source_published_at' in event_data:
                        event_data['source_published_at'] = event['source_published_at'].isoformat()
                    serializable_timeline['events'].append(event_data)
                
                serializable_data[timeline_id] = serializable_timeline
            
            with open(self.timelines_file, 'w') as f:
                json.dump(serializable_data, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving timelines: {e}")
    
    def process_article_for_timeline(self, article: 'NewsArticle') -> Optional[str]:
        """Process an article and add it to appropriate timeline(s)"""
        # Detect if article is part of a complex event
        event_info = self._detect_event_type(article)
        if not event_info:
            return None
        
        # Find or create timeline
        timeline_id = self._find_or_create_timeline(article, event_info)
        
        # Extract timeline events from article
        events = self._extract_events_from_article(article, event_info)
        
        # Add events to timeline
        if events:
            self._add_events_to_timeline(timeline_id, events)
            self._save_timelines()
            return timeline_id
        
        return None
    
    def _detect_event_type(self, article: 'NewsArticle') -> Optional[Dict[str, Any]]:
        """Detect if article describes a complex event worthy of timeline tracking"""
        article_text = f"{article.title} {article.description}".lower()
        
        # Check for event indicators
        detected_types = []
        for event_type, keywords in self.event_indicators.items():
            if any(keyword in article_text for keyword in keywords):
                detected_types.append(event_type)
        
        if not detected_types:
            return None
        
        # Check for timeline-worthy complexity indicators
        complexity_indicators = [
            len(article.entities) >= 3,  # Multiple entities involved
            any(stage in article_text for stage_keywords in self.stage_keywords.values() for stage in stage_keywords),
            any(word in article_text for word in ['timeline', 'sequence', 'chronology', 'develops', 'ongoing']),
            len(article_text.split()) > 50  # Substantial content
        ]
        
        complexity_score = sum(complexity_indicators)
        
        if complexity_score >= 2:  # Minimum complexity threshold
            return {
                'event_types': detected_types,
                'complexity_score': complexity_score,
                'primary_entities': list(article.entities)[:5],
                'detected_stage': self._detect_event_stage(article_text)
            }
        
        return None
    
    def _detect_event_stage(self, text: str) -> str:
        """Detect what stage of an event this article represents"""
        stage_scores = {}
        
        for stage, keywords in self.stage_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text)
            stage_scores[stage] = score
        
        if not any(stage_scores.values()):
            return 'development'  # Default stage
        
        return max(stage_scores.keys(), key=lambda k: stage_scores[k])
    
    def _find_or_create_timeline(self, article: 'NewsArticle', event_info: Dict[str, Any]) -> str:
        """Find existing timeline or create new one for the event"""
        # Try to match with existing timelines
        for timeline_id, timeline in self.timelines.items():
            if self._article_matches_timeline(article, timeline, event_info):
                return timeline_id
        
        # Create new timeline
        timeline_id = self._generate_timeline_id(article, event_info)
        self._create_new_timeline(timeline_id, article, event_info)
        return timeline_id
    
    def _article_matches_timeline(self, article: 'NewsArticle', timeline: Dict[str, Any], event_info: Dict[str, Any]) -> bool:
        """Check if article belongs to existing timeline"""
        # Entity overlap
        timeline_entities = set(timeline.get('primary_entities', []))
        article_entities = set(event_info['primary_entities'])
        entity_overlap = len(timeline_entities.intersection(article_entities)) / max(len(timeline_entities), 1)
        
        # Topic overlap
        timeline_topics = set(timeline.get('event_types', []))
        article_topics = set(event_info['event_types'])
        topic_overlap = len(timeline_topics.intersection(article_topics)) > 0
        
        # Time window (events should be reasonably close in time)
        time_diff = abs((article.published_at - timeline['last_update']).total_seconds())
        within_time_window = time_diff <= 86400 * 14  # 14 days
        
        # Title similarity for major events
        title_similarity = self._calculate_title_similarity(article.title, timeline.get('title', ''))
        
        return (entity_overlap >= 0.3 and topic_overlap and within_time_window) or title_similarity > 0.4
    
    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """Calculate similarity between two titles"""
        words1 = set(re.findall(r'\w+', title1.lower()))
        words2 = set(re.findall(r'\w+', title2.lower()))
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def _generate_timeline_id(self, article: 'NewsArticle', event_info: Dict[str, Any]) -> str:
        """Generate unique timeline ID"""
        primary_type = event_info['event_types'][0] if event_info['event_types'] else 'event'
        primary_entity = event_info['primary_entities'][0] if event_info['primary_entities'] else 'unknown'
        date_str = article.published_at.strftime('%Y%m%d')
        
        # Clean entity name for ID
        clean_entity = re.sub(r'[^\w\s]', '', primary_entity).replace(' ', '_').lower()[:20]
        
        return f"{primary_type}_{clean_entity}_{date_str}"
    
    def _create_new_timeline(self, timeline_id: str, article: 'NewsArticle', event_info: Dict[str, Any]):
        """Create a new timeline"""
        self.timelines[timeline_id] = {
            'timeline_id': timeline_id,
            'title': self._generate_timeline_title(article, event_info),
            'description': f"Timeline tracking {', '.join(event_info['event_types'])} involving {', '.join(event_info['primary_entities'][:3])}",
            'event_types': event_info['event_types'],
            'primary_entities': event_info['primary_entities'],
            'created_date': article.published_at,
            'last_update': article.published_at,
            'events': [],
            'status': 'active',
            'complexity_score': event_info['complexity_score']
        }
    
    def _generate_timeline_title(self, article: 'NewsArticle', event_info: Dict[str, Any]) -> str:
        """Generate a descriptive title for the timeline"""
        primary_entity = event_info['primary_entities'][0] if event_info['primary_entities'] else 'Unknown'
        primary_type = event_info['event_types'][0].title() if event_info['event_types'] else 'Event'
        
        # Try to extract a concise description from the article title
        title_words = article.title.split()
        if len(title_words) > 8:
            # Use first meaningful part of title
            return f"{primary_type}: {' '.join(title_words[:8])}..."
        else:
            return f"{primary_type}: {article.title}"
    
    def _extract_events_from_article(self, article: 'NewsArticle', event_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract individual events from article content"""
        events = []
        
        # Primary event from article
        primary_event = {
            'timestamp': article.published_at,
            'title': article.title,
            'description': article.description[:200] + '...' if len(article.description) > 200 else article.description,
            'stage': event_info['detected_stage'],
            'source': article.source,
            'source_url': article.url,
            'source_published_at': article.published_at,
            'entities_involved': event_info['primary_entities'][:3],
            'event_type': event_info['event_types'][0] if event_info['event_types'] else 'general',
            'confidence': self._calculate_event_confidence(article, event_info)
        }
        
        events.append(primary_event)
        
        # Try to extract sub-events from content if article is long enough
        if len(article.description) > 300:
            sub_events = self._extract_sub_events(article, event_info)
            events.extend(sub_events)
        
        return events
    
    def _extract_sub_events(self, article: 'NewsArticle', event_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract sub-events from longer articles"""
        sub_events = []
        text = article.description
        sentences = text.split('. ')
        
        # Look for sentences that describe specific actions or developments
        action_words = ['announced', 'confirmed', 'revealed', 'stated', 'reported', 'decided', 'approved', 'rejected']
        
        for sentence in sentences:
            if (len(sentence) > 30 and 
                any(action in sentence.lower() for action in action_words) and
                any(entity.lower() in sentence.lower() for entity in event_info['primary_entities'][:3])):
                
                # Estimate timestamp (could be same day or earlier)
                estimated_time = article.published_at
                
                # Look for time indicators in sentence
                if any(time_word in sentence.lower() for time_word in ['yesterday', 'earlier', 'morning', 'afternoon']):
                    if 'yesterday' in sentence.lower():
                        estimated_time = article.published_at - timedelta(days=1)
                    elif 'earlier' in sentence.lower():
                        estimated_time = article.published_at - timedelta(hours=2)
                
                sub_event = {
                    'timestamp': estimated_time,
                    'title': sentence[:100] + '...' if len(sentence) > 100 else sentence,
                    'description': sentence,
                    'stage': 'development',
                    'source': article.source,
                    'source_url': article.url,
                    'source_published_at': article.published_at,
                    'entities_involved': [entity for entity in event_info['primary_entities'] if entity.lower() in sentence.lower()],
                    'event_type': 'sub_event',
                    'confidence': 0.7  # Lower confidence for extracted sub-events
                }
                
                sub_events.append(sub_event)
        
        return sub_events[:3]  # Limit to 3 sub-events per article
    
    def _calculate_event_confidence(self, article: 'NewsArticle', event_info: Dict[str, Any]) -> float:
        """Calculate confidence in event extraction"""
        confidence = 0.5  # Base confidence
        
        # Higher confidence for more entities
        confidence += min(len(event_info['primary_entities']) * 0.1, 0.2)
        
        # Higher confidence for certain sources
        reliable_sources = ['reuters', 'ap news', 'bbc', 'associated press']
        if any(source in article.source.lower() for source in reliable_sources):
            confidence += 0.2
        
        # Higher confidence for recent articles
        age_hours = (datetime.now() - article.published_at).total_seconds() / 3600
        if age_hours < 24:
            confidence += 0.1
        
        # Higher confidence for longer, detailed articles
        if len(article.description) > 500:
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _add_events_to_timeline(self, timeline_id: str, events: List[Dict[str, Any]]):
        """Add events to timeline in chronological order"""
        if timeline_id not in self.timelines:
            return
        
        timeline = self.timelines[timeline_id]
        
        # Add new events
        for event in events:
            # Check for duplicates
            if not self._is_duplicate_event(event, timeline['events']):
                timeline['events'].append(event)
        
        # Sort events by timestamp
        timeline['events'].sort(key=lambda x: x['timestamp'])
        
        # Update timeline metadata
        timeline['last_update'] = max(event['timestamp'] for event in events)
        
        # Update status based on latest events
        latest_stages = [event['stage'] for event in timeline['events'][-3:]]
        if any(stage in ['resolution', 'aftermath'] for stage in latest_stages):
            timeline['status'] = 'concluded'
    
    def _is_duplicate_event(self, new_event: Dict[str, Any], existing_events: List[Dict[str, Any]]) -> bool:
        """Check if event is duplicate of existing events"""
        for existing in existing_events:
            # Same source and very similar time
            if (existing['source_url'] == new_event['source_url'] and
                abs((existing['timestamp'] - new_event['timestamp']).total_seconds()) < 3600):
                return True
            
            # Very similar title and same day
            title_similarity = self._calculate_title_similarity(existing['title'], new_event['title'])
            same_day = existing['timestamp'].date() == new_event['timestamp'].date()
            if title_similarity > 0.8 and same_day:
                return True
        
        return False
    
    def get_timeline(self, timeline_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific timeline with formatted events"""
        if timeline_id not in self.timelines:
            return None
        
        timeline = self.timelines[timeline_id].copy()
        
        # Format events for display
        formatted_events = []
        for event in timeline['events']:
            formatted_event = event.copy()
            formatted_event['formatted_time'] = event['timestamp'].strftime('%Y-%m-%d %H:%M')
            formatted_event['relative_time'] = self._get_relative_time(event['timestamp'])
            formatted_events.append(formatted_event)
        
        timeline['events'] = formatted_events
        timeline['duration'] = self._calculate_timeline_duration(timeline)
        timeline['event_count'] = len(formatted_events)
        
        return timeline
    
    def _get_relative_time(self, timestamp: datetime) -> str:
        """Get human-readable relative time"""
        now = datetime.now()
        diff = now - timestamp
        
        if diff.days > 0:
            return f"{diff.days} days ago"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} hours ago"
        else:
            minutes = diff.seconds // 60
            return f"{minutes} minutes ago"
    
    def _calculate_timeline_duration(self, timeline: Dict[str, Any]) -> str:
        """Calculate how long the timeline spans"""
        if not timeline['events']:
            return "No events"
        
        start_time = min(event['timestamp'] for event in timeline['events'])
        end_time = max(event['timestamp'] for event in timeline['events'])
        
        duration = end_time - start_time
        
        if duration.days > 0:
            return f"{duration.days} days"
        elif duration.seconds > 3600:
            hours = duration.seconds // 3600
            return f"{hours} hours"
        else:
            return "Same day"
    
    def get_active_timelines(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get currently active timelines"""
        active_timelines = []
        
        for timeline_id, timeline in self.timelines.items():
            if timeline['status'] == 'active':
                summary = {
                    'timeline_id': timeline_id,
                    'title': timeline['title'],
                    'event_types': timeline['event_types'],
                    'last_update': timeline['last_update'],
                    'event_count': len(timeline['events']),
                    'duration': self._calculate_timeline_duration(timeline),
                    'primary_entities': timeline['primary_entities'][:3]
                }
                active_timelines.append(summary)
        
        # Sort by last update (most recent first)
        active_timelines.sort(key=lambda x: x['last_update'], reverse=True)
        
        return active_timelines[:limit]
    
    def generate_timeline_markdown(self, timeline_id: str) -> str:
        """Generate markdown representation of timeline"""
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return "Timeline not found."
        
        markdown = f"# {timeline['title']}\n\n"
        markdown += f"**Description:** {timeline['description']}\n\n"
        markdown += f"**Status:** {timeline['status'].title()}\n"
        markdown += f"**Duration:** {timeline['duration']}\n"
        markdown += f"**Total Events:** {timeline['event_count']}\n"
        markdown += f"**Key Entities:** {', '.join(timeline['primary_entities'])}\n\n"
        
        markdown += "## Timeline of Events\n\n"
        
        current_date = None
        for event in timeline['events']:
            event_date = event['timestamp'].date()
            
            # Add date header if date changed
            if current_date != event_date:
                current_date = event_date
                markdown += f"### {event_date.strftime('%B %d, %Y')}\n\n"
            
            # Event entry
            time_str = event['timestamp'].strftime('%H:%M')
            markdown += f"**{time_str}** - {event['title']}\n"
            if event['description'] != event['title']:
                markdown += f"  {event['description']}\n"
            markdown += f"  *Source: {event['source']}*\n\n"
        
        return markdown


class CrossDayDuplicateDetector:
    """Advanced duplicate detection across multiple days using multiple algorithms"""
    
    def __init__(self, config):
        self.config = config
        self.duplicate_db_file = config.vault_path / "duplicate_database.json"
        self.article_signatures = self._load_signature_database()
        
        # Use configurable thresholds from NewsConfig
        self.title_similarity_threshold = config.TITLE_SIMILARITY_THRESHOLD
        self.content_similarity_threshold = 0.7  # For full content comparison
        self.entity_overlap_threshold = config.ENTITY_OVERLAP_THRESHOLD
        self.days_to_check = config.DUPLICATE_DETECTION_DAYS
        self.min_title_words = 3  # Minimum words for meaningful comparison
        
    def _load_signature_database(self) -> Dict[str, Dict]:
        """Load the signature database from disk"""
        if self.duplicate_db_file.exists():
            try:
                with open(self.duplicate_db_file, 'r') as f:
                    data = json.load(f)
                    # Convert date strings back to datetime objects for cutoff
                    cutoff_date = datetime.now() - timedelta(days=7)  # Fixed: Use fixed value instead of self.days_to_check
                    
                    # Filter out old entries to keep database size manageable
                    filtered_data = {}
                    for article_id, signature in data.items():
                        if datetime.fromisoformat(signature['date']) >= cutoff_date:
                            filtered_data[article_id] = signature
                    
                    return filtered_data
            except Exception as e:
                print(f"⚠️ Error loading duplicate database: {e}")
        return {}
    
    def _save_signature_database(self):
        """Save the signature database to disk"""
        try:
            with open(self.duplicate_db_file, 'w') as f:
                json.dump(self.article_signatures, f, indent=2, default=str)
        except Exception as e:
            print(f"⚠️ Error saving duplicate database: {e}")
    
    def _create_article_signature(self, article: 'NewsArticle') -> Dict[str, Any]:
        """Create a comprehensive signature for an article"""
        # Normalize title for comparison
        title_words = self._normalize_title(article.title)
        
        # Create different types of signatures
        signatures = {
            'date': article.published_at.isoformat(),
            'title_normalized': title_words,
            'title_hash': hashlib.md5(article.title.lower().encode()).hexdigest(),
            'url_domain': self._extract_domain(article.url),
            'source': article.source.lower(),
            'entities': sorted(list(article.entities)),
            'entity_hash': self._create_entity_hash(article.entities),
            'title_fingerprint': self._create_title_fingerprint(title_words),
            'content_hash': hashlib.md5(f"{article.title} {article.description}".encode()).hexdigest()[:16],
            'length_signature': (len(article.title), len(article.description)),
            'region': getattr(article, 'region', 'unknown')
        }
        
        return signatures
    
    def _normalize_title(self, title: str) -> List[str]:
        """Normalize title for comparison"""
        # Remove punctuation, convert to lowercase, split into words
        title_clean = re.sub(r'[^\w\s]', ' ', title.lower())
        words = title_clean.split()
        
        # Remove common stop words that don't add meaning
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'shall'}
        
        meaningful_words = [word for word in words if word not in stop_words and len(word) > 2]
        return meaningful_words
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.lower()
        except:
            return 'unknown'
    
    def _create_entity_hash(self, entities: Set[str]) -> str:
        """Create a hash of sorted entities"""
        if not entities:
            return ""
        sorted_entities = sorted([e.lower() for e in entities])
        return hashlib.md5('|'.join(sorted_entities).encode()).hexdigest()[:12]
    
    def _create_title_fingerprint(self, words: List[str]) -> str:
        """Create a fingerprint based on key words"""
        if len(words) < self.min_title_words:
            return ""
        
        # Take first 3 and last 2 meaningful words as fingerprint
        fingerprint_words = words[:3] + words[-2:] if len(words) >= 5 else words
        return '|'.join(sorted(set(fingerprint_words)))
    
    def _calculate_jaccard_similarity(self, set1: Set[str], set2: Set[str]) -> float:
        """Calculate Jaccard similarity between two sets"""
        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        return intersection / union if union > 0 else 0.0
    
    def _fuzzy_title_match(self, title_words1: List[str], title_words2: List[str]) -> float:
        """Calculate fuzzy similarity between two title word lists"""
        if not title_words1 or not title_words2:
            return 0.0
        
        # Convert to sets for intersection
        set1 = set(title_words1)
        set2 = set(title_words2)
        
        # Basic Jaccard similarity
        jaccard = self._calculate_jaccard_similarity(set1, set2)
        
        # Bonus for sequential matches (words in same order)
        sequential_bonus = 0.0
        min_len = min(len(title_words1), len(title_words2))
        if min_len >= 3:
            # Check for common subsequences
            common_seq = 0
            for i in range(min_len - 1):
                if (title_words1[i] in set2 and 
                    i < len(title_words1) - 1 and 
                    title_words1[i + 1] in set2):
                    common_seq += 1
            
            if common_seq > 0:
                sequential_bonus = min(0.2, common_seq / min_len)
        
        # Length similarity bonus
        len_similarity = 1.0 - abs(len(title_words1) - len(title_words2)) / max(len(title_words1), len(title_words2))
        length_bonus = (len_similarity - 0.5) * 0.1 if len_similarity > 0.5 else 0.0
        
        return min(1.0, jaccard + sequential_bonus + length_bonus)
    
    def _is_likely_duplicate(self, article: 'NewsArticle', existing_signature: Dict[str, Any]) -> Tuple[bool, str, float]:
        """Check if article is likely a duplicate of existing signature"""
        current_signature = self._create_article_signature(article)

        # Initialize default similarity scores
        title_similarity = 0.0
        entity_similarity = 0.0

        # Method 1: Exact title hash match
        if current_signature['title_hash'] == existing_signature['title_hash']:
            return True, "exact_title_match", 1.0

        # Method 2: Title fingerprint match (key words)
        if (current_signature['title_fingerprint'] and
            existing_signature['title_fingerprint'] and
            current_signature['title_fingerprint'] == existing_signature['title_fingerprint']):
            return True, "title_fingerprint_match", 0.95

        # Method 3: High title word similarity
        current_words = set(current_signature['title_normalized'])
        existing_words = set(existing_signature['title_normalized'])
        title_similarity = self._calculate_jaccard_similarity(current_words, existing_words)

        # Calculate entity overlap for later checks
        current_entities = set(current_signature['entities'])
        existing_entities = set(existing_signature['entities'])
        entity_similarity = self._calculate_jaccard_similarity(current_entities, existing_entities)

        # Check if articles are from the same day (more lenient for same-day duplicates)
        same_day = (datetime.fromisoformat(current_signature['date']).date() ==
                   datetime.fromisoformat(existing_signature['date']).date())

        # IMPROVED LOGIC: More flexible duplicate detection
        same_source = current_signature['source'] == existing_signature['source']

        # Method 3a: High title similarity (relaxed for same-day articles)
        title_threshold = 0.7 if same_day else self.title_similarity_threshold  # 0.7 for same day, 0.8 otherwise
        if title_similarity >= title_threshold:
            # Additional checks for high similarity
            if same_source and entity_similarity >= 0.4:  # Lower entity threshold
                return True, "high_similarity_same_source", title_similarity
            elif title_similarity >= 0.85:  # Very high title similarity
                return True, "very_high_title_similarity", title_similarity
            elif same_day and title_similarity >= 0.75 and entity_similarity >= 0.3:
                return True, "same_day_high_similarity", title_similarity

        # Method 3b: Fuzzy title matching for partial matches
        fuzzy_title_match = self._fuzzy_title_match(
            current_signature['title_normalized'],
            existing_signature['title_normalized']
        )
        if fuzzy_title_match >= 0.8:  # 80% fuzzy match
            return True, "fuzzy_title_match", fuzzy_title_match

        # Method 4: Entity hash match (same key entities, likely same story)
        if (current_signature['entity_hash'] and
            existing_signature['entity_hash'] and
            current_signature['entity_hash'] == existing_signature['entity_hash'] and
            len(current_signature['entities']) >= 2):  # Minimum entities for reliable match

            # More lenient title check since entities match perfectly
            if title_similarity >= 0.4:  # Much lower threshold since entities match
                return True, "entity_hash_match", entity_similarity

        # Method 5: High entity overlap with moderate title similarity
        if entity_similarity >= 0.7 and title_similarity >= 0.5:
            return True, "high_entity_overlap", entity_similarity

        # Method 6: Same-day articles with significant overlap
        if same_day and entity_similarity >= 0.5 and title_similarity >= 0.6:
            return True, "same_day_entity_overlap", max(title_similarity, entity_similarity)

        # Method 7: Content hash match
        if current_signature['content_hash'] == existing_signature['content_hash']:
            return True, "content_hash_match", 0.9

        return False, "no_match", 0.0
    
    def check_for_duplicates(self, articles: List['NewsArticle']) -> Tuple[List['NewsArticle'], List[Dict]]:
        """Check articles against existing database and return non-duplicates"""
        unique_articles = []
        duplicate_info = []
        articles_to_add = []  # Collect articles to add after all processing

        for article in articles:
            is_duplicate = False
            duplicate_details = None

            # Check against existing signatures (don't modify database during checking)
            for existing_id, existing_signature in self.article_signatures.items():
                is_dup, method, confidence = self._is_likely_duplicate(article, existing_signature)

                if is_dup:
                    duplicate_details = {
                        'article_title': article.title,
                        'article_url': article.url,
                        'duplicate_of_id': existing_id,
                        'duplicate_date': existing_signature['date'],
                        'detection_method': method,
                        'confidence': confidence,
                        'reason': f"Duplicate detected via {method} (confidence: {confidence:.2f})"
                    }
                    duplicate_info.append(duplicate_details)
                    is_duplicate = True
                    break

            if not is_duplicate:
                # Not a duplicate, add to unique list
                unique_articles.append(article)
                # Collect for adding to database later
                articles_to_add.append(article)

        # Only after all articles are processed, add unique ones to database
        for article in articles_to_add:
            article_id = f"{article.published_at.strftime('%Y%m%d')}_{hash(article.title + article.url)}"
            self.article_signatures[article_id] = self._create_article_signature(article)

        # Save updated database
        self._save_signature_database()

        return unique_articles, duplicate_info
    
    def cleanup_old_signatures(self):
        """Remove signatures older than the configured days"""
        cutoff_date = datetime.now() - timedelta(days=7)  # Fixed: Use fixed value instead of self.days_to_check
        
        old_keys = []
        for article_id, signature in self.article_signatures.items():
            try:
                if datetime.fromisoformat(signature['date']) < cutoff_date:
                    old_keys.append(article_id)
            except:
                # Invalid date format, remove it
                old_keys.append(article_id)
        
        for key in old_keys:
            del self.article_signatures[key]
        
        if old_keys:
            print(f"🗑️ Cleaned up {len(old_keys)} old article signatures")
            self._save_signature_database()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the duplicate detection database"""
        total_signatures = len(self.article_signatures)
        
        # Group by date
        dates = {}
        for signature in self.article_signatures.values():
            try:
                date = datetime.fromisoformat(signature['date']).date()
                dates[date] = dates.get(date, 0) + 1
            except:
                continue
        
        # Group by source
        sources = {}
        for signature in self.article_signatures.values():
            source = signature.get('source', 'unknown')
            sources[source] = sources.get(source, 0) + 1
        
        return {
            'total_signatures': total_signatures,
            'signatures_by_date': dict(sorted(dates.items(), reverse=True)),
            'signatures_by_source': dict(sorted(sources.items(), key=lambda x: x[1], reverse=True)),
            'oldest_signature': min(dates.keys()) if dates else None,
            'newest_signature': max(dates.keys()) if dates else None,
            'database_file_size': self.duplicate_db_file.stat().st_size if self.duplicate_db_file.exists() else 0
        }


class UserInterestProfile:
    """Manages user interest tracking and personalized content scoring"""
    
    def __init__(self, config):
        self.config = config
        self.profile_file = config.output_path / "user_profile.json"
        self.interests = self._load_profile()
        
    def _load_profile(self) -> Dict[str, Any]:
        """Load user interest profile from disk"""
        if self.profile_file.exists():
            try:
                with open(self.profile_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Error loading user profile: {e}")
        
        # Default profile
        return {
            'topics': {},  # topic -> interest_score (0-1)
            'entities': {},  # entity -> interest_score (0-1)
            'sources': {},  # source -> trust_score (0-1)
            'regions': {},  # region -> interest_score (0-1)
            'reading_history': [],  # list of article slugs
            'preferences': {
                'sentiment_preference': 0.0,  # -1 (negative) to 1 (positive)
                'complexity_preference': 0.5,  # 0 (simple) to 1 (complex)
                'length_preference': 0.5  # 0 (short) to 1 (long)
            }
        }
    
    def save_profile(self):
        """Save user profile to disk"""
        try:
            with open(self.profile_file, 'w') as f:
                json.dump(self.interests, f, indent=2, default=str)
        except Exception as e:
            print(f"⚠️ Error saving user profile: {e}")
    
    def update_interest(self, article: 'NewsArticle', engagement_type: str = 'viewed'):
        """Update user interests based on article interaction"""
        weights = {
            'viewed': 0.1,
            'read': 0.3,
            'saved': 0.5,
            'shared': 0.7
        }
        
        weight = weights.get(engagement_type, 0.1)
        
        # Update topic interests
        for topic in article.topics:
            current = self.interests['topics'].get(topic, 0.5)
            self.interests['topics'][topic] = min(1.0, current + weight * 0.1)
        
        # Update entity interests
        for entity in article.entities:
            current = self.interests['entities'].get(entity, 0.5)
            self.interests['entities'][entity] = min(1.0, current + weight * 0.05)
        
        # Update source trust
        current = self.interests['sources'].get(article.source, 0.5)
        self.interests['sources'][article.source] = min(1.0, current + weight * 0.02)
        
        # Update region interest
        current = self.interests['regions'].get(article.region, 0.5)
        self.interests['regions'][article.region] = min(1.0, current + weight * 0.05)
        
        # Add to reading history
        if article.slug not in self.interests['reading_history']:
            self.interests['reading_history'].append(article.slug)
            # Keep only last 100 articles
            if len(self.interests['reading_history']) > 100:
                self.interests['reading_history'] = self.interests['reading_history'][-100:]
        
        self.save_profile()
    
    def calculate_interest_score(self, article: 'NewsArticle') -> float:
        """Calculate personalized interest score for an article"""
        score = 0.5  # Base score
        
        # Topic relevance (40% weight)
        topic_scores = [self.interests['topics'].get(topic, 0.5) for topic in article.topics]
        if topic_scores:
            score += 0.4 * (sum(topic_scores) / len(topic_scores) - 0.5)
        
        # Entity relevance (30% weight)
        entity_scores = [self.interests['entities'].get(entity, 0.5) for entity in article.entities]
        if entity_scores:
            score += 0.3 * (sum(entity_scores) / len(entity_scores) - 0.5)
        
        # Source trust (20% weight)
        source_score = self.interests['sources'].get(article.source, 0.5)
        score += 0.2 * (source_score - 0.5)
        
        # Region interest (10% weight)
        region_score = self.interests['regions'].get(article.region, 0.5)
        score += 0.1 * (region_score - 0.5)
        
        # Sentiment preference adjustment
        if hasattr(article, 'sentiment') and article.sentiment:
            sentiment_diff = abs(article.sentiment['compound'] - self.interests['preferences']['sentiment_preference'])
            score -= sentiment_diff * 0.1  # Penalize mismatched sentiment
        
        return max(0.0, min(1.0, score))
    
    def get_recommended_articles(self, articles: List['NewsArticle'], limit: int = 10) -> List['NewsArticle']:
        """Get personalized article recommendations"""
        # Filter out already read articles
        unread_articles = [a for a in articles if a.slug not in self.interests['reading_history']]
        
        # Calculate interest scores
        scored_articles = [(article, self.calculate_interest_score(article)) for article in unread_articles]
        
        # Sort by interest score
        scored_articles.sort(key=lambda x: x[1], reverse=True)
        
        return [article for article, score in scored_articles[:limit]]


class NewsArticle:
    """Represents a news article with metadata and advanced analysis"""
    
    def __init__(self, title: str, description: str, url: str, source: str, 
                 published_at: datetime, content: str = ""):
        self.title = title
        self.description = description
        self.url = url
        self.source = source
        self.published_at = published_at
        self.content = content
        self.entities: Set[str] = set()
        self.slug = self._create_slug()
        self.region = "Other"
        self.topics: Set[str] = set()
        self.sentiment = {"compound": 0.0, "positive": 0.0, "negative": 0.0, "neutral": 0.0}
        self.readability_score = 0.0
        self.full_text = ""
        self.summary = ""
        self.hash = self._create_hash()
        
    def get_sentiment_emoji(self) -> str:
        """Get emoji based on sentiment score with rich semantic variety based on the emoji chart"""
        compound = self.sentiment['compound']
        
        # Very positive emotions (0.8+)
        if compound >= 0.9:
            return "🤩"  # Star-struck, very positive news
        elif compound >= 0.8:
            return "😄"  # Laughing, great news
        elif compound >= 0.7:
            return "😊"  # Smiling, good news
        
        # Moderately positive (0.3-0.7)  
        elif compound >= 0.5:
            return "😌"  # Slightly smiling, mildly positive
        elif compound >= 0.3:
            return "🙂"  # Relieved, cautiously positive
        elif compound >= 0.1:
            return "😐"  # Neutral face, barely positive
            
        # Neutral zone (-0.1 to 0.1)
        elif compound >= -0.1:
            return "😶"  # No mouth, truly neutral
            
        # Negative emotions
        elif compound >= -0.3:
            return "😕"  # Slightly frowning, mildly concerning
        elif compound >= -0.5:
            return "☹️"  # Frowning face, bad news
        elif compound >= -0.7:
            return "😟"  # Worried face, serious concern
        elif compound >= -0.8:
            return "😨"  # Fearful face, alarming news
        elif compound >= -0.9:
            return "😰"  # Anxious with sweat, very bad news
        else:
            return "😱"  # Screaming, catastrophic news
            
    def format_date(self, format_type: str = "dd_mm_yyyy") -> str:
        """Format date in DD MM YYYY format"""
        if format_type == "dd_mm_yyyy":
            return self.published_at.strftime("%d %m %Y")
        elif format_type == "dd-mm-yyyy":
            return self.published_at.strftime("%d-%m-%Y")
        else:
            return self.published_at.strftime("%Y-%m-%d")  # fallback
        
    def _create_hash(self) -> str:
        """Create a unique hash for the article"""
        content_str = f"{self.title}{self.url}{self.published_at.isoformat()}"
        return hashlib.md5(content_str.encode()).hexdigest()[:10]
        
    def _create_slug(self) -> str:
        """Create a safe filename slug from the title in DD MM YYYY folder structure"""
        date_str = self.published_at.strftime("%d %m %Y")
        title_slug = slugify(self.title, max_length=NewsConfig.MAX_TITLE_LENGTH)
        return f"{date_str}/{title_slug}"
    
    def extract_entities(self, nlp):
        """Extract named entities from the article content"""
        text = f"{self.title} {self.description} {self.content} {self.full_text}"
        doc = nlp(text)
        
        for ent in doc.ents:
            if ent.label_ in {'PERSON', 'ORG', 'GPE', 'EVENT', 'WORK_OF_ART'} and len(ent.text.strip()) > NewsConfig.MIN_ENTITY_LENGTH:
                # Clean and normalize entity text
                entity = re.sub(r'[^\w\s-]', '', ent.text.strip())
                if entity and not entity.lower() in {'the', 'a', 'an', 'this', 'that'}:
                    self.entities.add(entity)
        
        # Normalize entities after extraction
        self.entities = self._normalize_entities(self.entities)
    
    def _normalize_entities(self, entities: Set[str]) -> Set[str]:
        """Normalize and deduplicate similar entities"""
        normalized = set()
        entity_list = list(entities)
        
        # Known entity mappings
        entity_mappings = {
            'trump': 'Donald Trump',
            'biden': 'Joe Biden',
            'putin': 'Vladimir Putin',
            'zelensky': 'Volodymyr Zelensky',
            'xi': 'Xi Jinping',
            'harris': 'Kamala Harris',
            'us': 'United States',
            'usa': 'United States',
            'america': 'United States',
            'uk': 'United Kingdom',
            'britain': 'United Kingdom',
            'eu': 'European Union',
            'un': 'United Nations',
            'nato': 'NATO',
            'fed': 'Federal Reserve',
            'fbi': 'FBI',
            'cia': 'CIA',
            'nfl': 'NFL',
            'nba': 'NBA',
        }
        
        # First pass: apply known mappings
        for entity in entity_list:
            entity_lower = entity.lower().strip()
            if entity_lower in entity_mappings:
                normalized.add(entity_mappings[entity_lower])
            else:
                normalized.add(entity)
        
        # Second pass: merge similar entities
        final_entities = set()
        processed = set()
        
        for entity in normalized:
            if entity in processed:
                continue
                
            # Find similar entities
            similar_found = False
            for existing in list(final_entities):
                if self._are_similar_entities(entity, existing):
                    # Keep the longer, more complete name
                    if len(entity) > len(existing):
                        final_entities.remove(existing)
                        final_entities.add(entity)
                    similar_found = True
                    break
            
            if not similar_found:
                final_entities.add(entity)
            
            processed.add(entity)
        
        return final_entities
    
    def _are_similar_entities(self, entity1: str, entity2: str) -> bool:
        """Check if two entities refer to the same thing"""
        e1_lower = entity1.lower().strip()
        e2_lower = entity2.lower().strip()
        
        # Exact match
        if e1_lower == e2_lower:
            return True
        
        # One is contained in the other (e.g., "Trump" in "Donald Trump")
        if e1_lower in e2_lower or e2_lower in e1_lower:
            return True
        
        # Check for common patterns
        patterns = [
            # First name variations
            (r'\b(\w+)\s+\w+', r'\1'),  # "John Smith" -> "John"
            # Organization abbreviations
            (r'\b(federal\s+reserve|fed)\b', 'fed'),
            (r'\b(united\s+states|usa?|america)\b', 'us'),
            (r'\b(united\s+kingdom|uk|britain)\b', 'uk'),
        ]
        
        for pattern, replacement in patterns:
            if re.search(pattern, e1_lower) and re.search(pattern, e2_lower):
                return True
        
        return False
    
    def extract_full_text(self):
        """Extract full article text using newspaper3k with retry logic"""
        max_retries = 2
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                article = newspaper.Article(self.url)
                article.download()
                article.parse()
                
                if article.text and len(article.text) > 100:
                    # Clean up the text - remove standalone "advertisement" paragraphs
                    text = article.text[:50000]  # Limit for performance
                    
                    # Remove lines that are just "advertisement" or similar
                    lines = text.split('\n')
                    cleaned_lines = []
                    
                    for line in lines:
                        line_clean = line.strip().lower()
                        # Skip lines that are just advertisement-related words
                        if line_clean in ['advertisement','advertisement advertisement','ads', 'sponsored', 'sponsored content', 'ad']:
                            continue
                        cleaned_lines.append(line)
                    
                    self.full_text = '\n'.join(cleaned_lines)
                    
                    # Calculate readability
                    try:
                        self.readability_score = flesch_reading_ease(self.full_text)
                        print(f"✅ Full text extracted, readability: {self.readability_score:.1f}")
                    except Exception as e:
                        self.readability_score = 50.0
                        print(f"⚠️ Readability calculation failed: {e}")
                    return True
                else:
                    print(f"⚠️ No substantial text found for {self.url}")
                    return False
                        
            except Exception as e:
                if "403" in str(e) or "401" in str(e) or "Forbidden" in str(e):
                    # Don't retry for permission errors, mark as failed immediately
                    print(f"❌ Failed to extract full text from {self.url}: {e}")
                    return False
                elif attempt < max_retries - 1:
                    print(f"⚠️ Attempt {attempt + 1} failed for {self.url}, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    print(f"❌ Failed to extract full text from {self.url}: {e}")
                    return False
        
        return False
    
    def analyze_sentiment(self, sentiment_pipeline):
        """Analyze article sentiment using transformers"""
        if sentiment_pipeline is None:
            print("⚠️ Sentiment pipeline not available")
            return
            
        try:
            text = f"{self.title}. {self.description}"
            if len(text) > 512:
                text = text[:512]
                
            result = sentiment_pipeline(text)
            
            # Handle different result formats - transformers can return nested lists
            while isinstance(result, list) and len(result) > 0:
                result = result[0]  # Keep extracting until we get the actual result dict
            
            if isinstance(result, dict) and 'label' in result and 'score' in result:
                # Standard format with label and score
                if result['label'] == 'POSITIVE':
                    self.sentiment['positive'] = result['score']
                    self.sentiment['compound'] = result['score']
                else:
                    self.sentiment['negative'] = result['score']
                    self.sentiment['compound'] = -result['score']
                    
                print(f"✅ Sentiment analyzed: {result['label']} ({result['score']:.2f})")
            else:
                print(f"⚠️ Unexpected sentiment result format: {type(result)} - {result}")
                # Set neutral sentiment as fallback
                self.sentiment = {"compound": 0.0, "positive": 0.0, "negative": 0.0, "neutral": 1.0}
                
        except Exception as e:
            print(f"❌ Sentiment analysis failed: {e}")
            # Set neutral sentiment as fallback
            self.sentiment = {"compound": 0.0, "positive": 0.0, "negative": 0.0, "neutral": 1.0}
    
    def extract_topics(self, tracked_topics):
        """Extract topics from article content"""
        text = f"{self.title} {self.description} {self.content}".lower()
        
        for topic in tracked_topics:
            if topic in text:
                self.topics.add(topic)
    
    def infer_region(self, source_region_map):
        """Infer article region from source"""
        source_lower = self.source.lower()
        url_lower = self.url.lower()
        
        for source_key, region in source_region_map.items():
            if source_key in source_lower or source_key in url_lower:
                self.region = region
                return
        
        # Fallback: infer from entities
        for entity in self.entities:
            entity_lower = entity.lower()
            if any(country in entity_lower for country in ['united states', 'america', 'us']):
                self.region = "US"
                return
            elif any(country in entity_lower for country in ['china', 'india', 'japan', 'korea', 'singapore']):
                self.region = "Asia"
                return
            elif any(country in entity_lower for country in ['france', 'germany', 'uk', 'britain', 'russia', 'ukraine']):
                self.region = "Europe"
                return
            elif any(country in entity_lower for country in ['israel', 'iran', 'saudi', 'uae', 'qatar']):
                self.region = "Middle East"
                return
            elif any(country in entity_lower for country in ['nigeria', 'south africa', 'egypt', 'kenya']):
                self.region = "Africa"
                return


class NewsScraper:
    """Main news scraper class with advanced AI features and async support"""
    
    def __init__(self, config: NewsConfig):
        self.config = config
        self.nlp = None
        self.sentiment_pipeline = None
        self.summarizer = None
        
        # HTTP session for connection pooling and better performance
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'NewsScraper/1.0 (https://github.com/your-repo/news-scraper)'
        })
        
        # Async HTTP session for concurrent operations
        self.async_session = None
        
        # Thread pool for CPU-bound operations
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Caching layer
        self.cache = {}
        self.cache_ttl = 3600  # 1 hour
        
        # Metrics collection
        self.metrics = {
            'articles_processed': 0,
            'articles_filtered': 0,
            'duplicates_found': 0,
            'api_requests': 0,
            'api_errors': 0,
            'processing_time': 0.0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        self.start_time = time.time()
        
        self.event_tracker = EventTracker(config)
        self.source_tracker = SourceReliabilityTracker(config)
        self.geo_cluster = GeographicEventCluster()
        self.bias_analyzer = BiasAnalyzer()
        self.user_profile = UserInterestProfile(config)
        self.duplicate_detector = CrossDayDuplicateDetector(config)
        self.story_tracker = StoryEvolutionTracker(config)
        self.coverage_analyzer = CoverageGapAnalyzer(config)
        self.timeline_builder = EventTimelineBuilder(config)
        self._load_models()
        self._ensure_directories()
    
    def _get_cache_key(self, url: str, params: Optional[Dict] = None) -> str:
        """Generate cache key for URL and parameters"""
        key_parts = [url]
        if params:
            # Sort params for consistent caching
            sorted_params = sorted(params.items())
            key_parts.extend(f"{k}={v}" for k, v in sorted_params)
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()
    
    def _get_cached_response(self, cache_key: str) -> Optional[Dict]:
        """Get cached response if still valid"""
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_data
            else:
                # Remove expired cache entry
                del self.cache[cache_key]
        return None
    
    def _cache_response(self, cache_key: str, data: Dict):
        """Cache response data"""
        self.cache[cache_key] = (data, time.time())
        # Limit cache size to prevent memory issues
        if len(self.cache) > 1000:
            # Remove oldest entries
            oldest_keys = sorted(self.cache.keys(), 
                               key=lambda k: self.cache[k][1])[:100]
            for key in oldest_keys:
                del self.cache[key]
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get comprehensive health status"""
        uptime = time.time() - self.start_time
        
        return {
            'status': 'healthy',
            'uptime_seconds': uptime,
            'metrics': self.metrics.copy(),
            'config_valid': self._validate_config_health(),
            'dependencies': self._check_dependencies(),
            'cache_stats': {
                'size': len(self.cache),
                'ttl': self.cache_ttl
            }
        }
    
    def _validate_config_health(self) -> bool:
        """Validate configuration is healthy"""
        try:
            # Check critical paths exist
            required_paths = [
                self.config.vault_path,
                self.config.stories_path,
                self.config.entities_path
            ]
            return all(path.exists() for path in required_paths)
        except:
            return False
    
    def _check_dependencies(self) -> Dict[str, bool]:
        """Check if all dependencies are available"""
        return {
            'spacy': self.nlp is not None,
            'transformers': HAS_TRANSFORMERS,
            'torch': HAS_TORCH,
            'newsapi': bool(self.config.newsapi_key and 
                          self.config.newsapi_key != "YOUR_NEWSAPI_KEY_HERE")
        }
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get detailed performance statistics"""
        uptime = time.time() - self.start_time
        
        return {
            'uptime_hours': uptime / 3600,
            'articles_per_hour': self.metrics['articles_processed'] / max(uptime / 3600, 1),
            'cache_hit_ratio': (self.metrics['cache_hits'] / 
                              max(self.metrics['cache_hits'] + self.metrics['cache_misses'], 1)),
            'api_success_rate': (1 - self.metrics['api_errors'] / 
                               max(self.metrics['api_requests'], 1)),
            'avg_processing_time': (self.metrics['processing_time'] / 
                                  max(self.metrics['articles_processed'], 1))
        }
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.async_session = aiohttp.ClientSession(
            headers={'User-Agent': 'NewsScraper/1.0'},
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.async_session:
            await self.async_session.close()
    
    def __del__(self):
        """Cleanup resources"""
        try:
            if hasattr(self, 'session'):
                self.session.close()
            if hasattr(self, 'executor'):
                self.executor.shutdown(wait=False)
            if hasattr(self, 'async_session') and self.async_session:
                # Note: async_session cleanup should be handled by async context manager
                pass
        except:
            pass  # Ignore errors during cleanup
        
    def _load_models(self):
        """Load spaCy and transformer models"""
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError as e:
            logger.error("spaCy English model not found!")
            logger.error("Please install it with: python -m spacy download en_core_web_sm")
            raise
        
        # Load lightweight transformer models with GPU support
        self.sentiment_pipeline = None
        self.summarizer = None
        
        # Determine device (GPU if available on MacBook)
        device = self._get_optimal_device()
        
        try:
            if self.config.enable_sentiment_analysis and HAS_TRANSFORMERS:
                logger.info("🔄 Loading sentiment analysis model...")
                self.sentiment_pipeline = pipeline(
                    "sentiment-analysis", 
                    model="distilbert-base-uncased-finetuned-sst-2-english",
                    top_k=1,
                    device=device
                )
                logger.info(f"✅ Loaded sentiment model on {device}")
                
            if self.config.enable_auto_summarization and HAS_TRANSFORMERS:
                logger.info("🔄 Loading summarization model...")
                self.summarizer = pipeline(
                    "summarization", 
                    model="facebook/bart-large-cnn",
                    max_length=100,
                    min_length=30,
                    device=device
                )
                logger.info(f"✅ Loaded summarization model on {device}")
                
        except Exception as e:
            logger.warning(f"⚠️ Could not load transformer models: {e}")
            logger.warning("Continuing with basic features only...")
            self.sentiment_pipeline = None
            self.summarizer = None
    
    def _get_optimal_device(self):
        """Get the optimal device for transformer models"""
        if not HAS_TORCH:
            print("💻 PyTorch not available, using CPU")
            return -1
            
        try:
            # Try MPS first (Apple Silicon GPU)
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                logger.info("🚀 Using MacBook GPU (MPS) for AI models")
                return "mps"
            elif torch.cuda.is_available():
                logger.info("🚀 Using CUDA GPU for AI models")
                return 0
            else:
                logger.info("💻 Using CPU for AI models")
                return -1
        except Exception as e:
            logger.warning(f"💻 Device detection failed, using CPU: {e}")
            return -1
    
    def _ensure_directories(self):
        """Create necessary directories if they don't exist"""
        self.config.vault_path.mkdir(parents=True, exist_ok=True)
        self.config.stories_path.mkdir(parents=True, exist_ok=True)
        self.config.entities_path.mkdir(parents=True, exist_ok=True)
        self.config.topics_path.mkdir(parents=True, exist_ok=True)
        self.config.timelines_path.mkdir(parents=True, exist_ok=True)
    
    def fetch_from_newsapi(self) -> List[NewsArticle]:
        """Fetch news from NewsAPI.org (requires API key)"""
        if not self.config.newsapi_key:
            return []
        
        articles = []
        try:
            params = {
                'apiKey': self.config.newsapi_key,
                'category': 'general',
                'language': 'en',
                'pageSize': 50,
                'sortBy': 'publishedAt'
            }
            
            response = self.session.get(self.config.newsapi_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            for item in data.get('articles', []):
                if item.get('title') and item.get('description'):
                    article = NewsArticle(
                        title=item['title'],
                        description=item['description'] or "",
                        url=item['url'],
                        source=item['source']['name'],
                        published_at=datetime.fromisoformat(item['publishedAt'].replace('Z', '+00:00')),
                        content=item.get('content', '')
                    )
                    articles.append(article)
            
            print(f"Fetched {len(articles)} articles from NewsAPI")
            
        except Exception as e:
            print(f"Error fetching from NewsAPI: {e}")
        
        return articles
    
    def fetch_from_rss(self) -> List[NewsArticle]:
        """Fetch news from RSS feeds with strict filtering for real news"""
        articles = []
        current_time = datetime.now()
        cutoff_date = current_time - timedelta(days=2)  # Only articles from last 2 days

        # Marketing/promotional content indicators to filter out
        spam_indicators = [
            'review', 'pricing', 'features', 'marketing tools', 'ai studio', 
            'crunch hype', 'sponsored', 'advertisement', 'promo', 'deal',
            'discount', 'offer', 'sale', 'buy now', 'click here', 'affiliate',
            'top 10', 'top 11', 'best tools', 'you should use', 'updated 20',
            'everything you need to know', 'complete guide', 'ultimate guide',
            'how to make money', 'earn money', 'passive income'
        ]
        
        for feed_url in self.config.rss_feeds:
            try:
                print(f"Fetching from RSS: {feed_url}")
                feed = feedparser.parse(feed_url)
                
                # Verify this is a legitimate news source
                feed_title = getattr(feed.feed, 'title', '').lower() if hasattr(feed, 'feed') else ''
                if any(spam in feed_title for spam in ['crunch hype', 'marketing', 'promo', 'deal']):
                    print(f"⚠️ Skipping non-news feed: {feed_title}")
                    continue
                
                for entry in feed.entries[:10]:  # Limit per feed
                    if hasattr(entry, 'title') and hasattr(entry, 'link'):
                        # Parse publication date safely
                        pub_date = datetime.now()
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            try:
                                parsed_time = entry.published_parsed
                                if isinstance(parsed_time, tuple) and len(parsed_time) >= 6:
                                    pub_date = datetime(*parsed_time[:6])
                            except:
                                pub_date = datetime.now()
                        
                        # Filter out old articles
                        if pub_date < cutoff_date:
                            print(f"⚠️ Skipping old article from {pub_date.strftime('%Y-%m-%d')}: {str(entry.title)[:50]}")
                            continue
                        
                        # Filter out promotional/marketing content
                        title_str = str(entry.title) if hasattr(entry, 'title') else ''
                        description_str = str(getattr(entry, 'summary', ''))
                        title_lower = title_str.lower()
                        description_lower = description_str.lower()
                        
                        if any(spam in title_lower or spam in description_lower for spam in spam_indicators):
                            print(f"⚠️ Skipping promotional content: {title_str[:50]}")
                            continue
                        
                        # Additional filters for real news
                        if not self._is_legitimate_news_article(title_str, description_str):
                            print(f"⚠️ Skipping non-news content: {title_str[:50]}")
                            continue
                        
                        article = NewsArticle(
                            title=title_str,
                            description=description_str,
                            url=str(entry.link) if hasattr(entry, 'link') else '',
                            source=getattr(feed.feed, 'title', 'Unknown') if hasattr(feed, 'feed') else 'Unknown',
                            published_at=pub_date,
                            content=str(getattr(entry, 'content', ''))
                        )
                        articles.append(article)
                
                time.sleep(1)  # Be respectful to RSS feeds
                
            except Exception as e:
                print(f"Error fetching RSS from {feed_url}: {e}")
                continue
        
        print(f"Fetched {len(articles)} legitimate news articles from RSS feeds")
        return articles
    
    def _is_legitimate_news_article(self, title: str, description: str) -> bool:
        """Check if content appears to be legitimate news rather than promotional material"""
        content = f"{title} {description}".lower()
        
        # Require news indicators
        news_indicators = [
            'government', 'president', 'minister', 'parliament', 'congress', 'senate',
            'election', 'policy', 'economy', 'trade', 'market', 'industry',
            'court', 'judge', 'legal', 'law', 'regulation', 'investigation',
            'conflict', 'war', 'peace', 'treaty', 'diplomacy', 'international',
            'climate', 'environment', 'health', 'medical', 'research', 'study',
            'technology', 'innovation', 'breakthrough', 'discovery', 'science',
            'crisis', 'emergency', 'disaster', 'incident', 'accident', 'attack',
            'company', 'business', 'corporate', 'financial', 'revenue', 'profit',
            'society', 'community', 'public', 'citizen', 'people', 'population'
        ]
        
        # Red flags for non-news content
        non_news_flags = [
            'how to', 'guide to', 'tips for', 'ways to', 'steps to',
            'buy now', 'order now', 'get yours', 'limited time', 'special offer',
            'affiliate', 'commission', 'sponsored by', 'paid partnership',
            'review of', 'unboxing', 'tutorial', 'course', 'lesson',
            'webinar', 'ebook', 'download', 'subscribe', 'newsletter',
            'vs ', ' vs.', 'comparison', 'which is better', 'pros and cons'
        ]
        
        # Check for news indicators
        has_news_indicator = any(indicator in content for indicator in news_indicators)
        
        # Check for non-news flags
        has_non_news_flag = any(flag in content for flag in non_news_flags)
        
        # Must have news indicators and not have non-news flags
        return has_news_indicator and not has_non_news_flag
    
    def fetch_news(self) -> List[NewsArticle]:
        """Fetch news from RSS feeds with intelligent article selection"""
        articles = []
        
        # Prioritize RSS feeds for more diverse, editorial content
        print("📡 Fetching from curated RSS feeds...")
        rss_articles = self.fetch_from_rss()
        articles.extend(rss_articles)
        
        # Only use NewsAPI as supplementary if we're short on articles
        if len(articles) < self.config.max_articles_per_day * 0.8:  # 80% threshold
            print("📰 Supplementing with NewsAPI articles...")
            newsapi_articles = self.fetch_from_newsapi()
            articles.extend(newsapi_articles)
        
        # Remove duplicates based on title similarity
        unique_articles = self._deduplicate_articles(articles)
        
        print(f"Processing {len(unique_articles)} articles with AI features...")
        
        # Process each article with AI features and quality scoring
        scored_articles = []
        for i, article in enumerate(unique_articles):
            if i % 10 == 0:
                print(f"  Processed {i}/{len(unique_articles)} articles...")
            
            # Extract entities
            article.extract_entities(self.nlp)
            
            # Infer region
            article.infer_region(self.config.source_region_map)
            
            # Extract topics
            article.extract_topics(self.config.tracked_topics)
            
            # Extract full text (if enabled)
            if self.config.enable_full_text_extraction:
                extraction_success = article.extract_full_text()
                if not extraction_success:
                    # Skip articles that couldn't be extracted
                    print(f"⚠️ Skipping article due to extraction failure: {article.title[:50]}")
                    continue
            
            # Analyze sentiment (if enabled)
            if self.config.enable_sentiment_analysis and self.sentiment_pipeline:
                article.analyze_sentiment(self.sentiment_pipeline)
            
            # Calculate quality score for intelligent selection
            quality_score = self._calculate_article_quality(article)
            scored_articles.append((article, quality_score))
        
        # Sort by quality score (higher is better)
        scored_articles.sort(key=lambda x: x[1], reverse=True)
        processed_articles = [article for article, score in scored_articles]

        # Apply cross-day duplicate detection FIRST (before selection)
        if self.config.ENABLE_ADVANCED_DUPLICATE_DETECTION:
            print(f"🔍 Checking {len(processed_articles)} articles for cross-day duplicates...")
            unique_articles, duplicate_info = self.duplicate_detector.check_for_duplicates(processed_articles)

            if duplicate_info:
                print(f"🚫 Filtered out {len(duplicate_info)} duplicate articles:")
                for dup in duplicate_info[:5]:  # Show first 5 duplicates
                    print(f"   - '{dup['article_title'][:60]}...' - {dup['reason']}")
                if len(duplicate_info) > 5:
                    print(f"   ... and {len(duplicate_info) - 5} more duplicates")

            # Clean up old signatures periodically (every run)
            self.duplicate_detector.cleanup_old_signatures()

            # Generate duplicate detection report
            if duplicate_info:
                self._create_duplicate_report(duplicate_info)
        else:
            print("⚠️ Advanced duplicate detection disabled in config")
            unique_articles = processed_articles
            duplicate_info = []

        # Apply intelligent selection with regional balance (on unique articles only)
        selected = self._intelligent_article_selection(unique_articles)
        
        # 📈 Advanced Story Tracking & Analysis
        print(f"📈 Analyzing story evolution and coverage patterns...")
        
        # Track story evolution vs duplicates
        evolution_report = self._analyze_story_evolution(selected)
        
        # Analyze coverage gaps
        coverage_analysis = self.coverage_analyzer.analyze_daily_coverage(selected)
        
        # Build event timelines
        timeline_updates = self._build_event_timelines(selected)
        
        # Create comprehensive analysis report
        self._create_advanced_analysis_report(evolution_report, coverage_analysis, timeline_updates)
        
        print(f"✅ Selected {len(selected)} unique articles after duplicate filtering")
        return selected[:self.config.max_articles_per_day]

    def _create_duplicate_report(self, duplicate_info: List[Dict]):
        """Create a report of detected duplicates for analysis"""
        try:
            report_file = self.config.vault_path / "duplicate_detection_log.md"
            
            with open(report_file, 'a', encoding='utf-8') as f:
                f.write(f"\n## Duplicate Detection Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
                
                for dup in duplicate_info:
                    f.write(f"### 🚫 Filtered Duplicate\n")
                    f.write(f"- **Title**: {dup['article_title']}\n")
                    f.write(f"- **URL**: {dup['article_url']}\n")
                    f.write(f"- **Detection Method**: {dup['detection_method']}\n")
                    f.write(f"- **Confidence**: {dup['confidence']:.2f}\n")
                    f.write(f"- **Original Date**: {dup['duplicate_date']}\n")
                    f.write(f"- **Reason**: {dup['reason']}\n\n")
                
                f.write("---\n\n")
                
        except Exception as e:
            print(f"⚠️ Could not create duplicate report: {e}")

    def _calculate_article_quality(self, article: NewsArticle) -> float:
        """Multi-factor quality scoring with normalization"""
        factors = {
            'recency': self._score_recency(article.published_at),
            'source_credibility': self._score_source_credibility(article.source),
            'content_length': self._score_content_length(article),
            'entity_richness': self._score_entity_richness(article.entities),
            'sentiment_balance': self._score_sentiment_balance(article.sentiment) if hasattr(article, 'sentiment') and article.sentiment else 0.5
        }

        # Weighted combination with normalization
        weights = {
            'recency': 0.25,
            'source_credibility': 0.30,
            'content_length': 0.15,
            'entity_richness': 0.20,
            'sentiment_balance': 0.10
        }

        # Calculate weighted score
        quality_score = sum(score * weights[factor] for factor, score in factors.items())

        # Apply promotional content penalty
        if self._is_promotional_content(article):
            quality_score *= 0.1  # Heavy penalty but not complete disqualification

        return quality_score

    def _score_recency(self, published_at: datetime) -> float:
        """Score article recency (0-1 scale, higher is better)"""
        days_old = (datetime.now() - published_at).days

        if days_old == 0:
            return 1.0  # Today
        elif days_old == 1:
            return 0.8  # Yesterday
        elif days_old <= 3:
            return 0.6  # 2-3 days old
        elif days_old <= 7:
            return 0.3  # 4-7 days old
        else:
            return 0.0  # Too old

    def _score_source_credibility(self, source: str) -> float:
        """Score source credibility (0-1 scale, higher is better)"""
        source_lower = source.lower()

        # Premium sources
        if any(premium in source_lower for premium in ['reuters', 'bbc', 'ap', 'npr']):
            return 0.95

        # Major newspapers
        if any(major in source_lower for major in ['nytimes', 'washingtonpost', 'theguardian']):
            return 0.85

        # Regional quality sources
        if any(regional in source_lower for regional in ['straitstimes', 'scmp', 'dw', 'france24']):
            return 0.75

        # Default for unknown sources
        return 0.5

    def _score_content_length(self, article: NewsArticle) -> float:
        """Score content length (0-1 scale, higher is better)"""
        # Check title length
        title_words = len(article.title.split())
        if title_words < 5:
            return 0.3  # Too short
        elif title_words > 20:
            return 0.7  # Good length
        else:
            return 0.9  # Optimal length

    def _score_entity_richness(self, entities) -> float:
        """Score entity richness (0-1 scale, higher is better)"""
        if not entities:
            return 0.0

        entity_count = len(entities)
        if entity_count >= 5:
            return 1.0  # Rich in entities
        elif entity_count >= 3:
            return 0.7  # Good entity coverage
        elif entity_count >= 1:
            return 0.4  # Some entities
        else:
            return 0.1  # Very few entities

    def _score_sentiment_balance(self, sentiment) -> float:
        """Score sentiment balance (0-1 scale, higher is better)"""
        # Handle different sentiment formats
        if isinstance(sentiment, dict):
            # If sentiment is a dict, extract the compound score or average
            if 'compound' in sentiment:
                sentiment_value = sentiment['compound']
            else:
                # Calculate average of available sentiment scores
                scores = [v for v in sentiment.values() if isinstance(v, (int, float))]
                sentiment_value = sum(scores) / len(scores) if scores else 0.0
        elif isinstance(sentiment, (int, float)):
            sentiment_value = float(sentiment)
        else:
            return 0.5  # Default neutral

        # Prefer neutral to slightly positive sentiment for news
        if -0.1 <= sentiment_value <= 0.3:
            return 1.0  # Balanced/neutral
        elif -0.3 <= sentiment_value <= 0.5:
            return 0.7  # Slightly biased but acceptable
        else:
            return 0.3  # Too biased

    def _is_promotional_content(self, article: NewsArticle) -> bool:
        """Check if article appears to be promotional content"""
        text_to_check = f"{article.title} {article.description}".lower()

        promotional_indicators = [
            'review', 'pricing', 'features', 'marketing tools', 'ai studio',
            'sponsored', 'promo', 'deal', 'discount', 'offer', 'sale',
            'top 10', 'top 11', 'best tools', 'complete guide', 'ultimate guide',
            'everything you need to know', 'how to make money', 'affiliate',
            'buy now', 'subscribe', 'download free', 'limited time'
        ]

        return any(indicator in text_to_check for indicator in promotional_indicators)
    
    def _intelligent_article_selection(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """Select articles with regional balance and quality scoring"""
        # Group by region
        region_buckets = {region: [] for region in self.config.regional_quotas}
        other_articles = []
        
        for article in articles:
            if article.region in region_buckets:
                region_buckets[article.region].append(article)
            else:
                other_articles.append(article)
        
        selected = []
        
        # For each region, select highest quality articles
        for region, quota in self.config.regional_quotas.items():
            region_articles = region_buckets[region]
            if region_articles:
                # Sort by quality score if we have it, otherwise use original order
                try:
                    region_articles.sort(key=lambda x: self._calculate_article_quality(x), reverse=True)
                except:
                    pass
                selected.extend(region_articles[:quota])
        
        # Fill remaining slots with best quality articles regardless of region
        remaining_slots = self.config.max_articles_per_day - len(selected)
        if remaining_slots > 0:
            remaining = [a for a in articles if a not in selected]
            # Sort by quality
            try:
                remaining.sort(key=lambda x: self._calculate_article_quality(x), reverse=True)
            except:
                pass
            selected.extend(remaining[:remaining_slots])
        
        return selected

    def _deduplicate_articles(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """Remove duplicate articles based on title similarity"""
        unique_articles = []
        seen_titles = set()
        
        for article in articles:
            # Create a normalized title for comparison
            normalized = re.sub(r'[^\w\s]', '', article.title.lower())
            normalized = ' '.join(normalized.split())
            
            if normalized not in seen_titles:
                seen_titles.add(normalized)
                unique_articles.append(article)
        
        return unique_articles
    
    def load_existing_stories(self) -> Dict[str, Set[str]]:
        """Load entities from existing story files"""
        story_entities = {}
        
        if not self.config.stories_path.exists():
            return story_entities
        
        for story_file in self.config.stories_path.glob("*.md"):
            try:
                with open(story_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Extract entities from YAML frontmatter or content
                entities = set()
                
                # Look for YAML frontmatter
                if content.startswith('---'):
                    try:
                        yaml_end = content.find('---', 3)
                        if yaml_end > 0:
                            yaml_content = content[3:yaml_end]
                            yaml_data = yaml.safe_load(yaml_content)
                            if yaml_data and 'entities' in yaml_data:
                                entities.update(yaml_data['entities'])
                    except:
                        pass
                
                # Also extract from **Entities:** section
                entity_match = re.search(r'\*\*Entities:\*\*\s*(.+)', content)
                if entity_match:
                    entity_text = entity_match.group(1)
                    # Extract hashtags
                    hashtags = re.findall(r'#(\w+)', entity_text)
                    entities.update(hashtags)
                
                story_entities[story_file.stem] = entities
                
            except Exception as e:
                print(f"Error reading {story_file}: {e}")
        
        return story_entities
    
    def find_related_stories(self, article: NewsArticle, existing_stories: Dict[str, Set[str]]) -> List[str]:
        """Find related stories based on entity overlap and cross-day story continuations"""
        related = []
        
        for story_slug, story_entities in existing_stories.items():
            # Calculate entity overlap
            overlap = article.entities.intersection(story_entities)
            if len(overlap) >= self.config.min_entity_overlap:
                related.append(story_slug)
        
        # Find cross-day story continuations
        cross_day_related = self._find_cross_day_continuations(article)
        related.extend(cross_day_related)
        
        return list(set(related))  # Remove duplicates
    
    def _find_cross_day_continuations(self, article: NewsArticle) -> List[str]:
        """Find stories from previous days that this article continues"""
        continuations = []
        
        # Look back up to 7 days for related stories
        for days_back in range(1, 8):
            past_date = article.published_at - timedelta(days=days_back)
            past_date_str = past_date.strftime("%d %m %Y")
            past_stories_dir = self.config.stories_path / past_date_str
            
            if not past_stories_dir.exists():
                continue
                
            for story_file in past_stories_dir.glob("*.md"):
                try:
                    with open(story_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Extract entities from past story
                    past_entities = set()
                    entity_match = re.search(r'\*\*Entities:\*\*\s*(.+)', content)
                    if entity_match:
                        past_entities = {entity.strip() for entity in entity_match.group(1).split(',')}
                    
                    # Check for significant entity overlap
                    overlap = article.entities.intersection(past_entities)
                    if len(overlap) >= 2:  # Higher threshold for cross-day links
                        # Check if this is likely a continuation (similar keywords)
                        similarity_score = self._calculate_story_similarity(article, content)
                        if similarity_score > 0.3:  # 30% similarity threshold
                            relative_path = f"{past_date_str}/{story_file.stem}"
                            continuations.append(relative_path)
                            
                except Exception as e:
                    continue
        
        return continuations[:3]  # Limit to top 3 continuations
    
    def _calculate_story_similarity(self, article: NewsArticle, past_story_content: str) -> float:
        """Calculate similarity between current article and past story"""
        # Extract key terms from current article
        current_text = f"{article.title} {article.description}".lower()
        current_words = set(re.findall(r'\b\w{4,}\b', current_text))
        
        # Extract key terms from past story
        past_text = past_story_content.lower()
        past_words = set(re.findall(r'\b\w{4,}\b', past_text))
        
        # Calculate Jaccard similarity
        intersection = current_words.intersection(past_words)
        union = current_words.union(past_words)
        
        return len(intersection) / len(union) if union else 0.0
    
    def create_story_note(self, article: NewsArticle, related_stories: List[str]) -> str:
        """Create enhanced markdown content for a story note"""
        date_str = article.format_date("dd_mm_yyyy")
        
        # Get varying degree sentiment emoji
        sentiment_emoji = article.get_sentiment_emoji()
        
        # Create entity and topic hashtags
        entity_tags = ' '.join([f'#{entity.replace(" ", "")}' for entity in sorted(article.entities)])
        topic_tags = ' '.join([f'#{topic}' for topic in sorted(article.topics)])
        
        # Generate AI summary if available
        ai_summary = ""
        has_ai_summary = False
        if self.config.enable_auto_summarization and self.summarizer and article.full_text:
            try:
                summary_result = self.summarizer(article.full_text[:NewsConfig.SUMMARIZATION_MAX_CHARS])
                ai_summary = f"\n## 🤖 AI Summary\n{summary_result[0]['summary_text']}\n"
                has_ai_summary = True
            except:
                pass

        content = f"""# {sentiment_emoji} {article.title}

## 📊 Article Details

| **Attribute** | **Value** |
|---------------|-----------|
| **Date** | {article.published_at.strftime("%d %m %Y")} |
| **Source** | [{article.source}]({article.url}) |
| **Region** | {article.region} |
| **Sentiment** | {sentiment_emoji} {article.sentiment['compound']:.2f} (Pos: {article.sentiment['positive']:.2f}, Neg: {article.sentiment['negative']:.2f}) |
| **Readability** | {article.readability_score:.1f}/100 |
| **Entities** | {', '.join(sorted(article.entities)) if article.entities else 'None'} |
| **Topics** | {', '.join(sorted(article.topics)) if article.topics else 'None'} |
| **Hash** | `{article.hash}` |

**Tags:** {entity_tags} {topic_tags}"""

        # Only add basic summary if there's no AI summary
        if not has_ai_summary:
            content += f"""

## Summary
{article.description}"""

        # Add AI summary if available
        content += ai_summary

        content += f"""

## 📄 Full Article
{article.full_text if article.full_text else '*Full text extraction failed - showing preview only:*' + chr(10) + chr(10) + article.content[:1000] + '...'}

### 🔗 Related Stories
"""
        
        # Add related story links
        if related_stories:
            for story_slug in related_stories:
                content += f"- [[{story_slug}]]\n"
        else:
            content += "*No related stories found.*\n"
        
        return content
    
    def update_related_story_links(self, new_story_slug: str, related_stories: List[str]):
        """Add bidirectional links to related stories"""
        for related_slug in related_stories:
            story_file = self.config.stories_path / f"{related_slug}.md"
            
            if not story_file.exists():
                continue
            
            try:
                with open(story_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check if the new story is already linked
                if f"[[{new_story_slug}]]" in content:
                    continue
                
                # Find the Related Stories section and add the link
                if "### Related Stories" in content:
                    # Insert before the end of the Related Stories section
                    pattern = r"(### Related Stories\n)(.*?)(\n### |\n$|$)"
                    match = re.search(pattern, content, re.DOTALL)
                    
                    if match:
                        before = match.group(1)
                        existing_links = match.group(2).strip()
                        after = match.group(3) if match.group(3) else ""
                        
                        # Remove "No related stories found" if present
                        existing_links = re.sub(r'\*No related stories found\.\*\n?', '', existing_links)
                        
                        # Add the new link
                        if existing_links:
                            new_links = f"{existing_links}\n- [[{new_story_slug}]]"
                        else:
                            new_links = f"- [[{new_story_slug}]]"
                        
                        new_content = content.replace(
                            match.group(0),
                            f"{before}{new_links}{after}"
                        )
                        
                        with open(story_file, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                
            except Exception as e:
                print(f"Error updating related links in {story_file}: {e}")
    
    def create_daily_note(self, date: datetime, articles: List[NewsArticle]) -> str:
        """Create markdown content for daily note"""
        date_str = date.strftime("%Y-%m-%d")
        
        # Calculate previous and next day
        prev_day = (date - timedelta(days=1)).strftime("%d-%m-%Y")
        next_day = (date + timedelta(days=1)).strftime("%d-%m-%Y")
        
        content = f"""# 🌍 World News - {date_str}

[[{prev_day}|← Previous Day]] | [[{next_day}|Next Day →]]

## Headlines ({len(articles)} stories)

"""
        
        # Add article links
        for article in articles:
            content += f"- [[{article.slug}|{article.title}]]\n"
        
        content += f"""

---
*Generated on {datetime.now().strftime("%d-%m-%Y %H:%M")}*
"""
        
        return content
    
    def create_entity_profiles(self, articles: List[NewsArticle]):
        """Create/update entity profile notes"""
        entity_mentions = defaultdict(list)
        
        # Collect all entity mentions
        for article in articles:
            for entity in article.entities:
                entity_mentions[entity].append(article)
        
        # Create entity profile notes for frequently mentioned entities
        for entity, entity_articles in entity_mentions.items():
            if len(entity_articles) >= 2:  # Only create profiles for entities with 2+ mentions
                self._create_entity_profile(entity, entity_articles)
    
    def _create_entity_profile(self, entity: str, articles: List[NewsArticle]):
        """Create an entity profile note"""
        entity_slug = slugify(entity, max_length=50)
        entity_file = self.config.entities_path / f"{entity_slug}.md"
        
        # Ensure the entity directory exists
        entity_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Read existing content if file exists
        existing_articles = set()
        if entity_file.exists():
            try:
                with open(entity_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Extract existing article links
                    existing_links = re.findall(r'\[\[([^\]]+)\]\]', content)
                    existing_articles.update(existing_links)
            except:
                pass
        
        # Add new articles
        all_article_links = []
        for article in articles:
            if article.slug not in existing_articles:
                all_article_links.append(f"- [[{article.slug}|{article.title}]] ({article.published_at.strftime('%d-%m-%Y')})")

        if all_article_links:
            # Create/update entity profile
            content = f"""# {entity}

**Entity Type:** {self._get_entity_type(entity)}  
**First Mentioned:** {min(articles, key=lambda x: x.published_at).published_at.strftime('%d-%m-%Y')}  
**Total Mentions:** {len(articles)}  

## Recent Stories
{chr(10).join(all_article_links)}

---
*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
            
            with open(entity_file, 'w', encoding='utf-8') as f:
                f.write(content)
    
    def _get_entity_type(self, entity: str) -> str:
        """Determine entity type using spaCy"""
        if self.nlp:
            doc = self.nlp(entity)
            if doc.ents:
                return doc.ents[0].label_
        return "MISC"
    
    def create_topic_timelines(self, articles: List[NewsArticle]):
        """Create timeline notes for major topics"""
        topic_articles = defaultdict(list)
        
        # Group articles by topics
        for article in articles:
            for topic in article.topics:
                topic_articles[topic].append(article)
        
        # Create timeline for topics with multiple articles
        for topic, topic_articles_list in topic_articles.items():
            if len(topic_articles_list) >= 2:
                self._create_topic_timeline(topic, topic_articles_list)
    
    def _create_topic_timeline(self, topic: str, articles: List[NewsArticle]):
        """Create a timeline note for a topic with dynamic stats"""
        topic_file = self.config.timelines_path / f"{topic}-timeline.md"
        
        # Sort articles by date - normalize timezone info
        for article in articles:
            if article.published_at.tzinfo is not None:
                article.published_at = article.published_at.replace(tzinfo=None)
        
        articles.sort(key=lambda x: x.published_at)
        
        # Calculate topic statistics
        total_articles = len(articles)
        sentiment_breakdown = {
            'positive': sum(1 for a in articles if a.sentiment['compound'] > 0.1),
            'negative': sum(1 for a in articles if a.sentiment['compound'] < -0.1),
            'neutral': sum(1 for a in articles if abs(a.sentiment['compound']) <= 0.1)
        }
        
        # Get source diversity
        sources = list(set(article.source for article in articles))
        
        # Generate dynamic progress bars
        def create_progress_bar(value: int, total: int, width: int = 20) -> str:
            if total == 0:
                return "░" * width
            filled = int((value / total) * width)
            return "█" * filled + "░" * (width - filled)
        
        # Calculate sentiment percentages
        pos_pct = (sentiment_breakdown['positive'] / total_articles * 100) if total_articles > 0 else 0
        neg_pct = (sentiment_breakdown['negative'] / total_articles * 100) if total_articles > 0 else 0
        neu_pct = (sentiment_breakdown['neutral'] / total_articles * 100) if total_articles > 0 else 0
        
        content = f"""# {topic.title()} Timeline

## 📊 Topic Statistics

### Article Overview
- **Total Articles**: {total_articles}
- **Sources**: {len(sources)}
- **Date Range**: {articles[0].published_at.strftime('%d %b %Y')} - {articles[-1].published_at.strftime('%d %b %Y')}

### Sentiment Analysis
- **Positive** ({pos_pct:.1f}%): {create_progress_bar(sentiment_breakdown['positive'], total_articles)} ({sentiment_breakdown['positive']})
- **Negative** ({neg_pct:.1f}%): {create_progress_bar(sentiment_breakdown['negative'], total_articles)} ({sentiment_breakdown['negative']})
- **Neutral** ({neu_pct:.1f}%): {create_progress_bar(sentiment_breakdown['neutral'], total_articles)} ({sentiment_breakdown['neutral']})

### Source Diversity
"""
        
        # Add source breakdown
        source_counts = Counter(article.source for article in articles)
        for source, count in source_counts.most_common(5):
            pct = (count / total_articles * 100)
            content += f"- **{source}** ({pct:.1f}%): {create_progress_bar(count, total_articles)} ({count})\n"
        
        content += f"""

## Recent Developments

"""
        
        for article in articles:
            date_str = article.published_at.strftime('%d-%m-%Y')
            sentiment_icon = "📈" if article.sentiment['compound'] > 0.1 else "📉" if article.sentiment['compound'] < -0.1 else "📊"
            content += f"- **{date_str}** {sentiment_icon}: [[{article.slug}|{article.title}]] *({article.source})*\n"
        
        content += f"""

---
*Timeline updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
*Next update: Track this topic for ongoing developments*
"""
        
        with open(topic_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Also create a topic analysis file in the topics folder
        self._create_topic_analysis_file(topic, articles)
    
    def _create_topic_analysis_file(self, topic: str, articles: List[NewsArticle]):
        """Create detailed topic analysis in topics folder"""
        self.config.topics_path.mkdir(parents=True, exist_ok=True)
        topic_analysis_file = self.config.topics_path / f"{topic}.md"
        
        # Advanced topic analysis
        entity_mentions = Counter()
        key_phrases = []
        
        for article in articles:
            entity_mentions.update(article.entities)
            # Extract key phrases from titles
            words = article.title.lower().split()
            for i in range(len(words) - 1):
                if len(words[i]) > 3 and len(words[i+1]) > 3:
                    key_phrases.append(f"{words[i]} {words[i+1]}")
        
        phrase_counts = Counter(key_phrases)
        
        content = f"""# {topic.title()} - Detailed Analysis

## 📋 Topic Overview
- **Tracking since**: {articles[0].published_at.strftime('%d %B %Y')}
- **Total coverage**: {len(articles)} articles
- **Latest update**: {articles[-1].published_at.strftime('%d %B %Y')}

## 🎯 Key Entities
"""
        
        for entity, count in entity_mentions.most_common(10):
            content += f"- **{entity}**: {count} mentions\n"
        
        content += f"""

## 🔍 Key Phrases
"""
        
        for phrase, count in phrase_counts.most_common(10):
            if count > 1:  # Only show phrases mentioned more than once
                content += f"- **{phrase}**: {count} occurrences\n"
        
        content += f"""

## 📰 Recent Headlines
"""
        
        # Show last 10 headlines
        recent_articles = sorted(articles, key=lambda x: x.published_at, reverse=True)[:10]
        for article in recent_articles:
            date_str = article.published_at.strftime('%d %b')
            content += f"- **{date_str}**: {article.title} *({article.source})*\n"
        
        content += f"""

## 📊 Coverage Trends
- **Peak activity**: {max(Counter(a.published_at.date() for a in articles).values())} articles in one day
- **Source diversity**: {len(set(a.source for a in articles))} different sources
- **Geographic spread**: {len(set(a.region for a in articles if a.region))} regions

## 🔗 Related
- [[{topic}-timeline|{topic.title()} Timeline]]
- [[Topics MOC|All Topics]]

---
*Analysis generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
        
        with open(topic_analysis_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def _create_topic_analysis(self, articles: List[NewsArticle]):
        """Create comprehensive topic analysis and MOC"""
        # Create topics directory
        self.config.topics_path.mkdir(parents=True, exist_ok=True)
        
        # Group articles by topic
        topic_articles = defaultdict(list)
        for article in articles:
            for topic in article.topics:
                topic_articles[topic].append(article)
        
        # Create individual topic analyses
        for topic, topic_articles_list in topic_articles.items():
            if len(topic_articles_list) >= 1:  # Create analysis for any topic with articles
                self._create_topic_analysis_file(topic, topic_articles_list)
        
        # Create Topics MOC (Map of Content)
        self._create_topics_moc(topic_articles)
    
    def _create_topics_moc(self, topic_articles: dict):
        """Create a Map of Content for all topics"""
        moc_file = self.config.topics_path / "Topics MOC.md"
        
        content = f"""# Topics - Map of Content

*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*

## 📊 Active Topics ({len(topic_articles)} topics tracked)

"""
        
        # Sort topics by article count
        sorted_topics = sorted(topic_articles.items(), key=lambda x: len(x[1]), reverse=True)
        
        for topic, articles in sorted_topics:
            article_count = len(articles)
            latest_date = max(a.published_at for a in articles).strftime('%d %b')
            
            # Create visual indicator for activity level
            if article_count >= 10:
                activity = "🔥🔥🔥"  # High activity
            elif article_count >= 5:
                activity = "🔥🔥"    # Medium activity  
            elif article_count >= 2:
                activity = "🔥"      # Low activity
            else:
                activity = "📄"      # Single article
            
            content += f"- {activity} **[[{topic}|{topic.title()}]]** - {article_count} articles (latest: {latest_date})\n"
        
        content += f"""

## 🎯 Topic Categories

### 🏛️ Politics & Government
"""
        political_topics = [t for t in sorted_topics if any(word in t[0].lower() for word in ['politic', 'government', 'election', 'policy', 'congress', 'senate'])]
        for topic, articles in political_topics[:5]:
            content += f"- [[{topic[0]}|{topic[0].title()}]] ({len(articles)} articles)\n"
        
        content += f"""

### 💰 Economy & Business
"""
        economic_topics = [t for t in sorted_topics if any(word in t[0].lower() for word in ['economy', 'business', 'market', 'financial', 'trade', 'stock'])]
        for topic, articles in economic_topics[:5]:
            content += f"- [[{topic[0]}|{topic[0].title()}]] ({len(articles)} articles)\n"
        
        content += f"""

### 🌍 International Affairs
"""
        international_topics = [t for t in sorted_topics if any(word in t[0].lower() for word in ['international', 'china', 'russia', 'europe', 'war', 'conflict'])]
        for topic, articles in international_topics[:5]:
            content += f"- [[{topic[0]}|{topic[0].title()}]] ({len(articles)} articles)\n"
        
        content += f"""

### 💻 Technology & Science
"""
        tech_topics = [t for t in sorted_topics if any(word in t[0].lower() for word in ['technology', 'tech', 'ai', 'science', 'research', 'innovation'])]
        for topic, articles in tech_topics[:5]:
            content += f"- [[{topic[0]}|{topic[0].title()}]] ({len(articles)} articles)\n"
        
        content += f"""

## 📈 Recent Activity

### Today's New Topics
"""
        
        today = datetime.now().date()
        new_topics = [t for t, articles in sorted_topics if any(a.published_at.date() == today for a in articles)]
        
        if new_topics:
            for topic in new_topics[:10]:
                content += f"- [[{topic}|{topic.title()}]]\n"
        else:
            content += "- No new topics tracked today\n"
        
        content += f"""

## 🔗 Navigation
- [[Daily Notes]]
- [[Entity Profiles]]
- [[Event Timelines]]
- [[Timeline MOC]]

---
*Topics automatically tracked by the News Analysis System*
"""
        
        with open(moc_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def create_daily_summary(self, date: datetime, articles: List[NewsArticle]) -> str:
        """Create comprehensive daily dashboard with analytics"""
        date_str = date.strftime("%d %m %Y")
        
        # Calculate previous and next day
        prev_day = (date - timedelta(days=1)).strftime("%d %m %Y")
        next_day = (date + timedelta(days=1)).strftime("%d %m %Y")
        
        # Calculate statistics
        total_articles = len(articles)
        regional_stats = Counter(article.region for article in articles)
        sentiment_stats = {
            'positive': sum(1 for a in articles if a.sentiment['compound'] > 0.1),
            'negative': sum(1 for a in articles if a.sentiment['compound'] < -0.1),
            'neutral': sum(1 for a in articles if abs(a.sentiment['compound']) <= 0.1)
        }
        
        # Entity and topic analysis
        entity_mentions = Counter()
        topic_mentions = Counter()
        source_stats = Counter()
        
        for article in articles:
            entity_mentions.update(article.entities)
            topic_mentions.update(article.topics)
            source_stats[article.source] += 1
        
        content = f"""# 🌍 World News - {date_str}

[[{prev_day}|📊 Previous Dashboard]] | [[{next_day}|📊 Next Dashboard]]

## 📊 Daily Overview
- **Total Articles:** {total_articles}
- **Regional Coverage:** {', '.join([f"{region} ({count})" for region, count in regional_stats.most_common(3)])}
- **Sentiment:** 😊 {sentiment_stats['positive']} Positive | 😟 {sentiment_stats['negative']} Negative | 😐 {sentiment_stats['neutral']} Neutral

## 🔥 Top Stories by Sentiment

### 😊 Most Positive News
"""
        
        # Add top positive stories
        positive_stories = sorted([a for a in articles if a.sentiment['compound'] > 0.1], 
                                key=lambda x: x.sentiment['compound'], reverse=True)[:3]
        for story in positive_stories:
            content += f"- {story.get_sentiment_emoji()} [[{story.slug}|{story.title}]] *({story.sentiment['compound']:.2f})*\n"
        
        content += "\n### 😟 Most Concerning News\n"
        
        # Add top negative stories
        negative_stories = sorted([a for a in articles if a.sentiment['compound'] < -0.1], 
                                key=lambda x: x.sentiment['compound'])[:3]
        for story in negative_stories:
            content += f"- {story.get_sentiment_emoji()} [[{story.slug}|{story.title}]] *({story.sentiment['compound']:.2f})*\n"
        
        content += f"""

## 🌍 Regional Breakdown
"""
        
        for region, count in regional_stats.most_common():
            region_articles = [a for a in articles if a.region == region]
            avg_sentiment = sum(a.sentiment['compound'] for a in region_articles) / len(region_articles)
            sentiment_emoji = "😊" if avg_sentiment > 0.1 else "😟" if avg_sentiment < -0.1 else "😐"
            content += f"- **{region}** ({count} articles) {sentiment_emoji} *Avg sentiment: {avg_sentiment:.2f}*\n"
        
        # Add geographic event clustering
        regional_events = self.geo_cluster.identify_regional_events(articles)
        if regional_events:
            content += f"""

## 🗺️ Geographic Event Clusters

"""
            for location, events in regional_events.items():
                if sum(len(articles_list) for articles_list in events.values()) >= 2:  # Only show significant clusters
                    content += f"\n### {location.title()}\n"
                    for event_type, event_articles in events.items():
                        if len(event_articles) >= 2:
                            content += f"- **{event_type.replace('_', ' ').title()}** ({len(event_articles)} articles)\n"
                            for article in event_articles[:3]:  # Show top 3 articles
                                content += f"  - [[{article.slug}|{article.title[:60]}...]]\n"
                            if len(event_articles) > 3:
                                content += f"  - *+{len(event_articles) - 3} more articles*\n"
        
        content += f"""

## 🔗 Key Entities Today
"""
        
        for entity, count in entity_mentions.most_common(10):
            entity_slug = slugify(entity, max_length=50)
            content += f"- [[{entity_slug}|{entity}]] ({count} mentions)\n"
        
        # Add bias analysis
        source_bias = self.bias_analyzer.compare_source_bias(articles)
        if source_bias:
            content += f"""

## ⚖️ Source Bias Analysis

"""
            for source, metrics in sorted(source_bias.items(), key=lambda x: x[1]['average_bias']):
                bias_emoji = "🟢" if metrics['bias_level'] == "Low" else "🟡" if metrics['bias_level'] == "Moderate" else "🟠" if metrics['bias_level'] == "High" else "🔴"
                content += f"- {bias_emoji} **{source}** - {metrics['bias_level']} bias ({metrics['article_count']} articles)\n"
        
        # Add personalized recommendations
        recommended = self.user_profile.get_recommended_articles(articles, limit=5)
        if recommended:
            content += f"""

## 🎯 Personalized Recommendations

"""
            for article in recommended:
                interest_score = self.user_profile.calculate_interest_score(article)
                content += f"- ⭐ [[{article.slug}|{article.title}]] *({interest_score:.2f} match)*\n"
        
        content += f"""

## 📰 All Stories

"""
        
        # Group stories by region for better organization
        for region in regional_stats.keys():
            region_articles = [a for a in articles if a.region == region]
            if region_articles:
                content += f"\n### {region} ({len(region_articles)} stories)\n"
                for article in sorted(region_articles, key=lambda x: x.sentiment['compound'], reverse=True):
                    content += f"- {article.get_sentiment_emoji()} [[{article.slug}|{article.title}]] *({article.source})*\n"
        
        content += f"""

---
*Dashboard generated on {datetime.now().strftime('%d %m %Y at %H:%M')} with {total_articles} articles*
"""
        
        return content
    
    def create_event_timelines(self, articles: List[NewsArticle]):
        """Create comprehensive event timeline notes"""
        event_articles = self.event_tracker.detect_events(articles)
        
        for event_id, event_articles_list in event_articles.items():
            if event_articles_list:
                event = self.event_tracker.ongoing_events[event_id]
                self._create_event_timeline(event, event_articles_list)
    
    def _create_event_timeline(self, event: OngoingEvent, articles: List[NewsArticle]):
        """Create a comprehensive timeline for an ongoing event"""
        event_slug = slugify(event.name, max_length=50)
        timeline_file = self.config.timelines_path / f"{event_slug}-timeline.md"
        
        # Sort articles by date - normalize timezone info
        for article in articles:
            if article.published_at.tzinfo is not None:
                article.published_at = article.published_at.replace(tzinfo=None)
        
        articles.sort(key=lambda x: x.published_at)
        
        # Calculate event statistics
        total_articles = event.total_articles
        days_active = (datetime.now() - event.start_date).days
        avg_articles_per_day = total_articles / max(days_active, 1)
        
        content = f"""# {event.name} Timeline

> **Event ID:** {event_slug}  
> **Started:** {event.start_date.strftime('%d-%m-%Y')}  
> **Days Active:** {days_active}  
> **Total Articles:** {total_articles}  
> **Avg Articles/Day:** {avg_articles_per_day:.1f}  
> **Importance Score:** {event.importance_score:.1f}/10  

## Key Entities
{' '.join([f'#{entity.replace(" ", "")}' for entity in event.entities])}

## Keywords
`{', '.join(event.keywords)}`

## Recent Developments

"""
        
        # Group articles by date
        articles_by_date = defaultdict(list)
        for article in articles:
            date_key = article.published_at.strftime('%d-%m-%Y')
            articles_by_date[date_key].append(article)
        
        for date_str in sorted(articles_by_date.keys(), reverse=True):
            date_articles = articles_by_date[date_str]
            content += f"\n### {date_str} ({len(date_articles)} articles)\n"
            
            for article in date_articles:
                content += f"- {article.get_sentiment_emoji()} [[{article.slug}|{article.title}]] *({article.source})*\n"
        
        content += f"""

## Dataview Queries

```dataview
TABLE 
  file.link as "Article",
  date as "Date",
  source as "Source",
  sentiment.compound as "Sentiment"
FROM "stories"
WHERE contains(entities, "{list(event.entities)[0] if event.entities else 'Event'}")
SORT date DESC
```

---
*Timeline updated: {datetime.now().strftime('%d-%m-%Y %H:%M')} | Event tracking active since {event.start_date.strftime('%d-%m-%Y')}*
"""
        
        with open(timeline_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def create_enhanced_entity_profiles(self, articles: List[NewsArticle]):
        """Create comprehensive entity profiles with context and relationships"""
        entity_mentions = defaultdict(list)
        entity_contexts = defaultdict(list)
        entity_relationships = defaultdict(set)
        
        # Collect entity data
        for article in articles:
            for entity in article.entities:
                entity_mentions[entity].append(article)
                
                # Extract context around entity mentions
                full_text = f"{article.title}. {article.description}. {article.full_text}"
                for match in re.finditer(re.escape(entity), full_text, re.IGNORECASE):
                    start = max(0, match.start() - 100)
                    end = min(len(full_text), match.end() + 100)
                    context = full_text[start:end].strip()
                    entity_contexts[entity].append(context)
                
                # Find related entities (entities that appear in same articles)
                for other_entity in article.entities:
                    if other_entity != entity:
                        entity_relationships[entity].add(other_entity)
        
        # Create profiles for significant entities
        for entity, entity_articles in entity_mentions.items():
            if len(entity_articles) >= 2:  # Only create profiles for entities with 2+ mentions
                self._create_enhanced_entity_profile(entity, entity_articles, 
                                                   entity_contexts[entity], 
                                                   entity_relationships[entity])
    
    def _create_enhanced_entity_profile(self, entity: str, articles: List[NewsArticle], 
                                      contexts: List[str], relationships: Set[str]):
        """Create an enhanced entity profile with relationships and context"""
        entity_slug = slugify(entity, max_length=50)
        entity_file = self.config.entities_path / f"{entity_slug}.md"
        
        # Ensure the entity directory exists
        entity_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Sort articles by date - normalize timezone info
        for article in articles:
            if article.published_at.tzinfo is not None:
                article.published_at = article.published_at.replace(tzinfo=None)
        
        articles.sort(key=lambda x: x.published_at, reverse=True)
        
        # Calculate entity statistics
        first_mention = min(articles, key=lambda x: x.published_at).published_at
        last_mention = max(articles, key=lambda x: x.published_at).published_at
        mention_span = (last_mention - first_mention).days
        
        # Analyze sentiment trends
        sentiments = [article.sentiment['compound'] for article in articles]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0
        
        # Get entity type
        entity_type = self._get_entity_type(entity)
        
        content = f"""# {entity}

> **Type:** {entity_type}  
> **First Mentioned:** {first_mention.strftime('%d-%m-%Y')}  
> **Last Mentioned:** {last_mention.strftime('%d-%m-%Y')}  
> **Mention Span:** {mention_span} days  
> **Total Mentions:** {len(articles)}  
> **Average Sentiment:** {avg_sentiment:.2f} {"😊" if avg_sentiment > 0.1 else "😟" if avg_sentiment < -0.1 else "😐"}  

## Related Entities
{' '.join([f'[[{slugify(rel, max_length=50)}|{rel}]]' for rel in sorted(relationships)]) if relationships else '*No related entities found*'}

## Recent Context Snippets
"""
        
        # Add recent context snippets
        for context in contexts[:3]:  # Show top 3 contexts
            content += f"\n> *...{context}...*\n"
        
        content += f"""

## Recent Stories ({len(articles)} total)

"""
        
        # Add recent stories
        for article in articles[:10]:  # Show recent 10 stories
            date_str = article.published_at.strftime(('%d-%m-%Y'))
            content += f"- **{article.format_date('dd-mm-yyyy')}**: {article.get_sentiment_emoji()} [[{article.slug}|{article.title}]] *({article.source})*\n"
        
        if len(articles) > 10:
            content += f"\n*... and {len(articles) - 10} more stories*\n"
        
        content += f"""

## Dataview Timeline

```dataview
TABLE 
  file.link as "Article",
  date as "Date",
  region as "Region",
  sentiment.compound as "Sentiment"
FROM "stories"
WHERE contains(entities, "{entity}")
SORT date DESC
```

## Mention Graph
---
*Profile updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(articles)} total mentions*
"""
        
        with open(entity_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def create_daily_dashboard(self, date: datetime, articles: List[NewsArticle]) -> str:
        """Create an interactive dashboard for daily overview"""
        date_str = date.strftime("%d %m %Y")
        dashboard_file = self.config.vault_path / f"dashboard-{date_str}.md"
        
        # Calculate comprehensive statistics
        total_articles = len(articles)
        regional_stats = Counter(article.region for article in articles)
        sentiment_stats = {
            'positive': sum(1 for a in articles if a.sentiment['compound'] > 0.1),
            'negative': sum(1 for a in articles if a.sentiment['compound'] < -0.1),
            'neutral': sum(1 for a in articles if abs(a.sentiment['compound']) <= 0.1)
        }
        
        entity_mentions = Counter()
        topic_mentions = Counter()
        source_stats = Counter()
        
        for article in articles:
            entity_mentions.update(article.entities)
            topic_mentions.update(article.topics)
            source_stats[article.source] += 1
        
        # Get top sources info first
        top_sources_info = ', '.join([f"{source} ({count})" for source, count in source_stats.most_common(3)])
        
        # Calculate previous and next day
        prev_day = (date - timedelta(days=1)).strftime("%d %m %Y")
        next_day = (date + timedelta(days=1)).strftime("%d %m %Y")
        
        # Create interactive dashboard
        content = f"""# 📊 News Dashboard - {date_str}

[[{prev_day}|← Previous Day]] | [[{next_day}|Next Day →]]

## Quick Stats
- 📰 **Total Articles:** {total_articles}
- 🌍 **Regions Covered:** {len(regional_stats)}
- 😊 **Positive Stories:** {sentiment_stats['positive']} ({sentiment_stats['positive']/total_articles*100:.1f}%)
- 😟 **Negative Stories:** {sentiment_stats['negative']} ({sentiment_stats['negative']/total_articles*100:.1f}%)
- 📊 **Top Sources:** {top_sources_info}

## Regional Coverage

```mermaid
pie title Regional Distribution
"""
        
        for region, count in regional_stats.items():
            content += f'    "{region}" : {count}\n'
        
        content += f"""```

## Sentiment Analysis

```mermaid
pie title Sentiment Distribution
    "Positive" : {sentiment_stats['positive']}
    "Negative" : {sentiment_stats['negative']}
    "Neutral" : {sentiment_stats['neutral']}
```

## Top Entities Today

| Entity | Mentions | Type |
|--------|----------|------|
"""
        
        for entity, count in entity_mentions.most_common(10):
            entity_type = self._get_entity_type(entity)
            content += f"| [[{slugify(entity, max_length=50)}\\|{entity}]] | {count} | {entity_type} |\n"
        
        content += f"""

## Active Topics

"""
        
        for topic, count in topic_mentions.most_common(8):
            content += f"- **#{topic}** ({count} articles)\n"
        
        content += f"""

## Today's Timeline

"""
        
        # Create hourly timeline
        articles_by_hour = defaultdict(list)
        for article in articles:
            hour = article.published_at.hour
            articles_by_hour[hour].append(article)
        
        for hour in sorted(articles_by_hour.keys()):
            hour_articles = articles_by_hour[hour]
            content += f"\n### {hour:02d}:00 ({len(hour_articles)} articles)\n"
            for article in hour_articles[:3]:  # Show top 3 per hour
                content += f"- {article.get_sentiment_emoji()} [[{article.slug}|{article.title}]]\n"
        
        content += f"""


---
*Dashboard generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} with {total_articles} articles*
"""
        
        with open(dashboard_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return str(dashboard_file)
    
    def run_daily_scrape(self, target_date: Optional[datetime] = None) -> bool:
        """Run the enhanced daily news scraping process"""
        if target_date is None:
            target_date = datetime.now()
        
        date_str = target_date.strftime("%d %m %Y")
        print(f"🚀 Starting enhanced daily news scrape for {date_str}")
        
        # Check if daily note already exists
        daily_note_path = self.config.vault_path / f"{date_str}.md"
        if daily_note_path.exists():
            print(f"Daily note for {date_str} already exists. Skipping...")
            return False
        
        # Fetch and process articles
        articles = self._fetch_and_validate_articles()
        if not articles:
            return False
        
        # Process articles with AI features
        processed_articles = self._process_articles_with_ai(articles)
        if not processed_articles:
            print("❌ No articles processed successfully!")
            return False
        
        # Create all output files
        self._create_daily_outputs(target_date, processed_articles, daily_note_path)
        
        return True
    
    def _fetch_and_validate_articles(self) -> List[NewsArticle]:
        """Fetch articles and validate we have content"""
        print("📰 Fetching and analyzing news articles...")
        articles = self.fetch_news()
        
        if not articles:
            print("❌ No articles found!")
            return []
        
        print(f"🔍 Processing {len(articles)} articles with advanced features...")
        return articles
    
    def _process_articles_with_ai(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """Process articles with AI features and create story notes"""
        existing_stories = self.load_existing_stories()
        processed_articles = []
        
        for i, article in enumerate(articles):
            try:
                print(f"  📝 Processing article {i+1}/{len(articles)}: {article.title[:50]}...")
                
                # Find related stories and create story note
                related_stories = self.find_related_stories(article, existing_stories)
                story_content = self.create_story_note(article, related_stories)
                
                # Save story file with proper directory structure
                self._save_story_file(article, story_content)
                
                # Update bidirectional links and tracking
                self.update_related_story_links(article.slug, related_stories)
                existing_stories[article.slug] = article.entities
                processed_articles.append(article)
                
            except Exception as e:
                print(f"❌ Error processing article '{article.title}': {e}")
                continue
        
        return processed_articles
    
    def _save_story_file(self, article: NewsArticle, content: str):
        """Save story file with proper directory structure"""
        story_path = self.config.stories_path / f"{article.slug}.md"
        story_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(story_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def _create_daily_outputs(self, target_date: datetime, processed_articles: List[NewsArticle], daily_note_path: Path):
        """Create all daily output files"""
        # Create enhanced daily note with AI insights
        print("📊 Creating daily summary with AI insights...")
        daily_content = self.create_daily_summary(target_date, processed_articles)
        
        with open(daily_note_path, 'w', encoding='utf-8') as f:
            f.write(daily_content)
        
        # Create enhanced entity profiles with relationships
        print("👤 Creating/updating enhanced entity profiles...")
        self.create_enhanced_entity_profiles(processed_articles)
        
        # Create event timelines
        print("📅 Creating/updating event timelines...")
        self.create_event_timelines(processed_articles)
        
        # Create topic timelines  
        print("📈 Creating/updating topic timelines...")
        self.create_topic_timelines(processed_articles)
        
        # Create comprehensive topic analysis
        print("📊 Creating/updating topic analysis...")
        self._create_topic_analysis(processed_articles)
        
        # Daily outputs complete
        
        print(f"📄 Daily note: {daily_note_path}")
        print(f"🔗 Entity profiles: {self.config.entities_path}")
        print(f"🕐 Event timelines: {self.config.timelines_path}")
        print(f"📈 Topic timelines: {self.config.timelines_path}")
        print(f"📊 Topic analysis: {self.config.topics_path}")
        
        return True

    def _analyze_story_evolution(self, articles: List[NewsArticle]) -> Dict[str, Any]:
        """Analyze how stories are evolving vs being duplicated"""
        evolution_summary = {
            'new_stories': 0,
            'evolving_stories': 0,
            'duplicate_stories': 0,
            'story_threads': [],
            'evolution_analysis': []
        }
        
        existing_articles = []  # Would load from previous days in production
        
        for article in articles:
            # Analyze relationship to existing articles
            relationship = self.story_tracker.analyze_story_relationship(article, existing_articles)
            
            # Track in story threads
            thread_id = self.story_tracker.track_story_thread(article, relationship)
            
            # Update summary
            if relationship['type'] == 'new_story':
                evolution_summary['new_stories'] += 1
            elif relationship['type'] == 'evolution':
                evolution_summary['evolving_stories'] += 1
                evolution_summary['evolution_analysis'].append({
                    'article_title': article.title,
                    'evolution_type': relationship['type'],
                    'confidence': relationship['confidence'],
                    'thread_id': thread_id
                })
            elif relationship['type'] == 'duplicate':
                evolution_summary['duplicate_stories'] += 1
        
        # Get active story threads
        active_threads = self.story_tracker.get_active_story_threads()
        evolution_summary['story_threads'] = active_threads[:10]  # Top 10 most active
        
        return evolution_summary
    
    def _build_event_timelines(self, articles: List[NewsArticle]) -> Dict[str, Any]:
        """Build event timelines from articles"""
        timeline_updates = {
            'new_timelines': 0,
            'updated_timelines': 0,
            'timeline_summaries': []
        }
        
        for article in articles:
            timeline_id = self.timeline_builder.process_article_for_timeline(article)
            
            if timeline_id:
                # Check if this is a new timeline
                timeline = self.timeline_builder.get_timeline(timeline_id)
                if timeline and len(timeline['events']) == 1:
                    timeline_updates['new_timelines'] += 1
                else:
                    timeline_updates['updated_timelines'] += 1
        
        # Get active timelines summary
        active_timelines = self.timeline_builder.get_active_timelines(5)
        timeline_updates['timeline_summaries'] = active_timelines
        
        return timeline_updates
    
    def _create_advanced_analysis_report(self, evolution_report: Dict[str, Any], 
                                       coverage_analysis: Dict[str, Any], 
                                       timeline_updates: Dict[str, Any]):
        """Create comprehensive analysis report"""
        try:
            report_file = self.config.vault_path / "advanced_analysis_report.md"
            date_str = datetime.now().strftime('%Y-%m-%d %H:%M')
            
            # Create report content
            report_content = f"""# Advanced News Analysis Report
*Generated: {date_str}*

## 📈 Story Evolution Analysis

### Summary
- **New Stories**: {evolution_report['new_stories']}
- **Evolving Stories**: {evolution_report['evolving_stories']}
- **Duplicate Stories**: {evolution_report['duplicate_stories']}

### Active Story Threads
"""
            
            for thread in evolution_report['story_threads'][:5]:
                report_content += f"- **{thread['primary_topic']}**: {thread['article_count']} articles, last updated {thread['last_update'].strftime('%Y-%m-%d')}\n"
            
            report_content += f"""

## 📊 Coverage Gap Analysis

### Coverage Score: {coverage_analysis['coverage_score']:.1f}/100

### Identified Gaps
"""
            
            if coverage_analysis['identified_gaps']:
                for gap in coverage_analysis['identified_gaps'][:5]:
                    report_content += f"- **{gap['topic'].title()}**: {gap['severity']} severity, {gap['gap_size']} articles short\n"
            else:
                report_content += "- No significant coverage gaps detected ✅\n"
            
            report_content += f"""

## 🕐 Event Timeline Updates

### Summary
- **New Timelines Created**: {timeline_updates['new_timelines']}
- **Timelines Updated**: {timeline_updates['updated_timelines']}

### Active Event Timelines
"""
            
            for timeline in timeline_updates['timeline_summaries']:
                report_content += f"- **{timeline['title'][:60]}**: {timeline['event_count']} events, {timeline['duration']}\n"
            
            report_content += f"""

---
*Report generated by Advanced News Analysis System*
"""
            
            # Write report
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report_content)
                
            print(f"📊 Advanced analysis report saved to: {report_file}")
            
            # Also create quick summary for console
            print(f"📈 Story Analysis: {evolution_report['new_stories']} new, {evolution_report['evolving_stories']} evolving")
            print(f"📊 Coverage Score: {coverage_analysis['coverage_score']:.1f}/100")
            if coverage_analysis['identified_gaps']:
                critical_gaps = [g for g in coverage_analysis['identified_gaps'] if g['severity'] in ['critical', 'high']]
                if critical_gaps:
                    print(f"⚠️ {len(critical_gaps)} critical coverage gaps detected")
            print(f"🕐 Timeline Updates: {timeline_updates['new_timelines']} new, {timeline_updates['updated_timelines']} updated")
            
        except Exception as e:
            print(f"⚠️ Could not create advanced analysis report: {e}")



def main():
    """Main function to run the news scraper"""
    parser = argparse.ArgumentParser(description="Daily News Scraper for Obsidian")
    parser.add_argument('--date', type=str, help='Target date (DD MM YYYY or YYYY-MM-DD), defaults to today')
    parser.add_argument('--vault-path', type=str, help='Path to Obsidian vault News folder')
    parser.add_argument('--health', action='store_true', help='Show health status and exit')
    parser.add_argument('--stats', action='store_true', help='Show performance statistics and exit')
    parser.add_argument('--schedule', action='store_true', help='Run in scheduled mode (5 AM daily with catch-up)')
    parser.add_argument('--monitor', action='store_true', help='Run in monitoring mode (continuous internet checking)')
    
    args = parser.parse_args()
    
    # Setup configuration
    config = NewsConfig()
    
    if args.vault_path:
        config.vault_path = Path(args.vault_path)
        config.stories_path = config.vault_path / "stories"
    
    # Create scraper instance
    try:
        scraper = NewsScraper(config)
    except Exception as e:
        print(f"❌ Error initializing scraper: {e}")
        return 1
    
    # Handle health check
    if args.health:
        try:
            health = scraper.get_health_status()
            print("🔍 Health Status:")
            print(f"  Status: {health['status']}")
            print(".1f")
            print(f"  Config Valid: {health['config_valid']}")
            print(f"  Cache Size: {health['cache_stats']['size']}")
            print("  Dependencies:")
            for dep, available in health['dependencies'].items():
                status = "✅" if available else "❌"
                print(f"    {dep}: {status}")
            return 0
        except Exception as e:
            print(f"❌ Error getting health status: {e}")
            return 1
    
    # Handle stats
    if args.stats:
        try:
            stats = scraper.get_performance_stats()
            print("📊 Performance Statistics:")
            print(".1f")
            print(".1f")
            print(".1%")
            print(".1%")
            print(".2f")
            return 0
        except Exception as e:
            print(f"❌ Error getting performance stats: {e}")
            return 1
    
    # Handle scheduled mode
    if args.schedule or args.monitor:
        scheduler = SmartScheduler(scraper)
        
        if args.schedule:
            print("🕐 Starting scheduled mode (runs at 5 AM daily with catch-up)")
            try:
                scheduler.schedule_daily_runs()
            except KeyboardInterrupt:
                print("\n🛑 Scheduled mode stopped by user")
                return 0
        elif args.monitor:
            print("👀 Starting monitoring mode (continuous internet checking)")
            try:
                scheduler.start_monitoring()
            except KeyboardInterrupt:
                print("\n🛑 Monitoring mode stopped by user")
                return 0
        
        return 0
    
    # Parse target date
    target_date = datetime.now()
    if args.date:
        try:
            # Try DD MM YYYY format first
            if ' ' in args.date and len(args.date.split()) == 3:
                target_date = datetime.strptime(args.date, "%d %m %Y")
            else:
                # Fallback to YYYY-MM-DD format
                target_date = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print("Error: Date must be in DD MM YYYY or YYYY-MM-DD format")
            return 1
    
    # Create scraper and run
    try:
        success = scraper.run_daily_scrape(target_date)
        
        if success:
            print("✅ Daily news scrape completed successfully!")
            return 0
        else:
            print("⚠️  Daily news scrape skipped (already exists)")
            return 0
            
    except Exception as e:
        print(f"❌ Error running news scraper: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
