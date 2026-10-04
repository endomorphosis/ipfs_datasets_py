"""Entry-premise feasibility and requested-domain coverage for typed models.

These obligations concern the mathematical Int/Bool model of the admitted
source profile. They establish neither Python runtime types nor interpretation
of a natural-language request. Preconditions and requested domains are checked
independently of the postcondition and body equations. A separate property
query restricts its countermodels to the complete requested input domain.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any

from ipfs_datasets_py.logic.backends.smt.compiler import (
    BOOL_SORT, SmtObligation, SmtQueryMode, term_and, term_implies,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from .contracts import ProgramContract
from .pipeline import (
    SOURCE_SEMANTICS_PROFILE, UnsupportedConstructError,
    _ExpressionInjector, _SmtLowering, _function_by_name, lower_vc_obligation_to_smt,
)
from .program import ProgramIR, SymbolKind
from .vc import VCRuleKind, generate_verification_conditions

APPLICABILITY_SCHEMA = "typed-contract-input-applicability@1"
APPLICABILITY_PROFILE = "typed-entry-int-bool-linear@1"
_KINDS = ("premises_satisfiable", "domain_satisfiable", "domain_implies_preconditions",
          "property_on_requested_domain")


class UnsupportedApplicabilityError(UnsupportedConstructError):
    """An input predicate is outside the entry-only mathematical profile."""


def _text(value: Any, name: str, maximum: int = 512) -> str:
    if type(value) is not str or not value.strip():
        raise UnsupportedApplicabilityError(f"{name} must be a nonempty exact string")
    value = value.strip()
    if len(value.encode("utf-8")) > maximum or "\x00" in value:
        raise UnsupportedApplicabilityError(f"{name} exceeds its text bound")
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RequestedInputDomain:
    """Explicit parameter predicates; ``True`` requests the complete typed domain.

    ``domain_id`` is a logical selector. Full predicate content participates in
    every obligation identity, including when a caller supplies that selector.
    """

    function_name: str
    predicates: tuple[str, ...] = ("True",)
    domain_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "function_name", _text(self.function_name, "function_name"))
        if type(self.predicates) not in {tuple, list} or not 1 <= len(self.predicates) <= 32:
            raise UnsupportedApplicabilityError("predicates must contain 1–32 explicit input conditions")
        predicates = tuple(_text(item, "predicate", 16 * 1024) for item in self.predicates)
        if sum(len(item.encode("utf-8")) for item in predicates) > 16 * 1024:
            raise UnsupportedApplicabilityError("input predicate byte bound exceeded")
        object.__setattr__(self, "predicates", predicates)
        if type(self.domain_id) is not str:
            raise UnsupportedApplicabilityError("domain_id must be an exact string")
        domain_id = self.domain_id or "domain:" + _digest({
            "function_name": self.function_name, "predicates": list(predicates),
        })
        object.__setattr__(self, "domain_id", _text(domain_id, "domain_id"))

    def to_dict(self) -> dict[str, Any]:
        return {"function_name": self.function_name, "predicates": list(self.predicates),
                "domain_id": self.domain_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RequestedInputDomain:
        if type(value) is not dict or set(value) != {"function_name", "predicates", "domain_id"}:
            raise UnsupportedApplicabilityError("invalid requested-domain fields")
        result = cls(value["function_name"], value["predicates"], value["domain_id"])
        if result.to_dict() != value:
            raise UnsupportedApplicabilityError("requested domain is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class DomainCheckObligation:
    kind: str
    parent_contract_id: str
    domain_id: str
    smt_obligation: SmtObligation

    def __post_init__(self) -> None:
        if self.kind not in _KINDS or type(self.smt_obligation) is not SmtObligation:
            raise UnsupportedApplicabilityError("invalid domain-check kind or native obligation")
        if (self.smt_obligation.attributes.get("parent_contract_id") != self.parent_contract_id
                or self.smt_obligation.attributes.get("domain_id") != self.domain_id
                or self.smt_obligation.attributes.get("check_kind") != self.kind):
            raise UnsupportedApplicabilityError("domain-check identity lost its typed bindings")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": APPLICABILITY_SCHEMA, "kind": self.kind,
                "parent_contract_id": self.parent_contract_id, "domain_id": self.domain_id,
                "smt_obligation": self.smt_obligation.to_dict()}


def _admit_predicate_syntax(source: str) -> None:
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise UnsupportedApplicabilityError("invalid input predicate syntax") from error
    pending, count = [(tree, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > 256 or depth > 64:
            raise UnsupportedApplicabilityError("input predicate AST size/depth bound exceeded")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))


def derive_contract_domain_obligations(
    program: ProgramIR, contract: ProgramContract, domain: RequestedInputDomain,
) -> tuple[DomainCheckObligation, ...]:
    """Derive SAT(P), SAT(D), D ⇒ P and the property on D without running tools.

    Predicates may refer only to the contracted function's entry parameters.
    Return values, locals, old state and other functions' parameters are rejected.
    Each query records its complete source, contract, domain and symbol binding.
    The first three checks omit body equations and the property under test.
    The fourth retains the complete body and postcondition with D as its input
    premise, so a SAT countermodel necessarily belongs to the requested domain.
    """
    if (type(program) is not ProgramIR or type(contract) is not ProgramContract
            or type(domain) is not RequestedInputDomain):
        raise UnsupportedApplicabilityError("native ProgramIR, ProgramContract and RequestedInputDomain required")
    program.validate()
    contract.validate_against(program)
    if not contract.postconditions:
        raise UnsupportedApplicabilityError("an explicit postcondition is required for domain verification")
    function = _function_by_name(program, domain.function_name)
    if function.function_id != contract.function_id:
        raise UnsupportedApplicabilityError("requested domain targets another contracted function")
    # Preserve the same admitted source fragment as property verification. Its
    # equations are checked here, but never inserted as entry-input premises.
    _SmtLowering(program).body_assumptions(function)
    source_ref_ids = contract.source_ref_ids or function.source_ref_ids
    span_ids = contract.span_ids or function.span_ids
    if not source_ref_ids or not set(source_ref_ids) <= {ref.ref_id for ref in program.sources}:
        raise UnsupportedApplicabilityError("entry predicates require exact native source references")
    injector = _ExpressionInjector(program=program, function=function,
                                   source_ref_id=source_ref_ids[0], span_ids=span_ids)
    for predicate in domain.predicates:
        _admit_predicate_syntax(predicate)
    domain_ids = tuple(injector.inject(predicate) for predicate in domain.predicates)
    extended = injector.program_with_expressions()
    lowering = _SmtLowering(extended)
    parameters = set(function.parameter_symbol_ids)
    for symbol_id in function.parameter_symbol_ids:
        if lowering.symbols[symbol_id].kind is not SymbolKind.PARAMETER:
            raise UnsupportedApplicabilityError("entry parameters require parameter symbol roles")
        lowering.declare_symbol(symbol_id)

    def predicate_term(expression_id: str):
        pending, visited = [expression_id], set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            expression = lowering.expressions.get(current)
            if expression is None or len(visited) > 4096:
                raise UnsupportedApplicabilityError("missing or oversized entry predicate dependencies")
            if not set(expression.symbol_ids) <= parameters:
                raise UnsupportedApplicabilityError("input predicates may reference only entry parameters")
            pending.extend(expression.operand_ids)
        if lowering.expression_sort(expression_id) != BOOL_SORT:
            raise UnsupportedApplicabilityError("input predicates require explicit Boolean expressions")
        return lowering.term_for_expression(expression_id)

    premises = term_and(*(predicate_term(clause.expression_id) for clause in contract.preconditions))
    requested = term_and(*(predicate_term(expression_id) for expression_id in domain_ids))
    symbols = {symbol_id: {"name": lowering.declare_symbol(symbol_id),
                           "sort": lowering._symbol_sort(symbol_id).to_dict()}
               for symbol_id in sorted(parameters)}
    context = {"schema": APPLICABILITY_SCHEMA, "applicability_profile": APPLICABILITY_PROFILE,
               "source_semantics_profile": SOURCE_SEMANTICS_PROFILE, "program_id": program.program_id,
               "parent_contract_id": contract.contract_id, "contract": contract.to_dict(),
               "function_id": function.function_id, "domain_id": domain.domain_id,
               "domain": domain.to_dict(), "source_ref_ids": list(source_ref_ids),
               "span_ids": list(span_ids), "parameter_symbol_bindings": symbols,
               "premise_expression_ids": [clause.expression_id for clause in contract.preconditions],
               "scope": "entry_parameter_mathematical_model_only"}
    goals = (premises, requested, term_implies(requested, premises))
    modes = (SmtQueryMode.SATISFIABILITY, SmtQueryMode.SATISFIABILITY, SmtQueryMode.THEOREM_BY_NEGATION)
    obligations = []
    for kind, goal, mode in zip(_KINDS[:3], goals, modes):
        identity = _digest({"context": context, "kind": kind, "goal": goal.to_dict()})
        obligation = SmtObligation(
            obligation_id="input-domain:" + identity, query_mode=mode,
            features=("arithmetic", "equality", "verification_conditions"),
            goal=goal, functions=lowering.fun_decls(), assumptions=(),
            request_model=True, request_unsat_core=True,
            property_ids=("input-domain-property:" + identity,),
            attributes=FrozenMap({**context, "check_kind": kind}),
        )
        obligations.append(DomainCheckObligation(kind, contract.contract_id, domain.domain_id, obligation))
    conditions = generate_verification_conditions(extended, contract).obligations_by_rule(
        VCRuleKind.POSTCONDITION_NORMAL
    )
    if len(conditions) != 1:
        raise UnsupportedApplicabilityError("domain property requires one admitted normal-exit condition")
    condition = replace(conditions[0], assumption_expression_ids=domain_ids,
                        path_condition_expression_ids=domain_ids)
    property_obligation, _ = lower_vc_obligation_to_smt(extended, condition)
    kind = _KINDS[3]
    identity = _digest({"context": context, "kind": kind,
                        "property_obligation": property_obligation.to_dict()})
    property_obligation = replace(
        property_obligation, obligation_id="input-domain:" + identity,
        property_ids=("input-domain-property:" + identity,),
        attributes=FrozenMap({**property_obligation.attributes.to_dict(), **context,
                              "check_kind": kind,
                              "scope": "typed_function_model_with_requested_entry_domain",
                              "original_vc": conditions[0].to_dict(),
                              "requested_domain_vc": condition.to_dict()}),
    )
    obligations.append(DomainCheckObligation(kind, contract.contract_id, domain.domain_id,
                                           property_obligation))
    return tuple(obligations)


__all__ = ["APPLICABILITY_SCHEMA", "APPLICABILITY_PROFILE", "RequestedInputDomain",
           "DomainCheckObligation", "UnsupportedApplicabilityError", "derive_contract_domain_obligations"]
