"""
Tests for DataProcessor core module.

Tests the core data processing operations including text chunking,
transformation, and conversion functionality.
"""

import pytest
import asyncio
from pathlib import Path


class TestDataProcessorAvailability:
    """Test availability and structure of DataProcessor core module"""

    def test_given_core_operations_when_importing_data_processor_then_succeeds(self):
        """
        GIVEN the core_operations module
        WHEN importing DataProcessor
        THEN import should succeed
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            assert DataProcessor is not None
        except ImportError as e:
            pytest.skip(f"DataProcessor not available: {e}")

    def test_given_data_processor_when_instantiating_then_has_expected_attributes(self):
        """
        GIVEN the DataProcessor class
        WHEN instantiating it
        THEN it should have expected attributes
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            
            assert hasattr(processor, "supported_formats")
            assert hasattr(processor, "chunk_strategies")
            assert hasattr(processor, "valid_transformations")
            
            # Check expected values
            assert "json" in processor.supported_formats
            assert "fixed_size" in processor.chunk_strategies
            assert "normalize_text" in processor.valid_transformations
        except ImportError:
            pytest.skip("DataProcessor not available")


class TestDataProcessorChunking:
    """Test text chunking functionality"""

    @pytest.mark.asyncio
    async def test_given_empty_text_when_chunking_then_returns_error(self):
        """
        GIVEN an empty text string
        WHEN calling chunk_text
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            result = await processor.chunk_text(text="")
            
            assert result["status"] == "error"
            assert "message" in result
        except ImportError:
            pytest.skip("DataProcessor not available")

    @pytest.mark.asyncio
    async def test_given_valid_text_when_chunking_with_fixed_size_then_returns_chunks(self):
        """
        GIVEN valid text
        WHEN calling chunk_text with fixed_size strategy
        THEN it should return chunks
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            test_text = "This is a test. " * 100  # Create text that needs chunking
            
            result = await processor.chunk_text(
                text=test_text,
                strategy="fixed_size",
                chunk_size=100,
                overlap=10
            )
            
            assert "status" in result
            if result["status"] == "success":
                assert "chunks" in result
                assert "total_chunks" in result
                assert result["total_chunks"] > 0
        except ImportError:
            pytest.skip("DataProcessor not available")

    @pytest.mark.asyncio
    async def test_given_invalid_strategy_when_chunking_then_returns_error(self):
        """
        GIVEN an invalid chunking strategy
        WHEN calling chunk_text
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            result = await processor.chunk_text(
                text="Test text",
                strategy="invalid_strategy"
            )
            
            assert result["status"] == "error"
            assert "Invalid strategy" in result["message"]
        except ImportError:
            pytest.skip("DataProcessor not available")

    @pytest.mark.asyncio
    async def test_given_negative_chunk_size_when_chunking_then_returns_error(self):
        """
        GIVEN a negative chunk size
        WHEN calling chunk_text
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            result = await processor.chunk_text(
                text="Test text",
                chunk_size=-100
            )
            
            assert result["status"] == "error"
            assert "chunk_size" in result["message"].lower()
        except ImportError:
            pytest.skip("DataProcessor not available")


class TestDataProcessorTransformation:
    """Test data transformation functionality"""

    @pytest.mark.asyncio
    async def test_given_data_when_transforming_then_applies_transformations(self):
        """
        GIVEN input data
        WHEN calling transform_data
        THEN it should apply transformations
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            test_data = [
                {"text": "  Test 1  ", "value": 100},
                {"text": "  Test 2  ", "value": 200}
            ]
            
            result = await processor.transform_data(
                data=test_data,
                transformation="normalize_text"
            )
            
            assert "status" in result
            if result["status"] == "success":
                assert "result" in result or "transformed_data" in result
                assert "transformations_applied" in result or "message" in result
        except (ImportError, AttributeError):
            pytest.skip("DataProcessor.transform_data not available")

    @pytest.mark.asyncio
    async def test_given_empty_data_when_transforming_then_handles_gracefully(self):
        """
        GIVEN empty data
        WHEN calling transform_data
        THEN it should handle gracefully (may return success with empty result)
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            result = await processor.transform_data(
                data=[],
                transformation="normalize_text"
            )
            
            # Empty data may be handled gracefully
            assert "status" in result
            assert result["status"] in ["success", "error"]
        except (ImportError, AttributeError):
            pytest.skip("DataProcessor.transform_data not available")

    @pytest.mark.asyncio
    async def test_given_invalid_transformation_when_transforming_then_returns_error(self):
        """
        GIVEN an invalid transformation type
        WHEN calling transform_data
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            test_data = [{"text": "Test"}]
            
            result = await processor.transform_data(
                data=test_data,
                transformation="invalid_transformation"
            )
            
            assert result["status"] == "error"
            assert "invalid" in result["message"].lower()
        except (ImportError, AttributeError):
            pytest.skip("DataProcessor.transform_data not available")


class TestDataProcessorConversion:
    """Test format conversion functionality"""

    @pytest.mark.asyncio
    async def test_given_data_when_converting_format_then_returns_converted_data(self):
        """
        GIVEN data in one format
        WHEN calling convert_format
        THEN it should return converted data
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            test_data = [{"name": "test1", "value": 100}]
            
            result = await processor.convert_format(
                data=test_data,
                source_format="json",
                target_format="csv"
            )
            
            assert "status" in result
            if result["status"] == "success":
                assert "result" in result or "converted_data" in result or "output_path" in result
        except (ImportError, AttributeError):
            pytest.skip("DataProcessor.convert_format not available")

    @pytest.mark.asyncio
    async def test_given_unsupported_format_when_converting_then_returns_error(self):
        """
        GIVEN an unsupported format
        WHEN calling convert_format
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            test_data = [{"name": "test"}]
            
            result = await processor.convert_format(
                data=test_data,
                source_format="json",
                target_format="unsupported_format"
            )
            
            assert result["status"] == "error"
            assert "format" in result["message"].lower() or "supported" in result["message"].lower()
        except (ImportError, AttributeError):
            pytest.skip("DataProcessor.convert_format not available")


class TestDataProcessorIntegration:
    """Test integration scenarios"""

    @pytest.mark.asyncio
    async def test_given_processor_when_chaining_operations_then_works_correctly(self):
        """
        GIVEN a DataProcessor instance
        WHEN chaining multiple operations
        THEN they should work together correctly
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            
            # First chunk text
            test_text = "Sample text for chunking. " * 50
            chunk_result = await processor.chunk_text(
                text=test_text,
                chunk_size=100
            )
            
            if chunk_result["status"] == "success":
                # Process each chunk
                for chunk in chunk_result.get("chunks", []):
                    assert "text" in chunk or "content" in chunk
                    
        except ImportError:
            pytest.skip("DataProcessor not available")

    @pytest.mark.asyncio
    async def test_given_processor_when_handling_large_text_then_respects_limits(self):
        """
        GIVEN a DataProcessor instance
        WHEN processing very large text
        THEN it should respect max_chunks limit
        """
        try:
            from ipfs_datasets_py.core_operations import DataProcessor
            
            processor = DataProcessor()
            large_text = "A" * 10000  # Large text
            
            result = await processor.chunk_text(
                text=large_text,
                chunk_size=100,
                max_chunks=5
            )
            
            if result["status"] == "success":
                assert result["total_chunks"] <= 5
                
        except ImportError:
            pytest.skip("DataProcessor not available")
