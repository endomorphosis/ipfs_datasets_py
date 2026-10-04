"""Compare unchanged v1 weights through serial and batched readout.

Synthetic vectors and injected output cases test numerical/validation contracts;
they provide no semantic qualification, source fidelity, or Lake admission.
"""
from copy import deepcopy
import hashlib

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as base
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder_v2 as v2
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_batched_inference as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as legal


@pytest.fixture(scope="module")
def parent():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        binding = dict(domain="legal_ir", lineage_id="current_legal_v2", dimension=384,
            runtime_profile="synthetic-batching-unit-test/v1", core_sha256="a" * 64)
        rows = [dict(id="legal-training", source_text="The agency must save the report.",
            latent=[.5] + [0.] * 383, embedding=[.3] + [0.] * 383,
            canonical_ir={"rules": [dict(modality="O", actor="agency", action="save", object="report",
                conditions=[], exceptions=[], temporal=[])]})]
        checkpoint = legal.build_checkpoint(binding, rows, [], hidden_size=16,
            token_embedding_dim=8, projection_width=4, batch_size=1)
        return legal.train(checkpoint, rows, [], epochs=1, max_seconds=30)["checkpoint"]
    finally:
        torch.set_num_threads(previous)


def target(domain):
    if domain == "intent_ir":
        return dict(kind="intent_rich_ast", document=dict(kind="atom", actor="operator", action="save",
            object="report", modality="required"))
    if domain == "ui_ux_ir":
        return dict(kind="ui_component", document=dict(component_id="submit", role="button"))
    return dict(kind="program_expression", document=dict(expression_id="expr:one", kind="literal",
        type_ref="integer", attributes={"value": 1}, source_ref_ids=["authored-source"]))


def authored_row(domain, split, value):
    return dict(id=split, source_text=split + " authored source", embedding=[value] + [0.] * 383,
        target=target(domain))


@pytest.fixture(scope="module", params=base.DOMAINS)
def trained(request, parent):
    domain = request.param
    before = deepcopy(parent)
    result = base.train(domain, [authored_row(domain, "train", .4)],
        [authored_row(domain, "validation", .6)], parent_projection=parent,
        config=dict(epochs=20, batch_size=1, max_seconds=30, patience=20, max_target_tokens=64))
    assert parent == before
    return result["checkpoint"]


def inference_rows():
    return [dict(id=f"inference-{i}", source_text=f"Authored inference source {i}",
        embedding=[.2 + i / 10., .01 * i] + [0.] * 382) for i in range(5)]


@pytest.mark.parametrize("batch_size", [1, 2, 3, 64])
def test_serial_and_batched_readout_preserve_tokens_eos_and_embeddings(trained, batch_size):
    checkpoint_before = deepcopy(trained)
    source = inference_rows()
    original = base.Runtime(trained).infer(source)
    previous = torch.get_num_threads()
    adapted = api.Runtime(trained, batch_size=batch_size)
    actual = adapted.infer(source)
    assert torch.get_num_threads() == previous
    assert trained == checkpoint_before == adapted.checkpoint
    assert len(actual["rows"]) == len(original["rows"]) == 5
    assert actual["checkpoint_schema"] == base.SCHEMA
    assert adapted.checkpoint["config"]["max_target_tokens"] == 64
    for expected, observed in zip(original["rows"], actual["rows"]):
        for key in ("id", "source_sha256", "generated_tokens", "ended", "weights_sha256"):
            assert observed[key] == expected[key]
        assert len(observed["generated_tokens"]) <= 63
        assert observed["reconstructed_embedding"] == pytest.approx(
            expected["reconstructed_embedding"], rel=1e-5, abs=1e-6)
        assert observed["candidate_ir"] == expected["candidate_ir"]
        assert not observed["target_access"] and not observed["teacher_forcing"]
        assert all(observed[key] is False for key in api.FALSE)
    description = adapted.describe()
    assert description["weights_sha256"] == trained["weights_sha256"]
    assert description["inference_batch_size"] == batch_size
    assert description["checkpoint_schema"] == base.SCHEMA
    assert description["weights_modified"] is False
    assert description["training_executed"] is False
    assert description["checkpoint_migrated"] is False
    assert description["embedding_provenance_verified_by_runtime"] is False
    assert actual["inference_memory_estimate"]["estimated_tensor_bytes"] <= 512 * 1024**2


@pytest.mark.parametrize("ablation", ["zero_decoder", "zero_projection", "zero_condition"])
def test_ablation_matches_serial_readout_and_does_not_mutate_weights(trained, ablation):
    runtime = api.Runtime(trained, batch_size=3)
    inputs = inference_rows()
    before = runtime.infer(inputs)
    expected = base.Runtime(trained).infer(inputs, weight_ablation=ablation)
    actual = runtime.infer(inputs, weight_ablation=ablation)
    for a, b in zip(expected["rows"], actual["rows"]):
        assert a["generated_tokens"] == b["generated_tokens"] and a["ended"] == b["ended"]
        assert a["reconstructed_embedding"] == pytest.approx(b["reconstructed_embedding"], rel=1e-5, abs=1e-6)
        if ablation == "zero_decoder":
            assert b["candidate_ir"] is None and not b["native_semantic_valid"]
    assert runtime.infer(inputs) == before


def test_target_free_inputs_and_checkpoint_default_batch_are_preserved(trained):
    runtime = api.Runtime(trained)
    assert runtime.describe()["inference_batch_size"] == trained["config"]["batch_size"]
    inputs = inference_rows()
    before = runtime.infer(inputs)["rows"]
    with pytest.raises(ValueError, match="closed domain row"):
        runtime.infer([{**inputs[0], "target": target(trained["domain_id"])}])
    changed = deepcopy(inputs)
    for row in changed:
        row["source_text"] += " different provenance"
    after = runtime.infer(changed)["rows"]
    for a, b in zip(before, after):
        assert a["source_sha256"] != b["source_sha256"]
        for key in ("generated_tokens", "ended", "reconstructed_embedding", "candidate_ir"):
            assert a[key] == b[key]
    with pytest.raises(ValueError, match="unknown weight ablation"):
        runtime.infer(inputs, weight_ablation="invented")
    with pytest.raises(ValueError, match="384"):
        runtime.infer([{**inputs[0], "embedding": [0.] * 8}])


def test_loading_checks_digest_domain_schema_and_authority(trained, tmp_path):
    original = base._raw(trained)
    path = tmp_path / "parent-v1.json"; path.write_bytes(original)
    sha = hashlib.sha256(original).hexdigest()
    runtime = api.load_checkpoint(path, expected_sha256=sha,
        expected_domain=trained["domain_id"], batch_size=3)
    assert runtime.describe()["inference_batch_size"] == 3
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match="bytes differ"):
        api.load_checkpoint(path, expected_sha256="0" * 64, expected_domain=trained["domain_id"])
    with pytest.raises(ValueError, match="another domain"):
        api.load_checkpoint(path, expected_sha256=sha, expected_domain="legal_ir")
    changed = deepcopy(trained); changed["schema"] = v2.SCHEMA
    with pytest.raises(ValueError, match="closed domain checkpoint"):
        api.Runtime(changed)
    changed = deepcopy(trained); changed["qualified"] = True
    with pytest.raises(ValueError, match="authority"):
        api.Runtime(changed)
    changed = deepcopy(trained); changed["model_state"]["projection_up.bias"][0] += .1
    with pytest.raises(ValueError, match="weight digest"):
        api.Runtime(changed)
    link = tmp_path / "linked.json"; link.symlink_to(path)
    with pytest.raises(ValueError, match="regular checkpoint"):
        api.load_checkpoint(link, expected_sha256=sha, expected_domain=trained["domain_id"])


@pytest.mark.parametrize("options", [{"batch_size": 0}, {"batch_size": 65}, {"batch_size": True},
    {"memory_budget_bytes": True}, {"memory_budget_bytes": 0}, {"memory_budget_bytes": 9 * 1024**3}])
def test_resource_options_are_bounded_before_inference(trained, options):
    with pytest.raises(ValueError, match="invalid inference"):
        api.Runtime(trained, **options)


def test_tensor_reservation_prevents_oversized_inference(trained, monkeypatch):
    runtime = api.Runtime(trained, batch_size=64, memory_budget_bytes=1024**2)
    def forbidden(*args, **kwargs):
        pytest.fail("generation must not start after memory reservation fails")
    monkeypatch.setattr(api.batches, "_generate", forbidden)
    with pytest.raises(ValueError, match="reservation exceeds budget"):
        runtime.infer(inference_rows())


def test_malformed_config_none_fails_with_validation_error(trained):
    malformed = deepcopy(trained)
    malformed["config"] = None
    with pytest.raises(ValueError):
        api.Runtime(malformed)


def test_ablation_memory_reservation_precedes_weight_copy(trained, monkeypatch):
    runtime = api.Runtime(trained, batch_size=64, memory_budget_bytes=1024**2)
    def forbidden(*args, **kwargs):
        pytest.fail("ablation weights must not be copied before memory reservation")
    monkeypatch.setattr(api, "deepcopy", forbidden)
    with pytest.raises(ValueError, match="reservation exceeds budget"):
        runtime.infer(inference_rows(), weight_ablation="zero_decoder")


@pytest.mark.parametrize("field,value", [("privacy_sensitivity", "interactive"),
                                        ("presentation_classification", "restricted")])
def test_ui_cross_field_invalid_output_is_retained_without_native_credit(trained, monkeypatch, field, value):
    if trained["domain_id"] != "ui_ux_ir":
        pytest.skip("UI contract applies to UI only")
    candidate = target("ui_ux_ir")
    candidate["document"][field] = value
    assert base.validate_target("ui_ux_ir", candidate)["valid"]
    original = api.batches._generate
    def injected(*args, **kwargs):
        generated = original(*args, **kwargs)
        for row in generated:
            row.update(generated_tokens=base._tokens(candidate), ended=True)
        return generated
    monkeypatch.setattr(api.batches, "_generate", injected)
    observed = api.Runtime(trained, batch_size=2).infer(inference_rows())["rows"][0]
    assert observed["raw_candidate_ir"] == candidate
    assert observed["native_envelope_valid"] is True
    assert observed["candidate_ir"] is None and observed["native_semantic_valid"] is False
    assert observed["status"] == "invalid_generated_output"
    assert "closed vocabulary" in observed["reason"]
    assert all(observed[key] is False for key in api.FALSE)


def test_source_guard_rejects_changed_adapter(trained, monkeypatch):
    runtime = api.Runtime(trained)
    previous = api._implementation
    def changed():
        result = previous(); result["adapter"] = "0" * 64
        return result
    monkeypatch.setattr(api, "_implementation", changed)
    with pytest.raises(ValueError, match="producer changed"):
        runtime.infer(inference_rows())


def test_mixed_eos_bos_pad_and_length_limit_match_serial_termination(trained):
    """Scripted logits isolate termination bookkeeping, not learned fidelity."""
    vocabulary = trained["codec"]["target_vocabulary"]
    brace = vocabulary.index("{")
    class Scripted(torch.nn.Module):
        def project(self, data):
            return data
        def start(self, projected):
            return torch.stack((projected[:, 0], torch.zeros(len(projected))))
        def next_logits(self, current, hidden):
            marker, step = hidden
            # 0: immediate EOS, 1: one token then EOS, 2: invalid BOS,
            # 3: reaches the unchanged cap, 4: invalid PAD.
            index = torch.full((len(marker),), brace, dtype=torch.long)
            index[(marker == 0) | ((marker == 1) & (step >= 1))] = 2
            index[marker == 2] = 1
            index[marker == 4] = 0
            logits = torch.zeros((len(marker), 1, len(vocabulary)))
            logits[torch.arange(len(marker)), 0, index] = 10.
            return logits, torch.stack((marker, step + 1))
    inputs = inference_rows()
    for index, row in enumerate(inputs):
        row["embedding"][0] = float(index)
    serial, batched = base.Runtime(trained), api.Runtime(trained, batch_size=5)
    serial.model, batched.model = Scripted(), Scripted()
    expected, actual = serial.infer(inputs)["rows"], batched.infer(inputs)["rows"]
    assert [row["ended"] for row in actual] == [True, True, False, False, False]
    assert [len(row["generated_tokens"]) for row in actual] == [0, 1, 0, 63, 0]
    for a, b in zip(expected, actual):
        assert a["generated_tokens"] == b["generated_tokens"]
        assert a["ended"] == b["ended"]
        assert a["reconstructed_embedding"] == b["reconstructed_embedding"]
        assert b["candidate_ir"] is None and b["native_semantic_valid"] is False
