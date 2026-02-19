"""
Tests for Phase 8 Week 1-2: Package Imports

Tests clean package exports and public API for CEC modules.
Validates that all key components are importable with intuitive paths.
"""

import pytest
import time
import sys


class TestTopLevelImports:
    """
    GIVEN CEC package structure
    WHEN importing from top-level modules
    THEN all key components should be accessible
    """
    
    def test_import_cec_module(self):
        """
        GIVEN CEC package
        WHEN importing ipfs_datasets_py.logic.CEC
        THEN it should succeed without errors
        """
        import ipfs_datasets_py.logic.CEC
        assert ipfs_datasets_py.logic.CEC is not None
    
    def test_import_native_module(self):
        """
        GIVEN CEC.native package
        WHEN importing it
        THEN key classes should be available
        """
        from ipfs_datasets_py.logic.CEC import native
        assert hasattr(native, 'Sort')
        assert hasattr(native, 'Variable')
        assert hasattr(native, 'Formula')
        assert hasattr(native, 'TheoremProver')
    
    def test_import_optimization_module(self):
        """
        GIVEN CEC.optimization package
        WHEN importing it
        THEN cache and profiling tools should be available
        """
        from ipfs_datasets_py.logic.CEC import optimization
        assert hasattr(optimization, 'CacheManager')
        assert hasattr(optimization, 'FormulaProfiler')
    
    def test_import_provers_module(self):
        """
        GIVEN CEC.provers package
        WHEN importing it
        THEN prover interfaces should be available
        """
        from ipfs_datasets_py.logic.CEC import provers
        assert hasattr(provers, 'ProverManager')
        assert hasattr(provers, 'Z3Adapter')


class TestDirectImports:
    """
    GIVEN direct import paths
    WHEN importing specific classes
    THEN they should work without pulling in unnecessary dependencies
    """
    
    def test_direct_import_sort(self):
        """
        GIVEN Sort class
        WHEN importing directly
        THEN it should be accessible
        """
        from ipfs_datasets_py.logic.CEC.native import Sort
        sort = Sort("test")
        assert sort.name == "test"
    
    def test_direct_import_cache_manager(self):
        """
        GIVEN CacheManager class
        WHEN importing directly
        THEN it should be accessible
        """
        from ipfs_datasets_py.logic.CEC.optimization import CacheManager
        manager = CacheManager()
        assert manager is not None


class TestImportPerformance:
    """
    GIVEN package imports
    WHEN measuring import time
    THEN imports should be fast (< 1 second)
    """
    
    def test_native_import_speed(self):
        """
        GIVEN native module
        WHEN importing it
        THEN import should be fast
        """
        start = time.time()
        from ipfs_datasets_py.logic.CEC import native
        elapsed = time.time() - start
        assert elapsed < 1.0
    
    def test_optimization_import_speed(self):
        """
        GIVEN optimization module
        WHEN importing it
        THEN import should be fast
        """
        start = time.time()
        from ipfs_datasets_py.logic.CEC import optimization
        elapsed = time.time() - start
        assert elapsed < 1.0
    
    def test_selective_import_speed(self):
        """
        GIVEN selective imports
        WHEN importing specific classes
        THEN it should be faster than full module import
        """
        start = time.time()
        from ipfs_datasets_py.logic.CEC.native import Sort, Variable
        elapsed = time.time() - start
        assert elapsed < 0.5


class TestNamespaceOrganization:
    """
    GIVEN CEC package namespace
    WHEN exploring the API
    THEN it should be well-organized
    """
    
    def test_native_exports_logical_grouping(self):
        """
        GIVEN native module __all__
        WHEN checking exports
        THEN they should be logically grouped
        """
        from ipfs_datasets_py.logic.CEC import native
        assert 'DeonticOperator' in native.__all__
        assert 'Sort' in native.__all__
        assert 'Formula' in native.__all__
    
    def test_optimization_exports_complete(self):
        """
        GIVEN optimization module __all__
        WHEN checking exports
        THEN all cache and profiling components should be present
        """
        from ipfs_datasets_py.logic.CEC import optimization
        assert 'CacheManager' in optimization.__all__
        assert 'FormulaProfiler' in optimization.__all__
    
    def test_provers_exports_complete(self):
        """
        GIVEN provers module __all__
        WHEN checking exports
        THEN all prover components should be present
        """
        from ipfs_datasets_py.logic.CEC import provers
        assert 'ProverManager' in provers.__all__
        assert 'Z3Adapter' in provers.__all__
    
    def test_no_private_exports(self):
        """
        GIVEN module __all__ lists
        WHEN checking for private names
        THEN no names starting with _ should be exported
        """
        from ipfs_datasets_py.logic.CEC import native, optimization, provers
        for module in [native, optimization, provers]:
            for name in module.__all__:
                assert not name.startswith('_')


class TestDocumentation:
    """
    GIVEN package modules
    WHEN accessing documentation
    THEN it should be comprehensive and helpful
    """
    
    def test_native_module_docstring(self):
        """
        GIVEN native module
        WHEN accessing its docstring
        THEN it should describe the module
        """
        from ipfs_datasets_py.logic.CEC import native
        assert native.__doc__ is not None
        assert len(native.__doc__) > 50
    
    def test_optimization_module_docstring(self):
        """
        GIVEN optimization module
        WHEN accessing its docstring
        THEN it should describe optimization features
        """
        from ipfs_datasets_py.logic.CEC import optimization
        assert optimization.__doc__ is not None
    
    def test_provers_module_docstring(self):
        """
        GIVEN provers module
        WHEN accessing its docstring
        THEN it should describe prover interfaces
        """
        from ipfs_datasets_py.logic.CEC import provers
        assert provers.__doc__ is not None
    
    def test_class_docstrings_present(self):
        """
        GIVEN key classes
        WHEN accessing their docstrings
        THEN they should have documentation
        """
        from ipfs_datasets_py.logic.CEC.native import Sort, Variable
        from ipfs_datasets_py.logic.CEC.optimization import CacheManager
        assert Sort.__doc__ is not None
        assert Variable.__doc__ is not None
        assert CacheManager.__doc__ is not None


class TestImportCompatibility:
    """
    GIVEN different import styles
    WHEN using various import patterns
    THEN all should work correctly
    """
    
    def test_from_import_pattern(self):
        """
        GIVEN from...import pattern
        WHEN importing classes
        THEN it should work
        """
        from ipfs_datasets_py.logic.CEC.native import Sort, Variable
        sort = Sort("test")
        var = Variable("x", sort)
        assert sort.name == "test"
        assert var.name == "x"
    
    def test_import_as_pattern(self):
        """
        GIVEN import...as pattern
        WHEN importing modules
        THEN it should work with aliases
        """
        from ipfs_datasets_py.logic.CEC import native as cec_native
        from ipfs_datasets_py.logic.CEC import optimization as cec_opt
        sort = cec_native.Sort("test")
        cache = cec_opt.CacheManager()
        assert sort.name == "test"
        assert cache is not None
    
    def test_full_path_import_pattern(self):
        """
        GIVEN full path imports
        WHEN using complete module paths
        THEN it should work
        """
        import ipfs_datasets_py.logic.CEC.native
        import ipfs_datasets_py.logic.CEC.optimization
        sort = ipfs_datasets_py.logic.CEC.native.Sort("test")
        cache = ipfs_datasets_py.logic.CEC.optimization.CacheManager()
        assert sort.name == "test"
        assert cache is not None
