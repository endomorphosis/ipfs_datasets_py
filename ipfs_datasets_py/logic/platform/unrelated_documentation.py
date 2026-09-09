"""PCPR-066 unrelated documentation sidecar.

This module is documentation-only. It is not a LogicProviderProtocol@2
operation, does not remint protocol identity, does not add a protocol
operation, and is outside the semantic impact cone of DatasetsContextPack@1,
the PCPR-064 bounded PatchPlan, selected tests, and solver-qualification
proofs.

Eligible ContextPack, proof, and test reuse remains PCPR-067. A relevant
interface change remains PCPR-068. This sidecar never writes DuckDB or
Quack state and never emits a closed PCPR release outcome.
"""

from __future__ import annotations

from typing import Final

UNRELATED_DOCUMENTATION_INTERFACE: Final = (
    "LogicProviderProtocolUnrelatedDocumentation@1"
)
UNRELATED_DOCUMENTATION_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-unrelated-documentation@1"
)
UNRELATED_DOCUMENTATION_KIND: Final = "unrelated_documentation"
UNRELATED_DOCUMENTATION_TASK_ID: Final = "PCPR-066"
PROTOCOL_INTERFACE: Final = "LogicProviderProtocol@2"
SEMANTIC_FRONTIER: Final[tuple[str, ...]] = (
    "LogicProviderProtocol@2",
    "DatasetsContextPack@1",
    "tests/unit/test_pcpr_013_logic_provider_protocol.py",
    "tests/unit/test_pcpr_014_semantic_apis.py",
    "tests/unit/test_pcpr_017_solver_qualification.py",
    "ipfs_datasets_py/assurance/solver_qualification.py",
)
IMPACTED_CONE: Final[tuple[str, ...]] = ()
REMINTS_PROTOCOL: Final = False
ADDS_PROTOCOL_OPERATION: Final = False
WHOLE_PLAN_REGENERATION_REQUIRED: Final = False
RELEVANT_INTERFACE_CHANGE: Final = False
REUSE_DEMONSTRATED: Final = False
ELIGIBLE_REUSE: Final = True
NEXT_TASK_ID: Final = "PCPR-067"

UNRELATED_DOCUMENTATION_NOTE: Final = (
    "Operator documentation unrelated to the typed formal-logic API. This "
    "note does not modify LogicProviderProtocol@2, DatasetsContextPack@1, "
    "selected tests, or solver-qualification proofs. Eligible reuse remains "
    "PCPR-067. Relevant interface change remains PCPR-068."
)


def unrelated_documentation_record() -> dict[str, object]:
    """Return the documentation-only sidecar record. Not a protocol op."""

    return {
        "interface": UNRELATED_DOCUMENTATION_INTERFACE,
        "schema": UNRELATED_DOCUMENTATION_SCHEMA,
        "kind": UNRELATED_DOCUMENTATION_KIND,
        "task_id": UNRELATED_DOCUMENTATION_TASK_ID,
        "protocol_interface": PROTOCOL_INTERFACE,
        "semantic_frontier": list(SEMANTIC_FRONTIER),
        "impacted_cone": list(IMPACTED_CONE),
        "remints_protocol": REMINTS_PROTOCOL,
        "adds_protocol_operation": ADDS_PROTOCOL_OPERATION,
        "whole_plan_regeneration_required": WHOLE_PLAN_REGENERATION_REQUIRED,
        "relevant_interface_change": RELEVANT_INTERFACE_CHANGE,
        "eligible_reuse": ELIGIBLE_REUSE,
        "reuse_demonstrated": REUSE_DEMONSTRATED,
        "next_task_id": NEXT_TASK_ID,
        "note": UNRELATED_DOCUMENTATION_NOTE,
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
    }


__all__ = [
    "ADDS_PROTOCOL_OPERATION",
    "ELIGIBLE_REUSE",
    "IMPACTED_CONE",
    "NEXT_TASK_ID",
    "PROTOCOL_INTERFACE",
    "RELEVANT_INTERFACE_CHANGE",
    "REMINTS_PROTOCOL",
    "REUSE_DEMONSTRATED",
    "SEMANTIC_FRONTIER",
    "UNRELATED_DOCUMENTATION_INTERFACE",
    "UNRELATED_DOCUMENTATION_KIND",
    "UNRELATED_DOCUMENTATION_NOTE",
    "UNRELATED_DOCUMENTATION_SCHEMA",
    "UNRELATED_DOCUMENTATION_TASK_ID",
    "WHOLE_PLAN_REGENERATION_REQUIRED",
    "unrelated_documentation_record",
]
