"""Exact endpoint shadows preserve raw fields beyond normalized model identity."""

import copy
import hashlib
import math

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_patch_codec as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_state_diff as diff


def clone(state):
    result = ma.ModalAutoencoderTrainingState(**{
        name: copy.deepcopy(getattr(state, name))
        for name in ma.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS
    })
    result._state_identity_tracker.restore_revision(state.state_revision)
    return result


def replay(base, result, **kwargs):
    initial_base = diff.exact_state_snapshot(base)
    initial_result = diff.exact_state_snapshot(result)
    captured = diff.capture_endpoint_patch(base, result, base_version_id="registered-base", **kwargs)
    restored = clone(base)
    receipt = codec.replay_patch(restored, captured.data, expected_base_version_id="registered-base",
                                 expected_sequence=kwargs.get("sequence", 0))
    assert diff.exact_state_snapshot(restored) == initial_result
    assert diff.exact_state_snapshot(base) == initial_base
    assert diff.exact_state_snapshot(result) == initial_result
    assert captured.report["base_snapshot"] == initial_base
    assert captured.report["result_snapshot"] == initial_result
    assert receipt["admitted"] is False
    assert captured.report["admitted"] is False
    assert captured.report["patch_sha256"] == hashlib.sha256(captured.data).hexdigest()
    assert captured.report["patch_bytes"] == len(captured.data)
    return captured, restored


def test_snapshot_matches_independent_existing_codec_for_all_38_fields():
    state = ma.ModalAutoencoderTrainingState(
        feature_embedding_weights={"quoted\"\n\udfff\U0001f600": [0.0, -0.0, math.nextafter(1.0, 2.0)]},
        applied_todo_ids=["one", "one", "two"],
    )
    snapshot = diff.exact_state_snapshot(state)
    assert snapshot == diff.exact_state_snapshot(state)
    assert snapshot["component_count"] == 38
    assert snapshot["component_fields"] == list(ma.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)
    total = 0
    for name in ma.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS:
        raw = codec._json(codec._encode_value(getattr(state, name)))
        assert snapshot["components"][name] == {
            "sha256": hashlib.sha256(raw).hexdigest(), "encoded_bytes": len(raw),
        }
        total += len(raw)
    assert snapshot["total_encoded_bytes"] == total
    assert snapshot["plain_identity"] == state.state_identity_record().to_dict()


@pytest.mark.parametrize("name", ma.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)
def test_each_native_component_is_diffed_and_replayed(name):
    base = ma.ModalAutoencoderTrainingState()
    result = clone(base)
    if name == "architecture_version":
        result.architecture_version = "synthetic-different-architecture"
    elif name == "proof_feedback_version_fingerprint":
        result.proof_feedback_version_fingerprint = "synthetic-proof-version"
    elif name.startswith("applied_"):
        setattr(result, name, ["z", "a", "a"])
    elif name == "proof_auxiliary_head_logits":
        result.proof_auxiliary_head_logits["unrecognized-head"] = {"x": {"yes": -0.0}}
    elif name == "legal_ir_view_logits":
        result.legal_ir_view_logits["view"] = -0.0
    elif "embedding" in name:
        getattr(result, name)["row"] = [0.5, -0.0]
    else:
        getattr(result, name)["row"] = {"view": -0.0}
    captured, _ = replay(base, result)
    assert captured.report["changed_components"] == [name]
    assert captured.report["counts"]["changed_component_count"] == 1
    assert captured.report["revision_only"] is False


def test_signed_zero_delete_insert_and_nested_mapping_order():
    base = ma.ModalAutoencoderTrainingState(
        feature_embedding_weights={"keep": [0.0], "delete": []},
        feature_family_logits={"row": {"a": 0.0, "b": 1.0}},
    )
    result = clone(base)
    result.feature_embedding_weights["keep"][0] = -0.0
    del result.feature_embedding_weights["delete"]
    result.feature_embedding_weights["insert"] = []
    result.feature_family_logits["row"] = {"b": 1.0, "a": 0.0}
    captured, restored = replay(base, result)
    assert captured.report["counts"]["inserted_rows"] == 1
    assert captured.report["counts"]["deleted_rows"] == 1
    assert captured.report["counts"]["touched_row_count"] == 4
    assert captured.report["component_replacements"] == []
    assert math.copysign(1.0, restored.feature_embedding_weights["keep"][0]) == -1.0
    assert list(restored.feature_family_logits["row"]) == ["b", "a"]


@pytest.mark.parametrize("old,new", [
    ({"a": 1.0, "b": 2.0}, {"b": 2.0, "a": 1.0}),
    ({"b": 2.0}, {"a": 1.0, "b": 2.0}),
    ({1: 1.0}, {True: 1.0}),
    ({1: 1.0}, {1.0: 1.0}),
    ({0.0: 1.0}, {-0.0: 1.0}),
])
def test_reordering_or_equal_python_keys_with_different_types_replace_component(old, new):
    base = ma.ModalAutoencoderTrainingState(legal_ir_view_logits=old)
    result = clone(base)
    result.legal_ir_view_logits = new
    captured, restored = replay(base, result)
    assert captured.report["component_replacements"] == ["legal_ir_view_logits"]
    assert captured.report["counts"]["touched_row_count"] == 0
    assert codec._encode_value(restored.legal_ir_view_logits) == codec._encode_value(new)


def test_typed_tuple_and_string_keys_can_use_rows_without_coercion():
    base = ma.ModalAutoencoderTrainingState(legal_ir_view_logits={1: -0.0})
    result = clone(base)
    result.legal_ir_view_logits["1"] = 0.25
    result.legal_ir_view_logits[("tuple", 2)] = 0.75
    captured, restored = replay(base, result)
    assert list(restored.legal_ir_view_logits) == [1, "1", ("tuple", 2)]
    assert captured.report["counts"]["inserted_rows"] == 2


def test_proof_head_raw_change_is_not_lost_to_conditional_normalization():
    base = ma.ModalAutoencoderTrainingState(proof_auxiliary_head_logits={"unknown": {"f": {"x": 1.0}}})
    result = clone(base)
    result.proof_auxiliary_head_logits["unknown"]["f"]["x"] = 2.0
    assert base.component_digests == result.component_digests
    assert base.state_identity() == result.state_identity()
    captured, _ = replay(base, result)
    assert captured.report["changed_components"] == ["proof_auxiliary_head_logits"]
    assert captured.report["base_snapshot"]["raw_state_sha256"] != captured.report["result_snapshot"]["raw_state_sha256"]


@pytest.mark.parametrize("name", ["applied_proof_feedback_ids", "applied_leanstral_guidance_ids", "applied_todo_ids"])
def test_applied_ids_preserve_duplicates_order_and_removal(name):
    base = ma.ModalAutoencoderTrainingState(**{name: ["a", "b", "a"]})
    result = clone(base)
    setattr(result, name, ["b", "b", "a"])
    captured, restored = replay(base, result)
    assert list(getattr(restored, name)) == ["b", "b", "a"]
    assert captured.report["component_replacements"] == [name]


def test_revision_only_uses_explicit_unchanged_witness():
    base = ma.ModalAutoencoderTrainingState()
    result = clone(base)
    result.legal_ir_view_logits["temporary"] = 0.25
    del result.legal_ir_view_logits["temporary"]
    captured, _ = replay(base, result)
    report = captured.report
    assert report["changed_components"] == []
    assert report["revision_only"] is True
    assert report["revision_witness_component"] == "architecture_version"
    assert report["component_replacements"] == []
    assert report["counts"]["revision_witness_count"] == 1
    assert report["counts"]["touched_component_count"] == 1
    component, = codec.decode_patch(captured.data).patch.components
    assert component.after_value == base.architecture_version


def test_unchanged_same_object_has_empty_patch_and_no_revision_witness():
    state = ma.ModalAutoencoderTrainingState()
    captured, _ = replay(state, state)
    assert not codec.decode_patch(captured.data).patch.rows
    assert not codec.decode_patch(captured.data).patch.components
    assert captured.report["revision_witness_component"] is None
    assert captured.report["counts"] == {
        "changed_component_count": 0, "touched_row_count": 0,
        "touched_component_count": 0, "inserted_rows": 0,
        "deleted_rows": 0, "revision_witness_count": 0,
    }


def test_nonzero_compact_revision_and_full_compact_regeneration():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
        deserialize_checkpoint, serialize_checkpoint,
    )
    state = ma.ModalAutoencoderTrainingState(feature_embedding_weights={"row": [-0.0]})
    state._state_identity_tracker.restore_revision(41)
    base = deserialize_checkpoint(serialize_checkpoint(state)).state
    result = clone(base)
    result.applied_todo_ids.extend(["x", "x"])
    final = serialize_checkpoint(result, metadata={"reason": "synthetic-final"}, metric_lineage="test")
    loaded = deserialize_checkpoint(final)
    _, restored = replay(base, loaded.state)
    assert restored.state_revision == 42
    assert serialize_checkpoint(restored, metadata=loaded.manifest.metadata,
                                metric_lineage=loaded.manifest.metric_lineage) == final


def test_decreasing_revision_rejected_without_mutation():
    base = ma.ModalAutoencoderTrainingState()
    base.applied_todo_ids.append("old")
    result = ma.ModalAutoencoderTrainingState()
    with pytest.raises(diff.StateDiffError, match="precedes"):
        diff.capture_endpoint_patch(base, result, base_version_id="base")
    assert base.state_revision == 1 and result.state_revision == 0


@pytest.mark.parametrize("which", ["base", "result"])
def test_active_transaction_rejected(which):
    states = {"base": ma.ModalAutoencoderTrainingState(), "result": ma.ModalAutoencoderTrainingState()}
    tx = states[which].transaction().begin()
    try:
        with pytest.raises(diff.StateDiffError, match="active transaction"):
            diff.capture_endpoint_patch(**states, base_version_id="base")
        assert tx.active
    finally:
        tx.rollback()


@pytest.mark.parametrize("phase", ["scan", "encode"])
def test_observed_mutation_during_capture_rejects(phase, monkeypatch):
    base = ma.ModalAutoencoderTrainingState()
    result = clone(base)
    if phase == "scan":
        original = diff._TypedCopy.visit
        invoked = False
        def changing(self, value, depth=0):
            nonlocal invoked
            if value is base.decoded_embeddings and not invoked:
                invoked = True
                base.applied_todo_ids.append("concurrent")
            return original(self, value, depth)
        monkeypatch.setattr(diff._TypedCopy, "visit", changing)
    else:
        original = codec.encode_patch
        def changing(*args, **kwargs):
            value = original(*args, **kwargs)
            result.applied_todo_ids.append("concurrent")
            return value
        monkeypatch.setattr(codec, "encode_patch", changing)
    with pytest.raises(diff.StateDiffError, match="mutated"):
        diff.capture_endpoint_patch(base, result, base_version_id="base")


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan, 1 << 4096, object()])
def test_unsupported_or_unbounded_scalars_rejected(value):
    state = ma.ModalAutoencoderTrainingState(legal_ir_view_logits={"bad": value})
    with pytest.raises(diff.StateDiffError):
        diff.exact_state_snapshot(state)


def test_non_native_state_and_custom_field_values_rejected_without_callbacks():
    class Foreign:
        def __iter__(self):
            pytest.fail("custom iterator called")
    with pytest.raises(diff.StateDiffError, match="exact native"):
        diff.exact_state_snapshot(Foreign())
    state = ma.ModalAutoencoderTrainingState()
    state.legal_ir_view_logits["x"] = Foreign()
    with pytest.raises(diff.StateDiffError, match="unsupported native"):
        diff.exact_state_snapshot(state)


def test_component_and_total_bound_exact_edges(monkeypatch):
    state = ma.ModalAutoencoderTrainingState(applied_todo_ids=["x" * 100])
    snapshot = diff.exact_state_snapshot(state)
    largest = max(item["encoded_bytes"] for item in snapshot["components"].values())
    monkeypatch.setattr(diff, "MAX_COMPONENT_BYTES", largest)
    monkeypatch.setattr(diff, "MAX_STATE_BYTES", snapshot["total_encoded_bytes"])
    assert diff.exact_state_snapshot(state) == snapshot
    monkeypatch.setattr(diff, "MAX_STATE_BYTES", snapshot["total_encoded_bytes"] - 1)
    with pytest.raises(diff.StateDiffError, match="byte bound"):
        diff.exact_state_snapshot(state)
    monkeypatch.setattr(diff, "MAX_STATE_BYTES", snapshot["total_encoded_bytes"])
    monkeypatch.setattr(diff, "MAX_COMPONENT_BYTES", largest - 1)
    with pytest.raises(diff.StateDiffError, match="byte bound"):
        diff.exact_state_snapshot(state)


def test_long_escaped_string_chunking_matches_existing_codec():
    state = ma.ModalAutoencoderTrainingState(applied_todo_ids=[("a\n\udfff\U0001f600\\\"" * 1100)])
    raw = codec._json(codec._encode_value(state.applied_todo_ids))
    assert diff.exact_state_snapshot(state)["components"]["applied_todo_ids"] == {
        "sha256": hashlib.sha256(raw).hexdigest(), "encoded_bytes": len(raw),
    }


def test_depth_bound_and_cycle_rejection():
    state = ma.ModalAutoencoderTrainingState()
    nested = "leaf"
    for _ in range(codec.MAX_VALUE_DEPTH + 1):
        nested = [nested]
    # Bypass recursive tracking only to construct a hostile-value boundary.
    dict.__setitem__(state.legal_ir_view_logits, "deep", nested)
    with pytest.raises(diff.StateDiffError, match="depth"):
        diff.exact_state_snapshot(state)
    cycle = []
    cycle.append(cycle)
    dict.__setitem__(state.legal_ir_view_logits, "deep", cycle)
    with pytest.raises(diff.StateDiffError, match="depth"):
        diff.exact_state_snapshot(state)


def test_patch_entry_and_wire_caps_preserved(monkeypatch):
    base = ma.ModalAutoencoderTrainingState()
    result = clone(base)
    result.legal_ir_view_logits.update({"a": 1.0, "b": 2.0})
    monkeypatch.setattr(codec, "MAX_PATCH_ENTRIES", 1)
    with pytest.raises(diff.StateDiffError, match="entry count"):
        diff.capture_endpoint_patch(base, result, base_version_id="base")
    monkeypatch.setattr(codec, "MAX_PATCH_ENTRIES", 1_000_000)
    monkeypatch.setattr(codec, "MAX_PATCH_BYTES", 100)
    with pytest.raises(codec.PatchCodecError, match="byte bound"):
        diff.capture_endpoint_patch(base, result, base_version_id="base")


@pytest.mark.parametrize("kwargs", [
    {"sequence": True}, {"sequence": -1}, {"base_version_id": ""},
    {"base_version_id": "x" * 257}, {"provenance": []},
])
def test_binding_arguments_reject_before_scanning(kwargs, monkeypatch):
    monkeypatch.setattr(diff, "_snapshot", lambda *a, **k: pytest.fail("scanned invalid binding"))
    options = {"base_version_id": "base", **kwargs}
    with pytest.raises(diff.StateDiffError):
        diff.capture_endpoint_patch(ma.ModalAutoencoderTrainingState(), ma.ModalAutoencoderTrainingState(), **options)


def test_patch_provenance_is_detached_and_timings_are_outside_snapshots():
    base = ma.ModalAutoencoderTrainingState()
    result = clone(base)
    result.applied_todo_ids.append("id")
    provenance = {"run_id": "unit", "nested": ["before"]}
    captured, _ = replay(base, result, sequence=7, provenance=provenance)
    provenance["nested"].append("later")
    assert codec.decode_patch(captured.data).provenance == {"run_id": "unit", "nested": ["before"]}
    assert "timings" not in captured.report["base_snapshot"]
    assert "timings" not in captured.report["result_snapshot"]
    for key, value in captured.report["timings"].items():
        if key.endswith("_seconds"):
            assert math.isfinite(value) and value >= 0


def test_capture_does_not_copy_or_serialize_whole_native_state(monkeypatch):
    base = ma.ModalAutoencoderTrainingState(feature_embedding_weights={"untouched": [1.0] * 100})
    result = clone(base)
    result.legal_ir_view_logits["view"] = 0.5
    for state in (base, result):
        monkeypatch.setattr(state, "copy", lambda: pytest.fail("whole-state copy"))
        monkeypatch.setattr(state, "to_dict", lambda: pytest.fail("whole-state serialization"))
    monkeypatch.setattr(copy, "deepcopy", lambda *a, **k: pytest.fail("deepcopy"))
    original_visit = diff._TypedCopy.visit
    def checked_visit(self, value, depth=0):
        if value is base.feature_embedding_weights or value is result.feature_embedding_weights:
            assert not self.copy_values
        return original_visit(self, value, depth)
    monkeypatch.setattr(diff._TypedCopy, "visit", checked_visit)
    captured = diff.capture_endpoint_patch(base, result, base_version_id="base")
    assert captured.report["changed_components"] == ["legal_ir_view_logits"]
    assert captured.report["counts"]["touched_row_count"] == 1
