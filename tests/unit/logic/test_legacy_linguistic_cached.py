"""Cache acceleration cannot change the preserved teacher's representation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib

import pytest

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1"


@pytest.fixture(scope="module")
def modules():
    pytest.importorskip("spacy")
    return (importlib.import_module(PREFIX + ".linguistic"),
            importlib.import_module(PREFIX + ".linguistic_cached"))


@pytest.fixture
def models(modules):
    baseline, cached = modules
    return (baseline.LinguisticAutoencoder(compute_device="cpu", feature_family_logit_scale=1.0),
            cached.CachedLinguisticAutoencoder(compute_device="cpu", feature_family_logit_scale=1.0))


def sample(model, section="1", text="The agency shall submit reports."):
    return model.build_sample(title="5", section=section, text=text)


@pytest.mark.parametrize("text", [
    "The agency shall submit reports.",
    "The agency shall not disclose records.",
    "Company A shall submit backup report within 10 days unless emergency.",
    "The officer shall retain the file for at least 20 days.",
    "If the officer knows the filing is complete, the agency may issue a notice.",
])
def test_all_old_outputs_are_exact_and_share_one_parse(models, text):
    original, cached = models
    row = sample(original, text=text)
    assert cached._linguistic_identity == original._linguistic_identity
    for _ in range(2):
        assert cached.linguistic_observation(row) == original.linguistic_observation(row)
        for dimensions in (8, 16):
            assert (cached.feature_codec.decode_sample_embedding(row, dimensions=dimensions)
                    == original.feature_codec.decode_sample_embedding(row, dimensions=dimensions))
        for families in (original.modal_families, ("deontic", "temporal"), ("temporal", "deontic")):
            assert (cached.feature_codec.family_logits_for_sample(row, modal_families=families)
                    == original.feature_codec.family_logits_for_sample(row, modal_families=families))
        assert cached.feature_codec.feature_keys_for_sample(row) == original.feature_codec.feature_keys_for_sample(row)
        assert cached.encode(row, use_sample_memory=False) == original.encode(row, use_sample_memory=False)
    info = cached.feature_codec.cache_info()
    assert info["encodes"] == info["compiles"] == 1
    assert info["hits"] > 10
    assert info["retained_bytes"] <= info["max_bytes"]


def test_every_source_identity_field_is_part_of_key(models):
    original, cached = models
    row = sample(original)
    rows = [row, replace(row, text=row.text + " "), replace(row, text="The agency may submit reports."),
            replace(row, sample_id="other"), replace(row, citation="other citation"),
            replace(row, source="other source")]
    for value in rows:
        assert cached.feature_codec.encode_sample(value) == original.feature_codec.encode_sample(value)
    assert cached.feature_codec.cache_info()["encodes"] == len(rows)


def test_installed_spacy_backend_has_exact_outputs(modules):
    pytest.importorskip("en_core_web_sm")
    baseline, cached_module = modules
    original = baseline.LinguisticAutoencoder(backend="local_en_core_web_sm", compute_device="cpu")
    cached = cached_module.CachedLinguisticAutoencoder(backend="local_en_core_web_sm", compute_device="cpu")
    row = sample(original, text="Company A shall submit backup report within 10 days unless emergency.")
    assert cached.linguistic_observation(row) == original.linguistic_observation(row)
    assert cached.encode(row, use_sample_memory=False) == original.encode(row, use_sample_memory=False)
    assert cached.feature_codec.cache_info()["encodes"] == 1
    assert cached.feature_codec.encoder.used_fallback_model is False


def test_identical_text_in_different_contexts_matches_fresh_predictions(modules):
    baseline_module, cached_module = modules
    seed = baseline_module.LinguisticAutoencoder(compute_device="cpu", feature_family_logit_scale=1.0)
    seed.state.feature_family_logits["title:5"] = {"deontic": 1.0}
    seed.state.feature_family_logits["title:28"] = {"temporal": 2.0}
    rows = [seed.build_sample(title=title, section=section, text="The agency shall submit reports.")
            for title, section in (("5", "1"), ("28", "552"))]
    options = dict(compute_device="cpu", feature_family_logit_scale=1.0)
    expected = [baseline_module.LinguisticAutoencoder(state=deepcopy(seed.state), **options).encode(row, use_sample_memory=False)
                for row in rows]
    historical = baseline_module.LinguisticAutoencoder(state=deepcopy(seed.state), **options)
    historical.encode(rows[0], use_sample_memory=False)
    assert historical.encode(rows[1], use_sample_memory=False) != expected[1]
    for order in ([0, 1], [1, 0]):
        model = cached_module.CachedLinguisticAutoencoder(state=deepcopy(seed.state), **options)
        for index in order * 2:
            assert model.encode(rows[index], use_sample_memory=False) == expected[index]


@pytest.mark.parametrize("field", ["title", "section", "citation", "sample_id", "parser_trace", "losses", "modal_ir", "frame_candidates"])
def test_numerical_feature_cache_binds_all_source_metadata(models, field):
    original, cached = models
    row = sample(original)
    first = cached._sample_cache_for(row)
    first["sentinel"] = True
    if field == "modal_ir":
        changed = replace(row, modal_ir=replace(row.modal_ir, metadata={"provenance": "changed"}))
    elif field in {"parser_trace", "losses"}:
        changed = replace(row, **{field: {"different": 1.0}})
    elif field == "frame_candidates":
        changed = replace(row, frame_candidates=[{"frame_id": "different", "score": 2.0}])
    else:
        changed = replace(row, **{field: "different"})
    assert "sentinel" not in cached._sample_cache_for(changed)
    # In-place nested edits must invalidate too, despite LegalSample frozen=True.
    row.parser_trace["mutation"] = "nested metadata edit"
    assert "sentinel" not in cached._sample_cache_for(row)


def test_warm_other_context_does_not_change_training_or_reload(modules, tmp_path):
    baseline_module, cached_module = modules
    options = dict(compute_device="cpu", feature_family_logit_scale=1.0)
    baseline = baseline_module.LinguisticAutoencoder(**options)
    cached = cached_module.CachedLinguisticAutoencoder(**options)
    earlier = baseline.build_sample(title="0", section="obligation", text="The agency shall submit reports.")
    cached.encode(earlier, use_sample_memory=False)
    train = baseline.build_sample(title="training-fixture", section="1", text="The agency shall submit reports.")
    tuning = baseline.build_sample(title="tuning-fixture", section="2", text="The agency shall submit notices.")
    training = dict(epochs=1, learning_rate=.01, max_seconds=30, max_line_search_attempts=1,
                    projection_update_backend="python_sparse_batch", projection_max_update_families=4,
                    legal_ir_bridge_names=(), legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    old = baseline.train_generalizable_projection([train], validation_samples=[tuning], **training)
    new = cached.train_generalizable_projection([train], validation_samples=[tuning], **training)
    assert _without_timings(old) == _without_timings(new)
    assert cached.state.to_dict() == baseline.state.to_dict()
    fresh = baseline_module.LinguisticAutoencoder(state=deepcopy(cached.state), **options)
    for row in (train, tuning):
        assert cached.encode(row, use_sample_memory=False) == fresh.encode(row, use_sample_memory=False)
    checkpoint = tmp_path / "context-checkpoint"
    cached.save_training_checkpoint(checkpoint)
    resumed = cached_module.load_cached_training_checkpoint(checkpoint)
    for row in (train, tuning):
        assert cached.encode(row, use_sample_memory=False) == resumed.encode(row, use_sample_memory=False)


def test_mutable_public_outputs_cannot_poison_cache(models):
    original, cached = models
    row = sample(original)
    encoding = cached.feature_codec.encode_sample(row)
    encoding.tokens.clear()
    encoding.cues[0].token_indices.append(10000)
    ir = cached.feature_codec.compile_sample_ir(row)
    ir.formulas.clear()
    vector = cached.feature_codec.decode_sample_embedding(row, dimensions=8)
    vector[0] = 500
    keys = cached.feature_codec.feature_keys_for_sample(row)
    keys.clear()
    logits = cached.feature_codec.family_logits_for_sample(row, modal_families=original.modal_families)
    logits.clear()
    assert cached.linguistic_observation(row) == original.linguistic_observation(row)


def test_lru_and_byte_bounds_and_disabled_cache(modules):
    _, module = modules
    model = module.CachedLinguisticAutoencoder(compute_device="cpu", cache_max_entries=2)
    rows = [sample(model, section=str(i)) for i in range(4)]
    for row in rows:
        model.feature_codec.compile_sample_ir(row)
        model._sample_cache_for(row)["marker"] = row.sample_id
    info = model.feature_codec.cache_info()
    assert info["entries"] == 2
    assert info["evictions"] == 2
    assert info["retained_bytes"] <= info["max_bytes"]
    assert len(model._sample_feature_cache) == 2
    assert model.describe()["numerical_feature_cache"]["byte_bound"] is None
    assert model._sample_cache_for(rows[-1])["marker"] == rows[-1].sample_id
    assert "marker" not in model._sample_cache_for(rows[0])
    model.feature_codec.encode_sample(rows[-1])
    assert model.feature_codec.cache_info()["encodes"] == 4
    model.feature_codec.encode_sample(rows[0])
    assert model.feature_codec.cache_info()["encodes"] == 5
    model.feature_codec.clear_cache()
    assert model.feature_codec.cache_info()["entries"] == 0
    assert model.feature_codec.cache_info()["retained_bytes"] == 0
    for entries, limit in ((1, 1), (0, 1024 * 1024)):
        disabled = module.CachedLinguisticAutoencoder(compute_device="cpu", cache_max_entries=entries,
                                                    cache_max_bytes=limit)
        row = sample(disabled)
        disabled.feature_codec.encode_sample(row)
        disabled.feature_codec.encode_sample(row)
        assert disabled.feature_codec.cache_info()["entries"] == 0
        assert disabled.feature_codec.cache_info()["encodes"] == 2
        if entries == 0:
            disabled._sample_cache_for(row)["marker"] = True
            assert "marker" not in disabled._sample_cache_for(row)
            assert not disabled._sample_feature_cache


def test_concurrent_requests_share_one_encoding(models):
    original, cached = models
    row = sample(original)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _: cached.feature_codec.compile_sample_ir(row).to_dict(), range(16)))
    assert all(value == original.feature_codec.compile_sample_ir(row).to_dict() for value in values)
    assert cached.feature_codec.cache_info()["encodes"] == 1
    assert cached.feature_codec.cache_info()["compiles"] == 1


@pytest.mark.parametrize("mutation", ["model_name", "registry", "pipeline", "bounds"])
def test_codec_configuration_drift_clears_and_rejects(models, mutation):
    original, cached = models
    row = sample(original)
    codec = cached.feature_codec
    codec.encode_sample(row)
    if mutation == "model_name":
        codec.encoder.model_name = "different"
    elif mutation == "registry":
        # Replace one private index without mutating the shared frozen registry.
        registry = type(codec.encoder.registry)()
        registry._profiles.pop(next(iter(registry._profiles)))
        codec.encoder.registry = registry
    elif mutation == "pipeline":
        codec.encoder.nlp.config["nlp"]["batch_size"] += 1
    else:
        codec.max_entries += 1
    with pytest.raises(ValueError, match="configuration changed"):
        codec.encode_sample(row)
    assert codec.cache_info()["entries"] == 0


def test_original_training_checkpoint_resume_and_update_states_are_exact(models, modules, tmp_path):
    baseline_module, cached_module = modules
    original, cached = models
    train = sample(original)
    validation = sample(original, "2", "The agency shall submit notices.")
    options = dict(epochs=1, learning_rate=0.01, max_seconds=30,
                   max_line_search_attempts=1, projection_update_backend="python_sparse_batch",
                   projection_max_update_families=4, legal_ir_bridge_names=(),
                   legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    baseline_report = original.train_generalizable_projection([train], validation_samples=[validation], **options)
    cached_report = cached.train_generalizable_projection([train], validation_samples=[validation], **options)
    assert baseline_report["accepted_epochs"] == cached_report["accepted_epochs"] == 1
    assert original.state.to_dict() == cached.state.to_dict()
    assert original.state.feature_family_logits
    assert not original.state.decoded_embeddings
    path = tmp_path / "checkpoint"
    cached.save_training_checkpoint(path)
    resumed = cached_module.load_cached_training_checkpoint(path, cache_max_entries=3)
    uncached = baseline_module.load_training_checkpoint(path)
    assert type(resumed) is cached_module.CachedLinguisticAutoencoder
    assert resumed.feature_codec.cache_info()["entries"] == 0
    assert resumed.feature_codec.cache_info()["max_entries"] == 3
    assert resumed.state.to_dict() == uncached.state.to_dict() == cached.state.to_dict()
    assert resumed.describe()["checkpoint_identity"] == uncached.describe()["checkpoint_identity"]
    assert resumed._checkpoint_identity is not None
    assert resumed._checkpoint_identity is not uncached._checkpoint_identity
    assert resumed.linguistic_observation(train) == uncached.linguistic_observation(train)
    a = resumed.train_generalizable_projection([train], validation_samples=[validation], **options)
    b = uncached.train_generalizable_projection([train], validation_samples=[validation], **options)
    assert a["accepted_epochs"] == b["accepted_epochs"]
    assert resumed.state.to_dict() == uncached.state.to_dict()
    assert resumed.formula_checkpoint is None
    with pytest.raises(ValueError, match="formula training"):
        resumed.train_generalizable_projection([train], validation_samples=[validation], formula_targets=[])


@pytest.mark.parametrize("kwargs", [{"cache_max_entries": -1}, {"cache_max_entries": True},
                                    {"cache_max_bytes": 128 * 1024 * 1024}, {"cache_max_bytes": -1}])
def test_invalid_bounds_fail(modules, kwargs):
    with pytest.raises(ValueError):
        modules[1].CachedLinguisticAutoencoder(compute_device="cpu", **kwargs)


def _without_timings(value):
    if isinstance(value, dict):
        return {key: _without_timings(item) for key, item in value.items()
                if "elapsed" not in key and key != "duration_seconds"}
    if isinstance(value, list):
        return [_without_timings(item) for item in value]
    return value


def test_streamed_profile_reuses_existing_port_and_preserves_reports_and_resume(modules, tmp_path):
    baseline_module, cached_module = modules
    port = importlib.import_module(PREFIX.rsplit(".", 1)[0] + ".legacy_v1_optimized")
    cls = cached_module.StreamedCachedLinguisticAutoencoder
    assert cls._apply_projection_update_batch_in_transaction is port.Autoencoder._apply_projection_update_batch_in_transaction
    models = [constructor(compute_device="cpu", feature_family_logit_scale=1.0)
              for constructor in (baseline_module.LinguisticAutoencoder,
                                  cached_module.CachedLinguisticAutoencoder, cls)]
    train, validation = sample(models[0]), sample(models[0], "2", "The agency shall submit notices.")
    options = dict(epochs=2, learning_rate=0.01, max_seconds=30,
                   max_line_search_attempts=1, projection_update_backend="python_sparse_batch",
                   projection_max_update_families=4, legal_ir_bridge_names=(),
                   legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    reports = [model.train_generalizable_projection([train], validation_samples=[validation], **options)
               for model in models]
    assert reports[0]["accepted_epochs"] > 0
    assert all(_without_timings(report) == _without_timings(reports[0]) for report in reports)
    assert all(model.state.to_dict() == models[0].state.to_dict() for model in models)
    assert all(model.state.state_identity() == models[0].state.state_identity() for model in models)
    assert models[-1].describe()["runtime_profile"] == cached_module.STREAMED_RUNTIME_PROFILE
    assert models[-1].describe()["linguistic_identity"] == models[0].describe()["linguistic_identity"]
    bundle = tmp_path / "streamed-bundle"
    models[-1].save_training_checkpoint(bundle)
    resumed = cached_module.load_streamed_cached_training_checkpoint(bundle)
    baseline = baseline_module.load_training_checkpoint(bundle)
    assert type(resumed) is cls
    assert resumed.describe()["checkpoint_identity"] == baseline.describe()["checkpoint_identity"]
    a = resumed.train_generalizable_projection([train], validation_samples=[validation], **options)
    b = baseline.train_generalizable_projection([train], validation_samples=[validation], **options)
    assert _without_timings(a) == _without_timings(b)
    assert resumed.state.to_dict() == baseline.state.to_dict()


@pytest.mark.parametrize("streamed", [False, True])
def test_public_raw_checkpoint_loaders_verify_sha_and_keep_provenance(modules, tmp_path, streamed):
    baseline_module, cached_module = modules
    original = baseline_module.LinguisticAutoencoder(compute_device="cpu")
    path = tmp_path / "raw.state.json"
    original.state.save_json(path)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    load = (cached_module.load_streamed_cached_checkpoint if streamed
            else cached_module.load_cached_checkpoint)
    model = load(path, expected_sha256=sha, compute_device="cpu")
    expected_class = (cached_module.StreamedCachedLinguisticAutoencoder if streamed
                      else cached_module.CachedLinguisticAutoencoder)
    assert type(model) is expected_class
    assert model.describe()["checkpoint_identity"]["sha256"] == sha
    assert model.describe()["checkpoint_identity"]["read_only_checkpoint_load"] is True
    assert model.state.to_dict() == original.state.to_dict()
    assert path.read_bytes() == raw
    with pytest.raises(ValueError):
        load(path, expected_sha256="0" * 64, compute_device="cpu")
