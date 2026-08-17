"""Runtime MCP dual-binding adapter for the datasets MCP++ server.

Interface: RuntimeBindingAdapter@1
Task: MCPP-023

Datasets runtime prefers the shared accelerate implementation when available,
falling back to a local re-export of the same adapter surface so the package
can advertise and enforce dual MCP bindings independently.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Optional, Set

logger = logging.getLogger(__name__)

_HAVE_ACCELERATE_BINDINGS = False


def _ensure_ipfs_accelerate_on_path() -> None:
    """Make ipfs_accelerate_py importable when checked out as a sibling tree."""
    try:
        for parent in Path(__file__).resolve().parents:
            candidate = parent / "ipfs_accelerate_py"
            if (candidate / "mcp_server" / "mcplusplus").is_dir() or (
                candidate / "ipfs_accelerate_py" / "mcplusplus_module"
            ).exists():
                if str(candidate) not in sys.path:
                    sys.path.insert(0, str(candidate))
                return
    except Exception as exc:  # pragma: no cover - path probe best-effort
        logger.debug("Could not add ipfs_accelerate_py to sys.path: %s", exc)


_ensure_ipfs_accelerate_on_path()

try:
    from ipfs_accelerate_py.mcp_server.mcplusplus.bindings import (  # noqa: F401
        INTERFACE_LABEL,
        LEGACY_BINDING_ID,
        CURRENT_BINDING_ID,
        LEGACY_PROTOCOL_VERSION,
        CURRENT_PROTOCOL_VERSION,
        KNOWN_BINDING_IDS,
        META_PROTOCOL_VERSION,
        META_CLIENT_CAPS,
        META_CLIENT_INFO,
        META_SERVER_INFO,
        META_BINDING_ID,
        ERR_METHOD_NOT_FOUND,
        ERR_INVALID_PARAMS,
        ERR_UNSUPPORTED_PROTOCOL_VERSION,
        ERR_NOT_INITIALIZED,
        REASON_FORGED_VERSION,
        REASON_BINDING_MISMATCH,
        REASON_SILENT_DOWNGRADE,
        REASON_INIT_AS_CURRENT,
        REASON_BINDING_NOT_OFFERED,
        REASON_PATH_AMBIGUOUS,
        REASON_VERSION_BINDING_MISMATCH,
        PeerMode,
        SessionPhase,
        BindingResponse,
        RuntimeBindingAdapter,
        mode_to_bindings,
        mode_to_versions,
        extract_binding_and_profiles,
        legacy_initialize_params,
        current_request_meta,
        make_legacy_request,
        make_current_request,
        open_legacy_session,
        create_runtime_binding_adapter as _create_runtime_binding_adapter,
        DEFAULT_PROFILES,
    )

    _HAVE_ACCELERATE_BINDINGS = True
except ImportError as exc:  # pragma: no cover - exercised when accelerate missing
    logger.warning(
        "Accelerate RuntimeBindingAdapter unavailable (%s); "
        "datasets bindings require ipfs_accelerate_py.mcp_server.mcplusplus.bindings",
        exc,
    )
    raise


def create_runtime_binding_adapter(
    *,
    mode: PeerMode | str = PeerMode.DUAL,
    runtime: str = "datasets",
    server_name: Optional[str] = None,
    server_version: str = "1.0.0",
    profiles: Optional[Set[str]] = None,
) -> RuntimeBindingAdapter:
    """Factory for RuntimeBindingAdapter@1 used by datasets runtime."""
    if server_name is None:
        server_name = "ipfs-datasets-mcp++"
    return _create_runtime_binding_adapter(
        mode=mode,
        runtime=runtime,
        server_name=server_name,
        server_version=server_version,
        profiles=profiles,
    )


def create_datasets_binding_adapter(
    *,
    mode: PeerMode | str = PeerMode.DUAL,
    **kwargs: Any,
) -> RuntimeBindingAdapter:
    """Convenience factory pinned to the datasets runtime identity."""
    kwargs.setdefault("runtime", "datasets")
    kwargs.setdefault("server_name", "ipfs-datasets-mcp++")
    return create_runtime_binding_adapter(mode=mode, **kwargs)


HAVE_RUNTIME_BINDINGS = _HAVE_ACCELERATE_BINDINGS

__all__ = [
    "INTERFACE_LABEL",
    "LEGACY_BINDING_ID",
    "CURRENT_BINDING_ID",
    "LEGACY_PROTOCOL_VERSION",
    "CURRENT_PROTOCOL_VERSION",
    "KNOWN_BINDING_IDS",
    "META_PROTOCOL_VERSION",
    "META_CLIENT_CAPS",
    "META_CLIENT_INFO",
    "META_SERVER_INFO",
    "META_BINDING_ID",
    "ERR_METHOD_NOT_FOUND",
    "ERR_INVALID_PARAMS",
    "ERR_UNSUPPORTED_PROTOCOL_VERSION",
    "ERR_NOT_INITIALIZED",
    "REASON_FORGED_VERSION",
    "REASON_BINDING_MISMATCH",
    "REASON_SILENT_DOWNGRADE",
    "REASON_INIT_AS_CURRENT",
    "REASON_BINDING_NOT_OFFERED",
    "REASON_PATH_AMBIGUOUS",
    "REASON_VERSION_BINDING_MISMATCH",
    "PeerMode",
    "SessionPhase",
    "BindingResponse",
    "RuntimeBindingAdapter",
    "mode_to_bindings",
    "mode_to_versions",
    "extract_binding_and_profiles",
    "legacy_initialize_params",
    "current_request_meta",
    "make_legacy_request",
    "make_current_request",
    "open_legacy_session",
    "create_runtime_binding_adapter",
    "create_datasets_binding_adapter",
    "HAVE_RUNTIME_BINDINGS",
    "DEFAULT_PROFILES",
]
