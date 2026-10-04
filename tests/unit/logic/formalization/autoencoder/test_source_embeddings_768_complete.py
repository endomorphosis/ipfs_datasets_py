"""Complete checkpoint admission and dense encoder path checks without downloads."""
import importlib
from types import SimpleNamespace

import pytest

complete = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_768_complete")


def test_complete_loader_requires_every_tensor_and_no_ignored_classifier():
    keys = ["new.embeddings.weight", "classifier.weight", "classifier.bias"]
    complete._admit_loading({}, keys, keys)
    with pytest.raises(ValueError, match="tensor keys"):
        complete._admit_loading({}, keys, keys + ["unknown.weight"])
    with pytest.raises(ValueError, match="architecture"):
        complete._admit_loading({}, keys[:1], keys[:1])
    for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"):
        with pytest.raises(ValueError, match=key):
            complete._admit_loading({key: ["classifier.weight"]}, keys, keys)


def test_dense_path_verification_detects_any_output_modification():
    torch = pytest.importorskip("torch")
    hidden = torch.tensor([[[1., 2.], [3., 4.]]])
    class Tokenizer:
        def pad(self, rows, **kwargs):
            return {"input_ids": torch.tensor([rows[0]["input_ids"]])}
    class Model:
        training = False
        def __init__(self, delta):
            self.delta = delta
            self.new = lambda **kwargs: SimpleNamespace(last_hidden_state=hidden)
        def __call__(self, **kwargs):
            return SimpleNamespace(last_hidden_state=hidden + self.delta)
    row = {"input_ids": [1, 2], "attention_mask": [1, 1]}
    result = complete._verify_dense_path(torch, Model(0), Tokenizer(), row)
    assert result["encoder_and_complete_hidden_states_bitwise_equal"]
    with pytest.raises(ValueError, match="changed encoder"):
        complete._verify_dense_path(torch, Model(.001), Tokenizer(), row)


def test_input_limits_are_enforced_before_any_model_load(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid source reached model loading")
    monkeypatch.setattr(complete, "_load_backend", forbidden)
    for rows in ([], [{"id": "x", "source_text": "text", "canonical_ir": {}}],
                 [{"id": "x", "source_text": "x" * 65537}]):
        with pytest.raises(ValueError):
            complete.embed_rows(rows, manifest_path="missing", expected_manifest_sha256="0" * 64,
                                model_directory="missing", code_directory="missing")
