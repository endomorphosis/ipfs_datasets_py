from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_feature_inventory import (
    CANONICAL_ACCEPTED_ROW_COUNT,
    CANONICAL_ACCEPTED_STATE_SHA256,
    CANONICAL_EVALUATION_CANARY_SHA256,
    CANONICAL_EXACT_ROW_COUNT,
    CANONICAL_LEGACY_ROW_COUNT,
    CANONICAL_LEGACY_STATE_SHA256,
    CANONICAL_OMITTED_ROW_COUNT,
    CANONICAL_OVERRIDDEN_ROW_COUNT,
    CANONICAL_TRANSFER_REPORT_SHA256,
    LegacyFeatureInventoryError,
    LegacyFeatureInventoryPolicy,
    _load_state,
    build_legacy_feature_inventory,
    content_sha256,
    verify_inventory_digest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_feature_transfer import (
    MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION,
)


_HASHES = {
    "accepted_state": "sha256:" + "a" * 64,
    "evaluation_canary": "sha256:" + "c" * 64,
    "legacy_state": "sha256:" + "b" * 64,
    "transfer_report": "sha256:" + "d" * 64,
}
_TARGET_HASH = "sha256:" + "e" * 64


def _embedded(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result["report_sha256"] = content_sha256(result)
    return result


def _report(*, old_rows: int, new_rows: int) -> dict[str, Any]:
    group_reports = {}
    for group, fields in MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS.items():
        group_reports[group] = {
            "capacity": 32_768,
            "fields": list(fields),
            "imported_source_field_entries": 0,
            "incompatible_shared_rows": 0,
            "output_unique_keys": 0,
            "shared_field_entries_preserved_from_target": 0,
            "source_signal": 0.0,
            "source_signal_coverage": 1.0,
            "source_signal_retained": 0.0,
            "source_unique_keys": 0,
            "source_unique_keys_retained": 0,
            "source_unique_keys_total_including_deferred_embeddings": 0,
            "target_signal": 0.0,
            "target_signal_coverage": 1.0,
            "target_unique_keys": 0,
            "target_unique_keys_retained": 0,
        }
    report = {
        "accepted": True,
        "architecture": {
            "output": "proof_aware_auxiliary_heads_v2",
            "source_declared": "legacy_dense_v1",
            "source_loaded": "proof_aware_auxiliary_heads_v2",
            "target": "proof_aware_auxiliary_heads_v2",
        },
        "artifacts": {
            "legacy_state": {
                "path": "/not/serialized/legacy",
                "sha256": _HASHES["legacy_state"],
            },
            "output_state": {
                "bytes": 1,
                "checkpoint_id": "checkpoint",
                "path": "/not/serialized/accepted",
                "sha256": _HASHES["accepted_state"],
                "state_digest": "state-digest",
            },
            "target_state": {
                "path": "/not/serialized/target",
                "sha256": _TARGET_HASH,
            },
        },
        "capacity": 32_768,
        "deferred_components": {},
        "group_reports": group_reports,
        "imported_source_field_entries": 0,
        "incompatible_shared_rows_preserved_from_target": 0,
        "minimum_source_signal_coverage": 0.0,
        "output_generalizable_entry_count": new_rows,
        "policy": "target_exact_source_fill_v2",
        "required_runtime": {},
        "schema_version": MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION,
        "selection_lineage": {
            "candidate_id": "candidate",
            "params": {},
            "primary_seed": 1,
            "selection_embedded_sha256": "sha256:" + "1" * 64,
            "selection_file_sha256": "sha256:" + "2" * 64,
            "selection_path": "/not/serialized/selection",
            "target_state_sha256": _TARGET_HASH,
            "training_revision": "revision",
        },
        "shared_field_entries_preserved_from_target": 0,
        "source_embedding_transfer_enabled": False,
        "source_field_allowlist": [],
        "source_generalizable_entry_count": old_rows,
        "source_signal": 0.0,
        "source_signal_coverage": 1.0,
        "source_signal_retained": 0.0,
        "source_unique_keys": 0,
        "source_unique_keys_retained": 0,
        "target_generalizable_entry_count": new_rows,
        "target_preservation_failure_count": 0,
        "target_preservation_failures": [],
        "target_preserved": True,
        "target_unique_keys": 0,
    }
    return _embedded(report)


def _canary(report: dict[str, Any]) -> dict[str, Any]:
    metrics = {
        "autoencoder_cosine_similarity": 0.8,
        "autoencoder_cross_entropy_loss": 1.0,
        "ir_view_cosine_similarity": 0.7,
        "ir_view_cross_entropy_loss": 1.1,
    }
    evaluation = {
        "compute_backend": "torch_cuda",
        "compute_device": "cuda",
        "elapsed_seconds": 1.0,
        "metrics": metrics,
    }
    return _embedded(
        {
            "artifacts": {
                "candidate": {
                    "path": "/not/serialized/accepted",
                    "sha256": _HASHES["accepted_state"],
                },
                "target": {
                    "path": "/not/serialized/target",
                    "sha256": _TARGET_HASH,
                },
                "teacher": {
                    "path": "/not/serialized/legacy",
                    "sha256": _HASHES["legacy_state"],
                },
            },
            "bridge_names": ["modal_frame_logic"],
            "candidate_teacher_fidelity": {},
            "dataset_load_seconds": 1.0,
            "decision": "passed",
            "evaluations": {
                "candidate": evaluation,
                "target": evaluation,
                "teacher": evaluation,
            },
            "gate": {
                "accepted": True,
                "checks": {"cuda_verified": True},
                "fidelity_deltas": {},
                "metric_deltas": {},
                "tolerances": {},
            },
            "schema_version": "modal-autoencoder-feature-transfer-canary-v1",
            "target_build_seconds": 1.0,
            "target_teacher_fidelity": {},
            "transfer_report": {
                "embedded_sha256": report["report_sha256"],
                "file_sha256": _HASHES["transfer_report"],
                "path": "/not/serialized/report",
            },
            "validation_canary_indices": [1],
        }
    )


def _policy(
    *,
    old_rows: int,
    new_rows: int,
    exact_rows: int,
    overridden_rows: int,
) -> LegacyFeatureInventoryPolicy:
    return LegacyFeatureInventoryPolicy(
        require_canonical_artifacts=False,
        legacy_state_sha256=_HASHES["legacy_state"],
        accepted_state_sha256=_HASHES["accepted_state"],
        transfer_report_sha256=_HASHES["transfer_report"],
        evaluation_canary_sha256=_HASHES["evaluation_canary"],
        legacy_row_count=old_rows,
        accepted_row_count=new_rows,
        exact_row_count=exact_rows,
        overridden_row_count=overridden_rows,
        omitted_row_count=old_rows - new_rows,
    )


def _build(
    old: ModalAutoencoderTrainingState,
    new: ModalAutoencoderTrainingState,
) -> dict[str, Any]:
    old_rows = old.generalizable_entry_count()
    new_rows = new.generalizable_entry_count()
    report = _report(old_rows=old_rows, new_rows=new_rows)
    return build_legacy_feature_inventory(
        old,
        new,
        report,
        _canary(report),
        artifact_bindings=_HASHES,
        policy=_policy(
            old_rows=old_rows,
            new_rows=new_rows,
            exact_rows=max(0, new_rows - 1),
            overridden_rows=min(1, new_rows),
        ),
    )


def test_inventory_is_deterministic_content_addressed_and_source_free() -> None:
    old = ModalAutoencoderTrainingState(
        decoded_embeddings={"SECRET-SAMPLE": [99.0]},
        family_logits={"SECRET-SAMPLE": {"deontic": 99.0}},
        feature_family_logits={
            "SECRET-EXACT": {"deontic": 3.0, "frame": -2.0},
            "SECRET-OMITTED": {"deontic": 0.0},
        },
        legal_ir_view_logits={"SECRET-OVERRIDE": 2.0},
    )
    new = ModalAutoencoderTrainingState(
        feature_family_logits={
            "SECRET-EXACT": {"frame": -2.0, "deontic": 3.0},
        },
        legal_ir_view_logits={"SECRET-OVERRIDE": 1.0},
    )

    first = _build(old, new)
    second = _build(old, new)

    assert first == second
    assert verify_inventory_digest(first) == first["inventory_sha256"]
    serialized = first.__repr__()
    for secret in ("SECRET-SAMPLE", "SECRET-EXACT", "SECRET-OMITTED", "SECRET-OVERRIDE"):
        assert secret not in serialized
    assert first["privacy"]["source_samples_serialized"] is False
    assert first["privacy"]["tensor_rows_serialized"] is False
    assert first["trust_boundary"]["eligible_as_automatic_training_labels"] is False


def test_inventory_reconciles_dispositions_and_signed_signal() -> None:
    old = ModalAutoencoderTrainingState(
        feature_family_logits={
            "exact": {"a": 3.0, "b": -2.0},
            "omitted": {"a": 0.0, "b": -4.0},
        },
        legal_ir_view_logits={"override": 2.0},
    )
    new = ModalAutoencoderTrainingState(
        feature_family_logits={"exact": {"a": 3.0, "b": -2.0}},
        legal_ir_view_logits={"override": -1.0},
    )

    inventory = _build(old, new)

    assert inventory["row_counts"] == {
        "accepted_rows": 2,
        "legacy_rows": 3,
        "omitted": 1,
        "overridden": 1,
        "remapped": 0,
        "transferable_exact": 1,
    }
    feature = next(group for group in inventory["groups"] if group["group"] == "feature")
    omitted = feature["dispositions"]["omitted"]
    assert omitted["row_count"] == 1
    assert omitted["signed_signal_mass"] == -4.0
    assert omitted["absolute_signal_mass"] == 4.0
    assert omitted["activation_frequency"] == 1.0
    assert omitted["value_activation_frequency"] == 0.5
    assert sum(
        value["row_count"]
        for value in inventory["omitted_by_semantic_family"].values()
    ) == 1


def test_inventory_covers_every_capacity_field_exactly_once() -> None:
    report = _report(old_rows=0, new_rows=0)
    inventory = build_legacy_feature_inventory(
        ModalAutoencoderTrainingState(),
        ModalAutoencoderTrainingState(),
        report,
        _canary(report),
        artifact_bindings=_HASHES,
        policy=_policy(
            old_rows=0,
            new_rows=0,
            exact_rows=0,
            overridden_rows=0,
        ),
    )
    observed = [
        field["field"]
        for group in inventory["groups"]
        for field in group["fields"]
    ]
    expected = [
        field
        for fields in MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS.values()
        for field in fields
    ]
    assert sorted(observed) == sorted(expected)
    assert len(observed) == len(set(observed))


def test_inventory_fails_closed_on_unknown_report_fields() -> None:
    report = _report(old_rows=0, new_rows=0)
    report["unknown_payload"] = {"prompt": "must not pass"}
    report["report_sha256"] = content_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    with pytest.raises(LegacyFeatureInventoryError, match="unknown transfer report"):
        build_legacy_feature_inventory(
            ModalAutoencoderTrainingState(),
            ModalAutoencoderTrainingState(),
            report,
            _canary(report),
            artifact_bindings=_HASHES,
            policy=_policy(
                old_rows=0,
                new_rows=0,
                exact_rows=0,
                overridden_rows=0,
            ),
        )


def test_inventory_fails_closed_on_incompatible_dimensions_and_nonfinite_values() -> None:
    report = _report(old_rows=1, new_rows=1)
    canary = _canary(report)
    policy = _policy(
        old_rows=1,
        new_rows=1,
        exact_rows=0,
        overridden_rows=1,
    )
    with pytest.raises(LegacyFeatureInventoryError, match="incompatible"):
        build_legacy_feature_inventory(
            ModalAutoencoderTrainingState(
                feature_embedding_weights={"shared": [1.0, 2.0]}
            ),
            ModalAutoencoderTrainingState(
                feature_embedding_weights={"shared": [1.0]}
            ),
            report,
            canary,
            artifact_bindings=_HASHES,
            policy=policy,
        )

    with pytest.raises(LegacyFeatureInventoryError, match="finite"):
        build_legacy_feature_inventory(
            ModalAutoencoderTrainingState(
                feature_family_logits={"shared": {"deontic": float("nan")}}
            ),
            ModalAutoencoderTrainingState(
                feature_family_logits={"shared": {"deontic": float("nan")}}
            ),
            report,
            canary,
            artifact_bindings=_HASHES,
            policy=policy,
        )


def test_state_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('{"unknown_tensor_group": {}}', encoding="utf-8")

    with pytest.raises(LegacyFeatureInventoryError, match="unknown state fields"):
        _load_state(state_path)


def test_real_lineage_constants_are_immutable() -> None:
    assert CANONICAL_LEGACY_STATE_SHA256.endswith(
        "7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be"
    )
    assert CANONICAL_ACCEPTED_STATE_SHA256.endswith(
        "1c615f7c622b46e1a3d7349b436bf5daefc3e26866e9458c0feacfe545bcb033"
    )
    assert CANONICAL_TRANSFER_REPORT_SHA256.endswith(
        "5d6da2dca0c2ad5c74c16d9c47eee2fc43b18aabe5e53a6c1f55e3f6a14995e2"
    )
    assert CANONICAL_EVALUATION_CANARY_SHA256.endswith(
        "a71a67bf14b5740f9b52ef7ac3859b436df6406d4b60f0fc13e0e1e2125c2bb5"
    )
    assert CANONICAL_LEGACY_ROW_COUNT == 1_205_336
    assert CANONICAL_ACCEPTED_ROW_COUNT == 209_759
    assert CANONICAL_EXACT_ROW_COUNT == 209_753
    assert CANONICAL_OVERRIDDEN_ROW_COUNT == 6
    assert CANONICAL_OMITTED_ROW_COUNT == 995_577
    assert CANONICAL_EXACT_ROW_COUNT + CANONICAL_OVERRIDDEN_ROW_COUNT == (
        CANONICAL_ACCEPTED_ROW_COUNT
    )
    assert CANONICAL_ACCEPTED_ROW_COUNT + CANONICAL_OMITTED_ROW_COUNT == (
        CANONICAL_LEGACY_ROW_COUNT
    )
