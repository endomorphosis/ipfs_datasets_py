import pytest

from ipfs_datasets_py.logic.zkp.legal_theorem_semantics import (
    LegalTheoremSyntaxError,
    evaluate_tdfol_v1_holds,
    parse_tdfol_v1_axiom,
)


def test_parse_fact_axiom() -> None:
    ax = parse_tdfol_v1_axiom("P")
    assert ax.antecedent is None
    assert ax.consequent == "P"


def test_parse_implication_axiom() -> None:
    ax = parse_tdfol_v1_axiom("P -> Q")
    assert ax.antecedent == "P"
    assert ax.consequent == "Q"


def test_holds_forward_chaining_modus_ponens() -> None:
    assert evaluate_tdfol_v1_holds(["P", "P -> Q"], "Q") is True


def test_holds_transitive_chain() -> None:
    assert evaluate_tdfol_v1_holds(["P", "P -> Q", "Q -> R"], "R") is True


def test_not_holds_without_fact() -> None:
    assert evaluate_tdfol_v1_holds(["P -> Q"], "Q") is False


def test_whitespace_is_ignored() -> None:
    assert evaluate_tdfol_v1_holds(["  P  ", "P->Q", "Q  ->   R"], "R") is True


def test_rejects_invalid_atom_characters() -> None:
    with pytest.raises(LegalTheoremSyntaxError):
        parse_tdfol_v1_axiom("P -> Q!")


def test_rejects_multiple_arrows() -> None:
    with pytest.raises(LegalTheoremSyntaxError):
        parse_tdfol_v1_axiom("P -> Q -> R")
