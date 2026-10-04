"""Semantic profile checks must precede every portfolio process attempt."""
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.hammers import semantic_routing as routing


def target(text="p -> q", solvers=("z3", "cvc5", "vampire", "e")):
    parsed = routing.modal.parse_modal(text, routing.modal.profile_k())
    replay = routing.modal.parse_modal(parsed.printed, routing.modal.profile_k())
    return dict(request_id="test", source_construct="exact-projection", logic_family="propositional",
        ast_format="shared_logic", printed=parsed.printed, native_ast=replay.root.to_dict(), solver_names=solvers)


def test_routes_intersect_registry_fragment_operation_and_real_translation():
    attempts, receipt = routing.prepare_family_portfolio(**target())
    assert [item.solver_name for item in attempts] == ["z3", "cvc5", "vampire", "e"]
    routes = receipt["routes"]
    assert [row["operation"] for row in routes] == ["check_satisfiability"] * 2 + ["prove"] * 2
    assert all("(assert (=> p q))" in row.translation.translated_text for row in attempts[:2])
    assert all("conjecture" in row.translation.translated_text for row in attempts[2:])
    assert all("propositional" in row["declared_support"]["fragment_ids"] for row in routes)
    assert all(row["declared_support"]["support_level"] == "native" for row in routes)
    assert receipt["cross_operation_vote_permitted"] is False
    assert not receipt["qualified"] and not receipt["source_semantics_verified"]


@pytest.mark.parametrize("family", ["first_order", "fol", "dfol", "deontic", "temporal", "tfol", "tdfol",
    "modal", "cec", "dcec", "frame_logic", "transition_system", "tla_plus", "separation", "unknown"])
def test_declared_family_never_becomes_propositional_by_printing_atoms(family, monkeypatch):
    data = target()
    data["logic_family"] = family
    monkeypatch.setattr(routing.policy, "solver_spec", lambda *_: pytest.fail("solver policy reached before family gate"))
    with pytest.raises(ValueError, match="no faithful lowering"):
        routing.prepare_family_portfolio(**data)


@pytest.mark.parametrize("kind", ["extension", "forall", "exists", "equality", "obligation", "always",
    "event", "knowledge", "frame_slot"])
def test_operator_cannot_be_disguised_with_propositional_family_label(kind, monkeypatch):
    data = target()
    data["native_ast"]["kind"] = kind
    monkeypatch.setattr(routing.policy, "solver_spec", lambda *_: pytest.fail("solver policy reached before AST gate"))
    with pytest.raises(ValueError, match="unsupported native propositional operator"):
        routing.prepare_family_portfolio(**data)


def test_native_modal_formula_rejected_even_if_declared_propositional():
    with pytest.raises(ValueError, match="unsupported native propositional operator"):
        routing.prepare_family_portfolio(**target("box p"))


def test_exact_ast_replay_must_match():
    data = target()
    data["native_ast"]["arguments"][0]["symbol"] = "other"
    with pytest.raises(ValueError, match="AST differs"):
        routing.prepare_family_portfolio(**data)


def test_registry_declarations_are_necessary_not_execution_authority(monkeypatch):
    original = routing.providers.BASELINE_PROVIDER_CATALOG
    entry = original.get("z3")
    changed = replace(entry, family_support=tuple(s for s in entry.family_support if s.family_id != "propositional"))
    replacement = routing.providers.ProviderCapabilityCatalog((changed,), frozen=True)
    monkeypatch.setattr(routing.providers, "BASELINE_PROVIDER_CATALOG", replacement)
    with pytest.raises(ValueError, match="capability"):
        routing.prepare_family_portfolio(**target(solvers=("z3",)))


def test_catalog_dcec_claim_does_not_authorize_unimplemented_lowering():
    assert any(s.family_id == "dcec" for s in routing.providers.BASELINE_PROVIDER_CATALOG.get("vampire").family_support)
    data = target(solvers=("vampire",))
    data["logic_family"] = "dcec"
    with pytest.raises(ValueError, match="no faithful lowering"):
        routing.prepare_family_portfolio(**data)


def test_execution_replays_receipt_before_constructing_raw_portfolio(monkeypatch):
    data = target(solvers=("z3",))
    _, receipt = routing.prepare_family_portfolio(**data)
    altered = deepcopy(receipt)
    altered["routes"][0]["operation"] = "prove"
    monkeypatch.setattr(routing.portfolio, "SolverPortfolio", lambda *a, **k: pytest.fail("raw transport reached"))
    with pytest.raises(ValueError, match="routing changed"):
        routing.run_family_portfolio(expected_routing=altered, run_policy=object(), **data)


def test_mixed_operations_cannot_cancel_each_other(monkeypatch):
    data = target(solvers=("z3", "vampire"))
    _, receipt = routing.prepare_family_portfolio(**data)
    run_policy = routing.policy.PortfolioPolicy(cancel_on_first_conclusive=True)
    monkeypatch.setattr(routing.portfolio, "SolverPortfolio", lambda *a, **k: pytest.fail("raw transport reached"))
    with pytest.raises(ValueError, match="mixed solver operations"):
        routing.run_family_portfolio(expected_routing=receipt, run_policy=run_policy, **data)


def test_checked_run_builds_fresh_attempts_and_preserves_policy_scheduler(monkeypatch):
    data = target(solvers=("z3",))
    attempts, receipt = routing.prepare_family_portfolio(**data)
    attempts[0].translation.translated_text = "forged cached input"
    observed = []

    class FakePortfolio:
        def __init__(self, policy, **kwargs):
            observed.append((policy, kwargs))

        def run(self, request_id, attempts, **kwargs):
            observed.append((request_id, attempts))
            assert kwargs == {"parent_lease": None, "cancel_event": None}
            return "unchanged-result"

    monkeypatch.setattr(routing.portfolio, "SolverPortfolio", FakePortfolio)
    run_policy = routing.policy.PortfolioPolicy(cancel_on_first_conclusive=False)
    scheduler = object()
    result = routing.run_family_portfolio(expected_routing=receipt, run_policy=run_policy,
        resource_scheduler=scheduler, **data)
    assert result == "unchanged-result"
    assert observed[0][1]["resource_scheduler"] is scheduler
    assert "forged" not in observed[1][1][0].translation.translated_text


@pytest.mark.parametrize("field,value", [("solver_names", ("z3", "z3")), ("solver_names", ()),
    ("ast_format", "opaque"), ("printed", ""), ("request_id", ""), ("solver_names", (True,))])
def test_bad_contracts_fail_closed(field, value):
    data = target()
    data[field] = value
    with pytest.raises(ValueError):
        routing.prepare_family_portfolio(**data)


def test_ast_resource_bounds_fail_closed():
    data = target()
    node = data["native_ast"]
    for _ in range(70):
        node = {"kind": "not", "arguments": [node], "binders": []}
    data["native_ast"] = node
    with pytest.raises(ValueError, match="bounded binder-free"):
        routing.prepare_family_portfolio(**data)


def test_guard_refuses_source_changes(tmp_path, monkeypatch):
    source = tmp_path / "producer.py"
    source.write_text("changed")
    monkeypatch.setattr(routing, "_PINS", {str(source): "0" * 64})
    with pytest.raises(ValueError, match="producer changed"):
        routing.prepare_family_portfolio(**target())
