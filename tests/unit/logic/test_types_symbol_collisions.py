from __future__ import annotations

import inspect


def test_types_predicate_is_tdfol_predicate() -> None:
    import ipfs_datasets_py.logic.types as types

    # The public Predicate constructor is expected to be the TDFOL predicate
    # (name + arguments), not the FOL metadata predicate (name + arity).
    sig = inspect.signature(types.Predicate)
    params = list(sig.parameters.keys())
    assert params[:2] == ["name", "arguments"], params


def test_types_exports_fol_predicate_alias() -> None:
    import ipfs_datasets_py.logic.types as types

    assert hasattr(types, "FOLPredicate")
    sig = inspect.signature(types.FOLPredicate)
    params = list(sig.parameters.keys())
    assert params[:2] == ["name", "arity"], params

    exported = set(getattr(types, "__all__", []))
    assert "FOLPredicate" in exported
