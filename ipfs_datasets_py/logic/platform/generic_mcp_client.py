"""PCPR-081 generic-MCP-client sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned generic MCP-client demonstration.
DatasetsContextPack@1 remains stale and rejected after PCPR-069.
LogicProviderProtocol@2 is not reminted. The generic MCP client is owned
by Accelerate. This sidecar never writes DuckDB or Quack state and never
emits a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

GENERIC_MCP_CLIENT_INTERFACE: Final = (
    "LogicProviderProtocolGenericMcpClient@1"
)
GENERIC_MCP_CLIENT_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-generic-mcp-client@1"
)
GENERIC_MCP_CLIENT_KIND: Final = "generic_mcp_client_demonstration"
GENERIC_MCP_CLIENT_TASK_ID: Final = "PCPR-081"
PROTOCOL_INTERFACE: Final = "LogicProviderProtocol@2"
SEMANTIC_FRONTIER: Final[tuple[str, ...]] = (
    "LogicProviderProtocol@2",
    "DatasetsContextPack@1",
    "tests/unit/test_pcpr_013_logic_provider_protocol.py",
    "tests/unit/test_pcpr_014_semantic_apis.py",
    "tests/unit/test_pcpr_017_solver_qualification.py",
    "ipfs_datasets_py/assurance/solver_qualification.py",
)
STALE_IDENTITIES: Final[tuple[str, ...]] = (
    "DatasetsContextPack@1",
    "tests/unit/test_pcpr_013_logic_provider_protocol.py",
    "tests/unit/test_pcpr_014_semantic_apis.py",
)
UNAFFECTED: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_017_solver_qualification.py",
    "ipfs_datasets_py/assurance/solver_qualification.py",
)
REMINTS_PROTOCOL: Final = False
ADDS_PROTOCOL_OPERATION: Final = False
WHOLE_PLAN_REGENERATION_REQUIRED: Final = False
RELEVANT_INTERFACE_CHANGE: Final = False
STALE_REJECTED: Final = True
UNAFFECTED_PRESERVED: Final = True
SURVIVES_CHAIN: Final = True
SURVIVES_CLIENT: Final = True
IDEMPOTENT: Final = True
CLIENT_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-082"
PLAN_EPOCH: Final = 2
OWNER_GENERATION: Final = 2

GENERIC_MCP_CLIENT_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned generic "
    "MCP-client demonstration. DatasetsContextPack@1 remains stale "
    "and rejected. The canonical protocol identity remains "
    "LogicProviderProtocol@2. Unaffected solver-qualification proofs "
    "remain current. The generic MCP client is owned by Accelerate. "
    "Cross-client objective identity parity remains PCPR-082."
)


def generic_mcp_client_record() -> dict[str, object]:
    """Return the Datasets-owned generic-MCP-client sidecar record."""

    return {
        "interface": GENERIC_MCP_CLIENT_INTERFACE,
        "schema": GENERIC_MCP_CLIENT_SCHEMA,
        "kind": GENERIC_MCP_CLIENT_KIND,
        "task_id": GENERIC_MCP_CLIENT_TASK_ID,
        "protocol_interface": PROTOCOL_INTERFACE,
        "semantic_frontier": list(SEMANTIC_FRONTIER),
        "stale_identities": list(STALE_IDENTITIES),
        "unaffected": list(UNAFFECTED),
        "remints_protocol": REMINTS_PROTOCOL,
        "adds_protocol_operation": ADDS_PROTOCOL_OPERATION,
        "whole_plan_regeneration_required": WHOLE_PLAN_REGENERATION_REQUIRED,
        "relevant_interface_change": RELEVANT_INTERFACE_CHANGE,
        "stale_rejected": STALE_REJECTED,
        "unaffected_preserved": UNAFFECTED_PRESERVED,
        "survives_chain": SURVIVES_CHAIN,
        "survives_client": SURVIVES_CLIENT,
        "idempotent": IDEMPOTENT,
        "client_owned_by": CLIENT_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "owner_generation": OWNER_GENERATION,
        "next_task_id": NEXT_TASK_ID,
        "note": GENERIC_MCP_CLIENT_NOTE,
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "CLIENT_OWNED_BY",
    "GENERIC_MCP_CLIENT_INTERFACE",
    "GENERIC_MCP_CLIENT_KIND",
    "GENERIC_MCP_CLIENT_NOTE",
    "GENERIC_MCP_CLIENT_SCHEMA",
    "GENERIC_MCP_CLIENT_TASK_ID",
    "IDEMPOTENT",
    "NEXT_TASK_ID",
    "OWNER_GENERATION",
    "PLAN_EPOCH",
    "PROTOCOL_INTERFACE",
    "RELEVANT_INTERFACE_CHANGE",
    "REMINTS_PROTOCOL",
    "SEMANTIC_FRONTIER",
    "STALE_IDENTITIES",
    "STALE_REJECTED",
    "SURVIVES_CHAIN",
    "SURVIVES_CLIENT",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "generic_mcp_client_record",
]
