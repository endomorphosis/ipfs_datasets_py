"""
Tests for async pipeline with monadic error handling.

Phase 2 Feature 3: Async Pipeline
"""

import pytest
import asyncio
from pathlib import Path
from ipfs_datasets_py.file_converter.pipeline import (
    Result, Error, ErrorType, ok, error, wrap_exception,
    FileUnit, Pipeline, StreamProcessor,
    validate_file_exists, detect_format, extract_text
)


class TestResultMonad:
    """Test Result monad operations."""
    
    def test_result_creation(self):
        """Test creating Result."""
        result = Result(42)
        assert result.is_ok()
        assert not result.is_error()
        assert result.unwrap() == 42
    
    def test_result_map(self):
        """Test mapping function over Result."""
        result = Result(10)
        mapped = result.map(lambda x: x * 2)
        assert mapped.is_ok()
        assert mapped.unwrap() == 20
    
    def test_result_map_error(self):
        """Test map with function that raises."""
        result = Result(10)
        mapped = result.map(lambda x: 1/0)  # Will raise ZeroDivisionError
        assert mapped.is_error()
    
    @pytest.mark.asyncio
    async def test_result_map_async(self):
        """Test async map."""
        result = Result(5)
        
        async def double(x):
            await asyncio.sleep(0.001)
            return x * 2
        
        mapped = await result.map_async(double)
        assert mapped.is_ok()
        assert mapped.unwrap() == 10
    
    def test_result_flat_map(self):
        """Test flat_map for monadic chaining."""
        result = Result(10)
        
        def safe_divide(x):
            if x == 0:
                return error(ErrorType.VALIDATION_FAILED, "Division by zero")
            return ok(100 / x)
        
        chained = result.flat_map(safe_divide)
        assert chained.is_ok()
        assert chained.unwrap() == 10.0
    
    def test_result_unwrap_or(self):
        """Test unwrap_or with Result."""
        result = Result(42)
        assert result.unwrap_or(0) == 42
    
    def test_result_repr(self):
        """Test Result representation."""
        result = Result(42)
        assert "Result(42)" in repr(result)


class TestErrorMonad:
    """Test Error monad operations."""
    
    def test_error_creation(self):
        """Test creating Error."""
        err = Error(
            error_type=ErrorType.FILE_NOT_FOUND,
            message="File not found",
            context={'path': '/tmp/missing.txt'}
        )
        assert not err.is_ok()
        assert err.is_error()
        assert err.error_type == ErrorType.FILE_NOT_FOUND
        assert "File not found" in err.message
    
    def test_error_map_propagates(self):
        """Test that map on Error propagates error."""
        err = error(ErrorType.FILE_NOT_FOUND, "Missing")
        mapped = err.map(lambda x: x * 2)
        assert mapped.is_error()
        assert mapped.error_type == ErrorType.FILE_NOT_FOUND
    
    @pytest.mark.asyncio
    async def test_error_map_async_propagates(self):
        """Test that async map on Error propagates error."""
        err = error(ErrorType.FILE_NOT_FOUND, "Missing")
        
        async def double(x):
            return x * 2
        
        mapped = await err.map_async(double)
        assert mapped.is_error()
    
    def test_error_flat_map_propagates(self):
        """Test that flat_map on Error propagates error."""
        err = error(ErrorType.FILE_NOT_FOUND, "Missing")
        chained = err.flat_map(lambda x: ok(x * 2))
        assert chained.is_error()
        assert chained.error_type == ErrorType.FILE_NOT_FOUND
    
    def test_error_unwrap_raises(self):
        """Test that unwrap on Error raises."""
        err = error(ErrorType.FILE_NOT_FOUND, "Missing")
        with pytest.raises(ValueError, match="Called unwrap on Error"):
            err.unwrap()
    
    def test_error_unwrap_or(self):
        """Test unwrap_or with Error."""
        err = error(ErrorType.FILE_NOT_FOUND, "Missing")
        assert err.unwrap_or(42) == 42
    
    def test_error_repr(self):
        """Test Error representation."""
        err = error(ErrorType.FILE_NOT_FOUND, "Missing file")
        assert "Error(" in repr(err)
        assert "file_not_found" in repr(err)


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_ok_function(self):
        """Test ok() convenience function."""
        result = ok(42)
        assert isinstance(result, Result)
        assert result.unwrap() == 42
    
    def test_error_function(self):
        """Test error() convenience function."""
        err = error(
            ErrorType.VALIDATION_FAILED,
            "Invalid input",
            context={'field': 'email'}
        )
        assert isinstance(err, Error)
        assert err.error_type == ErrorType.VALIDATION_FAILED
        assert err.context['field'] == 'email'
    
    def test_wrap_exception(self):
        """Test wrapping exception as Error."""
        try:
            1 / 0
        except ZeroDivisionError as e:
            err = wrap_exception(e)
            assert isinstance(err, Error)
            assert err.error_type == ErrorType.UNKNOWN
            assert err.original_exception == e


class TestFileUnit:
    """Test FileUnit dataclass."""
    
    def test_file_unit_creation(self):
        """Test creating FileUnit."""
        unit = FileUnit(path=Path('/tmp/test.txt'))
        assert unit.path == Path('/tmp/test.txt')
        assert unit.mime_type is None
        assert unit.text is None
    
    def test_file_unit_from_path(self):
        """Test creating FileUnit from path."""
        unit = FileUnit.from_path('/tmp/test.txt')
        assert unit.path == Path('/tmp/test.txt')
    
    def test_file_unit_with_mime_type(self):
        """Test setting MIME type."""
        unit = FileUnit.from_path('/tmp/test.txt')
        updated = unit.with_mime_type('text/plain')
        assert updated.mime_type == 'text/plain'
        assert unit.mime_type is None  # Original unchanged
    
    def test_file_unit_with_text(self):
        """Test setting text."""
        unit = FileUnit.from_path('/tmp/test.txt')
        updated = unit.with_text('Hello, world!')
        assert updated.text == 'Hello, world!'
        assert unit.text is None  # Original unchanged
    
    def test_file_unit_with_metadata(self):
        """Test adding metadata."""
        unit = FileUnit.from_path('/tmp/test.txt')
        updated = unit.with_metadata(pages=10, author='Alice')
        assert updated.metadata['pages'] == 10
        assert updated.metadata['author'] == 'Alice'
        assert len(unit.metadata) == 0  # Original unchanged


class TestPipeline:
    """Test Pipeline composition."""
    
    @pytest.mark.asyncio
    async def test_empty_pipeline(self):
        """Test empty pipeline."""
        pipeline = Pipeline()
        result = await pipeline.process(42)
        assert result.is_ok()
        assert result.unwrap() == 42
    
    @pytest.mark.asyncio
    async def test_single_stage_pipeline(self):
        """Test pipeline with one stage."""
        pipeline = Pipeline()
        pipeline.add_stage(lambda x: ok(x * 2), name="double")
        
        result = await pipeline.process(10)
        assert result.is_ok()
        assert result.unwrap() == 20
    
    @pytest.mark.asyncio
    async def test_multi_stage_pipeline(self):
        """Test pipeline with multiple stages."""
        pipeline = Pipeline()
        pipeline.add_stage(lambda x: ok(x * 2), name="double")
        pipeline.add_stage(lambda x: ok(x + 5), name="add_five")
        pipeline.add_stage(lambda x: ok(x ** 2), name="square")
        
        result = await pipeline.process(3)
        # (3 * 2 + 5) ^ 2 = 11 ^ 2 = 121
        assert result.is_ok()
        assert result.unwrap() == 121
    
    @pytest.mark.asyncio
    async def test_pipeline_error_propagation(self):
        """Test that errors propagate through pipeline."""
        pipeline = Pipeline()
        pipeline.add_stage(lambda x: ok(x * 2), name="double")
        pipeline.add_stage(
            lambda x: error(ErrorType.VALIDATION_FAILED, "Invalid value"),
            name="fail"
        )
        pipeline.add_stage(lambda x: ok(x + 5), name="add_five")  # Should skip
        
        result = await pipeline.process(10)
        assert result.is_error()
        assert result.error_type == ErrorType.VALIDATION_FAILED
    
    @pytest.mark.asyncio
    async def test_pipeline_with_async_stages(self):
        """Test pipeline with async functions."""
        async def async_double(x):
            await asyncio.sleep(0.001)
            return ok(x * 2)
        
        async def async_add_ten(x):
            await asyncio.sleep(0.001)
            return ok(x + 10)
        
        pipeline = Pipeline()
        pipeline.add_stage(async_double, name="async_double")
        pipeline.add_stage(async_add_ten, name="async_add_ten")
        
        result = await pipeline.process(5)
        assert result.is_ok()
        assert result.unwrap() == 20  # (5 * 2) + 10
    
    @pytest.mark.asyncio
    async def test_pipeline_exception_handling(self):
        """Test pipeline handles exceptions."""
        def raise_error(x):
            raise ValueError("Test error")
        
        pipeline = Pipeline()
        pipeline.add_stage(raise_error, name="error_stage")
        
        result = await pipeline.process(10)
        assert result.is_error()
        assert result.error_type == ErrorType.UNKNOWN
        assert "Test error" in result.message
    
    def test_pipeline_repr(self):
        """Test Pipeline representation."""
        pipeline = Pipeline()
        pipeline.add_stage(lambda x: x, name="stage1")
        pipeline.add_stage(lambda x: x, name="stage2")
        
        repr_str = repr(pipeline)
        assert "Pipeline" in repr_str
        assert "2 stages" in repr_str


class TestStreamProcessor:
    """Test StreamProcessor."""
    
    @pytest.mark.asyncio
    async def test_stream_processor_initialization(self):
        """Test StreamProcessor initialization."""
        processor = StreamProcessor(chunk_size=1024)
        assert processor.chunk_size == 1024
    
    @pytest.mark.asyncio
    async def test_read_chunks(self, tmp_path):
        """Test reading file in chunks."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_content = b"Hello, World! " * 100  # 1400 bytes
        test_file.write_bytes(test_content)
        
        processor = StreamProcessor(chunk_size=100)
        chunks = []
        async for chunk in processor.read_chunks(test_file):
            chunks.append(chunk)
        
        # Should have multiple chunks
        assert len(chunks) > 1
        # Reassembled content should match original
        assert b''.join(chunks) == test_content
    
    @pytest.mark.asyncio
    async def test_process_stream(self, tmp_path):
        """Test processing file stream."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"abcdefghij" * 10)
        
        processor = StreamProcessor(chunk_size=10)
        
        # Count bytes in each chunk
        result = await processor.process_stream(
            test_file,
            lambda chunk: len(chunk)
        )
        
        assert result.is_ok()
        lengths = result.unwrap()
        assert sum(lengths) == 100  # Total bytes
    
    @pytest.mark.asyncio
    async def test_process_stream_error(self):
        """Test stream processing with nonexistent file."""
        processor = StreamProcessor()
        result = await processor.process_stream(
            Path("/nonexistent/file.txt"),
            lambda chunk: chunk
        )
        
        assert result.is_error()
        assert result.error_type == ErrorType.IO_ERROR


class TestPipelineStages:
    """Test built-in pipeline stages."""
    
    def test_validate_file_exists_success(self, tmp_path):
        """Test file validation with existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello")
        
        unit = FileUnit.from_path(test_file)
        result = validate_file_exists(unit)
        
        assert result.is_ok()
        assert result.unwrap().path == test_file
    
    def test_validate_file_exists_failure(self):
        """Test file validation with missing file."""
        unit = FileUnit.from_path("/nonexistent/file.txt")
        result = validate_file_exists(unit)
        
        assert result.is_error()
        assert result.error_type == ErrorType.FILE_NOT_FOUND
    
    @pytest.mark.asyncio
    async def test_detect_format_stage(self, tmp_path):
        """Test format detection stage."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, world!")
        
        unit = FileUnit.from_path(test_file)
        result = await detect_format(unit)
        
        assert result.is_ok()
        updated_unit = result.unwrap()
        assert updated_unit.mime_type is not None
    
    @pytest.mark.asyncio
    async def test_extract_text_stage(self, tmp_path):
        """Test text extraction stage."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, world!")
        
        unit = FileUnit.from_path(test_file)
        result = await extract_text(unit)
        
        assert result.is_ok()
        updated_unit = result.unwrap()
        assert "Hello, world!" in updated_unit.text


class TestIntegratedPipeline:
    """Test complete pipeline integration."""
    
    @pytest.mark.asyncio
    async def test_complete_file_processing_pipeline(self, tmp_path):
        """Test complete file processing from path to text."""
        # Create test file
        test_file = tmp_path / "document.txt"
        test_file.write_text("This is a test document.")
        
        # Build pipeline
        pipeline = Pipeline()
        pipeline.add_stage(validate_file_exists, name="validate")
        pipeline.add_stage(detect_format, name="detect_format")
        pipeline.add_stage(extract_text, name="extract_text")
        
        # Process file
        unit = FileUnit.from_path(test_file)
        result = await pipeline.process(unit)
        
        # Verify success
        assert result.is_ok()
        final_unit = result.unwrap()
        assert final_unit.mime_type is not None
        assert "test document" in final_unit.text
        assert len(final_unit.metadata) > 0
    
    @pytest.mark.asyncio
    async def test_pipeline_with_missing_file(self):
        """Test pipeline handles missing file gracefully."""
        pipeline = Pipeline()
        pipeline.add_stage(validate_file_exists, name="validate")
        pipeline.add_stage(detect_format, name="detect_format")
        pipeline.add_stage(extract_text, name="extract_text")
        
        unit = FileUnit.from_path("/nonexistent/file.txt")
        result = await pipeline.process(unit)
        
        # Should fail at validation stage
        assert result.is_error()
        assert result.error_type == ErrorType.FILE_NOT_FOUND
