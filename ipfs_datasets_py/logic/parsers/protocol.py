"""Target-neutral symbolic protocol DSL and ProVerif controlled-source adapter.

Interfaces:

* ``SymbolicProtocolSyntax@1`` — parse/print/elaborate for structured applied-pi
  protocol documents over the shared :class:`ProtocolIR`
* ``ProVerifControlledSource@1`` — deterministic ProtocolIR/process lowering to
  a controlled ProVerif ``.pv`` subset plus query-specific symbolic result
  interpretation

The frontend is deliberately tool-neutral: terms, equations, roles, channels,
adversaries, events, and secrecy/authentication/correspondence claims elaborate
into :class:`~ipfs_datasets_py.logic.software_verification.protocol.ProtocolIR`.
Equational theories and the attacker model participate in document identity.
Unsupported process constructs fail closed with stable diagnostic codes.

ProVerif results retain the symbolic-model ceiling (perfect cryptography /
Dolev-Yao over-approximation) and carry :attr:`ResultAuthority.PROTOCOL` only —
never theorem/kernel authority.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.protocol.proverif import (
    PROVERIF_COMPILER_VERSION,
    ClaimOutcome,
    ClaimVerdict,
    ProVerifCompileResult,
    ProVerifCompiler,
    SymbolicModelCeiling,
    classify_claim_outcomes,
    content_digest,
    parse_proverif_claim_outcomes,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.protocol import (
    PROTOCOL_IR_INTERFACE,
    AdversaryAccess,
    AdversaryCapability,
    AdversaryKind,
    AdversaryKnowledge,
    ChannelSecurity,
    CorrespondenceKind,
    EquationalTheory,
    EventPhase,
    FreshName,
    FreshNameKind,
    FunctionKind,
    KeyKind,
    ProtocolAdversary,
    ProtocolChannel,
    ProtocolClaim,
    ProtocolClaimKind,
    ProtocolEvent,
    ProtocolFunction,
    ProtocolIR,
    ProtocolKey,
    ProtocolMessage,
    ProtocolRole,
    ProtocolSort,
    ProtocolTerm,
    ProtocolValidationError,
    ProtocolVariable,
    RewriteFact,
    SortKind,
    TrustAssumption,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SYMBOLIC_PROTOCOL_SYNTAX_INTERFACE: Final = "SymbolicProtocolSyntax@1"
PROVERIF_CONTROLLED_SOURCE_INTERFACE: Final = "ProVerifControlledSource@1"
SYMBOLIC_PROTOCOL_NOTATION_ID: Final = "symbolic_protocol"
SYMBOLIC_PROTOCOL_NOTATION_VERSION: Final = "1.0.0"
SYMBOLIC_PROTOCOL_PROFILE_ID: Final = "applied_pi_controlled"
SYMBOLIC_PROTOCOL_FAMILY_ID: Final = "cryptographic_protocol"
PROTOCOL_MODULE_VERSION: Final = "1.0.0"
SYMBOLIC_PROTOCOL_DOCUMENT_SCHEMA: Final = "symbolic-protocol-document/v1"
SYMBOLIC_PROTOCOL_PROCESS_SCHEMA: Final = "symbolic-protocol-process/v1"
PROVERIF_CONTROLLED_SOURCE_SCHEMA: Final = "proverif-controlled-source/v1"
PROVERIF_SYMBOLIC_RESULT_SCHEMA: Final = "proverif-symbolic-result/v1"
SYMBOLIC_PROTOCOL_IDENTITY_DOMAIN: Final = "logic.parsers.symbolic-protocol"

# Stable namespaced diagnostic codes.
CODE_UNSUPPORTED_PROCESS: Final = "protocol.unsupported_process_construct"
CODE_INVALID_PROCESS: Final = "protocol.invalid_process"
CODE_MISSING_PROTOCOL: Final = "protocol.missing_protocol_ir"
CODE_INVALID_DOCUMENT: Final = "protocol.invalid_document"
CODE_IDENTITY_MISMATCH: Final = "protocol.identity_mismatch"
CODE_UNSUPPORTED_THEORY: Final = "protocol.unsupported_equational_theory"
CODE_UNSUPPORTED_CLAIM: Final = "protocol.unsupported_claim"
CODE_EMPTY_INPUT: Final = "protocol.empty_input"
CODE_MALFORMED_JSON: Final = "protocol.malformed_json"
CODE_ROLE_PROCESS_UNKNOWN: Final = "protocol.unknown_role_process"
CODE_RESULT_AUTHORITY: Final = "protocol.invalid_result_authority"

_ALL_PROTOCOL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNSUPPORTED_PROCESS,
        CODE_INVALID_PROCESS,
        CODE_MISSING_PROTOCOL,
        CODE_INVALID_DOCUMENT,
        CODE_IDENTITY_MISMATCH,
        CODE_UNSUPPORTED_THEORY,
        CODE_UNSUPPORTED_CLAIM,
        CODE_EMPTY_INPUT,
        CODE_MALFORMED_JSON,
        CODE_ROLE_PROCESS_UNKNOWN,
        CODE_RESULT_AUTHORITY,
    }
)

# Closed process algebra admitted by the controlled applied-pi subset.
class ProcessKind(StrEnum):
    """Supported target-neutral process constructs."""

    NULL = "null"
    OUT = "out"
    IN = "in"
    NEW = "new"
    EVENT = "event"
    LET = "let"
    IF_EQ = "if_eq"
    PARALLEL = "parallel"
    SEQUENCE = "sequence"
    REPLICATION = "replication"


# Explicitly rejected ProVerif/applied-pi constructs (fail closed).
UNSUPPORTED_PROCESS_CONSTRUCTS: Final[frozenset[str]] = frozenset(
    {
        "phase",
        "table",
        "insert",
        "get",
        "diff",
        "sync",
        "barrier",
        "among",
        "choice",
        "macro",
        "letfun",
        "reduc",
        "equation",
        "notin",
        "suchthat",
        "fail",
        "yield",
        "foreach",
    }
)

SUPPORTED_PROCESS_KINDS: Final[frozenset[str]] = frozenset(
    item.value for item in ProcessKind
)

PROVERIF_CONTROLLED_CLAIMS: Final[frozenset[ProtocolClaimKind]] = frozenset(
    {
        ProtocolClaimKind.SECRECY,
        ProtocolClaimKind.REACHABILITY,
        ProtocolClaimKind.AUTHENTICATION,
        ProtocolClaimKind.CORRESPONDENCE,
        ProtocolClaimKind.EQUIVALENCE,
    }
)

PROVERIF_CONTROLLED_THEORIES: Final[frozenset[EquationalTheory]] = frozenset(
    {
        EquationalTheory.FREE,
        EquationalTheory.PAIRING,
        EquationalTheory.SYMMETRIC_ENCRYPTION,
        EquationalTheory.ASYMMETRIC_ENCRYPTION,
        EquationalTheory.SIGNATURES,
        EquationalTheory.HASHING,
    }
)

_SAFE_IDENT = re.compile(r"[^A-Za-z0-9_]+")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,255}$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProtocolSyntaxError(ValueError):
    """Raised when the symbolic protocol DSL is malformed or unsupported."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_INVALID_DOCUMENT,
        path: str = "",
        remediation: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.remediation = remediation
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "remediation": self.remediation,
        }


class ProVerifControlledSourceError(ValueError):
    """Raised when controlled ProVerif lowering or result mapping fails."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_INVALID_DOCUMENT,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise ProtocolSyntaxError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise ProtocolSyntaxError(
            f"{label} must be a stable identifier",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolSyntaxError(
            f"{label} must be a mapping",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ProtocolSyntaxError(
            f"{label} must be a sequence",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return value


def _safe_ident(value: str, *, prefix: str = "id") -> str:
    cleaned = _SAFE_IDENT.sub("_", value.strip())
    cleaned = cleaned.strip("_") or prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned[:96]


def _term_to_pv(term: ProtocolTerm, names: Mapping[str, str]) -> str:
    if term.symbol_id:
        return names.get(term.symbol_id, _safe_ident(term.symbol_id, prefix="sym"))
    if term.function_id:
        fname = names.get(term.function_id, _safe_ident(term.function_id, prefix="f"))
        args = ", ".join(_term_to_pv(arg, names) for arg in term.arguments)
        return f"{fname}({args})" if args else f"{fname}()"
    literal = term.literal or "unit"
    return f'"{_safe_ident(literal, prefix="lit")}"'


def _parse_term(value: object, *, path: str = "term") -> ProtocolTerm:
    if isinstance(value, ProtocolTerm):
        return value
    try:
        return ProtocolTerm.from_dict(_mapping(value, path))
    except (TypeError, ValueError, ProtocolValidationError) as error:
        raise ProtocolSyntaxError(
            f"{path}: {error}",
            code=CODE_INVALID_DOCUMENT,
            path=path,
        ) from error


# ---------------------------------------------------------------------------
# Process algebra
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcessNode:
    """Target-neutral applied-pi process node.

    Supported kinds form a closed algebra.  Any construct listed in
    :data:`UNSUPPORTED_PROCESS_CONSTRUCTS` fails construction explicitly.
    """

    kind: ProcessKind | str
    channel: str = ""
    name: str = ""
    sort: str = ""
    variable: str = ""
    term: ProtocolTerm | None = None
    left: ProtocolTerm | None = None
    right: ProtocolTerm | None = None
    event_id: str = ""
    parameters: tuple[ProtocolTerm, ...] = ()
    children: tuple["ProcessNode", ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SYMBOLIC_PROTOCOL_PROCESS_SCHEMA

    def __post_init__(self) -> None:
        raw_kind = self.kind
        if isinstance(raw_kind, ProcessKind):
            kind_token = raw_kind.value
        else:
            kind_token = _text(raw_kind, "process.kind").casefold()

        if kind_token in UNSUPPORTED_PROCESS_CONSTRUCTS:
            raise ProtocolSyntaxError(
                f"unsupported process construct {kind_token!r}",
                code=CODE_UNSUPPORTED_PROCESS,
                path="process.kind",
                remediation=(
                    "Use only controlled applied-pi constructs: "
                    + ", ".join(sorted(SUPPORTED_PROCESS_KINDS))
                ),
            )
        if kind_token not in SUPPORTED_PROCESS_KINDS:
            raise ProtocolSyntaxError(
                f"unknown process construct {kind_token!r}",
                code=CODE_UNSUPPORTED_PROCESS,
                path="process.kind",
                remediation=(
                    "Admit a supported kind or omit the process; "
                    f"unsupported closed set includes: "
                    + ", ".join(sorted(UNSUPPORTED_PROCESS_CONSTRUCTS))
                ),
            )
        kind = ProcessKind(kind_token)
        object.__setattr__(self, "kind", kind)

        children = tuple(
            item
            if isinstance(item, ProcessNode)
            else ProcessNode.from_dict(_mapping(item, "process.child"))
            for item in _sequence(self.children, "process.children")
        )
        object.__setattr__(self, "children", children)

        parameters = tuple(
            item if isinstance(item, ProtocolTerm) else _parse_term(item, path="process.parameter")
            for item in _sequence(self.parameters, "process.parameters")
        )
        object.__setattr__(self, "parameters", parameters)

        term = self.term
        if term is not None and not isinstance(term, ProtocolTerm):
            term = _parse_term(term, path="process.term")
            object.__setattr__(self, "term", term)
        left = self.left
        if left is not None and not isinstance(left, ProtocolTerm):
            left = _parse_term(left, path="process.left")
            object.__setattr__(self, "left", left)
        right = self.right
        if right is not None and not isinstance(right, ProtocolTerm):
            right = _parse_term(right, path="process.right")
            object.__setattr__(self, "right", right)

        object.__setattr__(
            self, "channel", _text(self.channel, "process.channel", optional=True)
        )
        object.__setattr__(
            self, "name", _text(self.name, "process.name", optional=True)
        )
        object.__setattr__(
            self, "sort", _text(self.sort, "process.sort", optional=True)
        )
        object.__setattr__(
            self, "variable", _text(self.variable, "process.variable", optional=True)
        )
        object.__setattr__(
            self, "event_id", _text(self.event_id, "process.event_id", optional=True)
        )
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise ProtocolSyntaxError(
                "process.metadata must be immutable JSON-compatible data",
                code=CODE_INVALID_PROCESS,
                path="process.metadata",
            ) from error
        if self.schema_version != SYMBOLIC_PROTOCOL_PROCESS_SCHEMA:
            raise ProtocolSyntaxError(
                f"unsupported process schema: {self.schema_version!r}",
                code=CODE_INVALID_PROCESS,
            )
        self._validate_shape()

    def _validate_shape(self) -> None:
        kind = self.kind
        if kind is ProcessKind.NULL:
            if self.children or self.term is not None or self.parameters:
                raise ProtocolSyntaxError(
                    "null process must not carry children, term, or parameters",
                    code=CODE_INVALID_PROCESS,
                )
            return
        if kind is ProcessKind.OUT:
            if not self.channel or self.term is None:
                raise ProtocolSyntaxError(
                    "out process requires channel and term",
                    code=CODE_INVALID_PROCESS,
                )
            if len(self.children) > 1:
                raise ProtocolSyntaxError(
                    "out process may have at most one continuation",
                    code=CODE_INVALID_PROCESS,
                )
            return
        if kind is ProcessKind.IN:
            if not self.channel or not self.variable:
                raise ProtocolSyntaxError(
                    "in process requires channel and variable",
                    code=CODE_INVALID_PROCESS,
                )
            if len(self.children) > 1:
                raise ProtocolSyntaxError(
                    "in process may have at most one continuation",
                    code=CODE_INVALID_PROCESS,
                )
            return
        if kind is ProcessKind.NEW:
            if not self.name or not self.sort:
                raise ProtocolSyntaxError(
                    "new process requires name and sort",
                    code=CODE_INVALID_PROCESS,
                )
            if len(self.children) != 1:
                raise ProtocolSyntaxError(
                    "new process requires exactly one continuation",
                    code=CODE_INVALID_PROCESS,
                )
            return
        if kind is ProcessKind.EVENT:
            if not self.event_id:
                raise ProtocolSyntaxError(
                    "event process requires event_id",
                    code=CODE_INVALID_PROCESS,
                )
            if len(self.children) > 1:
                raise ProtocolSyntaxError(
                    "event process may have at most one continuation",
                    code=CODE_INVALID_PROCESS,
                )
            return
        if kind is ProcessKind.LET:
            if not self.variable or self.term is None:
                raise ProtocolSyntaxError(
                    "let process requires variable and term",
                    code=CODE_INVALID_PROCESS,
                )
            if len(self.children) != 1:
                raise ProtocolSyntaxError(
                    "let process requires exactly one continuation",
                    code=CODE_INVALID_PROCESS,
                )
            return
        if kind is ProcessKind.IF_EQ:
            if self.left is None or self.right is None:
                raise ProtocolSyntaxError(
                    "if_eq process requires left and right terms",
                    code=CODE_INVALID_PROCESS,
                )
            if len(self.children) not in {1, 2}:
                raise ProtocolSyntaxError(
                    "if_eq process requires then (and optional else) children",
                    code=CODE_INVALID_PROCESS,
                )
            return
        if kind is ProcessKind.PARALLEL:
            if len(self.children) < 2:
                raise ProtocolSyntaxError(
                    "parallel process requires at least two children",
                    code=CODE_INVALID_PROCESS,
                )
            return
        if kind is ProcessKind.SEQUENCE:
            if len(self.children) < 1:
                raise ProtocolSyntaxError(
                    "sequence process requires at least one child",
                    code=CODE_INVALID_PROCESS,
                )
            return
        if kind is ProcessKind.REPLICATION:
            if len(self.children) != 1:
                raise ProtocolSyntaxError(
                    "replication requires exactly one child process",
                    code=CODE_INVALID_PROCESS,
                )
            return
        raise ProtocolSyntaxError(
            f"unsupported process construct {kind.value!r}",
            code=CODE_UNSUPPORTED_PROCESS,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "children": [item.to_dict() for item in self.children],
            "event_id": self.event_id,
            "kind": self.kind.value,
            "left": self.left.to_dict() if self.left is not None else None,
            "metadata": self.metadata.to_dict(),
            "name": self.name,
            "parameters": [item.to_dict() for item in self.parameters],
            "right": self.right.to_dict() if self.right is not None else None,
            "schema_version": self.schema_version,
            "sort": self.sort,
            "term": self.term.to_dict() if self.term is not None else None,
            "variable": self.variable,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProcessNode":
        value = _mapping(value, "process")
        # Detect unsupported constructs early even if nested under aliases.
        kind_raw = value.get("kind", value.get("construct", value.get("op", "")))
        return cls(
            kind=kind_raw,
            channel=value.get("channel", ""),
            name=value.get("name", ""),
            sort=value.get("sort", ""),
            variable=value.get("variable", value.get("pattern", "")),
            term=value.get("term"),
            left=value.get("left"),
            right=value.get("right"),
            event_id=value.get("event_id", value.get("event", "")),
            parameters=tuple(value.get("parameters", ())),
            children=tuple(value.get("children", value.get("body", ()))),
            metadata=value.get("metadata", {}),
            schema_version=str(
                value.get("schema_version") or SYMBOLIC_PROTOCOL_PROCESS_SCHEMA
            ),
        )

    @classmethod
    def null(cls) -> "ProcessNode":
        return cls(kind=ProcessKind.NULL)

    def to_proverif(self, names: Mapping[str, str], *, channel_default: str = "c") -> str:
        """Lower this process into controlled ProVerif process syntax."""

        kind = self.kind
        if kind is ProcessKind.NULL:
            return "0"
        if kind is ProcessKind.OUT:
            channel = names.get(self.channel, self.channel or channel_default)
            assert self.term is not None
            payload = _term_to_pv(self.term, names)
            cont = (
                self.children[0].to_proverif(names, channel_default=channel_default)
                if self.children
                else "0"
            )
            return f"out({channel}, {payload}); {cont}"
        if kind is ProcessKind.IN:
            channel = names.get(self.channel, self.channel or channel_default)
            var = _safe_ident(self.variable, prefix="x")
            cont = (
                self.children[0].to_proverif(names, channel_default=channel_default)
                if self.children
                else "0"
            )
            return f"in({channel}, {var}: bitstring); {cont}"
        if kind is ProcessKind.NEW:
            name = names.get(self.name, _safe_ident(self.name, prefix="n"))
            cont = self.children[0].to_proverif(names, channel_default=channel_default)
            return f"new {name}: bitstring; {cont}"
        if kind is ProcessKind.EVENT:
            event_name = names.get(self.event_id, _safe_ident(self.event_id, prefix="ev"))
            if self.parameters:
                args = ", ".join(_term_to_pv(item, names) for item in self.parameters)
            else:
                args = "empty"
            cont = (
                self.children[0].to_proverif(names, channel_default=channel_default)
                if self.children
                else "0"
            )
            if args == "empty":
                return f"new empty: bitstring; event {event_name}(empty); {cont}"
            return f"event {event_name}({args}); {cont}"
        if kind is ProcessKind.LET:
            var = _safe_ident(self.variable, prefix="x")
            assert self.term is not None
            payload = _term_to_pv(self.term, names)
            cont = self.children[0].to_proverif(names, channel_default=channel_default)
            return f"let {var} = {payload} in {cont}"
        if kind is ProcessKind.IF_EQ:
            assert self.left is not None and self.right is not None
            left = _term_to_pv(self.left, names)
            right = _term_to_pv(self.right, names)
            then_p = self.children[0].to_proverif(names, channel_default=channel_default)
            else_p = (
                self.children[1].to_proverif(names, channel_default=channel_default)
                if len(self.children) > 1
                else "0"
            )
            return f"if {left} = {right} then {then_p} else {else_p}"
        if kind is ProcessKind.PARALLEL:
            parts = [
                item.to_proverif(names, channel_default=channel_default)
                for item in self.children
            ]
            return "(" + " | ".join(parts) + ")"
        if kind is ProcessKind.SEQUENCE:
            parts = [
                item.to_proverif(names, channel_default=channel_default)
                for item in self.children
            ]
            # Sequence of full processes: join with semicolon, strip trailing 0 noise.
            cleaned: list[str] = []
            for part in parts:
                text = part.rstrip()
                if text.endswith("; 0"):
                    text = text[: -len("; 0")]
                cleaned.append(text)
            body = "; ".join(cleaned)
            return f"{body}; 0" if not body.endswith("0") else body
        if kind is ProcessKind.REPLICATION:
            body = self.children[0].to_proverif(names, channel_default=channel_default)
            return f"! {body}"
        raise ProtocolSyntaxError(
            f"unsupported process construct {kind.value!r}",
            code=CODE_UNSUPPORTED_PROCESS,
        )


# ---------------------------------------------------------------------------
# Symbolic protocol document
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SymbolicProtocolDocument:
    """Target-neutral symbolic protocol document with optional role processes.

    Identity includes the underlying :class:`ProtocolIR` semantics — therefore
    equational theories and the attacker/adversary model enter identity — plus
    the controlled process trees bound to roles.
    """

    protocol: ProtocolIR
    processes: tuple[tuple[str, ProcessNode], ...] = ()
    notation_id: str = SYMBOLIC_PROTOCOL_NOTATION_ID
    notation_version: str = SYMBOLIC_PROTOCOL_NOTATION_VERSION
    profile_id: str = SYMBOLIC_PROTOCOL_PROFILE_ID
    schema_version: str = SYMBOLIC_PROTOCOL_DOCUMENT_SCHEMA
    document_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.protocol, ProtocolIR):
            raise ProtocolSyntaxError(
                "protocol must be a ProtocolIR",
                code=CODE_MISSING_PROTOCOL,
            )
        role_ids = {role.role_id for role in self.protocol.roles}
        normalized = self._normalize_processes(self.processes, role_ids)
        object.__setattr__(self, "processes", normalized)
        object.__setattr__(
            self, "notation_id", _text(self.notation_id, "notation_id")
        )
        object.__setattr__(
            self, "notation_version", _text(self.notation_version, "notation_version")
        )
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        if self.schema_version != SYMBOLIC_PROTOCOL_DOCUMENT_SCHEMA:
            raise ProtocolSyntaxError(
                f"unsupported symbolic protocol schema: {self.schema_version!r}",
                code=CODE_INVALID_DOCUMENT,
            )
        computed = self._compute_identity()
        if self.document_id and self.document_id != computed.cid:
            raise ProtocolSyntaxError(
                "document_id does not match canonical symbolic protocol identity",
                code=CODE_IDENTITY_MISMATCH,
            )
        object.__setattr__(self, "document_id", computed.cid)

    @staticmethod
    def _normalize_processes(
        raw_processes: object,
        role_ids: set[str],
    ) -> tuple[tuple[str, ProcessNode], ...]:
        if raw_processes is None:
            return ()
        pairs: list[tuple[object, object]] = []
        if isinstance(raw_processes, Mapping):
            pairs.extend(raw_processes.items())
        elif isinstance(raw_processes, Sequence) and not isinstance(
            raw_processes, (str, bytes, bytearray)
        ):
            for entry in raw_processes:
                if (
                    isinstance(entry, Sequence)
                    and not isinstance(entry, (str, bytes, bytearray))
                    and len(entry) == 2
                ):
                    pairs.append((entry[0], entry[1]))
                elif isinstance(entry, Mapping) and "role_id" in entry:
                    pairs.append((entry["role_id"], entry.get("process", entry)))
                else:
                    raise ProtocolSyntaxError(
                        "process entries must be (role_id, process) pairs",
                        code=CODE_INVALID_DOCUMENT,
                        path="processes",
                    )
        else:
            raise ProtocolSyntaxError(
                "processes must be a mapping or sequence of role bindings",
                code=CODE_INVALID_DOCUMENT,
                path="processes",
            )
        items: list[tuple[str, ProcessNode]] = []
        seen: set[str] = set()
        for role_id, process in pairs:
            rid = _identifier(role_id, "processes key")
            if rid not in role_ids:
                raise ProtocolSyntaxError(
                    f"process bound to unknown role {rid!r}",
                    code=CODE_ROLE_PROCESS_UNKNOWN,
                    path=f"processes.{rid}",
                )
            if rid in seen:
                raise ProtocolSyntaxError(
                    f"duplicate process binding for role {rid!r}",
                    code=CODE_INVALID_DOCUMENT,
                    path=f"processes.{rid}",
                )
            seen.add(rid)
            node = (
                process
                if isinstance(process, ProcessNode)
                else ProcessNode.from_dict(_mapping(process, f"processes.{rid}"))
            )
            items.append((rid, node))
        return tuple(sorted(items, key=lambda item: item[0]))

    @property
    def process_nodes(self) -> tuple[tuple[str, ProcessNode], ...]:
        return self.processes

    @property
    def interface(self) -> str:
        return SYMBOLIC_PROTOCOL_SYNTAX_INTERFACE

    @property
    def equational_theories(self) -> tuple[EquationalTheory, ...]:
        return self.protocol.equational_theories

    @property
    def adversary(self) -> ProtocolAdversary:
        return self.protocol.adversary

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=SYMBOLIC_PROTOCOL_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def semantic_dict(self) -> dict[str, Any]:
        """Identity preimage: protocol IR semantics + process trees.

        Equational theories and the attacker model enter through the embedded
        ProtocolIR semantic dictionary and are therefore identity-relevant.
        """

        process_payload = {
            role_id: process.to_dict() for role_id, process in self.process_nodes
        }
        return {
            "equational_theories": [
                item.value for item in self.protocol.equational_theories
            ],
            "family_id": SYMBOLIC_PROTOCOL_FAMILY_ID,
            "interface": SYMBOLIC_PROTOCOL_SYNTAX_INTERFACE,
            "notation_id": self.notation_id,
            "notation_version": self.notation_version,
            "processes": process_payload,
            "profile_id": self.profile_id,
            "protocol": self.protocol.semantic_dict(),
            "protocol_adversary_kind": self.protocol.adversary.kind.value,
            "protocol_document_id": self.protocol.document_id,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["document_id"] = self.document_id
        payload["protocol"] = self.protocol.to_dict()
        return payload

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SymbolicProtocolDocument":
        value = _mapping(value, "symbolic protocol document")
        raw_protocol = value.get("protocol") or value.get("protocol_ir")
        if raw_protocol is None and (
            "sorts" in value or "roles" in value or "adversary" in value
        ):
            # Bare ProtocolIR payload with optional sibling processes.
            protocol_payload = {
                key: item
                for key, item in value.items()
                if key
                not in {
                    "processes",
                    "notation_id",
                    "notation_version",
                    "profile_id",
                    "schema_version",
                    "document_id",
                    "interface",
                    "family_id",
                    "equational_theories_surface",
                    "protocol_adversary_kind",
                    "protocol_document_id",
                }
            }
            raw_protocol = protocol_payload
        if raw_protocol is None:
            raise ProtocolSyntaxError(
                "symbolic protocol document requires protocol or protocol_ir",
                code=CODE_MISSING_PROTOCOL,
            )
        try:
            protocol = (
                raw_protocol
                if isinstance(raw_protocol, ProtocolIR)
                else ProtocolIR.from_dict(_mapping(raw_protocol, "protocol"))
            )
        except (TypeError, ValueError, ProtocolValidationError) as error:
            raise ProtocolSyntaxError(
                f"invalid ProtocolIR payload: {error}",
                code=CODE_MISSING_PROTOCOL,
            ) from error

        return cls(
            protocol=protocol,
            processes=value.get("processes", ()),
            notation_id=str(value.get("notation_id") or SYMBOLIC_PROTOCOL_NOTATION_ID),
            notation_version=str(
                value.get("notation_version") or SYMBOLIC_PROTOCOL_NOTATION_VERSION
            ),
            profile_id=str(value.get("profile_id") or SYMBOLIC_PROTOCOL_PROFILE_ID),
            schema_version=str(
                value.get("schema_version") or SYMBOLIC_PROTOCOL_DOCUMENT_SCHEMA
            ),
            document_id=str(value.get("document_id") or ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "SymbolicProtocolDocument":
        if not isinstance(text, str) or not text.strip():
            raise ProtocolSyntaxError(
                "JSON protocol source must be non-empty text",
                code=CODE_EMPTY_INPUT,
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ProtocolSyntaxError(
                f"malformed protocol JSON: {error}",
                code=CODE_MALFORMED_JSON,
            ) from error
        if not isinstance(payload, Mapping):
            raise ProtocolSyntaxError(
                "protocol JSON root must be an object",
                code=CODE_MALFORMED_JSON,
            )
        return cls.from_dict(payload)

    def elaborate(self) -> ProtocolIR:
        """Return the target-neutral ProtocolIR (already validated)."""

        return self.protocol


# ---------------------------------------------------------------------------
# ProVerif controlled source + symbolic results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProVerifControlledSourceArtifact:
    """Controlled ProVerif source bound to protocol identity and ceiling."""

    source: str
    source_format: str
    source_digest: str
    protocol_document_id: str
    symbolic_document_id: str
    equational_theories: tuple[str, ...]
    adversary_kind: str
    claim_queries: FrozenMap
    ceiling: FrozenMap
    unsupported_claims: tuple[str, ...]
    schema_version: str = PROVERIF_CONTROLLED_SOURCE_SCHEMA
    interface: str = PROVERIF_CONTROLLED_SOURCE_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip() or "\x00" in self.source:
            raise ProVerifControlledSourceError(
                "controlled ProVerif source must be non-empty text without NUL"
            )
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format")
        )
        object.__setattr__(
            self, "source_digest", _text(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self,
            "protocol_document_id",
            _text(self.protocol_document_id, "protocol_document_id", optional=True),
        )
        object.__setattr__(
            self,
            "symbolic_document_id",
            _text(self.symbolic_document_id, "symbolic_document_id", optional=True),
        )
        theories = tuple(
            _text(item, "equational_theories item") for item in self.equational_theories
        )
        object.__setattr__(self, "equational_theories", theories)
        object.__setattr__(
            self, "adversary_kind", _text(self.adversary_kind, "adversary_kind")
        )
        try:
            object.__setattr__(self, "claim_queries", FrozenMap(self.claim_queries))
            object.__setattr__(self, "ceiling", FrozenMap(self.ceiling))
        except (TypeError, ValueError) as error:
            raise ProVerifControlledSourceError(
                "claim_queries and ceiling must be immutable JSON-compatible maps"
            ) from error
        unsupported = tuple(
            _text(item, "unsupported_claims item") for item in self.unsupported_claims
        )
        object.__setattr__(self, "unsupported_claims", unsupported)
        if self.schema_version != PROVERIF_CONTROLLED_SOURCE_SCHEMA:
            raise ProVerifControlledSourceError(
                f"unsupported controlled source schema: {self.schema_version!r}"
            )
        if self.interface != PROVERIF_CONTROLLED_SOURCE_INTERFACE:
            raise ProVerifControlledSourceError(
                f"unsupported controlled source interface: {self.interface!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversary_kind": self.adversary_kind,
            "ceiling": self.ceiling.to_dict(),
            "claim_queries": self.claim_queries.to_dict(),
            "equational_theories": list(self.equational_theories),
            "interface": self.interface,
            "protocol_document_id": self.protocol_document_id,
            "schema_version": self.schema_version,
            "source": self.source,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
            "symbolic_document_id": self.symbolic_document_id,
            "unsupported_claims": list(self.unsupported_claims),
        }


@dataclass(frozen=True, slots=True)
class ProVerifSymbolicResult:
    """Query-specific ProVerif outcome under the symbolic over-approximation.

    Authority is always :attr:`ResultAuthority.PROTOCOL`.  Results never claim
    theorem/kernel proof authority.  The symbolic-model ceiling and per-query
    claim outcomes are retained for audit.
    """

    status: ResultStatus | str
    authority: ResultAuthority | str
    claim_outcomes: tuple[ClaimOutcome, ...]
    ceiling: FrozenMap
    source_digest: str
    equational_theories: tuple[str, ...]
    adversary_kind: str
    accepted: bool
    translation_ceiling: EvidenceAuthority | str
    symbolic_over_approximation: bool = True
    computational_soundness: bool = False
    quarantine: Mapping[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()
    schema_version: str = PROVERIF_SYMBOLIC_RESULT_SCHEMA
    interface: str = PROVERIF_CONTROLLED_SOURCE_INTERFACE

    def __post_init__(self) -> None:
        status = (
            self.status
            if isinstance(self.status, ResultStatus)
            else ResultStatus(str(self.status))
        )
        object.__setattr__(self, "status", status)
        authority = (
            self.authority
            if isinstance(self.authority, ResultAuthority)
            else ResultAuthority(str(self.authority))
        )
        if authority is not ResultAuthority.PROTOCOL:
            raise ProVerifControlledSourceError(
                "ProVerif symbolic results must carry protocol authority "
                f"(got {authority.value!r})",
                code=CODE_RESULT_AUTHORITY,
            )
        object.__setattr__(self, "authority", authority)
        outcomes = tuple(self.claim_outcomes)
        if any(not isinstance(item, ClaimOutcome) for item in outcomes):
            raise ProVerifControlledSourceError(
                "claim_outcomes must be ClaimOutcome values"
            )
        object.__setattr__(self, "claim_outcomes", outcomes)
        try:
            object.__setattr__(self, "ceiling", FrozenMap(self.ceiling))
        except (TypeError, ValueError) as error:
            raise ProVerifControlledSourceError(
                "ceiling must be immutable JSON-compatible data"
            ) from error
        object.__setattr__(
            self, "source_digest", _text(self.source_digest, "source_digest")
        )
        theories = tuple(
            _text(item, "equational_theories item") for item in self.equational_theories
        )
        object.__setattr__(self, "equational_theories", theories)
        object.__setattr__(
            self, "adversary_kind", _text(self.adversary_kind, "adversary_kind")
        )
        if not isinstance(self.accepted, bool):
            raise ProVerifControlledSourceError("accepted must be a boolean")
        if not isinstance(self.symbolic_over_approximation, bool):
            raise ProVerifControlledSourceError(
                "symbolic_over_approximation must be a boolean"
            )
        if not self.symbolic_over_approximation:
            raise ProVerifControlledSourceError(
                "ProVerif results must retain symbolic over-approximation"
            )
        if not isinstance(self.computational_soundness, bool):
            raise ProVerifControlledSourceError(
                "computational_soundness must be a boolean"
            )
        if self.computational_soundness:
            raise ProVerifControlledSourceError(
                "ProVerif symbolic results cannot claim computational soundness"
            )
        translation = (
            self.translation_ceiling
            if isinstance(self.translation_ceiling, EvidenceAuthority)
            else EvidenceAuthority(str(self.translation_ceiling))
        )
        if translation is EvidenceAuthority.AUTHORITATIVE:
            raise ProVerifControlledSourceError(
                "ProVerif symbolic results cannot claim authoritative evidence",
                code=CODE_RESULT_AUTHORITY,
            )
        object.__setattr__(self, "translation_ceiling", translation)
        if self.quarantine is not None and not isinstance(self.quarantine, Mapping):
            raise ProVerifControlledSourceError("quarantine must be a mapping or None")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_text(item, "diagnostics item") for item in self.diagnostics),
        )
        if self.schema_version != PROVERIF_SYMBOLIC_RESULT_SCHEMA:
            raise ProVerifControlledSourceError(
                f"unsupported symbolic result schema: {self.schema_version!r}"
            )

    @property
    def query_specific(self) -> bool:
        """Results are scoped to individual claim queries, not global proofs."""

        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "adversary_kind": self.adversary_kind,
            "authority": self.authority.value,
            "ceiling": self.ceiling.to_dict(),
            "claim_outcomes": [item.to_dict() for item in self.claim_outcomes],
            "computational_soundness": self.computational_soundness,
            "diagnostics": list(self.diagnostics),
            "equational_theories": list(self.equational_theories),
            "interface": self.interface,
            "quarantine": dict(self.quarantine) if self.quarantine is not None else None,
            "query_specific": self.query_specific,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "status": self.status.value,
            "symbolic_over_approximation": self.symbolic_over_approximation,
            "translation_ceiling": self.translation_ceiling.value,
        }


class ProVerifControlledSource:
    """Lower symbolic protocols to controlled ProVerif source and map results.

    Interface: ``ProVerifControlledSource@1``.
    """

    interface: ClassVar[str] = PROVERIF_CONTROLLED_SOURCE_INTERFACE
    schema_version: ClassVar[str] = PROVERIF_CONTROLLED_SOURCE_SCHEMA

    def __init__(self, compiler: ProVerifCompiler | None = None) -> None:
        self._compiler = compiler or ProVerifCompiler()
        if not isinstance(self._compiler, ProVerifCompiler):
            raise ProVerifControlledSourceError("compiler must be a ProVerifCompiler")

    def disclose_ceiling(
        self,
        protocol: ProtocolIR | SymbolicProtocolDocument,
    ) -> dict[str, Any]:
        ir = protocol.protocol if isinstance(protocol, SymbolicProtocolDocument) else protocol
        if not isinstance(ir, ProtocolIR):
            raise ProVerifControlledSourceError("protocol must be ProtocolIR")
        return SymbolicModelCeiling.disclose(
            equational_theories=[item.value for item in ir.equational_theories],
            claim_kinds=[item.kind.value for item in ir.claims],
            adversary_kind=ir.adversary.kind.value,
        )

    def supports_claim(self, kind: ProtocolClaimKind | str) -> bool:
        kind = kind if isinstance(kind, ProtocolClaimKind) else ProtocolClaimKind(kind)
        return kind in PROVERIF_CONTROLLED_CLAIMS

    def supports_theory(self, theory: EquationalTheory | str) -> bool:
        theory = (
            theory if isinstance(theory, EquationalTheory) else EquationalTheory(theory)
        )
        return theory in PROVERIF_CONTROLLED_THEORIES

    def lower(
        self,
        document: SymbolicProtocolDocument | ProtocolIR | Mapping[str, Any],
    ) -> ProVerifControlledSourceArtifact:
        """Compile a protocol document into controlled ProVerif source."""

        if isinstance(document, Mapping):
            document = SymbolicProtocolDocument.from_dict(document)
        if isinstance(document, ProtocolIR):
            document = SymbolicProtocolDocument(protocol=document)
        if not isinstance(document, SymbolicProtocolDocument):
            raise ProVerifControlledSourceError(
                "lower requires SymbolicProtocolDocument, ProtocolIR, or mapping"
            )

        protocol = document.protocol
        for theory in protocol.equational_theories:
            if theory not in PROVERIF_CONTROLLED_THEORIES:
                raise ProVerifControlledSourceError(
                    f"unsupported equational theory for ProVerif: {theory.value}",
                    code=CODE_UNSUPPORTED_THEORY,
                )

        base = self._compiler.compile_protocol(protocol)
        source = base.source
        if document.process_nodes:
            source = self._inject_processes(base, document)

        ceiling = dict(base.ceiling.to_dict())
        # Explicit over-approximation markers retained on every artifact.
        ceiling["symbolic_over_approximation"] = True
        ceiling["computational_soundness"] = False
        ceiling["perfect_cryptography"] = True
        ceiling["result_authority"] = ResultAuthority.PROTOCOL.value
        ceiling["query_specific"] = True
        ceiling["equational_theories"] = list(
            item.value for item in protocol.equational_theories
        )
        ceiling["adversary_kind"] = protocol.adversary.kind.value

        return ProVerifControlledSourceArtifact(
            source=source,
            source_format="pv",
            source_digest=content_digest(source),
            protocol_document_id=protocol.document_id,
            symbolic_document_id=document.document_id,
            equational_theories=tuple(item.value for item in protocol.equational_theories),
            adversary_kind=protocol.adversary.kind.value,
            claim_queries=base.claim_queries,
            ceiling=FrozenMap(ceiling),
            unsupported_claims=base.unsupported_claims,
        )

    def _name_table(self, protocol: ProtocolIR) -> dict[str, str]:
        names: dict[str, str] = {}
        for sort in protocol.sorts:
            names[sort.sort_id] = _safe_ident(sort.name, prefix="t")
        for role in protocol.roles:
            names[role.role_id] = _safe_ident(role.name, prefix="role")
        for variable in protocol.variables:
            names[variable.variable_id] = _safe_ident(variable.name, prefix="v")
        for fresh in protocol.fresh_names:
            names[fresh.name_id] = _safe_ident(fresh.name, prefix="n")
        for key in protocol.keys:
            names[key.key_id] = _safe_ident(key.name, prefix="k")
        for function in protocol.functions:
            names[function.function_id] = _safe_ident(function.name, prefix="f")
        for event in protocol.events:
            names[event.event_id] = _safe_ident(event.name, prefix="ev")
        for channel in protocol.channels:
            names[channel.channel_id] = _safe_ident(channel.name, prefix="c")
        return names

    def _inject_processes(
        self,
        base: ProVerifCompileResult,
        document: SymbolicProtocolDocument,
    ) -> str:
        """Replace the minimal compiler process skeleton with controlled processes."""

        names = self._name_table(document.protocol)
        role_parts: list[str] = []
        for role_id, process in document.process_nodes:
            role_name = names.get(role_id, _safe_ident(role_id, prefix="role"))
            body = process.to_proverif(names)
            role_parts.append(f"(* role:{role_id} / {role_name} *)\n  {body}")
        if not role_parts:
            return base.source
        process_block = "process\n  (" + "\n  |\n  ".join(role_parts) + "\n  ).\n"
        # Drop the compiler's trailing process skeleton.
        head, sep, _tail = base.source.partition("\nprocess\n")
        if not sep:
            return base.source.rstrip() + "\n\n" + process_block
        return head.rstrip() + "\n\n" + process_block

    def interpret_results(
        self,
        *,
        stdout: str,
        stderr: str = "",
        artifact: ProVerifControlledSourceArtifact,
    ) -> ProVerifSymbolicResult:
        """Map ProVerif tool output to query-specific symbolic protocol authority."""

        if not isinstance(artifact, ProVerifControlledSourceArtifact):
            raise ProVerifControlledSourceError(
                "artifact must be a ProVerifControlledSourceArtifact"
            )
        outcomes = parse_proverif_claim_outcomes(
            stdout,
            stderr,
            claim_queries=artifact.claim_queries.to_dict(),
        )
        status, quarantine, accepted = classify_claim_outcomes(outcomes)
        translation = (
            EvidenceAuthority.BOUNDED
            if status in {ResultStatus.SECURE, ResultStatus.ATTACK_FOUND}
            else EvidenceAuthority.NONE
        )
        return ProVerifSymbolicResult(
            status=status,
            authority=ResultAuthority.PROTOCOL,
            claim_outcomes=outcomes,
            ceiling=artifact.ceiling,
            source_digest=artifact.source_digest,
            equational_theories=artifact.equational_theories,
            adversary_kind=artifact.adversary_kind,
            accepted=accepted,
            translation_ceiling=translation,
            symbolic_over_approximation=True,
            computational_soundness=False,
            quarantine=quarantine.to_dict() if quarantine is not None else None,
            diagnostics=tuple(
                filter(
                    None,
                    (
                        quarantine.detail if quarantine is not None else "",
                    ),
                )
            ),
        )


# ---------------------------------------------------------------------------
# Public syntax facade
# ---------------------------------------------------------------------------


class SymbolicProtocolSyntax:
    """Facade for the target-neutral symbolic protocol DSL.

    Interface: ``SymbolicProtocolSyntax@1``.
    """

    interface: ClassVar[str] = SYMBOLIC_PROTOCOL_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = SYMBOLIC_PROTOCOL_NOTATION_ID
    notation_version: ClassVar[str] = SYMBOLIC_PROTOCOL_NOTATION_VERSION
    profile_id: ClassVar[str] = SYMBOLIC_PROTOCOL_PROFILE_ID
    family_id: ClassVar[str] = SYMBOLIC_PROTOCOL_FAMILY_ID

    def __init__(self) -> None:
        self.proverif = ProVerifControlledSource()

    def parse_mapping(
        self, value: Mapping[str, Any]
    ) -> SymbolicProtocolDocument:
        return SymbolicProtocolDocument.from_dict(value)

    def parse_json(self, text: str) -> SymbolicProtocolDocument:
        return SymbolicProtocolDocument.from_json(text)

    def parse_protocol_ir(self, protocol: ProtocolIR) -> SymbolicProtocolDocument:
        if not isinstance(protocol, ProtocolIR):
            raise ProtocolSyntaxError(
                "parse_protocol_ir requires a ProtocolIR",
                code=CODE_MISSING_PROTOCOL,
            )
        return SymbolicProtocolDocument(protocol=protocol)

    def elaborate(self, document: SymbolicProtocolDocument) -> ProtocolIR:
        if not isinstance(document, SymbolicProtocolDocument):
            raise ProtocolSyntaxError(
                "elaborate requires SymbolicProtocolDocument",
                code=CODE_INVALID_DOCUMENT,
            )
        return document.elaborate()

    def print_json(self, document: SymbolicProtocolDocument) -> str:
        if not isinstance(document, SymbolicProtocolDocument):
            raise ProtocolSyntaxError(
                "print_json requires SymbolicProtocolDocument",
                code=CODE_INVALID_DOCUMENT,
            )
        return document.to_json()

    def lower_to_proverif(
        self, document: SymbolicProtocolDocument | ProtocolIR | Mapping[str, Any]
    ) -> ProVerifControlledSourceArtifact:
        return self.proverif.lower(document)

    def interpret_proverif(
        self,
        *,
        stdout: str,
        stderr: str = "",
        artifact: ProVerifControlledSourceArtifact,
    ) -> ProVerifSymbolicResult:
        return self.proverif.interpret_results(
            stdout=stdout, stderr=stderr, artifact=artifact
        )


def parse_symbolic_protocol(
    value: Mapping[str, Any] | str | ProtocolIR,
) -> SymbolicProtocolDocument:
    """Parse a structured symbolic protocol document."""

    syntax = SymbolicProtocolSyntax()
    if isinstance(value, ProtocolIR):
        return syntax.parse_protocol_ir(value)
    if isinstance(value, str):
        return syntax.parse_json(value)
    return syntax.parse_mapping(value)


def lower_to_proverif(
    value: SymbolicProtocolDocument | ProtocolIR | Mapping[str, Any],
) -> ProVerifControlledSourceArtifact:
    """Lower a protocol document to controlled ProVerif source."""

    return ProVerifControlledSource().lower(value)


def interpret_proverif_results(
    *,
    stdout: str,
    stderr: str = "",
    artifact: ProVerifControlledSourceArtifact,
) -> ProVerifSymbolicResult:
    """Interpret ProVerif output under query-specific protocol authority."""

    return ProVerifControlledSource().interpret_results(
        stdout=stdout, stderr=stderr, artifact=artifact
    )


# Re-export IR vocabulary commonly needed by DSL authors.
__all__ = [
    "CODE_UNSUPPORTED_PROCESS",
    "PROVERIF_CONTROLLED_CLAIMS",
    "PROVERIF_CONTROLLED_SOURCE_INTERFACE",
    "PROVERIF_CONTROLLED_THEORIES",
    "PROTOCOL_MODULE_VERSION",
    "ProcessKind",
    "ProcessNode",
    "ProVerifControlledSource",
    "ProVerifControlledSourceArtifact",
    "ProVerifControlledSourceError",
    "ProVerifSymbolicResult",
    "SYMBOLIC_PROTOCOL_FAMILY_ID",
    "SYMBOLIC_PROTOCOL_NOTATION_ID",
    "SYMBOLIC_PROTOCOL_SYNTAX_INTERFACE",
    "SUPPORTED_PROCESS_KINDS",
    "SymbolicProtocolDocument",
    "SymbolicProtocolSyntax",
    "UNSUPPORTED_PROCESS_CONSTRUCTS",
    "interpret_proverif_results",
    "lower_to_proverif",
    "parse_symbolic_protocol",
    # Frequently used ProtocolIR surface for DSL construction.
    "AdversaryAccess",
    "AdversaryCapability",
    "AdversaryKind",
    "AdversaryKnowledge",
    "ChannelSecurity",
    "CorrespondenceKind",
    "EquationalTheory",
    "EventPhase",
    "FreshName",
    "FreshNameKind",
    "FunctionKind",
    "KeyKind",
    "PROTOCOL_IR_INTERFACE",
    "ProtocolAdversary",
    "ProtocolChannel",
    "ProtocolClaim",
    "ProtocolClaimKind",
    "ProtocolEvent",
    "ProtocolFunction",
    "ProtocolIR",
    "ProtocolKey",
    "ProtocolMessage",
    "ProtocolRole",
    "ProtocolSort",
    "ProtocolSyntaxError",
    "ProtocolTerm",
    "ProtocolVariable",
    "RewriteFact",
    "SortKind",
    "SourceRef",
    "SourceSpan",
    "TrustAssumption",
    "ClaimOutcome",
    "ClaimVerdict",
    "ResultAuthority",
    "ResultStatus",
    "EvidenceAuthority",
    "PROVERIF_COMPILER_VERSION",
]
