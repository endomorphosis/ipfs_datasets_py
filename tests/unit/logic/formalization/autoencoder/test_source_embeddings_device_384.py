"""Input controls for additive sessions; native CUDA runs live in qualification."""
import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_device_384 import (
    SourceEmbeddingDeviceSession384,
    _device_features,
)


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_explicit_boolean_device_policy_before_model_load(value):
    with pytest.raises(ValueError, match="boolean"):
        SourceEmbeddingDeviceSession384(optimized=value)


@pytest.mark.parametrize("value", [None, [], (), "source", [""], [" "], [1], ["a" * 32769], ["a"] * 129])
def test_input_boundaries_before_model_or_device_access(value):
    session = object.__new__(SourceEmbeddingDeviceSession384)
    with pytest.raises(ValueError, match="bounded nonempty source texts"):
        session.infer(value)


@pytest.mark.parametrize("with_modality", [False, True])
def test_actual_native_cpu_token_tensors_preserve_optional_text_marker(with_modality):
    features = {"input_ids": torch.tensor([[1, 2]]), "attention_mask": torch.tensor([[1, 1]])}
    if with_modality:
        features["modality"] = "text"
    result = _device_features(features, torch, "cpu")
    assert result.keys() == features.keys()
    assert torch.equal(result["input_ids"], features["input_ids"])
    assert str(result["input_ids"].device) == "cpu"


@pytest.mark.parametrize("change", ["foreign_marker", "foreign_field", "missing_mask", "non_tensor"])
def test_foreign_features_cannot_be_counted_as_native_device_inputs(change):
    features = {"input_ids": torch.tensor([[1, 2]]), "attention_mask": torch.tensor([[1, 1]])}
    if change == "foreign_marker":
        features["modality"] = "image"
    elif change == "foreign_field":
        features["task"] = "foreign"
    elif change == "missing_mask":
        del features["attention_mask"]
    else:
        features["input_ids"] = [[1, 2]]
    with pytest.raises(ValueError, match="features|native tensors"):
        _device_features(features, torch, "cpu")
