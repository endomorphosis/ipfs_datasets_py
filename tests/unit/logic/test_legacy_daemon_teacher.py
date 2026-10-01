"""Exact old daemon replay and independent sparse-training checkpoint contract."""
from dataclasses import replace
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import legacy_v1
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import daemon_teacher as module
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1._daemon_snapshot import MANIFEST, verify_snapshot
from scripts.ops.legal_ir.legacy_teacher_history import load_daemon_wrappers


@pytest.fixture(scope="module")
def historical():
    return load_daemon_wrappers()


@pytest.fixture(scope="module")
def profile():
    return module.HistoricalDaemonAutoencoder(compute_device="cpu")


@pytest.mark.parametrize("text", [
    "The agency shall submit reports.",
    "The agency shall not disclose records.",
    "Company A shall submit backup report within 10 days unless emergency.",
    "The officer shall retain the file for at least 20 days.",
    "If the application is complete, the agency must issue written notice unless waived.",
    "The applicant may request review.",
    "The Secretary shall make the payment after May 13, 2002, and a producer may request review.",
])
def test_full_daemon_profile_exact_historical_git_replay(profile, historical, text):
    sample = profile.build_sample(title="diagnostic", section=str(len(text)), text=text)
    old_codec = historical["historical"]
    old_result = old_codec.encode(text, document_id=sample.sample_id, citation=sample.citation,
                                  source=sample.source, source_embedding=sample.embedding_vector)
    actual = profile.linguistic_observation(sample)
    assert actual["encoding"] == old_result.encoding.to_dict()
    assert actual["modal_ir"] == old_result.modal_ir.to_dict()
    assert actual["wrapper_decoded_vector"] == old_result.decoded_embedding
    assert actual["wrapper_losses"] == old_result.losses
    assert actual["kg_triples"] == old_result.kg_triples
    assert actual["decoded_modal_text"] == old_result.decoded_modal_text.to_dict()
    assert actual["feature_keys"] == old_codec.feature_keys_for_sample(
        sample, max_features=profile.max_codec_feature_keys)
    old_model = legacy_v1.Autoencoder(feature_codec=old_codec, compute_device="cpu",
                                     **historical["historical_constructor_fallbacks"])
    expected = old_model.encode(sample, use_sample_memory=False)
    observed = profile.encode(sample, use_sample_memory=False)
    assert observed == expected
    assert profile.decode(observed) == old_model.decode(expected)
    assert actual["producer_configuration_verified"] is False
    assert actual["independent_formula_generation"] is False
    assert actual["admitted"] is False


def test_profile_exposes_source_defaults_but_no_producer_claim(profile):
    assert len(verify_snapshot()["constructor_fallbacks"]) == 71
    assert len(MANIFEST["files"]) == 4
    description = profile.describe()
    assert description["historical_daemon_feature_codec_replay"] is True
    assert description["checkpoint_original_producer_configuration_verified"] is False
    assert profile.feature_family_logit_scale == 1.0
    assert profile.compiler_quality_family_logit_scale == 1.0
    assert profile.feature_codec.config.use_flogic is True
    assert profile.feature_codec.encoder.used_fallback_model is True
    assert description["training_profile"] == module.PROFILE_ID


def test_formula_head_and_foreign_linguistic_identity_rejected(profile):
    sample = profile.build_sample(title="diagnostic", section="bad", text="The agency shall submit reports.")
    with pytest.raises(ValueError, match="another backend or codec"):
        profile.encode(replace(sample, embedding_model="linguistic:spacy-feature-hash8d:foreign"))
    with pytest.raises(ValueError, match="cannot attach"):
        profile.attach_formula_checkpoint({})
    with pytest.raises(ValueError, match="formula"):
        profile.train_generalizable_projection([sample], formula_targets=[{}])
    with pytest.raises(ValueError, match="blank-English"):
        module.HistoricalDaemonAutoencoder(backend="local_en_core_web_sm")


def test_metadata_changes_do_not_alias_numerical_feature_cache():
    model = module.HistoricalDaemonAutoencoder(compute_device="cpu")
    sample = model.build_sample(title="training", section="1", text="The agency shall submit reports.")
    first = model._sample_cache_for(sample)
    first["sentinel"] = True
    changed = replace(sample, citation="different citation", section="different section")
    assert model._sample_cache_for(changed) == {}
    assert model._sample_cache_for(sample) is first
    for index in range(140):
        model._sample_cache_for(replace(sample, citation=f"citation {index}"))
    assert len(model._sample_feature_cache) <= 128


@pytest.mark.parametrize("component,attribute,value", [
    ("frame_selector", "k1", 2.1),
    ("frame_selector", "b", 0.5),
    ("frame_selector", "frames", ()),
    ("frame_selector", "_doc_freq", {}),
    ("frame_selector", "_avgdl", 999),
    ("flogic_optimizer.config", "similarity_threshold", .5),
    ("flogic_optimizer.config", "check_ontology_consistency", False),
])
def test_configuration_drift_rejected_before_inference_or_save(tmp_path, component, attribute, value):
    model = module.HistoricalDaemonAutoencoder(compute_device="cpu")
    sample = model.build_sample(title="test", section="1", text="The agency shall submit reports.")
    target = model.feature_codec
    for key in component.split("."):
        target = getattr(target, key)
    setattr(target, attribute, value)
    with pytest.raises(ValueError, match="codec configuration changed"):
        model.encode(sample, use_sample_memory=False)
    with pytest.raises(ValueError, match="codec configuration changed"):
        model.save_training_checkpoint(tmp_path / "must-not-save")
    assert not (tmp_path / "must-not-save").exists()


def test_runtime_identity_binds_optional_observer_and_inherited_facades(profile):
    hashes = profile.describe()["linguistic_identity"]["runtime_source_hashes"]
    for suffix in ("linguistic.py", "linguistic_cached.py", "_contract.py", "typesafe_advisor.py",
                   "lazy_installer.py", "advisors.py", "daemon_frame_scope.py"):
        assert any(name.endswith(suffix) and len(value) == 64 for name, value in hashes.items())
    assert profile.describe()["historical_environment_reproduced"] is False


def test_original_training_checkpoint_reload_resume_and_tamper(tmp_path, historical):
    model = module.HistoricalDaemonAutoencoder(compute_device="cpu")
    train = model.build_sample(title="training", section="1", text="The agency shall submit reports.")
    tuning = model.build_sample(title="tuning", section="2", text="The agency shall submit notices.")
    old = legacy_v1.Autoencoder(feature_codec=historical["historical"], compute_device="cpu",
                               **historical["historical_constructor_fallbacks"])
    options = dict(epochs=1, learning_rate=.01, max_seconds=60, max_line_search_attempts=1,
                   projection_update_backend="python_sparse_batch", projection_max_update_families=4,
                   legal_ir_bridge_names=(), legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    before = model.state.to_dict()
    report = model.train_generalizable_projection([train], validation_samples=[tuning], **options)
    old_report = old.train_generalizable_projection([train], validation_samples=[tuning], **options)
    assert report["accepted_epochs"] == old_report["accepted_epochs"] == 1
    assert model.state.to_dict() == old.state.to_dict()
    assert model.state.to_dict() != before
    path = tmp_path / "daemon-checkpoint"
    model.save_training_checkpoint(path)
    resumed = module.load_training_checkpoint(path)
    assert resumed.state.to_dict() == model.state.to_dict()
    assert resumed.encode(tuning, use_sample_memory=False) == model.encode(tuning, use_sample_memory=False)
    resumed_report = resumed.train_generalizable_projection([train], validation_samples=[tuning], **options)
    continued_report = model.train_generalizable_projection([train], validation_samples=[tuning], **options)
    assert resumed_report["accepted_epochs"] == continued_report["accepted_epochs"] == 1
    assert resumed.state.to_dict() == model.state.to_dict()
    assert not model.state.decoded_embeddings
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["configuration"]["feature_family_logit_scale"] = 0.5
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="configuration mismatch"):
        module.load_training_checkpoint(path)
