"""PCPR-069 stale-rejection sidecar.

This module records Datasets-owned stale rejection of ContextPack and
protocol-test identities after the PCPR-068 relevant interface change.
Unaffected solver-qualification proofs remain current. PlanDelta and
bounded refill are owned by Accelerate. This sidecar never writes
DuckDB or Quack state and never emits a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

STALE_REJECTION_INTERFACE: Final = "LogicProviderProtocolStaleRejection@1"
STALE_REJECTION_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-stale-rejection@1"
)
STALE_REJECTION_KIND: Final = "stale_rejection_and_plan_delta"
STALE_REJECTION_TASK_ID: Final = "PCPR-069"
PROTOCOL_INTERFACE: Final = "LogicProviderProtocol@2"
SEMANTIC_FRONTIER: Final[tuple[str, ...]] = (
    "LogicProviderProtocol@2",
    "DatasetsContextPack@1",
    "tests/unit/test_pcpr_013_logic_provider_protocol.py",
    "tests/unit/test_pcpr_014_semantic_apis.py",
    "tests/unit/test_pcpr_017_solver_qualification.py",
    "ipfs_datasets_py/assurance/solver_qualification.py",
)
IMPACTED_CONE: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/logic/backends/protocol_v2.py",
    "ipfs_datasets_py/logic/platform/relevant_interface.py",
    "tests/unit/test_pcpr_013_logic_provider_protocol.py",
    "tests/unit/test_pcpr_014_semantic_apis.py",
    "DatasetsContextPack@1",
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
PLAN_DELTA_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-070"
PLAN_EPOCH: Final = 2

STALE_REJECTION_NOTE: Final = (
    "Stale ContextPack and protocol-test identities are rejected after "
    "the PCPR-068 relevant interface change. The canonical protocol "
    "identity remains LogicProviderProtocol@2. Unaffected "
    "solver-qualification proofs remain current. PlanDelta and bounded "
    "refill are owned by Accelerate. Restart recovery remains PCPR-070."
)


def stale_rejection_record() -> dict[str, object]:
    """Return the Datasets-owned stale-rejection sidecar record."""

    return {
        "interface": STALE_REJECTION_INTERFACE,
        "schema": STALE_REJECTION_SCHEMA,
        "kind": STALE_REJECTION_KIND,
        "task_id": STALE_REJECTION_TASK_ID,
        "protocol_interface": PROTOCOL_INTERFACE,
        "semantic_frontier": list(SEMANTIC_FRONTIER),
        "impacted_cone": list(IMPACTED_CONE),
        "stale_identities": list(STALE_IDENTITIES),
        "unaffected": list(UNAFFECTED),
        "remints_protocol": REMINTS_PROTOCOL,
        "adds_protocol_operation": ADDS_PROTOCOL_OPERATION,
        "whole_plan_regeneration_required": WHOLE_PLAN_REGENERATION_REQUIRED,
        "relevant_interface_change": RELEVANT_INTERFACE_CHANGE,
        "stale_rejected": STALE_REJECTED,
        "unaffected_preserved": UNAFFECTED_PRESERVED,
        "plan_delta_owned_by": PLAN_DELTA_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "next_task_id": NEXT_TASK_ID,
        "note": STALE_REJECTION_NOTE,
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "IMPACTED_CONE",
    "NEXT_TASK_ID",
    "PLAN_DELTA_OWNED_BY",
    "PLAN_EPOCH",
    "PROTOCOL_INTERFACE",
    "RELEVANT_INTERFACE_CHANGE",
    "REMINTS_PROTOCOL",
    "SEMANTIC_FRONTIER",
    "STALE_IDENTITIES",
    "STALE_REJECTED",
    "STALE_REJECTION_INTERFACE",
    "STALE_REJECTION_KIND",
    "STALE_REJECTION_NOTE",
    "STALE_REJECTION_SCHEMA",
    "STALE_REJECTION_TASK_ID",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "stale_rejection_record",
]
