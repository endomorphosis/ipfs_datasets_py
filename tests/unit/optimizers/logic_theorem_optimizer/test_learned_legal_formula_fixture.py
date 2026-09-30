"""Audit the authored fixture independently of any compiler or learned decoder."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

import pytest

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR


FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/legal_formula_learning/v1.json"
PARTITIONS = ("train", "tuning", "heldout", "regression")


@pytest.fixture(scope="module")
def corpus():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _tokens(text):
    return set(re.findall(r"\w+|[^\w\s]", text.casefold()))


def _atoms(example):
    atoms = set()
    for rule in example["canonical_ir"]["rules"]:
        for value in rule.values():
            atoms.update(value if isinstance(value, list) else [value])
    return atoms


def test_fixture_is_authored_and_confers_no_authority(corpus):
    assert corpus["schema"] == "source-conditioned-legal-formula-fixture/v1"
    assert corpus["provenance"] == "authored_synthetic_not_legal_authority"
    assert corpus["inference_input_fields"] == ["source_text"]
    assert corpus["authority"] and all(value is False for value in corpus["authority"].values())
    assert corpus["partition_policy"]["heldout_for_optimizer_selection"] is False
    assert {name: len(corpus[name]) for name in PARTITIONS} == {
        "train": 72, "tuning": 12, "heldout": 12, "regression": 3,
    }


def test_targets_conform_to_canonical_contract_without_compilation(corpus):
    for partition in PARTITIONS:
        for example in corpus[partition]:
            assert set(example) == {"id", "source_text", "canonical_ir"}
            assert len(re.findall(r"\w+|[^\w\s]", example["source_text"])) <= 64
            ir = CanonicalRoundTripIR.from_dict(example["canonical_ir"])
            assert ir.to_dict() == example["canonical_ir"]
            assert len(ir.rules) == 1
            rule = ir.rules[0]
            assert len(rule.conditions) + len(rule.exceptions) + len(rule.temporal) <= 4


def test_partitions_have_no_source_or_complete_target_leakage(corpus):
    seen_ids, seen_sources, seen_targets = set(), set(), set()
    for partition in PARTITIONS:
        for example in corpus[partition]:
            source = " ".join(example["source_text"].casefold().split())
            source_hash, target_hash = _digest(source), _digest(example["canonical_ir"])
            assert example["id"] not in seen_ids
            assert source_hash not in seen_sources
            assert target_hash not in seen_targets
            seen_ids.add(example["id"])
            seen_sources.add(source_hash)
            seen_targets.add(target_hash)


def test_tuning_and_heldout_use_only_training_words_and_atoms(corpus):
    words = set().union(*(_tokens(row["source_text"]) for row in corpus["train"]))
    atoms = set().union(*(_atoms(row) for row in corpus["train"]))
    for partition in ("tuning", "heldout"):
        for row in corpus[partition]:
            assert _tokens(row["source_text"]) <= words
            assert _atoms(row) <= atoms
    # Multiword atoms deliberately test exact preservation by the new codec.
    assert {"Company A", "backup report", "within 10 days", "at least 20 days"} <= atoms
    for probe in corpus["oov_probes"]:
        assert probe["unseen_atom"] not in atoms
        assert not _tokens(probe["source_text"]) <= words
        assert probe["expected"] == "abstain_or_explicit_unsupported"


def test_heldout_contains_polarity_minimal_pairs_and_composed_qualifiers(corpus):
    pairs = defaultdict(set)
    temporal_kinds, combined = set(), set()
    for row in corpus["heldout"]:
        rule = row["canonical_ir"]["rules"][0]
        pair_key = _digest({key: value for key, value in rule.items() if key != "modality"})
        pairs[pair_key].add(rule["modality"])
        records = corpus["oracle_temporal_records"][row["id"]]
        for record in records:
            temporal_kinds.add(record["temporal_kind"])
            if rule["exceptions"]:
                combined.add(record["temporal_kind"])
    assert sum(values == {"O", "F", "P"} for values in pairs.values()) == 3
    assert temporal_kinds == combined == {"within_duration", "minimum_duration"}


def test_timing_oracle_retains_kind_and_quantity_without_admission(corpus):
    for partition in PARTITIONS:
        for row in corpus[partition]:
            rule = row["canonical_ir"]["rules"][0]
            records = corpus["oracle_temporal_records"][row["id"]]
            if not rule["temporal"]:
                assert records == []
            elif rule["temporal"] == ["within 10 days"]:
                assert records == [{"temporal_kind": "within_duration", "value": "10 days", "quantity": 10}]
            elif rule["temporal"] == ["at least 20 days"]:
                assert records == [{"temporal_kind": "minimum_duration", "value": "20 days", "quantity": 20}]
            else:
                pytest.fail("fixture introduced an unaudited temporal atom")


def test_familiar_gates_do_not_count_as_heldout(corpus):
    assert {row["source_text"] for row in corpus["regression"]} == {
        "Company A shall submit backup report within 10 days unless emergency.",
        "The agency shall not disclose records.",
        "The officer shall retain the file for at least 20 days.",
    }


def test_ablation_plan_requires_real_source_dependence_and_no_fallback(corpus):
    assert set(corpus["ablation_protocol"]) == {
        "same_init_untrained", "trained", "zeroed_decoder", "source_permutation",
        "target_poison", "compiler_disabled", "no_target_copy", "loss_reporting", "safety",
    }
