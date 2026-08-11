"""Unit tests for semantic instruction consistency processor (PATLAW-134).

Acceptance focus:
  - Exact-citation-but-wrong-proposition fixtures fail or require review
  - Superseded / conflicting / missing authority cannot pass
  - Consistent results require proposition-level support plus proof or a
    documented deterministic rule
  - Findings expose sources, assumptions, confidence, and human-review boundary
  - Citation resolution alone is never enough for consistency
  - Guidance is not substituted for controlling law
  - No final legal determination; no unlawful-conduct declaration
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_contracts import (
    AuthorityRank,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.semantic_instruction_consistency_processor import (
    DOCUMENTED_DETERMINISTIC_RULES,
    NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER,
    OUTPUT_KIND_SEMANTIC_INSTRUCTION_ASSURANCE,
    SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
    AuthoritySupportRecord,
    FindingKind,
    InstructionCheckUnit,
    PropositionAtom,
    SemanticConsistencyInput,
    SemanticConsistencyResult,
    SemanticDisposition,
    SemanticInstructionConsistencyProcessor,
    SemanticReasonCode,
    SemanticVerdict,
    SupportKind,
    atom_key,
    build_binding_authority_support,
    build_conflicting_authority_fixture,
    build_human_review_question,
    build_missing_authority_fixture,
    build_superseded_authority_fixture,
    build_verified_consistent_fixture,
    build_wrong_proposition_fixture,
    contains_forbidden_unlawful_token,
    documented_rule,
    extract_quoted_fragments,
    is_pass_verdict,
    list_documented_rules,
    quotes_match,
    sanitize_labels,
    sha256_hex,
    verify_semantic_instruction_consistency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _processor() -> SemanticInstructionConsistencyProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"sic:test:{counter['n']:04d}"

    return SemanticInstructionConsistencyProcessor(id_factory=_ids)


def _assert_round_trip(result: SemanticConsistencyResult) -> None:
    first = result.to_dict()
    restored = SemanticConsistencyResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert "findings" not in public
    assert public["declares_unlawful_conduct"] is False
    assert public["is_model_summary_substitution"] is False
    assert public["is_final_legal_determination"] is False
    assert public["output_kind"] == OUTPUT_KIND_SEMANTIC_INSTRUCTION_ASSURANCE
    blob = json.dumps(public)
    # Public projection must not leak instruction body text.
    assert "Claims 1-3" not in blob
    assert "particularly pointing" not in blob


def _assert_finding_exposes_boundary(result: SemanticConsistencyResult) -> None:
    assert result.human_review is not None
    assert result.human_review.is_final_legal_determination is False
    assert result.is_final_legal_determination is False
    assert result.declares_unlawful_conduct is False
    assert result.is_model_summary_substitution is False
    assert NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER[:40] in result.disclaimer
    for finding in result.findings:
        assert finding.sources  # sources exposed
        assert finding.human_review is not None
        assert finding.human_review.is_final_legal_determination is False
        assert finding.confidence is not None
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.declares_unlawful_conduct is False
        assert finding.is_model_summary_substitution is False
        # Assumptions / reason codes present on findings.
        assert finding.reason_codes
        assert SemanticReasonCode.SOURCES_EXPOSED.value in finding.reason_codes
        assert (
            SemanticReasonCode.HUMAN_REVIEW_BOUNDARY_EXPOSED.value
            in finding.reason_codes
        )
        assert (
            SemanticReasonCode.NOT_FINAL_LEGAL_DETERMINATION.value
            in finding.reason_codes
            or SemanticReasonCode.NOT_FINAL_LEGAL_DETERMINATION.value
            in result.reason_codes
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_extract_quoted_fragments() -> None:
    surface = 'The statute states "particularly pointing out" the claim.'
    frags = extract_quoted_fragments(surface)
    assert frags
    assert "particularly pointing out" in frags[0]


def test_quotes_match_normalized() -> None:
    assert quotes_match("  foo   bar ", "foo bar")
    assert quotes_match("abc", "xx abc yy")
    assert not quotes_match("nope", "something else entirely")


def test_atom_key_polarity() -> None:
    assert atom_key("Must Reply", polarity=True) == "+must reply"
    assert atom_key("Must Reply", polarity=False) == "-must reply"


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
    assert SemanticReasonCode.FORBIDDEN_LABEL_STRIPPED.value in reasons


def test_contains_forbidden_unlawful_token() -> None:
    assert contains_forbidden_unlawful_token("examiner_unlawful") is True
    assert contains_forbidden_unlawful_token("potential_inconsistency") is False


def test_documented_rules_have_digests() -> None:
    keys = list_documented_rules()
    assert "sic.proposition_atom_support@1" in keys
    assert "sic.quote_exact_match_binding@1" in keys
    for key in keys:
        rule = documented_rule(key)
        assert rule is not None
        assert rule["deterministic"] is True
        assert len(rule["rule_digest"]) == 64
        assert rule["on_no_match"] == "no_op"


def test_is_pass_verdict() -> None:
    assert is_pass_verdict(SemanticVerdict.VERIFIED_CONSISTENT) is True
    assert is_pass_verdict(SemanticVerdict.WRONG_PROPOSITION) is False
    assert is_pass_verdict("missing_authority") is False


def test_build_human_review_question_wrong_proposition() -> None:
    q = build_human_review_question(
        unit_id="unit:1",
        verdict=SemanticVerdict.WRONG_PROPOSITION,
        citation_surfaces=("35 U.S.C. § 112(b)",),
        authority_versions=("aia-2011",),
    )
    assert "unit:1" in q
    assert "not" in q.lower()
    assert "unlawful" in q.lower()


def test_sha256_hex_stable() -> None:
    assert sha256_hex("abc") == sha256_hex(b"abc")
    assert len(sha256_hex("x")) == 64


# ---------------------------------------------------------------------------
# Exact citation but wrong proposition
# ---------------------------------------------------------------------------


def test_exact_citation_wrong_proposition_fails() -> None:
    proc = _processor()
    result = proc.verify(build_wrong_proposition_fixture())
    _assert_round_trip(result)
    _assert_finding_exposes_boundary(result)
    assert result.is_pass is False
    assert result.disposition is SemanticDisposition.FAILED
    assert result.findings
    finding = result.findings[0]
    assert finding.verdict is SemanticVerdict.WRONG_PROPOSITION
    assert finding.is_pass is False
    assert finding.human_review.requires_human_review is True
    assert (
        SemanticReasonCode.CITATION_EXACT_BUT_WRONG_PROPOSITION.value
        in finding.reason_codes
        or SemanticReasonCode.VERDICT_WRONG_PROPOSITION.value in finding.reason_codes
    )
    assert (
        SemanticReasonCode.CITATION_ALONE_NOT_CONSISTENT.value in finding.reason_codes
        or SemanticReasonCode.PROPOSITION_ATOMS_MISMATCH.value in finding.reason_codes
    )
    # Counterexamples / sources retained for review.
    assert finding.sources
    assert finding.unsupported_atoms
    assert finding.authority_supports
    assert finding.authority_supports[0].version == "aia-2011"


# ---------------------------------------------------------------------------
# Superseded / conflicting / missing cannot pass
# ---------------------------------------------------------------------------


def test_superseded_authority_cannot_pass() -> None:
    result = _processor().verify(build_superseded_authority_fixture())
    _assert_finding_exposes_boundary(result)
    assert result.is_pass is False
    finding = result.findings[0]
    assert finding.verdict is SemanticVerdict.SUPERSEDED_AUTHORITY
    assert finding.is_pass is False
    assert SemanticReasonCode.AUTHORITY_SUPERSEDED.value in finding.reason_codes


def test_conflicting_authority_cannot_pass() -> None:
    result = _processor().verify(build_conflicting_authority_fixture())
    _assert_finding_exposes_boundary(result)
    assert result.is_pass is False
    finding = result.findings[0]
    assert finding.verdict is SemanticVerdict.CONFLICTING_AUTHORITY
    assert finding.is_pass is False
    assert SemanticReasonCode.AUTHORITY_CONFLICTING.value in finding.reason_codes
    # Competing sources both exposed.
    assert len(finding.authority_supports) == 2


def test_missing_authority_cannot_pass() -> None:
    result = _processor().verify(build_missing_authority_fixture())
    _assert_finding_exposes_boundary(result)
    assert result.is_pass is False
    finding = result.findings[0]
    assert finding.verdict is SemanticVerdict.MISSING_AUTHORITY
    assert finding.is_pass is False
    assert SemanticReasonCode.AUTHORITY_MISSING.value in finding.reason_codes


# ---------------------------------------------------------------------------
# Verified consistent requires prop support + proof or deterministic rule
# ---------------------------------------------------------------------------


def test_verified_consistent_with_proof() -> None:
    result = _processor().verify(
        build_verified_consistent_fixture(use_proof=True)
    )
    _assert_round_trip(result)
    _assert_finding_exposes_boundary(result)
    assert result.is_pass is True
    assert result.disposition is SemanticDisposition.ASSURED
    finding = result.findings[0]
    assert finding.verdict is SemanticVerdict.VERIFIED_CONSISTENT
    assert finding.is_pass is True
    assert finding.support_kind is SupportKind.PROOF_RECEIPT
    assert finding.proof_receipt is not None
    assert finding.proof_receipt.is_proved is True
    assert finding.supported_atoms
    assert not finding.unsupported_atoms
    assert finding.sources
    assert finding.confidence is not None
    # Still not a final legal determination.
    assert finding.human_review.is_final_legal_determination is False
    assert result.is_final_legal_determination is False


def test_verified_consistent_with_deterministic_rule() -> None:
    # Skip proof; quote + atom match should apply documented rules.
    result = _processor().verify(
        build_verified_consistent_fixture(use_proof=False)
    )
    _assert_round_trip(result)
    _assert_finding_exposes_boundary(result)
    assert result.is_pass is True
    finding = result.findings[0]
    assert finding.verdict is SemanticVerdict.VERIFIED_CONSISTENT
    assert finding.support_kind is SupportKind.DETERMINISTIC_RULE
    assert any(r.applied for r in finding.deterministic_rule_receipts)
    applied = [r for r in finding.deterministic_rule_receipts if r.applied]
    assert applied
    # Receipt cites documented rule identity + digest.
    for r in applied:
        assert r.rule_key in DOCUMENTED_DETERMINISTIC_RULES
        assert len(r.rule_digest) == 64
        assert r.rule_id
        assert r.rule_version


def test_citation_alone_without_proposition_cannot_pass() -> None:
    support = build_binding_authority_support(
        support_id="auth:cite-only",
        citation_surface="35 U.S.C. § 112(b)",
        citation_key="35-usc-112(b)",
        text_excerpt="Claims must particularly point out.",
        version="aia-2011",
        proposition_predicates=("claims_must_particularly_point_out",),
        effective_start="2011-09-16",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:cite-only",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:cite-only",
        instruction_surface_text="Rejected under 35 U.S.C. § 112(b).",
        instruction_text_digest=None,
        legal_citations=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        claimed_atoms=(),  # no proposition claims
        quoted_authority_text=None,
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.9,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={},
    )
    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:cite-only",
            units=(unit,),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2024-06-01",
            analysis_id="analysis:cite-only",
            run_proofs=True,
        )
    )
    assert result.is_pass is False
    finding = result.findings[0]
    assert finding.verdict is not SemanticVerdict.VERIFIED_CONSISTENT
    assert finding.is_pass is False
    assert (
        SemanticReasonCode.CITATION_ALONE_NOT_CONSISTENT.value in finding.reason_codes
        or SemanticReasonCode.PROPOSITION_SUPPORT_MISSING.value in finding.reason_codes
        or SemanticReasonCode.SUPPORT_INSUFFICIENT_FOR_CONSISTENT.value
        in finding.reason_codes
    )


def test_guidance_only_is_unsupported_not_consistent() -> None:
    support = build_binding_authority_support(
        support_id="auth:mpep",
        citation_surface="MPEP § 2106",
        citation_key="mpep-2106",
        text_excerpt="Patent subject matter eligibility guidance.",
        version="mpep-2024-08",
        proposition_predicates=("subject_matter_eligibility",),
        authority_rank=AuthorityRank.GUIDANCE.value,
        is_binding=False,
        effective_start="2024-01-01",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:mpep",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:mpep",
        instruction_surface_text="See MPEP § 2106 for eligibility.",
        instruction_text_digest=None,
        legal_citations=("MPEP § 2106",),
        citation_keys=("mpep-2106",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="claim:elig",
                predicate="subject_matter_eligibility",
                polarity=True,
            ),
        ),
        quoted_authority_text="Patent subject matter eligibility guidance.",
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.8,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={},
    )
    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:mpep",
            units=(unit,),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2024-06-01",
            analysis_id="analysis:mpep",
            run_proofs=True,
        )
    )
    assert result.is_pass is False
    finding = result.findings[0]
    assert finding.verdict is not SemanticVerdict.VERIFIED_CONSISTENT
    assert finding.is_pass is False
    assert (
        SemanticReasonCode.AUTHORITY_GUIDANCE_NOT_CONTROLLING.value
        in finding.reason_codes
        or finding.verdict is SemanticVerdict.UNSUPPORTED_INSTRUCTION
    )


# ---------------------------------------------------------------------------
# Deadline basis / required act / clerical / multi-unit
# ---------------------------------------------------------------------------


def test_deadline_basis_with_rule_support() -> None:
    support = build_binding_authority_support(
        support_id="auth:cfr-reply",
        citation_surface="37 C.F.R. § 1.134",
        citation_key="37-cfr-1.134",
        text_excerpt="Time period for reply to Office action.",
        version="2020-base",
        proposition_predicates=("reply_period_set_by_office",),
        effective_start="2020-01-01",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:deadline",
        finding_kind=FindingKind.DEADLINE_BASIS,
        instruction_span_id="span:deadline",
        instruction_surface_text=(
            "A shortened statutory period for reply is set to expire in 3 months "
            "from the mailing date under 37 C.F.R. § 1.134."
        ),
        instruction_text_digest=None,
        legal_citations=("37 C.F.R. § 1.134",),
        citation_keys=("37-cfr-1.134",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="claim:reply",
                predicate="reply_period_set_by_office",
                polarity=True,
            ),
        ),
        quoted_authority_text="Time period for reply to Office action.",
        deadline_basis="reply_period_set_by_office",
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=("mailing_date_known",),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.88,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={},
        force_skip_proof=True,
    )
    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:deadline",
            units=(unit,),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2024-06-01",
            analysis_id="analysis:deadline",
            run_proofs=False,
        )
    )
    finding = result.findings[0]
    assert finding.finding_kind is FindingKind.DEADLINE_BASIS
    assert finding.is_pass is True
    assert finding.verdict is SemanticVerdict.VERIFIED_CONSISTENT
    assert any(
        r.rule_key == "sic.deadline_basis_binding@1" and r.applied
        for r in finding.deterministic_rule_receipts
    )
    assert "mailing_date_known" in finding.assumptions or any(
        "mailing_date" in a for a in finding.assumptions
    )


def test_clerical_mismatch_requires_review() -> None:
    support = build_binding_authority_support(
        support_id="auth:clerical",
        citation_surface="35 U.S.C. § 112(b)",
        citation_key="35-usc-112(b)",
        text_excerpt="Definiteness requirement.",
        version="aia-2011",
        proposition_predicates=("claims_must_particularly_point_out",),
        effective_start="2011-09-16",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:clerical",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:clerical",
        instruction_surface_text="Rejected under 35 USC 112b (typo form).",
        instruction_text_digest=None,
        legal_citations=("35 USC 112b",),
        citation_keys=("35-usc-112(b)",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="claim:other",
                predicate="unrelated_predicate",
                polarity=True,
            ),
        ),
        quoted_authority_text=None,
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.5,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={},
        force_clerical_mismatch=True,
    )
    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:clerical",
            units=(unit,),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2024-06-01",
            analysis_id="analysis:clerical",
        )
    )
    assert result.is_pass is False
    finding = result.findings[0]
    # Wrong prop takes priority over clerical when exact cite + unsupported atoms.
    assert finding.verdict in (
        SemanticVerdict.CLERICAL_MISMATCH,
        SemanticVerdict.WRONG_PROPOSITION,
    )
    assert finding.is_pass is False
    assert finding.human_review.requires_human_review is True


def test_multi_unit_partial_disposition() -> None:
    ok = build_verified_consistent_fixture(use_proof=True).units[0]
    bad = build_wrong_proposition_fixture().units[0]
    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:partial",
            units=(ok, bad),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2024-06-01",
            analysis_id="analysis:partial",
            run_proofs=True,
        )
    )
    assert result.is_pass is False
    assert result.disposition is SemanticDisposition.PARTIAL
    assert result.pass_count == 1
    assert result.fail_count >= 1
    assert result.human_review.requires_human_review is True


def test_empty_input() -> None:
    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:empty",
            units=(),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2024-06-01",
            analysis_id="analysis:empty",
        )
    )
    assert result.disposition is SemanticDisposition.EMPTY
    assert result.is_pass is False
    assert SemanticReasonCode.EMPTY_INPUT.value in result.reason_codes


def test_module_level_entry_point() -> None:
    result = verify_semantic_instruction_consistency(
        build_missing_authority_fixture()
    )
    assert result.findings[0].verdict is SemanticVerdict.MISSING_AUTHORITY


def test_never_declares_unlawful_or_final_legal() -> None:
    for builder in (
        build_wrong_proposition_fixture,
        build_verified_consistent_fixture,
        build_superseded_authority_fixture,
        build_conflicting_authority_fixture,
        build_missing_authority_fixture,
    ):
        result = _processor().verify(builder())
        assert result.declares_unlawful_conduct is False
        assert result.is_final_legal_determination is False
        assert result.is_model_summary_substitution is False
        for f in result.findings:
            assert f.declares_unlawful_conduct is False
            assert f.is_model_summary_substitution is False
            assert f.verdict.value not in (
                "unlawful",
                "illegal",
                "examiner_unlawful",
            )
            assert "unlawful conduct" not in f.human_review.review_question.lower() or (
                "not" in f.human_review.review_question.lower()
            )


def test_authority_support_controlling_property() -> None:
    binding = build_binding_authority_support(
        support_id="a1",
        citation_surface="35 U.S.C. § 102",
        citation_key="35-usc-102",
        text_excerpt="Novelty.",
        version="aia-2011",
        proposition_predicates=("novelty",),
    )
    assert binding.is_controlling is True
    assert binding.has_exact_version is True

    guidance = build_binding_authority_support(
        support_id="g1",
        citation_surface="MPEP § 2106",
        citation_key="mpep-2106",
        text_excerpt="Guidance.",
        version="2024",
        proposition_predicates=("elig",),
        authority_rank=AuthorityRank.GUIDANCE.value,
        is_binding=False,
    )
    assert guidance.is_controlling is False


def test_documented_rules_listed_on_result() -> None:
    result = _processor().verify(build_verified_consistent_fixture())
    for key in list_documented_rules():
        assert key in result.documented_rules
    assert (
        result.ruleset_versions.get("semantic_instruction_consistency")
        is not None
    )
    assert result.schema_version == SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION
