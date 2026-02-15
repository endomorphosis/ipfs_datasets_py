"""Tests for ProcessorProtocol and related core types.

This module tests the core protocol interface and data structures that form
the foundation of the unified processor system.
"""

import pytest
from datetime import datetime
from typing import Dict, Any

from ipfs_datasets_py.processors.core import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
    is_processor,
)


class TestInputType:
    """Tests for InputType enum."""
    
    def test_enum_values(self):
        """Test that all expected input types exist.
        
        GIVEN: InputType enum
        WHEN: Accessing enum values
        THEN: All expected types are available
        """
        assert InputType.URL.value == "url"
        assert InputType.FILE.value == "file"
        assert InputType.FOLDER.value == "folder"
        assert InputType.TEXT.value == "text"
        assert InputType.BINARY.value == "binary"
        assert InputType.IPFS_CID.value == "ipfs_cid"
        assert InputType.IPNS.value == "ipns"
    
    def test_from_string_valid(self):
        """Test converting valid strings to InputType.
        
        GIVEN: Valid input type string
        WHEN: Converting to InputType enum
        THEN: Correct enum value is returned
        """
        assert InputType.from_string("url") == InputType.URL
        assert InputType.from_string("FILE") == InputType.FILE
        assert InputType.from_string("Folder") == InputType.FOLDER
    
    def test_from_string_invalid(self):
        """Test error handling for invalid strings.
        
        GIVEN: Invalid input type string
        WHEN: Converting to InputType enum
        THEN: ValueError is raised
        """
        with pytest.raises(ValueError, match="Unknown input type"):
            InputType.from_string("invalid_type")


class TestProcessingContext:
    """Tests for ProcessingContext dataclass."""
    
    def test_basic_creation(self):
        """Test creating a basic context.
        
        GIVEN: Required context parameters
        WHEN: Creating ProcessingContext
        THEN: Context is created with correct values
        """
        context = ProcessingContext(
            input_type=InputType.FILE,
            source="/path/to/file.pdf"
        )
        
        assert context.input_type == InputType.FILE
        assert context.source == "/path/to/file.pdf"
        assert context.metadata == {}
        assert context.options == {}
        assert isinstance(context.created_at, datetime)
    
    def test_with_metadata(self):
        """Test context with metadata.
        
        GIVEN: Context with metadata
        WHEN: Accessing metadata
        THEN: Metadata is available
        """
        context = ProcessingContext(
            input_type=InputType.FILE,
            source="file.pdf",
            metadata={'format': 'pdf', 'size': 1024}
        )
        
        assert context.metadata['format'] == 'pdf'
        assert context.metadata['size'] == 1024
    
    def test_get_format(self):
        """Test getting format from metadata.
        
        GIVEN: Context with format in metadata
        WHEN: Calling get_format()
        THEN: Format is returned
        """
        context = ProcessingContext(
            input_type=InputType.FILE,
            source="file.pdf",
            metadata={'format': 'pdf'}
        )
        
        assert context.get_format() == 'pdf'
    
    def test_get_mime_type(self):
        """Test getting MIME type from metadata.
        
        GIVEN: Context with MIME type in metadata
        WHEN: Calling get_mime_type()
        THEN: MIME type is returned
        """
        context = ProcessingContext(
            input_type=InputType.FILE,
            source="file.pdf",
            metadata={'mime_type': 'application/pdf'}
        )
        
        assert context.get_mime_type() == 'application/pdf'
    
    def test_is_url(self):
        """Test URL detection.
        
        GIVEN: Context with different input types
        WHEN: Calling is_url()
        THEN: Correct boolean is returned
        """
        url_context = ProcessingContext(InputType.URL, "https://example.com")
        file_context = ProcessingContext(InputType.FILE, "file.pdf")
        
        assert url_context.is_url() is True
        assert file_context.is_url() is False
    
    def test_is_file(self):
        """Test file detection.
        
        GIVEN: Context with different input types
        WHEN: Calling is_file()
        THEN: Correct boolean is returned
        """
        file_context = ProcessingContext(InputType.FILE, "file.pdf")
        url_context = ProcessingContext(InputType.URL, "https://example.com")
        
        assert file_context.is_file() is True
        assert url_context.is_file() is False
    
    def test_is_folder(self):
        """Test folder detection.
        
        GIVEN: Context with different input types
        WHEN: Calling is_folder()
        THEN: Correct boolean is returned
        """
        folder_context = ProcessingContext(InputType.FOLDER, "/path/to/folder")
        file_context = ProcessingContext(InputType.FILE, "file.pdf")
        
        assert folder_context.is_folder() is True
        assert file_context.is_folder() is False


class TestProcessingResult:
    """Tests for ProcessingResult dataclass."""
    
    def test_basic_creation(self):
        """Test creating a basic result.
        
        GIVEN: Success flag
        WHEN: Creating ProcessingResult
        THEN: Result is created with default values
        """
        result = ProcessingResult(success=True)
        
        assert result.success is True
        assert result.knowledge_graph == {}
        assert result.vectors == []
        assert result.metadata == {}
        assert result.errors == []
        assert result.warnings == []
    
    def test_with_knowledge_graph(self):
        """Test result with knowledge graph.
        
        GIVEN: Result with entities and relationships
        WHEN: Checking has_knowledge_graph()
        THEN: Returns True
        """
        result = ProcessingResult(
            success=True,
            knowledge_graph={
                'entities': [{'id': '1', 'type': 'Person'}],
                'relationships': [{'from': '1', 'to': '2', 'type': 'knows'}]
            }
        )
        
        assert result.has_knowledge_graph() is True
        assert result.get_entity_count() == 1
        assert result.get_relationship_count() == 1
    
    def test_with_vectors(self):
        """Test result with vectors.
        
        GIVEN: Result with vector embeddings
        WHEN: Checking has_vectors()
        THEN: Returns True
        """
        result = ProcessingResult(
            success=True,
            vectors=[[0.1, 0.2, 0.3]]
        )
        
        assert result.has_vectors() is True
        assert len(result.vectors) == 1
    
    def test_add_error(self):
        """Test adding errors to result.
        
        GIVEN: Successful result
        WHEN: Adding an error
        THEN: Error is added and success is set to False
        """
        result = ProcessingResult(success=True)
        result.add_error("Something went wrong")
        
        assert result.success is False
        assert "Something went wrong" in result.errors
    
    def test_add_warning(self):
        """Test adding warnings to result.
        
        GIVEN: Result
        WHEN: Adding a warning
        THEN: Warning is added but success unchanged
        """
        result = ProcessingResult(success=True)
        result.add_warning("Minor issue")
        
        assert result.success is True
        assert "Minor issue" in result.warnings
    
    def test_merge_knowledge_graphs(self):
        """Test merging knowledge graphs.
        
        GIVEN: Two results with knowledge graphs
        WHEN: Merging results
        THEN: Knowledge graphs are combined
        """
        result1 = ProcessingResult(
            success=True,
            knowledge_graph={
                'entities': [{'id': '1', 'type': 'Person'}],
                'relationships': [{'from': '1', 'to': '2'}]
            }
        )
        
        result2 = ProcessingResult(
            success=True,
            knowledge_graph={
                'entities': [{'id': '3', 'type': 'Organization'}],
                'relationships': [{'from': '3', 'to': '1'}]
            }
        )
        
        result1.merge(result2)
        
        assert result1.get_entity_count() == 2
        assert result1.get_relationship_count() == 2
    
    def test_merge_vectors(self):
        """Test merging vectors.
        
        GIVEN: Two results with vectors
        WHEN: Merging results
        THEN: Vectors are combined
        """
        result1 = ProcessingResult(
            success=True,
            vectors=[[0.1, 0.2]]
        )
        
        result2 = ProcessingResult(
            success=True,
            vectors=[[0.3, 0.4]]
        )
        
        result1.merge(result2)
        
        assert len(result1.vectors) == 2
    
    def test_merge_errors(self):
        """Test merging with errors.
        
        GIVEN: Two results, one with errors
        WHEN: Merging results
        THEN: Success is updated and errors combined
        """
        result1 = ProcessingResult(success=True)
        result2 = ProcessingResult(success=False, errors=["Error occurred"])
        
        result1.merge(result2)
        
        assert result1.success is False
        assert "Error occurred" in result1.errors


class TestProcessorProtocol:
    """Tests for ProcessorProtocol and is_processor utility."""
    
    def test_is_processor_valid(self):
        """Test is_processor with valid processor.
        
        GIVEN: Object implementing all protocol methods
        WHEN: Checking with is_processor()
        THEN: Returns True
        """
        class ValidProcessor:
            def can_handle(self, context: ProcessingContext) -> bool:
                return True
            
            def process(self, context: ProcessingContext) -> ProcessingResult:
                return ProcessingResult(success=True)
            
            def get_capabilities(self) -> Dict[str, Any]:
                return {'name': 'TestProcessor'}
        
        processor = ValidProcessor()
        assert is_processor(processor) is True
    
    def test_is_processor_missing_method(self):
        """Test is_processor with incomplete implementation.
        
        GIVEN: Object missing protocol methods
        WHEN: Checking with is_processor()
        THEN: Returns False
        """
        class IncompleteProcessor:
            def can_handle(self, context: ProcessingContext) -> bool:
                return True
            # Missing process() and get_capabilities()
        
        processor = IncompleteProcessor()
        assert is_processor(processor) is False
    
    def test_is_processor_not_callable(self):
        """Test is_processor with non-callable attributes.
        
        GIVEN: Object with non-callable protocol attributes
        WHEN: Checking with is_processor()
        THEN: Returns False
        """
        class BadProcessor:
            can_handle = "not a function"
            process = None
            get_capabilities = 123
        
        processor = BadProcessor()
        assert is_processor(processor) is False


class TestProcessorImplementation:
    """Tests for implementing a custom processor."""
    
    def test_minimal_processor(self):
        """Test a minimal processor implementation.
        
        GIVEN: Minimal processor implementation
        WHEN: Using processor with protocol
        THEN: All methods work correctly
        """
        class MinimalProcessor:
            def can_handle(self, context: ProcessingContext) -> bool:
                return context.get_format() == 'txt'
            
            def process(self, context: ProcessingContext) -> ProcessingResult:
                return ProcessingResult(
                    success=True,
                    knowledge_graph={'entities': [], 'relationships': []},
                    metadata={'processor': 'MinimalProcessor'}
                )
            
            def get_capabilities(self) -> Dict[str, Any]:
                return {
                    'name': 'MinimalProcessor',
                    'handles': ['txt'],
                    'outputs': ['knowledge_graph']
                }
        
        processor = MinimalProcessor()
        
        # Test can_handle
        context = ProcessingContext(
            InputType.FILE,
            "file.txt",
            metadata={'format': 'txt'}
        )
        assert processor.can_handle(context) is True
        
        # Test process
        result = processor.process(context)
        assert result.success is True
        assert result.metadata['processor'] == 'MinimalProcessor'
        
        # Test get_capabilities
        caps = processor.get_capabilities()
        assert caps['name'] == 'MinimalProcessor'
        assert 'txt' in caps['handles']
