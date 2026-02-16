"""Integration tests for processors engines facade pattern.

Tests verify that the new modular engines/ structure works correctly:
- engines/llm/ facade imports from llm_optimizer.py
- engines/query/ facade imports from query_engine.py
- engines/relationship/ facade imports from relationship_*.py

All tests should pass with the facade pattern implementation.
"""

import pytest
import warnings
from typing import Any


class TestEnginesLLMFacade:
    """Test engines/llm/ facade imports and functionality."""
    
    def test_llm_optimizer_import_from_engines(self):
        """Test LLMOptimizer can be imported from engines.llm."""
        from ipfs_datasets_py.processors.engines.llm import LLMOptimizer
        assert LLMOptimizer is not None
        assert hasattr(LLMOptimizer, '__name__')
    
    def test_llm_chunk_import_from_engines(self):
        """Test LLMChunk can be imported from engines.llm."""
        from ipfs_datasets_py.processors.engines.llm import LLMChunk
        assert LLMChunk is not None
    
    def test_llm_document_import_from_engines(self):
        """Test LLMDocument can be imported from engines.llm."""
        from ipfs_datasets_py.processors.engines.llm import LLMDocument
        assert LLMDocument is not None
    
    def test_llm_optimizer_submodule_imports(self):
        """Test all LLM submodules can be imported."""
        from ipfs_datasets_py.processors.engines.llm import optimizer
        from ipfs_datasets_py.processors.engines.llm import chunker
        from ipfs_datasets_py.processors.engines.llm import embeddings
        from ipfs_datasets_py.processors.engines.llm import context
        from ipfs_datasets_py.processors.engines.llm import tokenizer
        from ipfs_datasets_py.processors.engines.llm import summarizer
        from ipfs_datasets_py.processors.engines.llm import multimodal
        
        # All should be importable modules
        assert optimizer is not None
        assert chunker is not None
        assert embeddings is not None
    
    def test_llm_optimizer_facade_is_same_as_original(self):
        """Test that engines.llm.LLMOptimizer is the same as original."""
        from ipfs_datasets_py.processors.engines.llm import LLMOptimizer as EnginesLLM
        from ipfs_datasets_py.processors.llm_optimizer import LLMOptimizer as OriginalLLM
        
        # Should be the exact same class
        assert EnginesLLM is OriginalLLM
    
    def test_text_processor_import(self):
        """Test TextProcessor can be imported from engines.llm."""
        from ipfs_datasets_py.processors.engines.llm import TextProcessor
        assert TextProcessor is not None
    
    def test_chunk_optimizer_import(self):
        """Test ChunkOptimizer can be imported from engines.llm."""
        from ipfs_datasets_py.processors.engines.llm import ChunkOptimizer
        assert ChunkOptimizer is not None


class TestEnginesQueryFacade:
    """Test engines/query/ facade imports and functionality."""
    
    def test_query_engine_import_from_engines(self):
        """Test QueryEngine can be imported from engines.query."""
        from ipfs_datasets_py.processors.engines.query import QueryEngine
        assert QueryEngine is not None
        assert hasattr(QueryEngine, '__name__')
    
    def test_query_engine_submodule_imports(self):
        """Test all query submodules can be imported."""
        from ipfs_datasets_py.processors.engines.query import engine
        from ipfs_datasets_py.processors.engines.query import parser
        from ipfs_datasets_py.processors.engines.query import optimizer
        from ipfs_datasets_py.processors.engines.query import executor
        from ipfs_datasets_py.processors.engines.query import formatter
        from ipfs_datasets_py.processors.engines.query import cache
        
        # All should be importable modules
        assert engine is not None
        assert parser is not None
        assert optimizer is not None
    
    def test_query_engine_facade_is_same_as_original(self):
        """Test that engines.query.QueryEngine is the same as original."""
        from ipfs_datasets_py.processors.engines.query import QueryEngine as EnginesQuery
        from ipfs_datasets_py.processors.query_engine import QueryEngine as OriginalQuery
        
        # Should be the exact same class
        assert EnginesQuery is OriginalQuery
    
    def test_query_engine_from_engine_submodule(self):
        """Test QueryEngine can also be imported from engine submodule."""
        from ipfs_datasets_py.processors.engines.query.engine import QueryEngine
        assert QueryEngine is not None


class TestEnginesRelationshipFacade:
    """Test engines/relationship/ facade imports and functionality."""
    
    def test_relationship_analyzer_import_from_engines(self):
        """Test RelationshipAnalyzer can be imported from engines.relationship."""
        from ipfs_datasets_py.processors.engines.relationship import RelationshipAnalyzer
        assert RelationshipAnalyzer is not None
        assert hasattr(RelationshipAnalyzer, '__name__')
    
    def test_relationship_submodule_imports(self):
        """Test all relationship submodules can be imported."""
        from ipfs_datasets_py.processors.engines.relationship import analyzer
        from ipfs_datasets_py.processors.engines.relationship import api
        from ipfs_datasets_py.processors.engines.relationship import corpus
        
        # All should be importable modules
        assert analyzer is not None
        assert api is not None
        assert corpus is not None
    
    def test_relationship_analyzer_facade_is_same_as_original(self):
        """Test that engines.relationship.RelationshipAnalyzer is the same as original."""
        from ipfs_datasets_py.processors.engines.relationship import RelationshipAnalyzer as EnginesRA
        from ipfs_datasets_py.processors.relationship_analyzer import RelationshipAnalyzer as OriginalRA
        
        # Should be the exact same class
        assert EnginesRA is OriginalRA
    
    def test_relationship_analyzer_from_analyzer_submodule(self):
        """Test RelationshipAnalyzer can also be imported from analyzer submodule."""
        from ipfs_datasets_py.processors.engines.relationship.analyzer import RelationshipAnalyzer
        assert RelationshipAnalyzer is not None


class TestEnginesPackageStructure:
    """Test overall engines package structure."""
    
    def test_engines_package_imports(self):
        """Test engines package can be imported."""
        import ipfs_datasets_py.processors.engines
        assert ipfs_datasets_py.processors.engines is not None
    
    def test_engines_has_subpackages(self):
        """Test engines has llm, query, relationship subpackages."""
        from ipfs_datasets_py.processors import engines
        
        # Should have the subpackages
        assert hasattr(engines, 'llm')
        assert hasattr(engines, 'query')
        assert hasattr(engines, 'relationship')
    
    def test_all_exports_defined(self):
        """Test that __all__ is properly defined in each package."""
        from ipfs_datasets_py.processors.engines import llm
        from ipfs_datasets_py.processors.engines import query
        from ipfs_datasets_py.processors.engines import relationship
        
        # Check __all__ is defined
        assert hasattr(llm, '__all__')
        assert hasattr(query, '__all__')
        assert hasattr(relationship, '__all__')
        
        # Check __all__ has expected items
        assert 'LLMOptimizer' in llm.__all__
        assert 'QueryEngine' in query.__all__
        assert 'RelationshipAnalyzer' in relationship.__all__


class TestBackwardCompatibility:
    """Test that old import paths still work."""
    
    def test_original_llm_optimizer_import_works(self):
        """Test original LLMOptimizer import still works."""
        from ipfs_datasets_py.processors.llm_optimizer import LLMOptimizer
        assert LLMOptimizer is not None
    
    def test_original_query_engine_import_works(self):
        """Test original QueryEngine import still works."""
        from ipfs_datasets_py.processors.query_engine import QueryEngine
        assert QueryEngine is not None
    
    def test_original_relationship_analyzer_import_works(self):
        """Test original RelationshipAnalyzer import still works."""
        from ipfs_datasets_py.processors.relationship_analyzer import RelationshipAnalyzer
        assert RelationshipAnalyzer is not None
    
    def test_imports_are_identical(self):
        """Test that old and new imports return identical objects."""
        from ipfs_datasets_py.processors.llm_optimizer import LLMOptimizer as OldLLM
        from ipfs_datasets_py.processors.engines.llm import LLMOptimizer as NewLLM
        assert OldLLM is NewLLM
        
        from ipfs_datasets_py.processors.query_engine import QueryEngine as OldQuery
        from ipfs_datasets_py.processors.engines.query import QueryEngine as NewQuery
        assert OldQuery is NewQuery
        
        from ipfs_datasets_py.processors.relationship_analyzer import RelationshipAnalyzer as OldRA
        from ipfs_datasets_py.processors.engines.relationship import RelationshipAnalyzer as NewRA
        assert OldRA is NewRA


class TestDeprecationWarnings:
    """Test deprecation warnings for old import paths."""
    
    def test_registry_deprecation_warning(self):
        """Test that importing from old registry location fires warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            
            # Import from old location
            from ipfs_datasets_py.processors.registry import ProcessorRegistry
            
            # Should have fired a deprecation warning
            deprecation_warnings = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
            assert len(deprecation_warnings) > 0
            
            # Check warning message mentions new location
            warning_msg = str(deprecation_warnings[0].message)
            assert 'processors.core.registry' in warning_msg or 'deprecated' in warning_msg.lower()
    
    def test_advanced_media_deprecation_warning(self):
        """Test that importing from old advanced_media_processing location fires warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            
            # Import from old location
            from ipfs_datasets_py.processors.advanced_media_processing import AdvancedMediaProcessor
            
            # Should have fired a deprecation warning
            deprecation_warnings = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
            assert len(deprecation_warnings) > 0
            
            # Check warning message mentions new location
            warning_msg = str(deprecation_warnings[0].message)
            assert 'specialized.media' in warning_msg or 'deprecated' in warning_msg.lower()
    
    def test_advanced_web_archiving_deprecation_warning(self):
        """Test that importing from old advanced_web_archiving location fires warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            
            # Import from old location
            from ipfs_datasets_py.processors.advanced_web_archiving import AdvancedWebArchiver
            
            # Should have fired a deprecation warning
            deprecation_warnings = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
            assert len(deprecation_warnings) > 0
            
            # Check warning message mentions new location  
            warning_msg = str(deprecation_warnings[0].message)
            assert 'specialized.web_archive' in warning_msg or 'deprecated' in warning_msg.lower()


class TestEnginesFunctionalityBasics:
    """Basic functionality tests for engines."""
    
    def test_llm_optimizer_has_expected_methods(self):
        """Test LLMOptimizer has expected methods."""
        from ipfs_datasets_py.processors.engines.llm import LLMOptimizer
        
        # Should have key methods (check class attributes)
        assert hasattr(LLMOptimizer, '__init__')
    
    def test_query_engine_has_expected_methods(self):
        """Test QueryEngine has expected methods."""
        from ipfs_datasets_py.processors.engines.query import QueryEngine
        
        # Should have key methods
        assert hasattr(QueryEngine, '__init__')
    
    def test_relationship_analyzer_has_expected_methods(self):
        """Test RelationshipAnalyzer has expected methods."""
        from ipfs_datasets_py.processors.engines.relationship import RelationshipAnalyzer
        
        # Should have key methods
        assert hasattr(RelationshipAnalyzer, '__init__')
        assert hasattr(RelationshipAnalyzer, 'analyze_entity_relationships')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
