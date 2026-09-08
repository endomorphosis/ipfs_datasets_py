"""Canonical compositional software contracts.

This module extends the datasets-owned software-contract authority.  It does
not create a second formula language: executable semantics are either an
existing :class:`BoundedPredicate` or a content-addressed reference to an
existing logic-family artifact.  Legacy prose is retained only as an opaque
annotation and therefore cannot discharge an obligation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.contracts import (
    BoundedPredicate,
    CallableContract,
    ContractProvenance,
)
from ipfs_datasets_py.logic.software_verification.concurrency import (
    RelyGuaranteeContract,
)

COMPOSITIONAL_CONTRACT_INTERFACE: Final = "CompositionalContract@1"
COMPOSITIONAL_CONTRACT_SCHEMA: Final = "ipfs-datasets.software-contracts.compositional-contract@1"
SEMANTIC_CLAUSE_SCHEMA: Final = "ipfs-datasets.software-contracts.semantic-contract-clause@1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,511}$")
_CID_RE = re.compile(r"^(?:b[a-z2-7]+|sha256:[0-9a-f]{64})$")


class CompositionalContractError(ValueError):
    """Raised when authority-bearing compositional data is ambiguous."""


class ClauseKind(StrEnum):
    PRECONDITION = "precondition"
    NORMAL_POSTCONDITION = "normal_postcondition"
    EXCEPTIONAL_POSTCONDITION = "exceptional_postcondition"
    INVARIANT = "invariant"
    ASSUMPTION = "assumption"
    GUARANTEE = "guarantee"
    RELY = "rely"
    INTERFERENCE = "interference"
    TERMINATION = "termination"
    PROGRESS = "progress"
    FAIRNESS = "fairness"
    SECURITY = "security"
    LEGAL_POLICY = "legal_policy"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"


class SemanticSupport(StrEnum):
    TYPED_INLINE = "typed_inline"
    TYPED_REFERENCE = "typed_reference"
    OPAQUE = "opaque"


class ContractConfidence(StrEnum):
    EXACT = "exact"
    CONSERVATIVE = "conservative"
    HEURISTIC = "heuristic"
    OPAQUE = "opaque"


class EvidenceAuthority(StrEnum):
    CANDIDATE = "candidate"
    SYNTAX_CHECKED = "syntax_checked"
    BOUNDED_MODEL_CHECKED = "bounded_model_checked"
    SOLVER_CHECKED = "solver_checked"
    KERNEL_VERIFIED = "kernel_verified"
    RUNTIME_OBSERVED = "runtime_observed"
    CRYPTOGRAPHICALLY_ATTESTED = "cryptographically_attested"


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise CompositionalContractError(f"{label} must be a trimmed non-empty string")
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise CompositionalContractError(f"{label} must be a stable identifier")
    return result


def _root(value: object, label: str, *, optional: bool = False) -> str:
    result = _text(value, label, optional=optional)
    if not result:
        return result
    if not _CID_RE.fullmatch(result):
        raise CompositionalContractError(
            f"{label} must be a CIDv1/base32 or sha256 content identity"
        )
    return result


def _ids(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CompositionalContractError(f"{label} must be a sequence")
    result = tuple(sorted(_identifier(item, f"{label} item") for item in values))
    if len(result) != len(set(result)):
        raise CompositionalContractError(f"{label} must not contain duplicates")
    return result


def _roots(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CompositionalContractError(f"{label} must be a sequence")
    result = tuple(sorted(_root(item, f"{label} item") for item in values))
    if len(result) != len(set(result)):
        raise CompositionalContractError(f"{label} must not contain duplicates")
    return result


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    if not isinstance(value, Mapping):
        raise CompositionalContractError(f"{label} must be a mapping")
    missing = sorted(fields - set(value))
    extra = sorted(set(value) - fields)
    if missing or extra:
        raise CompositionalContractError(
            f"{label} fields are closed (missing={missing}, extra={extra})"
        )


@dataclass(frozen=True, slots=True)
class SemanticContractClause:
    """One typed semantic clause or an explicitly opaque legacy annotation."""

    clause_id: str
    kind: ClauseKind | str
    support: SemanticSupport | str
    predicate: BoundedPredicate | None = None
    formula_cid: str = ""
    logic_family: str = ""
    annotation: str = ""
    source_refs: tuple[str, ...] = ()
    schema: str = SEMANTIC_CLAUSE_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "annotation",
            "clause_id",
            "formula_cid",
            "kind",
            "logic_family",
            "predicate",
            "schema",
            "source_refs",
            "support",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "clause_id", _identifier(self.clause_id, "clause_id"))
        try:
            kind = self.kind if isinstance(self.kind, ClauseKind) else ClauseKind(self.kind)
            support = (
                self.support
                if isinstance(self.support, SemanticSupport)
                else SemanticSupport(self.support)
            )
        except ValueError as error:
            raise CompositionalContractError(str(error)) from error
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "support", support)
        if self.schema != SEMANTIC_CLAUSE_SCHEMA:
            raise CompositionalContractError("unsupported semantic clause schema")
        if self.predicate is not None and not isinstance(self.predicate, BoundedPredicate):
            raise CompositionalContractError("predicate must be a BoundedPredicate")
        object.__setattr__(
            self, "formula_cid", _root(self.formula_cid, "formula_cid", optional=True)
        )
        object.__setattr__(
            self, "logic_family", _text(self.logic_family, "logic_family", optional=True)
        )
        object.__setattr__(self, "annotation", _text(self.annotation, "annotation", optional=True))
        object.__setattr__(self, "source_refs", _ids(self.source_refs, "source_refs"))

        if support is SemanticSupport.TYPED_INLINE:
            if self.predicate is None or self.formula_cid:
                raise CompositionalContractError(
                    "typed_inline requires exactly one inline BoundedPredicate"
                )
        elif support is SemanticSupport.TYPED_REFERENCE:
            if not self.formula_cid or not self.logic_family or self.predicate is not None:
                raise CompositionalContractError(
                    "typed_reference requires formula_cid and logic_family only"
                )
        elif support is SemanticSupport.OPAQUE:
            if not self.annotation or self.predicate is not None or self.formula_cid:
                raise CompositionalContractError(
                    "opaque clauses require annotation and cannot carry typed semantics"
                )

    @property
    def can_discharge(self) -> bool:
        return self.support is not SemanticSupport.OPAQUE

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation": self.annotation,
            "clause_id": self.clause_id,
            "formula_cid": self.formula_cid,
            "kind": (
                self.kind.value if isinstance(self.kind, ClauseKind) else self.kind
            ),
            "logic_family": self.logic_family,
            "predicate": None if self.predicate is None else self.predicate.to_dict(),
            "schema": self.schema,
            "source_refs": list(self.source_refs),
            "support": (
                self.support.value
                if isinstance(self.support, SemanticSupport)
                else self.support
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SemanticContractClause:
        _closed(value, cls._FIELDS, cls.__name__)
        predicate = value["predicate"]
        return cls(
            annotation=str(value["annotation"]),
            clause_id=str(value["clause_id"]),
            formula_cid=str(value["formula_cid"]),
            kind=str(value["kind"]),
            logic_family=str(value["logic_family"]),
            predicate=(None if predicate is None else BoundedPredicate.from_dict(dict(predicate))),
            schema=str(value["schema"]),
            source_refs=tuple(value["source_refs"]),
            support=str(value["support"]),
        )


def _clauses(
    values: Sequence[SemanticContractClause] | object,
    label: str,
    allowed: frozenset[ClauseKind],
) -> tuple[SemanticContractClause, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CompositionalContractError(f"{label} must be a sequence")
    result = tuple(
        sorted(
            (
                item
                if isinstance(item, SemanticContractClause)
                else SemanticContractClause.from_dict(item)
                for item in values
            ),
            key=lambda item: item.clause_id,
        )
    )
    if len({item.clause_id for item in result}) != len(result):
        raise CompositionalContractError(f"{label} clause IDs must be unique")
    disallowed = sorted(
        item.kind.value if isinstance(item.kind, ClauseKind) else item.kind
        for item in result
        if item.kind not in allowed
    )
    if disallowed:
        raise CompositionalContractError(f"{label} contains disallowed kinds {disallowed}")
    return result


@dataclass(frozen=True, slots=True)
class CompositionalContract:
    """Canonical component contract used for assume-guarantee composition.

    Roots bind every source of semantic meaning.  Empty optional roots are
    visible unknowns, never wildcards.  Operational facts such as leases,
    clocks, attempts, or task status are intentionally absent.
    """

    contract_id: str
    component_id: str
    component_kind: str
    provenance: ContractProvenance
    source_root: str
    ast_root: str
    symbol_version_root: str
    interface_root: str
    configuration_root: str
    toolchain_root: str
    preconditions: tuple[SemanticContractClause, ...] = ()
    normal_postconditions: tuple[SemanticContractClause, ...] = ()
    exceptional_postconditions: tuple[SemanticContractClause, ...] = ()
    invariants: tuple[SemanticContractClause, ...] = ()
    assumptions: tuple[SemanticContractClause, ...] = ()
    guarantees: tuple[SemanticContractClause, ...] = ()
    rely: tuple[SemanticContractClause, ...] = ()
    guarantee_relation: tuple[SemanticContractClause, ...] = ()
    progress: tuple[SemanticContractClause, ...] = ()
    policy_obligations: tuple[SemanticContractClause, ...] = ()
    read_set: tuple[str, ...] = ()
    write_set: tuple[str, ...] = ()
    allocation_set: tuple[str, ...] = ()
    io_set: tuple[str, ...] = ()
    network_set: tuple[str, ...] = ()
    subprocess_set: tuple[str, ...] = ()
    filesystem_set: tuple[str, ...] = ()
    secret_set: tuple[str, ...] = ()
    synchronization_set: tuple[str, ...] = ()
    other_effects: tuple[str, ...] = ()
    modifies: tuple[str, ...] = ()
    allowed_interference: tuple[str, ...] = ()
    forbidden_interference: tuple[str, ...] = ()
    invalidation_selectors: tuple[str, ...] = ()
    proof_refs: tuple[str, ...] = ()
    counterexample_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    confidence: ContractConfidence | str = ContractConfidence.OPAQUE
    semantic_support_class: str = "opaque"
    evidence_authority: EvidenceAuthority | str = EvidenceAuthority.CANDIDATE
    open_world: bool = True
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema: str = COMPOSITIONAL_CONTRACT_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "allocation_set",
            "allowed_interference",
            "assumptions",
            "ast_root",
            "attributes",
            "component_id",
            "component_kind",
            "confidence",
            "configuration_root",
            "contract_id",
            "counterexample_refs",
            "evidence_authority",
            "exceptional_postconditions",
            "filesystem_set",
            "forbidden_interference",
            "guarantee_relation",
            "guarantees",
            "interface_root",
            "invalidation_selectors",
            "invariants",
            "io_set",
            "limitations",
            "modifies",
            "network_set",
            "normal_postconditions",
            "open_world",
            "other_effects",
            "policy_obligations",
            "preconditions",
            "progress",
            "proof_refs",
            "provenance",
            "read_set",
            "rely",
            "schema",
            "secret_set",
            "semantic_support_class",
            "source_root",
            "subprocess_set",
            "symbol_version_root",
            "synchronization_set",
            "toolchain_root",
            "write_set",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", _identifier(self.contract_id, "contract_id"))
        object.__setattr__(self, "component_id", _identifier(self.component_id, "component_id"))
        object.__setattr__(
            self, "component_kind", _identifier(self.component_kind, "component_kind")
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise CompositionalContractError("provenance must be ContractProvenance")
        if self.schema != COMPOSITIONAL_CONTRACT_SCHEMA:
            raise CompositionalContractError("unsupported compositional contract schema")
        for name in (
            "source_root",
            "ast_root",
            "symbol_version_root",
            "interface_root",
            "configuration_root",
            "toolchain_root",
        ):
            object.__setattr__(self, name, _root(getattr(self, name), name))
        object.__setattr__(
            self,
            "preconditions",
            _clauses(self.preconditions, "preconditions", frozenset({ClauseKind.PRECONDITION})),
        )
        object.__setattr__(
            self,
            "normal_postconditions",
            _clauses(
                self.normal_postconditions,
                "normal_postconditions",
                frozenset({ClauseKind.NORMAL_POSTCONDITION}),
            ),
        )
        object.__setattr__(
            self,
            "exceptional_postconditions",
            _clauses(
                self.exceptional_postconditions,
                "exceptional_postconditions",
                frozenset({ClauseKind.EXCEPTIONAL_POSTCONDITION}),
            ),
        )
        object.__setattr__(
            self,
            "invariants",
            _clauses(self.invariants, "invariants", frozenset({ClauseKind.INVARIANT})),
        )
        object.__setattr__(
            self,
            "assumptions",
            _clauses(self.assumptions, "assumptions", frozenset({ClauseKind.ASSUMPTION})),
        )
        object.__setattr__(
            self,
            "guarantees",
            _clauses(self.guarantees, "guarantees", frozenset({ClauseKind.GUARANTEE})),
        )
        object.__setattr__(
            self,
            "rely",
            _clauses(self.rely, "rely", frozenset({ClauseKind.RELY})),
        )
        object.__setattr__(
            self,
            "guarantee_relation",
            _clauses(
                self.guarantee_relation,
                "guarantee_relation",
                frozenset({ClauseKind.GUARANTEE, ClauseKind.INTERFERENCE}),
            ),
        )
        object.__setattr__(
            self,
            "progress",
            _clauses(
                self.progress,
                "progress",
                frozenset({ClauseKind.TERMINATION, ClauseKind.PROGRESS, ClauseKind.FAIRNESS}),
            ),
        )
        object.__setattr__(
            self,
            "policy_obligations",
            _clauses(
                self.policy_obligations,
                "policy_obligations",
                frozenset(
                    {
                        ClauseKind.SECURITY,
                        ClauseKind.LEGAL_POLICY,
                        ClauseKind.PROTOCOL,
                        ClauseKind.HYPERPROPERTY,
                    }
                ),
            ),
        )
        for name in (
            "read_set",
            "write_set",
            "allocation_set",
            "io_set",
            "network_set",
            "subprocess_set",
            "filesystem_set",
            "secret_set",
            "synchronization_set",
            "other_effects",
            "modifies",
            "allowed_interference",
            "forbidden_interference",
            "invalidation_selectors",
            "limitations",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        object.__setattr__(self, "proof_refs", _roots(self.proof_refs, "proof_refs"))
        object.__setattr__(
            self, "counterexample_refs", _roots(self.counterexample_refs, "counterexample_refs")
        )
        try:
            confidence = (
                self.confidence
                if isinstance(self.confidence, ContractConfidence)
                else ContractConfidence(self.confidence)
            )
            authority = (
                self.evidence_authority
                if isinstance(self.evidence_authority, EvidenceAuthority)
                else EvidenceAuthority(self.evidence_authority)
            )
        except ValueError as error:
            raise CompositionalContractError(str(error)) from error
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_authority", authority)
        object.__setattr__(
            self,
            "semantic_support_class",
            _identifier(self.semantic_support_class, "semantic_support_class"),
        )
        if not isinstance(self.open_world, bool):
            raise CompositionalContractError("open_world must be bool")
        object.__setattr__(
            self,
            "attributes",
            self.attributes
            if isinstance(self.attributes, FrozenMap)
            else FrozenMap(self.attributes),
        )
        if any(not clause.can_discharge for clause in self.all_semantic_clauses):
            if confidence is ContractConfidence.EXACT:
                raise CompositionalContractError(
                    "a contract containing opaque clauses cannot claim exact confidence"
                )

    @property
    def all_semantic_clauses(self) -> tuple[SemanticContractClause, ...]:
        return (
            self.preconditions
            + self.normal_postconditions
            + self.exceptional_postconditions
            + self.invariants
            + self.assumptions
            + self.guarantees
            + self.rely
            + self.guarantee_relation
            + self.progress
            + self.policy_obligations
        )

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contract_id": self.contract_id,
            "component_id": self.component_id,
            "component_kind": self.component_kind,
            "provenance": self.provenance.to_dict(),
            "source_root": self.source_root,
            "ast_root": self.ast_root,
            "symbol_version_root": self.symbol_version_root,
            "interface_root": self.interface_root,
            "configuration_root": self.configuration_root,
            "toolchain_root": self.toolchain_root,
            "confidence": (
                self.confidence.value
                if isinstance(self.confidence, ContractConfidence)
                else self.confidence
            ),
            "semantic_support_class": self.semantic_support_class,
            "evidence_authority": (
                self.evidence_authority.value
                if isinstance(self.evidence_authority, EvidenceAuthority)
                else self.evidence_authority
            ),
            "open_world": self.open_world,
            "attributes": self.attributes.to_dict(),
            "schema": self.schema,
        }
        clause_names = (
            "preconditions",
            "normal_postconditions",
            "exceptional_postconditions",
            "invariants",
            "assumptions",
            "guarantees",
            "rely",
            "guarantee_relation",
            "progress",
            "policy_obligations",
        )
        for name in clause_names:
            payload[name] = [item.to_dict() for item in getattr(self, name)]
        id_names = (
            "read_set",
            "write_set",
            "allocation_set",
            "io_set",
            "network_set",
            "subprocess_set",
            "filesystem_set",
            "secret_set",
            "synchronization_set",
            "other_effects",
            "modifies",
            "allowed_interference",
            "forbidden_interference",
            "invalidation_selectors",
            "proof_refs",
            "counterexample_refs",
            "limitations",
        )
        for name in id_names:
            payload[name] = list(getattr(self, name))
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CompositionalContract:
        _closed(value, cls._FIELDS, cls.__name__)
        data = dict(value)
        data["provenance"] = ContractProvenance.from_dict(dict(data["provenance"]))
        for name in (
            "preconditions",
            "normal_postconditions",
            "exceptional_postconditions",
            "invariants",
            "assumptions",
            "guarantees",
            "rely",
            "guarantee_relation",
            "progress",
            "policy_obligations",
        ):
            data[name] = tuple(SemanticContractClause.from_dict(item) for item in data[name])
        data["attributes"] = FrozenMap(data["attributes"])
        return cls(**data)


def _inline_clause(
    *, predicate: BoundedPredicate, clause_id: str, kind: ClauseKind
) -> SemanticContractClause:
    return SemanticContractClause(
        clause_id=clause_id,
        kind=kind,
        support=SemanticSupport.TYPED_INLINE,
        predicate=predicate,
    )


def adapt_callable_contract(
    contract: CallableContract,
    *,
    source_root: str,
    ast_root: str,
    symbol_version_root: str,
    interface_root: str,
    configuration_root: str,
    toolchain_root: str,
) -> CompositionalContract:
    """Conservatively adapt readable v1 callable records.

    V1 prose assumptions have no typed truth conditions, so they are retained
    as opaque clauses.  They never become ``true`` and prevent exact confidence.
    """

    assumptions = tuple(
        SemanticContractClause(
            clause_id=item.assumption_id,
            kind=ClauseKind.ASSUMPTION,
            support=SemanticSupport.OPAQUE,
            annotation=item.statement,
        )
        for item in contract.assumptions
    )
    effects: dict[str, list[str]] = {
        "filesystem": [],
        "subprocess": [],
        "network": [],
        "io": [],
        "secret": [],
        "read": [],
        "write": [],
        "other": [],
    }
    for item in contract.effects:
        target = item.kind if item.kind in effects else "other"
        effects[target].append(item.effect_id)
        if item.operation == "read":
            effects["read"].append(item.effect_id)
        if item.operation in {"write", "create", "delete", "mutate"}:
            effects["write"].append(item.effect_id)

    return CompositionalContract(
        contract_id=contract.contract_id,
        component_id=contract.symbol_id or contract.qualified_name,
        component_kind="callable",
        provenance=contract.provenance,
        source_root=source_root,
        ast_root=ast_root,
        symbol_version_root=symbol_version_root,
        interface_root=interface_root,
        configuration_root=configuration_root,
        toolchain_root=toolchain_root,
        preconditions=tuple(
            _inline_clause(
                predicate=item, clause_id=item.predicate_id, kind=ClauseKind.PRECONDITION
            )
            for item in contract.preconditions
        ),
        normal_postconditions=tuple(
            _inline_clause(
                predicate=item,
                clause_id=item.predicate_id,
                kind=ClauseKind.NORMAL_POSTCONDITION,
            )
            for item in contract.postconditions
        ),
        invariants=tuple(
            _inline_clause(predicate=item, clause_id=item.predicate_id, kind=ClauseKind.INVARIANT)
            for item in contract.invariants
        ),
        assumptions=assumptions,
        read_set=tuple(effects["read"]),
        write_set=tuple(effects["write"]),
        filesystem_set=tuple(effects["filesystem"]),
        subprocess_set=tuple(effects["subprocess"]),
        network_set=tuple(effects["network"]),
        io_set=tuple(effects["io"]),
        secret_set=tuple(effects["secret"]),
        other_effects=tuple(effects["other"]),
        modifies=tuple(effects["write"]),
        limitations=(("legacy_v1_prose_assumptions_are_opaque",) if assumptions else ()),
        confidence=(ContractConfidence.OPAQUE if assumptions else ContractConfidence.CONSERVATIVE),
        semantic_support_class=("partial" if assumptions else "supported_subset"),
        evidence_authority=EvidenceAuthority.CANDIDATE,
        open_world=True,
        attributes=FrozenMap({"adapted_from": "CallableContract@v1"}),
    )


def adapt_rely_guarantee_contract(
    contract: RelyGuaranteeContract,
    *,
    provenance: ContractProvenance,
    source_root: str,
    ast_root: str,
    symbol_version_root: str,
    interface_root: str,
    configuration_root: str,
    toolchain_root: str,
) -> CompositionalContract:
    """Read a v1 rely/guarantee record without assigning prose semantics."""

    rely = SemanticContractClause(
        clause_id=f"{contract.contract_id}:rely",
        kind=ClauseKind.RELY,
        support=SemanticSupport.OPAQUE,
        annotation=contract.rely_statement,
    )
    guarantee = SemanticContractClause(
        clause_id=f"{contract.contract_id}:guarantee",
        kind=ClauseKind.GUARANTEE,
        support=SemanticSupport.OPAQUE,
        annotation=contract.guarantee_statement,
    )
    return CompositionalContract(
        contract_id=contract.contract_id,
        component_id=contract.component_id,
        component_kind="concurrent_component",
        provenance=provenance,
        source_root=source_root,
        ast_root=ast_root,
        symbol_version_root=symbol_version_root,
        interface_root=interface_root,
        configuration_root=configuration_root,
        toolchain_root=toolchain_root,
        rely=(rely,),
        guarantees=(guarantee,),
        allowed_interference=contract.interference_ids,
        read_set=contract.shared_variable_ids,
        write_set=contract.shared_variable_ids,
        modifies=contract.shared_variable_ids,
        limitations=("legacy_v1_rely_guarantee_prose_is_opaque",),
        confidence=ContractConfidence.OPAQUE,
        semantic_support_class="opaque",
        evidence_authority=EvidenceAuthority.CANDIDATE,
        open_world=True,
        attributes=FrozenMap({"adapted_from": "RelyGuaranteeContract@v1"}),
    )


def compile_component_contract(
    contract: CallableContract | RelyGuaranteeContract,
    **bindings: Any,
) -> CompositionalContract:
    """Stable adapter entry point used by :mod:`logic.verification_api`."""

    if isinstance(contract, CallableContract):
        return adapt_callable_contract(contract, **bindings)
    if isinstance(contract, RelyGuaranteeContract):
        return adapt_rely_guarantee_contract(contract, **bindings)
    raise CompositionalContractError(
        f"unsupported component contract type {type(contract).__name__}"
    )


__all__ = [
    "COMPOSITIONAL_CONTRACT_INTERFACE",
    "COMPOSITIONAL_CONTRACT_SCHEMA",
    "ClauseKind",
    "CompositionalContract",
    "CompositionalContractError",
    "ContractConfidence",
    "EvidenceAuthority",
    "SEMANTIC_CLAUSE_SCHEMA",
    "SemanticContractClause",
    "SemanticSupport",
    "adapt_callable_contract",
    "adapt_rely_guarantee_contract",
    "compile_component_contract",
]
