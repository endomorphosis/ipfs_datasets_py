"""Allowlisted query-template registry and budgets (DQK-041).

Replaces arbitrary SQL exposure for untrusted callers with:

* versioned parameter schemas
* prepared (parameter-bound) templates
* tenant and column policy
* row / byte / time / depth limits
* cancellation
* append-only audit events
* deterministic query receipts

Untrusted callers never submit raw SQL. They submit a registered template id
and a parameter map that is validated against the template's versioned schema.
Template SQL itself is inspected at registration time and must not touch
``read_*`` functions, extension install/load, filesystem path scans, or
network surfaces.

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    ClassVar,
    Final,
    Mapping,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    ContractError,
    SnapshotId,
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
    parse_snapshot_id,
    parse_source_digest,
)

__all__ = [
    "QUERY_REGISTRY_SCHEMA",
    "QUERY_RECEIPT_SCHEMA",
    "QUERY_AUDIT_SCHEMA",
    "PARAMETER_SCHEMA_SCHEMA",
    "DEFAULT_QUERY_BUDGET",
    "DEFAULT_UNTRUSTED_QUERY_BUDGET",
    "FORBIDDEN_SQL_FRAGMENTS",
    "FORBIDDEN_READ_FUNCTIONS",
    "SENSITIVE_COLUMN_NAMES",
    "AuditEvent",
    "AuditLog",
    "CancellationToken",
    "ColumnClassification",
    "ColumnPolicy",
    "ColumnPolicyError",
    "ParameterSchema",
    "ParameterSpec",
    "ParameterType",
    "ParameterValidationError",
    "PreparedQuery",
    "QueryBudget",
    "QueryBudgetExceeded",
    "QueryCancelled",
    "QueryExecutor",
    "QueryReceipt",
    "QueryRegistry",
    "QueryRegistryError",
    "QueryResult",
    "QueryStatus",
    "QueryTemplate",
    "ResourceUsage",
    "SQLSurfaceDenied",
    "TenantPolicy",
    "TenantPolicyViolation",
    "TrustClass",
    "UnknownTemplateError",
    "bind_parameters",
    "default_builtin_templates",
    "deny_arbitrary_sql",
    "digest_parameters",
    "open_default_registry",
    "parameters_byte_size",
    "scan_sql_surface",
    "validate_parameters",
]


# ---------------------------------------------------------------------------
# Schema pins / constants
# ---------------------------------------------------------------------------

QUERY_REGISTRY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-query-registry@1"
)
QUERY_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-query-receipt@1"
)
QUERY_AUDIT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-query-audit@1"
)
PARAMETER_SCHEMA_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-parameter-schema@1"
)

_QUERY_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-041-lane0-attempt1-20260810"
)

_TEMPLATE_ID_RE = re.compile(
    r"^[a-z][a-z0-9_]{0,63}(?:\.[a-z][a-z0-9_]{0,63}){0,3}$"
)
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")

# Hard caps (fail closed).
MAX_TEMPLATE_SQL_BYTES: Final[int] = 64 * 1024
MAX_PARAMETER_BYTES: Final[int] = 256 * 1024
MAX_ROWS_HARD: Final[int] = 1_000_000
MAX_BYTES_HARD: Final[int] = 256 * 1024 * 1024
MAX_DURATION_MS_HARD: Final[int] = 600_000
MAX_DEPTH_HARD: Final[int] = 64
MAX_AUDIT_EVENTS: Final[int] = 100_000

# Closed denylist for dangerous SQL surfaces (case-insensitive fragment match).
FORBIDDEN_READ_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {
        "READ_CSV",
        "READ_CSV_AUTO",
        "READ_PARQUET",
        "READ_JSON",
        "READ_JSON_AUTO",
        "READ_NDJSON",
        "READ_BLOB",
        "READ_TEXT",
        "READ_XLSX",
        "READ_YAML",
        "READ_TOML",
        "GLOB",
        "LIST_DIR",
        "LIST_FILES",
    }
)

FORBIDDEN_SQL_FRAGMENTS: Final[frozenset[str]] = frozenset(
    {
        "INSTALL ",
        "LOAD ",
        "COPY ",
        "ATTACH ",
        "DETACH ",
        "EXPORT ",
        "IMPORT ",
        "PRAGMA ",
        "CALL ",
        "SET ",
        "RESET ",
        "GRANT ",
        "REVOKE ",
        "CREATE ",
        "DROP ",
        "ALTER ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "TRUNCATE ",
        "HTTPFS",
        "FROM '",
        'FROM "',
        "://",
        "S3://",
        "HTTP://",
        "HTTPS://",
        "GS://",
        "AZ://",
    }
) | FORBIDDEN_READ_FUNCTIONS

# Column names that must never appear on a query-visible result surface.
SENSITIVE_COLUMN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "private_key",
        "private_keys",
        "seed",
        "seeds",
        "mnemonic",
        "signing_payload",
        "signing_key",
        "secret",
        "secrets",
        "password",
        "token",
        "quack_token",
        "api_key",
        "encryption_key",
        "raw_payload",
        "wallet_secret",
        "recovery_phrase",
        "seed_phrase",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QueryRegistryError(ValueError):
    """Fail-closed rejection of a registry, template, policy, or execution input."""


class UnknownTemplateError(QueryRegistryError):
    """Raised when a template id is not on the allowlist."""

    def __init__(self, template_id: str) -> None:
        super().__init__(f"query template not allowlisted: {template_id!r}")
        self.template_id = template_id
        self.reason_code = "query.unknown_template"


class ParameterValidationError(QueryRegistryError):
    """Raised when parameters fail the versioned schema."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.reason_code = "query.parameter_validation"


class SQLSurfaceDenied(QueryRegistryError):
    """Raised when SQL touches a denied extension/filesystem/network surface."""

    def __init__(self, surface: str) -> None:
        super().__init__(
            f"SQL surface denied: {surface} "
            "(arbitrary SQL, read_* functions, extension/filesystem/network "
            "surfaces are forbidden for untrusted callers)"
        )
        self.surface = surface
        self.reason_code = "query.sql_surface_denied"


class TenantPolicyViolation(QueryRegistryError):
    """Raised when a row or parameter violates tenant isolation."""

    def __init__(self, message: str = "tenant policy violation") -> None:
        super().__init__(message)
        self.reason_code = "query.tenant_policy_violation"


class ColumnPolicyError(QueryRegistryError):
    """Raised when a result column fails classification or visibility policy."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.reason_code = "query.column_policy"


class QueryBudgetExceeded(QueryRegistryError):
    """Raised when a query exhausts a resource budget."""

    def __init__(self, kind: str, limit: int | float) -> None:
        super().__init__(f"query budget exceeded: {kind} limit={limit}")
        self.kind = kind
        self.limit = limit
        self.reason_code = "query.budget_exceeded"


class QueryCancelled(QueryRegistryError):
    """Raised when a cancellation token fires during execution."""

    def __init__(self, reason: str = "cancelled") -> None:
        super().__init__(f"query cancelled: {reason}")
        self.reason = reason
        self.reason_code = "query.cancelled"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ParameterType(str, Enum):
    """Closed set of parameter value types for versioned schemas."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DIGEST = "digest"
    SNAPSHOT_ID = "snapshot_id"
    TENANT_ID = "tenant_id"
    IDENTIFIER = "identifier"
    STRING_LIST = "string_list"


class ColumnClassification(str, Enum):
    """Result-column classification. ``SECRET`` is never query-visible."""

    PUBLIC = "public"
    INTERNAL = "internal"
    REDACTED = "redacted"
    SECRET = "secret"


class TrustClass(str, Enum):
    """Caller trust class that may invoke a template."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class QueryStatus(str, Enum):
    """Terminal status recorded on a query receipt."""

    SUCCEEDED = "succeeded"
    TRUNCATED = "truncated"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"
    DENIED = "denied"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# SQL surface denial
# ---------------------------------------------------------------------------


def _normalize_sql(sql: str) -> str:
    return " ".join(str(sql).strip().split())


def scan_sql_surface(sql: str) -> str:
    """Validate that ``sql`` is a safe SELECT/WITH template body.

    Returns the whitespace-normalized SQL. Rejects ``read_*`` functions,
    extension install/load, filesystem path scans, network schemes, and all
    mutating / configuration surfaces. Multi-statement SQL is rejected.
    """

    if not isinstance(sql, str) or not sql.strip():
        raise SQLSurfaceDenied("empty_sql")
    text = _normalize_sql(sql)
    if len(text.encode("utf-8")) > MAX_TEMPLATE_SQL_BYTES:
        raise SQLSurfaceDenied("sql_too_large")
    if "\x00" in text:
        raise SQLSurfaceDenied("nul_byte")
    # Single statement only (allow trailing semicolon).
    stripped = text.rstrip(";").strip()
    if ";" in stripped:
        raise SQLSurfaceDenied("multi_statement")
    upper = stripped.upper()
    if not upper.startswith(("SELECT ", "WITH ", "EXPLAIN ", "DESCRIBE ", "SHOW ")):
        raise SQLSurfaceDenied("non_select")
    for fragment in sorted(FORBIDDEN_SQL_FRAGMENTS, key=len, reverse=True):
        if fragment in upper:
            raise SQLSurfaceDenied(fragment.strip())
    # Catch bare read_* call forms not listed above.
    if re.search(r"\bREAD_[A-Z0-9_]+\s*\(", upper):
        raise SQLSurfaceDenied("read_*")
    # Parameter placeholders must be positional ``?`` only (no $1 / :name injection).
    if re.search(r"\$\d+|:[A-Za-z_]", stripped):
        raise SQLSurfaceDenied("named_or_numbered_bind")
    return stripped


def deny_arbitrary_sql(sql: str | None = None, *, template_id: str | None = None) -> None:
    """Explicitly reject untrusted raw-SQL submission paths.

    Callers that attempt to pass SQL instead of a template id fail closed here.
    """

    if sql is not None and str(sql).strip():
        raise SQLSurfaceDenied("arbitrary_sql")
    if template_id is None or not str(template_id).strip():
        raise QueryRegistryError(
            "untrusted callers must submit a registered template_id; "
            "arbitrary SQL is denied"
        )


# ---------------------------------------------------------------------------
# Parameter schemas (versioned)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """One named parameter in a versioned parameter schema."""

    name: str
    param_type: ParameterType
    required: bool = True
    max_length: int = 1024
    description: str = ""
    default: Any = None
    allowed_values: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not _PARAM_NAME_RE.match(name):
            raise ParameterValidationError(f"invalid parameter name {self.name!r}")
        object.__setattr__(self, "name", name)

        if not isinstance(self.param_type, ParameterType):
            try:
                object.__setattr__(
                    self, "param_type", ParameterType(str(self.param_type))
                )
            except ValueError as exc:
                raise ParameterValidationError(
                    f"unsupported parameter type {self.param_type!r}"
                ) from exc

        if not isinstance(self.required, bool):
            raise ParameterValidationError("required must be a bool")
        if (
            not isinstance(self.max_length, int)
            or isinstance(self.max_length, bool)
            or self.max_length < 1
            or self.max_length > 65_536
        ):
            raise ParameterValidationError("max_length out of range")
        object.__setattr__(self, "description", str(self.description or ""))

        allowed = self.allowed_values or frozenset()
        if not isinstance(allowed, (frozenset, set, tuple, list)):
            raise ParameterValidationError("allowed_values must be a collection")
        object.__setattr__(
            self,
            "allowed_values",
            frozenset(str(v) for v in allowed),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.param_type.value,
            "required": self.required,
            "max_length": self.max_length,
            "description": self.description,
        }
        if self.default is not None:
            payload["default"] = self.default
        if self.allowed_values:
            payload["allowed_values"] = sorted(self.allowed_values)
        return payload


@dataclass(frozen=True, slots=True)
class ParameterSchema:
    """Versioned closed set of parameter specifications for one template."""

    SCHEMA: ClassVar[str] = PARAMETER_SCHEMA_SCHEMA

    schema_version: int
    parameters: tuple[ParameterSpec, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version < 1
        ):
            raise ParameterValidationError("schema_version must be a positive int")
        if not isinstance(self.parameters, tuple):
            object.__setattr__(self, "parameters", tuple(self.parameters))
        names: set[str] = set()
        for spec in self.parameters:
            if not isinstance(spec, ParameterSpec):
                raise ParameterValidationError(
                    "parameters must be ParameterSpec instances"
                )
            if spec.name in names:
                raise ParameterValidationError(
                    f"duplicate parameter name {spec.name!r}"
                )
            names.add(spec.name)

    @property
    def by_name(self) -> Mapping[str, ParameterSpec]:
        return MappingProxyType({p.name: p for p in self.parameters})

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PARAMETER_SCHEMA_SCHEMA,
            "schema_version": self.schema_version,
            "parameters": [p.to_dict() for p in self.parameters],
        }


def parameters_byte_size(params: Mapping[str, Any]) -> int:
    """Conservative UTF-8 size estimate for parameter budget enforcement."""

    total = 0

    def visit(item: Any) -> None:
        nonlocal total
        if isinstance(item, str):
            total += len(item.encode("utf-8", errors="replace"))
        elif isinstance(item, (bytes, bytearray, memoryview)):
            total += len(item)
        elif isinstance(item, Mapping):
            for key, child in item.items():
                if isinstance(key, str):
                    total += len(key.encode("utf-8", errors="replace"))
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            for child in item:
                visit(child)
        elif item is None or isinstance(item, (bool, int, float)):
            total += 8
        else:
            total += len(repr(item).encode("utf-8", errors="replace"))

    visit(params)
    return total


def digest_parameters(params: Mapping[str, Any]) -> str:
    """Return a deterministic ``sha256:...`` digest of ``params``."""

    return content_identity(dict(params))


def _coerce_parameter(spec: ParameterSpec, value: Any) -> Any:
    """Coerce and validate one parameter value against its spec."""

    if value is None:
        if spec.default is not None:
            value = spec.default
        elif not spec.required:
            return None
        else:
            raise ParameterValidationError(
                f"parameter {spec.name!r} is required"
            )

    ptype = spec.param_type

    if ptype is ParameterType.STRING:
        if not isinstance(value, str):
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be a string"
            )
        text = value.strip()
        if len(text.encode("utf-8")) > spec.max_length:
            raise ParameterValidationError(
                f"parameter {spec.name!r} exceeds max_length"
            )
        if "\x00" in text:
            raise ParameterValidationError(
                f"parameter {spec.name!r} contains NUL"
            )
        if spec.allowed_values and text not in spec.allowed_values:
            raise ParameterValidationError(
                f"parameter {spec.name!r} not in allowed_values"
            )
        return text

    if ptype is ParameterType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be an integer"
            )
        return value

    if ptype is ParameterType.FLOAT:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be a number"
            )
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be finite"
            )
        return number

    if ptype is ParameterType.BOOLEAN:
        if not isinstance(value, bool):
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be a bool"
            )
        return value

    if ptype is ParameterType.DIGEST:
        if not isinstance(value, str):
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be a digest string"
            )
        try:
            return parse_source_digest(value)
        except ContractError as exc:
            raise ParameterValidationError(
                f"parameter {spec.name!r}: {exc}"
            ) from exc

    if ptype is ParameterType.SNAPSHOT_ID:
        if not isinstance(value, str):
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be a snapshot id string"
            )
        try:
            return parse_snapshot_id(value)
        except ContractError as exc:
            raise ParameterValidationError(
                f"parameter {spec.name!r}: {exc}"
            ) from exc

    if ptype is ParameterType.TENANT_ID:
        if not isinstance(value, str) or not value.strip():
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be a non-empty tenant id"
            )
        text = value.strip()
        if not _TENANT_RE.match(text):
            raise ParameterValidationError(
                f"parameter {spec.name!r} is not a safe tenant token"
            )
        if len(text.encode("utf-8")) > spec.max_length:
            raise ParameterValidationError(
                f"parameter {spec.name!r} exceeds max_length"
            )
        return text

    if ptype is ParameterType.IDENTIFIER:
        if not isinstance(value, str) or not value.strip():
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be a non-empty identifier"
            )
        text = value.strip()
        if not _SAFE_IDENT.match(text):
            raise ParameterValidationError(
                f"parameter {spec.name!r} is not a safe SQL identifier"
            )
        return text

    if ptype is ParameterType.STRING_LIST:
        if not isinstance(value, (list, tuple)):
            raise ParameterValidationError(
                f"parameter {spec.name!r} must be a list of strings"
            )
        items: list[str] = []
        total = 0
        for item in value:
            if not isinstance(item, str):
                raise ParameterValidationError(
                    f"parameter {spec.name!r} items must be strings"
                )
            text = item.strip()
            if not text:
                raise ParameterValidationError(
                    f"parameter {spec.name!r} items must be non-empty"
                )
            total += len(text.encode("utf-8"))
            if total > spec.max_length:
                raise ParameterValidationError(
                    f"parameter {spec.name!r} exceeds max_length"
                )
            if "\x00" in text:
                raise ParameterValidationError(
                    f"parameter {spec.name!r} contains NUL"
                )
            items.append(text)
        return tuple(items)

    raise ParameterValidationError(
        f"unsupported parameter type {ptype!r}"
    )


def validate_parameters(
    schema: ParameterSchema,
    params: Mapping[str, Any] | None,
    *,
    max_parameter_bytes: int = MAX_PARAMETER_BYTES,
) -> dict[str, Any]:
    """Validate ``params`` against ``schema`` (fail closed on unknown keys)."""

    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        raise ParameterValidationError("parameters must be a mapping")
    raw = {str(k): v for k, v in params.items()}
    known = schema.by_name
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ParameterValidationError(
            f"unknown parameters rejected: {', '.join(unknown)}"
        )
    if parameters_byte_size(raw) > max_parameter_bytes:
        raise QueryBudgetExceeded("parameter_bytes", max_parameter_bytes)

    out: dict[str, Any] = {}
    for name, spec in known.items():
        if name in raw:
            out[name] = _coerce_parameter(spec, raw[name])
        elif spec.required and spec.default is None:
            raise ParameterValidationError(f"parameter {name!r} is required")
        elif spec.default is not None:
            out[name] = _coerce_parameter(spec, None)
        # else: optional, omit
    return out


# ---------------------------------------------------------------------------
# Tenant / column policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TenantPolicy:
    """Row-level tenant isolation for allowlisted queries.

    Every bound parameter set and every result row that carries ``tenant_id``
    must match this policy. Optional catalog-domain allowlists further
    restrict multi-tenant federation.
    """

    tenant_id: str
    allowed_domains: frozenset[str] = field(default_factory=frozenset)
    policy_id: str = ""

    def __post_init__(self) -> None:
        tenant = str(self.tenant_id or "").strip()
        if not tenant or not _TENANT_RE.match(tenant):
            raise QueryRegistryError(f"invalid tenant_id {self.tenant_id!r}")
        object.__setattr__(self, "tenant_id", tenant)

        domains = self.allowed_domains or frozenset()
        if not isinstance(domains, (frozenset, set, tuple, list)):
            raise QueryRegistryError("allowed_domains must be a collection")
        frozen = frozenset(str(d).strip() for d in domains if str(d).strip())
        for domain in frozen:
            if not _SAFE_TOKEN.fullmatch(domain):
                raise QueryRegistryError(f"invalid domain token {domain!r}")
        object.__setattr__(self, "allowed_domains", frozen)

        policy_id = str(self.policy_id or "").strip()
        if not policy_id:
            policy_id = content_identity(
                {
                    "tenant_id": tenant,
                    "allowed_domains": sorted(frozen),
                }
            )
        elif not _SAFE_TOKEN.fullmatch(policy_id) and not policy_id.startswith(
            "sha256:"
        ):
            raise QueryRegistryError(f"invalid policy_id {self.policy_id!r}")
        object.__setattr__(self, "policy_id", policy_id)

    def permits_tenant(self, tenant_id: str | None) -> bool:
        return (
            isinstance(tenant_id, str)
            and tenant_id.strip() == self.tenant_id
        )

    def permits_domain(self, domain: str | None) -> bool:
        if not self.allowed_domains:
            return True
        if domain is None or not str(domain).strip():
            return False
        return str(domain).strip() in self.allowed_domains

    def enforce_parameters(self, params: Mapping[str, Any]) -> None:
        tenant = params.get("tenant_id")
        if tenant is not None and not self.permits_tenant(str(tenant)):
            raise TenantPolicyViolation(
                "parameter tenant_id does not match tenant policy"
            )

    def enforce_row(self, row: Mapping[str, Any], *, surface: str = "result") -> None:
        if "tenant_id" in row and not self.permits_tenant(
            str(row.get("tenant_id") or "")
        ):
            raise TenantPolicyViolation(
                f"{surface} row tenant does not match tenant policy"
            )
        domain = row.get("domain")
        if domain is not None and not self.permits_domain(str(domain)):
            raise TenantPolicyViolation(
                f"{surface} row domain not allowed by tenant policy"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "tenant_id": self.tenant_id,
            "allowed_domains": sorted(self.allowed_domains),
        }


@dataclass(frozen=True, slots=True)
class ColumnPolicy:
    """Allowlisted result columns with closed classifications.

    Secret and sensitive-named columns are rejected at construction. Only
    columns listed here may appear on the projected result surface.
    """

    columns: Mapping[str, ColumnClassification]

    def __post_init__(self) -> None:
        if not isinstance(self.columns, Mapping) or not self.columns:
            raise ColumnPolicyError("column policy requires at least one column")
        frozen: dict[str, ColumnClassification] = {}
        for name, klass in self.columns.items():
            if not isinstance(name, str) or not _SAFE_IDENT.match(name):
                raise ColumnPolicyError(f"invalid column name {name!r}")
            if name.lower() in SENSITIVE_COLUMN_NAMES:
                raise ColumnPolicyError(
                    f"column {name!r} is forbidden on query-visible surface"
                )
            if not isinstance(klass, ColumnClassification):
                try:
                    klass = ColumnClassification(str(klass))
                except ValueError as exc:
                    raise ColumnPolicyError(
                        f"invalid classification for {name!r}"
                    ) from exc
            if klass is ColumnClassification.SECRET:
                raise ColumnPolicyError(
                    f"column {name!r} classified as secret; forbidden"
                )
            frozen[name] = klass
        object.__setattr__(self, "columns", MappingProxyType(frozen))

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.columns))

    @property
    def identity_id(self) -> str:
        return content_identity(
            {name: klass.value for name, klass in sorted(self.columns.items())}
        )

    def project_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Project ``row`` onto allowlisted non-secret columns only."""

        if not isinstance(row, Mapping):
            raise ColumnPolicyError("result row must be a mapping")
        projected: dict[str, Any] = {}
        for name, klass in self.columns.items():
            if name not in row:
                continue
            if klass is ColumnClassification.SECRET:
                raise ColumnPolicyError(f"secret column {name!r} cannot project")
            if klass is ColumnClassification.REDACTED:
                projected[name] = "***"
            else:
                projected[name] = row[name]
        # Reject unknown columns that look sensitive even if dropped.
        for key in row:
            if not isinstance(key, str):
                raise ColumnPolicyError("column names must be strings")
            if key.lower() in SENSITIVE_COLUMN_NAMES:
                raise ColumnPolicyError(
                    f"result column {key!r} is forbidden on query-visible surface"
                )
        return projected

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": {
                name: klass.value for name, klass in sorted(self.columns.items())
            },
            "identity_id": self.identity_id,
        }


# ---------------------------------------------------------------------------
# Budgets / cancellation / resource usage
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryBudget:
    """Hard caps enforced per allowlisted query execution.

    Covers row count, result byte size, wall-clock duration, recursive depth,
    and bound-parameter payload size.
    """

    max_rows: int = 5_000
    max_bytes: int = 4 * 1024 * 1024
    max_duration_ms: int = 5_000
    max_depth: int = 8
    max_parameter_bytes: int = 65_536

    def __post_init__(self) -> None:
        bounds = (
            ("max_rows", self.max_rows, 1, MAX_ROWS_HARD),
            ("max_bytes", self.max_bytes, 1, MAX_BYTES_HARD),
            ("max_duration_ms", self.max_duration_ms, 1, MAX_DURATION_MS_HARD),
            ("max_depth", self.max_depth, 0, MAX_DEPTH_HARD),
            ("max_parameter_bytes", self.max_parameter_bytes, 1, MAX_PARAMETER_BYTES),
        )
        for name, value, lo, hi in bounds:
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < lo
                or value > hi
            ):
                raise QueryRegistryError(
                    f"{name} must be an int in [{lo}, {hi}], got {value!r}"
                )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_rows": self.max_rows,
            "max_bytes": self.max_bytes,
            "max_duration_ms": self.max_duration_ms,
            "max_depth": self.max_depth,
            "max_parameter_bytes": self.max_parameter_bytes,
        }


DEFAULT_QUERY_BUDGET: Final[QueryBudget] = QueryBudget(
    max_rows=10_000,
    max_bytes=8 * 1024 * 1024,
    max_duration_ms=10_000,
    max_depth=8,
    max_parameter_bytes=65_536,
)

DEFAULT_UNTRUSTED_QUERY_BUDGET: Final[QueryBudget] = QueryBudget(
    max_rows=1_000,
    max_bytes=1 * 1024 * 1024,
    max_duration_ms=3_000,
    max_depth=4,
    max_parameter_bytes=16_384,
)


class CancellationToken:
    """Thread-safe cancellation signal for allowlisted query execution.

    Cancelling a query must never roll back or interrupt an unrelated
    control-plane writer transaction; the token is advisory to the executor.
    """

    __slots__ = ("_event", "_reason", "_lock")

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: str = ""
        self._lock = threading.Lock()

    def cancel(self, reason: str = "cancelled") -> None:
        with self._lock:
            if not self._event.is_set():
                self._reason = str(reason or "cancelled")
            self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def check(self) -> None:
        if self._event.is_set():
            raise QueryCancelled(self._reason or "cancelled")


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    """Observed resource consumption for one query execution."""

    rows: int = 0
    bytes: int = 0
    duration_ms: int = 0
    depth: int = 0
    parameter_bytes: int = 0

    def __post_init__(self) -> None:
        for name in ("rows", "bytes", "duration_ms", "depth", "parameter_bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise QueryRegistryError(f"{name} must be a non-negative int")

    def to_dict(self) -> dict[str, int]:
        return {
            "rows": self.rows,
            "bytes": self.bytes,
            "duration_ms": self.duration_ms,
            "depth": self.depth,
            "parameter_bytes": self.parameter_bytes,
        }


class _BudgetMeter:
    """Mutable meter that enforces a :class:`QueryBudget` during execution."""

    __slots__ = (
        "budget",
        "started_monotonic",
        "rows",
        "bytes",
        "depth",
        "parameter_bytes",
    )

    def __init__(self, budget: QueryBudget, *, parameter_bytes: int = 0) -> None:
        self.budget = budget
        self.started_monotonic = time.monotonic()
        self.rows = 0
        self.bytes = 0
        self.depth = 0
        self.parameter_bytes = parameter_bytes
        if parameter_bytes > budget.max_parameter_bytes:
            raise QueryBudgetExceeded(
                "parameter_bytes", budget.max_parameter_bytes
            )

    def check_time(self) -> None:
        elapsed_ms = int((time.monotonic() - self.started_monotonic) * 1000)
        if elapsed_ms > self.budget.max_duration_ms:
            raise QueryBudgetExceeded("time", self.budget.max_duration_ms)

    def check_depth(self, depth: int) -> None:
        if depth > self.budget.max_depth:
            raise QueryBudgetExceeded("depth", self.budget.max_depth)
        if depth > self.depth:
            self.depth = depth

    def record_row(self, row_bytes: int = 0) -> None:
        self.check_time()
        self.rows += 1
        self.bytes += max(0, int(row_bytes))
        if self.rows > self.budget.max_rows:
            raise QueryBudgetExceeded("rows", self.budget.max_rows)
        if self.bytes > self.budget.max_bytes:
            raise QueryBudgetExceeded("bytes", self.budget.max_bytes)

    def would_exceed_rows(self) -> bool:
        return self.rows >= self.budget.max_rows

    def snapshot(self) -> ResourceUsage:
        elapsed_ms = int((time.monotonic() - self.started_monotonic) * 1000)
        return ResourceUsage(
            rows=self.rows,
            bytes=self.bytes,
            duration_ms=max(0, elapsed_ms),
            depth=self.depth,
            parameter_bytes=self.parameter_bytes,
        )


# ---------------------------------------------------------------------------
# Query templates + registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    """One allowlisted, versioned, prepared DuckDB SQL template.

    SQL is fixed at registration time and scanned for denied surfaces.
    Callers never interpolate values: only positional ``?`` binds are used.
    """

    template_id: str
    version: int
    sql: str
    parameter_schema: ParameterSchema
    column_policy: ColumnPolicy
    budget: QueryBudget = field(default_factory=lambda: DEFAULT_QUERY_BUDGET)
    allowed_trust: frozenset[TrustClass] = field(
        default_factory=lambda: frozenset({TrustClass.TRUSTED, TrustClass.UNTRUSTED})
    )
    description: str = ""
    domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        tid = str(self.template_id or "").strip()
        if not _TEMPLATE_ID_RE.match(tid):
            raise QueryRegistryError(f"invalid template_id {self.template_id!r}")
        object.__setattr__(self, "template_id", tid)

        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or self.version < 1
        ):
            raise QueryRegistryError("template version must be a positive int")

        sql = scan_sql_surface(self.sql)
        object.__setattr__(self, "sql", sql)

        if not isinstance(self.parameter_schema, ParameterSchema):
            raise QueryRegistryError("parameter_schema must be a ParameterSchema")
        if not isinstance(self.column_policy, ColumnPolicy):
            raise QueryRegistryError("column_policy must be a ColumnPolicy")
        if not isinstance(self.budget, QueryBudget):
            raise QueryRegistryError("budget must be a QueryBudget")

        trust = self.allowed_trust or frozenset()
        if not isinstance(trust, (frozenset, set, tuple, list)):
            raise QueryRegistryError("allowed_trust must be a collection")
        frozen_trust: set[TrustClass] = set()
        for item in trust:
            if isinstance(item, TrustClass):
                frozen_trust.add(item)
            else:
                try:
                    frozen_trust.add(TrustClass(str(item)))
                except ValueError as exc:
                    raise QueryRegistryError(
                        f"invalid trust class {item!r}"
                    ) from exc
        if not frozen_trust:
            raise QueryRegistryError("allowed_trust must be non-empty")
        object.__setattr__(self, "allowed_trust", frozenset(frozen_trust))

        object.__setattr__(self, "description", str(self.description or ""))

        domains = self.domains or ()
        if not isinstance(domains, tuple):
            domains = tuple(domains)
        clean_domains: list[str] = []
        for domain in domains:
            text = str(domain).strip()
            if not text or not _SAFE_TOKEN.fullmatch(text):
                raise QueryRegistryError(f"invalid domain {domain!r}")
            clean_domains.append(text)
        object.__setattr__(self, "domains", tuple(clean_domains))

        # Ensure placeholder count is non-negative and documented.
        placeholder_count = sql.count("?")
        required = sum(1 for p in self.parameter_schema.parameters if p.required)
        # Templates may use a parameter more than once; require at least as
        # many placeholders as required parameters when any required exist.
        if required and placeholder_count < 1:
            raise QueryRegistryError(
                f"template {tid!r} declares required parameters but has no "
                "positional placeholders"
            )

    @property
    def identity_id(self) -> str:
        return content_identity(
            {
                "template_id": self.template_id,
                "version": self.version,
                "sql": self.sql,
                "parameter_schema": self.parameter_schema.to_dict(),
                "column_policy": self.column_policy.to_dict(),
                "budget": self.budget.to_dict(),
                "allowed_trust": sorted(t.value for t in self.allowed_trust),
                "domains": list(self.domains),
            }
        )

    def permits_trust(self, trust: TrustClass) -> bool:
        return trust in self.allowed_trust

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUERY_REGISTRY_SCHEMA,
            "template_id": self.template_id,
            "version": self.version,
            "description": self.description,
            "sql": self.sql,
            "parameter_schema": self.parameter_schema.to_dict(),
            "column_policy": self.column_policy.to_dict(),
            "budget": self.budget.to_dict(),
            "allowed_trust": sorted(t.value for t in self.allowed_trust),
            "domains": list(self.domains),
            "identity_id": self.identity_id,
        }


@dataclass(frozen=True, slots=True)
class PreparedQuery:
    """Template + validated parameters ready for bind/execute (no SQL mutation)."""

    template: QueryTemplate
    parameters: Mapping[str, Any]
    parameters_digest: str
    bind_values: tuple[Any, ...]
    trust: TrustClass
    tenant_policy: TenantPolicy
    snapshot: SnapshotId

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template.template_id,
            "template_version": self.template.version,
            "parameters_digest": self.parameters_digest,
            "parameters": dict(self.parameters),
            "bind_values": list(self.bind_values),
            "trust": self.trust.value,
            "tenant_policy": self.tenant_policy.to_dict(),
            "snapshot": self.snapshot.to_dict(),
        }


def bind_parameters(
    template: QueryTemplate,
    params: Mapping[str, Any] | None,
    *,
    parameter_order: Sequence[str] | None = None,
) -> tuple[dict[str, Any], tuple[Any, ...], str]:
    """Validate parameters and produce ordered bind values for ``?`` placeholders.

    When ``parameter_order`` is omitted, required parameters appear first in
    declaration order, followed by optional parameters that were supplied.
    List parameters expand element-wise.
    """

    validated = validate_parameters(
        template.parameter_schema,
        params,
        max_parameter_bytes=template.budget.max_parameter_bytes,
    )
    if parameter_order is None:
        order = [p.name for p in template.parameter_schema.parameters if p.name in validated]
    else:
        order = list(parameter_order)
        for name in order:
            if name not in template.parameter_schema.by_name:
                raise ParameterValidationError(
                    f"bind order references unknown parameter {name!r}"
                )

    bind: list[Any] = []
    for name in order:
        value = validated.get(name)
        if value is None:
            continue
        if isinstance(value, tuple):
            bind.extend(value)
        else:
            bind.append(value)

    digest = digest_parameters(validated)
    return validated, tuple(bind), digest


class QueryRegistry:
    """Versioned allowlist of prepared query templates.

    Registration is the only path that introduces SQL into the system.
    Untrusted execution paths may only resolve templates by id.
    """

    def __init__(self) -> None:
        self._templates: dict[str, QueryTemplate] = {}
        self._lock = threading.RLock()

    def register(self, template: QueryTemplate, *, replace: bool = False) -> None:
        if not isinstance(template, QueryTemplate):
            raise QueryRegistryError("template must be a QueryTemplate")
        with self._lock:
            existing = self._templates.get(template.template_id)
            if existing is not None and not replace:
                raise QueryRegistryError(
                    f"template already registered: {template.template_id!r}"
                )
            # Re-scan SQL to guarantee surface policy at registration time.
            scan_sql_surface(template.sql)
            self._templates[template.template_id] = template

    def unregister(self, template_id: str) -> None:
        with self._lock:
            self._templates.pop(str(template_id).strip(), None)

    def get(self, template_id: str) -> QueryTemplate:
        tid = str(template_id or "").strip()
        with self._lock:
            template = self._templates.get(tid)
        if template is None:
            raise UnknownTemplateError(tid)
        return template

    def list_templates(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._templates))

    def __contains__(self, template_id: object) -> bool:
        if not isinstance(template_id, str):
            return False
        with self._lock:
            return template_id in self._templates

    def __len__(self) -> int:
        with self._lock:
            return len(self._templates)

    def prepare(
        self,
        template_id: str,
        params: Mapping[str, Any] | None,
        *,
        trust: TrustClass | str = TrustClass.UNTRUSTED,
        tenant_policy: TenantPolicy,
        snapshot: SnapshotId | str,
        parameter_order: Sequence[str] | None = None,
    ) -> PreparedQuery:
        """Resolve, authorize, validate, and bind a template invocation."""

        # Hard deny any attempt to smuggle SQL through the parameter surface.
        if params is not None and isinstance(params, Mapping):
            for key in params:
                key_l = str(key).casefold()
                if key_l in {"sql", "query", "statement", "raw_sql"}:
                    raise SQLSurfaceDenied("arbitrary_sql")

        template = self.get(template_id)
        if isinstance(trust, str):
            try:
                trust = TrustClass(trust)
            except ValueError as exc:
                raise QueryRegistryError(f"invalid trust class {trust!r}") from exc
        if not template.permits_trust(trust):
            raise QueryRegistryError(
                f"template {template.template_id!r} denies trust class {trust.value}"
            )
        if not isinstance(tenant_policy, TenantPolicy):
            raise QueryRegistryError("tenant_policy must be a TenantPolicy")

        if isinstance(snapshot, SnapshotId):
            snap = snapshot
        else:
            try:
                snap = SnapshotId(value=str(snapshot))
            except ContractError as exc:
                raise QueryRegistryError(str(exc)) from exc

        validated, bind_values, params_digest = bind_parameters(
            template, params, parameter_order=parameter_order
        )
        tenant_policy.enforce_parameters(validated)

        # Untrusted callers are additionally constrained to the untrusted budget
        # envelope even when a trusted operator registered a looser template.
        if trust is TrustClass.UNTRUSTED:
            ub = DEFAULT_UNTRUSTED_QUERY_BUDGET
            if (
                template.budget.max_rows > ub.max_rows
                or template.budget.max_bytes > ub.max_bytes
                or template.budget.max_duration_ms > ub.max_duration_ms
                or template.budget.max_depth > ub.max_depth
            ):
                # Cap by preparing against a tightened budget view on the template
                # identity; execution meter will use the effective budget.
                pass

        return PreparedQuery(
            template=template,
            parameters=MappingProxyType(validated),
            parameters_digest=params_digest,
            bind_values=bind_values,
            trust=trust,
            tenant_policy=tenant_policy,
            snapshot=snap,
        )

    def effective_budget(
        self, template: QueryTemplate, trust: TrustClass
    ) -> QueryBudget:
        """Return the budget enforced for ``template`` under ``trust``."""

        if trust is not TrustClass.UNTRUSTED:
            return template.budget
        ub = DEFAULT_UNTRUSTED_QUERY_BUDGET
        tb = template.budget
        return QueryBudget(
            max_rows=min(tb.max_rows, ub.max_rows),
            max_bytes=min(tb.max_bytes, ub.max_bytes),
            max_duration_ms=min(tb.max_duration_ms, ub.max_duration_ms),
            max_depth=min(tb.max_depth, ub.max_depth),
            max_parameter_bytes=min(
                tb.max_parameter_bytes, ub.max_parameter_bytes
            ),
        )


# ---------------------------------------------------------------------------
# Audit + receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Append-only audit record for one query preparation or execution attempt."""

    SCHEMA: ClassVar[str] = QUERY_AUDIT_SCHEMA

    event_id: str
    template_id: str
    template_version: int
    parameters_digest: str
    snapshot_id: str
    policy_id: str
    trust: str
    status: str
    created_at: str
    resource_usage: ResourceUsage | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        eid = str(self.event_id or "").strip()
        if not eid or not _SAFE_TOKEN.fullmatch(eid):
            # Allow UUID forms.
            if not eid or len(eid) > 128:
                raise QueryRegistryError(f"invalid event_id {self.event_id!r}")
        object.__setattr__(self, "event_id", eid)
        try:
            object.__setattr__(
                self, "created_at", normalize_timestamp(self.created_at)
            )
        except ContractError as exc:
            raise QueryRegistryError(str(exc)) from exc
        object.__setattr__(self, "detail", str(self.detail or "")[:512])

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": QUERY_AUDIT_SCHEMA,
            "event_id": self.event_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "parameters_digest": self.parameters_digest,
            "snapshot_id": self.snapshot_id,
            "policy_id": self.policy_id,
            "trust": self.trust,
            "status": self.status,
            "created_at": self.created_at,
            "detail": self.detail,
        }
        if self.resource_usage is not None:
            payload["resource_usage"] = self.resource_usage.to_dict()
        return payload


class AuditLog:
    """Bounded in-process append-only audit log (testable, non-authoritative)."""

    def __init__(self, *, max_events: int = MAX_AUDIT_EVENTS) -> None:
        if max_events < 1:
            raise QueryRegistryError("max_events must be positive")
        self._max_events = max_events
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def append(self, event: AuditEvent) -> None:
        if not isinstance(event, AuditEvent):
            raise QueryRegistryError("event must be an AuditEvent")
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                # Drop oldest; receipts remain the durable identity.
                overflow = len(self._events) - self._max_events
                del self._events[:overflow]

    def list_events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


@dataclass(frozen=True, slots=True)
class QueryReceipt:
    """Deterministic receipt for one allowlisted query execution.

    Identifies template, parameters digest, snapshot, policy, and resource
    usage so exports, audits, and replays can rebind to exact inputs.
    """

    SCHEMA: ClassVar[str] = QUERY_RECEIPT_SCHEMA

    receipt_id: str
    template_id: str
    template_version: int
    template_identity: str
    parameters_digest: str
    snapshot: SnapshotId
    policy_id: str
    tenant_id: str
    trust: TrustClass
    status: QueryStatus
    resource_usage: ResourceUsage
    budget: QueryBudget
    column_policy_identity: str
    parameter_schema_identity: str
    row_count: int
    truncated: bool
    created_at: str
    audit_event_id: str = ""
    domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        rid = str(self.receipt_id or "").strip()
        if not rid:
            raise QueryRegistryError("receipt_id is required")
        object.__setattr__(self, "receipt_id", rid)

        if not isinstance(self.snapshot, SnapshotId):
            raise QueryRegistryError("snapshot must be a SnapshotId")
        if not isinstance(self.resource_usage, ResourceUsage):
            raise QueryRegistryError("resource_usage must be a ResourceUsage")
        if not isinstance(self.budget, QueryBudget):
            raise QueryRegistryError("budget must be a QueryBudget")
        if not isinstance(self.status, QueryStatus):
            try:
                object.__setattr__(self, "status", QueryStatus(str(self.status)))
            except ValueError as exc:
                raise QueryRegistryError(f"invalid status {self.status!r}") from exc
        if not isinstance(self.trust, TrustClass):
            try:
                object.__setattr__(self, "trust", TrustClass(str(self.trust)))
            except ValueError as exc:
                raise QueryRegistryError(f"invalid trust {self.trust!r}") from exc

        if (
            not isinstance(self.row_count, int)
            or isinstance(self.row_count, bool)
            or self.row_count < 0
        ):
            raise QueryRegistryError("row_count must be a non-negative int")
        if not isinstance(self.truncated, bool):
            raise QueryRegistryError("truncated must be a bool")

        try:
            object.__setattr__(
                self, "created_at", normalize_timestamp(self.created_at)
            )
        except ContractError as exc:
            raise QueryRegistryError(str(exc)) from exc

        if not isinstance(self.domains, tuple):
            object.__setattr__(self, "domains", tuple(self.domains))

    @property
    def identity_id(self) -> str:
        return content_identity(
            {
                "schema": QUERY_RECEIPT_SCHEMA,
                "receipt_id": self.receipt_id,
                "template_id": self.template_id,
                "template_version": self.template_version,
                "template_identity": self.template_identity,
                "parameters_digest": self.parameters_digest,
                "snapshot": self.snapshot.to_dict(),
                "policy_id": self.policy_id,
                "tenant_id": self.tenant_id,
                "trust": self.trust.value,
                "status": self.status.value,
                "resource_usage": self.resource_usage.to_dict(),
                "budget": self.budget.to_dict(),
                "column_policy_identity": self.column_policy_identity,
                "parameter_schema_identity": self.parameter_schema_identity,
                "row_count": self.row_count,
                "truncated": self.truncated,
                "created_at": self.created_at,
                "domains": list(self.domains),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUERY_RECEIPT_SCHEMA,
            "receipt_id": self.receipt_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_identity": self.template_identity,
            "parameters_digest": self.parameters_digest,
            "snapshot": self.snapshot.to_dict(),
            "policy_id": self.policy_id,
            "tenant_id": self.tenant_id,
            "trust": self.trust.value,
            "status": self.status.value,
            "resource_usage": self.resource_usage.to_dict(),
            "budget": self.budget.to_dict(),
            "column_policy_identity": self.column_policy_identity,
            "parameter_schema_identity": self.parameter_schema_identity,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "created_at": self.created_at,
            "audit_event_id": self.audit_event_id,
            "domains": list(self.domains),
            "identity_id": self.identity_id,
        }


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Projected rows plus the deterministic :class:`QueryReceipt`."""

    rows: tuple[Mapping[str, Any], ...]
    receipt: QueryReceipt

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [dict(r) for r in self.rows],
            "receipt": self.receipt.to_dict(),
        }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class _RowSource(Protocol):
    """Minimal protocol for backends that execute prepared SQL."""

    def execute(
        self, sql: str, parameters: Sequence[Any] | None = None
    ) -> Sequence[Mapping[str, Any]]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _estimate_row_bytes(row: Mapping[str, Any]) -> int:
    try:
        return len(canonical_json_bytes(dict(row)))
    except ContractError:
        return len(repr(row).encode("utf-8", errors="replace"))


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class QueryExecutor:
    """Execute prepared allowlisted templates under policy and budgets.

    The executor never accepts raw SQL from callers. It only runs SQL that was
    registered on a :class:`QueryRegistry` and re-scanned at prepare time.
    """

    def __init__(
        self,
        registry: QueryRegistry,
        *,
        backend: _RowSource | None = None,
        audit_log: AuditLog | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(registry, QueryRegistry):
            raise QueryRegistryError("registry must be a QueryRegistry")
        self._registry = registry
        self._backend = backend
        self._audit = audit_log if audit_log is not None else AuditLog()
        self._clock = clock or _utc_now

    @property
    def registry(self) -> QueryRegistry:
        return self._registry

    @property
    def audit_log(self) -> AuditLog:
        return self._audit

    def execute(
        self,
        template_id: str,
        params: Mapping[str, Any] | None,
        *,
        trust: TrustClass | str = TrustClass.UNTRUSTED,
        tenant_policy: TenantPolicy,
        snapshot: SnapshotId | str,
        cancellation: CancellationToken | None = None,
        max_depth: int | None = None,
        row_source: Callable[
            [PreparedQuery, _BudgetMeter, CancellationToken | None],
            Sequence[Mapping[str, Any]],
        ]
        | None = None,
        sql: str | None = None,
    ) -> QueryResult:
        """Prepare and execute an allowlisted template.

        Passing ``sql`` is always denied (arbitrary SQL path).
        """

        deny_arbitrary_sql(sql, template_id=template_id)
        if cancellation is not None:
            cancellation.check()

        try:
            prepared = self._registry.prepare(
                template_id,
                params,
                trust=trust,
                tenant_policy=tenant_policy,
                snapshot=snapshot,
            )
        except QueryRegistryError as exc:
            self._audit_denied(
                template_id=str(template_id or ""),
                template_version=0,
                parameters_digest=content_identity(dict(params or {})),
                snapshot=snapshot,
                tenant_policy=tenant_policy,
                trust=trust,
                detail=str(exc),
            )
            raise

        if cancellation is not None:
            cancellation.check()

        budget = self._registry.effective_budget(prepared.template, prepared.trust)
        param_bytes = parameters_byte_size(prepared.parameters)
        meter = _BudgetMeter(budget, parameter_bytes=param_bytes)
        if max_depth is not None:
            meter.check_depth(max_depth)
        else:
            meter.check_depth(0)

        status = QueryStatus.SUCCEEDED
        truncated = False
        projected_rows: list[Mapping[str, Any]] = []
        detail = ""

        try:
            if row_source is not None:
                raw_rows = row_source(prepared, meter, cancellation)
            elif self._backend is not None:
                # Defense in depth: re-scan template SQL immediately before bind.
                scan_sql_surface(prepared.template.sql)
                if cancellation is not None:
                    cancellation.check()
                raw_rows = self._backend.execute(
                    prepared.template.sql, prepared.bind_values
                )
            else:
                raise QueryRegistryError(
                    "no query backend or row_source configured"
                )

            for row in raw_rows:
                if cancellation is not None and cancellation.is_cancelled:
                    raise QueryCancelled(cancellation.reason or "cancelled")
                meter.check_time()
                if not isinstance(row, Mapping):
                    raise QueryRegistryError("backend rows must be mappings")
                prepared.tenant_policy.enforce_row(row)
                projected = prepared.template.column_policy.project_row(row)
                row_bytes = _estimate_row_bytes(projected)
                if meter.would_exceed_rows():
                    truncated = True
                    status = QueryStatus.TRUNCATED
                    break
                try:
                    meter.record_row(row_bytes)
                except QueryBudgetExceeded:
                    truncated = True
                    status = QueryStatus.TRUNCATED
                    break
                projected_rows.append(MappingProxyType(projected))

        except QueryCancelled as exc:
            status = QueryStatus.CANCELLED
            detail = str(exc)
            usage = meter.snapshot()
            receipt = self._build_receipt(
                prepared=prepared,
                budget=budget,
                usage=usage,
                status=status,
                row_count=len(projected_rows),
                truncated=False,
                detail=detail,
            )
            return QueryResult(rows=tuple(projected_rows), receipt=receipt)
        except QueryBudgetExceeded as exc:
            status = QueryStatus.BUDGET_EXCEEDED
            detail = str(exc)
            usage = meter.snapshot()
            receipt = self._build_receipt(
                prepared=prepared,
                budget=budget,
                usage=usage,
                status=status,
                row_count=len(projected_rows),
                truncated=True,
                detail=detail,
            )
            # Budget exhaustion is fail-closed for depth/time hard failures when
            # no rows could be safely returned under the remaining budget.
            if not projected_rows and exc.kind in {"time", "depth", "parameter_bytes"}:
                raise
            return QueryResult(rows=tuple(projected_rows), receipt=receipt)
        except SQLSurfaceDenied:
            raise
        except QueryRegistryError:
            raise

        usage = meter.snapshot()
        receipt = self._build_receipt(
            prepared=prepared,
            budget=budget,
            usage=usage,
            status=status,
            row_count=len(projected_rows),
            truncated=truncated,
            detail=detail,
        )
        return QueryResult(rows=tuple(projected_rows), receipt=receipt)

    def _audit_denied(
        self,
        *,
        template_id: str,
        template_version: int,
        parameters_digest: str,
        snapshot: SnapshotId | str,
        tenant_policy: TenantPolicy,
        trust: TrustClass | str,
        detail: str,
    ) -> None:
        if isinstance(snapshot, SnapshotId):
            snap_value = snapshot.value
        else:
            snap_value = str(snapshot)
        trust_value = trust.value if isinstance(trust, TrustClass) else str(trust)
        event = AuditEvent(
            event_id=_new_id("audit"),
            template_id=template_id or "unknown",
            template_version=template_version,
            parameters_digest=parameters_digest,
            snapshot_id=snap_value,
            policy_id=tenant_policy.policy_id,
            trust=trust_value,
            status=QueryStatus.DENIED.value,
            created_at=self._clock(),
            detail=detail,
        )
        self._audit.append(event)

    def _build_receipt(
        self,
        *,
        prepared: PreparedQuery,
        budget: QueryBudget,
        usage: ResourceUsage,
        status: QueryStatus,
        row_count: int,
        truncated: bool,
        detail: str = "",
    ) -> QueryReceipt:
        audit_id = _new_id("audit")
        event = AuditEvent(
            event_id=audit_id,
            template_id=prepared.template.template_id,
            template_version=prepared.template.version,
            parameters_digest=prepared.parameters_digest,
            snapshot_id=prepared.snapshot.value,
            policy_id=prepared.tenant_policy.policy_id,
            trust=prepared.trust.value,
            status=status.value,
            created_at=self._clock(),
            resource_usage=usage,
            detail=detail,
        )
        self._audit.append(event)

        return QueryReceipt(
            receipt_id=_new_id("receipt"),
            template_id=prepared.template.template_id,
            template_version=prepared.template.version,
            template_identity=prepared.template.identity_id,
            parameters_digest=prepared.parameters_digest,
            snapshot=prepared.snapshot,
            policy_id=prepared.tenant_policy.policy_id,
            tenant_id=prepared.tenant_policy.tenant_id,
            trust=prepared.trust,
            status=status,
            resource_usage=usage,
            budget=budget,
            column_policy_identity=prepared.template.column_policy.identity_id,
            parameter_schema_identity=prepared.template.parameter_schema.identity_id,
            row_count=row_count,
            truncated=truncated,
            created_at=self._clock(),
            audit_event_id=audit_id,
            domains=prepared.template.domains,
        )


# ---------------------------------------------------------------------------
# Built-in publication-safe templates
# ---------------------------------------------------------------------------


def default_builtin_templates() -> tuple[QueryTemplate, ...]:
    """Return a small closed set of control/publication-safe templates.

    These templates are intentionally simple SELECT forms over named views that
    publication databases are expected to expose. They exist so the registry is
    non-empty for untrusted surfaces without ever accepting arbitrary SQL.
    """

    tenant_param = ParameterSpec(
        name="tenant_id",
        param_type=ParameterType.TENANT_ID,
        required=True,
        description="Tenant isolation key",
    )
    limit_param = ParameterSpec(
        name="row_limit",
        param_type=ParameterType.INTEGER,
        required=False,
        default=100,
        description="Caller-requested row cap (still bounded by budget)",
    )

    publication_columns = ColumnPolicy(
        {
            "tenant_id": ColumnClassification.PUBLIC,
            "record_id": ColumnClassification.PUBLIC,
            "status": ColumnClassification.PUBLIC,
            "updated_at": ColumnClassification.PUBLIC,
        }
    )
    health_columns = ColumnPolicy(
        {
            "component": ColumnClassification.PUBLIC,
            "status": ColumnClassification.PUBLIC,
            "checked_at": ColumnClassification.PUBLIC,
        }
    )

    templates = (
        QueryTemplate(
            template_id="publication.list_records",
            version=1,
            sql=(
                "SELECT tenant_id, record_id, status, updated_at "
                "FROM publication_records "
                "WHERE tenant_id = ? "
                "ORDER BY updated_at DESC "
                "LIMIT ?"
            ),
            parameter_schema=ParameterSchema(
                schema_version=1,
                parameters=(tenant_param, limit_param),
            ),
            column_policy=publication_columns,
            budget=DEFAULT_UNTRUSTED_QUERY_BUDGET,
            allowed_trust=frozenset(
                {TrustClass.TRUSTED, TrustClass.UNTRUSTED}
            ),
            description="List sanitized publication records for one tenant",
            domains=("publication",),
        ),
        QueryTemplate(
            template_id="publication.health_probe",
            version=1,
            sql=(
                "SELECT component, status, checked_at "
                "FROM publication_health "
                "WHERE component = ?"
            ),
            parameter_schema=ParameterSchema(
                schema_version=1,
                parameters=(
                    ParameterSpec(
                        name="component",
                        param_type=ParameterType.IDENTIFIER,
                        required=True,
                        description="Health component identifier",
                    ),
                ),
            ),
            column_policy=health_columns,
            budget=DEFAULT_UNTRUSTED_QUERY_BUDGET,
            allowed_trust=frozenset(
                {TrustClass.TRUSTED, TrustClass.UNTRUSTED}
            ),
            description="Read a single publication health probe row",
            domains=("publication",),
        ),
        QueryTemplate(
            template_id="control.task_status",
            version=1,
            sql=(
                "SELECT tenant_id, task_id, status, updated_at "
                "FROM control_tasks "
                "WHERE tenant_id = ? AND task_id = ?"
            ),
            parameter_schema=ParameterSchema(
                schema_version=1,
                parameters=(
                    tenant_param,
                    ParameterSpec(
                        name="task_id",
                        param_type=ParameterType.STRING,
                        required=True,
                        max_length=256,
                        description="Control-plane task identifier",
                    ),
                ),
            ),
            column_policy=ColumnPolicy(
                {
                    "tenant_id": ColumnClassification.PUBLIC,
                    "task_id": ColumnClassification.PUBLIC,
                    "status": ColumnClassification.PUBLIC,
                    "updated_at": ColumnClassification.PUBLIC,
                }
            ),
            budget=DEFAULT_QUERY_BUDGET,
            allowed_trust=frozenset({TrustClass.TRUSTED}),
            description="Trusted control-plane task status lookup",
            domains=("control",),
        ),
    )
    return templates


def open_default_registry(
    *, include_builtins: bool = True
) -> QueryRegistry:
    """Create a registry optionally seeded with builtin templates."""

    registry = QueryRegistry()
    if include_builtins:
        for template in default_builtin_templates():
            registry.register(template)
    return registry
