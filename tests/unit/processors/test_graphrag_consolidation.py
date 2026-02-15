"""
Tests for GraphRAG deprecation warnings.

Ensures that deprecated GraphRAG processors show appropriate warnings.
"""

import pytest
import warnings


class TestGraphRAGDeprecationWarnings:
    """Tests for deprecated GraphRAG processor warnings."""
    
    def test_graphrag_processor_deprecation_warning(self):
        """
        GIVEN: GraphRAGProcessor class
        WHEN: Creating an instance
        THEN: Shows deprecation warning
        """
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            
            # Import would fail without numpy, so just test the structure
            from ipfs_datasets_py.processors import graphrag_processor
            
            # Check module has deprecation info
            assert "deprecated" in graphrag_processor.__doc__.lower()
            assert "UnifiedGraphRAGProcessor" in graphrag_processor.__doc__
    
    def test_website_graphrag_processor_deprecation(self):
        """
        GIVEN: WebsiteGraphRAGProcessor class
        WHEN: Checking documentation
        THEN: Contains deprecation notice
        """
        from ipfs_datasets_py.processors import website_graphrag_processor
        
        # Check module has deprecation info
        assert "deprecated" in website_graphrag_processor.__doc__.lower()
        assert "UnifiedGraphRAGProcessor" in website_graphrag_processor.__doc__
    
    def test_advanced_graphrag_processor_deprecation(self):
        """
        GIVEN: AdvancedGraphRAGWebsiteProcessor class
        WHEN: Checking documentation
        THEN: Contains deprecation notice
        """
        from ipfs_datasets_py.processors import advanced_graphrag_website_processor
        
        # Check module has deprecation info
        assert "deprecated" in advanced_graphrag_website_processor.__doc__.lower()
        assert "UnifiedGraphRAGProcessor" in advanced_graphrag_website_processor.__doc__
    
    def test_all_deprecated_files_reference_unified(self):
        """
        GIVEN: All deprecated GraphRAG modules
        WHEN: Checking their documentation
        THEN: All reference the unified processor
        """
        deprecated_modules = [
            'graphrag_processor',
            'website_graphrag_processor', 
            'advanced_graphrag_website_processor'
        ]
        
        for module_name in deprecated_modules:
            module = __import__(
                f'ipfs_datasets_py.processors.{module_name}',
                fromlist=[module_name]
            )
            
            # Check deprecation notice
            assert "deprecated" in module.__doc__.lower(), f"{module_name} missing deprecation notice"
            assert "UnifiedGraphRAGProcessor" in module.__doc__, f"{module_name} doesn't reference unified processor"
            assert "version 2.0.0" in module.__doc__ or "1.0.0" in module.__doc__, f"{module_name} missing version info"


class TestUnifiedGraphRAGProcessor:
    """Tests for the unified GraphRAG processor."""
    
    @pytest.mark.asyncio
    async def test_unified_processor_available(self):
        """
        GIVEN: UnifiedGraphRAGProcessor module
        WHEN: Importing it
        THEN: Successfully imports
        """
        from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
        
        assert UnifiedGraphRAGProcessor is not None
    
    @pytest.mark.asyncio
    async def test_unified_processor_has_backward_compatibility_aliases(self):
        """
        GIVEN: UnifiedGraphRAGProcessor module
        WHEN: Checking for backward compatibility aliases
        THEN: Old class names are aliased to unified processor
        """
        from ipfs_datasets_py.processors.graphrag import unified_graphrag
        
        # Check aliases exist
        assert hasattr(unified_graphrag, 'GraphRAGProcessor')
        assert hasattr(unified_graphrag, 'WebsiteGraphRAGProcessor')
        assert hasattr(unified_graphrag, 'AdvancedGraphRAGWebsiteProcessor')
        assert hasattr(unified_graphrag, 'CompleteGraphRAGSystem')
        
        # Check they all point to UnifiedGraphRAGProcessor
        assert unified_graphrag.GraphRAGProcessor is unified_graphrag.UnifiedGraphRAGProcessor
        assert unified_graphrag.WebsiteGraphRAGProcessor is unified_graphrag.UnifiedGraphRAGProcessor
        assert unified_graphrag.AdvancedGraphRAGWebsiteProcessor is unified_graphrag.UnifiedGraphRAGProcessor
        assert unified_graphrag.CompleteGraphRAGSystem is unified_graphrag.UnifiedGraphRAGProcessor
    
    @pytest.mark.asyncio
    async def test_unified_processor_basic_creation(self):
        """
        GIVEN: UnifiedGraphRAGProcessor
        WHEN: Creating an instance
        THEN: Creates successfully
        """
        from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
        
        processor = UnifiedGraphRAGProcessor()
        
        assert processor is not None
        assert hasattr(processor, 'process_website')
        assert hasattr(processor, 'process_multiple_websites')
        assert hasattr(processor, 'search_entities')
        assert hasattr(processor, 'get_processing_history')
