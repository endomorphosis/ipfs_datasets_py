"""Deterministic migration between legacy maps and packed tensor state.

The migration is intentionally dual-read/compact-write.  It accepts the
current training object, its JSON mapping, a JSON checkpoint path, or a packed
state.  The reverse path recreates the current CPU object exactly (within the
chosen floating point dtype) and restores its durable operational revision.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import numpy as np

from .modal_autoencoder_tensor_state import (
    DEFAULT_SPARSE_OVERFLOW_CAPACITY,
    ModalAutoencoderTensorState,
    StableKeyRegistry,
    TensorKeyKind,
    TensorParameterTable,
    TypedParameterKey,
)


# (legacy field, row namespace)
_VECTOR_FIELDS: tuple[tuple[str, TensorKeyKind], ...] = (
    ("compiler_quality_embedding_weights", TensorKeyKind.TARGET),
    ("logic_signature_embedding_weights", TensorKeyKind.FEATURE),
    ("round_trip_signal_embedding_weights", TensorKeyKind.FEATURE),
    ("decompiler_plan_embedding_weights", TensorKeyKind.TARGET),
    ("predicate_argument_embedding_weights", TensorKeyKind.SEMANTIC_SLOT),
    ("feature_embedding_weights", TensorKeyKind.FEATURE),
    ("family_embedding_weights", TensorKeyKind.FAMILY),
    ("family_semantic_slot_embedding_weights", TensorKeyKind.INTERACTION),
    (
        "family_semantic_slot_legal_ir_view_embedding_weights",
        TensorKeyKind.INTERACTION,
    ),
    ("family_legal_ir_view_embedding_weights", TensorKeyKind.INTERACTION),
    ("semantic_slot_embedding_weights", TensorKeyKind.SEMANTIC_SLOT),
    ("legal_ir_view_embedding_weights", TensorKeyKind.LEGAL_IR_VIEW),
    (
        "semantic_slot_legal_ir_view_embedding_weights",
        TensorKeyKind.INTERACTION,
    ),
)

# (legacy field, row namespace, column namespace)
_MATRIX_FIELDS: tuple[tuple[str, TensorKeyKind, TensorKeyKind], ...] = (
    ("compiler_quality_family_logits", TensorKeyKind.TARGET, TensorKeyKind.FAMILY),
    ("logic_signature_family_logits", TensorKeyKind.FEATURE, TensorKeyKind.FAMILY),
    (
        "logic_signature_legal_ir_view_logits",
        TensorKeyKind.FEATURE,
        TensorKeyKind.LEGAL_IR_VIEW,
    ),
    ("round_trip_signal_family_logits", TensorKeyKind.FEATURE, TensorKeyKind.FAMILY),
    (
        "round_trip_signal_legal_ir_view_logits",
        TensorKeyKind.FEATURE,
        TensorKeyKind.LEGAL_IR_VIEW,
    ),
    ("decompiler_plan_family_logits", TensorKeyKind.TARGET, TensorKeyKind.FAMILY),
    (
        "decompiler_plan_legal_ir_view_logits",
        TensorKeyKind.TARGET,
        TensorKeyKind.LEGAL_IR_VIEW,
    ),
    (
        "predicate_argument_family_logits",
        TensorKeyKind.SEMANTIC_SLOT,
        TensorKeyKind.FAMILY,
    ),
    (
        "predicate_argument_legal_ir_view_logits",
        TensorKeyKind.SEMANTIC_SLOT,
        TensorKeyKind.LEGAL_IR_VIEW,
    ),
    ("feature_family_logits", TensorKeyKind.FEATURE, TensorKeyKind.FAMILY),
    (
        "semantic_slot_family_logits",
        TensorKeyKind.SEMANTIC_SLOT,
        TensorKeyKind.FAMILY,
    ),
    (
        "legal_ir_view_family_logits",
        TensorKeyKind.LEGAL_IR_VIEW,
        TensorKeyKind.FAMILY,
    ),
    (
        "feature_legal_ir_view_logits",
        TensorKeyKind.FEATURE,
        TensorKeyKind.LEGAL_IR_VIEW,
    ),
    (
        "family_semantic_slot_legal_ir_view_logits",
        TensorKeyKind.INTERACTION,
        TensorKeyKind.LEGAL_IR_VIEW,
    ),
    (
        "semantic_slot_legal_ir_view_family_logits",
        TensorKeyKind.INTERACTION,
        TensorKeyKind.FAMILY,
    ),
    (
        "semantic_slot_legal_ir_view_logits",
        TensorKeyKind.SEMANTIC_SLOT,
        TensorKeyKind.LEGAL_IR_VIEW,
    ),
)

_SCALAR_FIELDS: tuple[tuple[str, TensorKeyKind], ...] = (
    ("legal_ir_view_logits", TensorKeyKind.LEGAL_IR_VIEW),
)
_SAMPLE_MEMORY_FIELDS = frozenset({"decoded_embeddings", "family_logits"})
_PARAMETER_FIELDS = frozenset(
    [name for name, _kind in _VECTOR_FIELDS]
    + [name for name, _row, _column in _MATRIX_FIELDS]
    + [name for name, _kind in _SCALAR_FIELDS]
    + ["proof_auxiliary_head_logits"]
)


def _interaction_components(field: str) -> tuple[TensorKeyKind, ...]:
    if field.startswith("family_semantic_slot_legal_ir_view"):
        return (
            TensorKeyKind.FAMILY,
            TensorKeyKind.SEMANTIC_SLOT,
            TensorKeyKind.LEGAL_IR_VIEW,
        )
    if field.startswith("family_semantic_slot"):
        return (TensorKeyKind.FAMILY, TensorKeyKind.SEMANTIC_SLOT)
    if field.startswith("family_legal_ir_view"):
        return (TensorKeyKind.FAMILY, TensorKeyKind.LEGAL_IR_VIEW)
    if field.startswith("semantic_slot_legal_ir_view"):
        return (TensorKeyKind.SEMANTIC_SLOT, TensorKeyKind.LEGAL_IR_VIEW)
    return ()


def _typed_key(field: str, kind: TensorKeyKind, raw: Any) -> TypedParameterKey:
    text = str(raw)
    if kind is not TensorKeyKind.INTERACTION:
        return TypedParameterKey(kind, text)
    component_kinds = _interaction_components(field)
    parts = text.split("||")
    components: tuple[TypedParameterKey, ...] = ()
    if component_kinds and len(parts) == len(component_kinds):
        components = tuple(
            TypedParameterKey(component_kind, part)
            for component_kind, part in zip(component_kinds, parts)
        )
    # Old states occasionally contain opaque interaction strings.  They are
    # still safely typed in the interaction namespace; structured strings get
    # component IDs as well for future factorized heads.
    return TypedParameterKey(TensorKeyKind.INTERACTION, text, components)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"legacy state field {field!r} must be a mapping")
    return value


def _vector_table(
    name: str,
    kind: TensorKeyKind,
    raw: Mapping[str, Any],
    registry: StableKeyRegistry,
    overflow_capacity: int,
) -> TensorParameterTable:
    records: list[tuple[TypedParameterKey, list[float]]] = []
    for raw_key, raw_vector in raw.items():
        if isinstance(raw_vector, (str, bytes)) or not isinstance(raw_vector, Sequence):
            raise TypeError(f"vector field {name!r} row {raw_key!r} must be a sequence")
        key = _typed_key(name, kind, raw_key)
        vector = [float(value) for value in raw_vector]
        records.append((key, vector))
    records.sort(key=lambda pair: pair[0].stable_id)
    width = max((len(vector) for _key, vector in records), default=0)
    tensor = np.zeros((len(records), width), dtype=np.float64)
    present = np.zeros((len(records), width), dtype=np.bool_)
    lengths = np.zeros(len(records), dtype=np.int64)
    row_ids = []
    for row, (key, vector) in enumerate(records):
        row_ids.append(registry.register(key))
        if vector:
            tensor[row, : len(vector)] = vector
            present[row, : len(vector)] = True
        lengths[row] = len(vector)
    return TensorParameterTable(
        name=name,
        layout="vector",
        row_kind=kind,
        column_kind=None,
        row_component_kinds=(
            _interaction_components(name)
            if kind is TensorKeyKind.INTERACTION
            else ()
        ),
        registry=registry,
        row_ids=row_ids,
        values=tensor,
        present=present,
        lengths=lengths,
        overflow_capacity=overflow_capacity,
    )


def _matrix_table(
    name: str,
    row_kind: TensorKeyKind,
    column_kind: TensorKeyKind,
    raw: Mapping[str, Any],
    registry: StableKeyRegistry,
    overflow_capacity: int,
) -> TensorParameterTable:
    rows: list[tuple[TypedParameterKey, Mapping[str, Any]]] = []
    column_keys: Dict[int, TypedParameterKey] = {}
    for raw_row, raw_values in raw.items():
        row_key = _typed_key(name, row_kind, raw_row)
        values = _mapping(raw_values, field=f"{name}.{raw_row}")
        rows.append((row_key, values))
        for raw_column in values:
            key = TypedParameterKey(column_kind, str(raw_column))
            column_keys[key.stable_id] = key
    rows.sort(key=lambda pair: pair[0].stable_id)
    columns = [column_keys[key_id] for key_id in sorted(column_keys)]
    row_ids = [registry.register(key) for key, _values in rows]
    column_ids = [registry.register(key) for key in columns]
    column_index = {key.value: index for index, key in enumerate(columns)}
    tensor = np.zeros((len(rows), len(columns)), dtype=np.float64)
    present = np.zeros(tensor.shape, dtype=np.bool_)
    for row_index, (_row_key, values) in enumerate(rows):
        for raw_column, raw_value in values.items():
            index = column_index[str(raw_column)]
            tensor[row_index, index] = float(raw_value)
            present[row_index, index] = True
    return TensorParameterTable(
        name=name,
        layout="matrix",
        row_kind=row_kind,
        column_kind=column_kind,
        row_component_kinds=(
            _interaction_components(name)
            if row_kind is TensorKeyKind.INTERACTION
            else ()
        ),
        registry=registry,
        row_ids=row_ids,
        column_ids=column_ids,
        values=tensor,
        present=present,
        overflow_capacity=overflow_capacity,
    )


def _scalar_table(
    name: str,
    kind: TensorKeyKind,
    raw: Mapping[str, Any],
    registry: StableKeyRegistry,
    overflow_capacity: int,
) -> TensorParameterTable:
    records = sorted(
        ((_typed_key(name, kind, key), float(value)) for key, value in raw.items()),
        key=lambda pair: pair[0].stable_id,
    )
    return TensorParameterTable(
        name=name,
        layout="scalar",
        row_kind=kind,
        column_kind=None,
        registry=registry,
        row_ids=[registry.register(key) for key, _value in records],
        values=np.asarray([[value] for _key, value in records], dtype=np.float64).reshape((-1, 1)),
        present=np.ones((len(records), 1), dtype=np.bool_),
        overflow_capacity=overflow_capacity,
    )


def _proof_table(
    raw: Mapping[str, Any],
    registry: StableKeyRegistry,
    overflow_capacity: int,
) -> TensorParameterTable:
    flattened: Dict[TypedParameterKey, Mapping[str, Any]] = {}
    for raw_head, raw_contexts in raw.items():
        head = TypedParameterKey.target(str(raw_head))
        for raw_context, raw_logits in _mapping(
            raw_contexts, field=f"proof_auxiliary_head_logits.{raw_head}"
        ).items():
            context = TypedParameterKey.target(str(raw_context))
            value = json.dumps([head.value, context.value], ensure_ascii=True, separators=(",", ":"))
            key = TypedParameterKey.interaction(value, head, context)
            flattened[key] = _mapping(
                raw_logits,
                field=f"proof_auxiliary_head_logits.{raw_head}.{raw_context}",
            )
    # Build directly because ordinary migration stringifies row keys.
    rows = sorted(flattened.items(), key=lambda pair: pair[0].stable_id)
    column_by_id: Dict[int, TypedParameterKey] = {}
    for _row, logits in rows:
        for label in logits:
            key = TypedParameterKey.target(str(label))
            column_by_id[key.stable_id] = key
    columns = [column_by_id[item] for item in sorted(column_by_id)]
    column_index = {key.value: index for index, key in enumerate(columns)}
    tensor = np.zeros((len(rows), len(columns)), dtype=np.float64)
    present = np.zeros(tensor.shape, dtype=np.bool_)
    for row_index, (_key, logits) in enumerate(rows):
        for label, value in logits.items():
            column = column_index[str(label)]
            tensor[row_index, column] = float(value)
            present[row_index, column] = True
    return TensorParameterTable(
        name="proof_auxiliary_head_logits",
        layout="matrix",
        row_kind=TensorKeyKind.INTERACTION,
        column_kind=TensorKeyKind.TARGET,
        registry=registry,
        row_ids=[registry.register(key) for key, _logits in rows],
        column_ids=[registry.register(key) for key in columns],
        values=tensor,
        present=present,
        overflow_capacity=overflow_capacity,
    )


def _state_mapping(state: Any) -> tuple[Dict[str, Any], int]:
    if isinstance(state, ModalAutoencoderTensorState):
        return state.to_legacy_dict(), state.source_state_revision
    if isinstance(state, Mapping):
        return dict(state), int(state.get("state_revision", 0) or 0)
    to_dict = getattr(state, "to_dict", None)
    if not callable(to_dict):
        raise TypeError(f"unsupported modal autoencoder state: {type(state).__name__}")
    value = to_dict()
    if not isinstance(value, Mapping):
        raise TypeError("state.to_dict() must return a mapping")
    return dict(value), int(getattr(state, "state_revision", 0))


def pack_modal_autoencoder_state(
    state: Any,
    *,
    overflow_capacity: int = DEFAULT_SPARSE_OVERFLOW_CAPACITY,
) -> ModalAutoencoderTensorState:
    """Pack a current map state deterministically, independent of map order."""

    if isinstance(state, ModalAutoencoderTensorState):
        return state
    if int(overflow_capacity) < 0:
        raise ValueError("overflow_capacity must be non-negative")
    data, revision = _state_mapping(state)
    registry = StableKeyRegistry()
    tables: Dict[str, TensorParameterTable] = {}
    for name, kind in _VECTOR_FIELDS:
        tables[name] = _vector_table(
            name,
            kind,
            _mapping(data.get(name, {}), field=name),
            registry,
            int(overflow_capacity),
        )
    for name, row_kind, column_kind in _MATRIX_FIELDS:
        tables[name] = _matrix_table(
            name,
            row_kind,
            column_kind,
            _mapping(data.get(name, {}), field=name),
            registry,
            int(overflow_capacity),
        )
    for name, kind in _SCALAR_FIELDS:
        tables[name] = _scalar_table(
            name,
            kind,
            _mapping(data.get(name, {}), field=name),
            registry,
            int(overflow_capacity),
        )
    tables["proof_auxiliary_head_logits"] = _proof_table(
        _mapping(data.get("proof_auxiliary_head_logits", {}), field="proof_auxiliary_head_logits"),
        registry,
        int(overflow_capacity),
    )

    non_parameter = {
        name: data.get(name, {}) for name in sorted(_SAMPLE_MEMORY_FIELDS)
    }
    metadata = {
        str(name): value
        for name, value in sorted(data.items())
        if name not in _PARAMETER_FIELDS and name not in _SAMPLE_MEMORY_FIELDS
    }
    return ModalAutoencoderTensorState(
        registry=registry,
        tables=tables,
        non_parameter_state=non_parameter,
        state_metadata=metadata,
        table_encodings={"proof_auxiliary_head_logits": "proof_auxiliary_v1"},
        source_state_revision=revision,
    )


# Names used by rollout call sites and migration scripts.
migrate_legacy_state = pack_modal_autoencoder_state
pack_training_state = pack_modal_autoencoder_state


def unpack_modal_autoencoder_state(
    state: ModalAutoencoderTensorState,
    *,
    as_mapping: bool = False,
) -> Any:
    """Restore a packed state to the current map object or a plain mapping."""

    if not isinstance(state, ModalAutoencoderTensorState):
        raise TypeError("state must be ModalAutoencoderTensorState")
    data = state.to_legacy_dict()
    if as_mapping:
        return data
    from .modal_autoencoder import ModalAutoencoderTrainingState

    restored = ModalAutoencoderTrainingState.from_dict(data)
    tracker = getattr(restored, "_state_identity_tracker", None)
    restore_revision = getattr(tracker, "restore_revision", None)
    if callable(restore_revision):
        restore_revision(state.source_state_revision)
    return restored


restore_legacy_state = unpack_modal_autoencoder_state
unpack_training_state = unpack_modal_autoencoder_state


def load_and_pack_modal_autoencoder_checkpoint(
    source: str | Path | bytes | Mapping[str, Any],
    *,
    overflow_capacity: int = DEFAULT_SPARSE_OVERFLOW_CAPACITY,
) -> ModalAutoencoderTensorState:
    """Dual-read a JSON/current compact checkpoint and return packed state."""

    if isinstance(source, Mapping):
        data = dict(source)
        if data.get("schema_version") == "modal-autoencoder-tensor-state-v1":
            return ModalAutoencoderTensorState.from_dict(data)
        return pack_modal_autoencoder_state(data, overflow_capacity=overflow_capacity)
    if isinstance(source, bytes):
        if source.startswith(b"LIRMAECP"):
            from .modal_autoencoder_checkpoint import deserialize_checkpoint

            loaded = deserialize_checkpoint(source)
            return pack_modal_autoencoder_state(
                loaded.state, overflow_capacity=overflow_capacity
            )
        return load_and_pack_modal_autoencoder_checkpoint(
            json.loads(source.decode("utf-8")),
            overflow_capacity=overflow_capacity,
        )
    if isinstance(source, str) and source.lstrip().startswith("{"):
        return load_and_pack_modal_autoencoder_checkpoint(
            json.loads(source), overflow_capacity=overflow_capacity
        )
    path = Path(source)
    raw = path.read_bytes()
    if raw.startswith(b"LIRMAECP"):
        from .modal_autoencoder_checkpoint import load_checkpoint

        loaded = load_checkpoint(path)
        return pack_modal_autoencoder_state(
            loaded.state, overflow_capacity=overflow_capacity
        )
    return load_and_pack_modal_autoencoder_checkpoint(
        json.loads(raw.decode("utf-8")), overflow_capacity=overflow_capacity
    )


migrate_json_checkpoint = load_and_pack_modal_autoencoder_checkpoint
migrate_checkpoint = load_and_pack_modal_autoencoder_checkpoint


__all__ = [
    "load_and_pack_modal_autoencoder_checkpoint",
    "migrate_checkpoint",
    "migrate_json_checkpoint",
    "migrate_legacy_state",
    "pack_modal_autoencoder_state",
    "pack_training_state",
    "restore_legacy_state",
    "unpack_modal_autoencoder_state",
    "unpack_training_state",
]
