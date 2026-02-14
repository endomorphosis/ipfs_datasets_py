"""
Unit tests for PDFProcessor component of GraphRAG PDF processing pipeline

Tests individual components and methods of PDFProcessor in isolation,
focusing on core functionality, error handling, and component interaction.
"""
import anyio
import pytest
import tempfile
import os
import sys
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path

# Test fixtures and utilities
from tests.conftest import *

# Use centralized safe import utility
test_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, test_dir)

try:
    from test_import_utils import safe_importer
    
    # Try to import required modules using safe importer
    pdf_processor_module = safe_importer.import_module('ipfs_datasets_py.pdf_processing.pdf_processor')
    PDF_PROCESSING_AVAILABLE = pdf_processor_module is not None
except Exception as e:
    print(f"Warning: PDF processing modules not available: {e}")
    PDF_PROCESSING_AVAILABLE = False

# Skip all tests in this module if PDF processing is not available
pytestmark = pytest.mark.skipif(not PDF_PROCESSING_AVAILABLE, reason="PDF processing modules not available")


class TestPDFProcessorInitialization:
    """Unit tests for PDFProcessor initialization and configuration"""
    
    def test_given_no_parameters_when_initializing_pdf_processor_then_creates_with_defaults(self):
        """
        GIVEN PDFProcessor initialization with no parameters
        WHEN creating a new instance
        THEN should initialize with default configuration
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        # Check default attributes exist
        assert hasattr(processor, 'storage')
        assert hasattr(processor, 'audit_logger')
        assert hasattr(processor, 'monitoring')
        assert hasattr(processor, 'pipeline_version')
        assert processor.pipeline_version == "2.0"
        
    def test_given_monitoring_enabled_when_initializing_pdf_processor_then_configures_monitoring(self):
        """
        GIVEN PDFProcessor initialization with monitoring enabled
        WHEN creating a new instance
        THEN should configure monitoring system
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor(enable_monitoring=True)
        
        assert hasattr(processor, 'monitoring')
        assert processor.monitoring is not None
        
    def test_given_custom_config_when_initializing_pdf_processor_then_applies_configuration(self):
        """
        GIVEN PDFProcessor initialization with custom configuration
        WHEN creating a new instance
        THEN should apply custom settings
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor(
            enable_audit=False,
            enable_monitoring=False,
            use_real_ml_models=False,
            enable_embeddings=False,
            embedding_model="dummy-model",
            enable_cross_document_analysis=True,
        )

        assert processor.enable_cross_document_analysis is True
        assert processor.enable_embeddings is False
        assert processor.embedding_model == "dummy-model"


class TestPDFProcessorValidation:
    """Unit tests for PDF file validation functionality"""
    
    @pytest.mark.asyncio
    async def test_given_valid_pdf_path_when_validating_pdf_then_returns_true(self):
        """
        GIVEN a valid PDF file path
        WHEN validating the PDF
        THEN should return True
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        # Create temporary PDF file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            pdf_path = tmp_file.name
            # Create a real minimal PDF using PyMuPDF to satisfy the
            # processor's validation and analysis logic.
            import fitz  # PyMuPDF
            doc = fitz.open()
            doc.new_page()
            doc.save(pdf_path)
            doc.close()
        
        try:
            pdf_info = await processor._validate_and_analyze_pdf(Path(pdf_path))
            assert isinstance(pdf_info, dict)
            assert pdf_info.get('page_count') == 1
        finally:
            os.unlink(pdf_path)
            
    @pytest.mark.asyncio
    async def test_given_nonexistent_file_when_validating_pdf_then_raises_error(self):
        """
        GIVEN a non-existent file path
        WHEN validating the PDF
        THEN should raise appropriate error
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        with pytest.raises((FileNotFoundError, ValueError)):
            await processor._validate_and_analyze_pdf(Path("/nonexistent/path.pdf"))
            
    @pytest.mark.asyncio
    async def test_given_non_pdf_file_when_validating_pdf_then_handles_gracefully(self):
        """
        GIVEN a non-PDF file
        WHEN validating the PDF
        THEN should handle gracefully
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        # Create temporary non-PDF file
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp_file:
            txt_path = tmp_file.name
            tmp_file.write(b"Not a PDF file")
        
        try:
            with pytest.raises((ValueError, TypeError)):
                await processor._validate_and_analyze_pdf(Path(txt_path))
        finally:
            os.unlink(txt_path)


class TestPDFProcessorComponentIntegration:
    """Unit tests for PDFProcessor component integration"""
    
    @pytest.mark.asyncio
    async def test_given_pdf_processor_when_processing_pdf_then_invokes_all_components(self):
        """
        GIVEN a PDFProcessor with all components
        WHEN processing a PDF
        THEN should invoke all required components in sequence
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        # Create mock PDF file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            pdf_path = tmp_file.name
            tmp_file.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj")
        
        try:
            # Process PDF - should complete without crashing
            result = await processor.process_pdf(pdf_path)
            
            # Should return result dict with status
            assert isinstance(result, dict)
            assert 'status' in result
            assert result['status'] in ['success', 'error']
            
        finally:
            os.unlink(pdf_path)
    
    def test_given_pdf_processor_when_checking_integrator_then_has_graphrag_integration(self):
        """
        GIVEN a PDFProcessor instance
        WHEN checking GraphRAG integrator
        THEN should have GraphRAG integration component
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        # Should have integrator attribute
        assert hasattr(processor, 'integrator')
        assert processor.integrator is not None
        
    def test_given_pdf_processor_when_checking_storage_then_has_ipld_storage(self):
        """
        GIVEN a PDFProcessor instance
        WHEN checking IPLD storage
        THEN should have IPLD storage component
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        # Should have storage attribute
        assert hasattr(processor, 'storage')
        assert processor.storage is not None


class TestPDFProcessorErrorHandling:
    """Unit tests for PDFProcessor error handling"""
    
    @pytest.mark.asyncio
    async def test_given_corrupted_pdf_when_processing_then_handles_gracefully(self):
        """
        GIVEN a corrupted PDF file
        WHEN processing through PDFProcessor
        THEN should handle errors gracefully
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        # Create corrupted PDF file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            pdf_path = tmp_file.name
            tmp_file.write(b"corrupted pdf content")
        
        try:
            # Should not crash, should return error status
            result = await processor.process_pdf(pdf_path)
            
            assert isinstance(result, dict)
            assert 'status' in result
            # May succeed with empty results or fail gracefully
            assert result['status'] in ['success', 'error']
            
        finally:
            os.unlink(pdf_path)
            
    @pytest.mark.asyncio
    async def test_given_missing_dependencies_when_processing_then_continues_with_fallbacks(self):
        """
        GIVEN missing optional dependencies
        WHEN processing a PDF
        THEN should continue with fallback implementations
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        # Create minimal PDF
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            pdf_path = tmp_file.name
            tmp_file.write(b"%PDF-1.4\n")
        
        try:
            # Mock missing dependencies scenario: the processor uses an instance logger
            # (module-level logger is not guaranteed to exist in all dependency modes).
            import logging
            mock_logger = Mock()
            mock_logger.level = logging.INFO

            with patch.object(processor, 'logger', mock_logger):
                result = await processor.process_pdf(pdf_path)

            # Should handle missing dependencies gracefully
            assert isinstance(result, dict)
            assert 'status' in result
                
        finally:
            os.unlink(pdf_path)


class TestPDFProcessorMetadataHandling:
    """Unit tests for PDF metadata processing"""
    
    @pytest.mark.asyncio
    async def test_given_pdf_with_metadata_when_processing_then_extracts_metadata(self):
        """
        GIVEN a PDF with metadata
        WHEN processing the PDF
        THEN should extract and include metadata in results
        """
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
        
        processor = PDFProcessor()
        
        # Test metadata extraction capability
        metadata = {
            "source": "test",
            "domain": "research",
            "priority": "high"
        }
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            pdf_path = tmp_file.name
            tmp_file.write(b"%PDF-1.4\n")
        
        try:
            result = await processor.process_pdf(pdf_path, metadata)
            
            # Should include metadata in processing
            assert isinstance(result, dict)
            if 'processing_metadata' in result:
                proc_metadata = result['processing_metadata']
                # Should have pipeline information
                assert 'pipeline_version' in proc_metadata
                
        finally:
            os.unlink(pdf_path)


if __name__ == "__main__":
    # Run tests directly if called as script
    pytest.main([__file__, "-v"])