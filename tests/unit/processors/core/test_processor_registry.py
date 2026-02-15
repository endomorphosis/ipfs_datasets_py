"""Tests for ProcessorRegistry.

Comprehensive tests for processor registration, discovery, priority-based
selection, and capability reporting.
"""

import pytest
from typing import Dict, Any

from ipfs_datasets_py.processors.core import (
    ProcessorRegistry,
    ProcessorEntry,
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
    get_global_registry,
)


# Mock processors for testing
class MockPDFProcessor:
    """Mock processor that handles PDF files."""
    
    def can_handle(self, context: ProcessingContext) -> bool:
        return context.get_format() == 'pdf'
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        return ProcessingResult(
            success=True,
            knowledge_graph={'entities': ['pdf_entity']},
            metadata={'processor': 'MockPDFProcessor'}
        )
    
    def get_capabilities(self) -> Dict[str, Any]:
        return {
            'name': 'MockPDFProcessor',
            'input_types': [InputType.FILE],
            'formats': ['pdf'],
            'outputs': ['knowledge_graph', 'vectors']
        }


class MockGraphRAGProcessor:
    """Mock processor that handles URLs."""
    
    def can_handle(self, context: ProcessingContext) -> bool:
        return context.input_type == InputType.URL
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        return ProcessingResult(
            success=True,
            knowledge_graph={'entities': ['url_entity']},
            metadata={'processor': 'MockGraphRAGProcessor'}
        )
    
    def get_capabilities(self) -> Dict[str, Any]:
        return {
            'name': 'MockGraphRAGProcessor',
            'input_types': [InputType.URL],
            'formats': ['html', 'htm'],
            'outputs': ['knowledge_graph', 'vectors']
        }


class MockMultimediaProcessor:
    """Mock processor that handles multimedia files."""
    
    def can_handle(self, context: ProcessingContext) -> bool:
        fmt = context.get_format()
        return fmt in ('mp4', 'mp3', 'wav', 'avi')
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        return ProcessingResult(
            success=True,
            knowledge_graph={'entities': ['media_entity']},
            metadata={'processor': 'MockMultimediaProcessor'}
        )
    
    def get_capabilities(self) -> Dict[str, Any]:
        return {
            'name': 'MockMultimediaProcessor',
            'input_types': [InputType.FILE],
            'formats': ['mp4', 'mp3', 'wav', 'avi'],
            'outputs': ['knowledge_graph', 'vectors', 'transcription']
        }


class MockErrorProcessor:
    """Mock processor that raises errors."""
    
    def can_handle(self, context: ProcessingContext) -> bool:
        raise RuntimeError("Simulated can_handle error")
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        raise RuntimeError("Simulated processing error")
    
    def get_capabilities(self) -> Dict[str, Any]:
        raise RuntimeError("Simulated capabilities error")


class TestProcessorRegistry:
    """Test basic ProcessorRegistry functionality."""
    
    def test_registry_creation(self):
        """Test creating a new registry."""
        registry = ProcessorRegistry()
        assert len(registry) == 0
        assert registry.get_total_count() == 0
        assert registry.get_enabled_count() == 0
    
    def test_register_processor(self):
        """Test registering a processor."""
        registry = ProcessorRegistry()
        processor = MockPDFProcessor()
        
        name = registry.register(processor, priority=10, name="PDF Processor")
        
        assert name == "PDF Processor"
        assert len(registry) == 1
        assert "PDF Processor" in registry
        assert registry.get_processor("PDF Processor") is processor
    
    def test_register_without_name(self):
        """Test registering processor without explicit name."""
        registry = ProcessorRegistry()
        processor = MockPDFProcessor()
        
        name = registry.register(processor, priority=10)
        
        assert name == "MockPDFProcessor"  # Class name used
        assert len(registry) == 1
    
    def test_register_duplicate_name(self):
        """Test that registering duplicate name raises error."""
        registry = ProcessorRegistry()
        processor1 = MockPDFProcessor()
        processor2 = MockGraphRAGProcessor()
        
        registry.register(processor1, name="TestProcessor")
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(processor2, name="TestProcessor")
    
    def test_unregister_processor(self):
        """Test unregistering a processor."""
        registry = ProcessorRegistry()
        processor = MockPDFProcessor()
        
        registry.register(processor, name="PDF Processor")
        assert len(registry) == 1
        
        result = registry.unregister("PDF Processor")
        assert result is True
        assert len(registry) == 0
        assert "PDF Processor" not in registry
    
    def test_unregister_nonexistent(self):
        """Test unregistering a processor that doesn't exist."""
        registry = ProcessorRegistry()
        
        result = registry.unregister("Nonexistent")
        assert result is False


class TestProcessorSelection:
    """Test processor selection and discovery."""
    
    def test_get_processors_by_format(self):
        """Test getting processors by format."""
        registry = ProcessorRegistry()
        pdf_proc = MockPDFProcessor()
        graphrag_proc = MockGraphRAGProcessor()
        
        registry.register(pdf_proc, priority=10, name="PDF")
        registry.register(graphrag_proc, priority=10, name="GraphRAG")
        
        # PDF context should match PDF processor
        pdf_context = ProcessingContext(
            input_type=InputType.FILE,
            source="test.pdf",
            metadata={'format': 'pdf'}
        )
        processors = registry.get_processors(pdf_context)
        assert len(processors) == 1
        assert processors[0] is pdf_proc
    
    def test_get_processors_by_input_type(self):
        """Test getting processors by input type."""
        registry = ProcessorRegistry()
        pdf_proc = MockPDFProcessor()
        graphrag_proc = MockGraphRAGProcessor()
        
        registry.register(pdf_proc, priority=10, name="PDF")
        registry.register(graphrag_proc, priority=20, name="GraphRAG")
        
        # URL context should match GraphRAG processor
        url_context = ProcessingContext(
            input_type=InputType.URL,
            source="https://example.com"
        )
        processors = registry.get_processors(url_context)
        assert len(processors) == 1
        assert processors[0] is graphrag_proc
    
    def test_priority_ordering(self):
        """Test that processors are checked in priority order."""
        registry = ProcessorRegistry()
        pdf_proc = MockPDFProcessor()
        graphrag_proc = MockGraphRAGProcessor()
        multimedia_proc = MockMultimediaProcessor()
        
        # Register in random order
        registry.register(pdf_proc, priority=10, name="PDF")
        registry.register(graphrag_proc, priority=30, name="GraphRAG")
        registry.register(multimedia_proc, priority=20, name="Multimedia")
        
        # Get all processors - should be sorted by priority
        all_procs = registry.get_all_processors()
        assert len(all_procs) == 3
        
        # Check priority order (highest first)
        names = [name for name, _, _ in all_procs]
        priorities = [priority for _, _, priority in all_procs]
        
        assert priorities == [30, 20, 10]
        assert names == ["GraphRAG", "Multimedia", "PDF"]
    
    def test_get_processors_with_limit(self):
        """Test limiting number of returned processors."""
        registry = ProcessorRegistry()
        
        # Create multiple processors that all handle the same format
        class UniversalProcessor:
            def can_handle(self, context: ProcessingContext) -> bool:
                return True  # Handles everything
            
            def process(self, context: ProcessingContext) -> ProcessingResult:
                return ProcessingResult(success=True)
            
            def get_capabilities(self) -> Dict[str, Any]:
                return {'name': 'Universal'}
        
        # Register 5 universal processors
        for i in range(5):
            proc = UniversalProcessor()
            registry.register(proc, priority=10-i, name=f"Universal{i}")
        
        context = ProcessingContext(InputType.FILE, "test.txt")
        
        # Get all
        all_procs = registry.get_processors(context)
        assert len(all_procs) == 5
        
        # Get limited
        limited = registry.get_processors(context, limit=2)
        assert len(limited) == 2
    
    def test_no_suitable_processors(self):
        """Test when no processors can handle the input."""
        registry = ProcessorRegistry()
        pdf_proc = MockPDFProcessor()
        
        registry.register(pdf_proc, priority=10, name="PDF")
        
        # Try with a format no processor handles
        context = ProcessingContext(
            input_type=InputType.FILE,
            source="test.xyz",
            metadata={'format': 'xyz'}
        )
        processors = registry.get_processors(context)
        
        assert len(processors) == 0


class TestProcessorEnableDisable:
    """Test enabling and disabling processors."""
    
    def test_disable_processor(self):
        """Test disabling a processor."""
        registry = ProcessorRegistry()
        processor = MockPDFProcessor()
        
        registry.register(processor, name="PDF")
        assert registry.get_enabled_count() == 1
        
        result = registry.disable("PDF")
        assert result is True
        assert registry.get_enabled_count() == 0
        assert registry.get_total_count() == 1  # Still registered
    
    def test_enable_processor(self):
        """Test enabling a disabled processor."""
        registry = ProcessorRegistry()
        processor = MockPDFProcessor()
        
        registry.register(processor, name="PDF", enabled=False)
        assert registry.get_enabled_count() == 0
        
        result = registry.enable("PDF")
        assert result is True
        assert registry.get_enabled_count() == 1
    
    def test_disabled_processor_not_selected(self):
        """Test that disabled processors are not selected."""
        registry = ProcessorRegistry()
        processor = MockPDFProcessor()
        
        registry.register(processor, name="PDF")
        registry.disable("PDF")
        
        context = ProcessingContext(
            input_type=InputType.FILE,
            source="test.pdf",
            metadata={'format': 'pdf'}
        )
        processors = registry.get_processors(context)
        
        assert len(processors) == 0  # Disabled processor not returned


class TestCapabilities:
    """Test capability aggregation and reporting."""
    
    def test_get_capabilities(self):
        """Test getting aggregated capabilities."""
        registry = ProcessorRegistry()
        pdf_proc = MockPDFProcessor()
        graphrag_proc = MockGraphRAGProcessor()
        
        registry.register(pdf_proc, priority=10, name="PDF")
        registry.register(graphrag_proc, priority=20, name="GraphRAG")
        
        caps = registry.get_capabilities()
        
        assert caps['total_processors'] == 2
        assert caps['enabled_processors'] == 2
        assert len(caps['processors']) == 2
        
        # Check aggregated formats
        assert 'pdf' in caps['supported_formats']
        assert 'html' in caps['supported_formats']
        assert 'htm' in caps['supported_formats']
    
    def test_capabilities_with_disabled(self):
        """Test capabilities with disabled processors."""
        registry = ProcessorRegistry()
        pdf_proc = MockPDFProcessor()
        
        registry.register(pdf_proc, name="PDF")
        registry.disable("PDF")
        
        caps = registry.get_capabilities()
        
        assert caps['total_processors'] == 1
        assert caps['enabled_processors'] == 0
        assert caps['processors'][0]['enabled'] is False
    
    def test_capabilities_with_error(self):
        """Test capabilities when processor raises error."""
        registry = ProcessorRegistry()
        error_proc = MockErrorProcessor()
        
        registry.register(error_proc, name="Error")
        
        caps = registry.get_capabilities()
        
        # Should handle error gracefully
        assert caps['total_processors'] == 1
        assert 'error' in caps['processors'][0]


class TestErrorHandling:
    """Test error handling in registry operations."""
    
    def test_can_handle_error(self):
        """Test handling errors in can_handle()."""
        registry = ProcessorRegistry()
        error_proc = MockErrorProcessor()
        pdf_proc = MockPDFProcessor()
        
        registry.register(error_proc, priority=20, name="Error")
        registry.register(pdf_proc, priority=10, name="PDF")
        
        context = ProcessingContext(
            input_type=InputType.FILE,
            source="test.pdf",
            metadata={'format': 'pdf'}
        )
        
        # Should skip error processor and find PDF processor
        processors = registry.get_processors(context)
        assert len(processors) == 1
        assert processors[0] is pdf_proc


class TestRegistryClear:
    """Test clearing the registry."""
    
    def test_clear(self):
        """Test clearing all processors."""
        registry = ProcessorRegistry()
        
        registry.register(MockPDFProcessor(), name="PDF")
        registry.register(MockGraphRAGProcessor(), name="GraphRAG")
        
        assert len(registry) == 2
        
        registry.clear()
        
        assert len(registry) == 0
        assert registry.get_total_count() == 0
        assert "PDF" not in registry
        assert "GraphRAG" not in registry


class TestGlobalRegistry:
    """Test global registry singleton."""
    
    def test_get_global_registry(self):
        """Test getting the global registry."""
        registry1 = get_global_registry()
        registry2 = get_global_registry()
        
        # Should return same instance
        assert registry1 is registry2
    
    def test_global_registry_persistence(self):
        """Test that global registry persists across calls."""
        registry = get_global_registry()
        registry.clear()  # Start fresh
        
        processor = MockPDFProcessor()
        registry.register(processor, name="PDF")
        
        # Get registry again
        registry2 = get_global_registry()
        assert len(registry2) == 1
        assert "PDF" in registry2


class TestProcessorEntry:
    """Test ProcessorEntry dataclass."""
    
    def test_entry_creation(self):
        """Test creating a ProcessorEntry."""
        processor = MockPDFProcessor()
        
        entry = ProcessorEntry(
            processor=processor,
            priority=10,
            name="PDF",
            enabled=True,
            metadata={'version': '1.0'}
        )
        
        assert entry.processor is processor
        assert entry.priority == 10
        assert entry.name == "PDF"
        assert entry.enabled is True
        assert entry.metadata == {'version': '1.0'}
    
    def test_entry_auto_name(self):
        """Test auto-generating name from class name."""
        processor = MockPDFProcessor()
        
        entry = ProcessorEntry(processor=processor)
        
        assert entry.name == "MockPDFProcessor"


class TestRegistryMagicMethods:
    """Test magic methods on ProcessorRegistry."""
    
    def test_len(self):
        """Test __len__ method."""
        registry = ProcessorRegistry()
        
        assert len(registry) == 0
        
        registry.register(MockPDFProcessor(), name="PDF")
        assert len(registry) == 1
        
        registry.register(MockGraphRAGProcessor(), name="GraphRAG")
        assert len(registry) == 2
    
    def test_contains(self):
        """Test __contains__ method."""
        registry = ProcessorRegistry()
        
        assert "PDF" not in registry
        
        registry.register(MockPDFProcessor(), name="PDF")
        
        assert "PDF" in registry
        assert "GraphRAG" not in registry
    
    def test_repr(self):
        """Test __repr__ method."""
        registry = ProcessorRegistry()
        
        registry.register(MockPDFProcessor(), name="PDF")
        registry.register(MockGraphRAGProcessor(), name="GraphRAG", enabled=False)
        
        repr_str = repr(registry)
        
        assert "ProcessorRegistry" in repr_str
        assert "total=2" in repr_str
        assert "enabled=1" in repr_str


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
