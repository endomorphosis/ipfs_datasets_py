import copy
import hashlib
from pathlib import Path

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_ridge_path as ridge
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_prepared as prepared
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel


def test_shared_factorization_matches_separate_ridge_solves():
    torch.set_num_threads(1)
    generator = torch.Generator().manual_seed(3)
    training = torch.randn((6, 8), generator=generator, dtype=torch.float64)
    parameters = [torch.randn((8, 3), generator=generator, dtype=torch.float64),
                  torch.zeros(3, dtype=torch.float64), torch.zeros((3, 8), dtype=torch.float64),
                  torch.zeros(8, dtype=torch.float64)]
    masks = torch.tensor([[True, True, i % 2 == 0] for i in range(6)])
    spans = {"a": (0, 2), "b": (2, 5), "c": (5, 8)}
    proposals, factorizations = ridge._corrections(torch, parameters, training, masks, spans, (.001, .1))
    assert factorizations == 2
    for penalty in (.001, .1):
        reference, _ = prepared._calibrate_decoder(torch, parameters, training, masks, spans, penalty)
        for name, (start, end) in spans.items():
            correction = proposals[penalty][name]
            assert torch.allclose(correction[:-1], reference[2][:, start:end], atol=1e-10, rtol=1e-10)
            assert torch.allclose(correction[-1], reference[3][start:end], atol=1e-10, rtol=1e-10)


@pytest.fixture(scope="module")
def legal_reports():
    return panel.prepare_partition("legal_ir", "train"), panel.prepare_partition("legal_ir", "validation")


def test_training_is_family_nonregressing_and_inference_does_not_write(tmp_path, legal_reports):
    train, tuning = legal_reports
    result = ridge.train_family_ridge_path(train, tuning, output_dir=tmp_path / "model",
        required_families=("deontic", "frame_logic", "tdfol"))
    report = result["report"]
    assert report["training_executed"]
    assert report["gram_factorizations"] == 1
    assert all(value <= report["before"]["families"][family] + 1e-12
               for family, value in report["after"]["families"].items())
    checkpoint = Path(result["descriptor"]["path"])
    before = checkpoint.read_bytes()
    inferred = ridge.infer_family_ridge_path(result["descriptor"], tuning)
    assert inferred["objective"] == report["after"]["objective"]
    assert inferred["training_steps"] == 0
    assert checkpoint.read_bytes() == before
    assert not inferred["formalized"]


def test_missing_required_family_stops_before_checkpoint_write(tmp_path, legal_reports):
    train, tuning = legal_reports
    with pytest.raises(ValueError, match="required logic family"):
        ridge.train_family_ridge_path(train, tuning, output_dir=tmp_path / "missing", required_families=("separation_logic",))
    assert not (tmp_path / "missing").exists()


def test_overlap_is_rejected_before_fitting(tmp_path, legal_reports):
    train, _ = legal_reports
    with pytest.raises(ValueError, match="source leakage"):
        ridge.train_family_ridge_path(train, train, output_dir=tmp_path / "overlap")


def test_parent_is_preserved_and_tuning_identity_enforced(tmp_path, legal_reports):
    train, tuning = legal_reports
    parent = ridge.train_family_ridge_path(train, tuning, output_dir=tmp_path / "parent")
    path = Path(parent["descriptor"]["path"])
    before = path.read_bytes()
    child = ridge.train_family_ridge_path(train, tuning, output_dir=tmp_path / "child", parent_descriptor=parent["descriptor"])
    assert child["report"]["initial_parameters_sha256"] == parent["report"]["selected_parameters_sha256"]
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="tuning panel"):
        ridge.train_family_ridge_path(train, list(reversed(tuning)), output_dir=tmp_path / "bad", parent_descriptor=parent["descriptor"])
