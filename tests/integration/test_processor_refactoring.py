"""
Integration Tests for Universal Processor with Batch Processing.

These tests verify the end-to-end functionality of the refactored processor architecture.
"""

import pytest
import tempfile
import shutil
from pathlib import Path


class TestUniversalProcessorIntegration:
    """Integration tests for UniversalProcessor with all adapters."""
    
    def test_all_adapters_registered(self):
        """
        GIVEN: UniversalProcessor
        WHEN: Checking registered adapters
        THEN: All 5 adapters are registered
        """
        from ipfs_datasets_py.processors import UniversalProcessor
        
        processor = UniversalProcessor()
        processors = processor.list_processors()
        
        expected = {"PDFProcessor", "GraphRAGProcessor", "MultimediaProcessor", 
                   "FileConverterProcessor", "BatchProcessor"}
        actual = set(processors.keys())
        
        assert expected.issubset(actual), f"Missing processors: {expected - actual}"
    
    def test_adapter_priorities(self):
        """
        GIVEN: UniversalProcessor with all adapters
        WHEN: Checking priorities
        THEN: Priorities are correctly set
        """
        from ipfs_datasets_py.processors import UniversalProcessor
        
        processor = UniversalProcessor()
        processors = processor.list_processors()
        
        # BatchProcessor should have highest priority for folders
        assert processors["BatchProcessor"]["priority"] == 15
        
        # Specialized processors have high priority
        assert processors["PDFProcessor"]["priority"] == 10
        assert processors["GraphRAGProcessor"]["priority"] == 10
        assert processors["MultimediaProcessor"]["priority"] == 10
        
        # General purpose has lower priority
        assert processors["FileConverterProcessor"]["priority"] == 5
    
    @pytest.mark.asyncio
    async def test_routing_to_batch_processor(self):
        """
        GIVEN: UniversalProcessor and a folder
        WHEN: Finding processors for the folder
        THEN: BatchProcessor is selected
        """
        from ipfs_datasets_py.processors import UniversalProcessor
        
        processor = UniversalProcessor()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            processors_found = await processor.registry.find_processors(temp_dir)
            
            # Should find at least BatchProcessor
            assert len(processors_found) > 0
            
            # BatchProcessor should be first (highest priority)
            assert processors_found[0].get_name() == "BatchProcessor"
    
    @pytest.mark.asyncio
    async def test_batch_processing_workflow(self):
        """
        GIVEN: Folder with multiple files
        WHEN: Processing through UniversalProcessor
        THEN: All files are processed and aggregated
        """
        from ipfs_datasets_py.processors import UniversalProcessor
        from ipfs_datasets_py.processors.protocol import ProcessingStatus
        
        processor = UniversalProcessor()
        
        # Create test folder with files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            (Path(temp_dir) / "file1.txt").write_text("Test content 1")
            (Path(temp_dir) / "file2.txt").write_text("Test content 2")
            (Path(temp_dir) / "file3.md").write_text("# Markdown content")
            
            # Process the folder
            result = await processor.process(temp_dir)
            
            # Verify result structure
            assert result is not None
            assert result.knowledge_graph is not None
            assert result.vectors is not None
            assert result.metadata is not None
            
            # Check metadata
            assert result.metadata.processor_name == "BatchProcessor"
            assert result.metadata.status in (ProcessingStatus.SUCCESS, ProcessingStatus.PARTIAL)
            
            # Check content
            assert "total_files" in result.content
            assert result.content["total_files"] >= 3
    
    def test_statistics_tracking(self):
        """
        GIVEN: UniversalProcessor
        WHEN: Getting statistics
        THEN: Statistics are available
        """
        from ipfs_datasets_py.processors import UniversalProcessor
        
        processor = UniversalProcessor()
        stats = processor.get_statistics()
        
        # Check statistics structure
        assert "total_calls" in stats
        assert "successful_calls" in stats
        assert "failed_calls" in stats
        assert "cache_hits" in stats
        assert "success_rate" in stats


class TestGraphRAGConsolidation:
    """Tests for GraphRAG consolidation."""
    
    def test_unified_processor_exists(self):
        """
        GIVEN: Unified GraphRAG module
        WHEN: Importing UnifiedGraphRAGProcessor
        THEN: Successfully imports
        """
        from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
        
        assert UnifiedGraphRAGProcessor is not None
    
    def test_backward_compatibility_aliases(self):
        """
        GIVEN: Unified GraphRAG module
        WHEN: Importing old class names
        THEN: All resolve to UnifiedGraphRAGProcessor
        """
        from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
            UnifiedGraphRAGProcessor,
            GraphRAGProcessor,
            WebsiteGraphRAGProcessor,
            AdvancedGraphRAGWebsiteProcessor,
            CompleteGraphRAGSystem
        )
        
        # All should be the same class
        assert GraphRAGProcessor is UnifiedGraphRAGProcessor
        assert WebsiteGraphRAGProcessor is UnifiedGraphRAGProcessor
        assert AdvancedGraphRAGWebsiteProcessor is UnifiedGraphRAGProcessor
        assert CompleteGraphRAGSystem is UnifiedGraphRAGProcessor
    
    def test_unified_processor_interface(self):
        """
        GIVEN: UnifiedGraphRAGProcessor
        WHEN: Creating an instance
        THEN: Has all expected methods
        """
        from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
        
        processor = UnifiedGraphRAGProcessor()
        
        # Check async methods
        assert hasattr(processor, 'process_website')
        assert hasattr(processor, 'process_multiple_websites')
        
        # Check sync methods
        assert hasattr(processor, 'search_entities')
        assert hasattr(processor, 'get_processing_history')
        assert hasattr(processor, 'get_statistics')
    
    def test_old_modules_have_deprecation_notices(self):
        """
        GIVEN: Old GraphRAG modules
        WHEN: Checking their documentation
        THEN: All have deprecation notices
        """
        # Test what we can without numpy/anyio dependencies
        from ipfs_datasets_py.processors import advanced_graphrag_website_processor
        
        doc = advanced_graphrag_website_processor.__doc__
        
        assert 'deprecated' in doc.lower()
        assert 'UnifiedGraphRAGProcessor' in doc
        assert '2.0.0' in doc or '1.0.0' in doc


class TestProcessorProtocol:
    """Tests for ProcessorProtocol compliance."""
    
    def test_batch_adapter_implements_protocol(self):
        """
        GIVEN: BatchProcessorAdapter
        WHEN: Checking protocol compliance
        THEN: Implements all required methods
        """
        from ipfs_datasets_py.processors.adapters.batch_adapter import BatchProcessorAdapter
        
        adapter = BatchProcessorAdapter()
        
        # Check protocol methods
        assert hasattr(adapter, 'can_process')
        assert hasattr(adapter, 'process')
        assert hasattr(adapter, 'get_supported_types')
        assert hasattr(adapter, 'get_priority')
        assert hasattr(adapter, 'get_name')
        
        # Check return types
        assert isinstance(adapter.get_supported_types(), list)
        assert isinstance(adapter.get_priority(), int)
        assert isinstance(adapter.get_name(), str)


if __name__ == "__main__":
    # Manual test run
    import asyncio
    
    print("Running manual integration tests...")
    print()
    
    # Test 1
    test = TestUniversalProcessorIntegration()
    test.test_all_adapters_registered()
    print("✓ All adapters registered")
    
    test.test_adapter_priorities()
    print("✓ Adapter priorities correct")
    
    # Test 2
    test2 = TestGraphRAGConsolidation()
    test2.test_unified_processor_exists()
    print("✓ UnifiedGraphRAGProcessor exists")
    
    test2.test_backward_compatibility_aliases()
    print("✓ Backward compatibility aliases work")
    
    test2.test_unified_processor_interface()
    print("✓ UnifiedGraphRAGProcessor has correct interface")
    
    test2.test_old_modules_have_deprecation_notices()
    print("✓ Old modules have deprecation notices")
    
    # Test 3
    test3 = TestProcessorProtocol()
    test3.test_batch_adapter_implements_protocol()
    print("✓ BatchAdapter implements protocol")
    
    print()
    print("All manual tests passed!")
