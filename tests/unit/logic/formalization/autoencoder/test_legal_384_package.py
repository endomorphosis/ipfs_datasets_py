"""Self-contained Legal weight loading, replay and thread isolation."""
import hashlib

import pytest
torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import legal_384_package as subject
from ipfs_datasets_py.logic.formalization.autoencoder.checkpoint_hub import EMBEDDING
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint, modal_latent_formula as numerical


@pytest.fixture()
def packaged(tmp_path):
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        options = dict(compute_device="cpu", initial_embedding_scale=.2, initial_embedding_rotation_scale=1.)
        model = current_v2.Autoencoder(**options)
        rows = [dict(id="authored", source_text="The operator must save the report.", embedding=[.5] + [0.] * 383)]
        samples = subject._rows(rows, EMBEDDING)
        targets = [dict(id="authored", source_text=rows[0]["source_text"], canonical_ir={"rules": [dict(
            modality="O", actor="operator", action="save", object="report", conditions=[], exceptions=[], temporal=[])]})]
        training = joint._rows(model, samples, targets)
        initial = numerical.build_checkpoint(joint._core_binding(model), training, [], hidden_size=16,
            token_embedding_dim=8, projection_width=4, batch_size=1)
        trained = numerical.train(initial, training, [], epochs=1, max_seconds=30)["checkpoint"]
        model.attach_formula_checkpoint(trained)
        receipt = subject.build_package(tmp_path / "legal", model=model, core_options=options,
            embedding_contract=EMBEDDING, fixture_rows=rows, provenance={"synthetic_vectors": True})
        return receipt, rows
    finally:
        torch.set_num_threads(previous)


def test_restored_trained_head_replays_without_training_and_restores_threads(packaged):
    receipt, rows = packaged
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        restored = subject.load_package(receipt["path"], expected_sha256=receipt["sha256"])
        assert torch.get_num_threads() == 2
        assert restored.describe()["learned_formula_head"] is True
        report = restored.infer(rows)
        assert report == restored.infer(rows)
        assert report["training_steps"] == 0 and report["provider_calls"] == 0
        assert report["qualified"] is False and torch.get_num_threads() == 2
    finally:
        torch.set_num_threads(previous)


def test_changed_package_is_rejected_before_loading(packaged):
    receipt, _ = packaged
    from pathlib import Path
    path = Path(receipt["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        subject.load_package(path, expected_sha256=receipt["sha256"])
