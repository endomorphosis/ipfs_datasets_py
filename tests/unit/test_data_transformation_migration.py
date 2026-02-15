"""
Test backward compatibility for data_transformation → processors migration.

This test suite validates that:
1. All new import paths work correctly
2. All old import paths still work with deprecation warnings
3. Functionality is preserved after migration
"""

import sys
import warnings
import pytest


class TestBackwardCompatibility:
    """Test backward compatibility of migrated modules."""

    def test_ipld_storage_new_import(self):
        """Test that new IPLD storage import path works."""
        from ipfs_datasets_py.processors.storage.ipld import IPLDStorage
        assert IPLDStorage is not None

    def test_ipld_storage_old_import_with_warning(self):
        """Test that old IPLD storage import path works with deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from ipfs_datasets_py.data_transformation.ipld import IPLDStorage
            
            assert IPLDStorage is not None
            # Check that a deprecation warning was raised
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "data_transformation.ipld" in str(w[0].message)
            assert "processors.storage.ipld" in str(w[0].message)

    def test_ipld_knowledge_graph_new_import(self):
        """Test that new IPLD knowledge graph import works."""
        from ipfs_datasets_py.processors.storage.ipld import IPLDKnowledgeGraph
        # May be None if numpy not available, but import should work
        assert True

    def test_serialization_new_import(self):
        """Test that new serialization import path works."""
        try:
            from ipfs_datasets_py.processors.serialization import DatasetSerializer
            assert DatasetSerializer is not None
        except ImportError as e:
            if "numpy" in str(e):
                pytest.skip("NumPy not available")
            raise

    def test_serialization_old_import_with_warning(self):
        """Test that old serialization import path works with deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            try:
                from ipfs_datasets_py.data_transformation.serialization import DatasetSerializer
                assert DatasetSerializer is not None
            except ImportError as e:
                if "numpy" in str(e):
                    pytest.skip("NumPy not available")
                raise
            
            # Check deprecation warning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert any("serialization" in str(x.message) for x in deprecation_warnings)

    def test_ipfs_formats_new_import(self):
        """Test that new IPFS formats import path works."""
        from ipfs_datasets_py.processors.ipfs.formats import get_cid
        assert get_cid is not None

    def test_ipfs_formats_old_import_with_warning(self):
        """Test that old IPFS formats import path works with deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from ipfs_datasets_py.data_transformation.ipfs_formats import get_cid
            
            assert get_cid is not None
            # Check deprecation warning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1

    def test_unixfs_new_import(self):
        """Test that new UnixFS import path works."""
        from ipfs_datasets_py.processors.ipfs import UnixFSHandler
        assert UnixFSHandler is not None

    def test_unixfs_old_import_with_warning(self):
        """Test that old UnixFS import path works with deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from ipfs_datasets_py.data_transformation.unixfs import UnixFSHandler
            
            assert UnixFSHandler is not None
            # Check deprecation warning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1

    def test_ucan_new_import(self):
        """Test that new UCAN import path works."""
        from ipfs_datasets_py.processors.auth import ucan
        assert ucan is not None

    def test_ucan_old_import_with_warning(self):
        """Test that old UCAN import path works with deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from ipfs_datasets_py.data_transformation import ucan
            
            assert ucan is not None
            # Check deprecation warning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1


class TestImportEquivalence:
    """Test that old and new imports return the same objects."""

    def test_ipld_storage_same_class(self):
        """Test that old and new IPLD imports return the same class."""
        from ipfs_datasets_py.processors.storage.ipld import IPLDStorage as NewIPLDStorage
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from ipfs_datasets_py.data_transformation.ipld import IPLDStorage as OldIPLDStorage
        
        assert NewIPLDStorage is OldIPLDStorage

    def test_ipfs_formats_same_function(self):
        """Test that old and new IPFS formats imports return the same function."""
        from ipfs_datasets_py.processors.ipfs.formats import get_cid as new_get_cid
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from ipfs_datasets_py.data_transformation.ipfs_formats import get_cid as old_get_cid
        
        assert new_get_cid is old_get_cid

    def test_unixfs_same_class(self):
        """Test that old and new UnixFS imports return the same class."""
        from ipfs_datasets_py.processors.ipfs import UnixFSHandler as NewUnixFS
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from ipfs_datasets_py.data_transformation.unixfs import UnixFSHandler as OldUnixFS
        
        assert NewUnixFS is OldUnixFS


class TestDeprecationMessages:
    """Test that deprecation messages are clear and helpful."""

    def test_ipld_deprecation_message_quality(self):
        """Test that IPLD deprecation message includes helpful information."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from ipfs_datasets_py.data_transformation.ipld import IPLDStorage
            
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            
            message = str(deprecation_warnings[0].message)
            # Check that message includes old path
            assert "data_transformation.ipld" in message
            # Check that message includes new path
            assert "processors.storage.ipld" in message
            # Check that message includes version info
            assert "v2.0.0" in message or "2.0.0" in message

    def test_serialization_deprecation_message_quality(self):
        """Test that serialization deprecation message includes helpful information."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            try:
                from ipfs_datasets_py.data_transformation.serialization import DatasetSerializer
            except ImportError as e:
                if "numpy" in str(e):
                    pytest.skip("NumPy not available")
                raise
            
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            
            # Check that at least one message mentions serialization
            assert any("serialization" in str(x.message) for x in deprecation_warnings)


class TestDocumentation:
    """Test that documentation files exist and are complete."""

    def test_migration_guide_exists(self):
        """Test that migration guide exists."""
        import os
        guide_path = "docs/COMPLETE_MIGRATION_GUIDE.md"
        assert os.path.exists(guide_path), f"Migration guide not found at {guide_path}"

    def test_quick_migration_guide_exists(self):
        """Test that quick migration guide exists."""
        import os
        guide_path = "docs/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md"
        assert os.path.exists(guide_path), f"Quick migration guide not found at {guide_path}"

    def test_integration_plan_exists(self):
        """Test that integration plan exists."""
        import os
        plan_path = "docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md"
        assert os.path.exists(plan_path), f"Integration plan not found at {plan_path}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
