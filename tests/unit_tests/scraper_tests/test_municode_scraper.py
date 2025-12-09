#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for Municode Library webscraper.

Tests are based on the Gherkin scenarios defined in test_municode_scraper.feature.
Each test corresponds to a specific scenario from the feature file.
"""
import pytest


# Import directly from the module file
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municode_scraper import (
    search_jurisdictions,
    get_municode_jurisdictions,
    scrape_jurisdiction,
    batch_scrape
)


# Test Data Fixtures - Common test values used across multiple tests
@pytest.fixture
def state_wa():
    """Washington state code."""
    return "WA"


@pytest.fixture
def state_ca():
    """California state code."""
    return "CA"


@pytest.fixture
def limit_10():
    """Standard limit of 10 items."""
    return 10


@pytest.fixture
def limit_5():
    """Reduced limit of 5 items."""
    return 5


@pytest.fixture
def jurisdiction_seattle():
    """Seattle jurisdiction name (short form)."""
    return "Seattle"


@pytest.fixture
def jurisdiction_seattle_wa():
    """Seattle jurisdiction name (full form)."""
    return "Seattle, WA"


@pytest.fixture
def jurisdiction_url_seattle():
    """URL for Seattle jurisdiction."""
    return "https://library.municode.com/wa/seattle"


@pytest.fixture
def invalid_jurisdiction_url():
    """Invalid jurisdiction URL for error testing."""
    return "https://library.municode.com/invalid/url"


@pytest.fixture
def keyword_zoning():
    """Search keyword for zoning."""
    return "zoning"


@pytest.fixture
def invalid_jurisdiction_name():
    """Invalid jurisdiction name for negative testing."""
    return "NonexistentCity12345"


@pytest.fixture
def invalid_city_jurisdiction():
    """Invalid city jurisdiction for error testing."""
    return "InvalidCity, XX"


@pytest.fixture
def jurisdictions_list_two():
    """List of two jurisdictions for batch testing."""
    return ["Seattle, WA", "Portland, OR"]


@pytest.fixture
def jurisdictions_list_one():
    """List of one jurisdiction for batch testing."""
    return ["Seattle, WA"]


@pytest.fixture
def states_list_wa():
    """List containing Washington state."""
    return ["WA"]


@pytest.fixture
def output_format_json():
    """JSON output format."""
    return "json"


@pytest.fixture
def output_format_parquet():
    """Parquet output format."""
    return "parquet"


@pytest.fixture
def include_metadata_true():
    """Flag to include metadata."""
    return True


@pytest.fixture
def max_sections_10():
    """Maximum of 10 sections."""
    return 10


@pytest.fixture
def max_jurisdictions_5():
    """Maximum of 5 jurisdictions."""
    return 5


class TestSearchJurisdictions:
    """Test suite for search_jurisdictions callable."""
    
    @pytest.mark.asyncio
    async def test_search_by_state_returns_list(self, mock_search_jurisdictions, state_wa, limit_10):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN the response contains a list of jurisdictions
        """
        result = await mock_search_jurisdictions(state=state_wa, limit=limit_10)
        
        expected_key = "jurisdictions"
        actual_has_key = expected_key in result
        assert actual_has_key, f"expected key {expected_key} in result but got {result}"
    
    @pytest.mark.asyncio
    async def test_search_by_state_respects_limit(self, mock_search_jurisdictions, state_wa, limit_10):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN the list contains at most 10 jurisdictions
        """
        result = await mock_search_jurisdictions(state=state_wa, limit=limit_10)
        
        actual_count = len(result["jurisdictions"])
        expected_max = limit_10
        assert actual_count <= expected_max, f"expected at most {expected_max} jurisdictions but got {actual_count}"
    
    @pytest.mark.asyncio
    async def test_search_by_state_includes_name_field(self, mock_search_jurisdictions, state_wa, limit_10):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN each jurisdiction has a name field
        """
        result = await mock_search_jurisdictions(state=state_wa, limit=limit_10)
        
        expected_field = "name"
        actual_all_have_field = all(expected_field in j for j in result["jurisdictions"])
        assert actual_all_have_field, f"expected all jurisdictions to have {expected_field} field but got {result}"
    
    @pytest.mark.asyncio
    async def test_search_by_state_includes_state_field(self, mock_search_jurisdictions, state_wa, limit_10):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN each jurisdiction has a state field with value "WA"
        """
        result = await mock_search_jurisdictions(state=state_wa, limit=limit_10)
        
        expected_state_value = state_wa
        actual_all_match = all(j["state"] == expected_state_value for j in result["jurisdictions"])
        assert actual_all_match, f"expected all jurisdictions to have state {expected_state_value} but got {result}"
    
    @pytest.mark.asyncio
    async def test_search_by_state_includes_url_field(self, mock_search_jurisdictions, state_wa, limit_10):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN each jurisdiction has a url field
        """
        result = await mock_search_jurisdictions(state=state_wa, limit=limit_10)
        
        expected_field = "url"
        actual_all_have_field = all(expected_field in j for j in result["jurisdictions"])
        assert actual_all_have_field, f"expected all jurisdictions to have {expected_field} field but got {result}"

    @pytest.mark.asyncio
    async def test_search_by_state_includes_provider_field(self, mock_search_jurisdictions, state_wa, limit_10):
        """
        GIVEN I have a valid two-letter state code "WA"
        WHEN I call search_jurisdictions with state "WA" and limit 10
        THEN each jurisdiction has a provider field with value "municode"
        """
        result = await mock_search_jurisdictions(state=state_wa, limit=limit_10)
        
        expected_provider_value = "municode"
        actual_all_match = all(j["provider"] == expected_provider_value for j in result["jurisdictions"])
        assert actual_all_match, f"expected all jurisdictions to have provider {expected_provider_value} but got {result}"

    @pytest.mark.asyncio
    async def test_search_by_name_returns_list(self, mock_search_jurisdictions, jurisdiction_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle"
        WHEN I call search_jurisdictions with jurisdiction "Seattle"
        THEN the response contains a list of jurisdictions
        """
        result = await mock_search_jurisdictions(jurisdiction=jurisdiction_seattle)
        
        expected_key = "jurisdictions"
        actual_has_key = expected_key in result
        assert actual_has_key, f"expected key {expected_key} in result but got {result}"

    @pytest.mark.asyncio
    async def test_search_by_name_filters_by_name(self, mock_search_jurisdictions, jurisdiction_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle"
        WHEN I call search_jurisdictions with jurisdiction "Seattle"
        THEN each jurisdiction name contains "Seattle"
        """
        result = await mock_search_jurisdictions(jurisdiction=jurisdiction_seattle)
        
        expected_substring = jurisdiction_seattle
        actual_all_contain = all(expected_substring in j["name"] for j in result["jurisdictions"])
        assert actual_all_contain, f"expected all jurisdictions to contain {expected_substring} but got {result}"

    @pytest.mark.asyncio
    async def test_search_by_name_includes_url_field(self, mock_search_jurisdictions, jurisdiction_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle"
        WHEN I call search_jurisdictions with jurisdiction "Seattle"
        THEN each jurisdiction has a url field
        """
        result = await mock_search_jurisdictions(jurisdiction=jurisdiction_seattle)
        
        expected_field = "url"
        actual_all_have_field = all(expected_field in j for j in result["jurisdictions"])
        assert actual_all_have_field, f"expected all jurisdictions to have {expected_field} field but got {result}"

    @pytest.mark.asyncio
    async def test_search_by_name_includes_provider_field(self, mock_search_jurisdictions, jurisdiction_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle"
        WHEN I call search_jurisdictions with jurisdiction "Seattle"
        THEN each jurisdiction has a provider field with value "municode"
        """
        result = await mock_search_jurisdictions(jurisdiction=jurisdiction_seattle)
        
        expected_provider_value = "municode"
        actual_all_match = all(j["provider"] == expected_provider_value for j in result["jurisdictions"])
        assert actual_all_match, f"expected all jurisdictions to have provider {expected_provider_value} but got {result}"

    @pytest.mark.asyncio
    async def test_search_by_keywords_returns_list(self, mock_search_jurisdictions, keyword_zoning):
        """
        GIVEN I have a search keyword "zoning"
        WHEN I call search_jurisdictions with keywords "zoning"
        THEN the response contains a list of jurisdictions
        """
        result = await mock_search_jurisdictions(keywords=keyword_zoning)
        
        expected_key = "jurisdictions"
        actual_has_key = expected_key in result
        assert actual_has_key, f"expected key {expected_key} in result but got {result}"

    @pytest.mark.asyncio
    async def test_search_by_keywords_includes_url_field(self, mock_search_jurisdictions, keyword_zoning):
        """
        GIVEN I have a search keyword "zoning"
        WHEN I call search_jurisdictions with keywords "zoning"
        THEN each jurisdiction has a url field
        """
        result = await mock_search_jurisdictions(keywords=keyword_zoning)
        
        expected_field = "url"
        actual_all_have_field = all(expected_field in j for j in result["jurisdictions"])
        assert actual_all_have_field, f"expected all jurisdictions to have {expected_field} field but got {result}"

    @pytest.mark.asyncio
    async def test_search_by_keywords_includes_provider_field(self, mock_search_jurisdictions, keyword_zoning):
        """
        GIVEN I have a search keyword "zoning"
        WHEN I call search_jurisdictions with keywords "zoning"
        THEN each jurisdiction has a provider field with value "municode"
        """
        result = await mock_search_jurisdictions(keywords=keyword_zoning)
        
        expected_provider_value = "municode"
        actual_all_match = all(j["provider"] == expected_provider_value for j in result["jurisdictions"])
        assert actual_all_match, f"expected all jurisdictions to have provider {expected_provider_value} but got {result}"

    @pytest.mark.asyncio
    async def test_search_with_no_results(self, mock_search_jurisdictions, invalid_jurisdiction_name):
        """
        GIVEN I have an invalid jurisdiction name "NonexistentCity12345"
        WHEN I call search_jurisdictions with jurisdiction "NonexistentCity12345"
        THEN the response contains an empty list of jurisdictions
        """
        result = await mock_search_jurisdictions(jurisdiction=invalid_jurisdiction_name)
        
        expected_count = 0
        actual_count = len(result["jurisdictions"])
        assert actual_count == expected_count, f"expected {expected_count} jurisdictions but got {actual_count}"

    @pytest.mark.asyncio
    async def test_search_with_state_and_limit_returns_list(self, mock_search_jurisdictions, state_ca, limit_5):
        """
        GIVEN I have a valid two-letter state code "CA"
        WHEN I call search_jurisdictions with state "CA" and limit 5
        THEN the response contains a list of jurisdictions
        """
        result = await mock_search_jurisdictions(state=state_ca, limit=limit_5)
        
        expected_key = "jurisdictions"
        actual_has_key = expected_key in result
        assert actual_has_key, f"expected key {expected_key} in result but got {result}"

    @pytest.mark.asyncio
    async def test_search_with_state_and_limit_respects_limit(self, mock_search_jurisdictions, state_ca, limit_5):
        """
        GIVEN I have a valid two-letter state code "CA"
        WHEN I call search_jurisdictions with state "CA" and limit 5
        THEN the list contains at most 5 jurisdictions
        """
        result = await mock_search_jurisdictions(state=state_ca, limit=limit_5)
        
        actual_count = len(result["jurisdictions"])
        expected_max = limit_5
        assert actual_count <= expected_max, f"expected at most {expected_max} jurisdictions but got {actual_count}"

    @pytest.mark.asyncio
    async def test_search_with_state_and_limit_filters_by_state(self, mock_search_jurisdictions, state_ca, limit_5):
        """
        GIVEN I have a valid two-letter state code "CA"
        WHEN I call search_jurisdictions with state "CA" and limit 5
        THEN each jurisdiction has a state field with value "CA"
        """
        result = await mock_search_jurisdictions(state=state_ca, limit=limit_5)
        
        expected_state_value = state_ca
        actual_all_match = all(j["state"] == expected_state_value for j in result["jurisdictions"])
        assert actual_all_match, f"expected all jurisdictions to have state {expected_state_value} but got {result}"


class TestScrapeJurisdiction:
    """Test suite for scrape_jurisdiction callable."""
    
    @pytest.mark.asyncio
    async def test_scrape_returns_jurisdiction_field(self, mock_scrape_jurisdiction, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN the response contains a jurisdiction field with value "Seattle, WA"
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_jurisdiction_value = jurisdiction_seattle_wa
        actual_jurisdiction_value = result["jurisdiction"]
        assert actual_jurisdiction_value == expected_jurisdiction_value, f"expected {expected_jurisdiction_value} but got {actual_jurisdiction_value}"
    
    @pytest.mark.asyncio
    async def test_scrape_returns_sections_field(self, mock_scrape_jurisdiction, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN the response contains a sections field
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_field = "sections"
        actual_has_field = expected_field in result
        assert actual_has_field, f"expected field {expected_field} in result but got {result}"
    
    @pytest.mark.asyncio
    async def test_scrape_returns_sections_as_list(self, mock_scrape_jurisdiction, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN the sections field is a list
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_type = list
        actual_is_list = isinstance(result["sections"], expected_type)
        assert actual_is_list, f"expected sections to be {expected_type} but got {type(result['sections'])}"
    
    @pytest.mark.asyncio
    async def test_scrape_includes_section_number_field(self, mock_scrape_jurisdiction, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN each section has a section_number field
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_field = "section_number"
        actual_all_have_field = all(expected_field in s for s in result["sections"])
        assert actual_all_have_field, f"expected all sections to have {expected_field} field but got {result}"
    
    @pytest.mark.asyncio
    async def test_scrape_includes_title_field(self, mock_scrape_jurisdiction, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN each section has a title field
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_field = "title"
        actual_all_have_field = all(expected_field in s for s in result["sections"])
        assert actual_all_have_field, f"expected all sections to have {expected_field} field but got {result}"
    
    @pytest.mark.asyncio
    async def test_scrape_includes_text_field(self, mock_scrape_jurisdiction, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN each section has a text field
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_field = "text"
        actual_all_have_field = all(expected_field in s for s in result["sections"])
        assert actual_all_have_field, f"expected all sections to have {expected_field} field but got {result}"
    
    @pytest.mark.asyncio
    async def test_scrape_includes_source_url_field(self, mock_scrape_jurisdiction, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url
        THEN each section has a source_url field
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_field = "source_url"
        actual_all_have_field = all(expected_field in s for s in result["sections"])
        assert actual_all_have_field, f"expected all sections to have {expected_field} field but got {result}"
    
    @pytest.mark.asyncio
    async def test_scrape_with_metadata_includes_scraped_at(self, mock_scrape_jurisdiction, jurisdiction_seattle_wa, jurisdiction_url_seattle, include_metadata_true):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with include_metadata true
        THEN each section has a scraped_at field
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=jurisdiction_url_seattle, include_metadata=include_metadata_true)
        
        expected_field = "scraped_at"
        actual_all_have_field = all(expected_field in s for s in result["sections"])
        assert actual_all_have_field, f"expected all sections to have {expected_field} field but got {result}"
    
    @pytest.mark.asyncio
    async def test_scrape_with_limit_respects_max_sections(self, mock_scrape_jurisdiction, jurisdiction_seattle_wa, jurisdiction_url_seattle, max_sections_10):
        """
        GIVEN I have a jurisdiction name "Seattle, WA"
        WHEN I call scrape_jurisdiction with max_sections 10
        THEN the sections field contains at most 10 sections
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=jurisdiction_url_seattle, max_sections=max_sections_10)
        
        actual_count = len(result["sections"])
        expected_max = max_sections_10
        assert actual_count <= expected_max, f"expected at most {expected_max} sections but got {actual_count}"
    
    @pytest.mark.asyncio
    async def test_scrape_with_invalid_url_returns_error(self, mock_scrape_jurisdiction, invalid_city_jurisdiction, invalid_jurisdiction_url):
        """
        GIVEN I have an invalid jurisdiction URL
        WHEN I call scrape_jurisdiction with invalid URL
        THEN the response contains an error field
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=invalid_jurisdiction_url)
        
        expected_field = "error"
        actual_has_field = expected_field in result
        assert actual_has_field, f"expected field {expected_field} in result but got {result}"
    
    @pytest.mark.asyncio
    async def test_scrape_with_invalid_url_has_empty_sections(self, mock_scrape_jurisdiction, invalid_city_jurisdiction, invalid_jurisdiction_url):
        """
        GIVEN I have an invalid jurisdiction URL
        WHEN I call scrape_jurisdiction with invalid URL
        THEN the sections field is empty or missing
        """
        result = await mock_scrape_jurisdiction(jurisdiction_url=invalid_jurisdiction_url)
        
        expected_count = 0
        actual_count = len(result["sections"])
        assert actual_count == expected_count, f"expected {expected_count} sections but got {actual_count}"


class TestBatchScrape:
    """Test suite for batch_scrape callable."""
    
    @pytest.mark.asyncio
    async def test_batch_scrape_returns_data_field(self, mock_batch_scrape, jurisdictions_list_two):
        """
        GIVEN I have a list of jurisdictions
        WHEN I call batch_scrape with jurisdictions
        THEN the response contains a data field
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_two)
        
        expected_field = "data"
        actual_has_field = expected_field in result
        assert actual_has_field, f"expected field {expected_field} in result but got {result}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_returns_correct_count(self, mock_batch_scrape, jurisdictions_list_two):
        """
        GIVEN I have a list of 2 jurisdictions
        WHEN I call batch_scrape with jurisdictions
        THEN the data field is a list with 2 elements
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_two)
        
        expected_count = 2
        actual_count = len(result["data"])
        assert actual_count == expected_count, f"expected {expected_count} elements but got {actual_count}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_includes_jurisdiction_field(self, mock_batch_scrape, jurisdictions_list_two):
        """
        GIVEN I have a list of jurisdictions
        WHEN I call batch_scrape with jurisdictions
        THEN each element has a jurisdiction field
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_two)
        
        expected_field = "jurisdiction"
        actual_all_have_field = all(expected_field in elem for elem in result["data"])
        assert actual_all_have_field, f"expected all elements to have {expected_field} field but got {result}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_includes_sections_field(self, mock_batch_scrape, jurisdictions_list_two):
        """
        GIVEN I have a list of jurisdictions
        WHEN I call batch_scrape with jurisdictions
        THEN each element has a sections field
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_two)
        
        expected_field = "sections"
        actual_all_have_field = all(expected_field in elem for elem in result["data"])
        assert actual_all_have_field, f"expected all elements to have {expected_field} field but got {result}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_by_state_respects_max_jurisdictions(self, mock_batch_scrape, states_list_wa, max_jurisdictions_5):
        """
        GIVEN I have a list of states
        WHEN I call batch_scrape with max_jurisdictions 5
        THEN the data field contains at most 5 jurisdiction results
        """
        result = await mock_batch_scrape(states=states_list_wa, max_jurisdictions=max_jurisdictions_5)
        
        actual_count = len(result["data"])
        expected_max = max_jurisdictions_5
        assert actual_count <= expected_max, f"expected at most {expected_max} results but got {actual_count}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_json_format_returns_output_format_field(self, mock_batch_scrape, jurisdictions_list_one, output_format_json):
        """
        GIVEN I have a list of jurisdictions and output_format "json"
        WHEN I call batch_scrape
        THEN the response contains an output_format field with value "json"
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_one, output_format=output_format_json)
        
        expected_format_value = output_format_json
        actual_format_value = result["output_format"]
        assert actual_format_value == expected_format_value, f"expected {expected_format_value} but got {actual_format_value}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_parquet_format_returns_output_format_field(self, mock_batch_scrape, jurisdictions_list_one, output_format_parquet):
        """
        GIVEN I have a list of jurisdictions and output_format "parquet"
        WHEN I call batch_scrape
        THEN the response contains an output_format field with value "parquet"
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_one, output_format=output_format_parquet)
        
        expected_format_value = output_format_parquet
        actual_format_value = result["output_format"]
        assert actual_format_value == expected_format_value, f"expected {expected_format_value} but got {actual_format_value}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_no_inputs_returns_error(self):
        """
        WHEN I call batch_scrape with no jurisdictions and no states
        THEN a ValueError is raised
        """
        with pytest.raises(ValueError, match="Either jurisdictions or states must be provided"):
            await batch_scrape()
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_metadata_returns_metadata_field(self, mock_batch_scrape, jurisdictions_list_one, include_metadata_true):
        """
        GIVEN I have a list of jurisdictions and include_metadata true
        WHEN I call batch_scrape
        THEN the response contains a metadata field
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_one, include_metadata=include_metadata_true)
        
        expected_field = "metadata"
        actual_has_field = expected_field in result
        assert actual_has_field, f"expected field {expected_field} in result but got {result}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_metadata_includes_scraped_at(self, mock_batch_scrape, jurisdictions_list_one, include_metadata_true):
        """
        GIVEN I have a list of jurisdictions and include_metadata true
        WHEN I call batch_scrape
        THEN the metadata field contains a scraped_at field
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_one, include_metadata=include_metadata_true)
        
        expected_field = "scraped_at"
        actual_has_field = expected_field in result["metadata"]
        assert actual_has_field, f"expected field {expected_field} in metadata but got {result}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_metadata_includes_jurisdictions_count(self, mock_batch_scrape, jurisdictions_list_one, include_metadata_true):
        """
        GIVEN I have a list of jurisdictions and include_metadata true
        WHEN I call batch_scrape
        THEN the metadata field contains a jurisdictions_count field
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_one, include_metadata=include_metadata_true)
        
        expected_field = "jurisdictions_count"
        actual_has_field = expected_field in result["metadata"]
        assert actual_has_field, f"expected field {expected_field} in metadata but got {result}"
    
    @pytest.mark.asyncio
    async def test_batch_scrape_with_metadata_includes_provider_field(self, mock_batch_scrape, jurisdictions_list_one, include_metadata_true):
        """
        GIVEN I have a list of jurisdictions and include_metadata true
        WHEN I call batch_scrape
        THEN the metadata field contains a provider field with value "municode"
        """
        result = await mock_batch_scrape(jurisdictions=jurisdictions_list_one, include_metadata=include_metadata_true)
        
        expected_provider_value = "municode"
        actual_provider_value = result["metadata"]["provider"]
        assert actual_provider_value == expected_provider_value, f"expected {expected_provider_value} but got {actual_provider_value}"


class TestErrorHandling:
    """Test suite for error handling scenarios."""
    
    @pytest.mark.asyncio
    async def test_dns_failure_returns_error_field(self, mock_scrape_jurisdiction_dns_failure, invalid_city_jurisdiction, invalid_jurisdiction_url):
        """
        GIVEN DNS resolution fails
        WHEN I call scrape_jurisdiction
        THEN the response contains an error field
        """
        result = await mock_scrape_jurisdiction_dns_failure(jurisdiction_url=invalid_jurisdiction_url)
        
        expected_field = "error"
        actual_has_field = expected_field in result
        assert actual_has_field, f"expected field {expected_field} in result but got {result}"
    
    @pytest.mark.asyncio
    async def test_dns_failure_indicates_dns_error(self, mock_scrape_jurisdiction_dns_failure, invalid_city_jurisdiction, invalid_jurisdiction_url):
        """
        GIVEN DNS resolution fails
        WHEN I call scrape_jurisdiction
        THEN the error field indicates a DNS resolution failure
        """
        result = await mock_scrape_jurisdiction_dns_failure(jurisdiction_url=invalid_jurisdiction_url)
        
        expected_error_type = "dns"
        actual_error_type = result["error_type"]
        assert actual_error_type == expected_error_type, f"expected error_type {expected_error_type} but got {actual_error_type}"
    
    @pytest.mark.asyncio
    async def test_http_429_returns_error_field(self, mock_scrape_jurisdiction_http_429, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN the server returns HTTP 429
        WHEN I call scrape_jurisdiction
        THEN the response contains an error field
        """
        result = await mock_scrape_jurisdiction_http_429(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_field = "error"
        actual_has_field = expected_field in result
        assert actual_has_field, f"expected field {expected_field} in result but got {result}"
    
    @pytest.mark.asyncio
    async def test_http_429_indicates_rate_limiting(self, mock_scrape_jurisdiction_http_429, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN the server returns HTTP 429
        WHEN I call scrape_jurisdiction
        THEN the error field indicates rate limiting occurred
        """
        result = await mock_scrape_jurisdiction_http_429(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_error_type = "rate_limit"
        actual_error_type = result["error_type"]
        assert actual_error_type == expected_error_type, f"expected error_type {expected_error_type} but got {actual_error_type}"
    
    @pytest.mark.asyncio
    async def test_http_500_returns_error_field(self, mock_scrape_jurisdiction_http_500, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN the server returns HTTP 500
        WHEN I call scrape_jurisdiction
        THEN the response contains an error field
        """
        result = await mock_scrape_jurisdiction_http_500(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_field = "error"
        actual_has_field = expected_field in result
        assert actual_has_field, f"expected field {expected_field} in result but got {result}"
    
    @pytest.mark.asyncio
    async def test_http_500_indicates_server_error(self, mock_scrape_jurisdiction_http_500, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN the server returns HTTP 500
        WHEN I call scrape_jurisdiction
        THEN the error field indicates a server error
        """
        result = await mock_scrape_jurisdiction_http_500(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_error_type = "server_error"
        actual_error_type = result["error_type"]
        assert actual_error_type == expected_error_type, f"expected error_type {expected_error_type} but got {actual_error_type}"
    
    @pytest.mark.asyncio
    async def test_invalid_html_returns_sections_field(self, mock_scrape_jurisdiction_invalid_html, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN the server returns malformed HTML
        WHEN I call scrape_jurisdiction
        THEN the response contains a sections field
        """
        result = await mock_scrape_jurisdiction_invalid_html(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_field = "sections"
        actual_has_field = expected_field in result
        assert actual_has_field, f"expected field {expected_field} in result but got {result}"
    
    @pytest.mark.asyncio
    async def test_invalid_html_allows_empty_sections(self, mock_scrape_jurisdiction_invalid_html, jurisdiction_seattle_wa, jurisdiction_url_seattle):
        """
        GIVEN the server returns malformed HTML
        WHEN I call scrape_jurisdiction
        THEN the sections field may be empty
        """
        result = await mock_scrape_jurisdiction_invalid_html(jurisdiction_url=jurisdiction_url_seattle)
        
        expected_type = list
        actual_is_list = isinstance(result["sections"], expected_type)
        assert actual_is_list, f"expected sections to be {expected_type} but got {type(result['sections'])}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
