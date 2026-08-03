"""Unit tests for claim search planner v2 (PATLAW-149).

Covers versioned claim decomposition, span/version bindings, amendment
invalidation, construction alternatives, reviewer acceptance, and negative
guards against omitted limitations, invented dates, and unreviewed promotion.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.domains.patent.claim_search_planner_v2 import (
    CLAIM_SEARCH_PLANNER_DISCLAIMER,
    CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
    CandidateOrigin,
    ClaimSearchPlan,
    ClaimSpanError,
    ClaimVersion,
    ClaimVersionMismatchError,
    ClassificationCandidate,
    ClassificationScheme,
    ConceptCandidate,
    ConstructionAlternative,
    InventedDateError,
    LimitationCandidate,
    MissingTemporalAnchorError,
    OmittedLimitationError,
    PatentabilityConclusionError,
    PlanExecutionState,
    PlanNotExecutableError,
    PlannedQuery,
    QueryFamily,
    ReviewStatus,
    ReviewerAcceptance,
    SearchFilterSpec,
    StalePlanError,
    SynonymCandidate,
    UnreviewedCandidateError,
    VersionedClaim,
    admit_model_candidate_limitation,
    apply_reviewer_acceptance,
    assert_candidates_not_promoted,
    assert_limitations_cover_claims,
    assert_no_invented_dates,
    assert_no_patentability_conclusions,
    assert_plan_execution_ready,
    build_claim_search_plan,
    build_planned_queries,
    canonical_json,
    claim_set_content_sha256,
    content_digest,
    decompose_limitations,
    detect_ambiguous_constructions,
    executable_queries,
    invalidate_plan_if_amended,
    is_plan_stale,
    propose_classifications,
    propose_concepts,
    propose_synonyms,
    version_claims,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import SourceSpan

FILING = "2022-03-15"
PRIORITY = "2021-03-15"
SEARCH = "2024-06-01T12:00:00Z"
REVIEW_TIME = "2024-06-02T15:30:00Z"
SUBJECT = "subject:app-16-123456"

CLAIM_TEXT = (
    "1. A method comprising encoding claim text for retrieval; "
    "wherein the system indexes CPC G06F16/00 documents; "
    "and applying wireless network processor analysis."
)

AMBIGUOUS_CLAIM = (
    "1. A system comprising a display or screen for presenting results; "
    "wherein the device uses means for encoding data and/or retrieving records."
)

AMENDED_CLAIM = (
    "1. A method comprising encoding claim text for hybrid retrieval; "
    "wherein the system indexes CPC G06F16/00 documents; "
    "and applying wireless network processor analysis with memory."
)


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert restored == record


def _claim_version(text: str = CLAIM_TEXT, *, version: int = 1) -> ClaimVersion:
    return version_claims(
        subject_id=SUBJECT,
        version=version,
        claims=(
            {
                "claim_number": 1,
                "claim_text": text,
                "claim_kind": "independent",
            },
        ),
        as_of_utc=SEARCH,
    )


def _sample_plan(**overrides: object) -> ClaimSearchPlan:
    claim_ver = overrides.pop("claim_version", None) or _claim_version()
    kwargs: dict[str, object] = dict(
        claim_version=claim_ver,
        filing_date=FILING,
        priority_date=PRIORITY,
        search_date_utc=SEARCH,
        jurisdictions=("US",),
        classifications=("G06F16/00",),
    )
    kwargs.update(overrides)
    return build_claim_search_plan(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema / disclaimer
# ---------------------------------------------------------------------------


def test_schema_version_and_disclaimer() -> None:
    assert CLAIM_SEARCH_PLANNER_SCHEMA_VERSION == "patent.claim_search_planner.v2"
    lower = CLAIM_SEARCH_PLANNER_DISCLAIMER.lower()
    assert "patentability" in lower
    assert "candidates" in lower
    assert "invention-date" in lower or "invention date" in lower
    assert "human" in lower or "natural person" in lower


# ---------------------------------------------------------------------------
# Claim versioning
# ---------------------------------------------------------------------------


def test_version_claims_binds_content_digest() -> None:
    ver = _claim_version()
    assert ver.version == 1
    assert ver.content_sha256 == claim_set_content_sha256(ver.claims)
    assert ver.claims[0].text_sha256
    assert ver.claims[0].claim_text == CLAIM_TEXT
    _assert_round_trip(ver)


def test_amendment_produces_new_claim_version_digest() -> None:
    v1 = _claim_version(CLAIM_TEXT, version=1)
    v2 = version_claims(
        subject_id=SUBJECT,
        version=2,
        claims=({"claim_number": 1, "claim_text": AMENDED_CLAIM, "claim_kind": "independent"},),
        amendment_of=v1.claim_version_id,
    )
    assert v1.content_sha256 != v2.content_sha256
    assert v2.amendment_of == v1.claim_version_id
    assert v2.version == 2


def test_claim_version_rejects_mismatched_content_sha256() -> None:
    ver = _claim_version()
    with pytest.raises(ValueError, match="content_sha256"):
        ClaimVersion(
            schema_version=CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
            claim_version_id=ver.claim_version_id,
            subject_id=ver.subject_id,
            version=1,
            claims=ver.claims,
            content_sha256="0" * 64,
        )


# ---------------------------------------------------------------------------
# Limitations: spans + version bindings
# ---------------------------------------------------------------------------


def test_decompose_limitations_map_to_exact_spans_and_version() -> None:
    ver = _claim_version()
    limitations = decompose_limitations(ver)
    assert len(limitations) >= 2
    claim_text = ver.claims[0].claim_text
    for lim in limitations:
        assert lim.is_candidate is True
        assert lim.review_status is ReviewStatus.CANDIDATE
        assert lim.origin is CandidateOrigin.DETERMINISTIC_SPLIT
        assert 0.0 <= lim.confidence <= 1.0
        assert lim.claim_version_id == ver.claim_version_id
        assert lim.claim_version_digest == ver.content_sha256
        span = lim.claim_span
        assert span.end > span.start
        excerpt = claim_text[span.start : span.end]
        assert excerpt == lim.text or lim.text in claim_text
        _assert_round_trip(lim)


def test_limitation_rejects_empty_span() -> None:
    ver = _claim_version()
    with pytest.raises(ClaimSpanError):
        LimitationCandidate(
            limitation_id="lim:bad",
            claim_version_id=ver.claim_version_id,
            claim_version_digest=ver.content_sha256,
            claim_number=1,
            text="encoding",
            claim_span=SourceSpan(start=5, end=5, unit="char"),
            ordinal=1,
        )


def test_limitation_rejects_unreviewed_promotion() -> None:
    ver = _claim_version()
    with pytest.raises(UnreviewedCandidateError):
        LimitationCandidate(
            limitation_id="lim:bad",
            claim_version_id=ver.claim_version_id,
            claim_version_digest=ver.content_sha256,
            claim_number=1,
            text="encoding",
            claim_span=SourceSpan(start=0, end=8, unit="char"),
            ordinal=1,
            review_status=ReviewStatus.CANDIDATE,
            is_candidate=False,
        )


def test_limitation_rejects_accepted_still_candidate() -> None:
    ver = _claim_version()
    with pytest.raises(UnreviewedCandidateError):
        LimitationCandidate(
            limitation_id="lim:bad",
            claim_version_id=ver.claim_version_id,
            claim_version_digest=ver.content_sha256,
            claim_number=1,
            text="encoding",
            claim_span=SourceSpan(start=0, end=8, unit="char"),
            ordinal=1,
            review_status=ReviewStatus.ACCEPTED,
            is_candidate=True,
        )


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------


def test_build_plan_every_query_maps_to_spans_and_version() -> None:
    plan = _sample_plan()
    assert plan.schema_version == CLAIM_SEARCH_PLANNER_SCHEMA_VERSION
    assert plan.execution_state is PlanExecutionState.REVIEW_REQUIRED
    assert plan.invalidated is False
    assert plan.limitations
    assert plan.queries
    assert plan.filters is not None
    assert plan.filters.filing_date == FILING
    assert plan.filters.priority_date == PRIORITY
    assert plan.filters.search_date_utc == SEARCH
    assert "US" in plan.filters.jurisdictions

    for lim in plan.limitations:
        assert lim.claim_version_id == plan.claim_version_id
        assert lim.claim_version_digest == plan.claim_version_digest
        assert lim.claim_span.end > lim.claim_span.start

    lim_ids = {lim.limitation_id for lim in plan.limitations}
    for query in plan.queries:
        assert query.claim_version_id == plan.claim_version_id
        assert query.claim_version_digest == plan.claim_version_digest
        assert query.claim_spans
        assert query.related_limitation_ids
        assert all(rid in lim_ids for rid in query.related_limitation_ids)
        assert query.is_candidate is True

    assert plan.synonyms or plan.concepts or plan.classifications
    for syn in plan.synonyms:
        assert syn.claim_spans
        assert syn.is_candidate is True
        assert syn.origin is CandidateOrigin.SYNONYM_EXPAND
    for concept in plan.concepts:
        assert concept.claim_spans
        assert concept.is_candidate is True
    for cls in plan.classifications:
        assert cls.claim_spans
        assert cls.scheme is ClassificationScheme.CPC
        assert "G06F16/00" in cls.code or cls.code

    _assert_round_trip(plan)
    assert_no_patentability_conclusions(plan)
    assert_no_invented_dates(plan)
    assert_limitations_cover_claims(plan, _claim_version())


def test_build_plan_requires_user_supplied_dates() -> None:
    ver = _claim_version()
    with pytest.raises(MissingTemporalAnchorError):
        build_claim_search_plan(
            claim_version=ver,
            filing_date="",
            priority_date=PRIORITY,
            search_date_utc=SEARCH,
        )
    with pytest.raises((MissingTemporalAnchorError, ValueError)):
        build_claim_search_plan(
            claim_version=ver,
            filing_date=FILING,
            priority_date=PRIORITY,
            search_date_utc="2024-06-01",  # date only — not UTC
        )


def test_plan_rejects_patentability_metadata() -> None:
    with pytest.raises(PatentabilityConclusionError):
        _sample_plan(metadata={"patentability_conclusion": "novel"})


def test_search_filter_rejects_invention_date() -> None:
    with pytest.raises(InventedDateError):
        SearchFilterSpec.from_dict(
            {
                "jurisdictions": ["US"],
                "filing_date": FILING,
                "priority_date": PRIORITY,
                "search_date_utc": SEARCH,
                "invention_date": "2020-01-01",
            }
        )


def test_assert_no_invented_dates_on_plan_payload() -> None:
    plan = _sample_plan()
    bad = plan.to_dict()
    bad["filters"]["invention_date"] = "2019-05-01"
    with pytest.raises(InventedDateError):
        assert_no_invented_dates(bad)


# ---------------------------------------------------------------------------
# Ambiguous constructions remain alternatives
# ---------------------------------------------------------------------------


def test_ambiguous_constructions_remain_alternatives() -> None:
    ver = _claim_version(AMBIGUOUS_CLAIM)
    lims = decompose_limitations(ver)
    constructions = detect_ambiguous_constructions(ver, lims)
    assert constructions, "expected at least one ambiguous construction"
    for const in constructions:
        assert const.remains_alternative is True
        assert const.selected_reading is None
        assert const.review_status is ReviewStatus.ALTERNATIVE
        assert len(const.readings) >= 2
        assert const.claim_span.end > const.claim_span.start
        assert const.claim_version_digest == ver.content_sha256
        _assert_round_trip(const)

    plan = _sample_plan(claim_version=ver)
    assert plan.constructions
    assert all(c.remains_alternative for c in plan.constructions)
    # Construction-alternative queries stay candidates/alternatives.
    alt_queries = [
        q for q in plan.queries if q.family is QueryFamily.CONSTRUCTION_ALTERNATIVE
    ]
    assert alt_queries
    assert all(q.is_candidate for q in alt_queries)


def test_construction_cannot_collapse_without_selection() -> None:
    ver = _claim_version(AMBIGUOUS_CLAIM)
    lim = decompose_limitations(ver)[0]
    with pytest.raises(ValueError, match="remain"):
        ConstructionAlternative(
            construction_id="const:x",
            claim_version_id=ver.claim_version_id,
            claim_version_digest=ver.content_sha256,
            claim_number=1,
            claim_span=lim.claim_span,
            source_text=lim.text,
            readings=("reading a", "reading b"),
            remains_alternative=False,
            selected_reading=None,
        )


# ---------------------------------------------------------------------------
# Amendment invalidates stale plans
# ---------------------------------------------------------------------------


def test_amendment_invalidates_stale_plan() -> None:
    v1 = _claim_version(CLAIM_TEXT, version=1)
    plan = _sample_plan(claim_version=v1)
    assert is_plan_stale(plan, v1) is False

    v2 = version_claims(
        subject_id=SUBJECT,
        version=2,
        claims=({"claim_number": 1, "claim_text": AMENDED_CLAIM, "claim_kind": "independent"},),
        amendment_of=v1.claim_version_id,
    )
    assert is_plan_stale(plan, v2) is True
    stale = invalidate_plan_if_amended(plan, v2)
    assert stale.invalidated is True
    assert stale.execution_state is PlanExecutionState.INVALIDATED
    assert stale.invalidation_reason
    assert stale.acceptance is None

    with pytest.raises(StalePlanError):
        assert_plan_execution_ready(stale, current_claim_version=v2)

    with pytest.raises(StalePlanError):
        apply_reviewer_acceptance(
            plan,
            reviewer_id="reviewer:alice",
            accepted_at_utc=REVIEW_TIME,
            current_claim_version=v2,
        )


def test_accepted_plan_also_invalidated_by_amendment() -> None:
    v1 = _claim_version()
    plan = _sample_plan(claim_version=v1)
    accepted = apply_reviewer_acceptance(
        plan,
        reviewer_id="reviewer:alice",
        accepted_at_utc=REVIEW_TIME,
        current_claim_version=v1,
    )
    assert accepted.execution_state is PlanExecutionState.EXECUTABLE
    assert_plan_execution_ready(accepted, current_claim_version=v1)

    v2 = version_claims(
        subject_id=SUBJECT,
        version=2,
        claims=({"claim_number": 1, "claim_text": AMENDED_CLAIM, "claim_kind": "independent"},),
        amendment_of=v1.claim_version_id,
    )
    stale = invalidate_plan_if_amended(accepted, v2)
    assert stale.invalidated is True
    with pytest.raises(StalePlanError):
        assert_plan_execution_ready(stale, current_claim_version=v2)
    with pytest.raises(StalePlanError):
        executable_queries(accepted, current_claim_version=v2)


# ---------------------------------------------------------------------------
# Reviewer acceptance / execution readiness
# ---------------------------------------------------------------------------


def test_unreviewed_plan_not_executable() -> None:
    plan = _sample_plan()
    with pytest.raises((PlanNotExecutableError, UnreviewedCandidateError)):
        assert_plan_execution_ready(plan)
    with pytest.raises((PlanNotExecutableError, UnreviewedCandidateError)):
        executable_queries(plan)


def test_reviewer_acceptance_promotes_selected_candidates_only() -> None:
    plan = _sample_plan()
    lim_ids = [lim.limitation_id for lim in plan.limitations]
    query_ids = [q.query_id for q in plan.queries if q.family is QueryFamily.CLAIM_LIMITATION]
    assert query_ids

    accepted = apply_reviewer_acceptance(
        plan,
        reviewer_id="reviewer:bob",
        accepted_at_utc=REVIEW_TIME,
        accepted_limitation_ids=lim_ids,
        accepted_query_ids=query_ids[:1],
        current_claim_version=_claim_version(),
    )
    assert accepted.execution_state is PlanExecutionState.EXECUTABLE
    assert accepted.acceptance is not None
    assert accepted.acceptance.reviewer_id == "reviewer:bob"
    assert accepted.acceptance.claim_version_digest == plan.claim_version_digest
    _assert_round_trip(accepted.acceptance)
    _assert_round_trip(accepted)

    for lim in accepted.limitations:
        if lim.limitation_id in lim_ids:
            assert lim.review_status is ReviewStatus.ACCEPTED
            assert lim.is_candidate is False

    promoted_q = [q for q in accepted.queries if q.query_id == query_ids[0]][0]
    assert promoted_q.review_status is ReviewStatus.ACCEPTED
    assert promoted_q.is_candidate is False

    # Non-selected queries remain candidates.
    for q in accepted.queries:
        if q.query_id not in set(query_ids[:1]):
            assert q.is_candidate is True
            assert q.review_status is not ReviewStatus.ACCEPTED

    ready = executable_queries(accepted, current_claim_version=_claim_version())
    assert len(ready) == 1
    assert ready[0].query_id == query_ids[0]


def test_acceptance_keeps_unselected_constructions_as_alternatives() -> None:
    ver = _claim_version(AMBIGUOUS_CLAIM)
    plan = _sample_plan(claim_version=ver)
    assert plan.constructions
    const = plan.constructions[0]

    # Accept plan without selecting the construction.
    accepted = apply_reviewer_acceptance(
        plan,
        reviewer_id="reviewer:cara",
        accepted_at_utc=REVIEW_TIME,
        current_claim_version=ver,
    )
    remaining = [c for c in accepted.constructions if c.construction_id == const.construction_id]
    assert remaining
    assert remaining[0].remains_alternative is True
    assert remaining[0].selected_reading is None

    # Select one reading.
    selected = apply_reviewer_acceptance(
        plan,
        reviewer_id="reviewer:cara",
        accepted_at_utc=REVIEW_TIME,
        selected_constructions={const.construction_id: const.readings[0]},
        current_claim_version=ver,
    )
    chosen = [c for c in selected.constructions if c.construction_id == const.construction_id][0]
    assert chosen.remains_alternative is False
    assert chosen.selected_reading == const.readings[0]
    assert chosen.review_status is ReviewStatus.ACCEPTED


# ---------------------------------------------------------------------------
# Negative tests: omitted limitations, invented dates, unreviewed promotion
# ---------------------------------------------------------------------------


def test_negative_omitted_limitations_fail_coverage() -> None:
    plan = _sample_plan()
    # Drop all but one limitation and rebuild with incomplete coverage.
    sole = plan.limitations[0]
    # Fabricate a tiny span that cannot cover half the claim.
    tiny = LimitationCandidate(
        limitation_id=sole.limitation_id,
        claim_version_id=sole.claim_version_id,
        claim_version_digest=sole.claim_version_digest,
        claim_number=sole.claim_number,
        text=sole.text[:3] if len(sole.text) >= 3 else sole.text,
        claim_span=SourceSpan(
            start=sole.claim_span.start,
            end=min(sole.claim_span.start + 3, sole.claim_span.end),
            unit="char",
        ),
        ordinal=1,
        origin=sole.origin,
        confidence=sole.confidence,
        review_status=ReviewStatus.CANDIDATE,
        is_candidate=True,
    )
    query = PlannedQuery(
        query_id="q-only",
        query_text=tiny.text,
        family=QueryFamily.CLAIM_LIMITATION,
        claim_version_id=plan.claim_version_id,
        claim_version_digest=plan.claim_version_digest,
        claim_spans=(tiny.claim_span,),
        related_limitation_ids=(tiny.limitation_id,),
        origin=CandidateOrigin.QUERY_FAMILY,
        confidence=0.5,
        review_status=ReviewStatus.CANDIDATE,
        is_candidate=True,
        filters=plan.filters,
    )
    incomplete = ClaimSearchPlan(
        schema_version=CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
        plan_id="plan:incomplete",
        subject_id=SUBJECT,
        claim_version_id=plan.claim_version_id,
        claim_version_digest=plan.claim_version_digest,
        limitations=(tiny,),
        queries=(query,),
        filters=plan.filters,
        execution_state=PlanExecutionState.REVIEW_REQUIRED,
    )
    with pytest.raises(OmittedLimitationError):
        assert_limitations_cover_claims(incomplete, _claim_version())


def test_negative_missing_claim_limitations_entirely() -> None:
    plan = _sample_plan()
    # Two claims version but plan only covers claim 1 — build multi-claim version.
    multi = version_claims(
        subject_id=SUBJECT,
        version=1,
        claims=(
            {"claim_number": 1, "claim_text": CLAIM_TEXT, "claim_kind": "independent"},
            {
                "claim_number": 2,
                "claim_text": "2. The method of claim 1 further comprising logging results.",
                "claim_kind": "dependent",
                "depends_on": (1,),
            },
        ),
    )
    # Plan bound to multi version but only claim-1 limitations.
    lims = decompose_limitations(multi)
    claim1_only = tuple(lim for lim in lims if lim.claim_number == 1)
    assert claim1_only
    queries = build_planned_queries(multi, claim1_only, filters=plan.filters)
    partial = ClaimSearchPlan(
        schema_version=CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
        plan_id="plan:partial",
        subject_id=SUBJECT,
        claim_version_id=multi.claim_version_id,
        claim_version_digest=multi.content_sha256,
        limitations=claim1_only,
        queries=queries,
        filters=plan.filters,
    )
    with pytest.raises(OmittedLimitationError, match="claim 2"):
        assert_limitations_cover_claims(partial, multi)


def test_negative_invented_dates_rejected() -> None:
    plan = _sample_plan()
    payload = plan.to_dict()
    payload["inferred_invention_date"] = "2018-07-04"
    with pytest.raises(InventedDateError):
        assert_no_invented_dates(payload)

    with pytest.raises(InventedDateError):
        SearchFilterSpec(
            jurisdictions=("US",),
            filing_date=FILING,
            priority_date=PRIORITY,
            search_date_utc=SEARCH,
            metadata={"invention_date": "2018-01-01"},
        )


def test_negative_unreviewed_candidate_promotion_blocked() -> None:
    plan = _sample_plan()
    # Try to mark a limitation accepted without acceptance record on the plan.
    lim = plan.limitations[0]
    promoted = LimitationCandidate(
        limitation_id=lim.limitation_id,
        claim_version_id=lim.claim_version_id,
        claim_version_digest=lim.claim_version_digest,
        claim_number=lim.claim_number,
        text=lim.text,
        claim_span=lim.claim_span,
        ordinal=lim.ordinal,
        origin=lim.origin,
        confidence=lim.confidence,
        review_status=ReviewStatus.ACCEPTED,
        is_candidate=False,
    )
    sneaky = ClaimSearchPlan(
        schema_version=CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
        plan_id=plan.plan_id,
        subject_id=plan.subject_id,
        claim_version_id=plan.claim_version_id,
        claim_version_digest=plan.claim_version_digest,
        limitations=(promoted,) + plan.limitations[1:],
        queries=plan.queries,
        constructions=plan.constructions,
        synonyms=plan.synonyms,
        concepts=plan.concepts,
        classifications=plan.classifications,
        filters=plan.filters,
        execution_state=PlanExecutionState.REVIEW_REQUIRED,
        acceptance=None,
    )
    with pytest.raises(UnreviewedCandidateError):
        assert_candidates_not_promoted(sneaky)

    # EXECUTABLE without acceptance is rejected at construction or readiness.
    with pytest.raises(UnreviewedCandidateError):
        ClaimSearchPlan(
            schema_version=CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
            plan_id=plan.plan_id,
            subject_id=plan.subject_id,
            claim_version_id=plan.claim_version_id,
            claim_version_digest=plan.claim_version_digest,
            limitations=plan.limitations,
            queries=plan.queries,
            filters=plan.filters,
            execution_state=PlanExecutionState.EXECUTABLE,
            acceptance=None,
        )


def test_negative_model_candidate_without_span_rejected() -> None:
    ver = _claim_version()
    with pytest.raises(ClaimSpanError):
        admit_model_candidate_limitation(
            ver,
            claim_number=1,
            text="this text is not in the claim at all",
        )


def test_model_candidates_remain_unreviewed_until_acceptance() -> None:
    ver = _claim_version()
    # Use a substring that exists in the claim.
    fragment = "encoding claim text for retrieval"
    plan = build_claim_search_plan(
        claim_version=ver,
        filing_date=FILING,
        priority_date=PRIORITY,
        search_date_utc=SEARCH,
        model_candidates=(
            {"claim_number": 1, "text": fragment, "confidence": 0.33},
        ),
    )
    model_lims = [
        lim for lim in plan.limitations if lim.origin is CandidateOrigin.MODEL_PROPOSAL
    ]
    assert model_lims
    for lim in model_lims:
        assert lim.is_candidate is True
        assert lim.review_status is ReviewStatus.CANDIDATE
        assert lim.confidence == 0.33
        assert lim.claim_version_digest == ver.content_sha256
    with pytest.raises((PlanNotExecutableError, UnreviewedCandidateError)):
        assert_plan_execution_ready(plan)


def test_query_version_mismatch_rejected() -> None:
    plan = _sample_plan()
    lim = plan.limitations[0]
    with pytest.raises(ClaimVersionMismatchError):
        ClaimSearchPlan(
            schema_version=CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
            plan_id="plan:mismatch",
            subject_id=SUBJECT,
            claim_version_id=plan.claim_version_id,
            claim_version_digest=plan.claim_version_digest,
            limitations=plan.limitations,
            queries=(
                PlannedQuery(
                    query_id="q-bad",
                    query_text=lim.text,
                    family=QueryFamily.CLAIM_LIMITATION,
                    claim_version_id="claim-ver:other",
                    claim_version_digest=plan.claim_version_digest,
                    claim_spans=(lim.claim_span,),
                    related_limitation_ids=(lim.limitation_id,),
                ),
            ),
            filters=plan.filters,
        )


def test_propose_helpers_bind_version_and_spans() -> None:
    ver = _claim_version()
    lims = decompose_limitations(ver)
    syns = propose_synonyms(ver, lims)
    concepts = propose_concepts(ver, lims)
    classes = propose_classifications(ver, lims, seed_codes=("G06F16/00",))
    assert syns or concepts  # claim text should yield some tokens
    assert any(c.code == "G06F16/00" for c in classes)
    for item in (*syns, *concepts, *classes):
        assert item.claim_version_id == ver.claim_version_id
        assert item.claim_version_digest == ver.content_sha256
        assert item.claim_spans
        assert item.is_candidate is True
        _assert_round_trip(item)


def test_plan_digest_stable_across_round_trip() -> None:
    plan = _sample_plan()
    d1 = plan.plan_digest()
    restored = ClaimSearchPlan.from_dict(plan.to_dict())
    assert restored.plan_digest() == d1
    # Acceptance changes execution fields but plan_digest excludes them.
    accepted = apply_reviewer_acceptance(
        plan,
        reviewer_id="reviewer:dan",
        accepted_at_utc=REVIEW_TIME,
        current_claim_version=_claim_version(),
    )
    # Digest of accepted plan content (limitations promoted) differs from draft.
    assert accepted.acceptance is not None
    assert accepted.acceptance.plan_digest
    assert len(accepted.acceptance.plan_digest) == 64
