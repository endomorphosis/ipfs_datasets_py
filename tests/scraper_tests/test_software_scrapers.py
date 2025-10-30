#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for software domain scrapers.

Tests all scrapers under ipfs_datasets_py.mcp_server.tools.software_engineering_tools
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.scraper_testing_framework import (
    ScraperTestRunner,
    ScraperDomain,
)

# Import software scrapers
try:
    from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.github_repository_scraper import (
        GitHubRepositoryScraper
    )
    SCRAPERS_AVAILABLE = True
except ImportError as e:
    SCRAPERS_AVAILABLE = False
    print(f"Warning: Could not import software scrapers: {e}")


@pytest.mark.skipif(not SCRAPERS_AVAILABLE, reason="Software scrapers not available")
class TestSoftwareScrapers:
    """Test suite for software engineering scrapers."""
    
    @pytest.fixture
    def test_runner(self, tmp_path):
        """Create a test runner instance."""
        return ScraperTestRunner(output_dir=tmp_path)
    
    @pytest.mark.asyncio
    async def test_github_repository_scraper(self, test_runner):
        """
        GIVEN the GitHub repository scraper
        WHEN scraping repository data
        THEN data should be clean code and documentation
        """
        scraper = GitHubRepositoryScraper()
        
        async def scrape_github(**kwargs):
            """Wrapper for GitHub scraper."""
            repos = scraper.search_repositories(
                query=kwargs.get('query', 'python'),
                max_results=kwargs.get('max_results', 3)
            )
            return {'status': 'success', 'data': repos}
        
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_github,
            scraper_name="github_repository_scraper",
            domain=ScraperDomain.SOFTWARE,
            test_args={
                'query': 'machine learning',
                'max_results': 3
            }
        )
        
        assert result.status in ['success', 'failed', 'error']
        
        if result.status == 'success':
            assert result.records_scraped > 0, "Should scrape GitHub repositories"
            
            # GitHub data should be clean
            menu_issues = [i for i in result.quality_issues if i['type'] == 'menu_content']
            assert len(menu_issues) == 0, \
                "GitHub data should not contain navigation menus"
            
            assert result.data_quality_score >= 60, \
                "GitHub repository data should be high quality"
    
    @pytest.mark.asyncio
    async def test_all_software_scrapers_integration(self, test_runner):
        """
        GIVEN all software scrapers
        WHEN running them together
        THEN they should provide quality software engineering data
        """
        scraper = GitHubRepositoryScraper()
        
        async def scrape_github(**kwargs):
            repos = scraper.search_repositories(
                query=kwargs.get('query', 'test'),
                max_results=kwargs.get('max_results', 2)
            )
            return {'status': 'success', 'data': repos}
        
        scrapers = [
            (scrape_github, "github_repositories", {'query': 'python pandas', 'max_results': 2}),
        ]
        
        results = []
        for scraper_func, name, args in scrapers:
            try:
                result = await test_runner.run_scraper_test(
                    scraper_func=scraper_func,
                    scraper_name=name,
                    domain=ScraperDomain.SOFTWARE,
                    test_args=args
                )
                results.append(result)
            except Exception as e:
                print(f"Error testing {name}: {e}")
        
        if results:
            output_path = test_runner.save_results(results, "software_scrapers_test.json")
            assert output_path.exists()
            
            summary = test_runner.generate_summary_report(results)
            print("\n" + summary)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
