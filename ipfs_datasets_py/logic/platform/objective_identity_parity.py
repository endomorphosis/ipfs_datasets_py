"""PCPR-082 objective-identity-parity sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned Python and generic MCP client identity-parity proof.
DatasetsContextPack@1 remains stale and rejected after PCPR-069.
LogicProviderProtocol@2 is not reminted. Objective identity parity is
owned by Accelerate. This sidecar never writes DuckDB or Quack state
and never emits a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

OBJECTIVE_IDENTITY_PARITY_INTERFACE: Final = (
    "LogicProviderProtocolObjectiveIdentityParity@1"
)
OBJECTIVE_IDENTITY_PARITY_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-objective-identity-parity@1"
)
OBJECTIVE_IDENTITY_PARITY_KIND: Final = "objective_identity_parity"
OBJECTIVE_IDENTITY_PARITY_TASK_ID: Final = "PCPR-082"
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
IDEMPOTENT: Final = True
PARITY_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-083"
PLAN_EPOCH: Final = 2
OWNER_GENERATION: Final = 2

OBJECTIVE_IDENTITY_PARITY_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned Python and generic "
    "MCP client identity-parity proof. DatasetsContextPack@1 remains stale "
    "and rejected. The canonical protocol identity remains "
    "LogicProviderProtocol@2. Unaffected solver-qualification proofs "
    "remain current. Objective identity parity is owned by Accelerate. "
    "External-client authority-bypass proof remains PCPR-083."
)


def objective_identity_parity_record() -> dict[str, object]:
    """Return the Datasets-owned objective-identity-parity sidecar record."""

    return {
        "interface": OBJECTIVE_IDENTITY_PARITY_INTERFACE,
        "schema": OBJECTIVE_IDENTITY_PARITY_SCHEMA,
        "kind": OBJECTIVE_IDENTITY_PARITY_KIND,
        "task_id": OBJECTIVE_IDENTITY_PARITY_TASK_ID,
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
        "idempotent": IDEMPOTENT,
        "parity_owned_by": PARITY_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "owner_generation": OWNER_GENERATION,
        "next_task_id": NEXT_TASK_ID,
        "note": OBJECTIVE_IDENTITY_PARITY_NOTE,
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "IDEMPOTENT",
    "NEXT_TASK_ID",
    "OBJECTIVE_IDENTITY_PARITY_INTERFACE",
    "OBJECTIVE_IDENTITY_PARITY_KIND",
    "OBJECTIVE_IDENTITY_PARITY_NOTE",
    "OBJECTIVE_IDENTITY_PARITY_SCHEMA",
    "OBJECTIVE_IDENTITY_PARITY_TASK_ID",
    "OWNER_GENERATION",
    "PARITY_OWNED_BY",
    "PLAN_EPOCH",
    "PROTOCOL_INTERFACE",
    "RELEVANT_INTERFACE_CHANGE",
    "REMINTS_PROTOCOL",
    "SEMANTIC_FRONTIER",
    "STALE_IDENTITIES",
    "STALE_REJECTED",
    "SURVIVES_CHAIN",
    "SURVIVES_CLIENT",
    "SURVIVES_PARITY",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "objective_identity_parity_record",
]
