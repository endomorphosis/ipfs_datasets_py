"""Numerical warm-start, resume and receipt checks for the new child runtime."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as previous
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_role_curriculum as runtime

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_legal_span_consistency.py")))
rows_and_pairs = HELPERS["rows_and_pairs"]


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    before = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


@pytest.fixture(scope="module")
def parents():
    mixed = HELPERS["parent"].__wrapped__()
    rows, pairs = rows_and_pairs("consistency-parent")
    return {enabled: previous.train_decoder(previous.build_checkpoint(parent, rows, [], pairs,
        objective="consistency", seed=1729), rows, [], pairs, max_steps=2, max_seconds=30)["checkpoint"]
        for enabled, parent in mixed.items()}


def child(parent):
    rows, pairs = rows_and_pairs("role-fit")
    return runtime.build_checkpoint(parent, rows, [], pairs, objective="consistency", seed=1729)


@pytest.mark.parametrize("enabled", [False, True])
def test_exact_consistency_weights_inference_and_explicit_new_optimizer(parents, enabled):
    parent = parents[enabled]; checkpoint = child(parent)
    assert checkpoint["consistency_parent_checkpoint"] == parent
    assert checkpoint["model_state"] == parent["model_state"]
    assert checkpoint["optimizer_state"]["parameters"] == {}
    assert runtime.optimizer_steps(checkpoint) == 0 and checkpoint["consistency_parent_optimizer_steps"] == 2
    texts = [row["source_text"] for row in rows_and_pairs("probe")[0][-4:]]
    decoder = runtime.RoleCurriculumDecoder(checkpoint)
    assert decoder.decode_formal_logic(texts)["rows"] == previous.ConsistencyDecoder(parent).decode_formal_logic(texts)["rows"]
    checkpoint["model_state"] = {}
    assert decoder.checkpoint["model_state"] == parent["model_state"]


@pytest.mark.parametrize("enabled", [False, True])
def test_staged_training_retains_exact_moments_order_and_numerical_results(parents, enabled):
    cp = child(parents[enabled]); rows, pairs = rows_and_pairs("role-fit")
    full = runtime.train_decoder(cp, rows, [], pairs, max_steps=4, max_seconds=30)
    first = runtime.train_decoder(cp, rows, [], pairs, max_steps=2, max_seconds=30)
    second = runtime.train_decoder(first["checkpoint"], rows, [], pairs, max_steps=2, max_seconds=30)
    for key in ("model_state", "optimizer_state", "progress"):
        assert full["checkpoint"][key] == second["checkpoint"][key]
    for key in ("batch_losses", "batch_loss_components", "batch_exposures"):
        assert full["report"][key] == first["report"][key] + second["report"][key]
    assert runtime.optimizer_steps(second["checkpoint"]) == 4
    for row in full["report"]["batch_loss_components"]:
        assert row["total"] == pytest.approx(row["base_ce"] + .25 * row["consistency_js"], abs=1e-6)
    if not enabled:
        assert all(value == 0 for value in full["report"]["auxiliary_gradient_norm_max"].values())


def test_missing_trained_predecessor_hash_is_rejected(parents):
    cp = child(parents[True]); rows, pairs = rows_and_pairs("role-fit")
    trained = runtime.train_decoder(cp, rows, [], pairs, max_steps=1, max_seconds=30)["checkpoint"]
    trained["parent_checkpoint_sha256"] = None
    with pytest.raises(ValueError, match="trained checkpoint lacks preceding hash"):
        runtime.validate_checkpoint(trained)


def test_manifest_pair_and_budget_changes_cannot_continue_checkpoint(parents):
    cp = child(parents[True]); rows, pairs = rows_and_pairs("role-fit")
    with pytest.raises(ValueError, match="max_steps"):
        runtime.train_decoder(cp, rows, [], pairs, max_steps=401, max_seconds=30)
    changed = deepcopy(pairs); changed[0].reverse()
    with pytest.raises(ValueError, match="manifest"):
        runtime.train_decoder(cp, rows, [], changed, max_steps=1, max_seconds=30)
    bad = deepcopy(cp); bad["progress"]["optimizer_steps"] = 401
    with pytest.raises(ValueError, match="progress"):
        runtime.validate_checkpoint(bad)


def test_changed_parent_or_objective_and_inference_weights_are_rejected(parents):
    rows, pairs = rows_and_pairs("role-fit")
    with pytest.raises(ValueError, match="fixed consistency objective"):
        runtime.build_checkpoint(parents[True], rows, [], pairs, objective="ce", seed=1729)
    cp = child(parents[True]); cp["consistency_parent_checkpoint_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="parent hash"):
        runtime.validate_checkpoint(cp)
    decoder = runtime.RoleCurriculumDecoder(child(parents[True]))
    with torch.no_grad(): next(decoder.model.parameters()).add_(1)
    with pytest.raises(ValueError, match="model state changed"):
        decoder.decode_formal_logic([rows[0]["source_text"]])


def test_owned_checkpoint_file_roundtrip_preserves_exact_child_and_parent(parents, tmp_path):
    cp = child(parents[True]); reference = runtime.save_checkpoint(cp, tmp_path / "checkpoint.json")
    assert runtime.load_checkpoint(reference["path"], expected_sha256=reference["sha256"]) == cp
    with pytest.raises(FileExistsError): runtime.save_checkpoint(cp, tmp_path / "checkpoint.json")
    with pytest.raises(ValueError, match="hash"):
        runtime.load_checkpoint(reference["path"], expected_sha256="0" * 64)
