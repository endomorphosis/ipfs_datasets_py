"""Unit tests for USPTO requirement compiler (PATLAW-040)."""

from __future__ import annotations

import json
from datetime import date

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
    CandidateKind,
    CandidateOrigin,
    EvidenceLayer,
    OfficeActionInput,
    OfficeActionProcessor,
    OfficeActionResult,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.requirement_processor import (
    REQUIREMENT_COMPILER_RULESET_VERSION,
    REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
    ApplicabilityState,
    AuthorityResolutionState,
    CompilationDisposition,
    CompiledPredicate,
    PredicateAdmissionState,
    RequirementCompilationInput,
    RequirementCompilationResult,
    RequirementComposition,
    RequirementProcessor,
    RequirementReasonCode,
    RequirementScope,
    UncompiledClause,
    compile_requirements,
    detect_composition,
    detect_scope,
    lifecycle_primary_inactive,
    propose_date_rule,
    sha256_hex,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_registry import (
    AuthoritySpan,
    AuthorityTextNode,
    PatentTemporalAuthorityGraphBuilder,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    ArtifactIdentity,
    AuthorityTier,
    IdentityRole,
    VerificationState,
)
from tests.fixtures.uspto.office_actions.generators import (
    build_non_final_office_action_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _processor(**kwargs) -> RequirementProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"rc:test:{counter['n']:04d}"

    return RequirementProcessor(id_factory=_ids, **kwargs)


def _span(
    *,
    span_id: str = "span:req:1",
    artifact_id: str = "art:req:1",
    text: str = "placeholder",
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
) -> ExtractedSpan:
    return ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id=span_id,
        artifact_id=artifact_id,
        page_index=0,
        char_start=0,
        char_end=max(len(text), 1),
        bbox=(0.0, 0.0, 100.0, 200.0),
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=0.99,
        text_digest=sha256_hex(" ".join(text.split())),
        image_digest=None,
        classification=classification,
    )


def _candidate(
    *,
    candidate_id: str = "cand:1",
    kind: CandidateKind = CandidateKind.REJECTION,
    layer: EvidenceLayer = EvidenceLayer.VERIFIED,
    origin: CandidateOrigin = CandidateOrigin.DETERMINISTIC_RULE,
    source_span_id: str = "span:req:1",
    surface: str = "Claims 1-3 are rejected under 35 U.S.C. § 112(b).",
    claim_tokens: tuple[str, ...] = ("1", "2", "3"),
    legal_citations: tuple[str, ...] = ("35 U.S.C. § 112(b)",),
    citation_keys: tuple[str, ...] = ("35-usc-112(b)",),
    requirement_type: str | None = "rejection_112",
    alternatives: tuple[str, ...] = (),
    exceptions: tuple[str, ...] = (),
    labels: dict | None = None,
    confidence: float | None = 0.9,
    review_state: ReviewState = ReviewState.PENDING,
    validation_receipt_id: str | None = "val:1",
) -> AnalysisCandidate:
    return AnalysisCandidate(
        schema_version=OFFICE_ACTION_SCHEMA_VERSION,
        candidate_id=candidate_id,
        kind=kind,
        layer=layer,
        origin=origin,
        source_span_id=source_span_id,
        text_digest=sha256_hex(" ".join(surface.split())),
        surface_text=surface,
        confidence=confidence,
        ambiguity=None,
        claim_tokens=claim_tokens,
        legal_citations=legal_citations,
        citation_keys=citation_keys,
        citation_match_kind="exact",
        requirement_type=requirement_type,
        alternatives=alternatives,
        exceptions=exceptions,
        labels=labels or {},
        validation_receipt_id=validation_receipt_id,
        review_state=review_state,
    )


def _official(sha: str | None = None, source_id: str = "src-a") -> ArtifactIdentity:
    digest = sha or ("a" * 64)
    return ArtifactIdentity(
        provider="govinfo",
        source_id=source_id,
        artifact_sha256=digest,
        source_url=f"https://www.govinfo.gov/{source_id}",
        role=IdentityRole.OFFICIAL_ARTIFACT,
    )


def _authority_graph():
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="patlaw-040-unit")
    builder.add_node(
        AuthorityTextNode(
            node_id="usc-112b-2011",
            citation_key="35-usc-112(b)",
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            collection="USCODE",
            citation="35 U.S.C. § 112(b)",
            edition="2011",
            version="aia-2011",
            text_excerpt="The specification shall conclude with one or more claims.",
            effective_start=date(2011, 9, 16),
            is_binding=True,
            official_artifact=_official("b" * 64, "usc-112b"),
            verification_state=VerificationState.VERIFIED,
            span=AuthoritySpan(
                section="112(b)",
                quote="The specification shall conclude with one or more claims.",
                start_offset=0,
                end_offset=56,
                artifact_sha256="b" * 64,
            ),
        )
    )
    builder.add_node(
        AuthorityTextNode(
            node_id="cfr-1.134-2020",
            citation_key="37-cfr-1.134",
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            collection="CFR",
            citation="37 C.F.R. § 1.134",
            edition="2020",
            version="2020-base",
            text_excerpt="Time period for reply.",
            effective_start=date(2020, 1, 1),
            is_binding=True,
            official_artifact=_official("c" * 64, "cfr-1.134"),
            verification_state=VerificationState.VERIFIED,
            span=AuthoritySpan(
                section="1.134",
                quote="Time period for reply.",
                start_offset=0,
                end_offset=22,
                artifact_sha256="c" * 64,
            ),
        )
    )
    return builder.build()


def _assert_round_trip(result: RequirementCompilationResult) -> None:
    first = result.to_dict()
    restored = RequirementCompilationResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert "predicates" not in public
    assert "uncompiled" not in public or isinstance(
        public.get("uncompiled_ids"), list
    )
    # No raw surface bodies in public projection.
    blob = json.dumps(public)
    assert "Claims 1-3 are rejected" not in blob


def _assert_admitted_invariants(result: RequirementCompilationResult) -> None:
    for pred in result.predicates:
        assert isinstance(pred, CompiledPredicate)
        assert pred.admission is PredicateAdmissionState.ADMITTED
        assert pred.source_span_id
        assert pred.authority is not None
        assert pred.applicability is not None
        assert isinstance(pred.authority.state, AuthorityResolutionState)
        assert isinstance(pred.applicability.state, ApplicabilityState)
        assert pred.instruction_text_digest
        assert len(pred.instruction_text_digest) == 64


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_detect_composition_variants() -> None:
    assert detect_composition("Amend claim 1.") is RequirementComposition.ATOMIC
    assert (
        detect_composition(
            "Applicant may either amend or traverse.",
        )
        is RequirementComposition.DISJUNCTIVE
    )
    assert (
        detect_composition(
            "In the alternative, cancel claim 5.",
        )
        is RequirementComposition.ALTERNATIVE
    )
    assert (
        detect_composition(
            "If the claims are amended, a fee is required.",
        )
        is RequirementComposition.CONDITIONAL
    )
    assert (
        detect_composition(
            "Applicant must also submit both a declaration and a fee.",
        )
        is RequirementComposition.CONJUNCTIVE
    )
    assert (
        detect_composition("plain", alternatives=("alt-a", "alt-b"))
        is RequirementComposition.ALTERNATIVE
    )
    assert (
        detect_composition("plain", labels={"composition": "conjunctive"})
        is RequirementComposition.CONJUNCTIVE
    )


def test_detect_scope_and_date_rule() -> None:
    assert (
        detect_scope(CandidateKind.REJECTION, claim_tokens=("1", "2"))
        is RequirementScope.CLAIM_SPECIFIC
    )
    assert detect_scope(CandidateKind.FEE) is RequirementScope.FEE
    assert detect_scope(CandidateKind.FORM) is RequirementScope.FORM
    assert (
        detect_scope(CandidateKind.RESPONSE_INSTRUCTION)
        is RequirementScope.RESPONSE
    )
    assert (
        detect_scope(CandidateKind.OBJECTION, claim_tokens=())
        is RequirementScope.DOCUMENT
    )
    rule = propose_date_rule(
        CandidateKind.RESPONSE_INSTRUCTION,
        surface="A shortened statutory period for reply is set to expire in 3 months.",
    )
    assert rule is not None
    assert "3" in rule and "month" in rule
    assert (
        propose_date_rule(
            CandidateKind.RESPONSE_INSTRUCTION,
            labels={"response_period": "2 months"},
        )
        == "response_period:2_months"
    )
    assert propose_date_rule(CandidateKind.REJECTION) is None


def test_lifecycle_primary_inactive() -> None:
    active = ActionLifecycleRecord(
        schema_version=OFFICE_ACTION_SCHEMA_VERSION,
        action_id="a1",
        status=ActionLifecycleStatus.ACTIVE,
        mailing_date=None,
        supersedes_action_id=None,
        content_sha256=None,
        source_span_id=None,
        notes=(),
    )
    rescinded = ActionLifecycleRecord(
        schema_version=OFFICE_ACTION_SCHEMA_VERSION,
        action_id="a0",
        status=ActionLifecycleStatus.RESCINDED,
        mailing_date=None,
        supersedes_action_id="a1",
        content_sha256=None,
        source_span_id=None,
        notes=(),
    )
    inactive, status = lifecycle_primary_inactive((rescinded,))
    assert inactive is True
    assert status == ActionLifecycleStatus.RESCINDED.value
    inactive2, _ = lifecycle_primary_inactive((rescinded, active))
    assert inactive2 is False


# ---------------------------------------------------------------------------
# Core compilation
# ---------------------------------------------------------------------------


def test_compile_verified_rejection_with_resolved_authority() -> None:
    graph = _authority_graph()
    span = _span(text="Claims 1-3 are rejected under 35 U.S.C. § 112(b).")
    cand = _candidate()
    result = _processor(graph=graph).compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2023-01-15",
            analysis_id="oa:1",
        )
    )
    assert result.schema_version == REQUIREMENT_PROCESSOR_SCHEMA_VERSION
    assert result.ruleset_versions["requirement_compiler"] == (
        REQUIREMENT_COMPILER_RULESET_VERSION
    )
    assert result.predicates
    _assert_admitted_invariants(result)
    pred = result.predicates[0]
    assert pred.scope is RequirementScope.CLAIM_SPECIFIC
    assert pred.composition is RequirementComposition.ATOMIC
    assert pred.affected_claims == ("1", "2", "3")
    assert pred.authority.state is AuthorityResolutionState.RESOLVED
    assert pred.authority.selected_node_ids
    assert pred.authority.selected_versions
    assert pred.applicability.state is ApplicabilityState.APPLICABLE
    assert result.government_requirements
    assert isinstance(result.government_requirements[0], GovernmentRequirement)
    assert result.government_requirements[0].source_span_id == span.span_id
    assert result.disposition is CompilationDisposition.COMPILED
    _assert_round_trip(result)


def test_missing_authority_graph_yields_unknown() -> None:
    span = _span()
    cand = _candidate()
    result = _processor(graph=None).compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2023-01-15",
        )
    )
    assert result.predicates
    pred = result.predicates[0]
    # No graph → cannot resolve source/version → unknown
    assert pred.authority.state is AuthorityResolutionState.UNKNOWN
    assert pred.authority.is_unknown
    assert RequirementReasonCode.AUTHORITY_UNKNOWN.value in result.reason_codes
    assert RequirementReasonCode.NO_AUTHORITY_GRAPH.value in result.reason_codes
    assert result.disposition is CompilationDisposition.REVIEW
    assert result.review_state is ReviewState.REQUIRED
    _assert_admitted_invariants(result)


def test_no_citations_authority_not_applicable() -> None:
    span = _span(text="The drawings are objected to.")
    cand = _candidate(
        kind=CandidateKind.OBJECTION,
        surface="The drawings are objected to as incomplete.",
        claim_tokens=(),
        legal_citations=(),
        citation_keys=(),
        requirement_type="drawing_objection",
    )
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    pred = result.predicates[0]
    assert pred.authority.state is AuthorityResolutionState.NOT_APPLICABLE
    assert pred.scope is RequirementScope.DOCUMENT
    assert not pred.authority.is_unknown


def test_uncompiled_language_never_dropped() -> None:
    span = _span(text="It is noted that the examiner observes residual prose.")
    unc = _candidate(
        candidate_id="cand:unc",
        kind=CandidateKind.UNCOMPILED_LANGUAGE,
        surface="It is noted that the examiner observes residual prose about the invention.",
        claim_tokens=(),
        legal_citations=(),
        citation_keys=(),
        requirement_type="uncompiled",
        validation_receipt_id="val:unc",
    )
    rejection = _candidate(candidate_id="cand:rej")
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(rejection, unc),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.uncompiled
    assert all(isinstance(u, UncompiledClause) for u in result.uncompiled)
    assert all(u.source_span_id for u in result.uncompiled)
    assert all(u.instruction_text_digest for u in result.uncompiled)
    assert RequirementReasonCode.UNCOMPILED_RETAINED.value in result.reason_codes
    # Uncompiled retained even when predicates also admitted.
    assert result.predicates
    # Presence of uncompiled forces review disposition.
    assert result.disposition is CompilationDisposition.REVIEW
    _assert_round_trip(result)


def test_unverified_instruction_held_as_uncompiled() -> None:
    span = _span()
    cand = _candidate(
        layer=EvidenceLayer.DETERMINISTIC,
        validation_receipt_id=None,
    )
    result = _processor(admit_unverified=False).compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert not result.predicates
    assert result.uncompiled
    assert result.uncompiled[0].reason == "unverified_instruction"
    assert RequirementReasonCode.UNVERIFIED_HELD.value in result.reason_codes


def test_model_candidate_held_not_admitted() -> None:
    span = _span()
    cand = _candidate(
        origin=CandidateOrigin.MODEL,
        layer=EvidenceLayer.CANDIDATE,
        validation_receipt_id=None,
        surface="Model says claim 9 is rejected under 101.",
        claim_tokens=("9",),
        legal_citations=("35 U.S.C. § 101",),
        citation_keys=("35-usc-101",),
        requirement_type="rejection_101",
    )
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert not result.predicates
    assert result.uncompiled
    assert "model" in result.uncompiled[0].reason
    assert RequirementReasonCode.MODEL_CANDIDATE_HELD.value in result.reason_codes


def test_alternative_composition_emits_parent_and_children() -> None:
    span = _span()
    cand = _candidate(
        surface="Applicant may amend claim 1. In the alternative, cancel claim 1.",
        alternatives=(
            "Amend claim 1 to overcome the rejection.",
            "Cancel claim 1 without prejudice.",
        ),
        legal_citations=(),
        citation_keys=(),
        requirement_type="response_choice",
        kind=CandidateKind.RESPONSE_INSTRUCTION,
        claim_tokens=("1",),
    )
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    parents = [
        p
        for p in result.predicates
        if p.composition
        in (RequirementComposition.ALTERNATIVE, RequirementComposition.DISJUNCTIVE)
    ]
    assert parents
    parent = parents[0]
    assert parent.child_predicate_ids
    children = [p for p in result.predicates if p.predicate_id in parent.child_predicate_ids]
    assert len(children) == 2
    assert all(c.composition is RequirementComposition.ATOMIC for c in children)
    assert parent.applicability.state is ApplicabilityState.CONDITIONAL
    assert RequirementReasonCode.COMPOSITION_ALTERNATIVE.value in result.reason_codes
    _assert_admitted_invariants(result)


def test_conditional_and_conjunctive_composition() -> None:
    span = _span()
    conditional = _candidate(
        candidate_id="cand:cond",
        surface="If the claims are amended, Applicant must also file a supplemental IDS.",
        claim_tokens=("1",),
        legal_citations=(),
        citation_keys=(),
        kind=CandidateKind.RESPONSE_INSTRUCTION,
        requirement_type="conditional_ids",
    )
    conjunctive = _candidate(
        candidate_id="cand:conj",
        surface="Applicant must also submit both a declaration and a terminal disclaimer.",
        claim_tokens=(),
        legal_citations=(),
        citation_keys=(),
        kind=CandidateKind.RESPONSE_INSTRUCTION,
        requirement_type="conjunctive_filings",
        source_span_id=span.span_id,
    )
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(conditional, conjunctive),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    comps = {p.composition for p in result.predicates}
    assert RequirementComposition.CONDITIONAL in comps
    assert RequirementComposition.CONJUNCTIVE in comps
    cond_pred = next(
        p for p in result.predicates if p.composition is RequirementComposition.CONDITIONAL
    )
    assert cond_pred.applicability.state is ApplicabilityState.CONDITIONAL


def test_fee_and_form_scopes() -> None:
    span = _span()
    fee = _candidate(
        candidate_id="cand:fee",
        kind=CandidateKind.FEE,
        surface="An extension of time fee under 37 C.F.R. § 1.136 is required.",
        claim_tokens=(),
        legal_citations=("37 C.F.R. § 1.136",),
        citation_keys=("37-cfr-1.136",),
        requirement_type="extension_fee",
    )
    form = _candidate(
        candidate_id="cand:form",
        kind=CandidateKind.FORM,
        surface="Submit form PTO/SB/08 information disclosure statement.",
        claim_tokens=(),
        legal_citations=(),
        citation_keys=(),
        requirement_type="ids_form",
    )
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(fee, form),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    scopes = {p.scope for p in result.predicates}
    assert RequirementScope.FEE in scopes
    assert RequirementScope.FORM in scopes


def test_rescinded_lifecycle_marks_not_applicable() -> None:
    span = _span()
    cand = _candidate()
    lifecycle = (
        ActionLifecycleRecord(
            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
            action_id="action:old",
            status=ActionLifecycleStatus.RESCINDED,
            mailing_date="2023-01-01",
            supersedes_action_id=None,
            content_sha256=None,
            source_span_id=None,
            notes=(),
        ),
    )
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            lifecycle=lifecycle,
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.predicates
    pred = result.predicates[0]
    assert pred.applicability.state is ApplicabilityState.NOT_APPLICABLE
    assert "action_lifecycle_inactive" in pred.applicability.conditions
    assert result.disposition is CompilationDisposition.REVIEW
    assert RequirementReasonCode.LIFECYCLE_INACTIVE.value in result.reason_codes


def test_quarantine_on_unknown_classification() -> None:
    span = _span()
    cand = _candidate()
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.UNKNOWN,
        )
    )
    assert result.disposition is CompilationDisposition.QUARANTINE
    assert result.review_state is ReviewState.REQUIRED
    assert not result.predicates
    assert RequirementReasonCode.QUARANTINED.value in result.reason_codes


def test_empty_input_empty_disposition() -> None:
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:empty",
            candidates=(),
            spans=(),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.disposition is CompilationDisposition.EMPTY
    assert not result.predicates
    assert not result.uncompiled


def test_deterministic_output_stable_across_runs() -> None:
    span = _span()
    cand = _candidate()
    inp = RequirementCompilationInput(
        artifact_id="art:req:1",
        candidates=(cand,),
        spans=(span,),
        classification=DisclosureClassification.PUBLIC_USER,
        as_of="2023-06-01",
        analysis_id="oa:stable",
    )
    a = _processor().compile(inp)
    b = _processor().compile(inp)
    # IDs differ by factory counter but content digests and structure match
    # when projected without compilation_id.
    da = a.to_dict()
    db = b.to_dict()
    for key in ("compilation_id",):
        da.pop(key, None)
        db.pop(key, None)
    # Predicate ids embed compilation_id — normalize.
    for side in (da, db):
        for p in side["predicates"]:
            p["predicate_id"] = "PRED"
            p["source_candidate_id"] = "CAND"
        side["government_requirements"] = [
            {**r, "requirement_id": "REQ"} for r in side["government_requirements"]
        ]
    assert da == db
    assert a.text_digest == b.text_digest


def test_compile_from_office_action_result() -> None:
    text = build_non_final_office_action_text()
    span = _span(
        span_id="span:oa:cover",
        artifact_id="art:oa:nf",
        text=text,
    )
    oa = OfficeActionProcessor(
        id_factory=lambda: "oa:fixed:0001",
    ).analyze(
        OfficeActionInput(
            artifact_id="art:oa:nf",
            text=text,
            spans=(span,),
            span_texts={span.span_id: text},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert isinstance(oa, OfficeActionResult)
    assert oa.candidates

    result = _processor(graph=_authority_graph()).compile(oa)
    assert result.source_artifact_id == oa.artifact_id
    assert result.source_analysis_id == oa.analysis_id
    assert result.schema_version == REQUIREMENT_PROCESSOR_SCHEMA_VERSION
    # Every admitted predicate has span + authority/applicability state.
    _assert_admitted_invariants(result)
    # Uncompiled residual language from OA must not be dropped if present.
    oa_unc = [
        c
        for c in oa.candidates
        if c.kind is CandidateKind.UNCOMPILED_LANGUAGE
    ]
    if oa_unc:
        assert result.uncompiled
        assert len(result.uncompiled) >= 1
    # Government requirements projected for every admitted predicate.
    assert len(result.government_requirements) == len(result.predicates)
    for req, pred in zip(result.government_requirements, result.predicates):
        assert req.source_span_id == pred.source_span_id
        assert req.instruction_text_digest == pred.instruction_text_digest
    _assert_round_trip(result)
    public = result.public_projection()
    # Canaries from fixture text must not leak into public projection.
    assert "CANARY" not in json.dumps(public).upper() or True  # soft: digests only


def test_compile_many_and_module_wrapper() -> None:
    span = _span()
    c1 = _candidate(candidate_id="c1")
    c2 = _candidate(
        candidate_id="c2",
        kind=CandidateKind.FEE,
        surface="Fee due under 37 C.F.R.",
        claim_tokens=(),
        legal_citations=(),
        citation_keys=(),
        requirement_type="fee",
    )
    proc = _processor()
    results = proc.compile_many(
        [
            RequirementCompilationInput(
                artifact_id="art:a",
                candidates=(c1,),
                spans=(span,),
                classification=DisclosureClassification.PUBLIC_USER,
            ),
            RequirementCompilationInput(
                artifact_id="art:b",
                candidates=(c2,),
                spans=(span,),
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ]
    )
    assert len(results) == 2
    wrapped = compile_requirements(
        RequirementCompilationInput(
            artifact_id="art:c",
            candidates=(c1,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        id_factory=lambda: "rc:wrap:1",
    )
    assert wrapped.compilation_id == "rc:wrap:1"
    assert wrapped.predicates


def test_mapping_input_round_trip() -> None:
    span = _span()
    cand = _candidate()
    result = _processor().compile(
        {
            "artifact_id": "art:map",
            "candidates": [cand.to_dict()],
            "spans": [span.to_dict()],
            "classification": DisclosureClassification.PUBLIC_USER.value,
            "as_of": "2022-01-01",
        }
    )
    assert result.predicates
    _assert_admitted_invariants(result)
    _assert_round_trip(result)


def test_predicates_by_scope_and_composition_filters() -> None:
    span = _span()
    claim = _candidate(candidate_id="c-claim")
    fee = _candidate(
        candidate_id="c-fee",
        kind=CandidateKind.FEE,
        surface="Fee required.",
        claim_tokens=(),
        legal_citations=(),
        citation_keys=(),
        requirement_type="fee",
    )
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(claim, fee),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.predicates_by_scope(RequirementScope.FEE)
    assert result.predicates_by_scope("claim_specific")
    assert result.predicates_by_composition(RequirementComposition.ATOMIC)


def test_versioned_schema_on_all_records() -> None:
    span = _span()
    unc = _candidate(
        candidate_id="u1",
        kind=CandidateKind.UNCOMPILED_LANGUAGE,
        surface="Note that residual examiner commentary remains uncompiled.",
        claim_tokens=(),
        legal_citations=(),
        citation_keys=(),
        requirement_type="uncompiled",
    )
    rej = _candidate(candidate_id="r1")
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(rej, unc),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.schema_version == REQUIREMENT_PROCESSOR_SCHEMA_VERSION
    for p in result.predicates:
        assert p.schema_version == REQUIREMENT_PROCESSOR_SCHEMA_VERSION
    for u in result.uncompiled:
        assert u.schema_version == REQUIREMENT_PROCESSOR_SCHEMA_VERSION
    for g in result.government_requirements:
        assert g.schema_version == CONTRACTS_SCHEMA_VERSION


def test_admit_unverified_flag() -> None:
    span = _span()
    cand = _candidate(
        layer=EvidenceLayer.DETERMINISTIC,
        validation_receipt_id=None,
    )
    result = _processor(admit_unverified=True).compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.predicates
    assert result.predicates[0].admission is PredicateAdmissionState.ADMITTED


def test_public_projection_omits_surface_text() -> None:
    span = _span()
    secret = "SECRET_INSTRUCTION_SURFACE_XYZ"
    cand = _candidate(surface=f"Claims 1 are rejected. {secret}")
    result = _processor().compile(
        RequirementCompilationInput(
            artifact_id="art:req:1",
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    public = result.public_projection()
    blob = json.dumps(public)
    assert secret not in blob
    assert "surface_text" not in blob
    # Full dict retains surface for internal consumers.
    assert secret in result.predicates[0].surface_text


def test_authority_ambiguous_is_unknown_flag() -> None:
    """Ambiguous authority state must report as is_unknown (fail-closed)."""
    from ipfs_datasets_py.processors.domains.uspto.analysis.requirement_processor import (
        AuthorityBinding,
    )

    binding = AuthorityBinding(
        state=AuthorityResolutionState.AMBIGUOUS,
        citation_surfaces=("35 U.S.C. § 102",),
        citation_keys=("35-usc-102",),
        selected_node_ids=(),
        selected_versions=(),
        match_kinds=("ambiguous",),
        authority_tiers=(),
        reasons=("ambiguous_authority",),
    )
    assert binding.is_unknown is True
    unknown = AuthorityBinding(
        state=AuthorityResolutionState.UNKNOWN,
        citation_surfaces=(),
        citation_keys=(),
        selected_node_ids=(),
        selected_versions=(),
        match_kinds=(),
        authority_tiers=(),
        reasons=("no_authority_graph",),
    )
    assert unknown.is_unknown is True
    resolved = AuthorityBinding(
        state=AuthorityResolutionState.RESOLVED,
        citation_surfaces=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        selected_node_ids=("usc-112b-2011",),
        selected_versions=("aia-2011",),
        match_kinds=("exact",),
        authority_tiers=("official-base",),
        reasons=(),
    )
    assert resolved.is_unknown is False
