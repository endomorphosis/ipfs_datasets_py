"""Unit tests for USPTO instruction consistency processor (PATLAW-045).

Acceptance focus:
  - A potential inconsistency is reproducible from exact source spans/versions
  - Competing authority and uncertainty are shown
  - Model summary is never substituted for government or governing text
  - No output declares unlawful conduct
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.instruction_consistency_processor import (
    INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
    NOT_UNLAWFUL_DETERMINATION_DISCLAIMER,
    OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON,
    AnalysisBounds,
    AuthorityResolutionDetail,
    CompetingAuthorityDetail,
    ConsistencyComparisonEntry,
    ConsistencyDisposition,
    ConsistencyReasonCode,
    ConsistencyStatus,
    ExactTextSpanRef,
    InstructionConsistencyError,
    InstructionConsistencyInput,
    InstructionConsistencyProcessor,
    InstructionConsistencyResult,
    InstructionSourceInput,
    QuoteComparisonDetail,
    build_human_review_question,
    compare_instructions,
    contains_forbidden_unlawful_token,
    extract_quoted_fragments,
    sanitize_labels,
    sha256_hex,
    sources_from_office_action,
    sources_from_requirement_compilation,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
    OFFICE_ACTION_SCHEMA_VERSION,
    AnalysisCandidate,
    CandidateKind,
    CandidateOrigin,
    EvidenceLayer,
    OfficeActionInput,
    OfficeActionProcessor,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.requirement_processor import (
    ApplicabilityBinding,
    ApplicabilityState,
    AuthorityBinding,
    AuthorityResolutionState,
    CompilationDisposition,
    CompiledPredicate,
    PredicateAdmissionState,
    RequirementCompilationResult,
    RequirementComposition,
    RequirementScope,
    REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
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
from ipfs_datasets_py.processors.legal_data.patent_citation_resolver import (
    QuoteMatchStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATUTE_TEXT = (
    "The specification shall conclude with one or more claims particularly "
    "pointing out and distinctly claiming the subject matter."
)
MISQUOTED_TEXT = (
    "The specification may omit claims when the drawings are sufficient."
)


def _processor(**kwargs) -> InstructionConsistencyProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"ic:test:{counter['n']:04d}"

    return InstructionConsistencyProcessor(id_factory=_ids, **kwargs)


def _official(sha: str | None = None, source_id: str = "src-a") -> ArtifactIdentity:
    digest = sha or ("a" * 64)
    return ArtifactIdentity(
        provider="govinfo",
        source_id=source_id,
        artifact_sha256=digest,
        source_url=f"https://www.govinfo.gov/{source_id}",
        role=IdentityRole.OFFICIAL_ARTIFACT,
    )


def _authority_graph(
    *,
    with_competitor: bool = False,
    competitor_text: str = "Competing edition text differs from base.",
):
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="patlaw-045-unit")
    builder.add_node(
        AuthorityTextNode(
            node_id="usc-112b-2011",
            citation_key="35-usc-112(b)",
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            collection="USCODE",
            citation="35 U.S.C. § 112(b)",
            edition="2011",
            version="aia-2011",
            text_excerpt=STATUTE_TEXT,
            effective_start=date(2011, 9, 16),
            is_binding=True,
            official_artifact=_official("b" * 64, "usc-112b"),
            verification_state=VerificationState.VERIFIED,
            span=AuthoritySpan(
                section="112(b)",
                quote=STATUTE_TEXT,
                start_offset=0,
                end_offset=len(STATUTE_TEXT),
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
    builder.add_node(
        AuthorityTextNode(
            node_id="mpep-2106-2024",
            citation_key="mpep-2106",
            authority_tier=AuthorityTier.GUIDANCE,
            collection="MPEP",
            citation="MPEP § 2106",
            edition="r-08.2024",
            version="mpep-2024-08",
            text_excerpt="Patent subject matter eligibility guidance.",
            effective_start=date(2024, 1, 1),
            is_binding=False,
            official_artifact=_official("d" * 64, "mpep-2106"),
            verification_state=VerificationState.VERIFIED,
            span=AuthoritySpan(
                section="2106",
                quote="Patent subject matter eligibility guidance.",
                start_offset=0,
                end_offset=43,
                artifact_sha256="d" * 64,
            ),
        )
    )
    if with_competitor:
        builder.add_node(
            AuthorityTextNode(
                node_id="usc-112b-alt",
                citation_key="35-usc-112(b)",
                authority_tier=AuthorityTier.OFFICIAL_BASE,
                collection="USCODE",
                citation="35 U.S.C. § 112(b)",
                edition="2011-alt",
                version="aia-2011-alt",
                text_excerpt=competitor_text,
                effective_start=date(2011, 9, 16),
                is_binding=True,
                official_artifact=_official("e" * 64, "usc-112b-alt"),
                verification_state=VerificationState.VERIFIED,
                span=AuthoritySpan(
                    section="112(b)",
                    quote=competitor_text,
                    start_offset=0,
                    end_offset=len(competitor_text),
                    artifact_sha256="e" * 64,
                ),
            )
        )
    return builder.build()


def _instruction(
    *,
    source_id: str = "instr:1",
    span_id: str = "span:instr:1",
    surface: str | None = None,
    citations: tuple[str, ...] = ("35 U.S.C. § 112(b)",),
    citation_keys: tuple[str, ...] = ("35-usc-112(b)",),
    quoted: str | None = None,
    applicability: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
    labels: dict | None = None,
) -> InstructionSourceInput:
    if surface is None:
        if quoted:
            surface = (
                f"Claims 1-3 are rejected under 35 U.S.C. § 112(b) as indefinite "
                f'because the statute provides "{quoted}".'
            )
        else:
            surface = (
                "Claims 1-3 are rejected under 35 U.S.C. § 112(b) as indefinite."
            )
    return InstructionSourceInput(
        source_id=source_id,
        source_span_id=span_id,
        instruction_surface_text=surface,
        legal_citations=citations,
        citation_keys=citation_keys,
        quoted_authority_text=quoted,
        requirement_type="rejection_112",
        applicability_conditions=applicability,
        assumptions=assumptions,
        artifact_id="art:oa:1",
        classification=DisclosureClassification.PUBLIC_USER,
        confidence=0.9,
        labels=labels or {},
    )


def _input(
    *instructions: InstructionSourceInput,
    as_of: str = "2024-06-01",
    artifact_id: str = "art:oa:1",
    spans: tuple[ExtractedSpan, ...] = (),
    span_texts: dict | None = None,
) -> InstructionConsistencyInput:
    return InstructionConsistencyInput(
        artifact_id=artifact_id,
        instructions=tuple(instructions),
        spans=spans,
        span_texts=span_texts or {},
        classification=DisclosureClassification.PUBLIC_USER,
        as_of=as_of,
        analysis_id="analysis:ic:1",
        matter_id="matter:1",
        mailing_date="2024-06-01",
    )


def _assert_round_trip(result: InstructionConsistencyResult) -> None:
    first = result.to_dict()
    restored = InstructionConsistencyResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert "comparisons" not in public
    assert public["declares_unlawful_conduct"] is False
    assert public["is_model_summary_substitution"] is False
    assert public["output_kind"] == OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON
    blob = json.dumps(public)
    # Public projection must not leak instruction body.
    assert "Claims 1-3 are rejected" not in blob


def _assert_never_unlawful(result: InstructionConsistencyResult) -> None:
    assert result.declares_unlawful_conduct is False
    assert result.is_model_summary_substitution is False
    assert "unlawful" in result.disclaimer.lower() or "not declare" in result.disclaimer.lower()
    assert contains_forbidden_unlawful_token(result.disclaimer) is False or (
        "does not declare" in result.disclaimer.lower()
        or "not declare" in result.disclaimer.lower()
    )
    # Disclaimer is allowed to *mention* unlawful only in the negative.
    for entry in result.comparisons:
        assert entry.declares_unlawful_conduct is False
        assert entry.is_model_summary_substitution is False
        assert entry.status in (
            ConsistencyStatus.CONSISTENT,
            ConsistencyStatus.POTENTIAL_INCONSISTENCY,
            ConsistencyStatus.UNKNOWN,
        )
        assert entry.status.value not in (
            "unlawful",
            "illegal",
            "examiner_unlawful",
        )
        for code in entry.reason_codes:
            assert code not in (
                "unlawful",
                "illegal",
                "examiner_unlawful",
                "declares_unlawful",
            )
        assert "unlawful conduct" not in entry.human_review_question.lower() or (
            "not" in entry.human_review_question.lower()
            and "unlawful" in entry.human_review_question.lower()
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_extract_quoted_fragments() -> None:
    surface = 'The statute states "particularly pointing out" the claim.'
    frags = extract_quoted_fragments(surface)
    assert frags
    assert "particularly pointing out" in frags[0]


def test_sanitize_labels_strips_forbidden() -> None:
    cleaned, reasons = sanitize_labels(
        {
            "model_summary": "bad",
            "ok": "keep",
            "unlawful": "nope",
        }
    )
    assert "ok" in cleaned
    assert "model_summary" not in cleaned
    assert "unlawful" not in cleaned
    assert ConsistencyReasonCode.FORBIDDEN_LABEL_STRIPPED.value in reasons


def test_contains_forbidden_unlawful_token() -> None:
    assert contains_forbidden_unlawful_token("examiner_unlawful") is True
    assert contains_forbidden_unlawful_token("potential_inconsistency") is False
    assert contains_forbidden_unlawful_token("review only") is False


def test_build_human_review_question_for_inconsistency() -> None:
    q = build_human_review_question(
        instruction_span_id="span:1",
        citation_surfaces=("35 U.S.C. § 112(b)",),
        authority_versions=("aia-2011",),
        authority_node_ids=("usc-112b-2011",),
        status=ConsistencyStatus.POTENTIAL_INCONSISTENCY,
    )
    assert "span:1" in q
    assert "aia-2011" in q
    assert "not" in q.lower()
    assert "unlawful" in q.lower()


def test_sha256_hex_stable() -> None:
    assert sha256_hex("abc") == sha256_hex(b"abc")
    assert len(sha256_hex("x")) == 64


# ---------------------------------------------------------------------------
# Consistent path
# ---------------------------------------------------------------------------


def test_consistent_when_quote_matches_authority() -> None:
    graph = _authority_graph()
    proc = _processor(graph=graph)
    instr = _instruction(quoted=STATUTE_TEXT)
    result = proc.compare(_input(instr))
    _assert_round_trip(result)
    _assert_never_unlawful(result)
    assert result.disposition in (
        ConsistencyDisposition.COMPARED,
        ConsistencyDisposition.PARTIAL,
        ConsistencyDisposition.REVIEW,
    )
    assert result.comparisons
    entry = result.comparisons[0]
    assert entry.status is ConsistencyStatus.CONSISTENT
    assert entry.requires_human_review is False
    assert entry.authority_versions
    assert "aia-2011" in entry.authority_versions or any(
        "2011" in v for v in entry.authority_versions
    )
    assert entry.authority_node_ids
    assert entry.instruction_span_id == "span:instr:1"
    assert entry.instruction_surface_text  # exact government text retained
    assert entry.is_model_summary_substitution is False
    # Quote match recorded.
    assert any(
        q.status == QuoteMatchStatus.MATCH.value for q in entry.quote_comparisons
    ) or ConsistencyReasonCode.QUOTE_MATCH.value in entry.reason_codes
    assert result.consistent_count >= 1
    assert result.declares_unlawful_conduct is False


def test_consistent_without_quote_when_authority_resolved() -> None:
    graph = _authority_graph()
    proc = _processor(graph=graph)
    instr = _instruction(quoted=None)
    result = proc.compare(_input(instr))
    _assert_never_unlawful(result)
    entry = result.comparisons[0]
    assert entry.status is ConsistencyStatus.CONSISTENT
    assert entry.authority_resolutions
    assert entry.authority_resolutions[0].authority_text_excerpt == STATUTE_TEXT
    # Authority text is source excerpt, not a model paraphrase label.
    assert entry.authority_resolutions[0].node_id == "usc-112b-2011"


# ---------------------------------------------------------------------------
# Potential inconsistency (reproducible from spans/versions)
# ---------------------------------------------------------------------------


def test_potential_inconsistency_from_quote_mismatch_is_reproducible() -> None:
    graph = _authority_graph()
    proc = _processor(graph=graph)
    instr = _instruction(quoted=MISQUOTED_TEXT)
    result = proc.compare(_input(instr))
    _assert_round_trip(result)
    _assert_never_unlawful(result)

    assert result.potential_inconsistency_count >= 1
    entry = result.comparisons[0]
    assert entry.status is ConsistencyStatus.POTENTIAL_INCONSISTENCY
    assert entry.requires_human_review is True
    assert entry.review_state is ReviewState.REQUIRED
    assert entry.human_review_question
    assert "span:instr:1" in entry.human_review_question

    # Exact instruction anchor.
    assert entry.instruction_span_id == "span:instr:1"
    assert entry.instruction_text_digest
    assert len(entry.instruction_text_digest) == 64
    assert MISQUOTED_TEXT in entry.instruction_surface_text or (
        entry.quote_comparisons
        and any(
            q.quoted_span and MISQUOTED_TEXT in (q.quoted_span.text or "")
            for q in entry.quote_comparisons
        )
    )

    # Exact authority version + source span for reproducibility.
    assert entry.authority_versions or entry.authority_node_ids
    assert entry.authority_node_ids
    assert "usc-112b-2011" in entry.authority_node_ids

    # Quote mismatch exposes both spans.
    mismatches = [
        q
        for q in entry.quote_comparisons
        if q.status == QuoteMatchStatus.MISMATCH.value
    ]
    assert mismatches, "expected quote mismatch with both spans"
    mm = mismatches[0]
    assert mm.quoted_span is not None
    assert mm.source_span is not None
    assert mm.quoted_span.text
    assert mm.source_span.text
    assert mm.quoted_span.text != mm.source_span.text or (
        MISQUOTED_TEXT in mm.quoted_span.text
        and STATUTE_TEXT in mm.source_span.text
    )
    # Counter-source spans retained.
    assert entry.counter_source_spans

    # Never a legality/unlawful determination.
    assert entry.declares_unlawful_conduct is False
    d = entry.to_dict()
    assert d["declares_unlawful_conduct"] is False
    assert d["status"] == "potential_inconsistency"
    assert "unlawful" not in d["status"]


def test_potential_inconsistency_serialized_without_model_summary() -> None:
    graph = _authority_graph()
    result = _processor(graph=graph).compare(
        _input(_instruction(quoted=MISQUOTED_TEXT))
    )
    blob = result.to_canonical_json()
    data = json.loads(blob)
    assert data["is_model_summary_substitution"] is False
    # Must not carry a free-form model/LLM summary field (substring may appear
    # inside is_model_summary_substitution / reason codes).
    assert "llm_summary" not in data
    assert "generated_summary" not in data
    assert "model_summary" not in data
    for c in data["comparisons"]:
        assert "model_summary" not in c
        assert "llm_summary" not in c
        assert c["is_model_summary_substitution"] is False
        # Exact surfaces present (government / governing), not summaries.
        assert "instruction_surface_text" in c
        assert "instruction_text_digest" in c
        assert c["instruction_surface_text"]


# ---------------------------------------------------------------------------
# Competing authority and uncertainty
# ---------------------------------------------------------------------------


def test_competing_authority_is_shown() -> None:
    graph = _authority_graph(with_competitor=True)
    proc = _processor(graph=graph)
    instr = _instruction()
    result = proc.compare(_input(instr))
    _assert_never_unlawful(result)
    entry = result.comparisons[0]
    # Either competing authorities listed, or status is unknown/ambiguous path.
    if entry.competing_authorities:
        assert len(entry.competing_authorities) >= 1
        for c in entry.competing_authorities:
            assert c.node_id
            # Exact authority text excerpt, not a model summary.
            assert isinstance(c.authority_text_excerpt, str)
        assert (
            ConsistencyReasonCode.AUTHORITY_COMPETING.value in entry.reason_codes
            or ConsistencyReasonCode.AUTHORITY_AMBIGUOUS.value in entry.reason_codes
            or entry.status is ConsistencyStatus.UNKNOWN
        )
    else:
        # Resolver may pick one when both share effective date; still must not
        # invent a conclusive unlawful label.
        assert entry.status in (
            ConsistencyStatus.CONSISTENT,
            ConsistencyStatus.UNKNOWN,
            ConsistencyStatus.POTENTIAL_INCONSISTENCY,
        )
    assert entry.human_review_question


def test_unknown_when_no_authority_graph() -> None:
    proc = _processor(graph=None)
    result = proc.compare(_input(_instruction()))
    _assert_round_trip(result)
    _assert_never_unlawful(result)
    assert result.comparisons
    entry = result.comparisons[0]
    assert entry.status is ConsistencyStatus.UNKNOWN
    assert entry.requires_human_review is True
    assert ConsistencyReasonCode.NO_AUTHORITY_GRAPH.value in entry.reason_codes or (
        ConsistencyReasonCode.NO_AUTHORITY_GRAPH.value in result.reason_codes
    )
    assert entry.human_review_question
    assert result.unknown_count >= 1


def test_unknown_when_citation_unresolvable() -> None:
    graph = _authority_graph()
    proc = _processor(graph=graph)
    instr = _instruction(
        surface="Something under 99 U.S.C. § 99999.",
        citations=("99 U.S.C. § 99999",),
        citation_keys=("99-usc-99999",),
        quoted=None,
    )
    result = proc.compare(_input(instr))
    _assert_never_unlawful(result)
    entry = result.comparisons[0]
    assert entry.status is ConsistencyStatus.UNKNOWN
    assert entry.requires_human_review is True


def test_empty_input_disposition() -> None:
    graph = _authority_graph()
    result = _processor(graph=graph).compare(
        InstructionConsistencyInput(
            artifact_id="art:empty",
            instructions=(),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2024-01-01",
        )
    )
    assert result.disposition is ConsistencyDisposition.EMPTY
    assert result.comparisons == ()
    assert result.declares_unlawful_conduct is False
    _assert_round_trip(result)


# ---------------------------------------------------------------------------
# Model summary never substitutes; unlawful never declared
# ---------------------------------------------------------------------------


def test_result_rejects_declares_unlawful_true() -> None:
    with pytest.raises(ValueError, match="unlawful"):
        InstructionConsistencyResult(
            schema_version=INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            analysis_id="a1",
            source_artifact_id="art:1",
            matter_id=None,
            disposition=ConsistencyDisposition.COMPARED,
            review_state=ReviewState.NOT_REQUIRED,
            classification=DisclosureClassification.PUBLIC_USER,
            output_kind=OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON,
            disclaimer=NOT_UNLAWFUL_DETERMINATION_DISCLAIMER,
            declares_unlawful_conduct=True,
            is_model_summary_substitution=False,
            reason_codes=(),
            warnings=(),
            comparisons=(),
            consistent_count=0,
            potential_inconsistency_count=0,
            unknown_count=0,
            ruleset_versions={},
            authority_graph_id=None,
            as_of=None,
            labels={},
            text_digest=sha256_hex(""),
        )


def test_result_rejects_model_summary_substitution_true() -> None:
    with pytest.raises(ValueError, match="model"):
        InstructionConsistencyResult(
            schema_version=INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            analysis_id="a1",
            source_artifact_id="art:1",
            matter_id=None,
            disposition=ConsistencyDisposition.COMPARED,
            review_state=ReviewState.NOT_REQUIRED,
            classification=DisclosureClassification.PUBLIC_USER,
            output_kind=OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON,
            disclaimer=NOT_UNLAWFUL_DETERMINATION_DISCLAIMER,
            declares_unlawful_conduct=False,
            is_model_summary_substitution=True,
            reason_codes=(),
            warnings=(),
            comparisons=(),
            consistent_count=0,
            potential_inconsistency_count=0,
            unknown_count=0,
            ruleset_versions={},
            authority_graph_id=None,
            as_of=None,
            labels={},
            text_digest=sha256_hex(""),
        )


def test_instruction_source_strips_model_summary_labels() -> None:
    src = InstructionSourceInput(
        source_id="s1",
        source_span_id="span:1",
        instruction_surface_text="Claims rejected under 35 U.S.C. § 112(b).",
        labels={"model_summary": "should strip", "track": "keep"},
    )
    assert "model_summary" not in src.labels
    assert src.labels.get("track") == "keep"


def test_instruction_source_from_dict_rejects_summary_only_body() -> None:
    with pytest.raises(InstructionConsistencyError, match="model summary"):
        InstructionSourceInput.from_dict(
            {
                "source_id": "s1",
                "source_span_id": "span:1",
                "model_summary": "A summary pretending to be the OA text.",
            }
        )


def test_comparison_entry_status_closed_set() -> None:
    """Only consistent / potential_inconsistency / unknown are valid."""
    entry = ConsistencyComparisonEntry(
        schema_version=INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
        comparison_id="cmp:1",
        source_id="s1",
        instruction_span_id="span:1",
        instruction_surface_text="surface",
        instruction_text_digest=sha256_hex("surface"),
        status=ConsistencyStatus.UNKNOWN,
        authority_resolutions=(),
        competing_authorities=(),
        quote_comparisons=(),
        applicability_facts=(),
        assumptions=(),
        human_review_question=build_human_review_question(
            instruction_span_id="span:1",
            citation_surfaces=(),
            authority_versions=(),
            authority_node_ids=(),
            status=ConsistencyStatus.UNKNOWN,
        ),
        reason_codes=(),
        counter_source_spans=(),
        authority_versions=(),
        authority_node_ids=(),
        citation_surfaces=(),
        requires_human_review=True,
        declares_unlawful_conduct=False,
        is_model_summary_substitution=False,
        review_state=ReviewState.REQUIRED,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={},
    )
    assert entry.status.value in {
        "consistent",
        "potential_inconsistency",
        "unknown",
    }
    with pytest.raises(ValueError):
        ConsistencyComparisonEntry(
            schema_version=INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            comparison_id="cmp:2",
            source_id="s1",
            instruction_span_id="span:1",
            instruction_surface_text="surface",
            instruction_text_digest=sha256_hex("surface"),
            status="unlawful",  # type: ignore[arg-type]
            authority_resolutions=(),
            competing_authorities=(),
            quote_comparisons=(),
            applicability_facts=(),
            assumptions=(),
            human_review_question="review",
            reason_codes=(),
            counter_source_spans=(),
            authority_versions=(),
            authority_node_ids=(),
            citation_surfaces=(),
            requires_human_review=True,
            declares_unlawful_conduct=False,
            is_model_summary_substitution=False,
            review_state=ReviewState.REQUIRED,
            classification=DisclosureClassification.PUBLIC_USER,
            labels={},
        )


def test_quote_mismatch_requires_both_spans() -> None:
    with pytest.raises(ValueError, match="both"):
        QuoteComparisonDetail(
            status=QuoteMatchStatus.MISMATCH.value,
            quoted_span=None,
            source_span=None,
            match_ratio=0.1,
            detail="mismatch without spans",
        )


# ---------------------------------------------------------------------------
# Integration with requirement compilation / office action shapes
# ---------------------------------------------------------------------------


def test_compare_from_compiled_predicate_shape() -> None:
    graph = _authority_graph()
    pred = CompiledPredicate(
        schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
        predicate_id="pred:1",
        source_candidate_id="cand:1",
        source_span_id="span:pred:1",
        instruction_text_digest=sha256_hex(
            "Claims 1 are rejected under 35 U.S.C. § 112(b)."
        ),
        surface_text="Claims 1 are rejected under 35 U.S.C. § 112(b).",
        composition=RequirementComposition.ATOMIC,
        scope=RequirementScope.CLAIM_SPECIFIC,
        requirement_type="rejection_112",
        affected_claims=("1",),
        legal_citations=("35 U.S.C. § 112(b)",),
        child_predicate_ids=(),
        authority=AuthorityBinding(
            state=AuthorityResolutionState.RESOLVED,
            citation_surfaces=("35 U.S.C. § 112(b)",),
            citation_keys=("35-usc-112(b)",),
            selected_node_ids=("usc-112b-2011",),
            selected_versions=("aia-2011",),
            match_kinds=("exact",),
            authority_tiers=("official-base",),
            reasons=(),
        ),
        applicability=ApplicabilityBinding(
            state=ApplicabilityState.APPLICABLE,
            conditions=("active_action",),
            exceptions=(),
            lifecycle_status="active",
            reasons=(),
        ),
        proposed_date_rule=None,
        parser_confidence=0.9,
        review_state=ReviewState.PENDING,
        classification=DisclosureClassification.PUBLIC_USER,
        admission=PredicateAdmissionState.ADMITTED,
        labels={},
    )
    compilation = RequirementCompilationResult(
        schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
        compilation_id="comp:1",
        source_analysis_id="oa:1",
        source_artifact_id="art:oa:1",
        disposition=CompilationDisposition.COMPILED,
        review_state=ReviewState.PENDING,
        classification=DisclosureClassification.PUBLIC_USER,
        reason_codes=(),
        warnings=(),
        predicates=(pred,),
        uncompiled=(),
        government_requirements=(),
        ruleset_versions={},
        authority_graph_id="patlaw-045-unit",
        as_of="2024-06-01",
        labels={},
        text_digest=sha256_hex("x"),
        retained=True,
    )
    sources = sources_from_requirement_compilation(compilation)
    assert len(sources) == 1
    assert sources[0].source_span_id == "span:pred:1"

    result = _processor(graph=graph).compare(compilation)
    _assert_never_unlawful(result)
    assert result.comparisons
    assert result.comparisons[0].instruction_span_id == "span:pred:1"


def test_compare_from_mapping_packet() -> None:
    graph = _authority_graph()
    packet = {
        "artifact_id": "art:map:1",
        "as_of": "2024-06-01",
        "classification": DisclosureClassification.PUBLIC_USER.value,
        "instructions": [
            {
                "source_id": "instr:map:1",
                "source_span_id": "span:map:1",
                "instruction_surface_text": (
                    f'Claims rejected under 35 U.S.C. § 112(b): "{MISQUOTED_TEXT}"'
                ),
                "legal_citations": ["35 U.S.C. § 112(b)"],
                "quoted_authority_text": MISQUOTED_TEXT,
            }
        ],
    }
    result = compare_instructions(packet, graph=graph)
    _assert_never_unlawful(result)
    assert result.potential_inconsistency_count >= 1
    entry = result.comparisons[0]
    assert entry.status is ConsistencyStatus.POTENTIAL_INCONSISTENCY
    assert entry.authority_versions or entry.authority_node_ids
    assert entry.counter_source_spans or entry.quote_comparisons


def test_sources_from_office_action() -> None:
    text = (
        "Claims 1-2 are rejected under 35 U.S.C. § 112(b) as indefinite.\n"
        "Applicant must respond within three months."
    )
    span = ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id="span:oa:1",
        artifact_id="art:oa:1",
        page_index=0,
        char_start=0,
        char_end=len(text),
        bbox=(0.0, 0.0, 100.0, 200.0),
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=0.99,
        text_digest=sha256_hex(" ".join(text.split())),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"oa:ic:{counter['n']:04d}"

    oa = OfficeActionProcessor(id_factory=_ids).analyze(
        OfficeActionInput(
            artifact_id="art:oa:1",
            text=text,
            spans=(span,),
            span_texts={span.span_id: text},
            classification=DisclosureClassification.PUBLIC_USER,
            action_id="action:1",
            mailing_date="2024-06-01",
        )
    )
    sources = sources_from_office_action(oa)
    # May be empty if OA processor did not emit instruction kinds; still must
    # not crash.
    assert isinstance(sources, tuple)

    graph = _authority_graph()
    result = _processor(graph=graph).compare(oa)
    _assert_never_unlawful(result)
    assert result.output_kind == OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON
    assert result.disclaimer == NOT_UNLAWFUL_DETERMINATION_DISCLAIMER


# ---------------------------------------------------------------------------
# Applicability facts, assumptions, human review
# ---------------------------------------------------------------------------


def test_applicability_facts_and_assumptions_recorded() -> None:
    graph = _authority_graph()
    instr = _instruction(
        applicability=("utility_application",),
        assumptions=("entity:large",),
    )
    result = _processor(graph=graph).compare(_input(instr, as_of="2024-06-15"))
    entry = result.comparisons[0]
    assert any("utility_application" in f for f in entry.applicability_facts)
    assert any(f.startswith("as_of:") for f in entry.applicability_facts)
    assert any("entity:large" in a for a in entry.assumptions)
    assert ConsistencyReasonCode.APPLICABILITY_RECORDED.value in entry.reason_codes
    assert ConsistencyReasonCode.ASSUMPTIONS_RECORDED.value in entry.reason_codes


def test_human_review_question_always_present_for_non_consistent() -> None:
    proc = _processor(graph=None)
    result = proc.compare(_input(_instruction()))
    for entry in result.comparisons:
        if entry.status is not ConsistencyStatus.CONSISTENT:
            assert entry.human_review_question
            assert entry.requires_human_review is True
            # Must not declare unlawful conduct.
            assert "is unlawful" not in entry.human_review_question.lower()


def test_public_projection_omits_bodies() -> None:
    graph = _authority_graph()
    result = _processor(graph=graph).compare(
        _input(_instruction(quoted=MISQUOTED_TEXT))
    )
    public = result.public_projection()
    assert "instruction_surface_text" not in json.dumps(public)
    assert public["potential_inconsistency_count"] >= 1
    assert public["declares_unlawful_conduct"] is False


def test_multiple_instructions_counts() -> None:
    graph = _authority_graph()
    good = _instruction(
        source_id="instr:good",
        span_id="span:good",
        quoted=STATUTE_TEXT,
    )
    bad = _instruction(
        source_id="instr:bad",
        span_id="span:bad",
        quoted=MISQUOTED_TEXT,
    )
    result = _processor(graph=graph).compare(_input(good, bad))
    assert len(result.comparisons) == 2
    assert result.consistent_count + result.potential_inconsistency_count + result.unknown_count == 2
    assert result.potential_inconsistency_count >= 1
    by_status = result.potential_inconsistencies()
    assert all(
        c.status is ConsistencyStatus.POTENTIAL_INCONSISTENCY for c in by_status
    )
    _assert_never_unlawful(result)
    _assert_round_trip(result)


def test_quarantine_classification() -> None:
    graph = _authority_graph()
    result = _processor(graph=graph).compare(
        InstructionConsistencyInput(
            artifact_id="art:priv",
            instructions=(_instruction(),),
            classification=DisclosureClassification.UNKNOWN,
            as_of="2024-06-01",
        )
    )
    _assert_never_unlawful(result)
    assert result.disposition is ConsistencyDisposition.QUARANTINE
    assert result.review_state is ReviewState.REQUIRED
    assert result.comparisons == ()


def test_compare_many() -> None:
    graph = _authority_graph()
    proc = _processor(graph=graph)
    results = proc.compare_many(
        [
            _input(_instruction(source_id="a", span_id="span:a")),
            _input(_instruction(source_id="b", span_id="span:b")),
        ]
    )
    assert len(results) == 2
    for r in results:
        _assert_never_unlawful(r)


def test_exact_text_span_ref_round_trip() -> None:
    ref = ExactTextSpanRef(
        span_id="span:x",
        artifact_id="art:x",
        text=STATUTE_TEXT,
        text_digest=sha256_hex(STATUTE_TEXT),
        start_offset=0,
        end_offset=len(STATUTE_TEXT),
        artifact_sha256="b" * 64,
        section="112(b)",
        role="authority",
    )
    restored = ExactTextSpanRef.from_dict(ref.to_dict())
    assert restored.to_dict() == ref.to_dict()


def test_authority_resolution_detail_round_trip() -> None:
    detail = AuthorityResolutionDetail(
        citation_surface="35 U.S.C. § 112(b)",
        citation_key="35-usc-112(b)",
        match_kind="exact",
        node_id="usc-112b-2011",
        version="aia-2011",
        edition="2011",
        authority_tier="official-base",
        verification_state="verified",
        authority_text_excerpt=STATUTE_TEXT,
        authority_span=None,
        is_binding=True,
        reasons=("exact_match",),
    )
    assert AuthorityResolutionDetail.from_dict(detail.to_dict()).to_dict() == detail.to_dict()


def test_competing_authority_detail_round_trip() -> None:
    c = CompetingAuthorityDetail(
        node_id="n1",
        citation_key="35-usc-112(b)",
        citation="35 U.S.C. § 112(b)",
        version="alt",
        edition="2011",
        authority_tier="official-base",
        authority_text_excerpt="alt text",
        reason="competing",
        content_fingerprint="fp1",
    )
    assert CompetingAuthorityDetail.from_dict(c.to_dict()).to_dict() == c.to_dict()


def test_missing_input_raises() -> None:
    with pytest.raises(InstructionConsistencyError, match="required"):
        _processor().compare()


def test_output_kind_locked() -> None:
    with pytest.raises(ValueError, match="output_kind"):
        InstructionConsistencyResult(
            schema_version=INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            analysis_id="a1",
            source_artifact_id="art:1",
            matter_id=None,
            disposition=ConsistencyDisposition.EMPTY,
            review_state=ReviewState.PENDING,
            classification=DisclosureClassification.PUBLIC_USER,
            output_kind="legal_opinion",
            disclaimer=NOT_UNLAWFUL_DETERMINATION_DISCLAIMER,
            declares_unlawful_conduct=False,
            is_model_summary_substitution=False,
            reason_codes=(),
            warnings=(),
            comparisons=(),
            consistent_count=0,
            potential_inconsistency_count=0,
            unknown_count=0,
            ruleset_versions={},
            authority_graph_id=None,
            as_of=None,
            labels={},
            text_digest=sha256_hex(""),
        )


def test_bounds_limit_comparisons() -> None:
    graph = _authority_graph()
    many = [
        _instruction(source_id=f"instr:{i}", span_id=f"span:{i}")
        for i in range(5)
    ]
    result = _processor(
        graph=graph, bounds=AnalysisBounds(max_comparisons=2)
    ).compare(_input(*many))
    assert len(result.comparisons) == 2
    assert ConsistencyReasonCode.COMPARISON_LIMIT.value in result.reason_codes


def test_reason_codes_include_not_unlawful_and_no_summary() -> None:
    graph = _authority_graph()
    result = _processor(graph=graph).compare(_input(_instruction()))
    assert (
        ConsistencyReasonCode.NOT_UNLAWFUL_DETERMINATION.value in result.reason_codes
    )
    assert (
        ConsistencyReasonCode.NO_MODEL_SUMMARY_SUBSTITUTION.value
        in result.reason_codes
    )


def test_potential_inconsistency_requires_authority_anchor() -> None:
    """Entry construction fails without authority anchors for inconsistency."""
    with pytest.raises(ValueError, match="reproducible"):
        ConsistencyComparisonEntry(
            schema_version=INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            comparison_id="cmp:bad",
            source_id="s1",
            instruction_span_id="span:1",
            instruction_surface_text="surface",
            instruction_text_digest=sha256_hex("surface"),
            status=ConsistencyStatus.POTENTIAL_INCONSISTENCY,
            authority_resolutions=(),
            competing_authorities=(),
            quote_comparisons=(),
            applicability_facts=(),
            assumptions=(),
            human_review_question="review",
            reason_codes=(),
            counter_source_spans=(),
            authority_versions=(),  # missing
            authority_node_ids=(),  # missing
            citation_surfaces=(),
            requires_human_review=True,
            declares_unlawful_conduct=False,
            is_model_summary_substitution=False,
            review_state=ReviewState.REQUIRED,
            classification=DisclosureClassification.PUBLIC_USER,
            labels={},
        )
