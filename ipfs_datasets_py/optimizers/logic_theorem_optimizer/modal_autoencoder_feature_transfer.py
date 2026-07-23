"""Compatibility-aware transfer of legacy modal-autoencoder features.

The proof-aware v2 architecture retains the sparse embedding, family, and
LegalIR-view heads from ``legacy_dense_v1``.  Those rows can be transferred
directly.  Sample memory cannot be transferred without leaking prior examples,
and proof auxiliary heads require versioned Hammer feedback rather than
pseudo-labels inferred from legacy logits.

This module therefore uses a target-preserving, source-fill policy:

* every row already present in the v2 target is retained byte-for-value;
* unused capacity is filled with the strongest legacy-only semantic keys;
* coupled encoder/decoder maps use one shared key selection per head group;
* proof heads and sample memory are never synthesized from legacy state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence

from .modal_autoencoder import (
    MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS,
    MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS,
    MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
    ModalAutoencoderTrainingState,
)


MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION = (
    "modal-autoencoder-feature-transfer-v2"
)
DEFAULT_LEGACY_FEATURE_TRANSFER_CAPACITY = 32768
LEGACY_FEATURE_TRANSFER_FIELDS = frozenset(
    field_name
    for fields in MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS.values()
    for field_name in fields
)


@dataclass(frozen=True, slots=True)
class LegacyFeatureTransferConfig:
    """Fail-closed capacity and fidelity policy for one feature transfer."""

    max_entries_per_group: int = DEFAULT_LEGACY_FEATURE_TRANSFER_CAPACITY
    minimum_source_signal_coverage: float = 0.95
    require_target_preservation: bool = True
    transfer_source_embedding_weights: bool = False
    source_field_allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if int(self.max_entries_per_group) < 1:
            raise ValueError("max_entries_per_group must be positive")
        coverage = float(self.minimum_source_signal_coverage)
        if not math.isfinite(coverage) or not 0.0 <= coverage <= 1.0:
            raise ValueError(
                "minimum_source_signal_coverage must be finite and between 0 and 1"
            )
        unknown_fields = set(self.source_field_allowlist) - (
            LEGACY_FEATURE_TRANSFER_FIELDS
        )
        if unknown_fields:
            raise ValueError(
                "unknown source transfer fields: "
                + ", ".join(sorted(unknown_fields))
            )


@dataclass(frozen=True, slots=True)
class LegacyFeatureTransferResult:
    """Transferred state plus deterministic acceptance evidence."""

    state: ModalAutoencoderTrainingState
    report: Mapping[str, Any]

    @property
    def accepted(self) -> bool:
        return bool(self.report.get("accepted"))


def _signal(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return abs(number) if math.isfinite(number) else 0.0
    if isinstance(value, Mapping):
        return sum(_signal(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return sum(_signal(item) for item in value)
    return 0.0


def _copy_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _copy_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_copy_value(item) for item in value]
    return value


def _protected_key(value: Any) -> bool:
    text = str(value).strip().lower()
    return (
        text in {"__global__", "global", "bias"}
        or text.endswith(":bias")
        or text.endswith("|bias")
    )


def _ordered_keys(keys: set[Any], scores: Mapping[Any, float]) -> list[Any]:
    return sorted(
        keys,
        key=lambda key: (
            0 if _protected_key(key) else 1,
            -float(scores.get(key, 0.0)),
            str(key),
        ),
    )


def _row_shape(value: Any) -> tuple[str, int]:
    if isinstance(value, Mapping):
        return ("mapping", len(value))
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return ("sequence", len(value))
    return (type(value).__name__, 1)


def _source_architecture(value: str | None) -> str:
    architecture = str(
        value or MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION
    ).strip()
    if architecture not in MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS:
        raise ValueError(
            f"unsupported source autoencoder architecture: {architecture!r}"
        )
    return architecture


def _source_field_is_transferable(
    field_name: str,
    policy: LegacyFeatureTransferConfig,
) -> bool:
    if (
        policy.source_field_allowlist
        and field_name not in policy.source_field_allowlist
    ):
        return False
    if field_name.endswith("_embedding_weights"):
        return policy.transfer_source_embedding_weights
    return True


def transfer_legacy_autoencoder_features(
    source: ModalAutoencoderTrainingState,
    target: ModalAutoencoderTrainingState,
    *,
    config: LegacyFeatureTransferConfig | None = None,
    source_architecture_version: str | None = None,
) -> LegacyFeatureTransferResult:
    """Port compatible legacy rows into a proof-aware target state.

    Target rows always win when a field/key pair exists in both states.  This
    preserves all accepted current learning while allowing legacy-only rows to
    fill the explicit capacity budget.
    """

    policy = config or LegacyFeatureTransferConfig()
    capacity = int(policy.max_entries_per_group)
    declared_source_architecture = _source_architecture(
        source_architecture_version or source.architecture_version
    )
    if target.architecture_version not in (
        MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS
    ):
        raise ValueError(
            "unsupported target autoencoder architecture: "
            f"{target.architecture_version!r}"
        )

    source_generalizable = source.generalizable_copy()
    target_generalizable = target.generalizable_copy()
    candidate = target_generalizable.generalizable_copy()
    candidate.architecture_version = MODAL_AUTOENCODER_ARCHITECTURE_VERSION

    group_reports: Dict[str, Dict[str, Any]] = {}
    total_source_signal = 0.0
    retained_source_signal = 0.0
    total_source_keys = 0
    retained_source_keys = 0
    total_target_keys = 0
    imported_field_entries = 0
    shared_field_entries = 0
    incompatible_shared_rows = 0

    for group_name, fields in sorted(
        MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS.items()
    ):
        all_source_maps = {
            field_name: getattr(source_generalizable, field_name)
            for field_name in fields
        }
        source_maps = {
            field_name: mapping
            for field_name, mapping in all_source_maps.items()
            if _source_field_is_transferable(field_name, policy)
        }
        target_maps = {
            field_name: getattr(target_generalizable, field_name)
            for field_name in fields
        }
        source_keys: set[Any] = set()
        all_source_keys: set[Any] = set()
        target_keys: set[Any] = set()
        for mapping in source_maps.values():
            source_keys.update(mapping)
        for mapping in all_source_maps.values():
            all_source_keys.update(mapping)
        for mapping in target_maps.values():
            target_keys.update(mapping)

        if len(target_keys) > capacity and policy.require_target_preservation:
            raise ValueError(
                f"target group {group_name!r} has {len(target_keys)} keys, "
                f"exceeding transfer capacity {capacity}"
            )

        source_scores = {
            key: sum(
                _signal(mapping[key])
                for mapping in source_maps.values()
                if key in mapping
            )
            for key in source_keys
        }
        target_scores = {
            key: sum(
                _signal(mapping[key])
                for mapping in target_maps.values()
                if key in mapping
            )
            for key in target_keys
        }
        retained_target = set(
            _ordered_keys(target_keys, target_scores)[:capacity]
        )
        available = max(0, capacity - len(retained_target))
        source_only = source_keys - retained_target
        retained_source_only = set(
            _ordered_keys(source_only, source_scores)[:available]
        )
        retained = retained_target | retained_source_only

        group_imported_entries = 0
        group_shared_entries = 0
        group_incompatible_rows = 0
        for field_name in fields:
            source_map = source_maps.get(field_name, {})
            target_map = target_maps[field_name]
            output: Dict[Any, Any] = {}
            for key in sorted(retained, key=str):
                if key in target_map:
                    output[key] = _copy_value(target_map[key])
                    if key in source_map:
                        group_shared_entries += 1
                        if _row_shape(target_map[key])[0] != _row_shape(
                            source_map[key]
                        )[0]:
                            group_incompatible_rows += 1
                        elif (
                            _row_shape(target_map[key])[0] == "sequence"
                            and _row_shape(target_map[key])[1]
                            != _row_shape(source_map[key])[1]
                        ):
                            group_incompatible_rows += 1
                    continue
                if key in source_map:
                    output[key] = _copy_value(source_map[key])
                    group_imported_entries += 1
            setattr(candidate, field_name, output)

        source_signal = sum(source_scores.values())
        source_signal_retained = sum(
            source_scores[key] for key in source_keys & retained
        )
        target_signal = sum(target_scores.values())
        target_signal_retained = sum(
            target_scores[key] for key in target_keys & retained
        )
        group_source_keys_retained = len(source_keys & retained)
        total_source_signal += source_signal
        retained_source_signal += source_signal_retained
        total_source_keys += len(source_keys)
        retained_source_keys += group_source_keys_retained
        total_target_keys += len(target_keys)
        imported_field_entries += group_imported_entries
        shared_field_entries += group_shared_entries
        incompatible_shared_rows += group_incompatible_rows
        group_reports[group_name] = {
            "capacity": capacity,
            "fields": list(fields),
            "imported_source_field_entries": group_imported_entries,
            "incompatible_shared_rows": group_incompatible_rows,
            "output_unique_keys": len(retained),
            "shared_field_entries_preserved_from_target": group_shared_entries,
            "source_signal": source_signal,
            "source_signal_coverage": (
                source_signal_retained / source_signal
                if source_signal > 0.0
                else 1.0
            ),
            "source_signal_retained": source_signal_retained,
            "source_unique_keys": len(source_keys),
            "source_unique_keys_retained": group_source_keys_retained,
            "source_unique_keys_total_including_deferred_embeddings": len(
                all_source_keys
            ),
            "target_signal": target_signal,
            "target_signal_coverage": (
                target_signal_retained / target_signal
                if target_signal > 0.0
                else 1.0
            ),
            "target_unique_keys": len(target_keys),
            "target_unique_keys_retained": len(target_keys & retained),
        }

    target_preservation_failures: list[str] = []
    for _group_name, fields in sorted(
        MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS.items()
    ):
        for field_name in fields:
            target_map = getattr(target_generalizable, field_name)
            candidate_map = getattr(candidate, field_name)
            for key, value in target_map.items():
                if key not in candidate_map or candidate_map[key] != value:
                    target_preservation_failures.append(f"{field_name}:{key}")
    for field_name in (
        "applied_leanstral_guidance_ids",
        "applied_proof_feedback_ids",
        "proof_auxiliary_head_logits",
        "proof_feedback_version_fingerprint",
    ):
        if getattr(candidate, field_name) != getattr(
            target_generalizable,
            field_name,
        ):
            target_preservation_failures.append(field_name)

    source_signal_coverage = (
        retained_source_signal / total_source_signal
        if total_source_signal > 0.0
        else 1.0
    )
    target_preserved = not target_preservation_failures
    accepted = (
        source_signal_coverage >= policy.minimum_source_signal_coverage
        and (
            target_preserved
            or not policy.require_target_preservation
        )
    )
    report: Dict[str, Any] = {
        "accepted": accepted,
        "architecture": {
            "output": MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
            "source_declared": declared_source_architecture,
            "source_loaded": source.architecture_version,
            "target": target.architecture_version,
        },
        "capacity": capacity,
        "deferred_components": {
            "decoded_embeddings": (
                "sample-specific memory is excluded to prevent validation leakage"
            ),
            "family_logits": (
                "sample-specific memory is excluded to prevent validation leakage"
            ),
            "legacy_only_embedding_weights": (
                "kept in the teacher checkpoint for behavior distillation; "
                "direct activation is disabled because it can regress held-out cosine"
                if not policy.transfer_source_embedding_weights
                else "direct activation explicitly enabled by transfer policy"
            ),
            "proof_auxiliary_head_logits": (
                "legacy logits cannot supply versioned Hammer proof labels; "
                "target proof heads are preserved and new labels require trusted feedback"
            ),
        },
        "group_reports": group_reports,
        "imported_source_field_entries": imported_field_entries,
        "incompatible_shared_rows_preserved_from_target": (
            incompatible_shared_rows
        ),
        "minimum_source_signal_coverage": (
            policy.minimum_source_signal_coverage
        ),
        "output_generalizable_entry_count": candidate.generalizable_entry_count(),
        "policy": "target_exact_source_fill_v2",
        "source_field_allowlist": list(policy.source_field_allowlist),
        "source_embedding_transfer_enabled": (
            policy.transfer_source_embedding_weights
        ),
        "schema_version": MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION,
        "shared_field_entries_preserved_from_target": shared_field_entries,
        "source_generalizable_entry_count": (
            source_generalizable.generalizable_entry_count()
        ),
        "source_signal": total_source_signal,
        "source_signal_coverage": source_signal_coverage,
        "source_signal_retained": retained_source_signal,
        "source_unique_keys": total_source_keys,
        "source_unique_keys_retained": retained_source_keys,
        "target_generalizable_entry_count": (
            target_generalizable.generalizable_entry_count()
        ),
        "target_preservation_failure_count": len(
            target_preservation_failures
        ),
        "target_preservation_failures": target_preservation_failures[:64],
        "target_preserved": target_preserved,
        "target_unique_keys": total_target_keys,
    }
    return LegacyFeatureTransferResult(state=candidate, report=report)


__all__ = [
    "DEFAULT_LEGACY_FEATURE_TRANSFER_CAPACITY",
    "LEGACY_FEATURE_TRANSFER_FIELDS",
    "MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION",
    "LegacyFeatureTransferConfig",
    "LegacyFeatureTransferResult",
    "transfer_legacy_autoencoder_features",
]
