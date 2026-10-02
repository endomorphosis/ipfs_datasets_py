"""Audit development labels and split coordinates without opening test texts."""
from importlib.util import module_from_spec, spec_from_file_location
from itertools import product
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = spec_from_file_location("composition_panel", ROOT / "tests/fixtures/logic/intent_ui_source_compositions_v1/panel.py")
PANEL = module_from_spec(SPEC)
SPEC.loader.exec_module(PANEL)


def test_complete_compositions_excluded_without_claiming_disjoint_lexical_groups():
    groups = {s: set(PANEL.groups(s)) for s in ("train", "tuning", "test")}
    assert {s: len(v) for s, v in groups.items()} == {"train": 96, "tuning": 24, "test": 24}
    assert not groups["train"] & groups["tuning"]
    assert not groups["train"] & groups["test"]
    assert not groups["tuning"] & groups["test"]
    assert set.union(*groups.values()) == set(product(range(4), range(4), range(3), range(3)))
    for i, j, k in product(range(4), range(4), range(3)):
        assert sum((i, j, k, m) in groups["train"] for m in range(3)) == 2
    assert PANEL.metadata()["semantic_groups_disjoint"] is False


@pytest.mark.parametrize("domain", PANEL.DOMAINS)
def test_development_targets_closed_valid_and_vocabulary_from_training(domain):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.domain_384_fidelity import validate_native_target
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction

    training, tuning = PANEL.rows("train", domain), PANEL.rows("tuning", domain)
    assert len({row["id"] for row in training + tuning}) == 120
    assert len({row["source_text"] for row in training + tuning}) == 120
    for row in training + tuning:
        assert validate_native_target(domain, row["target"])["canonical_ir"] == row["target"]
        if domain == "intent_ir":
            assert parse_instruction(row["source_text"]) == row["target"]["document"]
    for path in PANEL.critical_paths(domain):
        assert {r["target"][path[0]][path[1]] for r in tuning} <= {
            r["target"][path[0]][path[1]] for r in training}


def test_unknown_split_and_domain_refuse():
    with pytest.raises(ValueError):
        PANEL.groups("canary")
    with pytest.raises(ValueError):
        PANEL.rows("train", "legal_ir")
    with pytest.raises(ValueError):
        PANEL.critical_paths("security_ir")
