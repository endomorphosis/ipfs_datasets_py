"""Deterministic packed tensor storage for modal-autoencoder parameters.

The historical modal autoencoder state is deliberately convenient for CPU
code: parameters are nested Python dictionaries keyed by feature strings.  It
is, however, a poor representation for batched training.  This module gives
those keys typed, content-derived identifiers and packs each parameter map into
contiguous NumPy tensors.  A small bounded overflow keeps late vocabulary
growth from forcing a repack (and, consequently, from changing the layout
identity) during a training run.

Sample-specific decoded embeddings and sample family logits are *not*
parameters.  They may be retained by the migration sidecar for a reversible
rollout, but are never admitted to :class:`StableKeyRegistry` or a parameter
table.  The same fail-closed rule rejects raw source prose presented as a
feature or target key.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from collections.abc import Iterator, Mapping, MutableMapping, MutableSequence, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

import numpy as np


MODAL_AUTOENCODER_TENSOR_STATE_SCHEMA_VERSION = "modal-autoencoder-tensor-state-v1"
MODAL_AUTOENCODER_KEY_REGISTRY_SCHEMA_VERSION = "modal-autoencoder-stable-key-registry-v1"
MODAL_AUTOENCODER_TENSOR_LAYOUT_VERSION = "modal-autoencoder-packed-layout-v1"
DEFAULT_SPARSE_OVERFLOW_CAPACITY = 4096


class TensorStateError(RuntimeError):
    """Base class for packed-state contract violations."""


class UnsafeParameterKeyError(TensorStateError, ValueError):
    """Raised when sample identity or raw source prose reaches key storage."""


class StableKeyCollisionError(TensorStateError):
    """Raised for the astronomically unlikely stable-ID hash collision."""


class SparseOverflowFullError(TensorStateError, OverflowError):
    """Raised instead of allowing a late-key table to grow without a bound."""


class TensorKeyKind(str, Enum):
    """Disjoint namespaces used by learned modal-autoencoder parameters."""

    FEATURE = "feature"
    FAMILY = "family"
    SEMANTIC_SLOT = "semantic_slot"
    LEGAL_IR_VIEW = "legal_ir_view"
    TARGET = "target"
    INTERACTION = "interaction"


# Friendly aliases for callers written while the tensor rollout was planned.
ParameterKeyKind = TensorKeyKind
TypedKeyKind = TensorKeyKind

_KIND_CODE = {
    TensorKeyKind.FEATURE: 1,
    TensorKeyKind.FAMILY: 2,
    TensorKeyKind.SEMANTIC_SLOT: 3,
    TensorKeyKind.LEGAL_IR_VIEW: 4,
    TensorKeyKind.TARGET: 5,
    TensorKeyKind.INTERACTION: 6,
}
_SAMPLE_KEY = re.compile(
    r"^(?:(?:sample|example)[-_:#]|document[-_:#]?id[-_:#])", re.I
)
_RAW_PREFIX = re.compile(r"^(?:raw[-_: ]?(?:source|text)|source[-_: ]?(?:span|text))", re.I)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _validate_atom(kind: TensorKeyKind, value: str) -> str:
    atom = str(value)
    if not atom or atom != atom.strip():
        raise UnsafeParameterKeyError(f"{kind.value} key must be non-empty and trimmed")
    if len(atom.encode("utf-8")) > 2048 or _CONTROL.search(atom):
        raise UnsafeParameterKeyError(f"{kind.value} key contains source-like or control data")
    # Source-copy *categories* are valid typed features.  Source prose and
    # sample IDs are not.  Long structured keys use punctuation and normally
    # contain no whitespace, whereas copied clauses contain several words.
    if _RAW_PREFIX.search(atom) or _SAMPLE_KEY.search(atom):
        raise UnsafeParameterKeyError(f"{kind.value} key is sample/source identity: {atom!r}")
    words = atom.split()
    if (
        len(words) >= 4
        or (len(words) >= 3 and len(atom) > 96)
        or (len(words) >= 3 and atom.endswith((".", ";", "?", "!")))
    ):
        raise UnsafeParameterKeyError(f"raw source prose cannot be a {kind.value} key")
    return atom


@dataclass(frozen=True, slots=True)
class TypedParameterKey:
    """A typed learned-key whose 63-bit ID is stable across processes/order."""

    kind: TensorKeyKind
    value: str
    components: tuple["TypedParameterKey", ...] = ()

    def __post_init__(self) -> None:
        kind = self.kind if isinstance(self.kind, TensorKeyKind) else TensorKeyKind(str(self.kind))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", _validate_atom(kind, self.value))
        components = tuple(self.components)
        if kind is not TensorKeyKind.INTERACTION and components:
            raise ValueError("only interaction keys may contain typed components")
        if kind is TensorKeyKind.INTERACTION and components and len(components) < 2:
            raise ValueError("an interaction must have at least two typed components")
        object.__setattr__(self, "components", components)

    @property
    def stable_id(self) -> int:
        payload = self.to_dict()
        low56 = int.from_bytes(hashlib.sha256(_canonical_bytes(payload)).digest()[:7], "big")
        return (_KIND_CODE[self.kind] << 56) | low56

    @property
    def id(self) -> int:
        return self.stable_id

    @property
    def name(self) -> str:
        return self.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "components": [item.to_dict() for item in self.components],
            "kind": self.kind.value,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TypedParameterKey":
        return cls(
            TensorKeyKind(str(value["kind"])),
            str(value["value"]),
            tuple(cls.from_dict(item) for item in value.get("components", ())),
        )

    @classmethod
    def feature(cls, value: str) -> "TypedParameterKey":
        return cls(TensorKeyKind.FEATURE, value)

    @classmethod
    def family(cls, value: str) -> "TypedParameterKey":
        return cls(TensorKeyKind.FAMILY, value)

    @classmethod
    def semantic_slot(cls, value: str) -> "TypedParameterKey":
        return cls(TensorKeyKind.SEMANTIC_SLOT, value)

    @classmethod
    def legal_ir_view(cls, value: str) -> "TypedParameterKey":
        return cls(TensorKeyKind.LEGAL_IR_VIEW, value)

    @classmethod
    def target(cls, value: str) -> "TypedParameterKey":
        return cls(TensorKeyKind.TARGET, value)

    @classmethod
    def interaction(
        cls, value: str, *components: "TypedParameterKey"
    ) -> "TypedParameterKey":
        return cls(TensorKeyKind.INTERACTION, value, tuple(components))


TypedKey = TypedParameterKey


def stable_parameter_id(
    kind: TensorKeyKind | str,
    value: str,
    *,
    components: Sequence[TypedParameterKey] = (),
) -> int:
    """Return the stable numeric ID without requiring a registry instance."""

    effective_kind = kind if isinstance(kind, TensorKeyKind) else TensorKeyKind(str(kind))
    return TypedParameterKey(effective_kind, value, tuple(components)).stable_id


stable_key_id = stable_parameter_id


class StableKeyRegistry:
    """Bidirectional registry for content-derived typed IDs.

    ``version_identity`` describes the ID algorithm, not current vocabulary.
    Consequently registering an unknown key cannot invalidate a snapshot or
    CUDA layout that was built using an earlier vocabulary.
    """

    def __init__(self, keys: Sequence[TypedParameterKey] = ()) -> None:
        self._by_id: Dict[int, TypedParameterKey] = {}
        self._by_key: Dict[TypedParameterKey, int] = {}
        for key in sorted(set(keys), key=lambda item: (item.stable_id, item.kind.value, item.value)):
            self.register(key)

    @property
    def version_identity(self) -> str:
        return _digest(
            {
                "algorithm": "sha256-kind-prefix-56-v1",
                "kinds": {kind.value: code for kind, code in _KIND_CODE.items()},
                "schema_version": MODAL_AUTOENCODER_KEY_REGISTRY_SCHEMA_VERSION,
            }
        )

    @property
    def content_identity(self) -> str:
        return _digest(self.to_dict())

    def register(self, key: TypedParameterKey) -> int:
        if not isinstance(key, TypedParameterKey):
            raise TypeError("registry keys must be TypedParameterKey instances")
        stable_id = key.stable_id
        prior = self._by_id.get(stable_id)
        if prior is not None and prior != key:
            raise StableKeyCollisionError(
                f"stable key collision {stable_id}: {prior!r} versus {key!r}"
            )
        self._by_id[stable_id] = key
        self._by_key[key] = stable_id
        for component in key.components:
            self.register(component)
        return stable_id

    def id_for(
        self,
        kind_or_key: TensorKeyKind | TypedParameterKey | str,
        value: Optional[str] = None,
        *,
        create: bool = False,
    ) -> Optional[int]:
        if isinstance(kind_or_key, TypedParameterKey):
            key = kind_or_key
        else:
            if value is None:
                raise TypeError("value is required when looking up by key kind")
            kind = (
                kind_or_key
                if isinstance(kind_or_key, TensorKeyKind)
                else TensorKeyKind(str(kind_or_key))
            )
            key = TypedParameterKey(kind, value)
        found = self._by_key.get(key)
        if found is None and create:
            found = self.register(key)
        return found

    def key_for(self, stable_id: int) -> TypedParameterKey:
        try:
            return self._by_id[int(stable_id)]
        except KeyError as exc:
            raise KeyError(f"unknown stable parameter ID: {stable_id}") from exc

    resolve = key_for

    def get_or_insert(
        self, kind: TensorKeyKind | str, value: str
    ) -> int:
        stable_id = self.id_for(kind, value, create=True)
        assert stable_id is not None
        return stable_id

    def __contains__(self, key_or_id: object) -> bool:
        if isinstance(key_or_id, int):
            return key_or_id in self._by_id
        return key_or_id in self._by_key

    def __len__(self) -> int:
        return len(self._by_id)

    def keys(self, kind: Optional[TensorKeyKind] = None) -> tuple[TypedParameterKey, ...]:
        values = self._by_id.values()
        if kind is not None:
            values = (key for key in values if key.kind is kind)
        return tuple(sorted(values, key=lambda item: item.stable_id))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm_version_identity": self.version_identity,
            "keys": [
                {"stable_id": key.stable_id, **key.to_dict()}
                for key in self.keys()
            ],
            "schema_version": MODAL_AUTOENCODER_KEY_REGISTRY_SCHEMA_VERSION,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StableKeyRegistry":
        if str(value.get("schema_version") or "") != MODAL_AUTOENCODER_KEY_REGISTRY_SCHEMA_VERSION:
            raise ValueError("unsupported stable key registry schema")
        registry = cls(
            [TypedParameterKey.from_dict(item) for item in value.get("keys", ())]
        )
        expected = str(value.get("algorithm_version_identity") or registry.version_identity)
        if expected != registry.version_identity:
            raise ValueError("stable key registry algorithm identity mismatch")
        for item in value.get("keys", ()):
            key = TypedParameterKey.from_dict(item)
            if int(item.get("stable_id", key.stable_id)) != key.stable_id:
                raise ValueError("stored stable ID does not match typed key")
        return registry


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("tensor parameters must be finite")
    return number


@dataclass(frozen=True, slots=True)
class _OverflowCell:
    row_id: int
    column_id: int
    values: tuple[float, ...]


class TensorParameterTable:
    """One dense contiguous parameter tensor plus bounded sparse late cells."""

    _LAYOUTS = frozenset({"vector", "matrix", "scalar"})

    def __init__(
        self,
        *,
        name: str,
        layout: str,
        row_kind: TensorKeyKind,
        column_kind: Optional[TensorKeyKind],
        registry: StableKeyRegistry,
        row_ids: Sequence[int],
        column_ids: Sequence[int] = (),
        values: Any,
        row_component_kinds: Sequence[TensorKeyKind] = (),
        present: Any = None,
        lengths: Any = None,
        overflow_capacity: int = DEFAULT_SPARSE_OVERFLOW_CAPACITY,
        overflow: Sequence[_OverflowCell] = (),
    ) -> None:
        if layout not in self._LAYOUTS:
            raise ValueError(f"unsupported tensor table layout: {layout!r}")
        if int(overflow_capacity) < 0:
            raise ValueError("overflow_capacity must be non-negative")
        self.name = str(name)
        self.layout = layout
        self.row_kind = TensorKeyKind(row_kind)
        self.column_kind = None if column_kind is None else TensorKeyKind(column_kind)
        self.row_component_kinds = tuple(TensorKeyKind(kind) for kind in row_component_kinds)
        if self.row_component_kinds and self.row_kind is not TensorKeyKind.INTERACTION:
            raise ValueError("row component kinds require interaction rows")
        self.registry = registry
        self.row_ids = np.ascontiguousarray(row_ids, dtype=np.int64)
        self.column_ids = np.ascontiguousarray(column_ids, dtype=np.int64)
        tensor = np.asarray(values, dtype=np.float64)
        if tensor.ndim != 2:
            raise ValueError("parameter tensor must be rank two")
        self.tensor = np.ascontiguousarray(tensor)
        self.values = self.tensor  # conventional alias used by training callers
        if not np.isfinite(self.tensor).all():
            raise ValueError("parameter tensor contains a non-finite value")
        expected_shape = (
            (len(self.row_ids), 1)
            if layout == "scalar"
            else (len(self.row_ids), len(self.column_ids))
            if layout == "matrix"
            else (len(self.row_ids), self.tensor.shape[1])
        )
        if self.tensor.shape != expected_shape:
            raise ValueError(
                f"table {name!r} tensor shape {self.tensor.shape} != {expected_shape}"
            )
        self.present = np.ascontiguousarray(
            np.ones(self.tensor.shape, dtype=np.bool_) if present is None else present,
            dtype=np.bool_,
        )
        if self.present.shape != self.tensor.shape:
            raise ValueError("tensor presence mask shape mismatch")
        default_lengths = np.full(len(self.row_ids), self.tensor.shape[1], dtype=np.int64)
        self.lengths = np.ascontiguousarray(
            default_lengths if lengths is None else lengths, dtype=np.int64
        )
        if self.lengths.shape != (len(self.row_ids),):
            raise ValueError("vector length tensor shape mismatch")
        self.overflow_capacity = int(overflow_capacity)
        self._overflow: Dict[tuple[int, int], tuple[float, ...]] = {}
        self._on_mutation: Optional[Any] = None
        self._row_index = {int(value): index for index, value in enumerate(self.row_ids)}
        self._column_index = {int(value): index for index, value in enumerate(self.column_ids)}
        for cell in overflow:
            self._store_overflow(cell.row_id, cell.column_id, cell.values)

    @property
    def is_contiguous(self) -> bool:
        return bool(
            self.tensor.flags.c_contiguous
            and self.row_ids.flags.c_contiguous
            and self.column_ids.flags.c_contiguous
            and self.present.flags.c_contiguous
            and self.lengths.flags.c_contiguous
        )

    @property
    def overflow_size(self) -> int:
        return len(self._overflow)

    @property
    def overflow_remaining(self) -> int:
        return self.overflow_capacity - len(self._overflow)

    @property
    def overflow(self) -> Dict[tuple[int, int], tuple[float, ...]]:
        """Return a safe snapshot of sparse late cells keyed by stable IDs."""

        return dict(self._overflow)

    sparse_overflow = overflow

    @property
    def parameter_count(self) -> int:
        dense = int(self.present.sum())
        sparse = sum(len(values) for values in self._overflow.values())
        return dense + sparse

    def _typed(self, value: str | TypedParameterKey, kind: TensorKeyKind) -> TypedParameterKey:
        if isinstance(value, TypedParameterKey):
            if value.kind is not kind:
                raise TypeError(f"expected {kind.value} key, received {value.kind.value}")
            return value
        text = str(value)
        if kind is TensorKeyKind.INTERACTION and self.row_component_kinds:
            parts = text.split("||")
            if len(parts) == len(self.row_component_kinds):
                return TypedParameterKey.interaction(
                    text,
                    *(
                        TypedParameterKey(component_kind, part)
                        for component_kind, part in zip(self.row_component_kinds, parts)
                    ),
                )
        return TypedParameterKey(kind, text)

    def _id(self, value: str | TypedParameterKey, kind: TensorKeyKind, *, create: bool) -> int:
        # CPU rollout callers use legacy strings and therefore cannot supply
        # interaction component types.  Resolve an existing table-local ID by
        # its reversible display value before constructing a new opaque key.
        if not isinstance(value, TypedParameterKey):
            text = str(value)
            candidate_ids = (
                tuple(int(item) for item in self.row_ids)
                if kind is self.row_kind
                else tuple(int(item) for item in self.column_ids)
            )
            candidate_ids += tuple(
                item
                for pair in self._overflow
                for item in pair
                if item != 0
            )
            for stable_id in candidate_ids:
                try:
                    key = self.registry.key_for(stable_id)
                except KeyError:
                    continue
                if key.kind is kind and key.value == text:
                    return stable_id
        key = self._typed(value, kind)
        if create and self.overflow_remaining <= 0:
            raise SparseOverflowFullError(
                f"overflow table {self.name!r} is full ({self.overflow_capacity} cells)"
            )
        stable_id = self.registry.id_for(key, create=create)
        if stable_id is None:
            return key.stable_id
        return stable_id

    def _store_overflow(self, row_id: int, column_id: int, values: Sequence[float]) -> None:
        key = (int(row_id), int(column_id))
        numbers = tuple(_finite(item) for item in values)
        if key not in self._overflow and len(self._overflow) >= self.overflow_capacity:
            raise SparseOverflowFullError(
                f"overflow table {self.name!r} is full ({self.overflow_capacity} cells)"
            )
        self._overflow[key] = numbers

    def _notify_mutation(self) -> None:
        if self._on_mutation is not None:
            self._on_mutation()

    def row_values(self, row: str | TypedParameterKey) -> list[float]:
        row_id = self._id(row, self.row_kind, create=False)
        row_index = self._row_index.get(row_id)
        if self.layout == "vector":
            if row_index is not None and self.lengths[row_index] >= 0:
                return self.tensor[row_index, : int(self.lengths[row_index])].tolist()
            cell = self._overflow.get((row_id, 0))
            if cell is None:
                raise KeyError(str(getattr(row, "value", row)))
            return list(cell)
        if self.layout == "scalar":
            if row_index is not None and bool(self.present[row_index, 0]):
                return [float(self.tensor[row_index, 0])]
            cell = self._overflow.get((row_id, 0))
            if cell is None:
                raise KeyError(str(getattr(row, "value", row)))
            return list(cell)
        raise TypeError("row_values is not valid for matrix tables")

    def set_row(self, row: str | TypedParameterKey, values: Sequence[float]) -> None:
        row_id = self._id(row, self.row_kind, create=True)
        numbers = [_finite(value) for value in values]
        row_index = self._row_index.get(row_id)
        if self.layout == "scalar" and len(numbers) != 1:
            raise ValueError("scalar table rows require exactly one value")
        if row_index is not None:
            if self.layout == "vector":
                if len(numbers) > self.tensor.shape[1]:
                    self._store_overflow(row_id, 0, numbers)
                    self.lengths[row_index] = -1
                    self._notify_mutation()
                    return
                self.tensor[row_index, :] = 0.0
                self.present[row_index, :] = False
                self.tensor[row_index, : len(numbers)] = numbers
                self.present[row_index, : len(numbers)] = True
                self.lengths[row_index] = len(numbers)
            elif self.layout == "scalar":
                self.tensor[row_index, 0] = numbers[0]
                self.present[row_index, 0] = True
            else:
                raise TypeError("use set_cell for a matrix table")
            self._overflow.pop((row_id, 0), None)
            self._notify_mutation()
            return
        self._store_overflow(row_id, 0, numbers)
        self._notify_mutation()

    def delete_row(self, row: str | TypedParameterKey) -> None:
        row_id = self._id(row, self.row_kind, create=False)
        row_index = self._row_index.get(row_id)
        existed = False
        if row_index is not None:
            if self.layout == "vector" and self.lengths[row_index] >= 0:
                self.lengths[row_index] = -1
                self.present[row_index, :] = False
                existed = True
            elif self.layout == "scalar" and self.present[row_index, 0]:
                self.present[row_index, 0] = False
                existed = True
            elif self.layout == "matrix" and self.present[row_index, :].any():
                self.present[row_index, :] = False
                self.lengths[row_index] = -1
                existed = True
            elif self.layout == "matrix" and self.lengths[row_index] >= 0:
                self.lengths[row_index] = -1
                existed = True
        removed = [key for key in self._overflow if key[0] == row_id]
        for key in removed:
            del self._overflow[key]
        if not existed and not removed:
            raise KeyError(str(getattr(row, "value", row)))
        self._notify_mutation()

    def cell_value(
        self, row: str | TypedParameterKey, column: str | TypedParameterKey
    ) -> float:
        if self.layout != "matrix" or self.column_kind is None:
            raise TypeError("cell access requires a matrix table")
        row_id = self._id(row, self.row_kind, create=False)
        column_id = self._id(column, self.column_kind, create=False)
        row_index, column_index = self._row_index.get(row_id), self._column_index.get(column_id)
        if (
            row_index is not None
            and column_index is not None
            and bool(self.present[row_index, column_index])
        ):
            return float(self.tensor[row_index, column_index])
        cell = self._overflow.get((row_id, column_id))
        if cell is None:
            raise KeyError(str(getattr(column, "value", column)))
        return float(cell[0])

    def set_cell(
        self,
        row: str | TypedParameterKey,
        column: str | TypedParameterKey,
        value: float,
    ) -> None:
        if self.layout != "matrix" or self.column_kind is None:
            raise TypeError("cell access requires a matrix table")
        row_id = self._id(row, self.row_kind, create=True)
        column_id = self._id(column, self.column_kind, create=True)
        row_index, column_index = self._row_index.get(row_id), self._column_index.get(column_id)
        number = _finite(value)
        if row_index is not None and column_index is not None:
            self.tensor[row_index, column_index] = number
            self.present[row_index, column_index] = True
            self.lengths[row_index] = len(self.column_ids)
            self._overflow.pop((row_id, column_id), None)
        else:
            self._store_overflow(row_id, column_id, (number,))
        self._overflow.pop((row_id, 0), None)
        self._notify_mutation()

    def set_empty_row(self, row: str | TypedParameterKey) -> None:
        """Represent an explicitly present matrix row with no scalar cells."""

        if self.layout != "matrix":
            raise TypeError("empty-row markers are only valid for matrix tables")
        row_id = self._id(row, self.row_kind, create=True)
        row_index = self._row_index.get(row_id)
        if row_index is not None:
            self.present[row_index, :] = False
            self.lengths[row_index] = 0
            self._notify_mutation()
            return
        self._store_overflow(row_id, 0, ())
        self._notify_mutation()

    def delete_cell(
        self, row: str | TypedParameterKey, column: str | TypedParameterKey
    ) -> None:
        if self.layout != "matrix" or self.column_kind is None:
            raise TypeError("cell access requires a matrix table")
        row_id = self._id(row, self.row_kind, create=False)
        column_id = self._id(column, self.column_kind, create=False)
        row_index, column_index = self._row_index.get(row_id), self._column_index.get(column_id)
        existed = False
        if row_index is not None and column_index is not None and self.present[row_index, column_index]:
            self.present[row_index, column_index] = False
            existed = True
        if self._overflow.pop((row_id, column_id), None) is not None:
            existed = True
        if not existed:
            raise KeyError(str(getattr(column, "value", column)))
        self._notify_mutation()

    def row_keys(self) -> tuple[str, ...]:
        ids = set()
        if self.layout == "matrix":
            ids.update(
                int(self.row_ids[index])
                for index in range(len(self.row_ids))
                if self.lengths[index] >= 0
            )
        elif self.layout == "vector":
            ids.update(
                int(self.row_ids[index])
                for index in range(len(self.row_ids))
                if self.lengths[index] >= 0
            )
        else:
            ids.update(
                int(self.row_ids[index])
                for index in range(len(self.row_ids))
                if self.present[index, 0]
            )
        ids.update(row_id for row_id, _column_id in self._overflow)
        return tuple(self.registry.key_for(item).value for item in sorted(ids))

    def column_keys_for(self, row: str | TypedParameterKey) -> tuple[str, ...]:
        if self.layout != "matrix":
            raise TypeError("column keys require a matrix table")
        row_id = self._id(row, self.row_kind, create=False)
        ids = set()
        row_index = self._row_index.get(row_id)
        if row_index is not None:
            ids.update(
                int(self.column_ids[index])
                for index in range(len(self.column_ids))
                if self.present[row_index, index]
            )
        ids.update(
            column_id
            for item_row, column_id in self._overflow
            if item_row == row_id and column_id != 0
        )
        return tuple(self.registry.key_for(item).value for item in sorted(ids))

    def to_legacy_mapping(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for row in sorted(self.row_keys()):
            if self.layout == "matrix":
                result[row] = {
                    column: self.cell_value(row, column)
                    for column in sorted(self.column_keys_for(row))
                }
            elif self.layout == "scalar":
                result[row] = self.row_values(row)[0]
            else:
                result[row] = self.row_values(row)
        return result

    def to_dict(self) -> Dict[str, Any]:
        overflow = [
            {"column_id": column_id, "row_id": row_id, "values": list(values)}
            for (row_id, column_id), values in sorted(self._overflow.items())
        ]
        return {
            "column_ids": self.column_ids.tolist(),
            "column_kind": None if self.column_kind is None else self.column_kind.value,
            "layout": self.layout,
            "lengths": self.lengths.tolist(),
            "name": self.name,
            "overflow": overflow,
            "overflow_capacity": self.overflow_capacity,
            "present": self.present.astype(np.uint8).tolist(),
            "row_ids": self.row_ids.tolist(),
            "row_component_kinds": [kind.value for kind in self.row_component_kinds],
            "row_kind": self.row_kind.value,
            "tensor": self.tensor.tolist(),
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any], registry: StableKeyRegistry
    ) -> "TensorParameterTable":
        row_ids = value.get("row_ids", ())
        column_ids = value.get("column_ids", ())
        layout = str(value["layout"])
        tensor = np.asarray(value.get("tensor", ()), dtype=np.float64)
        if tensor.ndim == 1 and tensor.size == 0:
            width = 1 if layout == "scalar" else len(column_ids) if layout == "matrix" else 0
            tensor = tensor.reshape((len(row_ids), width))
        present = np.asarray(value.get("present", ()), dtype=np.bool_)
        if present.ndim == 1 and present.size == 0:
            present = present.reshape(tensor.shape)
        return cls(
            name=str(value["name"]),
            layout=layout,
            row_kind=TensorKeyKind(str(value["row_kind"])),
            row_component_kinds=[
                TensorKeyKind(str(kind))
                for kind in value.get("row_component_kinds", ())
            ],
            column_kind=(
                None
                if value.get("column_kind") is None
                else TensorKeyKind(str(value["column_kind"]))
            ),
            registry=registry,
            row_ids=row_ids,
            column_ids=column_ids,
            values=tensor,
            present=present,
            lengths=value.get("lengths"),
            overflow_capacity=int(value.get("overflow_capacity", DEFAULT_SPARSE_OVERFLOW_CAPACITY)),
            overflow=[
                _OverflowCell(
                    int(item["row_id"]),
                    int(item["column_id"]),
                    tuple(float(number) for number in item.get("values", ())),
                )
                for item in value.get("overflow", ())
            ],
        )


class _VectorProxy(MutableSequence[float]):
    def __init__(self, table: TensorParameterTable, key: str) -> None:
        self._table, self._key = table, key

    def _values(self) -> list[float]:
        return self._table.row_values(self._key)

    def __len__(self) -> int:
        return len(self._values())

    def __getitem__(self, index: Any) -> Any:
        return self._values()[index]

    def __setitem__(self, index: Any, value: Any) -> None:
        values = self._values()
        values[index] = value
        self._table.set_row(self._key, values)

    def __delitem__(self, index: Any) -> None:
        values = self._values()
        del values[index]
        self._table.set_row(self._key, values)

    def insert(self, index: int, value: float) -> None:
        values = self._values()
        values.insert(index, value)
        self._table.set_row(self._key, values)

    def __iter__(self) -> Iterator[float]:
        return iter(self._values())

    def __repr__(self) -> str:
        return repr(self._values())

    def __eq__(self, other: object) -> bool:
        try:
            return self._values() == list(other)  # type: ignore[arg-type]
        except TypeError:
            return False


class _MatrixRowProxy(MutableMapping[str, float]):
    def __init__(self, table: TensorParameterTable, row: str) -> None:
        self._table, self._row = table, row

    def __getitem__(self, column: str) -> float:
        return self._table.cell_value(self._row, column)

    def __setitem__(self, column: str, value: float) -> None:
        self._table.set_cell(self._row, column, value)

    def __delitem__(self, column: str) -> None:
        self._table.delete_cell(self._row, column)

    def __iter__(self) -> Iterator[str]:
        return iter(self._table.column_keys_for(self._row))

    def __len__(self) -> int:
        return len(self._table.column_keys_for(self._row))

    def __repr__(self) -> str:
        return repr(dict(self))


class PackedParameterMap(MutableMapping[str, Any]):
    """Dictionary-compatible CPU view backed directly by packed tensors."""

    def __init__(self, table: TensorParameterTable) -> None:
        self.table = table

    def __getitem__(self, key: str) -> Any:
        if key not in self:
            raise KeyError(key)
        if self.table.layout == "matrix":
            return _MatrixRowProxy(self.table, key)
        if self.table.layout == "scalar":
            return self.table.row_values(key)[0]
        return _VectorProxy(self.table, key)

    def __setitem__(self, key: str, value: Any) -> None:
        if self.table.layout == "matrix":
            if not isinstance(value, Mapping):
                raise TypeError("matrix rows must be mappings")
            if key in self:
                self.table.delete_row(key)
            if not value:
                self.table.set_empty_row(key)
            else:
                for column, number in value.items():
                    self.table.set_cell(key, str(column), number)
        elif self.table.layout == "scalar":
            self.table.set_row(key, (value,))
        else:
            if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
                raise TypeError("vector rows must be numeric sequences")
            self.table.set_row(key, value)

    def __delitem__(self, key: str) -> None:
        self.table.delete_row(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.table.row_keys())

    def __len__(self) -> int:
        return len(self.table.row_keys())

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        try:
            return key in self.table.row_keys()
        except (UnsafeParameterKeyError, ValueError):
            return False

    def to_dict(self) -> Dict[str, Any]:
        return self.table.to_legacy_mapping()

    def __repr__(self) -> str:
        return repr(self.to_dict())


def _proof_interaction(head: str, context: str) -> TypedParameterKey:
    head_key = TypedParameterKey.target(head)
    context_key = TypedParameterKey.target(context)
    value = json.dumps([head_key.value, context_key.value], ensure_ascii=True, separators=(",", ":"))
    return TypedParameterKey.interaction(value, head_key, context_key)


def _proof_rows(table: TensorParameterTable) -> tuple[TypedParameterKey, ...]:
    row_ids = {
        int(table.row_ids[index])
        for index in range(len(table.row_ids))
        if table.lengths[index] >= 0
    }
    row_ids.update(row_id for row_id, _column_id in table._overflow)
    return tuple(table.registry.key_for(row_id) for row_id in sorted(row_ids))


class _ProofContextMap(MutableMapping[str, MutableMapping[str, float]]):
    def __init__(self, table: TensorParameterTable, head: str) -> None:
        self._table, self._head = table, head

    def _contexts(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    key.components[1].value
                    for key in _proof_rows(self._table)
                    if len(key.components) == 2 and key.components[0].value == self._head
                }
            )
        )

    def __getitem__(self, context: str) -> MutableMapping[str, float]:
        if context not in self._contexts():
            raise KeyError(context)
        return _MatrixRowProxy(self._table, _proof_interaction(self._head, context))

    def __setitem__(self, context: str, logits: MutableMapping[str, float]) -> None:
        if not isinstance(logits, Mapping):
            raise TypeError("proof context logits must be a mapping")
        interaction = _proof_interaction(self._head, str(context))
        if context in self._contexts():
            self._table.delete_row(interaction)
        if not logits:
            self._table.set_empty_row(interaction)
        else:
            for label, value in logits.items():
                self._table.set_cell(interaction, str(label), value)

    def __delitem__(self, context: str) -> None:
        self._table.delete_row(_proof_interaction(self._head, context))

    def __iter__(self) -> Iterator[str]:
        return iter(self._contexts())

    def __len__(self) -> int:
        return len(self._contexts())


class PackedProofAuxiliaryMap(
    MutableMapping[str, MutableMapping[str, MutableMapping[str, float]]]
):
    """Legacy three-level proof-head mapping backed by one matrix tensor."""

    def __init__(self, table: TensorParameterTable) -> None:
        self.table = table

    def _heads(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    key.components[0].value
                    for key in _proof_rows(self.table)
                    if len(key.components) == 2
                }
            )
        )

    def __getitem__(self, head: str) -> MutableMapping[str, MutableMapping[str, float]]:
        if head not in self._heads():
            raise KeyError(head)
        return _ProofContextMap(self.table, head)

    def __setitem__(
        self, head: str, contexts: MutableMapping[str, MutableMapping[str, float]]
    ) -> None:
        if not isinstance(contexts, Mapping):
            raise TypeError("proof head contexts must be a mapping")
        if head in self._heads():
            del self[head]
        target = _ProofContextMap(self.table, str(head))
        for context, logits in contexts.items():
            target[str(context)] = logits

    def __delitem__(self, head: str) -> None:
        contexts = _ProofContextMap(self.table, head)
        if not contexts:
            raise KeyError(head)
        for context in tuple(contexts):
            del contexts[context]

    def __iter__(self) -> Iterator[str]:
        return iter(self._heads())

    def __len__(self) -> int:
        return len(self._heads())

    def to_dict(self) -> Dict[str, Any]:
        return {
            head: {
                context: dict(labels)
                for context, labels in self[head].items()
            }
            for head in self
        }


class ModalAutoencoderTensorState:
    """Packed parameter tables with deterministic layout and CPU accessors."""

    def __init__(
        self,
        *,
        registry: StableKeyRegistry,
        tables: Mapping[str, TensorParameterTable],
        non_parameter_state: Optional[Mapping[str, Any]] = None,
        state_metadata: Optional[Mapping[str, Any]] = None,
        table_encodings: Optional[Mapping[str, str]] = None,
        source_state_revision: int = 0,
        layout_identity: Optional[str] = None,
    ) -> None:
        self.registry = registry
        self.tables = dict(sorted(tables.items()))
        if any(table.registry is not registry for table in self.tables.values()):
            raise ValueError("all tensor tables must share the state registry")
        if not all(table.is_contiguous for table in self.tables.values()):
            raise ValueError("all packed parameter tensors must be contiguous")
        self.non_parameter_state = json.loads(json.dumps(non_parameter_state or {}))
        self.state_metadata = json.loads(json.dumps(state_metadata or {}))
        self.table_encodings = {
            str(name): str(encoding)
            for name, encoding in sorted((table_encodings or {}).items())
        }
        self.source_state_revision = max(0, int(source_state_revision))
        computed = self._compute_layout_identity()
        if layout_identity is not None and str(layout_identity) != computed:
            raise ValueError("packed tensor layout identity mismatch")
        self._layout_identity = computed
        for table in self.tables.values():
            table._on_mutation = self._mark_mutation
        self._accessors = {
            name: (
                PackedProofAuxiliaryMap(table)
                if self.table_encodings.get(name) == "proof_auxiliary_v1"
                else PackedParameterMap(table)
            )
            for name, table in self.tables.items()
        }

    def _compute_layout_identity(self) -> str:
        return _digest(
            {
                "layout_version": MODAL_AUTOENCODER_TENSOR_LAYOUT_VERSION,
                "registry_version_identity": self.registry.version_identity,
                "tables": {
                    name: {
                        "column_ids": table.column_ids.tolist(),
                        "column_kind": None if table.column_kind is None else table.column_kind.value,
                        "layout": table.layout,
                        "row_ids": table.row_ids.tolist(),
                        "row_component_kinds": [
                            kind.value for kind in table.row_component_kinds
                        ],
                        "row_kind": table.row_kind.value,
                        "shape": list(table.tensor.shape),
                    }
                    for name, table in self.tables.items()
                },
            }
        )

    @property
    def version_identity(self) -> str:
        """Stable identity of the dense layout; overflow mutations do not alter it."""

        return self._layout_identity

    @property
    def tensor_version_identity(self) -> str:
        return self._layout_identity

    @property
    def content_identity(self) -> str:
        return _digest(self.to_legacy_dict())

    @property
    def parameter_tensors(self) -> Dict[str, np.ndarray]:
        return {name: table.tensor for name, table in self.tables.items()}

    @property
    def tensors(self) -> Dict[str, np.ndarray]:
        return self.parameter_tensors

    @property
    def overflow_size(self) -> int:
        return sum(table.overflow_size for table in self.tables.values())

    @property
    def overflow_tables(self) -> Dict[str, Dict[tuple[int, int], tuple[float, ...]]]:
        return {
            name: table.overflow
            for name, table in self.tables.items()
            if table.overflow_size
        }

    @property
    def parameter_count(self) -> int:
        return sum(table.parameter_count for table in self.tables.values())

    @property
    def allocated_scalar_count(self) -> int:
        return sum(int(table.tensor.size) for table in self.tables.values())

    @property
    def state_revision(self) -> int:
        """Durable source revision retained across migration/checkpoint I/O."""

        return self.source_state_revision

    def _mark_mutation(self) -> None:
        self.source_state_revision += 1

    def mark_updated(self, revisions: int = 1) -> None:
        """Record direct/batched tensor updates performed outside CPU proxies."""

        count = int(revisions)
        if count < 0:
            raise ValueError("revision increment must be non-negative")
        self.source_state_revision += count

    def restore_revision(self, revision: int) -> None:
        value = int(revision)
        if value < 0:
            raise ValueError("state revision must be non-negative")
        self.source_state_revision = value

    def named_tensors(self) -> Iterator[tuple[str, np.ndarray]]:
        for name in sorted(self.tables):
            yield name, self.tables[name].tensor

    def table(self, name: str) -> TensorParameterTable:
        return self.tables[str(name)]

    def cpu_accessor(self, name: str) -> Any:
        return self._accessors[str(name)]

    accessor = cpu_accessor

    @property
    def cpu_accessors(self) -> Dict[str, Any]:
        return dict(self._accessors)

    cpu_maps = cpu_accessors

    def __getattr__(self, name: str) -> Any:
        accessors = self.__dict__.get("_accessors", {})
        if name in accessors:
            return accessors[name]
        raise AttributeError(name)

    def to_legacy_dict(self) -> Dict[str, Any]:
        result = json.loads(json.dumps(self.state_metadata))
        result.update(json.loads(json.dumps(self.non_parameter_state)))
        for name, table in self.tables.items():
            if self.table_encodings.get(name) == "proof_auxiliary_v1":
                proof: Dict[str, Dict[str, Dict[str, float]]] = {}
                for row_id in sorted(
                    {key_id for key_id, _ in table._overflow}
                    | {
                        int(table.row_ids[index])
                        for index in range(len(table.row_ids))
                        if table.lengths[index] >= 0
                    }
                ):
                    key = self.registry.key_for(row_id)
                    if len(key.components) != 2:
                        raise ValueError("proof auxiliary interaction key is malformed")
                    head, context = key.components[0].value, key.components[1].value
                    proof.setdefault(head, {})[context] = {
                        column: table.cell_value(key, column)
                        for column in table.column_keys_for(key)
                    }
                result[name] = proof
            else:
                result[name] = table.to_legacy_mapping()
        return {key: result[key] for key in sorted(result)}

    # Old checkpoint writers deliberately persist the rollout-compatible map
    # shape.  Readers can then choose either the old object or re-pack it.
    to_checkpoint_dict = to_legacy_dict

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layout_identity": self.version_identity,
            "layout_version": MODAL_AUTOENCODER_TENSOR_LAYOUT_VERSION,
            "non_parameter_state": self.non_parameter_state,
            "registry": self.registry.to_dict(),
            "schema_version": MODAL_AUTOENCODER_TENSOR_STATE_SCHEMA_VERSION,
            "source_state_revision": self.source_state_revision,
            "state_metadata": self.state_metadata,
            "table_encodings": self.table_encodings,
            "tables": {name: table.to_dict() for name, table in self.tables.items()},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def save_json(self, path: str | os.PathLike[str]) -> None:
        destination = os.fspath(path)
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        temporary = f"{destination}.tmp-{os.getpid()}-{threading.get_ident()}"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(self.to_json() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModalAutoencoderTensorState":
        schema = str(value.get("schema_version") or "")
        if schema != MODAL_AUTOENCODER_TENSOR_STATE_SCHEMA_VERSION:
            # Dual-read migration convenience for current map checkpoints.
            from .modal_autoencoder_state_migration import pack_modal_autoencoder_state

            return pack_modal_autoencoder_state(value)
        if str(value.get("layout_version") or "") != MODAL_AUTOENCODER_TENSOR_LAYOUT_VERSION:
            raise ValueError("unsupported modal autoencoder tensor layout")
        registry = StableKeyRegistry.from_dict(value["registry"])
        tables = {
            str(name): TensorParameterTable.from_dict(table, registry)
            for name, table in dict(value.get("tables", {})).items()
        }
        return cls(
            registry=registry,
            tables=tables,
            non_parameter_state=value.get("non_parameter_state", {}),
            state_metadata=value.get("state_metadata", {}),
            table_encodings=value.get("table_encodings", {}),
            source_state_revision=int(value.get("source_state_revision", 0)),
            layout_identity=str(value.get("layout_identity") or "") or None,
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> "ModalAutoencoderTensorState":
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return cls.from_dict(json.loads(payload))

    @classmethod
    def load_json(cls, path: str | os.PathLike[str]) -> "ModalAutoencoderTensorState":
        with open(path, "rb") as handle:
            raw = handle.read()
        if raw.startswith(b"LIRMAECP"):
            from .modal_autoencoder_state_migration import (
                load_and_pack_modal_autoencoder_checkpoint,
            )

            return load_and_pack_modal_autoencoder_checkpoint(raw)
        return cls.from_json(raw)

    def to_torch(self, *, device: Any = "cpu", dtype: Any = None) -> Dict[str, Any]:
        """Materialize contiguous torch tensors without making torch mandatory."""

        try:
            import torch
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("torch is required to materialize torch tensors") from exc
        effective_dtype = torch.float64 if dtype is None else dtype
        return {
            name: torch.as_tensor(table.tensor, dtype=effective_dtype, device=device).contiguous()
            for name, table in self.tables.items()
        }

    @classmethod
    def from_training_state(
        cls,
        state: Any,
        *,
        overflow_capacity: int = DEFAULT_SPARSE_OVERFLOW_CAPACITY,
    ) -> "ModalAutoencoderTensorState":
        from .modal_autoencoder_state_migration import pack_modal_autoencoder_state

        return pack_modal_autoencoder_state(
            state, overflow_capacity=overflow_capacity
        )

    from_legacy_state = from_training_state

    def to_training_state(self) -> Any:
        from .modal_autoencoder_state_migration import unpack_modal_autoencoder_state

        return unpack_modal_autoencoder_state(self)

    to_legacy_state = to_training_state


__all__ = [
    "DEFAULT_SPARSE_OVERFLOW_CAPACITY",
    "MODAL_AUTOENCODER_KEY_REGISTRY_SCHEMA_VERSION",
    "MODAL_AUTOENCODER_TENSOR_LAYOUT_VERSION",
    "MODAL_AUTOENCODER_TENSOR_STATE_SCHEMA_VERSION",
    "ModalAutoencoderTensorState",
    "PackedParameterMap",
    "PackedProofAuxiliaryMap",
    "ParameterKeyKind",
    "SparseOverflowFullError",
    "StableKeyCollisionError",
    "StableKeyRegistry",
    "TensorKeyKind",
    "TensorParameterTable",
    "TensorStateError",
    "TypedKey",
    "TypedKeyKind",
    "TypedParameterKey",
    "UnsafeParameterKeyError",
    "stable_key_id",
    "stable_parameter_id",
]
