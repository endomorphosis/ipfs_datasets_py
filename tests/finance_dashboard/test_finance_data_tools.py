"""
Test suite for finance data tools.

This module tests the finance dashboard enhancement components including
stock scrapers, news scrapers, and financial theorems.
"""

import pytest
from datetime import datetime, timedelta
import json

# Test imports to ensure modules are properly structured
def test_imports():
    """
    GIVEN the finance_data_tools module
    WHEN importing core components
    THEN all imports should succeed without errors
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools import (
            TOOL_CATEGORIES,
            __version__
        )
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
            StockDataPoint,
            CorporateAction,
            StockDataScraper,
            YahooFinanceScraper,
            fetch_stock_data,
            fetch_corporate_actions
        )
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.news_scrapers import (
            NewsArticle,
            NewsScraperBase,
            APNewsScraper,
            ReutersScraper,
            BloombergScraper,
            fetch_financial_news,
            search_archive_news
        )
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            FinancialEventType,
            FinancialTheorem,
            FinancialTheoremLibrary,
            list_financial_theorems,
            apply_financial_theorem
        )
        
        assert TOOL_CATEGORIES is not None
        assert __version__ is not None
        assert True  # All imports successful
        
    except ImportError as e:
        pytest.fail(f"Import failed: {e}")


def test_stock_data_point_validation():
    """
    GIVEN a StockDataPoint with valid OHLCV data
    WHEN validating the data point
    THEN validation should pass
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import StockDataPoint
    
    # Valid data point
    data_point = StockDataPoint(
        symbol="AAPL",
        timestamp=datetime.now(),
        open=150.0,
        high=152.0,
        low=149.0,
        close=151.0,
        volume=1000000
    )
    
    is_valid, errors = data_point.validate()
    assert is_valid is True
    assert len(errors) == 0


def test_stock_data_point_invalid():
    """
    GIVEN a StockDataPoint with invalid OHLCV data (high < low)
    WHEN validating the data point
    THEN validation should fail with appropriate error
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import StockDataPoint
    
    # Invalid data point (high < low)
    data_point = StockDataPoint(
        symbol="AAPL",
        timestamp=datetime.now(),
        open=150.0,
        high=148.0,  # Invalid: high is less than low
        low=149.0,
        close=151.0,
        volume=1000000
    )
    
    is_valid, errors = data_point.validate()
    assert is_valid is False
    assert len(errors) > 0
    assert any("High" in error and "less than Low" in error for error in errors)


def test_news_article_id_generation():
    """
    GIVEN a news article URL and date
    WHEN generating article ID
    THEN ID should be consistent and unique
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.news_scrapers import NewsArticle
    
    url = "https://example.com/article"
    date = datetime(2024, 1, 1, 12, 0, 0)
    
    id1 = NewsArticle.generate_id(url, date)
    id2 = NewsArticle.generate_id(url, date)
    
    # Same inputs should generate same ID
    assert id1 == id2
    
    # Different URL should generate different ID
    id3 = NewsArticle.generate_id("https://different.com/article", date)
    assert id1 != id3


def test_financial_theorem_library():
    """
    GIVEN a FinancialTheoremLibrary
    WHEN querying for theorems
    THEN should return expected theorems
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
        FinancialTheoremLibrary,
        FinancialEventType
    )
    
    library = FinancialTheoremLibrary()
    
    # Check that library has theorems
    assert len(library.theorems) > 0
    
    # Get stock split theorems
    split_theorems = library.get_theorems_by_event_type(FinancialEventType.STOCK_SPLIT)
    assert len(split_theorems) > 0
    
    # Check specific theorem
    stock_split_theorem = library.get_theorem("fin_001")
    assert stock_split_theorem is not None
    assert stock_split_theorem.name == "Stock Split Price Adjustment"
    assert stock_split_theorem.event_type == FinancialEventType.STOCK_SPLIT


def test_list_financial_theorems_mcp_tool():
    """
    GIVEN the list_financial_theorems MCP tool
    WHEN calling it
    THEN should return JSON with theorem list
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
        list_financial_theorems
    )
    
    result = list_financial_theorems()
    
    # Should return valid JSON
    data = json.loads(result)
    assert "total_theorems" in data
    assert "theorems" in data
    assert data["total_theorems"] > 0


def test_fetch_stock_data_mcp_tool():
    """
    GIVEN the fetch_stock_data MCP tool
    WHEN calling it with valid parameters
    THEN should return JSON response (even if placeholder)
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
        fetch_stock_data
    )
    
    result = fetch_stock_data(
        symbol="AAPL",
        start_date="2024-01-01",
        end_date="2024-01-31",
        interval="1d",
        source="yahoo"
    )
    
    # Should return valid JSON
    data = json.loads(result)
    assert "symbol" in data
    assert data["symbol"] == "AAPL"


def test_rate_limiting():
    """
    GIVEN a StockDataScraper with rate limiting
    WHEN making multiple calls
    THEN rate limiting should be enforced
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
        StockDataScraper
    )
    
    # Create scraper with strict rate limit (1 call per 2 seconds)
    scraper = StockDataScraper(
        rate_limit_calls=1,
        rate_limit_period=2
    )
    
    # First call should be immediate
    import time
    start = time.time()
    scraper._check_rate_limit()
    first_call = time.time() - start
    
    # Should be nearly instant
    assert first_call < 0.1
    
    # Second call should be delayed
    start = time.time()
    scraper._check_rate_limit()
    second_call = time.time() - start
    
    # Should wait approximately 2 seconds
    assert second_call >= 1.8  # Allow small timing variance


def test_scraper_retry_logic():
    """
    GIVEN a scraper with retry logic
    WHEN a function fails initially but succeeds on retry
    THEN the retry mechanism should work
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
        StockDataScraper
    )
    
    scraper = StockDataScraper(max_retries=3, retry_delay=0.1)
    
    # Counter to track attempts
    attempts = []
    
    def failing_function():
        attempts.append(1)
        if len(attempts) < 2:
            raise ValueError("Temporary failure")
        return "success"
    
    # Should succeed on second attempt
    result = scraper._retry_with_backoff(failing_function)
    assert result == "success"
    assert len(attempts) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
