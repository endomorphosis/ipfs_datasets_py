from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
    classify_logic_family,
    last_conversion_verify,
    last_formula_lint,
    last_formula_rank,
    last_logic_family,
    last_logic_route,
    route_logic_hierarchy,
    lint_formula_against_clause,
    observe_formula_clause_lint,
    rank_allowlisted_formulas,
    typesafe_permitted,
    verify_conversion_fields,
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


def test_cross_view_lint_cannot_satisfy_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_advisor.typesafe_permitted",
        lambda **_kwargs: True,
    )

    class _Result:
        nouls = {"same_actors": SimpleNamespace(noul=0.99, confidence=0.99)}

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
    from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
        last_cross_view_lint,
        lint_cross_view_formulas,
    )

    view = lint_cross_view_formulas(
        dcec_formulas=["forall t (A -> O(Pay))"],
        tdfol_formulas=["forall t (A -> O(Pay,t))"],
    )
    assert view["same_actors"] == pytest.approx(0.99)
    assert view["satisfies_parity"] is False
    assert view["accepted_as_authority"] is False
    assert last_cross_view_lint()["satisfies_parity"] is False


def test_cross_view_lint_without_key_does_not_satisfy_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
        lint_cross_view_formulas,
    )

    view = lint_cross_view_formulas(
        dcec_formulas=["forall t (A -> O(Pay))"],
        tdfol_formulas=["forall t (A -> F(Pay,t))"],
    )
    assert view["satisfies_parity"] is False
    assert view["rewrites_ir"] is False


def test_intent_route_typecheck_not_skipped_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    from ipfs_datasets_py.logic.intent_ir.formalize.typed_compiler import (
        route_intent_view,
    )

    receipt = route_intent_view(
        "facts",
        formulas=({"formula_id": "f1", "expression": "P(x)"},),
        source_kind="declaration",
    )
    assert receipt.parse_typecheck is not None
    assert receipt.parse_typecheck.typechecked is True
    assert receipt.is_proof is False


def test_ui_and_security_view_lints_fail_open_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    ui = observe_formula_clause_lint("confirm(pay)", "O(confirm(pay))", view_id="ui_ux")
    sec = observe_formula_clause_lint("sec-sample", "formula:state:s1", view_id="security_ir")
    assert ui["rewrites_ir"] is False
    assert ui["drops_formula"] is False
    assert sec["accepted_as_authority"] is False
    assert sec["view_id"] == "security_ir"


def test_verify_conversion_fields_fail_open_does_not_escalate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    view = verify_conversion_fields(
        "All humans are mortal",
        "∀x.(Human(x) → Mortal(x))",
        parts={"pred_0": "Human"},
    )
    assert view["escalate"] is False
    assert view["drops_formula"] is False
    assert view["rewrites_ir"] is False
    assert last_conversion_verify()["escalate"] is False


def test_verify_any_flag_escalates_without_dropping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_advisor.typesafe_permitted",
        lambda **_kwargs: True,
    )

    class _Result:
        nouls = {
            "formula::hallucinated": SimpleNamespace(noul=0.95),
            "formula::off_target": SimpleNamespace(noul=0.2),
            "formula::incomplete": SimpleNamespace(noul=0.1),
            "pred_0::hallucinated": SimpleNamespace(noul=0.1),
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
    view = verify_conversion_fields(
        "All humans are mortal",
        "∀x.(Cat(x) → Mortal(x))",
        parts={"pred_0": "Cat"},
    )
    assert view["escalate"] is True
    assert view["drops_formula"] is False
    assert view["flags"]["formula::hallucinated"] == pytest.approx(0.95)


def test_classify_logic_family_fail_open_keeps_converter_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    view = classify_logic_family("All humans are mortal", produced_view="fol")
    assert view["family"] == "first_order"
    assert view["specificity"] == "group"
    assert view["rewrites_ir"] is False
    assert last_logic_family()["family"] == "first_order"


def test_classify_logic_family_low_confidence_coarsens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_advisor.typesafe_permitted",
        lambda **_kwargs: True,
    )

    class _Result:
        choices = {
            "family": SimpleNamespace(choice="program", confidence=0.2),
        }

    class _Choice:
        def __init__(self, instructions=None, criteria=None) -> None:
            self.instructions = instructions
            self.criteria = criteria

    import sys
    import types as _types

    parent = sys.modules.get("ipfs_accelerate_py")
    if parent is None:
        parent = _types.ModuleType("ipfs_accelerate_py")
        monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", parent)
    stub = _types.ModuleType("ipfs_accelerate_py.typesafe_inference")
    stub.Choice = _Choice
    stub.system_one = lambda *_a, **_k: _Result()
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.typesafe_inference", stub)
    view = classify_logic_family("shall pay rent", produced_view="deontic")
    assert view["specificity"] == "family"
    assert view["family"] == "deontic"
    assert view["rewrites_ir"] is False


def test_route_logic_hierarchy_fail_open_does_not_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    view = route_logic_hierarchy("All humans are mortal", produced_view="fol")
    assert view["switches_converter"] is False
    assert view["rewrites_ir"] is False
    assert view["leaf"] == "first_order"
    assert view["path"] == ["first_order"]
    assert last_logic_route()["switches_converter"] is False


def test_route_logic_hierarchy_greedy_child_when_confident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_advisor.typesafe_permitted",
        lambda **_kwargs: True,
    )

    class _Choice:
        def __init__(self, instructions=None, criteria=None) -> None:
            self.instructions = instructions
            self.criteria = criteria

    def fake_system_one(_state, questions, **_kwargs):
        if "family" in questions:
            return SimpleNamespace(
                choices={"family": SimpleNamespace(choice="deontic", confidence=0.95)}
            )
        return SimpleNamespace(
            choices={"child": SimpleNamespace(choice="obligation", confidence=0.96)}
        )

    import sys
    import types as _types

    parent = sys.modules.get("ipfs_accelerate_py")
    if parent is None:
        parent = _types.ModuleType("ipfs_accelerate_py")
        monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", parent)
    stub = _types.ModuleType("ipfs_accelerate_py.typesafe_inference")
    stub.Choice = _Choice
    stub.system_one = fake_system_one
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.typesafe_inference", stub)
    view = route_logic_hierarchy("The tenant shall pay rent", produced_view="deontic")
    assert view["path"] == ["deontic", "obligation"]
    assert view["leaf"] == "obligation"
    assert view["switches_converter"] is False
    assert view["rewrites_ir"] is False


def test_leanstral_draft_verify_fail_open_does_not_admit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
        observe_conversion_verify,
    )

    view = observe_conversion_verify(
        "The agency shall provide notice.",
        "obligation(agency, provide_notice)",
        view_id="leanstral_draft",
    )
    assert view["escalate"] is False
    assert view["drops_formula"] is False
    assert view["accepted_as_authority"] is False
    assert view["view_id"] == "leanstral_draft"


def test_intent_decompiler_verify_fail_open_does_not_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
        observe_conversion_verify,
    )

    view = observe_conversion_verify(
        "decl-1",
        "formula:goal:g1",
        parts={"goals": "g1", "modalities": "intended", "guards": ""},
        view_id="intent_decompiler",
    )
    assert view["rewrites_ir"] is False
    assert view["drops_formula"] is False
    assert view["accepted_as_authority"] is False
    assert view["view_id"] == "intent_decompiler"


def test_modal_decompiler_verify_fail_open_does_not_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
        observe_conversion_verify,
    )

    view = observe_conversion_verify(
        "The agency shall provide notice.",
        "O[deontic:std](provide_notice(agency))",
        view_id="modal_decompiler",
    )
    assert view["rewrites_ir"] is False
    assert view["drops_formula"] is False
    assert view["accepted_as_authority"] is False
    assert view["view_id"] == "modal_decompiler"


def test_suggest_declared_action_fail_open_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
        last_declared_action,
        suggest_declared_action,
    )

    view = suggest_declared_action(
        "reconstruction loss is high",
        allowed_actions=(
            "refine_decompiler_template",
            "refine_modal_registry_rule",
        ),
        allowed_paths=("ipfs_datasets_py/logic/modal/decompiler.py",),
    )
    assert view["action"] == ""
    assert view["invents_action"] is False
    assert view["invents_path"] is False
    assert last_declared_action()["action"] == ""


def test_suggest_declared_action_drops_unknown_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_advisor.typesafe_permitted",
        lambda **_kwargs: True,
    )

    class _Choice:
        def __init__(self, instructions=None, criteria=None) -> None:
            self.instructions = instructions
            self.criteria = criteria

    class _Result:
        choices = {
            "action": SimpleNamespace(choice="delete_locks", confidence=0.99),
        }

    import sys
    import types as _types

    parent = sys.modules.get("ipfs_accelerate_py")
    if parent is None:
        parent = _types.ModuleType("ipfs_accelerate_py")
        monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", parent)
    stub = _types.ModuleType("ipfs_accelerate_py.typesafe_inference")
    stub.Choice = _Choice
    stub.system_one = lambda *_a, **_k: _Result()
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.typesafe_inference", stub)
    from ipfs_datasets_py.logic.integrations.typesafe_advisor import (
        suggest_declared_action,
    )

    view = suggest_declared_action(
        "reconstruction loss is high",
        allowed_actions=("refine_decompiler_template",),
    )
    assert view["action"] == ""
    assert view["invents_action"] is False
