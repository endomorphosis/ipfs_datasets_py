"""Strict content-addressed records for the Solidity CPT derived corpus.

Source bodies are deliberately excluded from these records.  A source record
binds the separate body CID and digest plus normalized, explicitly unverified
metadata.  Every record binds source, parent, and producer-configuration CIDs.

Construction may derive an omitted identity.  Persisted ``from_dict`` and
``from_json`` paths require the identity assertion, rehash deterministic
content, and reject a missing, stale, or caller-selected identity.  Aggregate
loads additionally require an independently trusted lineage context, so a
caller cannot replace all lineage CIDs and merely recompute a self-consistent
but foreign dataset root.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import CanonicalIdentity, canonical_identity
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)
from .release_policy import SOLIDITY_CPT_DATASET_ID, SOLIDITY_CPT_REVISION
from .source_snapshot import SolidityCPTRow

SOLIDITY_CPT_SCHEMA_VERSION: Final = "solidity-cpt-derived-record/v1"
SOLIDITY_CPT_DATASET_SCHEMA_VERSION: Final = "solidity-cpt-derived-dataset/v1"
SOLIDITY_CPT_LINEAGE_SCHEMA_VERSION: Final = "solidity-cpt-lineage-context/v1"
SOLIDITY_CPT_CONFIG_SCHEMA_VERSION: Final = "solidity-cpt-producer-config/v1"
SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX: Final = "solidity-cpt-security-ir"

_CID_LENGTH = 59
_CID_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz234567")
_CID_HEADER = b"\x01\x55\x12\x20"
_SOURCE_BODY_KEYS: Final = frozenset(
    {
        "body",
        "code",
        "raw_source",
        "source_body",
        "source_code",
        "source_text",
        "text",
    }
)
_GRANT_KEYS: Final = frozenset(
    {
        "allow",
        "authoritative",
        "deployed_bytecode_equal",
        "execution_authority",
        "grants_authority",
        "grants_execution_authority",
        "proof_authority",
        "safe",
        "transaction_authority",
        "verified_source",
    }
)
_SOURCE_RECORD_PAYLOAD_FIELDS: Final = frozenset(
    {
        "address",
        "compiler",
        "license",
        "n_chars",
        "name",
        "path",
        "row_index",
        "source_provider",
    }
)


class SolidityCPTSchemaError(ValueError):
    """Raised when a record, lineage context, or aggregate fails closed."""


class DerivedAuthority(StrEnum):
    """Closed non-granting authority vocabulary for derived corpus data."""

    NON_AUTHORITATIVE = "non_authoritative"
    CANDIDATE = "candidate"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SolidityCPTSchemaError(f"{label} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    label: str,
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise SolidityCPTSchemaError(f"unknown {label} field(s): {', '.join(unknown)}")


def _exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        unknown = sorted(actual - set(expected))
        detail: list[str] = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unknown:
            detail.append("unknown=" + ",".join(unknown))
        raise SolidityCPTSchemaError(f"{label} schema drift: {'; '.join(detail)}")


def _text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value:
        raise SolidityCPTSchemaError(f"{label} must be a non-empty string")
    if value != value.strip() or "\x00" in value:
        raise SolidityCPTSchemaError(f"{label} must be normalized text without NUL")
    if len(value) > maximum:
        raise SolidityCPTSchemaError(f"{label} exceeds character bound")
    return value


def _cid(value: Any, label: str) -> str:
    result = _text(value, label, maximum=64)
    if (
        len(result) != _CID_LENGTH
        or not result.startswith("b")
        or any(character not in _CID_ALPHABET for character in result)
    ):
        raise SolidityCPTSchemaError(f"{label} must be an ir_core raw/sha2-256 CIDv1")
    try:
        encoded = result[1:].upper()
        raw = base64.b32decode(encoded + "=" * ((-len(encoded)) % 8))
    except (ValueError, base64.binascii.Error) as exc:
        raise SolidityCPTSchemaError(f"{label} must be an ir_core raw/sha2-256 CIDv1") from exc
    if len(raw) != 36 or not raw.startswith(_CID_HEADER):
        raise SolidityCPTSchemaError(f"{label} must be an ir_core raw/sha2-256 CIDv1")
    return result


def _cid_tuple(
    value: Any,
    label: str,
    *,
    nonempty: bool = True,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise SolidityCPTSchemaError(f"{label} must be a sequence of CIDs")
    result = tuple(_cid(item, f"{label} item") for item in value)
    if nonempty and not result:
        raise SolidityCPTSchemaError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise SolidityCPTSchemaError(f"{label} must not contain duplicate IDs")
    return tuple(sorted(result))


def _frozen_mapping(value: Any, label: str) -> Mapping[str, Any]:
    try:
        frozen = freeze_json_mapping(_mapping(value, label))
    except ProvenanceValidationError as exc:
        raise SolidityCPTSchemaError(f"{label}: {exc}") from exc
    _assert_source_free_and_non_granting(thaw_json(frozen), label=label)
    return frozen


def _assert_source_free_and_non_granting(value: Any, *, label: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            folded = key.casefold()
            location = f"{label}.{key}"
            if folded in _SOURCE_BODY_KEYS:
                raise SolidityCPTSchemaError(f"{location} cannot embed a source body")
            if folded in _GRANT_KEYS and item not in (False, None, ""):
                raise SolidityCPTSchemaError(f"{location} cannot grant authority or assert bytecode equality")
            if folded == "authority" and item not in (
                "candidate",
                "non_authoritative",
            ):
                raise SolidityCPTSchemaError(f"{location} contains unknown authority")
            _assert_source_free_and_non_granting(item, label=location)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _assert_source_free_and_non_granting(item, label=f"{label}[{index}]")


def _authority(value: Any, expected: DerivedAuthority) -> DerivedAuthority:
    try:
        result = value if isinstance(value, DerivedAuthority) else DerivedAuthority(value)
    except (TypeError, ValueError) as exc:
        raise SolidityCPTSchemaError("derived authority must be candidate or non_authoritative") from exc
    if result is not expected:
        raise SolidityCPTSchemaError(f"record requires authority={expected.value}; authority cannot broaden")
    return result


def _decode_json_object(
    value: str | bytes | bytearray,
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, (str, bytes, bytearray)):
        raise SolidityCPTSchemaError(f"{label} JSON must be text or bytes")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise SolidityCPTSchemaError(f"{label} JSON contains duplicate field {key!r}")
            result[key] = item
        return result

    def reject_constant(constant: str) -> None:
        raise SolidityCPTSchemaError(f"{label} JSON contains non-finite number {constant}")

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except SolidityCPTSchemaError:
        raise
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise SolidityCPTSchemaError(f"{label} is not valid JSON") from exc
    return _mapping(decoded, label)


def canonical_config_cid(
    config: Mapping[str, Any],
    *,
    schema_version: str = SOLIDITY_CPT_CONFIG_SCHEMA_VERSION,
) -> str:
    """Compute a producer-config CID from the actual frozen config mapping."""

    return canonical_identity(
        _mapping(config, "config"),
        domain=f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/config",
        schema_version=_text(schema_version, "schema_version"),
    ).cid


@dataclass(frozen=True, slots=True)
class ProducerConfig:
    """Persistable config artifact whose claimed CID is always recomputed."""

    config: Mapping[str, Any]
    config_cid: str = ""
    schema_version: str = SOLIDITY_CPT_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            frozen = freeze_json_mapping(_mapping(self.config, "config"))
        except ProvenanceValidationError as exc:
            raise SolidityCPTSchemaError(f"config: {exc}") from exc
        object.__setattr__(self, "config", frozen)
        if self.schema_version != SOLIDITY_CPT_CONFIG_SCHEMA_VERSION:
            raise SolidityCPTSchemaError("unknown producer config schema")
        computed = canonical_config_cid(thaw_json(self.config), schema_version=self.schema_version)
        if self.config_cid and self.config_cid != computed:
            raise SolidityCPTSchemaError("config_cid does not match rehashed producer config")
        object.__setattr__(self, "config_cid", computed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": thaw_json(self.config),
            "config_cid": self.config_cid,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProducerConfig:
        value = _mapping(value, "producer config")
        _exact_fields(
            value,
            frozenset({"config", "config_cid", "schema_version"}),
            "producer config",
        )
        if not value["config_cid"]:
            raise SolidityCPTSchemaError("persisted producer config requires config_cid")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class TrustedLineage:
    """Externally trusted roots against which an aggregate closes lineage."""

    source_cids: tuple[str, ...]
    producer_configs: tuple[ProducerConfig, ...]
    source_rows: tuple[SolidityCPTRow, ...]
    external_parent_cids: tuple[str, ...]
    context_id: str = ""
    schema_version: str = SOLIDITY_CPT_LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_cids", _cid_tuple(self.source_cids, "source_cids"))
        if isinstance(self.producer_configs, (str, bytes, bytearray)) or not isinstance(
            self.producer_configs, Sequence
        ):
            raise SolidityCPTSchemaError("producer_configs must be a sequence")
        configs = tuple(
            item if isinstance(item, ProducerConfig) else ProducerConfig.from_dict(_mapping(item, "producer config"))
            for item in self.producer_configs
        )
        if not configs:
            raise SolidityCPTSchemaError("producer_configs must not be empty")
        config_ids = tuple(item.config_cid for item in configs)
        if len(config_ids) != len(set(config_ids)):
            raise SolidityCPTSchemaError("producer_configs contain duplicate IDs")
        object.__setattr__(
            self,
            "producer_configs",
            tuple(sorted(configs, key=lambda item: item.config_cid)),
        )
        if isinstance(self.source_rows, (str, bytes, bytearray)) or not isinstance(self.source_rows, Sequence):
            raise SolidityCPTSchemaError("source_rows must be a sequence")
        rows = tuple(
            item if isinstance(item, SolidityCPTRow) else SolidityCPTRow.from_dict(_mapping(item, "source row"))
            for item in self.source_rows
        )
        if not rows:
            raise SolidityCPTSchemaError("source_rows must not be empty")
        row_ids = tuple(item.row_id for item in rows)
        if len(row_ids) != len(set(row_ids)):
            raise SolidityCPTSchemaError("source_rows contain duplicate IDs")
        if any(item.source_snapshot_cid not in self.source_cids or item.config_cid not in config_ids for item in rows):
            raise SolidityCPTSchemaError("source_rows differ from trusted source/config roots")
        object.__setattr__(
            self,
            "source_rows",
            tuple(sorted(rows, key=lambda item: item.row_id)),
        )
        object.__setattr__(
            self,
            "external_parent_cids",
            _cid_tuple(self.external_parent_cids, "external_parent_cids"),
        )
        if self.schema_version != SOLIDITY_CPT_LINEAGE_SCHEMA_VERSION:
            raise SolidityCPTSchemaError("unknown lineage context schema")
        computed = canonical_identity(
            self.deterministic_dict(),
            domain=f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/lineage",
            schema_version=self.schema_version,
        ).cid
        if self.context_id and self.context_id != computed:
            raise SolidityCPTSchemaError("context_id does not match rehashed trusted lineage")
        object.__setattr__(self, "context_id", computed)

    @property
    def config_cids(self) -> tuple[str, ...]:
        return tuple(item.config_cid for item in self.producer_configs)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "external_parent_cids": list(self.external_parent_cids),
            "producer_configs": [item.to_dict() for item in self.producer_configs],
            "schema_version": self.schema_version,
            "source_cids": list(self.source_cids),
            "source_rows": [item.to_dict() for item in self.source_rows],
        }

    def to_dict(self) -> dict[str, Any]:
        return {"context_id": self.context_id, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TrustedLineage:
        value = _mapping(value, "trusted lineage")
        _exact_fields(
            value,
            frozenset(
                {
                    "context_id",
                    "external_parent_cids",
                    "producer_configs",
                    "schema_version",
                    "source_cids",
                    "source_rows",
                }
            ),
            "trusted lineage",
        )
        if not value["context_id"]:
            raise SolidityCPTSchemaError("persisted trusted lineage requires context_id")
        raw_configs = value["producer_configs"]
        if isinstance(raw_configs, (str, bytes, bytearray)) or not isinstance(raw_configs, Sequence):
            raise SolidityCPTSchemaError("producer_configs must be a sequence")
        return cls(
            source_cids=value["source_cids"],
            producer_configs=tuple(ProducerConfig.from_dict(_mapping(item, "producer config")) for item in raw_configs),
            source_rows=tuple(SolidityCPTRow.from_dict(_mapping(item, "source row")) for item in value["source_rows"]),
            external_parent_cids=value["external_parent_cids"],
            context_id=value["context_id"],
            schema_version=value["schema_version"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalDerivedRecord:
    """Common strict identity and lineage behavior for derived records."""

    source_cids: tuple[str, ...]
    parent_cids: tuple[str, ...]
    config_cid: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    authority: DerivedAuthority = DerivedAuthority.NON_AUTHORITATIVE
    record_id: str = ""
    schema_version: str = SOLIDITY_CPT_SCHEMA_VERSION

    RECORD_TYPE: ClassVar[str] = "derived_record"
    IDENTITY_DOMAIN: ClassVar[str] = f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/derived-record"
    EXPECTED_AUTHORITY: ClassVar[DerivedAuthority] = DerivedAuthority.NON_AUTHORITATIVE
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_cids", _cid_tuple(self.source_cids, "source_cids"))
        object.__setattr__(self, "parent_cids", _cid_tuple(self.parent_cids, "parent_cids"))
        object.__setattr__(self, "config_cid", _cid(self.config_cid, "config_cid"))
        object.__setattr__(self, "payload", _frozen_mapping(self.payload, "payload"))
        object.__setattr__(
            self,
            "authority",
            _authority(self.authority, self.EXPECTED_AUTHORITY),
        )
        if self.schema_version != SOLIDITY_CPT_SCHEMA_VERSION:
            raise SolidityCPTSchemaError("unsupported record schema_version")
        self._validate_specific()
        computed = self.identity.cid
        if self.record_id and self.record_id != computed:
            raise SolidityCPTSchemaError(f"{self.RECORD_TYPE} record_id does not match rehashed content")
        object.__setattr__(self, "record_id", computed)

    def _validate_specific(self) -> None:
        pass

    def _specific_dict(self) -> dict[str, Any]:
        return {}

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "config_cid": self.config_cid,
            "parent_cids": list(self.parent_cids),
            "payload": thaw_json(self.payload),
            "record_type": self.RECORD_TYPE,
            "schema_version": self.schema_version,
            "source_cids": list(self.source_cids),
            **self._specific_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"record_id": self.record_id, **self.deterministic_dict()}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain=self.IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.record_id

    @property
    def digest(self) -> str:
        return self.identity.digest

    @classmethod
    def _common_values(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "authority": value.get("authority", cls.EXPECTED_AUTHORITY.value),
            "config_cid": value.get("config_cid", ""),
            "parent_cids": value.get("parent_cids", ()),
            "payload": value.get("payload", {}),
            "record_id": value.get("record_id", ""),
            "schema_version": value.get("schema_version", SOLIDITY_CPT_SCHEMA_VERSION),
            "source_cids": value.get("source_cids", ()),
        }

    @classmethod
    def _prepare_dict(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        value = _mapping(value, cls.RECORD_TYPE)
        _exact_fields(
            value,
            frozenset(
                {
                    "authority",
                    "config_cid",
                    "parent_cids",
                    "payload",
                    "record_id",
                    "record_type",
                    "schema_version",
                    "source_cids",
                    *cls.SPECIFIC_FIELDS,
                }
            ),
            cls.RECORD_TYPE,
        )
        if value.get("record_type") != cls.RECORD_TYPE:
            raise SolidityCPTSchemaError(f"record_type must be {cls.RECORD_TYPE!r}")
        if not value.get("record_id"):
            raise SolidityCPTSchemaError(f"persisted {cls.RECORD_TYPE} requires record_id")
        return value

    @classmethod
    def from_json(
        cls,
        value: str | bytes | bytearray,
    ) -> CanonicalDerivedRecord:
        return cls.from_dict(_decode_json_object(value, cls.RECORD_TYPE))


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRecord(CanonicalDerivedRecord):
    """One body-free normalized Solidity row bound to the reviewed snapshot."""

    source_uri: str
    source_revision: str
    row_key: str
    source_row_id: str
    raw_row_cid: str
    source_body_cid: str
    source_body_sha256: str
    address_is_unverified_hint: bool = True
    deployed_bytecode_equality: bool = False

    RECORD_TYPE: ClassVar[str] = "source_record"
    IDENTITY_DOMAIN: ClassVar[str] = f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/source-record"
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "address_is_unverified_hint",
            "deployed_bytecode_equality",
            "row_key",
            "raw_row_cid",
            "source_body_cid",
            "source_body_sha256",
            "source_row_id",
            "source_revision",
            "source_uri",
        }
    )

    def _validate_specific(self) -> None:
        object.__setattr__(self, "source_uri", _text(self.source_uri, "source_uri"))
        object.__setattr__(
            self,
            "source_revision",
            _text(self.source_revision, "source_revision"),
        )
        object.__setattr__(self, "row_key", _text(self.row_key, "row_key"))
        object.__setattr__(
            self,
            "source_row_id",
            _cid(self.source_row_id, "source_row_id"),
        )
        object.__setattr__(
            self,
            "raw_row_cid",
            _cid(self.raw_row_cid, "raw_row_cid"),
        )
        object.__setattr__(
            self,
            "source_body_cid",
            _cid(self.source_body_cid, "source_body_cid"),
        )
        if (
            not isinstance(self.source_body_sha256, str)
            or len(self.source_body_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.source_body_sha256)
        ):
            raise SolidityCPTSchemaError("source_body_sha256 must be lowercase SHA-256")
        if self.source_revision != SOLIDITY_CPT_REVISION:
            raise SolidityCPTSchemaError("source_revision differs from reviewed source pin")
        if self.source_uri != f"hf://datasets/{SOLIDITY_CPT_DATASET_ID}":
            raise SolidityCPTSchemaError("source_uri differs from reviewed dataset")
        if self.address_is_unverified_hint is not True:
            raise SolidityCPTSchemaError("address must remain an unverified source claim")
        if self.deployed_bytecode_equality is not False:
            raise SolidityCPTSchemaError("source metadata cannot assert deployed bytecode equality")
        unknown_payload = set(self.payload) - set(_SOURCE_RECORD_PAYLOAD_FIELDS)
        if unknown_payload:
            raise SolidityCPTSchemaError(
                "source_record payload contains non-projection field(s): " + ", ".join(sorted(unknown_payload))
            )
        if any(
            isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes, bytearray))
            for value in self.payload.values()
        ):
            raise SolidityCPTSchemaError("source_record payload values must be source-free scalars")

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "address_is_unverified_hint": self.address_is_unverified_hint,
            "deployed_bytecode_equality": self.deployed_bytecode_equality,
            "raw_row_cid": self.raw_row_cid,
            "row_key": self.row_key,
            "source_body_cid": self.source_body_cid,
            "source_body_sha256": self.source_body_sha256,
            "source_row_id": self.source_row_id,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceRecord:
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            source_uri=value.get("source_uri", ""),
            source_revision=value.get("source_revision", ""),
            row_key=value.get("row_key", ""),
            source_row_id=value.get("source_row_id", ""),
            raw_row_cid=value.get("raw_row_cid", ""),
            source_body_cid=value.get("source_body_cid", ""),
            source_body_sha256=value.get("source_body_sha256", ""),
            address_is_unverified_hint=value.get("address_is_unverified_hint", False),
            deployed_bytecode_equality=value.get("deployed_bytecode_equality", True),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CodeUnit(CanonicalDerivedRecord):
    unit_kind: str
    language: str
    path: str

    RECORD_TYPE: ClassVar[str] = "code_unit"
    IDENTITY_DOMAIN: ClassVar[str] = f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/code-unit"
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset({"language", "path", "unit_kind"})

    def _validate_specific(self) -> None:
        for name in ("unit_kind", "language", "path"):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "path": self.path,
            "unit_kind": self.unit_kind,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodeUnit:
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            unit_kind=value.get("unit_kind", ""),
            language=value.get("language", ""),
            path=value.get("path", ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphNode(CanonicalDerivedRecord):
    node_type: str

    RECORD_TYPE: ClassVar[str] = "graph_node"
    IDENTITY_DOMAIN: ClassVar[str] = f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/graph-node"
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset({"node_type"})

    def _validate_specific(self) -> None:
        object.__setattr__(self, "node_type", _text(self.node_type, "node_type"))

    def _specific_dict(self) -> dict[str, Any]:
        return {"node_type": self.node_type}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GraphNode:
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            node_type=value.get("node_type", ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphEdge(CanonicalDerivedRecord):
    edge_type: str
    source_node_cid: str
    target_node_cid: str

    RECORD_TYPE: ClassVar[str] = "graph_edge"
    IDENTITY_DOMAIN: ClassVar[str] = f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/graph-edge"
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset({"edge_type", "source_node_cid", "target_node_cid"})

    def _validate_specific(self) -> None:
        object.__setattr__(self, "edge_type", _text(self.edge_type, "edge_type"))
        object.__setattr__(
            self,
            "source_node_cid",
            _cid(self.source_node_cid, "source_node_cid"),
        )
        object.__setattr__(
            self,
            "target_node_cid",
            _cid(self.target_node_cid, "target_node_cid"),
        )

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "edge_type": self.edge_type,
            "source_node_cid": self.source_node_cid,
            "target_node_cid": self.target_node_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GraphEdge:
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            edge_type=value.get("edge_type", ""),
            source_node_cid=value.get("source_node_cid", ""),
            target_node_cid=value.get("target_node_cid", ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyCandidate(CanonicalDerivedRecord):
    effect: str
    scope: Mapping[str, Any]
    authority: DerivedAuthority = DerivedAuthority.CANDIDATE

    RECORD_TYPE: ClassVar[str] = "policy_candidate"
    IDENTITY_DOMAIN: ClassVar[str] = f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/policy-candidate"
    EXPECTED_AUTHORITY: ClassVar[DerivedAuthority] = DerivedAuthority.CANDIDATE
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset({"effect", "scope"})

    def _validate_specific(self) -> None:
        object.__setattr__(self, "effect", _text(self.effect, "effect"))
        if self.effect not in {"allow", "deny", "require", "audit"}:
            raise SolidityCPTSchemaError("unknown candidate effect")
        object.__setattr__(self, "scope", _frozen_mapping(self.scope, "scope"))
        if not self.scope:
            raise SolidityCPTSchemaError("scope must not be empty")

    def _specific_dict(self) -> dict[str, Any]:
        return {"effect": self.effect, "scope": thaw_json(self.scope)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PolicyCandidate:
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            effect=value.get("effect", ""),
            scope=value.get("scope", {}),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FormalView(CanonicalDerivedRecord):
    formalism: str
    expression: str

    RECORD_TYPE: ClassVar[str] = "formal_view"
    IDENTITY_DOMAIN: ClassVar[str] = f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/formal-view"
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset({"expression", "formalism"})

    def _validate_specific(self) -> None:
        object.__setattr__(self, "formalism", _text(self.formalism, "formalism"))
        object.__setattr__(
            self,
            "expression",
            _text(self.expression, "expression", maximum=1_000_000),
        )

    def _specific_dict(self) -> dict[str, Any]:
        return {"expression": self.expression, "formalism": self.formalism}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FormalView:
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            formalism=value.get("formalism", ""),
            expression=value.get("expression", ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationRecord(CanonicalDerivedRecord):
    subject_cids: tuple[str, ...]
    metrics: Mapping[str, Any]

    RECORD_TYPE: ClassVar[str] = "evaluation"
    IDENTITY_DOMAIN: ClassVar[str] = f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/evaluation"
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset({"metrics", "subject_cids"})

    def _validate_specific(self) -> None:
        object.__setattr__(self, "subject_cids", _cid_tuple(self.subject_cids, "subject_cids"))
        object.__setattr__(self, "metrics", _frozen_mapping(self.metrics, "metrics"))
        if not self.metrics:
            raise SolidityCPTSchemaError("metrics must not be empty")

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "metrics": thaw_json(self.metrics),
            "subject_cids": list(self.subject_cids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvaluationRecord:
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            subject_cids=value.get("subject_cids", ()),
            metrics=value.get("metrics", {}),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseManifest(CanonicalDerivedRecord):
    dataset_name: str
    profile: str
    record_cids: tuple[str, ...]
    shard_cids: tuple[str, ...]

    RECORD_TYPE: ClassVar[str] = "release_manifest"
    IDENTITY_DOMAIN: ClassVar[str] = f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/release-manifest"
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset({"dataset_name", "profile", "record_cids", "shard_cids"})

    def _validate_specific(self) -> None:
        object.__setattr__(self, "dataset_name", _text(self.dataset_name, "dataset_name"))
        object.__setattr__(self, "profile", _text(self.profile, "profile"))
        object.__setattr__(self, "record_cids", _cid_tuple(self.record_cids, "record_cids"))
        object.__setattr__(self, "shard_cids", _cid_tuple(self.shard_cids, "shard_cids"))

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "profile": self.profile,
            "record_cids": list(self.record_cids),
            "shard_cids": list(self.shard_cids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReleaseManifest:
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            dataset_name=value.get("dataset_name", ""),
            profile=value.get("profile", ""),
            record_cids=value.get("record_cids", ()),
            shard_cids=value.get("shard_cids", ()),
        )


DerivedRecord = (
    SourceRecord | CodeUnit | GraphNode | GraphEdge | PolicyCandidate | FormalView | EvaluationRecord | ReleaseManifest
)

_RECORD_TYPES: Final[dict[str, type[CanonicalDerivedRecord]]] = {
    record_type.RECORD_TYPE: record_type
    for record_type in (
        SourceRecord,
        CodeUnit,
        GraphNode,
        GraphEdge,
        PolicyCandidate,
        FormalView,
        EvaluationRecord,
        ReleaseManifest,
    )
}


def record_from_dict(value: Mapping[str, Any]) -> DerivedRecord:
    """Strictly rehash one persisted record selected by ``record_type``."""

    value = _mapping(value, "record")
    try:
        decoder = _RECORD_TYPES[value.get("record_type")]
    except (KeyError, TypeError) as exc:
        raise SolidityCPTSchemaError(f"unknown record_type {value.get('record_type')!r}") from exc
    return decoder.from_dict(value)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class DerivedDataset:
    """Canonical aggregate with strict recursive rehash and lineage closure."""

    records: tuple[DerivedRecord, ...]
    lineage: TrustedLineage
    dataset_id: str = ""
    schema_version: str = SOLIDITY_CPT_DATASET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SOLIDITY_CPT_DATASET_SCHEMA_VERSION:
            raise SolidityCPTSchemaError("unsupported dataset schema_version")
        if not isinstance(self.lineage, TrustedLineage):
            raise SolidityCPTSchemaError("lineage must be TrustedLineage")
        if isinstance(self.records, (str, bytes, bytearray)) or not isinstance(self.records, Sequence):
            raise SolidityCPTSchemaError("records must be a sequence")
        records = tuple(self.records)
        if not records or any(not isinstance(item, CanonicalDerivedRecord) for item in records):
            raise SolidityCPTSchemaError("records must be non-empty canonical records")
        record_ids = tuple(item.record_id for item in records)
        if len(record_ids) != len(set(record_ids)):
            raise SolidityCPTSchemaError("records contain duplicate IDs")
        record_id_set = set(record_ids)
        source_roots = set(self.lineage.source_cids)
        config_roots = set(self.lineage.config_cids)
        source_rows = {item.row_id: item for item in self.lineage.source_rows}
        allowed_parents = record_id_set | set(self.lineage.external_parent_cids)
        for record in records:
            if not set(record.source_cids) <= source_roots:
                raise SolidityCPTSchemaError(f"record {record.record_id} has foreign source lineage")
            if record.config_cid not in config_roots:
                raise SolidityCPTSchemaError(f"record {record.record_id} has foreign producer config")
            if not set(record.parent_cids) <= allowed_parents:
                raise SolidityCPTSchemaError(f"record {record.record_id} has unresolved parent lineage")
            if record.record_id in record.parent_cids:
                raise SolidityCPTSchemaError("record cannot parent itself")
            if isinstance(record, SourceRecord):
                try:
                    source_row = source_rows[record.source_row_id]
                except KeyError as exc:
                    raise SolidityCPTSchemaError("source record is not bound to an admitted source row") from exc
                if (
                    record.raw_row_cid != source_row.raw_row_cid
                    or record.source_body_cid != source_row.source_body_cid
                    or record.source_body_sha256 != source_row.source_body_sha256
                    or record.config_cid != source_row.config_cid
                    or set(record.source_cids) != {source_row.source_snapshot_cid}
                    or record.row_key != f"train:{source_row.row_index}"
                ):
                    raise SolidityCPTSchemaError("source record differs from admitted row/body identity")
                expected_payload = {
                    "address": source_row.address,
                    "compiler": source_row.compiler,
                    "license": source_row.license,
                    "n_chars": source_row.n_chars,
                    "name": source_row.name,
                    "path": source_row.path,
                    "row_index": source_row.row_index,
                    "source_provider": source_row.source,
                }
                if thaw_json(record.payload) != expected_payload:
                    raise SolidityCPTSchemaError("source record metadata differs from admitted normalized row")
            if isinstance(record, GraphEdge) and (
                record.source_node_cid not in record_id_set or record.target_node_cid not in record_id_set
            ):
                raise SolidityCPTSchemaError("graph edge endpoints must resolve inside the dataset")
        ordered = tuple(sorted(records, key=lambda item: item.record_id))
        object.__setattr__(self, "records", ordered)
        computed = self.identity.cid
        if self.dataset_id and self.dataset_id != computed:
            raise SolidityCPTSchemaError("dataset_id does not match rehashed aggregate")
        object.__setattr__(self, "dataset_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "lineage": self.lineage.to_dict(),
            "records": [item.to_dict() for item in self.records],
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"dataset_id": self.dataset_id, **self.deterministic_dict()}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain=f"{SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX}/dataset",
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.dataset_id

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        expected_lineage: TrustedLineage,
    ) -> DerivedDataset:
        """Load persisted data using independently trusted lineage roots."""

        if not isinstance(expected_lineage, TrustedLineage):
            raise SolidityCPTSchemaError("persisted dataset load requires trusted expected_lineage")
        value = _mapping(value, "dataset")
        _exact_fields(
            value,
            frozenset({"dataset_id", "lineage", "records", "schema_version"}),
            "dataset",
        )
        if not value["dataset_id"]:
            raise SolidityCPTSchemaError("persisted dataset requires dataset_id")
        persisted_lineage = TrustedLineage.from_dict(_mapping(value["lineage"], "lineage"))
        if persisted_lineage != expected_lineage:
            raise SolidityCPTSchemaError("persisted dataset lineage differs from trusted context")
        raw_records = value["records"]
        if isinstance(raw_records, (str, bytes, bytearray)) or not isinstance(raw_records, Sequence):
            raise SolidityCPTSchemaError("records must be a sequence")
        return cls(
            records=tuple(record_from_dict(_mapping(item, "record")) for item in raw_records),
            lineage=expected_lineage,
            dataset_id=value["dataset_id"],
            schema_version=value["schema_version"],
        )

    @classmethod
    def from_json(
        cls,
        value: str | bytes | bytearray,
        *,
        expected_lineage: TrustedLineage,
    ) -> DerivedDataset:
        return cls.from_dict(
            _decode_json_object(value, "dataset"),
            expected_lineage=expected_lineage,
        )


# Descriptive aliases for downstream Solidity pipeline modules.
SolidityCPTSourceRecord = SourceRecord
SolidityCPTCodeUnit = CodeUnit
SolidityCPTGraphNode = GraphNode
SolidityCPTGraphEdge = GraphEdge
SolidityCPTPolicyCandidate = PolicyCandidate
SolidityCPTFormalView = FormalView
SolidityCPTEvaluation = EvaluationRecord
SolidityCPTReleaseManifest = ReleaseManifest
SolidityCPTDerivedDataset = DerivedDataset
DatasetReleaseManifest = ReleaseManifest
Evaluation = EvaluationRecord


__all__ = [
    "CanonicalDerivedRecord",
    "CodeUnit",
    "DatasetReleaseManifest",
    "DerivedAuthority",
    "DerivedDataset",
    "DerivedRecord",
    "Evaluation",
    "EvaluationRecord",
    "FormalView",
    "GraphEdge",
    "GraphNode",
    "PolicyCandidate",
    "ProducerConfig",
    "ReleaseManifest",
    "SOLIDITY_CPT_CONFIG_SCHEMA_VERSION",
    "SOLIDITY_CPT_DATASET_SCHEMA_VERSION",
    "SOLIDITY_CPT_IDENTITY_DOMAIN_PREFIX",
    "SOLIDITY_CPT_LINEAGE_SCHEMA_VERSION",
    "SOLIDITY_CPT_SCHEMA_VERSION",
    "SolidityCPTCodeUnit",
    "SolidityCPTDerivedDataset",
    "SolidityCPTEvaluation",
    "SolidityCPTFormalView",
    "SolidityCPTGraphEdge",
    "SolidityCPTGraphNode",
    "SolidityCPTPolicyCandidate",
    "SolidityCPTReleaseManifest",
    "SolidityCPTSchemaError",
    "SolidityCPTSourceRecord",
    "SourceRecord",
    "TrustedLineage",
    "canonical_config_cid",
    "record_from_dict",
]
