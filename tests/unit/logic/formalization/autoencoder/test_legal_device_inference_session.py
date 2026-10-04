"""Native package replay and private ownership controls on explicit CPU opt-out."""
from copy import deepcopy

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_384_package as package
from ipfs_datasets_py.logic.formalization.autoencoder import legal_device_inference_session as subject
from ipfs_datasets_py.logic.formalization.autoencoder.checkpoint_hub import EMBEDDING, HubAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint, modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def one_cpu_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        options = dict(compute_device="cpu", initial_embedding_scale=.2, initial_embedding_rotation_scale=1.)
        model = current_v2.Autoencoder(**options)
        rows = [dict(id="authored", source_text="The operator must save the report.", embedding=[.5] + [0.] * 383)]
        samples = package._rows(rows, EMBEDDING)
        targets = [dict(id="authored", source_text=rows[0]["source_text"], canonical_ir={"rules": [dict(
            modality="O", actor="operator", action="save", object="report", conditions=[], exceptions=[], temporal=[])]})]
        training = joint._rows(model, samples, targets)
        initial = numerical.build_checkpoint(joint._core_binding(model), training, [], hidden_size=8,
            token_embedding_dim=8, projection_width=2, batch_size=1)
        trained = numerical.train(initial, training, [], epochs=1, max_seconds=30)["checkpoint"]
        model.attach_formula_checkpoint(trained)
        receipt = package.build_package(tmp_path_factory.mktemp("legal-device") / "package", model=model,
            core_options=options, embedding_contract=EMBEDDING, fixture_rows=rows,
            provenance={"synthetic_vectors": True, "scope": "CPU product control"})
        return receipt, rows
    finally:
        torch.set_num_threads(previous)


def loaded(fixture):
    receipt, rows = fixture
    runtime = package.load_package(receipt["path"], expected_sha256=receipt["sha256"])
    return HubAutoencoder("legal_ir", runtime, {}, None), deepcopy(rows)


def test_verified_cpu_package_has_independently_owned_head_and_no_checkpoint_changes(fixture):
    original, rows = loaded(fixture)
    before = deepcopy(original.runtime._payload)
    old_decoder = original.runtime.model._joint_formula_decoder
    with subject.DeviceLegalAutoencoder(original, optimized=False) as device:
        report = device.infer(rows)
        assert original.runtime.model._joint_formula_decoder is old_decoder
        assert device.runtime._session._decoder is not old_decoder
        assert original.runtime._payload == before
        assert report["training_steps"] == 0 and report["provider_calls"] == 0
        selection = device.describe()["runtime"]["inference_implementation"]
        assert selection["core_device"] == "cpu" and selection["whole_model_cuda"] is False
        assert selection["formula_head_selection"]["cuda_selected"] is False
        assert "cuda_executed" not in selection["formula_head_selection"]
        assert report["result"]["inference_implementation"]["formula_decoder"]["actual_forward_executed"] is True
    with pytest.raises(ValueError, match="closed"):
        device.infer(rows)
    assert original.runtime.infer(rows)["checkpoint_sha256"] == report["checkpoint_sha256"]


def test_changed_original_binding_is_rejected(fixture):
    original, rows = loaded(fixture)
    with subject.DeviceLegalAutoencoder(original, optimized=False) as device:
        original.runtime._payload["core_binding"]["core_sha256"] = "b" * 64
        with pytest.raises(ValueError, match="core changed"):
            device.infer(rows)


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_loader_requires_boolean_before_download(value):
    with pytest.raises(ValueError, match="boolean"):
        subject.open_legal_device_autoencoder(optimized=value)


def test_foreign_hub_domain_rejected_without_adaptation():
    with pytest.raises(ValueError, match="verified Legal"):
        subject.DeviceLegalAutoencoder(HubAutoencoder("security_ir", None, {}, None), optimized=False)


@pytest.mark.parametrize("value", [None, [], "source", [" "], [1], ["a"*32769], ["a"]*129])
def test_invalid_texts_rejected_before_any_encoder_or_runtime_access(value):
    device = object.__new__(subject.DeviceLegalAutoencoder)
    with pytest.raises(ValueError, match="bounded nonempty Legal"):
        device.infer_texts(value)


def test_failed_text_request_restores_callers_cpu_threads():
    device = object.__new__(subject.DeviceLegalAutoencoder)
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        with pytest.raises(ValueError):
            device.infer_texts([])
        assert torch.get_num_threads() == 2
    finally:
        torch.set_num_threads(previous)
