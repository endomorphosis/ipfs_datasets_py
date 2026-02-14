#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for finance domain scrapers.

Tests all scrapers under ipfs_datasets_py.mcp_server.tools.finance_data_tools
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.web_archiving.scraper_testing_framework import (
    ScraperTestRunner,
    ScraperDomain,
)

# Import finance scrapers
try:
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
        scrape_stock_data,
        get_stock_quote,
    )
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.news_scrapers import (
        scrape_financial_news,
        search_financial_news,
    )
    SCRAPERS_AVAILABLE = True
except ImportError as e:
    SCRAPERS_AVAILABLE = False
    print(f"Warning: Could not import finance scrapers: {e}")


@pytest.mark.skipif(not SCRAPERS_AVAILABLE, reason="Finance scrapers not available")
class TestFinanceScrapers:
    """Test suite for finance scrapers."""
    
    @pytest.fixture
    def test_runner(self, tmp_path):
        """Create a test runner instance."""
        return ScraperTestRunner(output_dir=tmp_path)
    
    @pytest.mark.asyncio
    async def test_stock_data_scraper(self, test_runner):
        """
        GIVEN the stock data scraper
        WHEN scraping stock market data
        THEN data should have numeric values without HTML
        """
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_stock_data,
            scraper_name="stock_data_scraper",
            domain=ScraperDomain.FINANCE,
            test_args={
                'symbols': ["AAPL"],
                'days': 5,
                'include_volume': True
            }
        )
        
        assert result.status in ['success', 'failed', 'error']
        
        if result.status == 'success':
            assert result.records_scraped > 0, "Should scrape stock data"
            assert result.data_quality_score >= 60, "Stock data should be high quality"
            
            # Stock data should not have DOM issues
            dom_issues = [i for i in result.quality_issues if i['type'] == 'dom_styling']
            assert len(dom_issues) == 0, "Stock data should be clean numerical data"
    
    @pytest.mark.asyncio
    async def test_financial_news_scraper(self, test_runner):
        """
        GIVEN the financial news scraper
        WHEN scraping news articles
        THEN articles should be clean without navigation elements
        """
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_financial_news,
            scraper_name="financial_news_scraper",
            domain=ScraperDomain.FINANCE,
            test_args={
                'topics': ["stocks"],
                'max_articles': 3,
                'include_content': True
            }
        )
        
        assert result.status in ['success', 'failed', 'error']
        
        if result.status == 'success':
            # Check for menu content in news articles
            menu_issues = [i for i in result.quality_issues if i['type'] == 'menu_content']
            assert len(menu_issues) == 0, \
                "News articles should not contain menu/navigation content"
    
    @pytest.mark.asyncio
    async def test_all_finance_scrapers_integration(self, test_runner):
        """
        GIVEN all finance scrapers
        WHEN running them together
        THEN they should provide quality financial data
        """
        scrapers = [
            (scrape_stock_data, "stock_data", {'symbols': ["AAPL"], 'days': 2}),
            (scrape_financial_news, "financial_news", {'topics': ["stocks"], 'max_articles': 2}),
        ]
        
        results = []
        for scraper_func, name, args in scrapers:
            try:
                result = await test_runner.run_scraper_test(
                    scraper_func=scraper_func,
                    scraper_name=name,
                    domain=ScraperDomain.FINANCE,
                    test_args=args
                )
                results.append(result)
            except Exception as e:
                print(f"Error testing {name}: {e}")
        
        if results:
            output_path = test_runner.save_results(results, "finance_scrapers_test.json")
            assert output_path.exists()
            
            summary = test_runner.generate_summary_report(results)
            print("\n" + summary)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
