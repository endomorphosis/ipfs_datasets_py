"""LPC-071: advisors may propose; they cannot raise proof authority."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.tactician import (
    LogicTactician,
    TacticianGoal,
    TacticianPolicy,
    TacticianReceipt,
    TacticianSource,
    TacticianValidationError,
    default_policy,
)
from ipfs_datasets_py.logic.tactician.receipts import ReceiptError


def _advisor_note() -> Path:
    relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "advisor_authority.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / relative


def test_advisor_authority_note_declares_the_boundary() -> None:
    text = _advisor_note().read_text(encoding="utf-8").lower()
    for phrase in (
        "cannot mark",
        "semantic_authority",
        "verification key",
        "reconstruction",
        "production",
        "assumptions",
        "blocking proof obligation",
    ):
        assert phrase in text, phrase


def test_planner_receipt_never_grants_semantic_authority(
    sample_goal: TacticianGoal,
    sample_sources: list[TacticianSource],
    baseline_policy: TacticianPolicy,
) -> None:
    plan = LogicTactician().plan(sample_goal, sample_sources, baseline_policy)
    assert plan.semantic_authority is False
    receipt = TacticianReceipt.from_plan(plan, baseline_policy)
    assert receipt.semantic_authority is False
    with pytest.raises(ReceiptError):
        TacticianReceipt(
            receipt_id="forged",
            plan=plan,
            policy_digest=receipt.policy_digest,
            planner_id=plan.planner_id,
            semantic_authority=True,
        ).validate()


def test_mismatched_policy_cannot_be_used_to_upgrade_a_plan(
    sample_goal: TacticianGoal,
    sample_sources: list[TacticianSource],
    baseline_policy: TacticianPolicy,
) -> None:
    plan = LogicTactician().plan(sample_goal, sample_sources, baseline_policy)
    other = default_policy(
        source_class_order=list(baseline_policy.source_class_order),
        denied_source_classes=list(baseline_policy.denied_source_classes),
    )
    if other.policy_id == plan.policy_id:
        pytest.skip("policies collided")
    with pytest.raises(ReceiptError, match="policy_id"):
        TacticianReceipt.from_plan(plan, other)


def test_goal_metadata_cannot_claim_semantic_authority() -> None:
    with pytest.raises(TacticianValidationError):
        TacticianGoal(
            goal_id="g1",
            statement_ref="s1",
            goal_family="family",
            goal_root="g",
            corpus_root="c",
            config_root="cfg",
            metadata={"semantic_authority": True},
        ).validate()
