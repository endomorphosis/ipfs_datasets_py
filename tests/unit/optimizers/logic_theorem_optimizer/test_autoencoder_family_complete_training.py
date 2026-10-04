import json
from pathlib import Path

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_complete_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_complete_training as training
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel


@pytest.mark.parametrize("value", ["archive_ledger", "HTTPServer12", "Δvalue", "isReady", "snake__case", "a-b", "abc012def" * 4])
def test_identifier_pieces_preserve_order_case_and_delimiters(value):
    assert "".join(features.identifier_pieces(value)) == value


def test_unseen_identifier_composition_retains_known_parts():
    atoms, _ = features.atom_encoder()
    training_atoms = set(atoms("archive_ledger")) | set(atoms("inspect_manifest"))
    unseen = set(atoms("archive_manifest"))
    assert unseen <= training_atoms
    assert set(atoms("archive-manifest")) != unseen
    assert set(atoms(True)) != set(atoms(1))


@pytest.fixture(scope="module")
def legal():
    return panel.prepare_partition("legal_ir", "train"), panel.prepare_partition("legal_ir", "validation")


def test_full_vocabulary_fails_instead_of_pruning(legal):
    train, tuning = legal
    with pytest.raises(ValueError, match="no atoms were pruned"):
        features.prepare(train, tuning, max_features=4)
    prepared = features.prepare(train, tuning)
    assert all(row["unknown_atoms"] == 0 for row in prepared["training_coverage"]["projections"])


@pytest.mark.parametrize("strategy", ["adam", "ridge_path"])
def test_fitting_and_reload_use_all_training_atoms_and_do_not_modify_weights(tmp_path, legal, strategy):
    train, tuning = legal
    result = training.train_complete_family_autoencoder(train, tuning, output_dir=tmp_path / strategy,
        strategy=strategy, epochs=2, required_families=("deontic", "tdfol", "frame_logic"))
    report = result["report"]
    assert report["training_atoms_pruned"] == 0
    assert report["after"]["objective"] <= report["before"]["objective"] + 1e-12
    path = Path(result["descriptor"]["path"])
    original = path.read_bytes()
    inferred = training.infer_complete_family_autoencoder(result["descriptor"], tuning)
    assert inferred["objective"] == report["after"]["objective"]
    assert inferred["training_steps"] == 0
    assert path.read_bytes() == original


def test_required_family_and_partition_overlap_fail(tmp_path, legal):
    train, tuning = legal
    with pytest.raises(ValueError, match="required family"):
        training.train_complete_family_autoencoder(train, tuning, output_dir=tmp_path / "missing",
            required_families=("cryptographic_protocol",))
    with pytest.raises(ValueError, match="source leakage"):
        training.train_complete_family_autoencoder(train, train, output_dir=tmp_path / "leak")


def test_matched_strategies_share_exact_training_only_basis(tmp_path, legal):
    train, tuning = legal
    results = [training.train_complete_family_autoencoder(train, tuning, output_dir=tmp_path / strategy,
        strategy=strategy, epochs=1) for strategy in ("adam", "ridge_path")]
    saved = [training.load_complete_family_checkpoint(row["descriptor"])[0] for row in results]
    assert saved[0]["space"] == saved[1]["space"]
    assert saved[0]["report"]["initial_parameters_sha256"] == saved[1]["report"]["initial_parameters_sha256"]
