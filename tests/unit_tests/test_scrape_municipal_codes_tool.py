#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for ScrapeMunicipalCodesTool MCP tool.

This test suite validates the municipal code scraping tool that integrates
the scrape_the_law_mk3 submodule as an MCP tool.

Test Coverage:
- Tool initialization and schema
- Parameter validation
- Job ID generation
- Jurisdiction handling
- Error handling
- Integration with scrape_the_law_mk3
"""

import pytest
import anyio
from typing import Dict, Any


class TestScrapeMunicipalCodesTool:
    """Test suite for municipal codes scraping MCP tool."""
    
    @pytest.fixture
    def tool_instance(self):
        """
        GIVEN the need to test ScrapeMunicipalCodesTool
        WHEN I import and instantiate the tool
        THEN it should be created successfully
        """
        from ipfs_datasets_py.mcp_tools.tools.legal_dataset_mcp_tools import ScrapeMunicipalCodesTool
        return ScrapeMunicipalCodesTool()
    
    def test_tool_initialization(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I check its attributes
        THEN it should have correct name, description, and schema
        """
        assert tool_instance.name == "scrape_municipal_codes"
        assert "municipal" in tool_instance.description.lower()
        assert "scrape_the_law_mk3" in tool_instance.description
        assert tool_instance.category == "legal_datasets"
        assert "municipal" in tool_instance.tags
        assert "codes" in tool_instance.tags
    
    def test_input_schema_structure(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I examine its input schema
        THEN it should have all required properties
        """
        schema = tool_instance.input_schema
        assert schema["type"] == "object"
        
        properties = schema["properties"]
        assert "jurisdiction" in properties
        assert "jurisdictions" in properties
        assert "provider" in properties
        assert "output_format" in properties
        assert "include_metadata" in properties
        assert "include_text" in properties
        assert "rate_limit_delay" in properties
        assert "max_sections" in properties
        assert "scraper_type" in properties
        assert "job_id" in properties
        assert "resume" in properties
    
    def test_get_schema(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I call get_schema()
        THEN it should return complete tool metadata
        """
        schema = tool_instance.get_schema()
        assert schema["name"] == "scrape_municipal_codes"
        assert "description" in schema
        assert "input_schema" in schema
        assert "category" in schema
        assert schema["category"] == "legal_datasets"
        assert "tags" in schema
        assert "version" in schema
    
    @pytest.mark.asyncio
    async def test_execute_with_single_jurisdiction(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I execute it with a single jurisdiction
        THEN it should initialize the scraping job successfully
        """
        parameters = {
            "jurisdiction": "New York, NY",
            "provider": "auto",
            "output_format": "json"
        }
        
        result = await tool_instance.execute(parameters)
        
        assert result["status"] == "success"
        assert "job_id" in result
        assert "New York, NY" in result["jurisdictions"]
        assert result["provider"] == "auto"
        assert result["output_format"] == "json"
    
    @pytest.mark.asyncio
    async def test_execute_with_multiple_jurisdictions(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I execute it with multiple jurisdictions
        THEN it should initialize jobs for all jurisdictions
        """
        parameters = {
            "jurisdictions": ["New York, NY", "Los Angeles, CA", "Chicago, IL"],
            "provider": "municode",
            "output_format": "parquet"
        }
        
        result = await tool_instance.execute(parameters)
        
        assert result["status"] == "success"
        assert "job_id" in result
        assert len(result["jurisdictions"]) == 3
        assert "New York, NY" in result["jurisdictions"]
        assert "Los Angeles, CA" in result["jurisdictions"]
        assert "Chicago, IL" in result["jurisdictions"]
    
    @pytest.mark.asyncio
    async def test_execute_without_jurisdiction(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I execute it without specifying jurisdictions
        THEN it should return an error
        """
        parameters = {
            "provider": "auto"
        }
        
        result = await tool_instance.execute(parameters)
        
        assert result["status"] == "error"
        assert "No jurisdictions specified" in result["error"]
    
    @pytest.mark.asyncio
    async def test_execute_with_custom_job_id(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I execute it with a custom job_id
        THEN it should use the provided job_id
        """
        parameters = {
            "jurisdiction": "Boston, MA",
            "job_id": "custom_job_123"
        }
        
        result = await tool_instance.execute(parameters)
        
        assert result["status"] == "success"
        assert result["job_id"] == "custom_job_123"
    
    @pytest.mark.asyncio
    async def test_execute_with_all_parameters(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I execute it with all possible parameters
        THEN it should handle them correctly
        """
        parameters = {
            "jurisdiction": "Seattle, WA",
            "provider": "general_code",
            "output_format": "sql",
            "include_metadata": True,
            "include_text": True,
            "rate_limit_delay": 3.0,
            "max_sections": 1000,
            "scraper_type": "selenium",
            "enable_fallbacks": True,
            "fallback_methods": ["wayback_machine", "common_crawl", "playwright"],
            "job_id": "full_test_job",
            "resume": False
        }
        
        result = await tool_instance.execute(parameters)
        
        assert result["status"] == "success"
        assert result["job_id"] == "full_test_job"
        assert result["provider"] == "general_code"
        assert result["scraper_type"] == "selenium"
        assert result["output_format"] == "sql"
        assert result["enable_fallbacks"] == True
        assert len(result["fallback_methods"]) == 3
    
    @pytest.mark.asyncio
    async def test_execute_auto_job_id_generation(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I execute it without providing a job_id
        THEN it should auto-generate a job_id
        """
        parameters = {
            "jurisdiction": "Portland, OR"
        }
        
        result = await tool_instance.execute(parameters)
        
        assert result["status"] == "success"
        assert "job_id" in result
        assert result["job_id"].startswith("municipal_codes_")
    
    @pytest.mark.asyncio
    async def test_execute_with_resume_capability(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I execute it with resume=True and a job_id
        THEN it should indicate resume capability
        """
        parameters = {
            "jurisdiction": "Austin, TX",
            "job_id": "resume_test_job",
            "resume": True
        }
        
        result = await tool_instance.execute(parameters)
        
        assert result["status"] == "success"
        assert result["job_id"] == "resume_test_job"
    
    def test_tool_in_legal_dataset_tools_list(self):
        """
        GIVEN the LEGAL_DATASET_MCP_TOOLS list
        WHEN I check if ScrapeMunicipalCodesTool is included
        THEN it should be present
        """
        from ipfs_datasets_py.mcp_tools.tools.legal_dataset_mcp_tools import LEGAL_DATASET_MCP_TOOLS
        
        tool_names = [tool.name for tool in LEGAL_DATASET_MCP_TOOLS]
        assert "scrape_municipal_codes" in tool_names
    
    def test_tool_accessible_via_mcp_server(self):
        """
        GIVEN the TemporalDeonticMCPServer
        WHEN I check its registered tools
        THEN scrape_municipal_codes should be available
        """
        from ipfs_datasets_py.mcp_tools.temporal_deontic_mcp_server import TemporalDeonticMCPServer
        
        server = TemporalDeonticMCPServer()
        assert "scrape_municipal_codes" in server.tools
        assert server.tools["scrape_municipal_codes"].name == "scrape_municipal_codes"
    
    @pytest.mark.asyncio
    async def test_execute_with_fallback_methods(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I execute it with fallback methods enabled
        THEN it should include fallback configuration in results
        """
        parameters = {
            "jurisdiction": "Portland, OR",
            "enable_fallbacks": True,
            "fallback_methods": ["wayback_machine", "archive_is", "common_crawl"]
        }
        
        result = await tool_instance.execute(parameters)
        
        assert result["status"] == "success"
        assert result["enable_fallbacks"] == True
        assert "fallback_methods" in result
        assert len(result["fallback_methods"]) == 3
        assert "wayback_machine" in result["fallback_methods"]
        assert "archive_is" in result["fallback_methods"]
        assert "common_crawl" in result["fallback_methods"]
        assert "fallback_strategy" in result["metadata"]
    
    @pytest.mark.asyncio
    async def test_execute_without_fallbacks(self, tool_instance):
        """
        GIVEN a ScrapeMunicipalCodesTool instance
        WHEN I execute it with fallbacks disabled
        THEN it should not include fallback methods
        """
        parameters = {
            "jurisdiction": "Denver, CO",
            "enable_fallbacks": False
        }
        
        result = await tool_instance.execute(parameters)
        
        assert result["status"] == "success"
        assert result["enable_fallbacks"] == False
        assert result["fallback_methods"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
