"""Datasets v0.1 assurance-specification binding (PCCE-018).

No campaign execution, persistence, or model authority lives here.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

from ipfs_datasets_py.logic.software_contracts.adversarial_assurance import (
    ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE,
    MUTATION_CAMPAIGN_PLAN_INTERFACE,
    PACKAGE_INTERFACE,
    PACKAGE_SCHEMA,
    AssuranceCampaignReceipt,
    AssuranceTerminalStatus,
    MutationCampaignPlan,
    freeze_adversarial_assurance_artifacts,
    held_out_results,
    package_schema_paths,
)

SPEC_SCHEMA: Final[str] = "ipfs-datasets.proof-context.assurance-specification@0.1"
SPEC_INTERFACE: Final[str] = "DatasetsAssuranceSpecification@0.1"

OUTCOMES: Final[tuple[str, ...]] = (
    "omission",
    "vacuity",
    "critical_survivor",
    "context_expansion",
    "human_review_required",
    "unavailable",
    "timeout",
    "infrastructure_failure",
)


class AssuranceSpecificationError(RuntimeError):
    reason = "invalid"


def specification_catalog() -> dict[str, Any]:
    artifacts = freeze_adversarial_assurance_artifacts()
    return {
        "schema": SPEC_SCHEMA,
        "interface": SPEC_INTERFACE,
        "package_interface": PACKAGE_INTERFACE,
        "package_schema": PACKAGE_SCHEMA,
        "plan_interface": MUTATION_CAMPAIGN_PLAN_INTERFACE,
        "receipt_interface": ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE,
        "outcomes": OUTCOMES,
        "held_out_results": tuple(held_out_results()),
        "schema_paths": tuple(str(path) for path in package_schema_paths()),
        "catalog": artifacts,
        "runtime_authority": False,
        "persistence_authority": False,
    }


def require_closed_outcome(status: str) -> None:
    names = {item.value if hasattr(item, "value") else str(item) for item in AssuranceTerminalStatus}
    if status not in names and status not in OUTCOMES:
        raise AssuranceSpecificationError(f"unknown assurance outcome {status!r}")


def bind_plan(plan: MutationCampaignPlan | Mapping[str, Any]) -> MutationCampaignPlan:
    if isinstance(plan, MutationCampaignPlan):
        return plan
    raise AssuranceSpecificationError("plan must be a datasets MutationCampaignPlan")


def bind_receipt(receipt: AssuranceCampaignReceipt | Mapping[str, Any]) -> AssuranceCampaignReceipt:
    if isinstance(receipt, AssuranceCampaignReceipt):
        return receipt
    raise AssuranceSpecificationError("receipt must be a datasets AssuranceCampaignReceipt")
