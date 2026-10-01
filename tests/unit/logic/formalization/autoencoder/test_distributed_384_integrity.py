"""Independent inventory, finite-statistic and immutable-file regressions."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import os
from pathlib import Path

import numpy as np
import pytest

from .test_structured_source_384 import parent, rows
from .test_distributed_384_numerics import grouped
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as reference
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import contracts as c
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import numerics as n


@pytest.fixture(scope="module")
def integrity_data(parent, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("distributed-integrity")
    train, tune = grouped("security_ir", "train"), grouped("security_ir", "validation")
    base = reference.train("security_ir", rows("security_ir", "train"), rows("security_ir", "validation"),
                           parent_projection=parent)["checkpoint"]
    path = c.write_json(tmp_path / "base.json", base)
    plan = n.make_plan(path, train, tune, source_descriptor={"schema": "ir384-corpus-source/v1",
        "description": "Authored integrity fixtures; synthetic source vectors"}, shard_size=2, machine_count=2)
    updates = [n.compute_update(plan, base, n.shard_rows(plan, train, shard["shard_id"]), shard["shard_id"])
               for shard in plan["shards"]]
    return train, tune, base, plan, updates


def reidentify(plan, *, recipe=False):
    if recipe:
        plan["recipe_sha256"] = c.digest(plan["recipe"])
    plan["plan_id"] = c.digest({k: v for k, v in plan.items() if k != "plan_id"})
    return plan


@pytest.mark.parametrize("mutation", [
    "dataset_digest", "empty_ridges", "boolean_ridge", "unordered_ridges", "dimension",
    "projection_unfrozen", "vocabulary_unfrozen", "pretend_history", "misleading_parent_role",
    "invented_family", "invented_inventory", "manifest_mismatch", "group_leakage", "embedding_leakage",
    "duplicate_rows", "split_group", "unsafe_shard_id", "unknown_field", "invalid_source_commit",
])
def test_self_rehashed_inconsistent_plans_fail_before_dispatch(integrity_data, mutation):
    _, _, _, plan, _ = deepcopy(integrity_data)
    if mutation == "dataset_digest": plan["dataset_sha256"] = "b" * 64
    elif mutation == "empty_ridges": plan["recipe"]["ridges"] = []
    elif mutation == "boolean_ridge": plan["recipe"]["ridges"] = [True]
    elif mutation == "unordered_ridges": plan["recipe"]["ridges"] = [.1, .01]
    elif mutation == "dimension": plan["recipe"]["input_dimension"] = True
    elif mutation == "projection_unfrozen": plan["recipe"]["projection_frozen"] = False
    elif mutation == "vocabulary_unfrozen": plan["recipe"]["vocabulary_frozen"] = False
    elif mutation == "pretend_history": plan["recipe"]["prior_training_statistics_recovered_from_weights"] = True
    elif mutation == "misleading_parent_role": plan["recipe"]["parent_head_role"] = "continues previous optimizer state"
    elif mutation == "invented_family": plan["recipe"]["required_families"] = ["not_an_installed_logic_family"]
    elif mutation == "invented_inventory": plan["recipe"]["native_family_ids"] = ["not_an_installed_logic_family"]
    elif mutation == "manifest_mismatch": plan["training_manifest"][0]["target_sha256"] = "a" * 64
    elif mutation == "group_leakage": plan["validation_bindings"][0]["group_id"] = plan["training_bindings"][0]["group_id"]
    elif mutation == "embedding_leakage":
        plan["validation_bindings"][0]["numeric_embedding_sha256"] = plan["training_bindings"][0]["numeric_embedding_sha256"]
    elif mutation == "duplicate_rows": plan["shards"][0]["row_ids"][1] = plan["shards"][0]["row_ids"][0]
    elif mutation == "split_group":
        a, b = plan["shards"][:2]
        a["row_ids"][0], b["row_ids"][0] = b["row_ids"][0], a["row_ids"][0]
    elif mutation == "unsafe_shard_id": plan["shards"][0]["shard_id"] = "../outside"
    elif mutation == "unknown_field": plan["claimed_qualification"] = True
    else:
        plan["dataset"]["source"]["huggingface"] = {"repository_id": "Publicus/example", "repo_type": "dataset", "revision": "main"}
        plan["dataset_sha256"] = c.digest(plan["dataset"])
    reidentify(plan, recipe=True)
    with pytest.raises(ValueError):
        n.validate_plan(plan)


def test_worker_rechecks_actual_ids_against_declared_shard(integrity_data):
    train, _, base, plan, _ = deepcopy(integrity_data)
    original_rows = n.shard_rows(plan, train, plan["shards"][0]["shard_id"])
    first, second = plan["shards"][:2]
    first["row_ids"], second["row_ids"] = second["row_ids"], first["row_ids"]
    reidentify(plan)
    n.validate_plan(plan)  # Whole groups remain a valid inventory; bytes contradict it.
    with pytest.raises(ValueError, match="row identities differ"):
        n.compute_update(plan, base, original_rows, first["shard_id"])


@pytest.mark.parametrize("binding", ["target_sha256", "group_id"])
def test_worker_rechecks_actual_manifest_and_group_bindings(integrity_data, binding):
    train, _, base, plan, _ = deepcopy(integrity_data)
    shard = plan["shards"][0]
    original_rows = n.shard_rows(plan, train, shard["shard_id"])
    for row in plan["training_bindings"]:
        if row["id"] in shard["row_ids"]:
            row[binding] = "f" * 64 if binding == "target_sha256" else "fabricated-group"
    if binding == "target_sha256":
        for row in plan["training_manifest"]:
            if row["id"] in shard["row_ids"]:
                row[binding] = "f" * 64
    reidentify(plan)
    n.validate_plan(plan)
    with pytest.raises(ValueError, match="worker rows differ"):
        n.compute_update(plan, base, original_rows, shard["shard_id"])


def test_worker_never_accepts_validation_labeled_rows(integrity_data):
    train, _, base, plan, _ = deepcopy(integrity_data)
    shard = plan["shards"][0]
    supplied = n.shard_rows(plan, train, shard["shard_id"])
    for row in supplied:
        row["split"] = "validation"
    shard["rows_sha256"] = c.digest(supplied)
    reidentify(plan)
    with pytest.raises(ValueError, match="expected train split"):
        n.compute_update(plan, base, supplied, shard["shard_id"])


@pytest.mark.parametrize("coordinate", ["0.125", True, None])
def test_self_rehashed_non_numeric_statistics_rejected(integrity_data, coordinate):
    _, _, base, plan, updates = deepcopy(integrity_data)
    update = updates[0]
    update["statistics"]["projected"][0][0] = coordinate
    update["update_id"] = c.digest({k: v for k, v in update.items() if k != "update_id"})
    with pytest.raises(ValueError, match="numerical projected"):
        n.validate_update(plan, base, update)


@pytest.mark.parametrize("offset", [1e4, 1e5])
def test_centered_factor_merge_retains_small_variance_with_large_offset(parent, tmp_path, offset):
    shifted_parent = deepcopy(parent)
    shifted_parent["model_state"]["projection_up.bias"] = [offset] * 384
    train, tune = grouped("security_ir", "train"), grouped("security_ir", "validation")
    base = reference.train("security_ir", rows("security_ir", "train"), rows("security_ir", "validation"),
                           parent_projection=shifted_parent)["checkpoint"]
    path = c.write_json(tmp_path / "offset-base.json", base)
    plan = n.make_plan(path, train, tune, source_descriptor={"schema": "ir384-corpus-source/v1",
        "description": "Numerical stress fixture with large finite projection bias"}, shard_size=2)
    updates = [n.compute_update(plan, base, n.shard_rows(plan, train, s["shard_id"]), s["shard_id"])
               for s in plan["shards"]]
    result = n.merge_updates(plan, base, updates, tune)
    fitted = result["checkpoint"]
    assert fitted["input_transform"]["scale"] == pytest.approx(base["input_transform"]["scale"], rel=1e-12)
    # Centering arithmetic can differ by a few ulps at a large offset; the fit
    # retains the same finite solution and validation decisions.
    np.testing.assert_allclose(fitted["head_state"]["weights"], base["head_state"]["weights"], atol=2e-7, rtol=2e-5)
    assert fitted["training"]["selected_validation"] == base["training"]["selected_validation"]
    assert result["report"]["remote_numerical_computation_proven"] is False
    assert fitted["training"]["centering"] == "two_pass_global_training_mean_then_add_centered_shard_statistics"


def test_json_and_file_reference_come_from_the_same_read(tmp_path, monkeypatch):
    path = c.write_json(tmp_path / "input.json", {"generation": 1})
    before = path.read_bytes()
    native_read = c._read_at
    calls = []
    def replace_after_snapshot(directory, name, maximum):
        data = native_read(directory, name, maximum)
        calls.append(name)
        path.write_bytes(c.raw({"generation": 2}))
        return data
    monkeypatch.setattr(c, "_read_at", replace_after_snapshot)
    value, reference = c.read_json_bound(path)
    assert value == {"generation": 1}
    assert reference == {"sha256": hashlib.sha256(before).hexdigest(), "bytes": len(before)}
    assert calls == ["input.json"]


def test_plan_base_json_and_file_hash_share_one_snapshot(integrity_data, tmp_path, monkeypatch):
    train, tune, base, _, _ = deepcopy(integrity_data)
    path = c.write_json(tmp_path / "base.json", base)
    original = path.read_bytes()
    native_read = c._read_at
    def replace_after_snapshot(directory, name, maximum):
        data = native_read(directory, name, maximum)
        if name == "base.json":
            path.write_bytes(b'{"changed_after_snapshot":true}')
        return data
    monkeypatch.setattr(c, "_read_at", replace_after_snapshot)
    plan = n.make_plan(path, train, tune, source_descriptor={"schema": "ir384-corpus-source/v1", "description": "read race fixture"})
    assert plan["base_json_sha256"] == c.digest(base)
    assert plan["base_checkpoint_sha256"] == hashlib.sha256(original).hexdigest()
    assert plan["base_checkpoint_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_rejects_changes_during_the_open_file_read(tmp_path, monkeypatch):
    path = c.write_json(tmp_path / "changing.json", {"value": 1})
    native_stat = os.fstat
    count = 0
    def change_after_stat(fd):
        nonlocal count
        result = native_stat(fd)
        count += 1
        if count == 1:
            path.write_bytes(b'{"value":999999}')
        return result
    monkeypatch.setattr(c.os, "fstat", change_after_stat)
    with pytest.raises(ValueError, match="changed during read"):
        c.read_json(path)


@pytest.mark.parametrize("kind", ["file_symlink", "parent_symlink", "fifo", "oversized"])
def test_bounded_reader_rejects_aliases_devices_and_oversized_files(tmp_path, kind):
    real = c.write_json(tmp_path / "real" / "file.json", {"value": 1})
    path, maximum = real, c.MAX_BYTES
    if kind == "file_symlink":
        path = tmp_path / "alias.json"
        path.symlink_to(real)
    elif kind == "parent_symlink":
        (tmp_path / "alias").symlink_to(real.parent, target_is_directory=True)
        path = tmp_path / "alias" / "file.json"
    elif kind == "fifo":
        path = tmp_path / "fifo"
        os.mkfifo(path)
    else:
        maximum = 1
    with pytest.raises(ValueError):
        c.read_bound(path, maximum=maximum)


def test_writer_rejects_parent_alias_before_creating_any_descendants(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        c.write_json(tmp_path / "alias" / "new" / "record.json", {"value": 1})
    assert list(outside.iterdir()) == []


def test_parallel_immutable_writers_retain_one_content_and_no_temporary_files(tmp_path):
    path = tmp_path / "nested" / "record.json"
    def write(index):
        try:
            c.write_json(path, {"value": index % 2})
            return index % 2
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, range(12)))
    winner = c.read_json(path)["value"]
    assert {r for r in results if r is not None} == {winner}
    assert [p.name for p in path.parent.iterdir()] == ["record.json"]
