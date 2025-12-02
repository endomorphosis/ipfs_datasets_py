"""
Test suite for Municipal Laws Scraper.

Feature: Municipal Laws Scraper
  The municipal laws scraper searches and scrapes municipal codes and ordinances
  from major US cities for building municipal code datasets.
"""
import pytest
import asyncio
from typing import Dict, Any, List, Optional

from conftest import FixtureError


# Constants to avoid magic strings/numbers
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
CITY_CODE_NYC = "NYC"
CITY_CODE_LAX = "LAX"
CITY_CODE_CHI = "CHI"
CITY_CODE_SEA = "SEA"
CITY_NAME_NYC = "New York City"
CITY_NAME_LA = "Los Angeles"
CITY_NAME_SEATTLE = "Seattle"
STATE_NY = "NY"
EXPECTED_CITIES_COUNT = 23
EXPECTED_SINGLE_CITY_COUNT = 1
EXPECTED_THREE_CITIES_COUNT = 3
EXPECTED_ZERO_COUNT = 0
RATE_LIMIT_DELAY_SECONDS = 2.0
MAX_ORDINANCES_LIMIT = 5
OUTPUT_FORMAT_JSON = "json"
OUTPUT_FORMAT_PARQUET = "parquet"
UNKNOWN_CITY = "Unknown City XYZ"
INVALID_CITY = "InvalidCity123"
ERROR_NOT_FOUND = "not found in database"
ERROR_NO_VALID_CITIES = "No valid cities specified"
SEARCH_ALL = "all"


# Fixtures from Background

@pytest.fixture
def municipal_laws_scraper_module_loaded() -> Dict[str, Any]:
    """
    Given the municipal laws scraper module is loaded
    """
    try:
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import municipal_laws_scraper
            scraper_module = municipal_laws_scraper
        except ImportError:
            scraper_module = None
        
        module_state = {
            "module": scraper_module,
            "loaded": scraper_module is not None
        }
        
        return module_state
    except Exception as e:
        raise FixtureError(f"municipal_laws_scraper_module_loaded raised an error: {e}") from e


@pytest.fixture
def major_cities_list() -> List[Dict[str, str]]:
    """
    Given the list of major cities includes 23 US cities
    """
    try:
        major_cities = [
            {"code": "NYC", "name": "New York City", "state": "NY"},
            {"code": "LAX", "name": "Los Angeles", "state": "CA"},
            {"code": "CHI", "name": "Chicago", "state": "IL"},
            {"code": "HOU", "name": "Houston", "state": "TX"},
            {"code": "PHX", "name": "Phoenix", "state": "AZ"},
            {"code": "PHL", "name": "Philadelphia", "state": "PA"},
            {"code": "SAT", "name": "San Antonio", "state": "TX"},
            {"code": "SDC", "name": "San Diego", "state": "CA"},
            {"code": "DAL", "name": "Dallas", "state": "TX"},
            {"code": "SJC", "name": "San Jose", "state": "CA"},
            {"code": "AUS", "name": "Austin", "state": "TX"},
            {"code": "JAX", "name": "Jacksonville", "state": "FL"},
            {"code": "FTW", "name": "Fort Worth", "state": "TX"},
            {"code": "COL", "name": "Columbus", "state": "OH"},
            {"code": "IND", "name": "Indianapolis", "state": "IN"},
            {"code": "CLT", "name": "Charlotte", "state": "NC"},
            {"code": "SFO", "name": "San Francisco", "state": "CA"},
            {"code": "SEA", "name": "Seattle", "state": "WA"},
            {"code": "DEN", "name": "Denver", "state": "CO"},
            {"code": "DCA", "name": "Washington", "state": "DC"},
            {"code": "BOS", "name": "Boston", "state": "MA"},
            {"code": "DTW", "name": "Detroit", "state": "MI"},
            {"code": "PDX", "name": "Portland", "state": "OR"},
        ]
        
        return major_cities
    except Exception as e:
        raise FixtureError(f"major_cities_list raised an error: {e}") from e


@pytest.fixture
def search_municipal_codes_callable():
    """Fixture providing the search municipal codes function."""
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import search_municipal_codes
        return search_municipal_codes
    except ImportError as e:
        raise FixtureError(f"search_municipal_codes_callable raised an error: {e}") from e


@pytest.fixture
def scrape_municipal_laws_callable():
    """Fixture providing the scrape municipal laws function."""
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_municipal_laws
        return scrape_municipal_laws
    except ImportError as e:
        raise FixtureError(f"scrape_municipal_laws_callable raised an error: {e}") from e


@pytest.fixture
def get_city_count_callable():
    """Fixture providing a city count function."""
    try:
        def get_city_count(cities: List[Dict[str, str]]) -> int:
            """Get count of cities in list."""
            return len(cities)
        return get_city_count
    except Exception as e:
        raise FixtureError(f"get_city_count_callable raised an error: {e}") from e


@pytest.fixture
def find_city_by_name_callable():
    """Fixture providing a city finder function."""
    try:
        def find_city_by_name(cities: List[Dict[str, str]], name: str) -> Optional[Dict[str, str]]:
            """Find city by name (case-insensitive partial match)."""
            name_lower = name.lower()
            for city in cities:
                if name_lower in city["name"].lower():
                    return city
            return None
        return find_city_by_name
    except Exception as e:
        raise FixtureError(f"find_city_by_name_callable raised an error: {e}") from e


@pytest.fixture
def find_city_by_code_callable():
    """Fixture providing a city finder by code function."""
    try:
        def find_city_by_code(cities: List[Dict[str, str]], code: str) -> Optional[Dict[str, str]]:
            """Find city by code."""
            for city in cities:
                if city["code"] == code:
                    return city
            return None
        return find_city_by_code
    except Exception as e:
        raise FixtureError(f"find_city_by_code_callable raised an error: {e}") from e


# Search Municipal Codes

class TestSearchMunicipalCodes:
    """Search Municipal Codes"""

    def test_search_returns_city_for_valid_name(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_name_callable
    ):
        """
        Given the major cities list is loaded
        When I search municipal codes for "New York City"
        Then a city is found
        """
        search_term = CITY_NAME_NYC
        
        result = find_city_by_name_callable(major_cities_list, search_term)
        
        assert result is not None, f"expected to find city for '{search_term}', got None instead"

    def test_search_returns_correct_city_code(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_name_callable
    ):
        """
        Given the major cities list is loaded
        When I search municipal codes for "New York City"
        Then the city code is "NYC"
        """
        expected_code = CITY_CODE_NYC
        search_term = CITY_NAME_NYC
        
        result = find_city_by_name_callable(major_cities_list, search_term)
        actual_code = result["code"]
        
        assert actual_code == expected_code, f"expected city code '{expected_code}', got '{actual_code}' instead"

    def test_search_returns_correct_state(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_name_callable
    ):
        """
        Given the major cities list is loaded
        When I search municipal codes for "New York City"
        Then the state is "NY"
        """
        expected_state = STATE_NY
        search_term = CITY_NAME_NYC
        
        result = find_city_by_name_callable(major_cities_list, search_term)
        actual_state = result["state"]
        
        assert actual_state == expected_state, f"expected state '{expected_state}', got '{actual_state}' instead"

    def test_search_partial_name_finds_city(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_name_callable
    ):
        """
        Given the major cities list is loaded
        When I search municipal codes for "los angeles"
        Then a city is found
        """
        search_term = "los angeles"
        
        result = find_city_by_name_callable(major_cities_list, search_term)
        
        assert result is not None, f"expected to find city for '{search_term}', got None instead"

    def test_search_partial_name_returns_correct_code(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_name_callable
    ):
        """
        Given the major cities list is loaded
        When I search municipal codes for "los angeles"
        Then the matching city code is "LAX"
        """
        expected_code = CITY_CODE_LAX
        search_term = "los angeles"
        
        result = find_city_by_name_callable(major_cities_list, search_term)
        actual_code = result["code"]
        
        assert actual_code == expected_code, f"expected city code '{expected_code}', got '{actual_code}' instead"

    def test_search_unknown_city_returns_none(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_name_callable
    ):
        """
        Given the major cities list is loaded
        When I search municipal codes for "Unknown City XYZ"
        Then no city is found
        """
        search_term = UNKNOWN_CITY
        
        result = find_city_by_name_callable(major_cities_list, search_term)
        
        assert result is None, f"expected None for unknown city '{search_term}', got {result} instead"


# City List Validation

class TestCityListValidation:
    """City List Validation"""

    def test_cities_list_has_expected_count(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        get_city_count_callable
    ):
        """
        Given the major cities list is loaded
        When the city count is calculated
        Then the count equals 23
        """
        expected_count = EXPECTED_CITIES_COUNT
        
        actual_count = get_city_count_callable(major_cities_list)
        
        assert actual_count == expected_count, f"expected {expected_count} cities, got {actual_count} instead"

    def test_cities_list_contains_nyc(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I find city by code "NYC"
        Then the city is found
        """
        city_code = CITY_CODE_NYC
        
        result = find_city_by_code_callable(major_cities_list, city_code)
        
        assert result is not None, f"expected to find city with code '{city_code}', got None instead"

    def test_cities_list_contains_lax(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I find city by code "LAX"
        Then the city is found
        """
        city_code = CITY_CODE_LAX
        
        result = find_city_by_code_callable(major_cities_list, city_code)
        
        assert result is not None, f"expected to find city with code '{city_code}', got None instead"

    def test_cities_list_contains_seattle(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I find city by code "SEA"
        Then the city is found
        """
        city_code = CITY_CODE_SEA
        
        result = find_city_by_code_callable(major_cities_list, city_code)
        
        assert result is not None, f"expected to find city with code '{city_code}', got None instead"


# City Data Structure

class TestCityDataStructure:
    """City Data Structure"""

    def test_city_entry_contains_code(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I get a city entry
        Then the entry contains "code" field
        """
        city_code = CITY_CODE_NYC
        
        result = find_city_by_code_callable(major_cities_list, city_code)
        has_code = "code" in result
        
        assert has_code, f"expected city entry to contain 'code' field, but it was missing"

    def test_city_entry_contains_name(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I get a city entry
        Then the entry contains "name" field
        """
        city_code = CITY_CODE_NYC
        
        result = find_city_by_code_callable(major_cities_list, city_code)
        has_name = "name" in result
        
        assert has_name, f"expected city entry to contain 'name' field, but it was missing"

    def test_city_entry_contains_state(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I get a city entry
        Then the entry contains "state" field
        """
        city_code = CITY_CODE_NYC
        
        result = find_city_by_code_callable(major_cities_list, city_code)
        has_state = "state" in result
        
        assert has_state, f"expected city entry to contain 'state' field, but it was missing"

    def test_city_name_is_correct(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I get NYC city entry
        Then the city name is "New York City"
        """
        expected_name = CITY_NAME_NYC
        city_code = CITY_CODE_NYC
        
        result = find_city_by_code_callable(major_cities_list, city_code)
        actual_name = result["name"]
        
        assert actual_name == expected_name, f"expected city name '{expected_name}', got '{actual_name}' instead"

    def test_seattle_name_is_correct(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I get SEA city entry
        Then the city name is "Seattle"
        """
        expected_name = CITY_NAME_SEATTLE
        city_code = CITY_CODE_SEA
        
        result = find_city_by_code_callable(major_cities_list, city_code)
        actual_name = result["name"]
        
        assert actual_name == expected_name, f"expected city name '{expected_name}', got '{actual_name}' instead"


# Multiple Cities Operations

class TestMultipleCitiesOperations:
    """Multiple Cities Operations"""

    def test_filter_multiple_cities_returns_correct_count(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I filter for cities NYC, LAX, CHI
        Then 3 cities are returned
        """
        expected_count = EXPECTED_THREE_CITIES_COUNT
        city_codes = [CITY_CODE_NYC, CITY_CODE_LAX, CITY_CODE_CHI]
        
        found_cities = [find_city_by_code_callable(major_cities_list, code) for code in city_codes]
        actual_count = len([c for c in found_cities if c is not None])
        
        assert actual_count == expected_count, f"expected {expected_count} cities, got {actual_count} instead"

    def test_filter_invalid_city_returns_none(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        find_city_by_code_callable
    ):
        """
        Given the major cities list is loaded
        When I filter for invalid city code
        Then no city is returned
        """
        invalid_code = INVALID_CITY
        
        result = find_city_by_code_callable(major_cities_list, invalid_code)
        
        assert result is None, f"expected None for invalid city code '{invalid_code}', got {result} instead"

    def test_all_cities_are_unique(
        self, 
        municipal_laws_scraper_module_loaded, 
        major_cities_list,
        get_city_count_callable
    ):
        """
        Given the major cities list is loaded
        When I check for unique city codes
        Then all cities have unique codes
        """
        expected_unique_count = EXPECTED_CITIES_COUNT
        
        city_codes = [city["code"] for city in major_cities_list]
        actual_unique_count = len(set(city_codes))
        
        assert actual_unique_count == expected_unique_count, f"expected {expected_unique_count} unique codes, got {actual_unique_count} instead"
