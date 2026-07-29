"""Serialized schema-version authority for Crypto IR kernel records.

Schema identifiers are exact, closed strings.  Registration order and module
import order never affect identity.  Unknown schema identifiers fail closed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping


SCHEMA_REGISTRY_SCHEMA: Final[str] = "ipfs-datasets.crypto-ir.schema-registry@1"
_SCHEMA_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$"
)
_MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1


class SchemaVersionError(ValueError):
    """Raised when a Crypto IR schema version or registry lookup is invalid."""


def _exact_text(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise SchemaVersionError(f"{field} must be an exact non-empty string")
    if value != value.strip():
        raise SchemaVersionError(f"{field} must not contain surrounding whitespace")
    if unicodedata.normalize("NFC", value) != value:
        raise SchemaVersionError(f"{field} must be NFC-normalized")
    if any(not character.isprintable() or character.isspace() for character in value):
        raise SchemaVersionError(
            f"{field} must contain only printable non-whitespace characters"
        )
    return value


def _component(value: Any, field: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise SchemaVersionError(f"{field} must be an integer")
    if not 0 <= value <= _MAX_SAFE_INTEGER:
        raise SchemaVersionError(
            f"{field} must be an integer in 0..{_MAX_SAFE_INTEGER}"
        )
    return value


@dataclass(frozen=True, slots=True, order=True)
class SchemaVersion:
    """One exact semantic-versioned shared schema identity."""

    name: str
    major: int
    minor: int = 0
    patch: int = 0

    def __post_init__(self) -> None:
        name = _exact_text(self.name, "name")
        if not _SCHEMA_NAME_RE.fullmatch(name):
            raise SchemaVersionError(
                "name must be a lowercase dot/dash-separated schema name"
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "major", _component(self.major, "major"))
        object.__setattr__(self, "minor", _component(self.minor, "minor"))
        object.__setattr__(self, "patch", _component(self.patch, "patch"))
        if self.major == 0:
            raise SchemaVersionError("shared durable schemas must have major >= 1")

    @property
    def version(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def identifier(self) -> str:
        return f"{self.name}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "major": self.major,
            "minor": self.minor,
            "name": self.name,
            "patch": self.patch,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SchemaVersion":
        if not isinstance(value, Mapping):
            raise SchemaVersionError("schema version must be a mapping")
        expected = {"name", "major", "minor", "patch", "identifier"}
        if set(value) != expected:
            raise SchemaVersionError(
                "schema version fields are closed "
                f"(missing={sorted(expected - set(value))}, "
                f"extra={sorted(set(value) - expected)})"
            )
        result = cls(
            name=value["name"],
            major=value["major"],
            minor=value["minor"],
            patch=value["patch"],
        )
        if type(value["identifier"]) is not str or value["identifier"] != result.identifier:
            raise SchemaVersionError(
                "schema version identifier does not match components"
            )
        return result


# Kernel model schemas (CRYPTOIR-G020).
CRYPTO_IR_MODEL_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.crypto-ir.model", 1, 0, 0
)
CRYPTO_IR_IDENTITY_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.crypto-ir.identity", 1, 0, 0
)
CRYPTO_IR_PROVENANCE_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.crypto-ir.provenance", 1, 0, 0
)
CRYPTO_IR_CHAIN_IDENTITY_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.crypto-ir.chain-identity", 1, 0, 0
)
CRYPTO_IR_ACCOUNT_IDENTITY_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.crypto-ir.account-identity", 1, 0, 0
)
CRYPTO_IR_UNSIGNED_INTENT_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.crypto-ir.unsigned-transaction-intent", 1, 0, 0
)
CRYPTO_IR_SERIALIZED_CANDIDATE_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.crypto-ir.serialized-transaction-candidate", 1, 0, 0
)
CRYPTO_IR_CONTRACT_ARTIFACT_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.crypto-ir.contract-artifact", 1, 0, 0
)
CRYPTO_IR_COMPLETENESS_RECEIPT_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.crypto-ir.completeness-receipt", 1, 0, 0
)

# Friendly aliases.
CRYPTO_IR_MODEL_SCHEMA: Final[SchemaVersion] = CRYPTO_IR_MODEL_SCHEMA_VERSION
CRYPTO_IR_IDENTITY_SCHEMA: Final[SchemaVersion] = CRYPTO_IR_IDENTITY_SCHEMA_VERSION
CRYPTO_IR_PROVENANCE_SCHEMA: Final[SchemaVersion] = CRYPTO_IR_PROVENANCE_SCHEMA_VERSION

# Stable string forms used in record schema_version fields.
CRYPTO_IR_MODEL_SCHEMA_ID: Final[str] = CRYPTO_IR_MODEL_SCHEMA_VERSION.identifier
CRYPTO_IR_KERNEL_SCHEMA_VERSION: Final[str] = "crypto-ir/v1"

_REGISTERED: Final[tuple[SchemaVersion, ...]] = (
    CRYPTO_IR_MODEL_SCHEMA_VERSION,
    CRYPTO_IR_IDENTITY_SCHEMA_VERSION,
    CRYPTO_IR_PROVENANCE_SCHEMA_VERSION,
    CRYPTO_IR_CHAIN_IDENTITY_SCHEMA_VERSION,
    CRYPTO_IR_ACCOUNT_IDENTITY_SCHEMA_VERSION,
    CRYPTO_IR_UNSIGNED_INTENT_SCHEMA_VERSION,
    CRYPTO_IR_SERIALIZED_CANDIDATE_SCHEMA_VERSION,
    CRYPTO_IR_CONTRACT_ARTIFACT_SCHEMA_VERSION,
    CRYPTO_IR_COMPLETENESS_RECEIPT_SCHEMA_VERSION,
)
if len({item.identifier for item in _REGISTERED}) != len(_REGISTERED):
    raise RuntimeError("duplicate Crypto IR schema registration")

SCHEMA_VERSIONS: Final[Mapping[str, SchemaVersion]] = MappingProxyType(
    {item.identifier: item for item in sorted(_REGISTERED)}
)


def get_schema_version(identifier: str) -> SchemaVersion:
    """Return an exact registered version or fail closed."""

    key = _exact_text(identifier, "identifier")
    try:
        return SCHEMA_VERSIONS[key]
    except KeyError as exc:
        raise SchemaVersionError(f"unknown shared schema: {key}") from exc


def schema_registry_descriptor() -> dict[str, Any]:
    """Return the deterministic, canonical registry payload."""

    return {
        "registry_schema": SCHEMA_REGISTRY_SCHEMA,
        "schemas": [item.to_dict() for item in sorted(_REGISTERED)],
    }


def is_registered_schema(identifier: str) -> bool:
    """Return True when *identifier* is an exact registered schema id."""

    if type(identifier) is not str:
        return False
    return identifier in SCHEMA_VERSIONS


__all__ = [
    "CRYPTO_IR_ACCOUNT_IDENTITY_SCHEMA_VERSION",
    "CRYPTO_IR_CHAIN_IDENTITY_SCHEMA_VERSION",
    "CRYPTO_IR_COMPLETENESS_RECEIPT_SCHEMA_VERSION",
    "CRYPTO_IR_CONTRACT_ARTIFACT_SCHEMA_VERSION",
    "CRYPTO_IR_IDENTITY_SCHEMA",
    "CRYPTO_IR_IDENTITY_SCHEMA_VERSION",
    "CRYPTO_IR_KERNEL_SCHEMA_VERSION",
    "CRYPTO_IR_MODEL_SCHEMA",
    "CRYPTO_IR_MODEL_SCHEMA_ID",
    "CRYPTO_IR_MODEL_SCHEMA_VERSION",
    "CRYPTO_IR_PROVENANCE_SCHEMA",
    "CRYPTO_IR_PROVENANCE_SCHEMA_VERSION",
    "CRYPTO_IR_SERIALIZED_CANDIDATE_SCHEMA_VERSION",
    "CRYPTO_IR_UNSIGNED_INTENT_SCHEMA_VERSION",
    "SCHEMA_REGISTRY_SCHEMA",
    "SCHEMA_VERSIONS",
    "SchemaVersion",
    "SchemaVersionError",
    "get_schema_version",
    "is_registered_schema",
    "schema_registry_descriptor",
]
