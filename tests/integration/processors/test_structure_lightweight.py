"""Lightweight tests for engines facade structure.

These tests validate the facade pattern implementation without
requiring full dependencies, focusing on structure and import paths.
"""

import pytest
import sys
from pathlib import Path


class TestEnginesStructure:
    """Test basic engines package structure."""
    
    def test_engines_package_exists(self):
        """Test engines package can be imported."""
        import ipfs_datasets_py.processors.engines
        assert ipfs_datasets_py.processors.engines is not None
    
    def test_engines_subpackages_exist(self):
        """Test that llm, query, relationship subpackages exist."""
        # Test they can be imported
        import ipfs_datasets_py.processors.engines.llm
        import ipfs_datasets_py.processors.engines.query
        import ipfs_datasets_py.processors.engines.relationship
        
        assert ipfs_datasets_py.processors.engines.llm is not None
        assert ipfs_datasets_py.processors.engines.query is not None
        assert ipfs_datasets_py.processors.engines.relationship is not None
    
    def test_engines_has_subpackages_as_attributes(self):
        """Test engines has llm, query, relationship as attributes."""
        from ipfs_datasets_py.processors import engines
        
        # Should have the subpackages as attributes
        assert hasattr(engines, 'llm')
        assert hasattr(engines, 'query')
        assert hasattr(engines, 'relationship')
    
    def test_llm_submodules_exist(self):
        """Test all LLM submodules are files."""
        llm_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'engines' / 'llm'
        
        expected_files = [
            '__init__.py',
            'optimizer.py',
            'chunker.py',
            'tokenizer.py',
            'embeddings.py',
            'context.py',
            'summarizer.py',
            'multimodal.py',
        ]
        
        for filename in expected_files:
            assert (llm_path / filename).exists(), f"Missing {filename}"
    
    def test_query_submodules_exist(self):
        """Test all query submodules are files."""
        query_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'engines' / 'query'
        
        expected_files = [
            '__init__.py',
            'engine.py',
            'parser.py',
            'optimizer.py',
            'executor.py',
            'formatter.py',
            'cache.py',
        ]
        
        for filename in expected_files:
            assert (query_path / filename).exists(), f"Missing {filename}"
    
    def test_relationship_submodules_exist(self):
        """Test all relationship submodules are files."""
        rel_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'engines' / 'relationship'
        
        expected_files = [
            '__init__.py',
            'analyzer.py',
            'api.py',
            'corpus.py',
        ]
        
        for filename in expected_files:
            assert (rel_path / filename).exists(), f"Missing {filename}"
    
    def test_all_exports_defined_in_packages(self):
        """Test that __all__ is defined in each subpackage."""
        import ipfs_datasets_py.processors.engines.llm as llm
        import ipfs_datasets_py.processors.engines.query as query
        import ipfs_datasets_py.processors.engines.relationship as relationship
        
        # Check __all__ is defined
        assert hasattr(llm, '__all__')
        assert hasattr(query, '__all__')
        assert hasattr(relationship, '__all__')
        
        # Check they're not empty
        assert len(llm.__all__) > 0
        assert len(query.__all__) > 0
        assert len(relationship.__all__) > 0


class TestDeprecationShims:
    """Test deprecation shims for moved files."""
    
    def test_registry_shim_exists(self):
        """Test registry.py exists as a shim."""
        registry_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'registry.py'
        assert registry_path.exists()
        
        # Check it has deprecation warning
        content = registry_path.read_text()
        assert 'deprecated' in content.lower()
        assert 'core.registry' in content or 'core/registry' in content
    
    def test_advanced_media_shim_exists(self):
        """Test advanced_media_processing.py exists as a shim."""
        media_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'advanced_media_processing.py'
        assert media_path.exists()
        
        # Check it has deprecation warning
        content = media_path.read_text()
        assert 'deprecated' in content.lower()
        assert 'specialized.media' in content or 'specialized/media' in content
    
    def test_advanced_web_archiving_shim_exists(self):
        """Test advanced_web_archiving.py exists as a shim."""
        archive_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'advanced_web_archiving.py'
        assert archive_path.exists()
        
        # Check it has deprecation warning
        content = archive_path.read_text()
        assert 'deprecated' in content.lower()
        assert 'specialized.web_archive' in content or 'specialized/web_archive' in content


class TestSpecializedPackages:
    """Test specialized packages structure."""
    
    def test_specialized_media_exists(self):
        """Test specialized/media/ package exists."""
        media_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'specialized' / 'media'
        assert media_path.exists()
        assert (media_path / '__init__.py').exists()
        assert (media_path / 'advanced_processing.py').exists()
    
    def test_specialized_web_archive_exists(self):
        """Test specialized/web_archive/ package exists."""
        archive_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'specialized' / 'web_archive'
        assert archive_path.exists()
        assert (archive_path / '__init__.py').exists()
        assert (archive_path / 'advanced_archiving.py').exists()


class TestCoreRegistry:
    """Test core registry consolidation."""
    
    def test_core_registry_exists(self):
        """Test core/registry.py exists."""
        registry_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'core' / 'registry.py'
        assert registry_path.exists()
    
    def test_core_registry_has_classes(self):
        """Test core registry has expected content."""
        registry_path = Path(__file__).parent.parent.parent.parent / 'ipfs_datasets_py' / 'processors' / 'core' / 'registry.py'
        content = registry_path.read_text()
        
        # Should have the main classes
        assert 'class ProcessorRegistry' in content
        assert 'class ProcessorEntry' in content
        assert 'def get_global_registry' in content


class TestDocumentation:
    """Test that documentation exists."""
    
    def test_comprehensive_plan_exists(self):
        """Test comprehensive plan document exists."""
        doc_path = Path(__file__).parent.parent.parent.parent / 'docs' / 'PROCESSORS_COMPREHENSIVE_PLAN_2026.md'
        assert doc_path.exists()
    
    def test_quick_reference_exists(self):
        """Test quick reference document exists."""
        doc_path = Path(__file__).parent.parent.parent.parent / 'docs' / 'PROCESSORS_PLAN_QUICK_REFERENCE.md'
        assert doc_path.exists()
    
    def test_visual_summary_exists(self):
        """Test visual summary document exists."""
        doc_path = Path(__file__).parent.parent.parent.parent / 'docs' / 'PROCESSORS_VISUAL_SUMMARY.md'
        assert doc_path.exists()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
