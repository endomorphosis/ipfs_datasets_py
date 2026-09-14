"""Closed advisory projection contracts for SPAR function/module semantic views.

This module owns ``SemanticProjection@1`` and ``ProjectionUnavailable@1``.
Records are advisory only: they never establish semantic, task, merge, vector,
or completion authority, and they cannot suppress raw-source fallback.

Projection identity binds subject, view, exact model/tokenizer/preprocessor/
profile, dimension, metric, dtype, byte order, quantization, vector bytes,
privacy, and availability.  Nonfinite or mismatched vectors fail closed.
Unavailable neural capability is a typed ``ProjectionUnavailable@1`` residual;
deterministic structural fingerprints remain usable for every declared view.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
import math
import struct
import unicodedata
from typing import Any, ClassVar, Final, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)


SEMANTIC_PROJECTION_INTERFACE: Final[str] = "SemanticProjection@1"
PROJECTION_UNAVAILABLE_INTERFACE: Final[str] = "ProjectionUnavailable@1"
STRUCTURAL_FINGERPRINT_INTERFACE: Final[str] = "StructuralFingerprint@1"
SEMANTIC_PROJECTION_SET_INTERFACE: Final[str] = "SemanticProjectionSet@1"

SEMANTIC_PROJECTION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.semantic-projection@1"
)
PROJECTION_UNAVAILABLE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.projection-unavailable@1"
)
STRUCTURAL_FINGERPRINT_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.structural-fingerprint@1"
)
SEMANTIC_PROJECTION_SET_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.semantic-projection-set@1"
)
PROJECTION_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.projection-subject@1"
)
PROJECTION_MODEL_PIN_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.projection-model-pin@1"
)
VECTOR_ENCODING_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.vector-encoding@1"
)
STRUCTURAL_FINGERPRINT_ALGORITHM: Final[str] = "structural.sha2-256@1"

DECLARED_SEMANTIC_VIEWS: Final[tuple[str, ...]] = (
    "source",
    "cst",
    "ast",
    "implementation_ir",
    "symbol_binding",
    "interface_contract",
    "effect_summary",
    "state_footprint",
    "dependency_slice",
    "behavior_summary",
    "initialization_dependency",
    "public_compatibility",
    "validation_profile",
)
DECLARED_SEMANTIC_VIEW_SET: Final[frozenset[str]] = frozenset(DECLARED_SEMANTIC_VIEWS)

DECLARED_SUBJECT_KINDS: Final[tuple[str, ...]] = (
    "function",
    "method",
    "class",
    "callsite",
    "top_level_block",
    "module",
    "package",
    "state_owner",
    "registration",
    "resource_lifecycle",
)
DECLARED_SUBJECT_KIND_SET: Final[frozenset[str]] = frozenset(DECLARED_SUBJECT_KINDS)

LOCATION_SENSITIVE_VIEWS: Final[frozenset[str]] = frozenset(
    {"symbol_binding", "public_compatibility"}
)
LOCATION_INDEPENDENT_VIEWS: Final[frozenset[str]] = (
    DECLARED_SEMANTIC_VIEW_SET - LOCATION_SENSITIVE_VIEWS
)

NEURAL_AVAILABLE: Final[str] = "available"
NEURAL_UNAVAILABLE: Final[str] = "unavailable"
NEURAL_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {NEURAL_AVAILABLE, NEURAL_UNAVAILABLE}
)

UNAVAILABLE_REASON_NEURAL: Final[str] = "neural_capability_unavailable"
UNAVAILABLE_REASONS: Final[frozenset[str]] = frozenset(
    {
        UNAVAILABLE_REASON_NEURAL,
        "model_mismatch",
        "dimension_mismatch",
        "vector_nonfinite",
        "vector_encoding_mismatch",
    }
)

METRICS: Final[frozenset[str]] = frozenset({"cosine", "dot_product", "euclidean"})
DTYPES: Final[frozenset[str]] = frozenset({"float32", "float16", "int8"})
BYTE_ORDERS: Final[frozenset[str]] = frozenset({"little"})
QUANTIZATIONS: Final[frozenset[str]] = frozenset({"none", "int8", "uint8"})
PRIVACY_MODES: Final[frozenset[str]] = frozenset({"none", "redacted", "restricted"})

_DTYPE_STRUCT: Final[Mapping[str, str]] = MappingProxyType(
    {"float32": "f", "float16": "e", "int8": "b"}
)
_DTYPE_WIDTH: Final[Mapping[str, int]] = MappingProxyType(
    {"float32": 4, "float16": 2, "int8": 1}
)
_AUTHORITY_FIELDS: Final[tuple[str, ...]] = (
    "semantic_authority",
    "authorizes_transition",
    "suppresses_raw_source",
    "raw_source_required",
)
_ADVISORY_AUTHORITY: Final[Mapping[str, bool]] = MappingProxyType(
    {
        "semantic_authority": False,
        "authorizes_transition": False,
        "suppresses_raw_source": False,
        "raw_source_required": True,
    }
)


class ProjectionContractError(ValueError):
    """Raised when a projection contract record is malformed or unauthorized."""


class NeuralCapability(str, Enum):
    AVAILABLE = NEURAL_AVAILABLE
    UNAVAILABLE = NEURAL_UNAVAILABLE


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise ProjectionContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ProjectionContractError(f"{name} must be trimmed NFC text")
    if "\x00" in value or any(not char.isprintable() for char in value):
        raise ProjectionContractError(f"{name} contains invalid text")
    if len(value.encode("utf-8")) > 16_384:
        raise ProjectionContractError(f"{name} exceeds its bound")
    return value


def _choice(value: Any, allowed: frozenset[str], name: str) -> str:
    text = _text(value, name)
    if text not in allowed:
        raise ProjectionContractError(f"{name} has unsupported value {text!r}")
    return text


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ProjectionContractError(f"{name} must be a valid CID") from exc


def _tree_id(value: Any) -> str:
    text = _text(value, "tree_id")
    if len(text) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in text):
        raise ProjectionContractError("tree_id must be a lowercase hex Git tree identity")
    return text


def _module_path(value: Any) -> str:
    text = _text(value, "module_path").replace("\\", "/")
    if text.startswith("/") or text.startswith("./") or ".." in text.split("/"):
        raise ProjectionContractError("module_path must be a relative POSIX repository path")
    if text.endswith("/") or "//" in text:
        raise ProjectionContractError("module_path must be a normalized POSIX path")
    return text


def _positive_int(value: Any, name: str, *, maximum: int = 65_536) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1 or value > maximum:
        raise ProjectionContractError(f"{name} must be an integer from 1 through {maximum}")
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ProjectionContractError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        unknown = actual - fields
        missing = fields - actual
        if unknown:
            raise ProjectionContractError(
                f"{name} rejects unknown fields: {sorted(unknown)}"
            )
        raise ProjectionContractError(
            f"{name} fields must be exactly {sorted(fields)}; missing {sorted(missing)}"
        )
    return dict(data)


def _authority(value: Any) -> Mapping[str, bool]:
    if not isinstance(value, Mapping):
        raise ProjectionContractError("authority must be a mapping")
    payload = _closed(value, frozenset(_AUTHORITY_FIELDS), "authority")
    for key, expected in _ADVISORY_AUTHORITY.items():
        flag = payload[key]
        if type(flag) is not bool:
            raise ProjectionContractError(f"authority.{key} must be a bool")
        if flag is not expected:
            raise ProjectionContractError(
                f"authority.{key} must be {expected}; projections are advisory only"
            )
    return MappingProxyType({key: payload[key] for key in _AUTHORITY_FIELDS})


def _hex_bytes(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) % 2 != 0 or any(ch not in "0123456789abcdef" for ch in text):
        raise ProjectionContractError(f"{name} must be lowercase even-length hex")
    return text


def encode_vector_bytes(
    values: Sequence[float] | Sequence[int],
    *,
    dtype: str,
    byte_order: str,
) -> str:
    """Encode a finite numeric vector as lowercase little-endian hex bytes."""

    dtype_name = _choice(dtype, DTYPES, "dtype")
    order = _choice(byte_order, BYTE_ORDERS, "byte_order")
    if isinstance(values, (str, bytes, bytearray, Mapping)):
        raise ProjectionContractError("vector values must be a numeric sequence")
    try:
        sequence = tuple(values)
    except TypeError as exc:
        raise ProjectionContractError("vector values must be a numeric sequence") from exc
    if not sequence:
        raise ProjectionContractError("vector values must be nonempty")

    if dtype_name == "int8":
        encoded: list[int] = []
        for item in sequence:
            if type(item) is bool or type(item) is not int or item < -128 or item > 127:
                raise ProjectionContractError("int8 vector values must be integers in [-128, 127]")
            encoded.append(item)
        payload = struct.pack("<" + ("b" * len(encoded)), *encoded)
        return payload.hex()

    floats: list[float] = []
    for item in sequence:
        if type(item) is bool or type(item) not in {int, float}:
            raise ProjectionContractError(f"{dtype_name} vector values must be finite numbers")
        number = float(item)
        if not math.isfinite(number):
            raise ProjectionContractError("vector values reject non-finite numbers")
        floats.append(number)
    code = _DTYPE_STRUCT[dtype_name]
    try:
        payload = struct.pack("<" + (code * len(floats)), *floats)
    except struct.error as exc:
        raise ProjectionContractError("vector values cannot be encoded for the declared dtype") from exc
    if order != "little":
        raise ProjectionContractError("byte_order must be little")
    return payload.hex()


def decode_vector_bytes(
    vector_bytes_hex: str,
    *,
    dtype: str,
    byte_order: str,
    dimension: int,
) -> tuple[float, ...]:
    """Decode hex vector bytes and reject nonfinite or mismatched payloads."""

    dtype_name = _choice(dtype, DTYPES, "dtype")
    _choice(byte_order, BYTE_ORDERS, "byte_order")
    dim = _positive_int(dimension, "dimension")
    hex_text = _hex_bytes(vector_bytes_hex, "vector_bytes_hex")
    raw = bytes.fromhex(hex_text)
    width = _DTYPE_WIDTH[dtype_name]
    expected = dim * width
    if len(raw) != expected:
        raise ProjectionContractError(
            f"vector byte length {len(raw)} does not match dimension {dim} and dtype {dtype_name}"
        )
    code = _DTYPE_STRUCT[dtype_name]
    unpacked = struct.unpack("<" + (code * dim), raw)
    if dtype_name == "int8":
        return tuple(float(item) for item in unpacked)
    decoded = tuple(float(item) for item in unpacked)
    if not all(math.isfinite(item) for item in decoded):
        raise ProjectionContractError("vector values reject non-finite numbers")
    return decoded


def _require_l2_for_cosine(values: Sequence[float], metric: str) -> None:
    if metric != "cosine":
        return
    norm = math.sqrt(sum(item * item for item in values))
    if not math.isfinite(norm) or abs(norm - 1.0) > 1e-5:
        raise ProjectionContractError("cosine metric requires a finite L2-normalized vector")


@dataclass(frozen=True, slots=True)
class ProjectionModelPin:
    """Exact model/tokenizer/preprocessor/profile pin for a neural projection."""

    model_id: str
    model_revision: str
    tokenizer_id: str
    tokenizer_revision: str
    preprocessor_id: str
    preprocessor_revision: str
    profile_id: str

    INTERFACE: ClassVar[str] = "ProjectionModelPin@1"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "model_id",
            "model_revision",
            "tokenizer_id",
            "tokenizer_revision",
            "preprocessor_id",
            "preprocessor_revision",
            "profile_id",
            "pin_cid",
        }
    )

    def __post_init__(self) -> None:
        for name in (
            "model_id",
            "model_revision",
            "tokenizer_id",
            "tokenizer_revision",
            "preprocessor_id",
            "preprocessor_revision",
            "profile_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PROJECTION_MODEL_PIN_SCHEMA,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
            "preprocessor_id": self.preprocessor_id,
            "preprocessor_revision": self.preprocessor_revision,
            "profile_id": self.profile_id,
        }

    @property
    def pin_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["pin_cid"] = self.pin_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectionModelPin":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("pin_cid")
        if payload.pop("schema") != PROJECTION_MODEL_PIN_SCHEMA:
            raise ProjectionContractError("unsupported ProjectionModelPin schema version")
        result = cls(**payload)
        if claimed != result.pin_cid:
            raise ProjectionContractError("ProjectionModelPin pin_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class VectorEncoding:
    """Exact vector bytes bound to dtype, order, quantization, metric, and CID."""

    dimension: int
    metric: str
    dtype: str
    byte_order: str
    quantization: str
    vector_bytes_hex: str

    INTERFACE: ClassVar[str] = "VectorEncoding@1"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "dimension",
            "metric",
            "dtype",
            "byte_order",
            "quantization",
            "vector_bytes_hex",
            "vector_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension", _positive_int(self.dimension, "dimension"))
        object.__setattr__(self, "metric", _choice(self.metric, METRICS, "metric"))
        object.__setattr__(self, "dtype", _choice(self.dtype, DTYPES, "dtype"))
        object.__setattr__(
            self, "byte_order", _choice(self.byte_order, BYTE_ORDERS, "byte_order")
        )
        object.__setattr__(
            self,
            "quantization",
            _choice(self.quantization, QUANTIZATIONS, "quantization"),
        )
        if self.dtype == "int8" and self.quantization not in {"int8", "none"}:
            raise ProjectionContractError("int8 dtype requires int8 or none quantization")
        if self.dtype != "int8" and self.quantization == "int8":
            raise ProjectionContractError("int8 quantization requires int8 dtype")
        if self.dtype == "float16" and self.quantization != "none":
            raise ProjectionContractError("float16 dtype requires none quantization")
        values = decode_vector_bytes(
            self.vector_bytes_hex,
            dtype=self.dtype,
            byte_order=self.byte_order,
            dimension=self.dimension,
        )
        object.__setattr__(
            self,
            "vector_bytes_hex",
            _hex_bytes(self.vector_bytes_hex, "vector_bytes_hex"),
        )
        _require_l2_for_cosine(values, self.metric)

    @property
    def vector_bytes(self) -> bytes:
        return bytes.fromhex(self.vector_bytes_hex)

    @property
    def vector_cid(self) -> str:
        return cid_for_bytes(self.vector_bytes)

    @property
    def values(self) -> tuple[float, ...]:
        return decode_vector_bytes(
            self.vector_bytes_hex,
            dtype=self.dtype,
            byte_order=self.byte_order,
            dimension=self.dimension,
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": VECTOR_ENCODING_SCHEMA,
            "dimension": self.dimension,
            "metric": self.metric,
            "dtype": self.dtype,
            "byte_order": self.byte_order,
            "quantization": self.quantization,
            "vector_bytes_hex": self.vector_bytes_hex,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["vector_cid"] = self.vector_cid
        return payload

    @classmethod
    def from_values(
        cls,
        values: Sequence[float] | Sequence[int],
        *,
        metric: str,
        dtype: str = "float32",
        byte_order: str = "little",
        quantization: str = "none",
    ) -> "VectorEncoding":
        hex_bytes = encode_vector_bytes(values, dtype=dtype, byte_order=byte_order)
        return cls(
            dimension=len(tuple(values)),
            metric=metric,
            dtype=dtype,
            byte_order=byte_order,
            quantization=quantization,
            vector_bytes_hex=hex_bytes,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VectorEncoding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("vector_cid")
        if payload.pop("schema") != VECTOR_ENCODING_SCHEMA:
            raise ProjectionContractError("unsupported VectorEncoding schema version")
        result = cls(**payload)
        if claimed != result.vector_cid:
            raise ProjectionContractError("VectorEncoding vector_cid does not verify")
        return result


def _identity_cids(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ProjectionContractError("identity_cids must be a mapping")
    if set(value) != DECLARED_SEMANTIC_VIEW_SET:
        missing = DECLARED_SEMANTIC_VIEW_SET - set(value)
        extra = set(value) - DECLARED_SEMANTIC_VIEW_SET
        if extra:
            raise ProjectionContractError(
                f"identity_cids rejects unknown views: {sorted(extra)}"
            )
        raise ProjectionContractError(
            f"identity_cids must cover every declared semantic view; missing {sorted(missing)}"
        )
    result = {
        view: _cid(value[view], f"identity_cids.{view}")
        for view in DECLARED_SEMANTIC_VIEWS
    }
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class ProjectionSubject:
    """Exact current-tree subject for function/module projection records."""

    kind: str
    tree_id: str
    source_cid: str
    stable_symbol_id: str
    module_path: str
    qualified_name: str
    identity_cids: Mapping[str, str]
    capsule_cid: str | None = None

    INTERFACE: ClassVar[str] = "ProjectionSubject@1"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "kind",
            "tree_id",
            "source_cid",
            "stable_symbol_id",
            "module_path",
            "qualified_name",
            "identity_cids",
            "capsule_cid",
            "subject_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _choice(self.kind, DECLARED_SUBJECT_KIND_SET, "kind"))
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "stable_symbol_id", _cid(self.stable_symbol_id, "stable_symbol_id")
        )
        object.__setattr__(self, "module_path", _module_path(self.module_path))
        object.__setattr__(self, "qualified_name", _text(self.qualified_name, "qualified_name"))
        object.__setattr__(self, "identity_cids", _identity_cids(self.identity_cids))
        if self.capsule_cid is not None:
            object.__setattr__(self, "capsule_cid", _cid(self.capsule_cid, "capsule_cid"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PROJECTION_SUBJECT_SCHEMA,
            "kind": self.kind,
            "tree_id": self.tree_id,
            "source_cid": self.source_cid,
            "stable_symbol_id": self.stable_symbol_id,
            "module_path": self.module_path,
            "qualified_name": self.qualified_name,
            "identity_cids": {
                view: self.identity_cids[view] for view in DECLARED_SEMANTIC_VIEWS
            },
            "capsule_cid": self.capsule_cid,
        }

    @property
    def subject_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def features_for_view(self, view: str) -> dict[str, Any]:
        view_name = _choice(view, DECLARED_SEMANTIC_VIEW_SET, "view")
        features: dict[str, Any] = {
            "view": view_name,
            "kind": self.kind,
            "identity_cid": self.identity_cids[view_name],
            "algorithm": STRUCTURAL_FINGERPRINT_ALGORITHM,
        }
        if view_name in LOCATION_SENSITIVE_VIEWS:
            features["module_path"] = self.module_path
            features["qualified_name"] = self.qualified_name
            features["stable_symbol_id"] = self.stable_symbol_id
        return features

    def relocated(
        self,
        *,
        module_path: str,
        qualified_name: str,
        identity_cids: Mapping[str, str] | None = None,
        stable_symbol_id: str | None = None,
    ) -> "ProjectionSubject":
        """Return a moved subject preserving location-independent identity CIDs."""

        updated = dict(self.identity_cids)
        if identity_cids is not None:
            if not isinstance(identity_cids, Mapping):
                raise ProjectionContractError("identity_cids must be a mapping")
            unknown = set(identity_cids) - DECLARED_SEMANTIC_VIEW_SET
            if unknown:
                raise ProjectionContractError(
                    f"relocated identity_cids rejects unknown views: {sorted(unknown)}"
                )
            for view, cid in identity_cids.items():
                updated[view] = _cid(cid, f"identity_cids.{view}")
        return ProjectionSubject(
            kind=self.kind,
            tree_id=self.tree_id,
            source_cid=self.source_cid,
            stable_symbol_id=stable_symbol_id or self.stable_symbol_id,
            module_path=module_path,
            qualified_name=qualified_name,
            identity_cids=updated,
            capsule_cid=self.capsule_cid,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["subject_cid"] = self.subject_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectionSubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_cid")
        if payload.pop("schema") != PROJECTION_SUBJECT_SCHEMA:
            raise ProjectionContractError("unsupported ProjectionSubject schema version")
        result = cls(**payload)
        if claimed != result.subject_cid:
            raise ProjectionContractError("ProjectionSubject subject_cid does not verify")
        return result


def _coerce_subject(value: ProjectionSubject | Mapping[str, Any]) -> ProjectionSubject:
    if isinstance(value, ProjectionSubject):
        return value
    if isinstance(value, Mapping):
        if "subject_cid" in value:
            return ProjectionSubject.from_dict(value)
        return ProjectionSubject(**dict(value))
    raise ProjectionContractError("subject must be a ProjectionSubject")


def _coerce_model_pin(value: ProjectionModelPin | Mapping[str, Any]) -> ProjectionModelPin:
    if isinstance(value, ProjectionModelPin):
        return value
    if isinstance(value, Mapping):
        if "pin_cid" in value:
            return ProjectionModelPin.from_dict(value)
        return ProjectionModelPin(**dict(value))
    raise ProjectionContractError("model_pin must be a ProjectionModelPin")


def _coerce_vector(value: VectorEncoding | Mapping[str, Any]) -> VectorEncoding:
    if isinstance(value, VectorEncoding):
        return value
    if isinstance(value, Mapping):
        if "vector_cid" in value:
            return VectorEncoding.from_dict(value)
        if "values" in value:
            payload = dict(value)
            values = payload.pop("values")
            return VectorEncoding.from_values(values, **payload)
        return VectorEncoding(**dict(value))
    raise ProjectionContractError("vector must be a VectorEncoding")


@dataclass(frozen=True, slots=True)
class StructuralFingerprint:
    """Deterministic structural fingerprint for one declared semantic view."""

    subject_kind: str
    view: str
    subject_cid: str
    tree_id: str
    source_cid: str
    features: Mapping[str, Any]
    algorithm: str = STRUCTURAL_FINGERPRINT_ALGORITHM

    INTERFACE: ClassVar[str] = STRUCTURAL_FINGERPRINT_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "subject_kind",
            "view",
            "subject_cid",
            "tree_id",
            "source_cid",
            "features",
            "algorithm",
            "fingerprint_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subject_kind",
            _choice(self.subject_kind, DECLARED_SUBJECT_KIND_SET, "subject_kind"),
        )
        object.__setattr__(self, "view", _choice(self.view, DECLARED_SEMANTIC_VIEW_SET, "view"))
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self,
            "algorithm",
            _text(self.algorithm, "algorithm"),
        )
        if self.algorithm != STRUCTURAL_FINGERPRINT_ALGORITHM:
            raise ProjectionContractError("unsupported structural fingerprint algorithm")
        if not isinstance(self.features, Mapping):
            raise ProjectionContractError("features must be a mapping")
        thawed = {str(key): self.features[key] for key in self.features}
        try:
            validate_structured_value(thawed)
        except Exception as exc:
            raise ProjectionContractError("features must be strict DAG-JSON") from exc
        if thawed.get("view") != self.view:
            raise ProjectionContractError("features.view must match the fingerprint view")
        object.__setattr__(self, "features", MappingProxyType(dict(thawed)))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": STRUCTURAL_FINGERPRINT_SCHEMA,
            "interface": STRUCTURAL_FINGERPRINT_INTERFACE,
            "subject_kind": self.subject_kind,
            "view": self.view,
            "subject_cid": self.subject_cid,
            "tree_id": self.tree_id,
            "source_cid": self.source_cid,
            "features": dict(self.features),
            "algorithm": self.algorithm,
        }

    @property
    def fingerprint_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["fingerprint_cid"] = self.fingerprint_cid
        return payload

    @classmethod
    def from_subject(cls, subject: ProjectionSubject, view: str) -> "StructuralFingerprint":
        bound = _coerce_subject(subject)
        view_name = _choice(view, DECLARED_SEMANTIC_VIEW_SET, "view")
        return cls(
            subject_kind=bound.kind,
            view=view_name,
            subject_cid=bound.subject_cid,
            tree_id=bound.tree_id,
            source_cid=bound.source_cid,
            features=bound.features_for_view(view_name),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StructuralFingerprint":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("fingerprint_cid")
        if payload.pop("schema") != STRUCTURAL_FINGERPRINT_SCHEMA:
            raise ProjectionContractError("unsupported StructuralFingerprint schema version")
        if payload.pop("interface") != STRUCTURAL_FINGERPRINT_INTERFACE:
            raise ProjectionContractError("unsupported StructuralFingerprint interface")
        result = cls(**payload)
        if claimed != result.fingerprint_cid:
            raise ProjectionContractError(
                "StructuralFingerprint fingerprint_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class SemanticProjection:
    """Model-pinned advisory projection for one declared semantic view."""

    subject: ProjectionSubject
    view: str
    model_pin: ProjectionModelPin
    vector: VectorEncoding
    privacy: str = "none"
    availability: str = NEURAL_AVAILABLE
    authority: Mapping[str, bool] = _ADVISORY_AUTHORITY

    INTERFACE: ClassVar[str] = SEMANTIC_PROJECTION_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "subject",
            "view",
            "model_pin",
            "vector",
            "privacy",
            "availability",
            "authority",
            "projection_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", _coerce_subject(self.subject))
        object.__setattr__(self, "view", _choice(self.view, DECLARED_SEMANTIC_VIEW_SET, "view"))
        object.__setattr__(self, "model_pin", _coerce_model_pin(self.model_pin))
        object.__setattr__(self, "vector", _coerce_vector(self.vector))
        object.__setattr__(self, "privacy", _choice(self.privacy, PRIVACY_MODES, "privacy"))
        object.__setattr__(
            self,
            "availability",
            _choice(self.availability, NEURAL_CAPABILITIES, "availability"),
        )
        if self.availability != NEURAL_AVAILABLE:
            raise ProjectionContractError(
                "SemanticProjection requires availability='available'; "
                "use ProjectionUnavailable when neural capability is absent"
            )
        object.__setattr__(self, "authority", _authority(self.authority))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_PROJECTION_SCHEMA,
            "interface": SEMANTIC_PROJECTION_INTERFACE,
            "subject": self.subject.to_dict(),
            "view": self.view,
            "model_pin": self.model_pin.to_dict(),
            "vector": self.vector.to_dict(),
            "privacy": self.privacy,
            "availability": self.availability,
            "authority": {key: self.authority[key] for key in _AUTHORITY_FIELDS},
        }

    @property
    def projection_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def semantic_authority(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["projection_cid"] = self.projection_cid
        return payload

    @classmethod
    def create(
        cls,
        *,
        subject: ProjectionSubject | Mapping[str, Any],
        view: str,
        model_pin: ProjectionModelPin | Mapping[str, Any],
        vector: VectorEncoding | Mapping[str, Any] | Sequence[float],
        metric: str = "cosine",
        dtype: str = "float32",
        byte_order: str = "little",
        quantization: str = "none",
        privacy: str = "none",
    ) -> "SemanticProjection":
        if isinstance(vector, (list, tuple)):
            encoded = VectorEncoding.from_values(
                vector,
                metric=metric,
                dtype=dtype,
                byte_order=byte_order,
                quantization=quantization,
            )
        else:
            encoded = _coerce_vector(vector)
        return cls(
            subject=subject,
            view=view,
            model_pin=model_pin,
            vector=encoded,
            privacy=privacy,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticProjection":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("projection_cid")
        if payload.pop("schema") != SEMANTIC_PROJECTION_SCHEMA:
            raise ProjectionContractError("unsupported SemanticProjection schema version")
        if payload.pop("interface") != SEMANTIC_PROJECTION_INTERFACE:
            raise ProjectionContractError("unsupported SemanticProjection interface")
        result = cls(
            subject=payload["subject"],
            view=payload["view"],
            model_pin=payload["model_pin"],
            vector=payload["vector"],
            privacy=payload["privacy"],
            availability=payload["availability"],
            authority=payload["authority"],
        )
        if claimed != result.projection_cid:
            raise ProjectionContractError("SemanticProjection projection_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class ProjectionUnavailable:
    """Typed neural-unavailability residual that still carries a fingerprint."""

    subject: ProjectionSubject
    view: str
    reason: str
    fingerprint: StructuralFingerprint
    privacy: str = "none"
    availability: str = NEURAL_UNAVAILABLE
    authority: Mapping[str, bool] = _ADVISORY_AUTHORITY

    INTERFACE: ClassVar[str] = PROJECTION_UNAVAILABLE_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "subject",
            "view",
            "reason",
            "fingerprint",
            "privacy",
            "availability",
            "authority",
            "unavailable_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", _coerce_subject(self.subject))
        object.__setattr__(self, "view", _choice(self.view, DECLARED_SEMANTIC_VIEW_SET, "view"))
        object.__setattr__(
            self, "reason", _choice(self.reason, UNAVAILABLE_REASONS, "reason")
        )
        fingerprint = self.fingerprint
        if isinstance(fingerprint, Mapping):
            fingerprint = StructuralFingerprint.from_dict(fingerprint)
        if not isinstance(fingerprint, StructuralFingerprint):
            raise ProjectionContractError("fingerprint must be a StructuralFingerprint")
        if fingerprint.view != self.view:
            raise ProjectionContractError("fingerprint.view must match the unavailable view")
        if fingerprint.subject_cid != self.subject.subject_cid:
            raise ProjectionContractError("fingerprint subject must match the unavailable subject")
        object.__setattr__(self, "fingerprint", fingerprint)
        object.__setattr__(self, "privacy", _choice(self.privacy, PRIVACY_MODES, "privacy"))
        object.__setattr__(
            self,
            "availability",
            _choice(self.availability, NEURAL_CAPABILITIES, "availability"),
        )
        if self.availability != NEURAL_UNAVAILABLE:
            raise ProjectionContractError(
                "ProjectionUnavailable requires availability='unavailable'"
            )
        object.__setattr__(self, "authority", _authority(self.authority))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PROJECTION_UNAVAILABLE_SCHEMA,
            "interface": PROJECTION_UNAVAILABLE_INTERFACE,
            "subject": self.subject.to_dict(),
            "view": self.view,
            "reason": self.reason,
            "fingerprint": self.fingerprint.to_dict(),
            "privacy": self.privacy,
            "availability": self.availability,
            "authority": {key: self.authority[key] for key in _AUTHORITY_FIELDS},
        }

    @property
    def unavailable_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def semantic_authority(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["unavailable_cid"] = self.unavailable_cid
        return payload

    @classmethod
    def for_subject(
        cls,
        subject: ProjectionSubject | Mapping[str, Any],
        view: str,
        *,
        reason: str = UNAVAILABLE_REASON_NEURAL,
        privacy: str = "none",
    ) -> "ProjectionUnavailable":
        bound = _coerce_subject(subject)
        return cls(
            subject=bound,
            view=view,
            reason=reason,
            fingerprint=StructuralFingerprint.from_subject(bound, view),
            privacy=privacy,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectionUnavailable":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("unavailable_cid")
        if payload.pop("schema") != PROJECTION_UNAVAILABLE_SCHEMA:
            raise ProjectionContractError("unsupported ProjectionUnavailable schema version")
        if payload.pop("interface") != PROJECTION_UNAVAILABLE_INTERFACE:
            raise ProjectionContractError("unsupported ProjectionUnavailable interface")
        result = cls(
            subject=payload["subject"],
            view=payload["view"],
            reason=payload["reason"],
            fingerprint=payload["fingerprint"],
            privacy=payload["privacy"],
            availability=payload["availability"],
            authority=payload["authority"],
        )
        if claimed != result.unavailable_cid:
            raise ProjectionContractError(
                "ProjectionUnavailable unavailable_cid does not verify"
            )
        return result


def _neural_capability(value: Any) -> str:
    if type(value) is bool:
        return NEURAL_AVAILABLE if value else NEURAL_UNAVAILABLE
    if isinstance(value, NeuralCapability):
        return value.value
    return _choice(value, NEURAL_CAPABILITIES, "neural_capability")


def _require_exact_views(values: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        raise ProjectionContractError(f"{name} must be a mapping")
    if set(values) != DECLARED_SEMANTIC_VIEW_SET:
        missing = DECLARED_SEMANTIC_VIEW_SET - set(values)
        extra = set(values) - DECLARED_SEMANTIC_VIEW_SET
        if extra:
            raise ProjectionContractError(f"{name} rejects unknown views: {sorted(extra)}")
        raise ProjectionContractError(
            f"{name} must cover every declared semantic view; missing {sorted(missing)}"
        )
    return {view: values[view] for view in DECLARED_SEMANTIC_VIEWS}


def fingerprints_for_subject(subject: ProjectionSubject) -> tuple[StructuralFingerprint, ...]:
    """Return one deterministic structural fingerprint per declared view."""

    bound = _coerce_subject(subject)
    return tuple(StructuralFingerprint.from_subject(bound, view) for view in DECLARED_SEMANTIC_VIEWS)


@dataclass(frozen=True, slots=True)
class SemanticProjectionSet:
    """Complete advisory projection coverage for every declared semantic view."""

    subject: ProjectionSubject
    neural_capability: str
    fingerprints: tuple[StructuralFingerprint, ...]
    projections: tuple[SemanticProjection, ...] = ()
    unavailability: tuple[ProjectionUnavailable, ...] = ()
    privacy: str = "none"

    INTERFACE: ClassVar[str] = SEMANTIC_PROJECTION_SET_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "subject",
            "neural_capability",
            "fingerprints",
            "projections",
            "unavailability",
            "privacy",
            "set_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", _coerce_subject(self.subject))
        object.__setattr__(
            self,
            "neural_capability",
            _neural_capability(self.neural_capability),
        )
        object.__setattr__(self, "privacy", _choice(self.privacy, PRIVACY_MODES, "privacy"))
        fingerprints = tuple(self.fingerprints)
        if len(fingerprints) != len(DECLARED_SEMANTIC_VIEWS):
            raise ProjectionContractError(
                "fingerprints must contain exactly one record per declared semantic view"
            )
        normalized_fps: list[StructuralFingerprint] = []
        for item, view in zip(fingerprints, DECLARED_SEMANTIC_VIEWS, strict=True):
            fingerprint = (
                StructuralFingerprint.from_dict(item)
                if isinstance(item, Mapping)
                else item
            )
            if not isinstance(fingerprint, StructuralFingerprint):
                raise ProjectionContractError("fingerprints must contain StructuralFingerprint records")
            if fingerprint.view != view:
                raise ProjectionContractError("fingerprints must be ordered by DECLARED_SEMANTIC_VIEWS")
            if fingerprint.subject_cid != self.subject.subject_cid:
                raise ProjectionContractError("fingerprint subject must match the projection set subject")
            normalized_fps.append(fingerprint)
        object.__setattr__(self, "fingerprints", tuple(normalized_fps))

        if self.neural_capability == NEURAL_AVAILABLE:
            if self.unavailability:
                raise ProjectionContractError(
                    "available neural capability rejects ProjectionUnavailable records"
                )
            if len(self.projections) != len(DECLARED_SEMANTIC_VIEWS):
                raise ProjectionContractError(
                    "available neural capability requires one SemanticProjection per declared view"
                )
            normalized: list[SemanticProjection] = []
            pin_cid: str | None = None
            for item, view in zip(self.projections, DECLARED_SEMANTIC_VIEWS, strict=True):
                projection = (
                    SemanticProjection.from_dict(item)
                    if isinstance(item, Mapping)
                    else item
                )
                if not isinstance(projection, SemanticProjection):
                    raise ProjectionContractError("projections must contain SemanticProjection records")
                if projection.view != view:
                    raise ProjectionContractError(
                        "projections must be ordered by DECLARED_SEMANTIC_VIEWS"
                    )
                if projection.subject.subject_cid != self.subject.subject_cid:
                    raise ProjectionContractError("projection subject must match the set subject")
                if pin_cid is None:
                    pin_cid = projection.model_pin.pin_cid
                elif projection.model_pin.pin_cid != pin_cid:
                    raise ProjectionContractError("model pin mismatch across semantic views")
                if projection.privacy != self.privacy:
                    raise ProjectionContractError("projection privacy must match the set privacy")
                normalized.append(projection)
            object.__setattr__(self, "projections", tuple(normalized))
            object.__setattr__(self, "unavailability", ())
            return

        if self.projections:
            raise ProjectionContractError(
                "unavailable neural capability rejects SemanticProjection records"
            )
        if len(self.unavailability) != len(DECLARED_SEMANTIC_VIEWS):
            raise ProjectionContractError(
                "unavailable neural capability requires one ProjectionUnavailable per declared view"
            )
        normalized_u: list[ProjectionUnavailable] = []
        for item, view in zip(self.unavailability, DECLARED_SEMANTIC_VIEWS, strict=True):
            record = (
                ProjectionUnavailable.from_dict(item)
                if isinstance(item, Mapping)
                else item
            )
            if not isinstance(record, ProjectionUnavailable):
                raise ProjectionContractError(
                    "unavailability must contain ProjectionUnavailable records"
                )
            if record.view != view:
                raise ProjectionContractError(
                    "unavailability must be ordered by DECLARED_SEMANTIC_VIEWS"
                )
            if record.subject.subject_cid != self.subject.subject_cid:
                raise ProjectionContractError("unavailable subject must match the set subject")
            if record.fingerprint.fingerprint_cid != self.fingerprints[
                DECLARED_SEMANTIC_VIEWS.index(view)
            ].fingerprint_cid:
                raise ProjectionContractError(
                    "unavailable fingerprint must match the set structural fingerprint"
                )
            normalized_u.append(record)
        object.__setattr__(self, "unavailability", tuple(normalized_u))
        object.__setattr__(self, "projections", ())

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_PROJECTION_SET_SCHEMA,
            "interface": SEMANTIC_PROJECTION_SET_INTERFACE,
            "subject": self.subject.to_dict(),
            "neural_capability": self.neural_capability,
            "fingerprints": [item.to_dict() for item in self.fingerprints],
            "projections": [item.to_dict() for item in self.projections],
            "unavailability": [item.to_dict() for item in self.unavailability],
            "privacy": self.privacy,
        }

    @property
    def set_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def semantic_authority(self) -> bool:
        return False

    def record_for_view(self, view: str) -> SemanticProjection | ProjectionUnavailable:
        view_name = _choice(view, DECLARED_SEMANTIC_VIEW_SET, "view")
        index = DECLARED_SEMANTIC_VIEWS.index(view_name)
        if self.neural_capability == NEURAL_AVAILABLE:
            return self.projections[index]
        return self.unavailability[index]

    def fingerprint_for_view(self, view: str) -> StructuralFingerprint:
        view_name = _choice(view, DECLARED_SEMANTIC_VIEW_SET, "view")
        return self.fingerprints[DECLARED_SEMANTIC_VIEWS.index(view_name)]

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["set_cid"] = self.set_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticProjectionSet":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("set_cid")
        if payload.pop("schema") != SEMANTIC_PROJECTION_SET_SCHEMA:
            raise ProjectionContractError("unsupported SemanticProjectionSet schema version")
        if payload.pop("interface") != SEMANTIC_PROJECTION_SET_INTERFACE:
            raise ProjectionContractError("unsupported SemanticProjectionSet interface")
        result = cls(
            subject=payload["subject"],
            neural_capability=payload["neural_capability"],
            fingerprints=tuple(payload["fingerprints"]),
            projections=tuple(payload["projections"]),
            unavailability=tuple(payload["unavailability"]),
            privacy=payload["privacy"],
        )
        if claimed != result.set_cid:
            raise ProjectionContractError("SemanticProjectionSet set_cid does not verify")
        return result


def project_declared_views(
    subject: ProjectionSubject | Mapping[str, Any],
    *,
    neural_capability: str | bool | NeuralCapability,
    model_pin: ProjectionModelPin | Mapping[str, Any] | None = None,
    vectors_by_view: Mapping[str, Any] | None = None,
    privacy: str = "none",
) -> SemanticProjectionSet:
    """Project every declared semantic view for one exact current-tree subject.

    Neural-available calls require a model pin and one finite vector per view.
    Neural-unavailable calls reject model/vector inputs, emit
    ``ProjectionUnavailable@1`` residuals, and still return structural
    fingerprints so analysis remains usable.
    """

    bound = _coerce_subject(subject)
    capability = _neural_capability(neural_capability)
    fingerprints = fingerprints_for_subject(bound)
    if capability == NEURAL_UNAVAILABLE:
        if model_pin is not None:
            raise ProjectionContractError(
                "neural capability unavailable rejects a model pin"
            )
        if vectors_by_view is not None:
            raise ProjectionContractError(
                "neural capability unavailable rejects neural vectors"
            )
        unavailable = tuple(
            ProjectionUnavailable(
                subject=bound,
                view=view,
                reason=UNAVAILABLE_REASON_NEURAL,
                fingerprint=fingerprint,
                privacy=privacy,
            )
            for view, fingerprint in zip(DECLARED_SEMANTIC_VIEWS, fingerprints, strict=True)
        )
        return SemanticProjectionSet(
            subject=bound,
            neural_capability=capability,
            fingerprints=fingerprints,
            unavailability=unavailable,
            privacy=privacy,
        )

    if model_pin is None:
        raise ProjectionContractError("neural capability available requires a model pin")
    if vectors_by_view is None:
        raise ProjectionContractError(
            "neural capability available requires vectors for every declared view"
        )
    pin = _coerce_model_pin(model_pin)
    vectors = _require_exact_views(vectors_by_view, "vectors_by_view")
    projections = tuple(
        SemanticProjection.create(
            subject=bound,
            view=view,
            model_pin=pin,
            vector=vectors[view],
            privacy=privacy,
        )
        for view in DECLARED_SEMANTIC_VIEWS
    )
    return SemanticProjectionSet(
        subject=bound,
        neural_capability=capability,
        fingerprints=fingerprints,
        projections=projections,
        privacy=privacy,
    )


def canonical_projection_bytes(value: Any) -> bytes:
    """Return canonical DAG-JSON bytes for a projection contract payload."""

    if hasattr(value, "identity_payload"):
        payload = value.identity_payload()
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        raise ProjectionContractError("canonical projection bytes require a contract record")
    return canonical_dag_json_bytes(payload)


__all__ = (
    "DECLARED_SEMANTIC_VIEWS",
    "DECLARED_SUBJECT_KINDS",
    "LOCATION_INDEPENDENT_VIEWS",
    "LOCATION_SENSITIVE_VIEWS",
    "NEURAL_AVAILABLE",
    "NEURAL_UNAVAILABLE",
    "PROJECTION_UNAVAILABLE_INTERFACE",
    "SEMANTIC_PROJECTION_INTERFACE",
    "STRUCTURAL_FINGERPRINT_INTERFACE",
    "NeuralCapability",
    "ProjectionContractError",
    "ProjectionModelPin",
    "ProjectionSubject",
    "ProjectionUnavailable",
    "SemanticProjection",
    "SemanticProjectionSet",
    "StructuralFingerprint",
    "VectorEncoding",
    "canonical_projection_bytes",
    "decode_vector_bytes",
    "encode_vector_bytes",
    "fingerprints_for_subject",
    "project_declared_views",
)
