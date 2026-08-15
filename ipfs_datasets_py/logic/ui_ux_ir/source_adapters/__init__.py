"""UI/UX IR source adapters (MCP-IDL, Intent IR, DOM/ARIA) — UIR-069.

Adapters are side-effect free: they never open network connections, invoke
tools, or mint execution grants. They convert reviewed external contracts into
stable UI program references, source maps, and explicit loss receipts.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Final

UIUXIR_INTERNAL_PACKAGES_INTERFACE: Final = "UIUXIRInternalPackages@1"

# Eager identity profile only (pure functions, no I/O).
from .mcp_idl_identity import (
    INTERFACE_IDENTITY_PROFILE,
    MCPIDLIdentityAuthority,
    VerifiedInterfaceIdentity,
    compute_verified_interface_cid,
    verify_interface_preimage,
)

__all__ = [
    "UIUXIR_INTERNAL_PACKAGES_INTERFACE",
    "INTERFACE_IDENTITY_PROFILE",
    "MCPIDLIdentityAuthority",
    "VerifiedInterfaceIdentity",
    "compute_verified_interface_cid",
    "verify_interface_preimage",
    "dom_aria",
    "intent_ir",
    "mcp_idl",
    "mcp_idl_identity",
]

_LAZY_MODULES = frozenset(
    {
        "dom_aria",
        "intent_ir",
        "mcp_idl",
        "mcp_idl_identity",
    }
)


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODULES:
        return import_module(f"{__name__}.{name}")
    # Re-export selected symbols from leaves for convenience (lazy).
    if name in {
        "MCPIDLAdapterResult",
        "MCPIDLUIIR_ADAPTER",
        "MCPIDLUIIRAdapter",
        "adapt_mcp_idl_to_uiir",
    }:
        mod = import_module(f"{__name__}.mcp_idl")
        return getattr(mod, name)
    if name in {
        "INTENT_UIIR_ADAPTER",
        "INVOCATION_UIIR_ADAPTER",
        "IntentUIIRAdapter",
        "InvocationUIIRAdapter",
    }:
        mod = import_module(f"{__name__}.intent_ir")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(
        set(__all__)
        | {
            "MCPIDLAdapterResult",
            "MCPIDLUIIR_ADAPTER",
            "MCPIDLUIIRAdapter",
            "adapt_mcp_idl_to_uiir",
            "INTENT_UIIR_ADAPTER",
            "INVOCATION_UIIR_ADAPTER",
            "IntentUIIRAdapter",
            "InvocationUIIRAdapter",
        }
    )
