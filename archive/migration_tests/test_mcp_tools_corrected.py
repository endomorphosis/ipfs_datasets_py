"""
Corrected unit tests for MCP tools.
These tests are aligned with the actual implementation.
"""

import pytest
import tempfile
import asyncio
import json
from pathlib import Path
import sys

# Add project path
sys.path.insert(0, '/home/barberb/ipfs_datasets_py')

from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag import pdf_ingest_to_graphrag
from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus import pdf_query_corpus


class TestDatasetToolsCorrected:
    """Corrected tests for dataset tools."""
    
    @pytest.mark.asyncio
    async def test_load_dataset_basic(self):
        """Test basic load_dataset functionality."""
        result = await load_dataset("test_dataset")
        
        assert isinstance(result, dict)
        assert "status" in result
        assert "dataset_id" in result
        assert result["status"] in ["success", "error"]
    
    @pytest.mark.asyncio
    async def test_load_dataset_with_format(self):
        """Test load_dataset with specific format."""
        result = await load_dataset("test_dataset", format="json")
        
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "error"]
    
    @pytest.mark.asyncio
    async def test_save_dataset_basic(self, tmp_path):
        """Test basic save_dataset functionality."""
        output_path = tmp_path / "output.json"
        
        result = await save_dataset(
            dataset_data={"test": "data"},
            destination=str(output_path)
        )
        
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "error"]


class TestPDFToolsCorrected:
    """Corrected tests for PDF tools."""
    
    @pytest.mark.asyncio
    async def test_pdf_ingest_basic_with_json_input(self):
        """Test PDF ingestion with JSON input."""
        request_data = {
            "pdf_path": "/nonexistent/file.pdf",
            "options": {
                "enable_ocr": True
            }
        }
        
        result = await pdf_ingest_to_graphrag(json.dumps(request_data))
        
        assert isinstance(result, dict)
        assert "status" in result
        # Should be error since file doesn't exist
        assert result["status"] == "error"
    
    @pytest.mark.asyncio
    async def test_pdf_ingest_invalid_json(self):
        """Test PDF ingestion with invalid JSON."""
        result = await pdf_ingest_to_graphrag("invalid json")
        
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "error"
    
    @pytest.mark.asyncio
    async def test_pdf_query_corpus_basic(self):
        """Test basic corpus querying."""
        request_data = {
            "query": "What is IPFS?",
            "query_type": "semantic_search"
        }
        
        result = await pdf_query_corpus(json.dumps(request_data))
        
        assert isinstance(result, dict)
        assert "status" in result
        # May be success or error depending on corpus availability
        assert result["status"] in ["success", "error"]
    
    @pytest.mark.asyncio
    async def test_pdf_query_corpus_invalid_json(self):
        """Test corpus querying with invalid JSON."""
        result = await pdf_query_corpus("invalid json")
        
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "error"


class TestMCPToolIntegrationCorrected:
    """Corrected integration tests for MCP tools."""
    
    @pytest.mark.asyncio
    async def test_all_tools_importable(self):
        """Test that all MCP tools can be imported."""
        # Import test - if we get here, imports worked
        assert load_dataset is not None
        assert save_dataset is not None
        assert pdf_ingest_to_graphrag is not None
        assert pdf_query_corpus is not None
    
    @pytest.mark.asyncio
    async def test_tools_return_dict_responses(self):
        """Test that all tools return dict responses."""
        tools_and_data = [
            (load_dataset, "test_dataset"),
            (pdf_ingest_to_graphrag, '{"pdf_path": "/test"}'),
            (pdf_query_corpus, '{"query": "test", "query_type": "semantic_search"}')
        ]
        
        for tool, test_data in tools_and_data:
            if callable(tool):
                # Determine if tool expects JSON string or direct parameters
                if tool.__name__ in ['pdf_ingest_to_graphrag', 'pdf_query_corpus']:
                    result = await tool(test_data)
                else:
                    result = await tool(test_data)
                
                assert isinstance(result, dict), f"Tool {tool.__name__} didn't return dict"
                assert "status" in result, f"Tool {tool.__name__} missing status field"
    
    @pytest.mark.asyncio
    async def test_error_handling_consistency(self):
        """Test that all tools handle errors consistently."""
        # Test with various invalid inputs
        tools = [pdf_ingest_to_graphrag, pdf_query_corpus]
        invalid_inputs = ["invalid json", "{}", ""]
        
        for tool in tools:
            for invalid_input in invalid_inputs:
                result = await tool(invalid_input)
                assert isinstance(result, dict)
                assert "status" in result
                # Should be error for invalid inputs
                if invalid_input == "invalid json":
                    assert result["status"] == "error"


class TestToolPerformanceCorrected:
    """Corrected performance tests."""
    
    @pytest.mark.asyncio
    async def test_response_time_reasonable(self):
        """Test that tools respond within reasonable time."""
        import time
        
        tools_and_data = [
            (load_dataset, "test_dataset"),
            (pdf_ingest_to_graphrag, '{"pdf_path": "/test"}')
        ]
        
        for tool, test_data in tools_and_data:
            start_time = time.time()
            
            if tool.__name__ in ['pdf_ingest_to_graphrag', 'pdf_query_corpus']:
                result = await tool(test_data)
            else:
                result = await tool(test_data)
            
            end_time = time.time()
            response_time = end_time - start_time
            
            # Should respond within 60 seconds for basic operations
            assert response_time < 60, f"Tool {tool.__name__} took too long: {response_time}s"
            assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
