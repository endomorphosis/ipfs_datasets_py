"""PCPR-091 trusted-computing-base sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned objective-to-release trusted-computing-base inventory.
DatasetsContextPack@1 remains stale and rejected after PCPR-069.
LogicProviderProtocol@2 is not reminted. TCB-inventory ownership remains
with Accelerate. This sidecar never writes DuckDB or Quack state and never
emits a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

TCB_INVENTORY_INTERFACE: Final = "LogicProviderProtocolTrustedComputingBase@1"
TCB_INVENTORY_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-trusted-computing-base@1"
)
TCB_INVENTORY_KIND: Final = "trusted_computing_base"
TCB_INVENTORY_TASK_ID: Final = "PCPR-091"
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
SURVIVES_THREAT_MODEL: Final = True
SURVIVES_TCB_INVENTORY: Final = True
IDEMPOTENT: Final = True
TCB_INVENTORY_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-092"
PLAN_EPOCH: Final = 2
OWNER_GENERATION: Final = 2

TCB_INVENTORY_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned objective-to-release "
    "trusted-computing-base inventory. DatasetsContextPack@1 remains stale "
    "and rejected. The canonical protocol identity remains "
    "LogicProviderProtocol@2. Unaffected solver-qualification proofs remain "
    "current. TCB-inventory ownership remains with Accelerate. Security and "
    "correctness audit package remains PCPR-092."
)


def trusted_computing_base_record() -> dict[str, object]:
    """Return the Datasets-owned TCB-inventory sidecar record."""

    return {
        "interface": TCB_INVENTORY_INTERFACE,
        "schema": TCB_INVENTORY_SCHEMA,
        "kind": TCB_INVENTORY_KIND,
        "task_id": TCB_INVENTORY_TASK_ID,
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
        "survives_threat_model": SURVIVES_THREAT_MODEL,
        "survives_tcb_inventory": SURVIVES_TCB_INVENTORY,
        "idempotent": IDEMPOTENT,
        "tcb_inventory_owned_by": TCB_INVENTORY_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "owner_generation": OWNER_GENERATION,
        "next_task_id": NEXT_TASK_ID,
        "note": TCB_INVENTORY_NOTE,
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
    "RELEVANT_INTERFACE_CHANGE",
    "REMINTS_PROTOCOL",
    "SEMANTIC_FRONTIER",
    "STALE_IDENTITIES",
    "STALE_REJECTED",
    "SURVIVES_BYPASS",
    "SURVIVES_CHAIN",
    "SURVIVES_CLIENT",
    "SURVIVES_PARITY",
    "SURVIVES_TCB_INVENTORY",
    "SURVIVES_THREAT_MODEL",
    "TCB_INVENTORY_INTERFACE",
    "TCB_INVENTORY_KIND",
    "TCB_INVENTORY_NOTE",
    "TCB_INVENTORY_OWNED_BY",
    "TCB_INVENTORY_SCHEMA",
    "TCB_INVENTORY_TASK_ID",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "trusted_computing_base_record",
]
