"""Native-width benchmark contracts using synthetic tensors, never checkpoints."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core

ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "scripts/ops/autoencoder/benchmark_native_dimension_source_training.py"
SPEC = importlib.util.spec_from_file_location("_native_dimension_runner_contract", PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False))
    return dict(path=str(path), sha256=subject.sha(path), bytes=path.stat().st_size)


@pytest.mark.parametrize("field,value", [
    ("dimensions", [8, 384]), ("fit_count", 4), ("source_seed", 2718),
    ("expected_optimizer_steps_per_arm", 339), ("expected_row_presentations_per_arm", 2439),
    ("expected_training_token_presentations_per_arm", 225839),
    ("expected_count_presentations_per_arm", 2439), ("expected_source_value_presentations_per_arm", 25599),
    ("historical_linguistic_teacher_modified", True), ("source_routes_reset", False),
    ("identity_projection_frozen", False), ("identity_mse_is_not_learned_reconstruction", False),
    ("source_independent_donor_tensors_copied", False), ("dimension_only_ablation", True),
    ("same_representation_within_paired_arms", False), ("teacher_distillation_used", True),
    ("fixed_encoder_context_tokens", 8192), ("fixed_decoder_output_limit", 1024),
    ("temperature", 1), ("selection_unchanged", False), ("full_vocabulary_retained", False),
    ("syntax_forced", True), ("closure_forced", True), ("production_promotion_allowed", True),
    ("generation_reference_count_access", True), ("encoder_executed_during_training", True),
    ("no_downloads", False), ("learning_rate", .01), ("count_exposure", "stage_only"),
])
def test_plan_rejects_changed_budget_inputs_or_authority(field, value):
    plan = deepcopy(subject.FIXED)
    subject.validate_plan(plan)
    plan[field] = value
    with pytest.raises(ValueError, match="fixed native-dimension"):
        subject.validate_plan(plan)


@pytest.mark.parametrize("mutation", [
    lambda p: p["dimensions"].__setitem__(0, 8.),
    lambda p: p["arms"][0].__setitem__("generated_boundary_weight", False),
    lambda p: p["arms"][1].__setitem__("order_augmentation", 0),
    lambda p: p["expected_balanced_count_presentations"].__setitem__("1", 610.),
    lambda p: p["postfit_controls"][0].__setitem__(2, "zero_condition"),
])
def test_plan_deep_types_and_control_labels_are_exact(mutation):
    plan = deepcopy(subject.FIXED)
    mutation(plan)
    with pytest.raises(ValueError, match="fixed native-dimension"):
        subject.validate_plan(plan)


def test_jobs_cover_all_twelve_paired_fits_with_no_shared_recipe_mutation():
    values = subject.jobs()
    assert [(d, s, a["name"]) for d, s, a in values] == [
        (d, s, a) for d in (8, 384, 768) for s in (1729, 2718) for a in ("pooled", "clauses")]
    values[0][2]["name"] = "mutated"
    assert subject.jobs()[0][2]["name"] == "pooled"
    assert values[2][2]["name"] == "pooled"
    assert len(subject.CONTROLS) * 2 * len(values) == 192
    assert all(value is False for value in subject.FALSE.values())


def manifest_fixture(tmp_path, monkeypatch, *, complete=True, bind_inputs=True):
    inputs = tmp_path / "dimension-inputs.json"
    source_inputs = {"complete": complete, "dimensions": {}}
    source_inputs["inputs_sha256"] = core.digest(source_inputs)
    write_json(inputs, source_inputs)
    parent_manifest, parent_plan = tmp_path / "prior-manifest.json", tmp_path / "prior-plan.json"
    write_json(parent_manifest, {})
    write_json(parent_plan, {})
    bound = {str(path): subject.sha(path) for path in (parent_manifest, parent_plan)}
    if bind_inputs:
        bound[str(inputs)] = subject.sha(inputs)
    plan = tmp_path / "plan.json"
    write_json(plan, dict(subject.FIXED, input_sha256=bound))
    manifest = tmp_path / "manifest.json"
    write_json(manifest, dict(plan_sha256=subject.sha(plan), inputs=bound,
        dimension_inputs=str(inputs), parent_manifest=str(parent_manifest),
        parent_plan=str(parent_plan), extensions={}))
    calls = []
    ctx = dict(rows={"train": [], "validation": []}, donor={"codec": {}}, owners={}, core=core,
        helpers=SimpleNamespace(extension=lambda *args: calls.append(("owner", args)) or "native-owner"))
    previous = SimpleNamespace(load_context=lambda args: calls.append(("parent", args)) or ctx)
    monkeypatch.setattr(subject, "load_helper", lambda *args: previous)
    args = SimpleNamespace(manifest=manifest, plan=plan, extension_root=tmp_path,
        dependency_root=tmp_path, output=tmp_path / "output", phase="training")
    return args, inputs, calls


def test_complete_source_inputs_are_read_through_hash_bound_manifest(tmp_path, monkeypatch):
    args, inputs, calls = manifest_fixture(tmp_path, monkeypatch)
    ctx = subject.load_context(args)
    assert ctx["dimension_inputs"]["complete"] is True
    assert ctx["original_rows"] == ctx["rows"] and ctx["original_rows"] is not ctx["rows"]
    assert ctx["original_donor"] == ctx["donor"] and ctx["original_donor"] is not ctx["donor"]
    assert ctx["owners"]["dimension_native_decoder_experiment"] == "native-owner"
    assert calls[0][0] == "parent"
    assert calls[0][1].manifest.name == "prior-manifest.json"
    assert calls[0][1].plan.name == "prior-plan.json"


@pytest.mark.parametrize("complete", [False, None, 1, "true"])
def test_incomplete_source_producer_cannot_start_training(tmp_path, monkeypatch, complete):
    args, _, _ = manifest_fixture(tmp_path, monkeypatch, complete=complete)
    with pytest.raises(ValueError, match="complete dimension source"):
        subject.load_context(args)


def test_unlisted_dimension_input_alias_cannot_bypass_provenance(tmp_path, monkeypatch):
    args, _, _ = manifest_fixture(tmp_path, monkeypatch, bind_inputs=False)
    with pytest.raises(ValueError, match="input|bound|manifest"):
        subject.load_context(args)


def test_changed_source_input_bytes_abort_before_parent_or_owner_load(tmp_path, monkeypatch):
    args, inputs, calls = manifest_fixture(tmp_path, monkeypatch)
    inputs.write_text('{"complete":true,"changed":true}')
    with pytest.raises(ValueError, match="input changed"):
        subject.load_context(args)
    assert calls == []


def test_helper_source_hash_is_checked_before_execution(tmp_path):
    helper = tmp_path / "helper.py"
    helper.write_text("raise RuntimeError('must not execute')\n")
    with pytest.raises(ValueError, match="frozen helper differs"):
        subject.load_helper(tmp_path, {"helper.py": "0" * 64}, "helper.py", "_wrong_native_helper")


def vector(dimension, index):
    angle = .0041 * (index + 1)
    return [math.cos(angle), math.sin(angle)] + [0.] * (dimension - 2)


class Identity:
    def __init__(self):
        self.seen = []

    def project(self, values):
        self.seen.append(values.detach().clone())
        return values


def preparation_context(dimension):
    calls = {"build": [], "normalize": [], "prior": [], "native": []}
    rows = {split: [dict(id=f"{split}-{i:02}", source_text=f"{split} literal source {i}",
        input=vector(dimension, i + shift)) for i in range(48)]
        for split, shift in (("train", 0), ("validation", 100))}
    originals = {split: [dict(row, input=[42.], target_ids=[1, i + 3, 2]) for i, row in enumerate(values)]
        for split, values in rows.items()}
    binding = {"training": {"dimension": dimension}, "validation": {"dimension": dimension},
        "training_clause_inventory": [dict(id=f"clause-train-{i}") for i in range(113)],
        "validation_clause_inventory": [dict(id=f"clause-validation-{i}") for i in range(54)]}
    unique = [dict(id=f"clause-train-{i}", input=vector(dimension, 200 + i),
        source_sha256=hashlib.sha256(f"train-clause-{i}".encode()).hexdigest()) for i in range(113)]

    def build(values, cache):
        assert all(set(row) == {"id", "source_text"} for row in values)
        calls["build"].append((deepcopy(values), cache))
        return {row["id"]: {"cache": cache} for row in values}

    def normalize(features, **kwargs):
        calls["normalize"].append((deepcopy(features), deepcopy(kwargs)))
        return dict(kind=kwargs["kind"], mean=[0.] * dimension, scale=1., receipt_sha256="synthetic")

    def prior(counts, **kwargs):
        calls["prior"].append((deepcopy(counts), deepcopy(kwargs)))
        return {"training_counts": deepcopy(counts)}

    identity = Identity()
    body = object()

    def bind(raw, **kwargs):
        assert raw is body
        calls["native"].append(kwargs)
        return identity, {"synthetic_native_recipe": dimension}

    # Owners are intentionally not deepcopyable: preparation must not copy modules.
    class Owner(SimpleNamespace):
        def __deepcopy__(self, memo):
            raise AssertionError("producer objects must be shared, not deep-copied")

    source_owner = Owner(build_source_contexts=build, validate_training_contexts=lambda *args: binding,
        unique_training_clauses=lambda *args: unique)
    owners = {"clause_source_context": source_owner,
        "dimension_native_decoder_experiment": Owner(bind_dimension_native_body=bind),
        "projected_source_decoder_experiment": Owner(fit_source_normalization=normalize, fit_source_count_prior=prior)}
    data = dict(rows, clause_cache={"train": "train-cache", "validation": "validation-cache"},
        representation={"kind": f"synthetic-{dimension}", "semantic_qualification": False})
    ctx = dict(owners=owners, core=core, original_rows=originals,
        original_donor={"input_transform": {"old": True}, "codec": {}},
        dimension_inputs={"dimensions": {str(dimension): data}}, base_model=SimpleNamespace(body=body),
        lineage={"original": True}, references={"train": [dict(id=r["id"], source_sha256="a" * 64,
            clause_count=(1, 2, 4, 8)[i % 4]) for i, r in enumerate(rows["train"])]})
    return ctx, calls, identity, binding, unique


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_dimension_preparation_fits_only_training_sources_and_preserves_original_targets(dimension):
    ctx, calls, identity, binding, unique = preparation_context(dimension)
    original = deepcopy((ctx["original_rows"], ctx["original_donor"], ctx["dimension_inputs"]))
    lane = subject.prepare_dimension(ctx, dimension)
    assert lane["owners"] is ctx["owners"] and lane["core"] is core
    assert calls["native"] == [{"dimension": dimension, "source_seed": 1729}]
    for split in ("train", "validation"):
        assert [r["target_ids"] for r in lane["rows"][split]] == [r["target_ids"] for r in ctx["original_rows"][split]]
        assert all(len(r["input"]) == dimension for r in lane["rows"][split])
        assert all(r["target_ids"] is not o["target_ids"] for r, o in zip(lane["rows"][split], ctx["original_rows"][split]))
    matrix = torch.tensor([r["input"] for r in lane["rows"]["train"]], dtype=torch.float32)
    mean = matrix.mean(0)
    scale = max(float((matrix - mean).square().sum(1).mean().sqrt()), .01)
    transform = lane["donor"]["input_transform"]
    assert transform == {"mode": "center_rms", "mean": mean.tolist(), "scale": scale, "origin": "training_only"}
    assert torch.equal(identity.seen[0], (matrix - mean) / scale)
    assert torch.equal(identity.seen[1], subject.transformed_rows(torch, unique, transform))
    paragraph, clause = calls["normalize"]
    assert len(paragraph[0]) == 48 and len(clause[0]) == 113
    assert paragraph[1]["expected_training_ids"] == [r["id"] for r in lane["rows"]["train"]]
    assert paragraph[1]["forbidden_validation_ids"] == [r["id"] for r in lane["rows"]["validation"]]
    assert clause[1]["expected_training_ids"] == [r["id"] for r in unique]
    assert clause[1]["forbidden_validation_ids"] == [r["id"] for r in binding["validation_clause_inventory"]]
    assert paragraph[1]["training_rows_sha256"] == clause[1]["training_rows_sha256"] == core.digest(lane["rows"]["train"])
    assert calls["prior"][0][1] == {k: v for k, v in paragraph[1].items() if k != "kind"}
    assert [r["count"] for r in calls["prior"][0][0]] == [r["clause_count"] for r in ctx["references"]["train"]]
    assert lane["clause_normalization"]["training_contexts_sha256"] == core.digest(lane["source_contexts"]["train"])
    assert lane["preparation"]["representation"] == ctx["dimension_inputs"]["dimensions"][str(dimension)]["representation"]
    assert lane["preparation"]["projection_policy"] == "frozen_identity_no_learned_reconstruction_claim"
    assert lane["lineage"]["student_role"] == "learned_formula_sidecar"
    assert not any(lane["preparation"][key] for key in subject.FALSE)
    assert (ctx["original_rows"], ctx["original_donor"], ctx["dimension_inputs"]) == original


@pytest.mark.parametrize("mutation,message", [
    (lambda d: d["train"].pop(), "coverage/order"),
    (lambda d: d["validation"].reverse(), "coverage/order"),
    (lambda d: d["train"][0].__setitem__("target_ids", [99]), "closed source-only"),
    (lambda d: d["train"][0].__setitem__("source_text", "changed source"), "source changed"),
    (lambda d: d["validation"][0].__setitem__("input", d["train"][0]["input"]), "vector split overlap"),
])
def test_preparation_rejects_relabeling_target_leak_and_split_collision_before_model_binding(mutation, message):
    ctx, calls, _, _, _ = preparation_context(8)
    mutation(ctx["dimension_inputs"]["dimensions"]["8"])
    with pytest.raises(ValueError, match=message):
        subject.prepare_dimension(ctx, 8)
    assert calls["native"] == []


def test_preparation_rejects_nonidentity_projection_before_normalization():
    ctx, calls, identity, _, _ = preparation_context(8)
    identity.project = lambda values: values + 1.
    with pytest.raises(ValueError, match="identity projection differs"):
        subject.prepare_dimension(ctx, 8)
    assert calls["normalize"] == []


@pytest.mark.parametrize("dimension", [8, 384, 768])
@pytest.mark.parametrize("recipe", subject.ARMS)
def test_native_binding_keeps_count_guidance_full_source_head_and_native_width(dimension, recipe):
    calls = []
    raw, persistent, projected = object(), object(), object()
    def bind_persistent(body, **kwargs):
        assert body is raw
        calls.append(("persistent", kwargs))
        return persistent
    def bind_projected(body, **kwargs):
        assert body is persistent
        calls.append(("projected", kwargs))
        return projected
    def head(kind):
        def bind(body, **kwargs):
            assert body is projected
            calls.append((kind, kwargs))
            return kind
        return bind
    ctx = dict(raw_initializer=raw, dimension=dimension, donor={"codec": {"v": "same"}},
        preprocessing={"normalizations": {"center_rms": "paragraph-stats"}, "count_prior": "count-prior"},
        clause_normalization="clause-stats", adapter=SimpleNamespace(bind_persistent_model=bind_persistent),
        owners={"projected_source_decoder_experiment": SimpleNamespace(bind_projected_source_model=bind_projected),
            "shared_slot_source_decoder_experiment": SimpleNamespace(bind_shared_slot_source_model=head("pooled")),
            "clause_source_decoder_experiment": SimpleNamespace(bind_clause_source_model=head("clauses"))})
    assert subject.bind_candidate(ctx, recipe, 1729) == recipe["name"]
    assert calls[0] == ("persistent", {"dimension": dimension, "conditioning": "every_step"})
    assert calls[1] == ("projected", dict(codec=ctx["donor"]["codec"], normalization_receipt="paragraph-stats",
        count_prior_receipt="count-prior", guide_boundary=True, scalar_guidance=True))
    assert calls[2][1] == ({"head_seed": 1729} if recipe["name"] == "pooled" else
        {"head_seed": 1729, "clause_normalization_receipt": "clause-stats"})


class InitialModel:
    def __init__(self, contextual):
        self.contextual = contextual
        key = "clause_head.weight" if contextual else "body.source_value_head.weight"
        self.parameters_by_name = {key: torch.nn.Parameter(torch.zeros(3)),
            "decoder.weight": torch.nn.Parameter(torch.ones(2))}
        if not contextual:
            self.parameters_by_name["body.source_value_head.slot_embeddings"] = torch.nn.Parameter(torch.zeros(8, 64))
        self.buffers_by_name = {"body.source_mean": torch.tensor([.1, .2]),
            "head_initialization_seed": torch.tensor(1729, dtype=torch.long)}
        if contextual:
            self.buffers_by_name["clause_source_mean"] = torch.zeros(2)

    def named_parameters(self):
        return self.parameters_by_name.items()

    def parameters(self):
        return self.parameters_by_name.values()

    def named_buffers(self):
        return self.buffers_by_name.items()


def initial_context(monkeypatch, *, contextual=True):
    ctx, _, _, _, _ = preparation_context(8)
    calls = []
    baseline, model = InitialModel(False), InitialModel(contextual)
    def greedy(torch, active, data, limit, vocabulary, deadline, **kwargs):
        calls.append((active, data, limit, vocabulary, deadline, kwargs))
        return data, [[3, 4] for _ in data], ["eos" for _ in data]
    def source_kwargs(torch, part, contexts, transform):
        assert all(set(r) == {"id", "source_text", "input", "target_ids"} for r in part)
        return {} if contexts is None else {"source_context": [r["id"] for r in part]}
    ctx.update(dimension=8, rows=ctx["original_rows"],
        core=SimpleNamespace(_greedy=greedy, _source_context_kwargs=source_kwargs),
        donor={"input_transform": {"mean": [0.], "scale": 1.}, "codec": {"target_vocabulary": ["a", "b", "c"]}},
        source_contexts={"train": "train-context", "validation": "validation-context"},
        clause_runner=SimpleNamespace(contextual=lambda value: value.contextual))
    monkeypatch.setattr(subject, "bind_candidate", lambda *args: baseline)
    return ctx, model, baseline, calls


@pytest.mark.parametrize("contextual", [False, True])
def test_initial_comparison_checks_all_source_rows_unchanged_buffers_and_exact_parameter_delta(monkeypatch, contextual):
    ctx, model, baseline, calls = initial_context(monkeypatch, contextual=contextual)
    value = subject.validate_initial(ctx, model, 1729)
    assert value["complete"] and len(calls) == 12
    assert [p["split"] for p in value["predictions"]] == ["train", "validation"]
    assert all(len(p["predictions"]) == 48 for p in value["predictions"])
    assert all(call[0] is model and len(call[1]) == 8 and call[2:4] == (512, 3) for call in calls)
    assert all(bool(call[-1]) == contextual for call in calls)
    assert value["trainable_parameters"] - value["baseline_trainable_parameters"] == (-512 if contextual else 0)
    assert value["inherited_buffers_equal"] and value["identity_projection_is_not_learned_reconstruction"]
    assert not any(value[k] for k in subject.FALSE)


@pytest.mark.parametrize("mutation,message", [
    (lambda m: m.parameters_by_name["clause_head.weight"].data.fill_(1), "parameters differ"),
    (lambda m: m.parameters_by_name["decoder.weight"].requires_grad_(False), "parameters differ"),
    (lambda m: m.parameters_by_name.__setitem__("unexpected", torch.nn.Parameter(torch.zeros(1))), "parameters differ"),
    (lambda m: m.buffers_by_name["head_initialization_seed"].fill_(2718), "inherited buffer differs"),
    (lambda m: m.buffers_by_name.pop("body.source_mean"), "inherited buffer differs"),
])
def test_initialization_drift_aborts_before_any_greedy_observation(monkeypatch, mutation, message):
    ctx, model, _, calls = initial_context(monkeypatch)
    mutation(model)
    with pytest.raises(ValueError, match=message):
        subject.validate_initial(ctx, model, 1729)
    assert calls == []


@pytest.mark.parametrize("incomplete", [True, False])
def test_initial_greedy_requires_completion_and_identity_projection(monkeypatch, incomplete):
    ctx, model, _, _ = initial_context(monkeypatch)
    ctx["core"]._greedy = lambda torch, model, data, *args, **kwargs: (None if incomplete else
        (data + 1., [[3] for _ in data], ["eos" for _ in data]))
    with pytest.raises(ValueError, match="identity projection or generation differs"):
        subject.validate_initial(ctx, model, 1729)


def test_wrapper_projection_is_preflighted_from_only_the_exact_raw_body_prefix():
    raw, receipt = object(), object()
    seen = []
    ctx = dict(raw_initializer=raw, initializer_receipt=receipt,
        owners={"dimension_native_decoder_experiment": SimpleNamespace(
            validate_restored_state=lambda *args: seen.append(args))})
    state = {"body.body.body.projection_up.weight": torch.zeros(2, 3),
        "body.body.body.condition.bias": torch.zeros(2), "body.source_mean": torch.zeros(2),
        "head_initialization_seed": torch.tensor(1729, dtype=torch.long)}
    subject.validate_wrapper_state(ctx, state)
    assert seen == [(raw, receipt, {"projection_up.weight": state["body.body.body.projection_up.weight"],
        "condition.bias": state["body.body.body.condition.bias"]})]


def state_context(tmp_path, *, corrupt_restore=False):
    events = []
    class StateModel:
        def __init__(self):
            self.values = {"body.body.body.projection_up.weight": torch.zeros(2, 3),
                "body.body.body.condition.bias": torch.tensor([.25, -.5]),
                "head_initialization_seed": torch.tensor(1729, dtype=torch.long)}
        def state_dict(self):
            return self.values
        def describe(self):
            return {"synthetic_private_model": True}
        def load_state_dict(self, restored, strict):
            events.append("load")
            assert strict is True
            self.values = {k: v.clone() for k, v in restored.items()}
    model = StateModel()
    def restore(ctx, saved, template):
        events.append("restore")
        result = {k: torch.tensor(saved[k], dtype=value.dtype) for k, value in template.items()}
        if corrupt_restore:
            result["body.body.body.projection_up.weight"][0, 0] = 1.
        return result
    def preflight(raw, receipt, values):
        events.append("preflight")
        assert raw is model and receipt == {"frozen": True}
        if not torch.equal(values["projection_up.weight"], torch.zeros(2, 3)):
            raise ValueError("frozen projection changed before restore")
    ctx = dict(core=SimpleNamespace(digest=core.digest,
        tensor_digest=lambda m: core.digest({k: {"dtype": str(v.dtype), "value": v.tolist()} for k, v in m.state_dict().items()})),
        dimension=8, initializer_receipt={"frozen": True}, raw_initializer=model,
        donor={"input_transform": {"mode": "none"}, "codec": {"original": True}}, lineage={"sidecar": True},
        helpers=SimpleNamespace(save=write_json), clause_runner=SimpleNamespace(restored_tensors=restore),
        owners={"dimension_native_decoder_experiment": SimpleNamespace(validate_restored_state=preflight)})
    return ctx, model, events


def test_saved_state_keeps_mixed_tensor_types_and_checks_projection_before_loading(tmp_path):
    ctx, model, events = state_context(tmp_path)
    before = ctx["core"].tensor_digest(model)
    path = tmp_path / "initial-state.json"
    value = subject.save_state(ctx, model, subject.ARMS[0], "initial", False, path)
    saved = json.loads(path.read_bytes())
    assert events == ["restore", "preflight", "load"]
    assert value["tensor_sha256"] == saved["tensor_sha256"] == ctx["core"].tensor_digest(model) == before
    assert type(saved["model_state"]["head_initialization_seed"]) is int
    assert model.state_dict()["head_initialization_seed"].dtype == torch.long
    assert saved["dimension"] == 8 and saved["schema"] == "private-native-dimension-source-state/v1"
    assert saved["weights_sha256"] == core.digest(saved["model_state"])
    assert saved["selected"] is False and saved["optimizer_resumable"] is False
    assert all(saved[k] is False for k in subject.FALSE)


def test_corrupt_frozen_projection_aborts_without_partial_wrapper_mutation(tmp_path):
    ctx, model, events = state_context(tmp_path, corrupt_restore=True)
    before = ctx["core"].tensor_digest(model)
    with pytest.raises(ValueError, match="frozen projection changed"):
        subject.save_state(ctx, model, subject.ARMS[0], "initial", False, tmp_path / "bad-state.json")
    assert events == ["restore", "preflight"]
    assert ctx["core"].tensor_digest(model) == before
