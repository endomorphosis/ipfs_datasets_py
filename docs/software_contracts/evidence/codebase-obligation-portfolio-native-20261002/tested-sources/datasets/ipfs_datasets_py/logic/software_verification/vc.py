"""Weakest-precondition calculus and verification-condition generation.

``VerificationConditionGenerator@1`` produces source-bound obligations from a
closed :class:`ProgramIR` together with its :class:`ProgramContract` and any
:class:`LoopContract` annotations.  Obligations are descriptive proof targets:
they bind a source construct, path assumptions, generated symbols, WP/VC rule,
and parent contract.  They do not execute solvers and they do not claim proof
authority.

Unsupported effects (I/O, synchronization, nondeterminism, or unframed
writes) remain explicit records rather than being silently dropped.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity

from .contracts import (
    ContractValidationError,
    LoopContract,
    ProgramContract,
)
from .program import (
    CommandKind,
    ControlFlowEdge,
    EdgeKind,
    EffectSummary,
    ProgramCommand,
    ProgramFunction,
    ProgramIR,
    ProgramValidationError,
    _enum,
    _frozen,
    _identifier,
    _ids,
    _mapping,
    _source_map,
    _text,
)

VERIFICATION_CONDITION_GENERATOR_INTERFACE: Final = "VerificationConditionGenerator@1"
VC_SCHEMA_VERSION: Final = "verification-condition/v1"
VC_SET_SCHEMA_VERSION: Final = "verification-condition-set/v1"
VC_IDENTITY_DOMAIN: Final = "logic.software-verification.vc"


class VCValidationError(ValueError):
    """Raised when VC generation inputs or results are incomplete."""


class VCRuleKind(str, Enum):
    """Dijkstra-style WP/VC rule applied to produce an obligation."""

    SKIP = "skip"
    ASSIGN = "assign"
    ASSUME = "assume"
    ASSERT = "assert"
    HAVOC = "havoc"
    CALL = "call"
    RETURN = "return"
    THROW = "throw"
    ALLOCATE = "allocate"
    DEALLOCATE = "deallocate"
    ATOMIC = "atomic"
    UNDEFINED = "undefined"
    BRANCH_TRUE = "branch_true"
    BRANCH_FALSE = "branch_false"
    PRECONDITION = "precondition"
    POSTCONDITION_NORMAL = "postcondition_normal"
    POSTCONDITION_EXCEPTIONAL = "postcondition_exceptional"
    FRAME = "frame"
    RESOURCE = "resource"
    LOOP_INVARIANT_INIT = "loop_invariant_init"
    LOOP_INVARIANT_PRESERVE = "loop_invariant_preserve"
    LOOP_VARIANT_DECREASE = "loop_variant_decrease"
    LOOP_VARIANT_BOUNDED = "loop_variant_bounded"
    UNSUPPORTED_EFFECT = "unsupported_effect"


class SourceConstructKind(str, Enum):
    """Program construct that an obligation is bound to."""

    COMMAND = "command"
    EDGE = "edge"
    BLOCK = "block"
    LOOP = "loop"
    FUNCTION = "function"
    CONTRACT = "contract"
    FRAME = "frame"
    RESOURCE = "resource"
    EXCEPTION = "exception"


class LoopVariantPolicy(str, Enum):
    """Whether a loop requires a well-founded variant.

    * ``NONE`` — partial correctness only; variants are forbidden.
    * ``REQUIRED`` — total correctness; at least one variant is mandatory.
    * ``OPTIONAL`` — variants may be supplied but are not required.
    """

    NONE = "none"
    REQUIRED = "required"
    OPTIONAL = "optional"


class UnsupportedEffectKind(str, Enum):
    """Effect classes that the WP calculus cannot discharge silently."""

    PERFORMS_IO = "performs_io"
    SYNCHRONIZES = "synchronizes"
    NONDETERMINISTIC = "nondeterministic"
    UNFRAMED_WRITE = "unframed_write"
    UNFRAMED_ALLOCATION = "unframed_allocation"
    UNFRAMED_DEALLOCATION = "unframed_deallocation"
    UNMODELED_CALL = "unmodeled_call"
    UNDEFINED_BEHAVIOR = "undefined_behavior"


def _vc_text(value: object, label: str) -> str:
    try:
        return _text(value, label)
    except ProgramValidationError as error:
        raise VCValidationError(str(error)) from error


def _vc_identifier(value: object, label: str) -> str:
    try:
        return _identifier(value, label)
    except ProgramValidationError as error:
        raise VCValidationError(str(error)) from error


def _vc_ids(
    values: Sequence[str],
    label: str,
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    try:
        return _ids(values, label, preserve_order=preserve_order)
    except ProgramValidationError as error:
        raise VCValidationError(str(error)) from error


def _unique_preserve(values: Sequence[str]) -> tuple[str, ...]:
    """Drop duplicate identifiers while retaining first-seen order."""

    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _vc_enum(value: object, enum_type: type[Enum], label: str) -> Any:
    try:
        return _enum(value, enum_type, label)
    except ProgramValidationError as error:
        raise VCValidationError(str(error)) from error


def _vc_source(
    source_ref_ids: Sequence[str],
    span_ids: Sequence[str],
    owner: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        return _source_map(source_ref_ids, span_ids, owner)
    except ProgramValidationError as error:
        raise VCValidationError(str(error)) from error


def _vc_frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return _frozen(value, label)
    except ProgramValidationError as error:
        raise VCValidationError(str(error)) from error


def _stable_obligation_id(
    *,
    rule: VCRuleKind,
    construct_kind: SourceConstructKind,
    construct_id: str,
    parent_contract_id: str,
    suffix: str = "",
) -> str:
    base = f"vc:{rule.value}:{construct_kind.value}:{construct_id}:{parent_contract_id}"
    if suffix:
        base = f"{base}:{suffix}"
    # Keep identifiers within the stable id grammar without hashing every field.
    cleaned = re.sub(r"[^A-Za-z0-9._:/-]+", "-", base)
    if len(cleaned) > 255:
        cleaned = cleaned[:255]
    return cleaned


@dataclass(frozen=True, slots=True)
class GeneratedSymbol:
    """A fresh or havoced symbol introduced by WP rewriting."""

    symbol_id: str
    origin_symbol_id: str
    rule: VCRuleKind | str
    construct_id: str
    reason: str
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol_id", _vc_identifier(self.symbol_id, "symbol_id"))
        object.__setattr__(
            self,
            "origin_symbol_id",
            _vc_identifier(self.origin_symbol_id, "origin_symbol_id"),
        )
        object.__setattr__(self, "rule", _vc_enum(self.rule, VCRuleKind, "rule"))
        object.__setattr__(
            self,
            "construct_id",
            _vc_identifier(self.construct_id, "construct_id"),
        )
        object.__setattr__(self, "reason", _vc_text(self.reason, "reason"))
        object.__setattr__(self, "attributes", _vc_frozen(self.attributes, "attributes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "construct_id": self.construct_id,
            "origin_symbol_id": self.origin_symbol_id,
            "reason": self.reason,
            "rule": self.rule.value,
            "symbol_id": self.symbol_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GeneratedSymbol":
        return cls(
            symbol_id=value.get("symbol_id", ""),
            origin_symbol_id=value.get("origin_symbol_id", ""),
            rule=value.get("rule", ""),
            construct_id=value.get("construct_id", ""),
            reason=value.get("reason", ""),
            attributes=_vc_frozen(
                _mapping(value.get("attributes", {}), "attributes"),
                "attributes",
            ),
        )


@dataclass(frozen=True, slots=True)
class UnsupportedEffect:
    """An effect that VC generation refuses to treat as discharged."""

    effect_id: str
    kind: UnsupportedEffectKind | str
    construct_kind: SourceConstructKind | str
    construct_id: str
    description: str
    symbol_ids: tuple[str, ...] = ()
    parent_contract_id: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _vc_identifier(self.effect_id, "effect_id"))
        object.__setattr__(self, "kind", _vc_enum(self.kind, UnsupportedEffectKind, "kind"))
        object.__setattr__(
            self,
            "construct_kind",
            _vc_enum(self.construct_kind, SourceConstructKind, "construct_kind"),
        )
        object.__setattr__(
            self,
            "construct_id",
            _vc_identifier(self.construct_id, "construct_id"),
        )
        object.__setattr__(self, "description", _vc_text(self.description, "description"))
        object.__setattr__(self, "symbol_ids", _vc_ids(self.symbol_ids, "symbol_ids"))
        parent = self.parent_contract_id
        if parent:
            parent = _vc_identifier(parent, "parent_contract_id")
        object.__setattr__(self, "parent_contract_id", parent)
        object.__setattr__(self, "attributes", _vc_frozen(self.attributes, "attributes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "construct_id": self.construct_id,
            "construct_kind": self.construct_kind.value,
            "description": self.description,
            "effect_id": self.effect_id,
            "kind": self.kind.value,
            "parent_contract_id": self.parent_contract_id,
            "symbol_ids": list(self.symbol_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnsupportedEffect":
        return cls(
            effect_id=value.get("effect_id", ""),
            kind=value.get("kind", ""),
            construct_kind=value.get("construct_kind", ""),
            construct_id=value.get("construct_id", ""),
            description=value.get("description", ""),
            symbol_ids=tuple(value.get("symbol_ids", ())),
            parent_contract_id=value.get("parent_contract_id", ""),
            attributes=_vc_frozen(
                _mapping(value.get("attributes", {}), "attributes"),
                "attributes",
            ),
        )


@dataclass(frozen=True, slots=True)
class VerificationObligation:
    """One source-bound weakest-precondition / verification-condition target.

    Every obligation must bind:
    * the WP/VC ``rule`` that produced it;
    * the ``source_construct`` that justifies it;
    * path ``assumption_expression_ids``;
    * any ``generated_symbol_ids`` introduced by rewriting;
    * the ``parent_contract_id`` whose clauses are being established.
    """

    obligation_id: str
    rule: VCRuleKind | str
    parent_contract_id: str
    function_id: str
    source_construct_kind: SourceConstructKind | str
    source_construct_id: str
    assumption_expression_ids: tuple[str, ...] = ()
    goal_expression_ids: tuple[str, ...] = ()
    generated_symbol_ids: tuple[str, ...] = ()
    path_condition_expression_ids: tuple[str, ...] = ()
    statement: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _vc_source(
            self.source_ref_ids, self.span_ids, "VerificationObligation"
        )
        object.__setattr__(
            self, "obligation_id", _vc_identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(self, "rule", _vc_enum(self.rule, VCRuleKind, "rule"))
        object.__setattr__(
            self,
            "parent_contract_id",
            _vc_identifier(self.parent_contract_id, "parent_contract_id"),
        )
        object.__setattr__(
            self, "function_id", _vc_identifier(self.function_id, "function_id")
        )
        object.__setattr__(
            self,
            "source_construct_kind",
            _vc_enum(self.source_construct_kind, SourceConstructKind, "source_construct_kind"),
        )
        object.__setattr__(
            self,
            "source_construct_id",
            _vc_identifier(self.source_construct_id, "source_construct_id"),
        )
        object.__setattr__(
            self,
            "assumption_expression_ids",
            _vc_ids(
                self.assumption_expression_ids,
                "assumption_expression_ids",
                preserve_order=True,
            ),
        )
        object.__setattr__(
            self,
            "goal_expression_ids",
            _vc_ids(
                self.goal_expression_ids,
                "goal_expression_ids",
                preserve_order=True,
            ),
        )
        object.__setattr__(
            self,
            "generated_symbol_ids",
            _vc_ids(self.generated_symbol_ids, "generated_symbol_ids"),
        )
        object.__setattr__(
            self,
            "path_condition_expression_ids",
            _vc_ids(
                self.path_condition_expression_ids,
                "path_condition_expression_ids",
                preserve_order=True,
            ),
        )
        statement = self.statement
        if statement:
            statement = _vc_text(statement, "statement")
        object.__setattr__(self, "statement", statement)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        object.__setattr__(self, "attributes", _vc_frozen(self.attributes, "attributes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_expression_ids": list(self.assumption_expression_ids),
            "attributes": self.attributes.to_dict(),
            "function_id": self.function_id,
            "generated_symbol_ids": list(self.generated_symbol_ids),
            "goal_expression_ids": list(self.goal_expression_ids),
            "obligation_id": self.obligation_id,
            "parent_contract_id": self.parent_contract_id,
            "path_condition_expression_ids": list(self.path_condition_expression_ids),
            "rule": self.rule.value,
            "source_construct_id": self.source_construct_id,
            "source_construct_kind": self.source_construct_kind.value,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationObligation":
        return cls(
            obligation_id=value.get("obligation_id", ""),
            rule=value.get("rule", ""),
            parent_contract_id=value.get("parent_contract_id", ""),
            function_id=value.get("function_id", ""),
            source_construct_kind=value.get("source_construct_kind", ""),
            source_construct_id=value.get("source_construct_id", ""),
            assumption_expression_ids=tuple(value.get("assumption_expression_ids", ())),
            goal_expression_ids=tuple(value.get("goal_expression_ids", ())),
            generated_symbol_ids=tuple(value.get("generated_symbol_ids", ())),
            path_condition_expression_ids=tuple(
                value.get("path_condition_expression_ids", ())
            ),
            statement=value.get("statement", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_vc_frozen(
                _mapping(value.get("attributes", {}), "attributes"),
                "attributes",
            ),
        )


@dataclass(frozen=True, slots=True)
class WeakestPrecondition:
    """WP formula attached to a command or block exit channel."""

    wp_id: str
    function_id: str
    program_point_kind: SourceConstructKind | str
    program_point_id: str
    exit_kind: str
    assumption_expression_ids: tuple[str, ...] = ()
    consequent_expression_ids: tuple[str, ...] = ()
    rule: VCRuleKind | str = VCRuleKind.SKIP
    parent_contract_id: str = ""
    generated_symbol_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _vc_source(self.source_ref_ids, self.span_ids, "WeakestPrecondition")
        object.__setattr__(self, "wp_id", _vc_identifier(self.wp_id, "wp_id"))
        object.__setattr__(
            self, "function_id", _vc_identifier(self.function_id, "function_id")
        )
        object.__setattr__(
            self,
            "program_point_kind",
            _vc_enum(self.program_point_kind, SourceConstructKind, "program_point_kind"),
        )
        object.__setattr__(
            self,
            "program_point_id",
            _vc_identifier(self.program_point_id, "program_point_id"),
        )
        object.__setattr__(self, "exit_kind", _vc_text(self.exit_kind, "exit_kind"))
        object.__setattr__(
            self,
            "assumption_expression_ids",
            _vc_ids(
                self.assumption_expression_ids,
                "assumption_expression_ids",
                preserve_order=True,
            ),
        )
        object.__setattr__(
            self,
            "consequent_expression_ids",
            _vc_ids(
                self.consequent_expression_ids,
                "consequent_expression_ids",
                preserve_order=True,
            ),
        )
        object.__setattr__(self, "rule", _vc_enum(self.rule, VCRuleKind, "rule"))
        parent = self.parent_contract_id
        if parent:
            parent = _vc_identifier(parent, "parent_contract_id")
        object.__setattr__(self, "parent_contract_id", parent)
        object.__setattr__(
            self,
            "generated_symbol_ids",
            _vc_ids(self.generated_symbol_ids, "generated_symbol_ids"),
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        object.__setattr__(self, "attributes", _vc_frozen(self.attributes, "attributes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_expression_ids": list(self.assumption_expression_ids),
            "attributes": self.attributes.to_dict(),
            "consequent_expression_ids": list(self.consequent_expression_ids),
            "exit_kind": self.exit_kind,
            "function_id": self.function_id,
            "generated_symbol_ids": list(self.generated_symbol_ids),
            "parent_contract_id": self.parent_contract_id,
            "program_point_id": self.program_point_id,
            "program_point_kind": self.program_point_kind.value,
            "rule": self.rule.value,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "wp_id": self.wp_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WeakestPrecondition":
        return cls(
            wp_id=value.get("wp_id", ""),
            function_id=value.get("function_id", ""),
            program_point_kind=value.get("program_point_kind", ""),
            program_point_id=value.get("program_point_id", ""),
            exit_kind=value.get("exit_kind", ""),
            assumption_expression_ids=tuple(value.get("assumption_expression_ids", ())),
            consequent_expression_ids=tuple(value.get("consequent_expression_ids", ())),
            rule=value.get("rule", VCRuleKind.SKIP.value),
            parent_contract_id=value.get("parent_contract_id", ""),
            generated_symbol_ids=tuple(value.get("generated_symbol_ids", ())),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_vc_frozen(
                _mapping(value.get("attributes", {}), "attributes"),
                "attributes",
            ),
        )


@dataclass(frozen=True, slots=True)
class VerificationConditionSet:
    """Content-addressed collection of VCs for one contracted function."""

    INTERFACE: ClassVar[str] = VERIFICATION_CONDITION_GENERATOR_INTERFACE

    program_id: str
    function_id: str
    parent_contract_id: str
    obligations: tuple[VerificationObligation, ...]
    weakest_preconditions: tuple[WeakestPrecondition, ...] = ()
    generated_symbols: tuple[GeneratedSymbol, ...] = ()
    unsupported_effects: tuple[UnsupportedEffect, ...] = ()
    loop_variant_policy: LoopVariantPolicy | str = LoopVariantPolicy.OPTIONAL
    attributes: FrozenMap = field(default_factory=FrozenMap)
    vc_set_id: str = ""
    schema_version: str = VC_SET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        obligations = tuple(
            item
            if isinstance(item, VerificationObligation)
            else VerificationObligation.from_dict(_mapping(item, "obligation"))
            for item in self.obligations
        )
        wps = tuple(
            item
            if isinstance(item, WeakestPrecondition)
            else WeakestPrecondition.from_dict(_mapping(item, "weakest_precondition"))
            for item in self.weakest_preconditions
        )
        generated = tuple(
            item
            if isinstance(item, GeneratedSymbol)
            else GeneratedSymbol.from_dict(_mapping(item, "generated_symbol"))
            for item in self.generated_symbols
        )
        unsupported = tuple(
            item
            if isinstance(item, UnsupportedEffect)
            else UnsupportedEffect.from_dict(_mapping(item, "unsupported_effect"))
            for item in self.unsupported_effects
        )
        obligation_ids = [item.obligation_id for item in obligations]
        if len(obligation_ids) != len(set(obligation_ids)):
            raise VCValidationError("duplicate verification-obligation identifiers")
        wp_ids = [item.wp_id for item in wps]
        if len(wp_ids) != len(set(wp_ids)):
            raise VCValidationError("duplicate weakest-precondition identifiers")
        generated_ids = [item.symbol_id for item in generated]
        if len(generated_ids) != len(set(generated_ids)):
            raise VCValidationError("duplicate generated-symbol identifiers")
        effect_ids = [item.effect_id for item in unsupported]
        if len(effect_ids) != len(set(effect_ids)):
            raise VCValidationError("duplicate unsupported-effect identifiers")
        policy = _vc_enum(self.loop_variant_policy, LoopVariantPolicy, "loop_variant_policy")
        if self.schema_version != VC_SET_SCHEMA_VERSION:
            raise VCValidationError(f"unsupported schema_version {self.schema_version!r}")
        object.__setattr__(self, "program_id", _vc_identifier(self.program_id, "program_id"))
        object.__setattr__(
            self, "function_id", _vc_identifier(self.function_id, "function_id")
        )
        object.__setattr__(
            self,
            "parent_contract_id",
            _vc_identifier(self.parent_contract_id, "parent_contract_id"),
        )
        object.__setattr__(
            self,
            "obligations",
            tuple(sorted(obligations, key=lambda item: item.obligation_id)),
        )
        object.__setattr__(
            self,
            "weakest_preconditions",
            tuple(sorted(wps, key=lambda item: item.wp_id)),
        )
        object.__setattr__(
            self,
            "generated_symbols",
            tuple(sorted(generated, key=lambda item: item.symbol_id)),
        )
        object.__setattr__(
            self,
            "unsupported_effects",
            tuple(sorted(unsupported, key=lambda item: item.effect_id)),
        )
        object.__setattr__(self, "loop_variant_policy", policy)
        object.__setattr__(self, "attributes", _vc_frozen(self.attributes, "attributes"))
        identity = self._compute_identity()
        if self.vc_set_id and self.vc_set_id != identity.cid:
            raise VCValidationError("vc_set_id does not match canonical VC semantics")
        object.__setattr__(self, "vc_set_id", identity.cid)

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=VC_IDENTITY_DOMAIN,
            schema_version=VC_SET_SCHEMA_VERSION,
        )

    def obligations_by_rule(self, rule: VCRuleKind | str) -> tuple[VerificationObligation, ...]:
        kind = _vc_enum(rule, VCRuleKind, "rule")
        return tuple(item for item in self.obligations if item.rule is kind)

    def branch_edge_ids(self) -> frozenset[str]:
        return frozenset(
            item.source_construct_id
            for item in self.obligations
            if item.rule in {VCRuleKind.BRANCH_TRUE, VCRuleKind.BRANCH_FALSE}
            and item.source_construct_kind is SourceConstructKind.EDGE
        )

    def frame_construct_ids(self) -> frozenset[str]:
        return frozenset(
            item.source_construct_id
            for item in self.obligations
            if item.rule is VCRuleKind.FRAME
        )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "function_id": self.function_id,
            "generated_symbols": [
                item.to_dict()
                for item in sorted(self.generated_symbols, key=lambda item: item.symbol_id)
            ],
            "interface": self.INTERFACE,
            "loop_variant_policy": self.loop_variant_policy.value,
            "obligations": [
                item.to_dict()
                for item in sorted(self.obligations, key=lambda item: item.obligation_id)
            ],
            "parent_contract_id": self.parent_contract_id,
            "program_id": self.program_id,
            "schema_version": self.schema_version,
            "unsupported_effects": [
                item.to_dict()
                for item in sorted(self.unsupported_effects, key=lambda item: item.effect_id)
            ],
            "weakest_preconditions": [
                item.to_dict()
                for item in sorted(self.weakest_preconditions, key=lambda item: item.wp_id)
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        value = self.semantic_dict()
        value["vc_set_id"] = self.vc_set_id
        return value

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationConditionSet":
        interface = value.get("interface", VERIFICATION_CONDITION_GENERATOR_INTERFACE)
        if interface != VERIFICATION_CONDITION_GENERATOR_INTERFACE:
            raise VCValidationError(
                f"unsupported interface {interface!r}; expected "
                f"{VERIFICATION_CONDITION_GENERATOR_INTERFACE}"
            )
        return cls(
            program_id=value.get("program_id", ""),
            function_id=value.get("function_id", ""),
            parent_contract_id=value.get("parent_contract_id", ""),
            obligations=tuple(
                VerificationObligation.from_dict(_mapping(item, "obligation"))
                for item in value.get("obligations", ())
            ),
            weakest_preconditions=tuple(
                WeakestPrecondition.from_dict(_mapping(item, "weakest_precondition"))
                for item in value.get("weakest_preconditions", ())
            ),
            generated_symbols=tuple(
                GeneratedSymbol.from_dict(_mapping(item, "generated_symbol"))
                for item in value.get("generated_symbols", ())
            ),
            unsupported_effects=tuple(
                UnsupportedEffect.from_dict(_mapping(item, "unsupported_effect"))
                for item in value.get("unsupported_effects", ())
            ),
            loop_variant_policy=value.get(
                "loop_variant_policy", LoopVariantPolicy.OPTIONAL.value
            ),
            attributes=_vc_frozen(
                _mapping(value.get("attributes", {}), "attributes"),
                "attributes",
            ),
            vc_set_id=value.get("vc_set_id", ""),
            schema_version=value.get("schema_version", VC_SET_SCHEMA_VERSION),
        )

    def without_rules(self, *rules: VCRuleKind | str) -> "VerificationConditionSet":
        """Return a mutated copy with selected obligation rules dropped.

        Used by mutation tests that detect incomplete VC coverage.
        """

        drop = {_vc_enum(rule, VCRuleKind, "rule") for rule in rules}
        return VerificationConditionSet(
            program_id=self.program_id,
            function_id=self.function_id,
            parent_contract_id=self.parent_contract_id,
            obligations=tuple(item for item in self.obligations if item.rule not in drop),
            weakest_preconditions=self.weakest_preconditions,
            generated_symbols=self.generated_symbols,
            unsupported_effects=self.unsupported_effects,
            loop_variant_policy=self.loop_variant_policy,
            attributes=self.attributes,
            vc_set_id="",
            schema_version=self.schema_version,
        )


@dataclass(frozen=True, slots=True)
class VerificationConditionGenerator:
    """Generate source-bound WP/VC obligations (``VerificationConditionGenerator@1``)."""

    INTERFACE: ClassVar[str] = VERIFICATION_CONDITION_GENERATOR_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = VC_SCHEMA_VERSION

    loop_variant_policy: LoopVariantPolicy | str = LoopVariantPolicy.OPTIONAL
    require_source_maps: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "loop_variant_policy",
            _vc_enum(self.loop_variant_policy, LoopVariantPolicy, "loop_variant_policy"),
        )
        if not isinstance(self.require_source_maps, bool):
            raise VCValidationError("require_source_maps must be boolean")

    def generate(
        self,
        program: ProgramIR,
        contract: ProgramContract,
        loop_contracts: Sequence[LoopContract] = (),
    ) -> VerificationConditionSet:
        """Emit VCs for ``contract`` against the closed ``program`` document."""

        if not isinstance(program, ProgramIR):
            raise VCValidationError("program must be a ProgramIR instance")
        if not isinstance(contract, ProgramContract):
            raise VCValidationError("contract must be a ProgramContract instance")
        loops = tuple(
            item
            if isinstance(item, LoopContract)
            else LoopContract.from_dict(_mapping(item, "loop_contract"))
            for item in loop_contracts
        )
        try:
            contract.validate_against(program)
            for loop in loops:
                loop.validate_against(program)
        except ContractValidationError as error:
            raise VCValidationError(str(error)) from error

        functions = {item.function_id: item for item in program.functions}
        function = functions[contract.function_id]
        if any(loop.function_id != contract.function_id for loop in loops):
            raise VCValidationError("loop contracts must target the contracted function")

        self._enforce_loop_variant_policy(loops)

        commands = {item.command_id: item for item in program.commands}
        obligations: list[VerificationObligation] = []
        weakest: list[WeakestPrecondition] = []
        generated: list[GeneratedSymbol] = []
        unsupported: list[UnsupportedEffect] = []

        pre_ids = tuple(item.expression_id for item in contract.preconditions)
        post_ids = tuple(item.expression_id for item in contract.postconditions)
        exceptional_by_type = {
            item.exception_type: item.expression_id
            for item in contract.exceptional_postconditions
        }

        # Entry: preconditions are assumed at the function boundary.
        if pre_ids:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.PRECONDITION,
                    construct_kind=SourceConstructKind.CONTRACT,
                    construct_id=contract.contract_id,
                    contract=contract,
                    function=function,
                    assumptions=(),
                    goals=pre_ids,
                    path=pre_ids,
                    statement=(
                        f"Entry of {function.function_id} assumes contract "
                        f"{contract.contract_id} preconditions."
                    ),
                    source_ref_ids=contract.source_ref_ids,
                    span_ids=contract.span_ids,
                )
            )
            weakest.append(
                WeakestPrecondition(
                    wp_id=f"wp:entry:{function.function_id}",
                    function_id=function.function_id,
                    program_point_kind=SourceConstructKind.FUNCTION,
                    program_point_id=function.function_id,
                    exit_kind="entry",
                    assumption_expression_ids=pre_ids,
                    consequent_expression_ids=pre_ids,
                    rule=VCRuleKind.PRECONDITION,
                    parent_contract_id=contract.contract_id,
                    source_ref_ids=function.source_ref_ids,
                    span_ids=function.span_ids,
                )
            )

        # Normal exits establish postconditions under path conditions.
        for block_id in function.cfg.normal_exit_block_ids:
            block = next(item for item in function.cfg.blocks if item.block_id == block_id)
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.POSTCONDITION_NORMAL,
                    construct_kind=SourceConstructKind.BLOCK,
                    construct_id=block_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=post_ids or pre_ids,
                    path=pre_ids,
                    statement=(
                        f"Normal exit block {block_id} must establish postconditions "
                        f"of {contract.contract_id}."
                    ),
                    source_ref_ids=block.source_ref_ids or function.source_ref_ids,
                    span_ids=block.span_ids or function.span_ids,
                    suffix="normal",
                )
            )
            weakest.append(
                WeakestPrecondition(
                    wp_id=f"wp:exit-normal:{block_id}",
                    function_id=function.function_id,
                    program_point_kind=SourceConstructKind.BLOCK,
                    program_point_id=block_id,
                    exit_kind="normal",
                    assumption_expression_ids=pre_ids,
                    consequent_expression_ids=post_ids or pre_ids,
                    rule=VCRuleKind.POSTCONDITION_NORMAL,
                    parent_contract_id=contract.contract_id,
                    source_ref_ids=block.source_ref_ids or function.source_ref_ids,
                    span_ids=block.span_ids or function.span_ids,
                )
            )

        # Exceptional exits establish matching exceptional postconditions.
        for block_id in function.cfg.exceptional_exit_block_ids:
            block = next(item for item in function.cfg.blocks if item.block_id == block_id)
            raised = self._block_raised_types(block, commands)
            for exception_type in raised or sorted(exceptional_by_type):
                goal = exceptional_by_type.get(exception_type)
                if goal is None:
                    unsupported.append(
                        UnsupportedEffect(
                            effect_id=(
                                f"unsupported:exception:{block_id}:{exception_type}"
                            ),
                            kind=UnsupportedEffectKind.UNMODELED_CALL,
                            construct_kind=SourceConstructKind.EXCEPTION,
                            construct_id=block_id,
                            description=(
                                f"Exceptional exit {block_id} raises {exception_type} "
                                "without a contract exceptional postcondition."
                            ),
                            parent_contract_id=contract.contract_id,
                        )
                    )
                    continue
                obligations.append(
                    self._obligation(
                        rule=VCRuleKind.POSTCONDITION_EXCEPTIONAL,
                        construct_kind=SourceConstructKind.EXCEPTION,
                        construct_id=block_id,
                        contract=contract,
                        function=function,
                        assumptions=pre_ids,
                        goals=(goal,),
                        path=pre_ids,
                        statement=(
                            f"Exceptional exit {block_id} for {exception_type} must "
                            f"establish the exceptional postcondition of "
                            f"{contract.contract_id}."
                        ),
                        source_ref_ids=block.source_ref_ids or function.source_ref_ids,
                        span_ids=block.span_ids or function.span_ids,
                        suffix=exception_type,
                        attributes={"exception_type": exception_type},
                    )
                )

        # Branch edges contribute independent true/false obligations.
        for edge in function.cfg.edges:
            if edge.kind is EdgeKind.TRUE:
                obligations.append(
                    self._branch_obligation(
                        edge=edge,
                        rule=VCRuleKind.BRANCH_TRUE,
                        contract=contract,
                        function=function,
                        pre_ids=pre_ids,
                        polarity=True,
                    )
                )
            elif edge.kind is EdgeKind.FALSE:
                obligations.append(
                    self._branch_obligation(
                        edge=edge,
                        rule=VCRuleKind.BRANCH_FALSE,
                        contract=contract,
                        function=function,
                        pre_ids=pre_ids,
                        polarity=False,
                    )
                )
            elif edge.kind is EdgeKind.EXCEPTION and edge.exception_type:
                goal = exceptional_by_type.get(edge.exception_type)
                if goal is not None:
                    obligations.append(
                        self._obligation(
                            rule=VCRuleKind.POSTCONDITION_EXCEPTIONAL,
                            construct_kind=SourceConstructKind.EDGE,
                            construct_id=edge.edge_id,
                            contract=contract,
                            function=function,
                            assumptions=pre_ids,
                            goals=(goal,),
                            path=pre_ids
                            + (
                                (edge.condition_expression_id,)
                                if edge.condition_expression_id
                                else ()
                            ),
                            statement=(
                                f"Exception edge {edge.edge_id} for "
                                f"{edge.exception_type} discharges the exceptional "
                                f"postcondition of {contract.contract_id}."
                            ),
                            source_ref_ids=function.source_ref_ids,
                            span_ids=function.span_ids,
                            suffix=edge.exception_type,
                            attributes={"exception_type": edge.exception_type},
                        )
                    )

        # Per-command WP rules, frames, resources, and unsupported effects.
        for command_id in function.cfg.command_ids:
            command = commands[command_id]
            cmd_obs, cmd_wp, cmd_gen, cmd_unsup = self._command_contributions(
                command=command,
                contract=contract,
                function=function,
                pre_ids=pre_ids,
                post_ids=post_ids,
            )
            obligations.extend(cmd_obs)
            weakest.extend(cmd_wp)
            generated.extend(cmd_gen)
            unsupported.extend(cmd_unsup)

        # Frame obligations for every write/alloc/dealloc in the contract frame.
        frame_obs = self._frame_obligations(contract=contract, function=function, pre_ids=pre_ids)
        obligations.extend(frame_obs)

        # Loop rules with explicit invariant / variant policy.
        for loop in loops:
            loop_obs, loop_unsup = self._loop_obligations(
                loop=loop,
                contract=contract,
                function=function,
                pre_ids=pre_ids,
            )
            obligations.extend(loop_obs)
            unsupported.extend(loop_unsup)

        # Function-level unsupported effects not localized to a command.
        unsupported.extend(
            self._function_level_unsupported(contract=contract, function=function)
        )

        if self.require_source_maps:
            for item in obligations:
                if not item.source_ref_ids and not item.span_ids:
                    raise VCValidationError(
                        f"obligation {item.obligation_id} is missing source maps"
                    )

        result = VerificationConditionSet(
            program_id=program.program_id,
            function_id=function.function_id,
            parent_contract_id=contract.contract_id,
            obligations=tuple(obligations),
            weakest_preconditions=tuple(weakest),
            generated_symbols=tuple(generated),
            unsupported_effects=tuple(unsupported),
            loop_variant_policy=self.loop_variant_policy,
            attributes={
                "generator_interface": self.INTERFACE,
                "generator_schema": self.SCHEMA_VERSION,
            },
        )
        self.validate_coverage(program, contract, result)
        return result

    def validate_coverage(
        self,
        program: ProgramIR,
        contract: ProgramContract,
        vc_set: VerificationConditionSet,
    ) -> None:
        """Fail closed when branch edges or frames lack obligations."""

        functions = {item.function_id: item for item in program.functions}
        function = functions[contract.function_id]
        branch_edges = {
            edge.edge_id
            for edge in function.cfg.edges
            if edge.kind in {EdgeKind.TRUE, EdgeKind.FALSE}
        }
        covered_branches = vc_set.branch_edge_ids()
        missing_branches = sorted(branch_edges - covered_branches)
        if missing_branches:
            raise VCValidationError(
                f"VC set is missing branch obligations for edges {missing_branches}"
            )

        frame_targets = set(contract.frame.writable_symbol_ids)
        if not contract.frame.allows_all_writes:
            modified = set(
                contract.effects.writes
                + contract.effects.allocates
                + contract.effects.deallocates
            )
            # Every non-wildcard write must have a frame obligation construct id.
            covered_frames = vc_set.frame_construct_ids()
            missing_frames = sorted(
                (frame_targets | modified)
                - covered_frames
                - set()  # explicit: symbols still need coverage via writable set
            )
            # Frame obligations are keyed by symbol id; require one per modified symbol.
            missing_modified = sorted(modified - covered_frames)
            if missing_modified and not contract.frame.allows_all_writes:
                raise VCValidationError(
                    f"VC set is missing frame obligations for symbols {missing_modified}"
                )

        if contract.postconditions and not vc_set.obligations_by_rule(
            VCRuleKind.POSTCONDITION_NORMAL
        ):
            raise VCValidationError("VC set is missing normal postcondition obligations")

    def _enforce_loop_variant_policy(self, loops: Sequence[LoopContract]) -> None:
        policy = self.loop_variant_policy
        for loop in loops:
            if policy is LoopVariantPolicy.REQUIRED:
                if not loop.variants and not loop.total_correctness:
                    raise VCValidationError(
                        f"loop {loop.loop_id} requires a variant under policy "
                        f"{policy.value}"
                    )
                if not loop.variants:
                    raise VCValidationError(
                        f"loop {loop.loop_id} requires at least one variant expression"
                    )
            if policy is LoopVariantPolicy.NONE and (loop.variants or loop.total_correctness):
                raise VCValidationError(
                    f"loop {loop.loop_id} supplies variants under policy {policy.value}"
                )
            if loop.total_correctness and not loop.variants:
                raise VCValidationError(
                    f"total-correctness loop {loop.loop_id} requires a variant"
                )

    def _obligation(
        self,
        *,
        rule: VCRuleKind,
        construct_kind: SourceConstructKind,
        construct_id: str,
        contract: ProgramContract,
        function: ProgramFunction,
        assumptions: Sequence[str],
        goals: Sequence[str],
        path: Sequence[str],
        statement: str,
        source_ref_ids: Sequence[str],
        span_ids: Sequence[str],
        generated_symbol_ids: Sequence[str] = (),
        suffix: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> VerificationObligation:
        return VerificationObligation(
            obligation_id=_stable_obligation_id(
                rule=rule,
                construct_kind=construct_kind,
                construct_id=construct_id,
                parent_contract_id=contract.contract_id,
                suffix=suffix,
            ),
            rule=rule,
            parent_contract_id=contract.contract_id,
            function_id=function.function_id,
            source_construct_kind=construct_kind,
            source_construct_id=construct_id,
            assumption_expression_ids=_unique_preserve(assumptions),
            goal_expression_ids=_unique_preserve(goals),
            generated_symbol_ids=tuple(generated_symbol_ids),
            path_condition_expression_ids=_unique_preserve(path),
            statement=statement,
            source_ref_ids=tuple(source_ref_ids),
            span_ids=tuple(span_ids),
            attributes=FrozenMap(attributes or {}),
        )

    def _branch_obligation(
        self,
        *,
        edge: ControlFlowEdge,
        rule: VCRuleKind,
        contract: ProgramContract,
        function: ProgramFunction,
        pre_ids: Sequence[str],
        polarity: bool,
    ) -> VerificationObligation:
        condition = edge.condition_expression_id
        polarity_label = "true" if polarity else "false"
        return self._obligation(
            rule=rule,
            construct_kind=SourceConstructKind.EDGE,
            construct_id=edge.edge_id,
            contract=contract,
            function=function,
            assumptions=tuple(pre_ids) + ((condition,) if condition else ()),
            goals=(condition,) if condition else tuple(pre_ids),
            path=tuple(pre_ids) + ((condition,) if condition else ()),
            statement=(
                f"Branch edge {edge.edge_id} ({polarity_label}) from "
                f"{edge.source_block_id} to {edge.target_block_id} contributes a "
                f"path condition under contract {contract.contract_id}."
            ),
            source_ref_ids=function.source_ref_ids,
            span_ids=function.span_ids,
            attributes={
                "polarity": polarity_label,
                "source_block_id": edge.source_block_id,
                "target_block_id": edge.target_block_id,
                "condition_expression_id": condition,
            },
        )

    def _command_contributions(
        self,
        *,
        command: ProgramCommand,
        contract: ProgramContract,
        function: ProgramFunction,
        pre_ids: Sequence[str],
        post_ids: Sequence[str],
    ) -> tuple[
        list[VerificationObligation],
        list[WeakestPrecondition],
        list[GeneratedSymbol],
        list[UnsupportedEffect],
    ]:
        obligations: list[VerificationObligation] = []
        weakest: list[WeakestPrecondition] = []
        generated: list[GeneratedSymbol] = []
        unsupported: list[UnsupportedEffect] = []
        kind = command.kind
        rule = self._rule_for_command(kind)
        sources = command.source_ref_ids or function.source_ref_ids
        spans = command.span_ids or function.span_ids
        expr_ids = command.expression_ids
        goals = expr_ids or post_ids or pre_ids

        if kind is CommandKind.ASSERT:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.ASSERT,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=expr_ids,
                    path=tuple(pre_ids) + tuple(expr_ids),
                    statement=(
                        f"Assert command {command.command_id} must hold under the "
                        f"path condition of {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                )
            )
        elif kind is CommandKind.ASSUME:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.ASSUME,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=tuple(pre_ids) + tuple(expr_ids),
                    goals=expr_ids,
                    path=tuple(pre_ids) + tuple(expr_ids),
                    statement=(
                        f"Assume command {command.command_id} strengthens the path "
                        f"condition for {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                )
            )
        elif kind is CommandKind.ASSIGN:
            for target in command.target_symbol_ids:
                gen_id = f"gen:{command.command_id}:{target}"
                generated.append(
                    GeneratedSymbol(
                        symbol_id=gen_id,
                        origin_symbol_id=target,
                        rule=VCRuleKind.ASSIGN,
                        construct_id=command.command_id,
                        reason="assignment substitution introduces a post-state value",
                    )
                )
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.ASSIGN,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Assignment {command.command_id} rewrites the weakest "
                        f"precondition of {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    generated_symbol_ids=tuple(
                        f"gen:{command.command_id}:{target}"
                        for target in command.target_symbol_ids
                    ),
                )
            )
        elif kind is CommandKind.HAVOC:
            for target in command.target_symbol_ids or command.effects.writes:
                gen_id = f"gen:havoc:{command.command_id}:{target}"
                generated.append(
                    GeneratedSymbol(
                        symbol_id=gen_id,
                        origin_symbol_id=target,
                        rule=VCRuleKind.HAVOC,
                        construct_id=command.command_id,
                        reason="havoc introduces an unconstrained fresh value",
                    )
                )
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.HAVOC,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Havoc command {command.command_id} quantifies fresh symbols "
                        f"for {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    generated_symbol_ids=tuple(
                        item.symbol_id
                        for item in generated
                        if item.construct_id == command.command_id
                    ),
                )
            )
        elif kind is CommandKind.THROW:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.THROW,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Throw command {command.command_id} transfers to the "
                        f"exceptional channel of {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    attributes={"raises": list(command.effects.raises)},
                )
            )
        elif kind is CommandKind.RETURN:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.RETURN,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=post_ids or goals,
                    path=pre_ids,
                    statement=(
                        f"Return command {command.command_id} must establish the "
                        f"normal postcondition of {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                )
            )
        elif kind is CommandKind.ALLOCATE:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.ALLOCATE,
                    construct_kind=SourceConstructKind.RESOURCE,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Allocation {command.command_id} produces a resource "
                        f"obligation under {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    attributes={"allocates": list(command.effects.allocates)},
                )
            )
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.RESOURCE,
                    construct_kind=SourceConstructKind.RESOURCE,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Resource assertion for allocate {command.command_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    suffix="resource",
                )
            )
        elif kind is CommandKind.DEALLOCATE:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.DEALLOCATE,
                    construct_kind=SourceConstructKind.RESOURCE,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Deallocation {command.command_id} produces a resource "
                        f"obligation under {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    attributes={"deallocates": list(command.effects.deallocates)},
                )
            )
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.RESOURCE,
                    construct_kind=SourceConstructKind.RESOURCE,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Resource assertion for deallocate {command.command_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    suffix="resource",
                )
            )
        elif kind is CommandKind.CALL:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.CALL,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Call command {command.command_id} requires modular contract "
                        f"composition under {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                )
            )
            # Without a callee contract, modular reasoning is unsupported.
            unsupported.append(
                UnsupportedEffect(
                    effect_id=f"unsupported:call:{command.command_id}",
                    kind=UnsupportedEffectKind.UNMODELED_CALL,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    description=(
                        f"Call {command.command_id} has no inlined callee contract; "
                        "modular composition remains explicit."
                    ),
                    parent_contract_id=contract.contract_id,
                )
            )
        elif kind is CommandKind.ATOMIC:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.ATOMIC,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Atomic region {command.command_id} is treated as an "
                        f"indivisible WP step for {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                )
            )
        elif kind is CommandKind.UNDEFINED:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.UNDEFINED,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=tuple(
                        item.expression_id for item in command.undefined_behavior
                    )
                    or goals,
                    path=pre_ids,
                    statement=(
                        f"Undefined command {command.command_id} remains an explicit "
                        f"obligation under {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                )
            )
            unsupported.append(
                UnsupportedEffect(
                    effect_id=f"unsupported:ub:{command.command_id}",
                    kind=UnsupportedEffectKind.UNDEFINED_BEHAVIOR,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    description=(
                        f"Command {command.command_id} has undefined behavior that "
                        "cannot be discharged by the WP calculus alone."
                    ),
                    parent_contract_id=contract.contract_id,
                )
            )
        else:
            # SKIP and any future pure no-ops.
            obligations.append(
                self._obligation(
                    rule=rule,
                    construct_kind=SourceConstructKind.COMMAND,
                    construct_id=command.command_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=goals,
                    path=pre_ids,
                    statement=(
                        f"Command {command.command_id} ({kind.value}) preserves the "
                        f"weakest precondition of {contract.contract_id}."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                )
            )

        for ub in command.undefined_behavior:
            if kind is not CommandKind.UNDEFINED:
                unsupported.append(
                    UnsupportedEffect(
                        effect_id=f"unsupported:ub:{ub.condition_id}",
                        kind=UnsupportedEffectKind.UNDEFINED_BEHAVIOR,
                        construct_kind=SourceConstructKind.COMMAND,
                        construct_id=command.command_id,
                        description=ub.description,
                        parent_contract_id=contract.contract_id,
                        attributes={"condition_id": ub.condition_id},
                    )
                )
                obligations.append(
                    self._obligation(
                        rule=VCRuleKind.UNDEFINED,
                        construct_kind=SourceConstructKind.COMMAND,
                        construct_id=command.command_id,
                        contract=contract,
                        function=function,
                        assumptions=pre_ids,
                        goals=(ub.expression_id,),
                        path=pre_ids,
                        statement=(
                            f"Undefined-behavior guard {ub.condition_id} on "
                            f"{command.command_id}."
                        ),
                        source_ref_ids=ub.source_ref_ids or sources,
                        span_ids=ub.span_ids or spans,
                        suffix=ub.condition_id,
                    )
                )

        unsupported.extend(
            self._effect_unsupported(
                effects=command.effects,
                construct_kind=SourceConstructKind.COMMAND,
                construct_id=command.command_id,
                contract=contract,
            )
        )

        weakest.append(
            WeakestPrecondition(
                wp_id=f"wp:command:{command.command_id}",
                function_id=function.function_id,
                program_point_kind=SourceConstructKind.COMMAND,
                program_point_id=command.command_id,
                exit_kind="normal",
                assumption_expression_ids=tuple(pre_ids),
                consequent_expression_ids=tuple(goals),
                rule=rule,
                parent_contract_id=contract.contract_id,
                generated_symbol_ids=tuple(
                    item.symbol_id
                    for item in generated
                    if item.construct_id == command.command_id
                ),
                source_ref_ids=sources,
                span_ids=spans,
            )
        )
        return obligations, weakest, generated, unsupported

    def _frame_obligations(
        self,
        *,
        contract: ProgramContract,
        function: ProgramFunction,
        pre_ids: Sequence[str],
    ) -> list[VerificationObligation]:
        obligations: list[VerificationObligation] = []
        modified = tuple(
            sorted(
                set(
                    contract.effects.writes
                    + contract.effects.allocates
                    + contract.effects.deallocates
                    + function.effects.writes
                    + function.effects.allocates
                    + function.effects.deallocates
                )
            )
        )
        for symbol_id in modified:
            if (
                not contract.frame.allows_all_writes
                and symbol_id not in contract.frame.writable_symbol_ids
            ):
                # Still emit a frame obligation so incompleteness is explicit.
                pass
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.FRAME,
                    construct_kind=SourceConstructKind.FRAME,
                    construct_id=symbol_id,
                    contract=contract,
                    function=function,
                    assumptions=pre_ids,
                    goals=pre_ids,
                    path=pre_ids,
                    statement=(
                        f"Frame condition of {contract.contract_id} covers "
                        f"modification of {symbol_id}."
                    ),
                    source_ref_ids=contract.source_ref_ids,
                    span_ids=contract.span_ids,
                    attributes={
                        "writable": contract.frame.allows_all_writes
                        or symbol_id in contract.frame.writable_symbol_ids,
                        "symbol_id": symbol_id,
                    },
                )
            )
        return obligations

    def _loop_obligations(
        self,
        *,
        loop: LoopContract,
        contract: ProgramContract,
        function: ProgramFunction,
        pre_ids: Sequence[str],
    ) -> tuple[list[VerificationObligation], list[UnsupportedEffect]]:
        obligations: list[VerificationObligation] = []
        unsupported: list[UnsupportedEffect] = []
        invariant_ids = tuple(item.expression_id for item in loop.invariants)
        variant_ids = tuple(item.expression_id for item in loop.variants)
        sources = loop.source_ref_ids or function.source_ref_ids
        spans = loop.span_ids or function.span_ids

        if not loop.invariants:
            raise VCValidationError(f"loop {loop.loop_id} requires an invariant")

        obligations.append(
            self._obligation(
                rule=VCRuleKind.LOOP_INVARIANT_INIT,
                construct_kind=SourceConstructKind.LOOP,
                construct_id=loop.loop_id,
                contract=contract,
                function=function,
                assumptions=pre_ids,
                goals=invariant_ids,
                path=pre_ids,
                statement=(
                    f"Loop {loop.loop_id} invariant must hold on entry to "
                    f"{loop.header_block_id}."
                ),
                source_ref_ids=sources,
                span_ids=spans,
                suffix="init",
            )
        )
        obligations.append(
            self._obligation(
                rule=VCRuleKind.LOOP_INVARIANT_PRESERVE,
                construct_kind=SourceConstructKind.LOOP,
                construct_id=loop.loop_id,
                contract=contract,
                function=function,
                assumptions=tuple(pre_ids) + invariant_ids,
                goals=invariant_ids,
                path=tuple(pre_ids) + invariant_ids,
                statement=(
                    f"Loop {loop.loop_id} body must preserve its invariant."
                ),
                source_ref_ids=sources,
                span_ids=spans,
                suffix="preserve",
            )
        )

        requires_variant = (
            loop.total_correctness
            or self.loop_variant_policy is LoopVariantPolicy.REQUIRED
        )
        if requires_variant:
            if not variant_ids:
                raise VCValidationError(
                    f"loop {loop.loop_id} requires a variant under the active policy"
                )
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.LOOP_VARIANT_DECREASE,
                    construct_kind=SourceConstructKind.LOOP,
                    construct_id=loop.loop_id,
                    contract=contract,
                    function=function,
                    assumptions=tuple(pre_ids) + invariant_ids,
                    goals=variant_ids,
                    path=tuple(pre_ids) + invariant_ids,
                    statement=(
                        f"Loop {loop.loop_id} variant must strictly decrease."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    suffix="decrease",
                )
            )
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.LOOP_VARIANT_BOUNDED,
                    construct_kind=SourceConstructKind.LOOP,
                    construct_id=loop.loop_id,
                    contract=contract,
                    function=function,
                    assumptions=tuple(pre_ids) + invariant_ids,
                    goals=variant_ids,
                    path=tuple(pre_ids) + invariant_ids,
                    statement=(
                        f"Loop {loop.loop_id} variant must be well-founded / bounded."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    suffix="bounded",
                )
            )
        elif variant_ids and self.loop_variant_policy is LoopVariantPolicy.OPTIONAL:
            obligations.append(
                self._obligation(
                    rule=VCRuleKind.LOOP_VARIANT_DECREASE,
                    construct_kind=SourceConstructKind.LOOP,
                    construct_id=loop.loop_id,
                    contract=contract,
                    function=function,
                    assumptions=tuple(pre_ids) + invariant_ids,
                    goals=variant_ids,
                    path=tuple(pre_ids) + invariant_ids,
                    statement=(
                        f"Optional variant for loop {loop.loop_id} decreases when supplied."
                    ),
                    source_ref_ids=sources,
                    span_ids=spans,
                    suffix="optional-decrease",
                )
            )

        return obligations, unsupported

    def _function_level_unsupported(
        self,
        *,
        contract: ProgramContract,
        function: ProgramFunction,
    ) -> list[UnsupportedEffect]:
        return self._effect_unsupported(
            effects=function.effects,
            construct_kind=SourceConstructKind.FUNCTION,
            construct_id=function.function_id,
            contract=contract,
            prefix="function",
        )

    def _effect_unsupported(
        self,
        *,
        effects: EffectSummary,
        construct_kind: SourceConstructKind,
        construct_id: str,
        contract: ProgramContract,
        prefix: str = "effect",
    ) -> list[UnsupportedEffect]:
        records: list[UnsupportedEffect] = []
        if effects.performs_io:
            records.append(
                UnsupportedEffect(
                    effect_id=f"unsupported:{prefix}:io:{construct_id}",
                    kind=UnsupportedEffectKind.PERFORMS_IO,
                    construct_kind=construct_kind,
                    construct_id=construct_id,
                    description=(
                        f"{construct_id} performs I/O; the WP calculus leaves it explicit."
                    ),
                    parent_contract_id=contract.contract_id,
                )
            )
        if effects.synchronizes:
            records.append(
                UnsupportedEffect(
                    effect_id=f"unsupported:{prefix}:sync:{construct_id}",
                    kind=UnsupportedEffectKind.SYNCHRONIZES,
                    construct_kind=construct_kind,
                    construct_id=construct_id,
                    description=(
                        f"{construct_id} synchronizes; concurrency is not discharged here."
                    ),
                    parent_contract_id=contract.contract_id,
                )
            )
        if effects.nondeterministic:
            records.append(
                UnsupportedEffect(
                    effect_id=f"unsupported:{prefix}:nondet:{construct_id}",
                    kind=UnsupportedEffectKind.NONDETERMINISTIC,
                    construct_kind=construct_kind,
                    construct_id=construct_id,
                    description=(
                        f"{construct_id} is nondeterministic; residual choice stays explicit."
                    ),
                    parent_contract_id=contract.contract_id,
                )
            )
        if not contract.frame.allows_all_writes:
            writable = set(contract.frame.writable_symbol_ids)
            for symbol_id in effects.writes:
                if symbol_id not in writable:
                    records.append(
                        UnsupportedEffect(
                            effect_id=f"unsupported:{prefix}:write:{construct_id}:{symbol_id}",
                            kind=UnsupportedEffectKind.UNFRAMED_WRITE,
                            construct_kind=construct_kind,
                            construct_id=construct_id,
                            description=(
                                f"Write of {symbol_id} at {construct_id} is outside the "
                                f"frame of {contract.contract_id}."
                            ),
                            symbol_ids=(symbol_id,),
                            parent_contract_id=contract.contract_id,
                        )
                    )
            for symbol_id in effects.allocates:
                if symbol_id not in writable:
                    records.append(
                        UnsupportedEffect(
                            effect_id=(
                                f"unsupported:{prefix}:alloc:{construct_id}:{symbol_id}"
                            ),
                            kind=UnsupportedEffectKind.UNFRAMED_ALLOCATION,
                            construct_kind=construct_kind,
                            construct_id=construct_id,
                            description=(
                                f"Allocation of {symbol_id} at {construct_id} is outside "
                                f"the frame of {contract.contract_id}."
                            ),
                            symbol_ids=(symbol_id,),
                            parent_contract_id=contract.contract_id,
                        )
                    )
            for symbol_id in effects.deallocates:
                if symbol_id not in writable:
                    records.append(
                        UnsupportedEffect(
                            effect_id=(
                                f"unsupported:{prefix}:dealloc:{construct_id}:{symbol_id}"
                            ),
                            kind=UnsupportedEffectKind.UNFRAMED_DEALLOCATION,
                            construct_kind=construct_kind,
                            construct_id=construct_id,
                            description=(
                                f"Deallocation of {symbol_id} at {construct_id} is outside "
                                f"the frame of {contract.contract_id}."
                            ),
                            symbol_ids=(symbol_id,),
                            parent_contract_id=contract.contract_id,
                        )
                    )
        return records

    @staticmethod
    def _rule_for_command(kind: CommandKind) -> VCRuleKind:
        mapping = {
            CommandKind.SKIP: VCRuleKind.SKIP,
            CommandKind.ASSIGN: VCRuleKind.ASSIGN,
            CommandKind.ASSUME: VCRuleKind.ASSUME,
            CommandKind.ASSERT: VCRuleKind.ASSERT,
            CommandKind.CALL: VCRuleKind.CALL,
            CommandKind.RETURN: VCRuleKind.RETURN,
            CommandKind.THROW: VCRuleKind.THROW,
            CommandKind.HAVOC: VCRuleKind.HAVOC,
            CommandKind.ALLOCATE: VCRuleKind.ALLOCATE,
            CommandKind.DEALLOCATE: VCRuleKind.DEALLOCATE,
            CommandKind.ATOMIC: VCRuleKind.ATOMIC,
            CommandKind.UNDEFINED: VCRuleKind.UNDEFINED,
        }
        return mapping[kind]

    @staticmethod
    def _block_raised_types(
        block: Any,
        commands: Mapping[str, ProgramCommand],
    ) -> tuple[str, ...]:
        raised: list[str] = []
        for command_id in block.command_ids:
            command = commands[command_id]
            raised.extend(command.effects.raises)
        return tuple(sorted(set(raised)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.INTERFACE,
            "loop_variant_policy": self.loop_variant_policy.value,
            "require_source_maps": self.require_source_maps,
            "schema_version": self.SCHEMA_VERSION,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationConditionGenerator":
        interface = value.get("interface", VERIFICATION_CONDITION_GENERATOR_INTERFACE)
        if interface != VERIFICATION_CONDITION_GENERATOR_INTERFACE:
            raise VCValidationError(
                f"unsupported interface {interface!r}; expected "
                f"{VERIFICATION_CONDITION_GENERATOR_INTERFACE}"
            )
        return cls(
            loop_variant_policy=value.get(
                "loop_variant_policy", LoopVariantPolicy.OPTIONAL.value
            ),
            require_source_maps=value.get("require_source_maps", True),
        )


def generate_verification_conditions(
    program: ProgramIR,
    contract: ProgramContract,
    loop_contracts: Sequence[LoopContract] = (),
    *,
    loop_variant_policy: LoopVariantPolicy | str = LoopVariantPolicy.OPTIONAL,
) -> VerificationConditionSet:
    """Module-level convenience wrapper around :class:`VerificationConditionGenerator`."""

    return VerificationConditionGenerator(
        loop_variant_policy=loop_variant_policy
    ).generate(program, contract, loop_contracts)


__all__ = [
    "VERIFICATION_CONDITION_GENERATOR_INTERFACE",
    "VC_IDENTITY_DOMAIN",
    "VC_SCHEMA_VERSION",
    "VC_SET_SCHEMA_VERSION",
    "GeneratedSymbol",
    "LoopVariantPolicy",
    "SourceConstructKind",
    "UnsupportedEffect",
    "UnsupportedEffectKind",
    "VCRuleKind",
    "VCValidationError",
    "VerificationConditionGenerator",
    "VerificationConditionSet",
    "VerificationObligation",
    "WeakestPrecondition",
    "generate_verification_conditions",
]
