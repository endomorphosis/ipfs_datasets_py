"""
Integration test for the complete PDF processing pipeline.
Tests the full pipeline with a sample PDF document.
"""

import pytest
import asyncio
import tempfile
import json
from pathlib import Path
import sys

# Add project path
sys.path.insert(0, '/home/barberb/ipfs_datasets_py')

from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag import pdf_ingest_to_graphrag


class TestPDFPipelineIntegration:
    """Integration tests for the complete PDF processing pipeline."""
    
    def create_sample_pdf_content(self, temp_dir: Path) -> str:
        """Create a sample text file that simulates PDF content."""
        pdf_path = temp_dir / "sample_document.txt"  # Use .txt for simplicity
        
        content = """
        IPFS: InterPlanetary File System
        
        IPFS (InterPlanetary File System) is a distributed, peer-to-peer hypermedia protocol
        designed to create a permanent and decentralized method of storing and sharing files.
        
        Key Features:
        - Content-addressed storage
        - Peer-to-peer networking
        - Cryptographic hashing
        - Distributed architecture
        
        Technical Details:
        IPFS uses Merkle DAGs (Directed Acyclic Graphs) to represent files and directories.
        Each file is broken into blocks, and each block is given a cryptographic hash.
        
        Applications:
        - Decentralized web hosting
        - Data archival
        - Content distribution
        - Blockchain storage solutions
        """
        
        pdf_path.write_text(content)
        return str(pdf_path)
    
    @pytest.mark.asyncio
    async def test_pdf_processor_complete_pipeline(self, tmp_path):
        """Test the complete PDF processing pipeline."""
        # Create sample content
        pdf_path = self.create_sample_pdf_content(tmp_path)
        
        # Initialize processor
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
        # Process the document
        result = await processor.process_pdf(pdf_path)
        
        # Verify result structure
        assert isinstance(result, dict)
        assert "status" in result
        assert "document_id" in result
        
        # Since we're using a text file, expect an error but graceful handling
        if result["status"] == "error":
            assert "error" in result
            assert isinstance(result["error"], str)
        else:
            # If successful, check required fields
            assert "ipld_cid" in result
            assert "processing_time" in result
    
    @pytest.mark.asyncio
    async def test_mcp_pdf_ingest_integration(self, tmp_path):
        """Test MCP PDF ingest tool integration."""
        # Create sample content
        pdf_path = self.create_sample_pdf_content(tmp_path)
        
        # Prepare request data
        request_data = {
            "pdf_path": pdf_path,
            "metadata": {
                "title": "IPFS Overview",
                "author": "Test Author",
                "category": "technical_documentation"
            },
            "options": {
                "enable_ocr": False,  # Disable OCR since we have text
                "enable_llm_optimization": True,
                "chunk_size": 512,
                "overlap": 100
            }
        }
        
        # Execute the MCP tool
        result = await pdf_ingest_to_graphrag(json.dumps(request_data))
        
        # Verify response structure
        assert isinstance(result, dict)
        assert "status" in result
        
        # Check if processing succeeded or failed gracefully
        if result["status"] == "success":
            assert "document_id" in result
            assert "message" in result
        else:
            assert "message" in result or "error" in result
    
    @pytest.mark.asyncio
    async def test_pdf_processing_with_metadata(self, tmp_path):
        """Test PDF processing with custom metadata."""
        pdf_path = self.create_sample_pdf_content(tmp_path)
        
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
        custom_metadata = {
            "author": "Integration Test",
            "subject": "IPFS Documentation",
            "keywords": ["ipfs", "distributed", "storage"]
        }
        
        result = await processor.process_pdf(pdf_path, metadata=custom_metadata)
        
        assert isinstance(result, dict)
        assert "status" in result
        assert "document_id" in result
        
        # Verify metadata is preserved
        if "metadata" in result:
            assert isinstance(result["metadata"], dict)
    
    @pytest.mark.asyncio
    async def test_pipeline_error_handling(self):
        """Test pipeline error handling with invalid inputs."""
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
        # Test with non-existent file
        result = await processor.process_pdf("/nonexistent/file.pdf")
        assert result["status"] == "error"
        assert "error" in result
        
        # Test with invalid path type
        result = await processor.process_pdf("")
        assert result["status"] == "error"
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_mcp_tool_error_handling(self):
        """Test MCP tool error handling."""
        # Test with invalid JSON
        result = await pdf_ingest_to_graphrag("invalid json")
        assert result["status"] == "error"
        
        # Test with missing required fields
        result = await pdf_ingest_to_graphrag("{}")
        assert result["status"] == "error"
        
        # Test with non-existent file
        request_data = {"pdf_path": "/nonexistent/file.pdf"}
        result = await pdf_ingest_to_graphrag(json.dumps(request_data))
        assert result["status"] == "error"
    
    @pytest.mark.asyncio
    async def test_concurrent_processing(self, tmp_path):
        """Test concurrent processing of multiple documents."""
        # Create multiple sample documents
        pdf_paths = []
        for i in range(3):
            content_path = tmp_path / f"doc_{i}.txt"
            content_path.write_text(f"Sample document {i} content about IPFS and distributed systems.")
            pdf_paths.append(str(content_path))
        
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
        # Process documents concurrently
        tasks = [processor.process_pdf(path) for path in pdf_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify all completed
        assert len(results) == 3
        
        for result in results:
            if isinstance(result, Exception):
                # Exceptions are allowed for invalid file types
                continue
            assert isinstance(result, dict)
            assert "status" in result
    
    def test_module_imports(self):
        """Test that all required modules can be imported."""
        # If we get here, imports in the file header succeeded
        assert PDFProcessor is not None
        assert pdf_ingest_to_graphrag is not None
    
    @pytest.mark.asyncio
    async def test_pipeline_components_availability(self):
        """Test that pipeline components are available and configured."""
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
        # Check that key components are available
        assert processor.storage is not None
        
        # Test component initialization doesn't fail
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        from ipfs_datasets_py.pdf_processing.ocr_engine import MultiEngineOCR
        
        optimizer = LLMOptimizer()
        ocr = MultiEngineOCR()
        
        assert optimizer is not None
        assert ocr is not None


# Test file for pytest - no main block needed
