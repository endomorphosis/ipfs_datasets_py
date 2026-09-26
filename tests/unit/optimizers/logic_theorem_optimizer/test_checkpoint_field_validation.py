"""Closed legacy field validation without materializing native weight graphs.

These are synthetic state and file fixtures. Constructor sentinels stop before
model construction, sample parsing, evaluation or training.
"""
from __future__ import annotations

from functools import wraps
import hashlib
import json
from pathlib import Path
import struct

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_sparse_checkpoint as sparse
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import (
    MappedFeatureEmbeddingWeights, build_feature_embedding_weights_ipc,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_worker import _job
from tests.unit.optimizers.logic_theorem_optimizer.test_modal_autoencoder_checkpoint_baseline import fixture
from tests.unit.optimizers.logic_theorem_optimizer.test_modal_autoencoder_sparse_checkpoint import Store, _state


# Frozen public legacy envelope, independent of the candidate field constant.
EXPECTED_FIELDS = frozenset("""
schema_version proof_auxiliary_head_schema_version architecture_version
decoded_embeddings family_logits compiler_quality_embedding_weights
compiler_quality_family_logits logic_signature_embedding_weights
logic_signature_family_logits logic_signature_legal_ir_view_logits
round_trip_signal_embedding_weights round_trip_signal_family_logits
round_trip_signal_legal_ir_view_logits decompiler_plan_embedding_weights
decompiler_plan_family_logits decompiler_plan_legal_ir_view_logits
predicate_argument_embedding_weights predicate_argument_family_logits
predicate_argument_legal_ir_view_logits feature_embedding_weights
family_embedding_weights family_semantic_slot_embedding_weights
family_semantic_slot_legal_ir_view_embedding_weights family_legal_ir_view_embedding_weights
semantic_slot_embedding_weights feature_family_logits semantic_slot_family_logits
legal_ir_view_logits legal_ir_view_embedding_weights legal_ir_view_family_logits
feature_legal_ir_view_logits family_semantic_slot_legal_ir_view_logits
semantic_slot_legal_ir_view_embedding_weights semantic_slot_legal_ir_view_family_logits
semantic_slot_legal_ir_view_logits proof_auxiliary_head_logits
proof_feedback_version_fingerprint applied_proof_feedback_ids
applied_leanstral_guidance_ids applied_todo_ids
""".split())


def _forbid_materialization(*args, **kwargs):
    raise AssertionError("field validation materialized the native state")


def _legacy_bytes(data):
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _worker_spec(tmp_path, data, *, mapped):
    payload = _job(tmp_path)
    checkpoint = Path(payload["base_checkpoint"]["path"])
    raw = _legacy_bytes(data)
    checkpoint.write_bytes(raw)
    payload["base_checkpoint"] = {"path": str(checkpoint),
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    if mapped:
        path = tmp_path / "features.arrow"
        # Match the exact parsed source order, including keys appended after
        # to_dict returned but sorted by canonical JSON serialization.
        ref = build_feature_embedding_weights_ipc(json.loads(raw)["feature_embedding_weights"], path,
            base_checkpoint_sha256=payload["base_checkpoint"]["sha256"])
        payload["arrow_feature_weights_artifact"] = {
            "path": str(path), "sha256": ref["sha256"], "bytes": ref["size_bytes"]}
    return worker.TrainingJobSpec.from_dict(payload), raw


@pytest.mark.parametrize("architecture", sorted(modal.MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS))
@pytest.mark.parametrize("kind", ["empty", "populated", "proof-hidden"])
def test_serialized_field_contract_is_exact_for_every_native_legacy_architecture(architecture, kind):
    state = modal.ModalAutoencoderTrainingState() if kind == "empty" else fixture()
    state.architecture_version = architecture
    if kind == "proof-hidden":
        state.proof_feedback_version_fingerprint = ""
        assert state.proof_auxiliary_head_logits
    data = state.to_dict()
    assert type(modal.MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS) is frozenset
    assert len(EXPECTED_FIELDS) == 40
    assert modal.MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS == EXPECTED_FIELDS == frozenset(data)
    assert len(modal.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS) == 38
    reloaded = modal.ModalAutoencoderTrainingState.from_dict(data)
    assert frozenset(reloaded.to_dict()) == EXPECTED_FIELDS
    # The preexisting loader upgrades compatible architectures and converts
    # numeric leaves to floats; validating keys must retain both behaviors.
    assert reloaded.architecture_version == modal.MODAL_AUTOENCODER_ARCHITECTURE_VERSION
    assert reloaded.state_revision == 0
    assert reloaded.to_dict() == {**data, "architecture_version": modal.MODAL_AUTOENCODER_ARCHITECTURE_VERSION}
    assert modal.ModalAutoencoderTrainingState.from_dict(reloaded.to_dict()).to_json() == reloaded.to_json()
    if kind == "proof-hidden":
        assert data["proof_auxiliary_head_logits"] == {}


@pytest.mark.parametrize("omitted", [(), ("schema_version",), ("architecture_version",),
    ("proof_auxiliary_head_schema_version",), ("schema_version", "architecture_version", "proof_auxiliary_head_schema_version")])
def test_omitted_legacy_schema_fields_keep_original_loader_defaults(tmp_path, omitted):
    data = fixture().to_dict()
    for name in omitted:
        data.pop(name)
    expected = modal.ModalAutoencoderTrainingState.from_dict(data)
    store = Store(tmp_path)
    ref = store.put(_legacy_bytes(data))
    resolved = store.load(ref)
    inventory = store.inventory(ref)
    assert frozenset(expected.to_dict()) == EXPECTED_FIELDS
    assert resolved.state.to_json() == expected.to_json()
    assert resolved.state.state_identity_record() == expected.state_identity_record()
    assert resolved.state.state_revision == resolved.replayed_revision == 0
    assert resolved.materialized_checkpoint == inventory.declared_materialized_checkpoint == ref
    assert inventory.weights_constructed is inventory.semantic_replay_verified is False


@pytest.mark.parametrize("unknown", ["feature_embedding_weight", "tensor_payload", "revision"])
@pytest.mark.parametrize("method", ["load", "inventory"])
def test_sparse_full_and_inventory_still_reject_unknown_top_level_fields(tmp_path, monkeypatch, unknown, method):
    data = fixture().to_dict()
    data[unknown] = {"looks": "otherwise valid"}
    store = Store(tmp_path)
    ref = store.put(_legacy_bytes(data))
    monkeypatch.setattr(modal.ModalAutoencoderTrainingState, "to_dict", _forbid_materialization)
    with pytest.raises(sparse.SparseCheckpointError, match="unknown fields"):
        getattr(store, method)(ref)


@pytest.mark.parametrize("mapped", [False, True])
def test_worker_unknown_field_rejected_before_constructor_and_output(tmp_path, monkeypatch, mapped):
    data = fixture().to_dict()
    data["feature_embedding_weight"] = {"extra": [0.125]}
    spec, original = _worker_spec(tmp_path, data, mapped=mapped)
    monkeypatch.setattr(modal.ModalAutoencoderTrainingState, "to_dict", _forbid_materialization)
    monkeypatch.setattr(modal.AdaptiveModalAutoencoder, "__init__",
                        lambda *args, **kwargs: pytest.fail("constructed model for unknown field"))
    with pytest.raises(worker.TrainingJobValidationError, match="unsupported checkpoint fields.*feature_embedding_weight"):
        worker.execute_training_job(spec, trainer=lambda *args, **kwargs: pytest.fail("trained"))
    assert not Path(spec.output_directory).exists()
    assert Path(spec.base_checkpoint.path).read_bytes() == original


MALFORMED_NESTED = [
    ("family_logits", {"row": {"deontic": []}}),
    ("decoded_embeddings", {"row": False}),
    ("semantic_slot_family_logits", {"slot": {"deontic": "not-a-number"}}),
]


@pytest.mark.parametrize("field,value", MALFORMED_NESTED)
def test_sparse_resolver_keeps_nested_numeric_validation_after_key_check_optimization(tmp_path, monkeypatch, field, value):
    data = fixture().to_dict()
    data[field] = value
    store = Store(tmp_path)
    ref = store.put(_legacy_bytes(data))
    monkeypatch.setattr(modal.ModalAutoencoderTrainingState, "to_dict", _forbid_materialization)
    with pytest.raises(sparse.SparseCheckpointError, match="invalid full legacy checkpoint"):
        store.load(ref)
    # Inventory remains framing-only, never a substitute for semantic loading.
    assert store.inventory(ref).semantic_replay_verified is False


@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize("field,value", MALFORMED_NESTED)
def test_worker_keeps_nested_numeric_errors_before_model_for_full_and_mapped_inputs(tmp_path, monkeypatch, mapped, field, value):
    data = fixture().to_dict()
    data[field] = value
    spec, original = _worker_spec(tmp_path, data, mapped=mapped)
    monkeypatch.setattr(modal.ModalAutoencoderTrainingState, "to_dict", _forbid_materialization)
    monkeypatch.setattr(modal.AdaptiveModalAutoencoder, "__init__",
                        lambda *args, **kwargs: pytest.fail("constructed model for malformed component"))
    with pytest.raises((ValueError, TypeError)):
        worker.execute_training_job(spec, trainer=lambda *args, **kwargs: pytest.fail("trained"))
    assert not Path(spec.output_directory).exists()
    assert Path(spec.base_checkpoint.path).read_bytes() == original


@pytest.mark.parametrize("consumer", ["worker", "sparse"])
def test_malformed_known_component_still_fails_before_unknown_field_check(tmp_path, monkeypatch, consumer):
    data = fixture().to_dict()
    data["family_logits"] = {"row": {"deontic": "fixture-not-a-number"}}
    data["also_unknown"] = {}
    if consumer == "worker":
        spec, _ = _worker_spec(tmp_path, data, mapped=False)
    else:
        store = Store(tmp_path)
        ref = store.put(_legacy_bytes(data))
    monkeypatch.setattr(modal.ModalAutoencoderTrainingState, "to_dict", _forbid_materialization)
    if consumer == "worker":
        monkeypatch.setattr(modal.AdaptiveModalAutoencoder, "__init__",
                            lambda *args, **kwargs: pytest.fail("constructed malformed model"))
        with pytest.raises(ValueError, match="fixture-not-a-number") as error:
            worker.execute_training_job(spec, trainer=lambda *args, **kwargs: pytest.fail("trained"))
        assert "unsupported checkpoint fields" not in str(error.value)
        assert not Path(spec.output_directory).exists()
    else:
        with pytest.raises(sparse.SparseCheckpointError, match="invalid full legacy checkpoint") as error:
            store.load(ref)
        assert isinstance(error.value.__cause__, ValueError)
        assert "fixture-not-a-number" in str(error.value.__cause__)


def test_sparse_full_resolution_does_not_call_to_dict_to_validate_fields(tmp_path, monkeypatch):
    data = fixture().to_dict()
    data["feature_embedding_weights"]["signed-zero"] = [-0.0, 0.0, 0.125]
    expected = modal.ModalAutoencoderTrainingState.from_dict(data)
    expected_json = expected.to_json()
    expected_identity = expected.state_identity_record()
    store = Store(tmp_path)
    ref = store.put(_legacy_bytes(data))
    with monkeypatch.context() as patch:
        patch.setattr(modal.ModalAutoencoderTrainingState, "to_dict", _forbid_materialization)
        resolved = store.load(ref)
        inventory = store.inventory(ref)
    assert resolved.state.to_json() == expected_json
    assert resolved.state.state_identity_record() == expected_identity
    assert resolved.state.state_revision == resolved.replayed_revision == 0
    assert resolved.materialized_checkpoint == inventory.declared_materialized_checkpoint == ref
    assert store.paths[ref["sha256"]].read_bytes() == _legacy_bytes(data)
    assert struct.pack("<ddd", *resolved.state.feature_embedding_weights["signed-zero"]) == struct.pack("<ddd", -0.0, 0.0, 0.125)


@pytest.mark.parametrize("mapped", [False, True])
def test_worker_reaches_constructor_without_materializing_full_or_mapped_state(tmp_path, monkeypatch, mapped):
    data = fixture().to_dict()
    data["feature_embedding_weights"]["signed-zero"] = [-0.0, 0.0, 0.125]
    expected = modal.ModalAutoencoderTrainingState.from_dict(data)
    expected_identity = expected.state_identity_record().to_dict()
    spec, original = _worker_spec(tmp_path, data, mapped=mapped)
    seen = []

    class ConstructorReached(Exception):
        pass

    @wraps(modal.AdaptiveModalAutoencoder.__init__)
    def constructor(self, *, state, **kwargs):
        assert state.state_identity_record().to_dict() == expected_identity
        assert state.state_revision == 0
        weights = state.feature_embedding_weights
        assert (type(weights) is MappedFeatureEmbeddingWeights) is mapped
        assert struct.pack("<ddd", *weights["signed-zero"]) == struct.pack("<ddd", -0.0, 0.0, 0.125)
        if mapped:
            assert weights.statistics["overlay_rows"] == 0
        seen.append(state)
        raise ConstructorReached

    monkeypatch.setattr(modal.ModalAutoencoderTrainingState, "to_dict", _forbid_materialization)
    monkeypatch.setattr(modal.AdaptiveModalAutoencoder, "__init__", constructor)
    with pytest.raises(ConstructorReached):
        worker.execute_training_job(spec, trainer=lambda *args, **kwargs: pytest.fail("trained"))
    assert len(seen) == 1
    assert not Path(spec.output_directory).exists()
    assert Path(spec.base_checkpoint.path).read_bytes() == original
    if mapped:
        with pytest.raises((RuntimeError, ValueError)):
            seen[0].feature_embedding_weights["signed-zero"]


@pytest.mark.parametrize("reset_revision", [False, True])
def test_sparse_chain_semantic_reload_and_revision_boundaries_remain_intact(tmp_path, reset_revision):
    store = Store(tmp_path)
    state = _state()
    base = store.put(_legacy_bytes(state.to_dict()))
    first, first_state, _ = store.job(base, state, changes=(2.0, 3.0))
    terminal, terminal_state, _ = store.job(first, first_state, version="second-job", changes=(4.0,))
    result = store.load(terminal, reset_revision=reset_revision)
    assert result.state.to_json() == terminal_state.to_json()
    assert result.state.state_identity() == terminal_state.state_identity()
    assert result.state.state_revision == (0 if reset_revision else 1)
    assert result.replayed_revision == 1
    assert result.depth == 2
    assert result.materialized_checkpoint == sparse.checkpoint_identity(terminal_state)
    assert result.anchor_checkpoint == base
