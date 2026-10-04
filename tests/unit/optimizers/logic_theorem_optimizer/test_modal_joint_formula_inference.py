"""Opt-in projection/session parity and mutable-source integrity boundaries."""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import importlib
import importlib.util
import math
from pathlib import Path
import struct

import pytest


PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
joint = importlib.import_module(PREFIX + ".modal_joint_formula")
fast = importlib.import_module(PREFIX + ".modal_joint_formula_inference")
_fixture_path = Path(__file__).parents[2] / "logic/test_autoencoder_lineage_runtimes.py"
_spec = importlib.util.spec_from_file_location("_fast_joint_lineage_fixture", _fixture_path)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
sample = _fixtures.sample


@pytest.fixture(params=("legacy_v1", "current_v2"))
def lineage(request):
    return importlib.import_module(PREFIX + ".autoencoder_lineages." + request.param)


def _seed_weights(model, rows):
    """Exercise every sparse adjustment with deterministic, distinct vectors."""
    def vector(key):
        seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big")
        return [0.003 * ((seed + index) % 13 - 6) for index in range(model.DIMENSION)]
    model.state.legal_ir_view_embedding_weights.update(
        {view: vector(view) for view in ("deontic.ir", "TDFOL.prover")})
    methods = (
        ("compiler_quality", "_compiler_quality_slot_distribution_for", False),
        ("logic_signature", "_logic_signature_distribution_for", False),
        ("round_trip_signal", "_round_trip_signal_distribution_for", False),
        ("decompiler_plan", "_decompiler_plan_distribution_for", False),
        ("predicate_argument", "_predicate_argument_distribution_for", False),
        ("family", "_family_distribution_for_embedding", True),
        ("semantic_slot", "_semantic_slot_distribution_for", False),
        ("family_semantic_slot", "_family_semantic_slot_distribution_for_embedding", True),
        ("semantic_slot_legal_ir_view", "_semantic_slot_legal_ir_view_distribution_for_embedding", True),
        ("family_semantic_slot_legal_ir_view", "_family_semantic_slot_legal_ir_view_distribution_for_embedding", True),
        ("family_legal_ir_view", "_family_legal_ir_view_distribution_for_embedding", True),
    )
    for row in rows:
        for name, method, memory in methods:
            options = {"use_sample_memory": False} if memory else {}
            table = getattr(model.state, name + "_embedding_weights")
            for key in getattr(model, method)(row, **options):
                table[key] = vector(name + key)
        for key in model._feature_keys_for(row):
            model.state.feature_embedding_weights[key] = vector(key)
    model._sample_feature_cache.clear()
    model._invalidate_legal_ir_view_family_candidates()


def test_private_projection_matches_original_all_sparse_adjustments_and_memory_isolation(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    _seed_weights(model, [row])
    model.state.family_logits[row.sample_id] = {"fake.view": 1000.0}
    model.state.decoded_embeddings[row.sample_id] = [999.0] * model.DIMENSION
    model._sample_feature_cache["owner-sentinel"] = {"sentinel": "preserve"}
    model._legal_ir_view_family_candidates_cache = ("stale.fake",)
    state_before = copy.deepcopy(model.state.to_dict())
    identity_before = model.state.state_identity_record()
    tracker_before = model.state._state_identity_tracker
    caches_before = copy.deepcopy(model._sample_feature_cache)
    sample_before = copy.deepcopy(row)
    expected = joint.raw_projection(model, row)
    assert fast.raw_projection(model, row) == expected
    assert model.state.to_dict() == state_before
    assert model._sample_feature_cache == caches_before
    assert model._legal_ir_view_family_candidates_cache == ("stale.fake",)
    assert row == sample_before
    assert model.state._state_identity_tracker is tracker_before
    assert model.state.state_identity_record() == identity_before
    assert "_sample_cache_for" not in model.__dict__


def test_validated_package_empty_heads_preserve_original_projection_and_signed_zeros(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    row.embedding_vector[:] = [-0.0, 0.0] * (model.DIMENSION // 2)
    state_before = copy.deepcopy(model.state.to_dict())
    identity_before = model.state.state_identity_record()
    expected = joint.raw_projection(model, row)
    actual = fast.raw_projection(model, row, _validated_package_sample=True)
    assert actual == expected
    assert [struct.pack("!d", value) for value in actual] == [struct.pack("!d", value) for value in expected]
    assert model.state.to_dict() == state_before
    assert model.state.state_identity_record() == identity_before
    model.state.family_embedding_weights["deontic"] = [0.25] * model.DIMENSION
    assert fast.raw_projection(model, row, _validated_package_sample=True) == joint.raw_projection(model, row)
    assert fast.raw_projection(model, row, _validated_package_sample=True) != actual


def test_validated_package_path_preserves_populated_heads_and_never_skips_legacy_tail(lineage, monkeypatch):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    _seed_weights(model, [row])
    calls = 0
    original = model._implementation_class._legacy_embedding_tail_adjustment
    def tail(worker, snapshot, **options):
        nonlocal calls
        calls += 1
        return original(worker, snapshot, **options)
    monkeypatch.setattr(model._implementation_class, "_legacy_embedding_tail_adjustment", tail)
    expected = joint.raw_projection(model, row)
    observed = fast.raw_projection(model, row, _validated_package_sample=True)
    assert observed == expected
    assert calls == 2


def test_default_empty_state_still_rejects_malformed_ir_and_nonboolean_package_flags(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    malformed = replace(row, modal_ir=None)
    with pytest.raises(AttributeError):
        joint.raw_projection(model, malformed)
    with pytest.raises(AttributeError):
        fast.raw_projection(model, malformed)
    with pytest.raises(ValueError, match="flag must be boolean"):
        fast.raw_projection(model, row, _validated_package_sample=1)


@pytest.mark.parametrize("nested_field", ("embedding", "argument", "metadata"))
def test_each_projection_observes_new_nested_mutations(lineage, nested_field):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    _seed_weights(model, [row])
    before = fast.raw_projection(model, row)
    if nested_field == "embedding":
        row.embedding_vector[0] += 0.25
    elif nested_field == "argument":
        row.modal_ir.formulas[0].predicate.arguments[-1] = "new-object"
    else:
        row.modal_ir.formulas[0].metadata["cue"] = "shall-not"
    after = fast.raw_projection(model, row)
    assert after == joint.raw_projection(model, row)
    assert after != before


def test_helpers_read_owned_snapshot_during_external_nested_mutation(lineage, monkeypatch):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    _seed_weights(model, [row])
    expected = joint.raw_projection(model, row)
    original = model._implementation_class._base_decoded_for
    def observe(worker, snapshot):
        assert snapshot is not row
        assert snapshot.embedding_vector is not row.embedding_vector
        assert snapshot.modal_ir is not row.modal_ir
        assert snapshot.modal_ir.formulas[0].predicate.arguments is not row.modal_ir.formulas[0].predicate.arguments
        row.embedding_vector[0] += 9.0
        row.modal_ir.formulas[0].predicate.arguments[-1] = "changed-during-extraction"
        return original(worker, snapshot)
    monkeypatch.setattr(model._implementation_class, "_base_decoded_for", observe)
    assert fast.raw_projection(model, row) == expected
    assert "_sample_cache_for" not in model.__dict__


def test_readout_avoids_sparse_state_reconstruction_and_preserves_mutation_tracking(lineage, monkeypatch):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    _seed_weights(model, [row])
    expected = joint.raw_projection(model, row)
    identity = model.state.state_identity()
    revision = model.state.state_revision
    def forbidden(state):
        raise AssertionError("inference rebuilt recursive tracking for the sparse state")
    monkeypatch.setattr(lineage.TrainingState, "__post_init__", forbidden)
    monkeypatch.setattr(lineage.TrainingState, "__copy__", forbidden)
    assert fast.raw_projection(model, row) == expected
    assert model.state.state_identity() == identity
    assert model.state.state_revision == revision
    model.state.family_embedding_weights["deontic"][0] += 0.25
    assert model.state.state_revision > revision
    assert model.state.state_identity() != identity


def test_private_candidate_order_matches_core_across_all_tables_and_key_types(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    vector = [0.0] * model.DIMENSION
    model.state.legal_ir_view_embedding_weights.update(
        {"first.view": vector, "deontic": vector, 7: vector})
    model.state.family_legal_ir_view_embedding_weights.update(
        {"deontic||second.view": vector, "bad||key||ignored.view": vector})
    model.state.semantic_slot_legal_ir_view_embedding_weights.update(
        {"slot||first.view": vector, "slot||third.view": vector})
    model.state.family_semantic_slot_legal_ir_view_embedding_weights.update(
        {"family||slot||fourth.view": vector, "bad||ignored.view": vector})
    model.state.legal_ir_view_logits.update({"fifth.view": 1.0, "first.view": 2.0})
    for index, name in enumerate((
        "feature_legal_ir_view_logits", "feature_family_logits",
        "semantic_slot_legal_ir_view_logits", "logic_signature_legal_ir_view_logits",
        "round_trip_signal_legal_ir_view_logits", "decompiler_plan_legal_ir_view_logits",
        "predicate_argument_legal_ir_view_logits", "family_semantic_slot_legal_ir_view_logits",
    )):
        getattr(model.state, name)["row"] = {
            "first.view": 1.0, "deontic": 2.0, f"table-{index}.view": 3.0,
            "7": 4.0, 7.0: 5.0,
        }
    model._invalidate_legal_ir_view_family_candidates()
    expected = model._legal_ir_view_family_candidates()
    model._legal_ir_view_family_candidates_cache = ("owner-stale.view",)
    assert fast._view_family_candidates(fast._worker(model)) == expected
    assert expected[:7] == ("first.view", "7", "second.view", "third.view",
                           "fourth.view", "fifth.view", "table-0.view")
    assert "7.0" in expected
    assert "deontic" not in expected
    assert "ignored.view" not in expected
    assert model._legal_ir_view_family_candidates_cache == ("owner-stale.view",)


def test_batch_reuses_candidates_only_within_request_without_touching_owner_caches(lineage, monkeypatch):
    model = lineage.Autoencoder(compute_device="cpu")
    rows = [sample(lineage, "reports"), sample(lineage, "notices")]
    _seed_weights(model, rows)
    expected = [joint.raw_projection(model, row) for row in rows]
    model._sample_feature_cache["owner-sentinel"] = {"preserve": True}
    model._legal_ir_view_family_candidates_cache = ("owner-stale.view",)
    caches_before = copy.deepcopy(model._sample_feature_cache)
    build_count = 0
    original = fast._view_family_candidates
    def candidates(worker):
        nonlocal build_count
        if worker._legal_ir_view_family_candidates_cache is None:
            build_count += 1
        return original(worker)
    monkeypatch.setattr(fast, "_view_family_candidates", candidates)
    actual = fast._rows(model, rows)
    assert [row["latent"] for row in actual] == expected
    assert build_count == 1
    assert model._sample_feature_cache == caches_before
    assert model._legal_ir_view_family_candidates_cache == ("owner-stale.view",)
    assert "_request_sample_cache_for" not in model.__dict__
    assert "_legal_ir_view_family_candidates" not in model.__dict__

    model.state.legal_ir_view_embedding_weights["new.request.view"] = [0.5] * model.DIMENSION
    rows[1].embedding_vector[0] += 0.25
    expected = [joint.raw_projection(model, row) for row in rows]
    actual = fast._rows(model, rows)
    assert [row["latent"] for row in actual] == expected
    assert build_count == 2
    assert model._sample_feature_cache == caches_before
    assert model._legal_ir_view_family_candidates_cache == ("owner-stale.view",)


def test_owned_sample_readout_reuse_returns_fresh_dicts_and_observes_sparse_revisions(lineage, monkeypatch):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    _seed_weights(model, [row])
    readouts = []
    implementation = model._implementation_class
    original_view = implementation._legal_ir_view_distribution_for_embedding
    original_base = implementation._base_decoded_for
    def view(worker, snapshot, *, use_sample_memory):
        readouts.append(worker.state.state_revision)
        return original_view(worker, snapshot, use_sample_memory=use_sample_memory)
    def probe(worker, snapshot):
        first = worker._legal_ir_view_distribution_for_embedding(snapshot, use_sample_memory=False)
        first["caller-mutated.view"] = 999.0
        second = worker._legal_ir_view_distribution_for_embedding(snapshot, use_sample_memory=False)
        assert "caller-mutated.view" not in second
        assert len(readouts) == 1
        worker.state.legal_ir_view_logits["deontic.ir"] = 10.0
        third = worker._legal_ir_view_distribution_for_embedding(snapshot, use_sample_memory=False)
        assert len(readouts) == 2
        assert third != second
        return original_base(worker, snapshot)
    monkeypatch.setattr(implementation, "_legal_ir_view_distribution_for_embedding", view)
    monkeypatch.setattr(implementation, "_base_decoded_for", probe)
    observed = fast.raw_projection(model, row)
    assert len(readouts) == 2
    monkeypatch.setattr(implementation, "_base_decoded_for", original_base)
    assert observed == joint.raw_projection(model, row)


@pytest.mark.parametrize("batch", (False, True))
def test_private_caches_are_discarded_after_extraction_failure(lineage, monkeypatch, batch):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    _seed_weights(model, [row])
    captured = []
    def fail(worker, snapshot):
        captured.append(worker)
        worker._sample_cache_for(snapshot)["private.observation"] = "temporary"
        worker._legal_ir_view_distribution_for_embedding(snapshot, use_sample_memory=False)
        raise RuntimeError("extraction interrupted")
    monkeypatch.setattr(model._implementation_class, "_base_decoded_for", fail)
    with pytest.raises(RuntimeError, match="extraction interrupted"):
        fast._rows(model, [row]) if batch else fast.raw_projection(model, row)
    assert len(captured) == 1
    worker = captured[0]
    assert worker._sample_feature_cache == {}
    assert worker._legal_ir_view_family_candidates_cache is None
    for name in ("_sample_cache_for", "_request_sample_cache_for",
                 "_legal_ir_view_family_candidates", "_legal_ir_view_distribution_for_embedding",
                 "_request_view_distribution_for_embedding", "_request_sample_readouts",
                 "_cue_names_for_text", "_request_cue_names_for_text", *fast._SAMPLE_READOUTS):
        assert name not in worker.__dict__
        assert name not in model.__dict__


@pytest.fixture(scope="module", params=("legacy_v1", "current_v2"))
def checkpointed(request):
    torch = pytest.importorskip("torch")
    learning = importlib.import_module(PREFIX + ".modal_latent_formula")
    namespace = importlib.import_module(PREFIX + ".autoencoder_lineages." + request.param)
    model = namespace.Autoencoder(compute_device="cpu")
    rows = [sample(namespace, "reports"), sample(namespace, "notices")]
    _seed_weights(model, rows)
    targets = [{"id": row.sample_id, "source_text": row.text,
        "canonical_ir": {"rules": [{"modality": "O", "actor": "agency",
            "action": "submit", "object": row.modal_ir.formulas[0].predicate.arguments[-1],
            "conditions": [], "exceptions": [], "temporal": []}]}} for row in rows]
    training = joint._rows(model, rows, targets)
    tuning_samples = []
    for row in rows:
        text = row.text.replace("shall", "must")
        identifier = "tuning-" + row.sample_id
        tuning_samples.append(replace(row, sample_id=identifier, text=text, normalized_text=text,
            modal_ir=replace(row.modal_ir, document_id=identifier, normalized_text=text)))
    tuning_targets = [{**target, "id": row.sample_id, "source_text": row.text}
                      for target, row in zip(targets, tuning_samples)]
    tuning = joint._rows(model, tuning_samples, tuning_targets)
    before = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        checkpoint = learning.build_checkpoint(joint._core_binding(model), training, tuning,
            hidden_size=16, token_embedding_dim=8, projection_width=4, seed=1729)
        checkpoint = learning.train(checkpoint, training, tuning, epochs=1,
                                    max_seconds=15)["checkpoint"]
        yield namespace, model.state.to_dict(), checkpoint, rows
    finally:
        torch.set_num_threads(before)


def _owner(checkpointed):
    lineage, state, checkpoint, _ = checkpointed
    model = lineage.Autoencoder(state=lineage.TrainingState.from_dict(copy.deepcopy(state)),
                               compute_device="cpu")
    model.attach_formula_checkpoint(checkpoint)
    return model


def test_fast_rows_preserve_complete_original_joint_result(checkpointed):
    model = _owner(checkpointed)
    expected = joint.infer(model, checkpointed[3])
    assert fast.infer(model, checkpointed[3]) == expected


def _assert_float32_parity(actual, expected):
    """Keep semantic results exact while allowing float32 GEMM rounding."""
    assert type(actual) is type(expected)
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            _assert_float32_parity(actual[key], expected[key])
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected)
        for value, reference in zip(actual, expected):
            _assert_float32_parity(value, reference)
    elif isinstance(expected, float):
        assert math.isfinite(actual) and math.isfinite(expected)
        assert actual == pytest.approx(expected, rel=1e-6, abs=1e-6)
    else:
        assert actual == expected


def test_session_batches_with_matching_results_and_no_owner_decoder_swap(checkpointed):
    model = _owner(checkpointed)
    decoder = model._joint_formula_decoder
    binding = joint._core_binding(model)
    expected = joint.infer(model, checkpointed[3])
    session = fast.JointInferenceSession(model)
    exposed = session.binding
    exposed["core_sha256"] = "0" * 64
    assert session.binding == binding
    observed = session.infer(checkpointed[3])
    metadata = observed.pop("inference_implementation")
    assert metadata["joint_projection"]["checkpoint_conversion_performed"] is False
    assert metadata["formula_decoder"]["checkpoint_conversion_performed"] is False
    _assert_float32_parity(observed, expected)
    assert model._joint_formula_decoder is decoder
    assert joint._core_binding(model) == binding


def _versioned_runtime(checkpointed, **options):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import open_runtime
    namespace, state, checkpoint, _ = checkpointed
    return open_runtime("legal_ir", namespace.__name__.rsplit(".", 1)[-1],
                        state=namespace.TrainingState.from_dict(copy.deepcopy(state)),
                        formula_checkpoint=checkpoint, compute_device="cpu", **options)


def test_versioned_runtime_optimizes_by_default_and_reuses_session(checkpointed):
    runtime = _versioned_runtime(checkpointed)
    rows = checkpointed[3]
    owner = runtime.model._joint_formula_decoder
    expected = joint.infer(runtime.model, rows)
    report = runtime.infer(rows)
    session = runtime._inference_session
    assert isinstance(session, fast.JointInferenceSession)
    assert report.pop("inference_implementation")["view_candidates"]["scope"] == "one_inference_request"
    _assert_float32_parity(report, expected)
    decoded = runtime.decode_formal_logic(rows)
    decoded.pop("inference_implementation")
    _assert_float32_parity(decoded, expected)
    assert runtime._inference_session is session
    assert runtime.model._joint_formula_decoder is owner


def test_versioned_runtime_opt_out_preserves_original_inference(checkpointed, monkeypatch):
    runtime = _versioned_runtime(checkpointed, optimized=False)
    def unexpected(*args, **options):
        raise AssertionError("opt-out must use original decoder")
    monkeypatch.setattr(fast, "JointInferenceSession", unexpected)
    expected = joint.infer(runtime.model, checkpointed[3])
    assert runtime.infer(checkpointed[3]) == expected
    assert runtime.decode_formal_logic(checkpointed[3], mode="learned_latent") == expected
    assert runtime._inference_session is None


@pytest.mark.parametrize("changed", ["sidecar", "owner_parameters", "core"])
def test_default_versioned_runtime_rejects_mutation_after_warming(checkpointed, changed):
    runtime = _versioned_runtime(checkpointed)
    runtime.infer(checkpointed[3])
    if changed == "sidecar":
        runtime.model._joint_formula_checkpoint["model_state"]["projection_up.bias"][0] += .25
    elif changed == "owner_parameters":
        next(runtime.model._joint_formula_decoder.model.parameters()).data.add_(.25)
    else:
        runtime.model.state.family_embedding_weights["deontic"][0] += .25
    with pytest.raises(ValueError, match="changed|differ"):
        runtime.infer(checkpointed[3])


def test_default_versioned_runtime_rebuilds_session_after_explicit_reattachment(checkpointed):
    runtime = _versioned_runtime(checkpointed)
    before = runtime.infer(checkpointed[3])
    session = runtime._inference_session
    runtime.model.attach_formula_checkpoint(checkpointed[2])
    assert runtime.infer(checkpointed[3]) == before
    assert runtime._inference_session is not session


def test_default_versioned_runtime_observes_replaced_model_even_with_same_decoder(checkpointed):
    runtime = _versioned_runtime(checkpointed)
    runtime.infer(checkpointed[3])
    decoder = runtime.model._joint_formula_decoder
    runtime.model = _owner(checkpointed)
    runtime.model._joint_formula_decoder = decoder
    runtime.model._legal_ir_view_target_cache["teacher"] = {"unexpected": True}
    with pytest.raises(ValueError, match="cached teacher"):
        runtime.infer(checkpointed[3])
    assert runtime._inference_session._model is runtime.model


def test_versioned_training_discards_session_even_when_training_fails(checkpointed, monkeypatch):
    runtime = _versioned_runtime(checkpointed)
    runtime.infer(checkpointed[3])
    def fail(*args, **options):
        raise ValueError("fixture training failure")
    monkeypatch.setattr(runtime.model, "train_generalizable_projection", fail)
    with pytest.raises(ValueError, match="fixture training failure"):
        runtime.train(checkpointed[3])
    assert runtime._inference_session is None
    assert runtime._inference_decoder is None


@pytest.mark.parametrize("optimized", [None, 1, "yes"])
def test_versioned_runtime_rejects_nonboolean_optimization_before_model_loading(optimized):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import open_runtime
    with pytest.raises(ValueError, match="optimized must be a boolean"):
        open_runtime("legal_ir", "current_v2", checkpoint="/unused", optimized=optimized)


@pytest.mark.parametrize("changed", ("core", "configuration", "sidecar", "owner_parameters",
                                      "private_parameters", "joint_source", "fast_source", "guard_source"))
def test_session_rejects_mutated_owner_private_decoder_and_sources(checkpointed, monkeypatch, changed):
    model = _owner(checkpointed)
    session = fast.JointInferenceSession(model)
    if changed == "core":
        model.state.family_embedding_weights["deontic"][0] += 0.25
    elif changed == "configuration":
        model.initial_embedding_scale += 0.25
    elif changed == "sidecar":
        model._joint_formula_checkpoint["model_state"]["projection_up.bias"][0] += 0.25
    elif changed.endswith("parameters"):
        decoder = model._joint_formula_decoder if changed == "owner_parameters" else session._decoder
        next(decoder.model.parameters()).data.add_(0.25)
    else:
        original = Path.read_bytes
        target = Path(importlib.import_module(PREFIX + ".checkpoint_content_guard").__file__
                      if changed == "guard_source" else
                      joint.__file__ if changed == "joint_source" else fast.__file__)
        def drift(path):
            data = original(path)
            return data + b"\n# source drift\n" if path == target else data
        monkeypatch.setattr(Path, "read_bytes", drift)
    with pytest.raises(ValueError, match="changed|differ|mutated|another core"):
        session.infer(checkpointed[3])


def test_session_detects_core_mutation_during_work(checkpointed, monkeypatch):
    model = _owner(checkpointed)
    session = fast.JointInferenceSession(model)
    method = "infer_with_projection" if hasattr(session._decoder, "infer_with_projection") else "infer"
    original = getattr(session._decoder, method)
    def mutate(rows):
        result = original(rows)
        model.initial_embedding_scale += 0.25
        return result
    monkeypatch.setattr(session._decoder, method, mutate)
    with pytest.raises(ValueError, match="core changed during formula inference"):
        session.infer(checkpointed[3])


def test_session_retains_cached_profile_after_dictionary_reordering_and_caller_edits(checkpointed):
    model = _owner(checkpointed)
    session = fast.JointInferenceSession(model)
    expected = joint.describe(model)
    sidecar = model._joint_formula_checkpoint
    model._joint_formula_checkpoint = dict(reversed(list(sidecar.items())))
    report = session.infer(checkpointed[3])
    assert report["joint_profile"] == expected
    report["joint_profile"]["trained_components"].append("caller-edit")
    assert session.infer(checkpointed[3])["joint_profile"] == expected


def test_session_rebuilds_candidates_and_sample_observations_for_each_request(checkpointed, monkeypatch):
    model = _owner(checkpointed)
    session = fast.JointInferenceSession(model)
    builds = 0
    original = fast._view_family_candidates
    def candidates(worker):
        nonlocal builds
        if worker._legal_ir_view_family_candidates_cache is None:
            builds += 1
        return original(worker)
    monkeypatch.setattr(fast, "_view_family_candidates", candidates)
    first = session.infer(checkpointed[3])
    assert builds == 1
    assert first["inference_implementation"]["view_candidates"] == {
        "scope": "one_inference_request", "retained_after_request": 0}
    rows = copy.deepcopy(checkpointed[3])
    rows[0].embedding_vector[0] += 0.25
    expected = joint.infer(model, rows)
    actual = session.infer(rows)
    assert builds == 2
    actual.pop("inference_implementation")
    _assert_float32_parity(actual, expected)
    assert model._sample_feature_cache == {}
    assert not hasattr(session, "_view_candidates")
    model.state.legal_ir_view_embedding_weights["new.view"] = [0.1] * model.DIMENSION
    with pytest.raises(ValueError, match="core changed"):
        session.infer(rows)
    assert builds == 2


def test_session_rebuilds_candidates_after_failed_inference(checkpointed, monkeypatch):
    model = _owner(checkpointed)
    session = fast.JointInferenceSession(model)
    builds = 0
    candidates_for = fast._view_family_candidates
    def candidates(worker):
        nonlocal builds
        if worker._legal_ir_view_family_candidates_cache is None:
            builds += 1
        return candidates_for(worker)
    monkeypatch.setattr(fast, "_view_family_candidates", candidates)
    original = session._decoder.infer_with_projection
    def fail(rows):
        raise RuntimeError("request failed")
    monkeypatch.setattr(session._decoder, "infer_with_projection", fail)
    with pytest.raises(RuntimeError, match="request failed"):
        session.infer(checkpointed[3])
    assert builds == 1
    monkeypatch.setattr(session._decoder, "infer_with_projection", original)
    session.infer(checkpointed[3])
    assert builds == 2
    assert model._sample_feature_cache == {}
    assert not hasattr(session, "_view_candidates")


def test_session_first_request_without_candidates_does_not_affect_later_lookup(checkpointed, monkeypatch):
    model = _owner(checkpointed)
    session = fast.JointInferenceSession(model)
    original_project = fast._project_sample
    # Exercise a valid extraction path that never asks for view candidates.
    def no_candidate_lookup(worker, row, **options):
        return joint.raw_projection(model, row)
    monkeypatch.setattr(fast, "_project_sample", no_candidate_lookup)
    session.infer(checkpointed[3])
    monkeypatch.setattr(fast, "_project_sample", original_project)
    builds = 0
    candidates_for = fast._view_family_candidates
    def candidates(worker):
        nonlocal builds
        if worker._legal_ir_view_family_candidates_cache is None:
            builds += 1
        return candidates_for(worker)
    monkeypatch.setattr(fast, "_view_family_candidates", candidates)
    second = session.infer(checkpointed[3])
    third = session.infer(checkpointed[3])
    assert builds == 2
    second.pop("inference_implementation")
    third.pop("inference_implementation")
    assert second == third


def test_session_recomputes_candidate_order_after_base_dictionary_reordering(checkpointed, monkeypatch):
    model = _owner(checkpointed)
    session = fast.JointInferenceSession(model)
    observed = []
    original = fast._view_family_candidates
    def candidates(worker):
        uncomputed = worker._legal_ir_view_family_candidates_cache is None
        result = original(worker)
        if uncomputed:
            observed.append(result)
        return result
    monkeypatch.setattr(fast, "_view_family_candidates", candidates)
    first = session.infer(checkpointed[3])
    assert len(observed) == 1
    binding = joint._core_binding(model)
    revision = model.state.state_revision
    primary = model.state.legal_ir_view_embedding_weights
    key = next(iter(primary))
    vector = dict.pop(primary, key)
    dict.__setitem__(primary, key, vector)
    assert model.state.state_revision == revision
    assert joint._core_binding(model) == binding
    actual = session.infer(checkpointed[3])
    assert len(observed) == 2
    assert observed[1] != observed[0]
    expected = fast.infer(model, checkpointed[3], session._decoder)
    assert observed[2] == observed[1]
    actual.pop("inference_implementation")
    expected.pop("inference_implementation")
    assert actual == expected
    assert first["joint_profile"] == actual["joint_profile"]


def test_session_recomputes_derived_string_key_aliases_with_unchanged_binding(checkpointed, monkeypatch):
    class KeyAlias(str):
        def __str__(self):
            return "new.view"
    model = _owner(checkpointed)
    model.state.feature_legal_ir_view_logits["alias-row"] = {"deontic.ir": 0.5}
    checkpoint = copy.deepcopy(model._joint_formula_checkpoint)
    checkpoint["binding"] = joint._core_binding(model)
    model.attach_formula_checkpoint(checkpoint)
    session = fast.JointInferenceSession(model)
    observed = []
    original = fast._view_family_candidates
    def candidates(worker):
        uncomputed = worker._legal_ir_view_family_candidates_cache is None
        result = original(worker)
        if uncomputed:
            observed.append(result)
        return result
    monkeypatch.setattr(fast, "_view_family_candidates", candidates)
    session.infer(checkpointed[3])
    assert len(observed) == 1
    assert "new.view" not in observed[0]
    binding = joint._core_binding(model)
    revision = model.state.state_revision
    row = model.state.feature_legal_ir_view_logits["alias-row"]
    value = dict.pop(row, "deontic.ir")
    dict.__setitem__(row, KeyAlias("deontic.ir"), value)
    assert model.state.state_revision == revision
    assert joint._core_binding(model) == binding
    actual = session.infer(checkpointed[3])
    assert len(observed) == 2
    assert "new.view" in observed[1]
    expected = fast.infer(model, checkpointed[3], session._decoder)
    assert observed[2] == observed[1]
    actual.pop("inference_implementation")
    expected.pop("inference_implementation")
    assert actual == expected


@pytest.mark.parametrize("changed", ("sidecar", "owner_parameters"))
def test_session_rechecks_owned_sidecar_and_decoder_after_work(checkpointed, monkeypatch, changed):
    model = _owner(checkpointed)
    session = fast.JointInferenceSession(model)
    original = session._decoder.infer_with_projection
    def mutate(rows):
        result = original(rows)
        if changed == "sidecar":
            model._joint_formula_checkpoint["model_state"]["projection_up.bias"][0] += 0.25
        else:
            next(model._joint_formula_decoder.model.parameters()).data.add_(0.25)
        return result
    monkeypatch.setattr(session._decoder, "infer_with_projection", mutate)
    with pytest.raises(ValueError, match="changed|differ|mutated"):
        session.infer(checkpointed[3])


def test_session_keeps_source_identity_and_teacher_cache_boundaries(checkpointed):
    model = _owner(checkpointed)
    session = fast.JointInferenceSession(model)
    row = checkpointed[3][0]
    with pytest.raises(ValueError, match="exact sample identity and normalized source"):
        session.infer([replace(row, text=row.text + " Changed source.")])
    model._legal_ir_view_target_cache[row.sample_id] = {"teacher": 1.0}
    with pytest.raises(ValueError, match="teacher bridge targets"):
        session.infer([row])
    assert model._legal_ir_view_target_cache == {row.sample_id: {"teacher": 1.0}}
