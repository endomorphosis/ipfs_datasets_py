"""PCPR-068 relevant interface-change sidecar.

This module records the Datasets-owned relevant successor operation
``impact`` (LogicProviderProtocolRelevantInterface@1) against
LogicProviderProtocol@2. It adds a protocol operation, does not remint
the canonical @2 identity, and has a nonempty semantic impact cone.

Unaffected solver-qualification proofs remain reusable. Stale
ContextPack and protocol-test identities are recorded here.
Stale rejection and PlanDelta remain PCPR-069. This sidecar never
writes DuckDB or Quack state and never emits a closed PCPR release
outcome.
"""

from __future__ import annotations

from typing import Final

from ipfs_datasets_py.logic.backends.protocol_v2 import (
    LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE,
    RELEVANT_INTERFACE_CHANGE_INTERFACE,
    RELEVANT_INTERFACE_CHANGE_SCHEMA,
    RELEVANT_INTERFACE_CHANGE_TASK_ID,
    RELEVANT_INTERFACE_IMPACTED_CONE,
    RELEVANT_INTERFACE_OPERATION,
    RELEVANT_INTERFACE_STALE_IDENTITIES,
    RELEVANT_INTERFACE_UNAFFECTED,
    ImpactRequestV2,
    RelevantInterfaceChangeV2,
)

RELEVANT_INTERFACE: Final = RELEVANT_INTERFACE_CHANGE_INTERFACE
RELEVANT_INTERFACE_SCHEMA: Final = RELEVANT_INTERFACE_CHANGE_SCHEMA
RELEVANT_INTERFACE_KIND: Final = "relevant_interface"
RELEVANT_INTERFACE_TASK_ID: Final = RELEVANT_INTERFACE_CHANGE_TASK_ID
PROTOCOL_INTERFACE: Final = LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE
SEMANTIC_FRONTIER: Final[tuple[str, ...]] = (
    "LogicProviderProtocol@2",
    "DatasetsContextPack@1",
    "tests/unit/test_pcpr_013_logic_provider_protocol.py",
    "tests/unit/test_pcpr_014_semantic_apis.py",
    "tests/unit/test_pcpr_017_solver_qualification.py",
    "ipfs_datasets_py/assurance/solver_qualification.py",
)
IMPACTED_CONE: Final[tuple[str, ...]] = RELEVANT_INTERFACE_IMPACTED_CONE
STALE_IDENTITIES: Final[tuple[str, ...]] = RELEVANT_INTERFACE_STALE_IDENTITIES
UNAFFECTED: Final[tuple[str, ...]] = RELEVANT_INTERFACE_UNAFFECTED
REMINTS_PROTOCOL: Final = False
ADDS_PROTOCOL_OPERATION: Final = True
WHOLE_PLAN_REGENERATION_REQUIRED: Final = False
RELEVANT_INTERFACE_CHANGE: Final = True
REUSE_DEMONSTRATED: Final = False
ELIGIBLE_REUSE: Final = True
NEXT_TASK_ID: Final = "PCPR-069"
OPERATION: Final = RELEVANT_INTERFACE_OPERATION

RELEVANT_INTERFACE_NOTE: Final = (
    "Successor protocol operation impact on LogicProviderProtocol@2. "
    "The canonical protocol identity remains LogicProviderProtocol@2. "
    "The closed @2 executable set is not reminted. The impacted cone is "
    "nonempty. Unaffected solver-qualification proofs remain reusable. "
    "Stale rejection and PlanDelta remain PCPR-069."
)


def relevant_interface_record() -> dict[str, object]:
    """Return the relevant interface-change sidecar record."""

    request = ImpactRequestV2(request_id="pcpr-068-impact-request")
    change = RelevantInterfaceChangeV2(
        paths=(
            "ipfs_datasets_py/logic/backends/protocol_v2.py",
            "ipfs_datasets_py/logic/platform/relevant_interface.py",
        )
    )
    return {
        "interface": RELEVANT_INTERFACE,
        "schema": RELEVANT_INTERFACE_SCHEMA,
        "kind": RELEVANT_INTERFACE_KIND,
        "task_id": RELEVANT_INTERFACE_TASK_ID,
        "protocol_interface": PROTOCOL_INTERFACE,
        "operation": OPERATION,
        "semantic_frontier": list(SEMANTIC_FRONTIER),
        "impacted_cone": list(IMPACTED_CONE),
        "stale_identities": list(STALE_IDENTITIES),
        "unaffected": list(UNAFFECTED),
        "remints_protocol": REMINTS_PROTOCOL,
        "adds_protocol_operation": ADDS_PROTOCOL_OPERATION,
        "whole_plan_regeneration_required": WHOLE_PLAN_REGENERATION_REQUIRED,
        "relevant_interface_change": RELEVANT_INTERFACE_CHANGE,
        "eligible_reuse": ELIGIBLE_REUSE,
        "reuse_demonstrated": REUSE_DEMONSTRATED,
        "next_task_id": NEXT_TASK_ID,
        "note": RELEVANT_INTERFACE_NOTE,
        "request": request.to_dict(),
        "change": change.to_dict(),
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "ELIGIBLE_REUSE",
    "IMPACTED_CONE",
    "NEXT_TASK_ID",
    "OPERATION",
    "PROTOCOL_INTERFACE",
    "RELEVANT_INTERFACE",
    "RELEVANT_INTERFACE_CHANGE",
    "RELEVANT_INTERFACE_KIND",
    "RELEVANT_INTERFACE_NOTE",
    "RELEVANT_INTERFACE_SCHEMA",
    "RELEVANT_INTERFACE_TASK_ID",
    "REMINTS_PROTOCOL",
    "REUSE_DEMONSTRATED",
    "SEMANTIC_FRONTIER",
    "STALE_IDENTITIES",
    "UNAFFECTED",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "relevant_interface_record",
]
