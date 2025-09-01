#!/usr/bin/env python3
"""
Test Advanced News Analysis Features
- Multi-day Story Tracking
- Coverage Gap Analysis  
- Event Timeline Reconstruction
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add the current directory to Python path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from news_scraper import (
    NewsConfig, 
    NewsArticle, 
    StoryEvolutionTracker, 
    CoverageGapAnalyzer, 
    EventTimelineBuilder
)

def create_test_articles():
    """Create test articles for different scenarios"""
    base_time = datetime.now()
    
    # Story evolution sequence - COVID vaccine development
    covid_articles = [
        NewsArticle(
            title="Pfizer Announces COVID Vaccine Trial Results",
            description="Pfizer announces preliminary results from Phase 3 COVID-19 vaccine trials showing 95% efficacy in preventing infection.",
            url="https://example.com/pfizer-trial-1",
            source="Reuters",
            published_at=base_time - timedelta(days=3)
        ),
        NewsArticle(
            title="Pfizer COVID Vaccine Receives Emergency Authorization",
            description="FDA grants emergency use authorization for Pfizer-BioNTech COVID-19 vaccine following trial results.",
            url="https://example.com/pfizer-authorization",
            source="Associated Press", 
            published_at=base_time - timedelta(days=2)
        ),
        NewsArticle(
            title="First COVID Vaccinations Begin in Hospitals",
            description="Healthcare workers receive first doses of Pfizer COVID vaccine as nationwide rollout begins.",
            url="https://example.com/first-vaccinations",
            source="CNN",
            published_at=base_time - timedelta(days=1)
        ),
        NewsArticle(
            title="Pfizer Vaccine Side Effects Reported by Healthcare Workers", 
            description="Some healthcare workers report mild side effects after receiving Pfizer COVID vaccine, officials say this is normal.",
            url="https://example.com/vaccine-side-effects",
            source="BBC News",
            published_at=base_time
        )
    ]
    
    # Economic crisis timeline
    economic_articles = [
        NewsArticle(
            title="Federal Reserve Raises Interest Rates by 0.75%",
            description="Federal Reserve announces aggressive interest rate hike to combat rising inflation.",
            url="https://example.com/fed-rate-hike",
            source="Wall Street Journal",
            published_at=base_time - timedelta(days=2)
        ),
        NewsArticle(
            title="Stock Market Tumbles Following Fed Decision",
            description="Stock markets fall sharply as investors react to Federal Reserve interest rate increase.",
            url="https://example.com/market-reaction",
            source="Financial Times",
            published_at=base_time - timedelta(days=1)
        )
    ]
    
    # Technology coverage (good coverage)
    tech_articles = [
        NewsArticle(
            title="OpenAI Releases GPT-4 with Enhanced Capabilities",
            description="OpenAI unveils GPT-4, showing improved reasoning and reduced hallucinations.",
            url="https://example.com/gpt4-release",
            source="TechCrunch",
            published_at=base_time
        ),
        NewsArticle(
            title="Google Announces Bard AI Assistant Updates",
            description="Google's Bard AI receives major updates to compete with ChatGPT and GPT-4.",
            url="https://example.com/bard-updates",
            source="The Verge",
            published_at=base_time
        )
    ]
    
    # Climate coverage gap (insufficient coverage)
    climate_articles = [
        NewsArticle(
            title="Antarctica Ice Sheet Shows Accelerated Melting",
            description="New research shows Antarctic ice sheet melting faster than previously predicted.",
            url="https://example.com/antarctica-melting",
            source="Nature News",
            published_at=base_time - timedelta(days=3)
        )
    ]
    
    # Duplicate articles (same story, different sources)
    duplicate_articles = [
        NewsArticle(
            title="Tesla Stock Drops 5% After Quarterly Report",
            description="Tesla shares decline following quarterly earnings report that missed analyst expectations.",
            url="https://example.com/tesla-stock-1",
            source="Reuters",
            published_at=base_time
        ),
        NewsArticle(
            title="Tesla Shares Fall 5% on Earnings Miss",
            description="Tesla stock falls after company reports quarterly earnings below Wall Street forecasts.",
            url="https://example.com/tesla-stock-2", 
            source="Bloomberg",
            published_at=base_time
        )
    ]
    
    all_articles = covid_articles + economic_articles + tech_articles + climate_articles + duplicate_articles
    
    # Add basic attributes to articles
    for article in all_articles:
        article.entities = set()
        article.topics = set()
        article.sentiment = {'compound': 0.0, 'pos': 0.0, 'neu': 1.0, 'neg': 0.0}
        article.hash = f"hash_{hash(article.title)}"
        
        # Add relevant entities and topics
        if 'covid' in article.title.lower() or 'vaccine' in article.title.lower():
            article.entities.add('Pfizer')
            article.entities.add('FDA')
            article.entities.add('COVID-19')
            article.topics.add('health')
            
        elif 'federal reserve' in article.title.lower() or 'interest rate' in article.title.lower():
            article.entities.add('Federal Reserve')
            article.entities.add('Jerome Powell')
            article.topics.add('economy')
            
        elif 'tesla' in article.title.lower():
            article.entities.add('Tesla')
            article.entities.add('Elon Musk')
            article.topics.add('business')
            
        elif 'gpt' in article.title.lower() or 'ai' in article.title.lower():
            article.entities.add('OpenAI')
            article.entities.add('Google')
            article.topics.add('technology')
            
        elif 'antarctica' in article.title.lower() or 'climate' in article.title.lower():
            article.entities.add('Antarctica')
            article.topics.add('climate')
    
    return all_articles

def test_story_evolution_tracker():
    """Test the story evolution tracking system"""
    print("🧪 Testing Story Evolution Tracker...")
    
    # Create test config
    config = NewsConfig()
    config.vault_path = Path("test_output")
    config.vault_path.mkdir(exist_ok=True)
    
    tracker = StoryEvolutionTracker(config)
    articles = create_test_articles()
    
    # Test each article
    results = []
    for i, article in enumerate(articles):
        previous_articles = articles[:i]  # Articles that came before this one
        relationship = tracker.analyze_story_relationship(article, previous_articles)
        thread_id = tracker.track_story_thread(article, relationship)
        
        results.append({
            'article': article.title[:50] + '...',
            'relationship': relationship['type'],
            'confidence': relationship.get('confidence', 0),
            'thread_id': thread_id
        })
        
        print(f"  📰 {article.title[:40]}... -> {relationship['type']} (confidence: {relationship.get('confidence', 0):.2f})")
    
    # Get active threads
    active_threads = tracker.get_active_story_threads()
    print(f"\n  📈 Found {len(active_threads)} active story threads:")
    for thread in active_threads:
        print(f"    - {thread['primary_topic']}: {len(thread['articles'])} articles")
    
    return results

def test_coverage_gap_analyzer():
    """Test the coverage gap analysis system"""
    print("\n🧪 Testing Coverage Gap Analyzer...")
    
    config = NewsConfig()
    config.vault_path = Path("test_output")
    
    analyzer = CoverageGapAnalyzer(config)
    articles = create_test_articles()
    
    # Analyze coverage for today
    analysis = analyzer.analyze_daily_coverage(articles)
    
    print(f"  📊 Coverage Score: {analysis['coverage_score']:.1f}/100")
    print(f"  📰 Articles by topic:")
    for topic, data in analysis['coverage_summary'].items():
        if data and data.get('count', 0) > 0:
            print(f"    - {topic}: {data['count']} articles")
    
    print(f"\n  ⚠️ Coverage Gaps:")
    if analysis['identified_gaps']:
        for gap in analysis['identified_gaps'][:5]:
            print(f"    - {gap['topic']}: {gap['severity']} severity, need {gap['gap_size']} more articles")
    else:
        print("    - No significant gaps detected!")
    
    # Generate weekly report
    weekly_report = analyzer.generate_gap_report(7)
    print(f"\n  📋 Weekly Coverage Score: {weekly_report['overall_coverage_score']:.1f}/100")
    
    return analysis

def test_event_timeline_builder():
    """Test the event timeline building system"""
    print("\n🧪 Testing Event Timeline Builder...")
    
    config = NewsConfig()
    config.vault_path = Path("test_output")
    
    builder = EventTimelineBuilder(config)
    articles = create_test_articles()
    
    # Process articles for timeline building
    timeline_results = []
    for article in articles:
        timeline_id = builder.process_article_for_timeline(article)
        if timeline_id:
            timeline_results.append(timeline_id)
            print(f"  🕐 Added to timeline: {timeline_id}")
    
    # Get active timelines
    active_timelines = builder.get_active_timelines()
    print(f"\n  📅 Created {len(active_timelines)} timelines:")
    
    for timeline_summary in active_timelines:
        print(f"    - {timeline_summary['title'][:50]}...")
        print(f"      Events: {timeline_summary['event_count']}, Duration: {timeline_summary['duration']}")
        
        # Get full timeline details
        full_timeline = builder.get_timeline(timeline_summary['timeline_id'])
        if full_timeline:
            print(f"      Entities: {', '.join(full_timeline['primary_entities'][:3])}")
    
    # Generate markdown for first timeline
    if active_timelines:
        first_timeline_id = active_timelines[0]['timeline_id']
        markdown = builder.generate_timeline_markdown(first_timeline_id)
        
        # Save markdown file
        timeline_file = config.vault_path / f"timeline_{first_timeline_id}.md"
        with open(timeline_file, 'w', encoding='utf-8') as f:
            f.write(markdown)
        
        print(f"  💾 Timeline markdown saved to: {timeline_file}")
    
    return active_timelines

def main():
    """Run all advanced feature tests"""
    print("🚀 Testing Advanced News Analysis Features")
    print("=" * 50)
    
    try:
        # Test story evolution tracking
        evolution_results = test_story_evolution_tracker()
        
        # Test coverage gap analysis
        coverage_results = test_coverage_gap_analyzer()
        
        # Test event timeline building
        timeline_results = test_event_timeline_builder()
        
        print("\n" + "=" * 50)
        print("✅ All Advanced Features Tested Successfully!")
        print(f"📈 Story Relationships: {len([r for r in evolution_results if r['relationship'] != 'new_story'])} connections found")
        print(f"📊 Coverage Gaps: {len(coverage_results['identified_gaps'])} gaps identified")
        print(f"🕐 Event Timelines: {len(timeline_results)} timelines created")
        
        # Cleanup
        import shutil
        test_output = Path("test_output")
        if test_output.exists():
            shutil.rmtree(test_output)
            print("🧹 Cleaned up test files")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
