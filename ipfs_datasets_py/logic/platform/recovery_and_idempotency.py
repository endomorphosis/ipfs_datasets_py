"""PCPR-071 recovery-and-idempotency sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned recovery and idempotency demonstration. DatasetsContextPack@1
remains stale and rejected after PCPR-069. LogicProviderProtocol@2 is not
reminted. Recovery, idempotency, lease, and fence continuation are owned by
Accelerate. This sidecar never writes DuckDB or Quack state and never emits
a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

RECOVERY_AND_IDEMPOTENCY_INTERFACE: Final = (
    "LogicProviderProtocolRecoveryAndIdempotency@1"
)
RECOVERY_AND_IDEMPOTENCY_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-recovery-and-idempotency@1"
)
RECOVERY_AND_IDEMPOTENCY_KIND: Final = "recovery_and_idempotency"
RECOVERY_AND_IDEMPOTENCY_TASK_ID: Final = "PCPR-071"
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
SURVIVES_RESTART: Final = True
SURVIVES_RECOVERY: Final = True
IDEMPOTENT: Final = True
RECOVERY_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-072"
PLAN_EPOCH: Final = 2
OWNER_GENERATION: Final = 2

RECOVERY_AND_IDEMPOTENCY_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned recovery and "
    "idempotency demonstration. DatasetsContextPack@1 remains stale and "
    "rejected. The canonical protocol identity remains "
    "LogicProviderProtocol@2. Unaffected solver-qualification proofs remain "
    "current. Recovery continuation, duplicate-effect rejection, lease, and "
    "fence authorization are owned by Accelerate. The final receipt chain "
    "remains PCPR-072."
)


def recovery_and_idempotency_record() -> dict[str, object]:
    """Return the Datasets-owned recovery-and-idempotency sidecar record."""

    return {
        "interface": RECOVERY_AND_IDEMPOTENCY_INTERFACE,
        "schema": RECOVERY_AND_IDEMPOTENCY_SCHEMA,
        "kind": RECOVERY_AND_IDEMPOTENCY_KIND,
        "task_id": RECOVERY_AND_IDEMPOTENCY_TASK_ID,
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
        "survives_restart": SURVIVES_RESTART,
        "survives_recovery": SURVIVES_RECOVERY,
        "idempotent": IDEMPOTENT,
        "recovery_owned_by": RECOVERY_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "owner_generation": OWNER_GENERATION,
        "next_task_id": NEXT_TASK_ID,
        "note": RECOVERY_AND_IDEMPOTENCY_NOTE,
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "IDEMPOTENT",
    "NEXT_TASK_ID",
    "OWNER_GENERATION",
    "PLAN_EPOCH",
    "PROTOCOL_INTERFACE",
    "RECOVERY_AND_IDEMPOTENCY_INTERFACE",
    "RECOVERY_AND_IDEMPOTENCY_KIND",
    "RECOVERY_AND_IDEMPOTENCY_NOTE",
    "RECOVERY_AND_IDEMPOTENCY_SCHEMA",
    "RECOVERY_AND_IDEMPOTENCY_TASK_ID",
    "RECOVERY_OWNED_BY",
    "RELEVANT_INTERFACE_CHANGE",
    "REMINTS_PROTOCOL",
    "SEMANTIC_FRONTIER",
    "STALE_IDENTITIES",
    "STALE_REJECTED",
    "SURVIVES_RECOVERY",
    "SURVIVES_RESTART",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "recovery_and_idempotency_record",
]
