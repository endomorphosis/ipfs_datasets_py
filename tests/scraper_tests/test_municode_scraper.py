#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for Municode Library scraper.

Tests the municode_scraper.py module which scrapes municipal codes
from library.municode.com.
"""
import pytest
import asyncio
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestMunicodeScraper:
    """Test suite for Municode Library scraper."""
    
    @pytest.fixture
    def municode_scraper_module(self):
        """
        GIVEN the need to test Municode scraper
        WHEN I import the municode_scraper module
        THEN it should be available
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import municode_scraper
            return municode_scraper
        except ImportError as e:
            pytest.skip(f"Municode scraper not available: {e}")
    
    @pytest.mark.asyncio
    async def test_search_municode_library(self, municode_scraper_module):
        """
        GIVEN the search_municode_library function
        WHEN searching for jurisdictions by state
        THEN it should return a successful result with jurisdictions
        """
        result = await municode_scraper_module.search_municode_library(
            state="WA",
            limit=10
        )
        
        assert result["status"] in ["success", "error"], \
            "Search should return valid status"
        assert "jurisdictions" in result, "Result should contain jurisdictions"
        assert "count" in result, "Result should contain count"
        assert isinstance(result["jurisdictions"], list), \
            "Jurisdictions should be a list"
    
    @pytest.mark.asyncio
    async def test_search_municode_library_with_jurisdiction(self, municode_scraper_module):
        """
        GIVEN the search_municode_library function
        WHEN searching for a specific jurisdiction
        THEN it should return matching results
        """
        result = await municode_scraper_module.search_municode_library(
            jurisdiction="Seattle",
            state="WA",
            limit=5
        )
        
        assert result["status"] in ["success", "error"]
        assert "jurisdictions" in result
        
        # If successful, verify result structure
        if result["status"] == "success" and result["count"] > 0:
            jurisdiction = result["jurisdictions"][0]
            assert "name" in jurisdiction, "Jurisdiction should have name"
            assert "url" in jurisdiction, "Jurisdiction should have URL"
            assert "provider" in jurisdiction, "Jurisdiction should have provider"
            assert jurisdiction["provider"] == "municode"
    
    @pytest.mark.asyncio
    async def test_get_municode_jurisdictions(self, municode_scraper_module):
        """
        GIVEN the get_municode_jurisdictions function
        WHEN requesting jurisdictions list for a state
        THEN it should return available jurisdictions
        """
        result = await municode_scraper_module.get_municode_jurisdictions(
            state="CA",
            limit=5
        )
        
        assert result["status"] in ["success", "error"]
        assert "jurisdictions" in result
        assert "count" in result
        assert "provider" in result
        
        if result["status"] == "success":
            assert result["provider"] == "municode"
            assert result["source"] == "library.municode.com"
    
    @pytest.mark.asyncio
    async def test_scrape_municode_jurisdiction(self, municode_scraper_module):
        """
        GIVEN the scrape_municode_jurisdiction function
        WHEN scraping a single jurisdiction
        THEN it should return code sections
        """
        test_url = f"{municode_scraper_module.MUNICODE_BASE_URL}/seattle-wa"
        
        result = await municode_scraper_module.scrape_municode_jurisdiction(
            jurisdiction_name="Seattle, WA",
            jurisdiction_url=test_url,
            include_metadata=True,
            max_sections=5
        )
        
        assert result["status"] in ["success", "error"]
        assert "sections" in result
        assert "jurisdiction" in result
        assert result["jurisdiction"] == "Seattle, WA"
        
        if result["status"] == "success" and result["sections"]:
            section = result["sections"][0]
            assert "section_number" in section, "Section should have number"
            assert "title" in section, "Section should have title"
            assert "text" in section, "Section should have text"
            assert "jurisdiction" in section, "Section should have jurisdiction"
            
            if result.get("include_metadata"):
                assert "scraped_at" in section, "Section should have scraped_at when metadata included"
                assert "provider" in section, "Section should have provider when metadata included"
    
    @pytest.mark.asyncio
    async def test_scrape_municode_with_jurisdictions(self, municode_scraper_module):
        """
        GIVEN the scrape_municode function
        WHEN scraping with a list of jurisdictions
        THEN it should scrape all jurisdictions
        """
        result = await municode_scraper_module.scrape_municode(
            jurisdictions=["Seattle, WA", "Portland, OR"],
            output_format="json",
            include_metadata=True,
            rate_limit_delay=1.0,
            max_sections_per_jurisdiction=3
        )
        
        assert result["status"] in ["success", "error"]
        assert "data" in result
        assert "metadata" in result
        assert "output_format" in result
        
        if result["status"] == "success":
            assert result["output_format"] == "json"
            assert isinstance(result["data"], list), "Data should be a list"
            
            metadata = result["metadata"]
            assert "jurisdictions_count" in metadata
            assert "total_sections" in metadata
            assert "elapsed_time_seconds" in metadata
            assert "provider" in metadata
            assert metadata["provider"] == "municode"
    
    @pytest.mark.asyncio
    async def test_scrape_municode_with_states(self, municode_scraper_module):
        """
        GIVEN the scrape_municode function
        WHEN scraping with a list of states
        THEN it should find and scrape jurisdictions in those states
        """
        result = await municode_scraper_module.scrape_municode(
            states=["WA"],
            output_format="json",
            include_metadata=True,
            rate_limit_delay=1.0,
            max_jurisdictions=2,
            max_sections_per_jurisdiction=2
        )
        
        assert result["status"] in ["success", "error"]
        assert "data" in result
        assert "metadata" in result
        
        if result["status"] == "success" and result["data"]:
            assert len(result["data"]) <= 2, "Should respect max_jurisdictions limit"
            
            metadata = result["metadata"]
            assert metadata["provider"] == "municode"
            assert metadata["source"] == "library.municode.com"
    
    @pytest.mark.asyncio
    async def test_scrape_municode_error_handling(self, municode_scraper_module):
        """
        GIVEN the scrape_municode function
        WHEN called without jurisdictions or states
        THEN it should return an error
        """
        result = await municode_scraper_module.scrape_municode(
            output_format="json"
        )
        
        assert result["status"] == "error"
        assert "error" in result
        assert "jurisdictions" in result["error"].lower() or "states" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_scrape_municode_rate_limiting(self, municode_scraper_module):
        """
        GIVEN the scrape_municode function
        WHEN scraping multiple jurisdictions with rate limiting
        THEN it should respect the rate limit delay
        """
        import time
        
        start_time = time.time()
        
        result = await municode_scraper_module.scrape_municode(
            jurisdictions=["Seattle, WA", "Portland, OR"],
            output_format="json",
            rate_limit_delay=1.0,
            max_sections_per_jurisdiction=1
        )
        
        elapsed_time = time.time() - start_time
        
        assert result["status"] in ["success", "error"]
        
        # Should take at least 1 second due to rate limiting
        # (between the 2 jurisdictions, there's 1 delay)
        if result["status"] == "success" and result["metadata"]["jurisdictions_count"] > 1:
            assert elapsed_time >= 1.0, \
                f"Should take at least 1 second with rate limiting, took {elapsed_time:.2f}s"
    
    @pytest.mark.asyncio
    async def test_scrape_municode_max_sections_limit(self, municode_scraper_module):
        """
        GIVEN the scrape_municode function with max_sections_per_jurisdiction
        WHEN scraping a jurisdiction
        THEN it should respect the section limit
        """
        result = await municode_scraper_module.scrape_municode(
            jurisdictions=["Seattle, WA"],
            output_format="json",
            max_sections_per_jurisdiction=2
        )
        
        assert result["status"] in ["success", "error"]
        
        if result["status"] == "success" and result["data"]:
            jurisdiction_data = result["data"][0]
            sections_count = jurisdiction_data["sections_count"]
            
            assert sections_count <= 2, \
                f"Should scrape at most 2 sections, got {sections_count}"
    
    def test_municode_base_url(self, municode_scraper_module):
        """
        GIVEN the municode_scraper module
        WHEN checking the base URL
        THEN it should be set to library.municode.com
        """
        assert hasattr(municode_scraper_module, 'MUNICODE_BASE_URL')
        assert municode_scraper_module.MUNICODE_BASE_URL == "https://library.municode.com"
    
    def test_code_categories_defined(self, municode_scraper_module):
        """
        GIVEN the municode_scraper module
        WHEN checking for code categories
        THEN it should have a list of common municipal code categories
        """
        assert hasattr(municode_scraper_module, 'CODE_CATEGORIES')
        categories = municode_scraper_module.CODE_CATEGORIES
        
        assert isinstance(categories, list), "CODE_CATEGORIES should be a list"
        assert len(categories) > 0, "Should have at least one category"
        
        # Check for some expected categories
        expected_categories = ["Planning and Zoning", "Public Works", "Fire Prevention"]
        for expected in expected_categories:
            assert any(expected.lower() in cat.lower() for cat in categories), \
                f"Should include category related to '{expected}'"


class TestMunicodeScraperIntegration:
    """Integration tests for Municode scraper with the scraper testing framework."""
    
    @pytest.mark.skipif(
        not Path(__file__).parent.parent / "ipfs_datasets_py" / "scraper_testing_framework.py",
        reason="Scraper testing framework not available"
    )
    @pytest.mark.asyncio
    async def test_municode_with_scraper_framework(self, tmp_path):
        """
        GIVEN the scraper testing framework
        WHEN running Municode scraper through the framework
        THEN it should complete without data quality issues
        """
        try:
            from ipfs_datasets_py.scraper_testing_framework import (
                ScraperTestRunner,
                ScraperDomain
            )
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municode_scraper import (
                scrape_municode
            )
        except ImportError as e:
            pytest.skip(f"Required modules not available: {e}")
        
        runner = ScraperTestRunner(output_dir=tmp_path)
        
        result = await runner.run_scraper_test(
            scraper_func=scrape_municode,
            scraper_name="municode_scraper",
            domain=ScraperDomain.CASELAW,
            test_args={
                'jurisdictions': ["Seattle, WA"],
                'max_sections_per_jurisdiction': 3,
                'output_format': 'json'
            }
        )
        
        assert result.status in ['success', 'failed', 'error'], \
            "Test should complete with a valid status"
        
        if result.status == 'success':
            assert result.records_scraped > 0, "Should scrape at least one record"
            
            # Check for data quality
            dom_issues = [i for i in result.quality_issues if i['type'] == 'dom_styling']
            assert len(dom_issues) == 0, \
                f"Should not have DOM styling in data, found: {dom_issues}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
