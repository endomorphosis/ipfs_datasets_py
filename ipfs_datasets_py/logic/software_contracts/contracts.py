"""Software-contract IR for a deliberately bounded proof model (DSCON-G200).

This module owns the versioned intermediate representation for callable, data,
effect, exception, capability, resource, temporal, determinism, schema, trust-
boundary, provenance, and authority records.  Only constructs that can be
validated and lowered soundly into reviewed theories or finite bounds are
admitted.

Key soundness rules:

* every fact carries explicit :class:`ContractProvenance` (source authority and
  fact kind: declared / extracted / witnessed / inferred);
* unbounded executable predicates (``eval``, free-form code, open quantifiers)
  are rejected at construction time;
* canonical values must be strict DAG-JSON scalars (no floats, no host objects);
* lower-authority facts cannot silently override higher-authority facts —
  contradictions surface as :class:`ContractFinding` records via the registry.

Content identity uses the software-contract CID profile from :mod:`.content`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, ClassVar, Final, Mapping, TypeVar

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)


# ---------------------------------------------------------------------------
# Schema / goal identity
# ---------------------------------------------------------------------------

GOAL_ID: Final[str] = "DSCON-G200"
TASK_ID: Final[str] = "DSCON-014"
SCHEMA_NAME: Final[str] = "ipfs-datasets.software-contracts.software-contract"
SCHEMA_MAJOR: Final[int] = 1
SCHEMA_MINOR: Final[int] = 0
SCHEMA_PATCH: Final[int] = 0
SCHEMA_VERSION: Final[str] = f"{SCHEMA_MAJOR}.{SCHEMA_MINOR}.{SCHEMA_PATCH}"
SCHEMA_IDENTIFIER: Final[str] = f"{SCHEMA_NAME}@{SCHEMA_VERSION}"
SOFTWARE_CONTRACT_SCHEMA: Final[str] = SCHEMA_IDENTIFIER
CONTRACT_DESCRIPTOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.software-contract-descriptor@1"
)

MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1

_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,511}$"
)
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
)

# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------

FACT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "declared",  # reviewed manifests / schemas (highest structural source)
        "extracted",  # Protocol / ABC / stub / annotation / decorator parse
        "witnessed",  # tests / traces (witnesses, not universal claims)
        "inferred",  # conservative inference (never self-promotes to authority)
    }
)

# Descending authority rank (matches SOUNDNESS_AND_THREAT_MODEL contract_authority).
AUTHORITY_RANKS: Final[tuple[str, ...]] = (
    "reviewed_registry",
    "public_schema",
    "documented_api",
    "type_declaration",
    "inference",
)
AUTHORITY_RANK_ORDER: Final[Mapping[str, int]] = {
    name: index for index, name in enumerate(AUTHORITY_RANKS)
}

# Bounded, lowerable predicate operators.  Executable / open forms are absent.
PREDICATE_OPERATORS: Final[frozenset[str]] = frozenset(
    {
        "type_is",
        "type_ref",
        "equals",
        "not_equals",
        "in_set",
        "range_int",
        "length_range",
        "is_null",
        "is_not_null",
        "schema_ref",
        "has_field",
        "capability_requires",
        "effect_permits",
        "effect_forbids",
        "resource_bound",
        "raises",
        "temporal_before",
        "temporal_after",
        "state_transition",
        "trust_label",
        "determinism_class",
        "idempotent",
        "pure",
    }
)

# Operators that must never appear (defense in depth if a caller invents one).
REJECTED_PREDICATE_OPERATORS: Final[frozenset[str]] = frozenset(
    {
        "eval",
        "exec",
        "python_eval",
        "python_exec",
        "javascript_eval",
        "free_form",
        "arbitrary_code",
        "unbounded_quantifier",
        "forall_unbounded",
        "exists_unbounded",
        "lambda",
        "callable",
        "expression",
        "ast_eval",
        "regex_unbounded",
    }
)

PREDICATE_ROLES: Final[frozenset[str]] = frozenset(
    {
        "precondition",
        "postcondition",
        "invariant",
        "assumption",
        "effect",
        "exception",
        "capability",
        "resource",
        "temporal",
        "determinism",
        "schema",
        "trust_boundary",
        "data",
    }
)

EFFECT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "filesystem",
        "subprocess",
        "network",
        "environment",
        "import",
        "database",
        "cache",
        "logging",
        "secret",
        "global_state",
        "object_state",
        "io",
        "exception",
        "await",
        "context_manager",
        "unknown",
    }
)

EFFECT_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "read",
        "write",
        "create",
        "delete",
        "mutate",
        "invoke",
        "open",
        "close",
        "raise",
        "await",
        "enter",
        "exit",
        "unknown",
    }
)

RESOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "bytes",
        "rows",
        "pages",
        "recursion",
        "retries",
        "timeout_ms",
        "processes",
        "concurrency",
        "file_handles",
        "memory_bytes",
        "cpu_ms",
    }
)

DETERMINISM_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "pure",
        "deterministic",
        "idempotent",
        "nondeterministic",
        "unknown",
    }
)

TRUST_LABELS: Final[frozenset[str]] = frozenset(
    {
        "public",
        "internal",
        "authenticated",
        "secret",
        "credential",
        "pii",
        "untrusted",
        "trusted",
    }
)

VISIBILITY_KINDS: Final[frozenset[str]] = frozenset(
    {"public", "protected", "private", "internal", "unspecified"}
)

CALLABLE_SHAPES: Final[frozenset[str]] = frozenset(
    {
        "sync_function",
        "async_function",
        "sync_generator",
        "async_generator",
        "method",
        "async_method",
        "constructor",
        "property",
        "unknown",
    }
)

EXCEPTION_HANDLING: Final[frozenset[str]] = frozenset(
    {
        "raises",
        "propagates",
        "swallows",
        "converts",
        "unknown",
    }
)

FINDING_KINDS: Final[frozenset[str]] = frozenset(
    {
        "contradiction",
        "authority_override",
        "missing_authority",
        "unbound_revision",
        "unsupported_construct",
        "ambiguous_value",
    }
)

FINDING_SEVERITIES: Final[frozenset[str]] = frozenset(
    {"info", "warning", "error", "fatal"}
)

PARAMETER_KINDS: Final[frozenset[str]] = frozenset(
    {
        "positional_only",
        "positional_or_named",
        "named_only",
        "variadic_positional",
        "variadic_named",
        "receiver",
        "unknown",
    }
)


class ContractIRError(ValueError):
    """Raised when a software-contract IR record is malformed or unsound."""


# ---------------------------------------------------------------------------
# Validation helpers (strict DAG-JSON / closed vocabularies)
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
    no_whitespace: bool = False,
    maximum: int = 16_384,
) -> str:
    if type(value) is not str:
        raise ContractIRError(f"{field_name} must be an exact string")
    if not allow_empty and not value:
        raise ContractIRError(f"{field_name} must not be empty")
    if value and value != value.strip():
        raise ContractIRError(
            f"{field_name} must not contain surrounding whitespace"
        )
    if len(value) > maximum:
        raise ContractIRError(f"{field_name} exceeds {maximum} characters")
    if unicodedata.normalize("NFC", value) != value:
        raise ContractIRError(f"{field_name} must be NFC-normalized")
    if any(not character.isprintable() for character in value):
        raise ContractIRError(f"{field_name} contains a control character")
    if no_whitespace and any(character.isspace() for character in value):
        raise ContractIRError(f"{field_name} must not contain whitespace")
    return value


def _identifier(value: Any, field_name: str) -> str:
    result = _text(value, field_name, no_whitespace=True, maximum=512)
    if not _ID_RE.fullmatch(result):
        raise ContractIRError(f"{field_name} is not a normalized record ID")
    return result


def _optional_identifier(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field_name)


def _integer(
    value: Any,
    field_name: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_SAFE_INTEGER,
) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise ContractIRError(f"{field_name} must be an exact integer")
    if not minimum <= value <= maximum:
        raise ContractIRError(
            f"{field_name} must be an integer in {minimum}..{maximum}"
        )
    return value


def _boolean(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise ContractIRError(f"{field_name} must be an exact bool")
    return value


def _choice(value: Any, field_name: str, allowed: frozenset[str]) -> str:
    result = _text(value, field_name, no_whitespace=True, maximum=128)
    if result not in allowed:
        raise ContractIRError(
            f"{field_name} must be one of {sorted(allowed)}, got {result!r}"
        )
    return result


def _token(value: Any, field_name: str) -> str:
    result = _text(value, field_name, no_whitespace=True, maximum=256)
    if not _TOKEN_RE.fullmatch(result):
        raise ContractIRError(f"{field_name} is not a lowercase token")
    return result


def _optional_cid(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        return validate_cid(value)
    except (TypeError, ValueError) as exc:
        raise ContractIRError(f"{field_name} is not a valid profile CID") from exc


T = TypeVar("T")


def _records(
    value: Any,
    expected_type: type[T],
    field_name: str,
    *,
    sort_key: Any | None = None,
) -> tuple[T, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping, set, frozenset)):
        raise ContractIRError(f"{field_name} must be an ordered sequence")
    try:
        result = tuple(value)
    except TypeError as exc:
        raise ContractIRError(
            f"{field_name} must be an ordered sequence"
        ) from exc
    if not all(isinstance(item, expected_type) for item in result):
        raise ContractIRError(
            f"{field_name} may contain only {expected_type.__name__} records"
        )
    return tuple(sorted(result, key=sort_key)) if sort_key else result


def _strings(
    value: Any,
    field_name: str,
    *,
    sorted_set: bool = False,
    identifiers: bool = False,
    maximum_item: int = 512,
    allow_duplicates: bool = False,
    allow_internal_whitespace: bool = False,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping, set, frozenset)):
        raise ContractIRError(f"{field_name} must be an ordered sequence")
    try:
        raw = tuple(value)
    except TypeError as exc:
        raise ContractIRError(
            f"{field_name} must be an ordered sequence"
        ) from exc
    result: list[str] = []
    for index, item in enumerate(raw):
        name = f"{field_name}[{index}]"
        if identifiers:
            normalized = _identifier(item, name)
        else:
            normalized = _text(
                item,
                name,
                no_whitespace=not allow_internal_whitespace,
                maximum=maximum_item,
            )
        result.append(normalized)
    if not allow_duplicates and len(set(result)) != len(result):
        raise ContractIRError(f"{field_name} must not contain duplicates")
    return tuple(sorted(result)) if sorted_set else tuple(result)


def _closed_mapping(
    value: Any,
    expected: frozenset[str],
    record_name: str,
) -> dict[str, Any]:
    try:
        validate_structured_value(value)
    except (TypeError, ValueError) as exc:
        raise ContractIRError(
            f"{record_name} must be a strict canonical mapping"
        ) from exc
    if type(value) is not dict:
        raise ContractIRError(f"{record_name} must be an exact mapping")
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise ContractIRError(
            f"{record_name} fields are closed (missing={missing}, extra={extra})"
        )
    return value


def _canonical_scalar(value: Any, field_name: str) -> Any:
    """Accept only null / bool / int / str (no float, bytes, host objects)."""

    if value is None:
        return None
    value_type = type(value)
    if value_type is bool or value_type is str:
        if value_type is str:
            return _text(value, field_name, allow_empty=True, maximum=4096)
        return value
    if value_type is int and not isinstance(value, bool):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise ContractIRError(
                f"{field_name} integer is outside the safe integer range"
            )
        return value
    if value_type is float:
        raise ContractIRError(
            f"{field_name} rejects float; use int or a reviewed string"
        )
    if value_type is list:
        return [
            _canonical_scalar(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ContractIRError(
        f"{field_name} must be a canonical scalar or scalar list, "
        f"got {value_type.__name__}"
    )


# ---------------------------------------------------------------------------
# Canonical record base
# ---------------------------------------------------------------------------


class CanonicalContractRecord:
    """Common content-identity surface for all contract IR records."""

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - abstract contract
        raise NotImplementedError

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes.decode("utf-8")

    def verify_cid(self, claimed_cid: str) -> str:
        return decode_and_recompute_structured(claimed_cid, self.to_dict())


# ---------------------------------------------------------------------------
# Core IR records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContractAuthority(CanonicalContractRecord):
    """Who/what authorizes a contract fact (rank + revision binding)."""

    authority_id: str
    rank: str
    owner: str
    revision: str
    policy_ref: str | None = None
    source_cid: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "authority_id",
            "rank",
            "owner",
            "revision",
            "policy_ref",
            "source_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "authority_id", _identifier(self.authority_id, "authority_id")
        )
        object.__setattr__(
            self, "rank", _choice(self.rank, "rank", frozenset(AUTHORITY_RANKS))
        )
        object.__setattr__(
            self,
            "owner",
            _text(self.owner, "owner", no_whitespace=True, maximum=512),
        )
        object.__setattr__(
            self,
            "revision",
            _text(self.revision, "revision", no_whitespace=True, maximum=512),
        )
        if self.policy_ref is not None:
            object.__setattr__(
                self,
                "policy_ref",
                _text(
                    self.policy_ref,
                    "policy_ref",
                    no_whitespace=True,
                    maximum=1024,
                ),
            )
        object.__setattr__(
            self, "source_cid", _optional_cid(self.source_cid, "source_cid")
        )

    @property
    def rank_order(self) -> int:
        return AUTHORITY_RANK_ORDER[self.rank]

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "rank": self.rank,
            "owner": self.owner,
            "revision": self.revision,
            "policy_ref": self.policy_ref,
            "source_cid": self.source_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractAuthority":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(**data)


@dataclass(frozen=True, slots=True)
class ContractProvenance(CanonicalContractRecord):
    """Provenance for one declared, extracted, witnessed, or inferred fact."""

    fact_kind: str
    authority: ContractAuthority
    source_path: str
    source_symbol: str | None = None
    note: str = ""

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "fact_kind",
            "authority",
            "source_path",
            "source_symbol",
            "note",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fact_kind", _choice(self.fact_kind, "fact_kind", FACT_KINDS)
        )
        if not isinstance(self.authority, ContractAuthority):
            raise ContractIRError("authority must be a ContractAuthority")
        # Inferred facts may only cite inference-rank authority.
        if self.fact_kind == "inferred" and self.authority.rank != "inference":
            raise ContractIRError(
                "inferred facts must use inference-rank authority "
                "(cannot self-promote to reviewed contract authority)"
            )
        # Declared / reviewed facts may not claim inference rank.
        if (
            self.fact_kind == "declared"
            and self.authority.rank == "inference"
        ):
            raise ContractIRError(
                "declared facts cannot use inference-rank authority"
            )
        object.__setattr__(
            self,
            "source_path",
            _text(
                self.source_path,
                "source_path",
                no_whitespace=True,
                maximum=4096,
            ),
        )
        if self.source_symbol is not None:
            object.__setattr__(
                self,
                "source_symbol",
                _text(
                    self.source_symbol,
                    "source_symbol",
                    no_whitespace=True,
                    maximum=2048,
                ),
            )
        object.__setattr__(
            self,
            "note",
            _text(self.note, "note", allow_empty=True, maximum=4096),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_kind": self.fact_kind,
            "authority": self.authority.to_dict(),
            "source_path": self.source_path,
            "source_symbol": self.source_symbol,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractProvenance":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            fact_kind=data["fact_kind"],
            authority=ContractAuthority.from_dict(data["authority"]),
            source_path=data["source_path"],
            source_symbol=data["source_symbol"],
            note=data["note"],
        )


@dataclass(frozen=True, slots=True)
class Assumption(CanonicalContractRecord):
    """An explicit named assumption bound into a proof model."""

    assumption_id: str
    statement: str
    provenance: ContractProvenance
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"assumption_id", "statement", "provenance", "required"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assumption_id", _identifier(self.assumption_id, "assumption_id")
        )
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "statement", maximum=8192),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        object.__setattr__(
            self, "required", _boolean(self.required, "required")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "statement": self.statement,
            "provenance": self.provenance.to_dict(),
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Assumption":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            assumption_id=data["assumption_id"],
            statement=data["statement"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            required=data["required"],
        )


@dataclass(frozen=True, slots=True)
class BoundedPredicate(CanonicalContractRecord):
    """One sound, lowerable predicate (no executable / unbounded forms)."""

    predicate_id: str
    role: str
    operator: str
    subject: str
    provenance: ContractProvenance
    arguments: tuple[Any, ...] = ()
    description: str = ""

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "predicate_id",
            "role",
            "operator",
            "subject",
            "provenance",
            "arguments",
            "description",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "predicate_id", _identifier(self.predicate_id, "predicate_id")
        )
        object.__setattr__(self, "role", _choice(self.role, "role", PREDICATE_ROLES))
        operator = _text(self.operator, "operator", no_whitespace=True, maximum=128)
        if operator in REJECTED_PREDICATE_OPERATORS:
            raise ContractIRError(
                f"operator {operator!r} is unbounded/executable and rejected"
            )
        if operator not in PREDICATE_OPERATORS:
            raise ContractIRError(
                f"operator {operator!r} is not a reviewed lowerable operator "
                f"(allowed={sorted(PREDICATE_OPERATORS)})"
            )
        object.__setattr__(self, "operator", operator)
        object.__setattr__(
            self,
            "subject",
            _text(self.subject, "subject", no_whitespace=True, maximum=2048),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        if isinstance(self.arguments, (str, bytes, bytearray, Mapping, set, frozenset)):
            raise ContractIRError("arguments must be an ordered sequence")
        try:
            raw_args = tuple(self.arguments)
        except TypeError as exc:
            raise ContractIRError("arguments must be an ordered sequence") from exc
        normalized_args = tuple(
            _canonical_scalar(item, f"arguments[{index}]")
            for index, item in enumerate(raw_args)
        )
        object.__setattr__(self, "arguments", normalized_args)
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description", allow_empty=True, maximum=4096),
        )
        self._validate_operator_arity()

    def _validate_operator_arity(self) -> None:
        """Reject ambiguous or incomplete argument shapes for each operator."""

        op = self.operator
        args = self.arguments
        nullary = {"is_null", "is_not_null", "pure", "idempotent"}
        if op in nullary and args:
            raise ContractIRError(f"{op} takes no arguments")
        if op in {"type_is", "type_ref", "schema_ref", "has_field", "trust_label", "raises"}:
            if len(args) != 1 or type(args[0]) is not str or not args[0]:
                raise ContractIRError(f"{op} requires exactly one non-empty string")
        if op in {"equals", "not_equals"}:
            if len(args) != 1:
                raise ContractIRError(f"{op} requires exactly one canonical value")
        if op == "in_set":
            if len(args) < 1:
                raise ContractIRError("in_set requires at least one value")
        if op in {"range_int", "length_range", "resource_bound"}:
            if len(args) != 2:
                raise ContractIRError(f"{op} requires [minimum, maximum] integers")
            if type(args[0]) is not int or type(args[1]) is not int:
                raise ContractIRError(f"{op} bounds must be exact integers")
            if args[0] > args[1]:
                raise ContractIRError(f"{op} minimum exceeds maximum")
        if op in {"capability_requires", "effect_permits", "effect_forbids"}:
            if len(args) < 1 or not all(type(a) is str and a for a in args):
                raise ContractIRError(f"{op} requires non-empty string arguments")
        if op in {"temporal_before", "temporal_after"}:
            if len(args) != 1 or type(args[0]) is not str or not args[0]:
                raise ContractIRError(f"{op} requires one event identifier string")
        if op == "state_transition":
            if len(args) != 2 or not all(type(a) is str and a for a in args):
                raise ContractIRError(
                    "state_transition requires [from_state, to_state] strings"
                )
        if op == "determinism_class":
            if (
                len(args) != 1
                or type(args[0]) is not str
                or args[0] not in DETERMINISM_CLASSES
            ):
                raise ContractIRError(
                    "determinism_class requires one reviewed class token"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicate_id": self.predicate_id,
            "role": self.role,
            "operator": self.operator,
            "subject": self.subject,
            "provenance": self.provenance.to_dict(),
            "arguments": list(self.arguments),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundedPredicate":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            predicate_id=data["predicate_id"],
            role=data["role"],
            operator=data["operator"],
            subject=data["subject"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            arguments=data["arguments"],
            description=data["description"],
        )


@dataclass(frozen=True, slots=True)
class EffectContract(CanonicalContractRecord):
    """Declared side-effect permission or obligation for a callable/scope."""

    effect_id: str
    kind: str
    operation: str
    provenance: ContractProvenance
    subject: str = ""
    permitted: bool = True
    required: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "effect_id",
            "kind",
            "operation",
            "provenance",
            "subject",
            "permitted",
            "required",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "effect_id", _identifier(self.effect_id, "effect_id")
        )
        object.__setattr__(self, "kind", _choice(self.kind, "kind", EFFECT_KINDS))
        object.__setattr__(
            self,
            "operation",
            _choice(self.operation, "operation", EFFECT_OPERATIONS),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        object.__setattr__(
            self,
            "subject",
            _text(self.subject, "subject", allow_empty=True, maximum=2048),
        )
        object.__setattr__(
            self, "permitted", _boolean(self.permitted, "permitted")
        )
        object.__setattr__(
            self, "required", _boolean(self.required, "required")
        )
        if self.required and not self.permitted:
            raise ContractIRError(
                "required effects must also be permitted"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "kind": self.kind,
            "operation": self.operation,
            "provenance": self.provenance.to_dict(),
            "subject": self.subject,
            "permitted": self.permitted,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EffectContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            effect_id=data["effect_id"],
            kind=data["kind"],
            operation=data["operation"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            subject=data["subject"],
            permitted=data["permitted"],
            required=data["required"],
        )


@dataclass(frozen=True, slots=True)
class ResourceContract(CanonicalContractRecord):
    """Finite resource bound (bytes, rows, retries, timeout, concurrency, ...)."""

    resource_id: str
    kind: str
    minimum: int
    maximum: int
    provenance: ContractProvenance
    unit: str = ""

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "resource_id",
            "kind",
            "minimum",
            "maximum",
            "provenance",
            "unit",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_id", _identifier(self.resource_id, "resource_id")
        )
        object.__setattr__(
            self, "kind", _choice(self.kind, "kind", RESOURCE_KINDS)
        )
        object.__setattr__(
            self, "minimum", _integer(self.minimum, "minimum", minimum=0)
        )
        object.__setattr__(
            self, "maximum", _integer(self.maximum, "maximum", minimum=0)
        )
        if self.minimum > self.maximum:
            raise ContractIRError("resource minimum exceeds maximum")
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        object.__setattr__(
            self,
            "unit",
            _text(self.unit, "unit", allow_empty=True, maximum=64),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "kind": self.kind,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "provenance": self.provenance.to_dict(),
            "unit": self.unit,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResourceContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            resource_id=data["resource_id"],
            kind=data["kind"],
            minimum=data["minimum"],
            maximum=data["maximum"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            unit=data["unit"],
        )


@dataclass(frozen=True, slots=True)
class ExceptionContract(CanonicalContractRecord):
    """Declared raised, propagated, swallowed, or converted exception."""

    exception_id: str
    exception_type: str
    handling: str
    provenance: ContractProvenance
    condition: str = ""

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "exception_id",
            "exception_type",
            "handling",
            "provenance",
            "condition",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "exception_id",
            _identifier(self.exception_id, "exception_id"),
        )
        object.__setattr__(
            self,
            "exception_type",
            _text(
                self.exception_type,
                "exception_type",
                no_whitespace=True,
                maximum=1024,
            ),
        )
        object.__setattr__(
            self,
            "handling",
            _choice(self.handling, "handling", EXCEPTION_HANDLING),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        object.__setattr__(
            self,
            "condition",
            _text(self.condition, "condition", allow_empty=True, maximum=2048),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_id": self.exception_id,
            "exception_type": self.exception_type,
            "handling": self.handling,
            "provenance": self.provenance.to_dict(),
            "condition": self.condition,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExceptionContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            exception_id=data["exception_id"],
            exception_type=data["exception_type"],
            handling=data["handling"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            condition=data["condition"],
        )


@dataclass(frozen=True, slots=True)
class CapabilityContract(CanonicalContractRecord):
    """Required or optional capability token for a callable."""

    capability_id: str
    capability: str
    required: bool
    provenance: ContractProvenance
    optional_dependency: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "capability_id",
            "capability",
            "required",
            "provenance",
            "optional_dependency",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_id",
            _identifier(self.capability_id, "capability_id"),
        )
        object.__setattr__(
            self, "capability", _token(self.capability, "capability")
        )
        object.__setattr__(
            self, "required", _boolean(self.required, "required")
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        if self.optional_dependency is not None:
            object.__setattr__(
                self,
                "optional_dependency",
                _text(
                    self.optional_dependency,
                    "optional_dependency",
                    no_whitespace=True,
                    maximum=512,
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "capability": self.capability,
            "required": self.required,
            "provenance": self.provenance.to_dict(),
            "optional_dependency": self.optional_dependency,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            capability_id=data["capability_id"],
            capability=data["capability"],
            required=data["required"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            optional_dependency=data["optional_dependency"],
        )


@dataclass(frozen=True, slots=True)
class TemporalConstraint(CanonicalContractRecord):
    """Finite temporal ordering constraint between named events."""

    temporal_id: str
    earlier_event: str
    later_event: str
    provenance: ContractProvenance
    strict: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "temporal_id",
            "earlier_event",
            "later_event",
            "provenance",
            "strict",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "temporal_id", _identifier(self.temporal_id, "temporal_id")
        )
        for name in ("earlier_event", "later_event"):
            object.__setattr__(
                self,
                name,
                _text(
                    getattr(self, name),
                    name,
                    no_whitespace=True,
                    maximum=512,
                ),
            )
        if self.earlier_event == self.later_event:
            raise ContractIRError(
                "temporal constraint events must be distinct"
            )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        object.__setattr__(self, "strict", _boolean(self.strict, "strict"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "temporal_id": self.temporal_id,
            "earlier_event": self.earlier_event,
            "later_event": self.later_event,
            "provenance": self.provenance.to_dict(),
            "strict": self.strict,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TemporalConstraint":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            temporal_id=data["temporal_id"],
            earlier_event=data["earlier_event"],
            later_event=data["later_event"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            strict=data["strict"],
        )


@dataclass(frozen=True, slots=True)
class DeterminismContract(CanonicalContractRecord):
    """Determinism / purity / idempotency class for a callable."""

    determinism_id: str
    classification: str
    provenance: ContractProvenance

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"determinism_id", "classification", "provenance"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "determinism_id",
            _identifier(self.determinism_id, "determinism_id"),
        )
        object.__setattr__(
            self,
            "classification",
            _choice(self.classification, "classification", DETERMINISM_CLASSES),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")

    def to_dict(self) -> dict[str, Any]:
        return {
            "determinism_id": self.determinism_id,
            "classification": self.classification,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeterminismContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            determinism_id=data["determinism_id"],
            classification=data["classification"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
        )


@dataclass(frozen=True, slots=True)
class SchemaContract(CanonicalContractRecord):
    """Binding of a callable parameter/return to a versioned schema identity."""

    schema_contract_id: str
    schema_identifier: str
    target: str
    provenance: ContractProvenance
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_contract_id",
            "schema_identifier",
            "target",
            "provenance",
            "required",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_contract_id",
            _identifier(self.schema_contract_id, "schema_contract_id"),
        )
        object.__setattr__(
            self,
            "schema_identifier",
            _text(
                self.schema_identifier,
                "schema_identifier",
                no_whitespace=True,
                maximum=512,
            ),
        )
        if "@" not in self.schema_identifier:
            raise ContractIRError(
                "schema_identifier must be a versioned name@version form"
            )
        object.__setattr__(
            self,
            "target",
            _text(self.target, "target", no_whitespace=True, maximum=512),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        object.__setattr__(
            self, "required", _boolean(self.required, "required")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_contract_id": self.schema_contract_id,
            "schema_identifier": self.schema_identifier,
            "target": self.target,
            "provenance": self.provenance.to_dict(),
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SchemaContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            schema_contract_id=data["schema_contract_id"],
            schema_identifier=data["schema_identifier"],
            target=data["target"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            required=data["required"],
        )


@dataclass(frozen=True, slots=True)
class TrustBoundaryContract(CanonicalContractRecord):
    """Data-classification / trust-boundary label for a value flow site."""

    boundary_id: str
    label: str
    site: str
    provenance: ContractProvenance
    direction: str = "both"

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "boundary_id",
            "label",
            "site",
            "provenance",
            "direction",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "boundary_id", _identifier(self.boundary_id, "boundary_id")
        )
        object.__setattr__(
            self, "label", _choice(self.label, "label", TRUST_LABELS)
        )
        object.__setattr__(
            self,
            "site",
            _text(self.site, "site", no_whitespace=True, maximum=1024),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        object.__setattr__(
            self,
            "direction",
            _choice(
                self.direction,
                "direction",
                frozenset({"in", "out", "both"}),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary_id": self.boundary_id,
            "label": self.label,
            "site": self.site,
            "provenance": self.provenance.to_dict(),
            "direction": self.direction,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrustBoundaryContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            boundary_id=data["boundary_id"],
            label=data["label"],
            site=data["site"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            direction=data["direction"],
        )


@dataclass(frozen=True, slots=True)
class DataContract(CanonicalContractRecord):
    """Contract for a data field / parameter / return payload shape."""

    data_id: str
    name: str
    type_name: str
    provenance: ContractProvenance
    nullable: bool = False
    predicates: tuple[BoundedPredicate, ...] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "data_id",
            "name",
            "type_name",
            "provenance",
            "nullable",
            "predicates",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_id", _identifier(self.data_id, "data_id"))
        object.__setattr__(
            self, "name", _text(self.name, "name", no_whitespace=True, maximum=512)
        )
        object.__setattr__(
            self,
            "type_name",
            _text(self.type_name, "type_name", no_whitespace=True, maximum=1024),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        object.__setattr__(
            self, "nullable", _boolean(self.nullable, "nullable")
        )
        predicates = _records(
            self.predicates,
            BoundedPredicate,
            "predicates",
            sort_key=lambda item: item.predicate_id,
        )
        for predicate in predicates:
            if predicate.role not in {"data", "precondition", "postcondition", "invariant"}:
                raise ContractIRError(
                    "data contract predicates must use data/pre/post/invariant roles"
                )
        object.__setattr__(self, "predicates", predicates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_id": self.data_id,
            "name": self.name,
            "type_name": self.type_name,
            "provenance": self.provenance.to_dict(),
            "nullable": self.nullable,
            "predicates": [item.to_dict() for item in self.predicates],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DataContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            data_id=data["data_id"],
            name=data["name"],
            type_name=data["type_name"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            nullable=data["nullable"],
            predicates=[
                BoundedPredicate.from_dict(item) for item in data["predicates"]
            ],
        )


@dataclass(frozen=True, slots=True)
class ParameterContract(CanonicalContractRecord):
    """One callable parameter with kind, position, and optional data contract."""

    name: str
    kind: str
    position: int
    data: DataContract | None = None
    default_present: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"name", "kind", "position", "data", "default_present"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "name", _text(self.name, "name", no_whitespace=True, maximum=512)
        )
        object.__setattr__(
            self, "kind", _choice(self.kind, "kind", PARAMETER_KINDS)
        )
        object.__setattr__(
            self, "position", _integer(self.position, "position", minimum=0)
        )
        if self.data is not None and not isinstance(self.data, DataContract):
            raise ContractIRError("data must be a DataContract or null")
        object.__setattr__(
            self,
            "default_present",
            _boolean(self.default_present, "default_present"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "position": self.position,
            "data": None if self.data is None else self.data.to_dict(),
            "default_present": self.default_present,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParameterContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            name=data["name"],
            kind=data["kind"],
            position=data["position"],
            data=(
                None
                if data["data"] is None
                else DataContract.from_dict(data["data"])
            ),
            default_present=data["default_present"],
        )


@dataclass(frozen=True, slots=True)
class ContractFinding(CanonicalContractRecord):
    """Explicit finding for contradictions or authority violations."""

    finding_id: str
    kind: str
    severity: str
    message: str
    subject: str
    left_contract_id: str | None = None
    right_contract_id: str | None = None
    details: tuple[str, ...] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "finding_id",
            "kind",
            "severity",
            "message",
            "subject",
            "left_contract_id",
            "right_contract_id",
            "details",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "finding_id", _identifier(self.finding_id, "finding_id")
        )
        object.__setattr__(self, "kind", _choice(self.kind, "kind", FINDING_KINDS))
        object.__setattr__(
            self, "severity", _choice(self.severity, "severity", FINDING_SEVERITIES)
        )
        object.__setattr__(
            self, "message", _text(self.message, "message", maximum=8192)
        )
        object.__setattr__(
            self,
            "subject",
            _text(self.subject, "subject", no_whitespace=True, maximum=1024),
        )
        object.__setattr__(
            self,
            "left_contract_id",
            _optional_identifier(self.left_contract_id, "left_contract_id"),
        )
        object.__setattr__(
            self,
            "right_contract_id",
            _optional_identifier(self.right_contract_id, "right_contract_id"),
        )
        object.__setattr__(
            self,
            "details",
            _strings(
                self.details,
                "details",
                maximum_item=2048,
                allow_duplicates=True,
                allow_internal_whitespace=True,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "subject": self.subject,
            "left_contract_id": self.left_contract_id,
            "right_contract_id": self.right_contract_id,
            "details": list(self.details),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractFinding":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            finding_id=data["finding_id"],
            kind=data["kind"],
            severity=data["severity"],
            message=data["message"],
            subject=data["subject"],
            left_contract_id=data["left_contract_id"],
            right_contract_id=data["right_contract_id"],
            details=data["details"],
        )


@dataclass(frozen=True, slots=True)
class CallableContract(CanonicalContractRecord):
    """Versioned callable contract: signature, predicates, effects, resources."""

    contract_id: str
    qualified_name: str
    owner_module: str
    shape: str
    provenance: ContractProvenance
    visibility: str = "unspecified"
    parameters: tuple[ParameterContract, ...] = ()
    return_data: DataContract | None = None
    preconditions: tuple[BoundedPredicate, ...] = ()
    postconditions: tuple[BoundedPredicate, ...] = ()
    invariants: tuple[BoundedPredicate, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    effects: tuple[EffectContract, ...] = ()
    exceptions: tuple[ExceptionContract, ...] = ()
    capabilities: tuple[CapabilityContract, ...] = ()
    resources: tuple[ResourceContract, ...] = ()
    temporal: tuple[TemporalConstraint, ...] = ()
    determinism: DeterminismContract | None = None
    schemas: tuple[SchemaContract, ...] = ()
    trust_boundaries: tuple[TrustBoundaryContract, ...] = ()
    symbol_id: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "contract_id",
            "qualified_name",
            "owner_module",
            "shape",
            "provenance",
            "visibility",
            "parameters",
            "return_data",
            "preconditions",
            "postconditions",
            "invariants",
            "assumptions",
            "effects",
            "exceptions",
            "capabilities",
            "resources",
            "temporal",
            "determinism",
            "schemas",
            "trust_boundaries",
            "symbol_id",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "contract_id", _identifier(self.contract_id, "contract_id")
        )
        object.__setattr__(
            self,
            "qualified_name",
            _text(
                self.qualified_name,
                "qualified_name",
                no_whitespace=True,
                maximum=2048,
            ),
        )
        object.__setattr__(
            self,
            "owner_module",
            _text(
                self.owner_module,
                "owner_module",
                no_whitespace=True,
                maximum=1024,
            ),
        )
        object.__setattr__(
            self, "shape", _choice(self.shape, "shape", CALLABLE_SHAPES)
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ContractIRError("provenance must be a ContractProvenance")
        object.__setattr__(
            self,
            "visibility",
            _choice(self.visibility, "visibility", VISIBILITY_KINDS),
        )
        parameters = _records(
            self.parameters,
            ParameterContract,
            "parameters",
            sort_key=lambda item: item.position,
        )
        positions = [item.position for item in parameters]
        if positions != list(range(len(parameters))):
            raise ContractIRError(
                "parameter positions must be unique and contiguous from zero"
            )
        object.__setattr__(self, "parameters", parameters)
        if self.return_data is not None and not isinstance(
            self.return_data, DataContract
        ):
            raise ContractIRError("return_data must be a DataContract or null")
        object.__setattr__(
            self,
            "preconditions",
            _role_predicates(self.preconditions, "precondition", "preconditions"),
        )
        object.__setattr__(
            self,
            "postconditions",
            _role_predicates(
                self.postconditions, "postcondition", "postconditions"
            ),
        )
        object.__setattr__(
            self,
            "invariants",
            _role_predicates(self.invariants, "invariant", "invariants"),
        )
        object.__setattr__(
            self,
            "assumptions",
            _records(
                self.assumptions,
                Assumption,
                "assumptions",
                sort_key=lambda item: item.assumption_id,
            ),
        )
        object.__setattr__(
            self,
            "effects",
            _records(
                self.effects,
                EffectContract,
                "effects",
                sort_key=lambda item: item.effect_id,
            ),
        )
        object.__setattr__(
            self,
            "exceptions",
            _records(
                self.exceptions,
                ExceptionContract,
                "exceptions",
                sort_key=lambda item: item.exception_id,
            ),
        )
        object.__setattr__(
            self,
            "capabilities",
            _records(
                self.capabilities,
                CapabilityContract,
                "capabilities",
                sort_key=lambda item: item.capability_id,
            ),
        )
        object.__setattr__(
            self,
            "resources",
            _records(
                self.resources,
                ResourceContract,
                "resources",
                sort_key=lambda item: item.resource_id,
            ),
        )
        object.__setattr__(
            self,
            "temporal",
            _records(
                self.temporal,
                TemporalConstraint,
                "temporal",
                sort_key=lambda item: item.temporal_id,
            ),
        )
        if self.determinism is not None and not isinstance(
            self.determinism, DeterminismContract
        ):
            raise ContractIRError(
                "determinism must be a DeterminismContract or null"
            )
        object.__setattr__(
            self,
            "schemas",
            _records(
                self.schemas,
                SchemaContract,
                "schemas",
                sort_key=lambda item: item.schema_contract_id,
            ),
        )
        object.__setattr__(
            self,
            "trust_boundaries",
            _records(
                self.trust_boundaries,
                TrustBoundaryContract,
                "trust_boundaries",
                sort_key=lambda item: item.boundary_id,
            ),
        )
        object.__setattr__(
            self,
            "symbol_id",
            _optional_identifier(self.symbol_id, "symbol_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "qualified_name": self.qualified_name,
            "owner_module": self.owner_module,
            "shape": self.shape,
            "provenance": self.provenance.to_dict(),
            "visibility": self.visibility,
            "parameters": [item.to_dict() for item in self.parameters],
            "return_data": (
                None if self.return_data is None else self.return_data.to_dict()
            ),
            "preconditions": [item.to_dict() for item in self.preconditions],
            "postconditions": [item.to_dict() for item in self.postconditions],
            "invariants": [item.to_dict() for item in self.invariants],
            "assumptions": [item.to_dict() for item in self.assumptions],
            "effects": [item.to_dict() for item in self.effects],
            "exceptions": [item.to_dict() for item in self.exceptions],
            "capabilities": [item.to_dict() for item in self.capabilities],
            "resources": [item.to_dict() for item in self.resources],
            "temporal": [item.to_dict() for item in self.temporal],
            "determinism": (
                None if self.determinism is None else self.determinism.to_dict()
            ),
            "schemas": [item.to_dict() for item in self.schemas],
            "trust_boundaries": [
                item.to_dict() for item in self.trust_boundaries
            ],
            "symbol_id": self.symbol_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CallableContract":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            contract_id=data["contract_id"],
            qualified_name=data["qualified_name"],
            owner_module=data["owner_module"],
            shape=data["shape"],
            provenance=ContractProvenance.from_dict(data["provenance"]),
            visibility=data["visibility"],
            parameters=[
                ParameterContract.from_dict(item) for item in data["parameters"]
            ],
            return_data=(
                None
                if data["return_data"] is None
                else DataContract.from_dict(data["return_data"])
            ),
            preconditions=[
                BoundedPredicate.from_dict(item)
                for item in data["preconditions"]
            ],
            postconditions=[
                BoundedPredicate.from_dict(item)
                for item in data["postconditions"]
            ],
            invariants=[
                BoundedPredicate.from_dict(item) for item in data["invariants"]
            ],
            assumptions=[
                Assumption.from_dict(item) for item in data["assumptions"]
            ],
            effects=[EffectContract.from_dict(item) for item in data["effects"]],
            exceptions=[
                ExceptionContract.from_dict(item) for item in data["exceptions"]
            ],
            capabilities=[
                CapabilityContract.from_dict(item)
                for item in data["capabilities"]
            ],
            resources=[
                ResourceContract.from_dict(item) for item in data["resources"]
            ],
            temporal=[
                TemporalConstraint.from_dict(item) for item in data["temporal"]
            ],
            determinism=(
                None
                if data["determinism"] is None
                else DeterminismContract.from_dict(data["determinism"])
            ),
            schemas=[
                SchemaContract.from_dict(item) for item in data["schemas"]
            ],
            trust_boundaries=[
                TrustBoundaryContract.from_dict(item)
                for item in data["trust_boundaries"]
            ],
            symbol_id=data["symbol_id"],
        )


def _role_predicates(
    value: Any,
    expected_role: str,
    field_name: str,
) -> tuple[BoundedPredicate, ...]:
    predicates = _records(
        value,
        BoundedPredicate,
        field_name,
        sort_key=lambda item: item.predicate_id,
    )
    for predicate in predicates:
        if predicate.role != expected_role:
            raise ContractIRError(
                f"{field_name} predicates must have role {expected_role!r}"
            )
    return predicates


@dataclass(frozen=True, slots=True)
class ContractDocument(CanonicalContractRecord):
    """Top-level content-addressed software-contract document (schema v1)."""

    document_id: str
    callables: tuple[CallableContract, ...]
    findings: tuple[ContractFinding, ...] = ()
    registry_revision: str = "1.0.0"
    owner_goal: str = GOAL_ID
    schema: str = SOFTWARE_CONTRACT_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "document_id",
            "owner_goal",
            "registry_revision",
            "callables",
            "findings",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(
            self,
            "schema",
            _text(self.schema, "schema", no_whitespace=True, maximum=256),
        )
        if self.schema != SOFTWARE_CONTRACT_SCHEMA:
            raise ContractIRError(
                f"schema must be exactly {SOFTWARE_CONTRACT_SCHEMA}"
            )
        object.__setattr__(
            self,
            "owner_goal",
            _text(self.owner_goal, "owner_goal", no_whitespace=True, maximum=64),
        )
        if self.owner_goal != GOAL_ID:
            raise ContractIRError(f"owner_goal must be {GOAL_ID}")
        object.__setattr__(
            self,
            "registry_revision",
            _text(
                self.registry_revision,
                "registry_revision",
                no_whitespace=True,
                maximum=64,
            ),
        )
        callables = _records(
            self.callables,
            CallableContract,
            "callables",
            sort_key=lambda item: item.contract_id,
        )
        ids = [item.contract_id for item in callables]
        if len(set(ids)) != len(ids):
            raise ContractIRError("callable contract_id values must be unique")
        object.__setattr__(self, "callables", callables)
        findings = _records(
            self.findings,
            ContractFinding,
            "findings",
            sort_key=lambda item: item.finding_id,
        )
        finding_ids = [item.finding_id for item in findings]
        if len(set(finding_ids)) != len(finding_ids):
            raise ContractIRError("finding_id values must be unique")
        object.__setattr__(self, "findings", findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "document_id": self.document_id,
            "owner_goal": self.owner_goal,
            "registry_revision": self.registry_revision,
            "callables": [item.to_dict() for item in self.callables],
            "findings": [item.to_dict() for item in self.findings],
        }

    def to_json(self) -> str:
        return self.canonical_bytes.decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractDocument":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            document_id=data["document_id"],
            callables=[
                CallableContract.from_dict(item) for item in data["callables"]
            ],
            findings=[
                ContractFinding.from_dict(item) for item in data["findings"]
            ],
            registry_revision=data["registry_revision"],
            owner_goal=data["owner_goal"],
            schema=data["schema"],
        )

    @classmethod
    def from_json(cls, text: str) -> "ContractDocument":
        if type(text) is not str:
            raise ContractIRError("JSON input must be a string")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ContractIRError("invalid JSON") from exc
        return cls.from_dict(payload)


def software_contract_schema_descriptor() -> dict[str, Any]:
    """Return the machine-readable descriptor for the software-contract IR."""

    return {
        "schema": CONTRACT_DESCRIPTOR_SCHEMA,
        "owner_goal": GOAL_ID,
        "task_id": TASK_ID,
        "contract_schema": SOFTWARE_CONTRACT_SCHEMA,
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "fact_kinds": sorted(FACT_KINDS),
        "authority_ranks_high_to_low": list(AUTHORITY_RANKS),
        "predicate_operators": sorted(PREDICATE_OPERATORS),
        "rejected_predicate_operators": sorted(REJECTED_PREDICATE_OPERATORS),
        "effect_kinds": sorted(EFFECT_KINDS),
        "resource_kinds": sorted(RESOURCE_KINDS),
        "determinism_classes": sorted(DETERMINISM_CLASSES),
        "trust_labels": sorted(TRUST_LABELS),
        "guarantees": {
            "explicit_assumptions_and_authority": True,
            "rejects_unbounded_executable_predicates": True,
            "rejects_ambiguous_canonical_values": True,
            "distinguishes_declared_extracted_witnessed_inferred": True,
            "contradictions_are_findings": True,
            "schema_round_trips_and_cids_stable": True,
            "only_sound_lowerable_constructs": True,
            "inference_cannot_self_promote": True,
            "closed_fields": True,
            "no_floats": True,
        },
        "json_schema_path": (
            "ipfs_datasets_py/docs/schemas/software-contract-v1.schema.json"
        ),
        "ast_symbols": [
            "CallableContract",
            "EffectContract",
            "ResourceContract",
            "ContractRegistry",
            "ContractAuthority",
        ],
    }


__all__ = [
    "AUTHORITY_RANKS",
    "AUTHORITY_RANK_ORDER",
    "Assumption",
    "BoundedPredicate",
    "CALLABLE_SHAPES",
    "CONTRACT_DESCRIPTOR_SCHEMA",
    "CapabilityContract",
    "CallableContract",
    "CanonicalContractRecord",
    "ContractAuthority",
    "ContractDocument",
    "ContractFinding",
    "ContractIRError",
    "ContractProvenance",
    "DataContract",
    "DETERMINISM_CLASSES",
    "DeterminismContract",
    "EFFECT_KINDS",
    "EFFECT_OPERATIONS",
    "EffectContract",
    "ExceptionContract",
    "FACT_KINDS",
    "FINDING_KINDS",
    "FINDING_SEVERITIES",
    "GOAL_ID",
    "MAX_SAFE_INTEGER",
    "PARAMETER_KINDS",
    "PREDICATE_OPERATORS",
    "PREDICATE_ROLES",
    "ParameterContract",
    "REJECTED_PREDICATE_OPERATORS",
    "RESOURCE_KINDS",
    "ResourceContract",
    "SCHEMA_IDENTIFIER",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "SOFTWARE_CONTRACT_SCHEMA",
    "SchemaContract",
    "TASK_ID",
    "TRUST_LABELS",
    "TemporalConstraint",
    "TrustBoundaryContract",
    "VISIBILITY_KINDS",
    "software_contract_schema_descriptor",
]
