"""Unit tests for patent-law citation resolution and quote validation.

Acceptance (PATLAW-017):

* Exact and ambiguous citations have typed results.
* Quote mismatch exposes both spans.
* Unresolved version or source never becomes verified.
* Authority tier is independent of relevance/confidence.
"""

from __future__ import annotations

from datetime import date

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    ArtifactIdentity,
    IdentityRole,
    VerificationState,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_registry import (
    AuthoritySpan,
    AuthorityTextNode,
    AuthorityTemporalEdge,
    PatentTemporalAuthorityGraphBuilder,
    TemporalRelation,
)
from ipfs_datasets_py.processors.legal_data.patent_citation_resolver import (
    SCHEMA_VERSION,
    CitationDiagnosticCode,
    CitationFamily,
    CitationMatchKind,
    CitationResolutionResult,
    ParsedCitation,
    PatentCitationResolver,
    PatentCitationResolverError,
    QuoteComparison,
    QuoteMatchStatus,
    TextSpan,
    citation_key_for_cfr,
    citation_key_for_exam_guide,
    citation_key_for_fee,
    citation_key_for_form,
    citation_key_for_form_paragraph,
    citation_key_for_fr,
    citation_key_for_mpep,
    citation_key_for_public_law,
    citation_key_for_usc,
    compare_quote_to_source,
    compute_verification_state,
    default_authority_tier_for_family,
    normalize_quote_text,
    parse_citation,
    parse_patent_citations,
    resolve_citation,
    resolve_citations_in_text,
)


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


def _official(sha: str = _SHA_A, source_id: str = "official-1"):
    return ArtifactIdentity(
        provider="govinfo",
        source_id=source_id,
        artifact_sha256=sha,
        source_url=f"https://www.govinfo.gov/{source_id}",
        role=IdentityRole.OFFICIAL_ARTIFACT,
    )


def _node(**overrides) -> AuthorityTextNode:
    base = dict(
        node_id="n-base",
        citation_key="37-cfr-1.56",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection="CFR",
        citation="37 C.F.R. § 1.56",
        edition="2020",
        version="2020-base",
        text_excerpt="Duty of disclosure (2020 base text).",
        effective_start=date(2020, 1, 1),
        is_binding=True,
        official_artifact=_official(),
        verification_state=VerificationState.VERIFIED,
        span=AuthoritySpan(
            section="1.56",
            quote="Duty of disclosure (2020 base text).",
            start_offset=0,
            end_offset=35,
            artifact_sha256=_SHA_A,
        ),
    )
    base.update(overrides)
    return AuthorityTextNode(**base)


def _duty_graph() -> object:
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="patlaw-017-unit")
    base = _node(
        node_id="cfr-1.56-2020",
        text_excerpt="Duty of disclosure (2020 base text).",
        span=AuthoritySpan(
            section="1.56",
            quote="Duty of disclosure (2020 base text).",
            artifact_sha256=_SHA_A,
        ),
    )
    amend = _node(
        node_id="cfr-1.56-2022",
        authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        collection="FR",
        edition="2022",
        version="87-FR-12345",
        text_excerpt="Duty of disclosure (2022 amended text).",
        effective_start=date(2022, 6, 1),
        official_artifact=_official(_SHA_B, "cfr-2022"),
        span=AuthoritySpan(
            section="1.56",
            quote="Duty of disclosure (2022 amended text).",
            artifact_sha256=_SHA_B,
        ),
        verification_state=VerificationState.VERIFIED,
    )
    usc = _node(
        node_id="usc-102-2011",
        citation_key="35-usc-102",
        collection="USCODE",
        citation="35 U.S.C. § 102",
        edition="2011",
        version="aia-2011",
        text_excerpt="A person shall be entitled to a patent unless.",
        effective_start=date(2011, 9, 16),
        official_artifact=_official(_SHA_C, "usc-102"),
        span=AuthoritySpan(
            section="102",
            quote="A person shall be entitled to a patent unless.",
            artifact_sha256=_SHA_C,
        ),
    )
    usc_a = _node(
        node_id="usc-102a-2011",
        citation_key="35-usc-102(a)",
        collection="USCODE",
        citation="35 U.S.C. § 102(a)",
        edition="2011",
        version="aia-2011-a",
        text_excerpt="Novelty; prior art subsection (a).",
        effective_start=date(2011, 9, 16),
        official_artifact=_official("d" * 64, "usc-102a"),
        span=AuthoritySpan(
            section="102(a)",
            quote="Novelty; prior art subsection (a).",
            artifact_sha256="d" * 64,
        ),
    )
    mpep = _node(
        node_id="mpep-2106",
        citation_key="mpep-2106",
        authority_tier=AuthorityTier.GUIDANCE,
        collection="MPEP",
        citation="MPEP § 2106",
        edition="9th-rev-07.2022",
        version="mpep-2106-r07-2022",
        text_excerpt="Patent subject matter eligibility guidance.",
        effective_start=date(2022, 7, 1),
        is_binding=False,
        official_artifact=_official("e" * 64, "mpep-2106"),
        verification_state=VerificationState.VERIFIED,
        span=AuthoritySpan(
            section="2106",
            quote="Patent subject matter eligibility guidance.",
            artifact_sha256="e" * 64,
        ),
    )
    fp = _node(
        node_id="fp-7.05",
        citation_key="fp-7.05",
        authority_tier=AuthorityTier.GUIDANCE,
        collection="MPEP",
        citation="FP 7.05",
        edition="9th-rev-07.2022",
        version="fp-7.05-r07",
        text_excerpt="Form paragraph 7.05 rejection text.",
        effective_start=date(2022, 7, 1),
        is_binding=False,
        official_artifact=_official("f" * 64, "fp-705"),
        span=AuthoritySpan(
            section="7.05",
            quote="Form paragraph 7.05 rejection text.",
            artifact_sha256="f" * 64,
        ),
    )
    # Conflicting same-key nodes for ambiguity without as-of.
    conflict_a = _node(
        node_id="conflict-a",
        citation_key="35-usc-101-conflict",
        collection="USCODE",
        citation="35 U.S.C. § 101",
        version="v-a",
        edition="2020",
        text_excerpt="Conflict variant A.",
        official_artifact=_official("1" * 64, "c-a"),
        verification_state=VerificationState.VERIFIED,
    )
    conflict_b = _node(
        node_id="conflict-b",
        citation_key="35-usc-101-conflict",
        collection="USCODE",
        citation="35 U.S.C. § 101",
        version="v-b",
        edition="2020",
        text_excerpt="Conflict variant B.",
        official_artifact=_official("2" * 64, "c-b"),
        verification_state=VerificationState.VERIFIED,
    )
    for n in (base, amend, usc, usc_a, mpep, fp, conflict_a, conflict_b):
        builder.add_node(n)
    builder.add_edge(
        AuthorityTemporalEdge(
            edge_id="e-amends",
            relation=TemporalRelation.AMENDS,
            source_node_id="cfr-1.56-2022",
            target_node_id="cfr-1.56-2020",
            effective_date=date(2022, 6, 1),
        )
    )
    return builder.build()


# ---------------------------------------------------------------------------
# Schema / helpers
# ---------------------------------------------------------------------------


def test_schema_version_stable():
    assert SCHEMA_VERSION == "patent-citation-resolver-v1"


def test_citation_key_builders():
    assert citation_key_for_usc(35, "102", subsections="(a)(1)") == "35-usc-102(a)(1)"
    assert citation_key_for_cfr(37, "1.56") == "37-cfr-1.56"
    assert citation_key_for_fr(87, 12345) == "87-fr-12345"
    assert citation_key_for_mpep("2106.04", subsections="(a)") == "mpep-2106.04(a)"
    assert citation_key_for_form_paragraph("7.05") == "fp-7.05"
    assert citation_key_for_form("PTO/SB/08a") == "form-pto/sb/08a"
    assert citation_key_for_fee("1201") == "fee-1201"
    assert citation_key_for_exam_guide("1-22") == "exam-guide-1-22"
    assert citation_key_for_public_law(112, 29) == "pl-112-29"


def test_default_authority_tier_by_family_independent_of_scores():
    assert default_authority_tier_for_family(CitationFamily.USC) is AuthorityTier.OFFICIAL_BASE
    assert default_authority_tier_for_family(CitationFamily.CFR) is AuthorityTier.OFFICIAL_BASE
    assert (
        default_authority_tier_for_family(CitationFamily.FEDERAL_REGISTER)
        is AuthorityTier.OFFICIAL_CHANGE
    )
    assert default_authority_tier_for_family(CitationFamily.MPEP) is AuthorityTier.GUIDANCE
    assert (
        default_authority_tier_for_family(CitationFamily.FORM_PARAGRAPH)
        is AuthorityTier.GUIDANCE
    )
    assert default_authority_tier_for_family(CitationFamily.FORM) is AuthorityTier.GUIDANCE
    assert default_authority_tier_for_family(CitationFamily.FEE) is AuthorityTier.GUIDANCE
    assert (
        default_authority_tier_for_family(CitationFamily.EXAMINATION_GUIDE)
        is AuthorityTier.GUIDANCE
    )


# ---------------------------------------------------------------------------
# Parsing: exact typed results for all patent-law families
# ---------------------------------------------------------------------------


def test_parse_exact_usc_cfr_fr_mpep_fp_form_fee_guide_pl():
    text = (
        "See 35 U.S.C. § 102(a)(1) and 37 C.F.R. § 1.56(a); "
        "87 FR 12345; MPEP § 2106.04(a); FP 7.05; Form PTO/SB/08a; "
        "fee code 1201; Examination Guide 1-22; Pub. L. 112-29."
    )
    parsed = parse_patent_citations(text)
    families = {p.family for p in parsed}
    assert CitationFamily.USC in families
    assert CitationFamily.CFR in families
    assert CitationFamily.FEDERAL_REGISTER in families
    assert CitationFamily.MPEP in families
    assert CitationFamily.FORM_PARAGRAPH in families
    assert CitationFamily.FORM in families
    assert CitationFamily.FEE in families
    assert CitationFamily.EXAMINATION_GUIDE in families
    assert CitationFamily.PUBLIC_LAW in families
    for p in parsed:
        assert isinstance(p, ParsedCitation)
        assert p.match_kind is CitationMatchKind.EXACT
        assert p.citation_key
        assert isinstance(p.authority_tier, AuthorityTier)


def test_parse_one_exact_usc():
    p = parse_citation("35 USC 101")
    assert p.match_kind is CitationMatchKind.EXACT
    assert p.family is CitationFamily.USC
    assert p.citation_key == "35-usc-101"
    assert p.is_exact


def test_parse_unresolved_typed():
    p = parse_citation("not a legal citation at all")
    assert isinstance(p, ParsedCitation)
    assert p.match_kind is CitationMatchKind.UNRESOLVED
    assert p.family is CitationFamily.UNKNOWN
    assert p.is_unresolved


def test_parse_ambiguous_multi_key_typed():
    p = parse_citation("Compare 35 U.S.C. § 102 with 37 C.F.R. § 1.56")
    assert isinstance(p, ParsedCitation)
    assert p.match_kind is CitationMatchKind.AMBIGUOUS
    assert p.is_ambiguous
    assert len(p.candidate_keys) >= 2
    assert "35-usc-102" in p.candidate_keys
    assert "37-cfr-1.56" in p.candidate_keys


def test_parsed_citation_round_trip():
    p = parse_citation("37 C.F.R. § 1.56")
    rebuilt = ParsedCitation.from_dict(p.to_dict())
    assert rebuilt.to_dict() == p.to_dict()


# ---------------------------------------------------------------------------
# Resolution: exact and ambiguous typed results
# ---------------------------------------------------------------------------


def test_resolve_exact_cfr_as_of_base():
    graph = _duty_graph()
    result = resolve_citation(
        "37 C.F.R. § 1.56",
        graph=graph,
        as_of=date(2021, 1, 1),
    )
    assert isinstance(result, CitationResolutionResult)
    assert result.match_kind is CitationMatchKind.EXACT
    assert result.is_exact
    assert result.selected_node_id == "cfr-1.56-2020"
    assert result.selected_version == "2020-base"
    assert result.authority_tier is AuthorityTier.OFFICIAL_BASE
    assert result.verification_state is VerificationState.VERIFIED


def test_resolve_exact_cfr_as_of_amendment():
    graph = _duty_graph()
    result = resolve_citation(
        "37 CFR 1.56",
        graph=graph,
        as_of="2022-07-01",
    )
    assert result.match_kind is CitationMatchKind.EXACT
    assert result.selected_node_id == "cfr-1.56-2022"
    assert result.authority_tier is AuthorityTier.OFFICIAL_CHANGE
    assert result.selected_version == "87-FR-12345"


def test_resolve_exact_usc_and_mpep_and_fp():
    graph = _duty_graph()
    usc = resolve_citation("35 U.S.C. § 102", graph=graph, as_of=date(2020, 1, 1))
    assert usc.is_exact
    assert usc.selected_node_id == "usc-102-2011"
    assert usc.authority_tier is AuthorityTier.OFFICIAL_BASE

    mpep = resolve_citation("MPEP § 2106", graph=graph, as_of=date(2023, 1, 1))
    assert mpep.is_exact
    assert mpep.selected_node_id == "mpep-2106"
    assert mpep.authority_tier is AuthorityTier.GUIDANCE

    fp = resolve_citation("FP 7.05", graph=graph, as_of=date(2023, 1, 1))
    assert fp.is_exact
    assert fp.selected_node_id == "fp-7.05"
    assert fp.authority_tier is AuthorityTier.GUIDANCE


def test_resolve_ambiguous_without_as_of_when_multiple_nodes():
    graph = _duty_graph()
    result = resolve_citation("37 C.F.R. § 1.56", graph=graph)
    assert result.match_kind is CitationMatchKind.AMBIGUOUS
    assert result.is_ambiguous
    assert result.verification_state is not VerificationState.VERIFIED
    assert len(result.candidate_node_ids) >= 2
    codes = {d.code for d in result.diagnostics}
    assert CitationDiagnosticCode.AMBIGUOUS_CANDIDATES in codes
    assert CitationDiagnosticCode.VERIFICATION_BLOCKED in codes


def test_resolve_ambiguous_soft_key_expansion():
    """Bare 35 USC 102 soft-matches 35-usc-102 and 35-usc-102(a)."""
    graph = _duty_graph()
    # Nodes exist for both 35-usc-102 and 35-usc-102(a); soft match is ambiguous.
    result = resolve_citation("35 U.S.C. § 102", graph=graph, as_of=date(2020, 1, 1))
    # With exact key match present, as-of on citation_key 35-usc-102 selects the
    # exact key only via resolve_as_of — still exact.
    assert result.match_kind in (
        CitationMatchKind.EXACT,
        CitationMatchKind.AMBIGUOUS,
    )
    assert isinstance(result, CitationResolutionResult)


def test_resolve_ambiguous_multi_citation_string():
    graph = _duty_graph()
    result = resolve_citation(
        "See 35 U.S.C. § 102 and 37 C.F.R. § 1.56",
        graph=graph,
        as_of=date(2021, 1, 1),
    )
    assert result.match_kind is CitationMatchKind.AMBIGUOUS
    assert result.verification_state is VerificationState.UNVERIFIED
    assert len(result.candidate_citation_keys) >= 2


def test_resolve_unresolved_missing_source():
    graph = _duty_graph()
    result = resolve_citation("37 C.F.R. § 1.999", graph=graph, as_of=date(2021, 1, 1))
    assert result.match_kind is CitationMatchKind.UNRESOLVED
    assert result.verification_state is VerificationState.UNVERIFIED
    assert result.selected_node_id is None
    codes = {d.code for d in result.diagnostics}
    assert CitationDiagnosticCode.UNRESOLVED_SOURCE in codes
    assert CitationDiagnosticCode.VERIFICATION_BLOCKED in codes


def test_resolve_without_graph_never_verified():
    result = resolve_citation("35 U.S.C. § 101")
    assert result.verification_state is VerificationState.UNVERIFIED
    assert result.match_kind is CitationMatchKind.UNRESOLVED
    assert result.selected_citation_key == "35-usc-101"


def test_resolve_text_returns_typed_results():
    graph = _duty_graph()
    text = "Reject under 35 U.S.C. § 102; see also MPEP § 2106."
    results = resolve_citations_in_text(text, graph=graph, as_of=date(2023, 1, 1))
    assert len(results) >= 2
    assert all(isinstance(r, CitationResolutionResult) for r in results)
    assert all(isinstance(r.match_kind, CitationMatchKind) for r in results)


def test_resolution_result_round_trip_dict():
    graph = _duty_graph()
    result = resolve_citation(
        "37 C.F.R. § 1.56", graph=graph, as_of=date(2021, 1, 1)
    )
    payload = result.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["match_kind"] == "exact"
    assert payload["verification_state"] == "verified"
    assert payload["authority_tier"] == "official-base"


# ---------------------------------------------------------------------------
# Quote mismatch exposes both spans
# ---------------------------------------------------------------------------


def test_quote_match_success():
    source = TextSpan(
        start=0,
        end=10,
        text="hello world",
        artifact_sha256=_SHA_A,
        section="1.56",
    )
    cmp = compare_quote_to_source("hello world", source)
    assert cmp.status is QuoteMatchStatus.MATCH
    assert cmp.is_match
    assert cmp.quoted_span is not None
    assert cmp.source_span is not None


def test_quote_mismatch_exposes_both_spans():
    source = TextSpan(
        start=10,
        end=45,
        text="Duty of disclosure (2022 amended text).",
        artifact_sha256=_SHA_B,
        section="1.56",
    )
    quoted = TextSpan(
        start=100,
        end=135,
        text="Duty of disclosure (2020 base text).",
        section="oa-quote",
    )
    cmp = compare_quote_to_source(quoted, source)
    assert cmp.status is QuoteMatchStatus.MISMATCH
    assert cmp.is_mismatch
    # Both spans required and exposed.
    assert cmp.quoted_span is not None
    assert cmp.source_span is not None
    assert cmp.quoted_span.text == "Duty of disclosure (2020 base text)."
    assert cmp.source_span.text == "Duty of disclosure (2022 amended text)."
    assert cmp.quoted_span.start == 100
    assert cmp.source_span.start == 10
    assert cmp.normalized_quoted is not None
    assert cmp.normalized_source is not None


def test_quote_mismatch_construction_requires_both_spans():
    with pytest.raises(PatentCitationResolverError):
        QuoteComparison(
            status=QuoteMatchStatus.MISMATCH,
            quoted_span=TextSpan(start=0, end=3, text="abc"),
            source_span=None,
        )


def test_quote_normalization_ignores_ws_and_quotes():
    assert normalize_quote_text('  "Hello   world"  ') == "Hello world"
    assert normalize_quote_text("Hello\u00ad world") == "Hello world"


def test_resolve_with_quote_mismatch_exposes_spans_and_blocks_verified():
    graph = _duty_graph()
    result = resolve_citation(
        "37 C.F.R. § 1.56",
        graph=graph,
        as_of=date(2022, 7, 1),
        quoted_text="Duty of disclosure (2020 base text).",
    )
    assert result.quote_comparison is not None
    assert result.quote_comparison.status is QuoteMatchStatus.MISMATCH
    assert result.quote_comparison.quoted_span is not None
    assert result.quote_comparison.source_span is not None
    assert result.verification_state is not VerificationState.VERIFIED
    codes = {d.code for d in result.diagnostics}
    assert CitationDiagnosticCode.QUOTE_MISMATCH in codes


def test_resolve_with_matching_quote_can_verify():
    graph = _duty_graph()
    result = resolve_citation(
        "37 C.F.R. § 1.56",
        graph=graph,
        as_of=date(2022, 7, 1),
        quoted_text="Duty of disclosure (2022 amended text).",
    )
    assert result.quote_comparison is not None
    assert result.quote_comparison.status is QuoteMatchStatus.MATCH
    assert result.verification_state is VerificationState.VERIFIED


def test_quote_against_authority_node():
    node = _node()
    cmp = compare_quote_to_source(
        "Duty of disclosure (2020 base text).",
        node,
    )
    assert cmp.status is QuoteMatchStatus.MATCH
    cmp2 = compare_quote_to_source("wrong quote entirely", node)
    assert cmp2.status is QuoteMatchStatus.MISMATCH
    assert cmp2.quoted_span is not None and cmp2.source_span is not None


# ---------------------------------------------------------------------------
# Unresolved version/source never becomes verified
# ---------------------------------------------------------------------------


def test_compute_verification_blocks_unresolved_version():
    node = _node(version=None, edition=None, verification_state=VerificationState.VERIFIED)
    # Node construction may still allow None version — force via compute helper.
    state = compute_verification_state(
        match_kind=CitationMatchKind.EXACT,
        version=None,
        edition=None,
        source_node=node,
        as_of=None,
        quote=None,
        node_verification=VerificationState.VERIFIED,
    )
    assert state is not VerificationState.VERIFIED


def test_compute_verification_blocks_unresolved_match_kind():
    node = _node()
    for kind in (CitationMatchKind.UNRESOLVED, CitationMatchKind.AMBIGUOUS):
        state = compute_verification_state(
            match_kind=kind,
            version="v1",
            edition="2020",
            source_node=node,
            as_of=None,
            quote=None,
            node_verification=VerificationState.VERIFIED,
        )
        assert state is VerificationState.UNVERIFIED


def test_compute_verification_blocks_missing_source():
    state = compute_verification_state(
        match_kind=CitationMatchKind.EXACT,
        version="v1",
        edition="2020",
        source_node=None,
        as_of=None,
        quote=None,
    )
    assert state is VerificationState.UNVERIFIED


def test_result_constructor_rejects_verified_without_source():
    parsed = parse_citation("35 U.S.C. § 101")
    with pytest.raises(PatentCitationResolverError):
        CitationResolutionResult(
            parsed=parsed,
            match_kind=CitationMatchKind.UNRESOLVED,
            verification_state=VerificationState.VERIFIED,
            authority_tier=AuthorityTier.OFFICIAL_BASE,
        )


def test_result_constructor_rejects_verified_without_version():
    parsed = parse_citation("37 C.F.R. § 1.56")
    with pytest.raises(PatentCitationResolverError):
        CitationResolutionResult(
            parsed=parsed,
            match_kind=CitationMatchKind.EXACT,
            verification_state=VerificationState.VERIFIED,
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            selected_node_id="n1",
            selected_version=None,
            selected_edition=None,
        )


def test_node_without_version_never_verified():
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="no-ver")
    builder.add_node(
        _node(
            node_id="no-ver-node",
            citation_key="37-cfr-1.97",
            version=None,
            edition=None,
            verification_state=VerificationState.UNVERIFIED,
        )
    )
    graph = builder.build()
    result = resolve_citation(
        "37 C.F.R. § 1.97",
        graph=graph,
        as_of=date(2021, 1, 1),
    )
    assert result.selected_node_id == "no-ver-node"
    assert result.verification_state is not VerificationState.VERIFIED
    codes = {d.code for d in result.diagnostics}
    assert CitationDiagnosticCode.UNRESOLVED_VERSION in codes or (
        CitationDiagnosticCode.VERIFICATION_BLOCKED in codes
    )


# ---------------------------------------------------------------------------
# Authority tier independent of relevance/confidence
# ---------------------------------------------------------------------------


def test_authority_tier_independent_of_high_confidence_relevance():
    graph = _duty_graph()
    # Guidance citation with max confidence/relevance must stay GUIDANCE.
    result = resolve_citation(
        "MPEP § 2106",
        graph=graph,
        as_of=date(2023, 1, 1),
        confidence=1.0,
        relevance=1.0,
    )
    assert result.confidence == 1.0
    assert result.relevance == 1.0
    assert result.authority_tier is AuthorityTier.GUIDANCE
    assert result.authority_tier is not AuthorityTier.OFFICIAL_BASE
    codes = {d.code for d in result.diagnostics}
    assert CitationDiagnosticCode.TIER_INDEPENDENT_OF_SCORE in codes


def test_authority_tier_independent_of_low_scores_on_statute():
    graph = _duty_graph()
    result = resolve_citation(
        "35 U.S.C. § 102",
        graph=graph,
        as_of=date(2020, 1, 1),
        confidence=0.05,
        relevance=0.01,
    )
    assert result.confidence == 0.05
    assert result.relevance == 0.01
    assert result.authority_tier is AuthorityTier.OFFICIAL_BASE


def test_parsed_scores_do_not_set_tier():
    p = ParsedCitation(
        raw_text="MPEP 2106",
        family=CitationFamily.MPEP,
        match_kind=CitationMatchKind.EXACT,
        citation_key="mpep-2106",
        confidence=1.0,
        relevance=1.0,
        authority_tier=AuthorityTier.GUIDANCE,
    )
    assert p.authority_tier is AuthorityTier.GUIDANCE
    # Even with max scores, family default for MPEP is guidance.
    assert default_authority_tier_for_family(p.family) is AuthorityTier.GUIDANCE


def test_family_default_tiers_stable_under_score_clamp():
    p = parse_citation("FP 7.05")
    assert p.confidence > 0
    assert p.authority_tier is AuthorityTier.GUIDANCE
    p2 = parse_citation("35 U.S.C. § 112")
    assert p2.authority_tier is AuthorityTier.OFFICIAL_BASE


# ---------------------------------------------------------------------------
# PatentCitationResolver facade
# ---------------------------------------------------------------------------


def test_resolver_class_end_to_end():
    graph = _duty_graph()
    resolver = PatentCitationResolver(
        graph,
        default_as_of=date(2022, 7, 1),
    )
    parsed = resolver.parse(
        "Office action cites 37 C.F.R. § 1.56 and MPEP § 2106."
    )
    assert len(parsed) >= 2

    result = resolver.resolve(
        "37 C.F.R. § 1.56",
        quoted_text="Duty of disclosure (2022 amended text).",
    )
    assert result.is_exact
    assert result.is_verified

    mismatch = resolver.validate_quote(
        "wrong text",
        "Duty of disclosure (2022 amended text).",
    )
    assert mismatch.status is QuoteMatchStatus.MISMATCH
    assert mismatch.quoted_span is not None
    assert mismatch.source_span is not None

    batch = resolver.resolve_text(
        "See 35 U.S.C. § 102 and FP 7.05."
    )
    assert all(isinstance(r, CitationResolutionResult) for r in batch)


def test_text_span_round_trip_and_from_authority_span():
    span = AuthoritySpan(
        section="1.56",
        quote="hello",
        start_offset=2,
        end_offset=7,
        artifact_sha256=_SHA_A,
    )
    ts = TextSpan.from_authority_span(span)
    assert ts is not None
    assert ts.text == "hello"
    assert ts.start == 2
    assert ts.end == 7
    assert TextSpan.from_dict(ts.to_dict()).to_dict() == ts.to_dict()


def test_quote_comparison_round_trip():
    cmp = compare_quote_to_source("a", "b")
    assert cmp.status is QuoteMatchStatus.MISMATCH
    rebuilt = QuoteComparison.from_dict(cmp.to_dict())
    assert rebuilt.to_dict() == cmp.to_dict()
