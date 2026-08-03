"""PATLAW-002: public processor import surface remains supported.

Pairs with ``docs/architecture/PATENT_LEGAL_PROCESSOR_PROTOCOL_ADR.md``.

The ADR selects ``processors.core.protocol`` as the *canonical runtime* while
preserving package-level and legacy public imports. These tests freeze that
compatibility surface so protocol unification does not delete supported
symbols used by adapters, CLI, MCP, and external callers.
"""

from __future__ import annotations

import importlib
from typing import Any, Iterable

import pytest


# Package-level symbols re-exported today from ipfs_datasets_py.processors
# for the unified architecture (see processors/__init__.py). These must remain
# importable after protocol unification; semantic deprecation is allowed only
# via adapters/docs, not by removing the names.
PACKAGE_ARCHITECTURE_EXPORTS = (
    "ProcessorProtocol",
    "ProcessingResult",
    "ProcessingMetadata",
    "ProcessingStatus",
    "InputType",
    "ProcessorRegistry",
    "UniversalProcessor",
    "ProcessorConfig",
    "InputDetector",
    "VectorStore",
    "get_global_registry",
    "detect_input_type",
    "classify_input",
    "UnifiedKnowledgeGraph",
    "UnifiedEntity",
    "UnifiedRelationship",
)

# Canonical runtime symbols (core package).
CORE_CANONICAL_EXPORTS = (
    "ProcessorProtocol",
    "ProcessingContext",
    "ProcessingResult",
    "InputType",
    "is_processor",
    "ProcessorRegistry",
    "UniversalProcessor",
    "get_global_registry",
    "Processor",
)

# Legacy module remains a supported import path for existing adapters.
LEGACY_MODULE_EXPORTS = (
    "ProcessorProtocol",
    "ProcessingResult",
    "ProcessingMetadata",
    "ProcessingStatus",
    "InputType",
    "KnowledgeGraph",
    "Entity",
    "Relationship",
    "VectorStore",
)


def _import_names(module_name: str, names: Iterable[str]) -> dict[str, Any]:
    module = importlib.import_module(module_name)
    found: dict[str, Any] = {}
    missing = []
    for name in names:
        if hasattr(module, name):
            found[name] = getattr(module, name)
        else:
            missing.append(name)
    if missing:
        raise AssertionError(
            f"{module_name} missing supported public names: {missing}"
        )
    return found


class TestPackagePublicSurfacePreserved:
    """Root package exports stay importable (no hard deletion)."""

    def test_architecture_exports_importable(self):
        exported = _import_names("ipfs_datasets_py.processors", PACKAGE_ARCHITECTURE_EXPORTS)
        assert exported["ProcessorProtocol"] is not None
        assert exported["ProcessingResult"] is not None
        assert exported["ProcessorRegistry"] is not None
        assert exported["UniversalProcessor"] is not None

    def test_package_processor_protocol_is_legacy_surface_for_compatibility(self):
        """
        Today the package default ProcessorProtocol is the legacy can_process
        API. That import path is preserved; new code should prefer core.
        """
        import ipfs_datasets_py.processors as processors_pkg
        import ipfs_datasets_py.processors.protocol as legacy
        import ipfs_datasets_py.processors.core.protocol as core

        assert processors_pkg.ProcessorProtocol is legacy.ProcessorProtocol
        assert processors_pkg.ProcessorProtocol is not core.ProcessorProtocol
        assert hasattr(processors_pkg.ProcessorProtocol, "can_process")
        assert not hasattr(processors_pkg.ProcessorProtocol, "can_handle")

    def test_package_registry_is_core_registry(self):
        """Registry re-export already points at the core registry module."""
        import ipfs_datasets_py.processors as processors_pkg
        from ipfs_datasets_py.processors.core.registry import (
            ProcessorRegistry as CoreRegistry,
        )

        assert processors_pkg.ProcessorRegistry is CoreRegistry

    def test_package_all_lists_key_architecture_names(self):
        import ipfs_datasets_py.processors as processors_pkg

        public_all = set(processors_pkg.__all__)
        for name in (
            "ProcessorProtocol",
            "ProcessingResult",
            "UniversalProcessor",
            "ProcessorRegistry",
            "InputType",
            "InputDetector",
        ):
            assert name in public_all, f"{name} missing from processors.__all__"


class TestCoreCanonicalSurface:
    """Canonical runtime remains available under processors.core."""

    def test_core_exports_importable(self):
        exported = _import_names(
            "ipfs_datasets_py.processors.core", CORE_CANONICAL_EXPORTS
        )
        assert hasattr(exported["ProcessorProtocol"], "can_handle")
        assert not hasattr(exported["ProcessorProtocol"], "can_process")
        assert exported["ProcessingContext"] is not None
        assert callable(exported["is_processor"])

    def test_core_protocol_module_path(self):
        import ipfs_datasets_py.processors.core.protocol as core_protocol

        assert core_protocol.__name__ == "ipfs_datasets_py.processors.core.protocol"

    def test_core_and_package_results_are_distinct_types(self):
        import ipfs_datasets_py.processors as processors_pkg
        import ipfs_datasets_py.processors.core as core_pkg

        assert processors_pkg.ProcessingResult is not core_pkg.ProcessingResult
        assert processors_pkg.InputType is not core_pkg.InputType


class TestLegacyModuleSurfacePreserved:
    """Legacy protocol module stays a supported public import."""

    def test_legacy_exports_importable(self):
        exported = _import_names(
            "ipfs_datasets_py.processors.protocol", LEGACY_MODULE_EXPORTS
        )
        assert hasattr(exported["ProcessorProtocol"], "can_process")
        assert callable(exported["ProcessorProtocol"].can_process)

    def test_legacy_adapters_can_still_import_protocol_symbols(self):
        """Adapters historically bind the legacy protocol module."""
        from ipfs_datasets_py.processors.protocol import (
            InputType,
            KnowledgeGraph,
            ProcessingMetadata,
            ProcessingResult,
            ProcessingStatus,
            ProcessorProtocol,
            VectorStore,
        )

        assert ProcessorProtocol is not None
        assert ProcessingResult is not None
        assert KnowledgeGraph is not None
        assert VectorStore is not None
        assert ProcessingMetadata is not None
        assert ProcessingStatus is not None
        assert InputType.FILE.value == "file"

    def test_pdf_adapter_module_still_imports_legacy_protocol(self):
        """Do not break adapter import paths as part of protocol decision."""
        mod = importlib.import_module("ipfs_datasets_py.processors.adapters.pdf_adapter")
        assert hasattr(mod, "PDFProcessorAdapter")
        assert hasattr(mod, "ProcessorProtocol")
        # Adapter is wired to the legacy can_process surface today.
        assert hasattr(mod.PDFProcessorAdapter, "can_process")
        assert not hasattr(mod.PDFProcessorAdapter, "can_handle")


class TestDualImportPathsDoNotCollapse:
    """Unification must not silently alias legacy and core protocols together."""

    def test_two_processor_protocol_objects_remain(self):
        from ipfs_datasets_py.processors.core.protocol import (
            ProcessorProtocol as CorePP,
        )
        from ipfs_datasets_py.processors.protocol import (
            ProcessorProtocol as LegacyPP,
        )

        assert CorePP is not LegacyPP
        assert set(dir(CorePP)) != set(dir(LegacyPP))

    def test_canonical_import_recommended_path(self):
        """Document the preferred import for new patent-legal code."""
        from ipfs_datasets_py.processors.core import (
            ProcessingContext,
            ProcessorProtocol,
            ProcessingResult,
            is_processor,
        )

        assert ProcessorProtocol is not None
        assert ProcessingContext is not None
        assert ProcessingResult is not None
        assert callable(is_processor)


class TestRegistryDeprecationShimStillImportable:
    """processors.registry deprecation shim remains importable for callers."""

    def test_deprecated_registry_module_reexports_core(self):
        with pytest.warns(DeprecationWarning, match="processors.registry is deprecated"):
            mod = importlib.import_module("ipfs_datasets_py.processors.registry")
        from ipfs_datasets_py.processors.core.registry import (
            ProcessorRegistry as CoreRegistry,
        )

        assert mod.ProcessorRegistry is CoreRegistry
        assert callable(mod.get_global_registry)
