"""PCPR-083 authority-bypass sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned Python and generic MCP client authority-bypass proof.
DatasetsContextPack@1 remains stale and rejected after PCPR-069.
LogicProviderProtocol@2 is not reminted. Authority-bypass proof is owned
by Accelerate. This sidecar never writes DuckDB or Quack state and never
emits a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

AUTHORITY_BYPASS_INTERFACE: Final = "LogicProviderProtocolAuthorityBypass@1"
AUTHORITY_BYPASS_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-authority-bypass@1"
)
AUTHORITY_BYPASS_KIND: Final = "authority_bypass"
AUTHORITY_BYPASS_TASK_ID: Final = "PCPR-083"
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
SURVIVES_PARITY: Final = True
SURVIVES_BYPASS: Final = True
IDEMPOTENT: Final = True
BYPASS_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-090"
PLAN_EPOCH: Final = 2
OWNER_GENERATION: Final = 2

AUTHORITY_BYPASS_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned Python and generic "
    "MCP client authority-bypass proof. DatasetsContextPack@1 remains stale "
    "and rejected. The canonical protocol identity remains "
    "LogicProviderProtocol@2. Unaffected solver-qualification proofs "
    "remain current. Authority-bypass proof is owned by Accelerate. "
    "Threat-model preparation remains PCPR-090."
)


def authority_bypass_record() -> dict[str, object]:
    """Return the Datasets-owned authority-bypass sidecar record."""

    return {
        "interface": AUTHORITY_BYPASS_INTERFACE,
        "schema": AUTHORITY_BYPASS_SCHEMA,
        "kind": AUTHORITY_BYPASS_KIND,
        "task_id": AUTHORITY_BYPASS_TASK_ID,
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
        "survives_parity": SURVIVES_PARITY,
        "survives_bypass": SURVIVES_BYPASS,
        "idempotent": IDEMPOTENT,
        "bypass_owned_by": BYPASS_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "owner_generation": OWNER_GENERATION,
        "next_task_id": NEXT_TASK_ID,
        "note": AUTHORITY_BYPASS_NOTE,
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "AUTHORITY_BYPASS_INTERFACE",
    "AUTHORITY_BYPASS_KIND",
    "AUTHORITY_BYPASS_NOTE",
    "AUTHORITY_BYPASS_SCHEMA",
    "AUTHORITY_BYPASS_TASK_ID",
    "BYPASS_OWNED_BY",
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
    "SURVIVES_BYPASS",
    "SURVIVES_CHAIN",
    "SURVIVES_CLIENT",
    "SURVIVES_PARITY",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "authority_bypass_record",
]
