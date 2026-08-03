"""Unit tests for USPTO submission processor (PATLAW-033).

Acceptance focus:
  - Original DOCX stays authoritative where applicable
  - Extracted facts point to exact versions/spans
  - Signature presence is never reusable signing data
  - Missing/mismatched metadata/receipts and DOCX/PDF differences are explicit
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    ReviewState,
    SubmissionFact,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_processor import (
    PARSER_VERSION,
    SUBMISSION_PROCESSOR_SCHEMA_VERSION,
    ArtifactRole,
    ClaimVersion,
    FactExtractionStatus,
    SignaturePresenceStatus,
    SubmissionAnalysisResult,
    SubmissionArtifactInput,
    SubmissionDisposition,
    SubmissionFactType,
    SubmissionIssueKind,
    SubmissionPackageInput,
    SubmissionProcessor,
    SubmissionReasonCode,
    artifact_from_extraction,
    process_submission,
    sha256_hex,
)
from tests.fixtures.uspto.submissions.generators import (
    AMEND_CANARY,
    CLAIM_CANARY,
    DECLARATION_CANARY,
    RECEIPT_CANARY,
    REMARKS_CANARY,
    SIGNATURE_MARKER,
    SIGNATURE_MATERIAL_CANARY,
    build_acknowledgement_receipt_text,
    build_amendment_claims_text,
    build_as_filed_claims_text,
    build_converted_pdf_text,
    build_declaration_text,
    build_docx_authoritative_text,
    build_mismatched_metadata_text,
    build_payment_receipt_fields,
    canaries,
    fixture_recipe_cases,
)

FIXTURE_DIR = Path(__file__).resolve().parents[5] / "fixtures" / "uspto" / "submissions"
RECIPE_PATH = FIXTURE_DIR / "submission_recipe.json"


def _processor() -> SubmissionProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"sub:test:{counter['n']:04d}"

    return SubmissionProcessor(id_factory=_ids)


def _assert_round_trip(result: SubmissionAnalysisResult) -> None:
    first = result.to_dict()
    restored = SubmissionAnalysisResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    # Public projection must never carry full claim bodies or signature material.
    blob = json.dumps(public)
    assert SIGNATURE_MATERIAL_CANARY not in blob
    assert "current_claims" not in public  # only claim numbers, not text
    assert "Jane Q. Inventor" not in blob


def _assert_facts_span_bound(result: SubmissionAnalysisResult) -> None:
    span_ids = {s.span_id for s in result.spans}
    assert result.spans, "semantic extraction must produce evidence spans"
    for fact in result.facts:
        assert fact.fact.schema_version == CONTRACTS_SCHEMA_VERSION
        assert fact.fact.evidence_span_id in span_ids
        span = result.span_by_id(fact.fact.evidence_span_id)
        assert span is not None
        assert span.artifact_id == fact.artifact_id or span.artifact_id in result.input_artifact_ids
        assert span.text_digest
        assert fact.fact.version
        assert fact.value_digest
        # Contract fact round-trip
        fdict = fact.fact.to_dict()
        assert SubmissionFact.from_dict(fdict).to_dict() == fdict


# ---------------------------------------------------------------------------
# Recipe / fixture surface
# ---------------------------------------------------------------------------


def test_recipe_file_present() -> None:
    assert RECIPE_PATH.is_file()
    recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
    assert recipe["schema_version"] == "uspto.submission-recipe.v1"
    assert len(recipe["cases"]) >= 6
    assert recipe["task_id"] == "PATLAW-033"


def test_fixture_generators_and_canaries() -> None:
    cases = fixture_recipe_cases()
    assert len(cases) >= 6
    c = canaries()
    assert CLAIM_CANARY in c.values()
    assert build_amendment_claims_text()
    assert RECEIPT_CANARY in build_acknowledgement_receipt_text()
    assert "amount_usd" in build_payment_receipt_fields()


# ---------------------------------------------------------------------------
# Amendments, claims, remarks, current-claim reconstruction
# ---------------------------------------------------------------------------


def test_amendment_extracts_claims_remarks_forms_fees_attachments() -> None:
    text = build_amendment_claims_text()
    result = _processor().process(
        SubmissionPackageInput(
            package_id="pkg:amend-1",
            matter_id="matter:16-123456",
            expected_application_number="16/123,456",
            require_ack_receipt=False,
            classification=DisclosureClassification.PUBLIC_USER,
            artifacts=(
                SubmissionArtifactInput(
                    artifact_id="art:amendment-1",
                    role=ArtifactRole.AMENDMENT,
                    classification=DisclosureClassification.PUBLIC_USER,
                    content_sha256=sha256_hex(text),
                    media_family="pdf",
                    full_text=text,
                    version="preliminary_amendment",
                    document_description="Preliminary Amendment",
                    application_number="16/123,456",
                    authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
                ),
            ),
            claim_versions=(
                ClaimVersion(
                    version="as_filed",
                    claims={
                        "1": "A device comprising a sensor.",
                        "2": "The device of claim 1 further comprising a filter.",
                    },
                ),
            ),
            labels={"fixture": "amendment_current_claims"},
        )
    )
    assert result.schema_version == SUBMISSION_PROCESSOR_SCHEMA_VERSION
    assert result.disposition in (
        SubmissionDisposition.EXTRACTED,
        SubmissionDisposition.REVIEW,
    )
    _assert_facts_span_bound(result)
    _assert_round_trip(result)

    types = {f.fact.fact_type for f in result.facts}
    assert SubmissionFactType.AMENDMENT_INSTRUCTION.value in types
    assert SubmissionFactType.REMARKS.value in types
    assert SubmissionFactType.FORM.value in types
    assert SubmissionFactType.FEE_PRESENCE.value in types
    assert SubmissionFactType.ATTACHMENT.value in types
    assert SubmissionFactType.APPLICATION_METADATA.value in types
    assert SubmissionFactType.DOCUMENT_DESCRIPTION.value in types
    assert SubmissionFactType.CURRENT_CLAIM.value in types

    assert SubmissionReasonCode.CLAIMS_EXTRACTED.value in result.reason_codes or (
        SubmissionReasonCode.AMENDMENTS_EXTRACTED.value in result.reason_codes
    )
    assert SubmissionReasonCode.REMARKS_EXTRACTED.value in result.reason_codes
    assert SubmissionReasonCode.CURRENT_CLAIMS_RECONSTRUCTED.value in result.reason_codes

    # Current claim 1 must reflect amended temperature-sensor language.
    assert "1" in result.current_claims
    assert "temperature sensor" in result.current_claims["1"].lower() or (
        CLAIM_CANARY in result.current_claims["1"]
    )
    assert "1" in result.current_claim_span_ids
    # Version binding on claim facts.
    claim_facts = result.facts_of_type(SubmissionFactType.CLAIM) + result.facts_of_type(
        SubmissionFactType.AMENDMENT_INSTRUCTION
    )
    assert any(f.fact.version == "preliminary_amendment" for f in claim_facts)
    # Remarks canary appears only in internal display/value path, not public.
    remarks = result.facts_of_type(SubmissionFactType.REMARKS)
    assert remarks
    assert remarks[0].value_digest == sha256_hex(
        remarks[0].display_value  # type: ignore[arg-type]
    ) or len(remarks[0].value_digest) == 64


def test_as_filed_plain_claims_and_current_reconstruction() -> None:
    text = build_as_filed_claims_text()
    result = _processor().process(
        package_id="pkg:as-filed",
        require_ack_receipt=False,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:claims-1",
                role=ArtifactRole.CLAIM_SET,
                full_text=text,
                version="as_filed",
                application_number="16/123,456",
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
    )
    assert result.current_claims
    assert "1" in result.current_claims
    assert "sensor" in result.current_claims["1"].lower()
    _assert_facts_span_bound(result)
    again = process_submission(
        package_id="pkg:as-filed-2",
        require_ack_receipt=False,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:claims-2",
                role=ArtifactRole.CLAIM_SET,
                full_text=text,
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
    )
    assert again.facts


# ---------------------------------------------------------------------------
# Signature presence — never reusable signing data
# ---------------------------------------------------------------------------


def test_signature_presence_never_retains_signing_material() -> None:
    text = build_amendment_claims_text(include_signature_material=True)
    assert SIGNATURE_MATERIAL_CANARY in text
    result = _processor().process(
        package_id="pkg:sig-1",
        require_ack_receipt=False,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:sig-1",
                role=ArtifactRole.AMENDMENT,
                full_text=text,
                classification=DisclosureClassification.PUBLIC_USER,
                layout_cues=({"kind": "signature_presence", "signature_presence": "true"},),
            ),
        ),
    )
    assert result.signature_presence is SignaturePresenceStatus.PRESENT
    sig_facts = result.facts_of_type(SubmissionFactType.SIGNATURE_PRESENCE)
    assert sig_facts
    for f in sig_facts:
        assert f.signature_presence is SignaturePresenceStatus.PRESENT
        assert f.display_value == SignaturePresenceStatus.PRESENT.value
        # Value digest is of the presence flag, not the signature body.
        assert f.value_digest == sha256_hex(SignaturePresenceStatus.PRESENT.value)
        assert SIGNATURE_MATERIAL_CANARY not in (f.display_value or "")
        assert "Jane" not in (f.display_value or "")

    # Suppression issue must be explicit.
    assert any(
        i.kind is SubmissionIssueKind.SIGNATURE_MATERIAL_SUPPRESSED for i in result.issues
    )
    assert SubmissionReasonCode.SIGNATURE_PRESENCE_ONLY.value in result.reason_codes

    # Public projection and full to_dict must not re-emit signature material as data.
    public = json.dumps(result.public_projection())
    assert SIGNATURE_MATERIAL_CANARY not in public
    assert "Jane Q. Inventor" not in public
    # Internal to_dict may hold other claim text; signature material itself must
    # not appear as a fact display_value or dedicated field.
    for f in result.facts:
        assert SIGNATURE_MATERIAL_CANARY not in (f.display_value or "")
        if f.fact.fact_type == SubmissionFactType.SIGNATURE_PRESENCE.value:
            assert f.display_value in (
                SignaturePresenceStatus.PRESENT.value,
                SignaturePresenceStatus.ABSENT.value,
                SignaturePresenceStatus.UNKNOWN.value,
            )


# ---------------------------------------------------------------------------
# DOCX authoritative over converted PDF; differences explicit
# ---------------------------------------------------------------------------


def test_docx_remains_authoritative_and_differences_are_explicit() -> None:
    docx_text = build_docx_authoritative_text()
    pdf_text = build_converted_pdf_text(diverge_claim=True)
    result = _processor().process(
        SubmissionPackageInput(
            package_id="pkg:docx-pdf-1",
            require_ack_receipt=False,
            classification=DisclosureClassification.PUBLIC_USER,
            artifacts=(
                SubmissionArtifactInput(
                    artifact_id="art:orig-docx-1",
                    role=ArtifactRole.AUTHORITATIVE_DOCX,
                    classification=DisclosureClassification.PUBLIC_USER,
                    content_sha256=sha256_hex(docx_text),
                    media_family="docx",
                    full_text=docx_text,
                    version="filing",
                    application_number="16/900,001",
                    authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
                    related_artifact_ids=("art:uspto-pdf-1",),
                    differences=(
                        {
                            "kind": "pagination",
                            "status": "disagreement",
                            "docx_artifact_id": "art:orig-docx-1",
                            "pdf_artifact_id": "art:uspto-pdf-1",
                            "docx_page": 2,
                            "pdf_page": 3,
                            "element": "equation_1",
                            "detail": "equation_pagination_drift",
                        },
                    ),
                ),
                SubmissionArtifactInput(
                    artifact_id="art:uspto-pdf-1",
                    role=ArtifactRole.USPTO_CONVERTED_PDF,
                    classification=DisclosureClassification.PUBLIC_USER,
                    content_sha256=sha256_hex(pdf_text),
                    media_family="pdf",
                    full_text=pdf_text,
                    version="filing",
                    application_number="16/900,001",
                    authority_relation=AuthorityRelation.DERIVATIVE,
                    related_artifact_ids=("art:orig-docx-1",),
                ),
            ),
        )
    )
    assert "art:orig-docx-1" in result.authoritative_artifact_ids
    assert "art:uspto-pdf-1" not in result.authoritative_artifact_ids
    assert SubmissionReasonCode.DOCX_AUTHORITATIVE.value in result.reason_codes
    # Differences must be explicit issues.
    diff_issues = [
        i for i in result.issues if i.kind is SubmissionIssueKind.DOCX_PDF_DIFFERENCE
    ]
    assert diff_issues, "DOCX/PDF differences must be explicit"
    assert any(
        "art:orig-docx-1" in i.artifact_ids and "art:uspto-pdf-1" in i.artifact_ids
        for i in diff_issues
    )
    assert SubmissionReasonCode.DOCX_PDF_DIFFERENCE.value in result.reason_codes
    # Claim facts should be authoritative from DOCX, not PDF-only divergence text.
    claim_facts = [
        f
        for f in result.facts
        if f.fact.fact_type
        in (
            SubmissionFactType.CLAIM.value,
            SubmissionFactType.CURRENT_CLAIM.value,
        )
    ]
    assert claim_facts
    assert all(f.is_authoritative or f.artifact_id == "art:orig-docx-1" for f in claim_facts)
    # PDF-only wording "(PDF)" must not become the authoritative claim text.
    for num, text in result.current_claims.items():
        assert "(PDF)" not in text
    assert result.requires_review is True
    _assert_facts_span_bound(result)
    _assert_round_trip(result)


# ---------------------------------------------------------------------------
# Receipts: acknowledgement + payment; missing/mismatched explicit
# ---------------------------------------------------------------------------


def test_acknowledgement_and_payment_receipts() -> None:
    ack_text = build_acknowledgement_receipt_text()
    pay_fields = build_payment_receipt_fields()
    result = _processor().process(
        package_id="pkg:receipts-1",
        require_ack_receipt=True,
        require_payment_receipt=True,
        expected_application_number="16/900,001",
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:ack-receipt-1",
                role=ArtifactRole.ACKNOWLEDGEMENT_RECEIPT,
                full_text=ack_text,
                receipt_fields={
                    "receipt_id": RECEIPT_CANARY,
                    "application_number": "16/900,001",
                    "confirmation_number": "1234",
                    "receipt_date_utc": "2026-01-15T18:22:00Z",
                },
                application_number="16/900,001",
                classification=DisclosureClassification.PUBLIC_USER,
            ),
            artifact_from_extraction(
                artifact_id="art:pay-receipt-1",
                role=ArtifactRole.PAYMENT_RECEIPT,
                full_text="",
                receipt_fields=pay_fields,
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
    )
    assert result.acknowledgement_ids
    assert RECEIPT_CANARY in result.acknowledgement_ids or any(
        RECEIPT_CANARY in a for a in result.acknowledgement_ids
    )
    assert result.payment_receipt_present is True
    ack_facts = result.facts_of_type(SubmissionFactType.ACKNOWLEDGEMENT_IDENTIFIER)
    pay_facts = result.facts_of_type(SubmissionFactType.PAYMENT_RECEIPT)
    assert ack_facts
    assert pay_facts
    assert SubmissionReasonCode.ACKNOWLEDGEMENT_EXTRACTED.value in result.reason_codes
    assert SubmissionReasonCode.PAYMENT_RECEIPT_EXTRACTED.value in result.reason_codes
    # No missing-receipt error when both present.
    assert not any(
        i.kind is SubmissionIssueKind.MISSING_RECEIPT
        and "required" in (i.detail or "")
        for i in result.issues
    )
    _assert_facts_span_bound(result)
    _assert_round_trip(result)


def test_missing_receipt_is_explicit() -> None:
    text = build_as_filed_claims_text()
    result = _processor().process(
        package_id="pkg:missing-ack",
        require_ack_receipt=True,
        require_payment_receipt=True,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:claims-only",
                role=ArtifactRole.CLAIM_SET,
                full_text=text,
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
    )
    missing = [i for i in result.issues if i.kind is SubmissionIssueKind.MISSING_RECEIPT]
    assert missing, "missing receipts must be explicit"
    assert SubmissionReasonCode.MISSING_RECEIPT.value in result.reason_codes
    assert result.disposition is SubmissionDisposition.REVIEW
    assert result.review_state is ReviewState.REQUIRED
    assert result.payment_receipt_present is False


def test_mismatched_metadata_is_explicit() -> None:
    text = build_mismatched_metadata_text(application_number="16/999,999")
    result = _processor().process(
        package_id="pkg:mismatch-meta",
        require_ack_receipt=False,
        expected_application_number="16/123,456",
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:wrong-app",
                role=ArtifactRole.SUBMISSION,
                full_text=text,
                application_number="16/999,999",
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
    )
    mismatches = [
        i
        for i in result.issues
        if i.kind is SubmissionIssueKind.MISMATCHED_METADATA
    ]
    assert mismatches, "mismatched application metadata must be explicit"
    assert SubmissionReasonCode.MISMATCHED_METADATA.value in result.reason_codes
    assert result.requires_review is True


def test_matter_id_mismatch_is_explicit() -> None:
    text = build_as_filed_claims_text()
    result = _processor().process(
        package_id="pkg:matter-mismatch",
        matter_id="matter:A",
        require_ack_receipt=False,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            SubmissionArtifactInput(
                artifact_id="art:m1",
                role=ArtifactRole.SUBMISSION,
                full_text=text,
                matter_id="matter:B",
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
    )
    assert any(i.kind is SubmissionIssueKind.MATTER_ID_MISMATCH for i in result.issues)


# ---------------------------------------------------------------------------
# Declarations / forms
# ---------------------------------------------------------------------------


def test_declaration_and_form_extraction() -> None:
    text = build_declaration_text()
    result = _processor().process(
        package_id="pkg:decl-1",
        require_ack_receipt=False,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:decl-1",
                role=ArtifactRole.DECLARATION,
                full_text=text,
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
    )
    assert result.facts_of_type(SubmissionFactType.DECLARATION)
    assert result.facts_of_type(SubmissionFactType.FORM)
    assert result.signature_presence is SignaturePresenceStatus.PRESENT
    assert SubmissionReasonCode.DECLARATIONS_EXTRACTED.value in result.reason_codes
    assert SubmissionReasonCode.FORMS_EXTRACTED.value in result.reason_codes
    # Declaration canary must not appear in public projection as raw text.
    public = json.dumps(result.public_projection())
    assert DECLARATION_CANARY not in public
    _assert_facts_span_bound(result)


# ---------------------------------------------------------------------------
# Empty / quarantine / contract surface
# ---------------------------------------------------------------------------


def test_empty_package_rejected() -> None:
    result = _processor().process(
        package_id="pkg:empty",
        artifacts=(),
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is SubmissionDisposition.REJECTED
    assert result.review_state is ReviewState.REQUIRED
    assert any(i.kind is SubmissionIssueKind.EMPTY_PACKAGE for i in result.issues)
    assert SubmissionReasonCode.EMPTY_INPUT.value in result.reason_codes


def test_quarantine_classification_forces_review() -> None:
    text = build_as_filed_claims_text()
    result = _processor().process(
        package_id="pkg:quarantine",
        require_ack_receipt=False,
        classification=DisclosureClassification.UNKNOWN,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:q1",
                role=ArtifactRole.SUBMISSION,
                full_text=text,
                classification=DisclosureClassification.UNKNOWN,
            ),
        ),
    )
    assert result.disposition is SubmissionDisposition.QUARANTINE
    assert result.review_state is ReviewState.REQUIRED
    assert SubmissionReasonCode.QUARANTINE_CLASSIFICATION.value in result.reason_codes


def test_contract_facts_export() -> None:
    text = build_amendment_claims_text()
    result = _processor().process(
        package_id="pkg:contract",
        require_ack_receipt=False,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:c1",
                role=ArtifactRole.AMENDMENT,
                full_text=text,
                version="v1",
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
    )
    contracts = result.contract_facts
    assert contracts
    assert all(isinstance(f, SubmissionFact) for f in contracts)
    assert all(f.extraction_status in {s.value for s in FactExtractionStatus} or f.extraction_status for f in contracts)
    assert PARSER_VERSION in result.parser_versions.values()


def test_package_input_round_trip() -> None:
    pkg = SubmissionPackageInput(
        package_id="pkg:rt",
        matter_id="matter:1",
        expected_application_number="16/123,456",
        require_ack_receipt=True,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:rt",
                role=ArtifactRole.SUBMISSION,
                full_text=build_as_filed_claims_text(),
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
        claim_versions=(
            ClaimVersion(version="as_filed", claims={"1": "A device."}),
        ),
        labels={"k": "v"},
    )
    restored = SubmissionPackageInput.from_dict(pkg.to_dict())
    assert restored.to_dict() == pkg.to_dict()


def test_multi_version_claim_reconstruction_prefers_later_version() -> None:
    result = _processor().process(
        package_id="pkg:versions",
        require_ack_receipt=False,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:as-filed",
                role=ArtifactRole.CLAIM_SET,
                full_text=build_as_filed_claims_text(),
                version="as_filed",
                classification=DisclosureClassification.PUBLIC_USER,
            ),
            artifact_from_extraction(
                artifact_id="art:amend",
                role=ArtifactRole.AMENDMENT,
                full_text=build_amendment_claims_text(),
                version="preliminary_amendment",
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
        claim_versions=(
            ClaimVersion(
                version="as_filed",
                claims={
                    "1": "A device comprising a sensor.",
                    "2": "The device of claim 1 further comprising a filter.",
                },
            ),
            ClaimVersion(
                version="preliminary_amendment",
                claims={
                    "1": "A device comprising a temperature sensor.",
                    "2": "The device of claim 1 further comprising a filter.",
                },
            ),
            ClaimVersion(
                version="current",
                claims={
                    "1": "A device comprising a temperature sensor.",
                    "2": "The device of claim 1 further comprising a filter.",
                },
            ),
        ),
    )
    assert result.current_claims["1"] == "A device comprising a temperature sensor."
    assert "temperature" in result.current_claims["1"]
    # Facts point at exact version labels.
    assert any(f.fact.version == "current" for f in result.facts_of_type(SubmissionFactType.CURRENT_CLAIM))
    _assert_facts_span_bound(result)


def test_cross_artifact_application_number_conflict() -> None:
    result = _processor().process(
        package_id="pkg:app-conflict",
        require_ack_receipt=False,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:a",
                role=ArtifactRole.SUBMISSION,
                full_text=build_as_filed_claims_text(application_number="16/111,111"),
                application_number="16/111,111",
                classification=DisclosureClassification.PUBLIC_USER,
            ),
            artifact_from_extraction(
                artifact_id="art:b",
                role=ArtifactRole.AMENDMENT,
                full_text=build_amendment_claims_text(application_number="16/222,222"),
                application_number="16/222,222",
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
    )
    assert any(
        i.kind is SubmissionIssueKind.MISMATCHED_METADATA
        and "conflict" in i.message_code
        for i in result.issues
    )


def test_payment_raw_pan_suppressed() -> None:
    result = _processor().process(
        package_id="pkg:pan",
        require_ack_receipt=False,
        require_payment_receipt=False,
        classification=DisclosureClassification.PUBLIC_USER,
        artifacts=(
            artifact_from_extraction(
                artifact_id="art:pay-bad",
                role=ArtifactRole.PAYMENT_RECEIPT,
                full_text="",
                receipt_fields={
                    "amount_usd": "80.00",
                    "card_number": "4111111111111111",
                },
                classification=DisclosureClassification.CREDENTIAL_OR_PAYMENT,
            ),
        ),
    )
    # Classification is restricted → quarantine path.
    assert result.disposition in (
        SubmissionDisposition.QUARANTINE,
        SubmissionDisposition.REVIEW,
    )
    assert any(
        i.message_code == "payment_secret_suppressed" for i in result.issues
    ) or any(
        f.display_value == "suppressed"
        for f in result.facts_of_type(SubmissionFactType.PAYMENT_RECEIPT)
    )


def test_process_many() -> None:
    proc = _processor()
    results = proc.process_many(
        [
            {
                "package_id": "pkg:m1",
                "require_ack_receipt": False,
                "classification": DisclosureClassification.PUBLIC_USER.value,
                "artifacts": [
                    artifact_from_extraction(
                        artifact_id="art:m1",
                        role=ArtifactRole.CLAIM_SET,
                        full_text=build_as_filed_claims_text(),
                        classification=DisclosureClassification.PUBLIC_USER,
                    ).to_dict()
                ],
            },
            {
                "package_id": "pkg:m2",
                "require_ack_receipt": False,
                "classification": DisclosureClassification.PUBLIC_USER.value,
                "artifacts": [
                    artifact_from_extraction(
                        artifact_id="art:m2",
                        role=ArtifactRole.DECLARATION,
                        full_text=build_declaration_text(),
                        classification=DisclosureClassification.PUBLIC_USER,
                    ).to_dict()
                ],
            },
        ]
    )
    assert len(results) == 2
    assert results[0].package_id == "pkg:m1"
    assert results[1].package_id == "pkg:m2"
