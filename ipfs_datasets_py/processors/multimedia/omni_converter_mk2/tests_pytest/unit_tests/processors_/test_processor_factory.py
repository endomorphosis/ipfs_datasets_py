"""
Tests for the processor factory functionality (pytest version).

This module tests the processor factory's ability to create processors
dynamically based on available dependencies, fall back gracefully,
and produce appropriate mocks when necessary.

Converted from unittest to pytest format.
"""
from __future__ import annotations
import logging
from typing import Any, Callable
import pytest
from unittest.mock import MagicMock, patch

# Skip tests if the module can't be imported
try:
    from core.content_extractor.processors.processor_factory import (
        _make_processor,
        make_processors,
        _apply_cross_processor_dependencies,
        _ProcessorResources,
    )
    from configs import Configs
    from logger import logger as _debug_logger
except ImportError:
    pytest.skip("core.content_extractor.processors.processor_factory module not available", allow_module_level=True)


@pytest.fixture
def basic_resources_fixture() -> dict[str, Any]:
    """Set up test fixtures."""
    mock_logger = MagicMock(spec=logging.Logger)
    mock_configs = MagicMock(spec=Configs)
    
    # Mock dependencies
    mock_dependencies = {
        "openpyxl": MagicMock(),
        "pandas": None,  # Simulate unavailable dependency
    }

    # Basic processor resources
    basic_resources = {
        "supported_formats": {"xlsx", "xlsm"},
        "processor_name": "test_processor",
        "dependencies": mock_dependencies,
        "critical_resources": ["extract_text", "extract_metadata"],
        "optional_resources": ["extract_images"],
        "logger": mock_logger,
        "configs": mock_configs,
    }
    return basic_resources


@pytest.fixture
def text_processor_resources() -> dict[str, Any]:
    """Basic text processor resources that should exist."""
    mock_logger = MagicMock(spec=logging.Logger)
    mock_configs = MagicMock(spec=Configs)
    
    return {
        "supported_formats": {"txt", "plain", "text"},
        "processor_name": "text_processor",  # Use actual processor that exists
        "dependencies": {},  # Text processor doesn't need dependencies
        "critical_resources": ["extract_text", "process", "extract_metadata", "extract_structure"],
        "optional_resources": ["analyze"],
        "logger": mock_logger,
        "configs": mock_configs,
        "get_version": lambda: "1.0.0",
        "can_handle": MagicMock(),
        "processor_available": True,
    }


@pytest.mark.unit
class TestMakeProcessor:
    """Test the _make_processor factory function."""

    def test_creates_processor_with_all_dependencies_available(self, text_processor_resources) -> None:
        """
        Test that _make_processor creates a fully functional processor
        when all dependencies are available.
        
        Expected behavior:
        - Returns a processor instance (not a mock)
        - All critical resources are properly injected
        - Processor has required methods and attributes
        """
        # Arrange
        resources = text_processor_resources.copy()

        # Act
        processor = _make_processor(resources)

        # Assert
        assert processor is not None
        assert not isinstance(processor, MagicMock)
        
        # Verify processor has the expected class name
        assert processor.__class__.__name__ == "TextProcessor"
        
        # Verify processor has required callable methods
        assert callable(getattr(processor, "get_version", None))
        assert hasattr(processor, "processor_info")
        assert hasattr(processor, "configs")
        assert hasattr(processor, "resources")
        
        # Verify processor_info has the expected structure
        processor_info = processor.processor_info
        assert "processor_name" in processor_info
        assert "supported_formats" in processor_info
        assert processor_info["processor_name"] == "text_processor"

    def test_creates_processor_with_fallback_dependencies(self, text_processor_resources) -> None:
        """
        Test that _make_processor falls back to secondary dependencies
        when primary ones are unavailable.
        
        Expected behavior:
        - Uses fallback mechanism to load functions from fallback directory
        - Returns a functional processor with fallback implementation
        - Successfully finds and loads critical resources
        """
        # Arrange - Use text processor which uses fallback functions
        resources = text_processor_resources.copy()
        
        # Act
        processor = _make_processor(resources)
        
        # Assert
        assert processor is not None
        assert not isinstance(processor, MagicMock)
        
        # Verify fallback mechanism worked by checking processor type
        assert processor.__class__.__name__ == "TextProcessor"
        
        # Verify processor has working methods from fallback
        processor_info = processor.processor_info
        assert "processor_name" in processor_info
        assert processor_info["processor_name"] == "text_processor"

    def test_creates_mock_when_no_dependencies_available(self, text_processor_resources) -> None:
        """
        Test that _make_processor returns a mock when no dependencies
        are available for critical resources.
        
        Expected behavior:
        - When no fallback functions can be found, returns a MagicMock
        - Mock has all required methods
        - Mock methods return appropriate default values
        """
        # Arrange - Use a processor name that doesn't exist
        resources = text_processor_resources.copy()
        resources["processor_name"] = "nonexistent_processor"
        resources["supported_formats"] = {"fake"}
        
        # Act
        processor = _make_processor(resources)
        
        # Assert
        assert isinstance(processor, MagicMock)
        
        # Verify mock has all required methods
        assert hasattr(processor, "extract_text")
        assert hasattr(processor, "extract_metadata")
        assert hasattr(processor, "can_process")
        assert hasattr(processor, "supported_formats")
        
        # Verify mock methods return appropriate values
        assert processor.extract_text() == "Mocked text content"
        assert processor.extract_metadata() == {"mocked": "metadata"}
        assert processor.supported_formats == {"fake"}
        
        # Verify processor reports all capabilities as mocked
        processor_info = processor.processor_info
        assert processor_info["implementation_used"] == "mock"

    def test_handles_partial_dependency_availability(self, text_processor_resources) -> None:
        """
        Test that _make_processor handles cases where some but not all
        methods can be provided by available dependencies.
        
        Expected behavior:
        - Factory tries to find all critical resources
        - If some are missing, falls back to mock
        - Current implementation is all-or-nothing for critical resources
        """
        # Arrange - Use existing processor but simulate missing critical resources
        resources = text_processor_resources.copy()
        resources["critical_resources"] = ["extract_text", "nonexistent_method"]
        
        # Act
        processor = _make_processor(resources)
        
        # Assert - Current implementation should return mock if critical resources missing
        # Since "nonexistent_method" won't be found, should fall back to mock
        assert isinstance(processor, MagicMock)
        
        # Verify mock has expected attributes
        processor_info = processor.processor_info
        assert processor_info["implementation_used"] == "mock"

    def test_respects_dependency_priority_order(self, text_processor_resources) -> None:
        """
        Test that _make_processor tries dependencies in the correct order.
        
        Expected behavior:
        - Dependencies are checked in order: by_dependency -> by_mime_type -> fallbacks
        - First available implementation is used
        - For text_processor, mime_type implementation should be preferred over fallback
        """
        # Arrange
        resources = text_processor_resources.copy()
        
        # Act
        processor = _make_processor(resources)
        
        # Assert
        assert processor is not None
        assert not isinstance(processor, MagicMock)
        
        # Verify that the correct implementation is being used
        # text_processor should use the TextProcessor class from mime_type
        assert processor.__class__.__name__ == "TextProcessor"
        
        # Verify processor info shows successful creation
        processor_info = processor.processor_info
        assert processor_info["processor_name"] == "text_processor"

    def test_when_processor_doesnt_exist(self, text_processor_resources) -> None:
        """Test that the processor factory correctly handles cases where the processor does not exist.

        Expected behavior:
        - If the processor does not exist, return a mock processor
        - Mock processor should have all required methods
        - Mock processor should report mock implementation
        """
        # Arrange
        nonexistent_resources = text_processor_resources.copy()
        nonexistent_resources["processor_name"] = "completely_nonexistent_processor"
        nonexistent_resources["supported_formats"] = {"fake_format"}
        
        # Act
        processor = _make_processor(nonexistent_resources)
        
        # Assert
        assert isinstance(processor, MagicMock)
        
        # Verify mock has all required methods
        assert hasattr(processor, "extract_text")
        assert hasattr(processor, "extract_metadata")
        assert hasattr(processor, "can_process")
        assert hasattr(processor, "supported_formats")
        
        # Verify processor info shows mock implementation
        processor_info = processor.processor_info
        assert processor_info["implementation_used"] == "mock"
        assert processor_info["processor_name"] == "completely_nonexistent_processor"

    def test_when_no_dependencies_are_needed(self, text_processor_resources) -> None:
        """Test that the processor factory correctly handles creation of processors that don't need any
        external dependencies or configurations to run.

        Expected behavior:
        - Function runs whether or not the dependency key is present or empty
        - If processor exists (like text_processor), return real processor
        - Should never return a mock for existing processors
        """
        # Arrange
        no_deps_resources = text_processor_resources.copy()
        no_deps_resources["dependencies"] = {}  # No dependencies needed
        
        # Act
        processor = _make_processor(no_deps_resources)
        
        # Assert
        assert processor is not None
        assert not isinstance(processor, MagicMock)
        
        # Verify processor is the real TextProcessor class
        assert processor.__class__.__name__ == "TextProcessor"
        
        # Verify processor has required attributes
        assert hasattr(processor, "configs")
        assert hasattr(processor, "resources")
        assert hasattr(processor, "processor_info")
        
        # Verify processor info shows successful creation
        processor_info = processor.processor_info
        assert processor_info["processor_name"] == "text_processor"

    def test_injects_logger_and_configs_properly(self, text_processor_resources) -> None:
        """
        Test that _make_processor properly injects logger and configs
        into the created processor.
        
        Expected behavior:
        - Logger is accessible in processor resources
        - Configs are passed to processor constructor
        - Both are available for use in processor methods
        """
        # Arrange
        resources = text_processor_resources.copy()
        mock_configs = resources["configs"]
        mock_logger = resources["logger"]
        
        # Act
        processor = _make_processor(resources)
        
        # Assert
        assert processor is not None
        assert not isinstance(processor, MagicMock)
        
        # Verify configs are accessible
        assert processor.configs == mock_configs
        
        # Verify resources contain the logger
        assert "logger" in processor.resources
        assert processor.resources["logger"] == mock_logger
        
        # Verify processor was created successfully
        assert processor.__class__.__name__ == "TextProcessor"


@pytest.mark.unit  
class TestMakeProcessors:
    """Test the make_processors function that creates all processors."""

    def test_creates_all_processor_types(self) -> None:
        """
        Test that make_processors creates all expected processor types.
        
        Expected behavior:
        - Creates ability processors (image, audio, text, etc.)
        - Creates MIME-type processors (xlsx, pdf, etc.)
        - Returns dict with all processor names as keys
        """
        # Act
        processors: dict[str, tuple[str, Any, set]] = make_processors()
        
        # Assert
        assert isinstance(processors, dict)

        # Verify ability processors
        expected_ability_processors = [
            "image_processor",
            "audio_processor", 
            "text_processor",
            "document_processor",
        ]
        for processor_name in expected_ability_processors:
            assert processor_name in processors
            assert processors[processor_name] is not None
        
        # Verify MIME-type processors
        expected_mime_processors = [
            "xlsx_processor",
            "pdf_processor",
            "docx_processor",
            "pptx_processor",
        ]
        for processor_name in expected_mime_processors:
            assert processor_name in processors
            assert processors[processor_name] is not None
        
        # Verify all processors have consistent interface
        for processor_name, processor in processors.items():
            assert hasattr(processor[1], "can_process")
            assert hasattr(processor[1], "supported_formats")
            assert hasattr(processor[1], "processor_info")

    def test_handles_cross_processor_dependencies(self) -> None:
        """
        Test that processors can use other processors (e.g., XLSX using image).
        
        Expected behavior:
        - XLSX processor can access image processor for extract_images
        - Dependency injection works across processor types
        - Circular dependencies are prevented
        """
        # Act
        processors = make_processors()
        
        # Assert
        xlsx_processor = processors["xlsx_processor"]
        image_processor = processors["image_processor"]
        
        # Verify XLSX processor can extract images (using image processor)
        assert hasattr(xlsx_processor[1], "extract_images")
        
        # Verify cross-processor method works
        images = xlsx_processor[1].extract_images()
        assert images is not None
        
        # Verify processor info shows cross-dependency
        xlsx_info = xlsx_processor[1].processor_info
        assert "dependencies" in xlsx_info
        assert "image_processor" in xlsx_info["dependencies"]

        # Verify no circular dependencies
        image_info = image_processor[1].processor_info
        if "dependencies" in image_info:
            assert "xlsx_processor" not in image_info["dependencies"]

    def test_reports_capability_availability_correctly(self) -> None:
        """
        Test that each processor correctly reports its available capabilities.
        
        Expected behavior:
        - processor.processor_info includes available capabilities
        - Degraded capabilities are clearly marked
        - Mock implementations are identified
        """
        # Act
        processors = make_processors()
        
        # Assert
        for processor_name, processor in processors.items():
            processor_info = processor[1].processor_info
            
            # Verify basic info structure
            assert "processor_name" in processor_info
            assert "capabilities" in processor_info
            assert "supported_formats" in processor_info
            
            # Verify capability reporting structure
            capabilities = processor_info["capabilities"]
            for capability_name, capability_info in capabilities.items():
                assert "available" in capability_info
                assert "implementation" in capability_info
                assert isinstance(capability_info["available"], bool)
                assert isinstance(capability_info["implementation"], str)
                
                # If not available, should be marked as mock
                if not capability_info["available"]:
                    assert capability_info["implementation"] == "mock"

    def test_all_processors_have_consistent_interface(self) -> None:
        """
        Test that all created processors implement the same interface.
        
        Expected behavior:
        - All have can_process method
        - All have supported_formats property
        - All have processor_info property
        - All have process method
        """
        # Act
        processors = make_processors()
        
        # Assert
        required_methods = ["can_process", "process"]
        required_properties = ["supported_formats", "processor_info"]
        
        for processor_name, processor in processors.items():
            # Check required methods
            for method_name in required_methods:
                assert hasattr(processor[1], method_name), \
                    f"{processor_name} missing method {method_name}"
                assert callable(getattr(processor[1], method_name)), \
                    f"{processor_name}.{method_name} is not callable"
            
            # Check required properties
            for property_name in required_properties:
                assert hasattr(processor[1], property_name), \
                    f"{processor_name} missing property {property_name}"
            
            # Verify property types
            assert isinstance(processor[1].supported_formats, (set, frozenset))
            assert isinstance(processor[1].processor_info, dict)
            
            # Verify method signatures work
            assert isinstance(processor[1].can_process("test.txt"), bool)


@pytest.fixture
def mock_processors():
    """Create mock processors for testing cross-processor dependencies."""
    mock_xlsx_processor = MagicMock()
    mock_xlsx_processor.processor_info = {"dependencies": []}
    mock_xlsx_processor.extract_images = MagicMock(return_value=["image1.png", "image2.jpg"])
    
    mock_image_processor = MagicMock()
    mock_image_processor.process_image = MagicMock(side_effect=lambda x: f"processed_{x}")
    
    mock_pdf_processor = MagicMock()
    mock_pdf_processor.processor_info = {"dependencies": []}
    mock_pdf_processor.extract_text = MagicMock(return_value="original text")
    
    mock_ocr_processor = MagicMock()
    mock_ocr_processor.enhance_text = MagicMock(side_effect=lambda x: f"enhanced_{x}")
    
    return {
        "xlsx_processor": mock_xlsx_processor,
        "image_processor": mock_image_processor,
        "pdf_processor": mock_pdf_processor,
        "ocr_processor": mock_ocr_processor
    }


@pytest.mark.unit
class TestCrossProcessorDependencies:
    """Test cases for cross-processor dependency utility function."""
    
    def test_apply_cross_processor_dependencies_basic_enhancement(self, mock_processors):
        """Test basic method enhancement with dependency."""
        result = _apply_cross_processor_dependencies(
            mock_processors,
            [("xlsx_processor", "extract_images", "image_processor", "process_image")]
        )
        
        # Should return the processors dict
        assert result == mock_processors
        
        # Test that the method was enhanced
        enhanced_result = mock_processors["xlsx_processor"].extract_images()
        expected = ["processed_image1.png", "processed_image2.jpg"]
        assert enhanced_result == expected
    
    def test_apply_cross_processor_dependencies_multiple_dependencies(self, mock_processors):
        """Test applying multiple cross-processor dependencies."""
        dependencies = [
            ("xlsx_processor", "extract_images", "image_processor", "process_image"),
            ("pdf_processor", "extract_text", "ocr_processor", "enhance_text")
        ]
        result = _apply_cross_processor_dependencies(mock_processors, dependencies)
        
        # Should return processors
        assert result == mock_processors
        
        # Test both enhancements work
        images_result = mock_processors["xlsx_processor"].extract_images()
        assert images_result == ["processed_image1.png", "processed_image2.jpg"]
        
        text_result = mock_processors["pdf_processor"].extract_text()
        assert text_result == "enhanced_original text"
    
    def test_apply_cross_processor_dependencies_empty_dependencies_list(self, mock_processors):
        """Test handling of empty dependencies list."""
        result = _apply_cross_processor_dependencies(mock_processors, [])
        # Should return processors unchanged
        assert result == mock_processors


@pytest.mark.unit
class TestProcessorResources:
    """Test the _ProcessorResources TypedDict structure."""

    def test_processor_resources_structure_is_valid(self) -> None:
        """
        Test that _ProcessorResources TypedDict has correct structure.
        
        Expected behavior:
        - Has all required fields
        - Field types are correct
        - Can be used for type checking
        """
        # This test verifies the TypedDict structure at import time
        # The fact that we can import _ProcessorResources means it's syntactically valid
        
        # Verify _ProcessorResources can be used for type annotations
        def test_function(resources: _ProcessorResources) -> None:
            pass
        
        # Create a valid resources dict
        valid_resources = {
            "supported_formats": {"xlsx", "xlsm"},
            "processor_name": "test_processor",
            "dependencies": {"openpyxl": MagicMock()},
            "critical_resources": ["extract_text"],
            "optional_resources": ["extract_images"],
            "logger": MagicMock(spec=logging.Logger),
            "configs": MagicMock(spec=Configs),
        }
        
        # Should not raise any type errors
        test_function(valid_resources)
        
        # Verify required fields
        required_fields = [
            "supported_formats", "processor_name", "dependencies",
            "critical_resources", "optional_resources", "logger", "configs"
        ]
        for field in required_fields:
            assert field in valid_resources


@pytest.mark.unit
class TestFactoryErrorHandling:
    """Test error handling in the factory."""

    def test_handles_import_errors_gracefully(self, basic_resources_fixture) -> None:
        """
        Test that factory handles ImportError when loading processors.
        
        Expected behavior:
        - Catches ImportError
        - Falls back to next option or mock
        - Logs appropriate warning
        - Never crashes
        """
        # Arrange
        resources = {
            **basic_resources_fixture,
            "processor_name": "nonexistent_processor",
            "dependencies": {"nonexistent_module": None},
        }
        
        # Act - should not raise an exception
        processor = _make_processor(resources)
        
        # Assert
        assert processor is not None
        # Should fall back to mock for nonexistent processor
        assert isinstance(processor, MagicMock)

    def test_handles_missing_critical_resources(self, basic_resources_fixture) -> None:
        """
        Test that factory handles cases where critical resources are missing.
        
        Expected behavior:
        - Identifies missing resources
        - Returns mock with those methods
        - Reports degradation clearly
        """
        # Arrange
        resources = {
            **basic_resources_fixture,
            "dependencies": {},  # No dependencies available
            "critical_resources": ["extract_text", "extract_metadata"],
        }
        
        # Act
        processor = _make_processor(resources)
        
        # Assert
        assert isinstance(processor, MagicMock)
        
        # Verify critical methods are available as mocks
        assert hasattr(processor, "extract_text")
        assert hasattr(processor, "extract_metadata")
        
        # Verify processor info reports missing critical resources
        processor_info = processor.processor_info
        assert "capabilities" in processor_info
        
        for critical_resource in resources["critical_resources"]:
            assert critical_resource in processor_info["capabilities"]
            assert not processor_info["capabilities"][critical_resource]["available"]
            assert processor_info["capabilities"][critical_resource]["implementation"] == "mock"