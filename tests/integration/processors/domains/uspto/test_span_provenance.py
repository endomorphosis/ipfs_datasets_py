"""Integration tests: extraction provenance → span validation (PATLAW-034).

Exercises the real PATLAW-031 document extractor with compact synthetic
fixtures, then runs span assurance. Prefer generators over golden dumps.
"""

from __future__ import annotations

import json
import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    SubmissionFact,
    CONTRACTS_SCHEMA_VERSION,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.document_extraction_processor import (
    DocumentExtractionInput,
    DocumentExtractionProcessor,
    MediaFamily,
    PageStatus,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.span_validator import (
    SPAN_VALIDATOR_SCHEMA_VERSION,
    SemanticCitation,
    SpanValidationDisposition,
    SpanValidationPolicy,
    SpanValidationReasonCode,
    SpanValidator,
    admit_semantic_citations,
    text_digest,
    validate_spans,
)
from tests.fixtures.uspto.documents.generators import (
    DOCX_CANARY,
    NATIVE_CANARY,
    SCANNED_CANARY,
    build_docx_application,
    build_native_pdf_with_metadata,
    build_scanned_image_only_pdf,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extractor(id_prefix: str = "extract:int") -> DocumentExtractionProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"{id_prefix}:{counter['n']:04d}"

    return DocumentExtractionProcessor(id_factory=_ids)


def _validator(id_prefix: str = "spanval:int") -> SpanValidator:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"{id_prefix}:{counter['n']:04d}"

    return SpanValidator(id_factory=_ids)


def _extract_native_pdf(artifact_id: str = "art:int-native") -> tuple:
    pdf = build_native_pdf_with_metadata()
    digest = sha256_hex(pdf)
    proc = _extractor()
    result = proc.extract(
        DocumentExtractionInput(
            artifact_id=artifact_id,
            content_bytes=pdf,
            declared_mime="application/pdf",
            filename="native_metadata.pdf",
            classification=DisclosureClassification.PUBLIC_USER,
            content_sha256=digest,
            labels={"fixture": "native_pdf", "suite": "span_provenance"},
        )
    )
    return result, digest, pdf


# ---------------------------------------------------------------------------
# End-to-end provenance validation
# ---------------------------------------------------------------------------


def test_native_pdf_extraction_passes_span_validation() -> None:
    extraction, digest, _pdf = _extract_native_pdf()
    assert extraction.media_family is MediaFamily.PDF
    assert extraction.page_count >= 1
    assert extraction.spans
    assert extraction.page_coverage
    assert NATIVE_CANARY in extraction.full_text

    # Relax coverage floors: synthetic one-page fixtures are sparse relative to
    # letter-size capacity, which is intentional for compact generators.
    policy = SpanValidationPolicy(
        min_coverage_ratio=0.01,
        min_overall_coverage=0.01,
        min_readability=0.15,
    )
    result = SpanValidator(
        policy=policy,
        id_factory=lambda: "spanval:int:native",
    ).validate(extraction, expected_content_sha256=digest)

    assert result.artifact_id == extraction.artifact_id
    assert result.content_sha256 == digest
    assert result.extraction_id == extraction.extraction_id
    assert not result.unaccounted_pages
    assert not result.invalid_span_ids
    assert not result.stale_span_ids
    assert (
        SpanValidationReasonCode.PAGE_COVERAGE_COMPLETE.value in result.reason_codes
    )
    assert (
        SpanValidationReasonCode.QUOTE_ROUND_TRIP_OK.value in result.reason_codes
        or any(
            s.char_start is None for s in extraction.spans
        )  # only if offsets absent
    )
    # Every span round-trips: page slice digest matches text_digest.
    page_text = extraction.page_texts.get("0", "")
    for span in extraction.spans:
        if span.char_start is None or span.char_end is None:
            continue
        quote = page_text[span.char_start : span.char_end]
        assert text_digest(quote) == span.text_digest
        assert span.artifact_id == extraction.artifact_id

    # Low native coverage on sparse fixtures may still force REVIEW; never INVALID.
    assert result.disposition in (
        SpanValidationDisposition.VALID,
        SpanValidationDisposition.REVIEW,
        SpanValidationDisposition.UNKNOWN,
    )
    assert result.disposition is not SpanValidationDisposition.INVALID

    # Round-trip + public projection privacy.
    restored = type(result).from_dict(result.to_dict())
    assert restored.to_dict() == result.to_dict()
    assert canonical_json(result.to_dict()) == result.to_canonical_json()
    public = result.public_projection()
    blob = json.dumps(public)
    assert NATIVE_CANARY not in blob
    assert "page_texts" not in public


def test_unaccounted_page_after_mutation_fails() -> None:
    extraction, digest, _ = _extract_native_pdf("art:int-unaccounted")
    # Mutate to claim two pages while retaining single coverage receipt.
    data = extraction.to_dict()
    data["page_count"] = 2
    mutated = type(extraction).from_dict(data)
    result = validate_spans(mutated, expected_content_sha256=digest)
    assert result.disposition is SpanValidationDisposition.INVALID
    assert 1 in result.unaccounted_pages
    assert any(
        f.reason_code == SpanValidationReasonCode.UNACCOUNTED_PAGE.value
        for f in result.findings
    )


def test_stale_span_after_digest_tamper_fails() -> None:
    extraction, digest, _ = _extract_native_pdf("art:int-stale")
    assert extraction.spans
    data = extraction.to_dict()
    # Tamper first span's text_digest to simulate a stale provenance record.
    data["spans"][0]["text_digest"] = sha256_hex(b"tampered-stale-digest-payload")
    mutated = type(extraction).from_dict(data)
    result = validate_spans(mutated, expected_content_sha256=digest)
    assert result.disposition is SpanValidationDisposition.INVALID
    assert result.stale_span_ids
    codes = {f.reason_code for f in result.findings}
    assert SpanValidationReasonCode.STALE_SPAN.value in codes
    assert SpanValidationReasonCode.TEXT_DIGEST_MISMATCH.value in codes


def test_semantic_citation_requires_matching_artifact_version() -> None:
    extraction, digest, _ = _extract_native_pdf("art:int-cite")
    first_span = extraction.spans[0]

    good = SemanticCitation(
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        citation_id="cite:int-good",
        span_id=first_span.span_id,
        artifact_id=extraction.artifact_id,
        content_sha256=digest,
        version="1",
        kind="submission_fact",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    bad_version = SemanticCitation(
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        citation_id="cite:int-bad-ver",
        span_id=first_span.span_id,
        artifact_id=extraction.artifact_id,
        content_sha256=sha256_hex(b"other-artifact-bytes"),
        version="9",
        kind="submission_fact",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    missing_span = SemanticCitation(
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        citation_id="cite:int-missing",
        span_id="span:does-not-exist-int",
        artifact_id=extraction.artifact_id,
        content_sha256=digest,
        version="1",
        kind="assessment",
        classification=DisclosureClassification.PUBLIC_USER,
    )

    policy = SpanValidationPolicy(
        min_coverage_ratio=0.01,
        min_overall_coverage=0.01,
        min_readability=0.1,
    )
    result = SpanValidator(policy=policy).validate(
        extraction,
        expected_content_sha256=digest,
        citations=[good, bad_version, missing_span],
    )
    assert "cite:int-good" in result.admitted_citation_ids
    assert "cite:int-bad-ver" in result.rejected_citation_ids
    assert "cite:int-missing" in result.rejected_citation_ids
    assert result.disposition is SpanValidationDisposition.INVALID
    assert any(
        f.reason_code == SpanValidationReasonCode.ARTIFACT_VERSION_MISMATCH.value
        for f in result.findings
    )
    assert any(
        f.reason_code == SpanValidationReasonCode.CITATION_SPAN_MISSING.value
        for f in result.findings
    )


def test_submission_fact_adapter_admission() -> None:
    extraction, digest, _ = _extract_native_pdf("art:int-fact")
    span = extraction.spans[0]
    fact = SubmissionFact(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        fact_id="fact:int-1",
        evidence_span_id=span.span_id,
        fact_type="filing_metadata",
        affected_claims=(),
        version="1",
        extraction_status="extracted",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    cite = SemanticCitation.from_submission_fact(
        fact,
        artifact_id=extraction.artifact_id,
        content_sha256=digest,
    )
    policy = SpanValidationPolicy(
        min_coverage_ratio=0.01,
        min_overall_coverage=0.01,
        min_readability=0.1,
    )
    result = admit_semantic_citations(extraction, [cite], policy=policy)
    assert cite.citation_id in result.admitted_citation_ids
    assert not result.rejected_citation_ids


def test_ocr_disagreement_retained_through_validation() -> None:
    """Scanned page + injected OCR that disagrees with sparse native text."""
    pdf = build_scanned_image_only_pdf()
    digest = sha256_hex(pdf)
    # Inject OCR that differs from any residual native text (image-only).
    ocr_text = f"{SCANNED_CANARY} OCR-DISAGREE-VARIANT-ZZZ"
    proc = _extractor("extract:ocr")
    extraction = proc.extract(
        DocumentExtractionInput(
            artifact_id="art:int-ocr",
            content_bytes=pdf,
            declared_mime="application/pdf",
            filename="scanned.pdf",
            classification=DisclosureClassification.PUBLIC_USER,
            content_sha256=digest,
            force_ocr=True,
            ocr_by_page={
                0: {
                    "text": ocr_text,
                    "confidence": 0.55,
                    "status": "ok",
                    "engine": "fixture",
                }
            },
            labels={"fixture": "scanned_ocr"},
        )
    )
    assert extraction.page_count >= 1
    # If extractor recorded disagreement or OCR origin, validator must retain it.
    policy = SpanValidationPolicy(
        min_coverage_ratio=0.0,
        min_overall_coverage=0.0,
        min_readability=0.0,
    )
    result = SpanValidator(policy=policy).validate(
        extraction, expected_content_sha256=digest
    )

    any_disagreement = any(c.disagreement for c in extraction.page_coverage) or any(
        c.status is PageStatus.DISAGREEMENT for c in extraction.page_coverage
    )
    ocr_present = any(
        "ocr" in c.origins_present for c in extraction.page_coverage
    ) or any(c.has_ocr_text for c in extraction.page_coverage)

    if any_disagreement:
        assert result.retained_disagreements
        assert any(
            f.reason_code == SpanValidationReasonCode.DISAGREEMENT_RETAINED.value
            for f in result.findings
        )
        # Disagreement never yields silent VALID.
        assert result.disposition is not SpanValidationDisposition.VALID
    elif ocr_present:
        # OCR without disagreement is fine; ensure spans still provenance-bound.
        assert extraction.spans
        for span in extraction.spans:
            assert span.artifact_id == extraction.artifact_id
    # Validation must not invent body text into public projection.
    assert SCANNED_CANARY not in json.dumps(result.public_projection())


def test_docx_extraction_span_provenance() -> None:
    docx = build_docx_application()
    digest = sha256_hex(docx)
    proc = _extractor("extract:docx")
    extraction = proc.extract(
        DocumentExtractionInput(
            artifact_id="art:int-docx",
            content_bytes=docx,
            declared_mime=(
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
            filename="application.docx",
            classification=DisclosureClassification.PUBLIC_USER,
            content_sha256=digest,
            labels={"fixture": "docx"},
        )
    )
    assert extraction.media_family is MediaFamily.DOCX
    assert DOCX_CANARY in extraction.full_text or extraction.spans

    policy = SpanValidationPolicy(
        min_coverage_ratio=0.01,
        min_overall_coverage=0.01,
        min_readability=0.1,
        require_page_index_for_pdf=True,  # DOCX may omit strict PDF page rules
    )
    result = SpanValidator(policy=policy).validate(
        extraction, expected_content_sha256=digest
    )
    assert not result.unaccounted_pages
    assert not result.stale_span_ids
    assert result.disposition is not SpanValidationDisposition.INVALID or (
        # Archive-like empty edge should not apply to DOCX with text.
        extraction.page_count == 0
    )
    if extraction.spans and extraction.page_count > 0:
        # Quote round-trip for spans with character offsets.
        for span in extraction.spans:
            if span.page_index is None or span.char_start is None or span.char_end is None:
                continue
            page_text = extraction.page_texts.get(str(span.page_index), "")
            if not page_text:
                continue
            quote = page_text[span.char_start : span.char_end]
            assert text_digest(quote) == span.text_digest

    public = result.public_projection()
    assert DOCX_CANARY not in json.dumps(public)


def test_low_readability_policy_unknown_on_synthetic_garbage_ocr() -> None:
    """Low-readability OCR injection yields unknown/review, not VALID."""
    pdf = build_scanned_image_only_pdf()
    digest = sha256_hex(pdf)
    garbage = "@@@ ### $$$ %%% ^^^ &&& *** ~~~ ``` ||| {{{ }}}"
    proc = _extractor("extract:garbage")
    extraction = proc.extract(
        DocumentExtractionInput(
            artifact_id="art:int-garbage",
            content_bytes=pdf,
            declared_mime="application/pdf",
            filename="scanned_garbage.pdf",
            classification=DisclosureClassification.PUBLIC_USER,
            content_sha256=digest,
            force_ocr=True,
            ocr_by_page={
                0: {
                    "text": garbage,
                    "confidence": 0.1,
                    "status": "low_confidence",
                    "engine": "fixture",
                }
            },
        )
    )
    policy = SpanValidationPolicy(
        min_readability=0.55,
        min_coverage_ratio=0.0,
        min_overall_coverage=0.0,
    )
    result = SpanValidator(policy=policy).validate(
        extraction, expected_content_sha256=digest
    )
    assert result.disposition in (
        SpanValidationDisposition.UNKNOWN,
        SpanValidationDisposition.REVIEW,
        SpanValidationDisposition.INVALID,
    )
    assert result.disposition is not SpanValidationDisposition.VALID
    assert result.review_state is ReviewState.REQUIRED
    # When text is present and unreadable, low_readability should surface.
    if any(extraction.page_texts.get(str(i), "").strip() for i in range(extraction.page_count)):
        assert (
            SpanValidationReasonCode.LOW_READABILITY.value in result.reason_codes
            or any(
                f.reason_code == SpanValidationReasonCode.LOW_READABILITY.value
                for f in result.findings
            )
            or result.disposition is SpanValidationDisposition.INVALID
        )


def test_mismatched_expected_content_digest_blocks_semantic_use() -> None:
    extraction, digest, _ = _extract_native_pdf("art:int-version-block")
    wrong = sha256_hex(b"not-the-bytes")
    result = validate_spans(extraction, expected_content_sha256=wrong)
    assert result.disposition is SpanValidationDisposition.INVALID
    assert any(
        f.reason_code == SpanValidationReasonCode.CONTENT_DIGEST_MISMATCH.value
        for f in result.findings
    )
    # Even a well-formed citation against the extraction cannot be used when
    # the caller bound the wrong expected version.
    if extraction.spans:
        cite = SemanticCitation(
            schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
            citation_id="cite:blocked",
            span_id=extraction.spans[0].span_id,
            artifact_id=extraction.artifact_id,
            content_sha256=wrong,
            version="1",
            kind="submission_fact",
            classification=DisclosureClassification.PUBLIC_USER,
        )
        result2 = validate_spans(
            extraction,
            expected_content_sha256=wrong,
            citations=[cite],
        )
        assert "cite:blocked" in result2.rejected_citation_ids or result2.is_invalid
