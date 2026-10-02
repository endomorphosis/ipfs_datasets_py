"""Serialized schema-version authority for software-contract analysis.

Language frontends consume this registry but do not extend it themselves.
Adding or changing a shared schema is an explicit compatibility decision owned
by DSCON-G105; registration order and module import order never affect the
result.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping


SCHEMA_REGISTRY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.schema-registry@1"
)
AST_IR_OBJECTIVE_VALIDATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.ast-ir-objective-validation@1"
)
AST_IR_OWNER_GOAL_ID: Final[str] = "DSCON-G105"
AST_IR_PACKET_GOAL_IDS: Final[tuple[str, ...]] = (
    "DSCON-G105",
    "DSCON-G110",
    "DSCON-G120",
)
AST_IR_REPAIR_TASK_ID: Final[str] = "DSCON-074"
OBJECTIVE_VALIDATION_EVIDENCE: Final[str] = "objective validation repair"
AST_IR_VALIDATION_COMMAND: Final[str] = (
    "python -m pytest -q "
    "ipfs_datasets_py/tests/unit/logic/software_contracts/test_ast_ir.py"
)
AST_IR_VALIDATED_ARTIFACTS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/software_contracts/__init__.py",
    "ipfs_datasets_py/ipfs_datasets_py/logic/software_contracts/ast_ir.py",
    "ipfs_datasets_py/ipfs_datasets_py/logic/software_contracts/schema_versions.py",
    "ipfs_datasets_py/tests/unit/logic/software_contracts/test_ast_ir.py",
)
_SCHEMA_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$"
)
_MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1


class SchemaVersionError(ValueError):
    """Raised when a shared schema version or registry lookup is invalid."""


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
    if type(value) is not int or not 0 <= value <= _MAX_SAFE_INTEGER:
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
            "name": self.name,
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "identifier": self.identifier,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SchemaVersion":
        if type(value) is not dict:
            raise SchemaVersionError("schema version must be an exact mapping")
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
            raise SchemaVersionError("schema version identifier does not match components")
        return result


AST_IR_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.software-contracts.ast-ir", 1, 0, 0
)
FRONTEND_CAPABILITY_SCHEMA_VERSION: Final[SchemaVersion] = SchemaVersion(
    "ipfs-datasets.software-contracts.frontend-capability", 1, 0, 0
)

# Friendly aliases for callers that prefer schema nouns over version nouns.
AST_IR_SCHEMA: Final[SchemaVersion] = AST_IR_SCHEMA_VERSION
FRONTEND_CAPABILITY_SCHEMA: Final[SchemaVersion] = (
    FRONTEND_CAPABILITY_SCHEMA_VERSION
)

_REGISTERED: Final[tuple[SchemaVersion, ...]] = (
    AST_IR_SCHEMA_VERSION,
    FRONTEND_CAPABILITY_SCHEMA_VERSION,
)
if len({item.identifier for item in _REGISTERED}) != len(_REGISTERED):
    raise RuntimeError("duplicate software-contract schema registration")

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
        "schema": SCHEMA_REGISTRY_SCHEMA,
        "owner_goal": AST_IR_OWNER_GOAL_ID,
        "compatibility": "exact-version-only",
        "schemas": [
            SCHEMA_VERSIONS[key].to_dict() for key in sorted(SCHEMA_VERSIONS)
        ],
    }


def ast_ir_objective_validation_contract() -> dict[str, Any]:
    """Return the deterministic DSCON-074 validation-gate evidence contract.

    The contract keeps the supervisor repair task aligned with the objective
    heap without making task metadata part of AST-record content identity.
    """

    return {
        "schema": AST_IR_OBJECTIVE_VALIDATION_SCHEMA,
        "evidence_term": OBJECTIVE_VALIDATION_EVIDENCE,
        "owner_goal": AST_IR_OWNER_GOAL_ID,
        "repair_task_id": AST_IR_REPAIR_TASK_ID,
        "packet_goals": list(AST_IR_PACKET_GOAL_IDS),
        "validation_command": AST_IR_VALIDATION_COMMAND,
        "validated_artifacts": list(AST_IR_VALIDATED_ARTIFACTS),
        "acceptance": {
            "canonical_values_fail_closed": True,
            "exact_shared_record_types": True,
            "frontend_identity_bound": True,
            "language_specific_payloads_rejected": True,
            "parser_resolution_separated": True,
            "canonical_cid_round_trip": True,
            "deterministic_golden_roots": True,
        },
    }


__all__ = [
    "AST_IR_SCHEMA",
    "AST_IR_SCHEMA_VERSION",
    "AST_IR_OBJECTIVE_VALIDATION_SCHEMA",
    "AST_IR_OWNER_GOAL_ID",
    "AST_IR_PACKET_GOAL_IDS",
    "AST_IR_REPAIR_TASK_ID",
    "AST_IR_VALIDATED_ARTIFACTS",
    "AST_IR_VALIDATION_COMMAND",
    "FRONTEND_CAPABILITY_SCHEMA",
    "FRONTEND_CAPABILITY_SCHEMA_VERSION",
    "OBJECTIVE_VALIDATION_EVIDENCE",
    "SCHEMA_REGISTRY_SCHEMA",
    "SCHEMA_VERSIONS",
    "SchemaVersion",
    "SchemaVersionError",
    "ast_ir_objective_validation_contract",
    "get_schema_version",
    "schema_registry_descriptor",
]
