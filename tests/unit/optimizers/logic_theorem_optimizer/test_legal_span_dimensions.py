"""Numerical lineage, native-dimension and resumption checks using synthetic data."""
from copy import deepcopy
import json

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims


def examples(dimension=0):
    result = []
    for i, (actor, modality, phrase, action, obj) in enumerate((
        ("Lark", "O", "must", "retain", "books"),
        ("Wren", "P", "may", "publish", "records"),
        ("Finch", "F", "must not", "destroy", "files"),
    )):
        row = {"id": f"synthetic-{i}", "source_text": f"{actor} {phrase} {action} {obj}.",
            "canonical_ir": {"rules": [{"actor": actor, "modality": modality, "action": action,
                "object": obj, "conditions": [], "exceptions": [], "temporal": []}]}}
        if dimension:
            row["latent"] = [(i + 1) / (j + 1) for j in range(dimension)]
        result.append(row)
    return result


def contract(dimension):
    return None if not dimension else {"dimension": dimension, "representation_id": "synthetic-test-only",
        "producer_sha256": "a" * 64, "training_index_sha256": "b" * 64}


@pytest.fixture(scope="module", autouse=True)
def threads():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


@pytest.fixture(scope="module")
def parent():
    data = examples(384)
    cp = span.build_checkpoint(data, latent_dimension=384, latent_enabled=False, hidden_size=8,
                               embedding_dim=4, projection_width=4, batch_size=2)
    return span.train_decoder(cp, data, max_steps=3, max_seconds=30)["checkpoint"]


def child(parent, dimension=768):
    return dims.build_checkpoint(parent, examples(dimension), latent_dimension=dimension,
                                 context_contract=contract(dimension), batch_size=2)


@pytest.mark.parametrize("dimension", [0, 8, 384, 768])
def test_warm_start_copies_source_and_preserves_every_logit(parent, dimension):
    before = dims.checkpoint_digest(parent)
    cp = child(parent, dimension)
    dims.validate_checkpoint(cp)
    assert cp["initial_source_model_sha256"] == dims.checkpoint_digest(dims._source_state(parent["model_state"]))
    assert dims.optimizer_steps(cp) == 0
    original = span.SpanLegalFormulaDecoder(parent)
    decoder = dims.DimensionalSpanDecoder(cp)
    tokens = span.tokenize_source("Synthetic actor must retain an unfamiliar register.")
    with torch.no_grad():
        a = original.model(*span._batch(torch, [{"tokens": tokens, "latent": [2.] * 384}]), enabled=False)
        b = decoder.model(*span._batch(torch, [{"tokens": tokens, "latent": [3.] * dimension}]))
    assert all(torch.equal(a[k], b[k]) for k in a)
    if dimension:
        assert len(cp["model_state"]["latent_down.weight"][0]) == dimension
        assert not torch.tensor(cp["model_state"]["latent_up.weight"]).count_nonzero()
        assert not torch.tensor(cp["model_state"]["latent_up.bias"]).count_nonzero()
    else:
        assert not any(k.startswith("latent_") for k in cp["model_state"])
    assert dims.checkpoint_digest(parent) == before


def test_split_training_exactly_resumes_optimizer_and_weights(parent):
    cp = child(parent)
    data = examples(768)
    full = dims.train_decoder(cp, data, max_steps=4, max_seconds=30)["checkpoint"]
    first = dims.train_decoder(cp, data, max_steps=2, max_seconds=30)["checkpoint"]
    resumed = dims.train_decoder(first, data, max_steps=2, max_seconds=30)["checkpoint"]
    for name in ("model_state", "optimizer_state", "progress"):
        assert full[name] == resumed[name]
    assert dims.optimizer_steps(full) == dims.optimizer_steps(resumed) == 4
    assert full["source_parent_checkpoint"] == parent
    assert full["model_state"]["latent_up.weight"] != cp["model_state"]["latent_up.weight"]
    assert full["model_state"]["latent_down.weight"] != cp["model_state"]["latent_down.weight"]


@pytest.mark.parametrize("dimension", [0, 8, 384, 768])
def test_all_dimensions_train_and_reload_without_target_inference(tmp_path, parent, dimension):
    cp = child(parent, dimension)
    trained = dims.train_decoder(cp, examples(dimension), max_steps=2, max_seconds=30)
    assert trained["report"]["optimizer_steps"] == 2
    receipt = dims.save_checkpoint(trained["checkpoint"], tmp_path / f"native-{dimension}.json")
    loaded = dims.load_checkpoint(receipt["path"], expected_sha256=receipt["sha256"])
    decoder = dims.DimensionalSpanDecoder(loaded)
    args = {"latents": [[.1] * dimension]} if dimension else {}
    result = decoder.decode_formal_logic(["A new agency may inspect a new record."], **args)
    expected = dims.DimensionalSpanDecoder(trained["checkpoint"]).decode_formal_logic(
        ["A new agency may inspect a new record."], **args)
    assert result == expected
    assert result["input_dimension"] == dimension
    assert result["model_state_unchanged"] is True
    assert result["target_access"] is result["teacher_forcing"] is result["qualified"] is False


def test_explicit_disabled_gate_is_distinct_from_zero_input_biases(parent):
    cp = dims.train_decoder(child(parent), examples(768), max_steps=2, max_seconds=30)["checkpoint"]
    decoder = dims.DimensionalSpanDecoder(cp)
    with torch.no_grad():
        decoder.model.latent_up.bias.fill_(.5)
    tokens = span.tokenize_source("A trustee may publish records.")
    args = span._batch(torch, [{"tokens": tokens, "latent": [0.] * 768}])
    with torch.no_grad():
        enabled = decoder.model(*args, enabled=True)
        disabled = decoder.model(*args, enabled=False)
    assert any(not torch.equal(enabled[k], disabled[k]) for k in enabled)


@pytest.mark.parametrize("dimension", [True, -1, 7, 385, 769])
def test_unsupported_dimensions_fail(parent, dimension):
    with pytest.raises(ValueError, match="dimension"):
        dims.build_checkpoint(parent, examples(), latent_dimension=dimension, context_contract=None)


@pytest.mark.parametrize("mutation,match", [
    (lambda cp: cp.update(qualified=True), "authority"),
    (lambda cp: cp["context_contract"].update(dimension=384), "dimension"),
    (lambda cp: cp["context_contract"].update(producer_sha256="c" * 64), "contract changed"),
    (lambda cp: cp.update(initial_source_model_sha256="c" * 64), "weight boundary"),
    (lambda cp: cp["model_state"]["modality.bias"].__setitem__(0, .3), "zero-update"),
    (lambda cp: cp["progress"].update(row_cursor=True), "progress"),
    (lambda cp: cp.update(extra_target={"rules": []}), "closed"),
    (lambda cp: cp["implementation"].update(dimensions_sha256="c" * 64), "source drift"),
])
def test_corrupted_lineage_or_state_fails(parent, mutation, match):
    cp = child(parent)
    mutation(cp)
    with pytest.raises(ValueError, match=match):
        dims.validate_checkpoint(cp)


def test_no_update_is_exact_noop_and_data_swap_fails(parent):
    cp = child(parent)
    result = dims.train_decoder(cp, examples(768), max_steps=0, max_seconds=0)
    assert result["checkpoint"] == cp
    dims.validate_checkpoint(result["checkpoint"])
    bad = examples(768)
    bad[0]["latent"][0] = 2.
    with pytest.raises(ValueError, match="manifests differ"):
        dims.train_decoder(cp, bad, max_steps=1)


def test_inference_rejects_dimension_mismatch_and_target_argument(parent):
    decoder = dims.DimensionalSpanDecoder(child(parent))
    with pytest.raises(ValueError, match="dimension"):
        decoder.decode_formal_logic(["Source only."], [[0.] * 384])
    with pytest.raises(TypeError):
        decoder.decode_formal_logic(["Source only."], [[0.] * 768], canonical_ir={"rules": []})
    source = dims.DimensionalSpanDecoder(child(parent, 0))
    with pytest.raises(ValueError, match="does not accept"):
        source.decode_formal_logic(["Source only."], [[0.] * 768])


def test_inference_owns_config_after_caller_mutates_input_checkpoint(parent):
    cp = dims.train_decoder(child(parent), examples(768), max_steps=2, max_seconds=30)["checkpoint"]
    decoder = dims.DimensionalSpanDecoder(cp)
    text, latent = ["A new trustee may inspect records."], [[.2] * 768]
    before = decoder.decode_formal_logic(text, latent)
    cp["config"]["latent_enabled"] = False
    cp["config"]["residual_scale"] = .75
    assert decoder.decode_formal_logic(text, latent) == before


def test_non_source_parent_and_overlapping_data_rejected(parent):
    altered = deepcopy(parent)
    altered["config"]["latent_enabled"] = True
    with pytest.raises(ValueError, match="source-only parent"):
        child(altered)
    with pytest.raises(ValueError, match="overlap"):
        dims.build_checkpoint(parent, examples(), examples(), latent_dimension=0)


def test_checkpoint_storage_is_exclusive_and_duplicate_json_keys_fail(parent, tmp_path):
    cp = child(parent)
    path = tmp_path / "state.json"
    receipt = dims.save_checkpoint(cp, path)
    with pytest.raises(FileExistsError):
        dims.save_checkpoint(cp, path)
    malformed = tmp_path / "duplicate.json"
    raw = '{"schema":"bad",' + json.dumps(cp)[1:]
    malformed.write_text(raw)
    import hashlib
    with pytest.raises(ValueError, match="duplicate"):
        dims.load_checkpoint(malformed, expected_sha256=hashlib.sha256(raw.encode()).hexdigest())
    with pytest.raises(ValueError, match="hash differs"):
        dims.load_checkpoint(receipt["path"], expected_sha256="0" * 64)
