"""Unit tests for semantic compliance processor (PATLAW-130).

Acceptance focus:
  - Unrelated remarks cannot satisfy a rejection response
  - Partial / conditional / contradictory evidence → incomplete / unknown / fail
  - Every result has obligation, evidence, authority, and proof provenance
  - Model similarity can rank candidates but cannot establish satisfaction
  - Category presence alone is never compliance
  - No final legal determination; no model-summary substitution
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.semantic_compliance_processor import (
    DOCUMENTED_DETERMINISTIC_RULES,
    NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER,
    OUTPUT_KIND_SEMANTIC_COMPLIANCE,
    PARSER_VERSION,
    SEMANTIC_COMPLIANCE_SCHEMA_VERSION,
    AtomicObligation,
    AuthorityProvenance,
    BindingRole,
    ComplianceDisposition,
    EvidenceAdmission,
    EvidenceItem,
    EvidenceOrigin,
    ObligationKind,
    ResponsiveEvidenceKind,
    SatisfactionStatus,
    SemanticComplianceInput,
    SemanticComplianceProcessor,
    SemanticComplianceReasonCode,
    SemanticComplianceResult,
    analyze_semantic_compliance,
    bind_evidence_to_obligation,
    build_contradiction_fixture,
    build_fee_evidence,
    build_fee_obligation,
    build_fee_satisfaction_fixture,
    build_model_candidate_evidence,
    build_model_similarity_only_fixture,
    build_partial_conditions_fixture,
    build_rejection_obligation,
    build_responsive_argument_evidence,
    build_responsive_satisfaction_fixture,
    build_unrelated_remarks_evidence,
    build_unrelated_remarks_fixture,
    claim_overlap,
    citation_overlap,
    contains_forbidden_unlawful_token,
    documented_rule,
    evaluate_conditions,
    is_satisfaction_pass,
    jaccard_similarity,
    kind_is_compatible,
    list_documented_rules,
    rank_similarity,
    requires_claim_or_citation_overlap,
    responsive_kinds_for,
    sanitize_labels,
    sha256_hex,
    tokenize_surface,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _processor() -> SemanticComplianceProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"sc:test:{counter['n']:04d}"

    return SemanticComplianceProcessor(id_factory=_ids)


def _assert_round_trip(result: SemanticComplianceResult) -> None:
    first = result.to_dict()
    restored = SemanticComplianceResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert "results" not in public
    assert public["is_final_legal_determination"] is False
    assert public["is_model_summary_substitution"] is False
    assert public["output_kind"] == OUTPUT_KIND_SEMANTIC_COMPLIANCE
    blob = json.dumps(public)
    # Public projection must not leak obligation/evidence body text.
    assert "rejected under" not in blob
    assert "Applicant traverses" not in blob


def _assert_four_provenance_legs(result: SemanticComplianceResult) -> None:
    assert result.results
    for ocr in result.results:
        assert ocr.has_obligation_provenance is True
        assert ocr.obligation.obligation_id
        assert ocr.obligation.source_span_ids
        # Evidence leg: bindings always emitted (may be empty support).
        assert ocr.bindings is not None
        assert ocr.has_evidence_provenance or ocr.bindings == ()
        # When evidence items were present, bindings non-empty.
        assert ocr.has_authority_provenance is True
        assert ocr.authority_provenance
        assert ocr.has_proof_provenance is True
        assert ocr.proof_provenance is not None or ocr.rule_receipts
        assert ocr.provenance_complete is True
        assert ocr.human_review is not None
        assert ocr.human_review.is_final_legal_determination is False


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_tokenize_surface_and_jaccard() -> None:
    a = tokenize_surface("Claims 1-3 rejected under 112")
    b = tokenize_surface("Applicant amends claims 1 and 2 under 112")
    assert "claims" in a
    sim = jaccard_similarity(a, b)
    assert 0.0 < sim < 1.0


def test_sha256_hex_stable() -> None:
    assert sha256_hex("abc") == sha256_hex(b"abc")
    assert len(sha256_hex("x")) == 64


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
    assert SemanticComplianceReasonCode.FORBIDDEN_LABEL_STRIPPED.value in reasons


def test_contains_forbidden_unlawful_token() -> None:
    assert contains_forbidden_unlawful_token("examiner_unlawful") is True
    assert contains_forbidden_unlawful_token("potential_gap") is False


def test_documented_rules_have_digests() -> None:
    keys = list_documented_rules()
    assert "sc.rejection_requires_responsive_argument@1" in keys
    assert "sc.exact_claim_citation_binding@1" in keys
    assert "sc.fee_form_presence_binding@1" in keys
    for key in keys:
        rule = documented_rule(key)
        assert rule is not None
        assert rule["deterministic"] is True
        assert len(rule["rule_digest"]) == 64
        assert rule["on_no_match"] == "no_op"
    assert DOCUMENTED_DETERMINISTIC_RULES


def test_is_satisfaction_pass() -> None:
    assert is_satisfaction_pass(SatisfactionStatus.SATISFIED) is True
    assert is_satisfaction_pass(SatisfactionStatus.UNSATISFIED) is False
    assert is_satisfaction_pass("incomplete") is False


def test_responsive_kinds_and_overlap_requirement() -> None:
    kinds = responsive_kinds_for(ObligationKind.REJECTION_RESPONSE)
    assert ResponsiveEvidenceKind.ARGUMENT.value in kinds
    assert ResponsiveEvidenceKind.AMENDMENT.value in kinds
    assert requires_claim_or_citation_overlap(ObligationKind.REJECTION_RESPONSE)
    assert not requires_claim_or_citation_overlap(ObligationKind.FEE)


def test_claim_and_citation_overlap() -> None:
    obl = build_rejection_obligation(claims=("1", "2"))
    ok = build_responsive_argument_evidence(claims=("2", "9"))
    bad = build_unrelated_remarks_evidence()
    assert claim_overlap(obl, ok) == ("2",)
    assert citation_overlap(obl, ok) == ("35-usc-112(b)",)
    assert claim_overlap(obl, bad) == ()
    assert citation_overlap(obl, bad) == ()
    assert kind_is_compatible(obl, ok) is True
    assert kind_is_compatible(obl, bad) is True  # kind ok; overlap fails later


def test_evaluate_conditions_partial() -> None:
    met, unmet = evaluate_conditions(
        ("timely_response", "fee_paid"),
        {"timely_response": True},
    )
    assert met == ("timely_response",)
    assert unmet == ("fee_paid",)


def test_rank_similarity_uses_model_score_for_ranking_only() -> None:
    obl = build_rejection_obligation()
    model = build_model_candidate_evidence(similarity=0.99)
    score = rank_similarity(obl, model)
    assert score is not None
    assert score > 0.5


def test_bind_unrelated_remarks_role() -> None:
    obl = build_rejection_obligation()
    items = (build_unrelated_remarks_evidence(),)
    counter = {"n": 0}

    def ids() -> str:
        counter["n"] += 1
        return f"{counter['n']}"

    bindings = bind_evidence_to_obligation(
        obligation=obl, evidence_items=items, id_factory=ids
    )
    assert len(bindings) == 1
    b = bindings[0]
    assert b.role is BindingRole.UNRELATED
    assert b.establishes_satisfaction is False
    assert (
        SemanticComplianceReasonCode.UNRELATED_REMARKS_REJECTED.value
        in b.reason_codes
    )


def test_bind_model_candidate_ranked_not_support() -> None:
    obl = build_rejection_obligation()
    items = (build_model_candidate_evidence(similarity=0.99),)
    counter = {"n": 0}

    def ids() -> str:
        counter["n"] += 1
        return f"{counter['n']}"

    bindings = bind_evidence_to_obligation(
        obligation=obl, evidence_items=items, id_factory=ids
    )
    assert bindings[0].role is BindingRole.CANDIDATE_RANKED
    assert bindings[0].establishes_satisfaction is False
    assert (
        SemanticComplianceReasonCode.MODEL_SIMILARITY_NOT_SATISFACTION.value
        in bindings[0].reason_codes
    )


# ---------------------------------------------------------------------------
# Acceptance: unrelated remarks cannot satisfy rejection response
# ---------------------------------------------------------------------------


def test_unrelated_remarks_cannot_satisfy_rejection() -> None:
    result = _processor().analyze(build_unrelated_remarks_fixture())
    _assert_round_trip(result)
    _assert_four_provenance_legs(result)
    assert result.is_pass is False
    assert result.overall_pass is False
    assert result.disposition in (
        ComplianceDisposition.FAILED,
        ComplianceDisposition.REVIEW,
    )
    ocr = result.results[0]
    assert ocr.status is SatisfactionStatus.UNSATISFIED
    assert ocr.is_pass is False
    assert not ocr.support_evidence_ids
    assert (
        SemanticComplianceReasonCode.UNRELATED_REMARKS_REJECTED.value
        in ocr.reason_codes
    )
    # Category presence of argument/remarks alone is not satisfaction.
    assert any(
        b.role is BindingRole.UNRELATED for b in ocr.bindings
    )
    assert ocr.human_review.requires_human_review is True


# ---------------------------------------------------------------------------
# Responsive evidence can satisfy with proof + rule
# ---------------------------------------------------------------------------


def test_responsive_argument_satisfies_with_provenance() -> None:
    result = _processor().analyze(build_responsive_satisfaction_fixture())
    _assert_round_trip(result)
    _assert_four_provenance_legs(result)
    assert result.is_pass is True
    assert result.overall_pass is True
    assert result.disposition is ComplianceDisposition.BOUND
    ocr = result.results[0]
    assert ocr.status is SatisfactionStatus.SATISFIED
    assert ocr.is_pass is True
    assert ocr.support_evidence_ids
    assert ocr.proof_provenance is not None
    assert ocr.proof_provenance.is_proved is True
    assert ocr.rule_receipts
    assert any(r.applied for r in ocr.rule_receipts)
    assert SemanticComplianceReasonCode.SATISFIED.value in ocr.reason_codes
    assert SemanticComplianceReasonCode.PROVENANCE_COMPLETE.value in ocr.reason_codes
    # Still not a final legal determination.
    assert result.is_final_legal_determination is False
    assert ocr.human_review.is_final_legal_determination is False
    assert NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER[:40] in result.disclaimer


def test_fee_obligation_satisfied_with_fee_evidence() -> None:
    result = _processor().analyze(build_fee_satisfaction_fixture())
    _assert_four_provenance_legs(result)
    assert result.is_pass is True
    ocr = result.results[0]
    assert ocr.status is SatisfactionStatus.SATISFIED
    assert ocr.obligation.kind is ObligationKind.FEE
    assert ocr.support_evidence_ids


def test_fee_not_satisfied_by_unrelated_remarks() -> None:
    inp = SemanticComplianceInput(
        analysis_id="analysis:fee-unrelated",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(build_fee_obligation(),),
        evidence=(build_unrelated_remarks_evidence(),),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={},
    )
    result = _processor().analyze(inp)
    assert result.is_pass is False
    ocr = result.results[0]
    assert ocr.status is not SatisfactionStatus.SATISFIED
    assert not ocr.support_evidence_ids


# ---------------------------------------------------------------------------
# Partial / conditional / contradictory
# ---------------------------------------------------------------------------


def test_partial_conditions_yields_incomplete() -> None:
    result = _processor().analyze(build_partial_conditions_fixture())
    _assert_four_provenance_legs(result)
    assert result.is_pass is False
    ocr = result.results[0]
    assert ocr.status is SatisfactionStatus.INCOMPLETE
    assert "timely_response" in ocr.conditions_met
    assert "fee_paid" in ocr.conditions_unmet
    assert SemanticComplianceReasonCode.INCOMPLETE.value in ocr.reason_codes
    assert SemanticComplianceReasonCode.CONDITIONS_PARTIAL.value in ocr.reason_codes
    # Support exists but cannot pass while conditions unresolved.
    assert ocr.support_evidence_ids
    assert ocr.is_pass is False


def test_contradictory_evidence_yields_fail() -> None:
    result = _processor().analyze(build_contradiction_fixture())
    _assert_four_provenance_legs(result)
    assert result.is_pass is False
    ocr = result.results[0]
    assert ocr.status is SatisfactionStatus.FAIL
    assert ocr.support_evidence_ids
    assert ocr.counter_evidence_ids
    assert SemanticComplianceReasonCode.CONTRADICTION.value in ocr.reason_codes
    assert (
        SemanticComplianceReasonCode.UNRESOLVED_CONTRADICTION.value
        in ocr.reason_codes
    )
    assert SemanticComplianceReasonCode.FAIL.value in ocr.reason_codes


def test_absent_evidence_unsatisfied() -> None:
    inp = SemanticComplianceInput(
        analysis_id="analysis:empty-ev",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(build_rejection_obligation(),),
        evidence=(),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={},
    )
    result = _processor().analyze(inp)
    assert result.is_pass is False
    ocr = result.results[0]
    assert ocr.status is SatisfactionStatus.UNSATISFIED
    assert SemanticComplianceReasonCode.EVIDENCE_ABSENT.value in ocr.reason_codes
    # Authority + proof legs still present.
    assert ocr.authority_provenance
    assert ocr.proof_provenance is not None


# ---------------------------------------------------------------------------
# Model similarity ranks but cannot satisfy
# ---------------------------------------------------------------------------


def test_model_similarity_ranks_but_cannot_satisfy() -> None:
    result = _processor().analyze(build_model_similarity_only_fixture())
    _assert_four_provenance_legs(result)
    assert result.is_pass is False
    ocr = result.results[0]
    assert ocr.status is SatisfactionStatus.UNSATISFIED
    assert ocr.ranked_candidate_ids
    assert "ev:model-cand" in ocr.ranked_candidate_ids
    assert not ocr.support_evidence_ids
    assert (
        SemanticComplianceReasonCode.MODEL_SIMILARITY_NOT_SATISFACTION.value
        in ocr.reason_codes
    )
    # Ranked candidates ordered; model candidate present with similarity.
    ranked_bindings = [
        b for b in ocr.bindings if b.role is BindingRole.CANDIDATE_RANKED
    ]
    assert ranked_bindings
    assert ranked_bindings[0].similarity_score is not None
    assert ranked_bindings[0].similarity_score > 0.5
    assert ranked_bindings[0].establishes_satisfaction is False


def test_model_origin_cannot_be_admitted_without_receipt() -> None:
    item = EvidenceItem(
        evidence_id="ev:model-no-receipt",
        kind=ResponsiveEvidenceKind.ARGUMENT,
        document_id="doc:m",
        anchor_ids=("a:1",),
        surface_text="Model text about claims 1-3 and 35-usc-112(b).",
        text_digest=sha256_hex("Model text about claims 1-3 and 35-usc-112(b)."),
        claim_tokens=("1", "2", "3"),
        citation_keys=("35-usc-112(b)",),
        admission=EvidenceAdmission.ADMITTED,  # attempted
        origin=EvidenceOrigin.MODEL,
        confidence=0.99,
        content_sha256=sha256_hex("m"),
        is_counter=False,
        labels={},  # no admission_receipt_id
        model_similarity=0.99,
    )
    # Coerced to candidate.
    assert item.admission is EvidenceAdmission.CANDIDATE


# ---------------------------------------------------------------------------
# Provenance completeness and package aggregation
# ---------------------------------------------------------------------------


def test_every_result_has_four_provenance_legs() -> None:
    for fixture in (
        build_unrelated_remarks_fixture(),
        build_responsive_satisfaction_fixture(),
        build_partial_conditions_fixture(),
        build_contradiction_fixture(),
        build_model_similarity_only_fixture(),
        build_fee_satisfaction_fixture(),
    ):
        result = _processor().analyze(fixture)
        _assert_four_provenance_legs(result)
        for ocr in result.results:
            # Obligation leg
            d = ocr.to_dict()
            assert d["obligation"]["obligation_id"]
            assert d["obligation"]["source_span_ids"]
            # Evidence leg
            assert "bindings" in d
            assert "support_evidence_ids" in d
            # Authority leg
            assert d["authority_provenance"]
            assert d["authority_provenance"][0]["authority_id"]
            # Proof leg
            assert d["proof_provenance"] is not None
            assert d["proof_provenance"]["receipt_id"]
            assert d["provenance_complete"] is True


def test_empty_obligations_empty_disposition() -> None:
    inp = SemanticComplianceInput(
        analysis_id="analysis:empty",
        matter_id=None,
        office_action_artifact_id=None,
        package_id=None,
        obligations=(),
        evidence=(),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={},
    )
    result = _processor().analyze(inp)
    assert result.disposition is ComplianceDisposition.EMPTY
    assert result.is_pass is False
    assert result.results == ()
    assert SemanticComplianceReasonCode.EMPTY_INPUT.value in result.reason_codes


def test_quarantine_classification() -> None:
    inp = SemanticComplianceInput(
        analysis_id="analysis:q",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(build_rejection_obligation(),),
        evidence=(build_responsive_argument_evidence(),),
        condition_facts={},
        classification=DisclosureClassification.UNKNOWN,
        run_proofs=True,
        labels={},
    )
    result = _processor().analyze(inp)
    assert result.disposition is ComplianceDisposition.QUARANTINE
    assert result.is_pass is False
    assert SemanticComplianceReasonCode.QUARANTINED.value in result.reason_codes
    assert result.is_final_legal_determination is False


def test_module_level_analyze_entry_point() -> None:
    result = analyze_semantic_compliance(build_responsive_satisfaction_fixture())
    assert result.schema_version == SEMANTIC_COMPLIANCE_SCHEMA_VERSION
    assert result.results


def test_parser_version_in_ruleset() -> None:
    result = _processor().analyze(build_responsive_satisfaction_fixture())
    assert "parser" in result.ruleset_versions
    assert result.ruleset_versions["parser"] == PARSER_VERSION
    assert "semantic_compliance" in result.ruleset_versions


def test_atomic_obligation_round_trip() -> None:
    obl = build_rejection_obligation()
    restored = AtomicObligation.from_dict(obl.to_dict())
    assert restored.to_dict() == obl.to_dict()


def test_evidence_item_round_trip() -> None:
    ev = build_responsive_argument_evidence()
    restored = EvidenceItem.from_dict(ev.to_dict())
    assert restored.to_dict() == ev.to_dict()


def test_input_from_mapping() -> None:
    fix = build_responsive_satisfaction_fixture()
    result = _processor().analyze(fix.to_dict())
    assert result.is_pass is True


def test_missing_input_raises() -> None:
    with pytest.raises(Exception):
        _processor().analyze()


def test_category_presence_of_wrong_kind_not_satisfaction() -> None:
    """Fee evidence cannot satisfy a rejection response."""
    inp = SemanticComplianceInput(
        analysis_id="analysis:wrong-kind",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(build_rejection_obligation(),),
        evidence=(build_fee_evidence(),),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={},
    )
    result = _processor().analyze(inp)
    assert result.is_pass is False
    ocr = result.results[0]
    assert ocr.status is not SatisfactionStatus.SATISFIED
    assert not ocr.support_evidence_ids
    assert any(
        SemanticComplianceReasonCode.KIND_INCOMPATIBLE.value in b.reason_codes
        for b in ocr.bindings
    )


def test_partial_package_aggregation() -> None:
    """One satisfied + one unsatisfied → partial, overall fail closed."""
    inp = SemanticComplianceInput(
        analysis_id="analysis:partial-pkg",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(
            build_rejection_obligation(obligation_id="obl:a"),
            build_rejection_obligation(
                obligation_id="obl:b",
                claims=("9",),
                citation_key="35-usc-103",
            ),
        ),
        evidence=(
            build_responsive_argument_evidence(
                evidence_id="ev:a",
                claims=("1", "2", "3"),
                citation_key="35-usc-112(b)",
            ),
        ),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={},
    )
    result = _processor().analyze(inp)
    assert result.is_pass is False
    assert result.disposition is ComplianceDisposition.PARTIAL
    assert result.satisfied_count == 1
    assert result.unsatisfied_count >= 1
    assert SemanticComplianceReasonCode.OVERALL_FAIL_CLOSED.value in result.reason_codes


def test_authority_provenance_present_when_missing_resolution() -> None:
    obl = AtomicObligation(
        obligation_id="obl:no-auth",
        kind=ObligationKind.REQUIREMENT_ACT,
        source_span_ids=("span:1",),
        source_field_id=None,
        surface_text="Provide sequence listing.",
        text_digest=sha256_hex("Provide sequence listing."),
        claim_tokens=(),
        citation_keys=(),
        legal_citations=(),
        required_conditions=(),
        exceptions=(),
        required_act="file_sequence",
        authority_refs=(),
        admission=EvidenceAdmission.ADMITTED,
        confidence=0.5,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={},
    )
    inp = SemanticComplianceInput(
        analysis_id="analysis:no-auth",
        matter_id=None,
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(obl,),
        evidence=(),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=False,
        labels={},
    )
    result = _processor().analyze(inp)
    ocr = result.results[0]
    assert ocr.authority_provenance
    assert (
        SemanticComplianceReasonCode.AUTHORITY_MISSING.value in ocr.reason_codes
    )
    assert ocr.proof_provenance is not None
    assert (
        SemanticComplianceReasonCode.PROOF_SKIPPED.value
        in ocr.proof_provenance.reason_codes
        or ocr.proof_provenance.outcome == "unknown"
    )
