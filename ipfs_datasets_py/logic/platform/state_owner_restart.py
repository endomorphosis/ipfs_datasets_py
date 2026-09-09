"""PCPR-070 state-owner-restart sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned authoritative state-owner restart. DatasetsContextPack@1
remains stale and rejected after PCPR-069. LogicProviderProtocol@2 is not
reminted. Restart, lease, and fence reconstruction are owned by Accelerate.
This sidecar never writes DuckDB or Quack state and never emits a closed
PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

STATE_OWNER_RESTART_INTERFACE: Final = "LogicProviderProtocolStateOwnerRestart@1"
STATE_OWNER_RESTART_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-state-owner-restart@1"
)
STATE_OWNER_RESTART_KIND: Final = "authoritative_state_owner_restart"
STATE_OWNER_RESTART_TASK_ID: Final = "PCPR-070"
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
RESTART_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-071"
PLAN_EPOCH: Final = 2

STATE_OWNER_RESTART_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned authoritative "
    "state-owner restart. DatasetsContextPack@1 remains stale and rejected. "
    "The canonical protocol identity remains LogicProviderProtocol@2. "
    "Unaffected solver-qualification proofs remain current. Restart, lease, "
    "and fence reconstruction are owned by Accelerate. Recovery and "
    "idempotency remain PCPR-071."
)


def state_owner_restart_record() -> dict[str, object]:
    """Return the Datasets-owned state-owner-restart sidecar record."""

    return {
        "interface": STATE_OWNER_RESTART_INTERFACE,
        "schema": STATE_OWNER_RESTART_SCHEMA,
        "kind": STATE_OWNER_RESTART_KIND,
        "task_id": STATE_OWNER_RESTART_TASK_ID,
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
        "restart_owned_by": RESTART_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "next_task_id": NEXT_TASK_ID,
        "note": STATE_OWNER_RESTART_NOTE,
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "NEXT_TASK_ID",
    "PLAN_EPOCH",
    "PROTOCOL_INTERFACE",
    "RELEVANT_INTERFACE_CHANGE",
    "REMINTS_PROTOCOL",
    "RESTART_OWNED_BY",
    "SEMANTIC_FRONTIER",
    "STALE_IDENTITIES",
    "STALE_REJECTED",
    "STATE_OWNER_RESTART_INTERFACE",
    "STATE_OWNER_RESTART_KIND",
    "STATE_OWNER_RESTART_NOTE",
    "STATE_OWNER_RESTART_SCHEMA",
    "STATE_OWNER_RESTART_TASK_ID",
    "SURVIVES_RESTART",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "state_owner_restart_record",
]
