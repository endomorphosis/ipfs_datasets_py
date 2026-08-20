"""Unit tests for ArgumentationLogic@1 (LFP2-038).

Evidence subset:

* arguments, attacks, support, priorities, defeasible rules
* grounded / preferred-style named profile identities
* undecided and multiple-extension outcomes preserved
* no classical entailment promotion
* parse/print/parse semantic round-trip
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.argumentation import (
    ARG_FAMILY_ID,
    ARG_NOTATION_ID,
    ARGUMENTATION_LOGIC_INTERFACE,
    ARGUMENTATION_PROFILE_INTERFACE,
    ArgumentLabel,
    ArgumentationEvidenceContract,
    ArgumentationFramework,
    ArgumentationLogic,
    ArgumentationLoweringReceipt,
    ArgumentationParser,
    ArgumentationPrinter,
    ArgumentationProfile,
    ArgumentationSemantics,
    AuthorityPromotionError,
    CODE_PROFILE_MISMATCH,
    CODE_SELF_ATTACK,
    EvidenceAuthority,
    EvidenceSource,
    argumentation_semantic_identity,
    defeasible_evidence_contract,
    evaluate_framework,
    grounded_evidence_contract,
    parse_argumentation,
    parse_print_parse,
    preferred_evidence_contract,
    print_argumentation,
    profile_complete,
    profile_defeasible,
    profile_grounded,
    profile_preferred,
    profile_stable,
    retain_authority_ceiling,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
    SyntaxContractError,
)


def _grounded():
    return profile_grounded()


def _preferred():
    return profile_preferred()


def _complete():
    return profile_complete()


def _stable():
    return profile_stable()


def _defeasible():
    return profile_defeasible()


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert ARGUMENTATION_LOGIC_INTERFACE == "ArgumentationLogic@1"
    assert ARGUMENTATION_PROFILE_INTERFACE == "ArgumentationProfile@1"
    assert ARG_FAMILY_ID == "argumentation"
    assert ARG_NOTATION_ID == "canonical_argumentation"
    logic = ArgumentationLogic(_grounded())
    assert logic.interface == ARGUMENTATION_LOGIC_INTERFACE
    assert isinstance(logic.parser, ArgumentationParser)
    assert isinstance(logic.printer, ArgumentationPrinter)


def test_profile_requires_named_semantics() -> None:
    with pytest.raises(SyntaxContractError, match="profile_id is required"):
        ArgumentationProfile(profile_id="", semantics="grounded")
    with pytest.raises(SyntaxContractError, match="unknown argumentation semantics"):
        ArgumentationProfile(profile_id="bad", semantics="classical")


def test_named_profiles_expose_semantics() -> None:
    g = _grounded()
    assert g.semantics is ArgumentationSemantics.GROUNDED
    assert g.semantics_name == "grounded"
    assert g.preserves_undecided is True
    assert g.is_multi_extension is False

    p = _preferred()
    assert p.semantics is ArgumentationSemantics.PREFERRED
    assert p.is_multi_extension is True
    assert p.preserves_undecided is True

    d = _defeasible()
    assert d.semantics is ArgumentationSemantics.DEFEASIBLE
    assert d.family_id == "nonmonotonic_logic"
    assert d.admit_defeasible_rules is True


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


def test_parse_arguments_and_attacks() -> None:
    result = parse_argumentation(
        "arg(a) and arg(b) and attack(a, b)",
        _grounded(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.AND
    assert result.profile is not None
    assert result.profile.semantics_name == "grounded"
    assert result.framework is not None
    assert set(result.framework.arguments) >= {"a", "b"}
    assert ("a", "b") in result.framework.attacks
    printed = print_argumentation(result.root)
    assert "arg(a)" in printed
    assert "attack(a, b)" in printed


def test_parse_support_and_priority() -> None:
    result = parse_argumentation(
        "arg(a) and arg(b) and support(a, b) and priority(a, b)",
        _preferred(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.framework is not None
    assert ("a", "b") in result.framework.supports
    assert ("a", "b") in result.framework.priorities
    printed = print_argumentation(result.root)
    assert "support(a, b)" in printed
    assert "priority(a, b)" in printed


def test_parse_defeasible_and_strict_rules() -> None:
    result = parse_argumentation(
        "strict bird :- penguin and defeasible flies :- bird and priority(penguin, flies)",
        _defeasible(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.framework is not None
    assert len(result.framework.rules) == 2
    kinds = {rule.defeasible for rule in result.framework.rules}
    assert True in kinds and False in kinds


def test_grounded_profile_rejects_defeasible_rules() -> None:
    result = parse_argumentation("defeasible flies :- bird", _grounded())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_self_attack_rejected_by_default() -> None:
    result = parse_argumentation("arg(a) and attack(a, a)", _grounded())
    assert not result.ok
    assert any(d.code == CODE_SELF_ATTACK for d in result.diagnostics)


def test_semantic_identity_includes_named_profile() -> None:
    result = parse_argumentation("arg(a) and attack(b, a)", _grounded())
    assert result.ok
    identity = argumentation_semantic_identity(result.root, _grounded())
    assert identity["family"] == "argumentation"
    assert identity["semantics"] == "grounded"
    assert identity["profile"]["profile_id"] == "argumentation_grounded"
    assert identity["profile"]["semantics"] == "grounded"


# ---------------------------------------------------------------------------
# Grounded semantics — undecided preserved
# ---------------------------------------------------------------------------


def test_grounded_unique_extension_with_undecided() -> None:
    # Classic 3-cycle: a->b->c->a has empty grounded extension; all undecided.
    text = (
        "arg(a) and arg(b) and arg(c) and "
        "attack(a, b) and attack(b, c) and attack(c, a)"
    )
    result = parse_argumentation(text, _grounded())
    assert result.ok, [d.message for d in result.diagnostics]
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.semantics_name == "grounded"
    assert evaluation.profile_id == "argumentation_grounded"
    assert evaluation.unique_extension
    assert evaluation.extensions == ((),)
    assert evaluation.has_undecided
    assert evaluation.labeling is not None
    assert evaluation.labeling.undecided_set == frozenset({"a", "b", "c"})
    assert evaluation.classical_entailment is False
    # status_of preserves undecided — never classical false.
    assert evaluation.status_of("a") is ArgumentLabel.UNDECIDED


def test_grounded_accepts_unattacked_argument() -> None:
    text = "arg(a) and arg(b) and attack(a, b) and status(a) and status(b)"
    result = parse_argumentation(text, _grounded())
    assert result.ok, [d.message for d in result.diagnostics]
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.extensions == (("a",),)
    assert evaluation.status_of("a") is ArgumentLabel.IN
    assert evaluation.status_of("b") is ArgumentLabel.OUT
    assert evaluation.queries["a"] is ArgumentLabel.IN
    assert evaluation.queries["b"] is ArgumentLabel.OUT


# ---------------------------------------------------------------------------
# Preferred / multi-extension — multiple extensions preserved
# ---------------------------------------------------------------------------


def test_preferred_preserves_multiple_extensions() -> None:
    # Mutual attack: two preferred extensions {a} and {b}.
    text = "arg(a) and arg(b) and attack(a, b) and attack(b, a)"
    result = parse_argumentation(text, _preferred())
    assert result.ok, [d.message for d in result.diagnostics]
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.semantics_name == "preferred"
    assert evaluation.multiple_extensions is True
    assert evaluation.extension_count == 2
    ext_set = {ext for ext in evaluation.extensions}
    assert ("a",) in ext_set
    assert ("b",) in ext_set
    # Disagreement → undecided under skeptical reading.
    assert evaluation.status_of("a") is ArgumentLabel.UNDECIDED
    assert evaluation.status_of("b") is ArgumentLabel.UNDECIDED
    assert evaluation.has_undecided
    assert evaluation.classical_entailment is False


def test_complete_enumerates_all_complete_extensions() -> None:
    text = "arg(a) and arg(b) and attack(a, b) and attack(b, a)"
    result = parse_argumentation(text, _complete())
    assert result.ok, [d.message for d in result.diagnostics]
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.semantics_name == "complete"
    # Empty set is complete; {a} and {b} are complete.
    assert evaluation.extension_count >= 2
    assert evaluation.multiple_extensions is True
    assert evaluation.classical_entailment is False


def test_stable_extensions_when_present() -> None:
    text = "arg(a) and arg(b) and attack(a, b) and attack(b, a)"
    result = parse_argumentation(text, _stable())
    assert result.ok, [d.message for d in result.diagnostics]
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.semantics_name == "stable"
    ext_set = {ext for ext in evaluation.extensions}
    assert ("a",) in ext_set
    assert ("b",) in ext_set
    assert evaluation.multiple_extensions is True


def test_evaluation_rejects_classical_entailment_flag() -> None:
    from ipfs_datasets_py.logic.parsers.argumentation import ArgumentationEvaluation

    with pytest.raises(AuthorityPromotionError, match="classical_entailment"):
        ArgumentationEvaluation(
            profile_id="argumentation_grounded",
            semantics=ArgumentationSemantics.GROUNDED,
            extensions=(("a",),),
            classical_entailment=True,
        )


# ---------------------------------------------------------------------------
# Defeasible / nonmonotonic
# ---------------------------------------------------------------------------


def test_defeasible_evaluation_with_priority() -> None:
    # penguin is a bird; birds fly defeasibly; penguin defeats flies.
    text = (
        "strict bird :- penguin and "
        "defeasible flies :- bird and "
        "arg(penguin) and "
        "attack(penguin, flies) and "
        "priority(penguin, flies) and "
        "status(flies) and status(bird)"
    )
    result = parse_argumentation(text, _defeasible())
    assert result.ok, [d.message for d in result.diagnostics]
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.semantics_name == "defeasible"
    assert evaluation.profile_id == "nonmonotonic_defeasible"
    # bird derived via strict rule from penguin fact.
    assert evaluation.status_of("bird") is ArgumentLabel.IN
    # flies defeated by higher-priority penguin attacker.
    assert evaluation.status_of("flies") in {
        ArgumentLabel.OUT,
        ArgumentLabel.UNDECIDED,
    }
    assert evaluation.classical_entailment is False


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_parse_print_parse_round_trip() -> None:
    text = "arg(a) and arg(b) and attack(a, b) and support(b, a)"
    first, second, equivalent = parse_print_parse(text, _preferred())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent
    assert alpha_equivalent(first.root, second.root)


def test_parse_print_parse_defeasible_rules() -> None:
    text = "strict bird :- penguin and defeasible flies :- bird"
    first, second, equivalent = parse_print_parse(text, _defeasible())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent


def test_empty_input_rejected() -> None:
    result = parse_argumentation("   ", _grounded())
    assert not result.ok
    assert result.status is not ParseStatus.OK


# ---------------------------------------------------------------------------
# Authority ceilings: no classical entailment promotion
# ---------------------------------------------------------------------------


def test_grounded_evidence_is_argumentation_not_classical() -> None:
    evidence = grounded_evidence_contract(_grounded())
    assert evidence.source is EvidenceSource.GROUNDED_EVALUATOR
    assert evidence.authority_ceiling is EvidenceAuthority.ARGUMENTATION
    assert evidence.grants_classical_entailment is False
    assert evidence.is_classical_entailment is False
    assert evidence.may_promote_to_classical_entailment is False
    assert evidence.preserves_undecided is True
    assert evidence.semantics is ArgumentationSemantics.GROUNDED
    assert evidence.profile_id == "argumentation_grounded"
    with pytest.raises(AuthorityPromotionError, match="classical entailment"):
        evidence.promote_to_classical_entailment()


def test_preferred_evidence_preserves_multiple_extensions() -> None:
    evidence = preferred_evidence_contract(_preferred())
    assert evidence.preserves_multiple_extensions is True
    assert evidence.preserves_undecided is True
    with pytest.raises(AuthorityPromotionError, match="classical entailment"):
        evidence.promote_to_classical_entailment()


def test_defeasible_evidence_is_nonmonotonic() -> None:
    evidence = defeasible_evidence_contract(_defeasible())
    assert evidence.authority_ceiling is EvidenceAuthority.NONMONOTONIC
    assert evidence.source is EvidenceSource.DEFEASIBLE_EVALUATOR
    with pytest.raises(AuthorityPromotionError, match="classical entailment"):
        evidence.promote_to_classical_entailment()


def test_cannot_construct_af_as_classical_entailment() -> None:
    with pytest.raises(AuthorityPromotionError, match="classical entailment"):
        ArgumentationEvidenceContract(
            source=EvidenceSource.GROUNDED_EVALUATOR,
            authority=EvidenceAuthority.CLASSICAL_ENTAILMENT,
            semantics=ArgumentationSemantics.GROUNDED,
            profile_id="argumentation_grounded",
        )


def test_cannot_set_grants_classical_entailment() -> None:
    with pytest.raises(AuthorityPromotionError, match="grants_classical_entailment"):
        ArgumentationEvidenceContract(
            source=EvidenceSource.PREFERRED_EVALUATOR,
            authority=EvidenceAuthority.ARGUMENTATION,
            semantics=ArgumentationSemantics.PREFERRED,
            profile_id="argumentation_preferred",
            grants_classical_entailment=True,
        )


def test_retain_authority_ceiling_rejects_escalation() -> None:
    evidence = grounded_evidence_contract(_grounded())
    retained = retain_authority_ceiling(evidence)
    assert retained["authority_ceiling"] == "argumentation"
    assert retained["grants_classical_entailment"] is False
    assert retained["may_promote_to_classical_entailment"] is False
    assert retained["preserves_undecided"] is True
    with pytest.raises(AuthorityPromotionError, match="classical entailment"):
        retain_authority_ceiling(
            evidence,
            claimed={
                "authority": "classical_entailment",
                "grants_classical_entailment": True,
            },
        )


def test_retain_rejects_undecided_collapse() -> None:
    evidence = preferred_evidence_contract(_preferred())
    with pytest.raises(AuthorityPromotionError, match="undecided"):
        retain_authority_ceiling(
            evidence,
            claimed={"preserves_undecided": False},
        )


def test_retain_rejects_multi_extension_collapse() -> None:
    evidence = preferred_evidence_contract(_preferred())
    with pytest.raises(AuthorityPromotionError, match="multiple extensions"):
        retain_authority_ceiling(
            evidence,
            claimed={"preserves_multiple_extensions": False},
        )


def test_lowering_receipt_rejects_classical_authorization() -> None:
    logic = ArgumentationLogic(_grounded())
    result = logic.parse_text("arg(a) and arg(b) and attack(a, b)")
    assert result.ok
    evidence = grounded_evidence_contract(_grounded())
    receipt = logic.attach_evidence(result, evidence)
    assert receipt.authorizes_classical_entailment is False
    assert receipt.authority_ceiling == "argumentation"
    assert receipt.semantics == "grounded"
    assert receipt.profile_id == "argumentation_grounded"
    assert receipt.evaluation.get("classical_entailment") is False
    # Forging a receipt that authorizes classical entailment fails.
    with pytest.raises(AuthorityPromotionError, match="classical entailment"):
        ArgumentationLoweringReceipt(
            document_id="doc:1",
            profile_id=result.profile.profile_id,
            semantics=result.profile.semantics_name,
            evaluation=result.evaluation.to_dict(),
            evidence={
                "source": "grounded_evaluator",
                "authority": "classical_entailment",
                "authority_ceiling": "classical_entailment",
                "grants_classical_entailment": True,
                "is_classical_entailment": True,
            },
            authorizes_classical_entailment=True,
        )


def test_evidence_contracts_carry_named_profile() -> None:
    evidence = preferred_evidence_contract(_preferred())
    payload = evidence.to_dict()
    assert payload["profile_id"] == "argumentation_preferred"
    assert payload["semantics"] == "preferred"
    assert payload["preserves_multiple_extensions"] is True
    assert payload["preserves_undecided"] is True
    assert payload["is_classical_entailment"] is False


def test_evaluate_framework_direct() -> None:
    fw = ArgumentationFramework(
        arguments=("a", "b"),
        attacks=(("a", "b"), ("b", "a")),
    )
    evaluation = evaluate_framework(fw, _preferred())
    assert evaluation.multiple_extensions
    assert evaluation.extension_count == 2
    assert evaluation.semantics_name == "preferred"
    assert evaluation.classical_entailment is False
