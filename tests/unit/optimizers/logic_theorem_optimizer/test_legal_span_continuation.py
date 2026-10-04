"""Warm-start tensor provenance, fresh moments, exact resumption and isolation."""
import copy
import importlib
import json

import pytest

torch = pytest.importorskip("torch")
prefix = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
span = importlib.import_module(prefix + "legal_span_formula")
continuation = importlib.import_module(prefix + "legal_span_continuation")


def examples(*, new=False):
    rows = []
    actor, obj = ("municipality", "documents") if new else ("agency", "records")
    for index, (marker, modality) in enumerate((("shall", "O"), ("may", "P"), ("shall not", "F"))):
        for qualifier in (False, True):
            text = "The " + actor + " " + marker + " disclose " + obj + (" unless exempt" if qualifier else "") + "."
            rows.append({"id": ("new" if new else "old") + str(index) + str(qualifier), "source_text": text,
                "canonical_ir": {"rules": [{"modality": modality, "actor": actor, "action": "disclose", "object": obj,
                    "conditions": [], "exceptions": ["exempt"] if qualifier else [], "temporal": []}]},
                "latent": [float(i == index) for i in range(384)]})
    return rows


def contract():
    return {"dimension": 384, "representation_id": "test_profile_context/v1", "producer_sha256": "a" * 64,
            "training_index_sha256": "b" * 64}


@pytest.fixture(scope="module", autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def parent():
    rows = examples()
    checkpoint = span.build_checkpoint(rows, latent_dimension=384, latent_enabled=False,
        seed=23, hidden_size=16, embedding_dim=8, projection_width=8, batch_size=3)
    return span.train_decoder(checkpoint, rows, max_steps=8)["checkpoint"]


def initial(parent, **options):
    return continuation.build_checkpoint(parent, examples(new=True), context_contract=contract(),
        batch_size=3, **options)


def test_warm_start_copies_every_trained_tensor_and_restarts_optimizer(parent):
    before = copy.deepcopy(parent)
    checkpoint = initial(parent)
    base = checkpoint["base_checkpoint"]
    assert base["model_state"] == parent["model_state"]
    assert base["progress"] == {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    assert not base["optimizer_state"]["parameters"]
    assert parent["optimizer_state"]["parameters"]
    assert base["config"]["learning_rate"] == .001
    assert base["config"]["initialization"] == "from_scratch"
    assert checkpoint["initialization"]["mode"] == "warm_start_all_source_parent_model_tensors"
    assert not checkpoint["initialization"]["parent_optimizer_moments_transferred"]
    assert checkpoint["source_parent_checkpoint_sha256"] == span.checkpoint_digest(parent)
    assert checkpoint["source_parent_optimizer_steps"] == 8
    assert checkpoint["initial_base_checkpoint_sha256"] == span.checkpoint_digest(base)
    assert continuation.initial_model_digest(checkpoint) == span.checkpoint_digest(parent["model_state"])
    assert continuation.optimizer_steps(checkpoint) == 0
    assert parent == before
    enabled, disabled = initial(parent), initial(parent, latent_enabled=False)
    assert enabled["base_checkpoint"]["model_state"] == disabled["base_checkpoint"]["model_state"]
    assert enabled["initial_model_state_sha256"] == disabled["initial_model_state_sha256"]


def test_warm_start_predictions_and_logits_preserve_parent_at_zero_updates(parent):
    checkpoint = initial(parent)
    old = span.SpanLegalFormulaDecoder(parent)
    new = continuation.SpanContinuationDecoder(checkpoint)
    rows = examples(new=True)
    texts, vectors = [row["source_text"] for row in rows], [row["latent"] for row in rows]
    before = old.decode_formal_logic(texts, vectors)
    after = new.decode_formal_logic(texts, vectors)
    assert [row["canonical_ir"] for row in before["rows"]] == [row["canonical_ir"] for row in after["rows"]]
    records, _, _ = span._records(rows, 384)
    with torch.no_grad():
        expected = old.model(*span._batch(torch, records))
        actual = new.model(*span._batch(torch, records))
    assert all(torch.equal(expected[key], actual[key]) for key in expected)
    assert after["checkpoint_sha256"] == continuation.checkpoint_digest(checkpoint)
    assert after["base_checkpoint_sha256"] == span.checkpoint_digest(checkpoint["base_checkpoint"])


@pytest.mark.parametrize("enabled", [False, True])
def test_resume_preserves_exact_child_adam_and_immutable_parent(parent, enabled):
    checkpoint = initial(parent, latent_enabled=enabled)
    before = copy.deepcopy(checkpoint)
    whole = continuation.train_decoder(checkpoint, examples(new=True), max_steps=6)
    first = continuation.train_decoder(checkpoint, examples(new=True), max_steps=3)
    resumed = continuation.train_decoder(first["checkpoint"], examples(new=True), max_steps=3)
    assert checkpoint == before
    for field in ("model_state", "optimizer_state", "progress"):
        assert whole["checkpoint"]["base_checkpoint"][field] == resumed["checkpoint"]["base_checkpoint"][field]
    assert resumed["checkpoint"]["source_parent_checkpoint"] == parent
    assert resumed["checkpoint"]["source_parent_checkpoint_sha256"] == checkpoint["source_parent_checkpoint_sha256"]
    assert resumed["checkpoint"]["parent_checkpoint_sha256"] == continuation.checkpoint_digest(first["checkpoint"])
    assert resumed["report"]["optimizer_steps"] == 3
    assert resumed["report"]["continuation_optimizer_steps_total"] == 6
    assert continuation.optimizer_steps(resumed["checkpoint"]) == 6
    names = whole["report"]["changed_parameter_names"]
    assert "byte_embedding.weight" in names and "start.weight" in names
    if enabled:
        assert "latent_up.weight" in names and "latent_down.weight" in names
    else:
        assert not any(name.startswith("latent_") for name in names)
    continuation.validate_checkpoint(resumed["checkpoint"])


def test_inference_receipts_isolation_and_latent_ablation(parent, monkeypatch):
    checkpoint = initial(parent)
    decoder = continuation.SpanContinuationDecoder(checkpoint)
    exposed = decoder.checkpoint
    exposed["source_parent_checkpoint_sha256"] = "0" * 64
    assert decoder.checkpoint == checkpoint
    def forbidden(*args, **kwargs):
        raise AssertionError("inference accessed supervision/training")
    monkeypatch.setattr(span, "_labels", forbidden)
    monkeypatch.setattr(continuation, "train_decoder", forbidden)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    rows = examples(new=True)
    result = decoder.decode_formal_logic([row["source_text"] for row in rows],
        [row["latent"] for row in rows], latent_ablation="disabled")
    assert result["schema"] == "warm-start-span-legal-formula-inference/v1"
    assert result["context_contract_sha256"] == checkpoint["context_contract_sha256"]
    assert all(not row["target_access"] and not row["teacher_forcing"] and not row["latent_input_enabled"]
               for row in result["rows"])
    assert all(result[key] is False for key in span.FALSE)
    assert "span_diagnostics" in result["rows"][0]


def test_source_parent_weights_context_manifests_and_lineage_tampering_reject(parent):
    checkpoint = initial(parent)
    broken = copy.deepcopy(checkpoint)
    broken["base_checkpoint"]["model_state"]["start.bias"][0] += .1
    with pytest.raises(ValueError, match="zero-update"):
        continuation.validate_checkpoint(broken)
    broken = copy.deepcopy(checkpoint)
    broken["source_parent_checkpoint"]["model_state"]["start.bias"][0] += .1
    with pytest.raises(ValueError, match="source parent hash"):
        continuation.validate_checkpoint(broken)
    broken = copy.deepcopy(checkpoint)
    broken["base_checkpoint"]["training_manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="initial continuation"):
        continuation.validate_checkpoint(broken)
    broken = copy.deepcopy(checkpoint)
    broken["context_contract"]["producer_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="context contract hash"):
        continuation.validate_checkpoint(broken)
    broken = copy.deepcopy(checkpoint)
    broken["initialization"]["mode"] = "from_scratch"
    with pytest.raises(ValueError, match="provenance"):
        continuation.validate_checkpoint(broken)
    changed = examples(new=True)
    changed[0]["latent"][0] += 1.
    with pytest.raises(ValueError, match="manifests differ"):
        continuation.train_decoder(checkpoint, changed, max_steps=1)
    with pytest.raises(ValueError, match="seed must match"):
        initial(parent, seed=24)


def test_outer_checkpoint_io_is_exclusive_hash_bound_and_contains_no_examples(parent, tmp_path):
    checkpoint = continuation.train_decoder(initial(parent), examples(new=True), max_steps=2)["checkpoint"]
    serialized = json.dumps(checkpoint)
    assert "The agency" not in serialized and "The municipality" not in serialized and "canonical_ir" not in serialized
    path = tmp_path / "continuation.json"
    receipt = continuation.save_checkpoint(checkpoint, path)
    assert continuation.load_checkpoint(path, expected_sha256=receipt["sha256"]) == checkpoint
    with pytest.raises(FileExistsError):
        continuation.save_checkpoint(checkpoint, path)
    with pytest.raises(ValueError, match="hash differs"):
        continuation.load_checkpoint(path, expected_sha256="0" * 64)
    broken = copy.deepcopy(checkpoint)
    broken["base_checkpoint"]["optimizer_state"]["parameters"]["start.bias"]["exp_avg_sq"][0] = -1
    with pytest.raises(ValueError):
        continuation.validate_checkpoint(broken)


def test_zero_update_call_preserves_warm_weights_and_records_chain(parent):
    checkpoint = initial(parent)
    result = continuation.train_decoder(checkpoint, examples(new=True), max_steps=0)
    assert not result["report"]["training_executed"]
    assert result["checkpoint"]["base_checkpoint"]["model_state"] == parent["model_state"]
    assert result["checkpoint"]["parent_checkpoint_sha256"] == continuation.checkpoint_digest(checkpoint)
    continuation.validate_checkpoint(result["checkpoint"])
