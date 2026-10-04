"""Joint-replay execution controls retain diagnostic CE without zero gradients."""
from copy import deepcopy

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as fields
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as subject
from .test_context_boundary_training_runner import fake_context_boundary
from .test_generated_field_training_runner import fake_joint
from .test_ordered_clause_recurrent_training_runner import real_fixture


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def fit(model, train, tune, options, contexts, **kwargs):
    return subject.train(model, train, tune, source_contexts=contexts,
        source_value_weight=.25, cardinality_weight=.25, count_exposure="balanced_all",
        action_contrastive_weight=.05, non_action_learning_rate_multiplier=10.,
        **options, **kwargs)


def assert_same(left, right, *, omitted=()):
    for role in ("state_dict", "last_complete_attempt_state_dict"):
        assert set(left[role]) == set(right[role])
        assert all(torch.equal(value, right[role][name]) for name, value in left[role].items())
    a, b = deepcopy(left["report"]), deepcopy(right["report"])
    for report in (a, b):
        report.pop("elapsed_seconds")
        for key in omitted:
            report.pop(key, None)
    assert a == b
    assert left["predictions"] == right["predictions"]


@pytest.mark.parametrize("positive", [False, True])
def test_explicit_false_keeps_existing_zero_and_positive_paths_exact(monkeypatch, positive):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    if positive:
        fake_joint(monkeypatch)
    else:
        fake_context_boundary(monkeypatch)
        for name in ("prepare_training_inventory", "collect_source_generated_sites", "generated_site_losses"):
            monkeypatch.setattr(fields, name, lambda *a, **kw: pytest.fail("default joint helper executed"))
    kwargs = dict(generated_boundary_weight=.05, generated_field_weight=.05 if positive else 0.)
    ordinary = fit(model, train, tune, options, contexts, **kwargs)
    explicit = fit(model, train, tune, options, contexts, joint_generated_replay=False, **kwargs)
    assert_same(ordinary, explicit)
    assert "joint_generated_replay" not in explicit["report"]
    assert "generated_field_objective_enabled" not in explicit["report"]
    assert "generated_field_diagnostic_only" not in explicit["report"]


def test_explicit_true_preserves_existing_positive_objective_and_schedule(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    fake_joint(monkeypatch)
    kwargs = dict(generated_boundary_weight=.05, generated_field_weight=.05, generated_site_interval=2)
    ordinary = fit(model, train, tune, options, contexts, **kwargs)
    explicit = fit(model, train, tune, options, contexts, joint_generated_replay=True, **kwargs)
    assert_same(ordinary, explicit, omitted=("joint_generated_replay",
        "generated_field_objective_enabled", "generated_field_diagnostic_only"))
    assert explicit["report"]["joint_generated_replay"] is True
    assert explicit["report"]["generated_field_objective_enabled"] is True
    assert explicit["report"]["generated_field_diagnostic_only"] is False


@pytest.mark.parametrize("bad", [None, 0, 1, .5, "true", [], {}, float("nan")])
def test_joint_flag_requires_exact_bool_before_private_copy(monkeypatch, bad):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, "deepcopy", lambda *a: pytest.fail("copy preceded flag validation"))
    with pytest.raises(ValueError, match="joint generated replay must be a boolean"):
        fit(model, train, tune, options, contexts, generated_boundary_weight=.05, joint_generated_replay=bad)


@pytest.mark.parametrize("interval", [2, 3, 32])
def test_zero_weight_joint_control_cannot_skip_boundary_updates(monkeypatch, interval):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, "deepcopy", lambda *a: pytest.fail("copy preceded cadence validation"))
    with pytest.raises(ValueError, match="cadence requires positive field weight"):
        fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
            joint_generated_replay=True, generated_site_interval=interval)


@pytest.mark.parametrize("boundary_weight,scope", [(0., "all_trainable"), (.05, "count_head_only")])
def test_joint_control_requires_positive_all_trainable_boundary_loss(monkeypatch, boundary_weight, scope):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, "deepcopy", lambda *a: pytest.fail("copy preceded paired-loss validation"))
    with pytest.raises(ValueError, match="all.trainable"):
        fit(model, train, tune, options, contexts, joint_generated_replay=True,
            generated_boundary_weight=boundary_weight, generated_boundary_gradient_scope=scope)


def test_joint_control_requires_contextual_head_before_private_copy(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, "_head_specification", lambda *a: None)
    monkeypatch.setattr(subject, "deepcopy", lambda *a: pytest.fail("copy preceded contextual validation"))
    with pytest.raises(ValueError, match="contextual model"):
        subject.train(model, train, tune, **options, generated_boundary_weight=.05,
            joint_generated_replay=True)


@pytest.mark.parametrize("field_weight", [0., .05])
def test_joint_ce_measured_but_only_positive_field_graph_receives_gradient(monkeypatch, field_weight):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    observed = fake_joint(monkeypatch)
    original = fields.generated_site_losses
    field_gradients, boundary_gradients, calls = [], [], []

    def measured(*args, **kwargs):
        result = original(*args, **kwargs)
        result["field_loss"].register_hook(lambda value: field_gradients.append(float(value)))
        result["boundary_loss"].register_hook(lambda value: boundary_gradients.append(float(value)))
        calls.append(result)
        return result

    monkeypatch.setattr(fields, "generated_site_losses", measured)
    before = core.tensor_digest(model)
    source_before = deepcopy((train, tune, options, contexts))
    rng = torch.get_rng_state().clone()
    result = fit(model, train, tune, options, contexts, joint_generated_replay=True,
        generated_boundary_weight=.05, generated_field_weight=field_weight)
    report = result["report"]
    assert report["optimizer_steps"] == len(calls) == len(observed["collections"]) == 2
    assert len(observed["preparations"]) == 1
    assert boundary_gradients == pytest.approx([.05, .05])
    assert field_gradients == (pytest.approx([field_weight, field_weight]) if field_weight else [])
    assert report["generated_field_diagnostic_only"] == (field_weight == 0.)
    assert report["generated_field_objective_enabled"] == (field_weight != 0.)
    assert report["generated_site_scheduled_updates"] == 2 and report["generated_site_skipped_updates"] == 0
    assert all(row["generated_sites"]["scheduled"] for row in report["committed_updates"])
    for update, loss in zip(report["committed_updates"], calls):
        expected = update["weighted_token_ce"] + report["config"]["reconstruction_weight"]*update["raw_reconstruction_mse"]
        expected += .25*update["count_ce"] + .25*update["source_value_ce"] + .05*update["action_contrastive"]["loss"]
        expected += .05*loss["receipt"]["boundary"]["mean_loss"]
        expected += field_weight*loss["receipt"]["field"]["mean_loss"]
        assert update["objective"] == pytest.approx(expected, abs=1e-6)
        assert update["generated_sites"]["receipt"]["field"]["mean_loss"] > 0
    assert report["selection"] == "per_length_nonregression_then_fidelity_progress_then_reference_ce"
    assert report["generated_field_used_for_selection"] is False
    assert all(report[name] is False for name in subject.FALSE)
    assert core.tensor_digest(model) == before and source_before == (train, tune, options, contexts)
    assert torch.equal(rng, torch.get_rng_state())


@pytest.mark.parametrize("phase", ["collection", "loss", "incremental_retry"])
def test_zero_weight_joint_deadline_clears_uncommitted_gradients(monkeypatch, phase):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    observed = fake_joint(monkeypatch, expired=phase)
    before = core.tensor_digest(model)
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        joint_generated_replay=True)
    assert result["report"]["optimizer_steps"] == 0
    assert result["report"]["stopped_reason"] == "deadline_during_generated_sites"
    assert result["report"]["committed_updates"] == []
    assert core.tensor_digest(model) == before
    assert observed["collections"]
    assert all(parameter.grad is None for parameter in observed["collections"][0]["model"].parameters())


def test_zero_weight_joint_uses_real_training_inventory_and_source_only_rollout(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    collect, losses = fields.collect_source_generated_sites, fields.generated_site_losses
    receipts, sources = [], []

    def observed(working, rows, **kwargs):
        assert all(set(row) == {"id", "input", "source_text"} for row in rows)
        assert {row["id"] for row in rows} <= set(contexts["train"])
        assert not ({"inventory", "references", "training_references", "site_policy"} & set(kwargs))
        sources.append(deepcopy(rows))
        return collect(working, rows, **kwargs)

    def replayed(*args, **kwargs):
        result = losses(*args, **kwargs)
        if result["field_loss"] is not None:
            result["field_loss"].register_hook(lambda value: pytest.fail("zero-weight field graph attached"))
        receipts.append(result["receipt"])
        return result

    monkeypatch.setattr(fields, "collect_source_generated_sites", observed)
    monkeypatch.setattr(fields, "generated_site_losses", replayed)
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        joint_generated_replay=True)
    assert result["report"]["optimizer_steps"] == len(sources) == len(receipts) == 2
    assert result["report"]["generated_field_inventory"]["validation_rows_used"] is False
    for receipt in receipts:
        assert receipt["full_vocabulary_cross_entropy"] and receipt["reference_labels_used_only_after_rollout"]
        assert not receipt["validation_rows_used"] and not receipt["target_prefixes_used"]
        assert receipt["field"]["fields"] == ["actor", "action", "modality", "object"]
        assert receipt["generation"]["rollout_count"] == 1
        for row in receipt["generation"]["rows"]:
            assert row["union_replay_positions"] == sorted({site["position"]
                for site in row["selected_boundary_sites"] + row["selected_field_sites"]})
