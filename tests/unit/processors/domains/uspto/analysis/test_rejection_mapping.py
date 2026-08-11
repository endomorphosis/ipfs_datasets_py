"""Unit tests for USPTO rejection mapping processor (PATLAW-043).

Acceptance focus:
  - Claim ranges and references are never guessed
  - Rescinded / reissued / amended claim cases retain history
  - Missing claim set yields unknown / review
  - Output states it is an examiner-statement map, not a patentability determination
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
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
    OfficeActionInput,
    OfficeActionKind,
    OfficeActionProcessor,
    OfficeActionResult,
    parse_claim_range_surface,
    sha256_hex as oa_sha256,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.rejection_mapping_processor import (
    NOT_PATENTABILITY_DISCLAIMER,
    OUTPUT_KIND_EXAMINER_STATEMENT_MAP,
    REJECTION_MAPPING_SCHEMA_VERSION,
    ClaimResolutionStatus,
    ClaimSetSnapshot,
    LaterDispositionEvent,
    LaterDispositionKind,
    MappingDisposition,
    MappingLifecycleStatus,
    ReferenceResolutionStatus,
    RejectionMappingInput,
    RejectionMappingProcessor,
    RejectionMappingReasonCode,
    RejectionMappingResult,
    RejectionSourceInput,
    StatutoryBasisFamily,
    extract_limitation_surfaces,
    map_rejections,
    parse_statutory_basis_surface,
    sha256_hex,
    sources_from_office_action,
)
from tests.fixtures.uspto.office_actions.generators import (
    FINAL_CANARY,
    NON_FINAL_CANARY,
    REISSUE_CANARY,
    RESCIND_CANARY,
    build_ambiguous_claim_range_text,
    build_final_office_action_text,
    build_non_final_office_action_text,
    build_reissued_action_text,
    build_rescinded_action_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _processor(**kwargs) -> RejectionMappingProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"rm:test:{counter['n']:04d}"

    return RejectionMappingProcessor(id_factory=_ids, **kwargs)


def _oa_processor() -> OfficeActionProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"oa:test:{counter['n']:04d}"

    return OfficeActionProcessor(id_factory=_ids)


def _span_for_text(
    text: str,
    *,
    artifact_id: str = "art:oa:1",
    span_id: str = "span:oa:cover",
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
        text_digest=oa_sha256(" ".join(text.split())),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )


def _analyze_oa(
    text: str,
    *,
    action_id: str = "action:test:1",
    artifact_id: str = "art:oa:1",
    lifecycle: tuple[ActionLifecycleRecord, ...] = (),
    mailing_date: str | None = None,
) -> OfficeActionResult:
    span = _span_for_text(text, artifact_id=artifact_id)
    inp = OfficeActionInput(
        artifact_id=artifact_id,
        text=text,
        spans=(span,),
        span_texts={span.span_id: text},
        classification=DisclosureClassification.PUBLIC_USER,
        action_id=action_id,
        lifecycle=lifecycle,
        mailing_date=mailing_date,
    )
    return _oa_processor().analyze(inp)


def _claim_set(
    numbers: list[str],
    *,
    version_id: str = "claims:current",
    is_current: bool = True,
) -> ClaimSetSnapshot:
    return ClaimSetSnapshot.from_numbers(
        version_id,
        numbers,
        is_current=is_current,
        artifact_id="art:claims:1",
        claim_span_ids={n: f"span:claim:{n}" for n in numbers},
    )


def _rejection_source(
    *,
    source_id: str = "cand:rej:1",
    surface: str = "Claim 1 is rejected under 35 U.S.C. 103 as unpatentable over U.S. Patent 8,888,888.",
    claim_tokens: tuple[str, ...] = ("1",),
    claim_ambiguity: str | None = ClaimRangeAmbiguity.EXACT.value,
    requirement_type: str | None = "rejection_103",
    lifecycle: MappingLifecycleStatus = MappingLifecycleStatus.ACTIVE,
    action_id: str | None = "action:1",
    prior_art: tuple[str, ...] = (),
    alternatives: tuple[str, ...] = (),
    citation_keys: tuple[str, ...] = (),
) -> RejectionSourceInput:
    return RejectionSourceInput(
        source_id=source_id,
        kind="rejection",
        surface_text=surface,
        source_span_id="span:rej:1",
        action_id=action_id,
        artifact_id="art:oa:1",
        claim_tokens=claim_tokens,
        claim_ambiguity=claim_ambiguity,
        legal_citations=("35 U.S.C. § 103",),
        citation_keys=citation_keys,
        requirement_type=requirement_type,
        alternatives=alternatives,
        exceptions=(),
        confidence=0.85,
        lifecycle_status=lifecycle,
        mailing_date="2026-08-01",
        prior_art_surfaces=prior_art,
        labels={},
    )


def _assert_round_trip(result: RejectionMappingResult) -> None:
    first = result.to_dict()
    restored = RejectionMappingResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert public["output_kind"] == OUTPUT_KIND_EXAMINER_STATEMENT_MAP
    assert public["is_patentability_determination"] is False
    assert "not a patentability determination" in public["disclaimer"].lower()
    # Public projection must not carry examiner statement surfaces.
    assert "mappings" not in public
    blob = json.dumps(public)
    assert NON_FINAL_CANARY not in blob
    assert FINAL_CANARY not in blob


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestStatutoryBasisParsing:
    def test_explicit_103(self) -> None:
        family, section, sub, surface = parse_statutory_basis_surface(
            "Claims 1-3 are rejected under 35 U.S.C. 103 as unpatentable."
        )
        assert family is StatutoryBasisFamily.USC_103
        assert section == "103"
        assert surface is not None
        assert "103" in surface

    def test_requirement_type_112a(self) -> None:
        family, section, sub, _ = parse_statutory_basis_surface(
            "Claim 1 is rejected.",
            requirement_type="rejection_112a",
        )
        assert family is StatutoryBasisFamily.USC_112
        assert section == "112"
        assert sub == "(a)"

    def test_unknown_when_silent(self) -> None:
        family, section, sub, surface = parse_statutory_basis_surface(
            "The examiner notes further consideration may be required."
        )
        assert family is StatutoryBasisFamily.UNKNOWN
        assert section is None
        assert surface is None

    def test_obviousness_keyword_is_stated_103(self) -> None:
        family, section, _, _ = parse_statutory_basis_surface(
            "It would have been obvious to combine the references."
        )
        assert family is StatutoryBasisFamily.USC_103
        assert section == "103"


class TestClaimRangeNeverGuessed:
    def test_open_ended_all_yields_no_tokens(self) -> None:
        tokens, amb = parse_claim_range_surface("Claims all")
        assert tokens == ()
        assert amb is ClaimRangeAmbiguity.OPEN_ENDED

    def test_about_range_unresolved_or_open(self) -> None:
        tokens, amb = parse_claim_range_surface("Claims about 1-5")
        assert tokens == ()
        assert amb in (
            ClaimRangeAmbiguity.OPEN_ENDED,
            ClaimRangeAmbiguity.UNRESOLVED,
        )

    def test_exact_range_tokens(self) -> None:
        tokens, amb = parse_claim_range_surface("Claims 1-3 and 5")
        assert tokens == ("1", "2", "3", "5")
        assert amb is ClaimRangeAmbiguity.MULTI_SEGMENT


class TestLimitationExtraction:
    def test_quoted_limitation_only(self) -> None:
        surfaces = extract_limitation_surfaces(
            'The limitation "neural routing module" is not taught by Smith.'
        )
        assert "neural routing module" in surfaces

    def test_no_invention_from_generic_prose(self) -> None:
        surfaces = extract_limitation_surfaces(
            "Claim 1 is rejected as unpatentable over the prior art."
        )
        assert surfaces == ()


# ---------------------------------------------------------------------------
# Core acceptance: examiner-statement map, not patentability
# ---------------------------------------------------------------------------


class TestExaminerStatementMapDisclaimer:
    def test_result_declares_examiner_statement_map(self) -> None:
        proc = _processor()
        result = proc.map(
            RejectionMappingInput(
                rejections=(_rejection_source(),),
                claim_sets=(_claim_set(["1", "2", "3"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert result.output_kind == OUTPUT_KIND_EXAMINER_STATEMENT_MAP
        assert result.is_patentability_determination is False
        assert "not a patentability determination" in result.disclaimer.lower()
        assert result.disclaimer == NOT_PATENTABILITY_DISCLAIMER
        assert (
            RejectionMappingReasonCode.EXAMINER_STATEMENT_MAP_ONLY.value
            in result.reason_codes
        )
        assert (
            RejectionMappingReasonCode.NOT_PATENTABILITY_DETERMINATION.value
            in result.reason_codes
        )
        _assert_round_trip(result)

    def test_rejects_patentability_true_on_result(self) -> None:
        with pytest.raises(ValueError, match="patentability"):
            RejectionMappingResult(
                schema_version=REJECTION_MAPPING_SCHEMA_VERSION,
                analysis_id="rm:x",
                matter_id=None,
                disposition=MappingDisposition.MAPPED,
                review_state=ReviewState.NOT_REQUIRED,
                classification=DisclosureClassification.PUBLIC_USER,
                output_kind=OUTPUT_KIND_EXAMINER_STATEMENT_MAP,
                disclaimer=NOT_PATENTABILITY_DISCLAIMER,
                is_patentability_determination=True,
                reason_codes=(),
                warnings=(),
                mappings=(),
                claim_sets=(),
                later_dispositions=(),
                retained_history_count=0,
                ruleset_versions={},
                labels={},
            )

    def test_rejects_wrong_output_kind(self) -> None:
        with pytest.raises(ValueError, match="output_kind"):
            RejectionMappingResult(
                schema_version=REJECTION_MAPPING_SCHEMA_VERSION,
                analysis_id="rm:x",
                matter_id=None,
                disposition=MappingDisposition.MAPPED,
                review_state=ReviewState.NOT_REQUIRED,
                classification=DisclosureClassification.PUBLIC_USER,
                output_kind="patentability_opinion",
                disclaimer=NOT_PATENTABILITY_DISCLAIMER,
                is_patentability_determination=False,
                reason_codes=(),
                warnings=(),
                mappings=(),
                claim_sets=(),
                later_dispositions=(),
                retained_history_count=0,
                ruleset_versions={},
                labels={},
            )


# ---------------------------------------------------------------------------
# Missing claim set → unknown / review
# ---------------------------------------------------------------------------


class TestMissingClaimSet:
    def test_missing_claim_set_yields_review(self) -> None:
        proc = _processor()
        result = proc.map(
            RejectionMappingInput(
                rejections=(_rejection_source(),),
                claim_sets=(),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert result.disposition is MappingDisposition.REVIEW
        assert result.review_state is ReviewState.REQUIRED
        assert result.requires_review
        assert (
            RejectionMappingReasonCode.MISSING_CLAIM_SET.value in result.reason_codes
        )
        assert len(result.mappings) == 1
        entry = result.mappings[0]
        assert entry.claim_resolution is ClaimResolutionStatus.MISSING_CLAIM_SET
        assert entry.review_state is ReviewState.REQUIRED
        # Stated tokens retained but not resolved against a set.
        assert entry.stated_claim_tokens == ("1",)
        assert all(
            link.resolution is ClaimResolutionStatus.MISSING_CLAIM_SET
            for link in entry.claim_links
        )
        _assert_round_trip(result)

    def test_empty_claim_set_numbers_treated_as_missing(self) -> None:
        proc = _processor()
        result = proc.map(
            RejectionMappingInput(
                rejections=(_rejection_source(),),
                claim_sets=(
                    ClaimSetSnapshot.from_numbers(
                        "claims:empty", (), is_current=True
                    ),
                ),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert result.disposition is MappingDisposition.REVIEW
        assert (
            RejectionMappingReasonCode.MISSING_CLAIM_SET.value in result.reason_codes
        )

    def test_empty_input_without_claim_set_is_review(self) -> None:
        result = map_rejections(
            RejectionMappingInput(
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert result.disposition is MappingDisposition.REVIEW
        assert (
            RejectionMappingReasonCode.NO_REJECTIONS.value in result.reason_codes
        )
        assert result.is_patentability_determination is False


# ---------------------------------------------------------------------------
# Claim ranges and references never guessed
# ---------------------------------------------------------------------------


class TestNoGuessing:
    def test_open_ended_claims_not_expanded(self) -> None:
        proc = _processor()
        src = _rejection_source(
            surface="Claims all are rejected under 35 U.S.C. 103.",
            claim_tokens=(),
            claim_ambiguity=ClaimRangeAmbiguity.OPEN_ENDED.value,
            requirement_type="rejection_103",
        )
        result = proc.map(
            RejectionMappingInput(
                rejections=(src,),
                claim_sets=(_claim_set(["1", "2", "3", "4", "5"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        entry = result.mappings[0]
        assert entry.claim_resolution is ClaimResolutionStatus.OPEN_ENDED
        assert entry.stated_claim_tokens == ()
        assert entry.claim_links == ()
        assert (
            RejectionMappingReasonCode.CLAIM_RANGE_OPEN_ENDED.value
            in result.reason_codes
        )
        # Must not invent claim numbers 1-5 from the claim set.
        assert not any(t in ("1", "2", "3", "4", "5") for t in entry.stated_claim_tokens)

    def test_unresolved_claim_surface_not_guessed(self) -> None:
        proc = _processor()
        src = _rejection_source(
            surface="Claims ??? are rejected under 35 U.S.C. 102.",
            claim_tokens=(),
            claim_ambiguity=ClaimRangeAmbiguity.UNRESOLVED.value,
            requirement_type="rejection_102",
        )
        result = proc.map(
            RejectionMappingInput(
                rejections=(src,),
                claim_sets=(_claim_set(["1", "2"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        entry = result.mappings[0]
        assert entry.claim_resolution is ClaimResolutionStatus.UNRESOLVED
        assert entry.stated_claim_tokens == ()

    def test_references_not_invented_when_unstated(self) -> None:
        proc = _processor()
        src = _rejection_source(
            surface="Claim 1 is rejected under 35 U.S.C. 112(b) as being indefinite.",
            claim_tokens=("1",),
            requirement_type="rejection_112b",
            prior_art=(),
            citation_keys=(),
        )
        result = proc.map(
            RejectionMappingInput(
                rejections=(src,),
                claim_sets=(_claim_set(["1", "2"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        entry = result.mappings[0]
        assert entry.reference_resolution is ReferenceResolutionStatus.UNSTATED
        assert entry.cited_references == ()
        assert (
            RejectionMappingReasonCode.REFERENCE_UNSTATED.value in result.reason_codes
        )

    def test_stated_references_retained(self) -> None:
        proc = _processor()
        surface = (
            "Claims 1-3 are rejected under 35 U.S.C. 103 as being unpatentable "
            "over U.S. Patent 8,888,888 in view of US 2019/0111111 A1."
        )
        tokens, amb = parse_claim_range_surface("Claims 1-3")
        src = _rejection_source(
            surface=surface,
            claim_tokens=tokens,
            claim_ambiguity=amb.value,
            requirement_type="rejection_103",
            prior_art=("U.S. Patent 8,888,888", "US 2019/0111111 A1"),
        )
        result = proc.map(
            RejectionMappingInput(
                rejections=(src,),
                claim_sets=(_claim_set(["1", "2", "3", "4"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        entry = result.mappings[0]
        assert entry.claim_resolution is ClaimResolutionStatus.RESOLVED
        assert set(entry.stated_claim_tokens) == {"1", "2", "3"}
        assert entry.reference_resolution is ReferenceResolutionStatus.STATED
        surfaces = {r.surface for r in entry.cited_references}
        assert any("8,888,888" in s or "8888888" in s.replace(",", "") for s in surfaces)
        assert (
            RejectionMappingReasonCode.REFERENCES_MAPPED.value in result.reason_codes
        )

    def test_claim_not_in_set_not_silently_accepted(self) -> None:
        proc = _processor()
        src = _rejection_source(
            claim_tokens=("1", "9"),
            claim_ambiguity=ClaimRangeAmbiguity.MULTI_SEGMENT.value,
        )
        result = proc.map(
            RejectionMappingInput(
                rejections=(src,),
                claim_sets=(_claim_set(["1", "2", "3"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        entry = result.mappings[0]
        assert entry.claim_resolution is ClaimResolutionStatus.PARTIAL
        by_num = {c.claim_number: c for c in entry.claim_links}
        assert by_num["1"].in_claim_set is True
        assert by_num["9"].in_claim_set is False
        assert by_num["9"].resolution is ClaimResolutionStatus.CLAIM_NOT_IN_SET
        assert result.disposition in (
            MappingDisposition.PARTIAL,
            MappingDisposition.REVIEW,
        )


# ---------------------------------------------------------------------------
# Rescinded / reissued / amended history retention
# ---------------------------------------------------------------------------


class TestHistoryRetention:
    def test_rescinded_and_reissued_actions_retain_both_mappings(self) -> None:
        proc = _processor()
        original_text = build_rescinded_action_text()
        reissue_text = build_reissued_action_text()

        original_lc = ActionLifecycleRecord(
            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
            action_id="oa:original-2026-02-01",
            status=ActionLifecycleStatus.RESCINDED,
            mailing_date="2026-02-01",
            supersedes_action_id=None,
            content_sha256=oa_sha256(original_text),
            source_span_id=None,
            notes=("rescinded",),
        )
        reissue_lc = ActionLifecycleRecord(
            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
            action_id="oa:reissue-2026-03-01",
            status=ActionLifecycleStatus.ACTIVE,
            mailing_date="2026-03-01",
            supersedes_action_id="oa:original-2026-02-01",
            content_sha256=oa_sha256(reissue_text),
            source_span_id=None,
            notes=("reissue",),
        )

        oa_original = _analyze_oa(
            original_text,
            action_id="oa:original-2026-02-01",
            artifact_id="art:oa:orig",
            lifecycle=(original_lc,),
            mailing_date="2026-02-01",
        )
        oa_reissue = _analyze_oa(
            reissue_text,
            action_id="oa:reissue-2026-03-01",
            artifact_id="art:oa:reissue",
            lifecycle=(reissue_lc,),
            mailing_date="2026-03-01",
        )

        # Ensure OA extraction found rejections for both.
        assert any(c.kind is CandidateKind.REJECTION for c in oa_original.candidates)
        assert any(c.kind is CandidateKind.REJECTION for c in oa_reissue.candidates)

        result = proc.map(
            RejectionMappingInput(
                office_action_results=(oa_original, oa_reissue),
                claim_sets=(_claim_set(["1", "2"]),),
                classification=DisclosureClassification.PUBLIC_USER,
                later_dispositions=(
                    LaterDispositionEvent(
                        schema_version=REJECTION_MAPPING_SCHEMA_VERSION,
                        event_id="evt:rescind",
                        kind=LaterDispositionKind.RESCINDED,
                        action_id="oa:original-2026-02-01",
                        related_mapping_ids=(),
                        as_of="2026-03-01",
                        notes=("superseded by reissue",),
                        source_span_id=None,
                    ),
                ),
            )
        )

        assert len(result.mappings) >= 2
        by_action = {
            m.action_id: m for m in result.mappings if m.action_id is not None
        }
        assert "oa:original-2026-02-01" in by_action
        assert "oa:reissue-2026-03-01" in by_action

        original_map = by_action["oa:original-2026-02-01"]
        reissue_map = by_action["oa:reissue-2026-03-01"]

        # History retained: rescinded original is not dropped.
        assert original_map.lifecycle_status is MappingLifecycleStatus.RESCINDED
        assert len(original_map.disposition_history) >= 1
        assert any(
            h.status is MappingLifecycleStatus.RESCINDED
            for h in original_map.disposition_history
        )

        assert reissue_map.lifecycle_status in (
            MappingLifecycleStatus.ACTIVE,
            MappingLifecycleStatus.REISSUED,
        )
        assert result.retained_history_count >= 1
        assert (
            RejectionMappingReasonCode.LIFECYCLE_HISTORY_RETAINED.value
            in result.reason_codes
        )
        # Both actions remain as first-class mappings (history not collapsed).
        assert len(result.mappings_for_action("oa:original-2026-02-01")) >= 1
        assert len(result.mappings_for_action("oa:reissue-2026-03-01")) >= 1
        public_blob = json.dumps(result.public_projection())
        assert RESCIND_CANARY not in public_blob
        assert REISSUE_CANARY not in public_blob
        # Public projection never embeds examiner body surfaces.
        assert "mappings" not in result.public_projection()
        _assert_round_trip(result)

    def test_amended_claim_set_versions_retained(self) -> None:
        proc = _processor()
        as_filed = _claim_set(
            ["1", "2"], version_id="claims:as_filed", is_current=False
        )
        amended = _claim_set(
            ["1", "2", "3"], version_id="claims:amended-1", is_current=False
        )
        current = _claim_set(
            ["1", "2", "3"], version_id="claims:current", is_current=True
        )
        src = _rejection_source(claim_tokens=("1", "2", "3"))
        result = proc.map(
            RejectionMappingInput(
                rejections=(src,),
                claim_sets=(as_filed, amended, current),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert len(result.claim_sets) == 3
        entry = result.mappings[0]
        assert "claims:as_filed" in entry.claim_set_version_ids
        assert "claims:amended-1" in entry.claim_set_version_ids
        assert "claims:current" in entry.claim_set_version_ids
        assert any(
            h.status is MappingLifecycleStatus.AMENDED_CLAIM_HISTORY
            for h in entry.disposition_history
        )
        assert (
            RejectionMappingReasonCode.AMENDED_CLAIM_HISTORY_RETAINED.value
            in result.reason_codes
        )
        assert result.retained_history_count >= 2
        _assert_round_trip(result)

    def test_later_disposition_events_appended_to_history(self) -> None:
        proc = _processor()
        src = _rejection_source(action_id="action:nf")
        result = proc.map(
            RejectionMappingInput(
                rejections=(src,),
                claim_sets=(_claim_set(["1"]),),
                classification=DisclosureClassification.PUBLIC_USER,
                later_dispositions=(
                    LaterDispositionEvent(
                        schema_version=REJECTION_MAPPING_SCHEMA_VERSION,
                        event_id="evt:withdraw",
                        kind=LaterDispositionKind.WITHDRAWN,
                        action_id="action:nf",
                        related_mapping_ids=(),
                        as_of="2026-09-01",
                        notes=("examiner withdrew rejection",),
                        source_span_id=None,
                    ),
                ),
            )
        )
        entry = result.mappings[0]
        assert entry.later_disposition is LaterDispositionKind.WITHDRAWN
        assert any(
            h.status is MappingLifecycleStatus.WITHDRAWN
            for h in entry.disposition_history
        )


# ---------------------------------------------------------------------------
# Integration with office-action extraction
# ---------------------------------------------------------------------------


class TestOfficeActionIntegration:
    def test_maps_non_final_112_rejection(self) -> None:
        text = build_non_final_office_action_text()
        oa = _analyze_oa(text, action_id="action:nf", mailing_date="2026-08-01")
        sources = sources_from_office_action(oa)
        assert sources, "expected rejection candidates from non-final OA"

        proc = _processor()
        result = proc.map(
            RejectionMappingInput(
                office_action_results=(oa,),
                claim_sets=(_claim_set(["1", "2", "3", "4", "5"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert result.mappings
        entry = result.mappings[0]
        assert entry.statutory_basis.family is StatutoryBasisFamily.USC_112
        assert entry.statutory_basis.stated_explicitly is True
        assert "1" in entry.stated_claim_tokens
        assert entry.examiner_statement_digest
        assert len(entry.examiner_statement_digest) == 64
        assert entry.source_span_id
        # Examiner statement is the OA rejection candidate surface (lead text).
        assert entry.examiner_statement_surface
        assert result.output_kind == OUTPUT_KIND_EXAMINER_STATEMENT_MAP
        assert result.is_patentability_determination is False
        # Fixture canary lives in full OA text, not necessarily the short lead.
        assert NON_FINAL_CANARY in text
        _assert_round_trip(result)

    def test_maps_final_103_with_claim_range_and_refs(self) -> None:
        text = build_final_office_action_text()
        oa = _analyze_oa(text, action_id="action:final", mailing_date="2026-03-15")
        proc = _processor()
        result = proc.map(
            RejectionMappingInput(
                office_action_results=(oa,),
                claim_sets=(_claim_set(["1", "2", "3", "4", "5"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert result.mappings
        entry = result.mappings[0]
        assert entry.statutory_basis.family is StatutoryBasisFamily.USC_103
        # Claims 1-3 and 5 from fixture — never invent claim 4.
        assert "4" not in entry.stated_claim_tokens
        for n in ("1", "2", "3", "5"):
            assert n in entry.stated_claim_tokens
        assert entry.claim_resolution is ClaimResolutionStatus.RESOLVED
        # References should be stated (patent numbers in surface / prior art).
        assert entry.reference_resolution is ReferenceResolutionStatus.STATED or any(
            "888" in r.surface for r in entry.cited_references
        )
        assert FINAL_CANARY in text
        assert result.is_patentability_determination is False

    def test_ambiguous_oa_preserves_ambiguity(self) -> None:
        text = build_ambiguous_claim_range_text()
        oa = _analyze_oa(text, action_id="action:amb")
        proc = _processor()
        result = proc.map(
            RejectionMappingInput(
                office_action_results=(oa,),
                claim_sets=(_claim_set(["1", "2", "3", "4", "5", "8"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert result.mappings
        # At least one open-ended / unresolved mapping must exist.
        statuses = {m.claim_resolution for m in result.mappings}
        assert statuses & {
            ClaimResolutionStatus.OPEN_ENDED,
            ClaimResolutionStatus.UNRESOLVED,
            ClaimResolutionStatus.AMBIGUOUS,
            ClaimResolutionStatus.RESOLVED,  # multi-segment 1-3 and 8 may resolve
        }
        # Open-ended "all" must not invent full claim set.
        for m in result.mappings:
            if m.claim_resolution is ClaimResolutionStatus.OPEN_ENDED:
                assert m.stated_claim_tokens == ()
        assert result.disposition in (
            MappingDisposition.REVIEW,
            MappingDisposition.PARTIAL,
            MappingDisposition.MAPPED,
        )


# ---------------------------------------------------------------------------
# Serialization / privacy / convenience
# ---------------------------------------------------------------------------


class TestSerializationAndPrivacy:
    def test_canonical_round_trip_and_public_projection(self) -> None:
        result = map_rejections(
            rejections=[
                _rejection_source(
                    surface=(
                        "Claim 1 is rejected under 35 U.S.C. 103 over "
                        "U.S. Patent 9,999,999. SECRET-CANARY-SHOULD-NOT-LEAK"
                    ),
                    prior_art=("U.S. Patent 9,999,999",),
                )
            ],
            claim_sets=[_claim_set(["1"])],
            matter_id="matter:demo",
            classification=DisclosureClassification.PUBLIC_USER,
        )
        _assert_round_trip(result)
        public = result.public_projection()
        blob = json.dumps(public)
        assert "SECRET-CANARY-SHOULD-NOT-LEAK" not in blob
        assert "9,999,999" not in blob
        assert public["matter_id"] == "matter:demo"

    def test_map_from_dict_input(self) -> None:
        proc = _processor()
        result = proc.map(
            {
                "matter_id": "matter:dict",
                "rejections": [_rejection_source().to_dict()],
                "claim_sets": [_claim_set(["1"]).to_dict()],
                "later_dispositions": [],
                "classification": DisclosureClassification.PUBLIC_USER.value,
            }
        )
        assert result.matter_id == "matter:dict"
        assert result.mappings
        assert result.output_kind == OUTPUT_KIND_EXAMINER_STATEMENT_MAP

    def test_alternatives_preserved(self) -> None:
        src = _rejection_source(
            alternatives=("cancel claim 1 without prejudice",),
        )
        result = _processor().map(
            RejectionMappingInput(
                rejections=(src,),
                claim_sets=(_claim_set(["1"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        assert result.mappings[0].alternatives == (
            "cancel claim 1 without prejudice",
        )
        assert (
            RejectionMappingReasonCode.ALTERNATIVES_PRESERVED.value
            in result.reason_codes
        )

    def test_quarantine_classification(self) -> None:
        # Unknown classification fails closed to quarantine (contracts invariant).
        result = _processor().map(
            RejectionMappingInput(
                rejections=(_rejection_source(),),
                claim_sets=(_claim_set(["1"]),),
                classification=DisclosureClassification.UNKNOWN,
            )
        )
        assert result.disposition is MappingDisposition.QUARANTINE
        assert result.review_state is ReviewState.REQUIRED
        assert (
            RejectionMappingReasonCode.QUARANTINE_CLASSIFICATION.value
            in result.reason_codes
        )

    def test_unknown_statutory_basis_flags_review(self) -> None:
        result = _processor().map(
            RejectionMappingInput(
                rejections=(
                    RejectionSourceInput(
                        source_id="cand:x",
                        kind="rejection",
                        surface_text="Claim 1 is rejected for the reasons of record.",
                        source_span_id="span:x",
                        action_id="action:x",
                        artifact_id="art:x",
                        claim_tokens=("1",),
                        claim_ambiguity=ClaimRangeAmbiguity.EXACT.value,
                        legal_citations=(),
                        citation_keys=(),
                        requirement_type=None,
                        alternatives=(),
                        exceptions=(),
                        confidence=0.5,
                        lifecycle_status=MappingLifecycleStatus.ACTIVE,
                        mailing_date=None,
                        prior_art_surfaces=(),
                        labels={},
                    ),
                ),
                claim_sets=(_claim_set(["1"]),),
                classification=DisclosureClassification.PUBLIC_USER,
            )
        )
        entry = result.mappings[0]
        assert entry.statutory_basis.family is StatutoryBasisFamily.UNKNOWN
        assert entry.statutory_basis.stated_explicitly is False
        assert result.disposition in (
            MappingDisposition.REVIEW,
            MappingDisposition.PARTIAL,
        )


class TestSha256Helper:
    def test_sha256_stable(self) -> None:
        assert sha256_hex("abc") == sha256_hex(b"abc")
        assert len(sha256_hex("hello")) == 64
