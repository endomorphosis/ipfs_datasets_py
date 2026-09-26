"""Sparse durable postimage and accepted-commit boundary qualification."""

import hashlib
import json
import math

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import (
    PatchCodecError, decode_patch, encode_patch, replay_patch,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_transaction import (
    ModalAutoencoderStatePatch, TouchedRow,
)


def _state():
    return ma.ModalAutoencoderTrainingState(
        feature_embedding_weights={"keep": [8.0], "change": [1.0, -0.0], "delete": []},
        feature_family_logits={"The agency shall retain the file.": {"deontic": 0.25}},
        applied_todo_ids=["prior"],
    )


def _captured():
    state = _state()
    base_identity = state.state_identity()
    with state.transaction() as tx:
        state.feature_embedding_weights["change"][0] = -0.0
        state.feature_embedding_weights["new"] = []
        del state.feature_embedding_weights["delete"]
        state.feature_family_logits["The agency shall retain the file."]["deontic"] = 0.0
        state.applied_todo_ids.append("accepted")
    blob = encode_patch(tx.patch, base_state_identity=base_identity,
                        result_state_identity=state.state_identity(), base_version_id="base-1",
                        sequence=0, provenance={"run_id": "run-1", "label": "epoch:1"})
    return state, tx.patch, blob


def _rewrite(blob, mutate):
    envelope = json.loads(blob)
    mutate(envelope["payload"])
    canonical = lambda obj: json.dumps(obj, allow_nan=False, ensure_ascii=True,
                                      sort_keys=True, separators=(",", ":")).encode()
    envelope["payload_sha256"] = hashlib.sha256(canonical(envelope["payload"])).hexdigest()
    return canonical(envelope)


def test_exact_replay_preserves_presence_private_keys_float_bits_metadata_and_revision():
    candidate, patch, blob = _captured()
    segment = decode_patch(blob)
    restored = _state()
    receipt = replay_patch(restored, segment, expected_base_version_id="base-1", expected_sequence=0)
    assert restored.to_json() == candidate.to_json()
    assert restored.state_revision == candidate.state_revision == patch.result_revision
    assert restored.state_identity() == candidate.state_identity()
    assert math.copysign(1.0, restored.feature_embedding_weights["change"][0]) == -1
    assert "delete" not in restored.feature_embedding_weights
    assert restored.feature_embedding_weights["new"] == []
    assert segment.provenance == {"run_id": "run-1", "label": "epoch:1"}
    assert receipt["admitted"] is False
    assert receipt["touched_row_count"] == 4
    assert receipt["identity_hashing_scope"] == "dirty_components_not_touched_rows"
    assert encode_patch(patch, base_state_identity=segment.base_state_identity,
                        result_state_identity=segment.result_state_identity, base_version_id="base-1",
                        sequence=0, provenance=segment.provenance) == blob


@pytest.mark.parametrize("change,match", [
    (lambda payload: payload.update(base_state_identity="0" * 64), "base state identity"),
    (lambda payload: payload.update(result_state_identity="0" * 64), "result state identity"),
    (lambda payload: payload.update(base_revision=7, result_revision=8), "base revision"),
    (lambda payload: payload["rows"][0].update(before_sha256="0" * 64), "before-image"),
    (lambda payload: payload["components"][0].update(before_sha256="0" * 64), "before-image"),
])
def test_wrong_identity_or_before_digest_fails_without_changing_state(change, match):
    _candidate, _patch, blob = _captured()
    state = _state()
    identity = state.state_identity_record()
    original = state.to_json()
    with pytest.raises(PatchCodecError, match=match):
        replay_patch(state, _rewrite(blob, change), expected_base_version_id="base-1")
    assert state.to_json() == original
    assert state.state_identity_record() == identity
    assert state._active_state_transaction is None


def test_sequence_version_duplicate_and_decoded_mutation_fail_closed():
    _candidate, _patch, blob = _captured()
    state = _state()
    with pytest.raises(PatchCodecError, match="base version"):
        replay_patch(state, blob, expected_base_version_id="another-base")
    with pytest.raises(PatchCodecError, match="sequence"):
        replay_patch(state, blob, expected_base_version_id="base-1", expected_sequence=1)
    segment = decode_patch(blob)
    segment.provenance["run_id"] = "changed"
    with pytest.raises(PatchCodecError, match="mutated"):
        replay_patch(state, segment, expected_base_version_id="base-1")
    replay_patch(state, blob, expected_base_version_id="base-1")
    with pytest.raises(PatchCodecError, match="base revision"):
        replay_patch(state, blob, expected_base_version_id="base-1")


@pytest.mark.parametrize("change,match", [
    (lambda payload: payload["rows"][0].update(component="__class__"), "unknown state component"),
    (lambda payload: payload["rows"].append(payload["rows"][0]), "duplicate row"),
    (lambda payload: payload["rows"][0].update(after_value=["pickle", "os.system"]), "unsupported typed"),
    (lambda payload: payload["rows"][0].update(after_value=["float64", "7ff0000000000000"]), "unsupported typed"),
    (lambda payload: payload.update(schema="future-version"), "unsupported patch schema"),
    (lambda payload: payload.update(sequence=True), "sequence"),
])
def test_safe_decoder_rejects_unsupported_or_ambiguous_payload(change, match):
    _candidate, _patch, blob = _captured()
    with pytest.raises(PatchCodecError, match=match):
        decode_patch(_rewrite(blob, change))


def test_corrupt_truncated_duplicate_json_and_nonfinite_input_fail():
    _candidate, _patch, blob = _captured()
    with pytest.raises(PatchCodecError, match="checksum"):
        decode_patch(blob.replace(b'"run-1"', b'"run-2"'))
    for bad in (blob[:-1], b'{"payload":1,"payload":2}', b'{"x":NaN}', b"\x80\x04pickle"):
        with pytest.raises(PatchCodecError):
            decode_patch(bad)
    patch = ModalAutoencoderStatePatch(0, 1, (TouchedRow("legal_ir_view_logits", "x", False,
                                                       None, True, math.nan, 0),), ())
    with pytest.raises(PatchCodecError, match="non-finite"):
        encode_patch(patch, base_state_identity="0" * 64, result_state_identity="1" * 64,
                     base_version_id="v", sequence=0)


def test_typed_keys_and_mapping_order_are_not_coerced():
    row = TouchedRow("feature_family_logits", ("a", 2), False, None, True,
                     {"2": 0.5, 2: -0.0, "empty": []}, 0)
    patch = ModalAutoencoderStatePatch(0, 1, (row,), ())
    decoded = decode_patch(encode_patch(patch, base_state_identity="0" * 64,
                                       result_state_identity="1" * 64, base_version_id="v", sequence=0))
    after = decoded.patch.rows[0]
    assert after.key == ("a", 2)
    assert list(after.after_value) == ["2", 2, "empty"]
    assert math.copysign(1.0, after.after_value[2]) == -1


def test_full_component_replacement_after_row_mutations_rolls_back_and_replays():
    state = _state()
    before = state.to_json()
    base = state.state_identity()
    tx = state.transaction().begin()
    state.feature_embedding_weights["change"][0] = 17.0
    state.feature_embedding_weights["new-before-replace"] = [9.0]
    state.feature_embedding_weights = {"replacement": [3.0]}
    state.feature_embedding_weights["replacement"].append(4.0)
    patch = tx.capture_patch()
    result = state.state_identity()
    expected = state.to_json()
    tx.rollback()
    assert state.to_json() == before
    assert not patch.rows
    assert len(patch.components) == 1
    blob = encode_patch(patch, base_state_identity=base, result_state_identity=result,
                        base_version_id="v", sequence=0)
    replay_patch(state, blob, expected_base_version_id="v")
    assert state.to_json() == expected


def test_codec_size_scales_with_touched_rows_not_untouched_state(monkeypatch):
    state = ma.ModalAutoencoderTrainingState(feature_embedding_weights={f"row-{i}": [float(i)] for i in range(5000)})
    base = state.state_identity()
    with state.transaction() as tx:
        state.feature_embedding_weights["row-2000"][0] = -2.0
    monkeypatch.setattr(state, "copy", lambda: pytest.fail("whole-state copy"))
    monkeypatch.setattr(state, "to_dict", lambda: pytest.fail("whole-state serialization"))
    blob = encode_patch(tx.patch, base_state_identity=base, result_state_identity=state.state_identity(),
                        base_version_id="v", sequence=0)
    assert len(blob) < 2000
    assert len(decode_patch(blob).patch.rows) == 1


def _controlled_training(monkeypatch, *, accepted=True, deadline=False):
    model = ma.AdaptiveModalAutoencoder(state=ma.ModalAutoencoderTrainingState(legal_ir_view_logits={"x": 0.0}))
    clock = {"now": 0.0}
    monkeypatch.setattr(ma.time, "time", lambda: clock["now"])
    monkeypatch.setattr(model, "_select_hard_examples_for_projection", lambda rows, **_: list(rows))

    def evaluate(rows, **_):
        changed = bool(model.state.legal_ir_view_logits["x"])
        if changed and deadline:
            clock["now"] = 2.0
        loss = (0.5 if accepted else 2.0) if changed else 1.0
        return ma.AutoencoderEvaluation(len(rows), 1.0, 0.0, 0.0, loss, 0.0, 0.0, {})

    def update(*_, **__):
        model.state.legal_ir_view_logits["x"] = 1.0
        return {name: {} for name in ("gradient_norms_by_family", "gradient_norms_by_head",
                                     "head_family_gradient_norms", "head_family_update_norms",
                                     "update_norms_by_family", "update_norms_by_head")}

    monkeypatch.setattr(model, "evaluate", evaluate)
    monkeypatch.setattr(model, "_apply_projection_update_batch", update)
    monkeypatch.setattr(ma.ModalAutoencoderTrainingState, "copy", lambda _: pytest.fail("whole-state copy"))
    return model


@pytest.mark.parametrize("deadline", [False, True])
def test_sink_receives_only_selected_committed_patch_including_deadline_path(monkeypatch, deadline):
    model = _controlled_training(monkeypatch, deadline=deadline)
    initial = model.state.to_dict()
    received = []

    def sink(patch, context):
        assert model.state._active_state_transaction is None
        assert model.state.legal_ir_view_logits["x"] == 1.0
        assert context["result_state_identity"] == model.state.state_identity()
        received.append(encode_patch(patch, base_state_identity=context["base_state_identity"],
                                     result_state_identity=context["result_state_identity"],
                                     base_version_id="v", sequence=len(received), provenance={"label": context["label"]}))

    report = model.train_generalizable_projection([object()], epochs=1, max_seconds=1 if deadline else None,
                                                  max_line_search_attempts=1, projection_max_update_families=2,
                                                  accepted_patch_sink=sink)
    assert report["accepted_epochs"] == len(received) == 1
    assert report["stopped_reason"] == ("projection_timeout" if deadline else None)
    restored = ma.ModalAutoencoderTrainingState.from_dict(initial)
    replay_patch(restored, received[0], expected_base_version_id="v")
    assert restored.to_json() == model.state.to_json()
    assert restored.state_revision == model.state.state_revision


def test_rejected_trials_never_call_sink(monkeypatch):
    model = _controlled_training(monkeypatch, accepted=False)
    before = model.state.to_json()
    report = model.train_generalizable_projection([object()], epochs=1, max_line_search_attempts=2,
                                                  projection_max_update_families=2,
                                                  accepted_patch_sink=lambda *_: pytest.fail("rejected trial emitted"))
    assert report["accepted_epochs"] == 0
    assert model.state.to_json() == before


def test_sink_failure_propagates_after_commit_and_does_not_claim_rollback(monkeypatch):
    model = _controlled_training(monkeypatch)

    def failing_sink(*_):
        raise OSError("patch storage unavailable")

    with pytest.raises(OSError, match="patch storage unavailable"):
        model.train_generalizable_projection([object()], epochs=1, max_line_search_attempts=1,
                                              projection_max_update_families=1, accepted_patch_sink=failing_sink)
    assert model.state.legal_ir_view_logits["x"] == 1.0
    assert model.state._active_state_transaction is None


def test_no_sink_does_not_call_new_logical_identity_hook(monkeypatch):
    model = _controlled_training(monkeypatch)
    monkeypatch.setattr(model.state, "state_identity", lambda **_: pytest.fail("no-sink hashing"))
    report = model.train_generalizable_projection([object()], epochs=1, max_line_search_attempts=1,
                                                  projection_max_update_families=1)
    assert report["accepted_epochs"] == 1


def test_real_bounded_projection_replays_complete_candidate_without_shared_mock_evaluator():
    # Diagnostic embedding fixture and bridge-off optimizer check, not a legal
    # IR speed measurement or held-out quality/admission claim.
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    sample = build_us_code_sample(title="5", section="1", text="The agency shall retain records.",
                                 embedding_vector=[0.8, 0.3, -0.2, 0.1])
    model = ma.AdaptiveModalAutoencoder(compute_device="python")
    base = model.state.to_dict()
    segments = []

    def sink(patch, context):
        segments.append(encode_patch(patch, base_state_identity=context["base_state_identity"],
                                     result_state_identity=context["result_state_identity"],
                                     base_version_id="fixture-base", sequence=len(segments)))

    report = model.train_generalizable_projection(
        [sample], validation_samples=[sample], legal_ir_bridge_names=(), epochs=1,
        max_line_search_attempts=1, projection_max_update_families=5, max_seconds=60,
        projection_update_backend="python_sparse_batch", accepted_patch_sink=sink,
    )
    assert report["accepted_epochs"] == len(segments) == 1
    restored = ma.ModalAutoencoderTrainingState.from_dict(base)
    for index, segment in enumerate(segments):
        replay_patch(restored, segment, expected_base_version_id="fixture-base", expected_sequence=index)
    assert restored.to_json() == model.state.to_json()
    assert restored.state_revision == model.state.state_revision
