"""UI/UX IR source adapters (MCP-IDL, Intent IR, ...).

Adapters are side-effect free: they never open network connections, invoke
tools, or mint execution grants. They convert reviewed external contracts into
stable UI program references, source maps, and explicit loss receipts.
"""

from __future__ import annotations

from .mcp_idl_identity import (
    INTERFACE_IDENTITY_PROFILE,
    MCPIDLIdentityAuthority,
    VerifiedInterfaceIdentity,
    compute_verified_interface_cid,
    verify_interface_preimage,
)

__all__ = [
    "INTERFACE_IDENTITY_PROFILE",
    "MCPIDLIdentityAuthority",
    "VerifiedInterfaceIdentity",
    "compute_verified_interface_cid",
    "verify_interface_preimage",
]

try:  # optional until UIR-030 adapter lands fully
    from .mcp_idl import (  # type: ignore
        MCPIDLAdapterResult,
        MCPIDLUIIR_ADAPTER,
        MCPIDLUIIRAdapter,
        adapt_mcp_idl_to_uiir,
    )

    __all__ += [
        "MCPIDLAdapterResult",
        "MCPIDLUIIR_ADAPTER",
        "MCPIDLUIIRAdapter",
        "adapt_mcp_idl_to_uiir",
    ]
except ImportError:  # pragma: no cover
    pass

try:  # optional until UIR-031 lands fully
    from .intent_ir import (  # type: ignore
        INTENT_UIIR_ADAPTER,
        INVOCATION_UIIR_ADAPTER,
        IntentUIIRAdapter,
        InvocationUIIRAdapter,
    )

    __all__ += [
        "INTENT_UIIR_ADAPTER",
        "INVOCATION_UIIR_ADAPTER",
        "IntentUIIRAdapter",
        "InvocationUIIRAdapter",
    ]
except ImportError:  # pragma: no cover
    pass
