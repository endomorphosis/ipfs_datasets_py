"""PCPR-090 threat-model sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned objective-to-release threat model.
DatasetsContextPack@1 remains stale and rejected after PCPR-069.
LogicProviderProtocol@2 is not reminted. Threat-model ownership remains
with Accelerate. This sidecar never writes DuckDB or Quack state and never
emits a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

THREAT_MODEL_INTERFACE: Final = "LogicProviderProtocolThreatModel@1"
THREAT_MODEL_SCHEMA: Final = "ipfs_datasets_py/logic-provider-threat-model@1"
THREAT_MODEL_KIND: Final = "threat_model"
THREAT_MODEL_TASK_ID: Final = "PCPR-090"
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
IDEMPOTENT: Final = True
THREAT_MODEL_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-091"
PLAN_EPOCH: Final = 2
OWNER_GENERATION: Final = 2

THREAT_MODEL_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned objective-to-release "
    "threat model. DatasetsContextPack@1 remains stale and rejected. The "
    "canonical protocol identity remains LogicProviderProtocol@2. Unaffected "
    "solver-qualification proofs remain current. Threat-model ownership "
    "remains with Accelerate. Trusted-computing-base inventory remains "
    "PCPR-091."
)


def threat_model_record() -> dict[str, object]:
    """Return the Datasets-owned threat-model sidecar record."""

    return {
        "interface": THREAT_MODEL_INTERFACE,
        "schema": THREAT_MODEL_SCHEMA,
        "kind": THREAT_MODEL_KIND,
        "task_id": THREAT_MODEL_TASK_ID,
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
        "idempotent": IDEMPOTENT,
        "threat_model_owned_by": THREAT_MODEL_OWNED_BY,
        "plan_epoch": PLAN_EPOCH,
        "owner_generation": OWNER_GENERATION,
        "next_task_id": NEXT_TASK_ID,
        "note": THREAT_MODEL_NOTE,
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
    "SURVIVES_THREAT_MODEL",
    "THREAT_MODEL_INTERFACE",
    "THREAT_MODEL_KIND",
    "THREAT_MODEL_NOTE",
    "THREAT_MODEL_OWNED_BY",
    "THREAT_MODEL_SCHEMA",
    "THREAT_MODEL_TASK_ID",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "threat_model_record",
]
