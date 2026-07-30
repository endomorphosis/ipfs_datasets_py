"""Lower supported source languages into the shared software-verification IR.

``SourceSoftwareVerificationAdapter@1`` converts admitted Python and
JavaScript/TypeScript subsets into source-bound :class:`ProgramIR` documents
and :class:`SoftwareVerificationIR` envelopes.  Supervisor program-AST evidence
is reused for accounting; unsupported syntax is retained as diagnostics rather
than silently dropped.  Adapter success never implies a prover verdict —
canonical backend request shells are emitted for downstream SMT/VC work.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Final

from ipfs_datasets_py.logic.families.models import BoundednessKind
from ipfs_datasets_py.logic.ir_core.artifacts import Artifact, ArtifactRole
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLocation,
    DiagnosticSeverity,
)
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan

from .ir import (
    DeclarationKind,
    SoftwareVerificationIR,
    VerificationBound,
    VerificationDeclaration,
    unsupported_construct_diagnostic,
)
from .program import (
    BasicBlock,
    CommandKind,
    ControlFlowGraph,
    EffectSummary,
    ExpressionKind,
    ProgramCommand,
    ProgramExpression,
    ProgramFunction,
    ProgramIR,
    ProgramSymbol,
    ProgramValidationError,
    Purity,
    SymbolKind,
)
from .properties import (
    AssumptionKind,
    PropertyKind,
    VerificationAssumption,
    VerificationProperty,
)


SOURCE_SOFTWARE_VERIFICATION_ADAPTER: Final = "SourceSoftwareVerificationAdapter@1"
SOURCE_ADAPTER_VERSION: Final = "software-verification-source-adapter/v1"
SOURCE_ADAPTER_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software-verification/source-adapter-result@1"
)
CANONICAL_BACKEND_REQUEST_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software-verification/canonical-backend-request@1"
)

_ID_SAFE = re.compile(r"[^A-Za-z0-9._:/-]+")
_PYTHON_MEDIA = {
    "python": "text/x-python",
    "javascript": "text/javascript",
    "jsx": "text/javascript",
    "typescript": "application/typescript",
    "tsx": "application/typescript",
}
_SUPPORTED_LANGUAGES = frozenset(_PYTHON_MEDIA)

# Python constructs the structural lowerer admits in v1.
_PYTHON_SUPPORTED_STMTS = (
    ast.FunctionDef,
    ast.Return,
    ast.Assign,
    ast.AnnAssign,
    ast.If,
    ast.Pass,
    ast.Expr,
)
_PYTHON_SUPPORTED_EXPRS = (
    ast.Constant,
    ast.Name,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.BoolOp,
    ast.Call,
    ast.Attribute,
)


class SourceAdapterError(ValueError):
    """Raised when a source adaptation request is malformed."""


class SourceAdapterStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise SourceAdapterError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise SourceAdapterError(f"{label} must not contain NUL bytes")
    return value


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def _safe_id(prefix: str, *parts: str) -> str:
    body = ".".join(_ID_SAFE.sub("_", part) for part in parts if part)
    body = body.strip("._:/-") or "anon"
    candidate = f"{prefix}:{body}"
    if len(candidate) > 256:
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:24]
        candidate = f"{prefix}:{digest}"
    return candidate


def _line_byte_offsets(source: str) -> list[int]:
    offsets = [0]
    total = 0
    for line in source.splitlines(keepends=True):
        total += len(line.encode("utf-8", errors="surrogatepass"))
        offsets.append(total)
    return offsets


def _ast_byte_span(
    node: ast.AST,
    *,
    source: str,
    offsets: Sequence[int],
) -> tuple[int, int, int, int, int, int]:
    lineno = int(getattr(node, "lineno", 1) or 1)
    end_lineno = int(getattr(node, "end_lineno", lineno) or lineno)
    col = int(getattr(node, "col_offset", 0) or 0)
    end_col = int(getattr(node, "end_col_offset", col) or col)
    start_line_idx = max(0, lineno - 1)
    end_line_idx = max(0, end_lineno - 1)
    if start_line_idx >= len(offsets):
        start_byte = 0
    else:
        start_byte = offsets[start_line_idx] + len(
            source.splitlines(keepends=True)[start_line_idx][:col].encode(
                "utf-8", errors="surrogatepass"
            )
            if start_line_idx < len(source.splitlines(keepends=True))
            else b""
        )
    if end_line_idx >= len(offsets):
        end_byte = len(source.encode("utf-8", errors="surrogatepass"))
    else:
        lines = source.splitlines(keepends=True)
        if end_line_idx < len(lines):
            end_byte = offsets[end_line_idx] + len(
                lines[end_line_idx][:end_col].encode("utf-8", errors="surrogatepass")
            )
        else:
            end_byte = offsets[min(end_line_idx, len(offsets) - 1)]
    if end_byte < start_byte:
        end_byte = start_byte
    return start_byte, end_byte, lineno, col + 1, end_lineno, max(1, end_col)


def _source_ref(
    *,
    path: str,
    source: str,
    language: str,
    revision: str = "workspace:local",
) -> SourceRef:
    digest = _sha256_hex(source)
    posix = PurePosixPath(path.replace("\\", "/") or f"snippet.{language}")
    return SourceRef(
        ref_id=_safe_id("source", str(posix)),
        source_uri=f"file:///{posix.as_posix().lstrip('/')}",
        source_id=posix.name or f"snippet.{language}",
        source_revision=revision,
        content_sha256=digest,
        metadata={"language": language, "path": posix.as_posix()},
    )


def _make_span(
    *,
    span_id: str,
    source_ref_id: str,
    start_byte: int,
    end_byte: int,
    start_line: int,
    start_column: int,
    end_line: int,
    end_column: int,
) -> SourceSpan:
    return SourceSpan(
        span_id=span_id,
        source_ref_id=source_ref_id,
        start_byte=start_byte,
        end_byte=max(end_byte, start_byte),
        start_line=start_line,
        start_column=start_column,
        end_line=end_line,
        end_column=end_column,
    )


def _mapped(source_ref_id: str, span_id: str) -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (source_ref_id,), "span_ids": (span_id,)}


def _load_program_ast_adapter():
    try:
        from ipfs_accelerate_py.agent_supervisor.program_ast_adapters import (  # type: ignore
            adapt_program_source,
            detect_program_language,
        )
    except Exception:  # pragma: no cover - exercised when supervisor is unavailable
        return None, None
    return adapt_program_source, detect_program_language


@dataclass(frozen=True, slots=True)
class CanonicalBackendRequest:
    """Provider-neutral request shell for a shared verification obligation."""

    request_id: str
    goal_kind: str
    subject_ids: tuple[str, ...]
    obligation_statement: str
    logic_family: str = "smt"
    theory_tags: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema: str = CANONICAL_BACKEND_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _text(self.request_id, "request_id"))
        object.__setattr__(self, "goal_kind", _text(self.goal_kind, "goal_kind"))
        object.__setattr__(
            self,
            "obligation_statement",
            _text(self.obligation_statement, "obligation_statement"),
        )
        object.__setattr__(self, "logic_family", _text(self.logic_family, "logic_family"))
        subjects = tuple(sorted({_text(item, "subject_ids item") for item in self.subject_ids}))
        object.__setattr__(self, "subject_ids", subjects)
        tags = tuple(sorted({_text(item, "theory_tags item") for item in self.theory_tags}))
        object.__setattr__(self, "theory_tags", tags)
        sources = tuple(
            sorted({_text(item, "source_ref_ids item") for item in self.source_ref_ids})
        )
        object.__setattr__(self, "source_ref_ids", sources)
        attrs = (
            self.attributes
            if isinstance(self.attributes, FrozenMap)
            else FrozenMap(self.attributes)
        )
        object.__setattr__(self, "attributes", attrs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "goal_kind": self.goal_kind,
            "logic_family": self.logic_family,
            "obligation_statement": self.obligation_statement,
            "request_id": self.request_id,
            "schema": self.schema,
            "source_ref_ids": list(self.source_ref_ids),
            "subject_ids": list(self.subject_ids),
            "theory_tags": list(self.theory_tags),
        }


@dataclass(frozen=True, slots=True)
class SourceAdapterResult:
    """Accounted outcome of one source-to-shared-IR adaptation."""

    status: SourceAdapterStatus | str
    language: str
    path: str
    document: SoftwareVerificationIR | None = None
    program: ProgramIR | None = None
    evidence: Any = None
    backend_requests: tuple[CanonicalBackendRequest, ...] = ()
    unsupported_constructs: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    adapter_version: str = SOURCE_ADAPTER_VERSION
    interface: str = SOURCE_SOFTWARE_VERIFICATION_ADAPTER
    schema: str = SOURCE_ADAPTER_SCHEMA

    def __post_init__(self) -> None:
        status = (
            self.status
            if isinstance(self.status, SourceAdapterStatus)
            else SourceAdapterStatus(str(self.status))
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "language", str(self.language or "unknown"))
        object.__setattr__(self, "path", str(self.path or "").replace("\\", "/"))
        object.__setattr__(
            self,
            "backend_requests",
            tuple(self.backend_requests),
        )
        object.__setattr__(
            self,
            "unsupported_constructs",
            tuple(sorted(set(self.unsupported_constructs))),
        )
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def supported(self) -> bool:
        return self.status in {
            SourceAdapterStatus.SUCCESS,
            SourceAdapterStatus.PARTIAL,
        }

    @property
    def fake_backend_success(self) -> bool:
        """Compatibility probe: adapters never claim prover success."""

        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_version": self.adapter_version,
            "backend_requests": [item.to_dict() for item in self.backend_requests],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document": self.document.to_dict() if self.document is not None else None,
            "evidence": (
                self.evidence.to_dict()
                if self.evidence is not None and hasattr(self.evidence, "to_dict")
                else None
            ),
            "fake_backend_success": self.fake_backend_success,
            "interface": self.interface,
            "language": self.language,
            "path": self.path,
            "program": self.program.to_dict() if self.program is not None else None,
            "schema": self.schema,
            "status": self.status.value,
            "unsupported_constructs": list(self.unsupported_constructs),
        }


class _PythonLowering:
    """Lower a supported Python subset into ProgramIR fragments."""

    def __init__(
        self,
        *,
        source: str,
        source_ref: SourceRef,
        path: str,
    ) -> None:
        self.source = source
        self.source_ref = source_ref
        self.path = path
        self.offsets = _line_byte_offsets(source)
        self.spans: list[SourceSpan] = []
        self.symbols: list[ProgramSymbol] = []
        self.expressions: list[ProgramExpression] = []
        self.commands: list[ProgramCommand] = []
        self.functions: list[ProgramFunction] = []
        self.declarations: list[VerificationDeclaration] = []
        self.unsupported: list[str] = []
        self.diagnostics: list[Diagnostic] = []
        self._counter = 0
        self._symbol_index: dict[str, str] = {}

    def _next(self, kind: str) -> str:
        self._counter += 1
        return f"{kind}:{self._counter}"

    def _span_for(self, node: ast.AST, *, label: str) -> str:
        start_byte, end_byte, sl, sc, el, ec = _ast_byte_span(
            node, source=self.source, offsets=self.offsets
        )
        self._counter += 1
        span_id = _safe_id("span", label, str(self._counter))
        self.spans.append(
            _make_span(
                span_id=span_id,
                source_ref_id=self.source_ref.ref_id,
                start_byte=start_byte,
                end_byte=end_byte,
                start_line=sl,
                start_column=sc,
                end_line=el,
                end_column=ec,
            )
        )
        return span_id

    def _retain(self, construct: str, node: ast.AST, *, subject_ids: Sequence[str]) -> None:
        if construct not in self.unsupported:
            self.unsupported.append(construct)
        span_id = self._span_for(node, label=construct.replace(".", "-"))
        # Diagnostic subjects must be semantic ids (declarations/properties/…),
        # never source ref ids.
        subjects = tuple(
            item for item in subject_ids if item and not str(item).startswith("source:")
        )
        self.diagnostics.append(
            unsupported_construct_diagnostic(
                construct=construct,
                subject_ids=subjects,
                source_ref_ids=(self.source_ref.ref_id,),
                span_ids=(span_id,),
                remediation="Retain for later language-feature work; do not invent semantics.",
            )
        )

    def _symbol(
        self,
        name: str,
        kind: SymbolKind,
        type_ref: str,
        span_id: str,
        *,
        function: str = "",
    ) -> str:
        key = f"{function}:{name}:{kind.value}"
        existing = self._symbol_index.get(key)
        if existing:
            return existing
        symbol_id = _safe_id("symbol", function or "module", name, kind.value)
        self.symbols.append(
            ProgramSymbol(
                symbol_id,
                name,
                type_ref,
                kind,
                **_mapped(self.source_ref.ref_id, span_id),
            )
        )
        self._symbol_index[key] = symbol_id
        return symbol_id

    def _literal(self, value: Any, span_id: str, type_ref: str = "any") -> str:
        expr_id = self._next("expr")
        self.expressions.append(
            ProgramExpression(
                expr_id,
                ExpressionKind.LITERAL,
                type_ref,
                attributes={"value": value if isinstance(value, (str, int, float, bool)) or value is None else str(value)},
                **_mapped(self.source_ref.ref_id, span_id),
            )
        )
        return expr_id

    def _name_expr(self, symbol_id: str, span_id: str, type_ref: str = "any") -> str:
        expr_id = self._next("expr")
        self.expressions.append(
            ProgramExpression(
                expr_id,
                ExpressionKind.SYMBOL,
                type_ref,
                symbol_ids=(symbol_id,),
                **_mapped(self.source_ref.ref_id, span_id),
            )
        )
        return expr_id

    def _binop(
        self,
        operator: str,
        left_id: str,
        right_id: str,
        span_id: str,
        type_ref: str = "any",
    ) -> str:
        expr_id = self._next("expr")
        self.expressions.append(
            ProgramExpression(
                expr_id,
                ExpressionKind.BINARY,
                type_ref,
                operand_ids=(left_id, right_id),
                evaluation_order=(left_id, right_id),
                operator=operator,
                **_mapped(self.source_ref.ref_id, span_id),
            )
        )
        return expr_id

    def _unary(self, operator: str, operand_id: str, span_id: str, type_ref: str = "any") -> str:
        expr_id = self._next("expr")
        self.expressions.append(
            ProgramExpression(
                expr_id,
                ExpressionKind.UNARY,
                type_ref,
                operand_ids=(operand_id,),
                evaluation_order=(operand_id,),
                operator=operator,
                **_mapped(self.source_ref.ref_id, span_id),
            )
        )
        return expr_id

    def lower_expression(
        self,
        node: ast.AST,
        *,
        function: str,
        locals_map: dict[str, str],
    ) -> str | None:
        span_id = self._span_for(node, label=f"{function}.expr")
        if isinstance(node, ast.Constant):
            type_ref = type(node.value).__name__ if node.value is not None else "none"
            return self._literal(node.value, span_id, type_ref=type_ref)
        if isinstance(node, ast.Name):
            symbol_id = locals_map.get(node.id) or self._symbol(
                node.id, SymbolKind.GLOBAL, "any", span_id, function=function
            )
            locals_map.setdefault(node.id, symbol_id)
            return self._name_expr(symbol_id, span_id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            operand = self.lower_expression(node.operand, function=function, locals_map=locals_map)
            if operand is None:
                return None
            op = {ast.USub: "neg", ast.UAdd: "pos", ast.Not: "not"}[type(node.op)]
            return self._unary(op, operand, span_id)
        if isinstance(node, ast.BinOp):
            left = self.lower_expression(node.left, function=function, locals_map=locals_map)
            right = self.lower_expression(node.right, function=function, locals_map=locals_map)
            if left is None or right is None:
                return None
            op_map = {
                ast.Add: "add",
                ast.Sub: "sub",
                ast.Mult: "mul",
                ast.Div: "div",
                ast.FloorDiv: "floordiv",
                ast.Mod: "mod",
                ast.Pow: "pow",
            }
            operator = op_map.get(type(node.op))
            if operator is None:
                self._retain(f"python.binop.{type(node.op).__name__}", node, subject_ids=())
                return None
            return self._binop(operator, left, right, span_id)
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left = self.lower_expression(node.left, function=function, locals_map=locals_map)
            right = self.lower_expression(
                node.comparators[0], function=function, locals_map=locals_map
            )
            if left is None or right is None:
                return None
            op_map = {
                ast.Eq: "eq",
                ast.NotEq: "ne",
                ast.Lt: "lt",
                ast.LtE: "le",
                ast.Gt: "gt",
                ast.GtE: "ge",
                ast.Is: "is",
                ast.IsNot: "is_not",
                ast.In: "in",
                ast.NotIn: "not_in",
            }
            operator = op_map.get(type(node.ops[0]))
            if operator is None:
                self._retain(
                    f"python.compare.{type(node.ops[0]).__name__}",
                    node,
                    subject_ids=(),
                )
                return None
            return self._binop(operator, left, right, span_id, type_ref="boolean")
        if isinstance(node, ast.BoolOp) and len(node.values) == 2:
            left = self.lower_expression(node.values[0], function=function, locals_map=locals_map)
            right = self.lower_expression(node.values[1], function=function, locals_map=locals_map)
            if left is None or right is None:
                return None
            operator = "and" if isinstance(node.op, ast.And) else "or"
            return self._binop(operator, left, right, span_id, type_ref="boolean")
        if isinstance(node, ast.Call):
            # Supported only as an opaque impure call expression for effect tracking.
            args: list[str] = []
            for arg in node.args:
                lowered = self.lower_expression(arg, function=function, locals_map=locals_map)
                if lowered is None:
                    return None
                args.append(lowered)
            callee = "<call>"
            if isinstance(node.func, ast.Name):
                callee = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee = node.func.attr
            expr_id = self._next("expr")
            self.expressions.append(
                ProgramExpression(
                    expr_id,
                    ExpressionKind.CALL,
                    "any",
                    operand_ids=tuple(args),
                    evaluation_order=tuple(args),
                    operator=callee,
                    attributes={"opaque": True, "callee": callee},
                    **_mapped(self.source_ref.ref_id, span_id),
                )
            )
            return expr_id
        self._retain(f"python.expr.{type(node).__name__}", node, subject_ids=())
        return None

    def _command(
        self,
        kind: CommandKind,
        *,
        span_id: str,
        expression_ids: Sequence[str] = (),
        target_symbol_ids: Sequence[str] = (),
        effects: EffectSummary | None = None,
    ) -> str:
        command_id = self._next("command")
        self.commands.append(
            ProgramCommand(
                command_id,
                kind,
                expression_ids=tuple(expression_ids),
                evaluation_order=tuple(expression_ids),
                target_symbol_ids=tuple(target_symbol_ids),
                effects=effects or EffectSummary(),
                **_mapped(self.source_ref.ref_id, span_id),
            )
        )
        return command_id

    def lower_statements(
        self,
        statements: Sequence[ast.stmt],
        *,
        function: str,
        locals_map: dict[str, str],
        function_decl_id: str,
    ) -> tuple[list[str], bool]:
        """Return command ids and whether every statement was fully supported."""

        command_ids: list[str] = []
        complete = True
        for stmt in statements:
            span_id = self._span_for(stmt, label=f"{function}.stmt")
            if isinstance(stmt, ast.Pass):
                command_ids.append(
                    self._command(CommandKind.SKIP, span_id=span_id)
                )
                continue
            if isinstance(stmt, ast.Return):
                if stmt.value is None:
                    command_ids.append(
                        self._command(CommandKind.RETURN, span_id=span_id)
                    )
                    continue
                expr_id = self.lower_expression(
                    stmt.value, function=function, locals_map=locals_map
                )
                if expr_id is None:
                    complete = False
                    command_ids.append(
                        self._command(CommandKind.RETURN, span_id=span_id)
                    )
                    continue
                command_ids.append(
                    self._command(
                        CommandKind.RETURN,
                        span_id=span_id,
                        expression_ids=(expr_id,),
                        effects=EffectSummary(),
                    )
                )
                continue
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(
                stmt.targets[0], ast.Name
            ):
                expr_id = self.lower_expression(
                    stmt.value, function=function, locals_map=locals_map
                )
                if expr_id is None:
                    complete = False
                    continue
                target = stmt.targets[0].id
                symbol_id = locals_map.get(target) or self._symbol(
                    target,
                    SymbolKind.LOCAL,
                    "any",
                    span_id,
                    function=function,
                )
                locals_map[target] = symbol_id
                command_ids.append(
                    self._command(
                        CommandKind.ASSIGN,
                        span_id=span_id,
                        expression_ids=(expr_id,),
                        target_symbol_ids=(symbol_id,),
                        effects=EffectSummary(writes=(symbol_id,)),
                    )
                )
                continue
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                if stmt.value is None:
                    complete = False
                    self._retain("python.annassign.no_value", stmt, subject_ids=(function_decl_id,))
                    continue
                expr_id = self.lower_expression(
                    stmt.value, function=function, locals_map=locals_map
                )
                if expr_id is None:
                    complete = False
                    continue
                target = stmt.target.id
                symbol_id = locals_map.get(target) or self._symbol(
                    target,
                    SymbolKind.LOCAL,
                    "any",
                    span_id,
                    function=function,
                )
                locals_map[target] = symbol_id
                command_ids.append(
                    self._command(
                        CommandKind.ASSIGN,
                        span_id=span_id,
                        expression_ids=(expr_id,),
                        target_symbol_ids=(symbol_id,),
                        effects=EffectSummary(writes=(symbol_id,)),
                    )
                )
                continue
            if isinstance(stmt, ast.If):
                cond = self.lower_expression(
                    stmt.test, function=function, locals_map=locals_map
                )
                if cond is None:
                    complete = False
                    continue
                # Encode branching as assume-true / assume-false sequences joined later
                # by the CFG builder at the function level.  Here we emit a branch marker
                # command carrying the condition and lower both arms sequentially with
                # explicit skip separators when needed.
                command_ids.append(
                    self._command(
                        CommandKind.ASSUME,
                        span_id=span_id,
                        expression_ids=(cond,),
                        effects=EffectSummary(),
                    )
                )
                then_ids, then_ok = self.lower_statements(
                    stmt.body,
                    function=function,
                    locals_map=locals_map,
                    function_decl_id=function_decl_id,
                )
                else_ids, else_ok = self.lower_statements(
                    stmt.orelse,
                    function=function,
                    locals_map=locals_map,
                    function_decl_id=function_decl_id,
                )
                complete = complete and then_ok and else_ok
                # Represent if as linearised then/else with attributes on a skip fence.
                fence = self._command(
                    CommandKind.SKIP,
                    span_id=span_id,
                    effects=EffectSummary(),
                )
                # Attach branch metadata via a no-op fence already created.
                self.commands[-1] = ProgramCommand(
                    fence,
                    CommandKind.SKIP,
                    attributes={
                        "branch_condition": cond,
                        "then_commands": list(then_ids),
                        "else_commands": list(else_ids),
                    },
                    **_mapped(self.source_ref.ref_id, span_id),
                )
                command_ids.extend(then_ids)
                command_ids.append(fence)
                command_ids.extend(else_ids)
                continue
            if isinstance(stmt, ast.Expr):
                # Expression statements: lower for side effects when possible.
                expr_id = self.lower_expression(
                    stmt.value, function=function, locals_map=locals_map
                )
                if expr_id is None:
                    complete = False
                    continue
                command_ids.append(
                    self._command(
                        CommandKind.SKIP,
                        span_id=span_id,
                        expression_ids=(expr_id,),
                        effects=EffectSummary(performs_io=isinstance(stmt.value, ast.Call)),
                    )
                )
                continue
            complete = False
            self._retain(
                f"python.stmt.{type(stmt).__name__}",
                stmt,
                subject_ids=(function_decl_id,),
            )
        return command_ids, complete

    def lower_function(self, node: ast.FunctionDef) -> bool:
        span_id = self._span_for(node, label=f"function.{node.name}")
        function_id = _safe_id("function", node.name)
        decl_id = _safe_id("decl", "function", node.name)
        locals_map: dict[str, str] = {}
        params: list[str] = []
        for arg in node.args.args:
            arg_span = self._span_for(arg, label=f"{node.name}.param.{arg.arg}")
            symbol_id = self._symbol(
                arg.arg,
                SymbolKind.PARAMETER,
                "any",
                arg_span,
                function=node.name,
            )
            locals_map[arg.arg] = symbol_id
            params.append(symbol_id)
        for unsupported_bucket, construct in (
            (node.args.posonlyargs, "python.function.posonlyargs"),
            (node.args.kwonlyargs, "python.function.kwonlyargs"),
            ([node.args.vararg] if node.args.vararg else [], "python.function.vararg"),
            ([node.args.kwarg] if node.args.kwarg else [], "python.function.kwarg"),
            (node.decorator_list, "python.function.decorators"),
        ):
            if unsupported_bucket:
                self._retain(construct, node, subject_ids=(decl_id,))
        if node.returns is not None and not isinstance(node.returns, (ast.Name, ast.Constant)):
            self._retain("python.function.complex_return_annotation", node, subject_ids=(decl_id,))

        result_symbol = self._symbol(
            "result",
            SymbolKind.RESULT,
            "any",
            span_id,
            function=node.name,
        )
        command_ids, complete = self.lower_statements(
            node.body,
            function=node.name,
            locals_map=locals_map,
            function_decl_id=decl_id,
        )
        if not command_ids:
            command_ids = [
                self._command(CommandKind.SKIP, span_id=span_id)
            ]

        # v1 uses a single straight-line CFG.  Branch metadata (if any) is retained
        # on SKIP fence commands so later revisions can expand structured edges
        # without orphaning commands or inventing control-flow.
        entry = "block:entry"
        cfg = ControlFlowGraph(
            graph_id=_safe_id("cfg", node.name),
            entry_block_id=entry,
            blocks=(
                BasicBlock(
                    entry,
                    tuple(command_ids),
                    **_mapped(self.source_ref.ref_id, span_id),
                ),
            ),
            edges=(),
            normal_exit_block_ids=(entry,),
        )

        local_ids = tuple(
            symbol_id
            for name, symbol_id in locals_map.items()
            if symbol_id not in params and symbol_id != result_symbol
        )
        # Effects: any write targets observed on assign commands.
        writes = tuple(
            sorted(
                {
                    target
                    for cmd in self.commands
                    if cmd.command_id in command_ids
                    for target in cmd.target_symbol_ids
                }
            )
        )
        reads = tuple(
            sorted(
                {
                    sid
                    for cmd in self.commands
                    if cmd.command_id in command_ids
                    for sid in cmd.effects.reads
                }
                | set(params)
            )
        )
        effects = EffectSummary(reads=reads, writes=writes)
        purity = Purity.PURE if effects.is_pure else Purity.IMPURE
        self.functions.append(
            ProgramFunction(
                function_id=function_id,
                name=node.name,
                cfg=cfg,
                parameter_symbol_ids=tuple(params),
                local_symbol_ids=local_ids,
                result_symbol_id=result_symbol,
                return_type="any",
                purity=purity,
                effects=effects,
                **_mapped(self.source_ref.ref_id, span_id),
            )
        )
        self.declarations.append(
            VerificationDeclaration(
                declaration_id=decl_id,
                kind=DeclarationKind.FUNCTION,
                name=node.name,
                payload={
                    "function_id": function_id,
                    "parameter_symbol_ids": list(params),
                    "return_type": "any",
                    "language": "python",
                    "complete_lowering": complete,
                },
                source_ref_ids=(self.source_ref.ref_id,),
                span_ids=(span_id,),
            )
        )
        return complete

    def lower_module(self, tree: ast.Module) -> bool:
        complete = True
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if not self.lower_function(node):
                    complete = False
                continue
            if isinstance(node, ast.AsyncFunctionDef):
                complete = False
                self._retain(
                    "python.async_function",
                    node,
                    subject_ids=(),
                )
                continue
            if isinstance(node, ast.ClassDef):
                complete = False
                self._retain(
                    "python.class",
                    node,
                    subject_ids=(),
                )
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Imports become module-level declarations without executable semantics.
                span_id = self._span_for(node, label="import")
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    names = [f"{node.module or ''}.{alias.name}" for alias in node.names]
                for name in names:
                    decl_id = _safe_id("decl", "import", name)
                    self.declarations.append(
                        VerificationDeclaration(
                            declaration_id=decl_id,
                            kind=DeclarationKind.MODULE,
                            name=name,
                            payload={"import": True, "language": "python"},
                            source_ref_ids=(self.source_ref.ref_id,),
                            span_ids=(span_id,),
                        )
                    )
                continue
            if isinstance(node, ast.Assign):
                complete = False
                self._retain(
                    "python.module_level_assign",
                    node,
                    subject_ids=(),
                )
                continue
            complete = False
            self._retain(
                f"python.module.{type(node).__name__}",
                node,
                subject_ids=(),
            )
        return complete and bool(self.functions)


def _language_assumptions(
    *,
    language: str,
    source_ref_id: str,
    span_ids: Sequence[str],
    subject_ids: Sequence[str],
) -> tuple[VerificationAssumption, ...]:
    span_tuple = tuple(span_ids) if span_ids else ()
    source_tuple = (source_ref_id,)
    # Assumptions must be source-mapped; prefer spans when available.
    map_kwargs: dict[str, tuple[str, ...]]
    if span_tuple:
        map_kwargs = {"span_ids": (span_tuple[0],)}
    else:
        map_kwargs = {"source_ref_ids": source_tuple}
    # subject_ids must reference declarations (not sources).
    subjects = tuple(sorted({item for item in subject_ids if item}))
    common = {
        "subject_ids": subjects,
        **map_kwargs,
    }
    return (
        VerificationAssumption(
            assumption_id=_safe_id("assumption", language, "runtime"),
            kind=AssumptionKind.PLATFORM,
            statement=(
                f"{language} runtime is sequential, single-threaded for the admitted "
                "subset; the GIL or event-loop concurrency is not modeled."
            ),
            expression={"language": language, "concurrency": "sequential"},
            **common,
        ),
        VerificationAssumption(
            assumption_id=_safe_id("assumption", language, "memory"),
            kind=AssumptionKind.MODELING,
            statement=(
                f"{language} memory is modeled as abstract object identity without "
                "a precise heap graph in this adapter version."
            ),
            expression={"memory_model": "abstract_objects"},
            **common,
        ),
        VerificationAssumption(
            assumption_id=_safe_id("assumption", language, "undefined-behavior"),
            kind=AssumptionKind.SEMANTIC,
            statement=(
                f"Undefined or implementation-defined {language} behavior is not "
                "silently executed; unsupported constructs are retained as diagnostics."
            ),
            expression={"undefined_behavior_policy": "retain_unsupported"},
            **common,
        ),
        VerificationAssumption(
            assumption_id=_safe_id("assumption", language, "language-semantics"),
            kind=AssumptionKind.SEMANTIC,
            statement=(
                f"Only the admitted {language} subset is given executable ProgramIR "
                "semantics; other features stay observational."
            ),
            expression={"adapter": SOURCE_ADAPTER_VERSION, "subset": "v1"},
            **common,
        ),
    )


def _backend_requests_for_program(
    program: ProgramIR,
    *,
    source_ref_id: str,
) -> tuple[CanonicalBackendRequest, ...]:
    requests: list[CanonicalBackendRequest] = []
    for function in program.functions:
        requests.append(
            CanonicalBackendRequest(
                request_id=_safe_id("backend-request", function.function_id, "contract"),
                goal_kind="verification_condition",
                subject_ids=(function.function_id,),
                obligation_statement=(
                    f"Establish the admitted contract obligations for function "
                    f"{function.name!r} via the shared SMT compiler; do not treat "
                    "adapter success as a proof."
                ),
                logic_family="smt",
                theory_tags=("qf_lia", "equality"),
                source_ref_ids=(source_ref_id,),
                attributes={
                    "function_id": function.function_id,
                    "program_id": program.program_id,
                    "requires_canonical_backend": True,
                    "fake_success_forbidden": True,
                },
            )
        )
    return tuple(requests)


def _program_properties(
    program: ProgramIR,
    *,
    assumption_ids: Sequence[str],
    source_ref_id: str,
    span_ids: Sequence[str],
) -> tuple[VerificationProperty, ...]:
    properties: list[VerificationProperty] = []
    span_tuple = tuple(span_ids)
    for function in program.functions:
        decl_subject = _safe_id("decl", "function", function.name)
        map_kwargs: dict[str, tuple[str, ...]]
        if span_tuple:
            map_kwargs = {
                "source_ref_ids": (source_ref_id,),
                "span_ids": span_tuple[:1],
            }
        else:
            map_kwargs = {"source_ref_ids": (source_ref_id,)}
        properties.append(
            VerificationProperty(
                property_id=_safe_id("property", function.function_id, "safety"),
                kind=PropertyKind.SAFETY,
                statement=(
                    f"Function {function.name} respects its admitted control-flow "
                    "and effect summary under the declared language assumptions."
                ),
                expression={
                    "function_id": function.function_id,
                    "purity": function.purity.value,
                },
                logic_family="software_verification",
                subject_ids=(decl_subject,),
                assumption_ids=tuple(sorted(set(assumption_ids))),
                **map_kwargs,
            )
        )
    return tuple(properties)


def _build_software_verification_ir(
    *,
    source_ref: SourceRef,
    spans: Sequence[SourceSpan],
    declarations: Sequence[VerificationDeclaration],
    program: ProgramIR | None,
    language: str,
    path: str,
    unsupported: Sequence[str],
    diagnostics: Sequence[Diagnostic],
    evidence: Any,
) -> tuple[SoftwareVerificationIR, tuple[CanonicalBackendRequest, ...]]:
    declarations = list(declarations)
    if not declarations:
        # Closed-world assumptions require declaration subjects or none at all.
        fallback_span = spans[0].span_id if spans else ""
        module_decl = VerificationDeclaration(
            declaration_id=_safe_id("decl", "module", path or language),
            kind=DeclarationKind.MODULE,
            name=path or language,
            payload={"language": language, "synthetic_module": True},
            source_ref_ids=(source_ref.ref_id,),
            span_ids=(fallback_span,) if fallback_span else (),
        )
        if not fallback_span:
            # Source-map via source_ref only when no spans exist.
            module_decl = VerificationDeclaration(
                declaration_id=_safe_id("decl", "module", path or language),
                kind=DeclarationKind.MODULE,
                name=path or language,
                payload={"language": language, "synthetic_module": True},
                source_ref_ids=(source_ref.ref_id,),
            )
        declarations.append(module_decl)
    subject_ids = [item.declaration_id for item in declarations]
    span_ids = [item.span_id for item in spans]
    assumptions = _language_assumptions(
        language=language,
        source_ref_id=source_ref.ref_id,
        span_ids=span_ids,
        subject_ids=subject_ids,
    )
    bounds = (
        VerificationBound(
            bound_id=_safe_id("bound", language, "source-bytes"),
            kind=BoundednessKind.RESOURCE_BOUNDED,
            limits={"max_source_bytes": 2 * 1024 * 1024},
            description="Adapter admission bound for source size.",
            source_ref_ids=(source_ref.ref_id,),
        ),
    )
    properties: tuple[VerificationProperty, ...] = ()
    backend_requests: tuple[CanonicalBackendRequest, ...] = ()
    if program is not None:
        properties = _program_properties(
            program,
            assumption_ids=tuple(item.assumption_id for item in assumptions),
            source_ref_id=source_ref.ref_id,
            span_ids=span_ids,
        )
        backend_requests = _backend_requests_for_program(
            program, source_ref_id=source_ref.ref_id
        )
    meta = dict(source_ref.metadata) if isinstance(source_ref.metadata, Mapping) else {}
    byte_length = meta.get("byte_length", 1)
    try:
        size = max(1, int(byte_length))
    except (TypeError, ValueError):
        size = 1
    artifact = Artifact(
        artifact_id=_safe_id("artifact", path or language),
        role=ArtifactRole.INPUT,
        content_sha256=source_ref.content_sha256,
        size=size,
        path=path.replace("\\", "/") or f"snippet.{language}",
        media_type=_PYTHON_MEDIA.get(language, "text/plain"),
        schema_id="software-verification-source",
        schema_version="v1",
        metadata={"language": language},
    )
    observations: dict[str, Any] = {
        "adapter_version": SOURCE_ADAPTER_VERSION,
        "interface": SOURCE_SOFTWARE_VERIFICATION_ADAPTER,
        "unsupported_constructs": list(sorted(set(unsupported))),
        "backend_requests": [item.to_dict() for item in backend_requests],
    }
    if evidence is not None and hasattr(evidence, "to_dict"):
        observations["program_ast_evidence"] = {
            "status": getattr(evidence, "status", None),
            "language": getattr(evidence, "language", None),
            "source_sha256": getattr(evidence, "source_sha256", None),
            "blob_identity": getattr(evidence, "blob_identity", None),
            "parser": getattr(evidence, "parser", None),
            "fact_count": len(getattr(evidence, "facts", ()) or ()),
        }
    document = SoftwareVerificationIR(
        sources=(source_ref,),
        spans=tuple(spans),
        declarations=tuple(declarations),
        properties=properties,
        assumptions=assumptions,
        bounds=bounds,
        diagnostics=tuple(diagnostics),
        artifacts=(artifact,),
        metadata={
            "language": language,
            "path": path.replace("\\", "/") or f"snippet.{language}",
            "adapter": SOURCE_SOFTWARE_VERIFICATION_ADAPTER,
        },
        extensions={"lfv.source_adapter.version": SOURCE_ADAPTER_VERSION},
        observations=observations,
    )
    return document, backend_requests


def _adapt_python(
    source: str,
    *,
    path: str,
    evidence: Any,
) -> SourceAdapterResult:
    source_ref = SourceRef(
        ref_id=_safe_id("source", path or "snippet.py"),
        source_uri=f"file:///{(path or 'snippet.py').replace(chr(92), '/').lstrip('/')}",
        source_id=PurePosixPath(path or "snippet.py").name,
        source_revision="workspace:local",
        content_sha256=_sha256_hex(source),
        metadata={
            "language": "python",
            "path": path.replace("\\", "/") or "snippet.py",
            "byte_length": len(source.encode("utf-8", errors="surrogatepass")),
        },
    )
    try:
        tree = ast.parse(source, filename=path or "<unknown>", type_comments=True)
    except SyntaxError as exc:
        diagnostic = Diagnostic(
            code=DiagnosticCode.VALIDATION_FAILED,
            message=str(exc),
            severity=DiagnosticSeverity.ERROR,
            location=DiagnosticLocation(
                subject_ids=(source_ref.ref_id,),
                source_ref_ids=(source_ref.ref_id,),
                metadata={"lineno": getattr(exc, "lineno", None), "kind": "parse_error"},
            ),
        )
        return SourceAdapterResult(
            status=SourceAdapterStatus.MALFORMED,
            language="python",
            path=path,
            evidence=evidence,
            diagnostics=(diagnostic,),
        )

    lowerer = _PythonLowering(source=source, source_ref=source_ref, path=path)
    complete = lowerer.lower_module(tree)
    if not lowerer.functions:
        document, requests = _build_software_verification_ir(
            source_ref=source_ref,
            spans=lowerer.spans,
            declarations=lowerer.declarations,
            program=None,
            language="python",
            path=path or "snippet.py",
            unsupported=lowerer.unsupported or ("python.no_supported_function",),
            diagnostics=lowerer.diagnostics,
            evidence=evidence,
        )
        return SourceAdapterResult(
            status=SourceAdapterStatus.UNSUPPORTED
            if not lowerer.declarations
            else SourceAdapterStatus.PARTIAL,
            language="python",
            path=path,
            document=document,
            evidence=evidence,
            backend_requests=requests,
            unsupported_constructs=tuple(lowerer.unsupported),
            diagnostics=tuple(lowerer.diagnostics),
        )

    try:
        program = ProgramIR(
            sources=(source_ref,),
            spans=tuple(lowerer.spans),
            symbols=tuple(lowerer.symbols),
            expressions=tuple(lowerer.expressions),
            commands=tuple(lowerer.commands),
            functions=tuple(lowerer.functions),
            metadata={
                "language": "python",
                "path": path.replace("\\", "/") or "snippet.py",
                "adapter": SOURCE_SOFTWARE_VERIFICATION_ADAPTER,
            },
        )
    except ProgramValidationError as exc:
        diagnostic = Diagnostic(
            code=DiagnosticCode.VALIDATION_FAILED,
            message=f"ProgramIR validation failed: {exc}",
            severity=DiagnosticSeverity.ERROR,
            location=DiagnosticLocation(
                subject_ids=(source_ref.ref_id,),
                source_ref_ids=(source_ref.ref_id,),
            ),
        )
        return SourceAdapterResult(
            status=SourceAdapterStatus.PARTIAL,
            language="python",
            path=path,
            evidence=evidence,
            unsupported_constructs=tuple(lowerer.unsupported),
            diagnostics=tuple(lowerer.diagnostics) + (diagnostic,),
        )

    document, requests = _build_software_verification_ir(
        source_ref=source_ref,
        spans=lowerer.spans,
        declarations=lowerer.declarations,
        program=program,
        language="python",
        path=path or "snippet.py",
        unsupported=lowerer.unsupported,
        diagnostics=lowerer.diagnostics,
        evidence=evidence,
    )
    status = (
        SourceAdapterStatus.SUCCESS
        if complete and not lowerer.unsupported
        else SourceAdapterStatus.PARTIAL
    )
    return SourceAdapterResult(
        status=status,
        language="python",
        path=path,
        document=document,
        program=program,
        evidence=evidence,
        backend_requests=requests,
        unsupported_constructs=tuple(lowerer.unsupported),
        diagnostics=tuple(lowerer.diagnostics),
    )


_JS_FUNCTION_RE = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*\{",
    re.MULTILINE,
)
_JS_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
    re.MULTILINE,
)
_JS_RETURN_RE = re.compile(r"\breturn\b")


def _adapt_ecmascript(
    source: str,
    *,
    path: str,
    language: str,
    evidence: Any,
) -> SourceAdapterResult:
    source_ref = SourceRef(
        ref_id=_safe_id("source", path or f"snippet.{language}"),
        source_uri=f"file:///{(path or f'snippet.{language}').replace(chr(92), '/').lstrip('/')}",
        source_id=PurePosixPath(path or f"snippet.{language}").name,
        source_revision="workspace:local",
        content_sha256=_sha256_hex(source),
        metadata={
            "language": language,
            "path": path.replace("\\", "/") or f"snippet.{language}",
            "byte_length": len(source.encode("utf-8", errors="surrogatepass")),
        },
    )
    full_span = _make_span(
        span_id=_safe_id("span", "file"),
        source_ref_id=source_ref.ref_id,
        start_byte=0,
        end_byte=len(source.encode("utf-8", errors="surrogatepass")),
        start_line=1,
        start_column=1,
        end_line=max(1, source.count("\n") + 1),
        end_column=1,
    )
    matches = list(_JS_FUNCTION_RE.finditer(source)) + list(_JS_ARROW_RE.finditer(source))
    unsupported: list[str] = []
    diagnostics: list[Diagnostic] = []
    symbols: list[ProgramSymbol] = []
    expressions: list[ProgramExpression] = []
    commands: list[ProgramCommand] = []
    functions: list[ProgramFunction] = []
    declarations: list[VerificationDeclaration] = []
    spans = [full_span]

    if "class " in source:
        unsupported.append("ecmascript.class")
    if "async " in source:
        unsupported.append("ecmascript.async")
    if "=>" in source and not _JS_ARROW_RE.search(source):
        unsupported.append("ecmascript.complex_arrow")

    for match in matches:
        name = match.group(1)
        params_raw = match.group(2).strip()
        param_names = [
            item.strip().split("=")[0].strip()
            for item in params_raw.split(",")
            if item.strip() and item.strip() != "..."
        ]
        param_names = [p for p in param_names if re.fullmatch(r"[A-Za-z_$][\w$]*", p)]
        span_id = _safe_id("span", "function", name)
        # Approximate span from match indices.
        start = match.start()
        end = match.end()
        spans.append(
            _make_span(
                span_id=span_id,
                source_ref_id=source_ref.ref_id,
                start_byte=start,
                end_byte=end,
                start_line=source.count("\n", 0, start) + 1,
                start_column=1,
                end_line=source.count("\n", 0, end) + 1,
                end_column=1,
            )
        )
        mapped = _mapped(source_ref.ref_id, span_id)
        params: list[str] = []
        for pname in param_names:
            sid = _safe_id("symbol", name, pname, "parameter")
            symbols.append(
                ProgramSymbol(sid, pname, "any", SymbolKind.PARAMETER, **mapped)
            )
            params.append(sid)
        result_sid = _safe_id("symbol", name, "result", "result")
        symbols.append(
            ProgramSymbol(result_sid, "result", "any", SymbolKind.RESULT, **mapped)
        )
        # Body is treated as opaque with a single return when present.
        body_start = match.end()
        body_slice = source[body_start : body_start + 4000]
        has_return = bool(_JS_RETURN_RE.search(body_slice))
        cmd_id = _safe_id("command", name, "body")
        if has_return:
            lit = _safe_id("expr", name, "return-opaque")
            expressions.append(
                ProgramExpression(
                    lit,
                    ExpressionKind.UNDEFINED,
                    "any",
                    attributes={"opaque_js_return": True},
                    **mapped,
                )
            )
            commands.append(
                ProgramCommand(
                    cmd_id,
                    CommandKind.RETURN,
                    expression_ids=(lit,),
                    evaluation_order=(lit,),
                    **mapped,
                )
            )
        else:
            commands.append(ProgramCommand(cmd_id, CommandKind.SKIP, **mapped))
        entry = _safe_id("block", name, "entry")
        # Use simple ids for CFG that remain valid identifiers.
        entry = f"block:{name}.entry".replace("$", "_")
        cmd_id_use = commands[-1].command_id
        cfg = ControlFlowGraph(
            graph_id=_safe_id("cfg", name),
            entry_block_id=entry,
            blocks=(BasicBlock(entry, (cmd_id_use,), **mapped),),
            edges=(),
            normal_exit_block_ids=(entry,),
        )
        function_id = _safe_id("function", name)
        functions.append(
            ProgramFunction(
                function_id=function_id,
                name=name,
                cfg=cfg,
                parameter_symbol_ids=tuple(params),
                result_symbol_id=result_sid,
                return_type="any",
                purity=Purity.UNKNOWN,
                effects=EffectSummary(nondeterministic=True),
                **mapped,
            )
        )
        declarations.append(
            VerificationDeclaration(
                declaration_id=_safe_id("decl", "function", name),
                kind=DeclarationKind.FUNCTION,
                name=name,
                payload={
                    "function_id": function_id,
                    "language": language,
                    "complete_lowering": False,
                    "opaque_body": True,
                },
                source_ref_ids=(source_ref.ref_id,),
                span_ids=(span_id,),
            )
        )

    for construct in unsupported:
        diagnostics.append(
            unsupported_construct_diagnostic(
                construct=construct,
                subject_ids=(source_ref.ref_id,),
                source_ref_ids=(source_ref.ref_id,),
                span_ids=(full_span.span_id,),
            )
        )

    if not functions:
        document, requests = _build_software_verification_ir(
            source_ref=source_ref,
            spans=spans,
            declarations=declarations,
            program=None,
            language=language,
            path=path or f"snippet.{language}",
            unsupported=unsupported or (f"{language}.no_supported_function",),
            diagnostics=diagnostics,
            evidence=evidence,
        )
        return SourceAdapterResult(
            status=SourceAdapterStatus.UNSUPPORTED,
            language=language,
            path=path,
            document=document,
            evidence=evidence,
            backend_requests=requests,
            unsupported_constructs=tuple(unsupported),
            diagnostics=tuple(diagnostics),
        )

    try:
        program = ProgramIR(
            sources=(source_ref,),
            spans=tuple(spans),
            symbols=tuple(symbols),
            expressions=tuple(expressions),
            commands=tuple(commands),
            functions=tuple(functions),
            metadata={
                "language": language,
                "path": path.replace("\\", "/") or f"snippet.{language}",
                "adapter": SOURCE_SOFTWARE_VERIFICATION_ADAPTER,
            },
        )
    except ProgramValidationError as exc:
        diagnostic = Diagnostic(
            code=DiagnosticCode.VALIDATION_FAILED,
            message=f"ProgramIR validation failed: {exc}",
            severity=DiagnosticSeverity.ERROR,
            location=DiagnosticLocation(
                subject_ids=(source_ref.ref_id,),
                source_ref_ids=(source_ref.ref_id,),
            ),
        )
        return SourceAdapterResult(
            status=SourceAdapterStatus.PARTIAL,
            language=language,
            path=path,
            evidence=evidence,
            unsupported_constructs=tuple(unsupported),
            diagnostics=tuple(diagnostics) + (diagnostic,),
        )

    # ECMAScript bodies are opaque → always partial when functions exist.
    unsupported = list(dict.fromkeys([*unsupported, f"{language}.opaque_function_body"]))
    diagnostics.append(
        unsupported_construct_diagnostic(
            construct=f"{language}.opaque_function_body",
            subject_ids=tuple(item.declaration_id for item in declarations),
            source_ref_ids=(source_ref.ref_id,),
            span_ids=(full_span.span_id,),
            remediation="Expand ECMAScript body lowering in a later revision.",
        )
    )
    document, requests = _build_software_verification_ir(
        source_ref=source_ref,
        spans=spans,
        declarations=declarations,
        program=program,
        language=language,
        path=path or f"snippet.{language}",
        unsupported=unsupported,
        diagnostics=diagnostics,
        evidence=evidence,
    )
    return SourceAdapterResult(
        status=SourceAdapterStatus.PARTIAL,
        language=language,
        path=path,
        document=document,
        program=program,
        evidence=evidence,
        backend_requests=requests,
        unsupported_constructs=tuple(unsupported),
        diagnostics=tuple(diagnostics),
    )


def adapt_source_to_software_verification(
    source: str,
    *,
    path: str = "",
    language: str = "",
    revision: str = "workspace:local",
    max_source_bytes: int = 2 * 1024 * 1024,
) -> SourceAdapterResult:
    """Adapt one source unit into shared software-verification artifacts."""

    if not isinstance(source, str):
        raise SourceAdapterError("source must be text")
    if not isinstance(max_source_bytes, int) or isinstance(max_source_bytes, bool) or max_source_bytes < 1:
        raise SourceAdapterError("max_source_bytes must be a positive integer")
    byte_count = len(source.encode("utf-8", errors="surrogatepass"))
    adapt_program_source, detect_program_language = _load_program_ast_adapter()
    detected = language
    evidence = None
    if detect_program_language is not None:
        detected = detect_program_language(path, language)
    elif not detected:
        suffix = PurePosixPath(path).suffix.lower()
        detected = {
            ".py": "python",
            ".pyi": "python",
            ".js": "javascript",
            ".mjs": "javascript",
            ".cjs": "javascript",
            ".jsx": "jsx",
            ".ts": "typescript",
            ".mts": "typescript",
            ".cts": "typescript",
            ".tsx": "tsx",
        }.get(suffix, "unknown")
    if adapt_program_source is not None:
        evidence = adapt_program_source(
            source,
            path=path,
            language=language or detected,
            max_source_bytes=max_source_bytes,
        )
        detected = getattr(evidence, "language", None) or detected

    if byte_count > max_source_bytes:
        return SourceAdapterResult(
            status=SourceAdapterStatus.UNSUPPORTED,
            language=detected or "unknown",
            path=path,
            evidence=evidence,
            unsupported_constructs=("source.size_bound",),
            diagnostics=(
                Diagnostic(
                    code=DiagnosticCode.UNSUPPORTED_FEATURE,
                    message=(
                        f"source contains {byte_count} bytes; adapter limit is "
                        f"{max_source_bytes}"
                    ),
                    severity=DiagnosticSeverity.ERROR,
                    location=DiagnosticLocation(metadata={"observed_bytes": byte_count}),
                ),
            ),
        )

    if detected == "python":
        result = _adapt_python(source, path=path, evidence=evidence)
        return result
    if detected in {"javascript", "jsx", "typescript", "tsx"}:
        return _adapt_ecmascript(
            source, path=path, language=detected, evidence=evidence
        )
    return SourceAdapterResult(
        status=SourceAdapterStatus.UNSUPPORTED,
        language=detected or "unknown",
        path=path,
        evidence=evidence,
        unsupported_constructs=(f"language.{detected or 'unknown'}",),
        diagnostics=(
            Diagnostic(
                code=DiagnosticCode.UNSUPPORTED_FEATURE,
                message=f"no source software-verification adapter for language {detected!r}",
                severity=DiagnosticSeverity.ERROR,
                location=DiagnosticLocation(
                    metadata={"language": detected, "path": path}
                ),
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class SourceSoftwareVerificationAdapter:
    """Stable interface object for ``SourceSoftwareVerificationAdapter@1``."""

    interface: str = SOURCE_SOFTWARE_VERIFICATION_ADAPTER
    version: str = SOURCE_ADAPTER_VERSION
    max_source_bytes: int = 2 * 1024 * 1024

    def adapt(
        self,
        source: str,
        *,
        path: str = "",
        language: str = "",
        revision: str = "workspace:local",
    ) -> SourceAdapterResult:
        return adapt_source_to_software_verification(
            source,
            path=path,
            language=language,
            revision=revision,
            max_source_bytes=self.max_source_bytes,
        )


__all__ = [
    "CANONICAL_BACKEND_REQUEST_SCHEMA",
    "SOURCE_ADAPTER_SCHEMA",
    "SOURCE_ADAPTER_VERSION",
    "SOURCE_SOFTWARE_VERIFICATION_ADAPTER",
    "CanonicalBackendRequest",
    "SourceAdapterError",
    "SourceAdapterResult",
    "SourceAdapterStatus",
    "SourceSoftwareVerificationAdapter",
    "adapt_source_to_software_verification",
]
