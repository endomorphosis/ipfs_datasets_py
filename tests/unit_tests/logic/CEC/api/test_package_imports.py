"""
Tests for Phase 8 Week 1-2: Package Imports

Tests clean package exports and public API for CEC modules.
"""

import pytest


class TestTopLevelImports:
    """Test top-level imports work correctly"""
    
    def test_import_cec_module(self):
        """Test importing CEC module"""
        import ipfs_datasets_py.logic.CEC
        assert ipfs_datasets_py.logic.CEC is not None
    
    def test_import_native_module(self):
        """Test importing native module"""
        from ipfs_datasets_py.logic.CEC import native
        assert hasattr(native, 'Sort')
        assert hasattr(native, 'Variable')
    
    def test_import_optimization_module(self):
        """Test importing optimization module"""
        from ipfs_datasets_py.logic.CEC import optimization
        assert hasattr(optimization, 'CacheManager')
    
    def test_import_provers_module(self):
        """Test importing provers module"""
        from ipfs_datasets_py.logic.CEC import provers
        assert hasattr(provers, 'ProverManager')


class TestDirectImports:
    """Test direct imports of specific classes"""
    
    def test_direct_import_sort(self):
        """Test direct Sort import"""
        from ipfs_datasets_py.logic.CEC.native import Sort
        sort = Sort("test")
        assert sort.name == "test"
    
    def test_direct_import_cache_manager(self):
        """Test direct CacheManager import"""
        from ipfs_datasets_py.logic.CEC.optimization import CacheManager
        manager = CacheManager()
        assert manager is not None
