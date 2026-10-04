"""Hybrid warm-start equivalence, actual gradients, isolation and integrity."""
import copy
import importlib
import json

import pytest

torch = pytest.importorskip("torch")
PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
source = importlib.import_module(PREFIX + ".legal_formula_learning")
codec = importlib.import_module(PREFIX + ".legal_formula_codec")
hybrid = importlib.import_module(PREFIX + ".legal_hybrid_formula")


def examples():
    def row(identifier, text, modality, exceptions=()):
        return {"id": identifier, "source_text": text, "canonical_ir": {"rules": [{
            "modality": modality, "actor": "agency", "action": "disclose", "object": "records",
            "conditions": [], "exceptions": list(exceptions), "temporal": []}]}}
    return [row("o", "The agency shall disclose records.", "O"),
            row("f", "The agency shall not disclose records.", "F"),
            row("e", "The agency shall disclose records unless exempt.", "O", ["exempt"])]


def rows(dimension=8):
    return [{**row, "latent": [float(i == index) for i in range(dimension)]}
            for index, row in enumerate(examples())]


def contract(dimension=8):
    return {"dimension": dimension, "representation_id": "test_fixture_vectors/v1",
            "encoder_sha256": "a" * 64}


@pytest.fixture(scope="module", autouse=True)
def threads():
    original = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(original)


@pytest.fixture(scope="module")
def parent():
    return source.train_decoder(examples(), [], epochs=25, max_seconds=60,
        hidden_size=16, embedding_dim=8, learning_rate=0.02, batch_size=2, seed=41)["checkpoint"]


def initial(parent, dimension=8, **options):
    return hybrid.build_checkpoint(parent, contract(dimension), rows(dimension), [],
        batch_size=2, projection_width=8, **options)


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_warm_start_copies_every_weight_and_preserves_exact_parent_logits(parent, dimension):
    checkpoint = initial(parent, dimension)
    assert checkpoint["codec"] == parent["codec"]
    assert all(checkpoint["model_state"][key] == value for key, value in parent["model_state"].items())
    assert checkpoint["source_parent_checkpoint_sha256"] == source.checkpoint_digest(parent)
    assert checkpoint["optimizer_state"]["parameters"] == {}
    _, parent_model, _ = source._restore(parent)
    _, model, _ = hybrid._restore(checkpoint)
    records = [(codec.encode_source(parent["codec"], row["source_text"]),
                codec.encode_target(parent["codec"], row["canonical_ir"])) for row in examples()]
    source_ids, lengths, target = source._batch(torch, records)
    with torch.no_grad():
        expected = parent_model(source_ids, lengths, target[:, :-1])
        actual = model(source_ids, lengths, target[:, :-1], torch.tensor([row["latent"] for row in rows(dimension)]))
    assert torch.equal(expected, actual)
    texts = [row["source_text"] for row in examples()]
    before = source.LearnedLegalFormulaDecoder(parent).decode_formal_logic(texts)
    after = hybrid.HybridLegalFormulaDecoder(checkpoint).decode_formal_logic(texts, [row["latent"] for row in rows(dimension)])
    assert [row.get("generated_token_ids") for row in before["rows"]] == [row.get("generated_token_ids") for row in after["rows"]]


@pytest.mark.parametrize("loss_mode", ["token_ce", "facet_balanced"])
def test_training_updates_latent_and_source_parameters_and_resumes_exactly(parent, loss_mode):
    checkpoint = initial(parent, loss_mode=loss_mode)
    original = copy.deepcopy(checkpoint)
    whole = hybrid.train_decoder(checkpoint, rows(), [], max_steps=6, max_seconds=60)
    first = hybrid.train_decoder(checkpoint, rows(), [], max_steps=3, max_seconds=60)
    resumed = hybrid.train_decoder(first["checkpoint"], rows(), [], max_steps=3, max_seconds=60)
    assert checkpoint == original
    assert whole["report"]["optimizer_steps"] == 6
    changed = whole["report"]["changed_parameter_names"]
    assert "latent_up.weight" in changed and "latent_down.weight" in changed
    assert "source_embedding.weight" in changed and "output.weight" in changed
    for field in ("model_state", "optimizer_state", "progress"):
        assert resumed["checkpoint"][field] == whole["checkpoint"][field]
    hybrid.validate_checkpoint(whole["checkpoint"])


def test_disabled_latent_control_has_same_shapes_and_never_updates_latent_parameters(parent):
    checkpoint = initial(parent, latent_enabled=False)
    result = hybrid.train_decoder(checkpoint, rows(), [], max_steps=4, max_seconds=60)
    assert not any(name.startswith("latent_") for name in result["report"]["changed_parameter_names"])
    active = initial(parent)
    assert {key: torch.tensor(value).shape for key, value in checkpoint["model_state"].items()} == {
        key: torch.tensor(value).shape for key, value in active["model_state"].items()}
    decoder = hybrid.HybridLegalFormulaDecoder(result["checkpoint"])
    texts = [row["source_text"] for row in examples()]
    vectors = [row["latent"] for row in rows()]
    ordinary = decoder.decode_formal_logic(texts, vectors)
    rotated = decoder.decode_formal_logic(texts, vectors, latent_ablation="rotate")
    assert [row.get("generated_token_ids") for row in ordinary["rows"]] == [row.get("generated_token_ids") for row in rotated["rows"]]


def test_inference_has_no_target_or_training_access_and_ablation_inputs_are_honest(parent, monkeypatch):
    checkpoint = hybrid.train_decoder(initial(parent), rows(), [], max_steps=4)["checkpoint"]
    decoder = hybrid.HybridLegalFormulaDecoder(checkpoint)
    original = copy.deepcopy(decoder.model.state_dict())
    def prohibited(*args, **kwargs):
        raise AssertionError("inference called target/training code")
    monkeypatch.setattr(codec, "encode_target", prohibited)
    monkeypatch.setattr(hybrid, "train_decoder", prohibited)
    monkeypatch.setattr(source, "train_decoder", prohibited)
    texts, vectors = [row["source_text"] for row in rows()], [row["latent"] for row in rows()]
    rotated = decoder.decode_formal_logic(texts, vectors, latent_ablation="rotate")
    assert rotated["rows"][0]["latent_sha256"] == hybrid.checkpoint_digest(vectors[1])
    zero = decoder.decode_formal_logic(texts, vectors, latent_ablation="zero")
    assert zero["rows"][0]["latent_sha256"] == hybrid.checkpoint_digest([0.0] * 8)
    disabled = decoder.decode_formal_logic(texts, vectors, latent_ablation="disabled")
    assert not disabled["rows"][0]["latent_input_enabled"]
    assert not rotated["target_access"] and not rotated["teacher_forcing"]
    assert all(rotated[key] is False for key in hybrid.FALSE)
    assert all(torch.equal(value, original[key]) for key, value in decoder.model.state_dict().items())


def test_oov_malformed_vectors_and_unsupported_binding_are_rejected(parent):
    checkpoint = initial(parent)
    decoder = hybrid.HybridLegalFormulaDecoder(checkpoint)
    result = decoder.decode_formal_logic(["Spacecraft shall orbit Mars."], [[0.0] * 8])
    assert result["rows"][0]["reason"] == "source_encoding_rejected"
    for vector in ([0.0] * 7, [float("nan")] * 8, [True] * 8):
        with pytest.raises(ValueError):
            decoder.decode_formal_logic([examples()[0]["source_text"]], [vector])
    altered = rows()
    altered[0]["canonical_ir"]["rules"][0]["quantifier"] = "forall"
    altered[0]["canonical_ir"]["rules"][0]["variables"] = ["x"]
    with pytest.raises(ValueError, match="seven canonical facets"):
        hybrid.build_checkpoint(parent, contract(), altered)
    altered = rows()
    altered[0]["canonical_ir"]["rules"][0]["exceptions"] = ["exempt", "exempt"]
    with pytest.raises(ValueError, match="sorted and unique"):
        hybrid.build_checkpoint(parent, contract(), altered)


def test_checkpoint_io_hashes_optimizer_and_manifests_fail_closed(parent, tmp_path):
    checkpoint = hybrid.train_decoder(initial(parent), rows(), [], max_steps=2)["checkpoint"]
    path = tmp_path / "hybrid.json"
    saved = hybrid.save_checkpoint(checkpoint, path)
    assert hybrid.load_checkpoint(path, expected_sha256=saved["sha256"]) == checkpoint
    with pytest.raises(FileExistsError):
        hybrid.save_checkpoint(checkpoint, path)
    with pytest.raises(ValueError, match="hash differs"):
        hybrid.load_checkpoint(path, expected_sha256="0" * 64)
    assert "source_text" not in json.dumps(checkpoint)
    broken = copy.deepcopy(checkpoint)
    broken["latent_contract"]["representation_id"] = "other"
    with pytest.raises(ValueError, match="contract hash"):
        hybrid.validate_checkpoint(broken)
    broken = copy.deepcopy(checkpoint)
    broken["optimizer_state"]["parameters"]["latent_up.bias"]["exp_avg_sq"][0] = -1
    with pytest.raises(ValueError):
        hybrid.validate_checkpoint(broken)
    changed = rows()
    changed[0]["latent"][0] = 2.0
    with pytest.raises(ValueError, match="manifests differ"):
        hybrid.train_decoder(checkpoint, changed, [], max_steps=1)


def test_equal_facet_mass_counts_exception_stop_and_zero_step_budget(parent):
    fitted = parent["codec"]
    targets = [codec.encode_target(fitted, row["canonical_ir"]) for row in examples()]
    weights = hybrid._facet_weights(fitted, targets, torch)
    assert torch.allclose(weights.sum(dim=1), torch.full((3,), 7.0))
    last = targets[-1]
    atom = fitted["target_vocabulary"].index('["atom","exceptions","exempt"]')
    stop = fitted["target_vocabulary"].index('["end","exceptions"]')
    assert weights[-1, last.index(atom) - 1] == 0.5
    assert weights[-1, last.index(stop) - 1] == 0.5
    checkpoint = initial(parent)
    result = hybrid.train_decoder(checkpoint, rows(), [], max_steps=0)
    assert result["report"]["optimizer_steps"] == 0
    assert result["checkpoint"]["model_state"] == checkpoint["model_state"]


def test_inference_rejects_runtime_source_provenance_drift(parent, monkeypatch):
    decoder = hybrid.HybridLegalFormulaDecoder(initial(parent))
    changed = copy.deepcopy(hybrid._IMPLEMENTATION_AT_IMPORT)
    changed["hybrid_sha256"] = "0" * 64
    monkeypatch.setattr(hybrid, "_capture_implementation", lambda: changed)
    with pytest.raises(ValueError, match="changed since import"):
        decoder.decode_formal_logic([examples()[0]["source_text"]], [[0.0] * 8])
