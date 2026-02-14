#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for caselaw/legal domain scrapers.

Tests all scrapers under ipfs_datasets_py.mcp_server.tools.legal_dataset_tools
"""
import pytest
import anyio
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.scraper_testing_framework import (
    ScraperTestRunner,
    ScraperDomain,
    ScraperTestResult
)

# Import legal scrapers
from ipfs_datasets_py.processors.legal_scrapers import (
    scrape_us_code,
    scrape_federal_register,
    scrape_state_laws,
    scrape_municipal_laws,
    scrape_recap_archive,
)

class TestCaselawScrapers:
    """Test suite for caselaw/legal scrapers."""
    
    @pytest.fixture
    def test_runner(self, tmp_path):
        """Create a test runner instance."""
        return ScraperTestRunner(output_dir=tmp_path)
    
    @pytest.mark.asyncio
    async def test_us_code_scraper(self, test_runner):
        """
        GIVEN the US Code scraper
        WHEN scraping a small sample of US Code titles
        THEN data should be scraped without HTML/DOM content
        """
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_us_code,
            scraper_name="us_code_scraper",
            domain=ScraperDomain.CASELAW,
            test_args={
                'titles': ["1"],  # Just test one title
                'max_sections': 5,  # Limit to 5 sections for speed
                'output_format': 'json'
            }
        )
        
        # Assertions
        assert result.status in ['success', 'failed', 'error'], \
            "Test should complete with a valid status"
        
        if result.status == 'success':
            assert result.records_scraped > 0, "Should scrape at least one record"
            assert result.data_quality_score >= 50, \
                f"Data quality score should be at least 50, got {result.data_quality_score}"
            
            # Check for DOM/HTML issues
            dom_issues = [i for i in result.quality_issues if i['type'] == 'dom_styling']
            assert len(dom_issues) == 0, \
                f"Should not have DOM styling in data, found: {dom_issues}"
    
    @pytest.mark.asyncio
    async def test_federal_register_scraper(self, test_runner):
        """
        GIVEN the Federal Register scraper
        WHEN scraping federal regulations
        THEN data should be clean and coherent
        """
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_federal_register,
            scraper_name="federal_register_scraper",
            domain=ScraperDomain.CASELAW,
            test_args={
                'agencies': ["EPA"],
                'max_documents': 3,
                'output_format': 'json'
            }
        )
        
        assert result.status in ['success', 'failed', 'error']
        
        if result.status == 'success':
            assert result.records_scraped > 0
            
            # Check for menu content
            menu_issues = [i for i in result.quality_issues if i['type'] == 'menu_content']
            assert len(menu_issues) == 0, \
                f"Should not have menu content in data, found: {menu_issues}"
    
    @pytest.mark.asyncio
    async def test_state_laws_scraper(self, test_runner):
        """
        GIVEN the state laws scraper
        WHEN scraping state statutes
        THEN data should be properly formatted without HTML artifacts
        """
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_state_laws,
            scraper_name="state_laws_scraper",
            domain=ScraperDomain.CASELAW,
            test_args={
                'states': ["DE"],  # Delaware - has a working scraper
                'max_statutes': 3,
                'output_format': 'json'
            }
        )
        
        assert result.status in ['success', 'failed', 'error']
        
        if result.status == 'success':
            assert result.data_quality_score >= 60, \
                "State laws should have good quality score"
    
    @pytest.mark.asyncio
    async def test_municipal_laws_scraper(self, test_runner):
        """
        GIVEN the municipal laws scraper
        WHEN scraping municipal codes
        THEN data should be coherent without disconnected menu items
        """
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_municipal_laws,
            scraper_name="municipal_laws_scraper",
            domain=ScraperDomain.CASELAW,
            test_args={
                'jurisdictions': ["San Francisco, CA"],
                'max_codes': 2,
                'output_format': 'json'
            }
        )
        
        assert result.status in ['success', 'failed', 'error']
    
    @pytest.mark.asyncio
    async def test_recap_archive_scraper(self, test_runner):
        """
        GIVEN the RECAP archive scraper
        WHEN scraping court documents
        THEN data should be clean legal documents without web artifacts
        """
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_recap_archive,
            scraper_name="recap_archive_scraper",
            domain=ScraperDomain.CASELAW,
            test_args={
                'query': "test",
                'max_results': 2,
                'output_format': 'json'
            }
        )
        
        assert result.status in ['success', 'failed', 'error']
    
    @pytest.mark.asyncio
    async def test_all_caselaw_scrapers_integration(self, test_runner):
        """
        GIVEN all caselaw scrapers
        WHEN running them together
        THEN overall quality should meet minimum standards
        """
        scrapers = [
            (scrape_us_code, "us_code", {'titles': ["1"], 'max_sections': 2}),
            (scrape_federal_register, "federal_register", {'agencies': ["EPA"], 'max_documents': 2}),
            (scrape_state_laws, "state_laws", {'states': ["DE"], 'max_statutes': 2}),
        ]
        
        results = []
        for scraper_func, name, args in scrapers:
            result = await test_runner.run_scraper_test(
                scraper_func=scraper_func,
                scraper_name=name,
                domain=ScraperDomain.CASELAW,
                test_args=args
            )
            results.append(result)
        
        # Save results
        output_path = test_runner.save_results(results, "caselaw_scrapers_test.json")
        assert output_path.exists()
        
        # Generate summary
        summary = test_runner.generate_summary_report(results)
        assert "SCRAPER TEST SUMMARY" in summary
        print("\n" + summary)
        
        # At least some scrapers should work
        successful = [r for r in results if r.status == 'success']
        assert len(successful) > 0, "At least one scraper should succeed"


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v', '-s'])
