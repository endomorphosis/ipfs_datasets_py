"""
Shared state management for MCP vector tools.

This module maintains state for vector indexes via ServerContext
or global fallback for backward compatibility.

Also binds the process-local DuckDB vector catalog so MCP create/list/delete
entrypoints share mapping/count/query parity with adapter producers:

* DQK-062 — shadow mode (legacy authority)
* DQK-063 — dual mode promotes collection/generation/tombstone/compaction
  metadata to DuckDB while vector bytes remain in the selected engine
* DQK-064 — after DuckDB promotion, pickle and process-local mappings are
  one-time import only; MCP restart rehydrates from DuckDB + vector segments
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Global manager instance (deprecated - use ServerContext instead)
_global_manager = None
# Durable catalog path used to rebind after process-local manager reset.
_mcp_catalog_path: Optional[str] = None



def _get_global_manager():
    """Get or create the global index manager.

    Note:
        Deprecated. New code should use ServerContext.get_vector_store() instead.
    """
    global _global_manager
    if _global_manager is None:
        from ipfs_datasets_py.ml.embeddings.ipfs_knn_index import IPFSKnnIndexManager

        _global_manager = IPFSKnnIndexManager()
        # Ensure a shared dual-mode authority catalog for MCP producers (DQK-063/064).
        try:
            from ipfs_datasets_py.vector_stores.management_engine import (
                get_vector_authority_catalog,
                configure_vector_authority_catalog,
            )
            if get_vector_authority_catalog() is None:
                configure_vector_authority_catalog(
                    _mcp_catalog_path, enabled=True
                )
            else:
                # Rehydrate mappings after process-local manager recreation.
                catalog = get_vector_authority_catalog()
                if catalog is not None and catalog.path != ":memory:":
                    catalog.rehydrate_process_maps_from_store()
        except Exception:
            try:
                from ipfs_datasets_py.vector_stores.management_engine import (
                    get_vector_shadow_catalog,
                    configure_vector_shadow_catalog,
                )
                if get_vector_shadow_catalog() is None:
                    configure_vector_shadow_catalog(
                        _mcp_catalog_path, enabled=True
                    )
            except Exception:
                pass
    return _global_manager


def _reset_global_manager():
    """Reset the global manager (for testing purposes)."""
    global _global_manager
    _global_manager = None
    try:
        from ipfs_datasets_py.vector_stores.management_engine import (
            reset_vector_authority_catalog,
        )
        reset_vector_authority_catalog()
    except Exception:
        try:
            from ipfs_datasets_py.vector_stores.management_engine import (
                reset_vector_shadow_catalog,
            )
            reset_vector_shadow_catalog()
        except Exception:
            pass


def configure_mcp_vector_shadow_catalog(
    catalog_path: Union[str, Path, None] = None,
    *,
    enabled: bool = True,
    dual_mode: bool = True,
    allow_legacy_io: Optional[bool] = None,
) -> Any:
    """Configure the process-local DuckDB catalog for MCP tools.

    When ``dual_mode`` is true (default, DQK-063), the catalog starts in dual
    authority mode so DuckDB owns lifecycle metadata. After promotion to
    db-primary (DQK-064), legacy pickle/JSON I/O is disabled unless
    *allow_legacy_io* is explicitly True.
    """

    global _mcp_catalog_path
    if catalog_path is not None and catalog_path != ":memory:":
        _mcp_catalog_path = str(catalog_path)

    if dual_mode:
        from ipfs_datasets_py.vector_stores.management_engine import (
            configure_vector_authority_catalog,
        )
        return configure_vector_authority_catalog(
            catalog_path,
            enabled=enabled,
            replace=True,
            allow_legacy_io=allow_legacy_io,
        )
    from ipfs_datasets_py.vector_stores.management_engine import (
        configure_vector_shadow_catalog,
    )
    return configure_vector_shadow_catalog(
        catalog_path,
        enabled=enabled,
        replace=True,
        allow_legacy_io=allow_legacy_io,
    )


def configure_mcp_vector_authority_catalog(
    catalog_path: Union[str, Path, None] = None,
    *,
    enabled: bool = True,
    allow_legacy_io: Optional[bool] = None,
) -> Any:
    """Configure dual-mode DuckDB authority catalog for MCP tools (DQK-063/064)."""

    return configure_mcp_vector_shadow_catalog(
        catalog_path,
        enabled=enabled,
        dual_mode=True,
        allow_legacy_io=allow_legacy_io,
    )


def restart_mcp_vector_catalog_from_duckdb(
    catalog_path: Union[str, Path, None] = None,
) -> Dict[str, Any]:
    """Simulate MCP process restart: rebind catalog from DuckDB + rehydrate maps.

    Does not rely on process-local mappings. Vector segment bytes remain in the
    selected engine; lifecycle metadata reloads from DuckDB (DQK-064).
    """

    global _global_manager, _mcp_catalog_path
    path = catalog_path or _mcp_catalog_path
    if path is None:
        existing = get_mcp_vector_authority_catalog() or get_mcp_vector_shadow_catalog()
        if existing is not None and existing.path != ":memory:":
            path = existing.path
    # Drop process-local manager + catalog, then rebind from durable path.
    _global_manager = None
    from ipfs_datasets_py.vector_stores.management_engine import (
        configure_vector_authority_catalog,
        reset_vector_authority_catalog,
    )
    reset_vector_authority_catalog()
    if path is None or path == ":memory:":
        catalog = configure_vector_authority_catalog(enabled=True, replace=True)
        summary = {"collections": 0, "live_vectors": 0, "mode": catalog.mode}
    else:
        _mcp_catalog_path = str(path)
        catalog = configure_vector_authority_catalog(
            path, enabled=True, replace=True
        )
        summary = catalog.rehydrate_process_maps_from_store()
    return {
        "status": "success",
        "catalog_path": catalog.path,
        "mode": catalog.mode,
        "authority": catalog._authority_label(),
        "legacy_io_allowed": catalog.legacy_io_allowed,
        "rehydrate": summary,
        "process_local_mapping_loss": False,
    }


def get_mcp_vector_shadow_catalog() -> Any:
    """Return the shared DuckDB vector catalog (may be ``None``)."""

    from ipfs_datasets_py.vector_stores.management_engine import (
        get_vector_authority_catalog,
        get_vector_shadow_catalog,
    )
    return get_vector_authority_catalog() or get_vector_shadow_catalog()


def get_mcp_vector_authority_catalog() -> Any:
    """Return the dual-mode authority catalog when configured."""

    from ipfs_datasets_py.vector_stores.management_engine import (
        get_vector_authority_catalog,
    )
    return get_vector_authority_catalog()


def mcp_vector_publication_document() -> Dict[str, Any]:
    """Approved collection/build statistics for Quack (no unrestricted embeddings)."""

    catalog = get_mcp_vector_authority_catalog() or get_mcp_vector_shadow_catalog()
    if catalog is None:
        from ipfs_datasets_py.vector_stores.management_engine import (
            VECTOR_PUBLICATION_TYPE,
            VECTOR_PUBLICATION_SCHEMA_VERSION,
            VECTOR_DUCKDB_ONLY_DOMAIN,
        )
        return {
            "publication_type": VECTOR_PUBLICATION_TYPE,
            "schema_version": VECTOR_PUBLICATION_SCHEMA_VERSION,
            "domain": VECTOR_DUCKDB_ONLY_DOMAIN,
            "approved_collection_build_statistics": [],
            "embeddings_excluded": True,
            "unrestricted_documents_excluded": True,
            "pickle_authority": False,
        }
    return catalog.publication_document()


# Main MCP functions for registration
async def get_global_manager(context: Optional["ServerContext"] = None) -> Dict[str, Any]:
    """Get or create the index manager.

    Args:
        context: Optional ServerContext. If provided, uses context's vector stores.
                Otherwise, falls back to global instance for backward compatibility.

    Returns:
        Status dict with manager information

    Note:
        The global instance is deprecated. New code should use ServerContext.
    """
    # If context provided, use it (new pattern)
    if context is not None:
        # Context manages vector stores via register_vector_store()
        return {
            "status": "success",
            "message": "Using ServerContext vector stores",
            "manager_available": True,
        }

    # Fallback to global for backward compatibility (deprecated)
    global _global_manager
    if _global_manager is None:
        try:
            from ipfs_datasets_py.ml.embeddings.ipfs_knn_index import IPFSKnnIndexManager

            _global_manager = IPFSKnnIndexManager()
        except ImportError:
            _global_manager = None
            return {"status": "error", "message": "IPFSKnnIndexManager not available"}
    return {
        "status": "success",
        "message": "Global manager retrieved successfully",
        "manager_available": _global_manager is not None,
    }


async def reset_global_manager():
    """Reset the global manager (for testing purposes)."""
    global _global_manager
    _global_manager = None
    return {"status": "success", "message": "Global manager reset successfully"}
