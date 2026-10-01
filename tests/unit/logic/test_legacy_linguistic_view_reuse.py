"""Encode-local reuse must preserve sparse training and all source boundaries."""
from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import linguistic_view_reuse as module
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import linguistic_cached, daemon_teacher

PROFILES = {
    "cached": (linguistic_cached.CachedLinguisticAutoencoder, module.ViewReuseCachedLinguisticAutoencoder),
    "streamed_cached": (linguistic_cached.StreamedCachedLinguisticAutoencoder, module.ViewReuseStreamedCachedLinguisticAutoencoder),
    "historical_daemon": (daemon_teacher.HistoricalDaemonAutoencoder, module.ViewReuseHistoricalDaemonAutoencoder),
}


def sample(model, text="The agency shall submit reports.", title="5", section="1"):
    return model.build_sample(title=title, section=section, text=text)


def options():
    return dict(compute_device="cpu", feature_family_logit_scale=1.0)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("text", ["The agency shall not disclose records.",
    "Company A shall submit backup report within 10 days unless emergency.",
    "The officer shall retain the file for at least 20 days."])
def test_exact_weighted_predictions_and_no_cross_call_retention(profile, text):
    baseline_class, fast_class = PROFILES[profile]
    baseline = baseline_class(**options())
    baseline.state.feature_family_logits["title:5"] = {"deontic": 0.8}
    baseline.state.legal_ir_view_logits.update({"deontic.ir": .3, "modal.frame_logic": -.2})
    fast = fast_class(state=deepcopy(baseline.state), **options())
    row = sample(baseline, text)
    before = fast.state.to_dict()
    for _ in range(2):
        expected = baseline.encode(row, use_sample_memory=False)
        assert fast.encode(row, use_sample_memory=False) == expected
        assert fast.decode(expected) == baseline.decode(expected)
        assert module._MEMO.get() is None
        assert fast.describe()["view_reuse"]["last_encode"]["retained_after_encode"] == 0
        assert fast.describe()["view_reuse"]["last_encode"]["hits"] > 0
    assert fast.state.to_dict() == before
    assert fast.formula_checkpoint is None
    assert fast.describe()["admitted"] is False


def test_repeated_view_computation_runs_once_per_encode(monkeypatch):
    model = module.ViewReuseHistoricalDaemonAutoencoder(**options())
    row = sample(model)
    calls = []
    original = model._legal_ir_view_logits_for
    def tracked(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(model, "_legal_ir_view_logits_for", tracked)
    model.encode(row, use_sample_memory=False)
    assert len(calls) == 1
    assert model.describe()["view_reuse"]["last_encode"]["hits"] >= 3
    model.encode(row, use_sample_memory=False)
    assert len(calls) == 2


def test_view_keys_cover_context_state_targets_and_memory_and_are_copy_safe():
    model = module.ViewReuseCachedLinguisticAutoencoder(**options())
    row = sample(model)
    model.state.legal_ir_view_logits.update({"deontic.ir": .3, "modal.frame_logic": -.2})
    scope = {"owner": model, "entries": {}, "hits": 0, "misses": 0}
    token = module._MEMO.set(scope)
    def read(value=row, use_sample_memory=False):
        expected = linguistic_cached.CachedLinguisticAutoencoder._legal_ir_view_distribution_for_embedding(
            model, value, use_sample_memory=use_sample_memory)
        actual = model._legal_ir_view_distribution_for_embedding(value, use_sample_memory=use_sample_memory)
        assert actual == expected
        return actual
    try:
        first = read()
        first["deontic.ir"] = 999
        assert read()["deontic.ir"] != 999
        assert scope["hits"] == 1
        read(replace(row, title="28", section="552", citation="different citation"))
        row.parser_trace["mutated"] = "new nested source metadata"
        read()
        model.state.legal_ir_view_logits["deontic.ir"] = 1.0
        read()
        model._legal_ir_view_target_cache[row.sample_id] = {"CEC.native": 1.0}
        read()
        model.state.family_logits[row.sample_id] = {"deontic.ir": 2.0}
        read(use_sample_memory=True)
        read(use_sample_memory=False)
        assert scope["misses"] == 7
        for index in range(20):
            read(replace(row, citation=str(index)))
        assert len(scope["entries"]) == module._MAX_MEMO_ENTRIES
        assert all(isinstance(key[2], bytes) and len(key[2]) == 32 for key in scope["entries"])
    finally:
        module._MEMO.reset(token)


def test_memo_cleared_on_failure_and_configuration_guard_still_active(monkeypatch):
    model = module.ViewReuseCachedLinguisticAutoencoder(**options())
    row = sample(model)
    old = model._decoded_for
    def fail(*args, **kwargs):
        raise RuntimeError("intentional decode failure")
    monkeypatch.setattr(model, "_decoded_for", fail)
    with pytest.raises(RuntimeError, match="intentional"):
        model.encode(row, use_sample_memory=False)
    assert module._MEMO.get() is None
    monkeypatch.setattr(model, "_decoded_for", old)
    model.encode(row, use_sample_memory=False)
    model.feature_family_logit_scale += 1
    with pytest.raises(ValueError, match="configuration changed"):
        model.encode(row, use_sample_memory=False)
    assert module._MEMO.get() is None


def test_source_guard_cannot_be_bypassed_by_view_hit():
    model = module.ViewReuseCachedLinguisticAutoencoder(**options())
    row = sample(model)
    model.encode(row, use_sample_memory=False)
    model._view_reuse_source_identity = (0, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="view reuse source changed"):
        model.encode(row, use_sample_memory=False)


def _without_timings(value):
    if isinstance(value, dict):
        return {key: _without_timings(item) for key, item in value.items()
                if "elapsed" not in key and key != "duration_seconds"}
    if isinstance(value, list):
        return [_without_timings(item) for item in value]
    return value


@pytest.mark.parametrize("profile", PROFILES)
def test_training_reports_weights_checkpoint_and_resume_are_exact(profile, tmp_path):
    baseline_class, fast_class = PROFILES[profile]
    baseline, fast = baseline_class(**options()), fast_class(**options())
    train = sample(baseline)
    tuning = sample(baseline, "The agency shall submit notices.", section="2")
    training = dict(epochs=1, learning_rate=.01, max_seconds=60, max_line_search_attempts=1,
                    projection_update_backend="python_sparse_batch", projection_max_update_families=4,
                    legal_ir_bridge_names=(), legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    a = baseline.train_generalizable_projection([train], validation_samples=[tuning], **training)
    b = fast.train_generalizable_projection([train], validation_samples=[tuning], **training)
    assert a["accepted_epochs"] == b["accepted_epochs"] == 1
    assert _without_timings(a) == _without_timings(b)
    assert baseline.state.to_dict() == fast.state.to_dict()
    assert baseline.state.state_identity() == fast.state.state_identity()
    checkpoint = tmp_path / "bundle"
    fast.save_training_checkpoint(checkpoint)
    resumed = module.load_training_checkpoint(checkpoint, profile=profile)
    assert type(resumed) is fast_class
    assert resumed.state.to_dict() == fast.state.to_dict()
    assert resumed.describe()["checkpoint_identity"]["sha256"]
    assert resumed.encode(tuning, use_sample_memory=False) == fast.encode(tuning, use_sample_memory=False)
    a = baseline.train_generalizable_projection([train], validation_samples=[tuning], **training)
    b = resumed.train_generalizable_projection([train], validation_samples=[tuning], **training)
    assert _without_timings(a) == _without_timings(b)
    assert baseline.state.to_dict() == resumed.state.to_dict()


@pytest.mark.parametrize("profile", PROFILES)
def test_existing_local_raw_weights_use_verified_loader(profile, tmp_path):
    model = PROFILES[profile][0](**options())
    path = tmp_path / "original.state.json"
    model.state.save_json(path)
    raw = path.read_bytes()
    loaded = module.load_checkpoint(path, expected_sha256=hashlib.sha256(raw).hexdigest(),
                                    profile=profile, **options())
    assert type(loaded) is PROFILES[profile][1]
    assert loaded.state.to_dict() == model.state.to_dict()
    assert path.read_bytes() == raw
    with pytest.raises(ValueError):
        module.load_checkpoint(path, expected_sha256="0" * 64, profile=profile, **options())
