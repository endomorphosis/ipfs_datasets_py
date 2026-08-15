"""Unit tests for content-addressed GUI verification receipts (VGO-041)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.logic.gui_optimizer.identity import (
    artifact_digest,
    sha256_digest,
)
from ipfs_datasets_py.logic.gui_optimizer.models import (
    AccessibilityReceipt,
    GuiImprovementReceipt,
    InteractionReceipt,
    UiConstraintReceipt,
    UiInvalidationPlan,
    VisualRegressionReceipt,
)
from ipfs_datasets_py.logic.gui_optimizer.receipts import (
    ACCESSIBILITY_RECEIPT_INTERFACE,
    DOMAIN_ACCESSIBILITY_RECEIPT,
    DOMAIN_CONSTRAINT_RECEIPT,
    DOMAIN_IMPROVEMENT_RECEIPT,
    DOMAIN_INTERACTION_RECEIPT,
    DOMAIN_PATCH,
    DOMAIN_SCREENSHOT,
    DOMAIN_VERIFICATION_ENVELOPE,
    DOMAIN_VISUAL_REGRESSION_RECEIPT,
    GUI_IMPROVEMENT_RECEIPT_INTERFACE,
    GUI_VERIFICATION_RECEIPT_AGGREGATOR_INTERFACE,
    GUI_VERIFICATION_RECEIPT_ENVELOPE_INTERFACE,
    GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA,
    INTERACTION_RECEIPT_INTERFACE,
    UI_CONSTRAINT_RECEIPT_INTERFACE,
    VERIFICATION_RECEIPT_INTERFACES,
    VISUAL_REGRESSION_RECEIPT_INTERFACE,
    GuiReceiptError,
    GuiReceiptIssueCode,
    GuiVerificationReceiptEnvelope,
    accessibility_receipt_identity,
    aggregate_verification_receipts,
    analysis_classification_for,
    authority_ceiling_for,
    bind_artifact_material,
    constraint_receipt_identity,
    create_verification_receipt_aggregator,
    decode_verification_envelope,
    envelope_identity,
    improvement_receipt_identity,
    interaction_receipt_identity,
    receipt_identity,
    rehash_nested_artifacts,
    rehash_receipt_identity,
    verify_envelope,
    verify_receipt_identity,
    visual_regression_receipt_identity,
)
from ipfs_datasets_py.logic.gui_optimizer.schema import (
    ACCESSIBILITY_RECEIPT_SCHEMA,
    GUI_IMPROVEMENT_RECEIPT_SCHEMA,
    INTERACTION_RECEIPT_SCHEMA,
    SCHEMA_VERSION_BY_INTERFACE,
    UI_CONSTRAINT_RECEIPT_SCHEMA,
    VISUAL_REGRESSION_RECEIPT_SCHEMA,
    AnalysisClassification,
    EvidenceLevel,
    GuiOptimizerDecodeError,
    ProposalDecision,
    VerificationStatus,
)

DIGESTS = tuple(f"sha256:{character * 64}" for character in "abcdef12345678")
GOLDEN_IMPROVEMENT_RECEIPT_ID = "receipt:improvement-1"


def _record(interface: str, **fields: Any) -> dict[str, Any]:
    nested = {
        "ViewportSpec@1": "gui-viewport-spec/v1",
        "VisualChangeRegion@1": "visual-change-region/v1",
        "UiInvalidationPlan@1": "ui-invalidation-plan/v1",
    }
    schema = dict(SCHEMA_VERSION_BY_INTERFACE) | nested
    return {**fields, "interface": interface, "schema_version": schema[interface]}


def _viewport() -> dict[str, Any]:
    return _record("ViewportSpec@1", width=1280, height=800, device_scale_factor=1)


def _visual_payload(**overrides: Any) -> dict[str, Any]:
    payload = _record(
        VISUAL_REGRESSION_RECEIPT_INTERFACE,
        receipt_id="receipt:visual-1",
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        scenario_id="scenario:keyboard-only",
        repository_revision="deadbeef",
        component_version_ids=["version:console-root"],
        viewport=_viewport(),
        screenshot_digest=DIGESTS[12],
        baseline_digest=DIGESTS[13],
        decision="pass",
        evidence_level="automated",
        pixel_diff_percent=0.25,
        structural_diff_percent=0.1,
        unexpected_layout_shift_count=0,
        missing_control_count=0,
        extra_control_count=0,
        screenshot_width=1280,
        screenshot_height=800,
        expected_change_regions=[
            _record(
                "VisualChangeRegion@1",
                region_id="region:label",
                x=0.25,
                y=0.25,
                width=0.25,
                height=0.25,
                evidence_reason="The label is the declared change target.",
            )
        ],
        forbidden_change_regions=[
            _record(
                "VisualChangeRegion@1",
                region_id="region:navigation",
                x=0.0,
                y=0.0,
                width=0.2,
                height=0.2,
                evidence_reason="Navigation is outside patch scope.",
            )
        ],
        max_unexplained_diff_percent=1.0,
        manual_review_threshold_percent=2.0,
        requires_human_review=False,
        color_scheme="light",
        locale="en-US",
        text_scale_percent=100,
        browser="chromium",
        browser_version="128.0.0",
        analysis_classification="exact",
        verification_status="verified",
    )
    payload.update(overrides)
    return payload


def _a11y_payload(**overrides: Any) -> dict[str, Any]:
    payload = _record(
        ACCESSIBILITY_RECEIPT_INTERFACE,
        receipt_id="receipt:a11y-1",
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        scenario_id="scenario:keyboard-only",
        repository_revision="deadbeef",
        automated_pass_count=12,
        violation_count=0,
        violation_ids=[],
        manual_check_ids=["manual:focus-order"],
        unsupported_criteria=["WCAG-1.3.5"],
        keyboard_result="satisfied",
        screen_reader_reviewed=False,
        evidence_level="automated",
        analysis_classification="exact",
        verification_status="verified",
    )
    payload.update(overrides)
    return payload


def _interaction_payload(**overrides: Any) -> dict[str, Any]:
    payload = _record(
        INTERACTION_RECEIPT_INTERFACE,
        receipt_id="receipt:interaction-1",
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        scenario_id="scenario:keyboard-only",
        repository_revision="deadbeef",
        step_ids=["step:focus-input", "step:activate-submit"],
        focus_sequence=["goal-input", "submit-button"],
        event_ids=["event:focus", "event:keyboard_activation"],
        action_invocation_ids=["invoke:dispatch"],
        confirmation_id="confirm:dispatch",
        recovery_ids=["recovery:return-ready"],
        unresolved_observation_ids=[],
        evidence_level="automated",
        analysis_classification="exact",
        verification_status="verified",
    )
    payload.update(overrides)
    return payload


def _constraint_payload(**overrides: Any) -> dict[str, Any]:
    payload = _record(
        UI_CONSTRAINT_RECEIPT_INTERFACE,
        receipt_id="receipt:constraint-1",
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        repository_revision="deadbeef",
        check_ids=["check:reachable", "check:confirmation", "check:manual"],
        statuses=["satisfied", "violated", "unsupported"],
        violated_check_ids=["check:confirmation"],
        unsupported_check_ids=["check:manual"],
        solver_id="solver:finite-graph",
        evidence_level="structural",
        analysis_classification="exact",
        verification_status="structurally_valid",
    )
    payload.update(overrides)
    return payload


def _plan_payload(**overrides: Any) -> dict[str, Any]:
    payload = _record(
        "UiInvalidationPlan@1",
        plan_id="invalidate:label-form",
        change_set_id="change:label-fix",
        reasons=["component_changed"],
        affected_component_ids=["comp:goal-form"],
        affected_scenario_ids=["scenario:keyboard-only"],
        affected_check_ids=["check:accessible-name"],
        confidence="exact",
        fallback_triggered=False,
        fallback_explanation="No uncertainty requires broad fallback.",
    )
    payload.update(overrides)
    return payload


def _visual(**overrides: Any) -> VisualRegressionReceipt:
    return VisualRegressionReceipt.from_dict(_visual_payload(**overrides))


def _a11y(**overrides: Any) -> AccessibilityReceipt:
    return AccessibilityReceipt.from_dict(_a11y_payload(**overrides))


def _interaction(**overrides: Any) -> InteractionReceipt:
    return InteractionReceipt.from_dict(_interaction_payload(**overrides))


def _constraint(**overrides: Any) -> UiConstraintReceipt:
    return UiConstraintReceipt.from_dict(_constraint_payload(**overrides))


def _plan(**overrides: Any) -> UiInvalidationPlan:
    return UiInvalidationPlan.from_dict(_plan_payload(**overrides))


def _accepted(**overrides: Any) -> GuiVerificationReceiptEnvelope:
    kwargs: dict[str, Any] = {
        "visual_receipts": [_visual()],
        "accessibility_receipts": [_a11y()],
        "interaction_receipts": [_interaction()],
        "constraint_receipts": [_constraint()],
        "decision": ProposalDecision.ACCEPT,
        "proposal_id": "proposal:label-form",
        "application_id": "app:agent-supervisor",
        "screen_id": "screen:agent-supervisor",
        "repository_revision": "deadbeef",
        "invalidation_plan": _plan(),
        "context_pack_id": "pack:label-form",
        "patch_digest": DIGESTS[13],
        "receipt_id": GOLDEN_IMPROVEMENT_RECEIPT_ID,
    }
    kwargs.update(overrides)
    return aggregate_verification_receipts(**kwargs)


def _rejected(**overrides: Any) -> GuiVerificationReceiptEnvelope:
    kwargs: dict[str, Any] = {
        "visual_receipts": [_visual()],
        "accessibility_receipts": [_a11y()],
        "interaction_receipts": [],
        "constraint_receipts": [_constraint()],
        "decision": ProposalDecision.REJECT,
        "proposal_id": "proposal:label-form",
        "application_id": "app:agent-supervisor",
        "screen_id": "screen:agent-supervisor",
        "repository_revision": "deadbeef",
        "rejection_reasons": [
            "missing_interaction_receipt",
            "invariants_violated",
        ],
        "receipt_id": "receipt:improvement-reject-1",
    }
    kwargs.update(overrides)
    return aggregate_verification_receipts(**kwargs)


# ---------------------------------------------------------------------------
# Inventory / interface surface
# ---------------------------------------------------------------------------


def test_verification_receipt_classes_are_the_four_declared_interfaces() -> None:
    assert VERIFICATION_RECEIPT_INTERFACES == (
        VISUAL_REGRESSION_RECEIPT_INTERFACE,
        ACCESSIBILITY_RECEIPT_INTERFACE,
        INTERACTION_RECEIPT_INTERFACE,
        UI_CONSTRAINT_RECEIPT_INTERFACE,
    )
    assert GUI_IMPROVEMENT_RECEIPT_INTERFACE not in VERIFICATION_RECEIPT_INTERFACES


# ---------------------------------------------------------------------------
# Accepted completeness
# ---------------------------------------------------------------------------


def test_accepted_receipt_contains_all_four_classes_plus_context_evidence() -> None:
    envelope = _accepted()
    receipt = envelope.receipt
    assert receipt.decision is ProposalDecision.ACCEPT
    assert receipt.visual_receipt_ids == ("receipt:visual-1",)
    assert receipt.accessibility_receipt_ids == ("receipt:a11y-1",)
    assert receipt.interaction_receipt_ids == ("receipt:interaction-1",)
    assert receipt.constraint_receipt_ids == ("receipt:constraint-1",)
    assert receipt.invalidation_plan_id == "invalidate:label-form"
    assert receipt.context_pack_id == "pack:label-form"
    assert receipt.patch_digest == DIGESTS[13]
    assert receipt.rejection_reasons == ()
    assert envelope.invalidation_plan is not None
    assert envelope.invalidation_plan.plan_id == "invalidate:label-form"
    assert envelope.scenario_inputs[0]["scenario_id"] == "scenario:keyboard-only"
    assert envelope.scenario_inputs[0]["browser"] == "chromium"
    assert envelope.before_artifact_digests == (DIGESTS[13],)
    assert envelope.after_artifact_digests == (DIGESTS[12],)
    assert "check:reachable" in envelope.checks["check_ids"]
    assert envelope.metrics["automated_pass_count"] == 12
    assert envelope.versions["component_version_ids"] == ["version:console-root"]
    assert envelope.patch_scope["affected_component_ids"] == ["comp:goal-form"]
    assert envelope.interface == GUI_VERIFICATION_RECEIPT_ENVELOPE_INTERFACE
    assert envelope.schema_version == GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA


@pytest.mark.parametrize(
    "missing,code",
    [
        ("visual_receipts", GuiReceiptIssueCode.MISSING_VISUAL_RECEIPT),
        ("accessibility_receipts", GuiReceiptIssueCode.MISSING_ACCESSIBILITY_RECEIPT),
        ("interaction_receipts", GuiReceiptIssueCode.MISSING_INTERACTION_RECEIPT),
        ("constraint_receipts", GuiReceiptIssueCode.MISSING_CONSTRAINT_RECEIPT),
        ("invalidation_plan", GuiReceiptIssueCode.MISSING_INVALIDATION_PLAN),
        ("context_pack_id", GuiReceiptIssueCode.MISSING_CONTEXT_PACK),
        ("patch_digest", GuiReceiptIssueCode.MISSING_PATCH_DIGEST),
    ],
)
def test_accepted_receipt_rejects_missing_required_evidence(
    missing: str, code: GuiReceiptIssueCode
) -> None:
    overrides: dict[str, Any]
    if missing.endswith("_receipts"):
        overrides = {missing: []}
    elif missing == "invalidation_plan":
        overrides = {"invalidation_plan": None}
    elif missing == "context_pack_id":
        overrides = {"context_pack_id": ""}
    else:
        overrides = {"patch_digest": ""}
    with pytest.raises(GuiReceiptError, match=code.value):
        _accepted(**overrides)


def test_accepted_receipt_rejects_rejection_reasons() -> None:
    with pytest.raises(GuiReceiptError, match="rejection reasons"):
        _accepted(rejection_reasons=["should-not-be-present"])


# ---------------------------------------------------------------------------
# Rejected receipts preserve reasons
# ---------------------------------------------------------------------------


def test_rejected_receipt_preserves_reasons_and_partial_evidence() -> None:
    envelope = _rejected()
    assert envelope.decision is ProposalDecision.REJECT
    assert envelope.receipt.rejection_reasons == (
        "missing_interaction_receipt",
        "invariants_violated",
    )
    assert envelope.rejection_reasons == envelope.receipt.rejection_reasons
    assert envelope.receipt.interaction_receipt_ids == ()
    assert envelope.receipt.visual_receipt_ids == ("receipt:visual-1",)
    restored = GuiImprovementReceipt.from_dict(envelope.receipt.to_dict())
    assert restored.rejection_reasons == envelope.receipt.rejection_reasons


def test_rejected_receipt_requires_nonempty_reasons() -> None:
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.MISSING_REJECTION_REASONS.value
    ):
        _rejected(rejection_reasons=[])


# ---------------------------------------------------------------------------
# Deterministic identity
# ---------------------------------------------------------------------------


def test_deterministic_inputs_produce_deterministic_receipt_identity() -> None:
    first = _accepted()
    second = _accepted()
    assert first.identity.digest == second.identity.digest
    assert first.identity.cid == second.identity.cid
    assert first.receipt_identity == second.receipt_identity
    assert first.to_dict() == second.to_dict()
    third = aggregate_verification_receipts(
        visual_receipts=[_visual_payload()],
        accessibility_receipts=[_a11y_payload()],
        interaction_receipts=[_interaction_payload()],
        constraint_receipts=[_constraint_payload()],
        decision="accept",
        proposal_id="proposal:label-form",
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        repository_revision="deadbeef",
        invalidation_plan=_plan_payload(),
        context_pack_id="pack:label-form",
        patch_digest=DIGESTS[13],
        receipt_id=GOLDEN_IMPROVEMENT_RECEIPT_ID,
    )
    assert third.identity.digest == first.identity.digest


def test_input_order_does_not_change_identity() -> None:
    visual_a = _visual(receipt_id="receipt:visual-a")
    visual_b = _visual(receipt_id="receipt:visual-b")
    left = _accepted(visual_receipts=[visual_a, visual_b])
    right = _accepted(visual_receipts=[visual_b, visual_a])
    assert left.identity.digest == right.identity.digest
    assert left.receipt.visual_receipt_ids == (
        "receipt:visual-a",
        "receipt:visual-b",
    )


def test_meaningful_payload_change_changes_identity() -> None:
    baseline = _accepted()
    changed = _accepted(
        accessibility_receipts=[_a11y(automated_pass_count=13)],
    )
    assert changed.identity.digest != baseline.identity.digest
    assert (
        accessibility_receipt_identity(changed.accessibility_receipts[0]).digest
        != accessibility_receipt_identity(baseline.accessibility_receipts[0]).digest
    )


# ---------------------------------------------------------------------------
# Canonical receipt vectors and domain separation
# ---------------------------------------------------------------------------


def test_receipt_identities_are_domain_separated_and_rehashable() -> None:
    visual = _visual()
    a11y = _a11y()
    interaction = _interaction()
    constraint = _constraint()
    visual_id = visual_regression_receipt_identity(visual)
    a11y_id = accessibility_receipt_identity(a11y)
    interaction_id = interaction_receipt_identity(interaction)
    constraint_id = constraint_receipt_identity(constraint)
    assert visual_id.domain == DOMAIN_VISUAL_REGRESSION_RECEIPT
    assert a11y_id.domain == DOMAIN_ACCESSIBILITY_RECEIPT
    assert interaction_id.domain == DOMAIN_INTERACTION_RECEIPT
    assert constraint_id.domain == DOMAIN_CONSTRAINT_RECEIPT
    assert visual_id.schema_version == VISUAL_REGRESSION_RECEIPT_SCHEMA
    assert a11y_id.schema_version == ACCESSIBILITY_RECEIPT_SCHEMA
    assert interaction_id.schema_version == INTERACTION_RECEIPT_SCHEMA
    assert constraint_id.schema_version == UI_CONSTRAINT_RECEIPT_SCHEMA
    assert len({visual_id.cid, a11y_id.cid, interaction_id.cid, constraint_id.cid}) == 4
    for identity, receipt in (
        (visual_id, visual),
        (a11y_id, a11y),
        (interaction_id, interaction),
        (constraint_id, constraint),
    ):
        assert rehash_receipt_identity(identity).digest == identity.digest
        assert verify_receipt_identity(identity, receipt).cid == identity.cid
        assert receipt_identity(receipt).digest == identity.digest
        assert receipt_identity(receipt.to_dict()).digest == identity.digest


def test_improvement_receipt_identity_uses_improvement_domain() -> None:
    envelope = _accepted()
    identity = improvement_receipt_identity(envelope.receipt)
    assert identity.domain == DOMAIN_IMPROVEMENT_RECEIPT
    assert identity.schema_version == GUI_IMPROVEMENT_RECEIPT_SCHEMA
    assert envelope.receipt_identity["digest"] == identity.digest
    assert envelope.receipt_identity["cid"] == identity.cid


def test_envelope_identity_excludes_own_cid_and_is_locked() -> None:
    envelope = _accepted()
    identity = envelope.identity
    assert identity.domain == DOMAIN_VERIFICATION_ENVELOPE
    assert identity.schema_version == GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA
    payload = envelope.identity_payload()
    assert "envelope_cid" not in payload
    assert "envelope_digest" not in payload
    wire = envelope.to_dict()
    assert wire["envelope_digest"] == identity.digest
    assert wire["envelope_cid"] == identity.cid
    assert envelope_identity(wire).digest == identity.digest
    # Lock the exact accepted vector once computed by the closed profile.
    assert identity.digest.startswith("sha256:")
    assert identity.cid.startswith("bafkrei")
    assert len(identity.hexdigest) == 64


def test_canonical_accepted_vector_is_stable_across_rehash() -> None:
    envelope = _accepted()
    first = envelope.identity
    second = GuiVerificationReceiptEnvelope.from_dict(envelope.to_dict()).identity
    third = envelope.rehash()
    assert first.digest == second.digest == third.digest
    assert first.cid == second.cid == third.cid
    assert first.canonical_bytes == second.canonical_bytes


# ---------------------------------------------------------------------------
# Missing / unknown field rejection
# ---------------------------------------------------------------------------


def test_envelope_rejects_unknown_fields() -> None:
    payload = _accepted().to_dict()
    payload["extra_note"] = "not-in-schema"
    with pytest.raises(GuiOptimizerDecodeError, match="unknown"):
        decode_verification_envelope(payload)


def test_envelope_rejects_missing_required_fields() -> None:
    payload = _accepted().to_dict()
    del payload["receipt"]
    with pytest.raises(GuiReceiptError, match=GuiReceiptIssueCode.MISSING_FIELD.value):
        decode_verification_envelope(payload)


def test_nested_receipt_unknown_field_is_rejected() -> None:
    payload = _visual_payload()
    payload["surprise"] = True
    with pytest.raises(GuiOptimizerDecodeError, match="unknown"):
        aggregate_verification_receipts(
            visual_receipts=[payload],
            accessibility_receipts=[_a11y()],
            interaction_receipts=[_interaction()],
            constraint_receipts=[_constraint()],
            decision="accept",
            proposal_id="proposal:label-form",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            repository_revision="deadbeef",
            invalidation_plan=_plan(),
            context_pack_id="pack:label-form",
            patch_digest=DIGESTS[13],
        )


def test_nested_receipt_missing_identifier_is_rejected() -> None:
    payload = _a11y_payload()
    payload["receipt_id"] = ""
    with pytest.raises(GuiOptimizerDecodeError):
        AccessibilityReceipt.from_dict(payload)


# ---------------------------------------------------------------------------
# Nested artifact rehash
# ---------------------------------------------------------------------------


def test_nested_artifact_and_receipt_identities_rehash() -> None:
    patch_bytes = b"diff --git a/label.js b/label.js\n+"
    screenshot = {"role": "screenshot", "bytes": "after"}
    baseline = {"role": "baseline", "bytes": "before"}
    screenshot_digest = artifact_digest(screenshot, domain=DOMAIN_SCREENSHOT).digest
    baseline_digest = artifact_digest(baseline, domain=DOMAIN_SCREENSHOT).digest
    digest = sha256_digest(patch_bytes)
    envelope = _accepted(
        visual_receipts=[
            _visual(
                screenshot_digest=screenshot_digest,
                baseline_digest=baseline_digest,
            )
        ],
        patch_digest=digest,
        patch_material=patch_bytes,
    )
    assert envelope.patch_digest == digest
    rehashed = rehash_nested_artifacts(
        envelope,
        artifacts={
            digest: patch_bytes,
            screenshot_digest: screenshot,
            baseline_digest: baseline,
        },
    )
    assert rehashed.identity.digest == envelope.identity.digest
    verify_envelope(envelope, artifacts={digest: patch_bytes})


def test_artifact_rehash_rejects_mismatched_bytes() -> None:
    patch_bytes = b"declared-patch"
    digest = sha256_digest(patch_bytes)
    envelope = _accepted(patch_digest=digest, patch_material=patch_bytes)
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.ARTIFACT_REHASH_MISMATCH.value
    ):
        rehash_nested_artifacts(envelope, artifacts={digest: b"other-bytes"})


def test_artifact_rehash_rejects_unbound_digest() -> None:
    envelope = _accepted()
    foreign = sha256_digest(b"unbound")
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.ARTIFACT_REHASH_MISMATCH.value
    ):
        rehash_nested_artifacts(envelope, artifacts={foreign: b"unbound"})


def test_bind_artifact_material_matches_claimed_digest() -> None:
    material = {"path": "swissknife/web/js/apps/agent-supervisor.js", "bytes": "x"}
    digest = artifact_digest(material, domain=DOMAIN_SCREENSHOT).digest
    assert bind_artifact_material(
        material, domain=DOMAIN_SCREENSHOT, claimed_digest=digest
    ) == digest
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.ARTIFACT_REHASH_MISMATCH.value
    ):
        bind_artifact_material(
            material, domain=DOMAIN_PATCH, claimed_digest=DIGESTS[0]
        )


def test_tampered_nested_identity_fails_rehash() -> None:
    envelope = _accepted()
    tampered = dict(envelope.visual_identities[0])
    tampered["digest"] = DIGESTS[0]
    object.__setattr__(envelope, "visual_identities", (tampered,))
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.IDENTITY_MISMATCH.value
    ):
        rehash_nested_artifacts(envelope)


# ---------------------------------------------------------------------------
# Authority-label tests
# ---------------------------------------------------------------------------


def test_authority_ceiling_is_the_weakest_declared_label() -> None:
    assert authority_ceiling_for(
        [EvidenceLevel.AUTOMATED, EvidenceLevel.STRUCTURAL]
    ) is EvidenceLevel.AUTOMATED
    assert authority_ceiling_for(
        ["heuristic", "automated", "integrity"]
    ) is EvidenceLevel.HEURISTIC
    assert authority_ceiling_for(
        ["simulated", "human_reviewed"]
    ) is EvidenceLevel.SIMULATED
    assert analysis_classification_for(
        ["exact", "heuristic", "conservative"]
    ) is AnalysisClassification.HEURISTIC


def test_envelope_preserves_declared_authority_labels() -> None:
    envelope = _accepted(
        visual_receipts=[
            _visual(evidence_level="heuristic", analysis_classification="heuristic")
        ],
        constraint_receipts=[_constraint(evidence_level="structural")],
    )
    assert envelope.evidence_levels["visual"] == ["heuristic"]
    assert envelope.evidence_levels["constraint"] == ["structural"]
    assert envelope.evidence_levels["accessibility"] == ["automated"]
    assert envelope.authority_ceiling is EvidenceLevel.HEURISTIC
    assert envelope.analysis_classification is AnalysisClassification.HEURISTIC
    assert envelope.visual_receipts[0].evidence_level is EvidenceLevel.HEURISTIC
    assert (
        envelope.constraint_receipts[0].verification_status
        is VerificationStatus.STRUCTURALLY_VALID
    )
    assert envelope.receipt.verification_status is VerificationStatus.VERIFIED


def test_cannot_elevate_authority_ceiling_beyond_constituents() -> None:
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.AUTHORITY_ELEVATION.value
    ):
        _accepted(authority_ceiling=EvidenceLevel.INTEGRITY)
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.AUTHORITY_ELEVATION.value
    ):
        _accepted(
            visual_receipts=[_visual(analysis_classification="heuristic")],
            analysis_classification=AnalysisClassification.EXACT,
        )


def test_simulated_visual_is_not_rewritten_as_automated() -> None:
    envelope = _accepted(
        visual_receipts=[
            _visual(
                evidence_level="simulated",
                verification_status="simulated",
                analysis_classification="heuristic",
            )
        ]
    )
    assert envelope.visual_receipts[0].evidence_level is EvidenceLevel.SIMULATED
    assert (
        envelope.visual_receipts[0].verification_status
        is VerificationStatus.SIMULATED
    )
    assert envelope.authority_ceiling is EvidenceLevel.SIMULATED
    assert envelope.receipt.verification_status is VerificationStatus.VERIFIED


def test_simulated_critical_receipt_blocks_accept() -> None:
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.CRITICAL_EVIDENCE_BLOCKED.value
    ):
        _accepted(
            accessibility_receipts=[
                _a11y(
                    evidence_level="simulated",
                    verification_status="simulated",
                )
            ]
        )


def test_weaker_requested_ceiling_is_allowed() -> None:
    envelope = _accepted(authority_ceiling=EvidenceLevel.HEURISTIC)
    assert envelope.authority_ceiling is EvidenceLevel.HEURISTIC


# ---------------------------------------------------------------------------
# Cross-binding and decode
# ---------------------------------------------------------------------------


def test_revision_and_application_mismatches_fail_closed() -> None:
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.REVISION_MISMATCH.value
    ):
        _accepted(
            accessibility_receipts=[_a11y(repository_revision="cafebabe")],
        )
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.APPLICATION_MISMATCH.value
    ):
        _accepted(
            interaction_receipts=[_interaction(application_id="app:other")],
        )
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.SCREEN_MISMATCH.value
    ):
        _accepted(constraint_receipts=[_constraint(screen_id="screen:other")])


def test_duplicate_receipt_ids_fail_closed() -> None:
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.DUPLICATE_RECEIPT_ID.value
    ):
        _accepted(visual_receipts=[_visual(), _visual()])


def test_envelope_round_trip_and_aggregator_facade() -> None:
    aggregator = create_verification_receipt_aggregator()
    assert aggregator.INTERFACE == GUI_VERIFICATION_RECEIPT_AGGREGATOR_INTERFACE
    envelope = aggregator.aggregate(
        visual_receipts=[_visual()],
        accessibility_receipts=[_a11y()],
        interaction_receipts=[_interaction()],
        constraint_receipts=[_constraint()],
        decision="accept",
        proposal_id="proposal:label-form",
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        repository_revision="deadbeef",
        invalidation_plan=_plan(),
        context_pack_id="pack:label-form",
        patch_digest=DIGESTS[13],
        receipt_id=GOLDEN_IMPROVEMENT_RECEIPT_ID,
    )
    restored = aggregator.decode(envelope.to_dict())
    assert restored.to_dict() == envelope.to_dict()
    assert aggregator.identity_for(
        visual_receipts=[_visual()],
        accessibility_receipts=[_a11y()],
        interaction_receipts=[_interaction()],
        constraint_receipts=[_constraint()],
        decision="accept",
        proposal_id="proposal:label-form",
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        repository_revision="deadbeef",
        invalidation_plan=_plan(),
        context_pack_id="pack:label-form",
        patch_digest=DIGESTS[13],
        receipt_id=GOLDEN_IMPROVEMENT_RECEIPT_ID,
    ).digest == envelope.identity.digest
    aggregator.verify(restored)


def test_claimed_envelope_digest_mismatch_is_rejected() -> None:
    payload = _accepted().to_dict()
    payload["envelope_digest"] = DIGESTS[0]
    with pytest.raises(
        GuiReceiptError, match=GuiReceiptIssueCode.IDENTITY_MISMATCH.value
    ):
        decode_verification_envelope(payload)


def test_human_review_allows_partial_evidence() -> None:
    envelope = aggregate_verification_receipts(
        visual_receipts=[_visual()],
        accessibility_receipts=[],
        interaction_receipts=[],
        constraint_receipts=[],
        decision=ProposalDecision.HUMAN_REVIEW,
        proposal_id="proposal:label-form",
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        repository_revision="deadbeef",
        receipt_id="receipt:improvement-review-1",
    )
    assert envelope.decision is ProposalDecision.HUMAN_REVIEW
    assert envelope.receipt.accessibility_receipt_ids == ()
    assert envelope.verification_status is VerificationStatus.UNVERIFIED


def test_package_avoids_excluded_imports() -> None:
    path = (
        Path(__file__).resolve().parents[4]
        / "ipfs_datasets_py"
        / "logic"
        / "gui_optimizer"
        / "receipts.py"
    )
    excluded = (
        "semantic_index",
        "semantic_capsule",
        "proof_cache",
        "proof_corpus",
        "model_routing",
        "ui_ux_ir",
        "router_deps",
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not any(part in name for part in excluded), (path, name)
