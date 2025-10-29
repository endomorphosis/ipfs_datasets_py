"""
Financial News Scraper with Archive.org Fallback.

This module provides functionality for scraping financial news from major sources
including AP News, Reuters, and Bloomberg. It includes archive.org fallback
mechanisms for historical news retrieval.

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
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
import json
import re

logger = logging.getLogger(__name__)


@dataclass
class NewsArticle:
    """
    Represents a financial news article.
    
    Attributes:
        article_id: Unique identifier
        source: News source (ap, reuters, bloomberg)
        url: Article URL
        title: Article title
        content: Article content/body
        published_date: Publication timestamp
        authors: List of authors
        entities_mentioned: Extracted entities (companies, people, events)
        sentiment: Sentiment analysis results
        archive_urls: List of archive.org URLs
        ipfs_cid: IPFS content identifier (if stored)
        metadata: Additional metadata
    """
    article_id: str
    source: str
    url: str
    title: str
    content: str
    published_date: datetime
    authors: List[str] = field(default_factory=list)
    entities_mentioned: Dict[str, List[str]] = field(default_factory=dict)
    sentiment: Dict[str, float] = field(default_factory=dict)
    archive_urls: List[str] = field(default_factory=list)
    ipfs_cid: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @staticmethod
    def generate_id(url: str, published_date: datetime) -> str:
        """Generate unique article ID from URL and date."""
        content = f"{url}_{published_date.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "article_id": self.article_id,
            "source": self.source,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "published_date": self.published_date.isoformat(),
            "authors": self.authors,
            "entities_mentioned": self.entities_mentioned,
            "sentiment": self.sentiment,
            "archive_urls": self.archive_urls,
            "ipfs_cid": self.ipfs_cid,
            "metadata": self.metadata
        }


class NewsScraperBase:
    """
    Base class for news scrapers.
    
    Provides common functionality including rate limiting, error handling,
    and archive.org fallback mechanisms.
    """
    
    def __init__(
        self,
        source_name: str,
        rate_limit_calls: int = 10,
        rate_limit_period: int = 60,
        max_retries: int = 3,
        use_archive_fallback: bool = True
    ):
        """
        Initialize news scraper.
        
        Args:
            source_name: Name of the news source
            rate_limit_calls: Maximum API calls per period
            rate_limit_period: Rate limit period in seconds
            max_retries: Maximum retry attempts
            use_archive_fallback: Enable archive.org fallback
        """
        self.source_name = source_name
        self.rate_limit_calls = rate_limit_calls
        self.rate_limit_period = rate_limit_period
        self.max_retries = max_retries
        self.use_archive_fallback = use_archive_fallback
        
        # Rate limiting state
        self._call_times: List[float] = []
        
        # Cache for processed articles
        self._article_cache: Set[str] = set()
    
    def _check_rate_limit(self) -> None:
        """Check and enforce rate limiting."""
        now = time.time()
        
        # Remove old calls
        self._call_times = [
            t for t in self._call_times 
            if now - t < self.rate_limit_period
        ]
        
        # Wait if needed
        if len(self._call_times) >= self.rate_limit_calls:
            oldest_call = self._call_times[0]
            wait_time = self.rate_limit_period - (now - oldest_call)
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)
        
        self._call_times.append(time.time())
    
    def fetch_articles(
        self,
        topic: str,
        start_date: datetime,
        end_date: datetime,
        max_articles: int = 100
    ) -> List[NewsArticle]:
        """
        Fetch news articles for a topic within a date range.
        
        This is a template method to be implemented by subclasses.
        
        Args:
            topic: Search topic/query
            start_date: Start date for search
            end_date: End date for search
            max_articles: Maximum number of articles to fetch
        
        Returns:
            List of NewsArticle objects
        
        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement fetch_articles")
    
    def fetch_from_archive(
        self,
        url: str,
        date: Optional[datetime] = None
    ) -> Optional[str]:
        """
        Fetch article content from archive.org Wayback Machine.
        
        Args:
            url: Original article URL
            date: Optional specific date to retrieve
        
        Returns:
            Article content HTML or None if not found
        """
        if not self.use_archive_fallback:
            return None
        
        try:
            # Construct Wayback Machine URL
            if date:
                # Format: https://web.archive.org/web/YYYYMMDDhhmmss/url
                timestamp = date.strftime('%Y%m%d%H%M%S')
                archive_url = f"https://web.archive.org/web/{timestamp}/{url}"
            else:
                # Get latest snapshot
                archive_url = f"https://web.archive.org/web/{url}"
            
            logger.info(f"Attempting to fetch from archive.org: {archive_url}")
            
            # Placeholder: In production, make actual HTTP request
            # import requests
            # response = requests.get(archive_url, timeout=30)
            # if response.status_code == 200:
            #     return response.text
            
            logger.warning(
                "Archive.org fallback is a placeholder. "
                "Implement actual HTTP request in production."
            )
            return None
            
        except Exception as e:
            logger.error(f"Error fetching from archive.org: {e}")
            return None
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract financial entities from text.
        
        This is a placeholder. In production, use NLP libraries like
        spaCy or transformers for entity extraction.
        
        Args:
            text: Article text
        
        Returns:
            Dictionary of entity types to entity lists
        """
        entities = {
            "companies": [],
            "people": [],
            "events": [],
            "locations": []
        }
        
        # Placeholder: Basic pattern matching for common stock symbols
        # In production, use NLP models
        stock_pattern = r'\b([A-Z]{1,5})\b'  # Very basic pattern
        potential_symbols = re.findall(stock_pattern, text)
        
        # Filter common words that aren't stock symbols
        common_words = {'THE', 'AND', 'FOR', 'ARE', 'WAS', 'BUT', 'NOT', 'YOU', 'ALL'}
        entities["companies"] = [
            sym for sym in potential_symbols 
            if sym not in common_words
        ][:10]  # Limit to 10
        
        logger.warning(
            "Entity extraction is a placeholder. "
            "Implement NLP-based extraction in production."
        )
        
        return entities
    
    def analyze_sentiment(self, text: str) -> Dict[str, float]:
        """
        Analyze sentiment of article text.
        
        This is a placeholder. In production, use sentiment analysis models.
        
        Args:
            text: Article text
        
        Returns:
            Sentiment scores
        """
        # Placeholder: Random sentiment
        sentiment = {
            "overall": 0.0,  # Range: -1 (negative) to 1 (positive)
            "confidence": 0.0
        }
        
        logger.warning(
            "Sentiment analysis is a placeholder. "
            "Implement actual sentiment model in production."
        )
        
        return sentiment
    
    def is_duplicate(self, article: NewsArticle) -> bool:
        """
        Check if article is a duplicate.
        
        Args:
            article: Article to check
        
        Returns:
            True if duplicate, False otherwise
        """
        if article.article_id in self._article_cache:
            return True
        
        self._article_cache.add(article.article_id)
        return False


class APNewsScraper(NewsScraperBase):
    """
    Scraper for AP News financial articles.
    """
    
    def __init__(self, **kwargs):
        """Initialize AP News scraper."""
        super().__init__(source_name="ap_news", **kwargs)
        self.base_url = "https://apnews.com/hub/financial-markets"
    
    def fetch_articles(
        self,
        topic: str,
        start_date: datetime,
        end_date: datetime,
        max_articles: int = 100
    ) -> List[NewsArticle]:
        """
        Fetch articles from AP News.
        
        Note: This is a placeholder implementation.
        
        Args:
            topic: Search topic
            start_date: Start date
            end_date: End date
            max_articles: Maximum articles to fetch
        
        Returns:
            List of NewsArticle objects
        """
        self._check_rate_limit()
        
        logger.info(
            f"Fetching AP News articles on '{topic}' "
            f"from {start_date.date()} to {end_date.date()}"
        )
        
        # Placeholder: In production, implement actual scraping
        # Options:
        # 1. RSS feed parsing
        # 2. API integration (if available)
        # 3. Web scraping with BeautifulSoup/Scrapy
        
        logger.warning(
            "APNewsScraper.fetch_articles is a placeholder. "
            "Implement actual scraping in production."
        )
        
        return []


class ReutersScraper(NewsScraperBase):
    """
    Scraper for Reuters financial articles.
    """
    
    def __init__(self, **kwargs):
        """Initialize Reuters scraper."""
        super().__init__(source_name="reuters", **kwargs)
        self.base_url = "https://www.reuters.com/finance/"
    
    def fetch_articles(
        self,
        topic: str,
        start_date: datetime,
        end_date: datetime,
        max_articles: int = 100
    ) -> List[NewsArticle]:
        """
        Fetch articles from Reuters.
        
        Note: This is a placeholder implementation.
        
        Args:
            topic: Search topic
            start_date: Start date
            end_date: End date
            max_articles: Maximum articles to fetch
        
        Returns:
            List of NewsArticle objects
        """
        self._check_rate_limit()
        
        logger.info(
            f"Fetching Reuters articles on '{topic}' "
            f"from {start_date.date()} to {end_date.date()}"
        )
        
        logger.warning(
            "ReutersScraper.fetch_articles is a placeholder. "
            "Implement actual scraping in production."
        )
        
        return []


class BloombergScraper(NewsScraperBase):
    """
    Scraper for Bloomberg financial articles.
    
    Note: Bloomberg often requires JavaScript rendering (Selenium/Playwright).
    """
    
    def __init__(self, **kwargs):
        """Initialize Bloomberg scraper."""
        super().__init__(source_name="bloomberg", **kwargs)
        self.base_url = "https://www.bloomberg.com/markets"
    
    def fetch_articles(
        self,
        topic: str,
        start_date: datetime,
        end_date: datetime,
        max_articles: int = 100
    ) -> List[NewsArticle]:
        """
        Fetch articles from Bloomberg.
        
        Note: This is a placeholder. Bloomberg typically requires
        JavaScript rendering (Selenium/Playwright) and may have
        anti-scraping measures.
        
        Args:
            topic: Search topic
            start_date: Start date
            end_date: End date
            max_articles: Maximum articles to fetch
        
        Returns:
            List of NewsArticle objects
        """
        self._check_rate_limit()
        
        logger.info(
            f"Fetching Bloomberg articles on '{topic}' "
            f"from {start_date.date()} to {end_date.date()}"
        )
        
        logger.warning(
            "BloombergScraper.fetch_articles is a placeholder. "
            "Implement actual scraping with Selenium/Playwright in production."
        )
        
        return []


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


__all__ = [
    "NewsArticle",
    "NewsScraperBase",
    "APNewsScraper",
    "ReutersScraper",
    "BloombergScraper",
    "fetch_financial_news",
    "search_archive_news"
]
