"""Source-form coverage, exact weak labels, and partition quarantine."""
from collections import Counter
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import coverage_curriculum as curriculum
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar
from ipfs_datasets_py.logic.intent_ir.formalize.rich_decoder import sha


def row(identity, text, split="train"):
    return {"id": identity, "instruction": text, "split": split,
            "ast": grammar.parse_instruction(text), "provenance": {"kind": "test_fixture"}}


def parent(rows=()):
    return {"schema": "intent-rich-continuation-corpus/v1", "samples": list(rows),
            "retained_metadata": {"unchanged": [True]}}


@pytest.fixture(scope="module")
def generated():
    return curriculum.build_coverage_curriculum(parent(), groups_per_split={"train": 8, "validation": 8, "test": 8})


def test_all_missing_shapes_and_verbs_have_train_support_with_exact_roundtrip(generated):
    train = [r for r in generated["samples"] if r["split"] == "train"]
    assert len(train) == 8 * 7 * 9
    assert {r["ast"]["action"] for r in train} == {"save", "view", "use", "reuse", "run", "create", "fetch"}
    assert {r["provenance"]["object_shape"] for r in train} == set(curriculum.OBJECT_SHAPES)
    for sample in train:
        ast = sample["ast"]
        assert grammar.parse_instruction(sample["instruction"]) == ast
        assert grammar.parse_instruction(grammar.ast_to_text(ast), normalized_inverse=True) == ast
        assert grammar.sequence_to_ast(grammar.ast_to_sequence(ast)) == ast
        assert sample["provenance"]["source_sha256"] == sha(sample["instruction"].encode())
        assert not sample["provenance"]["semantic_gold"]
        assert not sample["provenance"]["model_predictions_used"]
    objects = {r["ast"]["object"] for r in train}
    assert any(len(text.split()) >= 8 for text in objects)
    assert any(text.startswith(".cfg ") for text in objects)
    assert any("3-7x" in text for text in objects)
    assert "`orbit digest` for local disk diagnostics" in objects
    assert "API Receipt metrics under local storage" in objects
    sources = {r["instruction"] for r in train}
    assert "Run the local archive." in sources
    assert "Do not reuse the local archive." in sources
    assert "Fetch the local archive." in sources


def test_original_rows_are_untouched_and_compound_rehearsal_survives():
    original = parent([row("old", "agent must inspect cache and operator may save report."),
                       row("test", "Create the ReservedCapsule.", "test")])
    snapshot = deepcopy(original)
    result = curriculum.build_coverage_curriculum(original)
    assert original == snapshot
    assert result["samples"][:2] == original["samples"]
    assert result["samples"][0]["ast"]["kind"] == "and"
    result["samples"][0]["provenance"]["kind"] = "mutated_copy"
    assert original == snapshot


def test_all_new_source_families_and_semantic_aliases_remain_in_single_partition(generated):
    families, semantics, sources = {}, {}, {}
    for sample in generated["samples"]:
        for key, target in ((sample["provenance"]["source_family_id"], families),
                            (grammar.ast_to_sequence(sample["ast"]), semantics),
                            (curriculum._source_identity(sample["instruction"]), sources)):
            assert target.setdefault(key, sample["split"]) == sample["split"]
    assert generated["source_form_coverage"]["omitted"] == []


def test_heldout_compound_leaf_and_explicit_exclusion_quarantine_wording_aliases():
    original = parent([row("heldout", "unspecified intends to save local archive and operator may inspect parcel.", "test")])
    result = curriculum.build_coverage_curriculum(original, forbidden_sources=["Do not reuse the local archive."])
    train = [r for r in result["samples"] if r["split"] == "train"]
    forbidden = {grammar.ast_to_sequence(grammar.parse_instruction("Save local archive.")),
                 grammar.ast_to_sequence(grammar.parse_instruction("Never reuse local archive."))}
    assert not any(grammar.ast_to_sequence(r["ast"]) in forbidden for r in train)
    assert any(r["instruction"] == "Must save the local archive." for r in train)
    assert result["samples"][0] == original["samples"][0]
    reasons = {reason for row_ in result["source_form_coverage"]["omitted"] for reason in row_["reasons"]}
    assert "cross_partition_source_or_semantic_alias" in reasons
    assert "explicit_source_or_semantic_exclusion" in reasons


def test_existing_cross_split_aliases_are_quarantined_from_fit_and_tuning():
    corpus = parent([row("train", "Fetch the capsule."),
                     row("val", "unspecified intends to fetch capsule.", "validation"),
                     row("test", "Fetch capsule.", "test"),
                     row("clean", "Run local diagnostics.")])
    result = curriculum.prepare_coverage_training_data(corpus)
    assert result["selected_row_ids"] == {"train": ["clean"], "validation": []}
    assert {r["id"] for r in result["quarantined"]} == {"train", "val"}
    assert all("capsule" not in pair["source"] for pair in result["pairs"]["train"])
    assert result["family_targets_status"] == "explicit_builder_required"
    assert not result["test_used_for_fit_or_tuning"]


def test_projection_hook_is_source_bound_separate_from_neural_pairs_and_excludes_test():
    calls = []
    def project(domain, *, document, source_text):
        calls.append((domain, document, source_text))
        return {"source_sha256": sha(source_text.encode()), "projections": [], "family_inventory": []}
    result = curriculum.prepare_coverage_training_data(parent([
        row("train", "Run local diagnostics."), row("val", "View validation bundle.", "validation"),
        row("test", "Fetch reserved capsule.", "test")]), family_target_builder=project)
    assert [item[0] for item in calls] == ["intent_ir", "intent_ir"]
    assert all("reserved" not in item[2] for item in calls)
    assert len(result["family_targets"]) == 2
    assert not result["family_targets_are_neural_directions"]
    assert {pair["direction"] for pair in result["pairs"]["train"]} == {"encode", "decode"}
    with pytest.raises(ValueError, match="source-bound"):
        curriculum.prepare_coverage_training_data(parent([row("train", "Run diagnostics.")]),
            family_target_builder=lambda *a, **k: {"source_sha256": "0" * 64, "projections": [], "family_inventory": []})


def test_fixed_selection_never_uses_training_or_predictions_and_covers_shapes(generated):
    first = curriculum.freeze_coverage_holdouts(generated)
    second = curriculum.freeze_coverage_holdouts(deepcopy(generated))
    assert first == second
    assert len(first["rows"]) == 2 * 8 * 7
    assert Counter(r["split"] for r in first["rows"]) == {"validation": 56, "test": 56}
    assert {r["provenance"]["object_shape"] for r in first["rows"]} == set(curriculum.OBJECT_SHAPES)
    assert not first["model_predictions_consulted"]
    assert not first["prior_development_sets_reused"]
    assert len({r["id"] for r in first["rows"]}) == len(first["rows"])


@pytest.mark.parametrize("defect", ["duplicate_id", "wrong_label", "unknown_split", "cross_partition_family"])
def test_invalid_source_contracts_rejected_without_modification(defect):
    original = parent([row("one", "Run diagnostics.")])
    if defect == "duplicate_id":
        original["samples"].append(deepcopy(original["samples"][0]))
    elif defect == "wrong_label":
        original["samples"][0]["ast"]["modality"] = "required"
    elif defect == "unknown_split":
        original["samples"][0]["split"] = "unknown"
    else:
        original["samples"][0]["provenance"]["source_family_id"] = "same"
        other = row("two", "View packages.", "test")
        other["provenance"]["source_family_id"] = "same"
        original["samples"].append(other)
    snapshot = deepcopy(original)
    with pytest.raises(ValueError):
        curriculum.build_coverage_curriculum(original)
    assert original == snapshot
