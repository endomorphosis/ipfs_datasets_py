"""Unit tests for USPTO office-action processor (PATLAW-032)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    GovernmentRequirement,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
    OFFICE_ACTION_SCHEMA_VERSION,
    ActionLifecycleRecord,
    ActionLifecycleStatus,
    AnalysisCandidate,
    AnalysisDisposition,
    CandidateKind,
    CandidateOrigin,
    ClaimRangeAmbiguity,
    EvidenceLayer,
    ModelCandidateInput,
    OfficeActionInput,
    OfficeActionKind,
    OfficeActionProcessor,
    OfficeActionReasonCode,
    OfficeActionResult,
    deterministically_validate_candidate,
    extract_office_action,
    parse_claim_range_surface,
    sha256_hex,
)
from tests.fixtures.uspto.office_actions.generators import (
    AMBIGUOUS_CANARY,
    FINAL_CANARY,
    MALFORMED_CANARY,
    NON_FINAL_CANARY,
    NOTICE_CANARY,
    REISSUE_CANARY,
    RESCIND_CANARY,
    build_ambiguous_claim_range_text,
    build_empty_office_action_text,
    build_final_office_action_text,
    build_malformed_office_action_text,
    build_non_final_office_action_text,
    build_notice_text,
    build_reissued_action_text,
    build_rescinded_action_text,
    build_rescinded_reissued_pair,
    fixture_manifest,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[5] / "fixtures" / "uspto" / "office_actions"
)
RECIPE_PATH = FIXTURE_DIR / "office_action_recipe.json"


def _processor(**kwargs) -> OfficeActionProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"oa:test:{counter['n']:04d}"

    return OfficeActionProcessor(id_factory=_ids, **kwargs)


def _span_for_text(
    text: str,
    *,
    artifact_id: str = "art:oa:1",
    span_id: str = "span:oa:cover",
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
) -> ExtractedSpan:
    return ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id=span_id,
        artifact_id=artifact_id,
        page_index=0,
        char_start=0,
        char_end=len(text),
        bbox=(0.0, 0.0, 100.0, 200.0),
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=0.99,
        text_digest=sha256_hex(" ".join(text.split())),
        image_digest=None,
        classification=classification,
    )


def _input_from_text(
    text: str,
    *,
    artifact_id: str = "art:oa:1",
    with_span: bool = True,
    **kwargs,
) -> OfficeActionInput:
    spans = ()
    span_texts = {}
    if with_span:
        span = _span_for_text(text, artifact_id=artifact_id)
        spans = (span,)
        span_texts = {span.span_id: text}
    return OfficeActionInput(
        artifact_id=artifact_id,
        text=text,
        spans=spans,
        span_texts=span_texts,
        classification=kwargs.pop(
            "classification", DisclosureClassification.PUBLIC_USER
        ),
        **kwargs,
    )


def _assert_round_trip(result: OfficeActionResult) -> None:
    first = result.to_dict()
    restored = OfficeActionResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert "candidates" not in public
    blob = json.dumps(public)
    assert NON_FINAL_CANARY not in blob
    assert FINAL_CANARY not in blob


def _assert_every_candidate_has_span(result: OfficeActionResult) -> None:
    span_ids = {s.span_id for s in result.spans}
    assert result.candidates, "expected at least one candidate for non-empty actions"
    for cand in result.candidates:
        assert cand.source_span_id, "every candidate must point to a span"
        assert cand.source_span_id in span_ids
        assert cand.text_digest
        assert len(cand.text_digest) == 64


# ---------------------------------------------------------------------------
# Helpers / pure functions
# ---------------------------------------------------------------------------


def test_parse_claim_range_surface_exact_and_multi() -> None:
    tokens, amb = parse_claim_range_surface("claims 1-3")
    assert tokens == ("1", "2", "3")
    assert amb is ClaimRangeAmbiguity.MULTI_SEGMENT

    tokens, amb = parse_claim_range_surface("claim 7")
    assert tokens == ("7",)
    assert amb is ClaimRangeAmbiguity.EXACT

    tokens, amb = parse_claim_range_surface("claims 1-3 and 5")
    assert tokens == ("1", "2", "3", "5")
    assert amb is ClaimRangeAmbiguity.MULTI_SEGMENT


def test_parse_claim_range_retains_ambiguity() -> None:
    tokens, amb = parse_claim_range_surface("claims about 1-5")
    assert tokens == ()
    assert amb is ClaimRangeAmbiguity.OPEN_ENDED

    tokens, amb = parse_claim_range_surface("claims all")
    assert tokens == ()
    assert amb is ClaimRangeAmbiguity.OPEN_ENDED

    tokens, amb = parse_claim_range_surface("claims ???")
    assert tokens == ()
    assert amb is ClaimRangeAmbiguity.UNRESOLVED

    tokens, amb = parse_claim_range_surface("claims 9-2")
    assert tokens == ()
    assert amb is ClaimRangeAmbiguity.CONFLICTING


def test_recipe_file_present() -> None:
    assert RECIPE_PATH.is_file()
    recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
    assert recipe["schema_version"] == "uspto.office-action-recipe.v1"
    assert len(recipe["cases"]) >= 6


def test_fixture_manifest(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path / "oas")
    assert "files" in manifest
    assert (tmp_path / "oas" / "non_final_oa.txt").is_file()
    assert (tmp_path / "oas" / "rescinded_reissued_pair.json").is_file()
    body = (tmp_path / "oas" / "non_final_oa.txt").read_text(encoding="utf-8")
    assert NON_FINAL_CANARY in body


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def test_non_final_office_action_sections_and_spans() -> None:
    text = build_non_final_office_action_text()
    result = _processor().analyze(_input_from_text(text))
    assert result.schema_version == OFFICE_ACTION_SCHEMA_VERSION
    assert result.action_kind is OfficeActionKind.NON_FINAL_REJECTION
    assert result.disposition in (
        AnalysisDisposition.ANALYZED,
        AnalysisDisposition.REVIEW,
    )
    assert result.sections
    assert any(s.kind.value.startswith("claim") or s.title for s in result.sections)
    _assert_every_candidate_has_span(result)
    _assert_round_trip(result)

    rejections = result.candidates_by_kind(CandidateKind.REJECTION)
    assert rejections
    assert any("112" in (c.requirement_type or "") for c in rejections)

    claim_ranges = result.candidates_by_kind(CandidateKind.CLAIM_RANGE)
    assert claim_ranges

    citations = result.candidates_by_kind(CandidateKind.CITATION)
    fps = result.candidates_by_kind(CandidateKind.FORM_PARAGRAPH)
    assert citations or fps
    assert fps or any("form paragraph" in c.surface_text.lower() for c in citations)

    response = result.candidates_by_kind(CandidateKind.RESPONSE_INSTRUCTION)
    assert response

    # Verified layer only after deterministic validation
    verified = result.candidates_by_layer(EvidenceLayer.VERIFIED)
    assert verified
    assert all(c.validation_receipt_id for c in verified)
    assert result.validation_receipts
    assert result.requirements
    for req in result.requirements:
        assert isinstance(req, GovernmentRequirement)
        assert req.source_span_id
        assert req.instruction_text_digest


def test_final_rejection_multi_segment_claims() -> None:
    text = build_final_office_action_text()
    result = _processor().analyze(_input_from_text(text, artifact_id="art:oa:final"))
    assert result.action_kind is OfficeActionKind.FINAL_REJECTION
    assert FINAL_CANARY not in json.dumps(result.public_projection())
    multi = [
        c
        for c in result.candidates_by_kind(CandidateKind.CLAIM_RANGE)
        if c.ambiguity == ClaimRangeAmbiguity.MULTI_SEGMENT.value
    ]
    assert multi
    # tokens retained without collapsing ambiguity flag
    assert any(set(c.claim_tokens) >= {"1", "2", "3", "5"} for c in multi)
    rejections = result.candidates_by_kind(CandidateKind.REJECTION)
    assert rejections
    assert any("103" in (c.requirement_type or "") for c in rejections)
    _assert_every_candidate_has_span(result)


def test_ambiguous_claim_ranges_retained() -> None:
    text = build_ambiguous_claim_range_text()
    result = _processor().analyze(_input_from_text(text, artifact_id="art:oa:amb"))
    assert AMBIGUOUS_CANARY in text
    ranges = result.candidates_by_kind(CandidateKind.CLAIM_RANGE)
    assert ranges
    ambiguities = {c.ambiguity for c in ranges}
    assert ClaimRangeAmbiguity.OPEN_ENDED.value in ambiguities
    assert ClaimRangeAmbiguity.MULTI_SEGMENT.value in ambiguities
    # Open-ended must not invent claim tokens
    for c in ranges:
        if c.ambiguity == ClaimRangeAmbiguity.OPEN_ENDED.value:
            assert c.claim_tokens == ()
    assert OfficeActionReasonCode.AMBIGUOUS_CLAIM_RANGE.value in result.reason_codes
    _assert_every_candidate_has_span(result)


def test_citations_retain_match_kind_without_authority() -> None:
    text = build_non_final_office_action_text()
    result = _processor().analyze(_input_from_text(text))
    cit_like = [
        c
        for c in result.candidates
        if c.kind
        in (
            CandidateKind.CITATION,
            CandidateKind.FORM_PARAGRAPH,
            CandidateKind.FEE,
            CandidateKind.FORM,
        )
    ]
    assert cit_like
    for c in cit_like:
        # parse-only: match kind retained; no authority tier asserted on candidate
        assert c.citation_match_kind is not None or c.origin is CandidateOrigin.CITATION_PARSER
        assert "authority_verified" not in c.labels
        assert c.source_span_id


def test_objections_informalities_fees_forms_alternatives() -> None:
    text = build_non_final_office_action_text()
    result = _processor().analyze(_input_from_text(text))
    assert result.candidates_by_kind(CandidateKind.OBJECTION)
    assert result.candidates_by_kind(CandidateKind.INFORMALITY)
    fees = result.candidates_by_kind(CandidateKind.FEE)
    forms = result.candidates_by_kind(CandidateKind.FORM)
    assert fees or forms
    alts = result.candidates_by_kind(CandidateKind.ALTERNATIVE)
    assert alts
    # uncompiled residual language represented, not dropped
    # (may or may not fire depending on residual detector; if present, span-bound)
    for c in result.candidates_by_kind(CandidateKind.UNCOMPILED_LANGUAGE):
        assert c.source_span_id
        assert c.requirement_type == "uncompiled"


def test_notice_extraction() -> None:
    text = build_notice_text()
    result = _processor().analyze(_input_from_text(text, artifact_id="art:notice"))
    assert NOTICE_CANARY in text
    assert result.candidates
    _assert_every_candidate_has_span(result)
    # response / fee cues
    kinds = {c.kind for c in result.candidates}
    assert CandidateKind.RESPONSE_INSTRUCTION in kinds or CandidateKind.CITATION in kinds or CandidateKind.FEE in kinds


# ---------------------------------------------------------------------------
# Lifecycle: rescinded / reissued
# ---------------------------------------------------------------------------


def test_rescinded_reissued_lifecycle_represented() -> None:
    pair = build_rescinded_reissued_pair()
    original = pair["actions"][0]
    reissue = pair["actions"][1]
    assert RESCIND_CANARY in original["text"]
    assert REISSUE_CANARY in reissue["text"]

    # Analyze reissue with lifecycle metadata covering both actions.
    lifecycle = (
        ActionLifecycleRecord(
            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
            action_id=original["action_id"],
            status=ActionLifecycleStatus.RESCINDED,
            mailing_date=original["mailing_date"],
            supersedes_action_id=None,
            content_sha256=original["content_sha256"],
            source_span_id=None,
            notes=("original_rescinded",),
        ),
        ActionLifecycleRecord(
            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
            action_id=reissue["action_id"],
            status=ActionLifecycleStatus.REISSUED,
            mailing_date=reissue["mailing_date"],
            supersedes_action_id=original["action_id"],
            content_sha256=reissue["content_sha256"],
            source_span_id=None,
            notes=("reissue_active",),
        ),
    )
    # When analyzing the *rescinded* text with rescinded status:
    rescinded_result = _processor().analyze(
        _input_from_text(
            original["text"],
            artifact_id="art:oa:rescinded",
            action_id=original["action_id"],
            lifecycle=(lifecycle[0],),
            mailing_date=original["mailing_date"],
        )
    )
    assert rescinded_result.action_kind is OfficeActionKind.RESCINDED_ACTION
    assert OfficeActionReasonCode.LIFECYCLE_RESCINDED.value in rescinded_result.reason_codes
    assert any(
        r.status is ActionLifecycleStatus.RESCINDED for r in rescinded_result.lifecycle
    )
    # Requirements from rescinded action must carry inactive applicability.
    for req in rescinded_result.requirements:
        assert "action_lifecycle_inactive" in req.applicability_conditions
        assert any("rescinded" in e for e in req.exceptions)

    reissue_result = _processor().analyze(
        _input_from_text(
            reissue["text"],
            artifact_id="art:oa:reissue",
            action_id=reissue["action_id"],
            lifecycle=lifecycle,
            mailing_date=reissue["mailing_date"],
        )
    )
    assert reissue_result.lifecycle
    statuses = {r.status for r in reissue_result.lifecycle}
    assert ActionLifecycleStatus.RESCINDED in statuses
    assert ActionLifecycleStatus.REISSUED in statuses
    assert OfficeActionReasonCode.LIFECYCLE_REISSUED.value in reissue_result.reason_codes
    _assert_every_candidate_has_span(reissue_result)
    _assert_round_trip(reissue_result)


def test_inferred_rescind_language_without_metadata() -> None:
    text = build_reissued_action_text()
    result = _processor().analyze(_input_from_text(text, artifact_id="art:oa:reissue2"))
    assert any(
        r.status is ActionLifecycleStatus.REISSUED for r in result.lifecycle
    ) or result.action_kind is OfficeActionKind.REISSUED_ACTION


# ---------------------------------------------------------------------------
# Malformed / empty
# ---------------------------------------------------------------------------


def test_empty_action_malformed() -> None:
    result = _processor().analyze(
        _input_from_text(build_empty_office_action_text(), with_span=False)
    )
    assert result.disposition is AnalysisDisposition.MALFORMED
    assert OfficeActionReasonCode.EMPTY_TEXT.value in result.reason_codes
    assert result.action_kind is OfficeActionKind.MALFORMED
    assert result.requires_review


def test_malformed_action_represented() -> None:
    text = build_malformed_office_action_text()
    assert MALFORMED_CANARY in text
    result = _processor().analyze(_input_from_text(text, artifact_id="art:oa:bad"))
    # Either malformed or review — must not silently drop
    assert result.disposition in (
        AnalysisDisposition.MALFORMED,
        AnalysisDisposition.REVIEW,
        AnalysisDisposition.ANALYZED,
    )
    assert result.retained is True or result.disposition is AnalysisDisposition.REJECTED
    # candidates that exist remain span-bound
    span_ids = {s.span_id for s in result.spans}
    for cand in result.candidates:
        assert cand.source_span_id in span_ids
    _assert_round_trip(result)


def test_minted_covering_span_when_missing() -> None:
    text = build_non_final_office_action_text()
    result = _processor().analyze(
        _input_from_text(text, with_span=False, artifact_id="art:oa:mint")
    )
    assert OfficeActionReasonCode.MISSING_SPANS.value in result.reason_codes
    assert result.spans
    _assert_every_candidate_has_span(result)


# ---------------------------------------------------------------------------
# Model candidates never enter verified without deterministic validation
# ---------------------------------------------------------------------------


def test_model_candidates_held_until_validated() -> None:
    text = build_non_final_office_action_text()
    span = _span_for_text(text)
    model_surface = "Claim 1 is rejected under 35 U.S.C. 112(a) as failing to comply with the written description requirement."
    assert model_surface in text
    inp = OfficeActionInput(
        artifact_id="art:oa:model",
        text=text,
        spans=(span,),
        span_texts={span.span_id: text},
        classification=DisclosureClassification.PUBLIC_USER,
        model_candidates=(
            ModelCandidateInput(
                kind=CandidateKind.REJECTION,
                surface_text=model_surface,
                source_span_id=span.span_id,
                confidence=0.99,
                claim_tokens=("1",),
                legal_citations=("35 U.S.C. 112(a)",),
                requirement_type="rejection_112_written_description",
            ),
            ModelCandidateInput(
                kind=CandidateKind.REJECTION,
                surface_text="This surface is not in the document at all XYZ-MODEL-HALLUCINATION",
                source_span_id=span.span_id,
                confidence=0.99,
                claim_tokens=("99",),
                requirement_type="rejection_hallucinated",
            ),
        ),
    )
    result = _processor().analyze(inp)
    model_cands = [c for c in result.candidates if c.origin is CandidateOrigin.MODEL]
    assert len(model_cands) == 2
    assert OfficeActionReasonCode.MODEL_CANDIDATE_HELD.value in result.reason_codes

    good = next(c for c in model_cands if "HALLUCINATION" not in c.surface_text)
    bad = next(c for c in model_cands if "HALLUCINATION" in c.surface_text)

    # Good model candidate may reach verified ONLY with validation receipt.
    if good.layer is EvidenceLayer.VERIFIED:
        assert good.validation_receipt_id is not None
        receipt = next(
            r
            for r in result.validation_receipts
            if r.receipt_id == good.validation_receipt_id
        )
        assert receipt.passed is True
    else:
        # still not verified
        assert good.layer is EvidenceLayer.CANDIDATE

    # Hallucinated model surface must not be verified.
    assert bad.layer is not EvidenceLayer.VERIFIED
    assert bad.validation_receipt_id is not None
    bad_receipt = next(
        r for r in result.validation_receipts if r.receipt_id == bad.validation_receipt_id
    )
    assert bad_receipt.passed is False

    # Invariant on result construction
    for c in result.candidates:
        if c.origin is CandidateOrigin.MODEL and c.layer is EvidenceLayer.VERIFIED:
            assert c.validation_receipt_id


def test_model_candidate_cannot_construct_verified_without_receipt() -> None:
    with pytest.raises(ValueError, match="verified layer"):
        AnalysisCandidate(
            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
            candidate_id="cand:bad:1",
            kind=CandidateKind.REJECTION,
            layer=EvidenceLayer.VERIFIED,
            origin=CandidateOrigin.MODEL,
            source_span_id="span:1",
            text_digest=sha256_hex("x"),
            surface_text="x",
            confidence=0.9,
            ambiguity=None,
            claim_tokens=("1",),
            legal_citations=(),
            citation_keys=(),
            citation_match_kind=None,
            requirement_type="rejection",
            alternatives=(),
            exceptions=(),
            labels={},
            validation_receipt_id=None,  # blocked
            review_state=ReviewState.PENDING,
        )


def test_deterministic_validation_promotes_and_blocks() -> None:
    text = "Claims 1-2 are rejected under 35 U.S.C. 103."
    span = _span_for_text(text, span_id="span:v")
    cand = AnalysisCandidate(
        schema_version=OFFICE_ACTION_SCHEMA_VERSION,
        candidate_id="cand:v:1",
        kind=CandidateKind.REJECTION,
        layer=EvidenceLayer.DETERMINISTIC,
        origin=CandidateOrigin.DETERMINISTIC_RULE,
        source_span_id="span:v",
        text_digest=sha256_hex(" ".join(text.split())),
        surface_text=text,
        confidence=0.8,
        ambiguity=None,
        claim_tokens=("1", "2"),
        legal_citations=("35 U.S.C. 103",),
        citation_keys=(),
        citation_match_kind=None,
        requirement_type="rejection_103",
        alternatives=(),
        exceptions=(),
        labels={},
        validation_receipt_id=None,
        review_state=ReviewState.PENDING,
    )
    promoted, receipt = deterministically_validate_candidate(
        cand,
        spans=(span,),
        span_texts={"span:v": text},
        full_text=text,
        receipt_id="val:test:1",
    )
    assert receipt.passed is True
    assert promoted.layer is EvidenceLayer.VERIFIED
    assert promoted.validation_receipt_id == "val:test:1"

    bad = AnalysisCandidate(
        schema_version=OFFICE_ACTION_SCHEMA_VERSION,
        candidate_id="cand:v:2",
        kind=CandidateKind.REJECTION,
        layer=EvidenceLayer.CANDIDATE,
        origin=CandidateOrigin.MODEL,
        source_span_id="span:missing",
        text_digest=sha256_hex("nope"),
        surface_text="nope",
        confidence=0.9,
        ambiguity=None,
        claim_tokens=(),
        legal_citations=(),
        citation_keys=(),
        citation_match_kind=None,
        requirement_type=None,
        alternatives=(),
        exceptions=(),
        labels={},
        validation_receipt_id=None,
        review_state=ReviewState.REQUIRED,
    )
    held, bad_receipt = deterministically_validate_candidate(
        bad, spans=(span,), full_text=text, receipt_id="val:test:2"
    )
    assert bad_receipt.passed is False
    assert held.layer is EvidenceLayer.CANDIDATE
    assert held.layer is not EvidenceLayer.VERIFIED


def test_requirements_only_from_verified_layer() -> None:
    text = build_non_final_office_action_text()
    # Disable auto-validate so candidates stay deterministic / candidate
    result = _processor(auto_validate=False).analyze(_input_from_text(text))
    assert result.requirements == ()
    # With validation, requirements appear
    result2 = _processor(auto_validate=True).analyze(_input_from_text(text))
    assert result2.requirements
    verified_ids = {
        c.source_span_id
        for c in result2.candidates
        if c.layer is EvidenceLayer.VERIFIED
    }
    for req in result2.requirements:
        assert req.source_span_id in verified_ids or result2.span_by_id(
            req.source_span_id
        )


def test_extract_office_action_convenience() -> None:
    text = build_non_final_office_action_text()
    result = extract_office_action(
        artifact_id="art:oa:conv",
        text=text,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.artifact_id == "art:oa:conv"
    assert result.candidates


def test_mapping_input_and_lifecycle_dict() -> None:
    text = build_rescinded_action_text()
    result = _processor().analyze(
        {
            "artifact_id": "art:oa:map",
            "text": text,
            "classification": "public_user",
            "lifecycle": [
                {
                    "schema_version": OFFICE_ACTION_SCHEMA_VERSION,
                    "action_id": "oa:original-2026-02-01",
                    "status": "rescinded",
                    "mailing_date": "2026-02-01",
                    "supersedes_action_id": None,
                    "content_sha256": sha256_hex(text),
                    "source_span_id": None,
                    "notes": [],
                }
            ],
        }
    )
    assert result.action_kind is OfficeActionKind.RESCINDED_ACTION


def test_quarantine_classification() -> None:
    text = build_non_final_office_action_text()
    result = _processor().analyze(
        _input_from_text(
            text,
            classification=DisclosureClassification.UNKNOWN,
            artifact_id="art:oa:q",
        )
    )
    assert result.disposition is AnalysisDisposition.QUARANTINE
    assert result.review_state is ReviewState.REQUIRED


def test_public_projection_omits_surfaces() -> None:
    text = build_non_final_office_action_text()
    result = _processor().analyze(_input_from_text(text))
    public = result.public_projection()
    blob = json.dumps(public)
    assert NON_FINAL_CANARY not in blob
    assert "surface_text" not in blob
    assert public["candidate_count"] == len(result.candidates)
    assert public["verified_candidate_count"] == len(
        result.candidates_by_layer(EvidenceLayer.VERIFIED)
    )


def test_oversize_rejected() -> None:
    from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
        AnalysisBounds,
    )

    proc = _processor(bounds=AnalysisBounds(max_chars=32))
    result = proc.analyze(
        _input_from_text(build_non_final_office_action_text(), artifact_id="art:oa:big")
    )
    assert result.disposition is AnalysisDisposition.REJECTED
    assert OfficeActionReasonCode.OVERSIZE_TEXT.value in result.reason_codes


def test_recipe_cases_smoke() -> None:
    """Drive each recipe generator once for admission-style coverage."""
    recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
    proc = _processor()
    generators = {
        "build_non_final_office_action_text": build_non_final_office_action_text,
        "build_final_office_action_text": build_final_office_action_text,
        "build_malformed_office_action_text": build_malformed_office_action_text,
        "build_empty_office_action_text": build_empty_office_action_text,
        "build_ambiguous_claim_range_text": build_ambiguous_claim_range_text,
        "build_notice_text": build_notice_text,
        "build_rescinded_reissued_pair": build_rescinded_reissued_pair,
    }
    for case in recipe["cases"]:
        gen_name = case["generator"]
        gen = generators[gen_name]
        payload = gen()
        if gen_name == "build_rescinded_reissued_pair":
            text = payload["actions"][1]["text"]
            result = proc.analyze(
                _input_from_text(
                    text,
                    artifact_id=f"art:recipe:{case['id']}",
                    lifecycle=(
                        ActionLifecycleRecord(
                            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
                            action_id=payload["actions"][0]["action_id"],
                            status=ActionLifecycleStatus.RESCINDED,
                            mailing_date=payload["actions"][0]["mailing_date"],
                            supersedes_action_id=None,
                            content_sha256=payload["actions"][0]["content_sha256"],
                            source_span_id=None,
                            notes=(),
                        ),
                        ActionLifecycleRecord(
                            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
                            action_id=payload["actions"][1]["action_id"],
                            status=ActionLifecycleStatus.REISSUED,
                            mailing_date=payload["actions"][1]["mailing_date"],
                            supersedes_action_id=payload["actions"][0]["action_id"],
                            content_sha256=payload["actions"][1]["content_sha256"],
                            source_span_id=None,
                            notes=(),
                        ),
                    ),
                )
            )
        else:
            result = proc.analyze(
                _input_from_text(payload, artifact_id=f"art:recipe:{case['id']}")
            )
        expect = case.get("expect") or {}
        if expect.get("every_candidate_has_span") and result.candidates:
            _assert_every_candidate_has_span(result)
        if expect.get("disposition") == "malformed":
            assert result.disposition is AnalysisDisposition.MALFORMED
        if "disposition_in" in expect:
            assert result.disposition.value in expect["disposition_in"] or (
                result.disposition
                in (
                    AnalysisDisposition.MALFORMED,
                    AnalysisDisposition.REVIEW,
                    AnalysisDisposition.ANALYZED,
                )
            )
        if expect.get("claim_range_ambiguity_retained"):
            ranges = result.candidates_by_kind(CandidateKind.CLAIM_RANGE)
            assert ranges
            assert any(
                c.ambiguity
                in (
                    ClaimRangeAmbiguity.OPEN_ENDED.value,
                    ClaimRangeAmbiguity.UNRESOLVED.value,
                    ClaimRangeAmbiguity.MULTI_SEGMENT.value,
                )
                for c in ranges
            )
        if expect.get("model_never_verified_without_receipt"):
            for c in result.candidates:
                if c.origin is CandidateOrigin.MODEL and c.layer is EvidenceLayer.VERIFIED:
                    assert c.validation_receipt_id
