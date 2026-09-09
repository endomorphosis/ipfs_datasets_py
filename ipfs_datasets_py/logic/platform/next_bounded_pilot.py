"""PCPR-096 next-bounded-pilot sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned objective-to-release next-bounded-pilot recommendation
receipt. DatasetsContextPack@1 remains stale and rejected after PCPR-069.
LogicProviderProtocol@2 is not reminted. Next-bounded-pilot ownership
remains with Accelerate. This sidecar never writes DuckDB or Quack state
and never emits a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

NEXT_BOUNDED_PILOT_INTERFACE: Final = (
    "LogicProviderProtocolNextBoundedPilot@1"
)
NEXT_BOUNDED_PILOT_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-next-bounded-pilot@1"
)
NEXT_BOUNDED_PILOT_KIND: Final = "next_bounded_pilot"
NEXT_BOUNDED_PILOT_TASK_ID: Final = "PCPR-096"
RESIDUAL_GAP_REPORT_TASK_ID: Final = "PCPR-095"
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
SURVIVES_AUDIT_PACKAGE: Final = True
SURVIVES_RELEASE_CANDIDATE_GATE: Final = True
SURVIVES_PROMOTION_OR_NON_PROMOTION: Final = True
SURVIVES_NEXT_BOUNDED_PILOT: Final = True
SURVIVES_RESIDUAL_GAP_REPORT: Final = True
IDEMPOTENT: Final = True
NEXT_BOUNDED_PILOT_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = None
PLAN_EPOCH: Final = 2
OWNER_GENERATION: Final = 2

NEXT_BOUNDED_PILOT_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned objective-to-release "
    "next-bounded-pilot recommendation receipt. DatasetsContextPack@1 remains stale "
    "and rejected. The canonical protocol identity remains "
    "LogicProviderProtocol@2. Unaffected solver-qualification proofs remain "
    "current. Next-bounded-pilot ownership remains with Accelerate. This "
    "receipt is an honest R&D next-bounded-pilot recommendation and does not claim a "
    "closed PCPR release outcome. The recommended next pilot is synthetic, is not "
    "created, and does not expand PCPR. Residual reporting does not create a "
    "successor campaign."
)


def next_bounded_pilot_record() -> dict[str, object]:
    """Return the Datasets-owned next-bounded-pilot sidecar record."""

    return {
        "interface": NEXT_BOUNDED_PILOT_INTERFACE,
        "schema": NEXT_BOUNDED_PILOT_SCHEMA,
        "kind": NEXT_BOUNDED_PILOT_KIND,
        "task_id": NEXT_BOUNDED_PILOT_TASK_ID,
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
        "survives_audit_package": SURVIVES_AUDIT_PACKAGE,
        "survives_release_candidate_gate": SURVIVES_RELEASE_CANDIDATE_GATE,
        "survives_promotion_or_non_promotion": SURVIVES_PROMOTION_OR_NON_PROMOTION,
        "survives_next_bounded_pilot": SURVIVES_NEXT_BOUNDED_PILOT,
        "survives_residual_gap_report": SURVIVES_RESIDUAL_GAP_REPORT,
        "idempotent": IDEMPOTENT,
        "next_bounded_pilot_owned_by": NEXT_BOUNDED_PILOT_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "owner_generation": OWNER_GENERATION,
        "next_task_id": NEXT_TASK_ID,
        "note": NEXT_BOUNDED_PILOT_NOTE,
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
    "NEXT_BOUNDED_PILOT_INTERFACE",
    "NEXT_BOUNDED_PILOT_KIND",
    "NEXT_BOUNDED_PILOT_NOTE",
    "NEXT_BOUNDED_PILOT_OWNED_BY",
    "NEXT_BOUNDED_PILOT_SCHEMA",
    "NEXT_BOUNDED_PILOT_TASK_ID",
    "REMINTS_PROTOCOL",
    "SEMANTIC_FRONTIER",
    "STALE_IDENTITIES",
    "STALE_REJECTED",
    "SURVIVES_AUDIT_PACKAGE",
    "SURVIVES_BYPASS",
    "SURVIVES_CHAIN",
    "SURVIVES_CLIENT",
    "SURVIVES_PARITY",
    "SURVIVES_PROMOTION_OR_NON_PROMOTION",
    "SURVIVES_NEXT_BOUNDED_PILOT",
    "SURVIVES_RESIDUAL_GAP_REPORT",
    "SURVIVES_RELEASE_CANDIDATE_GATE",
    "SURVIVES_TCB_INVENTORY",
    "SURVIVES_THREAT_MODEL",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "next_bounded_pilot_record",
]
