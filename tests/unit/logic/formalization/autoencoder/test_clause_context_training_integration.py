"""Explicit source-context integration controls; no corpus/qualification claims."""
from copy import deepcopy
import hashlib
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as subject
from .test_long_span_source_value_training import prepared


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


class ContextProbe(torch.nn.Module):
    """Small actual differentiable decoder exposing the explicit start seam."""
    def __init__(self):
        super().__init__()
        self.dimension = 8
        self.output = torch.nn.Linear(8, 5)
        self.seen = []
        with torch.no_grad():
            self.output.weight.zero_(); self.output.bias.zero_()
            self.output.bias[2] = 4.
            self.output.weight[3, 0] = .5

    def project(self, data):
        return data

    def start(self, projected, *, source_context=None):
        if source_context is None:
            raise ValueError("explicit source context required")
        self.seen.append(source_context)
        return projected + source_context["vectors"][:, 0]

    def next_logits(self, tokens, state):
        return self.output(state).unsqueeze(1).expand(-1, tokens.shape[1], -1), state

    def source_value_logits(self, projected, *, source_context=None):
        if source_context is None:
            raise ValueError("explicit source context required")
        self.seen.append(source_context)
        return self.output(source_context["vectors"]).unsqueeze(2).expand(-1, -1, 4, -1)


def tensor_context(batch=2):
    vectors = torch.zeros(batch, 8, 8)
    vectors[:, 0, 0] = torch.arange(1, batch+1, dtype=torch.float32)
    mask = torch.zeros(batch, 8, dtype=torch.bool); mask[:, 0] = True
    return dict(vectors=vectors, mask=mask)


def test_teacher_forced_and_greedy_core_pass_the_same_explicit_context():
    model = ContextProbe(); context = tensor_context(); data = torch.zeros(2, 8)
    prefix = torch.tensor([[1, 3], [1, 4]])
    projected, scores = core._logits(torch, model, data, prefix, 5, source_context=context)
    generated = core._greedy(torch, model, data, 8, 5, time.monotonic()+5, source_context=context)
    assert model.seen == [context, context]
    assert all(value is context for value in model.seen)
    assert torch.equal(projected, data) and torch.equal(scores[:, 0, 3], torch.tensor([.5, 1.]))
    assert generated[1:] == ([[], []], ["eos", "eos"])
    assert torch.equal(context["vectors"], tensor_context()["vectors"])


@pytest.mark.parametrize("operation", ["logits", "greedy"])
def test_context_required_decoder_cannot_silently_take_legacy_path(operation):
    model = ContextProbe(); data = torch.zeros(2, 8)
    with pytest.raises(ValueError, match="context required"):
        if operation == "logits": core._logits(torch, model, data, torch.ones(2, 1, dtype=torch.long), 5)
        else: core._greedy(torch, model, data, 8, 5, time.monotonic()+5)


def test_explicit_context_is_differentiable_through_teacher_forced_decoder():
    model = ContextProbe(); context = tensor_context(); data = torch.zeros(2, 8)
    context["vectors"].requires_grad_(True)
    _, scores = core._logits(torch, model, data, torch.ones(2, 1, dtype=torch.long), 5, source_context=context)
    torch.nn.functional.cross_entropy(scores[:, 0], torch.tensor([3, 3])).backward()
    assert model.output.weight.grad is not None and model.output.weight.grad.abs().sum() > 0
    assert context["vectors"].grad is not None and context["vectors"].grad[:, 0, 0].abs().sum() > 0
    assert not context["vectors"].grad[:, 1:].any()


def test_default_none_core_calls_preserve_legacy_logits_and_greedy_exactly():
    model, _, train, _, options = prepared()
    data, labels = core._batch(torch, train, options["input_transform"])
    size = len(options["codec"]["target_vocabulary"])
    before = core.tensor_digest(model)
    expected = core._logits(torch, model, data, labels[:, :-1], size)
    actual = core._logits(torch, model, data, labels[:, :-1], size, source_context=None)
    assert all(torch.equal(a, b) for a, b in zip(expected, actual))
    old = core._greedy(torch, model, data, 12, size, time.monotonic()+5)
    new = core._greedy(torch, model, data, 12, size, time.monotonic()+5, source_context=None)
    assert torch.equal(old[0], new[0]) and old[1:] == new[1:]
    assert core.tensor_digest(model) == before


def test_default_none_training_preserves_states_predictions_and_committed_losses():
    model, _, train, tune, options = prepared()
    before = core.tensor_digest(model)
    original = deepcopy((train, tune, options))
    kwargs = dict(cardinality_weight=.25, source_value_weight=.25, count_exposure="balanced_all", **options)
    expected = subject.train(model, train, tune, **kwargs)
    actual = subject.train(model, train, tune, source_contexts=None, **kwargs)
    for role in ("state_dict", "last_complete_attempt_state_dict"):
        assert set(expected[role]) == set(actual[role])
        assert all(torch.equal(value, actual[role][key]) for key, value in expected[role].items())
    for key in ("predictions", "last_complete_attempt_predictions"):
        assert expected[key] == actual[key]
    for key in ("committed_updates", "selected_epoch", "history", "gradient_norms", "stopped_reason"):
        assert expected["report"][key] == actual["report"][key]
    assert not any(key.startswith("source_context") for key in actual["report"])
    assert core.tensor_digest(model) == before and (train, tune, options) == original


@pytest.mark.parametrize("contexts", [{}, {"train": {}, "validation": {}}, [], True])
def test_legacy_model_rejects_unplanned_context_sidecar_before_private_copy(monkeypatch, contexts):
    model, _, train, tune, options = prepared()
    def guard_copy(value):
        if isinstance(value, torch.nn.Module): pytest.fail("private copy before context-model pairing")
        return deepcopy(value)
    monkeypatch.setattr(subject, "deepcopy", guard_copy)
    with pytest.raises(ValueError, match="model and explicit contexts must be paired"):
        subject.train(model, train, tune, source_value_weight=.25, source_contexts=contexts, **options)


@pytest.mark.parametrize("extra", [
    {"order_augmentation": {"preparation": {}, "embedding_observations": {}}},
    {"generated_boundary_weight": .25},
])
def test_context_training_rejects_unimplemented_optional_combinations_before_copy(monkeypatch, extra):
    model, _, train, tune, options = prepared()
    # Only the architecture precheck is substituted: this case tests rejection
    # before either unsupported option can prepare data or copy the model.
    monkeypatch.setattr(subject, "_head_specification", lambda *args: {"schema": "clause-source-decoder-development/v1"})
    monkeypatch.setattr(subject, "deepcopy", lambda value: pytest.fail("private copy before compatibility check"))
    with pytest.raises(ValueError, match="does not support order substitution or generated-boundary"):
        subject.train(model, train, tune, source_value_weight=.25,
            source_contexts={"train": {}, "validation": {}}, **options, **extra)


def probe_context_rows():
    from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context
    rows = [dict(id="source-"+str(i), source_text="Observable clause "+str(i)+".",
        input=[0.]*8, target_ids=[1, 3, 2]) for i in range(2)]
    cache = [dict(id="clause-"+str(i), source_text=row["source_text"],
        input=[float(j == i) for j in range(8)]) for i,row in enumerate(rows)]
    contexts = clause_source_context.build_source_contexts(
        [{key:row[key] for key in ("id", "source_text")} for row in rows], cache)
    codec = dict(target_vocabulary=["<pad>", "<bos>", "<eos>", '"a"', '"b"'])
    transform = dict(mode="none", origin="training_only", mean=[0.]*8, scale=1.)
    lineage = dict(teacher_checkpoint_sha256="a"*64, teacher_codec_sha256=core.digest(codec),
        input_provenance_sha256="b"*64, domain="legal_ir", teacher_lineage="synthetic-context",
        student_lineage="synthetic-context-test", teacher_output_limit=8, student_role="learned_formula_sidecar")
    return rows, contexts, codec, transform, lineage


def test_public_evaluation_batches_actual_context_for_both_losses_and_generation(monkeypatch):
    rows, contexts, codec, transform, lineage = probe_context_rows()
    rows = list(reversed(rows)); original_inputs = deepcopy((rows, contexts))
    model = ContextProbe(); original_start = ContextProbe.start; seen = []
    def capture(self, projected, *, source_context=None):
        assert set(source_context) == {"vectors", "mask"}
        seen.append(source_context["vectors"][:, 0].clone())
        return original_start(self, projected, source_context=source_context)
    monkeypatch.setattr(ContextProbe, "start", capture)
    before = core.tensor_digest(model)
    result = core.evaluate_model(model, rows, codec=codec, input_transform=transform,
        lineage=lineage, max_target_tokens=8, max_seconds=10, batch_size=1, source_contexts=contexts)
    assert result["report"]["complete"] and result["report"]["optimizer_steps"] == 0
    assert [row["id"] for row in result["predictions"]] == [row["id"] for row in rows]
    assert len(seen) == 4
    for actual, index in zip(seen, [1, 1, 0, 0]):
        assert torch.equal(actual, torch.tensor([[float(j == index) for j in range(8)]]))
    assert result["report"]["source_contexts_sha256"] == core.digest(contexts)
    assert result["report"]["generation_target_access"] is False
    assert result["report"]["source_context_target_access"] is False
    assert core.tensor_digest(model) == before and model.seen == []
    assert (rows, contexts) == original_inputs


def test_auxiliary_value_evaluation_uses_context_by_actual_batch_identity():
    rows, contexts, codec, transform, _ = probe_context_rows()
    rows = list(reversed(rows)); model = ContextProbe()
    labels = {row["id"]:[[3]*4]+[[-1]*4 for _ in range(7)] for row in rows}
    value = subject._source_value_evaluation(torch, model, rows, labels, transform,
        core._config(dict(batch_size=1)), codec, time.monotonic()+10, source_contexts=contexts)
    assert value["present_values"] == 8 and value["used_for_selection"] is False
    assert value["references_passed_to_model"] is False
    assert [row["id"] for row in value["predictions"]] == [row["id"] for row in rows]
    assert [row["raw_logits"][0][0][3] for row in value["predictions"]] == [0., .5]
    assert len(model.seen) == 2
    assert all(set(context) == {"vectors", "mask"} for context in model.seen)


def contextual_training_fixture():
    from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context as contexts_owner
    from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_decoder_experiment as clause_model
    from ipfs_datasets_py.logic.formalization.autoencoder import projected_source_decoder_experiment as projected
    from .test_long_span_cardinality_training import setup
    _, persistent, train, tune, options = setup(guide=True)
    cache = []; number = 0
    for split, rows, references in (("train", train, options["training_references"]),
                                    ("validation", tune, options["validation_references"])):
        for index, (row, reference) in enumerate(zip(rows, references)):
            clauses = []
            for position in range(index+1):
                text = split+" observable clause "+str(index)+"/"+str(position)+"."
                clauses.append(text)
                cache.append(dict(id="clause-cache-"+str(number), source_text=text,
                    input=[float(j == number) for j in range(8)]))
                number += 1
            row["source_text"] = reference["source_text"] = "\n\n".join(clauses)
    contexts = {split:contexts_owner.build_source_contexts(
        [{key:row[key] for key in ("id", "source_text")} for row in rows], cache)
        for split, rows in (("train", train), ("validation", tune))}
    kwargs = dict(expected_training_ids=[row["id"] for row in train],
        forbidden_validation_ids=[row["id"] for row in tune], training_rows_sha256=core.digest(train))
    with torch.no_grad(): paragraph_features = persistent.project(torch.tensor([row["input"] for row in train])).tolist()
    features = [dict(id=row["id"], source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),
        features=value) for row,value in zip(train, paragraph_features)]
    normalization = projected.fit_source_normalization(features, kind="center_rms", **kwargs)
    counts = [{key:value for key,value in row.items() if key != "features"} | {"count":index+1}
        for index,row in enumerate(features)]
    prior = projected.fit_source_count_prior(counts, **kwargs)
    donor = projected.bind_projected_source_model(persistent, codec=options["codec"],
        normalization_receipt=normalization, count_prior_receipt=prior, guide_boundary=True)
    unique = contexts_owner.unique_training_clauses(train, tune, contexts)
    inventory = contexts_owner.validate_training_contexts(train, tune, contexts)
    with torch.no_grad(): values = donor.project(torch.tensor([row["input"] for row in unique])).tolist()
    clause_rows = [dict(id=row["id"], source_sha256=row["source_sha256"], features=value)
        for row,value in zip(unique, values)]
    clause_norm = projected.fit_source_normalization(clause_rows, kind="center_rms",
        expected_training_ids=[row["id"] for row in unique], training_rows_sha256=core.digest(train),
        forbidden_validation_ids=[row["id"] for row in inventory["validation_clause_inventory"]])
    clause_norm["training_contexts_sha256"] = core.digest(contexts["train"])
    clause_norm["receipt_sha256"] = core.digest({key:value for key,value in clause_norm.items() if key != "receipt_sha256"})
    model = clause_model.bind_clause_source_model(donor, head_seed=1729, clause_normalization_receipt=clause_norm)
    return model, train, tune, options, contexts


def test_actual_clause_training_updates_head_with_bound_context_and_preserves_caller(monkeypatch):
    model, train, tune, options, contexts = contextual_training_fixture()
    before = core.tensor_digest(model); inputs = deepcopy((train, tune, options, contexts))
    observed = []; original = subject._source_value_logits
    def capture(t, working, projected, vocabulary_size, *, source_context=None):
        assert source_context is not None and set(source_context) == {"vectors", "mask"}
        assert not source_context["vectors"].requires_grad
        observed.append(source_context["mask"].sum(1).tolist())
        return original(t, working, projected, vocabulary_size, source_context=source_context)
    monkeypatch.setattr(subject, "_source_value_logits", capture)
    result = subject.train(model, train, tune, cardinality_weight=.25, source_value_weight=.25,
        count_exposure="balanced_all", source_contexts=contexts, **options)
    report = result["report"]; last = result["last_complete_attempt_state_dict"]
    assert report["optimizer_steps"] == 2 and report["source_value_presentations"] == 16
    assert observed and any(2 in counts for counts in observed)
    assert torch.count_nonzero(last["clause_head.field_readout.weight"]) > 0
    assert any(not torch.equal(value, last[name]) for name,value in model.named_parameters()
        if name.startswith("clause_head.") and name.endswith("source_projection.weight"))
    assert report["source_contexts_sha256"] == core.digest(contexts)
    assert report["source_context_target_access"] is False
    assert report["source_context_used_for_scalar_head_only"] is True
    for name, value in model.state_dict().items():
        if name in dict(model.named_buffers()) or name in report["frozen_parameter_names"]:
            assert torch.equal(value, last[name])
    assert core.tensor_digest(model) == before and (train, tune, options, contexts) == inputs
    assert all(report[key] is False for key in subject.FALSE)


def test_coherent_context_vector_replacement_cannot_reuse_old_normalization(monkeypatch):
    model, train, tune, options, contexts = contextual_training_fixture()
    from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context
    forged = deepcopy(contexts); segment = forged["train"][train[0]["id"]]["segments"][0]
    segment["vector"] = [0.]*6+[1.,0.]
    segment["embedding_sha256"] = core.digest(segment["vector"])
    # The changed descriptor remains self-consistent and split-safe; only its
    # mismatch against the model's fitted context provenance must reject it.
    clause_source_context.validate_training_contexts(train, tune, forged)
    def guard_copy(value):
        if isinstance(value, torch.nn.Module): pytest.fail("copied before normalization/context binding")
        return deepcopy(value)
    monkeypatch.setattr(subject, "deepcopy", guard_copy)
    with pytest.raises(ValueError, match="clause normalization receipt differs"):
        subject.train(model, train, tune, source_value_weight=.25, source_contexts=forged, **options)


def test_actual_clause_context_cannot_override_generated_actor_fidelity_regression(monkeypatch):
    from .test_long_span_cardinality_training import evaluated
    model, train, tune, options, contexts = contextual_training_fixture()
    observations = [evaluated(options, ce=2.), evaluated(options, ce=.1,
        mutate=lambda target:target["rules"][0].update(actor="agency"))]
    for value in observations: value["source_values"] = dict(cross_entropy=.01, predictions=[])
    observed = iter(observations)
    def evaluate(*args, source_contexts=None):
        assert source_contexts == contexts["validation"]
        return next(observed)
    monkeypatch.setattr(subject, "_evaluate", evaluate)
    options["curriculum"] = [dict(name="one", training_ids=[row["id"] for row in train], epochs=1)]
    result = subject.train(model, train, tune, cardinality_weight=.25, source_value_weight=.25,
        count_exposure="balanced_all", source_contexts=contexts, **options)
    assert result["report"]["selected_epoch"] == 0
    assert any("actor" in reason for reason in result["report"]["history"][0]["rejection_reasons"])
