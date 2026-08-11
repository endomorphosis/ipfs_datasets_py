"""Unit tests for USPTO span coverage/readability validator (PATLAW-034)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
    SubmissionFact,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.document_extraction_processor import (
    DOCUMENT_EXTRACTION_SCHEMA_VERSION,
    DocumentExtractionResult,
    ExtractionDisposition,
    LayoutItem,
    LayoutItemKind,
    MediaFamily,
    PageCoverageRecord,
    PageExtraction,
    PageStatus,
    FilingMetadataField,
)
from ipfs_datasets_py.processors.domains.uspto.span_validator import (
    SPAN_VALIDATOR_SCHEMA_VERSION,
    CitationAdmission,
    FindingSeverity,
    SemanticCitation,
    SpanValidationDisposition,
    SpanValidationPolicy,
    SpanValidationReasonCode,
    SpanValidator,
    admit_semantic_citations,
    estimate_readability,
    extract_quote,
    sha256_hex,
    text_digest,
    validate_spans,
)

# ---------------------------------------------------------------------------
# Fixtures / builders (compact — no golden dumps)
# ---------------------------------------------------------------------------

_DIGEST_A = sha256_hex(b"artifact-bytes-version-a")
_DIGEST_B = sha256_hex(b"artifact-bytes-version-b")
_ART = "art:unit-span-1"
_EXT = "extract:unit:0001"


def _span(
    *,
    span_id: str = "span:unit:1",
    artifact_id: str = _ART,
    page_index: int | None = 0,
    char_start: int | None = 0,
    char_end: int | None = 11,
    text: str = "Hello world",
    origin: ExtractionOrigin = ExtractionOrigin.NATIVE,
    reading_order: int | None = 0,
    bbox: tuple[float, float, float, float] | None = (10.0, 10.0, 100.0, 30.0),
    confidence: float | None = 1.0,
) -> ExtractedSpan:
    return ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id=span_id,
        artifact_id=artifact_id,
        page_index=page_index,
        char_start=char_start,
        char_end=char_end,
        bbox=bbox,
        origin=origin,
        reading_order=reading_order,
        confidence=confidence,
        text_digest=text_digest(text),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )


def _coverage(
    *,
    page_index: int = 0,
    artifact_id: str = _ART,
    coverage_ratio: float = 0.9,
    native_coverage: float = 0.9,
    status: PageStatus = PageStatus.OK,
    disagreement: bool = False,
    disagreement_score: float = 0.0,
    origins: tuple[str, ...] = ("native",),
    render_digest: str | None = None,
    page_width: float | None = 612.0,
    page_height: float | None = 792.0,
    warnings: tuple[str, ...] = (),
    has_native_text: bool = True,
    has_ocr_text: bool = False,
    native_char_count: int = 100,
    ocr_char_count: int = 0,
    merged_char_count: int = 100,
) -> PageCoverageRecord:
    return PageCoverageRecord(
        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
        page_index=page_index,
        artifact_id=artifact_id,
        native_char_count=native_char_count,
        ocr_char_count=ocr_char_count,
        merged_char_count=merged_char_count,
        native_coverage=native_coverage,
        coverage_ratio=coverage_ratio,
        has_native_text=has_native_text,
        has_ocr_text=has_ocr_text,
        rotation=0,
        status=status,
        ocr_status="not_needed" if not has_ocr_text else "applied",
        ocr_confidence=0.9 if has_ocr_text else None,
        origins_present=origins,
        disagreement=disagreement,
        disagreement_score=disagreement_score,
        render_digest=render_digest or sha256_hex(f"render:{page_index}".encode()),
        page_width=page_width,
        page_height=page_height,
        warnings=warnings,
    )


def _extraction(
    *,
    page_text: str = "Hello world",
    spans: list[ExtractedSpan] | None = None,
    page_coverage: list[PageCoverageRecord] | None = None,
    page_count: int | None = None,
    overall_coverage: float = 0.9,
    content_sha256: str = _DIGEST_A,
    artifact_id: str = _ART,
    disposition: ExtractionDisposition = ExtractionDisposition.EXTRACTED,
    review_state: ReviewState = ReviewState.NOT_REQUIRED,
    layout_items: tuple[LayoutItem, ...] = (),
    filing_metadata: tuple[FilingMetadataField, ...] = (),
    media_family: MediaFamily = MediaFamily.PDF,
) -> DocumentExtractionResult:
    if spans is None:
        spans = [
            _span(
                text=page_text,
                char_start=0,
                char_end=len(page_text),
            )
        ]
    if page_coverage is None:
        page_coverage = [_coverage()]
    n_pages = page_count if page_count is not None else len(page_coverage)
    pages = tuple(
        PageExtraction(
            page_index=c.page_index,
            text=page_text if c.page_index == 0 else "",
            span_ids=tuple(
                s.span_id for s in spans if s.page_index == c.page_index
            ),
            coverage=c,
            layout_item_ids=(),
        )
        for c in page_coverage
    )
    page_texts = {str(c.page_index): (page_text if c.page_index == 0 else "") for c in page_coverage}
    if n_pages == 1:
        page_texts["0"] = page_text
    return DocumentExtractionResult(
        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
        extraction_id=_EXT,
        artifact_id=artifact_id,
        media_family=media_family,
        content_sha256=content_sha256,
        disposition=disposition,
        review_state=review_state,
        classification=DisclosureClassification.PUBLIC_USER,
        reason_codes=("native_text_extracted",),
        warnings=(),
        unsupported_features=(),
        overall_coverage=overall_coverage,
        page_count=n_pages,
        pages=pages,
        page_coverage=tuple(page_coverage),
        spans=tuple(spans),
        layout_items=layout_items,
        filing_metadata=filing_metadata,
        differences=(),
        page_texts=page_texts,
        full_text=page_text,
        labels={"fixture": "unit"},
        parser_versions={"extractor": "test"},
        related_artifact_ids=(),
        retained=True,
    )


def _validator(**kwargs: Any) -> SpanValidator:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"spanval:test:{counter['n']:04d}"

    return SpanValidator(id_factory=_ids, **kwargs)


def _assert_round_trip(result) -> None:
    first = result.to_dict()
    restored = type(result).from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    blob = json.dumps(public)
    assert "Hello world" not in blob
    assert "full_text" not in public
    assert "page_texts" not in public


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_estimate_readability() -> None:
    assert estimate_readability("") == 0.0
    assert estimate_readability("!!!@@@###") < 0.3
    assert estimate_readability(
        "The applicant claims a method of purifying a polypeptide composition."
    ) > 0.5
    # Highly repetitive short tokens score lower than varied prose.
    assert estimate_readability("a a a a a a a a a a") < estimate_readability(
        "diverse token sample with legal claim language present"
    )


def test_extract_quote_and_text_digest() -> None:
    page = "Hello world from unit test"
    assert extract_quote(page, 0, 5) == "Hello"
    assert extract_quote(page, 6, 11) == "world"
    assert extract_quote(page, -1, 3) is None
    assert extract_quote(page, 0, 999) is None
    assert extract_quote(page, 5, 3) is None
    assert text_digest("Hello   world") == text_digest("Hello world")


def test_semantic_citation_from_submission_fact() -> None:
    fact = SubmissionFact(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        fact_id="fact:1",
        evidence_span_id="span:unit:1",
        fact_type="claim_amendment",
        affected_claims=("1",),
        version="1",
        extraction_status="extracted",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    cite = SemanticCitation.from_submission_fact(
        fact, artifact_id=_ART, content_sha256=_DIGEST_A
    )
    assert cite.span_id == "span:unit:1"
    assert cite.content_sha256 == _DIGEST_A
    assert cite.kind == "submission_fact"
    assert cite.to_dict()["artifact_id"] == _ART


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_extraction_passes() -> None:
    page = "Applicant hereby amends claim 1 as follows for examination."
    span = _span(text=page, char_start=0, char_end=len(page))
    ex = _extraction(page_text=page, spans=[span], overall_coverage=0.95)
    result = _validator().validate(ex, expected_content_sha256=_DIGEST_A)
    assert result.disposition is SpanValidationDisposition.VALID
    assert result.review_state is ReviewState.NOT_REQUIRED
    assert result.is_valid
    assert not result.unaccounted_pages
    assert not result.invalid_span_ids
    assert not result.stale_span_ids
    assert SpanValidationReasonCode.VALIDATION_PASSED.value in result.reason_codes
    assert SpanValidationReasonCode.PAGE_COVERAGE_COMPLETE.value in result.reason_codes
    assert SpanValidationReasonCode.QUOTE_ROUND_TRIP_OK.value in result.reason_codes
    assert result.schema_version == SPAN_VALIDATOR_SCHEMA_VERSION
    _assert_round_trip(result)


def test_validate_spans_convenience() -> None:
    page = "Convenience wrapper validation path for span assurance unit tests."
    span = _span(text=page, char_start=0, char_end=len(page))
    ex = _extraction(page_text=page, spans=[span])
    result = validate_spans(ex, expected_content_sha256=_DIGEST_A)
    assert result.disposition is SpanValidationDisposition.VALID


# ---------------------------------------------------------------------------
# Invalid / stale spans
# ---------------------------------------------------------------------------


def test_invalid_char_bounds_fail() -> None:
    page = "Hello world"
    # char_end beyond page text
    span = _span(text="Hello world", char_start=0, char_end=500)
    # Override digest so construction is valid but bounds vs page fail
    span = ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id="span:unit:oob",
        artifact_id=_ART,
        page_index=0,
        char_start=0,
        char_end=500,
        bbox=None,
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=1.0,
        text_digest=text_digest("Hello world"),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    ex = _extraction(page_text=page, spans=[span])
    result = _validator().validate(ex)
    assert result.disposition is SpanValidationDisposition.INVALID
    assert "span:unit:oob" in result.invalid_span_ids
    assert any(
        f.reason_code == SpanValidationReasonCode.SPAN_BOUNDS_INVALID.value
        for f in result.findings
    )


def test_stale_text_digest_fails() -> None:
    page = "Current page text content here"
    span = ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id="span:unit:stale",
        artifact_id=_ART,
        page_index=0,
        char_start=0,
        char_end=len(page),
        bbox=None,
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=1.0,
        text_digest=text_digest("completely different stale quote"),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    ex = _extraction(page_text=page, spans=[span])
    result = _validator().validate(ex)
    assert result.is_invalid
    assert "span:unit:stale" in result.stale_span_ids
    codes = {f.reason_code for f in result.findings}
    assert SpanValidationReasonCode.STALE_SPAN.value in codes
    assert SpanValidationReasonCode.TEXT_DIGEST_MISMATCH.value in codes
    assert SpanValidationReasonCode.QUOTE_ROUND_TRIP_FAILED.value in codes


def test_span_artifact_mismatch_fails() -> None:
    page = "Artifact binding test text for mismatch."
    span = _span(
        span_id="span:unit:wrong-art",
        artifact_id="art:other-version",
        text=page,
        char_start=0,
        char_end=len(page),
    )
    ex = _extraction(page_text=page, spans=[span])
    result = _validator().validate(ex)
    assert result.is_invalid
    assert any(
        f.reason_code == SpanValidationReasonCode.SPAN_ARTIFACT_MISMATCH.value
        for f in result.findings
    )


def test_content_digest_mismatch_fails() -> None:
    page = "Version binding for expected content digest."
    span = _span(text=page, char_start=0, char_end=len(page))
    ex = _extraction(page_text=page, spans=[span], content_sha256=_DIGEST_A)
    result = _validator().validate(ex, expected_content_sha256=_DIGEST_B)
    assert result.is_invalid
    assert any(
        f.reason_code == SpanValidationReasonCode.CONTENT_DIGEST_MISMATCH.value
        for f in result.findings
    )


# ---------------------------------------------------------------------------
# Unaccounted pages
# ---------------------------------------------------------------------------


def test_unaccounted_pages_fail() -> None:
    page = "Only page zero is covered in this fixture."
    span = _span(text=page, char_start=0, char_end=len(page))
    # page_count=2 but only page 0 coverage
    ex = _extraction(
        page_text=page,
        spans=[span],
        page_coverage=[_coverage(page_index=0)],
        page_count=2,
    )
    result = _validator().validate(ex)
    assert result.is_invalid
    assert 1 in result.unaccounted_pages
    assert any(
        f.reason_code == SpanValidationReasonCode.UNACCOUNTED_PAGE.value
        for f in result.findings
    )


def test_duplicate_page_coverage_fails() -> None:
    page = "Duplicate coverage indices are invalid."
    span = _span(text=page, char_start=0, char_end=len(page))
    cov = _coverage(page_index=0)
    ex = _extraction(
        page_text=page,
        spans=[span],
        page_coverage=[cov, cov],
        page_count=1,
    )
    result = _validator().validate(ex)
    assert result.is_invalid
    assert any(
        f.reason_code == SpanValidationReasonCode.DUPLICATE_PAGE_INDEX.value
        for f in result.findings
    )


# ---------------------------------------------------------------------------
# Disagreement retained
# ---------------------------------------------------------------------------


def test_disagreement_is_retained() -> None:
    page = "Native text that disagrees with OCR injection content."
    span = _span(text=page, char_start=0, char_end=len(page))
    cov = _coverage(
        coverage_ratio=0.85,
        disagreement=True,
        disagreement_score=0.42,
        origins=("native", "ocr"),
        has_ocr_text=True,
        ocr_char_count=80,
        status=PageStatus.DISAGREEMENT,
        warnings=("native_ocr_disagreement",),
    )
    ex = _extraction(
        page_text=page,
        spans=[span],
        page_coverage=[cov],
        overall_coverage=0.85,
        disposition=ExtractionDisposition.REVIEW,
        review_state=ReviewState.REQUIRED,
    )
    result = _validator().validate(ex)
    assert result.retained_disagreements
    assert result.retained_disagreements[0].page_index == 0
    assert result.retained_disagreements[0].disagreement_score == pytest.approx(0.42)
    assert any(
        f.reason_code == SpanValidationReasonCode.DISAGREEMENT_RETAINED.value
        for f in result.findings
    )
    # Disagreement forces review (not silent valid).
    assert result.disposition in (
        SpanValidationDisposition.REVIEW,
        SpanValidationDisposition.UNKNOWN,
        SpanValidationDisposition.INVALID,
    )
    assert result.requires_review
    # Disagreement must appear in serialized form (retained).
    assert result.to_dict()["retained_disagreements"]
    _assert_round_trip(result)


def test_dropped_disagreement_flag_restored() -> None:
    page = "Warnings indicate disagreement but flag was cleared incorrectly."
    span = _span(text=page, char_start=0, char_end=len(page))
    cov = _coverage(
        coverage_ratio=0.8,
        disagreement=False,
        disagreement_score=0.0,
        origins=("native", "ocr"),
        has_ocr_text=True,
        warnings=("native_ocr_disagreement",),
    )
    ex = _extraction(page_text=page, spans=[span], page_coverage=[cov])
    result = _validator().validate(ex)
    assert any(
        f.reason_code == SpanValidationReasonCode.DISAGREEMENT_DROPPED.value
        for f in result.findings
    )
    assert result.retained_disagreements
    assert "disagreement_flag_restored" in result.retained_disagreements[0].warnings


# ---------------------------------------------------------------------------
# Low readability → unknown/review
# ---------------------------------------------------------------------------


def test_low_readability_creates_unknown_or_review() -> None:
    # High coverage of near-garbage symbols → low readability.
    page = "@@@ ### $$$ %%% ^^^ &&& *** ((( ))) ___ +++ ==="
    span = ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id="span:unit:low-read",
        artifact_id=_ART,
        page_index=0,
        char_start=0,
        char_end=len(page),
        bbox=None,
        origin=ExtractionOrigin.OCR,
        reading_order=0,
        confidence=0.2,
        text_digest=text_digest(page),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    cov = _coverage(
        coverage_ratio=0.9,
        native_coverage=0.1,
        origins=("ocr",),
        has_native_text=False,
        has_ocr_text=True,
        status=PageStatus.OK,
    )
    policy = SpanValidationPolicy(
        min_readability=0.5,
        min_coverage_ratio=0.2,
        min_overall_coverage=0.2,
    )
    ex = _extraction(
        page_text=page,
        spans=[span],
        page_coverage=[cov],
        overall_coverage=0.9,
    )
    result = _validator(policy=policy).validate(ex)
    assert result.disposition in (
        SpanValidationDisposition.UNKNOWN,
        SpanValidationDisposition.REVIEW,
    )
    assert result.review_state is ReviewState.REQUIRED
    assert result.requires_review
    assert any(
        f.reason_code == SpanValidationReasonCode.LOW_READABILITY.value
        for f in result.findings
    )
    assert result.overall_readability < 0.5


def test_low_coverage_creates_review() -> None:
    page = "Sparse"
    span = _span(text=page, char_start=0, char_end=len(page), bbox=None)
    cov = _coverage(
        coverage_ratio=0.05,
        native_coverage=0.05,
        status=PageStatus.LOW_COVERAGE,
        native_char_count=6,
        merged_char_count=6,
    )
    ex = _extraction(
        page_text=page,
        spans=[span],
        page_coverage=[cov],
        overall_coverage=0.05,
        disposition=ExtractionDisposition.REVIEW,
        review_state=ReviewState.REQUIRED,
    )
    result = _validator().validate(ex)
    assert result.disposition in (
        SpanValidationDisposition.REVIEW,
        SpanValidationDisposition.UNKNOWN,
        SpanValidationDisposition.INVALID,
    )
    assert result.requires_review
    assert any(
        f.reason_code == SpanValidationReasonCode.LOW_COVERAGE.value
        for f in result.findings
    )


# ---------------------------------------------------------------------------
# Semantic citations / artifact version
# ---------------------------------------------------------------------------


def test_citation_admitted_when_version_matches() -> None:
    page = "Exact evidence span text for admitted citation."
    span = _span(
        span_id="span:unit:cite-ok",
        text=page,
        char_start=0,
        char_end=len(page),
    )
    ex = _extraction(page_text=page, spans=[span], content_sha256=_DIGEST_A)
    cite = SemanticCitation(
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        citation_id="cite:ok-1",
        span_id="span:unit:cite-ok",
        artifact_id=_ART,
        content_sha256=_DIGEST_A,
        version="1",
        kind="submission_fact",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    result = _validator().validate(ex, citations=[cite])
    assert "cite:ok-1" in result.admitted_citation_ids
    assert not result.rejected_citation_ids
    assert result.citation_records[0].admission is CitationAdmission.ADMITTED


def test_citation_rejected_for_missing_span() -> None:
    page = "Citation targets a span that does not exist."
    span = _span(text=page, char_start=0, char_end=len(page))
    ex = _extraction(page_text=page, spans=[span], content_sha256=_DIGEST_A)
    cite = SemanticCitation(
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        citation_id="cite:missing-span",
        span_id="span:does-not-exist",
        artifact_id=_ART,
        content_sha256=_DIGEST_A,
        version="1",
        kind="assessment",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    result = _validator().validate(ex, citations=[cite])
    assert result.is_invalid
    assert "cite:missing-span" in result.rejected_citation_ids
    assert any(
        f.reason_code == SpanValidationReasonCode.CITATION_SPAN_MISSING.value
        for f in result.findings
    )


def test_citation_rejected_for_mismatched_artifact_version() -> None:
    page = "Semantic result must bind to the correct artifact version digest."
    span = _span(
        span_id="span:unit:ver",
        text=page,
        char_start=0,
        char_end=len(page),
    )
    ex = _extraction(page_text=page, spans=[span], content_sha256=_DIGEST_A)
    cite = SemanticCitation(
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        citation_id="cite:bad-version",
        span_id="span:unit:ver",
        artifact_id=_ART,
        content_sha256=_DIGEST_B,  # wrong version
        version="2",
        kind="submission_fact",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    result = admit_semantic_citations(ex, [cite])
    assert result.is_invalid
    assert "cite:bad-version" in result.rejected_citation_ids
    assert any(
        f.reason_code == SpanValidationReasonCode.ARTIFACT_VERSION_MISMATCH.value
        for f in result.findings
    )


def test_citation_rejected_when_version_missing() -> None:
    page = "Missing version on semantic citation is fail-closed."
    span = _span(
        span_id="span:unit:nover",
        text=page,
        char_start=0,
        char_end=len(page),
    )
    ex = _extraction(page_text=page, spans=[span], content_sha256=_DIGEST_A)
    cite = SemanticCitation(
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        citation_id="cite:no-ver",
        span_id="span:unit:nover",
        artifact_id=_ART,
        content_sha256=None,
        version=None,
        kind="requirement",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    result = _validator().validate(ex, citations=[cite])
    assert result.is_invalid
    assert "cite:no-ver" in result.rejected_citation_ids
    assert any(
        f.reason_code == SpanValidationReasonCode.ARTIFACT_VERSION_MISSING.value
        for f in result.findings
    )


def test_citation_rejected_for_stale_target_span() -> None:
    page = "Page text that no longer matches the stored span digest."
    span = ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id="span:unit:stale-cite",
        artifact_id=_ART,
        page_index=0,
        char_start=0,
        char_end=len(page),
        bbox=None,
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=1.0,
        text_digest=text_digest("old version of the quote"),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    ex = _extraction(page_text=page, spans=[span], content_sha256=_DIGEST_A)
    cite = SemanticCitation(
        schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
        citation_id="cite:stale-target",
        span_id="span:unit:stale-cite",
        artifact_id=_ART,
        content_sha256=_DIGEST_A,
        version="1",
        kind="submission_fact",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    result = _validator().validate(ex, citations=[cite])
    assert result.is_invalid
    assert "cite:stale-target" in result.rejected_citation_ids


# ---------------------------------------------------------------------------
# Reading order / layout dangling
# ---------------------------------------------------------------------------


def test_reading_order_inconsistency_warned() -> None:
    page = "AAAAABBBBBCCCCC"
    s1 = _span(
        span_id="span:ro:1",
        text="AAAAA",
        char_start=0,
        char_end=5,
        reading_order=1,  # later order but earlier chars — OK
    )
    s2 = _span(
        span_id="span:ro:2",
        text="BBBBB",
        char_start=10,  # after C in order? order 0 but later start
        char_end=15,
        reading_order=0,
        bbox=(10.0, 40.0, 100.0, 60.0),
    )
    # reading_order 0 has char_start 10; reading_order 1 has char_start 0 → inconsistent
    ex = _extraction(page_text=page, spans=[s1, s2])
    result = _validator().validate(ex)
    assert any(
        f.reason_code == SpanValidationReasonCode.READING_ORDER_INCONSISTENT.value
        for f in result.findings
    )


def test_dangling_layout_span_fails() -> None:
    page = "Layout item points at missing span identifier."
    span = _span(text=page, char_start=0, char_end=len(page))
    layout = LayoutItem(
        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
        item_id="layout:1",
        artifact_id=_ART,
        kind=LayoutItemKind.TABLE,
        span_id="span:missing-layout-target",
        page_index=0,
        bbox=None,
        text_digest=text_digest("table"),
        confidence=1.0,
        attributes={},
        origin=ExtractionOrigin.NATIVE,
    )
    ex = _extraction(page_text=page, spans=[span], layout_items=(layout,))
    result = _validator().validate(ex)
    assert result.is_invalid
    assert any(
        f.reason_code == SpanValidationReasonCode.LAYOUT_SPAN_DANGLING.value
        for f in result.findings
    )


# ---------------------------------------------------------------------------
# Mapping input / public projection privacy
# ---------------------------------------------------------------------------


def test_accepts_mapping_extraction_and_dict_citations() -> None:
    page = "Mapping input path for validator interoperability."
    span = _span(text=page, char_start=0, char_end=len(page), span_id="span:map:1")
    ex = _extraction(page_text=page, spans=[span], content_sha256=_DIGEST_A)
    result = validate_spans(
        ex.to_dict(),
        expected_content_sha256=_DIGEST_A,
        citations=[
            {
                "schema_version": SPAN_VALIDATOR_SCHEMA_VERSION,
                "citation_id": "cite:map-1",
                "span_id": "span:map:1",
                "artifact_id": _ART,
                "content_sha256": _DIGEST_A,
                "version": "1",
                "kind": "submission_fact",
                "classification": DisclosureClassification.PUBLIC_USER.value,
            }
        ],
    )
    assert "cite:map-1" in result.admitted_citation_ids
    public = result.public_projection()
    assert "Hello" not in json.dumps(public)
    assert public["admitted_citation_count"] == 1


def test_finding_severity_ordering_invalid_over_review() -> None:
    # Unaccounted page (critical) dominates low-coverage review.
    page = "x"
    span = _span(text=page, char_start=0, char_end=1, bbox=None)
    ex = _extraction(
        page_text=page,
        spans=[span],
        page_coverage=[_coverage(coverage_ratio=0.01, status=PageStatus.LOW_COVERAGE)],
        page_count=3,
        overall_coverage=0.01,
    )
    result = _validator().validate(ex)
    assert result.disposition is SpanValidationDisposition.INVALID
    assert FindingSeverity.CRITICAL in {f.severity for f in result.findings}


def test_policy_snapshot_present() -> None:
    page = "Policy snapshot is recorded for audit reproducibility."
    span = _span(text=page, char_start=0, char_end=len(page))
    ex = _extraction(page_text=page, spans=[span])
    result = _validator().validate(ex)
    assert "min_readability" in result.policy_snapshot
    assert result.policy_snapshot["schema_version"] == SPAN_VALIDATOR_SCHEMA_VERSION
