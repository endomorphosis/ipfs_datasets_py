#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for patent scraper module.

GIVEN: A patent scraper is initialized
WHEN: Search requests are made to USPTO PatentsView API
THEN: Patent data should be retrieved and parsed correctly
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import asdict

from ipfs_datasets_py.mcp_tools.tools.patent_scraper import (
    USPTOPatentScraper,
    PatentSearchCriteria,
    PatentDatasetBuilder,
    Patent,
    search_patents_by_keyword,
    search_patents_by_inventor,
    search_patents_by_assignee
)


# Test data
MOCK_PATENT_RESPONSE = {
    "patents": [
        {
            "patent_number": "US1234567",
            "patent_title": "Method for artificial intelligence processing",
            "patent_abstract": "A method for processing data using AI algorithms",
            "patent_date": "2024-01-15",
            "app_number": "16/123456",
            "app_date": "2022-06-01",
            "inventors": [
                {
                    "inventor_first_name": "John",
                    "inventor_last_name": "Smith"
                }
            ],
            "assignees": [
                {
                    "assignee_organization": "TechCorp Inc"
                }
            ],
            "cpcs": [
                {
                    "cpc_subgroup_id": "G06F"
                }
            ],
            "cited_patents": [
                {
                    "cited_patent_number": "US9876543"
                }
            ]
        }
    ]
}


class TestPatentSearchCriteria:
    """Tests for PatentSearchCriteria dataclass."""
    
    def test_create_basic_criteria(self):
        """
        GIVEN: Basic search parameters
        WHEN: Creating PatentSearchCriteria
        THEN: Criteria object should be created with defaults
        """
        criteria = PatentSearchCriteria(keywords=["AI", "machine learning"])
        
        assert criteria.keywords == ["AI", "machine learning"]
        assert criteria.limit == 100
        assert criteria.offset == 0
        assert criteria.inventor_name is None
    
    def test_create_full_criteria(self):
        """
        GIVEN: All search parameters
        WHEN: Creating PatentSearchCriteria
        THEN: Criteria object should contain all parameters
        """
        criteria = PatentSearchCriteria(
            keywords=["AI"],
            inventor_name="Smith",
            assignee_name="TechCorp",
            patent_number="US1234567",
            date_from="2020-01-01",
            date_to="2024-12-31",
            cpc_classification=["G06F"],
            limit=50,
            offset=10
        )
        
        assert criteria.keywords == ["AI"]
        assert criteria.inventor_name == "Smith"
        assert criteria.assignee_name == "TechCorp"
        assert criteria.patent_number == "US1234567"
        assert criteria.date_from == "2020-01-01"
        assert criteria.date_to == "2024-12-31"
        assert criteria.cpc_classification == ["G06F"]
        assert criteria.limit == 50
        assert criteria.offset == 10


class TestUSPTOPatentScraper:
    """Tests for USPTOPatentScraper class."""
    
    def test_scraper_initialization(self):
        """
        GIVEN: A rate limit delay
        WHEN: Initializing USPTOPatentScraper
        THEN: Scraper should be created with proper configuration
        """
        scraper = USPTOPatentScraper(rate_limit_delay=2.0)
        
        assert scraper.rate_limit_delay == 2.0
        assert scraper.session is not None
        assert scraper.last_request_time == 0
    
    def test_build_query_keywords(self):
        """
        GIVEN: Search criteria with keywords
        WHEN: Building API query
        THEN: Query should contain keyword search
        """
        scraper = USPTOPatentScraper()
        criteria = PatentSearchCriteria(keywords=["AI", "machine learning"])
        
        query = scraper._build_query(criteria)
        
        assert "_or" in query or "_text_any" in query
    
    def test_build_query_inventor(self):
        """
        GIVEN: Search criteria with inventor name
        WHEN: Building API query
        THEN: Query should contain inventor filter
        """
        scraper = USPTOPatentScraper()
        criteria = PatentSearchCriteria(inventor_name="Smith")
        
        query = scraper._build_query(criteria)
        
        assert "inventor_last_name" in query or "_and" in query
    
    def test_build_query_date_range(self):
        """
        GIVEN: Search criteria with date range
        WHEN: Building API query
        THEN: Query should contain date filter
        """
        scraper = USPTOPatentScraper()
        criteria = PatentSearchCriteria(
            date_from="2020-01-01",
            date_to="2024-12-31"
        )
        
        query = scraper._build_query(criteria)
        
        assert "patent_date" in query or "_and" in query
    
    @patch('ipfs_datasets_py.mcp_tools.tools.patent_scraper.requests.Session.post')
    def test_search_patents_success(self, mock_post):
        """
        GIVEN: Mock successful API response
        WHEN: Searching patents
        THEN: Patents should be parsed and returned
        """
        # Setup mock
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_PATENT_RESPONSE
        mock_post.return_value = mock_response
        
        # Search
        scraper = USPTOPatentScraper(rate_limit_delay=0.1)
        criteria = PatentSearchCriteria(keywords=["AI"])
        patents = scraper.search_patents(criteria)
        
        # Verify
        assert len(patents) == 1
        assert patents[0].patent_number == "US1234567"
        assert patents[0].patent_title == "Method for artificial intelligence processing"
        assert len(patents[0].inventors) == 1
        assert patents[0].inventors[0]["last_name"] == "Smith"
    
    @patch('ipfs_datasets_py.mcp_tools.tools.patent_scraper.requests.Session.post')
    def test_search_patents_error(self, mock_post):
        """
        GIVEN: Mock API error
        WHEN: Searching patents
        THEN: Exception should be raised
        """
        # Setup mock to raise exception
        mock_post.side_effect = Exception("API Error")
        
        # Search should raise exception
        scraper = USPTOPatentScraper(rate_limit_delay=0.1)
        criteria = PatentSearchCriteria(keywords=["AI"])
        
        with pytest.raises(Exception):
            scraper.search_patents(criteria)
    
    def test_parse_patent(self):
        """
        GIVEN: Raw patent data from API
        WHEN: Parsing patent
        THEN: Patent object should be created with all fields
        """
        scraper = USPTOPatentScraper()
        patent_data = MOCK_PATENT_RESPONSE["patents"][0]
        
        patent = scraper._parse_patent(patent_data)
        
        assert isinstance(patent, Patent)
        assert patent.patent_number == "US1234567"
        assert patent.patent_title == "Method for artificial intelligence processing"
        assert patent.patent_abstract is not None
        assert len(patent.inventors) == 1
        assert len(patent.assignees) == 1
        assert len(patent.cpc_classifications) == 1
        assert len(patent.citations) == 1


class TestPatentDatasetBuilder:
    """Tests for PatentDatasetBuilder class."""
    
    @patch('ipfs_datasets_py.mcp_tools.tools.patent_scraper.USPTOPatentScraper.search_patents')
    def test_build_dataset_json(self, mock_search):
        """
        GIVEN: Mock patent search results
        WHEN: Building dataset in JSON format
        THEN: Dataset should be created with metadata
        """
        # Setup mock
        mock_patent = Patent(
            patent_number="US1234567",
            patent_title="Test Patent",
            patent_abstract="Test abstract"
        )
        mock_search.return_value = [mock_patent]
        
        # Build dataset
        scraper = USPTOPatentScraper()
        builder = PatentDatasetBuilder(scraper)
        criteria = PatentSearchCriteria(keywords=["AI"])
        
        result = builder.build_dataset(criteria, output_format="json")
        
        # Verify
        assert result["status"] == "success"
        assert result["metadata"]["patent_count"] == 1
        assert result["metadata"]["source"] == "USPTO PatentsView API"
        assert len(result["patents"]) == 1
    
    @patch('ipfs_datasets_py.mcp_tools.tools.patent_scraper.USPTOPatentScraper.search_patents')
    @patch('builtins.open', create=True)
    def test_build_dataset_with_output_file(self, mock_open, mock_search):
        """
        GIVEN: Mock patent search results and output path
        WHEN: Building dataset with file output
        THEN: Dataset should be saved to file
        """
        # Setup mocks
        mock_patent = Patent(
            patent_number="US1234567",
            patent_title="Test Patent"
        )
        mock_search.return_value = [mock_patent]
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file
        
        # Build dataset
        scraper = USPTOPatentScraper()
        builder = PatentDatasetBuilder(scraper)
        criteria = PatentSearchCriteria(keywords=["AI"])
        
        from pathlib import Path
        result = builder.build_dataset(
            criteria,
            output_format="json",
            output_path=Path("/tmp/test_patents.json")
        )
        
        # Verify
        assert result["status"] == "success"
        assert result["metadata"]["output_path"] is not None


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    @patch('ipfs_datasets_py.mcp_tools.tools.patent_scraper.USPTOPatentScraper.search_patents')
    def test_search_by_keyword(self, mock_search):
        """
        GIVEN: Keyword list
        WHEN: Using search_patents_by_keyword
        THEN: Patents should be returned
        """
        mock_patent = Patent(
            patent_number="US1234567",
            patent_title="Test Patent"
        )
        mock_search.return_value = [mock_patent]
        
        patents = search_patents_by_keyword(["AI"], limit=10, rate_limit_delay=0.1)
        
        assert len(patents) == 1
        assert patents[0].patent_number == "US1234567"
    
    @patch('ipfs_datasets_py.mcp_tools.tools.patent_scraper.USPTOPatentScraper.search_patents')
    def test_search_by_inventor(self, mock_search):
        """
        GIVEN: Inventor name
        WHEN: Using search_patents_by_inventor
        THEN: Patents should be returned
        """
        mock_patent = Patent(
            patent_number="US1234567",
            patent_title="Test Patent"
        )
        mock_search.return_value = [mock_patent]
        
        patents = search_patents_by_inventor("Smith", limit=10, rate_limit_delay=0.1)
        
        assert len(patents) == 1
    
    @patch('ipfs_datasets_py.mcp_tools.tools.patent_scraper.USPTOPatentScraper.search_patents')
    def test_search_by_assignee(self, mock_search):
        """
        GIVEN: Assignee name
        WHEN: Using search_patents_by_assignee
        THEN: Patents should be returned
        """
        mock_patent = Patent(
            patent_number="US1234567",
            patent_title="Test Patent"
        )
        mock_search.return_value = [mock_patent]
        
        patents = search_patents_by_assignee("TechCorp", limit=10, rate_limit_delay=0.1)
        
        assert len(patents) == 1
