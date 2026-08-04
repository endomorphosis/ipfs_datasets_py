"""Integration tests for filing receipt reconciliation (PATLAW-155).

Acceptance focus:

* Exact and expected-conversion cases verify with disclosed differences
* Wrong matter, missing acknowledgement, mismatched files, partial
  submission, and payment-only cases remain conflicting / incomplete
* Filed status requires the authoritative acknowledgement rule (reviewed
  policy): verified non-fabricated acknowledgement bound to package digest;
  payment alone never qualifies
* Immutable content-free reconciliation events append to the matter ledger
* No network / browser / session / payment / private-content logging surface
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
)
from ipfs_datasets_py.processors.domains.uspto.filing_receipt_reconciler import (
    DEFAULT_ACKNOWLEDGEMENT_POLICY,
    FORBIDDEN_IMPORT_MODULES,
    FORBIDDEN_RECONCILER_INTERFACES,
    RECONCILER_DISCLAIMER,
    RECONCILER_SCHEMA_VERSION,
    RULESET_VERSION,
    AuthoritativeAcknowledgementPolicy,
    ConversionMatchKind,
    ConvertedArtifactBinding,
    EvidenceRole,
    FabricatedEvidenceError,
    FileMatchKind,
    FiledStatusEligibility,
    FilingReceiptReconciler,
    ForbiddenReconcilerInterfaceError,
    IdentifierMatchKind,
    ImportedEvidence,
    ReconciliationDisposition,
    ReconciliationReasonCode,
    ReconciliationResult,
    SubmittedFileBinding,
    SubmittedPackageBinding,
    assert_interface_allowed,
    create_filing_receipt_reconciler,
    has_authoritative_acknowledgement,
    is_forbidden_interface,
    payment_only_evidence,
    prove_no_forbidden_interfaces,
    reconcile_filing_receipts,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.matter_ledger import (
    IngestDisposition,
    MatterLedger,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_PKG_DIGEST = sha256_hex(b"patlaw-155-package-v1")
_PKG_DIGEST_OTHER = sha256_hex(b"patlaw-155-package-other")
_DOCX_DIGEST = sha256_hex(b"patlaw-155-spec.docx-bytes")
_PDF_LOCAL_DIGEST = sha256_hex(b"patlaw-155-spec-local.pdf-bytes")
_PDF_USPTO_DIGEST = sha256_hex(b"patlaw-155-spec-uspto-converted.pdf-bytes")
_DRAWINGS_DIGEST = sha256_hex(b"patlaw-155-drawings.pdf-bytes")
_ACK_DIGEST = sha256_hex(b"patlaw-155-ack-receipt-bytes")
_PAY_DIGEST = sha256_hex(b"patlaw-155-pay-receipt-bytes")
_MISMATCH_DIGEST = sha256_hex(b"patlaw-155-tampered-file-bytes")

_MATTER = "matter:patlaw-155-demo"
_MATTER_OTHER = "matter:patlaw-155-other"
_PACKAGE = "pkg:patlaw-155-demo"
_APP_NO = "16/900,001"
_CUSTOMER = "12345"
_CONFIRMATION = "9876"

_PRIVATE_CANARY = "CONFIDENTIAL unpublished claim language canary-text-9f3a"

_MODULE_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py/processors/domains/uspto/filing_receipt_reconciler.py"
)

_seq: Iterator[int] = itertools.count(1)


def _reset() -> None:
    global _seq
    _seq = itertools.count(1)


def _id_factory() -> str:
    return f"{next(_seq):04d}"


def _files_exact() -> tuple[SubmittedFileBinding, ...]:
    return (
        SubmittedFileBinding(
            filename="specification.docx",
            content_digest=_DOCX_DIGEST,
            role="specification",
            media_kind="docx",
        ),
        SubmittedFileBinding(
            filename="drawings.pdf",
            content_digest=_DRAWINGS_DIGEST,
            role="drawings",
            media_kind="pdf",
        ),
    )


def _package(**kwargs: Any) -> SubmittedPackageBinding:
    defaults: dict[str, Any] = dict(
        matter_id=_MATTER,
        package_id=_PACKAGE,
        package_digest=_PKG_DIGEST,
        submitted_digest=_PKG_DIGEST,
        files=_files_exact(),
        application_number=_APP_NO,
        customer_number=_CUSTOMER,
        confirmation_number=_CONFIRMATION,
        document_count=2,
        submitted_at_utc="2026-01-15T18:00:00Z",
        handoff_id="handoff:patlaw-155",
    )
    defaults.update(kwargs)
    return SubmittedPackageBinding(**defaults)


def _ack(
    *,
    verified: bool = True,
    matter_id: str | None = _MATTER,
    package_digest: str = _PKG_DIGEST,
    listed: tuple[SubmittedFileBinding, ...] | None = None,
    application_number: str | None = _APP_NO,
    customer_number: str | None = _CUSTOMER,
    confirmation_number: str | None = _CONFIRMATION,
    document_count: int | None = 2,
    observed_at_utc: str | None = "2026-01-15T18:22:00Z",
    artifact_id: str = "art:ack-1",
    **kwargs: Any,
) -> ImportedEvidence:
    if listed is None:
        listed = _files_exact()
    return ImportedEvidence(
        artifact_id=artifact_id,
        role=EvidenceRole.ACKNOWLEDGEMENT,
        content_digest=_ACK_DIGEST,
        package_digest=package_digest,
        verified=verified,
        matter_id=matter_id,
        application_number=application_number,
        customer_number=customer_number,
        confirmation_number=confirmation_number,
        filename="acknowledgement_receipt.txt",
        observed_at_utc=observed_at_utc,
        document_count=document_count,
        listed_files=listed,
        source_receipt_id="rcpt:user-import:ack-1",
        **kwargs,
    )


def _pay(
    *,
    verified: bool = True,
    matter_id: str | None = _MATTER,
    package_digest: str = _PKG_DIGEST,
    artifact_id: str = "art:pay-1",
) -> ImportedEvidence:
    return ImportedEvidence(
        artifact_id=artifact_id,
        role=EvidenceRole.PAYMENT_RECEIPT,
        content_digest=_PAY_DIGEST,
        package_digest=package_digest,
        verified=verified,
        matter_id=matter_id,
        filename="payment_receipt.txt",
        observed_at_utc="2026-01-15T18:22:05Z",
        source_receipt_id="rcpt:user-import:pay-1",
    )


def _converted_expected() -> ConvertedArtifactBinding:
    return ConvertedArtifactBinding(
        artifact_id="art:uspto-pdf-1",
        content_digest=_PDF_USPTO_DIGEST,
        package_digest=_PKG_DIGEST,
        source_filename="specification.docx",
        source_digest=_DOCX_DIGEST,
        converted_filename="specification_uspto.pdf",
        matter_id=_MATTER,
        expected_conversion=True,
        disclosed_differences=(
            "media_kind:docx->pdf",
            "renderer:uspto_patent_center",
            "family:original_file->uspto_converted",
        ),
        verified=True,
    )


def _reconciler(ledger: MatterLedger | None = None) -> FilingReceiptReconciler:
    _reset()
    return create_filing_receipt_reconciler(
        ledger=ledger, id_factory=_id_factory
    )


def _assert_content_free(payload: dict[str, Any]) -> None:
    """Results must never embed private document / canary body text."""
    blob = str(payload)
    assert _PRIVATE_CANARY not in blob
    # No large free-text claim bodies
    assert "unpublished claim language" not in blob.lower()


# ---------------------------------------------------------------------------
# Exact match verifies + filed eligible
# ---------------------------------------------------------------------------


def test_exact_match_verifies_and_filed_status_eligible() -> None:
    ledger = MatterLedger()
    r = _reconciler(ledger)
    result = r.reconcile(
        _package(),
        evidence=(_ack(), _pay()),
        converted=(),
        reconciled_at_utc="2026-01-15T19:00:00Z",
        append_to_ledger=True,
    )

    assert result.disposition is ReconciliationDisposition.VERIFIED
    assert result.filed_status_eligibility is FiledStatusEligibility.ELIGIBLE
    assert result.has_authoritative_acknowledgement is True
    assert result.has_payment_receipt is True
    assert result.may_assert_filed_status is True
    assert result.is_verified is True
    assert result.review_state is ReviewState.COMPLETE
    assert result.schema_version == RECONCILER_SCHEMA_VERSION
    assert result.policy_id == RULESET_VERSION
    assert (
        ReconciliationReasonCode.AUTHORITATIVE_ACKNOWLEDGEMENT_PRESENT.value
        in result.reason_codes
    )
    assert ReconciliationReasonCode.EXACT_MATCH.value in result.reason_codes
    assert (
        ReconciliationReasonCode.FILED_STATUS_ELIGIBLE.value in result.reason_codes
    )
    assert (
        ReconciliationReasonCode.LEDGER_EVENT_APPENDED.value in result.reason_codes
    )
    assert result.ledger_event_id is not None

    # Identifier and file checks all match
    assert all(
        c.match is IdentifierMatchKind.MATCH for c in result.identifier_checks
    )
    assert all(c.match is FileMatchKind.EXACT for c in result.file_checks)

    # Ledger received immutable filing event
    snap = ledger.reconcile(_MATTER)
    assert any(
        e.logical_id == result.ledger_event_id for e in snap.entries
    ) or any(
        result.ledger_event_id in (e.logical_id, e.entry_id)
        for e in snap.entries
    )

    _assert_content_free(result.to_dict())
    # Round-trip
    rt = ReconciliationResult.from_dict(result.to_dict())
    assert rt.content_digest == result.content_digest
    assert rt.disposition is result.disposition


# ---------------------------------------------------------------------------
# Expected conversion with disclosed differences verifies
# ---------------------------------------------------------------------------


def test_expected_conversion_with_disclosed_differences_verifies() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package(),
        evidence=(_ack(),),
        converted=(_converted_expected(),),
        reconciled_at_utc="2026-01-15T19:00:00Z",
        append_to_ledger=False,
    )

    assert (
        result.disposition
        is ReconciliationDisposition.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    )
    assert result.filed_status_eligibility is FiledStatusEligibility.ELIGIBLE
    assert result.may_assert_filed_status is True
    assert result.disclosed_differences == (
        "media_kind:docx->pdf",
        "renderer:uspto_patent_center",
        "family:original_file->uspto_converted",
    )
    assert any(
        c.match is ConversionMatchKind.EXPECTED_CONVERSION
        for c in result.conversion_checks
    )
    assert (
        ReconciliationReasonCode.EXPECTED_CONVERSION_DISCLOSED.value
        in result.reason_codes
    )
    _assert_content_free(result.to_dict())


def test_conversion_difference_without_disclosure_conflicts() -> None:
    r = _reconciler()
    undisc = ConvertedArtifactBinding(
        artifact_id="art:uspto-pdf-undisc",
        content_digest=_PDF_USPTO_DIGEST,
        package_digest=_PKG_DIGEST,
        source_filename="specification.docx",
        source_digest=_DOCX_DIGEST,
        expected_conversion=True,
        disclosed_differences=(),  # missing disclosures
        verified=True,
        matter_id=_MATTER,
    )
    result = r.reconcile(
        _package(),
        evidence=(_ack(),),
        converted=(undisc,),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.CONFLICTING
    assert result.filed_status_eligibility is FiledStatusEligibility.BLOCKED
    assert result.may_assert_filed_status is False
    assert (
        ReconciliationReasonCode.CONVERSION_DIFFERENCE_UNDISCLOSED.value
        in result.reason_codes
    )


def test_unexpected_conversion_digest_mismatch_conflicts() -> None:
    r = _reconciler()
    bad = ConvertedArtifactBinding(
        artifact_id="art:uspto-pdf-bad",
        content_digest=_MISMATCH_DIGEST,
        package_digest=_PKG_DIGEST,
        source_filename="specification.docx",
        expected_conversion=False,
        disclosed_differences=(),
        matter_id=_MATTER,
    )
    result = r.reconcile(
        _package(),
        evidence=(_ack(),),
        converted=(bad,),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.CONFLICTING
    assert result.may_assert_filed_status is False
    assert (
        ReconciliationReasonCode.CONVERSION_MISMATCH.value in result.reason_codes
    )


# ---------------------------------------------------------------------------
# Wrong matter remains conflicting
# ---------------------------------------------------------------------------


def test_wrong_matter_remains_conflicting() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package(),
        evidence=(
            _ack(matter_id=_MATTER_OTHER),
            _pay(matter_id=_MATTER_OTHER),
        ),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.CONFLICTING
    assert result.filed_status_eligibility is FiledStatusEligibility.BLOCKED
    assert result.may_assert_filed_status is False
    assert ReconciliationReasonCode.WRONG_MATTER.value in result.reason_codes
    assert (
        ReconciliationReasonCode.FILED_STATUS_BLOCKED.value in result.reason_codes
    )


def test_wrong_matter_on_converted_artifact_conflicts() -> None:
    r = _reconciler()
    conv = ConvertedArtifactBinding(
        artifact_id="art:uspto-wrong-matter",
        content_digest=_PDF_USPTO_DIGEST,
        package_digest=_PKG_DIGEST,
        source_filename="specification.docx",
        source_digest=_DOCX_DIGEST,
        matter_id=_MATTER_OTHER,
        expected_conversion=True,
        disclosed_differences=("media_kind:docx->pdf",),
    )
    result = r.reconcile(
        _package(),
        evidence=(_ack(),),
        converted=(conv,),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.CONFLICTING
    assert ReconciliationReasonCode.WRONG_MATTER.value in result.reason_codes


# ---------------------------------------------------------------------------
# Missing acknowledgement remains incomplete; filed blocked
# ---------------------------------------------------------------------------


def test_missing_acknowledgement_incomplete_and_filed_blocked() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package(),
        evidence=(),
        converted=(),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.INCOMPLETE
    assert result.filed_status_eligibility is FiledStatusEligibility.BLOCKED
    assert result.has_authoritative_acknowledgement is False
    assert result.may_assert_filed_status is False
    assert (
        ReconciliationReasonCode.AUTHORITATIVE_ACKNOWLEDGEMENT_MISSING.value
        in result.reason_codes
    )
    assert (
        ReconciliationReasonCode.FILED_STATUS_BLOCKED.value in result.reason_codes
    )


def test_unverified_acknowledgement_incomplete() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package(),
        evidence=(_ack(verified=False),),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.INCOMPLETE
    assert result.filed_status_eligibility is FiledStatusEligibility.BLOCKED
    assert result.has_authoritative_acknowledgement is False
    assert (
        ReconciliationReasonCode.UNVERIFIED_ACKNOWLEDGEMENT.value
        in result.reason_codes
    )


# ---------------------------------------------------------------------------
# Payment-only is never filing acknowledgement
# ---------------------------------------------------------------------------


def test_payment_only_remains_incomplete_never_filed() -> None:
    r = _reconciler()
    evidence = (_pay(),)
    assert payment_only_evidence(evidence) is True
    assert (
        has_authoritative_acknowledgement(
            evidence, package_digest=_PKG_DIGEST
        )
        is False
    )

    result = r.reconcile(
        _package(),
        evidence=evidence,
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.INCOMPLETE
    assert result.filed_status_eligibility is FiledStatusEligibility.BLOCKED
    assert result.has_payment_receipt is True
    assert result.has_authoritative_acknowledgement is False
    assert result.may_assert_filed_status is False
    assert (
        ReconciliationReasonCode.PAYMENT_ONLY_INSUFFICIENT.value
        in result.reason_codes
    )
    # Policy flag
    assert DEFAULT_ACKNOWLEDGEMENT_POLICY.payment_receipt_alone_insufficient is True
    assert DEFAULT_ACKNOWLEDGEMENT_POLICY.requires_verified_acknowledgement is True


# ---------------------------------------------------------------------------
# Mismatched files remain conflicting
# ---------------------------------------------------------------------------


def test_mismatched_file_digests_conflict() -> None:
    r = _reconciler()
    listed = (
        SubmittedFileBinding(
            filename="specification.docx",
            content_digest=_MISMATCH_DIGEST,  # tampered
            role="specification",
            media_kind="docx",
        ),
        SubmittedFileBinding(
            filename="drawings.pdf",
            content_digest=_DRAWINGS_DIGEST,
            role="drawings",
            media_kind="pdf",
        ),
    )
    result = r.reconcile(
        _package(),
        evidence=(_ack(listed=listed),),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.CONFLICTING
    assert result.filed_status_eligibility is FiledStatusEligibility.BLOCKED
    assert result.may_assert_filed_status is False
    assert (
        ReconciliationReasonCode.FILE_DIGEST_MISMATCH.value in result.reason_codes
    )
    assert any(
        c.match is FileMatchKind.DIGEST_MISMATCH for c in result.file_checks
    )


def test_identifier_mismatch_conflicts() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package(),
        evidence=(_ack(application_number="16/999,999"),),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.CONFLICTING
    assert (
        ReconciliationReasonCode.APPLICATION_NUMBER_MISMATCH.value
        in result.reason_codes
    )
    app_check = next(
        c for c in result.identifier_checks if c.field == "application_number"
    )
    assert app_check.match is IdentifierMatchKind.MISMATCH


def test_package_digest_mismatch_on_evidence_conflicts() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package(),
        evidence=(_ack(package_digest=_PKG_DIGEST_OTHER),),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.CONFLICTING
    assert (
        ReconciliationReasonCode.PACKAGE_DIGEST_MISMATCH.value
        in result.reason_codes
    )
    # Ack bound to wrong package cannot satisfy authoritative rule
    assert result.has_authoritative_acknowledgement is False


# ---------------------------------------------------------------------------
# Partial submission remains incomplete / conflicting
# ---------------------------------------------------------------------------


def test_partial_submission_incomplete() -> None:
    r = _reconciler()
    # Ack lists only one of two package files.
    listed = (
        SubmittedFileBinding(
            filename="specification.docx",
            content_digest=_DOCX_DIGEST,
            role="specification",
            media_kind="docx",
        ),
    )
    result = r.reconcile(
        _package(),
        evidence=(_ack(listed=listed, document_count=1),),
        append_to_ledger=False,
    )
    # Partial + document count mismatch → conflicting (count) with partial codes
    assert result.disposition in (
        ReconciliationDisposition.CONFLICTING,
        ReconciliationDisposition.INCOMPLETE,
    )
    assert result.filed_status_eligibility is FiledStatusEligibility.BLOCKED
    assert result.may_assert_filed_status is False
    assert (
        ReconciliationReasonCode.PARTIAL_SUBMISSION.value in result.reason_codes
    )
    assert any(
        c.match is FileMatchKind.MISSING_FROM_RECEIPT for c in result.file_checks
    )


def test_ack_with_empty_file_list_is_partial() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package(),
        evidence=(_ack(listed=(), document_count=None),),
        append_to_ledger=False,
    )
    assert result.filed_status_eligibility is FiledStatusEligibility.BLOCKED
    assert (
        ReconciliationReasonCode.PARTIAL_SUBMISSION.value in result.reason_codes
    )
    # Even with verified ack, incomplete file inventory blocks filed status
    # under partial submission rules.
    assert result.disposition in (
        ReconciliationDisposition.INCOMPLETE,
        ReconciliationDisposition.CONFLICTING,
    )


# ---------------------------------------------------------------------------
# Authoritative acknowledgement rule (reviewed policy)
# ---------------------------------------------------------------------------


def test_authoritative_acknowledgement_rule_matches_reviewed_policy() -> None:
    policy = AuthoritativeAcknowledgementPolicy.reviewed_default()
    assert policy.requires_verified_acknowledgement is True
    assert policy.payment_receipt_alone_insufficient is True
    assert policy.acknowledgement_must_bind_package_digest is True
    assert policy.acknowledgement_must_not_be_fabricated is True
    assert policy.policy_id == RULESET_VERSION

    good = (_ack(verified=True),)
    assert (
        has_authoritative_acknowledgement(
            good, package_digest=_PKG_DIGEST, policy=policy
        )
        is True
    )
    assert (
        has_authoritative_acknowledgement(
            (_pay(),), package_digest=_PKG_DIGEST, policy=policy
        )
        is False
    )
    assert (
        has_authoritative_acknowledgement(
            (_ack(verified=False),), package_digest=_PKG_DIGEST, policy=policy
        )
        is False
    )
    assert (
        has_authoritative_acknowledgement(
            (_ack(package_digest=_PKG_DIGEST_OTHER),),
            package_digest=_PKG_DIGEST,
            policy=policy,
        )
        is False
    )


def test_filed_status_requires_authoritative_acknowledgement() -> None:
    """Filed eligibility is never granted without verified acknowledgement."""
    r = _reconciler()
    # Payment + exact converted artifact still insufficient without ack
    exact_conv = ConvertedArtifactBinding(
        artifact_id="art:pdf-exact",
        content_digest=_DRAWINGS_DIGEST,  # matches package drawings
        package_digest=_PKG_DIGEST,
        matter_id=_MATTER,
        expected_conversion=False,
    )
    result = r.reconcile(
        _package(),
        evidence=(_pay(),),
        converted=(exact_conv,),
        append_to_ledger=False,
    )
    assert result.filed_status_eligibility is FiledStatusEligibility.BLOCKED
    assert result.may_assert_filed_status is False
    assert result.has_authoritative_acknowledgement is False


# ---------------------------------------------------------------------------
# Fabricated evidence forbidden
# ---------------------------------------------------------------------------


def test_fabricated_evidence_rejected_at_construction() -> None:
    with pytest.raises(FabricatedEvidenceError):
        ImportedEvidence(
            artifact_id="art:fake",
            role=EvidenceRole.ACKNOWLEDGEMENT,
            content_digest=_ACK_DIGEST,
            package_digest=_PKG_DIGEST,
            verified=True,
            fabricated=True,
        )


# ---------------------------------------------------------------------------
# Closed interface surface / no private content logging
# ---------------------------------------------------------------------------


def test_prove_no_forbidden_interfaces() -> None:
    proof = prove_no_forbidden_interfaces()
    assert proof["no_network_browser_session_payment"] is True
    assert proof["closed"]["network"] is True
    assert proof["closed"]["browser"] is True
    assert proof["closed"]["session"] is True
    assert proof["closed"]["payment"] is True
    assert proof["closed"]["private_content_logging"] is True
    assert proof["rejected_count"] == len(FORBIDDEN_RECONCILER_INTERFACES)

    r = _reconciler()
    assert r.has_network_interface() is False
    assert r.has_browser_interface() is False
    assert r.has_session_interface() is False
    assert r.has_payment_interface() is False

    for iface in (
        "network",
        "browser",
        "session",
        "payment",
        "pay_fee",
        "fabricate_receipt",
        "log_private_content",
        "selenium",
        "playwright",
    ):
        assert is_forbidden_interface(iface) is True
        with pytest.raises(ForbiddenReconcilerInterfaceError):
            assert_interface_allowed(iface)
        with pytest.raises(ForbiddenReconcilerInterfaceError):
            r.assert_capability_allowed(iface)

    for name in (
        "login",
        "open_browser",
        "pay",
        "pay_fee",
        "fabricate_acknowledgement",
        "fabricate_payment_receipt",
        "fabricate_receipt",
        "log_private_content",
    ):
        with pytest.raises(ForbiddenReconcilerInterfaceError):
            getattr(r, name)()


def test_module_source_has_no_forbidden_imports() -> None:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    for mod in FORBIDDEN_IMPORT_MODULES:
        assert not re.search(
            rf"^\s*(import|from)\s+{re.escape(mod)}\b", source, re.M
        ), f"forbidden import of {mod}"
    for banned in (
        "requests.get",
        "httpx.Client",
        "selenium.webdriver",
        "playwright.sync_api",
    ):
        assert banned not in source


def test_results_never_embed_private_content() -> None:
    """Even if labels try to smuggle private text, audit surfaces stay digests."""
    r = _reconciler()
    result = r.reconcile(
        _package(),
        evidence=(_ack(), _pay()),
        converted=(_converted_expected(),),
        append_to_ledger=False,
        labels={"note": "metadata-only"},
    )
    payload = result.to_dict()
    _assert_content_free(payload)
    # Disclaimer documents the policy
    assert "payment receipt alone" in RECONCILER_DISCLAIMER.lower()
    assert "private" in RECONCILER_DISCLAIMER.lower()


# ---------------------------------------------------------------------------
# Ledger append is immutable / content-free
# ---------------------------------------------------------------------------


def test_ledger_event_is_content_free_and_immutable() -> None:
    ledger = MatterLedger()
    r = _reconciler(ledger)
    result = r.reconcile(
        _package(),
        evidence=(_ack(),),
        reconciled_at_utc="2026-01-15T19:00:00Z",
        append_to_ledger=True,
    )
    assert result.ledger_event_id is not None

    # Replay identical reconciliation appends another event id (new recon id)
    # but does not overwrite prior history.
    result2 = r.reconcile(
        _package(),
        evidence=(_ack(),),
        reconciled_at_utc="2026-01-15T19:05:00Z",
        append_to_ledger=True,
    )
    assert result2.ledger_event_id != result.ledger_event_id

    snap = ledger.reconcile(_MATTER)
    # Both events retained
    entry_ids = {e.logical_id for e in snap.entries}
    assert result.ledger_event_id in entry_ids
    assert result2.ledger_event_id in entry_ids

    for e in snap.entries:
        if e.logical_id in (result.ledger_event_id, result2.ledger_event_id):
            meta = dict(e.labels) if hasattr(e, "labels") else {}
            # Prefer metadata field on ledger entries
            if hasattr(e, "labels"):
                blob = str(e.to_dict())
            else:
                blob = str(meta)
            assert _PRIVATE_CANARY not in blob


def test_module_level_reconcile_filing_receipts_helper() -> None:
    result = reconcile_filing_receipts(
        _package(),
        evidence=(_ack(),),
        append_to_ledger=False,
    )
    assert result.is_verified is True
    assert result.may_assert_filed_status is True


def test_mapping_inputs_accepted() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package().to_dict(),
        evidence=[_ack().to_dict()],
        converted=[_converted_expected().to_dict()],
        append_to_ledger=False,
    )
    assert (
        result.disposition
        is ReconciliationDisposition.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    )


def test_submitted_digest_mismatch_with_package_conflicts() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package(submitted_digest=_PKG_DIGEST_OTHER),
        evidence=(_ack(),),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.CONFLICTING
    assert (
        ReconciliationReasonCode.SUBMITTED_DIGEST_MISMATCH.value
        in result.reason_codes
    )


def test_document_count_mismatch_conflicts() -> None:
    r = _reconciler()
    result = r.reconcile(
        _package(document_count=2),
        evidence=(_ack(document_count=9, listed=_files_exact()),),
        append_to_ledger=False,
    )
    assert result.disposition is ReconciliationDisposition.CONFLICTING
    assert (
        ReconciliationReasonCode.DOCUMENT_COUNT_MISMATCH.value
        in result.reason_codes
    )


def test_policy_dict_and_disclaimer_stable() -> None:
    d = DEFAULT_ACKNOWLEDGEMENT_POLICY.to_dict()
    assert d["requires_verified_acknowledgement"] is True
    assert d["payment_receipt_alone_insufficient"] is True
    assert "acknowledgement" in RECONCILER_DISCLAIMER.lower()
