"""Unit tests for USPTO document classifier (PATLAW-030)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    AuthorityRelation,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.document_classifier import (
    DOCUMENT_CLASSIFIER_SCHEMA_VERSION,
    ArtifactAuthorityRole,
    ClassificationDisposition,
    ClassificationReasonCode,
    ClassificationSource,
    DocumentClassification,
    DocumentClassificationInput,
    DocumentClassifier,
    DocumentClassifierError,
    UsptoDocumentKind,
    authority_role_to_relation,
    classify_document,
    detect_media_from_bytes,
    media_types_compatible,
    normalize_matter_key,
)

PDF_BYTES = b"""%PDF-1.4
1 0 obj<<>>endobj
trailer<<>>
%%EOF
"""
# Minimal ZIP / DOCX-like magic (not a full package).
DOCX_MAGIC = b"PK\x03\x04" + b"\x00" * 28
XML_BYTES = b'<?xml version="1.0"?><doc xmlns="urn:uspto"/>'
TEXT_BYTES = b"This is plain text content for a receipt."


def _assert_round_trip(record: DocumentClassification) -> None:
    first = record.to_dict()
    restored = DocumentClassification.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert (
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == canonical_json(first)
    )
    assert restored == record


def _classifier() -> DocumentClassifier:
    # Stable ids for assertions.
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"classif:test:{counter['n']:04d}"

    return DocumentClassifier(id_factory=_ids)


# ---------------------------------------------------------------------------
# Media helpers
# ---------------------------------------------------------------------------


def test_detect_media_from_bytes() -> None:
    assert detect_media_from_bytes(PDF_BYTES) == "application/pdf"
    assert detect_media_from_bytes(DOCX_MAGIC) == "application/zip"
    assert detect_media_from_bytes(XML_BYTES) == "application/xml"
    assert detect_media_from_bytes(TEXT_BYTES) == "text/plain"
    assert detect_media_from_bytes(None) is None
    assert detect_media_from_bytes(b"") is None


def test_media_types_compatible_docx_zip() -> None:
    docx = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert media_types_compatible(docx, "application/zip")
    assert media_types_compatible("application/pdf", "application/pdf")
    assert not media_types_compatible("application/pdf", "application/zip")
    assert media_types_compatible(None, "application/pdf")
    assert media_types_compatible("PDF", "application/pdf")


def test_normalize_matter_key_application_numbers() -> None:
    a = normalize_matter_key("16/123,456")
    b = normalize_matter_key("16123456")
    c = normalize_matter_key("matter:16/123456")
    assert a == b == c == "16123456"
    assert normalize_matter_key(None) is None


def test_authority_role_to_relation_mapping() -> None:
    assert (
        authority_role_to_relation(ArtifactAuthorityRole.AUTHORITATIVE)
        is AuthorityRelation.AUTHORITATIVE_ORIGINAL
    )
    assert (
        authority_role_to_relation(ArtifactAuthorityRole.DERIVATIVE)
        is AuthorityRelation.DERIVATIVE
    )
    assert (
        authority_role_to_relation(ArtifactAuthorityRole.SUPPLEMENTAL)
        is AuthorityRelation.UNKNOWN
    )
    assert (
        authority_role_to_relation(ArtifactAuthorityRole.UNKNOWN)
        is AuthorityRelation.UNKNOWN
    )


# ---------------------------------------------------------------------------
# Kind classification by document code / description
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "description", "expected_kind", "mime", "body"),
    [
        ("CTNF", "Non-Final Rejection", UsptoDocumentKind.OFFICE_ACTION, "application/pdf", PDF_BYTES),
        ("CTFR", "Final Rejection", UsptoDocumentKind.OFFICE_ACTION, "application/pdf", PDF_BYTES),
        ("NOA", "Notice of Allowance", UsptoDocumentKind.NOTICE, "application/pdf", PDF_BYTES),
        ("CLM", "Claims", UsptoDocumentKind.SUBMISSION, "application/pdf", PDF_BYTES),
        ("SPEC", "Specification", UsptoDocumentKind.SUBMISSION, "application/pdf", PDF_BYTES),
        ("N417", "Electronic Acknowledgement Receipt", UsptoDocumentKind.ACKNOWLEDGEMENT, "application/pdf", PDF_BYTES),
        ("WFEE", "Fee Worksheet", UsptoDocumentKind.PAYMENT_RECEIPT, "application/pdf", PDF_BYTES),
        ("DECL", "Declaration", UsptoDocumentKind.DECLARATION, "application/pdf", PDF_BYTES),
        ("IDS", "Information Disclosure Statement", UsptoDocumentKind.CITATION, "application/pdf", PDF_BYTES),
        ("NPL", "Non-Patent Literature", UsptoDocumentKind.CITATION, "application/pdf", PDF_BYTES),
        (
            "APP.FILE.DOCX",
            "Original DOCX",
            UsptoDocumentKind.DOCX_ORIGINAL,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            DOCX_MAGIC,
        ),
        ("APP.FILE.PDF", "Converted PDF", UsptoDocumentKind.PDF_CONVERSION, "application/pdf", PDF_BYTES),
        ("ADS", "Application Data Sheet", UsptoDocumentKind.FORM, "application/pdf", PDF_BYTES),
    ],
)
def test_classify_known_document_codes(
    code: str,
    description: str,
    expected_kind: UsptoDocumentKind,
    mime: str,
    body: bytes,
) -> None:
    result = _classifier().classify(
        document_code=code,
        document_description=description,
        declared_mime=mime,
        content_bytes=body,
        expected_matter_id="16/123,456",
        observed_matter_id="16123456",
    )
    assert result.document_kind is expected_kind
    assert result.confidence >= 0.9
    assert ClassificationSource.DOCUMENT_CODE.value in result.sources
    assert result.reasons
    assert result.retained is True
    assert result.schema_version == DOCUMENT_CLASSIFIER_SCHEMA_VERSION
    _assert_round_trip(result)


def test_office_action_has_confidence_reasons_and_source() -> None:
    result = classify_document(
        document_code="CTNF",
        document_description="Non-Final Rejection",
        mime_type_identifier="PDF",
        content_bytes=PDF_BYTES,
    )
    assert result.document_kind is UsptoDocumentKind.OFFICE_ACTION
    assert result.authority_role is ArtifactAuthorityRole.AUTHORITATIVE
    assert result.authority_relation is AuthorityRelation.AUTHORITATIVE_ORIGINAL
    assert 0.0 <= result.confidence <= 1.0
    assert result.confidence >= 0.9
    assert any("document_code" in r for r in result.reasons)
    assert ClassificationSource.DOCUMENT_CODE.value in result.sources
    assert ClassificationReasonCode.MATCHED_DOCUMENT_CODE.value in result.reason_codes
    assert result.disposition is ClassificationDisposition.CLASSIFIED
    assert result.review_state is ReviewState.NOT_REQUIRED
    assert result.retained is True


def test_description_only_classification() -> None:
    result = _classifier().classify(
        document_description="Electronic Acknowledgement Receipt",
        content_bytes=PDF_BYTES,
        declared_mime="application/pdf",
    )
    assert result.document_kind is UsptoDocumentKind.ACKNOWLEDGEMENT
    assert ClassificationSource.DESCRIPTION.value in result.sources
    assert result.confidence >= 0.7
    assert result.retained is True


def test_content_preview_classification() -> None:
    result = _classifier().classify(
        content_preview=(
            "UNITED STATES PATENT AND TRADEMARK OFFICE\n"
            "This Office Action is responsive to the amendment filed.\n"
            "Claim rejection under 35 U.S.C. § 103.\n"
        ),
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
    )
    assert result.document_kind is UsptoDocumentKind.OFFICE_ACTION
    assert ClassificationSource.CONTENT_TEXT.value in result.sources
    assert result.retained is True


def test_filename_classification() -> None:
    result = _classifier().classify(
        filename="matter_16123456_payment_receipt.pdf",
        content_bytes=PDF_BYTES,
        declared_mime="application/pdf",
    )
    assert result.document_kind is UsptoDocumentKind.PAYMENT_RECEIPT
    assert ClassificationSource.FILENAME.value in result.sources


# ---------------------------------------------------------------------------
# Authority roles: authoritative / derivative / supplemental
# ---------------------------------------------------------------------------


def test_citation_is_supplemental() -> None:
    result = _classifier().classify(
        document_code="NPL",
        document_description="Non-Patent Literature",
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
    )
    assert result.document_kind is UsptoDocumentKind.CITATION
    assert result.authority_role is ArtifactAuthorityRole.SUPPLEMENTAL
    assert ClassificationReasonCode.SUPPLEMENTAL_CITATION.value in result.reason_codes


def test_pdf_conversion_with_parent_is_derivative() -> None:
    result = _classifier().classify(
        document_code="APP.FILE.PDF",
        document_description="USPTO-converted PDF of DOCX",
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
        parent_artifact_ids=("artifact:docx:1",),
    )
    assert result.document_kind is UsptoDocumentKind.PDF_CONVERSION
    assert result.authority_role is ArtifactAuthorityRole.DERIVATIVE
    assert result.authority_relation is AuthorityRelation.DERIVATIVE
    assert "artifact:docx:1" in result.parent_artifact_ids
    assert ClassificationSource.PARENT_LINK.value in result.sources


def test_docx_original_is_authoritative() -> None:
    result = _classifier().classify(
        document_code="APP.FILE.DOCX",
        document_description="Original filed DOCX",
        declared_mime=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        content_bytes=DOCX_MAGIC,
    )
    assert result.document_kind is UsptoDocumentKind.DOCX_ORIGINAL
    assert result.authority_role is ArtifactAuthorityRole.AUTHORITATIVE
    assert result.authority_relation is AuthorityRelation.AUTHORITATIVE_ORIGINAL
    # ZIP magic compatible with DOCX MIME — not a conflict.
    assert result.disposition is ClassificationDisposition.CLASSIFIED


def test_link_conversion_pair() -> None:
    clf = _classifier()
    original = clf.classify(
        artifact_id="artifact:docx:1",
        document_code="APP.FILE.DOCX",
        declared_mime=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        content_bytes=DOCX_MAGIC,
    )
    conversion = clf.classify(
        artifact_id="artifact:pdf:1",
        document_code="APP.FILE.PDF",
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
    )
    linked_orig, linked_conv = clf.link_conversion_pair(
        original=original,
        conversion=conversion,
        original_artifact_id="artifact:docx:1",
        conversion_artifact_id="artifact:pdf:1",
    )
    assert linked_orig.authority_role is ArtifactAuthorityRole.AUTHORITATIVE
    assert linked_conv.authority_role is ArtifactAuthorityRole.DERIVATIVE
    assert linked_conv.document_kind is UsptoDocumentKind.PDF_CONVERSION
    assert "artifact:docx:1" in linked_conv.parent_artifact_ids
    assert "artifact:pdf:1" in linked_orig.related_artifact_ids
    assert linked_orig.retained and linked_conv.retained
    assert ClassificationReasonCode.CONVERSION_PAIR.value in linked_conv.reason_codes
    _assert_round_trip(linked_orig)
    _assert_round_trip(linked_conv)


# ---------------------------------------------------------------------------
# Conflicts → quarantine / review; wrong matter ID
# ---------------------------------------------------------------------------


def test_mime_content_conflict_quarantines() -> None:
    result = _classifier().classify(
        document_code="CTNF",
        document_description="Non-Final Rejection",
        declared_mime="application/pdf",
        content_bytes=DOCX_MAGIC,  # ZIP, not PDF
    )
    assert result.disposition is ClassificationDisposition.QUARANTINE
    assert result.review_state is ReviewState.REQUIRED
    assert result.is_quarantined is True
    assert result.requires_review is True
    assert ClassificationReasonCode.MIME_CONTENT_CONFLICT.value in result.reason_codes
    assert result.confidence <= 0.35
    assert result.retained is True  # never silently dropped


def test_document_code_description_conflict_quarantines() -> None:
    result = _classifier().classify(
        document_code="CTNF",  # office action
        document_description="Electronic Acknowledgement Receipt",  # acknowledgement
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
    )
    assert result.disposition is ClassificationDisposition.QUARANTINE
    assert (
        ClassificationReasonCode.DOCUMENT_CODE_DESCRIPTION_CONFLICT.value
        in result.reason_codes
    )
    assert result.retained is True


def test_description_content_conflict_quarantines() -> None:
    result = _classifier().classify(
        document_code="N417",
        document_description="Electronic Acknowledgement Receipt",
        content_preview=(
            "This Office Action rejects claims 1-20 under 35 U.S.C. § 103."
        ),
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
    )
    assert result.disposition is ClassificationDisposition.QUARANTINE
    assert (
        ClassificationReasonCode.DESCRIPTION_CONTENT_CONFLICT.value
        in result.reason_codes
    )
    assert result.retained is True


def test_wrong_matter_id_quarantines() -> None:
    result = _classifier().classify(
        document_code="CLM",
        document_description="Claims",
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
        expected_matter_id="16/123,456",
        observed_matter_id="17/999,999",
    )
    assert result.disposition is ClassificationDisposition.QUARANTINE
    assert ClassificationReasonCode.MATTER_ID_MISMATCH.value in result.reason_codes
    assert result.review_state is ReviewState.REQUIRED
    assert result.retained is True
    assert any("matter" in r.lower() for r in result.reasons)


def test_matching_matter_ids_do_not_quarantine() -> None:
    result = _classifier().classify(
        document_code="CLM",
        document_description="Claims",
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
        expected_matter_id="16/123,456",
        observed_matter_id="16123456",
    )
    assert result.disposition is ClassificationDisposition.CLASSIFIED
    assert ClassificationReasonCode.MATTER_ID_MISMATCH.value not in result.reason_codes
    assert ClassificationSource.MATTER_ID.value in result.sources


# ---------------------------------------------------------------------------
# Unknown artifacts retained
# ---------------------------------------------------------------------------


def test_unknown_artifact_retained_for_review() -> None:
    result = _classifier().classify(
        artifact_id="artifact:mystery:1",
        filename="mystery.bin",
        content_bytes=b"\xff\xfe\x00\x01unknown binary blob",
    )
    assert result.document_kind is UsptoDocumentKind.UNKNOWN
    assert result.is_unknown is True
    assert result.authority_role is ArtifactAuthorityRole.UNKNOWN
    assert result.disposition is ClassificationDisposition.REVIEW
    assert result.review_state is ReviewState.REQUIRED
    assert result.retained is True
    assert ClassificationReasonCode.UNKNOWN_ARTIFACT.value in result.reason_codes
    assert result.confidence < 0.5
    # Must never silently ignore: result exists with full audit trail.
    assert result.classification_id
    assert result.reasons
    assert result.sources
    _assert_round_trip(result)


def test_empty_input_unknown_retained() -> None:
    result = classify_document()
    assert result.document_kind is UsptoDocumentKind.UNKNOWN
    assert result.retained is True
    assert result.disposition is ClassificationDisposition.REVIEW
    assert result.sources  # at least default source


def test_classify_many_retains_all_including_unknown() -> None:
    clf = _classifier()
    results = clf.classify_many(
        [
            {"document_code": "CTNF", "declared_mime": "application/pdf", "content_bytes": PDF_BYTES},
            {"document_code": "NPL", "declared_mime": "application/pdf", "content_bytes": PDF_BYTES},
            {"filename": "unknown.dat"},
        ]
    )
    assert len(results) == 3
    assert results[0].document_kind is UsptoDocumentKind.OFFICE_ACTION
    assert results[1].document_kind is UsptoDocumentKind.CITATION
    assert results[2].document_kind is UsptoDocumentKind.UNKNOWN
    assert all(r.retained for r in results)


# ---------------------------------------------------------------------------
# Mapping / ODP-shaped input and serialization
# ---------------------------------------------------------------------------


def test_odp_mapping_keys_accepted() -> None:
    result = _classifier().classify(
        {
            "documentCode": "CTNF",
            "documentCodeDescriptionText": "Non-Final Rejection",
            "mimeTypeIdentifier": "PDF",
            "content_bytes": PDF_BYTES,
            "artifact_id": "artifact:odp:1",
        }
    )
    assert result.document_kind is UsptoDocumentKind.OFFICE_ACTION
    assert result.declared_mime == "application/pdf"
    assert result.artifact_id == "artifact:odp:1"


def test_explicit_kind_label_wins() -> None:
    result = _classifier().classify(
        document_code="CTNF",
        explicit_kind="form",
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
    )
    assert result.document_kind is UsptoDocumentKind.FORM
    assert ClassificationSource.LABEL.value in result.sources


def test_retained_false_rejected_on_record() -> None:
    with pytest.raises(ValueError, match="retain"):
        DocumentClassification(
            schema_version=DOCUMENT_CLASSIFIER_SCHEMA_VERSION,
            document_kind=UsptoDocumentKind.UNKNOWN,
            authority_role=ArtifactAuthorityRole.UNKNOWN,
            authority_relation=AuthorityRelation.UNKNOWN,
            confidence=0.1,
            reasons=("x",),
            sources=(ClassificationSource.DEFAULT.value,),
            disposition=ClassificationDisposition.REVIEW,
            review_state=ReviewState.REQUIRED,
            reason_codes=(ClassificationReasonCode.UNKNOWN_ARTIFACT.value,),
            document_code=None,
            declared_mime=None,
            detected_media=None,
            expected_matter_id=None,
            observed_matter_id=None,
            parent_artifact_ids=(),
            related_artifact_ids=(),
            labels={},
            retained=False,
            classification_id="classif:x",
            artifact_id=None,
        )


def test_input_record_and_kwargs() -> None:
    inp = DocumentClassificationInput(
        document_code="NOA",
        document_description="Notice of Allowance",
        declared_mime="application/pdf",
        content_bytes=PDF_BYTES,
    )
    result = _classifier().classify(inp)
    assert result.document_kind is UsptoDocumentKind.NOTICE

    with pytest.raises(DocumentClassifierError):
        _classifier().classify(inp, document_code="CTNF")


def test_module_constants_and_interface() -> None:
    assert DOCUMENT_CLASSIFIER_SCHEMA_VERSION == "uspto.document-classifier.v1"
    kinds = {k.value for k in UsptoDocumentKind}
    assert {
        "office_action",
        "notice",
        "submission",
        "docx_original",
        "pdf_conversion",
        "declaration",
        "form",
        "acknowledgement",
        "payment_receipt",
        "citation",
        "unknown",
    } <= kinds
    roles = {r.value for r in ArtifactAuthorityRole}
    assert roles == {
        "authoritative",
        "derivative",
        "supplemental",
        "unknown",
    }
