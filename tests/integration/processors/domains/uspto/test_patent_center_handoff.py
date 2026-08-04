"""Integration tests for the human Patent Center handoff state machine (PATLAW-154).

Acceptance focus:
  - Invalid transitions fail
  - System cannot advance past exported without an external human assertion
  - System cannot advance to receipt-verified without verified official artifacts
  - Tests prove no network / browser / session / payment interface exists
  - Content-free training and live instructions are emitted
  - User must record submitted digest and download official artifacts
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path
from typing import Any, Iterator

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.patent_center_handoff import (
    ALLOWED_TRANSITIONS,
    FORBIDDEN_HANDOFF_INTERFACES,
    FORBIDDEN_IMPORT_MODULES,
    FORBIDDEN_METHOD_NAMES,
    HANDOFF_DISCLAIMER,
    HANDOFF_SCHEMA_VERSION,
    PATENT_CENTER_LIVE_URL_LABEL,
    PATENT_CENTER_TRAINING_URL_LABEL,
    ArtifactVerificationStatus,
    ExportBundle,
    ExternalHumanAssertionRequiredError,
    FilingStateMachine,
    ForbiddenHandoffInterfaceError,
    HandoffDigestMismatchError,
    HandoffError,
    HandoffInstructions,
    HandoffInvalidatedError,
    HandoffMode,
    HandoffReasonCode,
    HandoffRecord,
    HandoffState,
    HumanApprovalRecord,
    InstructionStep,
    InvalidTransitionError,
    OfficialArtifact,
    OfficialArtifactKind,
    PatentCenterHandoff,
    TransitionEvent,
    UserSubmissionAssertion,
    VerifiedArtifactsRequiredError,
    assert_interface_allowed,
    assert_transition_allowed,
    build_content_free_instructions,
    create_handoff,
    has_verified_official_artifacts_for_receipt,
    is_forbidden_interface,
    is_transition_allowed,
    prove_no_forbidden_interfaces,
    sha256_hex,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PACKAGE_DIGEST = sha256_hex(b"patlaw-154-package-v1")
_PACKAGE_DIGEST_V2 = sha256_hex(b"patlaw-154-package-v2")
_ACK_DIGEST = sha256_hex(b"patlaw-154-ack-receipt-bytes")
_PAY_DIGEST = sha256_hex(b"patlaw-154-pay-receipt-bytes")
_PDF_DIGEST = sha256_hex(b"patlaw-154-uspto-converted-pdf")
_FILE_DOCX = sha256_hex(b"patlaw-154-spec-docx")
_FILE_PDF = sha256_hex(b"patlaw-154-spec-pdf")

_MATTER = "matter:patlaw-154-demo"
_PACKAGE = "pkg:patlaw-154-demo"

_seq: Iterator[int] = itertools.count(1)

_MODULE_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py/processors/domains/uspto/patent_center_handoff.py"
)


def _reset() -> None:
    global _seq
    _seq = itertools.count(1)


def _id_factory() -> str:
    return f"{next(_seq):04d}"


def _handoff() -> PatentCenterHandoff:
    _reset()
    return PatentCenterHandoff(id_factory=_id_factory)


def _draft(**kwargs: Any) -> HandoffRecord:
    h = _handoff()
    defaults = dict(
        matter_id=_MATTER,
        package_id=_PACKAGE,
        package_digest=_PACKAGE_DIGEST,
        inventor_reviewer="Inventor A",
        practitioner_reviewer="Practitioner B Esq",
        started_at_utc="2025-06-01T10:00:00Z",
        started_by="operator",
    )
    defaults.update(kwargs)
    return h.start_draft(**defaults)


def _validated(h: PatentCenterHandoff | None = None) -> tuple[PatentCenterHandoff, HandoffRecord]:
    h = h or _handoff()
    rec = h.start_draft(
        matter_id=_MATTER,
        package_id=_PACKAGE,
        package_digest=_PACKAGE_DIGEST,
        inventor_reviewer="Inventor A",
        practitioner_reviewer="Practitioner B Esq",
        started_at_utc="2025-06-01T10:00:00Z",
    )
    rec = h.mark_validated(
        rec, actor="validator", at_utc="2025-06-01T11:00:00Z"
    )
    return h, rec


def _human_approved(
    h: PatentCenterHandoff | None = None,
) -> tuple[PatentCenterHandoff, HandoffRecord]:
    h, rec = _validated(h)
    rec = h.record_human_approval(
        rec,
        approver_name="Practitioner B Esq",
        approved_at_utc="2025-06-01T12:00:00Z",
        statement=(
            "I approve this exact package digest for external Patent Center "
            "handoff. Signatures, fees, and Submit remain my actions."
        ),
        role="practitioner",
    )
    return h, rec


def _exported(
    h: PatentCenterHandoff | None = None,
) -> tuple[PatentCenterHandoff, HandoffRecord]:
    h, rec = _human_approved(h)
    rec = h.export_for_patent_center(
        rec,
        exported_by="Practitioner B Esq",
        exported_at_utc="2025-06-01T13:00:00Z",
        export_root_label="/local/exports/pkg-154",
        file_digests={"spec.docx": _FILE_DOCX, "spec.pdf": _FILE_PDF},
    )
    return h, rec


def _user_submitted(
    h: PatentCenterHandoff | None = None,
) -> tuple[PatentCenterHandoff, HandoffRecord]:
    h, rec = _exported(h)
    rec = h.record_user_submission(
        rec,
        asserted_by="Practitioner B Esq",
        asserted_at_utc="2025-06-01T15:00:00Z",
        statement=(
            "I personally submitted this package in Patent Center live mode "
            "and recorded the submitted digest."
        ),
        submitted_digest=_PACKAGE_DIGEST,
        mode=HandoffMode.LIVE,
        confirmation_number="CONF-154-001",
        external_human_action=True,
    )
    return h, rec


def _verified_ack(
    *,
    package_digest: str = _PACKAGE_DIGEST,
    status: ArtifactVerificationStatus = ArtifactVerificationStatus.VERIFIED,
    kind: OfficialArtifactKind = OfficialArtifactKind.ACKNOWLEDGEMENT,
    artifact_id: str = "art:ack:154",
) -> OfficialArtifact:
    return OfficialArtifact(
        artifact_id=artifact_id,
        kind=kind,
        content_digest=_ACK_DIGEST if kind is OfficialArtifactKind.ACKNOWLEDGEMENT else _PAY_DIGEST,
        package_digest=package_digest,
        verification_status=status,
        imported_at_utc="2025-06-01T16:00:00Z",
        imported_by="docket-clerk",
        source_receipt_id="rcpt:user-import:ack-154",
        filename="electronic_acknowledgement_receipt.pdf",
        fabricated=False,
    )


def _roundtrip(record: Any) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()
    restored = type(record).from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_happy_path_to_receipt_verified() -> None:
    h, rec = _user_submitted()
    assert rec.state is HandoffState.USER_SUBMITTED
    assert rec.is_submitted is True
    assert rec.filing_is_external is True
    assert rec.can_file is False
    assert rec.filing_authorization is False

    ack = _verified_ack()
    pay = OfficialArtifact(
        artifact_id="art:pay:154",
        kind=OfficialArtifactKind.PAYMENT_RECEIPT,
        content_digest=_PAY_DIGEST,
        package_digest=_PACKAGE_DIGEST,
        verification_status=ArtifactVerificationStatus.VERIFIED,
        imported_at_utc="2025-06-01T16:01:00Z",
        imported_by="docket-clerk",
        source_receipt_id="rcpt:user-import:pay-154",
        filename="payment_receipt.pdf",
    )
    converted = OfficialArtifact(
        artifact_id="art:pdf:154",
        kind=OfficialArtifactKind.USPTO_CONVERTED_PDF,
        content_digest=_PDF_DIGEST,
        package_digest=_PACKAGE_DIGEST,
        verification_status=ArtifactVerificationStatus.VERIFIED,
        imported_at_utc="2025-06-01T16:02:00Z",
        imported_by="docket-clerk",
        filename="uspto_converted.pdf",
    )
    rec = h.bind_official_artifact(rec, ack)
    rec = h.bind_official_artifact(rec, pay)
    rec = h.bind_official_artifact(rec, converted)
    assert rec.has_verified_acknowledgement is True

    rec = h.verify_receipts(
        rec, actor="docket-clerk", at_utc="2025-06-01T17:00:00Z"
    )
    assert rec.state is HandoffState.RECEIPT_VERIFIED
    assert rec.is_terminal is True
    assert HandoffReasonCode.RECEIPT_VERIFIED.value in rec.reason_codes
    _roundtrip(rec)


def test_states_follow_exact_order() -> None:
    h = _handoff()
    rec = h.start_draft(
        matter_id=_MATTER,
        package_id=_PACKAGE,
        package_digest=_PACKAGE_DIGEST,
    )
    assert rec.state is HandoffState.DRAFT
    rec = h.mark_validated(rec, actor="v", at_utc="2025-06-01T11:00:00Z")
    assert rec.state is HandoffState.VALIDATED
    rec = h.record_human_approval(
        rec,
        approver_name="Approver",
        approved_at_utc="2025-06-01T12:00:00Z",
        statement="I approve this exact package digest for external handoff.",
    )
    assert rec.state is HandoffState.HUMAN_APPROVED
    rec = h.export_for_patent_center(
        rec,
        exported_by="Approver",
        exported_at_utc="2025-06-01T13:00:00Z",
        export_root_label="/export",
    )
    assert rec.state is HandoffState.EXPORTED
    rec = h.record_user_submission(
        rec,
        asserted_by="Approver",
        asserted_at_utc="2025-06-01T14:00:00Z",
        statement="I submitted in Patent Center and recorded the digest.",
        external_human_action=True,
    )
    assert rec.state is HandoffState.USER_SUBMITTED
    rec = h.bind_official_artifact(rec, _verified_ack())
    rec = h.verify_receipts(
        rec, actor="Approver", at_utc="2025-06-01T15:00:00Z"
    )
    assert rec.state is HandoffState.RECEIPT_VERIFIED

    # Transition log records each forward step.
    states = [e.to_state for e in rec.transition_log]
    assert HandoffState.VALIDATED in states
    assert HandoffState.HUMAN_APPROVED in states
    assert HandoffState.EXPORTED in states
    assert HandoffState.USER_SUBMITTED in states
    assert HandoffState.RECEIPT_VERIFIED in states


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


def test_invalid_transitions_fail() -> None:
    h, rec = _validated()
    # Skip human-approved → try export from validated
    with pytest.raises(InvalidTransitionError) as exc:
        h.export_for_patent_center(
            rec,
            exported_by="x",
            exported_at_utc="2025-06-01T13:00:00Z",
            export_root_label="/export",
        )
    assert exc.value.from_state == HandoffState.VALIDATED.value

    # Skip to user-submitted from draft
    draft = _draft()
    with pytest.raises(InvalidTransitionError):
        h.record_user_submission(
            draft,
            asserted_by="x",
            asserted_at_utc="2025-06-01T14:00:00Z",
            statement="I claim submission without export",
            external_human_action=True,
        )

    # Skip to receipt-verified from exported
    h2, exported = _exported()
    with pytest.raises(InvalidTransitionError):
        h2.verify_receipts(
            exported, actor="x", at_utc="2025-06-01T17:00:00Z"
        )

    # Pure state machine rejects reverse and skip edges
    sm = FilingStateMachine()
    assert not sm.can_transition(
        HandoffState.EXPORTED, HandoffState.HUMAN_APPROVED
    )
    assert not is_transition_allowed(
        HandoffState.DRAFT, HandoffState.RECEIPT_VERIFIED
    )
    with pytest.raises(InvalidTransitionError):
        assert_transition_allowed(
            HandoffState.USER_SUBMITTED, HandoffState.EXPORTED
        )


def test_allowed_transition_map_is_linear() -> None:
    # Each happy-path state has exactly one forward edge (except terminal).
    assert ALLOWED_TRANSITIONS[HandoffState.DRAFT] == frozenset(
        {HandoffState.VALIDATED}
    )
    assert ALLOWED_TRANSITIONS[HandoffState.VALIDATED] == frozenset(
        {HandoffState.HUMAN_APPROVED}
    )
    assert ALLOWED_TRANSITIONS[HandoffState.HUMAN_APPROVED] == frozenset(
        {HandoffState.EXPORTED}
    )
    assert ALLOWED_TRANSITIONS[HandoffState.EXPORTED] == frozenset(
        {HandoffState.USER_SUBMITTED}
    )
    assert ALLOWED_TRANSITIONS[HandoffState.USER_SUBMITTED] == frozenset(
        {HandoffState.RECEIPT_VERIFIED}
    )
    assert ALLOWED_TRANSITIONS[HandoffState.RECEIPT_VERIFIED] == frozenset()
    assert ALLOWED_TRANSITIONS[HandoffState.INVALIDATED] == frozenset()


# ---------------------------------------------------------------------------
# Cannot advance past exported without external human assertion
# ---------------------------------------------------------------------------


def test_cannot_advance_past_exported_without_external_human_assertion() -> None:
    h, rec = _exported()
    assert rec.state is HandoffState.EXPORTED
    assert rec.submission is None

    # State machine alone: missing assertion
    sm = FilingStateMachine()
    with pytest.raises(ExternalHumanAssertionRequiredError):
        sm.assert_can_transition(
            HandoffState.EXPORTED,
            HandoffState.USER_SUBMITTED,
            submission=None,
            package_digest=_PACKAGE_DIGEST,
        )

    # external_human_action=False rejected at assertion construction
    with pytest.raises(ExternalHumanAssertionRequiredError):
        UserSubmissionAssertion(
            assertion_id="usa:bad",
            package_digest=_PACKAGE_DIGEST,
            submitted_digest=_PACKAGE_DIGEST,
            asserted_by="spoof",
            asserted_at_utc="2025-06-01T15:00:00Z",
            statement="system-generated submission",
            external_human_action=False,
        )

    # API path also fails closed
    with pytest.raises(ExternalHumanAssertionRequiredError):
        h.record_user_submission(
            rec,
            asserted_by="spoof",
            asserted_at_utc="2025-06-01T15:00:00Z",
            statement="attempt without external action",
            external_human_action=False,
        )

    # Still exported
    assert rec.state is HandoffState.EXPORTED
    assert rec.is_submitted is False


def test_user_submission_requires_matching_digest() -> None:
    h, rec = _exported()
    with pytest.raises(HandoffDigestMismatchError):
        h.record_user_submission(
            rec,
            asserted_by="Practitioner B Esq",
            asserted_at_utc="2025-06-01T15:00:00Z",
            statement="I submitted a different package",
            submitted_digest=_PACKAGE_DIGEST_V2,
            external_human_action=True,
        )


# ---------------------------------------------------------------------------
# Cannot advance to receipt-verified without verified official artifacts
# ---------------------------------------------------------------------------


def test_cannot_advance_to_receipt_verified_without_verified_artifacts() -> None:
    h, rec = _user_submitted()
    assert rec.official_artifacts == ()

    with pytest.raises(VerifiedArtifactsRequiredError):
        h.verify_receipts(
            rec, actor="clerk", at_utc="2025-06-01T17:00:00Z"
        )

    # Unverified acknowledgement is insufficient
    unverified = _verified_ack(
        status=ArtifactVerificationStatus.UNVERIFIED
    )
    rec2 = h.bind_official_artifact(rec, unverified)
    with pytest.raises(VerifiedArtifactsRequiredError):
        h.verify_receipts(
            rec2, actor="clerk", at_utc="2025-06-01T17:00:00Z"
        )

    # Payment-only (even verified) is insufficient — need acknowledgement
    pay_only = OfficialArtifact(
        artifact_id="art:pay-only",
        kind=OfficialArtifactKind.PAYMENT_RECEIPT,
        content_digest=_PAY_DIGEST,
        package_digest=_PACKAGE_DIGEST,
        verification_status=ArtifactVerificationStatus.VERIFIED,
        imported_at_utc="2025-06-01T16:01:00Z",
        imported_by="clerk",
    )
    rec3 = h.bind_official_artifact(rec, pay_only)
    assert has_verified_official_artifacts_for_receipt(
        rec3.official_artifacts, package_digest=_PACKAGE_DIGEST
    ) is False
    with pytest.raises(VerifiedArtifactsRequiredError):
        h.verify_receipts(
            rec3, actor="clerk", at_utc="2025-06-01T17:00:00Z"
        )

    # Wrong-matter digest fails binding
    with pytest.raises(HandoffDigestMismatchError):
        h.bind_official_artifact(
            rec, _verified_ack(package_digest=_PACKAGE_DIGEST_V2)
        )


def test_fabricated_artifacts_forbidden() -> None:
    with pytest.raises(ForbiddenHandoffInterfaceError):
        OfficialArtifact(
            artifact_id="art:fake",
            kind=OfficialArtifactKind.ACKNOWLEDGEMENT,
            content_digest=_ACK_DIGEST,
            package_digest=_PACKAGE_DIGEST,
            verification_status=ArtifactVerificationStatus.VERIFIED,
            imported_at_utc="2025-06-01T16:00:00Z",
            imported_by="system",
            fabricated=True,
        )


# ---------------------------------------------------------------------------
# No network / browser / session / payment interface
# ---------------------------------------------------------------------------


def test_prove_no_network_browser_session_payment_interface() -> None:
    proof = prove_no_forbidden_interfaces()
    assert proof["no_network_browser_session_payment"] is True
    assert proof["closed"] == {
        "network": True,
        "browser": True,
        "session": True,
        "payment": True,
    }
    assert proof["rejected_count"] == len(FORBIDDEN_HANDOFF_INTERFACES)

    h = _handoff()
    assert h.has_network_interface() is False
    assert h.has_browser_interface() is False
    assert h.has_session_interface() is False
    assert h.has_payment_interface() is False

    for iface in (
        "network",
        "browser",
        "session",
        "payment",
        "network_login",
        "browser_control",
        "session_cookie_replay",
        "payment_interface",
        "pay_fee",
        "selenium",
        "playwright",
        "automate_patent_center",
        "fabricate_receipt",
    ):
        assert is_forbidden_interface(iface) is True
        with pytest.raises(ForbiddenHandoffInterfaceError):
            assert_interface_allowed(iface)
        with pytest.raises(ForbiddenHandoffInterfaceError):
            h.assert_capability_allowed(iface)

    # Forbidden method surface raises
    for name in (
        "login",
        "open_browser",
        "control_browser",
        "pay",
        "pay_fee",
        "submit_to_uspto",
        "file_application",
        "store_session",
        "load_session_cookies",
        "fabricate_acknowledgement",
        "fabricate_payment_receipt",
        "fabricate_receipt",
    ):
        assert name in FORBIDDEN_METHOD_NAMES or hasattr(h, name)
        with pytest.raises(ForbiddenHandoffInterfaceError):
            getattr(h, name)()


def test_module_source_has_no_forbidden_imports() -> None:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    for mod in FORBIDDEN_IMPORT_MODULES:
        assert not re.search(
            rf"^\s*(import|from)\s+{re.escape(mod)}\b", source, re.M
        ), f"forbidden import of {mod}"
    # Also no httpx/requests string used as live client construction patterns
    for banned in (
        "requests.get",
        "requests.post",
        "httpx.Client",
        "selenium.webdriver",
        "playwright.sync_api",
        "urllib.request.urlopen",
    ):
        assert banned not in source


def test_forbidden_interfaces_set_covers_acceptance_axes() -> None:
    axes = {"network", "browser", "session", "payment"}
    covered = {
        a
        for a in axes
        if any(a in iface for iface in FORBIDDEN_HANDOFF_INTERFACES)
    }
    assert covered == axes


# ---------------------------------------------------------------------------
# Content-free instructions (training + live)
# ---------------------------------------------------------------------------


def test_export_emits_content_free_training_and_live_instructions() -> None:
    h, rec = _exported()
    assert rec.training_instructions is not None
    assert rec.live_instructions is not None
    assert rec.training_instructions.mode is HandoffMode.TRAINING
    assert rec.live_instructions.mode is HandoffMode.LIVE
    assert (
        rec.training_instructions.patent_center_url_label
        == PATENT_CENTER_TRAINING_URL_LABEL
    )
    assert (
        rec.live_instructions.patent_center_url_label
        == PATENT_CENTER_LIVE_URL_LABEL
    )
    assert rec.export_bundle is not None
    assert rec.export_bundle.package_digest == _PACKAGE_DIGEST

    for ins in (rec.training_instructions, rec.live_instructions):
        assert len(ins.steps) >= 8
        joined = " ".join(s.summary for s in ins.steps).lower()
        # Requires user to record digest and download artifacts
        assert "submitted" in joined or "digest" in joined
        assert "download" in joined
        assert "acknowledgement" in joined or "receipt" in joined
        # Content-free: no pasted secret material
        for banned in (
            "api_key=",
            "authorization: bearer ",
            "cookie=",
            "-----begin",
        ):
            assert banned not in joined
        _roundtrip(ins)

    assert HandoffReasonCode.CONTENT_FREE_INSTRUCTIONS.value in rec.reason_codes
    assert HandoffReasonCode.INSTRUCTIONS_EMITTED.value in rec.reason_codes
    assert HANDOFF_DISCLAIMER


def test_build_content_free_instructions_rejects_secret_markers() -> None:
    with pytest.raises(HandoffError):
        InstructionStep(
            step_id="bad",
            ordinal=1,
            summary="Paste authorization: bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 here",
        )
    with pytest.raises(HandoffError):
        InstructionStep(
            step_id="bad2",
            ordinal=1,
            summary="cookie=sessionid=deadbeefcafebabe; path=/",
        )


def test_generate_instructions_helper() -> None:
    h, rec = _exported()
    train = h.generate_instructions(rec, mode=HandoffMode.TRAINING)
    live = h.generate_instructions(rec, mode="live")
    assert train.mode is HandoffMode.TRAINING
    assert live.mode is HandoffMode.LIVE
    assert train.package_digest == _PACKAGE_DIGEST


# ---------------------------------------------------------------------------
# Digests, invalidation, serialization
# ---------------------------------------------------------------------------


def test_digest_mismatch_on_validation_and_approval() -> None:
    h, rec = _validated()
    with pytest.raises(HandoffDigestMismatchError):
        h.mark_validated(
            # already validated; use draft with wrong digest path via re-approve
            _draft(),
            actor="v",
            at_utc="2025-06-01T11:30:00Z",
            package_digest=_PACKAGE_DIGEST_V2,
        )
    with pytest.raises(HandoffDigestMismatchError):
        h.record_human_approval(
            rec,
            approver_name="x",
            approved_at_utc="2025-06-01T12:00:00Z",
            statement="approve wrong digest",
            package_digest=_PACKAGE_DIGEST_V2,
        )


def test_invalidate_blocks_further_progress() -> None:
    h, rec = _exported()
    bad = h.invalidate(
        rec,
        actor="operator",
        at_utc="2025-06-01T14:00:00Z",
        reason="material package inputs changed",
    )
    assert bad.state is HandoffState.INVALIDATED
    with pytest.raises(HandoffInvalidatedError):
        h.record_user_submission(
            bad,
            asserted_by="x",
            asserted_at_utc="2025-06-01T15:00:00Z",
            statement="late claim",
            external_human_action=True,
        )


def test_handoff_record_roundtrip_and_create_helper() -> None:
    rec = create_handoff(
        matter_id=_MATTER,
        package_id=_PACKAGE,
        package_digest=_PACKAGE_DIGEST,
        id_factory=_id_factory,
        inventor_reviewer="Inventor A",
    )
    assert rec.state is HandoffState.DRAFT
    assert rec.schema_version == HANDOFF_SCHEMA_VERSION
    assert rec.classification is DisclosureClassification.CONFIDENTIAL_APPLICATION
    assert rec.review_state is ReviewState.REQUIRED
    _roundtrip(rec)

    # Nested component round-trips
    _roundtrip(
        HumanApprovalRecord(
            approval_id="hap:1",
            package_digest=_PACKAGE_DIGEST,
            approver_name="A",
            approved_at_utc="2025-06-01T12:00:00Z",
            statement="I approve this exact package digest.",
        )
    )
    _roundtrip(
        ExportBundle(
            export_id="exp:1",
            package_digest=_PACKAGE_DIGEST,
            exported_at_utc="2025-06-01T13:00:00Z",
            exported_by="A",
            export_root_label="/export",
            file_digests={"a.docx": _FILE_DOCX},
        )
    )
    _roundtrip(
        UserSubmissionAssertion(
            assertion_id="usa:1",
            package_digest=_PACKAGE_DIGEST,
            submitted_digest=_PACKAGE_DIGEST,
            asserted_by="A",
            asserted_at_utc="2025-06-01T15:00:00Z",
            statement="I submitted and recorded the digest.",
            external_human_action=True,
        )
    )
    _roundtrip(_verified_ack())
    _roundtrip(
        TransitionEvent(
            from_state=HandoffState.DRAFT,
            to_state=HandoffState.VALIDATED,
            at_utc="2025-06-01T11:00:00Z",
            actor="v",
            reason_code="state_validated",
        )
    )
    _roundtrip(
        build_content_free_instructions(
            mode=HandoffMode.LIVE,
            package_digest=_PACKAGE_DIGEST,
            instructions_id="ins:1",
        )
    )


def test_named_reviewer_responsibilities_recorded() -> None:
    rec = _draft(
        inventor_reviewer="Inventor A",
        practitioner_reviewer="Practitioner B Esq",
    )
    assert rec.inventor_reviewer == "Inventor A"
    assert rec.practitioner_reviewer == "Practitioner B Esq"


def test_state_enum_values_match_acceptance_language() -> None:
    assert HandoffState.DRAFT.value == "draft"
    assert HandoffState.VALIDATED.value == "validated"
    assert HandoffState.HUMAN_APPROVED.value == "human-approved"
    assert HandoffState.EXPORTED.value == "exported"
    assert HandoffState.USER_SUBMITTED.value == "user-submitted"
    assert HandoffState.RECEIPT_VERIFIED.value == "receipt-verified"


def test_ast_surface_classes_exist() -> None:
    """AST query surface: PatentCenterHandoff, FilingStateMachine."""
    assert PatentCenterHandoff.interface == "PatentCenterHandoff@1"
    assert FilingStateMachine.interface == "FilingStateMachine@1"
    h = PatentCenterHandoff()
    assert isinstance(h, PatentCenterHandoff)
    assert isinstance(FilingStateMachine(), FilingStateMachine)
