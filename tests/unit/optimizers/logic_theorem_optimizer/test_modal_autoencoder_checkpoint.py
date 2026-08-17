"""Regression tests for compact modal-autoencoder checkpoints and deltas."""

from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.async_artifact_writer import (
    ArtifactFsyncPolicy,
    AsyncArtifactWriter,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.logic.formalization.checkpoints import (
    CHECKPOINT_MANIFEST_SCHEMA_VERSION,
    IR_CHECKPOINT_LIFECYCLE_STATES,
    IR_CHECKPOINT_LIFECYCLE_TRANSITIONS,
    IR_CHECKPOINT_M1_FIELDS,
    IR_CHECKPOINT_M1_IDENTITY_FIELDS,
    IR_CHECKPOINT_MANIFEST_SCHEMA,
    IR_CHECKPOINT_SIDE_OUTCOME_KINDS,
    CheckpointManifest as FormalizationCheckpointManifest,
    FormalizationValidationError,
    IRCheckpointLifecycleError,
    IRCheckpointManifest,
    IRCheckpointPromotionError,
    IRCheckpointSideOutcome,
    IRCheckpointValidationError,
    IRPromotionManifest,
    adapt_formalization_advisor_manifest,
    allowed_lifecycle_transition,
    validate_ir_checkpoint_manifest,
    verify_ir_checkpoint_manifest,
    verify_lifecycle_transition,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
    AmbiguousCurrentPointerError,
    CHECKPOINT_MAGIC,
    CHECKPOINT_WRITE_KEY,
    DELTA_MAGIC,
    MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION,
    PROMOTION_KEY,
    CheckpointCorruptionError,
    CheckpointLifecycleStore,
    CheckpointLineageError,
    CheckpointQuarantineError,
    IncompatibleManifestAliasError,
    adapt_modal_state_manifest,
    append_delta_segment,
    deserialize_checkpoint,
    iter_delta_segments,
    load_checkpoint,
    quantize_float,
    reject_incompatible_manifest_alias,
    serialize_checkpoint,
    serialize_delta,
    write_checkpoint_atomic,
)


METRIC_LINEAGE = {
    "metric_schema": "legal-ir-checkpoint-test-metrics-v1",
    "suite": "canonical",
}


def _canonical_state(rows: int = 800, width: int = 64) -> ModalAutoencoderTrainingState:
    randomizer = random.Random(103)
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={
            f"sample-{row:05d}": [randomizer.uniform(-1.0, 1.0) for _ in range(width)]
            for row in range(rows)
        },
        family_logits={
            f"sample-{row:05d}": {
                family: randomizer.uniform(-2.0, 2.0)
                for family in ("cec", "deontic", "flogic", "kg", "tdfol")
            }
            for row in range(rows)
        },
        feature_embedding_weights={
            f"feature-{row:04d}": [
                math.sin((row + 1) * (column + 1) / 37.0) for column in range(width)
            ]
            for row in range(100)
        },
        feature_family_logits={
            "shall": {"deontic": 0.875, "kg": -0.125},
            "unless": {"cec": 0.625, "tdfol": 0.375},
        },
        proof_auxiliary_head_logits={
            "obligation_family": {"__global__": {"mandatory": 0.75, "permissive": -0.25}}
        },
        proof_feedback_version_fingerprint="hammer-toolchain-v1",
        applied_proof_feedback_ids=["proof-a"],
        applied_leanstral_guidance_ids=["guidance-a"],
        applied_todo_ids=["todo-a"],
    )
    # Give the fixture a meaningful durable operational revision.
    state.legal_ir_view_logits["deontic"] = 0.25
    return state


def test_full_checkpoint_is_typed_checksummed_and_sixty_percent_smaller() -> None:
    state = _canonical_state()
    encoded = serialize_checkpoint(state, metric_lineage=METRIC_LINEAGE)
    loaded = deserialize_checkpoint(
        encoded,
        expected_state_schema_version=MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
        expected_metric_lineage=METRIC_LINEAGE,
        expected_revision=state.state_revision,
    )

    assert encoded.startswith(CHECKPOINT_MAGIC)
    assert loaded.manifest.schema_version == MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION
    assert loaded.manifest.table_count >= 4
    assert loaded.manifest.numeric_value_count > 50_000
    assert loaded.manifest.float_precision == "float64"
    assert loaded.state.to_dict() == state.to_dict()
    assert loaded.state.state_revision == state.state_revision
    assert loaded.state.state_identity(metric_lineage=METRIC_LINEAGE) == (
        state.state_identity(metric_lineage=METRIC_LINEAGE)
    )
    json_size = len((state.to_json() + "\n").encode("utf-8"))
    assert len(encoded) <= int(json_size * 0.40)


def test_float32_round_trip_is_exact_at_declared_precision() -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample": [0.123456789, -0.987654321, 1.0 / 3.0]},
        family_logits={"sample": {"deontic": 0.777777777}},
    )
    loaded = deserialize_checkpoint(serialize_checkpoint(state, float_precision="float32"))

    expected = [quantize_float(value, "float32") for value in state.decoded_embeddings["sample"]]
    assert loaded.manifest.float_precision == "float32"
    assert loaded.state.decoded_embeddings["sample"] == expected
    assert loaded.state.family_logits["sample"]["deontic"] == quantize_float(
        state.family_logits["sample"]["deontic"], "float32"
    )


def test_current_json_state_remains_loadable(tmp_path: Path) -> None:
    state = _canonical_state(rows=2, width=4)
    path = tmp_path / "legacy.state.json"
    state.save_json(path)

    loaded = load_checkpoint(
        path,
        expected_state_schema_version=MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
        expected_metric_lineage=METRIC_LINEAGE,
    )

    assert loaded.format == "json"
    assert loaded.manifest.metadata["legacy_json"] is True
    assert loaded.state.to_dict() == state.to_dict()


@pytest.mark.parametrize("location", [80, -1])
def test_checkpoint_rejects_manifest_and_payload_corruption(location: int) -> None:
    encoded = bytearray(serialize_checkpoint(_canonical_state(rows=2, width=4)))
    encoded[location] ^= 0x01

    with pytest.raises(CheckpointCorruptionError, match="checksum"):
        deserialize_checkpoint(bytes(encoded))


def test_delta_log_applies_only_touched_components_and_verifies_revision(
    tmp_path: Path,
) -> None:
    base = _canonical_state(rows=4, width=8)
    checkpoint_path = tmp_path / "state.checkpoint"
    delta_path = tmp_path / "state.deltas"
    write_checkpoint_atomic(
        checkpoint_path,
        base,
        metric_lineage=METRIC_LINEAGE,
    )

    changed = base.copy()
    changed._state_identity_tracker.restore_revision(base.state_revision)
    changed.feature_embedding_weights["feature-0000"][2] = 0.8125
    changed.applied_todo_ids.append("todo-b")
    segment = serialize_delta(base, changed, metric_lineage=METRIC_LINEAGE)
    assert segment.startswith(DELTA_MAGIC)
    [(manifest, _payload)], _offset, recovered = iter_delta_segments(segment)
    assert recovered == 0
    assert set(manifest.changed_components) == {
        "applied_todo_ids",
        "feature_embedding_weights",
    }
    append_delta_segment(delta_path, segment)

    loaded = load_checkpoint(
        checkpoint_path,
        delta_path=delta_path,
        expected_metric_lineage=METRIC_LINEAGE,
        expected_revision=changed.state_revision,
    )
    assert loaded.applied_delta_count == 1
    assert loaded.state.to_dict() == changed.to_dict()
    assert loaded.state.state_revision == changed.state_revision


def test_metadata_only_unchanged_delta_is_bounded_and_idempotent(tmp_path: Path) -> None:
    state = _canonical_state(rows=20, width=16)
    delta_path = tmp_path / "state.deltas"
    segment = serialize_delta(
        state,
        state,
        metadata={"cycle": 7, "run_id": "bounded-test"},
    )
    [(manifest, _payload)], _offset, _recovered = iter_delta_segments(segment)

    assert manifest.changed_components == ()
    assert manifest.numeric_value_count == 0
    assert len(segment) < 8_192
    assert append_delta_segment(delta_path, segment) == len(segment)
    assert append_delta_segment(delta_path, segment) == 0
    assert delta_path.stat().st_size == len(segment)


def test_interrupted_final_delta_is_truncated_and_prior_segments_survive(
    tmp_path: Path,
) -> None:
    base = _canonical_state(rows=3, width=8)
    checkpoint_path = tmp_path / "state.checkpoint"
    delta_path = tmp_path / "state.deltas"
    write_checkpoint_atomic(checkpoint_path, base)
    changed = base.copy()
    changed._state_identity_tracker.restore_revision(base.state_revision)
    changed.legal_ir_view_logits["deontic"] = 0.875
    complete = serialize_delta(base, changed)
    later = changed.copy()
    later._state_identity_tracker.restore_revision(changed.state_revision)
    later.legal_ir_view_logits["kg"] = -0.25
    torn = serialize_delta(changed, later)
    delta_path.write_bytes(complete + torn[: len(torn) // 2])

    loaded = load_checkpoint(checkpoint_path, delta_path=delta_path, recover=True)

    assert loaded.applied_delta_count == 1
    assert loaded.recovered_tail_bytes == len(torn) // 2
    assert loaded.state.to_dict() == changed.to_dict()
    assert delta_path.read_bytes() == complete


def test_delta_rejects_wrong_metric_lineage_and_revision_gap(tmp_path: Path) -> None:
    base = _canonical_state(rows=2, width=4)
    checkpoint_path = tmp_path / "state.checkpoint"
    delta_path = tmp_path / "state.deltas"
    write_checkpoint_atomic(checkpoint_path, base, metric_lineage=METRIC_LINEAGE)
    changed = base.copy()
    changed._state_identity_tracker.restore_revision(base.state_revision)
    changed.legal_ir_view_logits["kg"] = 0.5
    delta_path.write_bytes(
        serialize_delta(
            base,
            changed,
            metric_lineage={"metric_schema": "wrong"},
        )
    )

    with pytest.raises(CheckpointLineageError, match="metric lineage"):
        load_checkpoint(
            checkpoint_path,
            delta_path=delta_path,
            expected_metric_lineage=METRIC_LINEAGE,
        )

    delta_path.write_bytes(
        serialize_delta(
            base,
            changed,
            metric_lineage=METRIC_LINEAGE,
            base_revision=base.state_revision + 1,
            revision=changed.state_revision + 1,
        )
    )
    with pytest.raises(CheckpointLineageError, match="revision"):
        load_checkpoint(
            checkpoint_path,
            delta_path=delta_path,
            expected_metric_lineage=METRIC_LINEAGE,
        )


def test_atomic_checkpoint_ignores_interrupted_temporary_file(tmp_path: Path) -> None:
    state = _canonical_state(rows=2, width=4)
    path = tmp_path / "state.checkpoint"
    first = write_checkpoint_atomic(path, state)
    interrupted = path.with_name(f".{path.name}.tmp-{os.getpid()}-interrupted")
    interrupted.write_bytes(b"partial-new-checkpoint")

    loaded = load_checkpoint(path)

    assert loaded.manifest.checkpoint_id == first.checkpoint_id
    assert loaded.state.to_dict() == state.to_dict()


def test_async_writer_compact_checkpoint_and_delta_round_trip(tmp_path: Path) -> None:
    base = _canonical_state(rows=5, width=8)
    changed = base.copy()
    changed._state_identity_tracker.restore_revision(base.state_revision)
    changed.family_logits["sample-00000"]["deontic"] = -0.75
    checkpoint_path = tmp_path / "state.checkpoint"
    delta_path = tmp_path / "state.deltas"
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        full_receipt = writer.write_state_checkpoint(
            checkpoint_path,
            base,
            cycle=1,
            metric_lineage=METRIC_LINEAGE,
            wait=True,
        )
        delta_receipt = writer.append_state_delta(
            delta_path,
            changed,
            base_state=base,
            cycle=2,
            metric_lineage=METRIC_LINEAGE,
            wait=True,
        )
    finally:
        writer.close(cancel_pending=True)

    assert full_receipt.metadata["compact"] is True
    assert delta_receipt.kind == "state_checkpoint_delta"
    assert checkpoint_path.read_bytes().startswith(CHECKPOINT_MAGIC)
    assert delta_path.read_bytes().startswith(DELTA_MAGIC)
    loaded = load_checkpoint(
        checkpoint_path,
        delta_path=delta_path,
        expected_metric_lineage=METRIC_LINEAGE,
    )
    assert loaded.state.to_dict() == changed.to_dict()


def test_async_compact_snapshot_is_immutable_after_enqueue(tmp_path: Path) -> None:
    state = _canonical_state(rows=2, width=4)
    expected = state.to_dict()
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        autostart=False,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        future = writer.write_state_checkpoint(
            tmp_path / "state.checkpoint",
            state,
            cycle=3,
        )
        state.decoded_embeddings["sample-00000"][0] = 99.0
        writer.start()
        future.result(timeout=2.0)
        loaded = load_checkpoint(tmp_path / "state.checkpoint")
        assert loaded.state.to_dict() == expected
    finally:
        writer.close(cancel_pending=True)


def test_complete_delta_checksum_corruption_is_not_silently_recovered() -> None:
    state = _canonical_state(rows=2, width=4)
    segment = bytearray(serialize_delta(state, state))
    segment[-1] ^= 0x01

    with pytest.raises(CheckpointCorruptionError, match="checksum"):
        iter_delta_segments(bytes(segment), recover_truncated_tail=True)


def test_manifest_is_small_and_non_executable() -> None:
    state = _canonical_state(rows=10, width=8)
    encoded = serialize_checkpoint(state)
    # The fixed header stores the manifest length immediately after magic,
    # version, and flags.  It must remain bounded independently of table rows.
    manifest_length = int.from_bytes(encoded[12:16], "big")
    manifest = json.loads(encoded[88 : 88 + manifest_length])

    assert manifest_length < 4_096
    assert manifest["compression"] == "zlib"
    assert manifest["table_schema_version"].endswith("v1")
    assert b"pickle" not in encoded[: 88 + manifest_length].lower()


_SHA = {
    name: f"sha256:{index:064x}"
    for index, name in enumerate(IR_CHECKPOINT_M1_IDENTITY_FIELDS, start=1)
}

_GOLDEN_CHECKPOINT_DIGEST = (
    "sha256:7f89cbd1d2a507940f3386e101873a005fd6d9839fc6867d9062a73c77946bc5"
)


def _semantic_manifest(
    checkpoint_id: str = "ir:checkpoint:golden-m1", **changes: object
) -> IRCheckpointManifest:
    values: dict[str, object] = {
        "checkpoint_id": checkpoint_id,
        "feature_schema_version": "formalization-features/v1",
        "state_schema_version": "modal-autoencoder-state-v1",
        **_SHA,
    }
    values.update(changes)
    return IRCheckpointManifest(**values)  # type: ignore[arg-type]


def _formalization_legacy() -> FormalizationCheckpointManifest:
    return FormalizationCheckpointManifest(
        checkpoint_id="intent:checkpoint:advisor-v1",
        domain="intent",
        head_id="intent:head:formula",
        model_id="shared:formalization-encoder",
        model_version="1",
        weights_digest=_SHA["weights_digest"],
        training_config_identity=_SHA["training_config_identity"],
        ontology_identity=_SHA["ontology_identity"],
        view_registry_identity=_SHA["view_registry_identity"],
        feature_schema_version="formalization-features/v1",
    )


def _promotion(
    candidate: str,
    baseline: str,
    *,
    decision: str = "promote",
    expected: str = "",
    loss_only: bool = False,
    self_promotion: bool = False,
    gates: tuple[str, ...] = ("lineage", "semantic", "proof", "calibration"),
) -> IRPromotionManifest:
    return IRPromotionManifest(
        promotion_id="ir:promotion:unit-1",
        candidate_checkpoint_id=candidate,
        baseline_checkpoint_id=baseline,
        expected_current_pointer=expected,
        actor_identity=_SHA["code_identity"],
        policy_identity=_SHA["campaign_identity"],
        evaluation_report_identity=_SHA["metric_lineage_digest"],
        proof_evidence_identity=_SHA["state_digest"],
        admitted_gates=gates,
        decision=decision,
        reason="unit-promotion",
        human_approval_identity=_SHA["environment_identity"],
        loss_only=loss_only,
        self_promotion=self_promotion,
    )


def _advance(store: CheckpointLifecycleStore, checkpoint_id: str, target: str) -> None:
    order = (
        "created",
        "persisted",
        "trained",
        "evaluated",
        "candidate",
        "admitted",
    )
    current = store.get(checkpoint_id).lifecycle_state
    for nxt in order[order.index(current) + 1 :]:
        store.transition(checkpoint_id, nxt, reason=f"advance-to-{nxt}")
        if nxt == target:
            return


def test_ir_checkpoint_golden_manifest_defines_every_m1_field() -> None:
    manifest = _semantic_manifest()
    encoded = manifest.to_json()
    decoded = json.loads(encoded)

    assert set(decoded) == set(IR_CHECKPOINT_M1_FIELDS)
    assert set(decoded["artifact_identities"]) == set(IR_CHECKPOINT_M1_IDENTITY_FIELDS)
    assert encoded == IRCheckpointManifest.from_json(encoded).to_json()
    assert manifest.schema_version == IR_CHECKPOINT_MANIFEST_SCHEMA
    assert decoded["schema_version"] == IR_CHECKPOINT_MANIFEST_SCHEMA
    assert manifest.authority is False
    assert manifest.digest.startswith("sha256:")
    assert manifest.cid.startswith("b")
    assert manifest.identity.digest == verify_ir_checkpoint_manifest(manifest).digest
    assert IRCheckpointManifest.from_json(encoded).digest == manifest.digest
    assert manifest.digest == _GOLDEN_CHECKPOINT_DIGEST


def test_lifecycle_transition_table_is_closed_and_complete() -> None:
    assert set(IR_CHECKPOINT_LIFECYCLE_STATES) == {
        "created",
        "persisted",
        "trained",
        "evaluated",
        "candidate",
        "admitted",
        "promoted",
        "rejected",
        "quarantined",
        "rolled_back",
        "superseded",
    }
    for current, nxt in IR_CHECKPOINT_LIFECYCLE_TRANSITIONS:
        assert allowed_lifecycle_transition(current, nxt)
    assert allowed_lifecycle_transition("promoted", "quarantined")
    assert not allowed_lifecycle_transition("created", "promoted")
    assert not allowed_lifecycle_transition("admitted", "trained")
    with pytest.raises(IRCheckpointLifecycleError, match="illegal lifecycle"):
        verify_lifecycle_transition("created", "promoted")


def test_legacy_manifests_cannot_be_aliased_as_semantic() -> None:
    formal = _formalization_legacy()
    compact = serialize_checkpoint(_canonical_state(rows=1, width=2))
    loaded = deserialize_checkpoint(compact)

    with pytest.raises(IRCheckpointValidationError, match="aliasing"):
        IRCheckpointManifest.from_dict(formal.to_dict())
    with pytest.raises(IRCheckpointValidationError, match="aliasing"):
        IRCheckpointManifest.from_dict(loaded.manifest.to_dict())
    with pytest.raises(IncompatibleManifestAliasError):
        reject_incompatible_manifest_alias({"schema_version": IR_CHECKPOINT_MANIFEST_SCHEMA})
    with pytest.raises(IRCheckpointValidationError, match="aliasing"):
        IRPromotionManifest.from_dict(
            {
                "schema_version": IR_CHECKPOINT_MANIFEST_SCHEMA,
                "promotion_id": "ir:promotion:x",
            }
        )
    assert formal.schema_version == CHECKPOINT_MANIFEST_SCHEMA_VERSION
    assert loaded.manifest.schema_version == MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION


def test_compatibility_adapters_keep_legacy_documents_separate() -> None:
    formal = _formalization_legacy()
    compact = deserialize_checkpoint(serialize_checkpoint(_canonical_state(rows=1, width=2)))
    adapted_formal = adapt_formalization_advisor_manifest(
        formal,
        identities=_SHA,
        checkpoint_id="ir:checkpoint:adapted-formal",
    )
    adapted_modal = adapt_modal_state_manifest(
        compact.manifest,
        identities=_SHA,
        checkpoint_id="ir:checkpoint:adapted-modal",
    )

    assert adapted_formal.source_kind == "adapted_formalization_advisor"
    assert adapted_formal.legacy_manifest_kind == CHECKPOINT_MANIFEST_SCHEMA_VERSION
    assert adapted_formal.legacy_manifest_digest == formal.digest
    assert adapted_formal.authority is False
    assert adapted_modal.source_kind == "adapted_modal_state"
    assert adapted_modal.legacy_manifest_kind == "modal-autoencoder-checkpoint-v1"
    assert adapted_formal.digest != formal.digest
    assert adapted_modal.digest != compact.manifest.state_digest
    assert {item.kind for item in adapted_formal.side_outcomes} == {
        "compatibility_adapter_receipt"
    }
    assert set(IR_CHECKPOINT_SIDE_OUTCOME_KINDS) >= {
        item.kind for item in adapted_modal.side_outcomes
    }


def test_store_walks_created_to_promoted_and_keeps_one_current_pointer(
    tmp_path: Path,
) -> None:
    store = CheckpointLifecycleStore(tmp_path / "lifecycle")
    baseline = store.create(_semantic_manifest("ir:checkpoint:baseline")).manifest
    candidate = store.create(_semantic_manifest("ir:checkpoint:candidate")).manifest
    _advance(store, baseline.checkpoint_id, "admitted")
    _advance(store, candidate.checkpoint_id, "admitted")
    first = store.promote(
        _promotion(baseline.checkpoint_id, candidate.checkpoint_id)
    )
    second = store.promote(
        _promotion(
            candidate.checkpoint_id,
            baseline.checkpoint_id,
            expected=baseline.checkpoint_id,
        )
    )

    assert first.manifest.lifecycle_state == "promoted"
    assert first.manifest.authority is True
    assert first.pointer is not None
    assert store.current_pointer() is not None
    assert store.current_pointer().checkpoint_id == candidate.checkpoint_id
    assert store.get(baseline.checkpoint_id).lifecycle_state == "superseded"
    assert second.pointer.fence == first.pointer.fence + 1
    assert {item.kind for item in second.outcomes} >= {
        "promotion_receipt",
        "current_pointer",
    }
    assert first.manifest.digest == store.get(baseline.checkpoint_id).digest


def test_loss_only_and_self_promotion_are_rejected(tmp_path: Path) -> None:
    store = CheckpointLifecycleStore(tmp_path / "lifecycle")
    checkpoint = store.create(_semantic_manifest("ir:checkpoint:solo")).manifest
    _advance(store, checkpoint.checkpoint_id, "admitted")

    with pytest.raises(IRCheckpointPromotionError, match="loss-only"):
        _promotion(
            checkpoint.checkpoint_id,
            "ir:checkpoint:other",
            loss_only=True,
        )
    with pytest.raises(IRCheckpointPromotionError, match="self-promotion"):
        _promotion(checkpoint.checkpoint_id, checkpoint.checkpoint_id)
    with pytest.raises(IRCheckpointPromotionError, match="promotion must go"):
        store.transition(checkpoint.checkpoint_id, "promoted", reason="self")
    other = store.create(_semantic_manifest("ir:checkpoint:other")).manifest
    _advance(store, other.checkpoint_id, "admitted")
    store.promote(_promotion(checkpoint.checkpoint_id, other.checkpoint_id))
    with pytest.raises(IRCheckpointLifecycleError, match="only an admitted"):
        store.promote(
            _promotion(
                checkpoint.checkpoint_id,
                other.checkpoint_id,
                expected=checkpoint.checkpoint_id,
            )
        )


def test_stale_cas_loses_and_torn_corrupt_stale_mismatched_are_quarantined(
    tmp_path: Path,
) -> None:
    store = CheckpointLifecycleStore(tmp_path / "lifecycle")
    first = store.create(_semantic_manifest("ir:checkpoint:alpha")).manifest
    second = store.create(_semantic_manifest("ir:checkpoint:beta")).manifest
    third = store.create(_semantic_manifest("ir:checkpoint:gamma")).manifest
    for item in (first, second, third):
        _advance(store, item.checkpoint_id, "admitted")
    store.promote(_promotion(first.checkpoint_id, second.checkpoint_id))
    with pytest.raises(IRCheckpointPromotionError, match="expected_current_pointer|stale"):
        store.promote(
            _promotion(
                second.checkpoint_id,
                first.checkpoint_id,
                expected=second.checkpoint_id,
            )
        )

    torn = store.manifests_dir / "ir_checkpoint_torn.json"
    torn.write_bytes(b'{"schema_version":"IRCheckpointManifest@1"')
    restarted = CheckpointLifecycleStore(store.root)
    restarted.restart()
    assert (store.quarantine_dir / "ir_checkpoint_torn.json").exists()
    assert not torn.exists()

    store.quarantine(third.checkpoint_id, reason="unit-mismatch", kind="mismatched")
    assert (store.quarantine_dir / "ir_checkpoint_gamma.json").exists()
    with pytest.raises(Exception):
        store.get(third.checkpoint_id)

    pointer = store.pointer_dir / "CURRENT.json"
    pointer.write_text("{not-json", encoding="utf-8")
    result = CheckpointLifecycleStore(store.root).restart()
    assert result is not None and result.quarantined is True
    assert store.current_pointer() is None

    live = store.create(_semantic_manifest("ir:checkpoint:delta")).manifest
    _advance(store, live.checkpoint_id, "admitted")
    store.promote(_promotion(live.checkpoint_id, first.checkpoint_id))
    payload = json.loads(store.pointer_dir.joinpath("CURRENT.json").read_text(encoding="utf-8"))
    payload["artifact_digest"] = _SHA["state_digest"]
    store.pointer_dir.joinpath("CURRENT.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    assert CheckpointLifecycleStore(store.root).restart() is None
    assert store.current_pointer() is None


def test_restart_preserves_promoted_pointer_and_quarantines_only_torn(
    tmp_path: Path,
) -> None:
    store = CheckpointLifecycleStore(tmp_path / "lifecycle")
    first = store.create(_semantic_manifest("ir:checkpoint:keep")).manifest
    second = store.create(_semantic_manifest("ir:checkpoint:other")).manifest
    _advance(store, first.checkpoint_id, "admitted")
    _advance(store, second.checkpoint_id, "admitted")
    store.promote(_promotion(first.checkpoint_id, second.checkpoint_id))
    torn = store.manifests_dir / "ir_checkpoint_torn.json"
    torn.write_bytes(b'{"schema_version":"IRCheckpointManifest@1"')

    result = CheckpointLifecycleStore(store.root).restart()

    assert result is not None
    assert result.quarantined is False
    assert result.pointer is not None
    assert result.pointer.checkpoint_id == first.checkpoint_id
    assert store.get(first.checkpoint_id).lifecycle_state == "promoted"
    assert store.current_pointer().checkpoint_id == first.checkpoint_id
    assert (store.quarantine_dir / "ir_checkpoint_torn.json").exists()
    assert not torn.exists()


def test_restart_discards_torn_tmp_and_refuses_ambiguous_current_pointer(
    tmp_path: Path,
) -> None:
    store = CheckpointLifecycleStore(tmp_path / "lifecycle")
    first = store.create(_semantic_manifest("ir:checkpoint:one")).manifest
    second = store.create(_semantic_manifest("ir:checkpoint:two")).manifest
    _advance(store, first.checkpoint_id, "admitted")
    _advance(store, second.checkpoint_id, "admitted")
    store.promote(_promotion(first.checkpoint_id, second.checkpoint_id))
    leftover = store.pointer_dir / ".CURRENT.json.tmp-1-interrupted"
    leftover.write_bytes(b"partial-pointer")
    store.pointer_dir.joinpath("CURRENT.json.alt").write_text(
        store.pointer_dir.joinpath("CURRENT.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(AmbiguousCurrentPointerError, match="ambiguous"):
        CheckpointLifecycleStore(store.root).restart()
    assert not leftover.exists()
    assert list(store.pointer_dir.glob("CURRENT*")) == []


def test_reject_and_rollback_are_recorded_side_outcomes(tmp_path: Path) -> None:
    store = CheckpointLifecycleStore(tmp_path / "lifecycle")
    baseline = store.create(_semantic_manifest("ir:checkpoint:base")).manifest
    winner = store.create(_semantic_manifest("ir:checkpoint:win")).manifest
    loser = store.create(_semantic_manifest("ir:checkpoint:lose")).manifest
    for item in (baseline, winner, loser):
        _advance(store, item.checkpoint_id, "admitted")
    store.promote(_promotion(baseline.checkpoint_id, winner.checkpoint_id))
    store.promote(
        _promotion(
            winner.checkpoint_id,
            baseline.checkpoint_id,
            expected=baseline.checkpoint_id,
        )
    )
    rejected = store.reject(
        _promotion(
            loser.checkpoint_id,
            winner.checkpoint_id,
            decision="reject",
        )
    )
    rolled = store.rollback(
        expected_current=winner.checkpoint_id,
        prior_checkpoint_id=baseline.checkpoint_id,
        reason="operator-rollback",
    )

    assert rejected.manifest.lifecycle_state == "rejected"
    assert rejected.manifest.authority is False
    assert store.get(winner.checkpoint_id).lifecycle_state == "rolled_back"
    assert rolled.manifest.checkpoint_id == baseline.checkpoint_id
    assert rolled.manifest.lifecycle_state == "promoted"
    assert store.current_pointer().checkpoint_id == baseline.checkpoint_id
    assert any(item.kind == "rejection_receipt" for item in rejected.outcomes)
    assert any(item.kind == "rollback_receipt" for item in rolled.outcomes)


def test_exclusive_keys_and_incomplete_identities_fail_closed(tmp_path: Path) -> None:
    store = CheckpointLifecycleStore(tmp_path / "lifecycle")
    assert CHECKPOINT_WRITE_KEY == "checkpoint-write"
    assert PROMOTION_KEY == "promotion"
    with store.exclusive_key(CHECKPOINT_WRITE_KEY):
        with store.exclusive_key(PROMOTION_KEY):
            assert store.current_pointer() is None
    incomplete = dict(_SHA)
    incomplete["tokenizer_identity"] = ""
    with pytest.raises(FormalizationValidationError, match="tokenizer_identity"):
        IRCheckpointManifest(
            checkpoint_id="ir:checkpoint:incomplete",
            feature_schema_version="formalization-features/v1",
            state_schema_version="modal-autoencoder-state-v1",
            **incomplete,
        )
    created = _semantic_manifest("ir:checkpoint:authority-created")
    with pytest.raises(IRCheckpointValidationError, match="authority"):
        validate_ir_checkpoint_manifest(
            {**created.to_dict(), "authority": True, "lifecycle_state": "created"}
        )
    with pytest.raises(CheckpointQuarantineError, match="unsupported quarantine"):
        store.quarantine("ir:checkpoint:missing", reason="nope", kind="loss")


def test_side_outcome_kinds_are_closed_and_subject_bound() -> None:
    with pytest.raises(FormalizationValidationError, match="one of"):
        IRCheckpointSideOutcome(
            kind="self_promotion",
            subject_checkpoint_id="ir:checkpoint:golden-m1",
            reason="illegal",
        )
    outcome = IRCheckpointSideOutcome(
        kind="recovery_receipt",
        subject_checkpoint_id="ir:checkpoint:golden-m1",
        reason="restart-recovered-torn-tail",
    )
    assert outcome.digest.startswith("sha256:")
    with pytest.raises(IRCheckpointValidationError, match="subject must match"):
        _semantic_manifest(
            side_outcomes=(
                IRCheckpointSideOutcome(
                    kind="recovery_receipt",
                    subject_checkpoint_id="ir:checkpoint:other",
                    reason="mismatch",
                ),
            )
        )
