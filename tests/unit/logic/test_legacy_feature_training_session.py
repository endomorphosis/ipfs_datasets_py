"""Persistent legacy LR/budget control without altered numerical semantics."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import active_training as active
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import feature_training_session as module
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_view_reuse import ViewReuseCachedLinguisticAutoencoder as Model


def fixture(*, proposal_budget=6, **options):
    model = Model(compute_device="cpu", feature_family_logit_scale=1.0)
    train = [model.build_sample(title="fixture", section="training", text="The agency shall submit reports.")]
    tune = [model.build_sample(title="fixture", section="tuning", text="The agency shall submit notices.")]
    session = module.FeatureTrainingSession(model, train, validation_samples=tune,
        proposal_budget=proposal_budget, **options)
    return session, train, tune


def load(receipt, train, tune):
    return module.load_training_session(receipt["path"], expected_sha256=receipt["sha256"],
                                        samples=train, validation_samples=tune)


def test_uninterrupted_and_checkpoint_resumed_updates_rates_and_counters_are_exact(tmp_path):
    session, train, tune = fixture()
    uninterrupted = Model(state=deepcopy(session.model.state), compute_device="cpu", feature_family_logit_scale=1.0)
    whole = active.train_active_family_features(uninterrupted, train, validation_samples=tune,
        epochs=6, learning_rate=.01, growth_factor=1.5, max_line_search_attempts=1, max_seconds=60)
    linguistic = session.model.linguistic_observation(tune[0])
    first = session.advance(max_proposals=3, max_seconds=60)
    receipt = session.save(tmp_path / "generation-1")
    resumed = load(receipt, train, tune)
    assert resumed.state == session.state
    second = resumed.advance(max_proposals=3, max_seconds=60)
    assert first["accepted_updates"] == second["accepted_updates"] == 3
    assert resumed.state["progress"]["proposals_used"] == 6
    assert resumed.state["progress"]["next_learning_rate"] == whole["next_learning_rate"]
    assert resumed.model.state.to_dict() == uninterrupted.state.to_dict()
    assert second["after"] == whole["after"]
    assert resumed.state["progress"]["terminal_reason"] == "proposal_budget"
    assert resumed.model.linguistic_observation(tune[0]) == linguistic
    assert not resumed.model.state.family_logits and not resumed.model.state.decoded_embeddings
    assert resumed.model.formula_checkpoint is None
    no_more = resumed.advance(max_proposals=6, max_seconds=30)
    assert no_more["proposal_count"] == 0 and no_more["stopped_reason"] == "proposal_budget"
    for flag in module._FALSE:
        assert second[flag] is False


def test_rejected_step_shrinks_and_persists_without_touching_model(tmp_path, monkeypatch):
    session, train, tune = fixture(max_consecutive_rejections=2, learning_rate=.02)
    identity = session.model.state.state_identity()
    baseline = active._evaluation(session.model, tune)
    calls = 0
    def reject(owner, rows):
        nonlocal calls
        calls += 1
        return (replace(baseline, cross_entropy_loss=baseline.cross_entropy_loss + 1,
                        cross_entropy_excess_loss=baseline.cross_entropy_excess_loss + 1)
                if calls % 3 == 0 else baseline)
    monkeypatch.setattr(active, "_evaluation", reject)
    result = session.advance(max_proposals=1, max_seconds=30)
    assert result["accepted_updates"] == 0
    assert session.state["progress"]["next_learning_rate"] == .01
    assert session.model.state.state_identity() == identity
    receipt = session.save(tmp_path / "rejected-1")
    resumed = load(receipt, train, tune)
    assert resumed.state["progress"]["consecutive_rejections"] == 1
    result = resumed.advance(max_proposals=6, max_seconds=30)
    assert result["proposal_count"] == 1
    assert result["proposal_reports"][0]["learning_rate"] == .01
    assert result["stopped_reason"] == "plateau"
    assert resumed.state["progress"]["proposals_used"] == 2
    assert resumed.state["progress"]["next_learning_rate"] == .005
    assert resumed.model.state.state_identity() == identity


@pytest.mark.parametrize("late", ["setup", "proposal", "evaluation"])
def test_deadline_preserves_rate_and_weights_without_false_plateau(tmp_path, monkeypatch, late):
    session, train, tune = fixture()
    identity, rate = session.model.state.state_identity(), session.state["progress"]["next_learning_rate"]
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    evaluate, update = active._evaluation, session.model._apply_projection_update_batch
    calls = 0
    def timed_evaluate(owner, rows):
        nonlocal calls
        calls += 1
        result = evaluate(owner, rows)
        if (late == "setup" and calls == 1) or (late == "evaluation" and calls == 3):
            clock[0] = 31.0
        return result
    def timed_update(*args, **kwargs):
        result = update(*args, **kwargs)
        if late == "proposal":
            clock[0] = 31.0
        return result
    monkeypatch.setattr(active, "_evaluation", timed_evaluate)
    monkeypatch.setattr(session.model, "_apply_projection_update_batch", timed_update)
    result = session.advance(max_proposals=3, max_seconds=30)
    assert result["stopped_reason"] == "deadline"
    progress = session.state["progress"]
    assert progress["accepted_updates"] == progress["consecutive_rejections"] == 0
    assert progress["next_learning_rate"] == rate
    assert progress["proposals_used"] == (0 if late == "setup" else 1)
    assert session.model.state.state_identity() == identity
    receipt = session.save(tmp_path / ("deadline-" + late))
    assert load(receipt, train, tune).state == session.state


def test_checkpoint_publication_is_exclusive_and_failed_generation_keeps_prior_intact(tmp_path, monkeypatch):
    session, train, tune = fixture()
    session.advance(max_proposals=1, max_seconds=30)
    old = session.save(tmp_path / "old")
    contents = {p.relative_to(tmp_path / "old"): p.read_bytes() for p in (tmp_path / "old").rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError):
        session.save(tmp_path / "old")
    original = module.os.link
    def fail_link(*args, **kwargs):
        raise OSError("simulated publication failure")
    monkeypatch.setattr(module.os, "link", fail_link)
    with pytest.raises(OSError, match="publication failure"):
        session.save(tmp_path / "partial")
    assert not (tmp_path / "partial/session.json").exists()
    assert contents == {p.relative_to(tmp_path / "old"): p.read_bytes() for p in (tmp_path / "old").rglob("*") if p.is_file()}
    assert load(old, train, tune).state == session.state
    monkeypatch.setattr(module.os, "link", original)
    assert load(session.save(tmp_path / "new"), train, tune).state == session.state


def test_inference_only_state_copy_is_detached_and_external_updates_rejected():
    session, train, tune = fixture()
    exposed = session.state
    exposed["progress"]["next_learning_rate"] = .3
    assert session.state["progress"]["next_learning_rate"] == .01
    session.model.state.feature_family_logits["external"] = {"deontic": 1.0}
    with pytest.raises(ValueError, match="outside feature session"):
        session.advance(max_proposals=1)


def test_changed_inputs_fail_before_proposal_and_saved_binding_rejects_other_sources(tmp_path):
    session, train, tune = fixture()
    saved = session.save(tmp_path / "saved")
    changed = [replace(tune[0], citation="new citation")]
    with pytest.raises(ValueError, match="input/model binding differs"):
        load(saved, train, changed)
    identity = session.model.state.state_identity()
    tune[0].parser_trace["changed"] = True
    with pytest.raises(ValueError, match="input or model configuration changed"):
        session.advance(max_proposals=1)
    assert session.model.state.state_identity() == identity


def test_failed_optimization_cannot_publish_ambiguous_progress(tmp_path, monkeypatch):
    session, train, tune = fixture()
    saved = session.save(tmp_path / "saved")
    def failed(*args, **kwargs):
        raise RuntimeError("interrupted trainer")
    monkeypatch.setattr(active, "train_active_family_features", failed)
    with pytest.raises(RuntimeError, match="interrupted"):
        session.advance(max_proposals=2)
    with pytest.raises(ValueError, match="requires reload"):
        session.save(tmp_path / "ambiguous")
    assert load(saved, train, tune).state["progress"]["proposals_used"] == 0


def test_exception_after_accepted_update_requires_prior_generation_reload(tmp_path, monkeypatch):
    session, train, tune = fixture()
    saved = session.save(tmp_path / "prior-generation")
    original_identity = session.model.state.state_identity()
    original = active.train_active_family_features
    def commit_then_interrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result["accepted_epochs"] == 1
        raise RuntimeError("interrupted after accepted update before scheduler receipt")
    monkeypatch.setattr(active, "train_active_family_features", commit_then_interrupt)
    with pytest.raises(RuntimeError, match="after accepted"):
        session.advance(max_proposals=2, max_seconds=30)
    assert session.model.state.state_identity() != original_identity
    with pytest.raises(ValueError, match="requires reload"):
        session.advance(max_proposals=1)
    with pytest.raises(ValueError, match="requires reload"):
        session.save(tmp_path / "ambiguous-generation")
    restored = load(saved, train, tune)
    assert restored.model.state.state_identity() == original_identity
    assert restored.state["progress"]["proposals_used"] == 0


def test_source_change_since_import_fails_before_training_or_load(tmp_path, monkeypatch):
    session, train, tune = fixture()
    saved = session.save(tmp_path / "saved")
    monkeypatch.setattr(module, "_source_identity", lambda: (0, 0, 0, 0, 0))
    with pytest.raises(ValueError, match="source changed since import"):
        session.advance(max_proposals=1)
    with pytest.raises(ValueError, match="source changed since import"):
        load(saved, train, tune)


@pytest.mark.parametrize("damage", ["budget", "rate", "counter", "flags", "model_manifest", "source"])
def test_malformed_checkpoint_metadata_is_rejected_even_with_explicit_new_file_hash(tmp_path, damage):
    session, train, tune = fixture()
    saved = session.save(tmp_path / damage)
    path = tmp_path / damage / "session.json"
    value = json.loads(path.read_bytes())
    if damage == "budget":
        value["session"]["progress"]["proposals_used"] = 6
        value["session"]["progress"]["rejected_proposals"] = 6
    elif damage == "rate":
        value["session"]["progress"]["next_learning_rate"] = 1.1
    elif damage == "counter":
        value["session"]["progress"]["accepted_updates"] = 1
    elif damage == "flags":
        value["qualified"] = True
    elif damage == "model_manifest":
        value["model_manifest_sha256"] = "0" * 64
    else:
        value["session"]["sources"]["active_training"] = "0" * 64
    payload = json.dumps(value).encode()
    path.write_bytes(payload)
    saved["sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError):
        load(saved, train, tune)


def test_checkpoint_hash_and_duplicate_keys_are_not_silently_accepted(tmp_path):
    session, train, tune = fixture()
    saved = session.save(tmp_path / "saved")
    wrong = dict(saved, sha256="0" * 64)
    with pytest.raises(ValueError, match="digest differs"):
        load(wrong, train, tune)
    path = tmp_path / "saved/session.json"
    payload = path.read_bytes().replace(b'{', b'{"schema":"duplicate",', 1)
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="duplicate"):
        load(dict(saved, sha256=hashlib.sha256(payload).hexdigest()), train, tune)
