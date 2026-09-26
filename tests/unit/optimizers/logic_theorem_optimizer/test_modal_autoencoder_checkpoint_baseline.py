"""Exact persisted-baseline parity against frozen pre-change serializer bodies.

These synthetic native-state fixtures execute no training or bridge generation.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
import gc
import hashlib
import json
import weakref

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState, MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS,
    MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS,
)

# Exact serialize_checkpoint/serialize_delta bodies from pre-edit source
# 054f48d51309d6489c237bb18604ae9a6490c1597d00117dc5439cfd744bbba5.
# Kept here rather than depending on a workspace audit artifact.
_REFERENCE_SOURCE = '\ndef serialize_checkpoint(\n    state: Any,\n    *,\n    float_precision: str = "float64",\n    metric_lineage: Any = None,\n    metadata: Optional[Mapping[str, Any]] = None,\n    revision: Optional[int] = None,\n) -> bytes:\n    """Serialize a full state into the safe compact binary format."""\n\n    source_data = _state_data(state)\n    _source_digest, source_revision, _source_lineage, _source_components, _source_schema = (\n        _identity_record(state, metric_lineage)\n    )\n    effective_revision = source_revision if revision is None else int(revision)\n    data = _quantized_copy(source_data, float_precision)\n    persisted_state = _state_from_data(data)\n    _restore_revision(persisted_state, effective_revision)\n    digest, _persisted_revision, lineage_digest, component_digests, state_schema = _identity_record(\n        persisted_state, metric_lineage\n    )\n    payload, tables = _encode_state_payload(\n        data,\n        precision=float_precision,\n        component_digests=component_digests,\n    )\n    payload_checksum = _sha256(payload)\n    checkpoint_id = (\n        "lir-mae-checkpoint-"\n        + canonical_digest(\n            {\n                "metric_lineage_digest": lineage_digest,\n                "payload_checksum": payload_checksum,\n                "revision": effective_revision,\n                "state_digest": digest,\n                "state_schema_version": state_schema,\n            }\n        )[:32]\n    )\n    manifest = CheckpointManifest(\n        schema_version=MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION,\n        kind="full",\n        state_schema_version=state_schema,\n        state_digest=digest,\n        revision=effective_revision,\n        metric_lineage_digest=lineage_digest,\n        metric_lineage=_canonical_copy(metric_lineage),\n        float_precision=float_precision,\n        payload_checksum=payload_checksum,\n        checkpoint_id=checkpoint_id,\n        table_count=len(tables),\n        numeric_value_count=sum(int(table["value_count"]) for table in tables),\n        metadata=_canonical_copy(metadata or {}),\n    )\n    return _container_bytes(CHECKPOINT_MAGIC, manifest.to_dict(), payload)\n\n\ndef serialize_delta(\n    base_state: Any,\n    state: Any,\n    *,\n    float_precision: str = "float64",\n    metric_lineage: Any = None,\n    metadata: Optional[Mapping[str, Any]] = None,\n    base_revision: Optional[int] = None,\n    revision: Optional[int] = None,\n) -> bytes:\n    """Serialize whole replacements for only the components that changed."""\n\n    (\n        _source_base_digest,\n        source_base_revision,\n        _source_base_lineage,\n        _source_base_components,\n        _source_base_schema,\n    ) = _identity_record(base_state, metric_lineage)\n    _source_digest, source_revision, _source_lineage, _source_components, _source_schema = (\n        _identity_record(state, metric_lineage)\n    )\n    base_data = _quantized_copy(_state_data(base_state), float_precision)\n    data = _quantized_copy(_state_data(state), float_precision)\n    persisted_base = _state_from_data(base_data)\n    persisted_state = _state_from_data(data)\n    effective_base_revision = source_base_revision if base_revision is None else int(base_revision)\n    effective_revision = source_revision if revision is None else int(revision)\n    _restore_revision(persisted_base, effective_base_revision)\n    _restore_revision(persisted_state, effective_revision)\n    base_digest, _base_revision, base_lineage, base_components, base_schema = _identity_record(\n        persisted_base, metric_lineage\n    )\n    digest, _revision, lineage_digest, components, state_schema = _identity_record(\n        persisted_state, metric_lineage\n    )\n    if state_schema != base_schema or lineage_digest != base_lineage:\n        raise CheckpointLineageError("delta endpoints have different schema or metric lineage")\n    if effective_revision < effective_base_revision:\n        raise CheckpointLineageError("delta revision precedes its base revision")\n    changed = tuple(\n        sorted(\n            name\n            for name in set(base_components) | set(components)\n            if base_components.get(name) != components.get(name)\n        )\n    )\n    if effective_revision == effective_base_revision and changed:\n        raise CheckpointLineageError("changed delta must advance the state revision")\n    missing = [name for name in changed if name not in data]\n    if missing:\n        raise CheckpointLineageError(f"delta deletes unsupported state components: {missing}")\n    payload, tables = _encode_state_payload(\n        data,\n        precision=float_precision,\n        component_digests=components,\n        include_components=changed,\n    )\n    payload_checksum = _sha256(payload)\n    delta_id = (\n        "lir-mae-delta-"\n        + canonical_digest(\n            {\n                "base_revision": effective_base_revision,\n                "base_state_digest": base_digest,\n                "payload_checksum": payload_checksum,\n                "revision": effective_revision,\n                "state_digest": digest,\n            }\n        )[:32]\n    )\n    manifest = CheckpointManifest(\n        schema_version=MODAL_AUTOENCODER_DELTA_SCHEMA_VERSION,\n        kind="delta",\n        state_schema_version=state_schema,\n        state_digest=digest,\n        revision=effective_revision,\n        metric_lineage_digest=lineage_digest,\n        metric_lineage=_canonical_copy(metric_lineage),\n        float_precision=float_precision,\n        payload_checksum=payload_checksum,\n        checkpoint_id=delta_id,\n        base_state_digest=base_digest,\n        base_revision=effective_base_revision,\n        changed_components=changed,\n        table_count=len(tables),\n        numeric_value_count=sum(int(table["value_count"]) for table in tables),\n        metadata=_canonical_copy(metadata or {}),\n    )\n    return _container_bytes(DELTA_MAGIC, manifest.to_dict(), payload)\n\n'


def reference_functions():
    namespace = vars(codec).copy()
    exec(compile(_REFERENCE_SOURCE, "<frozen-pre-baseline-serializers>", "exec"), namespace)
    return namespace["serialize_checkpoint"], namespace["serialize_delta"]


def fixture():
    state = ModalAutoencoderTrainingState()
    for name in MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS:
        current = getattr(state, name)
        if isinstance(current, dict):
            if name == "proof_auxiliary_head_logits":
                value = {"obligation_family": {"__global__": {"mandatory": -0.0, "permissive": 0.123456789012345}}}
            elif name == "legal_ir_view_logits":
                value = {"deontic": -0.0, "flogic": 1}
            elif "embedding" in name:
                value = {"z": [-0.0, 1, 1.0 / 3.0], "a": [0.2, -0.4, 1.25]}
            else:
                value = {"z": {"deontic": -0.0, "flogic": 1}, "a": {"deontic": 0.5}}
            setattr(state, name, value)
        elif isinstance(current, list):
            setattr(state, name, ["z", "a", "z"])
    state.proof_feedback_version_fingerprint = "fixture-proof-v1"
    return state


def copied(state):
    value = state.copy()
    value._state_identity_tracker.restore_revision(state.state_revision)
    return value


def mutate(state, name):
    value = getattr(state, name)
    if isinstance(value, dict):
        if name == "proof_auxiliary_head_logits":
            value["obligation_family"]["__global__"]["mandatory"] = 0.375
        elif name == "legal_ir_view_logits":
            value["deontic"] = 0.375
        elif "embedding" in name:
            del value["a"]
            value["new"] = [0.5, -0.0]
        else:
            del value["a"]
            value["z"]["deontic"] = 0.375
    elif isinstance(value, list):
        value[:] = ["later", "z", "later"]
    elif name == "proof_feedback_version_fingerprint":
        setattr(state, name, "")
    elif name == "architecture_version":
        alternatives = sorted(set(MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS) - {value})
        assert alternatives
        setattr(state, name, alternatives[0])
    else:
        raise AssertionError(name)


@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("lineage", [None, {"schema": "fixture-v1", "threshold": -0.0, "flags": [True, 1, 1.0]}])
def test_full_snapshot_and_startup_token_match_frozen_legacy(precision, lineage):
    old_full, _ = reference_functions()
    state = fixture()
    options = {"float_precision": precision, "metric_lineage": lineage, "metadata": {"cycle": 2, "fixture": True}, "revision": state.state_revision + 7}
    expected = old_full(state, **options)
    result = codec.serialize_checkpoint_snapshot(state, **options)
    assert type(result.payload) is bytes
    assert result.payload == expected == codec.serialize_checkpoint(state, **options)
    token = codec.checkpoint_baseline(state, **{key: value for key, value in options.items() if key != "metadata"})
    assert result.baseline == token
    assert len(token.component_digests) == len(MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS) == 38
    loaded = codec.deserialize_checkpoint(result.payload)
    assert token.state_digest == loaded.manifest.state_digest
    assert token.revision == loaded.state.state_revision
    assert token.component_digests == tuple(sorted(loaded.state.state_identity_record(metric_lineage=lineage).component_digests.items()))


@pytest.mark.parametrize("name", MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)
@pytest.mark.parametrize("precision", ["float32", "float64"])
def test_all_components_delta_exact_legacy_and_runner_copy_baseline(name, precision, tmp_path):
    old_full, old_delta = reference_functions()
    original = fixture()
    runner_previous = copied(original)
    token = codec.serialize_checkpoint_snapshot(original, float_precision=precision).baseline
    current = copied(original)
    mutate(current, name)
    options = {"float_precision": precision, "metadata": {"cycle": 2, "component": name}}
    expected = old_delta(runner_previous, current, **options)
    result = codec.serialize_delta_from_baseline(token, current, **options)
    legacy_result = codec.serialize_delta_snapshot(runner_previous, current, **options)
    assert result.payload == expected == legacy_result.payload == codec.serialize_delta(runner_previous, current, **options)
    assert result.baseline == legacy_result.baseline == codec.checkpoint_baseline(current, float_precision=precision)
    # Actual full/delta decoder enforces the same persisted endpoint identity.
    base_path = tmp_path / "base.bin"
    delta_path = tmp_path / "delta.bin"
    base_path.write_bytes(old_full(runner_previous, float_precision=precision))
    delta_path.write_bytes(result.payload)
    replayed = codec.load_checkpoint(base_path, delta_path=delta_path)
    expected_loaded = codec.deserialize_checkpoint(old_full(current, float_precision=precision))
    assert replayed.state.to_json() == expected_loaded.state.to_json()
    assert replayed.state.state_revision == expected_loaded.state.state_revision


@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("change", ["unchanged", "revision_only", "signed_zero", "int_float", "proof_hidden"])
def test_edge_normalization_exact_existing_semantics(precision, change):
    _, old_delta = reference_functions()
    base = fixture()
    state = copied(base)
    if change == "revision_only":
        state._state_identity_tracker.restore_revision(base.state_revision + 2)
    elif change == "signed_zero":
        state.legal_ir_view_logits["deontic"] = 0.0
    elif change == "int_float":
        state.legal_ir_view_logits["flogic"] = 1.0
    elif change == "proof_hidden":
        base.proof_feedback_version_fingerprint = ""
        state = copied(base)
        state.proof_auxiliary_head_logits = {"ignored": {"raw": {"x": 9.0}}}
    baseline = codec.checkpoint_baseline(base, float_precision=precision)
    expected = old_delta(copied(base), state, float_precision=precision, metadata={"fixture": change})
    actual = codec.serialize_delta_from_baseline(baseline, state, float_precision=precision, metadata={"fixture": change})
    assert actual.payload == expected


def test_baseline_has_no_graph_or_payload_and_is_immutable():
    state = fixture()
    state_ref = weakref.ref(state)
    snapshot = codec.serialize_checkpoint_snapshot(state)
    token = snapshot.baseline
    assert {item.name for item in fields(token)} == {"profile", "state_schema_version", "state_digest", "revision", "metric_lineage_digest", "metric_lineage_json", "float_precision", "component_digests"}
    assert not hasattr(token, "__dict__")
    assert len(repr(token)) < 10_000
    with pytest.raises(FrozenInstanceError):
        token.revision += 1
    del state, snapshot
    gc.collect()
    assert state_ref() is None


def test_current_native_target_reconstructed_once_and_startup_avoids_payload(monkeypatch):
    state = fixture()
    token = codec.checkpoint_baseline(state)
    next_state = copied(state)
    next_state.legal_ir_view_logits["new"] = 0.2
    calls = []
    original = codec._state_from_data
    def observe(data, state_factory=None):
        calls.append(1)
        return original(data, state_factory)
    monkeypatch.setattr(codec, "_state_from_data", observe)
    codec.serialize_delta_from_baseline(token, next_state)
    assert len(calls) == 1
    calls.clear()
    def no_encoding(*args, **kwargs):
        raise AssertionError("startup baseline encoded a checkpoint")
    monkeypatch.setattr(codec, "_encode_state_payload", no_encoding)
    assert codec.checkpoint_baseline(state) == token
    assert len(calls) == 1


@pytest.mark.parametrize("field,value", [
    ("profile", "wrong"), ("revision", True), ("revision", -1),
    ("float_precision", "float16"), ("state_digest", "z" * 64),
    ("metric_lineage_digest", "short"), ("component_digests", []),
    ("component_digests", (("z", "a" * 64), ("a", "b" * 64))),
    ("component_digests", (("a", "a" * 64), ("a", "b" * 64))),
    ("component_digests", (("a", "b"),)),
    ("metric_lineage_json", bytearray(b"null")),
    ("metric_lineage_json", b'{"a":1,"a":1}'),
    ("metric_lineage_json", b'NaN'), ("metric_lineage_json", b' null'),
])
def test_malformed_baseline_rejected(field, value):
    token = codec.checkpoint_baseline(fixture())
    with pytest.raises(codec.CheckpointLineageError):
        replace(token, **{field: value})


def test_binding_and_lineage_and_revision_rejections():
    state = fixture()
    token = codec.checkpoint_baseline(state, metric_lineage={"limit": 1.0})
    for lineage in ({"limit": 1}, {"limit": True}, {"limit": 1.000000000000001}, None):
        with pytest.raises(codec.CheckpointLineageError, match="requested lineage"):
            codec.serialize_delta_from_baseline(token, state, metric_lineage=lineage)
    with pytest.raises(codec.CheckpointLineageError, match="precision"):
        codec.serialize_delta_from_baseline(token, state, float_precision="float32", metric_lineage={"limit": 1.0})
    with pytest.raises(codec.CheckpointLineageError, match="precedes"):
        codec.serialize_delta_from_baseline(token, state, revision=token.revision - 1, metric_lineage={"limit": 1.0})
    state.legal_ir_view_logits["new"] = 0.25
    with pytest.raises(codec.CheckpointLineageError, match="advance"):
        codec.serialize_delta_from_baseline(token, state, revision=token.revision, metric_lineage={"limit": 1.0})
    bad_schema = replace(token, state_schema_version="different")
    with pytest.raises(codec.CheckpointLineageError, match="schema"):
        codec.serialize_delta_from_baseline(bad_schema, state, metric_lineage={"limit": 1.0})
    with pytest.raises(codec.CheckpointLineageError, match="exact"):
        codec.serialize_delta_from_baseline({}, state)


def test_token_revalidated_on_use_and_no_source_mutation():
    state = fixture()
    before = state.to_json(), state.state_revision
    token = codec.checkpoint_baseline(state)
    codec.serialize_delta_from_baseline(token, state)
    assert (state.to_json(), state.state_revision) == before
    object.__setattr__(token, "revision", True)
    with pytest.raises(codec.CheckpointLineageError):
        codec.serialize_delta_from_baseline(token, state)


def test_existing_precision_string_subclasses_keep_legacy_bytes():
    from enum import Enum
    class Precision(str, Enum):
        F64 = "float64"
    class String(str):
        pass
    old_full, old_delta = reference_functions()
    base = fixture()
    state = copied(base)
    state.legal_ir_view_logits["new"] = 0.125
    for precision in (String("float64"), Precision.F64):
        assert codec.serialize_checkpoint(state, float_precision=precision) == old_full(state, float_precision=precision)
        assert codec.serialize_delta(base, state, float_precision=precision) == old_delta(base, state, float_precision=precision)
        baseline = codec.serialize_checkpoint_snapshot(state, float_precision=precision).baseline
        assert type(baseline.float_precision) is str
        assert baseline.float_precision == "float64"


def test_explicit_legacy_revision_overrides_and_metadata_do_not_change_baseline():
    old_full, old_delta = reference_functions()
    base = fixture()
    state = copied(base)
    state.legal_ir_view_logits["new"] = 0.125
    options = {"base_revision": 100, "revision": 200, "metadata": {"override": True}}
    result = codec.serialize_delta_snapshot(base, state, **options)
    assert result.payload == old_delta(base, state, **options)
    baseline = codec.checkpoint_baseline(base, revision=100)
    assert codec.serialize_delta_from_baseline(baseline, state, revision=200, metadata=options["metadata"]) == result
    other = codec.serialize_checkpoint_snapshot(state, revision=200, metadata={"other": True})
    assert other.baseline == result.baseline
    assert other.payload == old_full(state, revision=200, metadata={"other": True})
