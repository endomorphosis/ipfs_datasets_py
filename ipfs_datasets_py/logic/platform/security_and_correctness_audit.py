"""PCPR-092 security-and-correctness-audit-package sidecar.

This module records Datasets-owned survival of semantic identities across
the Accelerate-owned objective-to-release security and correctness audit
package. DatasetsContextPack@1 remains stale and rejected after PCPR-069.
LogicProviderProtocol@2 is not reminted. Audit-package ownership remains
with Accelerate. This sidecar never writes DuckDB or Quack state and never
emits a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

AUDIT_PACKAGE_INTERFACE: Final = (
    "LogicProviderProtocolSecurityAndCorrectnessAuditPackage@1"
)
AUDIT_PACKAGE_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-security-and-correctness-audit-package@1"
)
AUDIT_PACKAGE_KIND: Final = "security_and_correctness_audit_package"
AUDIT_PACKAGE_TASK_ID: Final = "PCPR-092"
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
IDEMPOTENT: Final = True
AUDIT_PACKAGE_OWNED_BY: Final = "ipfs_accelerate_py"
NEXT_TASK_ID: Final = "PCPR-093"
PLAN_EPOCH: Final = 2
OWNER_GENERATION: Final = 2
AUDIT_STATUS: Final = "external_audit_ready"

AUDIT_PACKAGE_NOTE: Final = (
    "Semantic identities survive the Accelerate-owned objective-to-release "
    "security and correctness audit package. DatasetsContextPack@1 remains "
    "stale and rejected. The canonical protocol identity remains "
    "LogicProviderProtocol@2. Unaffected solver-qualification proofs remain "
    "current. Audit-package ownership remains with Accelerate. Package "
    "status is external_audit_ready and is never externally_audited. Closed "
    "release decision remains PCPR-093/094."
)


def security_and_correctness_audit_record() -> dict[str, object]:
    """Return the Datasets-owned audit-package sidecar record."""

    return {
        "interface": AUDIT_PACKAGE_INTERFACE,
        "schema": AUDIT_PACKAGE_SCHEMA,
        "kind": AUDIT_PACKAGE_KIND,
        "task_id": AUDIT_PACKAGE_TASK_ID,
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
        "idempotent": IDEMPOTENT,
        "audit_package_owned_by": AUDIT_PACKAGE_OWNED_BY,
        "audit_status": AUDIT_STATUS,
        "externally_audited": False,
        "plan_epoch": PLAN_EPOCH,
        "owner_generation": OWNER_GENERATION,
        "next_task_id": NEXT_TASK_ID,
        "note": AUDIT_PACKAGE_NOTE,
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "AUDIT_PACKAGE_INTERFACE",
    "AUDIT_PACKAGE_KIND",
    "AUDIT_PACKAGE_NOTE",
    "AUDIT_PACKAGE_OWNED_BY",
    "AUDIT_PACKAGE_SCHEMA",
    "AUDIT_PACKAGE_TASK_ID",
    "AUDIT_STATUS",
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
    "SURVIVES_AUDIT_PACKAGE",
    "SURVIVES_BYPASS",
    "SURVIVES_CHAIN",
    "SURVIVES_CLIENT",
    "SURVIVES_PARITY",
    "SURVIVES_TCB_INVENTORY",
    "SURVIVES_THREAT_MODEL",
    "UNAFFECTED",
    "UNAFFECTED_PRESERVED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "security_and_correctness_audit_record",
]
