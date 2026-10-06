"""Synthetic restoration/source-only boundaries, without retained asset files."""
from copy import deepcopy
import hashlib
import json

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_numeric as subject


@pytest.fixture(autouse=True)
def one_cpu():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


@pytest.fixture
def packet():
    core, persistent, native, projected, clauses, action, ordered, contexts = subject._owners()
    dimension = 384
    strings = ("actor", "action", "modality", "object", "conditions", "exceptions",
               "temporal", "rules", "O", "P", "F", "agency", "save", "report")
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=["<pad>", "<bos>", "<eos>"]
        + sorted({json.dumps(value) for value in strings} | set("{}[],:")))
    config = dict(seed=1729, hidden_size=8, token_embedding_dim=16, projection_width=2)
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(config["seed"])
        fixture = torch.nn.Module()
        fixture.projection_down = torch.nn.Linear(384, 2)
        fixture.projection_up = torch.nn.Linear(2, 384)
        fixture.condition = torch.nn.Linear(384, 8)
        fixture.target_embedding = torch.nn.Embedding(len(codec["target_vocabulary"]), 16, padding_idx=0)
        fixture.decoder = torch.nn.GRU(16, 8, batch_first=True)
        fixture.output = torch.nn.Linear(8, len(codec["target_vocabulary"]))
        donor = dict(codec=codec, config=config,
                     model_state={name: value.tolist() for name, value in fixture.state_dict().items()})
        raw = subject._raw_donor(torch, donor)
        body, initializer = native.bind_dimension_native_body(raw, dimension=dimension)
        feature_rows = [dict(id=f"train-{i}", source_sha256=hashlib.sha256(str(i).encode()).hexdigest(),
            features=[float(index == i) for index in range(dimension)]) for i in range(4)]
        keywords = dict(expected_training_ids=[row["id"] for row in feature_rows],
            forbidden_validation_ids=["validation"], training_rows_sha256="a" * 64)
        normalization = projected.fit_source_normalization(feature_rows, kind="center_rms", **keywords)
        count_rows = [{key: row[key] for key in ("id", "source_sha256")} | dict(count=i+1)
                      for i, row in enumerate(feature_rows)]
        prior = projected.fit_source_count_prior(count_rows, **keywords)
        clause_features = [{**row, "id": "clause:" + row["source_sha256"]} for row in feature_rows]
        clause_normalization = projected.fit_source_normalization(clause_features,
            kind="center_rms", expected_training_ids=[row["id"] for row in clause_features],
            forbidden_validation_ids=["clause:" + "c" * 64], training_rows_sha256="a" * 64)
        clause_normalization["training_contexts_sha256"] = "b" * 64
        clause_normalization["receipt_sha256"] = core.digest({k: v for k, v in clause_normalization.items()
                                                              if k != "receipt_sha256"})
        transform = dict(mode="center_rms", mean=[.1] * dimension, scale=2., origin="training_only")
        preprocessing = dict(initializer=initializer, input_transform=transform,
            paragraph_normalization=normalization, clause_normalization=clause_normalization,
            count_prior=prior)
        model = persistent.bind_persistent_model(body, dimension=dimension)
        model = projected.bind_projected_source_model(model, codec=codec,
            normalization_receipt=normalization, count_prior_receipt=prior,
            guide_boundary=True, scalar_guidance=True)
        model = clauses.bind_clause_source_model(model, head_seed=1729,
                                                 clause_normalization_receipt=clause_normalization)
        model = action.bind_action_factorized_clause_model(model, codec=codec)
        model = ordered.bind_ordered_clause_recurrent_model(model, codec=codec)
        architecture = model.describe()
        with torch.no_grad():
            model.body.body.body.output.weight.zero_()
            model.body.body.body.output.bias.zero_()
            model.body.body.body.output.bias[2] = 100.
        serialized = {name: value.tolist() for name, value in model.state_dict().items()}
        checkpoint = dict(schema="private-native-dimension-source-state/v1", dimension=dimension,
            selected=True, role="selected", codec=codec, input_transform=transform,
            initializer_receipt=initializer, architecture=architecture, model_state=serialized,
            weights_sha256=core.digest(serialized), tensor_sha256=core.tensor_digest(model),
            qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False)
    rows = [dict(id="source-1", source_text="agency saves report", input=[1.] + [0.] * 383)]
    context = contexts.build_source_contexts(
        [dict(id=rows[0]["id"], source_text=rows[0]["source_text"])], rows)
    return dict(checkpoint=checkpoint, preprocessing=preprocessing, donor_checkpoint=donor), {
        "rows": rows, "contexts": context}


def test_complete_restore_generation_preserves_rng_weights_and_inputs_without_fit_or_optimizer(packet, monkeypatch):
    prepared, inputs = packet
    saved = deepcopy((prepared, inputs))
    owners = subject._owners()

    def forbidden(*args, **kwargs):
        raise AssertionError("training/fitting path invoked")

    monkeypatch.setattr(owners[3], "fit_source_normalization", forbidden)
    monkeypatch.setattr(owners[3], "fit_source_count_prior", forbidden)
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(torch.optim, "AdamW", forbidden)
    rng = torch.get_rng_state().clone()
    restored = subject.restore_contextual_legal_model(prepared)
    assert torch.equal(rng, torch.get_rng_state())
    report = subject.infer_contextual_legal_model(restored, inputs)
    assert report["predictions"] == [dict(id="source-1", token_ids=[], eos_reached=True,
                                          generation_status="eos")]
    assert report["completed"] and report["ambient_rng_preserved"] and report["weights_unchanged"]
    assert all(report[key] is False for key in subject._FALSE)
    assert (prepared, inputs) == saved
    assert report["model_tensor_sha256_before"] == report["model_tensor_sha256_after"]
    assert torch.equal(rng, torch.get_rng_state())


def test_nested_projection_preflight_refuses_mutation_even_with_updated_serialized_digest(packet):
    prepared, _ = packet
    core = subject._owners()[0]
    prepared["checkpoint"]["model_state"]["body.body.body.projection_up.bias"][0] = .25
    prepared["checkpoint"]["weights_sha256"] = core.digest(prepared["checkpoint"]["model_state"])
    rng = torch.get_rng_state().clone()
    with pytest.raises(ValueError, match="frozen native projection differs"):
        subject.restore_contextual_legal_model(prepared)
    assert torch.equal(rng, torch.get_rng_state())


def test_restoration_uses_explicit_cpu_float32_without_changing_caller_default_dtype(packet):
    prepared, inputs = packet
    before = torch.get_default_dtype()
    try:
        torch.set_default_dtype(torch.float64)
        restored = subject.restore_contextual_legal_model(prepared)
        assert all(value.device.type == "cpu" and
                   (not value.is_floating_point() or value.dtype == torch.float32)
                   for value in restored.model.state_dict().values())
        subject.infer_contextual_legal_model(restored, inputs)
        assert torch.get_default_dtype() == torch.float64
    finally:
        torch.set_default_dtype(before)


@pytest.mark.parametrize("mutation", ["missing", "boolean_seed", "wrong_seed", "donor"])
def test_strict_state_donor_and_integer_scalar_restore(packet, mutation):
    prepared, _ = packet
    core = subject._owners()[0]
    if mutation == "missing":
        prepared["checkpoint"]["model_state"].pop("ordered_clause_recurrent_version")
    elif mutation == "boolean_seed":
        prepared["checkpoint"]["model_state"]["head_initialization_seed"] = True
    elif mutation == "wrong_seed":
        prepared["checkpoint"]["model_state"]["head_initialization_seed"] = 1728
    else:
        prepared["donor_checkpoint"]["model_state"]["output.bias"][0] += .1
    prepared["checkpoint"]["weights_sha256"] = core.digest(prepared["checkpoint"]["model_state"])
    with pytest.raises(ValueError):
        subject.restore_contextual_legal_model(prepared)


@pytest.mark.parametrize("mutation", ["target", "reference", "extra_context", "mixed_width", "bad_offset"])
def test_closed_source_only_input_refuses_targets_and_broken_cache_binding(packet, mutation):
    prepared, inputs = packet
    restored = subject.restore_contextual_legal_model(prepared)
    if mutation == "target":
        inputs["rows"][0]["target_ids"] = [1, 2]
    elif mutation == "reference":
        inputs["reference"] = {"rules": []}
    elif mutation == "extra_context":
        inputs["contexts"]["extra"] = deepcopy(inputs["contexts"]["source-1"])
    elif mutation == "mixed_width":
        inputs["rows"][0]["input"].append(0.)
    else:
        inputs["contexts"]["source-1"]["segments"][0]["char_end"] += 1
    with pytest.raises(ValueError):
        subject.infer_contextual_legal_model(restored, inputs)


def test_transform_real_clauses_before_zero_padding_and_internal_feature_normalization(packet, monkeypatch):
    prepared, inputs = packet
    restored = subject.restore_contextual_legal_model(prepared)
    core = subject._owners()[0]
    original = core._greedy

    def observe(torch_arg, model, data, *args, source_context, **kwargs):
        expected = (torch.tensor(inputs["rows"][0]["input"]) - .1) / 2.
        assert torch.equal(data[0], expected)
        assert torch.equal(source_context["vectors"][0, 0], expected)
        assert not bool(source_context["vectors"][0, 1:].any())
        assert source_context["mask"].dtype == torch.bool
        assert source_context["mask"].tolist() == [[True] + [False] * 7]
        return original(torch_arg, model, data, *args, source_context=source_context, **kwargs)

    monkeypatch.setattr(core, "_greedy", observe)
    subject.infer_contextual_legal_model(restored, inputs)


def test_deadline_reports_raw_unfinished_rows_and_mutated_model_refused(packet, monkeypatch):
    prepared, inputs = packet
    restored = subject.restore_contextual_legal_model(prepared)
    ticks = iter([0., 1., 2.])
    monkeypatch.setattr(subject.time, "monotonic", lambda: next(ticks))
    report = subject.infer_contextual_legal_model(restored, inputs, deadline_seconds=.01)
    assert report["predictions"][0]["generation_status"] == "deadline"
    assert not report["completed"] and not report["predictions"][0]["eos_reached"]
    with torch.no_grad():
        restored.model.action_head.field_readout.bias[0] += 1.
    with pytest.raises(ValueError, match="model changed before inference"):
        subject.infer_contextual_legal_model(restored, inputs)
