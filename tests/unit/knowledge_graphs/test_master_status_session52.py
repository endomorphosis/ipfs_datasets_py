"""
Session 52: Cover ImportError except branches across 5 modules by reloading
each module with its optional dependency temporarily removed from sys.modules.

Targets:
- reasoning/types.py:24-26    (numpy ImportError except → np=None, _NpNdarray=None)
- lineage/core.py:18-20       (networkx ImportError except → NETWORKX_AVAILABLE=False, nx=None)
- neo4j_compat/driver.py:35-38 (router_deps ImportError except → HAVE_DEPS=False)
- reasoning/cross_document.py:31-32  (numpy ImportError except → np=None)
- reasoning/cross_document.py:64-66  (optimizer ImportError except → UnifiedGraphRAGQueryOptimizer=None)
- ipld.py:98                  (ipld_car import SUCCESS → HAVE_IPLD_CAR=True)

All reloads are isolated: we save/restore sys.modules so normal tests are unaffected.
"""

import sys
import importlib
import pytest
from unittest.mock import MagicMock

# Sentinel — distinct from None (which is a valid sys.modules value)
_MISSING = object()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_with_absent_dep(module_name: str, absent_deps: list[str]):
    """
    Reload *module_name* while each dep in *absent_deps* is blocked (set to
    None in sys.modules so ``import dep`` raises ImportError).  Returns the
    freshly-loaded module.  Always restores sys.modules and parent package
    attributes afterwards to avoid polluting test isolation.
    """
    saved: dict[str, object] = {}

    # Block each dependency
    for dep in absent_deps:
        saved[dep] = sys.modules.pop(dep, _MISSING)
        sys.modules[dep] = None  # type: ignore[assignment]

    # Remove cached module so Python re-executes it
    saved_mod = sys.modules.pop(module_name, _MISSING)

    # Also save the parent package's attribute for the leaf module name, because
    # Python sets pkg.leaf = <module> when it first imports a sub-module.  If we
    # don't restore this, the fresh (wrong) module leaks via `import pkg.leaf`.
    parent_name, _, leaf = module_name.rpartition(".")
    parent_pkg = sys.modules.get(parent_name)
    saved_pkg_attr = getattr(parent_pkg, leaf, _MISSING) if parent_pkg and leaf else _MISSING

    try:
        fresh = importlib.import_module(module_name)
    finally:
        # Restore dependencies
        for dep, old in saved.items():
            if old is _MISSING:
                sys.modules.pop(dep, None)
            else:
                sys.modules[dep] = old  # type: ignore[assignment]

        # Restore the original module in sys.modules
        if saved_mod is _MISSING:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = saved_mod  # type: ignore[assignment]

        # Restore the parent package attribute so `import pkg.leaf as m` sees
        # the original module, not the freshly-reloaded one.
        if parent_pkg is not None and leaf:
            if saved_pkg_attr is _MISSING:
                try:
                    delattr(parent_pkg, leaf)
                except AttributeError:
                    pass
            else:
                setattr(parent_pkg, leaf, saved_pkg_attr)

    return fresh


def _reload_with_mock_dep(module_name: str, mock_deps: dict[str, object]):
    """
    Reload *module_name* with each entry in *mock_deps* injected into
    sys.modules (so ``import dep`` succeeds with the mock value).  Returns the
    freshly-loaded module.  Always restores sys.modules and parent package
    attributes afterwards.
    """
    saved: dict[str, object] = {}

    for dep, mock_val in mock_deps.items():
        saved[dep] = sys.modules.pop(dep, _MISSING)
        sys.modules[dep] = mock_val  # type: ignore[assignment]

    saved_mod = sys.modules.pop(module_name, _MISSING)

    parent_name, _, leaf = module_name.rpartition(".")
    parent_pkg = sys.modules.get(parent_name)
    saved_pkg_attr = getattr(parent_pkg, leaf, _MISSING) if parent_pkg and leaf else _MISSING

    try:
        fresh = importlib.import_module(module_name)
    finally:
        for dep, old in saved.items():
            if old is _MISSING:
                sys.modules.pop(dep, None)
            else:
                sys.modules[dep] = old  # type: ignore[assignment]

        if saved_mod is _MISSING:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = saved_mod  # type: ignore[assignment]

        if parent_pkg is not None and leaf:
            if saved_pkg_attr is _MISSING:
                try:
                    delattr(parent_pkg, leaf)
                except AttributeError:
                    pass
            else:
                setattr(parent_pkg, leaf, saved_pkg_attr)

    return fresh

class TestReasoningTypesNumpyAbsent:
    """
    GIVEN numpy is not importable
    WHEN reasoning/types.py is loaded
    THEN the ImportError except block fires: np=None, _NpNdarray=None
    """

    def test_np_is_none_when_numpy_absent(self):
        """GIVEN numpy absent WHEN types loaded THEN np is None."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.reasoning.types",
            ["numpy"],
        )
        assert mod.np is None

    def test_np_ndarray_stub_is_none_when_numpy_absent(self):
        """GIVEN numpy absent WHEN types loaded THEN _NpNdarray is None."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.reasoning.types",
            ["numpy"],
        )
        assert mod._NpNdarray is None

    def test_enums_still_importable_when_numpy_absent(self):
        """Core enum classes remain importable regardless of numpy."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.reasoning.types",
            ["numpy"],
        )
        assert hasattr(mod, "InformationRelationType")
        assert hasattr(mod, "DocumentNode")


# ---------------------------------------------------------------------------
# lineage/core.py:18-20 — networkx ImportError except
# ---------------------------------------------------------------------------

class TestLineageCoreNetworkxAbsent:
    """
    GIVEN networkx is not importable
    WHEN lineage/core.py is loaded
    THEN NETWORKX_AVAILABLE=False and nx=None
    """

    def test_networkx_available_false_when_absent(self):
        """GIVEN networkx absent WHEN core loaded THEN NETWORKX_AVAILABLE=False."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.lineage.core",
            ["networkx"],
        )
        assert mod.NETWORKX_AVAILABLE is False

    def test_nx_is_none_when_networkx_absent(self):
        """GIVEN networkx absent WHEN core loaded THEN nx=None."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.lineage.core",
            ["networkx"],
        )
        assert mod.nx is None

    def test_lineage_tracker_still_present_when_networkx_absent(self):
        """LineageTracker class is defined regardless of networkx."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.lineage.core",
            ["networkx"],
        )
        assert hasattr(mod, "LineageTracker")


# ---------------------------------------------------------------------------
# neo4j_compat/driver.py:35-38 — router_deps ImportError except
# ---------------------------------------------------------------------------

class TestNeo4jCompatDriverDepsAbsent:
    """
    GIVEN router_deps or IPLDBackend are not importable
    WHEN neo4j_compat/driver.py is loaded
    THEN HAVE_DEPS=False and stub None values set
    """

    def test_have_deps_false_when_router_deps_absent(self):
        """GIVEN router_deps absent WHEN driver loaded THEN HAVE_DEPS=False."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver",
            ["ipfs_datasets_py.router_deps"],
        )
        assert mod.HAVE_DEPS is False

    def test_router_deps_stub_none_when_absent(self):
        """GIVEN router_deps absent WHEN driver loaded THEN RouterDeps=None."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver",
            ["ipfs_datasets_py.router_deps"],
        )
        assert mod.RouterDeps is None

    def test_ipld_backend_stub_none_when_absent(self):
        """GIVEN router_deps absent WHEN driver loaded THEN IPLDBackend=None."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver",
            ["ipfs_datasets_py.router_deps"],
        )
        assert mod.IPLDBackend is None

    def test_ipfs_driver_class_still_present(self):
        """IPFSDriver class is defined regardless of optional deps."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver",
            ["ipfs_datasets_py.router_deps"],
        )
        assert hasattr(mod, "IPFSDriver")


# ---------------------------------------------------------------------------
# reasoning/cross_document.py:31-32 — numpy ImportError except
# ---------------------------------------------------------------------------

class TestCrossDocumentNumpyAbsent:
    """
    GIVEN numpy is not importable
    WHEN cross_document.py is loaded
    THEN the numpy except block fires: np=None
    """

    def test_np_is_none_when_numpy_absent(self):
        """GIVEN numpy absent WHEN cross_document loaded THEN np=None."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.reasoning.cross_document",
            ["numpy"],
        )
        assert mod.np is None

    def test_cross_document_reasoner_still_present(self):
        """CrossDocumentReasoner is defined regardless of numpy."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.reasoning.cross_document",
            ["numpy"],
        )
        assert hasattr(mod, "CrossDocumentReasoner")


# ---------------------------------------------------------------------------
# reasoning/cross_document.py:64-66 — optimizer ImportError except
# ---------------------------------------------------------------------------

class TestCrossDocumentOptimizerAbsent:
    """
    GIVEN the graphrag query optimizer is not importable
    WHEN cross_document.py is loaded
    THEN UnifiedGraphRAGQueryOptimizer=None and _UNIFIED_OPT_IMPORT_ERROR is set
    """

    def test_optimizer_none_when_optimizer_absent(self):
        """GIVEN optimizer absent WHEN cross_document loaded THEN optimizer=None."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.reasoning.cross_document",
            ["ipfs_datasets_py.optimizers.graphrag.query_optimizer"],
        )
        assert mod.UnifiedGraphRAGQueryOptimizer is None

    def test_import_error_recorded_when_optimizer_absent(self):
        """GIVEN optimizer absent WHEN loaded THEN _UNIFIED_OPT_IMPORT_ERROR is an Exception."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.reasoning.cross_document",
            ["ipfs_datasets_py.optimizers.graphrag.query_optimizer"],
        )
        assert isinstance(mod._UNIFIED_OPT_IMPORT_ERROR, Exception)

    def test_cross_document_reasoner_still_instantiable(self):
        """CrossDocumentReasoner can still be instantiated when optimizer absent."""
        mod = _reload_with_absent_dep(
            "ipfs_datasets_py.knowledge_graphs.reasoning.cross_document",
            ["ipfs_datasets_py.optimizers.graphrag.query_optimizer"],
        )
        reasoner = mod.CrossDocumentReasoner()
        assert reasoner is not None


# ---------------------------------------------------------------------------
# ipld.py:98 — HAVE_IPLD_CAR=True when ipld_car import succeeds
# ---------------------------------------------------------------------------

class TestIpldCarAvailable:
    """
    GIVEN ipld_car is importable (mocked in sys.modules)
    WHEN ipld.py is loaded
    THEN HAVE_IPLD_CAR=True (line 98 is executed)
    """

    def test_have_ipld_car_true_when_mock_available(self):
        """GIVEN mock ipld_car in sys.modules WHEN ipld.py loaded THEN HAVE_IPLD_CAR=True."""
        mock_ipld_car = MagicMock()
        mock_ipld_car.__name__ = "ipld_car"
        fresh = _reload_with_mock_dep(
            "ipfs_datasets_py.knowledge_graphs.ipld",
            {"ipld_car": mock_ipld_car},
        )
        assert fresh.HAVE_IPLD_CAR is True

    def test_ipld_car_attribute_set_when_available(self):
        """GIVEN mock ipld_car WHEN ipld.py loaded THEN ipld_car attr is the mock."""
        mock_ipld_car = MagicMock()
        mock_ipld_car.__name__ = "ipld_car"
        fresh = _reload_with_mock_dep(
            "ipfs_datasets_py.knowledge_graphs.ipld",
            {"ipld_car": mock_ipld_car},
        )
        assert fresh.ipld_car is mock_ipld_car
