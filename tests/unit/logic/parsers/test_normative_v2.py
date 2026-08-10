"""Unit tests for NormativeLogicProfiles@2 (LFP2-037).

Evidence subset:

* dyadic / conditional norms
* defeasible norms with exceptions
* prioritized norms and conflicts
* contrary-to-duty / reparation structures
* semantic decision records per profile
* parser/printer fixtures and parse/print/parse round-trip
* negative ambiguity cases
* no unearned equivalence between norm systems
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.normative_v2 import (
    CODE_AMBIGUOUS_FORM,
    CODE_PROFILE_MISMATCH,
    CODE_UNEARNED_EQUIVALENCE,
    NORM_FAMILY_ID,
    NORM_NOTATION_ID,
    NORMATIVE_LOGIC_PROFILES_INTERFACE,
    NORMATIVE_PROFILE_INTERFACE,
    NORMATIVE_SEMANTIC_DECISION_INTERFACE,
    AuthorityPromotionError,
    EvidenceAuthority,
    EvidenceSource,
    NormStatus,
    NormativeEvaluation,
    NormativeEvidenceContract,
    NormativeLogicProfiles,
    NormativeLoweringReceipt,
    NormativeParser,
    NormativePrinter,
    NormativeProfile,
    NormativeSemantics,
    SemanticDecisionRecord,
    ctd_evidence_contract,
    defeasible_evidence_contract,
    dyadic_evidence_contract,
    evaluate_theory,
    extract_theory,
    normative_semantic_identity,
    parse_normative,
    parse_print_parse,
    print_normative,
    prioritized_evidence_contract,
    profile_contrary_to_duty,
    profile_defeasible,
    profile_dyadic,
    profile_prioritized,
    profiles_are_equivalent,
    reject_unearned_equivalence,
    retain_authority_ceiling,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
    SyntaxContractError,
)


def _dyadic():
    return profile_dyadic()


def _defeasible():
    return profile_defeasible()


def _prioritized():
    return profile_prioritized()


def _ctd():
    return profile_contrary_to_duty()


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert NORMATIVE_LOGIC_PROFILES_INTERFACE == "NormativeLogicProfiles@2"
    assert NORMATIVE_PROFILE_INTERFACE == "NormativeProfile@2"
    assert NORMATIVE_SEMANTIC_DECISION_INTERFACE == "NormativeSemanticDecision@2"
    assert NORM_FAMILY_ID == "deontic"
    assert NORM_NOTATION_ID == "canonical_normative_v2"
    logic = NormativeLogicProfiles(_dyadic())
    assert logic.interface == NORMATIVE_LOGIC_PROFILES_INTERFACE
    assert isinstance(logic.parser, NormativeParser)
    assert isinstance(logic.printer, NormativePrinter)


def test_profile_requires_named_semantics() -> None:
    with pytest.raises(SyntaxContractError, match="profile_id is required"):
        NormativeProfile(profile_id="", semantics="dyadic")
    with pytest.raises(SyntaxContractError, match="unknown normative semantics"):
        NormativeProfile(profile_id="bad", semantics="classical")


def test_named_profiles_expose_semantics() -> None:
    d = _dyadic()
    assert d.semantics is NormativeSemantics.DYADIC
    assert d.semantics_name == "dyadic"
    assert d.admit_dyadic is True
    assert d.admit_defeasible is False

    f = _defeasible()
    assert f.semantics is NormativeSemantics.DEFEASIBLE
    assert f.admit_defeasible is True
    assert f.admit_exception is True

    p = _prioritized()
    assert p.semantics is NormativeSemantics.PRIORITIZED
    assert p.admit_priority is True
    assert p.admit_conflict is True

    c = _ctd()
    assert c.semantics is NormativeSemantics.CONTRARY_TO_DUTY
    assert c.admit_contrary_to_duty is True
    assert c.admit_reparation is True
    assert c.admit_violation is True


# ---------------------------------------------------------------------------
# Semantic decision records — one per profile
# ---------------------------------------------------------------------------


def test_each_profile_has_semantic_decision_record() -> None:
    profiles = (_dyadic(), _defeasible(), _prioritized(), _ctd())
    for prof in profiles:
        sdr = prof.semantic_decision_record
        assert isinstance(sdr, SemanticDecisionRecord)
        assert sdr.profile_id == prof.profile_id
        assert sdr.semantics_name == prof.semantics_name
        assert sdr.grants_classical_entailment is False
        assert sdr.grants_material_implication_equiv is False
        assert sdr.grants_cross_profile_equiv is False
        assert len(sdr.admitted_constructs) >= 1
        assert len(sdr.rejected_equivalences) >= 1
        payload = sdr.to_dict()
        assert payload["interface"] == NORMATIVE_SEMANTIC_DECISION_INTERFACE
        assert payload["grants_classical_entailment"] is False


def test_dyadic_sdr_rejects_material_implication_equiv() -> None:
    sdr = _dyadic().semantic_decision_record
    assert sdr.admits("dyadic_norm")
    assert sdr.rejects_equivalence(
        "dyadic_equals_monadic_material_implication"
    )
    assert sdr.rejects_equivalence("O(p|q)_equals_O(q_implies_p)")
    assert sdr.rejects_equivalence("dyadic_equals_defeasible")
    assert sdr.rejects_equivalence("dyadic_equals_contrary_to_duty")


def test_defeasible_sdr_rejects_strict_implication() -> None:
    sdr = _defeasible().semantic_decision_record
    assert sdr.admits("defeasible_norm")
    assert sdr.admits("exception")
    assert sdr.rejects_equivalence("defeasible_equals_strict_implication")
    assert sdr.rejects_equivalence("defeasible_equals_dyadic")


def test_prioritized_sdr_rejects_unprioritized_conjunction() -> None:
    sdr = _prioritized().semantic_decision_record
    assert sdr.admits("priority")
    assert sdr.admits("conflict")
    assert sdr.rejects_equivalence(
        "prioritized_equals_unprioritized_conjunction"
    )
    assert sdr.rejects_equivalence("prioritized_equals_dyadic")


def test_ctd_sdr_rejects_conjunction_of_monadic() -> None:
    sdr = _ctd().semantic_decision_record
    assert sdr.admits("contrary_to_duty")
    assert sdr.admits("reparation")
    assert sdr.rejects_equivalence("ctd_equals_conjunction_of_monadic_norms")
    assert sdr.rejects_equivalence("ctd_equals_dyadic_conditional")
    assert sdr.rejects_equivalence("reparation_equals_independent_obligation")


def test_sdr_cannot_grant_classical_or_cross_profile() -> None:
    with pytest.raises(AuthorityPromotionError, match="classical"):
        SemanticDecisionRecord(
            profile_id="x",
            semantics=NormativeSemantics.DYADIC,
            admitted_constructs=("monadic_norm",),
            rejected_equivalences=(),
            grants_classical_entailment=True,
        )
    with pytest.raises(AuthorityPromotionError, match="material"):
        SemanticDecisionRecord(
            profile_id="x",
            semantics=NormativeSemantics.DYADIC,
            admitted_constructs=("monadic_norm",),
            rejected_equivalences=(),
            grants_material_implication_equiv=True,
        )
    with pytest.raises(AuthorityPromotionError, match="cross-profile"):
        SemanticDecisionRecord(
            profile_id="x",
            semantics=NormativeSemantics.DYADIC,
            admitted_constructs=("monadic_norm",),
            rejected_equivalences=(),
            grants_cross_profile_equiv=True,
        )


# ---------------------------------------------------------------------------
# Parser / printer fixtures — dyadic
# ---------------------------------------------------------------------------


def test_parse_monadic_and_dyadic_norms() -> None:
    result = parse_normative(
        "O(pay) and O(refund | breach) and fact(breach) and status(refund)",
        _dyadic(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.profile is not None
    assert result.profile.semantics_name == "dyadic"
    assert result.semantic_decision_record is not None
    assert result.theory is not None
    assert len(result.theory.monadic) == 1
    assert len(result.theory.dyadic) == 1
    assert result.theory.dyadic[0].content == "refund"
    assert result.theory.dyadic[0].condition == "breach"
    assert result.theory.dyadic[0].operator == "obligation"
    # Payload records rejected material-implication equivalence.
    assert result.theory.dyadic[0].to_dict()["kind"] == "dyadic"
    printed = print_normative(result.root)
    assert "O(pay)" in printed
    assert "O(refund | breach)" in printed
    assert "fact(breach)" in printed


def test_dyadic_evaluation_condition_gated() -> None:
    # Without condition fact: content inactive (not classical O(q→p)).
    inactive = parse_normative(
        "O(refund | breach) and status(refund)",
        _dyadic(),
    )
    assert inactive.ok
    assert inactive.evaluation is not None
    assert inactive.evaluation.status_of("refund") is NormStatus.INACTIVE
    assert inactive.evaluation.material_implication_equiv is False
    assert inactive.evaluation.classical_entailment is False

    # With condition fact: content active.
    active = parse_normative(
        "O(refund | breach) and fact(breach) and status(refund)",
        _dyadic(),
    )
    assert active.ok
    assert active.evaluation is not None
    assert active.evaluation.status_of("refund") is NormStatus.ACTIVE
    assert "refund" in active.evaluation.active_norms


def test_dyadic_slash_separator() -> None:
    result = parse_normative("P(enter / ticket)", _dyadic())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.theory is not None
    assert result.theory.dyadic[0].condition == "ticket"
    printed = print_normative(result.root)
    assert "P(enter | ticket)" in printed  # canonical print uses |


def test_dyadic_profile_rejects_defeasible() -> None:
    result = parse_normative("defeasible O(fly) unless penguin", _dyadic())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_dyadic_profile_rejects_ctd() -> None:
    result = parse_normative("ctd(keep, apologize)", _dyadic())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Parser / printer fixtures — defeasible
# ---------------------------------------------------------------------------


def test_parse_defeasible_with_unless() -> None:
    result = parse_normative(
        "defeasible O(flies) unless penguin and fact(penguin) and status(flies)",
        _defeasible(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.theory is not None
    assert len(result.theory.defeasible) == 1
    assert result.theory.defeasible[0].unless == "penguin"
    printed = print_normative(result.root)
    assert "defeasible O(flies)" in printed
    assert "unless penguin" in printed


def test_defeasible_defeated_by_unless_fact() -> None:
    result = parse_normative(
        "defeasible O(flies) unless penguin and fact(penguin) and status(flies)",
        _defeasible(),
    )
    assert result.ok
    assert result.evaluation is not None
    assert result.evaluation.status_of("flies") is NormStatus.INACTIVE
    assert result.evaluation.classical_entailment is False


def test_defeasible_active_without_exception() -> None:
    result = parse_normative(
        "defeasible O(flies) unless penguin and status(flies)",
        _defeasible(),
    )
    assert result.ok
    assert result.evaluation is not None
    assert result.evaluation.status_of("flies") is NormStatus.ACTIVE


def test_defeasible_exception_construct() -> None:
    result = parse_normative(
        "defeasible O(flies) and exception(flies, penguin) and "
        "fact(penguin) and status(flies)",
        _defeasible(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.theory is not None
    assert ("flies", "penguin") in result.theory.exceptions
    assert result.evaluation is not None
    assert result.evaluation.status_of("flies") is NormStatus.INACTIVE


def test_defeasible_profile_rejects_dyadic() -> None:
    result = parse_normative("O(refund | breach)", _defeasible())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_normally_alias() -> None:
    result = parse_normative("normally O(quiet)", _defeasible())
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_normative(result.root)
    assert "defeasible O(quiet)" in printed


# ---------------------------------------------------------------------------
# Parser / printer fixtures — prioritized
# ---------------------------------------------------------------------------


def test_parse_priority_and_conflict() -> None:
    text = (
        "norm(n1, O(keep_secret)) and norm(n2, O(tell_truth)) and "
        "priority(n1, n2) and conflict(n1, n2) and "
        "status(n1) and status(n2)"
    )
    result = parse_normative(text, _prioritized())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.theory is not None
    assert ("n1", "n2") in result.theory.priorities
    assert ("n1", "n2") in result.theory.conflicts
    printed = print_normative(result.root)
    assert "priority(n1, n2)" in printed
    assert "conflict(n1, n2)" in printed
    assert "norm(n1, O(keep_secret))" in printed


def test_prioritized_higher_wins_conflict() -> None:
    text = (
        "norm(n1, O(keep_secret)) and norm(n2, O(tell_truth)) and "
        "priority(n1 > n2) and conflict(n1, n2) and "
        "status(n1) and status(n2)"
    )
    result = parse_normative(text, _prioritized())
    assert result.ok, [d.message for d in result.diagnostics]
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.status_of("n1") is NormStatus.ACTIVE
    assert evaluation.status_of("n2") is NormStatus.INACTIVE
    assert evaluation.classical_entailment is False
    assert evaluation.cross_profile_equiv is False


def test_prioritized_equal_rank_conflict_undecided() -> None:
    text = (
        "norm(n1, O(a)) and norm(n2, O(b)) and "
        "conflict(n1, n2) and status(n1) and status(n2)"
    )
    result = parse_normative(text, _prioritized())
    assert result.ok, [d.message for d in result.diagnostics]
    evaluation = result.evaluation
    assert evaluation is not None
    # Equal rank → undecided, not classical inconsistency.
    assert evaluation.status_of("n1") is NormStatus.UNDECIDED
    assert evaluation.status_of("n2") is NormStatus.UNDECIDED


def test_prioritized_profile_rejects_dyadic() -> None:
    result = parse_normative("O(p | q)", _prioritized())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_prioritized_profile_rejects_defeasible() -> None:
    result = parse_normative("defeasible O(p)", _prioritized())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Parser / printer fixtures — contrary-to-duty
# ---------------------------------------------------------------------------


def test_parse_ctd_and_reparation() -> None:
    text = (
        "ctd(keep_promise, apologize) and "
        "reparation(keep_promise, compensate) and "
        "status(keep_promise) and status(apologize)"
    )
    result = parse_normative(text, _ctd())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.theory is not None
    assert len(result.theory.ctd) == 1
    assert result.theory.ctd[0].primary == "keep_promise"
    assert result.theory.ctd[0].secondary == "apologize"
    printed = print_normative(result.root)
    assert "ctd(keep_promise, apologize)" in printed
    assert "reparation(keep_promise, compensate)" in printed


def test_ctd_secondary_inactive_when_primary_holds() -> None:
    # No violation: primary active, secondary NOT independently active.
    result = parse_normative(
        "ctd(keep_promise, apologize) and "
        "status(keep_promise) and status(apologize)",
        _ctd(),
    )
    assert result.ok
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.status_of("keep_promise") is NormStatus.ACTIVE
    assert evaluation.status_of("apologize") is NormStatus.INACTIVE
    assert evaluation.classical_entailment is False


def test_ctd_reparation_activates_on_violation() -> None:
    result = parse_normative(
        "ctd(keep_promise, apologize) and "
        "violation(keep_promise) and "
        "status(keep_promise) and status(apologize)",
        _ctd(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.status_of("keep_promise") is NormStatus.VIOLATED
    assert evaluation.status_of("apologize") is NormStatus.REPARATION_ACTIVE
    assert "apologize" in evaluation.reparation_active
    assert "keep_promise" in evaluation.violated_norms


def test_ctd_not_conjunction_of_monadic() -> None:
    """CTD secondary is inactive without violation — not O(p) ∧ O(s)."""

    result = parse_normative(
        "ctd(keep_promise, apologize) and status(apologize)",
        _ctd(),
    )
    assert result.ok
    # Independent monadic pair would activate both; CTD does not.
    assert result.evaluation is not None
    assert result.evaluation.status_of("apologize") is not NormStatus.ACTIVE
    sdr = result.semantic_decision_record
    assert sdr is not None
    assert sdr.rejects_equivalence("ctd_equals_conjunction_of_monadic_norms")


def test_ctd_profile_rejects_priority() -> None:
    result = parse_normative("priority(a, b)", _ctd())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_contrary_to_duty_keyword_alias() -> None:
    result = parse_normative(
        "contrary_to_duty(primary, secondary)",
        _ctd(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_normative(result.root)
    assert "ctd(primary, secondary)" in printed


# ---------------------------------------------------------------------------
# Negative ambiguity cases
# ---------------------------------------------------------------------------


def test_bare_typically_is_ambiguous() -> None:
    result = parse_normative("typically O(pay)", _defeasible())
    assert not result.ok
    assert any(d.code == CODE_AMBIGUOUS_FORM for d in result.diagnostics)


def test_bare_prima_facie_is_ambiguous() -> None:
    result = parse_normative("prima_facie O(pay)", _defeasible())
    assert not result.ok
    assert any(d.code == CODE_AMBIGUOUS_FORM for d in result.diagnostics)


def test_or_is_not_dyadic_separator() -> None:
    result = parse_normative("O(pay or breach)", _dyadic())
    assert not result.ok
    assert any(d.code == CODE_AMBIGUOUS_FORM for d in result.diagnostics)


def test_defeasible_dyadic_hybrid_rejected() -> None:
    result = parse_normative(
        "defeasible O(refund | breach)",
        _defeasible(),
    )
    assert not result.ok
    assert any(d.code == CODE_AMBIGUOUS_FORM for d in result.diagnostics)


def test_empty_input_rejected() -> None:
    result = parse_normative("   ", _dyadic())
    assert not result.ok
    assert result.status is not ParseStatus.OK


# ---------------------------------------------------------------------------
# Round-trip fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,profile_factory",
    [
        ("O(pay) and O(refund | breach) and fact(breach)", _dyadic),
        ("defeasible O(flies) unless penguin and fact(bird)", _defeasible),
        (
            "norm(n1, O(a)) and norm(n2, O(b)) and priority(n1, n2)",
            _prioritized,
        ),
        (
            "ctd(keep, apologize) and violation(keep) and reparation(keep, pay)",
            _ctd,
        ),
    ],
)
def test_parse_print_parse_round_trip(text, profile_factory) -> None:
    profile = profile_factory()
    first, second, equivalent = parse_print_parse(text, profile)
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent
    assert alpha_equivalent(first.root, second.root)
    # Round-trip preserves profile semantics identity.
    assert first.profile.semantics_name == profile.semantics_name
    assert second.profile.semantics_name == profile.semantics_name


def test_semantic_identity_includes_sdr() -> None:
    result = parse_normative("O(p | q)", _dyadic())
    assert result.ok
    identity = normative_semantic_identity(result.root, _dyadic())
    assert identity["family"] == "deontic"
    assert identity["semantics"] == "dyadic"
    assert identity["profile"]["profile_id"] == "normative_dyadic"
    sdr = identity["profile"]["semantic_decision_record"]
    assert sdr["grants_material_implication_equiv"] is False
    assert "dyadic_equals_monadic_material_implication" in sdr[
        "rejected_equivalences"
    ]


# ---------------------------------------------------------------------------
# No unearned equivalence between norm systems
# ---------------------------------------------------------------------------


def test_distinct_semantics_not_equivalent() -> None:
    pairs = [
        (_dyadic(), _defeasible()),
        (_dyadic(), _prioritized()),
        (_dyadic(), _ctd()),
        (_defeasible(), _prioritized()),
        (_defeasible(), _ctd()),
        (_prioritized(), _ctd()),
    ]
    for left, right in pairs:
        assert not profiles_are_equivalent(left, right)
        with pytest.raises(AuthorityPromotionError, match="unearned equivalence"):
            reject_unearned_equivalence(left, right)


def test_same_profile_is_equivalent_to_itself() -> None:
    p = _dyadic()
    assert profiles_are_equivalent(p, profile_dyadic())
    reject_unearned_equivalence(p, profile_dyadic())  # does not raise


def test_dyadic_payload_marks_no_material_implication() -> None:
    result = parse_normative("O(p | q)", _dyadic())
    assert result.ok
    assert result.root is not None
    # Walk extension payload.
    ext = result.root.extension
    assert ext is not None
    assert ext.payload.get("material_implication_equiv") is False


def test_ctd_payload_marks_no_conjunction_equiv() -> None:
    result = parse_normative("ctd(a, b)", _ctd())
    assert result.ok
    assert result.root is not None
    ext = result.root.extension
    assert ext is not None
    assert ext.payload.get("conjunction_equiv") is False


def test_defeasible_payload_marks_no_strict_implication() -> None:
    result = parse_normative("defeasible O(p)", _defeasible())
    assert result.ok
    assert result.root is not None
    ext = result.root.extension
    assert ext is not None
    assert ext.payload.get("strict_implication_equiv") is False


def test_evaluation_rejects_classical_and_cross_profile_flags() -> None:
    with pytest.raises(AuthorityPromotionError, match="classical"):
        NormativeEvaluation(
            profile_id="normative_dyadic",
            semantics=NormativeSemantics.DYADIC,
            classical_entailment=True,
        )
    with pytest.raises(AuthorityPromotionError, match="material"):
        NormativeEvaluation(
            profile_id="normative_dyadic",
            semantics=NormativeSemantics.DYADIC,
            material_implication_equiv=True,
        )
    with pytest.raises(AuthorityPromotionError, match="cross-profile"):
        NormativeEvaluation(
            profile_id="normative_dyadic",
            semantics=NormativeSemantics.DYADIC,
            cross_profile_equiv=True,
        )


# ---------------------------------------------------------------------------
# Authority ceilings
# ---------------------------------------------------------------------------


def test_dyadic_evidence_is_normative_not_classical() -> None:
    evidence = dyadic_evidence_contract(_dyadic())
    assert evidence.source is EvidenceSource.DYADIC_EVALUATOR
    assert evidence.authority_ceiling is EvidenceAuthority.NORMATIVE
    assert evidence.grants_classical_entailment is False
    assert evidence.is_classical_entailment is False
    assert evidence.may_promote_to_classical_entailment is False
    with pytest.raises(AuthorityPromotionError, match="classical"):
        evidence.promote_to_classical_entailment()


def test_defeasible_evidence_is_nonmonotonic() -> None:
    evidence = defeasible_evidence_contract(_defeasible())
    assert evidence.authority_ceiling is EvidenceAuthority.NONMONOTONIC
    assert evidence.source is EvidenceSource.DEFEASIBLE_EVALUATOR
    with pytest.raises(AuthorityPromotionError, match="classical"):
        evidence.promote_to_classical_entailment()


def test_prioritized_and_ctd_evidence() -> None:
    p = prioritized_evidence_contract(_prioritized())
    assert p.authority_ceiling is EvidenceAuthority.NORMATIVE
    c = ctd_evidence_contract(_ctd())
    assert c.authority_ceiling is EvidenceAuthority.NORMATIVE
    assert c.semantics is NormativeSemantics.CONTRARY_TO_DUTY or (
        str(c.semantics) == "contrary_to_duty"
        or getattr(c.semantics, "value", None) == "contrary_to_duty"
    )


def test_cannot_construct_normative_as_classical_entailment() -> None:
    with pytest.raises(AuthorityPromotionError, match="classical"):
        NormativeEvidenceContract(
            source=EvidenceSource.DYADIC_EVALUATOR,
            authority=EvidenceAuthority.CLASSICAL_ENTAILMENT,
            semantics=NormativeSemantics.DYADIC,
            profile_id="normative_dyadic",
        )


def test_cannot_grant_material_implication_equiv_on_evidence() -> None:
    with pytest.raises(AuthorityPromotionError):
        NormativeEvidenceContract(
            source=EvidenceSource.DYADIC_EVALUATOR,
            authority=EvidenceAuthority.NORMATIVE,
            semantics=NormativeSemantics.DYADIC,
            profile_id="normative_dyadic",
            grants_material_implication_equiv=True,
        )


def test_retain_authority_ceiling_rejects_escalation() -> None:
    evidence = dyadic_evidence_contract(_dyadic())
    retained = retain_authority_ceiling(evidence)
    assert retained["authority_ceiling"] == "normative"
    assert retained["grants_classical_entailment"] is False
    assert retained["grants_material_implication_equiv"] is False
    with pytest.raises(AuthorityPromotionError, match="classical"):
        retain_authority_ceiling(
            evidence,
            claimed={
                "authority": "classical_entailment",
                "grants_classical_entailment": True,
            },
        )
    with pytest.raises(AuthorityPromotionError):
        retain_authority_ceiling(
            evidence,
            claimed={"grants_material_implication_equiv": True},
        )
    with pytest.raises(AuthorityPromotionError):
        retain_authority_ceiling(
            evidence,
            claimed={"grants_cross_profile_equiv": True},
        )


def test_lowering_receipt_carries_sdr() -> None:
    logic = NormativeLogicProfiles(_dyadic())
    result = logic.parse_text("O(p | q) and fact(q)")
    assert result.ok
    evidence = dyadic_evidence_contract(_dyadic())
    receipt = logic.attach_evidence(result, evidence)
    assert receipt.authorizes_classical_entailment is False
    assert receipt.authority_ceiling == "normative"
    assert receipt.semantics == "dyadic"
    assert receipt.semantic_decision_record["semantics"] == "dyadic"
    assert receipt.semantic_decision_record[
        "grants_material_implication_equiv"
    ] is False
    with pytest.raises(AuthorityPromotionError, match="classical"):
        NormativeLoweringReceipt(
            document_id="doc:1",
            profile_id=result.profile.profile_id,
            semantics=result.profile.semantics_name,
            evaluation=result.evaluation.to_dict(),
            evidence={
                "source": "dyadic_evaluator",
                "authority": "classical_entailment",
                "authority_ceiling": "classical_entailment",
                "grants_classical_entailment": True,
            },
            authorizes_classical_entailment=True,
        )


def test_parse_result_includes_sdr() -> None:
    result = parse_normative("O(a)", _prioritized())
    assert result.ok
    assert result.semantic_decision_record is not None
    assert result.semantic_decision_record.semantics_name == "prioritized"
    payload = result.to_dict()
    assert payload["semantic_decision_record"]["semantics"] == "prioritized"


def test_multi_letter_operators() -> None:
    result = parse_normative(
        "obligated(pay) and permitted(enter) and forbidden(steal)",
        _dyadic(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_normative(result.root)
    assert "O(pay)" in printed
    assert "P(enter)" in printed
    assert "F(steal)" in printed


def test_evaluate_theory_direct() -> None:
    result = parse_normative(
        "O(refund | breach) and fact(breach)",
        _dyadic(),
    )
    assert result.ok and result.theory is not None
    evaluation = evaluate_theory(result.theory, _dyadic())
    assert evaluation.semantics_name == "dyadic"
    assert evaluation.status_of("refund") is NormStatus.ACTIVE
    assert evaluation.classical_entailment is False


def test_extract_theory_from_ast() -> None:
    result = parse_normative(
        "norm(n1, O(a)) and priority(n1, n2) and conflict(n1, n2)",
        _prioritized(),
    )
    assert result.ok
    theory = extract_theory(result.root)
    assert len(theory.named) == 1
    assert theory.named[0][0] == "n1"
    assert ("n1", "n2") in theory.priorities
