"""Deterministic, privacy-preserving legacy autoencoder feature inventory.

The legacy feature transfer is an audit input, not a source of trusted labels.
This module independently reconciles every reusable state row in the legacy
and accepted checkpoints.  The emitted inventory contains aggregate counts and
signals only: sparse keys, samples, prompts, decoded text, and tensor payloads
are deliberately never serialized.

The canonical audit is fail closed.  It verifies the four immutable artifacts,
their embedded digests and lineage, the complete state/report schemas, tensor
shapes, accepted row equality, omission counts, and the evaluation canary.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .modal_autoencoder import (
    MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS,
    MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS,
    MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_SCHEMA_VERSION,
    MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS,
    MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
    PROOF_AUXILIARY_HEAD_SCHEMA_VERSION,
    ModalAutoencoderTrainingState,
)
from .modal_autoencoder_checkpoint import (
    CHECKPOINT_MAGIC,
    CheckpointManifest,
    _parse_container,
    load_checkpoint,
)
from .modal_autoencoder_feature_transfer import (
    MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION,
)


MODAL_AUTOENCODER_FEATURE_INVENTORY_SCHEMA_VERSION = (
    "modal-autoencoder-legacy-feature-inventory-v1"
)
MODAL_AUTOENCODER_FEATURE_INVENTORY_ARCHITECTURE_SCHEMA_VERSION = (
    "modal-autoencoder-feature-inventory-architecture-v1"
)
MODAL_AUTOENCODER_FEATURE_TOKENIZER_BINDING_SCHEMA_VERSION = (
    "legal-ir-feature-tokenizer-source-bundle-v1"
)
MODAL_AUTOENCODER_COMPILER_BINDING_SCHEMA_VERSION = (
    "legal-ir-compiler-source-bundle-v1"
)

CANONICAL_LEGACY_STATE_SHA256 = (
    "sha256:7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be"
)
CANONICAL_ACCEPTED_STATE_SHA256 = (
    "sha256:1c615f7c622b46e1a3d7349b436bf5daefc3e26866e9458c0feacfe545bcb033"
)
CANONICAL_TRANSFER_REPORT_SHA256 = (
    "sha256:5d6da2dca0c2ad5c74c16d9c47eee2fc43b18aabe5e53a6c1f55e3f6a14995e2"
)
CANONICAL_EVALUATION_CANARY_SHA256 = (
    "sha256:a71a67bf14b5740f9b52ef7ac3859b436df6406d4b60f0fc13e0e1e2125c2bb5"
)

CANONICAL_LEGACY_ROW_COUNT = 1_205_336
CANONICAL_ACCEPTED_ROW_COUNT = 209_759
CANONICAL_EXACT_ROW_COUNT = 209_753
CANONICAL_OVERRIDDEN_ROW_COUNT = 6
CANONICAL_OMITTED_ROW_COUNT = 995_577

_STATE_ENVELOPE_FIELDS = frozenset(
    {
        *MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS,
        "schema_version",
        "proof_auxiliary_head_schema_version",
    }
)
_SAMPLE_MEMORY_FIELDS = ("decoded_embeddings", "family_logits")
_GENERALIZABLE_FIELDS = frozenset(
    field_name
    for fields in MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS.values()
    for field_name in fields
)

_TRANSFER_REPORT_FIELDS = frozenset(
    {
        "accepted",
        "architecture",
        "artifacts",
        "capacity",
        "deferred_components",
        "group_reports",
        "imported_source_field_entries",
        "incompatible_shared_rows_preserved_from_target",
        "minimum_source_signal_coverage",
        "output_generalizable_entry_count",
        "policy",
        "report_sha256",
        "required_runtime",
        "schema_version",
        "selection_lineage",
        "shared_field_entries_preserved_from_target",
        "source_embedding_transfer_enabled",
        "source_field_allowlist",
        "source_generalizable_entry_count",
        "source_signal",
        "source_signal_coverage",
        "source_signal_retained",
        "source_unique_keys",
        "source_unique_keys_retained",
        "target_generalizable_entry_count",
        "target_preservation_failure_count",
        "target_preservation_failures",
        "target_preserved",
        "target_unique_keys",
    }
)
_TRANSFER_GROUP_REPORT_FIELDS = frozenset(
    {
        "capacity",
        "fields",
        "imported_source_field_entries",
        "incompatible_shared_rows",
        "output_unique_keys",
        "shared_field_entries_preserved_from_target",
        "source_signal",
        "source_signal_coverage",
        "source_signal_retained",
        "source_unique_keys",
        "source_unique_keys_retained",
        "source_unique_keys_total_including_deferred_embeddings",
        "target_signal",
        "target_signal_coverage",
        "target_unique_keys",
        "target_unique_keys_retained",
    }
)
_CANARY_REPORT_FIELDS = frozenset(
    {
        "artifacts",
        "bridge_names",
        "candidate_teacher_fidelity",
        "dataset_load_seconds",
        "decision",
        "evaluations",
        "gate",
        "report_sha256",
        "schema_version",
        "target_build_seconds",
        "target_teacher_fidelity",
        "transfer_report",
        "validation_canary_indices",
    }
)
_CHECKPOINT_MANIFEST_FIELDS = frozenset(
    {
        "checkpoint_id",
        "compression",
        "float_precision",
        "kind",
        "metadata",
        "metric_lineage",
        "metric_lineage_digest",
        "numeric_value_count",
        "payload_checksum",
        "revision",
        "schema_version",
        "state_digest",
        "state_schema_version",
        "table_count",
        "table_schema_version",
    }
)
_TRANSFER_CHECKPOINT_METADATA_FIELDS = frozenset(
    {
        "feature_transfer_schema_version",
        "legacy_state_sha256",
        "required_max_generalizable_entries_per_group",
        "selection_embedded_sha256",
        "target_state_sha256",
    }
)

# These labels describe operational risk, not feature quality.  In particular,
# a high-risk omitted row is not a negative label and cannot be used for
# training without separate, trusted evidence.
_GROUP_SEMANTICS: Mapping[str, tuple[str, str]] = {
    "compiler_quality": ("compiler_quality", "low"),
    "logic_signature": ("logic_signature", "medium"),
    "round_trip_signal": ("round_trip_and_provenance", "low"),
    "decompiler_plan": ("decompiler_structure", "medium"),
    "predicate_argument": ("predicate_argument_structure", "medium"),
    "feature": ("sparse_lexical_and_compiler_feature", "high"),
    "family": ("modal_family", "medium"),
    "family_semantic_slot": ("family_slot_interaction", "high"),
    "family_semantic_slot_legal_ir_view": (
        "family_slot_view_interaction",
        "high",
    ),
    "family_legal_ir_view": ("family_view_interaction", "medium"),
    "semantic_slot": ("semantic_slot", "medium"),
    "legal_ir_view": ("global_legal_ir_view", "low"),
    "semantic_slot_legal_ir_view": ("slot_view_interaction", "high"),
}

_TOKENIZER_SOURCE_PATHS = (
    "logic/modal/codec.py",
    "optimizers/logic_theorem_optimizer/legal_modal_parser.py",
    "optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
)
_COMPILER_SOURCE_PATHS = (
    "logic/modal",
    "optimizers/logic_theorem_optimizer/frame_bm25_selector.py",
    "optimizers/logic_theorem_optimizer/legal_modal_parser.py",
    "optimizers/logic_theorem_optimizer/legal_samples.py",
    "optimizers/logic_theorem_optimizer/modal_ir.py",
    "optimizers/logic_theorem_optimizer/modal_registry.py",
    "optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
)
_CANONICAL_SOURCE_FIELD_ALLOWLIST = (
    "compiler_quality_family_logits",
    "decompiler_plan_family_logits",
    "decompiler_plan_legal_ir_view_logits",
    "family_semantic_slot_legal_ir_view_logits",
    "feature_family_logits",
    "legal_ir_view_family_logits",
    "logic_signature_family_logits",
    "predicate_argument_family_logits",
    "predicate_argument_legal_ir_view_logits",
    "round_trip_signal_family_logits",
    "semantic_slot_family_logits",
    "semantic_slot_legal_ir_view_family_logits",
    "semantic_slot_legal_ir_view_logits",
)


class LegacyFeatureInventoryError(ValueError):
    """Raised when an audit input cannot be reconciled safely."""


@dataclass(frozen=True, slots=True)
class LegacyFeatureInventoryPolicy:
    """Expected immutable inputs and row lineage for one path-based audit."""

    require_canonical_artifacts: bool = True
    legacy_state_sha256: str = CANONICAL_LEGACY_STATE_SHA256
    accepted_state_sha256: str = CANONICAL_ACCEPTED_STATE_SHA256
    transfer_report_sha256: str = CANONICAL_TRANSFER_REPORT_SHA256
    evaluation_canary_sha256: str = CANONICAL_EVALUATION_CANARY_SHA256
    legacy_row_count: int = CANONICAL_LEGACY_ROW_COUNT
    accepted_row_count: int = CANONICAL_ACCEPTED_ROW_COUNT
    exact_row_count: int = CANONICAL_EXACT_ROW_COUNT
    overridden_row_count: int = CANONICAL_OVERRIDDEN_ROW_COUNT
    omitted_row_count: int = CANONICAL_OMITTED_ROW_COUNT

    def __post_init__(self) -> None:
        for name in (
            "legacy_row_count",
            "accepted_row_count",
            "exact_row_count",
            "overridden_row_count",
            "omitted_row_count",
        ):
            if int(getattr(self, name)) < 0:
                raise LegacyFeatureInventoryError(f"{name} must be non-negative")
        if self.exact_row_count + self.overridden_row_count != self.accepted_row_count:
            raise LegacyFeatureInventoryError(
                "accepted rows must equal exact plus overridden rows"
            )
        if self.accepted_row_count + self.omitted_row_count != self.legacy_row_count:
            raise LegacyFeatureInventoryError(
                "legacy rows must equal accepted plus omitted rows"
            )
        for name in (
            "legacy_state_sha256",
            "accepted_state_sha256",
            "transfer_report_sha256",
            "evaluation_canary_sha256",
        ):
            value = str(getattr(self, name))
            if not _is_sha256(value):
                raise LegacyFeatureInventoryError(f"{name} is not a SHA-256 digest")


def _is_sha256(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return the strict canonical JSON representation used by the inventory."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def content_sha256(value: Any) -> str:
    """Return a prefixed SHA-256 digest of a strict JSON value."""

    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Hash a file without loading its contents into the inventory."""

    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def verify_inventory_digest(inventory: Mapping[str, Any]) -> str:
    """Verify and return the embedded content address."""

    expected = str(inventory.get("inventory_sha256") or "")
    payload = dict(inventory)
    payload.pop("inventory_sha256", None)
    observed = content_sha256(payload)
    if expected != observed:
        raise LegacyFeatureInventoryError(
            f"inventory digest mismatch: {expected or '<missing>'} != {observed}"
        )
    return observed


def _strict_fields(
    value: Mapping[str, Any],
    allowed: Iterable[str],
    *,
    label: str,
) -> None:
    unknown = set(value) - set(allowed)
    if unknown:
        raise LegacyFeatureInventoryError(
            f"unknown {label} fields: {', '.join(sorted(map(str, unknown)))}"
        )


def _json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyFeatureInventoryError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LegacyFeatureInventoryError(f"expected JSON object: {path}")
    return value


class _StrictStateFactory:
    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> ModalAutoencoderTrainingState:
        _strict_fields(value, _STATE_ENVELOPE_FIELDS, label="state")
        return ModalAutoencoderTrainingState.from_dict(value)


def _load_state(path: Path) -> tuple[ModalAutoencoderTrainingState, dict[str, Any]]:
    with path.open("rb") as handle:
        prefix = handle.read(len(CHECKPOINT_MAGIC))
    if prefix == CHECKPOINT_MAGIC:
        raw = path.read_bytes()
        manifest_data, _payload, end = _parse_container(
            raw,
            expected_magic=CHECKPOINT_MAGIC,
        )
        if end != len(raw):
            raise LegacyFeatureInventoryError("accepted checkpoint has trailing bytes")
        _strict_fields(
            manifest_data,
            _CHECKPOINT_MANIFEST_FIELDS,
            label="checkpoint manifest",
        )
        metadata = manifest_data.get("metadata")
        if not isinstance(metadata, Mapping):
            raise LegacyFeatureInventoryError("checkpoint metadata must be an object")
        _strict_fields(
            metadata,
            _TRANSFER_CHECKPOINT_METADATA_FIELDS,
            label="checkpoint metadata",
        )
        loaded = load_checkpoint(
            path,
            allow_json=False,
            expected_state_schema_version=MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
            state_factory=_StrictStateFactory,
        )
        manifest = loaded.manifest
        if not isinstance(manifest, CheckpointManifest):
            raise LegacyFeatureInventoryError("checkpoint manifest was not validated")
        return loaded.state, {
            "checkpoint_id": manifest.checkpoint_id,
            "format": loaded.format,
            "metadata": dict(metadata),
            "state_digest": manifest.state_digest,
        }

    value = _json_object(path)
    _strict_fields(value, _STATE_ENVELOPE_FIELDS, label="state")
    state = ModalAutoencoderTrainingState.from_dict(value)
    return state, {
        "declared_architecture": str(
            value.get("architecture_version")
            or MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION
        ),
        "format": "json",
    }


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LegacyFeatureInventoryError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise LegacyFeatureInventoryError(f"{label} must be finite")
    return number


def _row_values(
    field_name: str,
    row: Any,
    *,
    label: str,
) -> tuple[tuple[str, ...], tuple[float, ...], int | None]:
    if field_name == "legal_ir_view_logits":
        return (), (_finite_number(row, label=label),), None
    if field_name.endswith("_embedding_weights"):
        if isinstance(row, (str, bytes, bytearray)) or not isinstance(row, Sequence):
            raise LegacyFeatureInventoryError(f"{label} must be a numeric vector")
        values = tuple(
            _finite_number(value, label=f"{label} vector value") for value in row
        )
        if not values:
            raise LegacyFeatureInventoryError(f"{label} has an empty vector")
        return (), values, len(values)
    if not isinstance(row, Mapping):
        raise LegacyFeatureInventoryError(f"{label} must be a numeric mapping")
    labels: list[str] = []
    values: list[float] = []
    for raw_key in sorted(row, key=str):
        key = str(raw_key)
        if not key or raw_key != key:
            raise LegacyFeatureInventoryError(
                f"{label} contains a non-canonical label"
            )
        labels.append(key)
        values.append(_finite_number(row[raw_key], label=f"{label} value"))
    return tuple(labels), tuple(values), None


def _validate_field_dimensions(
    field_name: str,
    legacy: Mapping[str, Any],
    accepted: Mapping[str, Any],
) -> tuple[str, int | None]:
    kind = (
        "global_scalar"
        if field_name == "legal_ir_view_logits"
        else "embedding_vector"
        if field_name.endswith("_embedding_weights")
        else "sparse_logits"
    )
    dimensions: set[int] = set()
    legacy_rows: dict[str, tuple[tuple[str, ...], int | None]] = {}
    for state_label, mapping in (("legacy", legacy), ("accepted", accepted)):
        if not isinstance(mapping, Mapping):
            raise LegacyFeatureInventoryError(
                f"{state_label}.{field_name} must be an object"
            )
        for key, row in mapping.items():
            if not isinstance(key, str) or not key:
                raise LegacyFeatureInventoryError(
                    f"{state_label}.{field_name} contains a non-canonical row key"
                )
            labels, _values, dimension = _row_values(
                field_name,
                row,
                label=f"{state_label}.{field_name} row",
            )
            if dimension is not None:
                dimensions.add(dimension)
            if state_label == "legacy":
                legacy_rows[str(key)] = (labels, dimension)
            elif key in legacy_rows:
                old_labels, old_dimension = legacy_rows[str(key)]
                if labels != old_labels or dimension != old_dimension:
                    raise LegacyFeatureInventoryError(
                        f"incompatible shared row dimensions in {field_name}"
                    )
    if len(dimensions) > 1:
        raise LegacyFeatureInventoryError(
            f"incompatible vector dimensions in {field_name}: {sorted(dimensions)}"
        )
    return kind, next(iter(dimensions), None)


def _empty_signal() -> dict[str, Any]:
    return {
        "absolute_signal_mass": 0.0,
        "activation_frequency": 0.0,
        "active_rows": 0,
        "negative_signal_mass": 0.0,
        "nonzero_values": 0,
        "numeric_values": 0,
        "positive_signal_mass": 0.0,
        "row_count": 0,
        "signed_signal_mass": 0.0,
        "value_activation_frequency": 0.0,
    }


def _signal_summary(
    field_name: str,
    rows: Iterable[Any],
) -> dict[str, Any]:
    row_count = 0
    active_rows = 0
    numeric_values = 0
    nonzero_values = 0
    signed_parts: list[float] = []
    absolute_parts: list[float] = []
    positive_parts: list[float] = []
    negative_parts: list[float] = []
    for row in rows:
        _labels, values, _dimension = _row_values(
            field_name,
            row,
            label=f"{field_name} row",
        )
        row_count += 1
        numeric_values += len(values)
        row_nonzero = sum(value != 0.0 for value in values)
        nonzero_values += row_nonzero
        active_rows += row_nonzero > 0
        signed_parts.append(math.fsum(values))
        absolute_parts.append(math.fsum(abs(value) for value in values))
        positive_parts.append(math.fsum(value for value in values if value > 0.0))
        negative_parts.append(math.fsum(value for value in values if value < 0.0))
    if row_count == 0:
        return _empty_signal()
    return {
        "absolute_signal_mass": math.fsum(absolute_parts),
        "activation_frequency": active_rows / row_count,
        "active_rows": active_rows,
        "negative_signal_mass": math.fsum(negative_parts),
        "nonzero_values": nonzero_values,
        "numeric_values": numeric_values,
        "positive_signal_mass": math.fsum(positive_parts),
        "row_count": row_count,
        "signed_signal_mass": math.fsum(signed_parts),
        "value_activation_frequency": (
            nonzero_values / numeric_values if numeric_values else 0.0
        ),
    }


def _merge_signals(values: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(values)
    if not items:
        return _empty_signal()
    row_count = sum(int(item["row_count"]) for item in items)
    active_rows = sum(int(item["active_rows"]) for item in items)
    numeric_values = sum(int(item["numeric_values"]) for item in items)
    nonzero_values = sum(int(item["nonzero_values"]) for item in items)
    return {
        "absolute_signal_mass": math.fsum(
            float(item["absolute_signal_mass"]) for item in items
        ),
        "activation_frequency": active_rows / row_count if row_count else 0.0,
        "active_rows": active_rows,
        "negative_signal_mass": math.fsum(
            float(item["negative_signal_mass"]) for item in items
        ),
        "nonzero_values": nonzero_values,
        "numeric_values": numeric_values,
        "positive_signal_mass": math.fsum(
            float(item["positive_signal_mass"]) for item in items
        ),
        "row_count": row_count,
        "signed_signal_mass": math.fsum(
            float(item["signed_signal_mass"]) for item in items
        ),
        "value_activation_frequency": (
            nonzero_values / numeric_values if numeric_values else 0.0
        ),
    }


def _field_inventory(
    group_name: str,
    field_name: str,
    legacy: Mapping[str, Any],
    accepted: Mapping[str, Any],
) -> dict[str, Any]:
    tensor_kind, vector_dimension = _validate_field_dimensions(
        field_name,
        legacy,
        accepted,
    )
    exact_keys: list[str] = []
    overridden_keys: list[str] = []
    omitted_keys: list[str] = []
    for key in sorted(legacy, key=str):
        if key not in accepted:
            omitted_keys.append(key)
        elif legacy[key] == accepted[key]:
            exact_keys.append(key)
        else:
            overridden_keys.append(key)
    accepted_only = sorted(set(accepted) - set(legacy), key=str)
    if accepted_only:
        raise LegacyFeatureInventoryError(
            f"accepted field {field_name} contains {len(accepted_only)} "
            "rows absent from the legacy lineage"
        )

    semantic_family, group_risk = _GROUP_SEMANTICS[group_name]
    transfer_risk = "high" if tensor_kind == "embedding_vector" else group_risk
    risk_reason = (
        "direct legacy embedding activation can regress held-out cosine"
        if tensor_kind == "embedding_vector"
        else "high-cardinality sparse interaction requires evidence-aware selection"
        if transfer_risk == "high"
        else "semantic logits require matched compiler and tokenizer lineage"
        if transfer_risk == "medium"
        else "bounded categorical/global signal with target-preserving transfer"
    )
    dispositions = {
        "omitted": _signal_summary(
            field_name,
            (legacy[key] for key in omitted_keys),
        ),
        "overridden": _signal_summary(
            field_name,
            (legacy[key] for key in overridden_keys),
        ),
        "remapped": _empty_signal(),
        "transferable_exact": _signal_summary(
            field_name,
            (legacy[key] for key in exact_keys),
        ),
    }
    return {
        "accepted_signal": _signal_summary(
            field_name,
            (accepted[key] for key in sorted(accepted, key=str)),
        ),
        "dispositions": dispositions,
        "field": field_name,
        "legacy_signal": _merge_signals(dispositions.values()),
        "risk_reason": risk_reason,
        "semantic_family": semantic_family,
        "tensor_kind": tensor_kind,
        "transfer_risk": transfer_risk,
        "vector_dimension": vector_dimension,
    }


def _group_inventory(
    group_name: str,
    fields: Sequence[str],
    legacy_state: ModalAutoencoderTrainingState,
    accepted_state: ModalAutoencoderTrainingState,
) -> dict[str, Any]:
    field_inventories = [
        _field_inventory(
            group_name,
            field_name,
            getattr(legacy_state, field_name),
            getattr(accepted_state, field_name),
        )
        for field_name in fields
    ]
    disposition_names = (
        "transferable_exact",
        "remapped",
        "overridden",
        "omitted",
    )
    dispositions = {
        name: _merge_signals(
            field["dispositions"][name] for field in field_inventories
        )
        for name in disposition_names
    }
    semantic_family, transfer_risk = _GROUP_SEMANTICS[group_name]
    legacy_unique_keys: set[Any] = set()
    accepted_unique_keys: set[Any] = set()
    for field_name in fields:
        legacy_unique_keys.update(getattr(legacy_state, field_name))
        accepted_unique_keys.update(getattr(accepted_state, field_name))
    return {
        "accepted_unique_keys": len(accepted_unique_keys),
        "accepted_signal": _merge_signals(
            field["accepted_signal"] for field in field_inventories
        ),
        "dispositions": dispositions,
        "fields": field_inventories,
        "group": group_name,
        "legacy_unique_keys": len(legacy_unique_keys),
        "legacy_signal": _merge_signals(
            field["legacy_signal"] for field in field_inventories
        ),
        "semantic_family": semantic_family,
        "transfer_risk": transfer_risk,
    }


def _verify_embedded_digest(
    value: Mapping[str, Any],
    *,
    field: str,
    label: str,
) -> str:
    expected = str(value.get(field) or "")
    payload = dict(value)
    payload.pop(field, None)
    observed = content_sha256(payload)
    if expected != observed:
        raise LegacyFeatureInventoryError(
            f"{label} embedded digest mismatch: "
            f"{expected or '<missing>'} != {observed}"
        )
    return observed


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LegacyFeatureInventoryError(f"{label} must be an object")
    return value


def _verify_transfer_report_schema(report: Mapping[str, Any]) -> None:
    _strict_fields(report, _TRANSFER_REPORT_FIELDS, label="transfer report")
    if report.get("schema_version") != MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION:
        raise LegacyFeatureInventoryError("unsupported transfer report schema")
    architecture = _mapping(report.get("architecture"), label="transfer architecture")
    _strict_fields(
        architecture,
        {"output", "source_declared", "source_loaded", "target"},
        label="transfer architecture",
    )
    artifacts = _mapping(report.get("artifacts"), label="transfer artifacts")
    _strict_fields(
        artifacts,
        {"legacy_state", "output_state", "target_state"},
        label="transfer artifacts",
    )
    _strict_fields(
        _mapping(artifacts.get("legacy_state"), label="legacy artifact"),
        {"path", "sha256"},
        label="legacy artifact",
    )
    _strict_fields(
        _mapping(artifacts.get("output_state"), label="output artifact"),
        {"bytes", "checkpoint_id", "path", "sha256", "state_digest"},
        label="output artifact",
    )
    _strict_fields(
        _mapping(artifacts.get("target_state"), label="target artifact"),
        {"path", "sha256"},
        label="target artifact",
    )
    expected_groups = set(MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS)
    groups = _mapping(report.get("group_reports"), label="transfer group reports")
    if set(groups) != expected_groups:
        raise LegacyFeatureInventoryError(
            "transfer group set does not match architecture schema"
        )
    for group_name, group_report in groups.items():
        group_mapping = _mapping(
            group_report,
            label=f"transfer group {group_name}",
        )
        _strict_fields(
            group_mapping,
            _TRANSFER_GROUP_REPORT_FIELDS,
            label=f"transfer group {group_name}",
        )
        if tuple(group_mapping.get("fields") or ()) != tuple(
            MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS[group_name]
        ):
            raise LegacyFeatureInventoryError(
                f"transfer fields mismatch for group {group_name}"
            )
    _verify_embedded_digest(
        report,
        field="report_sha256",
        label="transfer report",
    )


def _verify_canary_schema(canary: Mapping[str, Any]) -> None:
    _strict_fields(canary, _CANARY_REPORT_FIELDS, label="canary report")
    if canary.get("schema_version") != "modal-autoencoder-feature-transfer-canary-v1":
        raise LegacyFeatureInventoryError("unsupported evaluation canary schema")
    artifacts = _mapping(canary.get("artifacts"), label="canary artifacts")
    _strict_fields(
        artifacts,
        {"candidate", "target", "teacher"},
        label="canary artifacts",
    )
    for name in ("candidate", "target", "teacher"):
        _strict_fields(
            _mapping(artifacts.get(name), label=f"canary {name} artifact"),
            {"path", "sha256"},
            label=f"canary {name} artifact",
        )
    _strict_fields(
        _mapping(canary.get("transfer_report"), label="canary transfer report"),
        {"embedded_sha256", "file_sha256", "path"},
        label="canary transfer report",
    )
    gate = _mapping(canary.get("gate"), label="canary gate")
    _strict_fields(
        gate,
        {"accepted", "checks", "fidelity_deltas", "metric_deltas", "tolerances"},
        label="canary gate",
    )
    evaluations = _mapping(canary.get("evaluations"), label="canary evaluations")
    _strict_fields(
        evaluations,
        {"candidate", "target", "teacher"},
        label="canary evaluations",
    )
    for name in ("candidate", "target", "teacher"):
        evaluation = _mapping(
            evaluations.get(name),
            label=f"canary {name} evaluation",
        )
        _strict_fields(
            evaluation,
            {"compute_backend", "compute_device", "elapsed_seconds", "metrics"},
            label=f"canary {name} evaluation",
        )
        for metric_name, metric_value in _mapping(
            evaluation.get("metrics"),
            label=f"canary {name} metrics",
        ).items():
            _finite_number(
                metric_value,
                label=f"canary {name} metric {metric_name}",
            )
    _verify_embedded_digest(canary, field="report_sha256", label="canary report")


def architecture_schema_binding() -> dict[str, Any]:
    """Return the content-addressed current state/transfer architecture."""

    descriptor = {
        "architecture_versions": sorted(
            MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS
        ),
        "capacity_groups": {
            group: list(fields)
            for group, fields in sorted(
                MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS.items()
            )
        },
        "capacity_schema_version": (
            MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_SCHEMA_VERSION
        ),
        "current_architecture_version": MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
        "generalizable_fields": sorted(_GENERALIZABLE_FIELDS),
        "field_shapes": {
            field_name: (
                "global_scalar"
                if field_name == "legal_ir_view_logits"
                else "embedding_vector[8]"
                if field_name.endswith("_embedding_weights")
                else "sparse_logits"
            )
            for field_name in sorted(_GENERALIZABLE_FIELDS)
        },
        "legacy_architecture_version": MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
        "proof_head_schema_version": PROOF_AUXILIARY_HEAD_SCHEMA_VERSION,
        "schema_version": (
            MODAL_AUTOENCODER_FEATURE_INVENTORY_ARCHITECTURE_SCHEMA_VERSION
        ),
        "state_component_fields": list(MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS),
        "state_schema_version": MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
    }
    return {
        "schema_version": descriptor["schema_version"],
        "sha256": content_sha256(descriptor),
    }


def _source_bundle_binding(
    package_root: Path,
    candidates: Sequence[str],
    *,
    schema_version: str,
    configuration: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    files: set[Path] = set()
    for relative in candidates:
        candidate = package_root / relative
        if candidate.is_dir():
            files.update(candidate.rglob("*.py"))
        elif candidate.is_file():
            files.add(candidate)
        else:
            raise LegacyFeatureInventoryError(
                f"binding source does not exist: {relative}"
            )
    entries = []
    for path in sorted(files):
        entries.append(
            {
                "relative_path": path.relative_to(package_root).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    if not entries:
        raise LegacyFeatureInventoryError("binding source bundle is empty")
    descriptor = {
        "configuration": dict(configuration or {}),
        "files": entries,
        "schema_version": schema_version,
    }
    return {
        "schema_version": schema_version,
        "sha256": content_sha256(descriptor),
    }


def tokenizer_binding(package_root: str | Path) -> dict[str, str]:
    """Bind the deterministic tokenization and parser implementation."""

    return _source_bundle_binding(
        Path(package_root),
        _TOKENIZER_SOURCE_PATHS,
        schema_version=MODAL_AUTOENCODER_FEATURE_TOKENIZER_BINDING_SCHEMA_VERSION,
        configuration={
            "embedding_dimensions": 8,
            "fallback_required": True,
            "parser_backend": "spacy",
            "spacy_model_name": "definitely_missing_legal_model",
            "use_flogic": True,
        },
    )


def compiler_binding(package_root: str | Path) -> dict[str, str]:
    """Bind the deterministic compiler implementation by source content."""

    return _source_bundle_binding(
        Path(package_root),
        _COMPILER_SOURCE_PATHS,
        schema_version=MODAL_AUTOENCODER_COMPILER_BINDING_SCHEMA_VERSION,
        configuration={
            "bridge_names": [
                "modal_frame_logic",
                "deontic_norms",
                "fol_tdfol",
                "cec_dcec",
                "external_prover_router",
            ],
            "evaluate_provers": False,
        },
    )


def _validate_lineage(
    groups: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
    canary: Mapping[str, Any],
    *,
    bindings: Mapping[str, str],
    policy: LegacyFeatureInventoryPolicy,
) -> dict[str, int]:
    totals = {
        name: sum(
            int(group["dispositions"][name]["row_count"]) for group in groups
        )
        for name in (
            "transferable_exact",
            "remapped",
            "overridden",
            "omitted",
        )
    }
    legacy_rows = sum(int(group["legacy_signal"]["row_count"]) for group in groups)
    accepted_rows = sum(
        int(group["accepted_signal"]["row_count"]) for group in groups
    )
    if totals["remapped"] != 0:
        raise LegacyFeatureInventoryError(
            "current architecture declares no legacy field remaps"
        )
    if totals["transferable_exact"] + totals["overridden"] != accepted_rows:
        raise LegacyFeatureInventoryError(
            "accepted rows do not reconcile to exact and overridden legacy rows"
        )
    if accepted_rows + totals["omitted"] != legacy_rows:
        raise LegacyFeatureInventoryError(
            "legacy rows do not reconcile to accepted and omitted rows"
        )

    report_counts = {
        "legacy_rows": int(report.get("source_generalizable_entry_count", -1)),
        "accepted_rows": int(report.get("output_generalizable_entry_count", -1)),
    }
    if report_counts != {
        "legacy_rows": legacy_rows,
        "accepted_rows": accepted_rows,
    }:
        raise LegacyFeatureInventoryError(
            f"transfer report row counts mismatch: {report_counts}"
        )
    if report.get("accepted") is not True or report.get("target_preserved") is not True:
        raise LegacyFeatureInventoryError(
            "transfer report does not identify an accepted target-preserving transfer"
        )
    if int(report.get("incompatible_shared_rows_preserved_from_target", -1)) != 0:
        raise LegacyFeatureInventoryError(
            "transfer report declares incompatible shared rows"
        )
    if int(report.get("target_preservation_failure_count", -1)) != 0:
        raise LegacyFeatureInventoryError(
            "transfer report declares target preservation failures"
        )
    source_fill_rows = int(report.get("imported_source_field_entries", -1))
    target_preserved_rows = int(report.get("target_generalizable_entry_count", -1))
    if source_fill_rows + target_preserved_rows != accepted_rows:
        raise LegacyFeatureInventoryError(
            "accepted rows do not reconcile to target-preserved plus source-fill rows"
        )
    if policy.require_canonical_artifacts:
        if tuple(report.get("source_field_allowlist") or ()) != (
            _CANONICAL_SOURCE_FIELD_ALLOWLIST
        ):
            raise LegacyFeatureInventoryError(
                "canonical source field allowlist mismatch"
            )
        if report.get("source_embedding_transfer_enabled") is not False:
            raise LegacyFeatureInventoryError(
                "canonical transfer must defer direct legacy embeddings"
            )
        report_groups = _mapping(
            report.get("group_reports"),
            label="transfer group reports",
        )
        for group in groups:
            group_name = str(group["group"])
            report_group = _mapping(
                report_groups.get(group_name),
                label=f"transfer group {group_name}",
            )
            if int(report_group.get("output_unique_keys", -1)) != int(
                group["accepted_unique_keys"]
            ):
                raise LegacyFeatureInventoryError(
                    f"accepted unique-key count mismatch for {group_name}"
                )
            if int(
                report_group.get(
                    "source_unique_keys_total_including_deferred_embeddings",
                    -1,
                )
            ) != int(group["legacy_unique_keys"]):
                raise LegacyFeatureInventoryError(
                    f"legacy unique-key count mismatch for {group_name}"
                )
        if sum(
            int(_mapping(value, label="transfer group").get(
                "imported_source_field_entries",
                -1,
            ))
            for value in report_groups.values()
        ) != source_fill_rows:
            raise LegacyFeatureInventoryError(
                "group source-fill rows do not reconcile to transfer report"
            )
        if sum(
            int(_mapping(value, label="transfer group").get(
                "shared_field_entries_preserved_from_target",
                -1,
            ))
            for value in report_groups.values()
        ) != int(report.get("shared_field_entries_preserved_from_target", -1)):
            raise LegacyFeatureInventoryError(
                "group shared rows do not reconcile to transfer report"
            )

    report_artifacts = _mapping(report.get("artifacts"), label="transfer artifacts")
    if _mapping(
        report_artifacts.get("legacy_state"),
        label="legacy artifact",
    ).get("sha256") != bindings["legacy_state"]:
        raise LegacyFeatureInventoryError("transfer report legacy state hash mismatch")
    if _mapping(
        report_artifacts.get("output_state"),
        label="accepted artifact",
    ).get("sha256") != bindings["accepted_state"]:
        raise LegacyFeatureInventoryError("transfer report accepted state hash mismatch")
    target_artifact_hash = str(
        _mapping(
            report_artifacts.get("target_state"),
            label="target artifact",
        ).get("sha256")
        or ""
    )
    selection_lineage = _mapping(
        report.get("selection_lineage"),
        label="selection lineage",
    )
    _strict_fields(
        selection_lineage,
        {
            "candidate_id",
            "params",
            "primary_seed",
            "selection_embedded_sha256",
            "selection_file_sha256",
            "selection_path",
            "target_state_sha256",
            "training_revision",
        },
        label="selection lineage",
    )
    if selection_lineage.get("target_state_sha256") != target_artifact_hash:
        raise LegacyFeatureInventoryError(
            "selection target state hash mismatch"
        )

    canary_artifacts = _mapping(canary.get("artifacts"), label="canary artifacts")
    if _mapping(
        canary_artifacts.get("teacher"),
        label="canary teacher",
    ).get("sha256") != bindings["legacy_state"]:
        raise LegacyFeatureInventoryError("canary teacher hash mismatch")
    if _mapping(
        canary_artifacts.get("candidate"),
        label="canary candidate",
    ).get("sha256") != bindings["accepted_state"]:
        raise LegacyFeatureInventoryError("canary candidate hash mismatch")
    if _mapping(
        canary_artifacts.get("target"),
        label="canary target",
    ).get("sha256") != target_artifact_hash:
        raise LegacyFeatureInventoryError("canary target state hash mismatch")
    canary_transfer = _mapping(
        canary.get("transfer_report"),
        label="canary transfer report",
    )
    if canary_transfer.get("file_sha256") != bindings["transfer_report"]:
        raise LegacyFeatureInventoryError("canary transfer report hash mismatch")
    if canary_transfer.get("embedded_sha256") != report.get("report_sha256"):
        raise LegacyFeatureInventoryError(
            "canary embedded transfer report digest mismatch"
        )
    if (
        canary.get("decision") != "passed"
        or _mapping(canary.get("gate"), label="canary gate").get("accepted") is not True
    ):
        raise LegacyFeatureInventoryError("evaluation canary did not pass")

    if policy.require_canonical_artifacts:
        expected_counts = {
            "legacy_rows": policy.legacy_row_count,
            "accepted_rows": policy.accepted_row_count,
            "transferable_exact": policy.exact_row_count,
            "remapped": 0,
            "overridden": policy.overridden_row_count,
            "omitted": policy.omitted_row_count,
        }
        observed_counts = {
            "legacy_rows": legacy_rows,
            "accepted_rows": accepted_rows,
            **totals,
        }
        if observed_counts != expected_counts:
            raise LegacyFeatureInventoryError(
                f"canonical row lineage mismatch: {observed_counts}"
            )
    return {
        "accepted_rows": accepted_rows,
        "legacy_rows": legacy_rows,
        **totals,
    }


def build_legacy_feature_inventory(
    legacy_state: ModalAutoencoderTrainingState,
    accepted_state: ModalAutoencoderTrainingState,
    transfer_report: Mapping[str, Any],
    canary_report: Mapping[str, Any],
    *,
    artifact_bindings: Mapping[str, str],
    architecture_binding: Mapping[str, str] | None = None,
    tokenizer_source_binding: Mapping[str, str] | None = None,
    compiler_source_binding: Mapping[str, str] | None = None,
    policy: LegacyFeatureInventoryPolicy | None = None,
    legacy_format: str = "json",
    accepted_format: str = "compact",
) -> dict[str, Any]:
    """Build a source-free inventory from already loaded, immutable inputs."""

    audit_policy = policy or LegacyFeatureInventoryPolicy(
        require_canonical_artifacts=False,
        legacy_state_sha256=str(artifact_bindings.get("legacy_state") or ""),
        accepted_state_sha256=str(artifact_bindings.get("accepted_state") or ""),
        transfer_report_sha256=str(artifact_bindings.get("transfer_report") or ""),
        evaluation_canary_sha256=str(
            artifact_bindings.get("evaluation_canary") or ""
        ),
        legacy_row_count=int(transfer_report.get("source_generalizable_entry_count", 0)),
        accepted_row_count=int(transfer_report.get("output_generalizable_entry_count", 0)),
        exact_row_count=int(transfer_report.get("output_generalizable_entry_count", 0)),
        overridden_row_count=0,
        omitted_row_count=max(
            0,
            int(transfer_report.get("source_generalizable_entry_count", 0))
            - int(transfer_report.get("output_generalizable_entry_count", 0)),
        ),
    )
    required_binding_names = {
        "accepted_state",
        "evaluation_canary",
        "legacy_state",
        "transfer_report",
    }
    if set(artifact_bindings) != required_binding_names:
        raise LegacyFeatureInventoryError(
            "artifact bindings must contain exactly: "
            + ", ".join(sorted(required_binding_names))
        )
    for name, digest in artifact_bindings.items():
        if not _is_sha256(str(digest)):
            raise LegacyFeatureInventoryError(
                f"artifact binding {name} is not a SHA-256 digest"
            )
    if audit_policy.require_canonical_artifacts:
        expected_artifact_bindings = {
            "accepted_state": audit_policy.accepted_state_sha256,
            "evaluation_canary": audit_policy.evaluation_canary_sha256,
            "legacy_state": audit_policy.legacy_state_sha256,
            "transfer_report": audit_policy.transfer_report_sha256,
        }
        if dict(artifact_bindings) != expected_artifact_bindings:
            raise LegacyFeatureInventoryError(
                "artifact bindings do not match the immutable audit policy"
            )
    _verify_transfer_report_schema(transfer_report)
    _verify_canary_schema(canary_report)

    architecture = dict(architecture_binding or architecture_schema_binding())
    tokenizer = dict(
        tokenizer_source_binding
        or {
            "schema_version": (
                MODAL_AUTOENCODER_FEATURE_TOKENIZER_BINDING_SCHEMA_VERSION
            ),
            "sha256": content_sha256(
                {
                    "schema_version": (
                        MODAL_AUTOENCODER_FEATURE_TOKENIZER_BINDING_SCHEMA_VERSION
                    )
                }
            ),
        }
    )
    compiler = dict(
        compiler_source_binding
        or {
            "schema_version": MODAL_AUTOENCODER_COMPILER_BINDING_SCHEMA_VERSION,
            "sha256": content_sha256(
                {
                    "schema_version": (
                        MODAL_AUTOENCODER_COMPILER_BINDING_SCHEMA_VERSION
                    )
                }
            ),
        }
    )
    for label, binding in (
        ("architecture", architecture),
        ("tokenizer", tokenizer),
        ("compiler", compiler),
    ):
        _strict_fields(binding, {"schema_version", "sha256"}, label=f"{label} binding")
        if not _is_sha256(str(binding.get("sha256") or "")):
            raise LegacyFeatureInventoryError(f"{label} binding is not content addressed")

    groups = [
        _group_inventory(
            group_name,
            fields,
            legacy_state,
            accepted_state,
        )
        for group_name, fields in sorted(
            MODAL_AUTOENCODER_GENERALIZABLE_CAPACITY_GROUPS.items()
        )
    ]
    row_counts = _validate_lineage(
        groups,
        transfer_report,
        canary_report,
        bindings=artifact_bindings,
        policy=audit_policy,
    )
    omitted_by_semantic_family = {
        str(group["semantic_family"]): {
            "activation_frequency": group["dispositions"]["omitted"][
                "activation_frequency"
            ],
            "absolute_signal_mass": group["dispositions"]["omitted"][
                "absolute_signal_mass"
            ],
            "row_count": group["dispositions"]["omitted"]["row_count"],
            "signed_signal_mass": group["dispositions"]["omitted"][
                "signed_signal_mass"
            ],
            "transfer_risk": max(
                (
                    str(field["transfer_risk"])
                    for field in group["fields"]
                    if int(field["dispositions"]["omitted"]["row_count"]) > 0
                ),
                key={"low": 0, "medium": 1, "high": 2}.get,
                default=str(group["transfer_risk"]),
            ),
            "value_activation_frequency": group["dispositions"]["omitted"][
                "value_activation_frequency"
            ],
        }
        for group in groups
    }
    if sum(
        int(value["row_count"]) for value in omitted_by_semantic_family.values()
    ) != row_counts["omitted"]:
        raise LegacyFeatureInventoryError(
            "semantic-family omission ledger does not reconcile"
        )
    omitted_signal = _merge_signals(
        group["dispositions"]["omitted"] for group in groups
    )
    omitted_by_transfer_risk = {
        risk: _merge_signals(
            field["dispositions"]["omitted"]
            for group in groups
            for field in group["fields"]
            if field["transfer_risk"] == risk
        )
        for risk in ("low", "medium", "high")
    }
    if sum(
        int(value["row_count"]) for value in omitted_by_transfer_risk.values()
    ) != row_counts["omitted"]:
        raise LegacyFeatureInventoryError(
            "transfer-risk omission ledger does not reconcile"
        )

    sample_memory_counts = {
        "accepted_sample_memory_rows": sum(
            len(getattr(accepted_state, field_name))
            for field_name in _SAMPLE_MEMORY_FIELDS
        ),
        "legacy_sample_memory_rows": sum(
            len(getattr(legacy_state, field_name))
            for field_name in _SAMPLE_MEMORY_FIELDS
        ),
    }
    inventory: dict[str, Any] = {
        "audit_decision": "verified_immutable_inputs",
        "bindings": {
            "accepted_state": {
                "format": accepted_format,
                "sha256": artifact_bindings["accepted_state"],
            },
            "architecture_schema": architecture,
            "compiler": compiler,
            "evaluation_canary": {
                "embedded_sha256": str(canary_report.get("report_sha256") or ""),
                "indices_sha256": content_sha256(
                    list(canary_report.get("validation_canary_indices") or ())
                ),
                "schema_version": str(canary_report.get("schema_version") or ""),
                "sha256": artifact_bindings["evaluation_canary"],
            },
            "legacy_state": {
                "format": legacy_format,
                "sha256": artifact_bindings["legacy_state"],
            },
            "tokenizer": tokenizer,
            "transfer_report": {
                "embedded_sha256": str(transfer_report.get("report_sha256") or ""),
                "file_sha256": artifact_bindings["transfer_report"],
                "schema_version": str(transfer_report.get("schema_version") or ""),
            },
        },
        "groups": groups,
        "metric_definitions": {
            "absolute_signal_mass": "math.fsum(abs(value)) over finite numeric leaves",
            "activation_frequency": "rows with at least one nonzero numeric leaf divided by rows",
            "signed_signal_mass": "math.fsum(value) over finite numeric leaves",
            "value_activation_frequency": "nonzero numeric leaves divided by numeric leaves",
        },
        "omitted_by_semantic_family": omitted_by_semantic_family,
        "omitted_by_transfer_risk": omitted_by_transfer_risk,
        "omitted_signal": omitted_signal,
        "privacy": {
            **sample_memory_counts,
            "nested_artifact_payloads_serialized": False,
            "prompts_serialized": False,
            "sample_keys_serialized": False,
            "source_samples_serialized": False,
            "tensor_rows_serialized": False,
            "text_payloads_serialized": False,
        },
        "row_counts": row_counts,
        "schema_version": MODAL_AUTOENCODER_FEATURE_INVENTORY_SCHEMA_VERSION,
        "transfer_lineage": {
            "accepted_row_provenance": {
                "source_fill_rows": int(
                    transfer_report.get("imported_source_field_entries", -1)
                ),
                "target_preserved_rows": int(
                    transfer_report.get("target_generalizable_entry_count", -1)
                ),
            },
            "architecture": dict(
                _mapping(
                    transfer_report.get("architecture"),
                    label="transfer architecture",
                )
            ),
            "capacity": int(transfer_report.get("capacity", -1)),
            "policy": str(transfer_report.get("policy") or ""),
            "shared_source_target_rows": int(
                transfer_report.get(
                    "shared_field_entries_preserved_from_target",
                    -1,
                )
            ),
            "source_embedding_transfer_enabled": bool(
                transfer_report.get("source_embedding_transfer_enabled")
            ),
            "source_signal_coverage": float(
                transfer_report.get("source_signal_coverage", 0.0)
            ),
            "target_preserved": bool(transfer_report.get("target_preserved")),
        },
        "trust_boundary": {
            "artifact_acceptance_flags_are_audit_observations_only": True,
            "eligible_as_automatic_training_labels": False,
            "requires_independent_promotion_evidence": True,
        },
    }
    inventory["inventory_sha256"] = content_sha256(inventory)
    verify_inventory_digest(inventory)
    return inventory


def audit_legacy_feature_inventory(
    old_state_path: str | Path,
    new_state_path: str | Path,
    transfer_report_path: str | Path,
    canary_report_path: str | Path,
    *,
    policy: LegacyFeatureInventoryPolicy | None = None,
    package_root: str | Path | None = None,
) -> dict[str, Any]:
    """Load, verify, reconcile, and content-address the four audit artifacts."""

    audit_policy = policy or LegacyFeatureInventoryPolicy()
    paths = {
        "accepted_state": Path(new_state_path).resolve(),
        "evaluation_canary": Path(canary_report_path).resolve(),
        "legacy_state": Path(old_state_path).resolve(),
        "transfer_report": Path(transfer_report_path).resolve(),
    }
    for name, path in paths.items():
        if not path.is_file():
            raise LegacyFeatureInventoryError(
                f"required {name} input does not exist: {path}"
            )
    artifact_bindings = {
        name: sha256_file(path) for name, path in paths.items()
    }
    if audit_policy.require_canonical_artifacts:
        expected = {
            "accepted_state": audit_policy.accepted_state_sha256,
            "evaluation_canary": audit_policy.evaluation_canary_sha256,
            "legacy_state": audit_policy.legacy_state_sha256,
            "transfer_report": audit_policy.transfer_report_sha256,
        }
        if artifact_bindings != expected:
            mismatches = [
                f"{name}: {artifact_bindings[name]} != {expected[name]}"
                for name in sorted(expected)
                if artifact_bindings[name] != expected[name]
            ]
            raise LegacyFeatureInventoryError(
                "immutable artifact digest mismatch: " + "; ".join(mismatches)
            )

    legacy_state, legacy_metadata = _load_state(paths["legacy_state"])
    accepted_state, accepted_metadata = _load_state(paths["accepted_state"])
    report = _json_object(paths["transfer_report"])
    canary = _json_object(paths["evaluation_canary"])
    root = (
        Path(package_root).resolve()
        if package_root is not None
        else Path(__file__).resolve().parents[2]
    )
    inventory = build_legacy_feature_inventory(
        legacy_state,
        accepted_state,
        report,
        canary,
        artifact_bindings=artifact_bindings,
        architecture_binding=architecture_schema_binding(),
        tokenizer_source_binding=tokenizer_binding(root),
        compiler_source_binding=compiler_binding(root),
        policy=audit_policy,
        legacy_format=str(legacy_metadata["format"]),
        accepted_format=str(accepted_metadata["format"]),
    )
    checkpoint_metadata = accepted_metadata.get("metadata")
    if isinstance(checkpoint_metadata, Mapping):
        if checkpoint_metadata.get("legacy_state_sha256") != artifact_bindings[
            "legacy_state"
        ]:
            raise LegacyFeatureInventoryError(
                "accepted checkpoint legacy binding mismatch"
            )
        if (
            checkpoint_metadata.get("feature_transfer_schema_version")
            != MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION
        ):
            raise LegacyFeatureInventoryError(
                "accepted checkpoint transfer schema mismatch"
            )
    return inventory


def write_inventory_atomic(path: str | Path, inventory: Mapping[str, Any]) -> None:
    """Write a verified inventory without exposing a partial destination."""

    verify_inventory_digest(inventory)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                inventory,
                handle,
                allow_nan=False,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "CANONICAL_ACCEPTED_ROW_COUNT",
    "CANONICAL_ACCEPTED_STATE_SHA256",
    "CANONICAL_EVALUATION_CANARY_SHA256",
    "CANONICAL_EXACT_ROW_COUNT",
    "CANONICAL_LEGACY_ROW_COUNT",
    "CANONICAL_LEGACY_STATE_SHA256",
    "CANONICAL_OMITTED_ROW_COUNT",
    "CANONICAL_OVERRIDDEN_ROW_COUNT",
    "CANONICAL_TRANSFER_REPORT_SHA256",
    "MODAL_AUTOENCODER_FEATURE_INVENTORY_SCHEMA_VERSION",
    "LegacyFeatureInventoryError",
    "LegacyFeatureInventoryPolicy",
    "architecture_schema_binding",
    "audit_legacy_feature_inventory",
    "build_legacy_feature_inventory",
    "canonical_json_bytes",
    "compiler_binding",
    "content_sha256",
    "sha256_file",
    "tokenizer_binding",
    "verify_inventory_digest",
    "write_inventory_atomic",
]
