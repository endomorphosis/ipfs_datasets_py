"""Pure receiving-response controls for coverage and replay accounting.

These deliberately small protocol fixtures do not instantiate a model,
perform inference, open an owner, fit weights or substitute host resources.
"""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_inventory_scan as scanner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_feature_worker as worker


def protocol_fixture(optimized):
    projections = ["codebase_ir.contracts@1", "codebase_ir.program@1"]
    saved = {"feature_space": {"projection_ids": projections,
                             "columns": [[name, "fixture-atom"] for name in projections]},
             "state": {"contract_sha256": "a" * 64, "latent_width": 1}}
    entries, shards = [], []
    for index in range(2):
        source = str(index + 1) * 64
        coverage = [{"projection_id": name, "known_atoms": 1, "unknown_atoms": 0}
                    for name in projections]
        row = {"source_digest": source, "latent": [.25],
               "reconstructed_projection_features": {name: [.5] for name in projections}}
        entries.append({"source_digest": source, "coverage": deepcopy(coverage), "inference": None})
        inference = {"schema": "native-projection-feature-inference/v1",
            "contract_sha256": saved["state"]["contract_sha256"],
            "state_sha256": features.digest(saved["state"]),
            "feature_space_sha256": features.digest(saved["feature_space"]),
            "rows": [row], "coverage": coverage,
            "training_executed": False, "decoded_formulas_generated": False,
            "representation": "native_compiler_structural_features_not_semantic_text_embeddings",
            **features.FALSE}
        shards.append({"shard_index": index, "inference": inference})
    # Two shards distinguish one optimized preparation from two reference
    # preparations, while every target still reports one full native replay.
    preparations = 1 if optimized else 2
    counters = {
        "shared_inventory_validations": 1, "target_restorations": 2, "native_target_replays": 2,
        "matrix_builds": 2, "vocabulary_builds": preparations,
        "weight_tensor_builds": preparations * 4, "input_tensor_builds": 2,
        "contract_validations": preparations, "state_validations": preparations,
        "rows": 2, "shards": 2,
        "replay_shared_replay_preparations": 1 if optimized else 0,
        "replay_target_replay_attempts": 2, "replay_target_replays": 2,
        "replay_source_digest_checks": 2, "replay_ast_digest_checks": 2,
        "replay_authored_contract_replays": 2, "replay_native_lowering_replays": 2,
        "replay_full_target_comparisons": 2,
        "replay_shared_manifest_parses_avoided": 2 if optimized else 0,
        "replay_shared_receipt_parses_avoided": 2 if optimized else 0,
    }
    response = {"schema": worker.SCHEMA, "optimized": optimized, "shards": shards,
        "metrics": {"counters": counters, "stage_seconds": {"native_target_replay": .01},
                    "elapsed_seconds": .02,
                    "time_scope": "execute_before_final_protocol_serialization_and_write"},
        "worker": {"python": "fixture", "torch": "fixture", "device": "cpu", "dtype": "float64",
            "cpu_threads": 1, "repository_code_executed": False, "registry_opened": False,
            "training_executed": False, "proof_authority": False, "decoded_formulas_generated": False}}
    return response, entries, [[0], [1]], saved


@pytest.mark.parametrize("optimized", [True, False])
def test_valid_two_shard_response_preserves_bound_rows_and_receipts(optimized):
    response, entries, shard_entries, saved = protocol_fixture(optimized)
    receipts = scanner._accept_response(response, entries, shard_entries, saved, optimized)
    assert [receipt["shard_index"] for receipt in receipts] == [0, 1]
    assert [receipt["target_source_digests"] for receipt in receipts] == [["1" * 64], ["2" * 64]]
    for entry, shard, receipt in zip(entries, response["shards"], receipts):
        assert entry["inference"] == shard["inference"]["rows"][0]
        assert receipt["inference_sha256"] == features.digest(shard["inference"])


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("field,bad_value", [
    ("known_atoms", True), ("known_atoms", 1.0),
    ("unknown_atoms", False), ("unknown_atoms", 0.0),
])
def test_coverage_rejects_boolean_and_float_integer_aliases(optimized, field, bad_value):
    response, entries, shard_entries, saved = protocol_fixture(optimized)
    original = deepcopy(response)
    response["shards"][0]["inference"]["coverage"][0][field] = bad_value
    # Establish that ordinary equality would overlook the corrupt type.
    assert response["shards"][0]["inference"]["coverage"] == original["shards"][0]["inference"]["coverage"]
    with pytest.raises(scanner.CodebaseInventoryScanError, match="coverage"):
        scanner._accept_response(response, entries, shard_entries, saved, optimized)
    assert entries[0]["inference"] is None


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("mutation", ["count", "projection", "missing", "extra", "ordering"])
def test_coverage_rejects_changed_counts_membership_and_order(optimized, mutation):
    response, entries, shard_entries, saved = protocol_fixture(optimized)
    coverage = response["shards"][0]["inference"]["coverage"]
    if mutation == "count":
        coverage[0]["known_atoms"] = 2
    elif mutation == "projection":
        coverage[0]["projection_id"] = "foreign.projection@1"
    elif mutation == "missing":
        del coverage[0]["unknown_atoms"]
    elif mutation == "extra":
        coverage[0]["proof_authority"] = False
    else:
        coverage.reverse()
    with pytest.raises(scanner.CodebaseInventoryScanError, match="coverage"):
        scanner._accept_response(response, entries, shard_entries, saved, optimized)


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("counter", [
    "rows", "replay_shared_replay_preparations", "replay_target_replays",
    "replay_full_target_comparisons", "replay_shared_manifest_parses_avoided",
    "replay_shared_receipt_parses_avoided",
])
@pytest.mark.parametrize("numeric_alias", ["bool", "float"])
def test_replay_accounting_requires_exact_integer_types(optimized, counter, numeric_alias):
    response, entries, shard_entries, saved = protocol_fixture(optimized)
    original = response["metrics"]["counters"][counter]
    response["metrics"]["counters"][counter] = bool(original) if numeric_alias == "bool" else float(original)
    with pytest.raises(scanner.CodebaseInventoryScanError, match="accounting"):
        scanner._accept_response(response, entries, shard_entries, saved, optimized)


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("mutation", ["missing", "extra", "lowering_skipped", "false_reuse"])
def test_replay_accounting_rejects_incomplete_or_incorrect_work(optimized, mutation):
    response, entries, shard_entries, saved = protocol_fixture(optimized)
    counters = response["metrics"]["counters"]
    if mutation == "missing":
        del counters["replay_full_target_comparisons"]
    elif mutation == "extra":
        counters["replay_semantics_proved"] = 0
    elif mutation == "lowering_skipped":
        counters["replay_native_lowering_replays"] = 0
    else:
        counters["replay_shared_manifest_parses_avoided"] = 0 if optimized else 2
    with pytest.raises(scanner.CodebaseInventoryScanError, match="accounting"):
        scanner._accept_response(response, entries, shard_entries, saved, optimized)
