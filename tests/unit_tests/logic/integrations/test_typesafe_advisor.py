from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
    last_formula_lint,
    last_formula_rank,
    lint_formula_against_clause,
    observe_formula_clause_lint,
    rank_allowlisted_formulas,
    typesafe_permitted,
)


def test_lint_without_key_does_not_rewrite_or_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    view = lint_formula_against_clause(
        "All humans are mortal",
        "∀x.(Human(x) → Mortal(x))",
        view_id="fol",
    )
    assert view["accepted_as_authority"] is False
    assert view["rewrites_ir"] is False
    assert view["drops_formula"] is False
    assert last_formula_lint()["rewrites_ir"] is False
    assert typesafe_permitted() is False


def test_lint_does_not_call_http_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    observe_formula_clause_lint("shall pay", "O(Pay(x))", view_id="deontic")


def test_low_noul_does_not_drop_formula(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_advisor.typesafe_permitted",
        lambda **_kwargs: True,
    )

    class _Result:
        nouls = {
            "captures": SimpleNamespace(noul=0.1, confidence=0.9),
            "modality_matches": SimpleNamespace(noul=0.2, confidence=0.9),
        }

    class _Noul:
        def __init__(self, instructions=None, criteria=None) -> None:
            self.instructions = instructions

    import sys
    import types as _types

    parent = sys.modules.get("ipfs_accelerate_py")
    if parent is None:
        parent = _types.ModuleType("ipfs_accelerate_py")
        monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", parent)
    stub = _types.ModuleType("ipfs_accelerate_py.typesafe_inference")
    stub.Noul = _Noul
    stub.system_one = lambda *_a, **_k: _Result()
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.typesafe_inference", stub)
    view = lint_formula_against_clause(
        "All humans are mortal",
        "∀x.(Human(x) → Mortal(x))",
        view_id="fol",
    )
    assert view["captures"] == pytest.approx(0.1)
    assert view["drops_formula"] is False
    assert view["rewrites_ir"] is False
    assert view["accepted_as_authority"] is False


def test_fol_converter_keeps_formula_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    from ipfs_datasets_py.logic.fol import FOLConverter

    converter = FOLConverter(use_ml=False, use_nlp=False, enable_monitoring=False)
    result = converter.convert("All humans are mortal")
    assert result.success is True
    assert result.output is not None
    assert result.output.formula_string
    lint = (result.output.metadata or {}).get("typesafe_lint") or {}
    assert lint.get("drops_formula") is False
    assert lint.get("rewrites_ir") is False


def test_rank_allowlisted_formulas_fail_open_keeps_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    ranked = rank_allowlisted_formulas(("cand-b", "cand-a", "cand-evil-kept"))
    assert ranked == ("cand-b", "cand-a", "cand-evil-kept")
    view = last_formula_rank()
    assert view["invents_ids"] is False
    assert view["admits_candidate"] is False
    assert "cand-invented" not in view["ranked_ids"]


def test_rank_allowlisted_formulas_drops_unknown_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_advisor.typesafe_permitted",
        lambda **_kwargs: True,
    )

    class _Result:
        nouls = {
            "matches_cand-low": SimpleNamespace(noul=0.1),
            "matches_cand-high": SimpleNamespace(noul=0.9),
            "matches_invented": SimpleNamespace(noul=1.0),
        }

    class _Noul:
        def __init__(self, instructions=None, criteria=None) -> None:
            self.instructions = instructions

    import sys
    import types as _types

    parent = sys.modules.get("ipfs_accelerate_py")
    if parent is None:
        parent = _types.ModuleType("ipfs_accelerate_py")
        monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", parent)
    stub = _types.ModuleType("ipfs_accelerate_py.typesafe_inference")
    stub.Noul = _Noul
    stub.system_one = lambda *_a, **_k: _Result()
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.typesafe_inference", stub)
    ranked = rank_allowlisted_formulas(("cand-low", "cand-high"))
    assert ranked == ("cand-high", "cand-low")
    assert "invented" not in ranked


def test_smt_trap_forces_solver_without_http(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_advisor.typesafe_permitted",
        lambda **_kwargs: True,
    )

    def boom(*_a, **_k):
        called.append(1)
        raise AssertionError("system_one must not run on FP/BV traps")

    import sys
    import types as _types

    parent = sys.modules.get("ipfs_accelerate_py")
    if parent is None:
        parent = _types.ModuleType("ipfs_accelerate_py")
        monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", parent)
    stub = _types.ModuleType("ipfs_accelerate_py.typesafe_inference")
    stub.Noul = object
    stub.Choice = object
    stub.system_one = boom
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.typesafe_inference", stub)
    from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
        last_smt_triage,
        triage_smt_goal,
    )

    view = triage_smt_goal(
        smtlib="(set-logic QF_FP)\n(check-sat)\n",
        case_id="float32_trap",
    )
    assert view["action"] == "run_solver"
    assert view["skips_solver"] is False
    assert view["verified"] is False
    assert view["trap_family"] is True
    assert called == []
    assert last_smt_triage()["hint_only"] is True


def test_smt_triage_without_key_still_runs_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    from ipfs_datasets_py.logic.integrations.typesafe_advisor import triage_smt_goal

    view = triage_smt_goal(smtlib="(assert true)\n(check-sat)\n", case_id="easy")
    assert view["action"] == "run_solver"
    assert view["skips_solver"] is False
    assert view["verified"] is False
