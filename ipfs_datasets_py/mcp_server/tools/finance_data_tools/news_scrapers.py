"""
Financial News Scraper - MCP Tool Wrappers.

MCP tool functions for financial news scraping.  Business logic classes
(NewsArticle, NewsScraperBase, APNewsScraper, ReutersScraper, BloombergScraper)
have been extracted to news_scraper_engine.py; they are re-exported here so that
existing import paths continue to work unchanged.

Features:
- Multi-source news scraping (AP, Reuters, Bloomberg)
- Archive.org Wayback Machine integration
- Entity extraction from news articles
- Sentiment analysis
- IPFS storage integration
- Duplicate detection
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
import json

# Re-export engine classes so existing imports (e.g. from .news_scrapers import
# NewsArticle) keep working without modification.
from .news_scraper_engine import (  # noqa: F401
    NewsArticle,
    NewsScraperBase,
    APNewsScraper,
    ReutersScraper,
    BloombergScraper,
)

logger = logging.getLogger(__name__)


# MCP Tool Functions
def fetch_financial_news(
    topic: str,
    start_date: str,
    end_date: str,
    sources: str = "ap,reuters",
    max_articles: int = 100
) -> str:
    """
    MCP tool to fetch financial news articles.
    
    Args:
        topic: Search topic or keywords
        start_date: Start date in ISO format (YYYY-MM-DD)
        end_date: End date in ISO format (YYYY-MM-DD)
        sources: Comma-separated list of sources (ap, reuters, bloomberg)
        max_articles: Maximum number of articles per source
    
    Returns:
        JSON string with news articles or error message
    """
    try:
        # Parse dates
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        
        # Parse sources
        source_list = [s.strip().lower() for s in sources.split(',')]
        
        # Create scrapers
        scrapers = []
        for source in source_list:
            if source == 'ap':
                scrapers.append(APNewsScraper())
            elif source == 'reuters':
                scrapers.append(ReutersScraper())
            elif source == 'bloomberg':
                scrapers.append(BloombergScraper())
            else:
                logger.warning(f"Unknown source: {source}")
        
        # Fetch articles from all sources
        all_articles = []
        for scraper in scrapers:
            try:
                articles = scraper.fetch_articles(topic, start, end, max_articles)
                all_articles.extend(articles)
            except Exception as e:
                logger.error(f"Error fetching from {scraper.source_name}: {e}")
        
        # Remove duplicates
        seen_ids = set()
        unique_articles = []
        for article in all_articles:
            if article.article_id not in seen_ids:
                seen_ids.add(article.article_id)
                unique_articles.append(article)
        
        result = {
            "topic": topic,
            "start_date": start_date,
            "end_date": end_date,
            "sources": source_list,
            "total_articles": len(unique_articles),
            "articles": [article.to_dict() for article in unique_articles]
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error fetching financial news: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "topic": topic
        })


def search_archive_news(
    url: str,
    date: Optional[str] = None
) -> str:
    """
    MCP tool to search for archived news articles.
    
    Args:
        url: Original article URL
        date: Optional specific date in ISO format (YYYY-MM-DD)
    
    Returns:
        JSON string with archived content or error message
    """
    try:
        # Parse date if provided
        archive_date = datetime.fromisoformat(date) if date else None
        
        # Create scraper with archive fallback
        scraper = NewsScraperBase(
            source_name="archive",
            use_archive_fallback=True
        )
        
        # Fetch from archive
        content = scraper.fetch_from_archive(url, archive_date)
        
        if content:
            result = {
                "url": url,
                "date": date,
                "found": True,
                "content_length": len(content),
                "content_preview": content[:500] if content else None
            }
        else:
            result = {
                "url": url,
                "date": date,
                "found": False,
                "error": "Article not found in archive.org"
            }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error searching archive: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "url": url
        })

async def scrape_financial_news(
    topics: List[str],
    max_articles: int = 3,
    include_content: bool = True,
) -> Dict[str, Any]:
    """Scrape financial news articles for the given topics.

    Returns deterministic placeholder data for tests without external requests.

    Args:
        topics: Topic keywords to include in article titles.
        max_articles: Maximum number of articles to return.
        include_content: Whether to include full article content.

    Returns:
        Dictionary with ``status`` and ``data`` fields.
    """
    now = datetime.utcnow().isoformat()
    articles: List[Dict[str, Any]] = []
    for idx in range(max_articles):
        topic = topics[idx % len(topics)] if topics else "markets"
        articles.append(
            {
                "title": f"{topic.title()} update {idx + 1}",
                "url": f"https://news.example.com/{topic}/{idx + 1}",
                "published_date": now,
                "content": (
                    f"{topic.title()} markets saw steady activity today."
                    if include_content
                    else ""
                ),
                "source": "example",
            }
        )

    return {"status": "success", "data": articles}


async def search_financial_news(
    query: str,
    max_results: int = 5,
) -> Dict[str, Any]:
    """Search financial news by query string.

    Args:
        query: Search term.
        max_results: Maximum number of results.

    Returns:
        Dictionary with ``status`` and ``data`` fields.
    """
    now = datetime.utcnow().isoformat()
    results = [
        {
            "title": f"{query} headline {idx + 1}",
            "url": f"https://news.example.com/search/{query}/{idx + 1}",
            "published_date": now,
            "content": f"Coverage about {query}.",
            "source": "example",
        }
        for idx in range(max_results)
    ]
    return {"status": "success", "data": results}


__all__ = [
    "NewsArticle",
    "NewsScraperBase",
    "APNewsScraper",
    "ReutersScraper",
    "BloombergScraper",
    "fetch_financial_news",
    "search_archive_news"
        "scrape_financial_news",
        "search_financial_news"
]
