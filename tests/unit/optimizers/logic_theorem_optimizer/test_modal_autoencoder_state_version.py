"""Regression tests for mutation-tracked modal-autoencoder state identity."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_version import (
    StaleStateResultError,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.snapshot_evaluator import (
    EvaluationSnapshot,
    SnapshotEvaluator,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION,
    autoencoder_canonical_state_hash,
    build_autoencoder_evaluation_snapshot,
    matching_snapshot_versions,
)


METRIC_LINEAGE = {
    "metric_schema": AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION,
    "metric_suite": "all-legal-ir-families-v1",
}


def _persisted_state_fields() -> tuple[str, ...]:
    """Return every mutable dataclass field represented in a checkpoint."""

    state = ModalAutoencoderTrainingState()
    return tuple(
        sorted(name for name in state.to_dict() if hasattr(state, name))
    )


PERSISTED_STATE_FIELDS = _persisted_state_fields()


def _populated_state() -> ModalAutoencoderTrainingState:
    """Build one state with a mutable value in every persisted component."""

    state = ModalAutoencoderTrainingState()
    for name in PERSISTED_STATE_FIELDS:
        if name == "architecture_version":
            continue
        if name == "proof_feedback_version_fingerprint":
            setattr(state, name, "proof-toolchain-a")
        elif name == "proof_auxiliary_head_logits":
            setattr(
                state,
                name,
                {"obligation_family": {"__global__": {"label-a": 0.125}}},
            )
        elif name.startswith("applied_") and name.endswith("_ids"):
            setattr(state, name, [f"{name}-a"])
        elif name == "legal_ir_view_logits":
            setattr(state, name, {"deontic": 0.125})
        elif name == "decoded_embeddings" or name.endswith(
            "embedding_weights"
        ):
            setattr(state, name, {"key-a": [0.125, -0.25]})
        elif name.endswith("logits"):
            setattr(state, name, {"key-a": {"label-a": 0.125}})
        else:  # pragma: no cover - protects this fixture as state evolves
            raise AssertionError(f"unclassified persisted state field: {name}")
    return state


def _mutate_persisted_field(
    state: ModalAutoencoderTrainingState,
    name: str,
) -> None:
    value = getattr(state, name)
    if name == "architecture_version":
        setattr(state, name, MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION)
    elif name == "proof_feedback_version_fingerprint":
        setattr(state, name, "proof-toolchain-b")
    elif name.startswith("applied_") and name.endswith("_ids"):
        value.append(f"{name}-b")
    elif name == "proof_auxiliary_head_logits":
        value["obligation_family"]["__global__"]["label-a"] = 0.875
    elif name == "legal_ir_view_logits":
        value["deontic"] = 0.875
    elif name == "decoded_embeddings" or name.endswith("embedding_weights"):
        value["key-a"][0] = 0.875
    elif name.endswith("logits"):
        value["key-a"]["label-a"] = 0.875
    else:  # pragma: no cover - protects this fixture as state evolves
        raise AssertionError(f"unclassified persisted state field: {name}")


def _component_compute_counts(stats: Mapping[str, Any]) -> Mapping[str, int]:
    """Read the public per-component diagnostics with a useful failure."""

    counts = stats.get("component_digest_compute_counts")
    assert isinstance(counts, Mapping), stats
    return {str(name): int(count) for name, count in counts.items()}


def test_identity_is_deterministic_and_stable_across_save_reload(
    tmp_path: Path,
) -> None:
    first = _populated_state()
    second = ModalAutoencoderTrainingState.from_dict(first.to_dict())

    # Reinsert representative mappings in a different order.  Identity must be
    # based on canonical values, not Python insertion history.
    second.feature_embedding_weights = {
        "z": [3.0, 4.0],
        "a": [1.0, 2.0],
        **second.feature_embedding_weights,
    }
    first.feature_embedding_weights["a"] = [1.0, 2.0]
    first.feature_embedding_weights["z"] = [3.0, 4.0]

    first_identity = first.state_identity(metric_lineage=METRIC_LINEAGE)
    assert second.state_identity(metric_lineage=METRIC_LINEAGE) == first_identity
    assert second.component_digests == first.component_digests

    path = tmp_path / "state.json"
    first.save_json(path)
    restored = ModalAutoencoderTrainingState.load_json(path)

    assert restored.state_identity(metric_lineage=METRIC_LINEAGE) == first_identity
    assert restored.component_digests == first.component_digests


def test_unchanged_identity_is_constant_time_after_warmup_and_only_touched_component_rehashes() -> None:
    state = _populated_state()
    before_identity = state.state_identity(metric_lineage=METRIC_LINEAGE)
    before_revision = state.state_revision
    before_digests = dict(state.component_digests)
    before_stats = dict(state.identity_stats)
    before_counts = _component_compute_counts(before_stats)

    for _ in range(50):
        assert state.state_identity(metric_lineage=METRIC_LINEAGE) == before_identity
        assert state.component_digests == before_digests

    warm_stats = dict(state.identity_stats)
    assert warm_stats["component_digest_compute_count"] == before_stats[
        "component_digest_compute_count"
    ]
    assert _component_compute_counts(warm_stats) == before_counts

    state.feature_embedding_weights["key-a"][0] = 0.875
    assert state.state_revision == before_revision + 1
    after_identity = state.state_identity(metric_lineage=METRIC_LINEAGE)
    after_digests = dict(state.component_digests)
    after_stats = dict(state.identity_stats)
    after_counts = _component_compute_counts(after_stats)

    assert after_identity != before_identity
    assert {
        name for name in after_digests if after_digests[name] != before_digests[name]
    } == {"feature_embedding_weights"}
    assert after_stats["component_digest_compute_count"] == (
        before_stats["component_digest_compute_count"] + 1
    )
    assert after_counts["feature_embedding_weights"] == (
        before_counts["feature_embedding_weights"] + 1
    )
    assert {
        name
        for name in after_counts
        if after_counts[name] != before_counts.get(name, 0)
    } == {"feature_embedding_weights"}


@pytest.mark.parametrize("field_name", PERSISTED_STATE_FIELDS)
def test_every_persisted_parameter_mutation_invalidates_identity(
    field_name: str,
) -> None:
    state = _populated_state()
    before_identity = state.state_identity(metric_lineage=METRIC_LINEAGE)
    before_revision = state.state_revision
    before_digests = dict(state.component_digests)

    _mutate_persisted_field(state, field_name)

    assert state.state_revision > before_revision
    assert state.state_identity(metric_lineage=METRIC_LINEAGE) != before_identity
    assert dict(state.component_digests) != before_digests


def test_identity_binds_architecture_and_canonical_metric_lineage() -> None:
    state = _populated_state()
    lineage_a = {
        "metric_schema": "legal-ir-metrics-v1",
        "families": ["deontic", "kg"],
    }
    lineage_a_reordered = {
        "families": ["deontic", "kg"],
        "metric_schema": "legal-ir-metrics-v1",
    }
    lineage_b = {**lineage_a, "metric_schema": "legal-ir-metrics-v2"}

    identity_a = state.state_identity(metric_lineage=lineage_a)
    assert state.state_identity(metric_lineage=lineage_a_reordered) == identity_a
    assert state.state_identity(metric_lineage=lineage_b) != identity_a

    state.architecture_version = MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION
    assert state.state_identity(metric_lineage=lineage_a) != identity_a


def test_identity_binds_state_and_proof_schema_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _populated_state().state_identity(metric_lineage=METRIC_LINEAGE)

    monkeypatch.setattr(
        modal_autoencoder,
        "MODAL_AUTOENCODER_STATE_SCHEMA_VERSION",
        "modal-autoencoder-state-schema-test-next",
    )
    state_schema_changed = _populated_state().state_identity(
        metric_lineage=METRIC_LINEAGE
    )
    assert state_schema_changed != original

    monkeypatch.setattr(
        modal_autoencoder,
        "PROOF_AUXILIARY_HEAD_SCHEMA_VERSION",
        "proof-auxiliary-head-schema-test-next",
    )
    proof_schema_changed = _populated_state().state_identity(
        metric_lineage=METRIC_LINEAGE
    )
    assert proof_schema_changed != state_schema_changed


def test_copied_state_rebinds_nested_mutation_callbacks() -> None:
    original = _populated_state()
    copied = original.copy()
    original_identity = original.state_identity(metric_lineage=METRIC_LINEAGE)
    copied_identity = copied.state_identity(metric_lineage=METRIC_LINEAGE)
    assert copied_identity == original_identity

    copied.feature_embedding_weights["key-a"][0] = 0.875

    assert copied.state_identity(metric_lineage=METRIC_LINEAGE) != copied_identity
    assert original.state_identity(metric_lineage=METRIC_LINEAGE) == original_identity


def test_hot_lineage_identity_and_revision_guards_do_not_serialize_full_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _populated_state()
    expected = state.state_identity(
        metric_lineage=AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION
    )

    def fail_to_json(_self: ModalAutoencoderTrainingState) -> str:
        raise AssertionError("hot state lineage check called state.to_json()")

    monkeypatch.setattr(ModalAutoencoderTrainingState, "to_json", fail_to_json)

    assert autoencoder_canonical_state_hash(state) == expected
    versions = matching_snapshot_versions(
        state,
        compiler_version="compiler-a",
        holdout_sample_ids=("holdout-a",),
        validation_mode="fixed",
    )
    assert versions.state_version == expected
    token = state.state_revision_token(metric_lineage=METRIC_LINEAGE)
    assert state.is_current_state_revision(token) is True
    state.require_current_state_revision(token)


def test_revision_tokens_reject_stale_asynchronous_results() -> None:
    state = _populated_state()
    token = state.state_revision_token(metric_lineage=METRIC_LINEAGE)

    assert state.is_current_state_revision(token) is True
    state.legal_ir_view_logits["deontic"] = 0.875

    assert state.is_current_state_revision(token) is False
    with pytest.raises(StaleStateResultError, match="stale"):
        state.require_current_state_revision(token)


def test_snapshot_payload_checksum_is_independent_from_incremental_state_version() -> None:
    state = _populated_state()
    payload = state.to_json()
    version_a = state.state_identity(metric_lineage="metric-lineage-a")
    version_b = state.state_identity(metric_lineage="metric-lineage-b")

    snapshot_a = EvaluationSnapshot.from_state_json(
        payload,
        sequence=1,
        compiler_version="compiler-a",
        holdout_version="holdout-a",
        state_version=version_a,
    )
    snapshot_b = EvaluationSnapshot.from_state_json(
        payload,
        sequence=1,
        compiler_version="compiler-a",
        holdout_version="holdout-a",
        state_version=version_b,
    )

    assert snapshot_a.payload_digest == hashlib.sha256(payload.encode()).hexdigest()
    assert snapshot_b.payload_digest == snapshot_a.payload_digest
    assert snapshot_a.versions.state_version == version_a
    assert snapshot_b.versions.state_version == version_b
    assert version_a != version_b

    with pytest.raises(ValueError, match="payload_digest"):
        replace(snapshot_a, state_payload=b"{}")


def test_snapshot_evaluator_rejects_result_after_trainer_revision_changes() -> None:
    state = _populated_state()
    snapshot = build_autoencoder_evaluation_snapshot(
        state,
        sequence=7,
        compiler_version="compiler-a",
        holdout_sample_ids=("holdout-a",),
        validation_mode="fixed",
    )
    evaluator = SnapshotEvaluator(lambda _snapshot: {"loss": 0.125})
    try:
        evaluator.publish(snapshot)
        result = evaluator.wait_for_result(timeout=2.0)
        assert result is not None

        state.feature_family_logits["key-a"]["label-a"] = 0.875
        current_versions = matching_snapshot_versions(
            state,
            compiler_version="compiler-a",
            holdout_sample_ids=("holdout-a",),
            validation_mode="fixed",
        )

        assert current_versions.state_version != snapshot.versions.state_version
        assert evaluator.accept_result(
            result,
            current_versions,
            expected_sequence=snapshot.sequence,
        ) is False
        summary = evaluator.summary()
        assert summary["rejected_result_count"] == 1
    finally:
        evaluator.close(cancel_pending=True)
