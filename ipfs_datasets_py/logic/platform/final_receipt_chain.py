"""PCPR-072 final-receipt-chain sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned final proof-carrying receipt chain. DatasetsContextPack@1
remains stale and rejected after PCPR-069. LogicProviderProtocol@2 is not
reminted. Independent semantic validation, hermetic ExecutionReceipt
emission, and chain storage are owned by Accelerate. This sidecar never
writes DuckDB or Quack state and never emits a closed PCPR release
outcome.
"""

from __future__ import annotations

from typing import Final

FINAL_RECEIPT_CHAIN_INTERFACE: Final = "LogicProviderProtocolFinalReceiptChain@1"
FINAL_RECEIPT_CHAIN_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-final-receipt-chain@1"
)
FINAL_RECEIPT_CHAIN_KIND: Final = "final_proof_carrying_receipt_chain"
FINAL_RECEIPT_CHAIN_TASK_ID: Final = "PCPR-072"
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
SURVIVES_CHAIN: Final = True
IDEMPOTENT: Final = True
CHAIN_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-080"
PLAN_EPOCH: Final = 2
OWNER_GENERATION: Final = 2

FINAL_RECEIPT_CHAIN_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned final proof-carrying "
    "receipt chain. DatasetsContextPack@1 remains stale and rejected. The "
    "canonical protocol identity remains LogicProviderProtocol@2. Unaffected "
    "solver-qualification proofs remain current. Independent semantic "
    "validation, hermetic ExecutionReceipt emission, and chain storage are "
    "owned by Accelerate. External-client demonstration remains PCPR-080."
)


def final_receipt_chain_record() -> dict[str, object]:
    """Return the Datasets-owned final-receipt-chain sidecar record."""

    return {
        "interface": FINAL_RECEIPT_CHAIN_INTERFACE,
        "schema": FINAL_RECEIPT_CHAIN_SCHEMA,
        "kind": FINAL_RECEIPT_CHAIN_KIND,
        "task_id": FINAL_RECEIPT_CHAIN_TASK_ID,
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
        "survives_chain": SURVIVES_CHAIN,
        "idempotent": IDEMPOTENT,
        "chain_owned_by": CHAIN_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "owner_generation": OWNER_GENERATION,
        "next_task_id": NEXT_TASK_ID,
        "note": FINAL_RECEIPT_CHAIN_NOTE,
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "CHAIN_OWNED_BY",
    "FINAL_RECEIPT_CHAIN_INTERFACE",
    "FINAL_RECEIPT_CHAIN_KIND",
    "FINAL_RECEIPT_CHAIN_NOTE",
    "FINAL_RECEIPT_CHAIN_SCHEMA",
    "FINAL_RECEIPT_CHAIN_TASK_ID",
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
    "SURVIVES_RECOVERY",
    "SURVIVES_RESTART",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "final_receipt_chain_record",
]
