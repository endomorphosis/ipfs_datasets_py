"""Deterministic migration between legacy maps and packed tensor state.

The migration is intentionally dual-read/compact-write.  It accepts the
current training object, its JSON mapping, a JSON checkpoint path, or a packed
state.  The reverse path recreates the current CPU object exactly (within the
chosen floating point dtype) and restores its durable operational revision.
"""

from __future__ import annotations

import hashlib
import json
import math
import zlib
from dataclasses import dataclass, field
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

# The packed tensor migration above remains the dual-read path for legacy
# checkpoints.  PORTAL-LIR-HAMMER-109 adds a compact-write path for the three
# Cartesian semantic interaction tables.  Imports are local in public
# functions where possible so old packed-state consumers do not pay for NumPy
# fitting or create a circular import during package initialization.


@dataclass(frozen=True, slots=True)
class FactorizedStateMigrationConfig:
    """Fail-closed policy for migrating the high-cardinality head family."""

    rank: int = 8
    residual_capacity: int = 4096
    tolerance: float = 1.0e-6
    fitting_steps: int = 600
    learning_rate: float = 0.035
    regularization: float = 1.0e-8
    seed: int = 0
    minimum_state_reduction: float = 4.0
    enforce_minimum_reduction: bool = True
    verified_exceptions: Mapping[str, Mapping[tuple[str, str, str], str]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if int(self.rank) < 0:
            raise ValueError("rank must be non-negative")
        if int(self.residual_capacity) < 0:
            raise ValueError("residual_capacity must be non-negative")
        if not math.isfinite(float(self.tolerance)) or float(self.tolerance) < 0.0:
            raise ValueError("tolerance must be finite and non-negative")
        if (
            not math.isfinite(float(self.minimum_state_reduction))
            or float(self.minimum_state_reduction) <= 0.0
        ):
            raise ValueError("minimum_state_reduction must be finite and positive")

    def head_config(self) -> Any:
        from .modal_autoencoder_factorized_heads import FactorizedHeadConfig

        return FactorizedHeadConfig(
            rank=self.rank,
            residual_capacity=self.residual_capacity,
            tolerance=self.tolerance,
            fitting_steps=self.fitting_steps,
            learning_rate=self.learning_rate,
            regularization=self.regularization,
            seed=self.seed,
        )


@dataclass(frozen=True, slots=True)
class FactorizedStateMigrationReport:
    """Compression, fidelity, and residual evidence for the full head family."""

    head_reports: Mapping[str, Any]
    legacy_parameter_bytes: int
    factorized_parameter_bytes: int
    legacy_checkpoint_bytes: int
    factorized_checkpoint_bytes: int
    minimum_state_reduction: float
    source_state_digest: str

    @property
    def parameter_reduction_ratio(self) -> float:
        if self.factorized_parameter_bytes <= 0:
            return math.inf if self.legacy_parameter_bytes else 0.0
        return self.legacy_parameter_bytes / self.factorized_parameter_bytes

    @property
    def checkpoint_reduction_ratio(self) -> float:
        if self.factorized_checkpoint_bytes <= 0:
            return math.inf if self.legacy_checkpoint_bytes else 0.0
        return self.legacy_checkpoint_bytes / self.factorized_checkpoint_bytes

    @property
    def max_absolute_error(self) -> float:
        return max(
            (float(report.max_absolute_error) for report in self.head_reports.values()),
            default=0.0,
        )

    @property
    def residual_count(self) -> int:
        return sum(int(report.residual_count) for report in self.head_reports.values())

    @property
    def accepted(self) -> bool:
        return (
            all(bool(report.logits_preserved) for report in self.head_reports.values())
            and self.parameter_reduction_ratio >= self.minimum_state_reduction
            and self.checkpoint_reduction_ratio >= self.minimum_state_reduction
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "checkpoint_reduction_ratio": round(self.checkpoint_reduction_ratio, 12),
            "factorized_checkpoint_bytes": self.factorized_checkpoint_bytes,
            "factorized_parameter_bytes": self.factorized_parameter_bytes,
            "head_reports": {
                name: report.to_dict() for name, report in sorted(self.head_reports.items())
            },
            "legacy_checkpoint_bytes": self.legacy_checkpoint_bytes,
            "legacy_parameter_bytes": self.legacy_parameter_bytes,
            "max_absolute_error": self.max_absolute_error,
            "minimum_state_reduction": self.minimum_state_reduction,
            "parameter_reduction_ratio": round(self.parameter_reduction_ratio, 12),
            "residual_count": self.residual_count,
            "source_state_digest": self.source_state_digest,
        }


@dataclass(frozen=True, slots=True)
class FactorizedStateMigrationResult:
    heads: Any
    report: FactorizedStateMigrationReport

    @property
    def accepted(self) -> bool:
        return self.report.accepted


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


def _canonical_state_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _split_interaction_key(raw: Any, width: int, *, field: str) -> tuple[str, ...]:
    parts = tuple(str(raw).split("||"))
    if len(parts) != width or any(not part for part in parts):
        raise ValueError(
            f"legacy field {field!r} has malformed {width}-part interaction key {raw!r}"
        )
    return parts


def _legacy_factorized_records(
    data: Mapping[str, Any],
) -> Dict[str, Dict[tuple[str, str, str], Any]]:
    """Normalize all legacy layouts to the canonical (family, slot, view) key."""

    from .modal_autoencoder_factorized_heads import (
        FAMILY_LOGIT_HEAD,
        LEGAL_IR_VIEW_LOGIT_HEAD,
        TRIPLE_EMBEDDING_HEAD,
    )

    embedding: Dict[tuple[str, str, str], Any] = {}
    for raw_key, vector in _mapping(
        data.get(TRIPLE_EMBEDDING_HEAD, {}), field=TRIPLE_EMBEDDING_HEAD
    ).items():
        family, slot, view = _split_interaction_key(
            raw_key, 3, field=TRIPLE_EMBEDDING_HEAD
        )
        if isinstance(vector, (str, bytes)) or not isinstance(vector, Sequence):
            raise TypeError(f"{TRIPLE_EMBEDDING_HEAD}.{raw_key} must be a vector")
        embedding[(family, slot, view)] = tuple(float(value) for value in vector)

    legal_logits: Dict[tuple[str, str, str], float] = {}
    for raw_key, raw_logits in _mapping(
        data.get(LEGAL_IR_VIEW_LOGIT_HEAD, {}), field=LEGAL_IR_VIEW_LOGIT_HEAD
    ).items():
        family, slot = _split_interaction_key(
            raw_key, 2, field=LEGAL_IR_VIEW_LOGIT_HEAD
        )
        for raw_view, value in _mapping(
            raw_logits, field=f"{LEGAL_IR_VIEW_LOGIT_HEAD}.{raw_key}"
        ).items():
            legal_logits[(family, slot, str(raw_view))] = float(value)

    family_logits: Dict[tuple[str, str, str], float] = {}
    for raw_key, raw_logits in _mapping(
        data.get(FAMILY_LOGIT_HEAD, {}), field=FAMILY_LOGIT_HEAD
    ).items():
        slot, view = _split_interaction_key(raw_key, 2, field=FAMILY_LOGIT_HEAD)
        for raw_family, value in _mapping(
            raw_logits, field=f"{FAMILY_LOGIT_HEAD}.{raw_key}"
        ).items():
            family_logits[(str(raw_family), slot, view)] = float(value)
    return {
        TRIPLE_EMBEDDING_HEAD: embedding,
        LEGAL_IR_VIEW_LOGIT_HEAD: legal_logits,
        FAMILY_LOGIT_HEAD: family_logits,
    }


def migrate_modal_autoencoder_factorized_heads(
    state: Any,
    *,
    config: Optional[FactorizedStateMigrationConfig] = None,
) -> FactorizedStateMigrationResult:
    """Compact the three unbounded semantic tables into typed factorized heads.

    The migration is fail-closed: observed values must reconstruct within the
    declared tolerance, residual capacity is a hard bound, and (by default)
    both numeric parameters and compressed checkpoint bytes must fall by at
    least fourfold.  Small test fixtures may explicitly lower the reduction
    target; production callers should retain the default.
    """

    from .modal_autoencoder_factorized_heads import (
        FACTORIZED_HEADS_SCHEMA_VERSION,
        FAMILY_LOGIT_HEAD,
        LEGAL_IR_VIEW_LOGIT_HEAD,
        TRIPLE_EMBEDDING_HEAD,
        FactorizedMigrationError,
        FactorizedSemanticInteractionHeads,
        factorize_interaction_records,
    )

    effective = config or FactorizedStateMigrationConfig()
    data, _revision = _state_mapping(state)
    records = _legacy_factorized_records(data)
    source_projection = {
        name: data.get(name, {})
        for name in (TRIPLE_EMBEDDING_HEAD, LEGAL_IR_VIEW_LOGIT_HEAD, FAMILY_LOGIT_HEAD)
    }
    source_digest = hashlib.sha256(_canonical_state_bytes(source_projection)).hexdigest()
    heads: Dict[str, Any] = {}
    reports: Dict[str, Any] = {}
    for offset, name in enumerate(
        (TRIPLE_EMBEDDING_HEAD, LEGAL_IR_VIEW_LOGIT_HEAD, FAMILY_LOGIT_HEAD)
    ):
        values = records[name]
        # Empty legacy fields carry no parameters and do not need a placeholder
        # head.  This also avoids inventing vocabularies during partial rollout.
        if not values:
            continue
        first = next(iter(values.values()))
        width = len(first) if isinstance(first, Sequence) else 1
        labels = tuple(str(index) for index in range(width))
        head_config = effective.head_config()
        head_config = type(head_config)(
            **{**head_config.to_dict(), "seed": int(effective.seed) + offset}
        )
        head, report = factorize_interaction_records(
            values,
            name=name,
            config=head_config,
            output_labels=labels,
            verified_exceptions=effective.verified_exceptions.get(name),
        )
        heads[name] = head
        reports[name] = report
    bundle = FactorizedSemanticInteractionHeads(
        heads=heads,
        migration_reports=reports,
        source_state_digest=source_digest,
        metadata={
            "architecture": "typed-additive-cp-low-rank-bounded-residual",
            "legacy_fields": [
                TRIPLE_EMBEDDING_HEAD,
                LEGAL_IR_VIEW_LOGIT_HEAD,
                FAMILY_LOGIT_HEAD,
            ],
            "schema_version": FACTORIZED_HEADS_SCHEMA_VERSION,
        },
    )
    legacy_parameter_bytes = sum(report.legacy_parameter_bytes for report in reports.values())
    factorized_parameter_bytes = bundle.parameter_bytes
    # Compare actual deterministic compressed encodings of the scoped state.
    legacy_checkpoint_bytes = len(zlib.compress(_canonical_state_bytes(source_projection), 9))
    factorized_checkpoint_bytes = bundle.checkpoint_bytes
    migration_report = FactorizedStateMigrationReport(
        head_reports=reports,
        legacy_parameter_bytes=legacy_parameter_bytes,
        factorized_parameter_bytes=factorized_parameter_bytes,
        legacy_checkpoint_bytes=legacy_checkpoint_bytes,
        factorized_checkpoint_bytes=factorized_checkpoint_bytes,
        minimum_state_reduction=float(effective.minimum_state_reduction),
        source_state_digest=source_digest,
    )
    if effective.enforce_minimum_reduction and not migration_report.accepted:
        reasons = []
        if migration_report.parameter_reduction_ratio < effective.minimum_state_reduction:
            reasons.append(
                "parameter reduction "
                f"{migration_report.parameter_reduction_ratio:.3f}x < "
                f"{effective.minimum_state_reduction:.3f}x"
            )
        if migration_report.checkpoint_reduction_ratio < effective.minimum_state_reduction:
            reasons.append(
                "checkpoint reduction "
                f"{migration_report.checkpoint_reduction_ratio:.3f}x < "
                f"{effective.minimum_state_reduction:.3f}x"
            )
        if not all(report.logits_preserved for report in reports.values()):
            reasons.append("canonical logits exceeded migration tolerance")
        raise FactorizedMigrationError("factorized state migration rejected: " + "; ".join(reasons))
    return FactorizedStateMigrationResult(heads=bundle, report=migration_report)


def factorize_modal_autoencoder_state(
    state: Any,
    *,
    config: Optional[FactorizedStateMigrationConfig] = None,
) -> Any:
    """Convenience API returning only the compact factorized head bundle."""

    return migrate_modal_autoencoder_factorized_heads(state, config=config).heads


def materialize_legacy_interaction_tables(
    heads: Any,
    *,
    observed_only: bool = False,
) -> Dict[str, Any]:
    """Materialize legacy maps for rollback/read compatibility.

    ``observed_only`` restricts output to residual-backed cells.  The default
    emits each known typed Cartesian product and is appropriate for an old
    reader that cannot consume the factorized checkpoint directly.
    """

    from .modal_autoencoder_factorized_heads import (
        FAMILY_LOGIT_HEAD,
        LEGAL_IR_VIEW_LOGIT_HEAD,
        TRIPLE_EMBEDDING_HEAD,
        FactorizedSemanticInteractionHeads,
    )

    if not isinstance(heads, FactorizedSemanticInteractionHeads):
        raise TypeError("heads must be FactorizedSemanticInteractionHeads")
    result: Dict[str, Any] = {
        TRIPLE_EMBEDDING_HEAD: {},
        LEGAL_IR_VIEW_LOGIT_HEAD: {},
        FAMILY_LOGIT_HEAD: {},
    }
    for name, head in heads.heads.items():
        if observed_only:
            triples = [residual.key for residual in head.residuals]
        else:
            triples = [
                (family, slot, view)
                for family in head.families
                for slot in head.semantic_slots
                for view in head.legal_ir_views
            ]
        if name == TRIPLE_EMBEDDING_HEAD:
            for family, slot, view in triples:
                result[name][f"{family}||{slot}||{view}"] = [
                    float(value) for value in head.forward(family, slot, view)
                ]
        elif name == LEGAL_IR_VIEW_LOGIT_HEAD:
            for family, slot, view in triples:
                result[name].setdefault(f"{family}||{slot}", {})[view] = head.scalar(
                    family, slot, view
                )
        elif name == FAMILY_LOGIT_HEAD:
            for family, slot, view in triples:
                result[name].setdefault(f"{slot}||{view}", {})[family] = head.scalar(
                    family, slot, view
                )
    return result


def load_factorized_head_checkpoint(source: str | Path | bytes | Mapping[str, Any]) -> Any:
    """Load deterministic JSON or compact factorized-head checkpoint bytes."""

    from .modal_autoencoder_factorized_heads import (
        FACTORIZED_HEAD_CHECKPOINT_MAGIC,
        FactorizedSemanticInteractionHeads,
    )

    if isinstance(source, Mapping):
        return FactorizedSemanticInteractionHeads.from_dict(source)
    if isinstance(source, bytes):
        if source.startswith(FACTORIZED_HEAD_CHECKPOINT_MAGIC):
            return FactorizedSemanticInteractionHeads.from_checkpoint_bytes(source)
        return FactorizedSemanticInteractionHeads.from_dict(json.loads(source.decode("utf-8")))
    if isinstance(source, str) and source.lstrip().startswith("{"):
        return FactorizedSemanticInteractionHeads.from_dict(json.loads(source))
    return load_factorized_head_checkpoint(Path(source).read_bytes())


# Migration-script aliases kept deliberately explicit for discoverability.
migrate_state_to_factorized_heads = migrate_modal_autoencoder_factorized_heads
restore_factorized_heads_to_legacy = materialize_legacy_interaction_tables


__all__ = [
    "FactorizedStateMigrationConfig",
    "FactorizedStateMigrationReport",
    "FactorizedStateMigrationResult",
    "factorize_modal_autoencoder_state",
    "load_and_pack_modal_autoencoder_checkpoint",
    "load_factorized_head_checkpoint",
    "materialize_legacy_interaction_tables",
    "migrate_checkpoint",
    "migrate_json_checkpoint",
    "migrate_legacy_state",
    "migrate_modal_autoencoder_factorized_heads",
    "migrate_state_to_factorized_heads",
    "pack_modal_autoencoder_state",
    "pack_training_state",
    "restore_legacy_state",
    "restore_factorized_heads_to_legacy",
    "unpack_modal_autoencoder_state",
    "unpack_training_state",
]
