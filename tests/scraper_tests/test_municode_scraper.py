#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for Municode Library webscraper.

Tests are based on the Gherkin scenarios defined in test_municode_scraper.feature.
Each test corresponds to a specific scenario from the feature file.
"""
import pytest
import asyncio
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestSearchJurisdictions:
    """Test suite for search_jurisdictions callable."""
    
    @pytest.mark.asyncio
    async def test_search_by_state_returns_list(self, mock_search_jurisdictions):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN the response contains a list of jurisdictions
        """
        result = await mock_search_jurisdictions(state="WA", limit=10)
        assert "jurisdictions" in result
        assert isinstance(result["jurisdictions"], list)
    
    @pytest.mark.asyncio
    async def test_search_by_state_respects_limit(self, mock_search_jurisdictions):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN the list contains at most 10 jurisdictions
        """
        result = await mock_search_jurisdictions(state="WA", limit=10)
        assert len(result["jurisdictions"]) <= 10
    
    @pytest.mark.asyncio
    async def test_search_by_state_includes_name_field(self, mock_search_jurisdictions):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN each jurisdiction has a name field
        """
        result = await mock_search_jurisdictions(state="WA", limit=10)
        for jurisdiction in result["jurisdictions"]:
            assert "name" in jurisdiction
    
    @pytest.mark.asyncio
    async def test_search_by_state_includes_state_field(self, mock_search_jurisdictions):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN each jurisdiction has a state field with value "WA"
        """
        result = await mock_search_jurisdictions(state="WA", limit=10)
        for jurisdiction in result["jurisdictions"]:
            assert jurisdiction["state"] == "WA"
    
    @pytest.mark.asyncio
    async def test_search_by_state_includes_url_field(self, mock_search_jurisdictions):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN each jurisdiction has a url field
        """
        result = await mock_search_jurisdictions(state="WA", limit=10)
        for jurisdiction in result["jurisdictions"]:
            assert "url" in jurisdiction
    
    @pytest.mark.asyncio
    async def test_search_by_state_includes_provider_field(self, mock_search_jurisdictions):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN each jurisdiction has a provider field with value "municode"
        """
        result = await mock_search_jurisdictions(state="WA", limit=10)
        for jurisdiction in result["jurisdictions"]:
            assert jurisdiction["provider"] == "municode"
    
    @pytest.mark.asyncio
    async def test_search_by_name_returns_list(self, mock_search_jurisdictions):
        """
        GIVEN I have a jurisdiction name "Seattle"
        WHEN I call search_jurisdictions with jurisdiction "Seattle"
        THEN the response contains a list of jurisdictions
        """
        result = await mock_search_jurisdictions(jurisdiction="Seattle")
        assert "jurisdictions" in result
        assert isinstance(result["jurisdictions"], list)
    
    @pytest.mark.asyncio
    async def test_search_by_name_filters_by_name(self, mock_search_jurisdictions):
        """
        GIVEN I have a jurisdiction name "Seattle"
        WHEN I call search_jurisdictions with jurisdiction "Seattle"
        THEN each jurisdiction name contains "Seattle"
        """
        result = await mock_search_jurisdictions(jurisdiction="Seattle")
        for jurisdiction in result["jurisdictions"]:
            assert "Seattle" in jurisdiction["name"]
    
    @pytest.mark.asyncio
    async def test_search_by_name_includes_url_field(self, mock_search_jurisdictions):
        """
        GIVEN I have a jurisdiction name "Seattle"
        WHEN I call search_jurisdictions with jurisdiction "Seattle"
        THEN each jurisdiction has a url field
        """
        result = await mock_search_jurisdictions(jurisdiction="Seattle")
        for jurisdiction in result["jurisdictions"]:
            assert "url" in jurisdiction
    
    @pytest.mark.asyncio
    async def test_search_by_name_includes_provider_field(self, mock_search_jurisdictions):
        """
        GIVEN I have a jurisdiction name "Seattle"
        WHEN I call search_jurisdictions with jurisdiction "Seattle"
        THEN each jurisdiction has a provider field with value "municode"
        """
        result = await mock_search_jurisdictions(jurisdiction="Seattle")
        for jurisdiction in result["jurisdictions"]:
            assert jurisdiction["provider"] == "municode"
    
    @pytest.mark.asyncio
    async def test_search_by_keywords_returns_list(self, mock_search_jurisdictions):
        """
        GIVEN I have a search keyword "zoning"
        WHEN I call search_jurisdictions with keywords "zoning"
        THEN the response contains a list of jurisdictions
        """
        result = await mock_search_jurisdictions(keywords="zoning")
        assert "jurisdictions" in result
        assert isinstance(result["jurisdictions"], list)
    
    @pytest.mark.asyncio
    async def test_search_by_keywords_includes_url_field(self, mock_search_jurisdictions):
        """
        GIVEN I have a search keyword "zoning"
        WHEN I call search_jurisdictions with keywords "zoning"
        THEN each jurisdiction has a url field
        """
        result = await mock_search_jurisdictions(keywords="zoning")
        for jurisdiction in result["jurisdictions"]:
            assert "url" in jurisdiction
    
    @pytest.mark.asyncio
    async def test_search_by_keywords_includes_provider_field(self, mock_search_jurisdictions):
        """
        GIVEN I have a search keyword "zoning"
        WHEN I call search_jurisdictions with keywords "zoning"
        THEN each jurisdiction has a provider field with value "municode"
        """
        result = await mock_search_jurisdictions(keywords="zoning")
        for jurisdiction in result["jurisdictions"]:
            assert jurisdiction["provider"] == "municode"
    
    @pytest.mark.asyncio
    async def test_search_with_no_results(self, mock_search_jurisdictions):
        """
        GIVEN I have an invalid jurisdiction name "NonexistentCity12345"
        WHEN I call search_jurisdictions with jurisdiction "NonexistentCity12345"
        THEN the response contains an empty list of jurisdictions
        """
        result = await mock_search_jurisdictions(jurisdiction="NonexistentCity12345")
        assert result["jurisdictions"] == []
    
    @pytest.mark.asyncio
    async def test_search_with_state_and_limit_returns_list(self, mock_search_jurisdictions):
        """
        GIVEN I have a valid two-letter state code "CA"
        WHEN I call search_jurisdictions with state "CA" and limit 5
        THEN the response contains a list of jurisdictions
        """
        result = await mock_search_jurisdictions(state="CA", limit=5)
        assert "jurisdictions" in result
        assert isinstance(result["jurisdictions"], list)
    
    @pytest.mark.asyncio
    async def test_search_with_state_and_limit_respects_limit(self, mock_search_jurisdictions):
        """
        GIVEN I have a valid two-letter state code "CA"
        WHEN I call search_jurisdictions with state "CA" and limit 5
        THEN the list contains at most 5 jurisdictions
        """
        result = await mock_search_jurisdictions(state="CA", limit=5)
        assert len(result["jurisdictions"]) <= 5
    
    @pytest.mark.asyncio
    async def test_search_with_state_and_limit_filters_by_state(self, mock_search_jurisdictions):
        """
        GIVEN I have a valid two-letter state code "CA"
        WHEN I call search_jurisdictions with state "CA" and limit 5
        THEN each jurisdiction has a state field with value "CA"
        """
        result = await mock_search_jurisdictions(state="CA", limit=5)
        for jurisdiction in result["jurisdictions"]:
            assert jurisdiction["state"] == "CA"


class TestScrapeJurisdiction:
    """Test suite for scrape_jurisdiction callable."""
    
    @pytest.mark.asyncio
    async def test_scrape_returns_jurisdiction_field(self, mock_scrape_jurisdiction):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN the response contains a jurisdiction field with value "Seattle, WA"
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="Seattle, WA",
            url="https://library.municode.com/wa/seattle"
        )
        assert result["jurisdiction"] == "Seattle, WA"
    
    @pytest.mark.asyncio
    async def test_scrape_returns_sections_field(self, mock_scrape_jurisdiction):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN the response contains a sections field
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="Seattle, WA",
            url="https://library.municode.com/wa/seattle"
        )
        assert "sections" in result
    
    @pytest.mark.asyncio
    async def test_scrape_returns_sections_as_list(self, mock_scrape_jurisdiction):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN the sections field is a list
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="Seattle, WA",
            url="https://library.municode.com/wa/seattle"
        )
        assert isinstance(result["sections"], list)
    
    @pytest.mark.asyncio
    async def test_scrape_includes_section_number_field(self, mock_scrape_jurisdiction):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN each section has a section_number field
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="Seattle, WA",
            url="https://library.municode.com/wa/seattle"
        )
        for section in result["sections"]:
            assert "section_number" in section
    
    @pytest.mark.asyncio
    async def test_scrape_includes_title_field(self, mock_scrape_jurisdiction):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN each section has a title field
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="Seattle, WA",
            url="https://library.municode.com/wa/seattle"
        )
        for section in result["sections"]:
            assert "title" in section
    
    @pytest.mark.asyncio
    async def test_scrape_includes_text_field(self, mock_scrape_jurisdiction):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN each section has a text field
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="Seattle, WA",
            url="https://library.municode.com/wa/seattle"
        )
        for section in result["sections"]:
            assert "text" in section
    
    @pytest.mark.asyncio
    async def test_scrape_includes_source_url_field(self, mock_scrape_jurisdiction):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN each section has a source_url field
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="Seattle, WA",
            url="https://library.municode.com/wa/seattle"
        )
        for section in result["sections"]:
            assert "source_url" in section
    
    @pytest.mark.asyncio
    async def test_scrape_with_metadata_includes_scraped_at(self, mock_scrape_jurisdiction):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with include_metadata true
        THEN each section has a scraped_at field
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="Seattle, WA",
            url="https://library.municode.com/wa/seattle",
            include_metadata=True
        )
        for section in result["sections"]:
            assert "scraped_at" in section
    
    @pytest.mark.asyncio
    async def test_scrape_with_limit_respects_max_sections(self, mock_scrape_jurisdiction):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with max_sections 10
        THEN the sections field contains at most 10 sections
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="Seattle, WA",
            url="https://library.municode.com/wa/seattle",
            max_sections=10
        )
        assert len(result["sections"]) <= 10
    
    @pytest.mark.asyncio
    async def test_scrape_with_invalid_url_returns_error(self, mock_scrape_jurisdiction):
        """
        GIVEN I have an invalid jurisdiction URL
        WHEN I call scrape_jurisdiction with invalid URL
        THEN the response contains an error field
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="InvalidCity, XX",
            url="https://library.municode.com/invalid/url"
        )
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_scrape_with_invalid_url_has_empty_sections(self, mock_scrape_jurisdiction):
        """
        GIVEN I have an invalid jurisdiction URL
        WHEN I call scrape_jurisdiction with invalid URL
        THEN the sections field is empty or missing
        """
        result = await mock_scrape_jurisdiction(
            jurisdiction="InvalidCity, XX",
            url="https://library.municode.com/invalid/url"
        )
        assert result["sections"] == []


class TestBatchScrape:
    """Test suite for batch_scrape callable."""
    
    @pytest.mark.asyncio
    async def test_batch_scrape_returns_data_field(self, mock_batch_scrape):
        """
        GIVEN I have a list of jurisdictions
        WHEN I call batch_scrape with jurisdictions
        THEN the response contains a data field
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA", "Portland, OR"]
        )
        assert "data" in result
    
    @pytest.mark.asyncio
    async def test_batch_scrape_returns_correct_count(self, mock_batch_scrape):
        """
        GIVEN I have a list of 2 jurisdictions
        WHEN I call batch_scrape with jurisdictions
        THEN the data field is a list with 2 elements
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA", "Portland, OR"]
        )
        assert len(result["data"]) == 2
    
    @pytest.mark.asyncio
    async def test_batch_scrape_includes_jurisdiction_field(self, mock_batch_scrape):
        """
        GIVEN I have a list of jurisdictions
        WHEN I call batch_scrape with jurisdictions
        THEN each element has a jurisdiction field
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA", "Portland, OR"]
        )
        for element in result["data"]:
            assert "jurisdiction" in element
    
    @pytest.mark.asyncio
    async def test_batch_scrape_includes_sections_field(self, mock_batch_scrape):
        """
        GIVEN I have a list of jurisdictions
        WHEN I call batch_scrape with jurisdictions
        THEN each element has a sections field
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA", "Portland, OR"]
        )
        for element in result["data"]:
            assert "sections" in element
    
    @pytest.mark.asyncio
    async def test_batch_scrape_by_state_respects_max_jurisdictions(self, mock_batch_scrape):
        """
        GIVEN I have a list of states
        WHEN I call batch_scrape with max_jurisdictions 5
        THEN the data field contains at most 5 jurisdiction results
        """
        result = await mock_batch_scrape(
            states=["WA"],
            max_jurisdictions=5
        )
        assert len(result["data"]) <= 5
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_json_format_returns_output_format_field(self, mock_batch_scrape):
        """
        GIVEN I have a list of jurisdictions and output_format "json"
        WHEN I call batch_scrape
        THEN the response contains an output_format field with value "json"
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA"],
            output_format="json"
        )
        assert result["output_format"] == "json"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_parquet_format_returns_output_format_field(self, mock_batch_scrape):
        """
        GIVEN I have a list of jurisdictions and output_format "parquet"
        WHEN I call batch_scrape
        THEN the response contains an output_format field with value "parquet"
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA"],
            output_format="parquet"
        )
        assert result["output_format"] == "parquet"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_no_inputs_returns_error(self, mock_batch_scrape):
        """
        WHEN I call batch_scrape with no jurisdictions and no states
        THEN the response contains an error field
        """
        result = await mock_batch_scrape()
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_metadata_returns_metadata_field(self, mock_batch_scrape):
        """
        GIVEN I have a list of jurisdictions and include_metadata true
        WHEN I call batch_scrape
        THEN the response contains a metadata field
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA"],
            include_metadata=True
        )
        assert "metadata" in result
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_metadata_includes_scraped_at(self, mock_batch_scrape):
        """
        GIVEN I have a list of jurisdictions and include_metadata true
        WHEN I call batch_scrape
        THEN the metadata field contains a scraped_at field
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA"],
            include_metadata=True
        )
        assert "scraped_at" in result["metadata"]
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_metadata_includes_jurisdictions_count(self, mock_batch_scrape):
        """
        GIVEN I have a list of jurisdictions and include_metadata true
        WHEN I call batch_scrape
        THEN the metadata field contains a jurisdictions_count field
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA"],
            include_metadata=True
        )
        assert "jurisdictions_count" in result["metadata"]
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_metadata_includes_provider_field(self, mock_batch_scrape):
        """
        GIVEN I have a list of jurisdictions and include_metadata true
        WHEN I call batch_scrape
        THEN the metadata field contains a provider field with value "municode"
        """
        result = await mock_batch_scrape(
            jurisdictions=["Seattle, WA"],
            include_metadata=True
        )
        assert result["metadata"]["provider"] == "municode"


class TestErrorHandling:
    """Test suite for error handling scenarios."""
    
    @pytest.mark.asyncio
    async def test_dns_failure_returns_error_field(self, mock_dns_failure):
        """
        GIVEN DNS resolution fails
        WHEN I call scrape_jurisdiction
        THEN the response contains an error field
        """
        assert "error" in mock_dns_failure
    
    @pytest.mark.asyncio
    async def test_dns_failure_indicates_dns_error(self, mock_dns_failure):
        """
        GIVEN DNS resolution fails
        WHEN I call scrape_jurisdiction
        THEN the error field indicates a DNS resolution failure
        """
        assert mock_dns_failure["error_type"] == "dns"
    
    @pytest.mark.asyncio
    async def test_http_429_returns_error_field(self, mock_http_429):
        """
        GIVEN the server returns HTTP 429
        WHEN I call scrape_jurisdiction
        THEN the response contains an error field
        """
        assert "error" in mock_http_429
    
    @pytest.mark.asyncio
    async def test_http_429_indicates_rate_limiting(self, mock_http_429):
        """
        GIVEN the server returns HTTP 429
        WHEN I call scrape_jurisdiction
        THEN the error field indicates rate limiting occurred
        """
        assert mock_http_429["error_type"] == "rate_limit"
    
    @pytest.mark.asyncio
    async def test_http_500_returns_error_field(self, mock_http_500):
        """
        GIVEN the server returns HTTP 500
        WHEN I call scrape_jurisdiction
        THEN the response contains an error field
        """
        assert "error" in mock_http_500
    
    @pytest.mark.asyncio
    async def test_http_500_indicates_server_error(self, mock_http_500):
        """
        GIVEN the server returns HTTP 500
        WHEN I call scrape_jurisdiction
        THEN the error field indicates a server error
        """
        assert mock_http_500["error_type"] == "server_error"
    
    @pytest.mark.asyncio
    async def test_invalid_html_returns_sections_field(self, mock_invalid_html):
        """
        GIVEN the server returns malformed HTML
        WHEN I call scrape_jurisdiction
        THEN the response contains a sections field
        """
        assert "sections" in mock_invalid_html
    
    @pytest.mark.asyncio
    async def test_invalid_html_allows_empty_sections(self, mock_invalid_html):
        """
        GIVEN the server returns malformed HTML
        WHEN I call scrape_jurisdiction
        THEN the sections field may be empty
        """
        assert isinstance(mock_invalid_html["sections"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
