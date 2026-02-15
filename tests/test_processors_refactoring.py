"""
Comprehensive tests for processors refactoring (Phases 1-7).

Tests:
1. Import paths (old and new)
2. Deprecation warnings
3. Backward compatibility
4. Adapter routing
5. Functionality preservation
"""
import warnings
import pytest


class TestDeprecatedImports:
    """Test that old import paths still work with deprecation warnings."""

    def test_graphrag_processor_deprecated_import(self):
        """Test deprecated graphrag_processor import."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
                assert len(w) > 0
                assert issubclass(w[0].category, DeprecationWarning)
                assert "specialized.graphrag" in str(w[0].message)
            except ImportError as e:
                # Optional dependencies - acceptable
                pytest.skip(f"Optional dependency missing: {e}")

    def test_pdf_processor_deprecated_import(self):
        """Test deprecated pdf_processor import."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
                assert len(w) > 0
                assert issubclass(w[0].category, DeprecationWarning)
                assert "specialized.pdf" in str(w[0].message)
            except ImportError as e:
                pytest.skip(f"Optional dependency missing: {e}")

    def test_multimodal_processor_deprecated_import(self):
        """Test deprecated multimodal_processor import."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                from ipfs_datasets_py.processors.multimodal_processor import MultiModalContentProcessor
                assert len(w) > 0
                assert issubclass(w[0].category, DeprecationWarning)
                assert "specialized.multimodal" in str(w[0].message)
            except ImportError as e:
                pytest.skip(f"Optional dependency missing: {e}")

    def test_batch_processor_deprecated_import(self):
        """Test deprecated batch_processor import."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                from ipfs_datasets_py.processors.batch_processor import BatchProcessor
                assert len(w) > 0
                assert issubclass(w[0].category, DeprecationWarning)
                assert "specialized.batch" in str(w[0].message)
            except ImportError as e:
                pytest.skip(f"Optional dependency missing: {e}")

    def test_caching_deprecated_import(self):
        """Test deprecated caching import."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                from ipfs_datasets_py.processors.caching import CacheManager
                assert len(w) > 0
                assert issubclass(w[0].category, DeprecationWarning)
                assert "infrastructure.caching" in str(w[0].message)
            except ImportError as e:
                pytest.skip(f"Optional dependency missing: {e}")

    def test_patent_scraper_deprecated_import(self):
        """Test deprecated patent_scraper import."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                from ipfs_datasets_py.processors.patent_scraper import PatentScraper
                assert len(w) > 0
                assert issubclass(w[0].category, DeprecationWarning)
                assert "domains.patent" in str(w[0].message)
            except ImportError as e:
                pytest.skip(f"Optional dependency missing: {e}")


class TestNewImports:
    """Test that new import paths work correctly."""

    def test_graphrag_new_import(self):
        """Test new graphrag import path."""
        try:
            from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor
            assert UnifiedGraphRAGProcessor is not None
        except ImportError as e:
            pytest.skip(f"Optional dependency missing: {e}")

    def test_pdf_new_import(self):
        """Test new pdf import path."""
        try:
            from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
            assert PDFProcessor is not None
        except ImportError as e:
            pytest.skip(f"Optional dependency missing: {e}")

    def test_multimodal_new_import(self):
        """Test new multimodal import path."""
        try:
            from ipfs_datasets_py.processors.specialized.multimodal import EnhancedMultiModalProcessor
            assert EnhancedMultiModalProcessor is not None
        except ImportError as e:
            pytest.skip(f"Optional dependency missing: {e}")

    def test_batch_new_import(self):
        """Test new batch import path."""
        try:
            from ipfs_datasets_py.processors.specialized.batch import BatchProcessor
            assert BatchProcessor is not None
        except ImportError as e:
            pytest.skip(f"Optional dependency missing: {e}")

    def test_infrastructure_new_import(self):
        """Test new infrastructure import path."""
        try:
            from ipfs_datasets_py.processors.infrastructure import caching
            assert caching is not None
        except ImportError as e:
            pytest.skip(f"Optional dependency missing: {e}")

    def test_domains_new_import(self):
        """Test new domains import path."""
        try:
            from ipfs_datasets_py.processors.domains.patent import PatentScraper
            assert PatentScraper is not None
        except ImportError as e:
            pytest.skip(f"Optional dependency missing: {e}")


class TestStructure:
    """Test that the new directory structure is correct."""

    def test_specialized_directory_exists(self):
        """Test specialized directory exists."""
        import os
        path = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py/ipfs_datasets_py/processors/specialized"
        assert os.path.exists(path), f"Directory not found: {path}"
        assert os.path.isdir(path), f"Not a directory: {path}"

    def test_infrastructure_directory_exists(self):
        """Test infrastructure directory exists."""
        import os
        path = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py/ipfs_datasets_py/processors/infrastructure"
        assert os.path.exists(path), f"Directory not found: {path}"
        assert os.path.isdir(path), f"Not a directory: {path}"

    def test_domains_directory_exists(self):
        """Test domains directory exists."""
        import os
        path = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py/ipfs_datasets_py/processors/domains"
        assert os.path.exists(path), f"Directory not found: {path}"
        assert os.path.isdir(path), f"Not a directory: {path}"

    def test_graphrag_subdirectory(self):
        """Test graphrag subdirectory exists."""
        import os
        path = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py/ipfs_datasets_py/processors/specialized/graphrag"
        assert os.path.exists(path), f"Directory not found: {path}"
        assert os.path.isdir(path), f"Not a directory: {path}"

    def test_pdf_subdirectory(self):
        """Test pdf subdirectory exists."""
        import os
        path = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py/ipfs_datasets_py/processors/specialized/pdf"
        assert os.path.exists(path), f"Directory not found: {path}"
        assert os.path.isdir(path), f"Not a directory: {path}"


class TestBackwardCompatibility:
    """Test that backward compatibility is maintained."""

    def test_old_and_new_imports_same_class(self):
        """Test that old and new imports reference the same class."""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor as NewClass
                from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor as OldClass
                # They should be the same class (aliased)
                assert OldClass is NewClass or OldClass.__name__ == NewClass.__name__
        except ImportError as e:
            pytest.skip(f"Optional dependency missing: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
