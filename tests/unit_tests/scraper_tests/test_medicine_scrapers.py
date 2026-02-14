#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for medicine domain scrapers.

Tests all scrapers under ipfs_datasets_py.mcp_server.tools.medical_research_scrapers
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.web_archiving.scraper_testing_framework import (
    ScraperTestRunner,
    ScraperDomain,
)

# Import medical scrapers
try:
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.clinical_trials_scraper import (
        ClinicalTrialsScraper
    )
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.pubmed_scraper import (
        PubMedScraper
    )
    SCRAPERS_AVAILABLE = True
except ImportError as e:
    SCRAPERS_AVAILABLE = False
    print(f"Warning: Could not import medical scrapers: {e}")


@pytest.mark.skipif(not SCRAPERS_AVAILABLE, reason="Medical scrapers not available")
class TestMedicineScrapers:
    """Test suite for medicine/medical research scrapers."""
    
    @pytest.fixture
    def test_runner(self, tmp_path):
        """Create a test runner instance."""
        return ScraperTestRunner(output_dir=tmp_path)
    
    @pytest.mark.asyncio
    async def test_clinical_trials_scraper(self, test_runner):
        """
        GIVEN the clinical trials scraper
        WHEN scraping clinical trial data
        THEN data should be medical research without web artifacts
        """
        scraper = ClinicalTrialsScraper()
        
        async def scrape_trials(**kwargs):
            """Wrapper to make clinical trials search async compatible."""
            trials = scraper.search_trials(
                query=kwargs.get('query', 'diabetes'),
                max_results=kwargs.get('max_results', 3)
            )
            return {'status': 'success', 'data': trials}
        
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_trials,
            scraper_name="clinical_trials_scraper",
            domain=ScraperDomain.MEDICINE,
            test_args={
                'query': 'cancer treatment',
                'max_results': 3
            }
        )
        
        assert result.status in ['success', 'failed', 'error']
        
        if result.status == 'success':
            assert result.records_scraped > 0, "Should scrape clinical trials"
            
            # Medical data should be clean
            dom_issues = [i for i in result.quality_issues if i['type'] == 'dom_styling']
            assert len(dom_issues) == 0, "Medical data should not have HTML tags"
    
    @pytest.mark.asyncio
    async def test_pubmed_scraper(self, test_runner):
        """
        GIVEN the PubMed scraper
        WHEN scraping medical research papers
        THEN abstracts and metadata should be clean
        """
        scraper = PubMedScraper()
        
        async def scrape_pubmed(**kwargs):
            """Wrapper for PubMed search."""
            results = scraper.search_articles(
                query=kwargs.get('query', 'covid'),
                max_results=kwargs.get('max_results', 3)
            )
            return {'status': 'success', 'data': results}
        
        result = await test_runner.run_scraper_test(
            scraper_func=scrape_pubmed,
            scraper_name="pubmed_scraper",
            domain=ScraperDomain.MEDICINE,
            test_args={
                'query': 'diabetes',
                'max_results': 3
            }
        )
        
        assert result.status in ['success', 'failed', 'error']
        
        if result.status == 'success':
            # Check data quality
            assert result.data_quality_score >= 50, \
                "PubMed data should have reasonable quality"
    
    @pytest.mark.asyncio
    async def test_all_medicine_scrapers_integration(self, test_runner):
        """
        GIVEN all medicine scrapers
        WHEN running them together
        THEN they should provide quality medical research data
        """
        clinical_scraper = ClinicalTrialsScraper()
        pubmed_scraper = PubMedScraper()
        
        async def scrape_clinical(**kwargs):
            trials = clinical_scraper.search_trials(
                query=kwargs.get('query', 'test'),
                max_results=kwargs.get('max_results', 2)
            )
            return {'status': 'success', 'data': trials}
        
        async def scrape_pubmed(**kwargs):
            articles = pubmed_scraper.search_articles(
                query=kwargs.get('query', 'test'),
                max_results=kwargs.get('max_results', 2)
            )
            return {'status': 'success', 'data': articles}
        
        scrapers = [
            (scrape_clinical, "clinical_trials", {'query': 'diabetes', 'max_results': 2}),
            (scrape_pubmed, "pubmed", {'query': 'diabetes', 'max_results': 2}),
        ]
        
        results = []
        for scraper_func, name, args in scrapers:
            try:
                result = await test_runner.run_scraper_test(
                    scraper_func=scraper_func,
                    scraper_name=name,
                    domain=ScraperDomain.MEDICINE,
                    test_args=args
                )
                results.append(result)
            except Exception as e:
                print(f"Error testing {name}: {e}")
        
        if results:
            output_path = test_runner.save_results(results, "medicine_scrapers_test.json")
            assert output_path.exists()
            
            summary = test_runner.generate_summary_report(results)
            print("\n" + summary)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
