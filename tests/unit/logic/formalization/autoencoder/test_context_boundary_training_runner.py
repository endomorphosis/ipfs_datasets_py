"""Contextual boundary training contracts; synthetic checks grant no qualification."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from .test_ordered_clause_recurrent_training_runner import real_fixture


ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location("_context_boundary_runner_tests",
    ROOT / "scripts/ops/autoencoder/benchmark_context_boundary_training.py")
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False))


@pytest.mark.parametrize("field,value", [
    ("dimensions", [8, 384]), ("fit_count", 12), ("fresh_initialization", False),
    ("selection_unchanged", False), ("fixed_encoder_context_tokens", 1024),
    ("fixed_decoder_output_limit", 1024), ("temperature", .1),
    ("validation_pairs_added_to_training", True), ("teacher_distillation_used", True),
    ("generated_boundary_gradient_scope", "count_head_only"),
    ("boundary_labels_after_source_only_rollout", False),
    ("generated_boundary_vocabulary_policy", "binary_stop_continue"),
    ("full_vocabulary_retained", False), ("syntax_forced", True), ("closure_forced", True),
    ("no_downloads", False), ("baseline_replay_required", False),
    ("expected_optimizer_steps_per_arm", 339), ("recurrent_parameter_delta", 2048),
    ("generation_reference_count_access", True), ("production_promotion_allowed", True),
])
def test_fixed_comparison_cannot_change_authority_context_or_objective_scope(field, value):
    plan = deepcopy(subject.FIXED)
    subject.validate_plan(plan)
    plan[field] = value
    with pytest.raises(ValueError, match="fixed context-boundary"):
        subject.validate_plan(plan)


def test_registered_eighteen_jobs_isolate_weight_and_sampling_policy():
    jobs = subject.jobs()
    assert [(dimension, seed, arm["name"]) for dimension, seed, arm in jobs] == [
        (dimension, seed, name) for dimension in (8, 384, 768) for seed in (1729, 2718)
        for name in ("recurrent-clause", "boundary-first-last", "boundary-first-wrong")]
    assert len(jobs) == 18
    assert [(arm["generated_boundary_weight"], arm["generated_boundary_site_policy"])
            for _, _, arm in jobs[:3]] == [(0., "first_last"), (.05, "first_last"), (.05, "first_wrong")]
    assert all(arm["recurrent"] and arm["factorized"] and arm["action_contrastive_weight"] == .05
        and not arm["order_augmentation"] for _, _, arm in jobs)
    jobs[0][2]["generated_boundary_weight"] = .9
    assert subject.jobs()[0][2]["generated_boundary_weight"] == 0.
    assert all(value is False for value in subject.FALSE.values())


def context_fixture(tmp_path, monkeypatch):
    parent_manifest, parent_plan = tmp_path / "parent-manifest.json", tmp_path / "parent-plan.json"
    write(parent_manifest, {})
    write(parent_plan, {})
    inputs = {str(path): subject.sha(path) for path in (parent_manifest, parent_plan)}
    summaries = {}
    for dimension in (8, 384, 768):
        for seed in (1729, 2718):
            name = f"{dimension}-recurrent-clause-{seed}"
            report = tmp_path / name / "training.json"
            write(report, {"selected_epoch": 0, "generated_boundary_weight": None})
            inputs[str(report)] = subject.sha(report)
            panels = {}
            for role in ("selected", "last-attempt"):
                panels[role] = {}
                for label in [*[row[0] for row in subject.CONTROLS], "recurrent-residual-off"]:
                    path = tmp_path / name / role / (label + ".json")
                    write(path, {"predictions": [{"id": "v", "token_ids": [3]}]})
                    inputs[str(path)] = subject.sha(path)
                    panels[role][label] = {"path": str(path), "sha256": subject.sha(path)}
            summary = tmp_path / name / "summary.json"
            write(summary, {"arm": name, "budget_completed": True,
                "training_ref": {"path": str(report), "sha256": subject.sha(report)}, "postfit": panels})
            inputs[str(summary)] = subject.sha(summary)
            summaries[name] = str(summary)
    plan = tmp_path / "plan.json"
    write(plan, dict(subject.FIXED, input_sha256=inputs))
    manifest = tmp_path / "manifest.json"
    write(manifest, dict(inputs=inputs, plan_sha256=subject.sha(plan), extensions={},
        parent_manifest=str(parent_manifest), parent_plan=str(parent_plan), baseline_summaries=summaries))
    calls = []
    context = dict(owners={}, helpers=SimpleNamespace(
        extension=lambda *args: calls.append(("extension", args)) or object()))
    native = SimpleNamespace(load_context=lambda args: calls.append(("parent", args)) or context)
    monkeypatch.setattr(subject, "load_helper", lambda *args: native)
    args = SimpleNamespace(manifest=manifest, plan=plan, dependency_root=tmp_path,
        extension_root=tmp_path, output=tmp_path / "out", phase="training")
    return args, calls, summaries


def test_context_dereferences_six_immutable_training_and_all_control_panels(tmp_path, monkeypatch):
    args, calls, summaries = context_fixture(tmp_path, monkeypatch)
    context = subject.load_context(args)
    assert set(context["baseline_runs"]) == set(summaries)
    assert calls[0][0] == "parent"
    assert set(context["owners"]) == {"action_factorized_clause_decoder_experiment",
        "action_contrastive_decoder_training", "ordered_clause_recurrent_decoder_experiment",
        "contextual_generated_boundary_training"}
    for record in context["baseline_runs"].values():
        assert record["training"]["selected_epoch"] == 0
        assert all(len(panels) == 9 for panels in record["postfit"].values())
        assert all("predictions" in panel for panels in record["postfit"].values() for panel in panels.values())


@pytest.mark.parametrize("mutation", ["unbound_report", "bad_report_hash", "changed_panel", "unbound_panel", "wrong_arm", "incomplete"])
def test_unbound_or_changed_predecessor_evidence_is_rejected(tmp_path, monkeypatch, mutation):
    args, _, summaries = context_fixture(tmp_path, monkeypatch)
    manifest = json.loads(args.manifest.read_text())
    name, summary_path = next(iter(summaries.items()))
    summary_path = Path(summary_path)
    summary = json.loads(summary_path.read_text())
    if mutation == "unbound_report":
        manifest["inputs"].pop(summary["training_ref"]["path"])
    elif mutation == "bad_report_hash":
        summary["training_ref"]["sha256"] = "0" * 64
    elif mutation == "changed_panel":
        write(Path(summary["postfit"]["selected"]["validation"]["path"]), {"predictions": []})
    elif mutation == "unbound_panel":
        manifest["inputs"].pop(summary["postfit"]["selected"]["validation"]["path"])
    elif mutation == "wrong_arm":
        summary["arm"] = "other"
    elif mutation == "incomplete":
        summary["budget_completed"] = False
    write(summary_path, summary)
    manifest["inputs"][str(summary_path)] = subject.sha(summary_path)
    plan = json.loads(args.plan.read_text())
    plan["input_sha256"] = manifest["inputs"]
    write(args.plan, plan)
    manifest["plan_sha256"] = subject.sha(args.plan)
    write(args.manifest, manifest)
    with pytest.raises(ValueError):
        subject.load_context(args)


def test_three_candidates_use_the_same_fresh_architecture_and_training_recipe():
    binds, fits = [], []
    model = object()
    native = SimpleNamespace(ARMS=[None, {"head_kind": "clauses"}],
        bind_candidate=lambda *args: binds.append(args) or model)
    context = dict(native_runner=native, donor=dict(codec={}, input_transform={}),
        rows=dict(train=[{"id": "t"}], validation=[{"id": "v"}]),
        references=dict(train=[{"id": "t"}], validation=[{"id": "v"}]),
        lineage={}, source_contexts={"train": {}, "validation": {}}, stages=[],
        validate_rule=lambda rule: rule, validator_id="test", owners={
            "action_factorized_clause_decoder_experiment": SimpleNamespace(bind_action_factorized_clause_model=lambda value, **kwargs: value),
            "ordered_clause_recurrent_decoder_experiment": SimpleNamespace(bind_ordered_clause_recurrent_model=lambda value, **kwargs: value),
            "long_span_source_value_training": SimpleNamespace(train=lambda *args, **kwargs: fits.append((args, kwargs)))})
    for arm in subject.ARMS:
        assert subject.bind_candidate(context, arm, 1729) is model
        subject.train_candidate(context, model, 1729, arm)
    assert len(binds) == len(fits) == 3
    assert all(call[1:] == binds[0][1:] for call in binds)
    common = [{key: value for key, value in kwargs.items()
        if key not in ("generated_boundary_weight", "generated_boundary_site_policy")} for _, kwargs in fits]
    common = deepcopy(common)
    assert "max_memory_bytes" not in common[0]["config"]
    assert common[1]["config"].pop("max_memory_bytes") == common[2]["config"].pop("max_memory_bytes") == 1073741824
    assert common[0] == common[1] == common[2]
    assert common[0]["config"]["max_target_tokens"] == 512
    assert common[0]["config"]["max_seconds"] == 180
    assert common[0]["action_contrastive_weight"] == .05


def replay_fixture():
    report = dict(elapsed_seconds=1., selected_weights_sha256="selected", last_complete_attempt_weights_sha256="final",
        history=[dict(accepted=False, selected_epoch=0)], action_contrastive_weight=.05,
        config=dict(max_seconds=180))
    panels = {role: {label: dict(predictions=[dict(id="v1", token_ids=[1, 2])])
        for label in [*[row[0] for row in subject.CONTROLS], "recurrent-residual-off"]}
        for role in ("selected", "last-attempt")}
    context = dict(core=core, dimension=8,
        baseline_runs={"8-recurrent-clause-1729": dict(training=deepcopy(report), postfit=deepcopy(panels))})
    return context, report, panels


def test_baseline_replay_excludes_only_elapsed_time():
    context, report, panels = replay_fixture()
    report["elapsed_seconds"] = 999.
    assert subject.validate_baseline(context, report, panels, 1729)["complete"]
    report["action_contrastive_weight"] = .1
    with pytest.raises(ValueError, match="baseline replay differs"):
        subject.validate_baseline(context, report, panels, 1729)


@pytest.mark.parametrize("role", ["selected", "last-attempt"])
@pytest.mark.parametrize("label", ["validation", "context-rotate", "recurrent-residual-off"])
def test_baseline_replay_includes_residual_off_and_source_controls(role, label):
    context, report, panels = replay_fixture()
    panels[role][label]["predictions"][0]["token_ids"] = [1, 5, 2]
    with pytest.raises(ValueError, match="control predictions"):
        subject.validate_baseline(context, report, panels, 1729)


@pytest.fixture
def one_cpu():
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def fit(model, train, tune, options, contexts, **extra):
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    return trainer.train(model, train, tune, source_contexts=contexts,
        source_value_weight=.25, cardinality_weight=.25, count_exposure="balanced_all",
        action_contrastive_weight=.05, **options, **extra)


def fake_context_boundary(monkeypatch, *, empty=False, expired=False, loss_expired=False):
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as boundary
    seen = []

    def collect(model, rows, **kwargs):
        assert all(set(row) == {"id", "input", "source_text"} for row in rows)
        assert set(kwargs["source_contexts"]) == {row["id"] for row in rows}
        assert all(row["id"].startswith("train-") for row in rows)
        assert not ({"site_policy", "training_counts_by_id", "training_references", "validation_references"} & set(kwargs))
        seen.append({"rows": deepcopy(rows), "contexts": deepcopy(kwargs["source_contexts"]),
            "loss_kwargs": None, "model": model})
        if expired:
            raise TimeoutError("synthetic contextual boundary collection deadline")
        return {"rows": rows}

    def loss(torch, model, collection, counts, **kwargs):
        assert all(identity.startswith("train-") for identity in counts)
        assert all(row["id"] in counts for row in collection["rows"])
        assert set(kwargs["source_contexts"]) == {row["id"] for row in collection["rows"]}
        assert all(type(count) is int and 1 <= count <= 32 for count in counts.values())
        seen[-1]["loss_kwargs"] = deepcopy(kwargs)
        parameter = next(parameter for parameter in model.parameters() if parameter.requires_grad)
        if loss_expired:
            parameter.grad = torch.ones_like(parameter)
            raise TimeoutError("synthetic contextual replay deadline")
        value = parameter.square().mean() + .125
        return dict(loss=None if empty else value, receipt=dict(synthetic=True,
            row_ids=[row["id"] for row in collection["rows"]],
            training_counts={row["id"]: counts[row["id"]] for row in collection["rows"]},
            selection_policy=kwargs["site_policy"], mean_loss=None if empty else float(value.detach())))

    monkeypatch.setattr(boundary, "collect_source_boundary_prefixes", collect)
    monkeypatch.setattr(boundary, "generated_boundary_loss", loss)
    return seen


def test_zero_baseline_skips_both_boundary_owners_and_keeps_report(monkeypatch, one_cpu):
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as contextual
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_boundary_training as legacy
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    for owner in (contextual, legacy):
        monkeypatch.setattr(owner, "collect_source_boundary_prefixes",
            lambda *args, **kwargs: pytest.fail("zero boundary weight invoked collector"))
    ordinary = fit(model, train, tune, options, contexts)
    explicit = fit(model, train, tune, options, contexts,
        generated_boundary_weight=0., generated_boundary_site_policy="first_last")
    fields = set(ordinary["report"]) - {"elapsed_seconds"}
    assert fields == set(explicit["report"]) - {"elapsed_seconds"}
    assert all(core.digest(ordinary["report"][key]) == core.digest(explicit["report"][key]) for key in fields)
    assert not any(key.startswith("generated_boundary_") for key in explicit["report"])
    for role in ("state_dict", "last_complete_attempt_state_dict"):
        assert all(value.equal(explicit[role][key]) for key, value in ordinary[role].items())


@pytest.mark.parametrize("policy", ["first_last", "first_wrong"])
def test_training_context_and_labels_reach_separate_optional_loss(monkeypatch, one_cpu, policy):
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_boundary_training as legacy
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    original = deepcopy((train, tune, options, contexts))
    before = core.tensor_digest(model)
    seen = fake_context_boundary(monkeypatch)
    monkeypatch.setattr(legacy, "collect_source_boundary_prefixes",
        lambda *args, **kwargs: pytest.fail("contextual training used the legacy collector"))
    result = fit(model, train, tune, options, contexts,
        generated_boundary_weight=.05, generated_boundary_site_policy=policy)
    report = result["report"]
    assert len(seen) == report["optimizer_steps"] == 2
    assert core.tensor_digest(model) == before
    assert (train, tune, options, contexts) == original
    assert report["generated_boundary_used_for_selection"] is False
    assert report["selection"] == "per_length_nonregression_then_fidelity_progress_then_reference_ce"
    counts = {row["id"]: row["clause_count"] for row in options["training_references"]}
    for update, call in zip(report["committed_updates"], seen):
        assert update["decoder_row_ids"] == [row["id"] for row in call["rows"]]
        assert call["contexts"] == {row["id"]: contexts["train"][row["id"]] for row in call["rows"]}
        assert call["loss_kwargs"]["site_policy"] == policy
        assert call["loss_kwargs"].get("gradient_scope", "all_trainable") == "all_trainable"
        receipt = update["generated_boundary"]
        assert receipt["training_counts"] == {row["id"]: counts[row["id"]] for row in call["rows"]}
        expected = update["weighted_token_ce"] + report["config"]["reconstruction_weight"] * update["raw_reconstruction_mse"]
        expected += .25 * update["count_ce"] + .25 * update["source_value_ce"]
        expected += .05 * update["action_contrastive"]["loss"] + .05 * receipt["mean_loss"]
        assert update["objective"] == pytest.approx(expected, abs=1e-6)


def test_no_sites_attach_no_graph_and_preserve_ordinary_updates(monkeypatch, one_cpu):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    ordinary = fit(model, train, tune, options, contexts)
    fake_context_boundary(monkeypatch, empty=True)
    empty = fit(model, train, tune, options, contexts,
        generated_boundary_weight=.05, generated_boundary_site_policy="first_wrong")
    for role in ("state_dict", "last_complete_attempt_state_dict"):
        assert all(value.equal(empty[role][key]) for key, value in ordinary[role].items())
    assert ordinary["predictions"] == empty["predictions"]
    assert ordinary["last_complete_attempt_predictions"] == empty["last_complete_attempt_predictions"]
    assert all(update["generated_boundary"]["mean_loss"] is None for update in empty["report"]["committed_updates"])


@pytest.mark.parametrize("phase", ["collection", "loss"])
def test_boundary_deadline_cannot_commit_partial_context_update(monkeypatch, one_cpu, phase):
    torch = pytest.importorskip("torch")
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    before = core.tensor_digest(model)
    seen = fake_context_boundary(monkeypatch, expired=phase == "collection", loss_expired=phase == "loss")
    monkeypatch.setattr(torch.optim.AdamW, "step", lambda *args, **kwargs: pytest.fail("deadline called optimizer.step"))
    result = fit(model, train, tune, options, contexts,
        generated_boundary_weight=.05, generated_boundary_site_policy="first_wrong")
    assert result["report"]["optimizer_steps"] == 0
    assert result["report"]["stopped_reason"] == "deadline_during_generated_boundary"
    assert result["report"]["committed_updates"] == []
    assert result["report"]["row_presentations"] == result["report"]["count_training_row_presentations"] == 0
    assert all(parameter.grad is None for parameter in seen[0]["model"].parameters())
    assert core.tensor_digest(model) == before
    assert all(value.equal(result["state_dict"][key]) for key, value in model.state_dict().items())


def test_deadline_after_backward_retains_prior_complete_state_without_stream_commit(monkeypatch, one_cpu):
    torch = pytest.importorskip("torch")
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    seen = fake_context_boundary(monkeypatch)
    expired = [False]
    original_clock = trainer.time.monotonic
    original_clip = torch.nn.utils.clip_grad_norm_

    def clip(*args, **kwargs):
        value = original_clip(*args, **kwargs)
        expired[0] = True
        return value

    monkeypatch.setattr(trainer, "time", SimpleNamespace(monotonic=lambda: original_clock() + (1000. if expired[0] else 0.)))
    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", clip)
    monkeypatch.setattr(torch.optim.AdamW, "step", lambda *args, **kwargs: pytest.fail("expired update called optimizer.step"))
    result = fit(model, train, tune, options, contexts,
        generated_boundary_weight=.05, generated_boundary_site_policy="first_wrong")
    report = result["report"]
    assert expired[0] and report["stopped_reason"] == "deadline"
    assert report["optimizer_steps"] == report["row_presentations"] == report["count_training_row_presentations"] == 0
    assert report["valid_target_token_presentations"] == report["source_value_presentations"] == 0
    assert report["committed_updates"] == [] and report["selected_epoch"] == 0
    assert all(parameter.grad is None for parameter in seen[0]["model"].parameters())
    assert all(value.equal(result["state_dict"][key]) for key, value in model.state_dict().items())


@pytest.mark.parametrize("policy", [None, True, [], "all", "first", "validation_error"])
def test_unknown_site_policy_rejected_before_copy(monkeypatch, one_cpu, policy):
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(trainer, "deepcopy", lambda value: pytest.fail("copied before policy validation"))
    with pytest.raises(ValueError, match="policy"):
        fit(model, train, tune, options, contexts,
            generated_boundary_weight=.05, generated_boundary_site_policy=policy)


@pytest.mark.parametrize("policy", ["first_last", "first_wrong"])
def test_small_real_contextual_training_uses_helper_without_validation_inputs(monkeypatch, one_cpu, policy):
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as boundary
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    before = core.tensor_digest(model)
    original_collect, original_loss = boundary.collect_source_boundary_prefixes, boundary.generated_boundary_loss
    observations = []

    def collect(model, rows, **kwargs):
        assert all(set(row) == {"id", "input", "source_text"} for row in rows)
        assert set(kwargs["source_contexts"]) == {row["id"] for row in rows}
        assert all(row["id"].startswith("train-") for row in rows)
        assert "training_counts_by_id" not in kwargs and "site_policy" not in kwargs
        return original_collect(model, rows, **kwargs)

    def loss(torch, model, collection, counts, **kwargs):
        assert set(counts) == {row["id"] for row in train}
        result = original_loss(torch, model, collection, counts, **kwargs)
        observations.append(result["receipt"])
        return result

    monkeypatch.setattr(boundary, "collect_source_boundary_prefixes", collect)
    monkeypatch.setattr(boundary, "generated_boundary_loss", loss)
    result = fit(model, train, tune, options, contexts,
        generated_boundary_weight=.05, generated_boundary_site_policy=policy)
    report = result["report"]
    assert report["optimizer_steps"] == len(observations) == 2
    assert core.tensor_digest(model) == before
    assert report["generation_temperature"] == 0 and report["generated_boundary_used_for_selection"] is False
    for receipt in observations:
        assert receipt["selection_policy"] == policy
        assert receipt["reference_counts_used_only_in_loss"]
        assert receipt["full_vocabulary_cross_entropy"]
        assert not receipt["target_prefixes_used"]
        assert all(row["id"].startswith("train-") for row in receipt["generation"]["rows"])
        assert all("input" not in row and "source_contexts" not in row for row in receipt["generation"]["rows"])
