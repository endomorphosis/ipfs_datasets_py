"""Real joint decoder training over authored, explicitly synthetic modal vectors.

These tests establish integration and exact persistence, not semantic embedding
quality, held-out generalization, legal formalization or Lake admission.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import importlib
import importlib.util
from pathlib import Path

import pytest


PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
joint = importlib.import_module(PREFIX + ".modal_joint_formula")

# Reuse the existing typed fixture: no parser/ranker, network or weights needed.
_fixture_path = Path(__file__).parents[2] / "logic/test_autoencoder_lineage_runtimes.py"
_spec = importlib.util.spec_from_file_location("_modal_joint_lineage_fixture", _fixture_path)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
sample = _fixtures.sample


@pytest.fixture(params=("legacy_v1", "current_v2"))
def lineage(request):
    return importlib.import_module(PREFIX + ".autoencoder_lineages." + request.param)


def _training_rows(lineage):
    train = [sample(lineage, "reports"), sample(lineage, "notices")]
    train[1] = replace(train[1], embedding_vector=[-value for value in train[1].embedding_vector])
    # Deliberately equivalent synthetic structures with different wording and
    # new IDs; this checks wiring, not independent legal generalization.
    tuning = []
    for row in train:
        text = row.text.replace("shall", "must")
        tuning.append(replace(row, sample_id="tuning-" + row.sample_id,
            text=text, normalized_text=text, modal_ir=replace(row.modal_ir,
                document_id="tuning-" + row.sample_id, normalized_text=text)))
    def target(row):
        return {"id": row.sample_id, "source_text": row.text,
                "canonical_ir": {"rules": [{"modality": "O", "actor": "agency",
                    "action": "submit", "object": row.modal_ir.formulas[0].predicate.arguments[-1],
                    "conditions": [], "exceptions": [], "temporal": []}]}}
    return train, tuning, [target(row) for row in train], [target(row) for row in tuning]


def test_raw_projection_is_actual_additive_candidate_before_safety_and_memory(lineage, monkeypatch):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    width = lineage.DIMENSION
    vector = [0.003 * (i % 5 - 2) for i in range(width)]
    for key in model._feature_keys_for(row):
        model.state.feature_embedding_weights[key] = list(vector)
    for method, table in (
        ("_logic_signature_distribution_for", "logic_signature_embedding_weights"),
        ("_decompiler_plan_distribution_for", "decompiler_plan_embedding_weights"),
        ("_predicate_argument_distribution_for", "predicate_argument_embedding_weights"),
    ):
        for key in getattr(model, method)(row):
            getattr(model.state, table)[key] = list(vector)
    model.state.family_embedding_weights["deontic"] = list(vector)
    model.state.decoded_embeddings[row.sample_id] = [99.0] * width
    model.state.family_logits[row.sample_id] = {"deontic": -999.0, "temporal": 999.0}
    before = copy.deepcopy(model.state.to_dict())
    captured = []
    def capture(target, base, candidate):
        captured.append(list(candidate))
        assert candidate != base
        return [-77.0] * width
    monkeypatch.setattr(model, "_reconstruction_safe_projection", capture)
    assert model._decoded_for(row, use_sample_memory=False) == [-77.0] * width
    assert len(captured) == 1
    observed = joint.raw_projection(model, row)
    assert observed == captured[0]
    assert len(captured) == 1  # Extraction did not call the safety projection.
    assert observed != model.state.decoded_embeddings[row.sample_id]
    assert model.state.to_dict() == before


@pytest.mark.parametrize("cache_name", ("_legal_ir_view_target_cache", "_legal_ir_loss_target_cache"))
def test_cached_teacher_targets_are_rejected_without_erasure(lineage, cache_name):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    cache = getattr(model, cache_name)
    cache[row.sample_id] = {"teacher": 1.0}
    original = copy.deepcopy(cache)
    with pytest.raises(ValueError, match="teacher bridge targets"):
        joint.raw_projection(model, row)
    assert cache == original


def test_targets_bind_exact_source_and_sample_identity_before_training(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    train, _, targets, _ = _training_rows(lineage)
    for field in ("id", "source_text"):
        altered = copy.deepcopy(targets)
        altered[0][field] += " altered"
        with pytest.raises(ValueError, match="exact sample ID and text"):
            joint._rows(model, train, altered)
    extra = copy.deepcopy(targets)
    extra[0]["admitted"] = True
    with pytest.raises(ValueError, match="closed id/source_text/canonical_ir"):
        joint._rows(model, train, extra)


@pytest.mark.parametrize("mismatch", ("document_id", "source_text", "normalized_text"))
def test_modal_features_bind_sample_identity_and_normalized_source(lineage, mismatch):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    if mismatch == "document_id":
        row = replace(row, modal_ir=replace(row.modal_ir, document_id="another-sample"))
    elif mismatch == "source_text":
        row = replace(row, text="The agency shall not submit reports.")
    else:
        row = replace(row, normalized_text="different normalized source",
                      modal_ir=replace(row.modal_ir, normalized_text="different normalized source"))
    with pytest.raises(ValueError, match="exact sample identity and normalized source"):
        joint._rows(model, [row])


def test_identical_weights_yield_identical_inputs_despite_stale_family_cache(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    model.state.legal_ir_view_embedding_weights["deontic.ir"] = [0.1] * model.DIMENSION
    model.state.legal_ir_view_embedding_weights["TDFOL.prover"] = [0.2] * model.DIMENSION
    pristine = lineage.Autoencoder(state=lineage.TrainingState.from_dict(model.state.to_dict()), compute_device="cpu")
    row = sample(lineage)
    expected = joint._rows(pristine, [row])
    model._legal_ir_view_family_candidates_cache = ("stale.fake",)
    assert joint._rows(model, [row]) == expected
    assert model._legal_ir_view_family_candidates_cache is None
    assert model.state.to_dict() == pristine.state.to_dict()


def test_raw_readout_ignores_sample_view_memory_and_preserves_owner_state_and_caches(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    model.state.legal_ir_view_embedding_weights["deontic.ir"] = [0.3] * model.DIMENSION
    expected = joint.raw_projection(model, row)
    # Historical _legal_ir_view_distribution reads per-sample family-logit
    # keys even when use_sample_memory=False. The private extraction view must
    # remove this hidden input without deleting memories from the owner.
    model.state.family_logits[row.sample_id] = {"fake.view": 1.0}
    model.state.decoded_embeddings[row.sample_id] = [99.0] * model.DIMENSION
    model._sample_feature_cache["unrelated-owner-entry"] = {"sentinel": "preserve"}
    model._legal_ir_view_family_candidates_cache = ("stale.fake",)
    before_state = copy.deepcopy(model.state.to_dict())
    before_samples = copy.deepcopy(model._sample_feature_cache)
    before_families = model._legal_ir_view_family_candidates_cache
    assert joint.raw_projection(model, row) == expected
    assert model.state.to_dict() == before_state
    assert model._sample_feature_cache == before_samples
    assert model._legal_ir_view_family_candidates_cache == before_families


def test_core_binding_tracks_sparse_weights_configuration_and_source(lineage, monkeypatch):
    model = lineage.Autoencoder(compute_device="cpu")
    expected = joint._core_binding(model)
    assert expected["dimension"] == lineage.DIMENSION
    model.state.family_embedding_weights["deontic"] = [0.1] * lineage.DIMENSION
    assert joint._core_binding(model) != expected
    model.state.family_embedding_weights.clear()
    assert joint._core_binding(model) == expected
    model.initial_embedding_scale += 0.001
    assert joint._core_binding(model) != expected
    model.initial_embedding_scale -= 0.001
    assert joint._core_binding(model) == expected
    original_read = Path.read_bytes
    source = Path(joint.__file__)
    def changed_source(path):
        data = original_read(path)
        return data + b"\n# synthetic source drift\n" if path == source else data
    monkeypatch.setattr(Path, "read_bytes", changed_source)
    assert joint._core_binding(model) != expected


def test_custom_unbound_feature_codec_rejected(lineage):
    model = lineage.Autoencoder(compute_device="cpu", feature_codec=object())
    with pytest.raises(ValueError, match="external codecs need a versioned binding"):
        joint._core_binding(model)


@pytest.fixture(scope="module", params=("legacy_v1", "current_v2"))
def trained(request):
    torch = pytest.importorskip("torch")
    old_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    namespace = importlib.import_module(PREFIX + ".autoencoder_lineages." + request.param)
    model = namespace.Autoencoder(compute_device="cpu")
    rows, tuning, targets, tuning_targets = _training_rows(namespace)
    for row in rows + tuning:
        model.state.decoded_embeddings[row.sample_id] = [99.0] * namespace.DIMENSION
    core_before = copy.deepcopy(model.state.to_dict())
    result = model.train_generalizable_projection(
        rows, validation_samples=tuning,
        formula_targets=targets, validation_formula_targets=tuning_targets,
        formula_options={"learning_rate": 0.03, "batch_size": 2, "hidden_size": 16,
                         "token_embedding_dim": 8, "projection_width": 4, "seed": 1729},
        epochs=250, max_seconds=60,
    )
    yield {"lineage": namespace, "model": model, "result": result,
           "rows": rows, "tuning": tuning, "targets": targets,
           "tuning_targets": tuning_targets, "core_before": core_before}
    torch.set_num_threads(old_threads)


def _clone(trained):
    lineage = trained["lineage"]
    model = lineage.Autoencoder(
        state=lineage.TrainingState.from_dict(trained["core_before"]), compute_device="cpu")
    model.attach_formula_checkpoint(trained["result"]["checkpoint"])
    return model


def test_facade_joint_training_updates_projection_and_decoder_and_learns_formulas(trained):
    model = trained["model"]
    report = trained["result"]["report"]
    assert report["training_executed"]
    assert report["optimizer_steps"] == 250
    assert report["training_after"]["token_cross_entropy"] < report["training_before"]["token_cross_entropy"] / 10
    assert report["training_after"]["reconstruction_mse"] < report["training_before"]["reconstruction_mse"]
    assert report["formula_projection_gradient_norm_max"] > 0
    for group in ("projection", "decoder"):
        evidence = report["parameter_evidence"][group]
        assert evidence["initial_parameters_sha256"] != evidence["final_parameters_sha256"]
        assert evidence["parameter_update_l2"] > 0
        assert evidence["gradient_norm_max"] > 0
    assert model.state.to_dict() == trained["core_before"]
    result = model.decode_formal_logic(trained["rows"])
    assert [row["canonical_ir"] for row in result["rows"]] == [row["canonical_ir"] for row in trained["targets"]]
    assert all(row["formula_text"] and row["formal_outputs"] for row in result["rows"])
    assert all(row["temperature"] == 0 for row in result["rows"])
    assert result["sample_memory_used"] is False
    assert result["target_access"] is False
    assert result["training_executed"] is False
    assert result["joint_profile"]["core_sparse_weights_frozen"]
    assert result["joint_profile"]["full_logic_floor_coverage"] is False
    for field in joint.FALSE:
        assert result[field] is False


def test_attached_encode_and_evaluate_use_joint_model_without_training_or_compiler(trained, monkeypatch):
    model = _clone(trained)
    learning = importlib.import_module(PREFIX + ".modal_latent_formula")
    decoder = importlib.import_module(PREFIX + ".legal_formal_decoder")
    checkpoint_before = model.formula_checkpoint
    def forbidden(*args, **kwargs):
        raise AssertionError("joint inference called training, target encoder, legacy evaluation or compiler")
    monkeypatch.setattr(joint, "train", forbidden)
    monkeypatch.setattr(learning.codec_module, "encode_target", forbidden)
    monkeypatch.setattr(decoder, "decode_legal_formulas", forbidden)
    monkeypatch.setattr(model._implementation_class, "evaluate", forbidden)
    row = trained["rows"][0]
    raw = joint.raw_projection(model, row)
    encoded = model.encode(row)
    reconstructed = model.decode(encoded)
    assert reconstructed != raw
    assert reconstructed != model.state.decoded_embeddings[row.sample_id]
    assert len(reconstructed) == trained["lineage"].DIMENSION
    assert encoded["projection_origin"] == "joint_learned_residual_projection"
    evaluated = model.evaluate(trained["rows"])
    assert evaluated == model.decode_formal_logic(trained["rows"])
    assert evaluated["decoded_embeddings"][row.sample_id] == pytest.approx(reconstructed, abs=1e-6)
    assert evaluated["reconstruction_loss"] >= 0
    assert model.formula_checkpoint == checkpoint_before
    with pytest.raises(ValueError, match="forbids sample memory"):
        model.encode(row, use_sample_memory=True)


def test_attached_decoder_training_cannot_be_skipped_and_checkpoint_is_not_aliased(trained):
    model = _clone(trained)
    before = model.formula_checkpoint
    exposed = model.formula_checkpoint
    exposed["progress"]["optimizer_steps"] = 0
    assert model.formula_checkpoint == before
    incoming = copy.deepcopy(before)
    model.attach_formula_checkpoint(incoming)
    incoming["progress"]["optimizer_steps"] = 0
    assert model.formula_checkpoint == before
    with pytest.raises(ValueError, match="decoder training cannot be skipped"):
        model.train_generalizable_projection(trained["rows"], validation_samples=trained["tuning"], epochs=1)
    assert model.formula_checkpoint == before


@pytest.mark.parametrize("changed", ("core", "configuration", "source"))
def test_attached_formula_checkpoint_rejects_changed_core_configuration_or_source(trained, monkeypatch, changed):
    model = _clone(trained)
    checkpoint = model.formula_checkpoint
    if changed == "core":
        model.state.family_embedding_weights["deontic"] = [0.1] * model.DIMENSION
    elif changed == "configuration":
        model.initial_embedding_scale += 0.001
    else:
        original_read = Path.read_bytes
        source = Path(joint.__file__)
        def changed_source(path):
            data = original_read(path)
            return data + b"\n# synthetic source drift\n" if path == source else data
        monkeypatch.setattr(Path, "read_bytes", changed_source)
    with pytest.raises(ValueError, match="core changed|source drift|another core"):
        model.decode_formal_logic(trained["rows"])
    with pytest.raises(ValueError, match="another core|source drift"):
        model.attach_formula_checkpoint(checkpoint)


def test_formula_checkpoint_roundtrip_hash_exclusive_write_and_cross_lineage_rejection(trained, tmp_path):
    model = _clone(trained)
    path = tmp_path / "authored-diagnostic-head.json"
    receipt = model.save_formula_checkpoint(path)
    assert receipt["core_weights_included"] is False
    restored = trained["lineage"].Autoencoder(
        state=trained["lineage"].TrainingState.from_dict(trained["core_before"]), compute_device="cpu")
    restored.load_formula_checkpoint(path, expected_sha256=receipt["sha256"])
    assert restored.formula_checkpoint == model.formula_checkpoint
    assert restored.decode_formal_logic(trained["rows"]) == model.decode_formal_logic(trained["rows"])
    with pytest.raises(FileExistsError):
        model.save_formula_checkpoint(path)
    with pytest.raises(ValueError, match="hash differs|hash mismatch"):
        restored.load_formula_checkpoint(path, expected_sha256="0" * 64)
    other_name = "current_v2" if model.DIMENSION == 8 else "legacy_v1"
    other = importlib.import_module(PREFIX + ".autoencoder_lineages." + other_name)
    foreign = other.Autoencoder(compute_device="cpu")
    with pytest.raises(ValueError, match="another core, lineage or configuration"):
        foreign.attach_formula_checkpoint(model.formula_checkpoint)
    with pytest.raises(ValueError, match="another core, lineage or configuration|binding differs"):
        foreign.load_formula_checkpoint(path, expected_sha256=receipt["sha256"])
    assert foreign.formula_checkpoint is None


def test_resumed_facade_trains_projection_and_decoder_in_same_optimizer_step(trained):
    model = _clone(trained)
    before = model.formula_checkpoint
    result = model.train_generalizable_projection(
        trained["rows"], validation_samples=trained["tuning"],
        formula_targets=trained["targets"], validation_formula_targets=trained["tuning_targets"],
        epochs=1, max_seconds=15,
    )
    assert result["checkpoint"]["progress"]["optimizer_steps"] == before["progress"]["optimizer_steps"] + 1
    assert result["report"]["formula_projection_gradient_norm_max"] > 0
    for group in ("projection", "decoder"):
        assert result["report"]["parameter_evidence"][group]["parameter_update_l2"] > 0
    assert model.formula_checkpoint == result["checkpoint"]
    assert model.state.to_dict() == trained["core_before"]


def test_runtime_registry_loads_and_trains_the_same_attached_decoder(trained, tmp_path):
    registry = importlib.import_module(PREFIX + ".autoencoder_runtime_registry")
    namespace = trained["lineage"]
    version = namespace.__name__.rsplit(".", 1)[-1]
    options = {"compute_device": "cpu"}
    runtime = registry.LegalRuntime(version,
        state=namespace.TrainingState.from_dict(trained["core_before"]),
        formula_checkpoint=trained["result"]["checkpoint"], **options)
    assert runtime.describe()["model"]["learned_latent_formula_decoder"] is True
    assert runtime.infer(trained["rows"]) == runtime.decode_formal_logic(trained["rows"])
    path = tmp_path / "registry-head.json"
    saved = runtime.model.save_formula_checkpoint(path)
    loaded = registry.LegalRuntime(version,
        state=namespace.TrainingState.from_dict(trained["core_before"]),
        formula_checkpoint=path, formula_sha256=saved["sha256"], **options)
    assert loaded.infer(trained["rows"]) == runtime.infer(trained["rows"])
    result = loaded.train(trained["rows"], validation_samples=trained["tuning"],
        formula_targets=trained["targets"], validation_formula_targets=trained["tuning_targets"],
        epochs=1, max_seconds=15)
    assert result["report"]["optimizer_steps"] == 1
    assert loaded.model.formula_checkpoint["progress"]["optimizer_steps"] == 251
    with pytest.raises(ValueError, match="no bridge or compiler options"):
        loaded.infer(trained["rows"], use_sample_memory=True)


def test_same_width_optimized_profile_rejects_legacy_head_and_trains_its_own():
    torch = pytest.importorskip("torch")
    legacy = importlib.import_module(PREFIX + ".autoencoder_lineages.legacy_v1")
    optimized = importlib.import_module(PREFIX + ".autoencoder_lineages.legacy_v1_optimized")
    left = legacy.Autoencoder(compute_device="cpu")
    right = optimized.Autoencoder(compute_device="cpu")
    assert left.DIMENSION == right.DIMENSION == 8
    rows, tuning, targets, tuning_targets = _training_rows(legacy)
    options = {"formula_targets": targets, "validation_formula_targets": tuning_targets,
               "validation_samples": tuning, "epochs": 1, "max_seconds": 15,
               "formula_options": {"learning_rate": 0.03, "batch_size": 2, "hidden_size": 16,
                   "token_embedding_dim": 8, "projection_width": 4, "seed": 1729}}
    old_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        left.train_generalizable_projection(rows, **options)
        with pytest.raises(ValueError, match="another core, lineage or configuration"):
            right.attach_formula_checkpoint(left.formula_checkpoint)
        right.train_generalizable_projection(rows, **options)
        assert right.formula_checkpoint["progress"]["optimizer_steps"] == 1
        assert right.formula_checkpoint["binding"] != left.formula_checkpoint["binding"]
        assert right.attach_formula_checkpoint(right.formula_checkpoint)["attached"]
    finally:
        torch.set_num_threads(old_threads)
