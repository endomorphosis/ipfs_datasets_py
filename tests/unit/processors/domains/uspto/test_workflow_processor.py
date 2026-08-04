"""Unit tests for pre-submission workflow and mandatory human gate (PATLAW-052).

Acceptance focus:
  - Workflow cannot sign/pay/file or mark itself submitted
  - Changed inputs invalidate review
  - Final filing remains external
  - Acknowledgement/payment receipts are imported as new evidence, never fabricated
"""

from __future__ import annotations

import itertools
from typing import Any, Iterator

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.workflow_processor import (
    FORBIDDEN_WORKFLOW_ACTIONS,
    OUTPUT_KIND_HUMAN_REVIEW_RECEIPT,
    OUTPUT_KIND_POST_FILING_EVIDENCE,
    OUTPUT_KIND_PREFLIGHT_RESULT,
    OUTPUT_KIND_REVIEWED_PACKAGE_MANIFEST,
    WORKFLOW_DISCLAIMER,
    WORKFLOW_SCHEMA_VERSION,
    EvidenceSourceChannel,
    FabricatedEvidenceError,
    ForbiddenWorkflowActionError,
    HumanReviewReceipt,
    ImportedPostFilingEvidence,
    ItemResolution,
    PostFilingEvidenceKind,
    PreflightDisposition,
    PreflightGateKind,
    PreflightNotReadyError,
    PreflightPackageInput,
    PreflightPhase,
    PreflightResult,
    ResolutionDisposition,
    ReviewInvalidatedError,
    ReviewedPackageManifest,
    WorkflowProcessor,
    WorkflowProcessorError,
    WorkflowReasonCode,
    accept_all_open_gates,
    assert_action_allowed,
    build_resolution,
    is_forbidden_action,
    package_inputs_match,
    run_package_preflight,
    sha256_hex,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BUNDLE_DIGEST = sha256_hex(b"analysis-bundle-v1")
_GAP_DIGEST = sha256_hex(b"gap-report-v1")
_BUNDLE_DIGEST_V2 = sha256_hex(b"analysis-bundle-v2")
_GAP_DIGEST_V2 = sha256_hex(b"gap-report-v2")
_ARTIFACT_SHA = sha256_hex(b"user-ack-receipt-bytes")

_seq: Iterator[int] = itertools.count(1)


def _reset() -> None:
    global _seq
    _seq = itertools.count(1)


def _id_factory() -> str:
    return f"{next(_seq):04d}"


def _processor() -> WorkflowProcessor:
    _reset()
    return WorkflowProcessor(id_factory=_id_factory)


def _package_input(**overrides: Any) -> PreflightPackageInput:
    base: dict[str, Any] = {
        "matter_id": "matter:unit-1",
        "source_bundle_id": "bundle:unit-1",
        "source_bundle_digest": _BUNDLE_DIGEST,
        "gap_report_id": "gap:unit-1",
        "gap_report_digest": _GAP_DIGEST,
        "analysis_id": "analysis:unit-1",
        "classification": DisclosureClassification.PUBLIC_USER,
        "open_unknown_ids": ("unk:1",),
        "open_gap_ids": ("req:112b",),
        "open_candidate_date_ids": ("date:response-1",),
        "open_reviewer_action_ids": ("action:confirm-scope",),
        "mandatory_review_remaining": True,
        "gap_report_label": "review_required",
        "labels": {"channel": "unit"},
    }
    base.update(overrides)
    return PreflightPackageInput(**base)


# ---------------------------------------------------------------------------
# Forbidden actions
# ---------------------------------------------------------------------------


class TestForbiddenActions:
    def test_forbidden_set_includes_sign_pay_file_submit_fabricate(self) -> None:
        for action in (
            "sign",
            "pay",
            "file",
            "submit",
            "mark_submitted",
            "fabricate_acknowledgement",
            "fabricate_payment_receipt",
            "perform_final_submission",
        ):
            assert action in FORBIDDEN_WORKFLOW_ACTIONS
            assert is_forbidden_action(action)

    def test_assert_action_allowed_raises(self) -> None:
        with pytest.raises(ForbiddenWorkflowActionError) as exc:
            assert_action_allowed("mark_submitted")
        assert exc.value.code == "forbidden_workflow_action"
        assert exc.value.action == "mark_submitted"

    def test_processor_methods_raise(self) -> None:
        wp = _processor()
        for method_name in (
            "sign",
            "pay",
            "file",
            "submit",
            "mark_submitted",
            "fabricate_acknowledgement",
            "fabricate_payment_receipt",
        ):
            with pytest.raises(ForbiddenWorkflowActionError):
                getattr(wp, method_name)()

    def test_perform_action_blocks_forbidden(self) -> None:
        wp = _processor()
        with pytest.raises(ForbiddenWorkflowActionError):
            wp.perform_action("pay_fee")

    def test_preflight_result_never_submitted_or_capable(self) -> None:
        pf = _processor().run_preflight(_package_input())
        assert pf.is_submitted is False
        assert pf.can_sign is False
        assert pf.can_pay is False
        assert pf.can_file is False
        assert pf.filing_is_external is True
        # Even if caller tries to set True via from_dict, locks remain.
        data = pf.to_dict()
        data["is_submitted"] = True
        data["can_sign"] = True
        data["can_pay"] = True
        data["can_file"] = True
        data.pop("content_digest", None)
        revived = PreflightResult.from_dict(data)
        assert revived.is_submitted is False
        assert revived.can_sign is False
        assert revived.can_pay is False
        assert revived.can_file is False


# ---------------------------------------------------------------------------
# Preflight gates
# ---------------------------------------------------------------------------


class TestRunPreflight:
    def test_run_preflight_opens_gates_for_unknowns_gaps_dates_actions(self) -> None:
        wp = _processor()
        pf = wp.run_preflight(_package_input())
        assert pf.schema_version == WORKFLOW_SCHEMA_VERSION
        assert pf.output_kind == OUTPUT_KIND_PREFLIGHT_RESULT
        assert pf.phase is PreflightPhase.PREFLIGHT_OPEN
        assert pf.disposition is PreflightDisposition.REVIEW_REQUIRED
        kinds = {g.kind for g in pf.gate_items}
        assert PreflightGateKind.UNKNOWN in kinds
        assert PreflightGateKind.GAP in kinds
        assert PreflightGateKind.CANDIDATE_DATE in kinds
        assert PreflightGateKind.REVIEWER_ACTION in kinds
        assert PreflightGateKind.MANDATORY_PACKAGE_ACCEPTANCE in kinds
        assert pf.open_gate_ids
        assert not pf.resolved_gate_ids
        assert WorkflowReasonCode.EXTERNAL_FILING_ONLY.value in pf.reason_codes
        assert WorkflowReasonCode.NEVER_MARKED_SUBMITTED.value in pf.reason_codes

    def test_package_digest_stable_for_same_inputs(self) -> None:
        a = _package_input()
        b = _package_input()
        assert a.package_digest() == b.package_digest()
        pf1 = run_package_preflight(a, id_factory=_id_factory)
        _reset()
        pf2 = run_package_preflight(b, id_factory=_id_factory)
        assert pf1.package_digest == pf2.package_digest
        assert package_inputs_match(pf1, a)

    def test_package_digest_changes_when_bundle_digest_changes(self) -> None:
        a = _package_input()
        b = _package_input(source_bundle_digest=_BUNDLE_DIGEST_V2)
        assert a.package_digest() != b.package_digest()

    def test_prior_art_incomplete_adds_coverage_gate(self) -> None:
        pf = _processor().run_preflight(
            _package_input(
                prior_art_checklist_id="checklist:pa:1",
                prior_art_checklist_digest=sha256_hex(b"pa-checklist"),
                prior_art_search_complete=False,
                prior_art_blocking_reason_codes=("missing_human_coverage_acknowledgment",),
            )
        )
        kinds = {g.kind for g in pf.gate_items}
        assert PreflightGateKind.PRIOR_ART_COVERAGE in kinds
        assert WorkflowReasonCode.PRIOR_ART_READINESS_BLOCK.value in pf.reason_codes

    def test_quarantine_blocks(self) -> None:
        # contracts.requires_quarantine is fail-closed for UNKNOWN only.
        pf = _processor().run_preflight(
            _package_input(classification=DisclosureClassification.UNKNOWN)
        )
        assert pf.disposition is PreflightDisposition.BLOCKED
        assert any(g.kind is PreflightGateKind.QUARANTINE for g in pf.gate_items)
        assert pf.review_state is ReviewState.REQUIRED

    def test_round_trip_preflight_result(self) -> None:
        pf = _processor().run_preflight(_package_input())
        revived = PreflightResult.from_dict(pf.to_dict())
        assert revived.to_dict() == pf.to_dict()
        assert revived.content_digest == pf.content_digest

    def test_public_projection_has_no_capabilities(self) -> None:
        pf = _processor().run_preflight(_package_input())
        pub = pf.public_projection()
        assert pub["is_submitted"] is False
        assert pub["can_sign"] is False
        assert pub["filing_is_external"] is True


# ---------------------------------------------------------------------------
# Human review binding
# ---------------------------------------------------------------------------


class TestHumanReviewGate:
    def test_cannot_bind_with_open_gates(self) -> None:
        wp = _processor()
        pf = wp.run_preflight(_package_input())
        partial = accept_all_open_gates(
            pf,
            reviewer_name="Pat Attorney",
            resolved_at_utc="2024-07-01T12:00:00Z",
        )[:-1]  # leave one open
        with pytest.raises(PreflightNotReadyError):
            wp.bind_human_review(
                pf,
                reviewer_name="Pat Attorney",
                reviewed_at_utc="2024-07-01T12:00:00Z",
                resolutions=partial,
                statement="partial acceptance",
            )

    def test_bind_requires_matching_package_digest_on_resolutions(self) -> None:
        wp = _processor()
        pf = wp.run_preflight(_package_input())
        bad = [
            ItemResolution(
                gate_id=gid,
                disposition=ResolutionDisposition.ACCEPTED,
                reviewer_name="Pat Attorney",
                resolved_at_utc="2024-07-01T12:00:00Z",
                statement="ok",
                bound_package_digest=_BUNDLE_DIGEST,  # wrong — not package digest
            )
            for gid in pf.open_gate_ids
        ]
        with pytest.raises(ReviewInvalidatedError):
            wp.bind_human_review(
                pf,
                reviewer_name="Pat Attorney",
                reviewed_at_utc="2024-07-01T12:00:00Z",
                resolutions=bad,
                statement="bad digest binding",
            )

    def test_bind_human_review_success(self) -> None:
        wp = _processor()
        pf = wp.run_preflight(_package_input())
        resolutions = accept_all_open_gates(
            pf,
            reviewer_name="Pat Attorney",
            resolved_at_utc="2024-07-01T12:00:00Z",
            statement="accepted after human review of unknowns/gaps/dates",
        )
        bound, receipt = wp.bind_human_review(
            pf,
            reviewer_name="Pat Attorney",
            reviewed_at_utc="2024-07-01T12:00:00Z",
            resolutions=resolutions,
            statement="I reviewed the preflight package and accept remaining risks.",
        )
        assert bound.phase is PreflightPhase.REVIEW_BOUND
        assert bound.disposition is PreflightDisposition.REVIEW_COMPLETE
        assert bound.review_state is ReviewState.COMPLETE
        assert not bound.open_gate_ids
        assert receipt.output_kind == OUTPUT_KIND_HUMAN_REVIEW_RECEIPT
        assert receipt.package_digest == pf.package_digest
        assert receipt.binds_package_digest(pf.package_digest)
        assert receipt.reviewer_name == "Pat Attorney"
        # Receipt round-trip
        revived = HumanReviewReceipt.from_dict(receipt.to_dict())
        assert revived.content_digest == receipt.content_digest

    def test_build_resolution_helper(self) -> None:
        r = build_resolution(
            "gate:package:acceptance",
            disposition=ResolutionDisposition.ACCEPTED,
            reviewer_name="Reviewer",
            resolved_at_utc="2024-07-01T12:00:00Z",
            statement="accepted",
            package_digest=_BUNDLE_DIGEST,
        )
        assert r.gate_id == "gate:package:acceptance"
        assert r.clears_gate is True

    def test_rejected_disposition_does_not_clear_gate(self) -> None:
        wp = _processor()
        pf = wp.run_preflight(_package_input())
        gate_id = pf.open_gate_ids[0]
        rejected = ItemResolution(
            gate_id=gate_id,
            disposition=ResolutionDisposition.REJECTED,
            reviewer_name="Pat Attorney",
            resolved_at_utc="2024-07-01T12:00:00Z",
            statement="not acceptable",
            bound_package_digest=pf.package_digest,
        )
        updated = wp.apply_resolutions(pf, (rejected,))
        assert gate_id in updated.open_gate_ids
        assert gate_id not in updated.resolved_gate_ids


# ---------------------------------------------------------------------------
# Export + external filing
# ---------------------------------------------------------------------------


class TestExportReviewedPackage:
    def _bound(
        self, wp: WorkflowProcessor
    ) -> tuple[PreflightResult, HumanReviewReceipt]:
        pf = wp.run_preflight(_package_input())
        resolutions = accept_all_open_gates(
            pf,
            reviewer_name="Pat Attorney",
            resolved_at_utc="2024-07-01T12:00:00Z",
        )
        return wp.bind_human_review(
            pf,
            reviewer_name="Pat Attorney",
            reviewed_at_utc="2024-07-01T12:00:00Z",
            resolutions=resolutions,
            statement="review complete",
        )

    def test_export_only_after_review_bound(self) -> None:
        wp = _processor()
        pf = wp.run_preflight(_package_input())
        # Fake receipt without binding
        with pytest.raises(PreflightNotReadyError):
            fake = HumanReviewReceipt(
                schema_version=WORKFLOW_SCHEMA_VERSION,
                receipt_id="review:x",
                preflight_id=pf.preflight_id,
                matter_id=pf.matter_id,
                reviewer_name="Pat Attorney",
                reviewed_at_utc="2024-07-01T12:00:00Z",
                package_digest=pf.package_digest,
                source_bundle_digest=pf.source_bundle_digest,
                gap_report_digest=pf.gap_report_digest,
                resolutions=(),
                statement="premature",
            )
            wp.export_reviewed_package(
                pf,
                fake,
                exported_at_utc="2024-07-01T13:00:00Z",
            )

    def test_export_produces_external_handoff_manifest(self) -> None:
        wp = _processor()
        bound, receipt = self._bound(wp)
        exported, manifest = wp.export_reviewed_package(
            bound,
            receipt,
            exported_at_utc="2024-07-01T13:00:00Z",
        )
        assert exported.phase is PreflightPhase.EXTERNAL_FILING_HANDOFF
        assert exported.disposition is PreflightDisposition.EXPORTABLE
        assert exported.is_submitted is False
        assert exported.filing_is_external is True
        assert manifest.output_kind == OUTPUT_KIND_REVIEWED_PACKAGE_MANIFEST
        assert manifest.is_submitted is False
        assert manifest.filing_is_external is True
        assert manifest.filing_authorization is False
        assert manifest.can_sign is False
        assert manifest.can_pay is False
        assert manifest.can_file is False
        assert manifest.review_receipt_id == receipt.receipt_id
        assert manifest.package_digest == bound.package_digest
        revived = ReviewedPackageManifest.from_dict(manifest.to_dict())
        assert revived.content_digest == manifest.content_digest
        # from_dict cannot elevate submission flags
        data = manifest.to_dict()
        data["is_submitted"] = True
        data["filing_authorization"] = True
        data["can_file"] = True
        data.pop("content_digest", None)
        locked = ReviewedPackageManifest.from_dict(data)
        assert locked.is_submitted is False
        assert locked.filing_authorization is False
        assert locked.can_file is False


# ---------------------------------------------------------------------------
# Input change invalidates review
# ---------------------------------------------------------------------------


class TestInputChangeInvalidation:
    def test_changed_bundle_digest_invalidates(self) -> None:
        wp = _processor()
        original = _package_input()
        pf = wp.run_preflight(original)
        resolutions = accept_all_open_gates(
            pf,
            reviewer_name="Pat Attorney",
            resolved_at_utc="2024-07-01T12:00:00Z",
        )
        bound, receipt = wp.bind_human_review(
            pf,
            reviewer_name="Pat Attorney",
            reviewed_at_utc="2024-07-01T12:00:00Z",
            resolutions=resolutions,
            statement="review complete",
        )
        assert package_inputs_match(bound, original)

        changed = _package_input(source_bundle_digest=_BUNDLE_DIGEST_V2)
        assert not package_inputs_match(bound, changed)
        invalidated = wp.check_inputs_still_valid(bound, changed, receipt=receipt)
        assert invalidated.phase is PreflightPhase.INVALIDATED
        assert invalidated.disposition is PreflightDisposition.INVALIDATED
        assert WorkflowReasonCode.INPUTS_CHANGED.value in invalidated.reason_codes
        assert WorkflowReasonCode.REVIEW_INVALIDATED.value in invalidated.reason_codes
        assert invalidated.open_gate_ids  # re-opened
        assert not invalidated.resolved_gate_ids

        with pytest.raises(ReviewInvalidatedError):
            wp.export_reviewed_package(
                invalidated,
                receipt,
                exported_at_utc="2024-07-01T14:00:00Z",
            )

    def test_changed_gap_report_digest_invalidates(self) -> None:
        wp = _processor()
        original = _package_input()
        pf = wp.run_preflight(original)
        changed = _package_input(gap_report_digest=_GAP_DIGEST_V2)
        invalidated = wp.check_inputs_still_valid(pf, changed)
        assert invalidated.phase is PreflightPhase.INVALIDATED

    def test_unchanged_inputs_keep_preflight(self) -> None:
        wp = _processor()
        original = _package_input()
        pf = wp.run_preflight(original)
        same = wp.check_inputs_still_valid(pf, original)
        assert same.phase is pf.phase
        assert same.package_digest == pf.package_digest
        assert same.content_digest == pf.content_digest

    def test_manual_invalidate(self) -> None:
        wp = _processor()
        pf = wp.run_preflight(_package_input())
        inv = wp.invalidate_review(pf, reason="operator withdrew review")
        assert inv.phase is PreflightPhase.INVALIDATED


# ---------------------------------------------------------------------------
# Post-filing evidence import
# ---------------------------------------------------------------------------


class TestPostFilingEvidence:
    def test_import_user_supplied_acknowledgement(self) -> None:
        wp = _processor()
        evidence = wp.import_post_filing_evidence(
            matter_id="matter:unit-1",
            kind=PostFilingEvidenceKind.ACKNOWLEDGEMENT,
            artifact_id="art:ack:1",
            artifact_sha256=_ARTIFACT_SHA,
            imported_at_utc="2024-07-02T10:00:00Z",
            imported_by="docket-clerk",
            package_digest=_BUNDLE_DIGEST,
            source_receipt_id="rcpt:import:1",
        )
        assert evidence.output_kind == OUTPUT_KIND_POST_FILING_EVIDENCE
        assert evidence.kind is PostFilingEvidenceKind.ACKNOWLEDGEMENT
        assert evidence.source_channel is EvidenceSourceChannel.USER_SUPPLIED_IMPORT
        assert evidence.fabricated is False
        revived = ImportedPostFilingEvidence.from_dict(evidence.to_dict())
        assert revived.fabricated is False
        assert revived.artifact_sha256 == _ARTIFACT_SHA

    def test_import_payment_receipt(self) -> None:
        wp = _processor()
        evidence = wp.import_post_filing_evidence(
            matter_id="matter:unit-1",
            kind=PostFilingEvidenceKind.PAYMENT_RECEIPT,
            artifact_id="art:pay:1",
            artifact_sha256=sha256_hex(b"payment-receipt-bytes"),
            imported_at_utc="2024-07-02T10:05:00Z",
            imported_by="docket-clerk",
        )
        assert evidence.kind is PostFilingEvidenceKind.PAYMENT_RECEIPT
        assert evidence.fabricated is False

    def test_fabricated_flag_rejected(self) -> None:
        with pytest.raises(FabricatedEvidenceError):
            ImportedPostFilingEvidence(
                schema_version=WORKFLOW_SCHEMA_VERSION,
                evidence_id="pfevid:x",
                matter_id="matter:unit-1",
                kind=PostFilingEvidenceKind.ACKNOWLEDGEMENT,
                artifact_id="art:ack:1",
                artifact_sha256=_ARTIFACT_SHA,
                source_channel=EvidenceSourceChannel.USER_SUPPLIED_IMPORT,
                imported_at_utc="2024-07-02T10:00:00Z",
                imported_by="system",
                fabricated=True,
            )

    def test_fabricate_labels_rejected(self) -> None:
        wp = _processor()
        with pytest.raises(FabricatedEvidenceError):
            wp.import_post_filing_evidence(
                matter_id="matter:unit-1",
                kind=PostFilingEvidenceKind.ACKNOWLEDGEMENT,
                artifact_id="art:ack:1",
                artifact_sha256=_ARTIFACT_SHA,
                imported_at_utc="2024-07-02T10:00:00Z",
                imported_by="system",
                labels={"fabricated": "true"},
            )

    def test_import_does_not_mark_submitted(self) -> None:
        """Importing receipts is evidence only — never a submission claim."""
        wp = _processor()
        pf = wp.run_preflight(_package_input())
        evidence = wp.import_post_filing_evidence(
            matter_id=pf.matter_id,
            kind=PostFilingEvidenceKind.ACKNOWLEDGEMENT,
            artifact_id="art:ack:1",
            artifact_sha256=_ARTIFACT_SHA,
            imported_at_utc="2024-07-02T10:00:00Z",
            imported_by="docket-clerk",
            package_digest=pf.package_digest,
        )
        # Preflight remains non-submitted; evidence carries no submission flag.
        assert pf.is_submitted is False
        assert "is_submitted" not in evidence.to_dict() or evidence.to_dict().get(
            "fabricated"
        ) is False
        assert "submitted" not in evidence.to_dict()


# ---------------------------------------------------------------------------
# Disclaimer / schema
# ---------------------------------------------------------------------------


class TestDisclaimerAndSchema:
    def test_disclaimer_states_external_filing(self) -> None:
        text = WORKFLOW_DISCLAIMER.lower()
        assert "never signs" in text or "sign" in text
        assert "external" in text
        assert "fabricated" in text or "never fabricated" in text

    def test_preflight_disclaimer_incomplete_rejected(self) -> None:
        pf = _processor().run_preflight(_package_input())
        data = pf.to_dict()
        data.pop("content_digest", None)
        data["disclaimer"] = "a short disclaimer without required language"
        with pytest.raises(WorkflowProcessorError):
            PreflightResult.from_dict(data)
