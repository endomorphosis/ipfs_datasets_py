"""Preserve historical linguistic features without activating a formula head."""

from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path

import pytest


PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages"


@pytest.fixture
def profile():
    pytest.importorskip("spacy")
    return importlib.import_module(f"{PREFIX}.legacy_v1.linguistic")


@pytest.fixture
def model(profile):
    return profile.LinguisticAutoencoder(compute_device="cpu")


def sample(model, section="1", noun="reports"):
    return model.build_sample(title="5", section=section,
                              text=f"The agency shall submit {noun}.")


def test_codec_is_historical_except_frozen_import_relocation(profile):
    codec = importlib.import_module(f"{PREFIX}.legacy_v1._linguistic_snapshot.spacy_modal_codec")
    raw = Path(codec.__file__).read_bytes()
    for dependency in ("legal_modal_parser", "legal_samples", "modal_ir", "modal_registry"):
        raw = raw.replace(f"from .._snapshot.{dependency} import".encode(),
                          f"from .{dependency} import".encode())
    assert hashlib.sha256(raw).hexdigest() == "49446ed1e1289ac5cf8cc07e65f67968adc12666ebb66cf951107c9d8c591617"
    assert codec.LegalSample.__module__.startswith(f"{PREFIX}.legacy_v1._snapshot.")
    assert codec.ModalIRDocument.__module__.startswith(f"{PREFIX}.legacy_v1._snapshot.")


def test_old_features_vectors_and_ir_are_repeatable(model):
    row = sample(model)
    codec = model.feature_codec
    assert codec.encoder.used_fallback_model is True
    assert codec.feature_keys_for_sample(row)
    assert codec.compile_sample_ir(row).formulas
    assert codec.decode_sample_embedding(row, dimensions=8) == row.embedding_vector
    before = model.state.to_dict()
    first = model.linguistic_observation(row)
    assert first == model.linguistic_observation(row)
    assert model.state.to_dict() == before
    assert model.formula_checkpoint is None
    assert len(model.decode(model.encode(row, use_sample_memory=False))) == 8
    assert model.describe()["admitted"] is False


def test_installed_model_is_explicit_richer_profile(profile):
    pytest.importorskip("en_core_web_sm")
    model = profile.LinguisticAutoencoder(backend="local_en_core_web_sm", compute_device="cpu")
    row = sample(model)
    encoding = model.feature_codec.encode_sample(row)
    assert model.feature_codec.encoder.used_fallback_model is False
    assert any(token.pos for token in encoding.tokens)
    assert any(token.dep for token in encoding.tokens)
    assert any(token.lemma for token in encoding.tokens)
    assert model.formula_checkpoint is None


@pytest.mark.parametrize("operation", ["targets", "attach", "load", "decode"])
def test_formula_training_and_inference_cannot_replace_legacy_path(model, operation, tmp_path):
    before = model.state.to_dict()
    with pytest.raises((ValueError, RuntimeError, TypeError)):
        if operation == "targets":
            model.train_generalizable_projection(
                [sample(model)], validation_samples=[sample(model, "2", "notices")],
                formula_targets=[{}], validation_formula_targets=[{}])
        elif operation == "attach":
            model.attach_formula_checkpoint({})
        elif operation == "load":
            model.load_formula_checkpoint(tmp_path / "absent.json", expected_sha256="0" * 64)
        else:
            model.decode_formal_logic([sample(model)], mode="learned_latent")
    assert model.state.to_dict() == before
    assert model.formula_checkpoint is None


@pytest.mark.parametrize("validation_kind", ["absent", "empty", "same_id", "same_text"])
def test_validation_must_be_explicit_and_disjoint(model, validation_kind):
    row = sample(model)
    cases = {"absent": None, "empty": [], "same_id": [row],
             "same_text": [replace(row, sample_id="another-id")]}
    before = model.state.to_dict()
    with pytest.raises(ValueError):
        model.train_generalizable_projection([row], validation_samples=cases[validation_kind], epochs=1)
    assert model.state.to_dict() == before


def test_checkpoint_restores_configuration_and_predictions(profile, model, tmp_path):
    model = profile.LinguisticAutoencoder(
        compute_device="cpu", max_codec_feature_keys=17,
        feature_family_logit_scale=0.125, cosine_reconstruction_weight=0.3)
    row = sample(model)
    model.state.feature_embedding_weights["fixture"] = [0.01] * 8
    before = model.state.to_dict()
    prediction = model.encode(row, use_sample_memory=False)
    path = tmp_path / "bundle"
    model.save_training_checkpoint(path)
    files_before = {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    restored = profile.load_training_checkpoint(path)
    assert restored.state.to_dict() == before
    assert restored.max_codec_feature_keys == 17
    assert restored.feature_family_logit_scale == 0.125
    assert restored.cosine_reconstruction_weight == 0.3
    assert restored.encode(row, use_sample_memory=False) == prediction
    assert restored.linguistic_observation(row) == model.linguistic_observation(row)
    assert restored.formula_checkpoint is None
    assert files_before == {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    with pytest.raises((ValueError, FileExistsError)):
        model.save_training_checkpoint(path)


def test_checkpoint_tampering_fails_closed(profile, model, tmp_path):
    path = tmp_path / "bundle"
    model.save_training_checkpoint(path)
    candidates = [p for p in path.glob("*.json") if "state" in p.name]
    assert len(candidates) == 1
    with candidates[0].open("a") as handle:
        handle.write(" ")
    with pytest.raises(ValueError):
        profile.load_training_checkpoint(path)


def test_foreign_384_state_rejected_before_feature_training(profile):
    current = importlib.import_module(f"{PREFIX}.current_v2")
    state = current.TrainingState()
    before = state.to_dict()
    with pytest.raises(TypeError):
        profile.LinguisticAutoencoder(state=state, compute_device="cpu")
    assert state.to_dict() == before


def test_codec_injection_is_not_a_silent_profile_change(profile):
    with pytest.raises((TypeError, ValueError)):
        profile.LinguisticAutoencoder(feature_codec=object(), compute_device="cpu")


def test_manifest_cannot_silently_change_backend(profile, model, tmp_path):
    pytest.importorskip("en_core_web_sm")
    path = tmp_path / "bundle"
    model.save_training_checkpoint(path)
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["configuration"]["backend"] = "local_en_core_web_sm"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        profile.load_training_checkpoint(path)


def test_runtime_configuration_drift_is_rejected(model, tmp_path):
    model.feature_family_logit_scale = 0.25
    with pytest.raises(ValueError):
        model.save_training_checkpoint(tmp_path / "bundle")


def test_other_linguistic_representation_is_rejected(profile, model):
    pytest.importorskip("en_core_web_sm")
    richer = profile.LinguisticAutoencoder(backend="local_en_core_web_sm", compute_device="cpu")
    row = sample(richer)
    with pytest.raises(ValueError):
        model.encode(row, use_sample_memory=False)


def test_wrapper_preserves_original_numerical_training(profile):
    """Compare real accepted updates against the unwrapped frozen trainer."""
    legacy = importlib.import_module(f"{PREFIX}.legacy_v1")
    model = profile.LinguisticAutoencoder(compute_device="cpu", feature_family_logit_scale=1.0)
    original = legacy.Autoencoder(compute_device="cpu", feature_codec=model.feature_codec,
                                  max_codec_feature_keys=64, feature_family_logit_scale=1.0)
    train, tuning = sample(model), sample(model, "2", "notices")
    options = dict(epochs=1, learning_rate=0.01, max_seconds=30,
                   max_line_search_attempts=1, projection_update_backend="python_sparse_batch",
                   projection_max_update_families=4, legal_ir_bridge_names=(),
                   legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    wrapped = model.train_generalizable_projection([train], validation_samples=[tuning], **options)
    unwrapped = original.train_generalizable_projection([train], validation_samples=[tuning], **options)
    assert wrapped["accepted_epochs"] == unwrapped["accepted_epochs"] == 1
    assert model.state.to_dict() == original.state.to_dict()
    assert model.state.feature_family_logits
    assert not model.state.decoded_embeddings


def test_historical_quantitative_formula_feature_option_is_still_supported(profile):
    model = profile.LinguisticAutoencoder(compute_device="cpu", max_quantitative_formula_features=12)
    assert model.max_quantitative_formula_features == 12


def test_canonical_formula_route_is_distinct_from_historical_feature_ir(model):
    row = model.build_sample(title="5", section="negative-fixture",
                             text="The agency shall not disclose records.")
    # Preserve and expose this known historical conflict, never qualify it.
    historical = model.linguistic_observation(row)
    formulas = historical["modal_ir"]["formulas"]
    assert [f["operator"]["symbol"] for f in formulas if f["operator"]["family"] == "deontic"] == ["O"]
    assert historical["semantic_qualification"] is False
    result = model.decode_formal_logic([row])
    assert result["mode"] == "canonical_compiler"
    assert result["rows"][0]["formal_outputs"][0]["payload"]["modality"] == "F"
    assert result["admitted"] is False
    with pytest.raises(ValueError):
        model.decode_formal_logic([row], mode="guided_compiler")
