"""Source-to-VC-to-SMT vertical slice composition (``SourceToVerificationPipeline@1``).

Connects a source snapshot through typed program/contracts, verification-condition
generation, backend-neutral SMT obligations, Z3/CVC5 differential execution, and
source-bound proof/counterexample receipts.

This module **owns composition only**. It reuses:

* :func:`adapt_source_to_software_verification` for ProgramIR lowering;
* :class:`VerificationConditionGenerator` for source-bound VC sets;
* :class:`SoftwareVerificationSMTCompiler` for backend-neutral SMT-LIB;
* :func:`run_z3_cvc5_differential` for dual-solver execution and disagreement
  quarantine.

Unsupported constructs fail closed rather than being erased.  Every solver
result binds source spans, program tree identity, property/assumption ids,
tool identities, resource bounds, and translation receipts.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.smt.compiler import (
    BOOL_SORT,
    INT_SORT,
    SMT_COMPILER_ID,
    SmtCompilation,
    SmtFunDecl,
    SmtNamedAssertion,
    SmtObligation,
    SmtQueryMode,
    SmtSort,
    SmtTerm,
    SmtTermKind,
    SoftwareVerificationSMTCompiler,
    smt_sanitize,
    term_and,
    term_eq,
    term_false,
    term_int,
    term_not,
    term_symbol,
    term_true,
)
from ipfs_datasets_py.logic.backends.smt.differential import (
    DifferentialClassification,
    SmtDifferentialReport,
    SoftwareVerificationSmtBackend,
    run_z3_cvc5_differential,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.contracts import (
    ContractClause,
    ContractClauseKind,
    FrameCondition,
    LoopContract,
    ProgramContract,
)
from ipfs_datasets_py.logic.software_verification.program import (
    CommandKind,
    ExpressionKind,
    ProgramExpression,
    ProgramFunction,
    ProgramIR,
    ProgramSymbol,
    Purity,
    SymbolKind,
)
from ipfs_datasets_py.logic.software_verification.source_adapters import (
    SourceAdapterResult,
    SourceAdapterStatus,
    adapt_source_to_software_verification,
)
from ipfs_datasets_py.logic.software_verification.vc import (
    VCRuleKind,
    VerificationConditionSet,
    VerificationObligation,
    generate_verification_conditions,
)

SOURCE_TO_VERIFICATION_PIPELINE_INTERFACE: Final = "SourceToVerificationPipeline@1"
PIPELINE_SCHEMA_VERSION: Final = "source-to-verification-pipeline/v1"
PIPELINE_VERSION: Final = "1.0.0"

# Solver-facing VC rules that lower into theorem-by-negation SMT queries.
_SOLVER_RULES: Final[frozenset[VCRuleKind]] = frozenset(
    {
        VCRuleKind.POSTCONDITION_NORMAL,
        VCRuleKind.ASSERT,
        VCRuleKind.PRECONDITION,
    }
)

_BINARY_OP_TO_SMT: Final[dict[str, SmtTermKind]] = {
    "add": SmtTermKind.ADD,
    "sub": SmtTermKind.SUB,
    "mul": SmtTermKind.MUL,
    "div": SmtTermKind.DIV,
    "floordiv": SmtTermKind.DIV,
    "mod": SmtTermKind.MOD,
    "eq": SmtTermKind.EQ,
    "ne": SmtTermKind.DISTINCT,  # handled specially for binary
    "lt": SmtTermKind.LT,
    "le": SmtTermKind.LE,
    "gt": SmtTermKind.GT,
    "ge": SmtTermKind.GE,
    "and": SmtTermKind.AND,
    "or": SmtTermKind.OR,
    "greater_than": SmtTermKind.GT,
    "less_than": SmtTermKind.LT,
    "greater_equal": SmtTermKind.GE,
    "less_equal": SmtTermKind.LE,
}

_UNARY_OP_TO_SMT: Final[dict[str, SmtTermKind]] = {
    "neg": SmtTermKind.NEG,
    "not": SmtTermKind.NOT,
    "pos": SmtTermKind.ADD,  # unary + is identity; handled specially
}


class PipelineError(ValueError):
    """Fail-closed pipeline error."""


class UnsupportedConstructError(PipelineError):
    """Source or contract construct is outside the admitted fragment."""


class PipelineStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    DISAGREEMENT_QUARANTINED = "disagreement_quarantined"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PipelineError(f"{label} must be a non-empty string")
    return value.strip()


def _safe_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(
        "|".join(str(part) for part in parts).encode("utf-8", errors="surrogatepass")
    ).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _mapped(source_ref_id: str, span_ids: Sequence[str] = ()) -> dict[str, tuple[str, ...]]:
    payload: dict[str, tuple[str, ...]] = {"source_ref_ids": (source_ref_id,)}
    if span_ids:
        payload["span_ids"] = tuple(span_ids)
    return payload


def _sort_for_type_ref(type_ref: str) -> SmtSort:
    lowered = (type_ref or "any").lower()
    if lowered in {"bool", "boolean"}:
        return BOOL_SORT
    return INT_SORT


def _symbol_smt_name(symbol: ProgramSymbol) -> str:
    return smt_sanitize(symbol.name or symbol.symbol_id, prefix="v")


@dataclass(frozen=True, slots=True)
class ContractSpec:
    """Declarative pre/post conditions for a named source function.

    Expression strings are Python expression source (``ast.parse(..., mode="eval")``)
    over function parameter names and the reserved name ``result``.
    """

    function_name: str
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    contract_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "function_name", _text(self.function_name, "function_name")
        )
        object.__setattr__(
            self,
            "preconditions",
            tuple(_text(item, "precondition") for item in self.preconditions),
        )
        object.__setattr__(
            self,
            "postconditions",
            tuple(_text(item, "postcondition") for item in self.postconditions),
        )
        contract_id = self.contract_id.strip() if isinstance(self.contract_id, str) else ""
        if not contract_id:
            contract_id = _safe_id("contract", self.function_name)
        object.__setattr__(self, "contract_id", contract_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "function_name": self.function_name,
            "postconditions": list(self.postconditions),
            "preconditions": list(self.preconditions),
        }


@dataclass(frozen=True, slots=True)
class SourceBinding:
    """Source identity and span map carried on every pipeline result."""

    source_ref_ids: tuple[str, ...]
    span_ids: tuple[str, ...]
    program_id: str
    language: str
    path: str
    content_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "language": self.language,
            "path": self.path,
            "program_id": self.program_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }


@dataclass(frozen=True, slots=True)
class PipelineResultBindings:
    """Mandatory bindings for every solver-facing pipeline outcome."""

    source: SourceBinding
    property_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    tool_ids: tuple[str, ...]
    bounds: Mapping[str, Any]
    translation_receipt_ids: tuple[str, ...]
    vc_set_ids: tuple[str, ...]
    parent_contract_ids: tuple[str, ...]
    schema_version: str = PIPELINE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "bounds": dict(self.bounds),
            "parent_contract_ids": list(self.parent_contract_ids),
            "property_ids": list(self.property_ids),
            "schema_version": self.schema_version,
            "source": self.source.to_dict(),
            "tool_ids": list(self.tool_ids),
            "translation_receipt_ids": list(self.translation_receipt_ids),
            "vc_set_ids": list(self.vc_set_ids),
        }


@dataclass(frozen=True, slots=True)
class ObligationSolveResult:
    """One VC obligation lowered to SMT and (optionally) solved differentially."""

    vc_obligation: VerificationObligation
    smt_obligation: SmtObligation
    compilation: SmtCompilation
    differential: SmtDifferentialReport | None
    property_id: str
    body_assumption_names: tuple[str, ...] = ()
    solver_executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_assumption_names": list(self.body_assumption_names),
            "compilation_id": self.compilation.compilation_id,
            "differential": (
                None if self.differential is None else self.differential.to_dict()
            ),
            "property_id": self.property_id,
            "script_digest": self.compilation.script.digest,
            "smt_obligation_id": self.smt_obligation.obligation_id,
            "solver_executed": self.solver_executed,
            "translation_receipt_id": self.compilation.receipt.receipt_id,
            "vc_obligation": self.vc_obligation.to_dict(),
            "verdict_classification": (
                None
                if self.differential is None
                else self.differential.classification.value
            ),
        }


@dataclass(frozen=True, slots=True)
class SourceToVerificationResult:
    """Complete vertical-slice outcome for one source snapshot."""

    status: PipelineStatus | str
    interface: str = SOURCE_TO_VERIFICATION_PIPELINE_INTERFACE
    schema_version: str = PIPELINE_SCHEMA_VERSION
    pipeline_version: str = PIPELINE_VERSION
    adapter: SourceAdapterResult | None = None
    program: ProgramIR | None = None
    contracts: tuple[ProgramContract, ...] = ()
    vc_sets: tuple[VerificationConditionSet, ...] = ()
    obligation_results: tuple[ObligationSolveResult, ...] = ()
    bindings: PipelineResultBindings | None = None
    unsupported_constructs: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    disagreement_quarantined: bool = False

    def __post_init__(self) -> None:
        status = (
            self.status
            if isinstance(self.status, PipelineStatus)
            else PipelineStatus(str(self.status))
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "contracts", tuple(self.contracts))
        object.__setattr__(self, "vc_sets", tuple(self.vc_sets))
        object.__setattr__(self, "obligation_results", tuple(self.obligation_results))
        object.__setattr__(
            self,
            "unsupported_constructs",
            tuple(sorted(set(self.unsupported_constructs))),
        )
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def proved(self) -> bool:
        if not self.obligation_results:
            return False
        for item in self.obligation_results:
            report = item.differential
            if report is None:
                return False
            if report.classification is not DifferentialClassification.AGREE_PROVED:
                return False
        return True

    @property
    def disproved(self) -> bool:
        return any(
            item.differential is not None
            and item.differential.classification
            is DifferentialClassification.AGREE_DISPROVED
            for item in self.obligation_results
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": None if self.adapter is None else self.adapter.to_dict(),
            "bindings": None if self.bindings is None else self.bindings.to_dict(),
            "contracts": [item.to_dict() for item in self.contracts],
            "diagnostics": list(self.diagnostics),
            "disagreement_quarantined": self.disagreement_quarantined,
            "disproved": self.disproved,
            "interface": self.interface,
            "obligation_results": [item.to_dict() for item in self.obligation_results],
            "pipeline_version": self.pipeline_version,
            "program_id": None if self.program is None else self.program.program_id,
            "proved": self.proved,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "unsupported_constructs": list(self.unsupported_constructs),
            "vc_sets": [item.to_dict() for item in self.vc_sets],
        }


class _ExpressionInjector:
    """Parse Python expression strings into ProgramExpression graphs."""

    def __init__(
        self,
        *,
        program: ProgramIR,
        function: ProgramFunction,
        source_ref_id: str,
        span_ids: Sequence[str],
    ) -> None:
        self.program = program
        self.function = function
        self.source_ref_id = source_ref_id
        self.span_ids = tuple(span_ids)
        self.symbols = {item.symbol_id: item for item in program.symbols}
        self.expressions = list(program.expressions)
        self._name_to_symbol: dict[str, str] = {}
        for symbol_id in function.scoped_symbol_ids:
            symbol = self.symbols.get(symbol_id)
            if symbol is not None:
                self._name_to_symbol[symbol.name] = symbol_id
        self._counter = 0

    def _next_id(self, kind: str) -> str:
        self._counter += 1
        return f"expr:pipeline:{kind}:{self._counter}:{self.function.name}"

    def _mapped(self) -> dict[str, tuple[str, ...]]:
        return _mapped(self.source_ref_id, self.span_ids)

    def inject(self, source: str) -> str:
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as error:
            raise PipelineError(
                f"contract expression is not valid Python: {source!r}: {error}"
            ) from error
        return self._lower(tree.body)

    def _lower(self, node: ast.AST) -> str:
        mapped = self._mapped()
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool):
                type_ref = "boolean"
            elif isinstance(value, int):
                type_ref = "integer"
            elif value is None:
                type_ref = "none"
            else:
                raise UnsupportedConstructError(
                    f"unsupported literal type in contract expression: {type(value).__name__}"
                )
            expr_id = self._next_id("lit")
            self.expressions.append(
                ProgramExpression(
                    expr_id,
                    ExpressionKind.LITERAL,
                    type_ref,
                    attributes={"value": value},
                    **mapped,
                )
            )
            return expr_id
        if isinstance(node, ast.Name):
            symbol_id = self._name_to_symbol.get(node.id)
            if symbol_id is None:
                raise PipelineError(
                    f"contract expression references unknown name {node.id!r} "
                    f"in function {self.function.name}"
                )
            symbol = self.symbols[symbol_id]
            kind = (
                ExpressionKind.RESULT
                if symbol.kind is SymbolKind.RESULT
                else ExpressionKind.SYMBOL
            )
            expr_id = self._next_id("name")
            self.expressions.append(
                ProgramExpression(
                    expr_id,
                    kind,
                    symbol.type_ref or "integer",
                    symbol_ids=(symbol_id,),
                    **mapped,
                )
            )
            return expr_id
        if isinstance(node, ast.UnaryOp):
            operand = self._lower(node.operand)
            if isinstance(node.op, ast.USub):
                operator = "neg"
            elif isinstance(node.op, ast.Not):
                operator = "not"
            elif isinstance(node.op, ast.UAdd):
                return operand
            else:
                raise UnsupportedConstructError(
                    f"unsupported unary operator {type(node.op).__name__}"
                )
            expr_id = self._next_id("unary")
            self.expressions.append(
                ProgramExpression(
                    expr_id,
                    ExpressionKind.UNARY,
                    "boolean" if operator == "not" else "integer",
                    operand_ids=(operand,),
                    evaluation_order=(operand,),
                    operator=operator,
                    **mapped,
                )
            )
            return expr_id
        if isinstance(node, ast.BinOp):
            left = self._lower(node.left)
            right = self._lower(node.right)
            op_map = {
                ast.Add: "add",
                ast.Sub: "sub",
                ast.Mult: "mul",
                ast.Div: "div",
                ast.FloorDiv: "floordiv",
                ast.Mod: "mod",
            }
            operator = op_map.get(type(node.op))
            if operator is None:
                raise UnsupportedConstructError(
                    f"unsupported binary operator {type(node.op).__name__}"
                )
            expr_id = self._next_id("bin")
            self.expressions.append(
                ProgramExpression(
                    expr_id,
                    ExpressionKind.BINARY,
                    "integer",
                    operand_ids=(left, right),
                    evaluation_order=(left, right),
                    operator=operator,
                    **mapped,
                )
            )
            return expr_id
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left = self._lower(node.left)
            right = self._lower(node.comparators[0])
            op_map = {
                ast.Eq: "eq",
                ast.NotEq: "ne",
                ast.Lt: "lt",
                ast.LtE: "le",
                ast.Gt: "gt",
                ast.GtE: "ge",
            }
            operator = op_map.get(type(node.ops[0]))
            if operator is None:
                raise UnsupportedConstructError(
                    f"unsupported comparison {type(node.ops[0]).__name__}"
                )
            expr_id = self._next_id("cmp")
            self.expressions.append(
                ProgramExpression(
                    expr_id,
                    ExpressionKind.BINARY,
                    "boolean",
                    operand_ids=(left, right),
                    evaluation_order=(left, right),
                    operator=operator,
                    **mapped,
                )
            )
            return expr_id
        if isinstance(node, ast.BoolOp) and len(node.values) >= 2:
            operator = "and" if isinstance(node.op, ast.And) else "or"
            current = self._lower(node.values[0])
            for value in node.values[1:]:
                right = self._lower(value)
                expr_id = self._next_id("bool")
                self.expressions.append(
                    ProgramExpression(
                        expr_id,
                        ExpressionKind.BINARY,
                        "boolean",
                        operand_ids=(current, right),
                        evaluation_order=(current, right),
                        operator=operator,
                        **mapped,
                    )
                )
                current = expr_id
            return current
        raise UnsupportedConstructError(
            f"unsupported construct in contract expression: {type(node).__name__}"
        )

    def program_with_expressions(self) -> ProgramIR:
        return replace(
            self.program,
            expressions=tuple(self.expressions),
            program_id="",
        )


class _SmtLowering:
    """Lower ProgramExpression DAGs and body semantics into SMT terms."""

    def __init__(self, program: ProgramIR) -> None:
        self.program = program
        self.symbols = {item.symbol_id: item for item in program.symbols}
        self.expressions = {item.expression_id: item for item in program.expressions}
        self.commands = {item.command_id: item for item in program.commands}
        self._cache: dict[str, SmtTerm] = {}
        self._fun_decls: dict[str, SmtFunDecl] = {}

    def fun_decls(self) -> tuple[SmtFunDecl, ...]:
        return tuple(sorted(self._fun_decls.values(), key=lambda item: item.name))

    def declare_symbol(self, symbol_id: str) -> str:
        symbol = self.symbols.get(symbol_id)
        if symbol is None:
            # Generated / synthetic symbol: declare as unconstrained Int.
            name = smt_sanitize(symbol_id, prefix="g")
            if name not in self._fun_decls:
                self._fun_decls[name] = SmtFunDecl(
                    name=name, range=INT_SORT, is_const=True
                )
            return name
        name = _symbol_smt_name(symbol)
        if name not in self._fun_decls:
            self._fun_decls[name] = SmtFunDecl(
                name=name,
                range=_sort_for_type_ref(symbol.type_ref),
                is_const=True,
            )
        return name

    def term_for_expression(self, expression_id: str) -> SmtTerm:
        if expression_id in self._cache:
            return self._cache[expression_id]
        expr = self.expressions.get(expression_id)
        if expr is None:
            raise PipelineError(f"unknown expression_id {expression_id!r}")
        term = self._lower_expression(expr)
        self._cache[expression_id] = term
        return term

    def _lower_expression(self, expr: ProgramExpression) -> SmtTerm:
        kind = expr.kind
        if kind is ExpressionKind.LITERAL:
            value = expr.attributes.get("value") if expr.attributes else None
            if isinstance(value, bool):
                return term_true() if value else term_false()
            if isinstance(value, int) and not isinstance(value, bool):
                return term_int(value)
            if value is None:
                return term_int(0)
            raise UnsupportedConstructError(
                f"literal expression {expr.expression_id} has unsupported value {value!r}"
            )
        if kind in {ExpressionKind.SYMBOL, ExpressionKind.RESULT, ExpressionKind.OLD}:
            if not expr.symbol_ids:
                raise PipelineError(
                    f"expression {expr.expression_id} of kind {kind.value} lacks symbol_ids"
                )
            name = self.declare_symbol(expr.symbol_ids[0])
            return term_symbol(name)
        if kind is ExpressionKind.UNARY:
            if len(expr.operand_ids) != 1:
                raise PipelineError(
                    f"unary expression {expr.expression_id} requires one operand"
                )
            operand = self.term_for_expression(expr.operand_ids[0])
            if expr.operator == "pos":
                return operand
            smt_kind = _UNARY_OP_TO_SMT.get(expr.operator)
            if smt_kind is None:
                raise UnsupportedConstructError(
                    f"unsupported unary operator {expr.operator!r}"
                )
            return SmtTerm(smt_kind, arguments=(operand,))
        if kind is ExpressionKind.BINARY:
            if len(expr.operand_ids) != 2:
                raise PipelineError(
                    f"binary expression {expr.expression_id} requires two operands"
                )
            left = self.term_for_expression(expr.operand_ids[0])
            right = self.term_for_expression(expr.operand_ids[1])
            if expr.operator == "ne":
                return term_not(term_eq(left, right))
            smt_kind = _BINARY_OP_TO_SMT.get(expr.operator)
            if smt_kind is None:
                raise UnsupportedConstructError(
                    f"unsupported binary operator {expr.operator!r}"
                )
            return SmtTerm(smt_kind, arguments=(left, right))
        if kind is ExpressionKind.CONDITIONAL:
            if len(expr.operand_ids) != 3:
                raise PipelineError(
                    f"conditional expression {expr.expression_id} requires three operands"
                )
            cond = self.term_for_expression(expr.operand_ids[0])
            then = self.term_for_expression(expr.operand_ids[1])
            else_ = self.term_for_expression(expr.operand_ids[2])
            return SmtTerm(SmtTermKind.ITE, arguments=(cond, then, else_))
        raise UnsupportedConstructError(
            f"expression kind {kind.value} cannot be lowered to SMT "
            f"(expression_id={expr.expression_id})"
        )

    def body_assumptions(
        self, function: ProgramFunction
    ) -> tuple[SmtNamedAssertion, ...]:
        """Encode straight-line body facts: assignments and result-return equalities."""

        assumptions: list[SmtNamedAssertion] = []
        index = 0
        for command_id in function.cfg.command_ids:
            command = self.commands.get(command_id)
            if command is None:
                continue
            if command.kind is CommandKind.ASSIGN:
                if not command.target_symbol_ids or not command.expression_ids:
                    continue
                target = self.declare_symbol(command.target_symbol_ids[0])
                value = self.term_for_expression(command.expression_ids[0])
                assumptions.append(
                    SmtNamedAssertion(
                        formula=term_eq(term_symbol(target), value),
                        name=f"body_assign_{index}",
                    )
                )
                index += 1
            elif command.kind is CommandKind.RETURN:
                if not command.expression_ids or not function.result_symbol_id:
                    continue
                result_name = self.declare_symbol(function.result_symbol_id)
                value = self.term_for_expression(command.expression_ids[0])
                assumptions.append(
                    SmtNamedAssertion(
                        formula=term_eq(term_symbol(result_name), value),
                        name=f"body_return_{index}",
                    )
                )
                index += 1
            elif command.kind is CommandKind.ASSUME:
                # Path-condition fragments retained as named assumptions.
                for expr_id in command.expression_ids:
                    try:
                        formula = self.term_for_expression(expr_id)
                    except UnsupportedConstructError:
                        continue
                    assumptions.append(
                        SmtNamedAssertion(
                            formula=formula,
                            name=f"body_assume_{index}",
                        )
                    )
                    index += 1
            elif command.kind in {
                CommandKind.CALL,
                CommandKind.THROW,
                CommandKind.HAVOC,
                CommandKind.ALLOCATE,
                CommandKind.DEALLOCATE,
                CommandKind.ATOMIC,
                CommandKind.UNDEFINED,
            }:
                raise UnsupportedConstructError(
                    f"command kind {command.kind.value} cannot be encoded in the "
                    "straight-line SMT body fragment"
                )
        return tuple(assumptions)


def _function_by_name(program: ProgramIR, name: str) -> ProgramFunction:
    matches = [item for item in program.functions if item.name == name]
    if not matches:
        raise PipelineError(f"no function named {name!r} in adapted program")
    if len(matches) > 1:
        raise PipelineError(f"ambiguous function name {name!r}")
    return matches[0]


def _primary_source_maps(program: ProgramIR) -> tuple[str, tuple[str, ...]]:
    if not program.sources:
        raise PipelineError("adapted program has no source references")
    source_ref_id = program.sources[0].ref_id
    span_ids = tuple(item.span_id for item in program.spans[:1])
    return source_ref_id, span_ids


def attach_contract_specs(
    program: ProgramIR,
    specs: Sequence[ContractSpec],
) -> tuple[ProgramIR, tuple[ProgramContract, ...]]:
    """Inject contract expression graphs and build validating ProgramContracts."""

    if not specs:
        raise PipelineError("at least one ContractSpec is required")
    current = program
    contracts: list[ProgramContract] = []
    source_ref_id, span_ids = _primary_source_maps(current)
    mapped = _mapped(source_ref_id, span_ids)

    for spec in specs:
        function = _function_by_name(current, spec.function_name)
        injector = _ExpressionInjector(
            program=current,
            function=function,
            source_ref_id=source_ref_id,
            span_ids=span_ids or function.span_ids,
        )
        pre_ids: list[str] = []
        post_ids: list[str] = []
        for text in spec.preconditions:
            pre_ids.append(injector.inject(text))
        for text in spec.postconditions:
            post_ids.append(injector.inject(text))
        if not post_ids and not pre_ids:
            raise PipelineError(
                f"contract for {spec.function_name} requires at least one "
                "precondition or postcondition"
            )
        current = injector.program_with_expressions()
        preconditions = tuple(
            ContractClause(
                clause_id=_safe_id("clause", "pre", spec.function_name, str(index)),
                kind=ContractClauseKind.PRECONDITION,
                expression_id=expression_id,
                statement=f"precondition[{index}] of {spec.function_name}",
                **mapped,
            )
            for index, expression_id in enumerate(pre_ids)
        )
        postconditions = tuple(
            ContractClause(
                clause_id=_safe_id("clause", "post", spec.function_name, str(index)),
                kind=ContractClauseKind.POSTCONDITION,
                expression_id=expression_id,
                statement=f"postcondition[{index}] of {spec.function_name}",
                **mapped,
            )
            for index, expression_id in enumerate(post_ids)
        )
        # Re-resolve function after expression injection (ids stable).
        function = _function_by_name(current, spec.function_name)
        contracts.append(
            ProgramContract(
                contract_id=spec.contract_id,
                function_id=function.function_id,
                preconditions=preconditions,
                postconditions=postconditions,
                frame=FrameCondition(allows_all_reads=True, allows_all_writes=True),
                effects=function.effects,
                purity=function.purity if function.purity is not Purity.UNKNOWN else Purity.PURE,
                **mapped,
            )
        )
    return current, tuple(contracts)


def lower_vc_obligation_to_smt(
    program: ProgramIR,
    obligation: VerificationObligation,
    *,
    include_body_semantics: bool = True,
    property_id: str = "",
) -> tuple[SmtObligation, tuple[str, ...]]:
    """Lower one VC obligation into a backend-neutral :class:`SmtObligation`.

    Path/contract assumptions become named SMT assumptions; goals become the
    theorem goal.  Straight-line body facts (assignments, returns) are added as
    additional named assumptions so solvers can generate their own witnesses.
    """

    functions = {item.function_id: item for item in program.functions}
    function = functions.get(obligation.function_id)
    if function is None:
        raise PipelineError(
            f"obligation {obligation.obligation_id} references unknown function "
            f"{obligation.function_id}"
        )
    lowering = _SmtLowering(program)
    named: list[SmtNamedAssertion] = []
    body_names: list[str] = []

    if include_body_semantics:
        for assumption in lowering.body_assumptions(function):
            named.append(assumption)
            body_names.append(assumption.name)

    for index, expression_id in enumerate(obligation.assumption_expression_ids):
        named.append(
            SmtNamedAssertion(
                formula=lowering.term_for_expression(expression_id),
                name=f"assume_{index}",
            )
        )
    for index, expression_id in enumerate(obligation.path_condition_expression_ids):
        if expression_id in obligation.assumption_expression_ids:
            continue
        named.append(
            SmtNamedAssertion(
                formula=lowering.term_for_expression(expression_id),
                name=f"path_{index}",
            )
        )

    goal_ids = obligation.goal_expression_ids or obligation.assumption_expression_ids
    if not goal_ids:
        raise PipelineError(
            f"obligation {obligation.obligation_id} has no goal expressions to solve"
        )
    goal_terms = [lowering.term_for_expression(item) for item in goal_ids]
    goal = goal_terms[0] if len(goal_terms) == 1 else term_and(*goal_terms)

    prop = property_id or f"property:{obligation.obligation_id}"
    smt_obligation = SmtObligation(
        obligation_id=f"smt:{obligation.obligation_id}",
        query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
        features=("verification_conditions", "arithmetic", "equality"),
        goal=goal,
        assumptions=tuple(named),
        functions=lowering.fun_decls(),
        request_model=True,
        request_unsat_core=True,
        property_ids=(prop,),
        attributes=FrozenMap(
            {
                "vc_obligation_id": obligation.obligation_id,
                "vc_rule": obligation.rule.value
                if isinstance(obligation.rule, VCRuleKind)
                else str(obligation.rule),
                "parent_contract_id": obligation.parent_contract_id,
                "function_id": obligation.function_id,
                "source_construct_id": obligation.source_construct_id,
                "source_ref_ids": list(obligation.source_ref_ids),
                "span_ids": list(obligation.span_ids),
            }
        ),
    )
    return smt_obligation, tuple(body_names)


@dataclass(frozen=True, slots=True)
class SourceToVerificationPipeline:
    """Production composition of source → ProgramIR → VC → SMT → Z3/CVC5.

    Interface: ``SourceToVerificationPipeline@1``.
    """

    INTERFACE: ClassVar[str] = SOURCE_TO_VERIFICATION_PIPELINE_INTERFACE

    compiler: SoftwareVerificationSMTCompiler | None = None
    z3_backend: SoftwareVerificationSmtBackend | None = None
    cvc5_backend: SoftwareVerificationSmtBackend | None = None
    bounds: ExecutionBounds | None = None
    fail_on_unsupported: bool = True
    execute_solvers: bool = True
    solver_rules: tuple[VCRuleKind, ...] = (
        VCRuleKind.POSTCONDITION_NORMAL,
        VCRuleKind.ASSERT,
    )

    def __post_init__(self) -> None:
        if self.compiler is None:
            object.__setattr__(self, "compiler", SoftwareVerificationSMTCompiler())
        if self.bounds is None:
            object.__setattr__(
                self,
                "bounds",
                ExecutionBounds(
                    timeout_ms=10_000,
                    max_steps=100_000,
                    max_memory_bytes=128 * 1024 * 1024,
                    max_output_bytes=256 * 1024,
                ),
            )
        rules = tuple(
            item if isinstance(item, VCRuleKind) else VCRuleKind(str(item))
            for item in self.solver_rules
        )
        if not rules:
            raise PipelineError("solver_rules must not be empty")
        object.__setattr__(self, "solver_rules", rules)

    def run(
        self,
        source: str,
        *,
        path: str = "",
        language: str = "",
        contracts: Sequence[ContractSpec | ProgramContract] | None = None,
        loop_contracts: Sequence[LoopContract] = (),
        revision: str = "workspace:local",
    ) -> SourceToVerificationResult:
        """Execute the full vertical slice for one source snapshot."""

        if not isinstance(source, str):
            raise PipelineError("source must be text")

        adapter = adapt_source_to_software_verification(
            source,
            path=path,
            language=language,
            revision=revision,
        )
        diagnostics: list[str] = [
            item.message for item in adapter.diagnostics if getattr(item, "message", None)
        ]
        unsupported = list(adapter.unsupported_constructs)

        if adapter.status is SourceAdapterStatus.UNSUPPORTED or adapter.program is None:
            return SourceToVerificationResult(
                status=PipelineStatus.UNSUPPORTED,
                adapter=adapter,
                unsupported_constructs=tuple(unsupported),
                diagnostics=tuple(diagnostics)
                + ("source adapter did not produce a ProgramIR",),
            )

        if unsupported and self.fail_on_unsupported:
            return SourceToVerificationResult(
                status=PipelineStatus.UNSUPPORTED,
                adapter=adapter,
                program=adapter.program,
                unsupported_constructs=tuple(unsupported),
                diagnostics=tuple(diagnostics)
                + (
                    "unsupported constructs present; failing closed "
                    f"({', '.join(sorted(set(unsupported)))})",
                ),
            )

        try:
            program, resolved_contracts = self._resolve_contracts(
                adapter.program, contracts
            )
        except (PipelineError, UnsupportedConstructError) as error:
            return SourceToVerificationResult(
                status=PipelineStatus.ERROR,
                adapter=adapter,
                program=adapter.program,
                unsupported_constructs=tuple(unsupported),
                diagnostics=tuple(diagnostics) + (str(error),),
            )

        vc_sets: list[VerificationConditionSet] = []
        try:
            for contract in resolved_contracts:
                vc_sets.append(
                    generate_verification_conditions(
                        program, contract, loop_contracts=loop_contracts
                    )
                )
        except Exception as error:  # noqa: BLE001 - surface as pipeline diagnostic
            return SourceToVerificationResult(
                status=PipelineStatus.ERROR,
                adapter=adapter,
                program=program,
                contracts=tuple(resolved_contracts),
                unsupported_constructs=tuple(unsupported),
                diagnostics=tuple(diagnostics) + (f"VC generation failed: {error}",),
            )

        obligation_results: list[ObligationSolveResult] = []
        disagreement = False
        try:
            for vc_set, contract in zip(vc_sets, resolved_contracts):
                for obligation in vc_set.obligations:
                    rule = (
                        obligation.rule
                        if isinstance(obligation.rule, VCRuleKind)
                        else VCRuleKind(str(obligation.rule))
                    )
                    if rule not in self.solver_rules:
                        continue
                    property_id = (
                        f"property:{contract.contract_id}:{obligation.obligation_id}"
                    )
                    smt_obl, body_names = lower_vc_obligation_to_smt(
                        program,
                        obligation,
                        include_body_semantics=True,
                        property_id=property_id,
                    )
                    compilation = self.compiler.compile(smt_obl)  # type: ignore[union-attr]
                    differential: SmtDifferentialReport | None = None
                    if self.execute_solvers:
                        differential = run_z3_cvc5_differential(
                            compilation,
                            bounds=self.bounds,
                            z3_backend=self.z3_backend,
                            cvc5_backend=self.cvc5_backend,
                            compiler=self.compiler,
                        )
                        if (
                            differential.classification
                            is DifferentialClassification.DISAGREE
                        ):
                            disagreement = True
                    obligation_results.append(
                        ObligationSolveResult(
                            vc_obligation=obligation,
                            smt_obligation=smt_obl,
                            compilation=compilation,
                            differential=differential,
                            property_id=property_id,
                            body_assumption_names=body_names,
                            solver_executed=self.execute_solvers,
                        )
                    )
        except UnsupportedConstructError as error:
            return SourceToVerificationResult(
                status=PipelineStatus.UNSUPPORTED,
                adapter=adapter,
                program=program,
                contracts=tuple(resolved_contracts),
                vc_sets=tuple(vc_sets),
                unsupported_constructs=tuple(unsupported) + (str(error),),
                diagnostics=tuple(diagnostics) + (str(error),),
            )
        except Exception as error:  # noqa: BLE001
            return SourceToVerificationResult(
                status=PipelineStatus.ERROR,
                adapter=adapter,
                program=program,
                contracts=tuple(resolved_contracts),
                vc_sets=tuple(vc_sets),
                unsupported_constructs=tuple(unsupported),
                diagnostics=tuple(diagnostics) + (f"SMT/solver stage failed: {error}",),
            )

        bindings = self._bindings(
            adapter=adapter,
            program=program,
            contracts=tuple(resolved_contracts),
            vc_sets=tuple(vc_sets),
            obligation_results=tuple(obligation_results),
        )

        if disagreement:
            status = PipelineStatus.DISAGREEMENT_QUARANTINED
        elif not obligation_results:
            status = PipelineStatus.PARTIAL
            diagnostics.append("no solver-facing VC obligations selected")
        elif unsupported:
            status = PipelineStatus.PARTIAL
        else:
            status = PipelineStatus.SUCCESS

        return SourceToVerificationResult(
            status=status,
            adapter=adapter,
            program=program,
            contracts=tuple(resolved_contracts),
            vc_sets=tuple(vc_sets),
            obligation_results=tuple(obligation_results),
            bindings=bindings,
            unsupported_constructs=tuple(unsupported),
            diagnostics=tuple(diagnostics),
            disagreement_quarantined=disagreement,
        )

    def _resolve_contracts(
        self,
        program: ProgramIR,
        contracts: Sequence[ContractSpec | ProgramContract] | None,
    ) -> tuple[ProgramIR, tuple[ProgramContract, ...]]:
        if not contracts:
            raise PipelineError(
                "contracts are required: pass ContractSpec values describing "
                "pre/post conditions for the target function(s)"
            )
        specs: list[ContractSpec] = []
        ready: list[ProgramContract] = []
        for item in contracts:
            if isinstance(item, ContractSpec):
                specs.append(item)
            elif isinstance(item, ProgramContract):
                ready.append(item)
            elif isinstance(item, Mapping):
                if "function_name" in item:
                    specs.append(
                        ContractSpec(
                            function_name=str(item["function_name"]),
                            preconditions=tuple(item.get("preconditions", ())),
                            postconditions=tuple(item.get("postconditions", ())),
                            contract_id=str(item.get("contract_id", "")),
                        )
                    )
                else:
                    ready.append(ProgramContract.from_dict(item))
            else:
                raise PipelineError(
                    f"unsupported contract entry type {type(item).__name__}"
                )
        if specs:
            program, attached = attach_contract_specs(program, specs)
            ready.extend(attached)
        if not ready:
            raise PipelineError("no contracts resolved")
        return program, tuple(ready)

    def _bindings(
        self,
        *,
        adapter: SourceAdapterResult,
        program: ProgramIR,
        contracts: tuple[ProgramContract, ...],
        vc_sets: tuple[VerificationConditionSet, ...],
        obligation_results: tuple[ObligationSolveResult, ...],
    ) -> PipelineResultBindings:
        source_ref_ids = tuple(item.ref_id for item in program.sources)
        span_ids = tuple(item.span_id for item in program.spans)
        content_sha256 = ""
        if program.sources:
            content_sha256 = getattr(program.sources[0], "content_sha256", "") or ""
        property_ids = tuple(
            sorted({item.property_id for item in obligation_results})
        )
        assumption_ids: list[str] = []
        if adapter.document is not None:
            assumption_ids.extend(
                item.assumption_id for item in adapter.document.assumptions
            )
        for contract in contracts:
            assumption_ids.extend(
                clause.expression_id for clause in contract.preconditions
            )
        tool_ids: list[str] = [SMT_COMPILER_ID]
        translation_ids: list[str] = []
        for item in obligation_results:
            translation_ids.append(item.compilation.receipt.receipt_id)
            if item.differential is not None:
                tool_ids.append(item.differential.left.backend_id)
                tool_ids.append(item.differential.right.backend_id)
        bounds_payload = {
            "timeout_ms": self.bounds.timeout_ms,  # type: ignore[union-attr]
            "max_steps": self.bounds.max_steps,  # type: ignore[union-attr]
            "max_memory_bytes": getattr(self.bounds, "max_memory_bytes", 0),
            "max_output_bytes": getattr(self.bounds, "max_output_bytes", 0),
        }
        return PipelineResultBindings(
            source=SourceBinding(
                source_ref_ids=source_ref_ids,
                span_ids=span_ids,
                program_id=program.program_id,
                language=adapter.language,
                path=adapter.path or "",
                content_sha256=content_sha256,
            ),
            property_ids=property_ids,
            assumption_ids=tuple(dict.fromkeys(assumption_ids)),
            tool_ids=tuple(dict.fromkeys(tool_ids)),
            bounds=bounds_payload,
            translation_receipt_ids=tuple(dict.fromkeys(translation_ids)),
            vc_set_ids=tuple(item.vc_set_id for item in vc_sets),
            parent_contract_ids=tuple(item.contract_id for item in contracts),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execute_solvers": self.execute_solvers,
            "fail_on_unsupported": self.fail_on_unsupported,
            "interface": self.INTERFACE,
            "pipeline_version": PIPELINE_VERSION,
            "schema_version": PIPELINE_SCHEMA_VERSION,
            "solver_rules": [
                item.value if isinstance(item, VCRuleKind) else str(item)
                for item in self.solver_rules
            ],
        }


def run_source_to_verification_pipeline(
    source: str,
    *,
    path: str = "",
    language: str = "",
    contracts: Sequence[ContractSpec | ProgramContract] | None = None,
    **kwargs: Any,
) -> SourceToVerificationResult:
    """Module-level convenience wrapper around :class:`SourceToVerificationPipeline`."""

    pipeline_kwargs = {
        key: kwargs.pop(key)
        for key in (
            "compiler",
            "z3_backend",
            "cvc5_backend",
            "bounds",
            "fail_on_unsupported",
            "execute_solvers",
            "solver_rules",
        )
        if key in kwargs
    }
    return SourceToVerificationPipeline(**pipeline_kwargs).run(
        source,
        path=path,
        language=language,
        contracts=contracts,
        **kwargs,
    )


__all__ = [
    "PIPELINE_SCHEMA_VERSION",
    "PIPELINE_VERSION",
    "SOURCE_TO_VERIFICATION_PIPELINE_INTERFACE",
    "ContractSpec",
    "ObligationSolveResult",
    "PipelineError",
    "PipelineResultBindings",
    "PipelineStatus",
    "SourceBinding",
    "SourceToVerificationPipeline",
    "SourceToVerificationResult",
    "UnsupportedConstructError",
    "attach_contract_specs",
    "lower_vc_obligation_to_smt",
    "run_source_to_verification_pipeline",
]
