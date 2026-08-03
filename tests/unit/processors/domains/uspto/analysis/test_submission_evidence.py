"""Unit tests for USPTO submission fact admission and evidence maps (PATLAW-041)."""

from __future__ import annotations

import itertools
from typing import Any, Iterator

import pytest

from ipfs_datasets_py.processors.domains.uspto.analysis.submission_evidence import (
    PARSER_VERSION,
    SUBMISSION_EVIDENCE_SCHEMA_VERSION,
    AdmittedSubmissionFact,
    ArtifactVersionBinding,
    CounterEvidenceCandidate,
    EvidenceDisposition,
    EvidenceEdge,
    EvidenceEdgeRole,
    EvidenceReasonCode,
    ExclusionReasonCode,
    PatentSupportMapAdapter,
    SubmissionEvidenceBuilder,
    SubmissionEvidenceInput,
    SubmissionEvidenceMap,
    admit_submission_facts,
    build_submission_evidence_map,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_processor import (
    ClaimVersion,
    EnrichedSubmissionFact,
    FactExtractionStatus,
    SubmissionFactType,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
    SubmissionFact,
    canonical_json,
)
from ipfs_datasets_py.processors.legal_data.support_map import MotionSupportMap


# ---------------------------------------------------------------------------
# Compact fixtures (no golden dumps)
# ---------------------------------------------------------------------------

_DIGEST_A = sha256_hex(b"artifact-bytes-version-a")
_DIGEST_B = sha256_hex(b"artifact-bytes-version-b")
_ART = "art:unit-ev-1"
_ART2 = "art:unit-ev-2"
_PKG = "pkg:unit-ev-1"

_seq: Iterator[int] = itertools.count(1)


def _reset_seq() -> None:
    global _seq
    _seq = itertools.count(1)


def _id_factory() -> str:
    return f"{next(_seq):04d}"


def _span(
    *,
    span_id: str = "span:unit:1",
    artifact_id: str = _ART,
    page_index: int | None = 0,
    char_start: int | None = 0,
    char_end: int | None = 20,
    text: str = "Claim 1. A widget comprising a hinge.",
    origin: ExtractionOrigin = ExtractionOrigin.NATIVE,
    confidence: float | None = 1.0,
) -> ExtractedSpan:
    return ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id=span_id,
        artifact_id=artifact_id,
        page_index=page_index,
        char_start=char_start,
        char_end=char_end if char_end is not None else len(text),
        bbox=(10.0, 10.0, 200.0, 40.0),
        origin=origin,
        reading_order=0,
        confidence=confidence,
        text_digest=sha256_hex(text),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )


def _fact(
    *,
    fact_id: str = "fact:unit:1",
    span_id: str = "span:unit:1",
    fact_type: str = SubmissionFactType.CLAIM.value,
    affected_claims: tuple[str, ...] = ("1",),
    version: str = "1",
    extraction_status: str = FactExtractionStatus.OK.value,
) -> SubmissionFact:
    return SubmissionFact(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        fact_id=fact_id,
        evidence_span_id=span_id,
        fact_type=fact_type,
        affected_claims=affected_claims,
        version=version,
        extraction_status=extraction_status,
        classification=DisclosureClassification.PUBLIC_USER,
    )


def _enriched(
    fact: SubmissionFact | None = None,
    *,
    artifact_id: str = _ART,
    value_text: str = "Claim 1. A widget comprising a hinge.",
    field_name: str | None = "claim:1",
    is_authoritative: bool = True,
) -> EnrichedSubmissionFact:
    f = fact or _fact()
    return EnrichedSubmissionFact(
        fact=f,
        artifact_id=artifact_id,
        value_digest=sha256_hex(value_text),
        display_value=None,
        field_name=field_name,
        page_index=0,
        authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
        is_authoritative=is_authoritative,
        signature_presence=None,
    )


def _builder() -> SubmissionEvidenceBuilder:
    _reset_seq()
    return SubmissionEvidenceBuilder(id_factory=_id_factory)


def _assert_round_trip(result: SubmissionEvidenceMap) -> None:
    payload = result.to_dict()
    restored = SubmissionEvidenceMap.from_dict(payload)
    assert restored.to_canonical_json() == result.to_canonical_json()
    assert restored.schema_version == SUBMISSION_EVIDENCE_SCHEMA_VERSION
    assert result.all_edges_round_trip()
    assert restored.all_edges_round_trip()


# ---------------------------------------------------------------------------
# Empty / no implicit support
# ---------------------------------------------------------------------------


def test_empty_submission_produces_no_implicit_support() -> None:
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(),
            spans=(),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.disposition is EvidenceDisposition.EMPTY
    assert result.is_empty
    assert result.admitted_facts == ()
    assert result.support_edges == ()
    assert result.counter_edges == ()
    assert EvidenceReasonCode.EMPTY_NO_IMPLICIT_SUPPORT.value in result.reason_codes
    # SupportMap adapter must not invent entries either.
    smap = PatentSupportMapAdapter().to_motion_support_map(result)
    assert smap.to_dict()["entry_count"] == 0
    _assert_round_trip(result)


def test_admit_submission_facts_empty_package() -> None:
    result = admit_submission_facts(
        [],
        [],
        package_id=_PKG,
        artifact_versions={_ART: _DIGEST_A},
        id_factory=_id_factory,
    )
    _reset_seq()
    assert result.disposition is EvidenceDisposition.EMPTY
    assert not result.support_edges


# ---------------------------------------------------------------------------
# Happy path: admit + round-trip
# ---------------------------------------------------------------------------


def test_admits_validated_fact_and_maps_support_edge() -> None:
    span = _span()
    fact = _enriched()
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            artifact_version_labels={_ART: "as_filed"},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.disposition is EvidenceDisposition.MAPPED
    assert len(result.admitted_facts) == 1
    assert len(result.support_edges) == 1
    assert not result.excluded
    edge = result.support_edges[0]
    assert edge.role is EvidenceEdgeRole.SUPPORT
    assert edge.fact_id == fact.fact.fact_id
    assert edge.span_id == span.span_id
    assert edge.artifact_id == _ART
    assert edge.content_sha256 == _DIGEST_A
    resolved = result.resolve_edge(edge.edge_id)
    assert resolved is not None
    r_edge, r_span, r_binding = resolved
    assert r_edge.round_trip_key() == edge.round_trip_key()
    assert r_span.span_id == span.span_id
    assert r_binding.content_sha256 == _DIGEST_A
    assert result.document_versions
    assert result.document_versions[0].artifact_id == _ART
    assert result.document_versions[0].version_label == "as_filed"
    assert "1" in result.document_versions[0].claim_numbers
    assert result.parser_versions["submission_evidence"] == PARSER_VERSION
    _assert_round_trip(result)


def test_every_edge_round_trips_to_artifact_version_and_span() -> None:
    spans = (
        _span(span_id="span:a", text="Claim 1 text A", char_end=14),
        _span(span_id="span:b", text="Remarks support claim 1", char_end=23),
    )
    facts = (
        _enriched(
            _fact(fact_id="fact:a", span_id="span:a"),
            value_text="Claim 1 text A",
            field_name="claim:1",
        ),
        _enriched(
            _fact(
                fact_id="fact:b",
                span_id="span:b",
                fact_type=SubmissionFactType.REMARKS.value,
                affected_claims=("1",),
            ),
            value_text="Remarks support claim 1",
            field_name="remarks",
        ),
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=facts,
            spans=spans,
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert len(result.support_edges) == 2
    assert result.all_edges_round_trip()
    for edge in result.support_edges:
        resolved = result.resolve_edge(edge.edge_id)
        assert resolved is not None
        _, span, binding = resolved
        assert span.artifact_id == edge.artifact_id
        assert binding.content_sha256 == edge.content_sha256
        assert binding.artifact_id == edge.artifact_id


def test_build_from_mapping_input() -> None:
    span = _span()
    fact = _enriched()
    result = build_submission_evidence_map(
        {
            "package_id": _PKG,
            "facts": [fact.to_dict()],
            "spans": [span.to_dict()],
            "artifact_versions": {_ART: _DIGEST_A},
            "classification": DisclosureClassification.PUBLIC_USER.value,
        },
        id_factory=_id_factory,
    )
    _reset_seq()
    assert len(result.admitted_facts) == 1
    assert result.all_edges_round_trip()


# ---------------------------------------------------------------------------
# Exclusions: stale / invalid / ambiguous / missing version / summary
# ---------------------------------------------------------------------------


def test_stale_span_excluded_with_reason() -> None:
    span = _span(span_id="span:stale")
    fact = _enriched(_fact(fact_id="fact:stale", span_id="span:stale"))
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            stale_span_ids=("span:stale",),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert not result.admitted_facts
    assert not result.support_edges
    assert len(result.excluded) == 1
    assert ExclusionReasonCode.STALE_SPAN.value in result.excluded[0].reason_codes
    assert result.disposition is EvidenceDisposition.REVIEW
    _assert_round_trip(result)


def test_invalid_span_excluded_with_reason() -> None:
    span = _span(span_id="span:bad")
    fact = _enriched(_fact(fact_id="fact:bad", span_id="span:bad"))
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            invalid_span_ids=("span:bad",),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert ExclusionReasonCode.INVALID_SPAN.value in result.excluded[0].reason_codes
    assert not result.support_edges


def test_missing_span_excluded() -> None:
    fact = _enriched(_fact(span_id="span:missing"))
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(),  # empty catalog
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    codes = set(result.excluded[0].reason_codes)
    assert ExclusionReasonCode.MISSING_SPAN.value in codes
    assert ExclusionReasonCode.FACT_SPAN_UNRESOLVED.value in codes


def test_missing_artifact_version_excluded() -> None:
    span = _span()
    fact = _enriched()
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={},  # no registry entry
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert (
        ExclusionReasonCode.MISSING_ARTIFACT_VERSION.value
        in result.excluded[0].reason_codes
    )
    assert not result.support_edges


def test_artifact_version_mismatch_excluded() -> None:
    span = _span()
    fact = _enriched()
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            expected_content_sha256_by_artifact={_ART: _DIGEST_B},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert (
        ExclusionReasonCode.ARTIFACT_VERSION_MISMATCH.value
        in result.excluded[0].reason_codes
    )


def test_span_artifact_mismatch_excluded() -> None:
    span = _span(artifact_id=_ART2)
    fact = _enriched()  # artifact_id defaults to _ART
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A, _ART2: _DIGEST_B},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert (
        ExclusionReasonCode.SPAN_ARTIFACT_MISMATCH.value
        in result.excluded[0].reason_codes
    )


def test_summary_fact_never_admitted_as_evidence() -> None:
    span = _span(span_id="span:sum", text="Summary of claims...")
    fact = _enriched(
        _fact(
            fact_id="fact:sum",
            span_id="span:sum",
            fact_type="llm_summary",
        ),
        value_text="Summary of claims...",
        field_name="summary",
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert not result.admitted_facts
    assert (
        ExclusionReasonCode.SUMMARY_NOT_EVIDENCE.value
        in result.excluded[0].reason_codes
    )


def test_summary_fact_id_flag_excludes() -> None:
    span = _span()
    fact = _enriched(_fact(fact_id="fact:flagged-summary"))
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            summary_fact_ids=("fact:flagged-summary",),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert (
        ExclusionReasonCode.SUMMARY_NOT_EVIDENCE.value
        in result.excluded[0].reason_codes
    )


def test_extraction_status_excluded() -> None:
    span = _span()
    fact = _enriched(
        _fact(extraction_status=FactExtractionStatus.MISSING.value)
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert (
        ExclusionReasonCode.EXTRACTION_STATUS_EXCLUDED.value
        in result.excluded[0].reason_codes
    )


def test_ambiguous_same_field_conflicting_digests_excluded() -> None:
    span_a = _span(span_id="span:a", text="version A of claim text")
    span_b = _span(span_id="span:b", text="version B of claim text DIFFERENT")
    fact_a = _enriched(
        _fact(fact_id="fact:a", span_id="span:a", version="2"),
        value_text="version A of claim text",
        field_name="claim:1",
    )
    fact_b = _enriched(
        _fact(fact_id="fact:b", span_id="span:b", version="2"),
        value_text="version B of claim text DIFFERENT",
        field_name="claim:1",
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact_a, fact_b),
            spans=(span_a, span_b),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    # Both should be excluded as ambiguous; no support edges remain.
    assert not result.admitted_facts
    assert not result.support_edges
    assert len(result.excluded) == 2
    for excl in result.excluded:
        assert ExclusionReasonCode.AMBIGUOUS_EVIDENCE.value in excl.reason_codes


def test_no_exact_span_bounds_excluded() -> None:
    span = _span(char_start=None, char_end=None)
    fact = _enriched()
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert ExclusionReasonCode.NO_EXACT_SPAN.value in result.excluded[0].reason_codes


# ---------------------------------------------------------------------------
# Counter-evidence
# ---------------------------------------------------------------------------


def test_mismatched_fact_becomes_counter_evidence() -> None:
    support_span = _span(span_id="span:support", text="Authoritative claim text")
    counter_span = _span(span_id="span:counter", text="Conflicting claim text")
    support_fact = _enriched(
        _fact(fact_id="fact:support", span_id="span:support"),
        value_text="Authoritative claim text",
        field_name="claim:1",
        is_authoritative=True,
    )
    mismatched = _enriched(
        _fact(
            fact_id="fact:mismatch",
            span_id="span:counter",
            extraction_status=FactExtractionStatus.MISMATCHED.value,
        ),
        value_text="Conflicting claim text",
        field_name="claim:1",
        is_authoritative=False,
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(support_fact, mismatched),
            spans=(support_span, counter_span),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert len(result.admitted_facts) == 1
    assert len(result.support_edges) == 1
    assert len(result.counter_edges) == 1
    counter = result.counter_edges[0]
    assert counter.role is EvidenceEdgeRole.COUNTER
    assert counter.fact_id == "fact:support"
    assert counter.span_id == "span:counter"
    admitted = result.admitted_facts[0]
    assert counter.edge_id in admitted.counter_edge_ids
    assert result.all_edges_round_trip()
    _assert_round_trip(result)


def test_explicit_counter_candidate_mapped() -> None:
    support_span = _span(span_id="span:s", text="Support text here")
    counter_span = _span(span_id="span:c", text="Counter text here")
    support_fact = _enriched(
        _fact(fact_id="fact:s", span_id="span:s"),
        value_text="Support text here",
        field_name="fee_presence",
    )
    candidate = CounterEvidenceCandidate(
        candidate_id="cand:1",
        against_fact_id="fact:s",
        span_id="span:c",
        artifact_id=_ART,
        content_sha256=_DIGEST_A,
        relation_note="docx_pdf_difference",
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(support_fact,),
            spans=(support_span, counter_span),
            artifact_versions={_ART: _DIGEST_A},
            counter_candidates=(candidate,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert len(result.counter_edges) == 1
    assert result.counter_edges[0].relation_note == "docx_pdf_difference"
    assert result.all_edges_round_trip()


def test_summary_counter_candidate_excluded() -> None:
    support_span = _span()
    support_fact = _enriched()
    candidate = CounterEvidenceCandidate(
        candidate_id="cand:sum",
        against_fact_id="fact:unit:1",
        span_id="span:unit:1",
        artifact_id=_ART,
        is_summary=True,
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(support_fact,),
            spans=(support_span,),
            artifact_versions={_ART: _DIGEST_A},
            counter_candidates=(candidate,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    # Support still admitted; summary counter excluded.
    assert len(result.admitted_facts) == 1
    assert not result.counter_edges
    assert any(
        ExclusionReasonCode.SUMMARY_NOT_EVIDENCE.value in x.reason_codes
        for x in result.excluded
    )


def test_stale_counter_candidate_excluded() -> None:
    support_span = _span(span_id="span:s", text="Support")
    counter_span = _span(span_id="span:c", text="Counter stale")
    support_fact = _enriched(
        _fact(fact_id="fact:s", span_id="span:s"),
        value_text="Support",
        field_name="claim:1",
    )
    candidate = CounterEvidenceCandidate(
        candidate_id="cand:stale",
        against_fact_id="fact:s",
        span_id="span:c",
        artifact_id=_ART,
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(support_fact,),
            spans=(support_span, counter_span),
            artifact_versions={_ART: _DIGEST_A},
            stale_span_ids=("span:c",),
            counter_candidates=(candidate,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert not result.counter_edges
    assert any(
        ExclusionReasonCode.STALE_SPAN.value in x.reason_codes for x in result.excluded
    )


# ---------------------------------------------------------------------------
# SupportMap adapter
# ---------------------------------------------------------------------------


def test_patent_support_map_adapter_projects_admitted_facts() -> None:
    span = _span()
    fact = _enriched()
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    adapter = PatentSupportMapAdapter()
    catalog = adapter.to_fact_catalog(result)
    assert fact.fact.fact_id in catalog
    assert catalog[fact.fact.fact_id]["status"] == "supported"
    assert span.span_id in catalog[fact.fact.fact_id]["source_ids"]
    assert (
        catalog[fact.fact.fact_id]["attributes"]["content_sha256"] == _DIGEST_A
    )

    support_facts = adapter.to_support_facts(result)
    assert len(support_facts) == 1
    assert support_facts[0].fact_id == fact.fact.fact_id

    motion = adapter.to_motion_support_map(result)
    assert isinstance(motion, MotionSupportMap)
    assert motion.to_dict()["entry_count"] == 1
    entry = motion.entries[0]
    assert entry.evidence_ids
    assert entry.facts[0].attributes["artifact_id"] == _ART
    assert EvidenceReasonCode.FACTS_ADMITTED.value in result.reason_codes


def test_empty_map_support_adapter_has_zero_entries() -> None:
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    motion = PatentSupportMapAdapter().to_motion_support_map(result)
    assert motion.entries == []


# ---------------------------------------------------------------------------
# Partial admission + public projection + claim versions
# ---------------------------------------------------------------------------


def test_partial_admission_when_some_facts_excluded() -> None:
    good_span = _span(span_id="span:good", text="Good claim text")
    bad_span = _span(span_id="span:bad", text="Bad claim text")
    good = _enriched(
        _fact(fact_id="fact:good", span_id="span:good"),
        value_text="Good claim text",
        field_name="claim:1",
    )
    bad = _enriched(
        _fact(fact_id="fact:bad", span_id="span:bad"),
        value_text="Bad claim text",
        field_name="claim:2",
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(good, bad),
            spans=(good_span, bad_span),
            artifact_versions={_ART: _DIGEST_A},
            stale_span_ids=("span:bad",),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.disposition is EvidenceDisposition.PARTIAL
    assert len(result.admitted_facts) == 1
    assert result.admitted_facts[0].fact_id == "fact:good"
    assert len(result.excluded) == 1
    assert EvidenceReasonCode.EXCLUSIONS_RECORDED.value in result.reason_codes


def test_public_projection_omits_body_text() -> None:
    span = _span()
    fact = _enriched()
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    public = result.public_projection()
    blob = canonical_json(public)
    assert "widget" not in blob  # claim body not leaked
    assert public["support_edge_count"] == 1
    assert public["admitted_fact_count"] == 1
    assert public["schema_version"] == SUBMISSION_EVIDENCE_SCHEMA_VERSION


def test_claim_versions_retained() -> None:
    span = _span()
    fact = _enriched()
    cv = ClaimVersion(
        version="current",
        claims={"1": "A widget comprising a hinge."},
        artifact_id=_ART,
        source_span_ids={"1": "span:unit:1"},
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            claim_versions=(cv,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert len(result.claim_versions) == 1
    assert result.claim_versions[0].version == "current"
    assert (
        EvidenceReasonCode.CLAIM_VERSIONS_RECONSTRUCTED.value in result.reason_codes
    )


def test_quarantine_classification_forces_review() -> None:
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(),
            spans=(),
            artifact_versions={},
            classification=DisclosureClassification.UNKNOWN,
        )
    )
    assert result.review_state is ReviewState.REQUIRED


def test_plain_submission_fact_without_enriched_uses_span_artifact() -> None:
    span = _span()
    fact = _fact()
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert len(result.admitted_facts) == 1
    assert result.admitted_facts[0].artifact_id == _ART
    assert result.support_edges[0].content_sha256 == _DIGEST_A


def test_edge_and_exclusion_dict_round_trips() -> None:
    edge = EvidenceEdge(
        edge_id="edge:1",
        fact_id="fact:1",
        span_id="span:1",
        artifact_id=_ART,
        content_sha256=_DIGEST_A,
        role=EvidenceEdgeRole.SUPPORT,
        fact_type="claim",
        fact_version="1",
        page_index=0,
        char_start=0,
        char_end=10,
        text_digest=sha256_hex("hello"),
        field_name="claim:1",
    )
    assert EvidenceEdge.from_dict(edge.to_dict()).to_dict() == edge.to_dict()

    binding = ArtifactVersionBinding(
        artifact_id=_ART, content_sha256=_DIGEST_A, version_label="v1"
    )
    assert (
        ArtifactVersionBinding.from_dict(binding.to_dict()).to_dict()
        == binding.to_dict()
    )


def test_build_from_analysis_rejects_non_analysis() -> None:
    with pytest.raises(TypeError):
        SubmissionEvidenceBuilder(id_factory=_id_factory).build_from_analysis(
            object(),  # type: ignore[arg-type]
            artifact_versions={_ART: _DIGEST_A},
        )


def test_multi_artifact_versions_bound_independently() -> None:
    span_a = _span(span_id="span:a", artifact_id=_ART, text="Doc A claim")
    span_b = _span(span_id="span:b", artifact_id=_ART2, text="Doc B remarks")
    fact_a = _enriched(
        _fact(fact_id="fact:a", span_id="span:a"),
        artifact_id=_ART,
        value_text="Doc A claim",
        field_name="claim:1",
    )
    fact_b = _enriched(
        _fact(
            fact_id="fact:b",
            span_id="span:b",
            fact_type=SubmissionFactType.REMARKS.value,
        ),
        artifact_id=_ART2,
        value_text="Doc B remarks",
        field_name="remarks",
    )
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact_a, fact_b),
            spans=(span_a, span_b),
            artifact_versions={_ART: _DIGEST_A, _ART2: _DIGEST_B},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert len(result.support_edges) == 2
    digests = {e.content_sha256 for e in result.support_edges}
    assert digests == {_DIGEST_A, _DIGEST_B}
    assert len(result.document_versions) == 2
    assert result.all_edges_round_trip()


def test_contract_fact_schema_version_on_admitted() -> None:
    span = _span()
    fact = _enriched()
    result = _builder().build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(fact,),
            spans=(span,),
            artifact_versions={_ART: _DIGEST_A},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    admitted = result.admitted_facts[0]
    assert admitted.fact.schema_version == CONTRACTS_SCHEMA_VERSION
    restored = AdmittedSubmissionFact.from_dict(admitted.to_dict())
    assert restored.fact_id == admitted.fact_id
    assert restored.public_projection()["evidence_span_id"] == span.span_id
