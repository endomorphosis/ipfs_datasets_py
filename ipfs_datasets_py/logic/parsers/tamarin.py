"""Tamarin multiset-rewriting protocol mappings and controlled-source adapter.

Interfaces:

* ``ProtocolRewritingAdapter@1`` — map multiset rules, persistent/linear facts,
  restrictions, actions, state, equations, and trace lemmas onto the neutral
  :class:`ProtocolIR` model while preserving event/fact provenance
* ``TamarinControlledSource@1`` — deterministic ProtocolIR/rewriting lowering to
  a controlled Tamarin ``.spthy`` subset plus tool/version/profile-bound
  symbolic result interpretation

Tamarin status is always a symbolic protocol result.  It cannot become proof
(theorem/kernel) authority without an independently replayable route that is
explicitly recorded on the result.  Unsupported theory and rule features fail
closed with stable diagnostic codes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.protocol.tamarin import (
    TAMARIN_COMPILER_VERSION,
    ClaimOutcome,
    SymbolicModelCeiling,
    TamarinCompileResult,
    TamarinCompiler,
    classify_claim_outcomes,
    content_digest,
    parse_tamarin_claim_outcomes,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.software_verification.protocol import (
    EquationalTheory,
    ProtocolClaimKind,
    ProtocolEvent,
    ProtocolIR,
    ProtocolTerm,
    ProtocolValidationError,
    RewriteFact,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

TAMARIN_CONTROLLED_SOURCE_INTERFACE: Final = "TamarinControlledSource@1"
PROTOCOL_REWRITING_ADAPTER_INTERFACE: Final = "ProtocolRewritingAdapter@1"
TAMARIN_NOTATION_ID: Final = "tamarin_spthy"
TAMARIN_NOTATION_VERSION: Final = "1.0.0"
TAMARIN_PROFILE_ID: Final = "multiset_rewriting_controlled"
TAMARIN_FAMILY_ID: Final = "cryptographic_protocol"
TAMARIN_MODULE_VERSION: Final = "1.0.0"
PROTOCOL_REWRITING_DOCUMENT_SCHEMA: Final = "protocol-rewriting-document/v1"
MULTISET_FACT_SCHEMA: Final = "tamarin-multiset-fact/v1"
MULTISET_RULE_SCHEMA: Final = "tamarin-multiset-rule/v1"
RESTRICTION_SCHEMA: Final = "tamarin-restriction/v1"
TRACE_LEMMA_SCHEMA: Final = "tamarin-trace-lemma/v1"
TAMARIN_CONTROLLED_SOURCE_SCHEMA: Final = "tamarin-controlled-source/v1"
TAMARIN_SYMBOLIC_RESULT_SCHEMA: Final = "tamarin-symbolic-result/v1"
PROTOCOL_REWRITING_IDENTITY_DOMAIN: Final = "logic.parsers.protocol-rewriting"
DEFAULT_TOOL_ID: Final = "tamarin-prover"
DEFAULT_TOOL_VERSION: Final = "unspecified"

# Stable namespaced diagnostic codes.
CODE_UNSUPPORTED_THEORY: Final = "tamarin.unsupported_theory_feature"
CODE_UNSUPPORTED_RULE: Final = "tamarin.unsupported_rule_feature"
CODE_UNSUPPORTED_CLAIM: Final = "tamarin.unsupported_claim"
CODE_INVALID_FACT: Final = "tamarin.invalid_fact"
CODE_INVALID_RULE: Final = "tamarin.invalid_rule"
CODE_INVALID_RESTRICTION: Final = "tamarin.invalid_restriction"
CODE_INVALID_LEMMA: Final = "tamarin.invalid_lemma"
CODE_INVALID_DOCUMENT: Final = "tamarin.invalid_document"
CODE_MISSING_PROTOCOL: Final = "tamarin.missing_protocol_ir"
CODE_IDENTITY_MISMATCH: Final = "tamarin.identity_mismatch"
CODE_EMPTY_INPUT: Final = "tamarin.empty_input"
CODE_MALFORMED_JSON: Final = "tamarin.malformed_json"
CODE_RESULT_AUTHORITY: Final = "tamarin.invalid_result_authority"
CODE_PROVENANCE: Final = "tamarin.missing_provenance"
CODE_REPLAY_ROUTE: Final = "tamarin.missing_replayable_route"

_ALL_TAMARIN_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNSUPPORTED_THEORY,
        CODE_UNSUPPORTED_RULE,
        CODE_UNSUPPORTED_CLAIM,
        CODE_INVALID_FACT,
        CODE_INVALID_RULE,
        CODE_INVALID_RESTRICTION,
        CODE_INVALID_LEMMA,
        CODE_INVALID_DOCUMENT,
        CODE_MISSING_PROTOCOL,
        CODE_IDENTITY_MISMATCH,
        CODE_EMPTY_INPUT,
        CODE_MALFORMED_JSON,
        CODE_RESULT_AUTHORITY,
        CODE_PROVENANCE,
        CODE_REPLAY_ROUTE,
    }
)

# Closed multiset-rewriting vocabulary admitted by the controlled subset.
class FactMultiplicity(StrEnum):
    """Linear vs persistent fact consumption."""

    LINEAR = "linear"
    PERSISTENT = "persistent"


class FactKind(StrEnum):
    """Semantic role of a multiset fact."""

    STATE = "state"
    ACTION = "action"
    FRESH = "fresh"
    MESSAGE_IN = "message_in"
    MESSAGE_OUT = "message_out"
    KNOWLEDGE = "knowledge"
    EVENT = "event"
    EQUATION = "equation"


class LemmaQuantifier(StrEnum):
    """Trace-lemma quantification."""

    ALL_TRACES = "all-traces"
    EXISTS_TRACE = "exists-trace"


# Explicitly rejected theory features (fail closed).
UNSUPPORTED_THEORY_FEATURES: Final[frozenset[str]] = frozenset(
    {
        "diff",
        "diffie_hellman",
        "xor",
        "multiset",
        "natural_numbers",
        "bilinear_pairing",
        "homomorphic_encryption",
        "revealing_signing",
        "dest_pairing",
        "dest_signing",
        "dest_symmetric_encryption",
        "dest_asymmetric_encryption",
        "equations_ac",
        "equations_aci",
        "oracles",
        "macros",
        "ifdef",
        "define",
        "include",
        "options",
        "heuristic",
        "tactic",
        "predicate",
        "process",
        "letfun",
        "functions_private_outside_controlled",
    }
)

# Explicitly rejected rule features (fail closed).
UNSUPPORTED_RULE_FEATURES: Final[frozenset[str]] = frozenset(
    {
        "lock",
        "unlock",
        "lookup",
        "insert",
        "delete",
        "asynchronous",
        "rule_variants",
        "color",
        "modulo",
        "annotated_priority",
        "embedded_process",
        "diff_rule",
    }
)

TAMARIN_CONTROLLED_CLAIMS: Final[frozenset[ProtocolClaimKind]] = frozenset(
    {
        ProtocolClaimKind.SECRECY,
        ProtocolClaimKind.REACHABILITY,
        ProtocolClaimKind.AUTHENTICATION,
        ProtocolClaimKind.CORRESPONDENCE,
    }
)

TAMARIN_CONTROLLED_THEORIES: Final[frozenset[EquationalTheory]] = frozenset(
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
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TamarinMappingError(ValueError):
    """Raised when multiset-rewriting mapping or controlled source fails."""

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


class TamarinControlledSourceError(TamarinMappingError):
    """Raised when controlled Tamarin lowering or result mapping fails."""


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
        raise TamarinMappingError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise TamarinMappingError(
            f"{label} must be a stable identifier",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TamarinMappingError(
            f"{label} must be a mapping",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TamarinMappingError(
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


def _parse_term(value: object, *, path: str = "term") -> ProtocolTerm:
    if isinstance(value, ProtocolTerm):
        return value
    try:
        return ProtocolTerm.from_dict(_mapping(value, path))
    except (TypeError, ValueError, ProtocolValidationError) as error:
        raise TamarinMappingError(
            f"{path}: {error}",
            code=CODE_INVALID_DOCUMENT,
            path=path,
        ) from error


def _normalize_ids(
    values: object,
    label: str,
) -> tuple[str, ...]:
    if values is None:
        return ()
    items = tuple(_identifier(item, f"{label} item") for item in _sequence(values, label))
    if len(items) != len(set(items)):
        raise TamarinMappingError(
            f"{label} must not contain duplicates",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return items


def _reject_unsupported_token(
    token: str,
    *,
    unsupported: frozenset[str],
    code: str,
    path: str,
    kind: str,
) -> None:
    normalized = token.strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized in unsupported:
        raise TamarinMappingError(
            f"unsupported Tamarin {kind} feature {token!r}",
            code=code,
            path=path,
            remediation=(
                f"Omit {kind} feature {token!r}; controlled subset rejects: "
                + ", ".join(sorted(unsupported))
            ),
        )


def _term_to_spthy(term: ProtocolTerm, names: Mapping[str, str]) -> str:
    if term.symbol_id:
        return names.get(term.symbol_id, _safe_ident(term.symbol_id, prefix="sym"))
    if term.function_id:
        fname = names.get(term.function_id, _safe_ident(term.function_id, prefix="f"))
        args = ", ".join(_term_to_spthy(arg, names) for arg in term.arguments)
        return f"{fname}({args})" if args else f"{fname}()"
    literal = term.literal or "unit"
    return f"'{_safe_ident(literal, prefix='lit')}'"


# ---------------------------------------------------------------------------
# Multiset facts, rules, restrictions, lemmas
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MultisetFact:
    """A linear or persistent multiset fact with provenance.

    Event/action facts retain ``source_ref_ids`` / ``span_ids`` so provenance is
    never dropped when mapping to the neutral protocol model.
    """

    fact_id: str
    name: str
    multiplicity: FactMultiplicity | str = FactMultiplicity.LINEAR
    kind: FactKind | str = FactKind.STATE
    arguments: tuple[ProtocolTerm, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = MULTISET_FACT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact.fact_id"))
        object.__setattr__(self, "name", _text(self.name, "fact.name"))
        multiplicity = (
            self.multiplicity
            if isinstance(self.multiplicity, FactMultiplicity)
            else FactMultiplicity(str(self.multiplicity).casefold())
        )
        object.__setattr__(self, "multiplicity", multiplicity)
        kind = (
            self.kind
            if isinstance(self.kind, FactKind)
            else FactKind(str(self.kind).casefold())
        )
        object.__setattr__(self, "kind", kind)
        arguments = tuple(
            item if isinstance(item, ProtocolTerm) else _parse_term(item, path="fact.argument")
            for item in _sequence(self.arguments, "fact.arguments")
        )
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(
            self,
            "source_ref_ids",
            _normalize_ids(self.source_ref_ids, "fact.source_ref_ids"),
        )
        object.__setattr__(
            self, "span_ids", _normalize_ids(self.span_ids, "fact.span_ids")
        )
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise TamarinMappingError(
                "fact.metadata must be immutable JSON-compatible data",
                code=CODE_INVALID_FACT,
                path="fact.metadata",
            ) from error
        if self.schema_version != MULTISET_FACT_SCHEMA:
            raise TamarinMappingError(
                f"unsupported multiset fact schema: {self.schema_version!r}",
                code=CODE_INVALID_FACT,
            )
        # Action/event facts must retain provenance for audit.
        if kind in {FactKind.ACTION, FactKind.EVENT} and not (
            self.source_ref_ids or self.span_ids
        ):
            raise TamarinMappingError(
                f"{kind.value} fact {self.fact_id!r} requires source provenance "
                "(source_ref_ids or span_ids)",
                code=CODE_PROVENANCE,
                path=f"fact.{self.fact_id}",
                remediation="Attach source_ref_ids/span_ids from the originating protocol event",
            )

    @property
    def is_persistent(self) -> bool:
        return self.multiplicity is FactMultiplicity.PERSISTENT

    def spthy_name(self) -> str:
        name = _safe_ident(self.name, prefix="F")
        return f"!{name}" if self.is_persistent else name

    def to_spthy(self, names: Mapping[str, str]) -> str:
        fname = self.spthy_name()
        if not self.arguments:
            return fname
        args = ", ".join(_term_to_spthy(item, names) for item in self.arguments)
        return f"{fname}({args})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "arguments": [item.to_dict() for item in self.arguments],
            "fact_id": self.fact_id,
            "kind": self.kind.value,
            "metadata": self.metadata.to_dict(),
            "multiplicity": self.multiplicity.value,
            "name": self.name,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MultisetFact":
        value = _mapping(value, "multiset fact")
        feature = value.get("feature") or value.get("construct")
        if isinstance(feature, str):
            _reject_unsupported_token(
                feature,
                unsupported=UNSUPPORTED_RULE_FEATURES | UNSUPPORTED_THEORY_FEATURES,
                code=CODE_UNSUPPORTED_RULE,
                path="fact.feature",
                kind="fact",
            )
        return cls(
            fact_id=value.get("fact_id", value.get("id", "")),
            name=value.get("name", ""),
            multiplicity=value.get("multiplicity", FactMultiplicity.LINEAR.value),
            kind=value.get("kind", FactKind.STATE.value),
            arguments=tuple(value.get("arguments", ())),
            source_ref_ids=tuple(value.get("source_ref_ids", value.get("source_refs", ()))),
            span_ids=tuple(value.get("span_ids", ())),
            metadata=value.get("metadata", {}),
            schema_version=str(value.get("schema_version") or MULTISET_FACT_SCHEMA),
        )

    @classmethod
    def from_protocol_event(cls, event: ProtocolEvent) -> "MultisetFact":
        """Map a ProtocolIR event into an action fact, preserving provenance."""

        if not isinstance(event, ProtocolEvent):
            raise TamarinMappingError(
                "from_protocol_event requires a ProtocolEvent",
                code=CODE_INVALID_FACT,
            )
        return cls(
            fact_id=f"fact:{event.event_id}",
            name=event.name,
            multiplicity=FactMultiplicity.LINEAR,
            kind=FactKind.ACTION,
            arguments=event.parameters,
            source_ref_ids=event.source_ref_ids,
            span_ids=event.span_ids,
            metadata=FrozenMap(
                {
                    "event_id": event.event_id,
                    "phase": event.phase.value,
                    "role_id": event.role_id,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class MultisetRule:
    """A controlled multiset rewrite rule: premises --[actions]-> conclusions."""

    rule_id: str
    name: str
    premises: tuple[MultisetFact, ...] = ()
    actions: tuple[MultisetFact, ...] = ()
    conclusions: tuple[MultisetFact, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = MULTISET_RULE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule.rule_id"))
        object.__setattr__(self, "name", _text(self.name, "rule.name"))
        premises = tuple(
            item if isinstance(item, MultisetFact) else MultisetFact.from_dict(_mapping(item, "rule.premise"))
            for item in _sequence(self.premises, "rule.premises")
        )
        actions = tuple(
            item if isinstance(item, MultisetFact) else MultisetFact.from_dict(_mapping(item, "rule.action"))
            for item in _sequence(self.actions, "rule.actions")
        )
        conclusions = tuple(
            item
            if isinstance(item, MultisetFact)
            else MultisetFact.from_dict(_mapping(item, "rule.conclusion"))
            for item in _sequence(self.conclusions, "rule.conclusions")
        )
        object.__setattr__(self, "premises", premises)
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "conclusions", conclusions)
        object.__setattr__(
            self,
            "source_ref_ids",
            _normalize_ids(self.source_ref_ids, "rule.source_ref_ids"),
        )
        object.__setattr__(
            self, "span_ids", _normalize_ids(self.span_ids, "rule.span_ids")
        )
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise TamarinMappingError(
                "rule.metadata must be immutable JSON-compatible data",
                code=CODE_INVALID_RULE,
                path="rule.metadata",
            ) from error
        if self.schema_version != MULTISET_RULE_SCHEMA:
            raise TamarinMappingError(
                f"unsupported multiset rule schema: {self.schema_version!r}",
                code=CODE_INVALID_RULE,
            )
        # Reject unsupported features smuggled through metadata.
        for key in self.metadata.to_dict():
            _reject_unsupported_token(
                str(key),
                unsupported=UNSUPPORTED_RULE_FEATURES,
                code=CODE_UNSUPPORTED_RULE,
                path=f"rule.metadata.{key}",
                kind="rule",
            )
        if not premises and not conclusions and not actions:
            raise TamarinMappingError(
                f"rule {self.rule_id!r} must declare premises, actions, or conclusions",
                code=CODE_INVALID_RULE,
                path=f"rule.{self.rule_id}",
            )
        for action in actions:
            if action.kind not in {FactKind.ACTION, FactKind.EVENT}:
                raise TamarinMappingError(
                    f"rule action fact {action.fact_id!r} must have kind action or event",
                    code=CODE_INVALID_RULE,
                    path=f"rule.{self.rule_id}.actions",
                )

    def to_spthy(self, names: Mapping[str, str]) -> str:
        rule_name = _safe_ident(self.name, prefix="Rule")
        left = ", ".join(item.to_spthy(names) for item in self.premises) or ""
        acts = ", ".join(item.to_spthy(names) for item in self.actions) or ""
        right = ", ".join(item.to_spthy(names) for item in self.conclusions) or ""
        return (
            f"rule {rule_name}:\n"
            f"  [ {left} ]\n"
            f"  --[ {acts} ]->\n"
            f"  [ {right} ]"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [item.to_dict() for item in self.actions],
            "conclusions": [item.to_dict() for item in self.conclusions],
            "metadata": self.metadata.to_dict(),
            "name": self.name,
            "premises": [item.to_dict() for item in self.premises],
            "rule_id": self.rule_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MultisetRule":
        value = _mapping(value, "multiset rule")
        for key in ("feature", "construct", "kind"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.casefold() in UNSUPPORTED_RULE_FEATURES:
                _reject_unsupported_token(
                    raw,
                    unsupported=UNSUPPORTED_RULE_FEATURES,
                    code=CODE_UNSUPPORTED_RULE,
                    path=f"rule.{key}",
                    kind="rule",
                )
        # Explicit unsupported feature list field.
        for feature in value.get("unsupported_features", value.get("features", ())):
            if isinstance(feature, str):
                _reject_unsupported_token(
                    feature,
                    unsupported=UNSUPPORTED_RULE_FEATURES,
                    code=CODE_UNSUPPORTED_RULE,
                    path="rule.features",
                    kind="rule",
                )
        return cls(
            rule_id=value.get("rule_id", value.get("id", "")),
            name=value.get("name", ""),
            premises=tuple(value.get("premises", value.get("lhs", ()))),
            actions=tuple(value.get("actions", value.get("label", ()))),
            conclusions=tuple(value.get("conclusions", value.get("rhs", ()))),
            source_ref_ids=tuple(value.get("source_ref_ids", value.get("source_refs", ()))),
            span_ids=tuple(value.get("span_ids", ())),
            metadata=value.get("metadata", {}),
            schema_version=str(value.get("schema_version") or MULTISET_RULE_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class Restriction:
    """A controlled Tamarin restriction formula with provenance."""

    restriction_id: str
    name: str
    formula: str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = RESTRICTION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "restriction_id",
            _identifier(self.restriction_id, "restriction.restriction_id"),
        )
        object.__setattr__(self, "name", _text(self.name, "restriction.name"))
        object.__setattr__(self, "formula", _text(self.formula, "restriction.formula"))
        object.__setattr__(
            self,
            "source_ref_ids",
            _normalize_ids(self.source_ref_ids, "restriction.source_ref_ids"),
        )
        object.__setattr__(
            self,
            "span_ids",
            _normalize_ids(self.span_ids, "restriction.span_ids"),
        )
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise TamarinMappingError(
                "restriction.metadata must be immutable JSON-compatible data",
                code=CODE_INVALID_RESTRICTION,
            ) from error
        if self.schema_version != RESTRICTION_SCHEMA:
            raise TamarinMappingError(
                f"unsupported restriction schema: {self.schema_version!r}",
                code=CODE_INVALID_RESTRICTION,
            )
        for token in ("diff", "oracle", "modulo"):
            if token in self.formula.casefold():
                raise TamarinMappingError(
                    f"restriction formula contains unsupported feature {token!r}",
                    code=CODE_UNSUPPORTED_THEORY,
                    path=f"restriction.{self.restriction_id}.formula",
                )

    def to_spthy(self) -> str:
        name = _safe_ident(self.name, prefix="Restr")
        return f'restriction {name}:\n  "{self.formula}"'

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula,
            "metadata": self.metadata.to_dict(),
            "name": self.name,
            "restriction_id": self.restriction_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Restriction":
        value = _mapping(value, "restriction")
        return cls(
            restriction_id=value.get("restriction_id", value.get("id", "")),
            name=value.get("name", ""),
            formula=value.get("formula", value.get("body", "")),
            source_ref_ids=tuple(value.get("source_ref_ids", value.get("source_refs", ()))),
            span_ids=tuple(value.get("span_ids", ())),
            metadata=value.get("metadata", {}),
            schema_version=str(value.get("schema_version") or RESTRICTION_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class TraceLemma:
    """A controlled trace lemma bound to an optional ProtocolIR claim."""

    lemma_id: str
    name: str
    formula: str
    quantifier: LemmaQuantifier | str = LemmaQuantifier.ALL_TRACES
    claim_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = TRACE_LEMMA_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "lemma_id", _identifier(self.lemma_id, "lemma.lemma_id"))
        object.__setattr__(self, "name", _text(self.name, "lemma.name"))
        object.__setattr__(self, "formula", _text(self.formula, "lemma.formula"))
        quantifier = (
            self.quantifier
            if isinstance(self.quantifier, LemmaQuantifier)
            else LemmaQuantifier(str(self.quantifier).casefold())
        )
        object.__setattr__(self, "quantifier", quantifier)
        object.__setattr__(
            self, "claim_id", _text(self.claim_id, "lemma.claim_id", optional=True)
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _normalize_ids(self.source_ref_ids, "lemma.source_ref_ids"),
        )
        object.__setattr__(
            self, "span_ids", _normalize_ids(self.span_ids, "lemma.span_ids")
        )
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise TamarinMappingError(
                "lemma.metadata must be immutable JSON-compatible data",
                code=CODE_INVALID_LEMMA,
            ) from error
        if self.schema_version != TRACE_LEMMA_SCHEMA:
            raise TamarinMappingError(
                f"unsupported trace lemma schema: {self.schema_version!r}",
                code=CODE_INVALID_LEMMA,
            )

    def to_spthy(self) -> str:
        name = _safe_ident(self.name, prefix="lemma")
        if self.quantifier is LemmaQuantifier.EXISTS_TRACE:
            return f'lemma {name}:\n  exists-trace\n  "{self.formula}"'
        return f'lemma {name}:\n  "{self.formula}"'

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "formula": self.formula,
            "lemma_id": self.lemma_id,
            "metadata": self.metadata.to_dict(),
            "name": self.name,
            "quantifier": self.quantifier.value,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceLemma":
        value = _mapping(value, "trace lemma")
        return cls(
            lemma_id=value.get("lemma_id", value.get("id", "")),
            name=value.get("name", ""),
            formula=value.get("formula", value.get("body", "")),
            quantifier=value.get("quantifier", LemmaQuantifier.ALL_TRACES.value),
            claim_id=value.get("claim_id", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", value.get("source_refs", ()))),
            span_ids=tuple(value.get("span_ids", ())),
            metadata=value.get("metadata", {}),
            schema_version=str(value.get("schema_version") or TRACE_LEMMA_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Protocol rewriting document
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolRewritingDocument:
    """Neutral multiset-rewriting document over ProtocolIR plus controlled rules.

    Identity includes ProtocolIR semantics (equational theories, adversary,
    events, claims) and the rewriting surface (facts, rules, restrictions,
    lemmas).  Event and fact provenance participates through those records.
    """

    protocol: ProtocolIR
    facts: tuple[MultisetFact, ...] = ()
    rules: tuple[MultisetRule, ...] = ()
    restrictions: tuple[Restriction, ...] = ()
    lemmas: tuple[TraceLemma, ...] = ()
    equations: tuple[RewriteFact, ...] = ()
    theory_features: tuple[str, ...] = ()
    notation_id: str = TAMARIN_NOTATION_ID
    notation_version: str = TAMARIN_NOTATION_VERSION
    profile_id: str = TAMARIN_PROFILE_ID
    schema_version: str = PROTOCOL_REWRITING_DOCUMENT_SCHEMA
    document_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.protocol, ProtocolIR):
            raise TamarinMappingError(
                "protocol must be a ProtocolIR",
                code=CODE_MISSING_PROTOCOL,
            )
        facts = tuple(
            item if isinstance(item, MultisetFact) else MultisetFact.from_dict(_mapping(item, "fact"))
            for item in _sequence(self.facts, "facts")
        )
        rules = tuple(
            item if isinstance(item, MultisetRule) else MultisetRule.from_dict(_mapping(item, "rule"))
            for item in _sequence(self.rules, "rules")
        )
        restrictions = tuple(
            item
            if isinstance(item, Restriction)
            else Restriction.from_dict(_mapping(item, "restriction"))
            for item in _sequence(self.restrictions, "restrictions")
        )
        lemmas = tuple(
            item if isinstance(item, TraceLemma) else TraceLemma.from_dict(_mapping(item, "lemma"))
            for item in _sequence(self.lemmas, "lemmas")
        )
        equations = tuple(
            item
            if isinstance(item, RewriteFact)
            else RewriteFact.from_dict(_mapping(item, "equation"))
            for item in _sequence(self.equations, "equations")
        )
        features = tuple(
            _text(item, "theory_features item") for item in self.theory_features
        )
        for feature in features:
            _reject_unsupported_token(
                feature,
                unsupported=UNSUPPORTED_THEORY_FEATURES,
                code=CODE_UNSUPPORTED_THEORY,
                path="theory_features",
                kind="theory",
            )
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "restrictions", restrictions)
        object.__setattr__(self, "lemmas", lemmas)
        object.__setattr__(self, "equations", equations)
        object.__setattr__(self, "theory_features", features)
        object.__setattr__(self, "notation_id", _text(self.notation_id, "notation_id"))
        object.__setattr__(
            self, "notation_version", _text(self.notation_version, "notation_version")
        )
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        if self.schema_version != PROTOCOL_REWRITING_DOCUMENT_SCHEMA:
            raise TamarinMappingError(
                f"unsupported protocol rewriting schema: {self.schema_version!r}",
                code=CODE_INVALID_DOCUMENT,
            )
        # Unique IDs within each collection.
        for label, items in (
            ("facts", [item.fact_id for item in facts]),
            ("rules", [item.rule_id for item in rules]),
            ("restrictions", [item.restriction_id for item in restrictions]),
            ("lemmas", [item.lemma_id for item in lemmas]),
            ("equations", [item.fact_id for item in equations]),
        ):
            if len(items) != len(set(items)):
                raise TamarinMappingError(
                    f"{label} IDs must be unique",
                    code=CODE_INVALID_DOCUMENT,
                    path=label,
                )
        computed = self._compute_identity()
        if self.document_id and self.document_id != computed.cid:
            raise TamarinMappingError(
                "document_id does not match canonical protocol rewriting identity",
                code=CODE_IDENTITY_MISMATCH,
            )
        object.__setattr__(self, "document_id", computed.cid)

    @property
    def interface(self) -> str:
        return PROTOCOL_REWRITING_ADAPTER_INTERFACE

    @property
    def equational_theories(self) -> tuple[EquationalTheory, ...]:
        return self.protocol.equational_theories

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=PROTOCOL_REWRITING_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "equations": [item.to_dict() for item in self.equations],
            "equational_theories": [
                item.value for item in self.protocol.equational_theories
            ],
            "facts": [item.to_dict() for item in self.facts],
            "family_id": TAMARIN_FAMILY_ID,
            "interface": PROTOCOL_REWRITING_ADAPTER_INTERFACE,
            "lemmas": [item.to_dict() for item in self.lemmas],
            "notation_id": self.notation_id,
            "notation_version": self.notation_version,
            "profile_id": self.profile_id,
            "protocol": self.protocol.semantic_dict(),
            "protocol_adversary_kind": self.protocol.adversary.kind.value,
            "protocol_document_id": self.protocol.document_id,
            "restrictions": [item.to_dict() for item in self.restrictions],
            "rules": [item.to_dict() for item in self.rules],
            "schema_version": self.schema_version,
            "theory_features": list(self.theory_features),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["document_id"] = self.document_id
        payload["protocol"] = self.protocol.to_dict()
        return payload

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolRewritingDocument":
        value = _mapping(value, "protocol rewriting document")
        # Detect unsupported theory features early.
        for feature in value.get("theory_features", value.get("features", ())):
            if isinstance(feature, str):
                _reject_unsupported_token(
                    feature,
                    unsupported=UNSUPPORTED_THEORY_FEATURES,
                    code=CODE_UNSUPPORTED_THEORY,
                    path="theory_features",
                    kind="theory",
                )
        raw_protocol = value.get("protocol") or value.get("protocol_ir")
        if raw_protocol is None and (
            "sorts" in value or "roles" in value or "adversary" in value
        ):
            protocol_payload = {
                key: item
                for key, item in value.items()
                if key
                not in {
                    "facts",
                    "rules",
                    "restrictions",
                    "lemmas",
                    "equations",
                    "theory_features",
                    "features",
                    "notation_id",
                    "notation_version",
                    "profile_id",
                    "schema_version",
                    "document_id",
                    "interface",
                    "family_id",
                    "protocol_adversary_kind",
                    "protocol_document_id",
                    "equational_theories",
                }
            }
            raw_protocol = protocol_payload
        if raw_protocol is None:
            raise TamarinMappingError(
                "protocol rewriting document requires protocol or protocol_ir",
                code=CODE_MISSING_PROTOCOL,
            )
        try:
            protocol = (
                raw_protocol
                if isinstance(raw_protocol, ProtocolIR)
                else ProtocolIR.from_dict(_mapping(raw_protocol, "protocol"))
            )
        except (TypeError, ValueError, ProtocolValidationError) as error:
            raise TamarinMappingError(
                f"invalid ProtocolIR payload: {error}",
                code=CODE_MISSING_PROTOCOL,
            ) from error
        equations_raw = value.get("equations", ())
        if not equations_raw and protocol.rewrite_facts:
            equations_raw = protocol.rewrite_facts
        return cls(
            protocol=protocol,
            facts=tuple(value.get("facts", ())),
            rules=tuple(value.get("rules", ())),
            restrictions=tuple(value.get("restrictions", ())),
            lemmas=tuple(value.get("lemmas", ())),
            equations=tuple(equations_raw),
            theory_features=tuple(value.get("theory_features", ())),
            notation_id=str(value.get("notation_id") or TAMARIN_NOTATION_ID),
            notation_version=str(
                value.get("notation_version") or TAMARIN_NOTATION_VERSION
            ),
            profile_id=str(value.get("profile_id") or TAMARIN_PROFILE_ID),
            schema_version=str(
                value.get("schema_version") or PROTOCOL_REWRITING_DOCUMENT_SCHEMA
            ),
            document_id=str(value.get("document_id") or ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "ProtocolRewritingDocument":
        if not isinstance(text, str) or not text.strip():
            raise TamarinMappingError(
                "JSON rewriting source must be non-empty text",
                code=CODE_EMPTY_INPUT,
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise TamarinMappingError(
                f"malformed rewriting JSON: {error}",
                code=CODE_MALFORMED_JSON,
            ) from error
        if not isinstance(payload, Mapping):
            raise TamarinMappingError(
                "rewriting JSON root must be an object",
                code=CODE_MALFORMED_JSON,
            )
        return cls.from_dict(payload)

    def elaborate(self) -> ProtocolIR:
        """Return the target-neutral ProtocolIR (already validated)."""

        return self.protocol

    def event_fact_provenance(self) -> tuple[dict[str, Any], ...]:
        """Return provenance receipts for event/action facts and protocol events."""

        receipts: list[dict[str, Any]] = []
        for fact in self.facts:
            if fact.kind in {FactKind.ACTION, FactKind.EVENT}:
                receipts.append(
                    {
                        "fact_id": fact.fact_id,
                        "kind": fact.kind.value,
                        "name": fact.name,
                        "source_ref_ids": list(fact.source_ref_ids),
                        "span_ids": list(fact.span_ids),
                    }
                )
        for event in self.protocol.events:
            receipts.append(
                {
                    "event_id": event.event_id,
                    "kind": "protocol_event",
                    "name": event.name,
                    "source_ref_ids": list(event.source_ref_ids),
                    "span_ids": list(event.span_ids),
                }
            )
        for rule in self.rules:
            for action in rule.actions:
                receipts.append(
                    {
                        "fact_id": action.fact_id,
                        "kind": action.kind.value,
                        "name": action.name,
                        "rule_id": rule.rule_id,
                        "source_ref_ids": list(action.source_ref_ids),
                        "span_ids": list(action.span_ids),
                    }
                )
        return tuple(receipts)


# ---------------------------------------------------------------------------
# Protocol rewriting adapter
# ---------------------------------------------------------------------------


class ProtocolRewritingAdapter:
    """Map multiset-rewriting surfaces onto ProtocolIR with provenance.

    Interface: ``ProtocolRewritingAdapter@1``.
    """

    interface: ClassVar[str] = PROTOCOL_REWRITING_ADAPTER_INTERFACE
    schema_version: ClassVar[str] = PROTOCOL_REWRITING_DOCUMENT_SCHEMA

    def identify_unsupported_theory_features(
        self, features: Sequence[str]
    ) -> tuple[str, ...]:
        """Return the subset of *features* that the controlled mapping rejects."""

        rejected: list[str] = []
        for feature in features:
            token = str(feature).strip().casefold().replace("-", "_").replace(" ", "_")
            if token in UNSUPPORTED_THEORY_FEATURES:
                rejected.append(token)
        return tuple(dict.fromkeys(rejected))

    def identify_unsupported_rule_features(
        self, features: Sequence[str]
    ) -> tuple[str, ...]:
        """Return the subset of *features* that the controlled rule algebra rejects."""

        rejected: list[str] = []
        for feature in features:
            token = str(feature).strip().casefold().replace("-", "_").replace(" ", "_")
            if token in UNSUPPORTED_RULE_FEATURES:
                rejected.append(token)
        return tuple(dict.fromkeys(rejected))

    def require_supported_theory_features(self, features: Sequence[str]) -> None:
        rejected = self.identify_unsupported_theory_features(features)
        if rejected:
            raise TamarinMappingError(
                "unsupported Tamarin theory features: " + ", ".join(rejected),
                code=CODE_UNSUPPORTED_THEORY,
                path="theory_features",
                remediation="Remove unsupported theory features from the controlled subset",
            )

    def require_supported_rule_features(self, features: Sequence[str]) -> None:
        rejected = self.identify_unsupported_rule_features(features)
        if rejected:
            raise TamarinMappingError(
                "unsupported Tamarin rule features: " + ", ".join(rejected),
                code=CODE_UNSUPPORTED_RULE,
                path="rule_features",
                remediation="Remove unsupported rule features from the controlled subset",
            )

    def map_protocol_events_to_facts(
        self, protocol: ProtocolIR
    ) -> tuple[MultisetFact, ...]:
        """Project ProtocolIR events into action facts, preserving provenance."""

        if not isinstance(protocol, ProtocolIR):
            raise TamarinMappingError(
                "map_protocol_events_to_facts requires ProtocolIR",
                code=CODE_MISSING_PROTOCOL,
            )
        return tuple(MultisetFact.from_protocol_event(event) for event in protocol.events)

    def map_equations(self, protocol: ProtocolIR) -> tuple[RewriteFact, ...]:
        if not isinstance(protocol, ProtocolIR):
            raise TamarinMappingError(
                "map_equations requires ProtocolIR",
                code=CODE_MISSING_PROTOCOL,
            )
        return protocol.rewrite_facts

    def build_document(
        self,
        protocol: ProtocolIR | Mapping[str, Any],
        *,
        facts: Sequence[MultisetFact | Mapping[str, Any]] = (),
        rules: Sequence[MultisetRule | Mapping[str, Any]] = (),
        restrictions: Sequence[Restriction | Mapping[str, Any]] = (),
        lemmas: Sequence[TraceLemma | Mapping[str, Any]] = (),
        equations: Sequence[RewriteFact | Mapping[str, Any]] | None = None,
        theory_features: Sequence[str] = (),
        include_event_facts: bool = True,
    ) -> ProtocolRewritingDocument:
        """Build a rewriting document, optionally auto-mapping protocol events."""

        if isinstance(protocol, Mapping):
            protocol = ProtocolIR.from_dict(protocol)
        if not isinstance(protocol, ProtocolIR):
            raise TamarinMappingError(
                "build_document requires ProtocolIR",
                code=CODE_MISSING_PROTOCOL,
            )
        self.require_supported_theory_features(theory_features)
        mapped_facts = list(facts)
        if include_event_facts and not mapped_facts:
            mapped_facts.extend(self.map_protocol_events_to_facts(protocol))
        eq = (
            tuple(equations)
            if equations is not None
            else self.map_equations(protocol)
        )
        return ProtocolRewritingDocument(
            protocol=protocol,
            facts=tuple(mapped_facts),
            rules=tuple(rules),
            restrictions=tuple(restrictions),
            lemmas=tuple(lemmas),
            equations=eq,
            theory_features=tuple(theory_features),
        )

    def parse(
        self, value: Mapping[str, Any] | str | ProtocolIR
    ) -> ProtocolRewritingDocument:
        if isinstance(value, ProtocolIR):
            return self.build_document(value)
        if isinstance(value, str):
            return ProtocolRewritingDocument.from_json(value)
        return ProtocolRewritingDocument.from_dict(value)

    def elaborate(self, document: ProtocolRewritingDocument) -> ProtocolIR:
        if not isinstance(document, ProtocolRewritingDocument):
            raise TamarinMappingError(
                "elaborate requires ProtocolRewritingDocument",
                code=CODE_INVALID_DOCUMENT,
            )
        return document.elaborate()

    def provenance_receipts(
        self, document: ProtocolRewritingDocument
    ) -> tuple[dict[str, Any], ...]:
        if not isinstance(document, ProtocolRewritingDocument):
            raise TamarinMappingError(
                "provenance_receipts requires ProtocolRewritingDocument",
                code=CODE_INVALID_DOCUMENT,
            )
        return document.event_fact_provenance()


# ---------------------------------------------------------------------------
# Tamarin controlled source + symbolic results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TamarinControlledSourceArtifact:
    """Controlled Tamarin ``.spthy`` source bound to protocol identity and ceiling."""

    source: str
    source_format: str
    source_digest: str
    protocol_document_id: str
    rewriting_document_id: str
    equational_theories: tuple[str, ...]
    adversary_kind: str
    claim_lemmas: FrozenMap
    ceiling: FrozenMap
    unsupported_claims: tuple[str, ...]
    unsupported_theory_features: tuple[str, ...]
    unsupported_rule_features: tuple[str, ...]
    event_fact_provenance: tuple[dict[str, Any], ...]
    profile_id: str = TAMARIN_PROFILE_ID
    tool_id: str = DEFAULT_TOOL_ID
    tool_version: str = DEFAULT_TOOL_VERSION
    schema_version: str = TAMARIN_CONTROLLED_SOURCE_SCHEMA
    interface: str = TAMARIN_CONTROLLED_SOURCE_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip() or "\x00" in self.source:
            raise TamarinControlledSourceError(
                "controlled Tamarin source must be non-empty text without NUL"
            )
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format")
        )
        object.__setattr__(
            self, "source_digest", _text(self.source_digest, "source_digest")
        )
        if not _DIGEST_RE.fullmatch(self.source_digest):
            # content_digest may produce non-raw digests in some builds; accept
            # any non-empty digest string already validated by _text.
            pass
        object.__setattr__(
            self,
            "protocol_document_id",
            _text(self.protocol_document_id, "protocol_document_id", optional=True),
        )
        object.__setattr__(
            self,
            "rewriting_document_id",
            _text(self.rewriting_document_id, "rewriting_document_id", optional=True),
        )
        theories = tuple(
            _text(item, "equational_theories item") for item in self.equational_theories
        )
        object.__setattr__(self, "equational_theories", theories)
        object.__setattr__(
            self, "adversary_kind", _text(self.adversary_kind, "adversary_kind")
        )
        try:
            object.__setattr__(self, "claim_lemmas", FrozenMap(self.claim_lemmas))
            object.__setattr__(self, "ceiling", FrozenMap(self.ceiling))
        except (TypeError, ValueError) as error:
            raise TamarinControlledSourceError(
                "claim_lemmas and ceiling must be immutable JSON-compatible maps"
            ) from error
        object.__setattr__(
            self,
            "unsupported_claims",
            tuple(_text(item, "unsupported_claims item") for item in self.unsupported_claims),
        )
        object.__setattr__(
            self,
            "unsupported_theory_features",
            tuple(
                _text(item, "unsupported_theory_features item")
                for item in self.unsupported_theory_features
            ),
        )
        object.__setattr__(
            self,
            "unsupported_rule_features",
            tuple(
                _text(item, "unsupported_rule_features item")
                for item in self.unsupported_rule_features
            ),
        )
        provenance = tuple(
            dict(item) if isinstance(item, Mapping) else item
            for item in self.event_fact_provenance
        )
        if any(not isinstance(item, Mapping) for item in provenance):
            raise TamarinControlledSourceError(
                "event_fact_provenance entries must be mappings"
            )
        object.__setattr__(self, "event_fact_provenance", provenance)
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(self, "tool_id", _text(self.tool_id, "tool_id"))
        object.__setattr__(
            self, "tool_version", _text(self.tool_version, "tool_version")
        )
        if self.schema_version != TAMARIN_CONTROLLED_SOURCE_SCHEMA:
            raise TamarinControlledSourceError(
                f"unsupported controlled source schema: {self.schema_version!r}"
            )
        if self.interface != TAMARIN_CONTROLLED_SOURCE_INTERFACE:
            raise TamarinControlledSourceError(
                f"unsupported controlled source interface: {self.interface!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversary_kind": self.adversary_kind,
            "ceiling": self.ceiling.to_dict(),
            "claim_lemmas": self.claim_lemmas.to_dict(),
            "equational_theories": list(self.equational_theories),
            "event_fact_provenance": [dict(item) for item in self.event_fact_provenance],
            "interface": self.interface,
            "profile_id": self.profile_id,
            "protocol_document_id": self.protocol_document_id,
            "rewriting_document_id": self.rewriting_document_id,
            "schema_version": self.schema_version,
            "source": self.source,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "unsupported_claims": list(self.unsupported_claims),
            "unsupported_rule_features": list(self.unsupported_rule_features),
            "unsupported_theory_features": list(self.unsupported_theory_features),
        }


@dataclass(frozen=True, slots=True)
class TamarinSymbolicResult:
    """Tool/version/profile-bound Tamarin symbolic protocol outcome.

    Authority is always :attr:`ResultAuthority.PROTOCOL`.  Results never claim
    theorem/kernel proof authority.  Promotion to proof authority is gated by
    an independently replayable route that must be explicitly recorded; the
    default is that Tamarin status alone is insufficient.
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
    tool_id: str
    tool_version: str
    profile_id: str
    independently_replayable: bool = False
    replay_route: str = ""
    symbolic_model: bool = True
    computational_soundness: bool = False
    quarantine: Mapping[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()
    event_fact_provenance: tuple[dict[str, Any], ...] = ()
    schema_version: str = TAMARIN_SYMBOLIC_RESULT_SCHEMA
    interface: str = TAMARIN_CONTROLLED_SOURCE_INTERFACE

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
            raise TamarinControlledSourceError(
                "Tamarin symbolic results must carry protocol authority "
                f"(got {authority.value!r})",
                code=CODE_RESULT_AUTHORITY,
            )
        object.__setattr__(self, "authority", authority)
        outcomes = tuple(self.claim_outcomes)
        if any(not isinstance(item, ClaimOutcome) for item in outcomes):
            raise TamarinControlledSourceError(
                "claim_outcomes must be ClaimOutcome values"
            )
        object.__setattr__(self, "claim_outcomes", outcomes)
        try:
            object.__setattr__(self, "ceiling", FrozenMap(self.ceiling))
        except (TypeError, ValueError) as error:
            raise TamarinControlledSourceError(
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
            raise TamarinControlledSourceError("accepted must be a boolean")
        if not isinstance(self.symbolic_model, bool):
            raise TamarinControlledSourceError("symbolic_model must be a boolean")
        if not self.symbolic_model:
            raise TamarinControlledSourceError(
                "Tamarin results must retain the symbolic-model ceiling"
            )
        if not isinstance(self.computational_soundness, bool):
            raise TamarinControlledSourceError(
                "computational_soundness must be a boolean"
            )
        if self.computational_soundness:
            raise TamarinControlledSourceError(
                "Tamarin symbolic results cannot claim computational soundness"
            )
        translation = (
            self.translation_ceiling
            if isinstance(self.translation_ceiling, EvidenceAuthority)
            else EvidenceAuthority(str(self.translation_ceiling))
        )
        if translation is EvidenceAuthority.AUTHORITATIVE:
            raise TamarinControlledSourceError(
                "Tamarin symbolic results cannot claim authoritative evidence",
                code=CODE_RESULT_AUTHORITY,
            )
        object.__setattr__(self, "translation_ceiling", translation)
        object.__setattr__(self, "tool_id", _text(self.tool_id, "tool_id"))
        object.__setattr__(
            self, "tool_version", _text(self.tool_version, "tool_version")
        )
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        if not isinstance(self.independently_replayable, bool):
            raise TamarinControlledSourceError(
                "independently_replayable must be a boolean"
            )
        object.__setattr__(
            self, "replay_route", _text(self.replay_route, "replay_route", optional=True)
        )
        # Proof-authority gate: without an independently replayable route the
        # result remains a tool/version/profile-bound symbolic status only.
        if self.independently_replayable and not self.replay_route:
            raise TamarinControlledSourceError(
                "independently_replayable requires an explicit replay_route",
                code=CODE_REPLAY_ROUTE,
            )
        if self.quarantine is not None and not isinstance(self.quarantine, Mapping):
            raise TamarinControlledSourceError("quarantine must be a mapping or None")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_text(item, "diagnostics item") for item in self.diagnostics),
        )
        provenance = tuple(
            dict(item) if isinstance(item, Mapping) else item
            for item in self.event_fact_provenance
        )
        if any(not isinstance(item, Mapping) for item in provenance):
            raise TamarinControlledSourceError(
                "event_fact_provenance entries must be mappings"
            )
        object.__setattr__(self, "event_fact_provenance", provenance)
        if self.schema_version != TAMARIN_SYMBOLIC_RESULT_SCHEMA:
            raise TamarinControlledSourceError(
                f"unsupported symbolic result schema: {self.schema_version!r}"
            )

    @property
    def tool_version_profile_bound(self) -> bool:
        """Status is bound to tool identity, version, and controlled profile."""

        return bool(self.tool_id and self.tool_version and self.profile_id)

    @property
    def can_become_proof_authority(self) -> bool:
        """Tamarin status alone never grants theorem/kernel proof authority.

        An independently replayable route is a necessary but not sufficient
        condition; this property reports only the local gate recorded on the
        result.  The authority field remains PROTOCOL either way.
        """

        return bool(
            self.independently_replayable
            and self.replay_route
            and self.authority is ResultAuthority.PROTOCOL
        )

    def as_proof_authority(self) -> None:
        """Refuse promotion to theorem/kernel proof authority."""

        if not self.can_become_proof_authority:
            raise TamarinControlledSourceError(
                "Tamarin status is a tool/version/profile-bound symbolic result "
                "and cannot become proof authority without an independently "
                "replayable route",
                code=CODE_RESULT_AUTHORITY,
            )
        # Even with a replay route, this adapter never re-labels authority.
        raise TamarinControlledSourceError(
            "Tamarin results retain protocol authority; independent replay may "
            "feed a separate kernel/proof lane but does not rewrite this result",
            code=CODE_RESULT_AUTHORITY,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "adversary_kind": self.adversary_kind,
            "authority": self.authority.value,
            "can_become_proof_authority": self.can_become_proof_authority,
            "ceiling": self.ceiling.to_dict(),
            "claim_outcomes": [item.to_dict() for item in self.claim_outcomes],
            "computational_soundness": self.computational_soundness,
            "diagnostics": list(self.diagnostics),
            "equational_theories": list(self.equational_theories),
            "event_fact_provenance": [dict(item) for item in self.event_fact_provenance],
            "independently_replayable": self.independently_replayable,
            "interface": self.interface,
            "profile_id": self.profile_id,
            "quarantine": dict(self.quarantine) if self.quarantine is not None else None,
            "replay_route": self.replay_route,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "status": self.status.value,
            "symbolic_model": self.symbolic_model,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "tool_version_profile_bound": self.tool_version_profile_bound,
            "translation_ceiling": self.translation_ceiling.value,
        }


class TamarinControlledSource:
    """Lower rewriting documents to controlled Tamarin source and map results.

    Interface: ``TamarinControlledSource@1``.
    """

    interface: ClassVar[str] = TAMARIN_CONTROLLED_SOURCE_INTERFACE
    schema_version: ClassVar[str] = TAMARIN_CONTROLLED_SOURCE_SCHEMA

    def __init__(
        self,
        compiler: TamarinCompiler | None = None,
        *,
        tool_id: str = DEFAULT_TOOL_ID,
        tool_version: str = DEFAULT_TOOL_VERSION,
        rewriting: ProtocolRewritingAdapter | None = None,
    ) -> None:
        self._compiler = compiler or TamarinCompiler()
        if not isinstance(self._compiler, TamarinCompiler):
            raise TamarinControlledSourceError("compiler must be a TamarinCompiler")
        self.tool_id = _text(tool_id, "tool_id")
        self.tool_version = _text(tool_version, "tool_version")
        self.rewriting = rewriting or ProtocolRewritingAdapter()
        if not isinstance(self.rewriting, ProtocolRewritingAdapter):
            raise TamarinControlledSourceError(
                "rewriting must be a ProtocolRewritingAdapter"
            )

    def disclose_ceiling(
        self,
        protocol: ProtocolIR | ProtocolRewritingDocument,
    ) -> dict[str, Any]:
        ir = protocol.protocol if isinstance(protocol, ProtocolRewritingDocument) else protocol
        if not isinstance(ir, ProtocolIR):
            raise TamarinControlledSourceError("protocol must be ProtocolIR")
        ceiling = SymbolicModelCeiling.disclose(
            equational_theories=[item.value for item in ir.equational_theories],
            claim_kinds=[item.kind.value for item in ir.claims],
            adversary_kind=ir.adversary.kind.value,
        )
        ceiling["result_authority"] = ResultAuthority.PROTOCOL.value
        ceiling["tool_id"] = self.tool_id
        ceiling["tool_version"] = self.tool_version
        ceiling["profile_id"] = TAMARIN_PROFILE_ID
        ceiling["independently_replayable_required_for_proof"] = True
        ceiling["proof_authority"] = False
        return ceiling

    def supports_claim(self, kind: ProtocolClaimKind | str) -> bool:
        kind = kind if isinstance(kind, ProtocolClaimKind) else ProtocolClaimKind(kind)
        return kind in TAMARIN_CONTROLLED_CLAIMS

    def supports_theory(self, theory: EquationalTheory | str) -> bool:
        theory = (
            theory if isinstance(theory, EquationalTheory) else EquationalTheory(theory)
        )
        return theory in TAMARIN_CONTROLLED_THEORIES

    def lower(
        self,
        document: ProtocolRewritingDocument | ProtocolIR | Mapping[str, Any],
        *,
        tool_version: str | None = None,
    ) -> TamarinControlledSourceArtifact:
        """Compile a rewriting/protocol document into controlled Tamarin source."""

        if isinstance(document, Mapping):
            document = ProtocolRewritingDocument.from_dict(document)
        if isinstance(document, ProtocolIR):
            document = self.rewriting.build_document(document)
        if not isinstance(document, ProtocolRewritingDocument):
            raise TamarinControlledSourceError(
                "lower requires ProtocolRewritingDocument, ProtocolIR, or mapping"
            )

        protocol = document.protocol
        for theory in protocol.equational_theories:
            if theory not in TAMARIN_CONTROLLED_THEORIES:
                raise TamarinControlledSourceError(
                    f"unsupported equational theory for Tamarin: {theory.value}",
                    code=CODE_UNSUPPORTED_THEORY,
                )

        base = self._compiler.compile_protocol(protocol)
        source = self._inject_rewriting(base, document)

        ceiling = dict(base.ceiling.to_dict())
        ceiling["symbolic_model"] = True
        ceiling["computational_soundness"] = False
        ceiling["perfect_cryptography"] = True
        ceiling["result_authority"] = ResultAuthority.PROTOCOL.value
        ceiling["proof_authority"] = False
        ceiling["tool_id"] = self.tool_id
        ceiling["tool_version"] = tool_version or self.tool_version
        ceiling["profile_id"] = document.profile_id
        ceiling["independently_replayable_required_for_proof"] = True
        ceiling["equational_theories"] = list(
            item.value for item in protocol.equational_theories
        )
        ceiling["adversary_kind"] = protocol.adversary.kind.value
        ceiling["compiler"] = TAMARIN_COMPILER_VERSION

        version = tool_version or self.tool_version
        return TamarinControlledSourceArtifact(
            source=source,
            source_format="spthy",
            source_digest=content_digest(source),
            protocol_document_id=protocol.document_id,
            rewriting_document_id=document.document_id,
            equational_theories=tuple(item.value for item in protocol.equational_theories),
            adversary_kind=protocol.adversary.kind.value,
            claim_lemmas=base.claim_lemmas,
            ceiling=FrozenMap(ceiling),
            unsupported_claims=base.unsupported_claims,
            # Theory/rule features fail closed at document construction.
            unsupported_theory_features=(),
            unsupported_rule_features=(),
            event_fact_provenance=document.event_fact_provenance(),
            profile_id=document.profile_id,
            tool_id=self.tool_id,
            tool_version=version,
        )

    def _name_table(self, protocol: ProtocolIR) -> dict[str, str]:
        names: dict[str, str] = {}
        for sort in protocol.sorts:
            names[sort.sort_id] = _safe_ident(sort.name, prefix="Sort")
        for role in protocol.roles:
            names[role.role_id] = _safe_ident(role.name, prefix="Role")
        for variable in protocol.variables:
            names[variable.variable_id] = _safe_ident(variable.name, prefix="v")
        for fresh in protocol.fresh_names:
            names[fresh.name_id] = f"~{_safe_ident(fresh.name, prefix='n')}"
        for key in protocol.keys:
            names[key.key_id] = _safe_ident(key.name, prefix="k")
        for function in protocol.functions:
            names[function.function_id] = _safe_ident(function.name, prefix="f")
        for event in protocol.events:
            names[event.event_id] = _safe_ident(event.name, prefix="Ev")
        return names

    def _inject_rewriting(
        self,
        base: TamarinCompileResult,
        document: ProtocolRewritingDocument,
    ) -> str:
        """Append controlled multiset rules, restrictions, and lemmas to source."""

        if not (
            document.rules
            or document.restrictions
            or document.lemmas
            or document.facts
            or document.equations
        ):
            return base.source

        names = self._name_table(document.protocol)
        blocks: list[str] = []
        blocks.append("/* ProtocolRewritingAdapter@1 controlled multiset surface */")

        # Persistent / linear fact declarations as comments with provenance.
        for fact in document.facts:
            prov = (
                f" sources={list(fact.source_ref_ids)} spans={list(fact.span_ids)}"
                if fact.source_ref_ids or fact.span_ids
                else ""
            )
            blocks.append(
                f"/* fact {fact.fact_id} multiplicity={fact.multiplicity.value} "
                f"kind={fact.kind.value}{prov} */"
            )

        for equation in document.equations:
            left = _term_to_spthy(equation.left, names)
            right = _term_to_spthy(equation.right, names)
            blocks.append(
                f"/* equation {equation.fact_id} theory={equation.theory.value}: "
                f"{left} = {right} "
                f"sources={list(equation.source_ref_ids)} "
                f"spans={list(equation.span_ids)} */"
            )

        for rule in document.rules:
            blocks.append(rule.to_spthy(names))
            blocks.append("")

        for restriction in document.restrictions:
            blocks.append(restriction.to_spthy())
            blocks.append("")

        for lemma in document.lemmas:
            # Avoid duplicating claim lemmas already emitted by the compiler.
            claim_lemmas = base.claim_lemmas.to_dict()
            if lemma.claim_id and lemma.claim_id in claim_lemmas:
                blocks.append(
                    f"/* lemma {lemma.lemma_id} bound to claim {lemma.claim_id} "
                    f"(compiler lemma {claim_lemmas[lemma.claim_id]}) "
                    f"sources={list(lemma.source_ref_ids)} */"
                )
            else:
                blocks.append(lemma.to_spthy())
                blocks.append("")

        extra = "\n".join(blocks).rstrip() + "\n"
        # Insert before trailing "end" (callable repl avoids backslash escapes).
        if re.search(r"(?m)^\s*end\s*$", base.source):
            return re.sub(
                r"(?m)^\s*end\s*$",
                lambda _match: extra + "\nend\n",
                base.source,
                count=1,
            )
        return base.source.rstrip() + "\n\n" + extra

    def interpret_results(
        self,
        *,
        stdout: str,
        stderr: str = "",
        artifact: TamarinControlledSourceArtifact,
        independently_replayable: bool = False,
        replay_route: str = "",
    ) -> TamarinSymbolicResult:
        """Map Tamarin tool output to a tool/version/profile-bound symbolic result."""

        if not isinstance(artifact, TamarinControlledSourceArtifact):
            raise TamarinControlledSourceError(
                "artifact must be a TamarinControlledSourceArtifact"
            )
        outcomes = parse_tamarin_claim_outcomes(
            stdout,
            stderr,
            claim_lemmas=artifact.claim_lemmas.to_dict(),
        )
        status, quarantine, accepted = classify_claim_outcomes(outcomes)
        translation = (
            EvidenceAuthority.BOUNDED
            if status in {ResultStatus.SECURE, ResultStatus.ATTACK_FOUND}
            else EvidenceAuthority.NONE
        )
        # Attack traces from Tamarin are not an independent proof route by
        # themselves; callers must set independently_replayable + replay_route.
        return TamarinSymbolicResult(
            status=status,
            authority=ResultAuthority.PROTOCOL,
            claim_outcomes=outcomes,
            ceiling=artifact.ceiling,
            source_digest=artifact.source_digest,
            equational_theories=artifact.equational_theories,
            adversary_kind=artifact.adversary_kind,
            accepted=accepted,
            translation_ceiling=translation,
            tool_id=artifact.tool_id,
            tool_version=artifact.tool_version,
            profile_id=artifact.profile_id,
            independently_replayable=independently_replayable,
            replay_route=replay_route,
            symbolic_model=True,
            computational_soundness=False,
            quarantine=quarantine.to_dict() if quarantine is not None else None,
            diagnostics=tuple(
                filter(
                    None,
                    (quarantine.detail if quarantine is not None else "",),
                )
            ),
            event_fact_provenance=artifact.event_fact_provenance,
        )


# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------


class TamarinProtocolMappings:
    """Facade combining ProtocolRewritingAdapter@1 and TamarinControlledSource@1."""

    interface_rewriting: ClassVar[str] = PROTOCOL_REWRITING_ADAPTER_INTERFACE
    interface_source: ClassVar[str] = TAMARIN_CONTROLLED_SOURCE_INTERFACE
    notation_id: ClassVar[str] = TAMARIN_NOTATION_ID
    notation_version: ClassVar[str] = TAMARIN_NOTATION_VERSION
    profile_id: ClassVar[str] = TAMARIN_PROFILE_ID
    family_id: ClassVar[str] = TAMARIN_FAMILY_ID

    def __init__(
        self,
        *,
        tool_id: str = DEFAULT_TOOL_ID,
        tool_version: str = DEFAULT_TOOL_VERSION,
    ) -> None:
        self.rewriting = ProtocolRewritingAdapter()
        self.tamarin = TamarinControlledSource(
            tool_id=tool_id,
            tool_version=tool_version,
            rewriting=self.rewriting,
        )

    def parse(
        self, value: Mapping[str, Any] | str | ProtocolIR
    ) -> ProtocolRewritingDocument:
        return self.rewriting.parse(value)

    def elaborate(self, document: ProtocolRewritingDocument) -> ProtocolIR:
        return self.rewriting.elaborate(document)

    def lower_to_tamarin(
        self,
        document: ProtocolRewritingDocument | ProtocolIR | Mapping[str, Any],
        *,
        tool_version: str | None = None,
    ) -> TamarinControlledSourceArtifact:
        return self.tamarin.lower(document, tool_version=tool_version)

    def interpret_tamarin(
        self,
        *,
        stdout: str,
        stderr: str = "",
        artifact: TamarinControlledSourceArtifact,
        independently_replayable: bool = False,
        replay_route: str = "",
    ) -> TamarinSymbolicResult:
        return self.tamarin.interpret_results(
            stdout=stdout,
            stderr=stderr,
            artifact=artifact,
            independently_replayable=independently_replayable,
            replay_route=replay_route,
        )


def parse_protocol_rewriting(
    value: Mapping[str, Any] | str | ProtocolIR,
) -> ProtocolRewritingDocument:
    """Parse a multiset-rewriting protocol document."""

    return ProtocolRewritingAdapter().parse(value)


def lower_to_tamarin(
    value: ProtocolRewritingDocument | ProtocolIR | Mapping[str, Any],
    *,
    tool_version: str = DEFAULT_TOOL_VERSION,
) -> TamarinControlledSourceArtifact:
    """Lower a rewriting/protocol document to controlled Tamarin source."""

    return TamarinControlledSource(tool_version=tool_version).lower(
        value, tool_version=tool_version
    )


def interpret_tamarin_results(
    *,
    stdout: str,
    stderr: str = "",
    artifact: TamarinControlledSourceArtifact,
    independently_replayable: bool = False,
    replay_route: str = "",
) -> TamarinSymbolicResult:
    """Interpret Tamarin output as a tool/version/profile-bound symbolic result."""

    return TamarinControlledSource(
        tool_id=artifact.tool_id,
        tool_version=artifact.tool_version,
    ).interpret_results(
        stdout=stdout,
        stderr=stderr,
        artifact=artifact,
        independently_replayable=independently_replayable,
        replay_route=replay_route,
    )


__all__ = [
    "CODE_PROVENANCE",
    "CODE_RESULT_AUTHORITY",
    "CODE_UNSUPPORTED_RULE",
    "CODE_UNSUPPORTED_THEORY",
    "DEFAULT_TOOL_ID",
    "DEFAULT_TOOL_VERSION",
    "FactKind",
    "FactMultiplicity",
    "LemmaQuantifier",
    "MultisetFact",
    "MultisetRule",
    "PROTOCOL_REWRITING_ADAPTER_INTERFACE",
    "ProtocolRewritingAdapter",
    "ProtocolRewritingDocument",
    "Restriction",
    "TAMARIN_CONTROLLED_CLAIMS",
    "TAMARIN_CONTROLLED_SOURCE_INTERFACE",
    "TAMARIN_CONTROLLED_THEORIES",
    "TAMARIN_FAMILY_ID",
    "TAMARIN_PROFILE_ID",
    "TamarinControlledSource",
    "TamarinControlledSourceArtifact",
    "TamarinControlledSourceError",
    "TamarinMappingError",
    "TamarinProtocolMappings",
    "TamarinSymbolicResult",
    "TraceLemma",
    "UNSUPPORTED_RULE_FEATURES",
    "UNSUPPORTED_THEORY_FEATURES",
    "interpret_tamarin_results",
    "lower_to_tamarin",
    "parse_protocol_rewriting",
]
