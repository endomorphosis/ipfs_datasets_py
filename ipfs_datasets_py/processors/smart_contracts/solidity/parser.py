"""Bounded inert Solidity source parser (CRYPTOIR-G730).

Implements the smart-contract :class:`~..protocols.ContractParser` protocol for
offline Solidity source.  The default ``inert`` backend is pure Python: it
never installs packages, never invokes system ``solc``, never resolves imports
over the network, and never executes corpus code.

Optional backends may be injected.  When a non-default backend is requested but
unavailable, the result is a typed :attr:`~.models.ParseStatus.UNSUPPORTED`
receipt — not an import-time failure.

Acceptance invariants:

* Deterministic results preserve exact source spans.
* Coverage includes contracts, libraries, interfaces, inheritance, imports,
  functions, constructors, modifiers, state variables, events, errors, calls,
  reads/writes, authorization guards, value effects, assembly, and unsupported
  syntax.
* Parser identity/version/config and all byte, node, nesting, import,
  diagnostic, cancellation, and time bounds are receipt-bound.
* Source/compiler/address claims remain evidence, not deployed semantics.
* Failure and partial coverage are explicit.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json
from ..errors import (
    DeadlineExceededError,
    InvalidRequestError,
    OperationCancelledError,
    ResourceLimitError,
    UnsupportedCapabilityError,
)
from ..protocols import (
    Capabilities,
    Capability,
    ContractParser,
    OperationContext,
    ParsedArtifact,
    enforce_batch_limits,
)
from .models import (
    PARSER_ID,
    PARSER_SCHEMA_VERSION,
    PARSER_VERSION,
    AssemblyBlockFact,
    AuthGuardFact,
    AuthGuardKind,
    CallFact,
    CallKind,
    ClaimKind,
    ContractKind,
    DiagnosticSeverity,
    ErrorFact,
    EventFact,
    EvidenceClaim,
    FunctionFact,
    InheritanceRef,
    ParameterFact,
    ParseDiagnostic,
    ParseStatus,
    ParseUsage,
    ParserBounds,
    ParserConfig,
    ParserIdentity,
    SolidityImport,
    SolidityParseResult,
    SolidityPragma,
    SoliditySourceUnit,
    SolidityTypeDefinition,
    SourceSpan,
    StateMutability,
    StateVariableFact,
    StorageAccessFact,
    StorageAccessKind,
    UnsupportedSyntaxFact,
    ValueEffectFact,
    ValueEffectKind,
    Visibility,
)


# ---------------------------------------------------------------------------
# Regex patterns (structure-only; not a full Solidity grammar)
# ---------------------------------------------------------------------------

_PRAGMA_RE = re.compile(
    r"\bpragma\s+([A-Za-z_][\w$]*)\s+([^;]*);",
    re.MULTILINE,
)
_IMPORT_RE = re.compile(
    r"""\bimport\s+"""
    r"""(?P<body>"""
    r"""(?:\{[^}]*\}\s+from\s+)"""
    r"""|(?:\*\s+as\s+[A-Za-z_][\w$]*\s+from\s+)"""
    r"""|(?:[A-Za-z_][\w$]*\s+from\s+)"""
    r"""|"""
    r""")"""
    r"""(?P<q>["'])(?P<path>[^"']+)(?P=q)\s*;""",
    re.MULTILINE,
)
_IMPORT_SIMPLE_RE = re.compile(
    r"""\bimport\s+(?P<q>["'])(?P<path>[^"']+)(?P=q)"""
    r"""(?:\s+as\s+(?P<alias>[A-Za-z_][\w$]*))?\s*;""",
    re.MULTILINE,
)
_IMPORT_NAMED_RE = re.compile(
    r"""\bimport\s+\{(?P<symbols>[^}]*)\}\s+from\s+"""
    r"""(?P<q>["'])(?P<path>[^"']+)(?P=q)\s*;""",
    re.MULTILINE,
)
_IMPORT_STAR_RE = re.compile(
    r"""\bimport\s+\*\s+as\s+(?P<alias>[A-Za-z_][\w$]*)\s+from\s+"""
    r"""(?P<q>["'])(?P<path>[^"']+)(?P=q)\s*;""",
    re.MULTILINE,
)
_TYPE_HEADER_RE = re.compile(
    r"\b(?P<abstract>abstract\s+)?(?P<kind>contract|library|interface)\s+"
    r"(?P<name>[A-Za-z_][\w$]*)"
    r"(?:\s+is\s+(?P<bases>[^{]+))?"
    r"\s*\{",
    re.MULTILINE,
)
_FUNCTION_RE = re.compile(
    r"\bfunction\s+(?P<name>[A-Za-z_][\w$]*)\s*"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?P<suffix>[^{;]*)",
    re.MULTILINE,
)
_CONSTRUCTOR_RE = re.compile(
    r"\bconstructor\s*\((?P<params>[^)]*)\)\s*(?P<suffix>[^{;]*)",
    re.MULTILINE,
)
_MODIFIER_DECL_RE = re.compile(
    r"\bmodifier\s+(?P<name>[A-Za-z_][\w$]*)\s*"
    r"(?:\((?P<params>[^)]*)\))?\s*"
    r"(?P<suffix>[^{;]*)",
    re.MULTILINE,
)
_RECEIVE_RE = re.compile(
    r"\breceive\s*\(\s*\)\s*(?P<suffix>[^{;]*)",
    re.MULTILINE,
)
_FALLBACK_RE = re.compile(
    r"\bfallback\s*(?:\((?P<params>[^)]*)\))?\s*(?P<suffix>[^{;]*)",
    re.MULTILINE,
)
_EVENT_RE = re.compile(
    r"\bevent\s+(?P<name>[A-Za-z_][\w$]*)\s*\((?P<params>[^)]*)\)\s*"
    r"(?P<anon>anonymous\s*)?;",
    re.MULTILINE,
)
_ERROR_RE = re.compile(
    r"\berror\s+(?P<name>[A-Za-z_][\w$]*)\s*\((?P<params>[^)]*)\)\s*;",
    re.MULTILINE,
)
_STATE_VAR_RE = re.compile(
    r"(?P<type>(?:mapping\s*\([^;{]+\)|[A-Za-z_][\w$]*(?:\s*\[[^\]]*\])?(?:\s*\.\s*[A-Za-z_][\w$]*)*))"
    r"\s+(?P<vis>public|private|internal)?\s*"
    r"(?P<flags>(?:constant|immutable|override|transient)\s+)*"
    r"(?P<name>[A-Za-z_][\w$]*)\s*"
    r"(?:=\s*[^;]+)?\s*;",
    re.MULTILINE,
)
_CALL_RE = re.compile(
    r"\b(?P<callee>"
    r"super\.[A-Za-z_][\w$]*|"
    r"[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*|"
    r"new\s+[A-Za-z_][\w$]*"
    r")\s*"
    r"(?:\{[^}]*\})?\s*"
    r"\(",
    re.MULTILINE,
)
_LOW_LEVEL_CALL_RE = re.compile(
    r"\.(?P<kind>call|delegatecall|staticcall|callcode)\s*(?:\{[^}]*\})?\s*\(",
    re.MULTILINE,
)
_VALUE_CALL_RE = re.compile(
    r"\.(?:call|transfer|send)\s*(?:\{\s*value\s*:\s*(?P<val>[^}]+)\s*\})?\s*\(",
    re.MULTILINE,
)
_REQUIRE_RE = re.compile(r"\brequire\s*\(", re.MULTILINE)
_ASSERT_RE = re.compile(r"\bassert\s*\(", re.MULTILINE)
_REVERT_RE = re.compile(r"\brevert\s*(?:[A-Za-z_][\w$]*)?\s*(?:\(|;)", re.MULTILINE)
_SELFDESTRUCT_RE = re.compile(r"\b(?:selfdestruct|suicide)\s*\(", re.MULTILINE)
_ASSEMBLY_RE = re.compile(
    r"\bassembly\s*(?:\"[^\"]*\"\s*)?\{",
    re.MULTILINE,
)
_ONLY_OWNER_RE = re.compile(
    r"\b(onlyOwner|onlyRole|onlyAdmin|whenNotPaused|nonReentrant)\b",
    re.MULTILINE,
)
_ASSIGNMENT_RE = re.compile(
    r"\b(?P<target>[A-Za-z_][\w$]*(?:\[[^\]]*\])?(?:\.[A-Za-z_][\w$]*)*)\s*"
    r"(?P<op>=|\+=|-=|\*=|/=)\s*",
    re.MULTILINE,
)
_USING_RE = re.compile(
    r"\busing\s+[A-Za-z_][\w$]*\s+for\s+[^;]+;",
    re.MULTILINE,
)
_STRUCT_RE = re.compile(
    r"\bstruct\s+[A-Za-z_][\w$]*\s*\{",
    re.MULTILINE,
)
_ENUM_RE = re.compile(
    r"\benum\s+[A-Za-z_][\w$]*\s*\{",
    re.MULTILINE,
)
_USER_TYPE_RE = re.compile(
    r"\btype\s+[A-Za-z_][\w$]*\s+is\s+[^;]+;",
    re.MULTILINE,
)
_TRY_RE = re.compile(r"\btry\s+", re.MULTILINE)
_UNCHECKED_RE = re.compile(r"\bunchecked\s*\{", re.MULTILINE)

_VISIBILITY = {
    "public": Visibility.PUBLIC,
    "private": Visibility.PRIVATE,
    "internal": Visibility.INTERNAL,
    "external": Visibility.EXTERNAL,
}
_MUTABILITY = {
    "pure": StateMutability.PURE,
    "view": StateMutability.VIEW,
    "payable": StateMutability.PAYABLE,
    "nonpayable": StateMutability.NONPAYABLE,
}
_BUILTIN_CALLS = frozenset(
    {
        "require",
        "assert",
        "revert",
        "keccak256",
        "sha256",
        "ripemd160",
        "ecrecover",
        "addmod",
        "mulmod",
        "blockhash",
        "gasleft",
        "type",
        "abi",
    }
)
_KEYWORDS_NOT_STATE = frozenset(
    {
        "function",
        "modifier",
        "event",
        "error",
        "constructor",
        "receive",
        "fallback",
        "if",
        "else",
        "for",
        "while",
        "do",
        "return",
        "emit",
        "require",
        "assert",
        "revert",
        "assembly",
        "unchecked",
        "try",
        "catch",
        "using",
        "struct",
        "enum",
        "mapping",
        "type",
        "import",
        "pragma",
        "contract",
        "library",
        "interface",
        "abstract",
        "is",
        "new",
        "delete",
        "true",
        "false",
        "this",
        "super",
        "msg",
        "tx",
        "block",
        "abi",
    }
)


@runtime_checkable
class SolidityParseBackend(Protocol):
    """Optional injectable parse backend (never auto-installed)."""

    @property
    def backend_id(self) -> str:
        ...

    @property
    def available(self) -> bool:
        ...

    def parse_source(
        self,
        source: str,
        *,
        path: str,
        bounds: ParserBounds,
        config: ParserConfig,
        context: OperationContext | None,
    ) -> SolidityParseResult:
        ...


def _line_col_map(text: str) -> list[int]:
    """Return list of byte/char offsets where each line starts (0-based lines)."""

    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _span_at(starts: list[int], start: int, end: int) -> SourceSpan:
    def loc(offset: int) -> tuple[int, int]:
        # Binary search line.
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        line = lo + 1
        col = offset - starts[lo] + 1
        return line, max(1, col)

    sl, sc = loc(start)
    el, ec = loc(max(start, end))
    return SourceSpan(
        start_offset=start,
        end_offset=end,
        start_line=sl,
        start_column=sc,
        end_line=el,
        end_column=ec,
    )


def _strip_comments_preserve_offsets(source: str) -> str:
    """Replace comments with spaces/newlines so offsets stay aligned."""

    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        if source[i] == "/" and i + 1 < n:
            nxt = source[i + 1]
            if nxt == "/":
                out.append("  ")
                i += 2
                while i < n and source[i] != "\n":
                    out.append(" ")
                    i += 1
                continue
            if nxt == "*":
                out.append("  ")
                i += 2
                while i < n:
                    if source[i] == "\n":
                        out.append("\n")
                        i += 1
                        continue
                    if source[i] == "*" and i + 1 < n and source[i + 1] == "/":
                        out.append("  ")
                        i += 2
                        break
                    out.append(" ")
                    i += 1
                continue
        # String literals: preserve contents length without treating // inside.
        if source[i] in "\"'":
            quote = source[i]
            out.append(quote)
            i += 1
            while i < n:
                ch = source[i]
                out.append(ch)
                if ch == "\\" and i + 1 < n:
                    out.append(source[i + 1])
                    i += 2
                    continue
                i += 1
                if ch == quote:
                    break
            continue
        out.append(source[i])
        i += 1
    return "".join(out)


def _match_braces(text: str, open_brace_index: int, max_nesting: int) -> tuple[int, int]:
    """Return (close_index, max_depth_seen) for ``{`` at open_brace_index.

    ``close_index`` is the index of the matching ``}``, or -1 if unmatched /
    nesting exceeded.
    """

    depth = 0
    max_depth = 0
    i = open_brace_index
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "{":
            depth += 1
            max_depth = max(max_depth, depth)
            if max_depth > max_nesting:
                return -1, max_depth
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i, max_depth
        i += 1
    return -1, max_depth


def _parse_params(params_text: str, base_offset: int, starts: list[int]) -> tuple[ParameterFact, ...]:
    if not params_text.strip():
        return ()
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in params_text:
        if ch in "([<{":
            depth += 1
        elif ch in ")]>}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))

    facts: list[ParameterFact] = []
    cursor = 0
    for part in parts:
        raw = part
        # Track relative offset within params_text.
        rel = params_text.find(raw.strip(), cursor)
        if rel < 0:
            rel = cursor
        cursor = rel + len(raw)
        piece = raw.strip()
        if not piece:
            continue
        indexed = bool(re.search(r"\bindexed\b", piece))
        piece_clean = re.sub(r"\bindexed\b", " ", piece)
        piece_clean = re.sub(r"\s+", " ", piece_clean).strip()
        tokens = piece_clean.split()
        storage_location = ""
        name = ""
        type_name = piece_clean
        if tokens:
            if tokens[-1] not in {
                "memory",
                "storage",
                "calldata",
                "payable",
                "public",
                "private",
                "internal",
                "external",
            } and re.fullmatch(r"[A-Za-z_][\w$]*", tokens[-1] or ""):
                # Heuristic: last token is name if type has earlier tokens.
                if len(tokens) >= 2:
                    name = tokens[-1]
                    type_tokens = tokens[:-1]
                    if type_tokens and type_tokens[-1] in {
                        "memory",
                        "storage",
                        "calldata",
                    }:
                        storage_location = type_tokens[-1]
                        type_tokens = type_tokens[:-1]
                    type_name = " ".join(type_tokens) if type_tokens else name
                    if not type_tokens:
                        type_name = name
                        name = ""
            elif tokens[-1] in {"memory", "storage", "calldata"}:
                storage_location = tokens[-1]
                type_name = " ".join(tokens[:-1]) or tokens[-1]
        span = _span_at(starts, base_offset + rel, base_offset + rel + len(raw.strip()))
        if not type_name:
            type_name = "unknown"
        facts.append(
            ParameterFact(
                name=name,
                type_name=type_name,
                span=span,
                indexed=indexed,
                storage_location=storage_location,
            )
        )
    return tuple(facts)


def _parse_suffix_flags(suffix: str) -> tuple[Visibility, StateMutability, tuple[str, ...], bool, bool]:
    visibility = Visibility.DEFAULT
    mutability = StateMutability.UNKNOWN
    modifiers: list[str] = []
    is_virtual = False
    is_override = False
    # Remove returns(...) for modifier scan.
    cleaned = re.sub(r"\breturns\s*\([^)]*\)", " ", suffix)
    tokens = re.findall(r"[A-Za-z_][\w$]*", cleaned)
    for tok in tokens:
        low = tok.lower()
        if low in _VISIBILITY:
            visibility = _VISIBILITY[low]
        elif low in _MUTABILITY:
            mutability = _MUTABILITY[low]
        elif low == "virtual":
            is_virtual = True
        elif low == "override":
            is_override = True
        elif low not in {
            "public",
            "private",
            "internal",
            "external",
            "pure",
            "view",
            "payable",
            "nonpayable",
            "virtual",
            "override",
            "returns",
            "memory",
            "storage",
            "calldata",
        }:
            modifiers.append(tok)
    return visibility, mutability, tuple(modifiers), is_virtual, is_override


def _parse_returns(suffix: str, match_start: int, starts: list[int]) -> tuple[ParameterFact, ...]:
    m = re.search(r"\breturns\s*\(([^)]*)\)", suffix)
    if not m:
        return ()
    # Approximate absolute offset: suffix is relative to function match; caller
    # passes base for suffix start.
    return _parse_params(m.group(1), match_start + m.start(1), starts)


def _parse_inheritance(bases: str, base_offset: int, starts: list[int]) -> tuple[InheritanceRef, ...]:
    if not bases or not bases.strip():
        return ()
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in bases:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    refs: list[InheritanceRef] = []
    cursor = 0
    for part in parts:
        piece = part.strip()
        if not piece:
            continue
        rel = bases.find(piece, cursor)
        if rel < 0:
            rel = cursor
        cursor = rel + len(piece)
        name_m = re.match(r"([A-Za-z_][\w$]*)", piece)
        if not name_m:
            continue
        name = name_m.group(1)
        args: tuple[str, ...] = ()
        arg_m = re.search(r"\((.*)\)\s*$", piece)
        if arg_m:
            args = tuple(
                a.strip() for a in arg_m.group(1).split(",") if a.strip()
            )
        span = _span_at(
            starts, base_offset + rel, base_offset + rel + len(piece)
        )
        refs.append(InheritanceRef(name=name, span=span, arguments=args))
    return tuple(refs)


@dataclass
class _Budget:
    bounds: ParserBounds
    nodes: int = 0
    max_nesting_seen: int = 0
    imports: int = 0
    diagnostics: int = 0
    declarations: int = 0
    calls: int = 0
    facts: int = 0
    limited: bool = False
    limit_messages: list[str] = field(default_factory=list)

    def use_node(self, n: int = 1) -> bool:
        self.nodes += n
        if self.nodes > self.bounds.max_nodes:
            self.limited = True
            self.limit_messages.append("max_nodes exceeded")
            return False
        return True

    def use_import(self) -> bool:
        self.imports += 1
        if self.imports > self.bounds.max_imports:
            self.limited = True
            self.limit_messages.append("max_imports exceeded")
            return False
        return True

    def use_decl(self) -> bool:
        self.declarations += 1
        if self.declarations > self.bounds.max_declarations:
            self.limited = True
            self.limit_messages.append("max_declarations exceeded")
            return False
        return True

    def use_call(self) -> bool:
        self.calls += 1
        if self.calls > self.bounds.max_calls:
            self.limited = True
            self.limit_messages.append("max_calls exceeded")
            return False
        return True

    def use_fact(self) -> bool:
        self.facts += 1
        if self.facts > self.bounds.max_facts:
            self.limited = True
            self.limit_messages.append("max_facts exceeded")
            return False
        return True

    def note_nesting(self, depth: int) -> None:
        self.max_nesting_seen = max(self.max_nesting_seen, depth)


class InertSolidityBackend:
    """Pure-Python offline Solidity structure extractor (default backend)."""

    backend_id = "inert"

    @property
    def available(self) -> bool:
        return True

    def parse_source(
        self,
        source: str,
        *,
        path: str = "",
        bounds: ParserBounds | None = None,
        config: ParserConfig | None = None,
        context: OperationContext | None = None,
        evidence: Mapping[str, Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> SolidityParseResult:
        bounds = bounds or ParserBounds()
        config = config or ParserConfig()
        if config.backend != "inert" and config.backend != self.backend_id:
            # This backend only serves inert.
            pass
        t0 = (clock or time.perf_counter)()
        identity = ParserIdentity(
            parser_id=PARSER_ID,
            parser_version=PARSER_VERSION,
            schema_version=PARSER_SCHEMA_VERSION,
            config_digest=config.content_digest,
            bounds_digest=content_digest(bounds.to_dict()),
        )

        def _elapsed_ms() -> int:
            return max(0, int(((clock or time.perf_counter)() - t0) * 1000))

        def _check_context() -> None:
            if context is None:
                return
            context.check_active()

        try:
            _check_context()
        except OperationCancelledError:
            return SolidityParseResult(
                status=ParseStatus.CANCELLED,
                identity=identity,
                bounds=bounds,
                config=config,
                usage=ParseUsage(elapsed_ms=_elapsed_ms()),
                diagnostics=(
                    ParseDiagnostic(
                        code="cancelled",
                        message="parse cancelled by caller",
                        severity=DiagnosticSeverity.ERROR,
                    ),
                ),
                notes=("operation cancelled",),
            )
        except DeadlineExceededError:
            return SolidityParseResult(
                status=ParseStatus.DEADLINE_EXCEEDED,
                identity=identity,
                bounds=bounds,
                config=config,
                usage=ParseUsage(elapsed_ms=_elapsed_ms()),
                diagnostics=(
                    ParseDiagnostic(
                        code="deadline",
                        message="parse deadline exceeded before work",
                        severity=DiagnosticSeverity.ERROR,
                    ),
                ),
                notes=("deadline exceeded",),
            )

        if not isinstance(source, str):
            return SolidityParseResult(
                status=ParseStatus.INVALID_INPUT,
                identity=identity,
                bounds=bounds,
                config=config,
                usage=ParseUsage(elapsed_ms=_elapsed_ms()),
                diagnostics=(
                    ParseDiagnostic(
                        code="invalid_input",
                        message="source must be a string",
                        severity=DiagnosticSeverity.ERROR,
                    ),
                ),
            )

        source_bytes = source.encode("utf-8")
        byte_length = len(source_bytes)
        if byte_length > bounds.max_source_bytes:
            return SolidityParseResult(
                status=ParseStatus.RESOURCE_LIMIT,
                identity=identity,
                bounds=bounds,
                config=config,
                usage=ParseUsage(
                    source_bytes=byte_length, elapsed_ms=_elapsed_ms()
                ),
                diagnostics=(
                    ParseDiagnostic(
                        code="max_source_bytes",
                        message=(
                            f"source is {byte_length} bytes; "
                            f"limit is {bounds.max_source_bytes}"
                        ),
                        severity=DiagnosticSeverity.LIMIT,
                    ),
                ),
                notes=("source byte budget exceeded",),
            )

        cleaned = _strip_comments_preserve_offsets(source)
        starts = _line_col_map(cleaned)
        budget = _Budget(bounds=bounds)
        diagnostics: list[ParseDiagnostic] = []
        unsupported: list[UnsupportedSyntaxFact] = []
        evidence_claims: list[EvidenceClaim] = []

        # External evidence claims (compiler/address) — never deployed semantics.
        if evidence:
            for key, val in evidence.items():
                if val is None or val == "":
                    continue
                kind = ClaimKind.OTHER
                key_l = str(key).lower()
                if "compiler" in key_l or key_l in {"solc", "pragma_solidity"}:
                    kind = ClaimKind.COMPILER
                elif "address" in key_l:
                    kind = ClaimKind.ADDRESS
                elif "license" in key_l:
                    kind = ClaimKind.LICENSE
                elif "path" in key_l:
                    kind = ClaimKind.SOURCE_PATH
                elif "verified" in key_l:
                    kind = ClaimKind.VERIFIED_SOURCE
                evidence_claims.append(
                    EvidenceClaim(
                        kind=kind,
                        value=str(val),
                        source_field=str(key),
                        attributes={"role": "unverified_evidence"},
                    )
                )
                if not budget.use_fact():
                    break

        # Pragmas
        pragmas: list[SolidityPragma] = []
        for m in _PRAGMA_RE.finditer(cleaned):
            if not budget.use_node():
                break
            _check_context()
            span = _span_at(starts, m.start(), m.end())
            name = m.group(1)
            value = m.group(2).strip()
            pragmas.append(SolidityPragma(name=name, value=value, span=span))
            if name == "solidity" and value:
                evidence_claims.append(
                    EvidenceClaim(
                        kind=ClaimKind.COMPILER,
                        value=value,
                        span=span,
                        source_field="pragma solidity",
                        attributes={"role": "unverified_evidence"},
                    )
                )
                budget.use_fact()

        # Imports (never resolved)
        imports: list[SolidityImport] = []

        def _add_import(
            path_value: str,
            start: int,
            end: int,
            *,
            symbols: tuple[str, ...] = (),
            alias: str = "",
            is_star: bool = False,
        ) -> None:
            if budget.limited:
                return
            if not budget.use_import():
                diagnostics.append(
                    ParseDiagnostic(
                        code="max_imports",
                        message="import budget exceeded",
                        severity=DiagnosticSeverity.LIMIT,
                        span=_span_at(starts, start, end),
                    )
                )
                return
            if not budget.use_node():
                return
            imports.append(
                SolidityImport(
                    path=path_value,
                    span=_span_at(starts, start, end),
                    symbols=symbols,
                    alias=alias,
                    is_star=is_star,
                    resolved=False,
                )
            )

        for m in _IMPORT_NAMED_RE.finditer(cleaned):
            _check_context()
            symbols = tuple(
                s.strip().split()[0]
                for s in m.group("symbols").split(",")
                if s.strip()
            )
            _add_import(
                m.group("path"),
                m.start(),
                m.end(),
                symbols=symbols,
            )
        for m in _IMPORT_STAR_RE.finditer(cleaned):
            _check_context()
            _add_import(
                m.group("path"),
                m.start(),
                m.end(),
                alias=m.group("alias"),
                is_star=True,
            )
        for m in _IMPORT_SIMPLE_RE.finditer(cleaned):
            _check_context()
            # Skip if already captured as named/star overlapping.
            if any(imp.span.start_offset == m.start() for imp in imports):
                continue
            _add_import(
                m.group("path"),
                m.start(),
                m.end(),
                alias=m.group("alias") or "",
            )

        # Type definitions
        type_defs: list[SolidityTypeDefinition] = []
        for m in _TYPE_HEADER_RE.finditer(cleaned):
            if budget.limited:
                break
            _check_context()
            if not budget.use_node() or not budget.use_decl():
                break
            kind_raw = m.group("kind")
            if m.group("abstract"):
                kind = ContractKind.ABSTRACT_CONTRACT
            elif kind_raw == "contract":
                kind = ContractKind.CONTRACT
            elif kind_raw == "library":
                kind = ContractKind.LIBRARY
            elif kind_raw == "interface":
                kind = ContractKind.INTERFACE
            else:
                kind = ContractKind.UNKNOWN
            name = m.group("name")
            open_brace = m.end() - 1  # points at '{'
            close, depth = _match_braces(
                cleaned, open_brace, bounds.max_nesting
            )
            budget.note_nesting(depth)
            if close < 0:
                span = _span_at(starts, m.start(), m.end())
                unsupported.append(
                    UnsupportedSyntaxFact(
                        reason="unmatched_braces_or_nesting_limit",
                        span=span,
                        construct=kind_raw,
                    )
                )
                diagnostics.append(
                    ParseDiagnostic(
                        code="unmatched_braces",
                        message=f"could not close body for {kind_raw} {name}",
                        severity=DiagnosticSeverity.WARNING,
                        span=span,
                    )
                )
                continue
            body_start = open_brace + 1
            body_end = close
            body = cleaned[body_start:body_end]
            type_span = _span_at(starts, m.start(), close + 1)
            bases_raw = m.group("bases") or ""
            inheritance = _parse_inheritance(
                bases_raw,
                m.start("bases") if m.group("bases") is not None else m.start(),
                starts,
            )

            functions: list[FunctionFact] = []
            modifiers: list[FunctionFact] = []
            state_vars: list[StateVariableFact] = []
            events: list[EventFact] = []
            errors: list[ErrorFact] = []
            calls: list[CallFact] = []
            storage_accesses: list[StorageAccessFact] = []
            auth_guards: list[AuthGuardFact] = []
            value_effects: list[ValueEffectFact] = []
            assembly_blocks: list[AssemblyBlockFact] = []
            type_unsupported: list[UnsupportedSyntaxFact] = []

            def abs_span(rel_start: int, rel_end: int) -> SourceSpan:
                return _span_at(
                    starts, body_start + rel_start, body_start + rel_end
                )

            # Nested type markers as unsupported-for-deep-extraction (still noted).
            for um in _STRUCT_RE.finditer(body):
                if not budget.use_fact():
                    break
                type_unsupported.append(
                    UnsupportedSyntaxFact(
                        reason="struct_body_not_fully_normalized",
                        span=abs_span(um.start(), um.end()),
                        construct="struct",
                    )
                )
            for um in _ENUM_RE.finditer(body):
                if not budget.use_fact():
                    break
                type_unsupported.append(
                    UnsupportedSyntaxFact(
                        reason="enum_body_not_fully_normalized",
                        span=abs_span(um.start(), um.end()),
                        construct="enum",
                    )
                )
            for um in _USER_TYPE_RE.finditer(body):
                if not budget.use_fact():
                    break
                type_unsupported.append(
                    UnsupportedSyntaxFact(
                        reason="user_defined_value_type",
                        span=abs_span(um.start(), um.end()),
                        construct="type",
                    )
                )
            for um in _USING_RE.finditer(body):
                if not budget.use_fact():
                    break
                type_unsupported.append(
                    UnsupportedSyntaxFact(
                        reason="using_for_directive",
                        span=abs_span(um.start(), um.end()),
                        construct="using",
                    )
                )
            for um in _TRY_RE.finditer(body):
                if not budget.use_fact():
                    break
                type_unsupported.append(
                    UnsupportedSyntaxFact(
                        reason="try_catch_partial",
                        span=abs_span(um.start(), um.end()),
                        construct="try",
                    )
                )
            for um in _UNCHECKED_RE.finditer(body):
                if not budget.use_fact():
                    break
                type_unsupported.append(
                    UnsupportedSyntaxFact(
                        reason="unchecked_block",
                        span=abs_span(um.start(), um.end()),
                        construct="unchecked",
                    )
                )

            # Events
            for em in _EVENT_RE.finditer(body):
                if budget.limited or not budget.use_decl() or not budget.use_node():
                    break
                params = _parse_params(
                    em.group("params"),
                    body_start + em.start("params"),
                    starts,
                )
                events.append(
                    EventFact(
                        name=em.group("name"),
                        span=abs_span(em.start(), em.end()),
                        parameters=params,
                        is_anonymous=bool(em.group("anon")),
                    )
                )

            # Errors
            for erm in _ERROR_RE.finditer(body):
                if budget.limited or not budget.use_decl() or not budget.use_node():
                    break
                params = _parse_params(
                    erm.group("params"),
                    body_start + erm.start("params"),
                    starts,
                )
                errors.append(
                    ErrorFact(
                        name=erm.group("name"),
                        span=abs_span(erm.start(), erm.end()),
                        parameters=params,
                    )
                )

            # State variables (best-effort; skip function-like prefixes)
            for sm in _STATE_VAR_RE.finditer(body):
                if budget.limited or not budget.use_decl() or not budget.use_node():
                    break
                type_name = re.sub(r"\s+", " ", sm.group("type")).strip()
                var_name = sm.group("name")
                if var_name in _KEYWORDS_NOT_STATE or type_name in _KEYWORDS_NOT_STATE:
                    continue
                # Avoid matching return types inside function bodies naively:
                # require declaration at "top level" of type body — depth 0 braces.
                prefix = body[: sm.start()]
                if prefix.count("{") != prefix.count("}"):
                    continue
                vis_raw = (sm.group("vis") or "").lower()
                visibility = _VISIBILITY.get(vis_raw, Visibility.DEFAULT)
                flags = sm.group("flags") or ""
                state_vars.append(
                    StateVariableFact(
                        name=var_name,
                        type_name=type_name,
                        span=abs_span(sm.start(), sm.end()),
                        visibility=visibility,
                        is_constant="constant" in flags,
                        is_immutable="immutable" in flags,
                    )
                )

            def _add_function(
                *,
                name: str,
                kind: str,
                start: int,
                end: int,
                params_text: str,
                params_abs: int,
                suffix: str,
            ) -> FunctionFact | None:
                if budget.limited or not budget.use_decl() or not budget.use_node():
                    return None
                visibility, mutability, mods, is_virtual, is_override = (
                    _parse_suffix_flags(suffix)
                )
                params = _parse_params(params_text, params_abs, starts)
                returns = _parse_returns(suffix, body_start + start, starts)
                # Body: search after the full match end.
                j = end
                while j < len(body) and body[j].isspace():
                    j += 1
                body_span: SourceSpan | None = None
                body_text = ""
                if j < len(body) and body[j] == "{":
                    close_i, depth_i = _match_braces(
                        body, j, bounds.max_nesting
                    )
                    budget.note_nesting(depth_i)
                    if close_i >= 0:
                        body_span = abs_span(j, close_i + 1)
                        body_text = body[j + 1 : close_i]
                fact = FunctionFact(
                    name=name,
                    span=abs_span(start, end if body_span is None else body_span.end_offset - body_start),
                    kind=kind,
                    visibility=visibility,
                    state_mutability=mutability,
                    parameters=params,
                    returns=returns,
                    modifiers=mods,
                    is_virtual=is_virtual,
                    is_override=is_override,
                    body_span=body_span,
                )
                # Intra-body facts
                if body_text and config.extract_calls:
                    self._extract_body_facts(
                        body_text,
                        body_abs=body_start + j + 1,
                        starts=starts,
                        enclosing=f"{name}",
                        config=config,
                        budget=budget,
                        calls=calls,
                        storage_accesses=storage_accesses,
                        auth_guards=auth_guards,
                        value_effects=value_effects,
                        assembly_blocks=assembly_blocks,
                        type_unsupported=type_unsupported,
                        modifiers_on_fn=mods,
                    )
                return fact

            for fm in _FUNCTION_RE.finditer(body):
                _check_context()
                fact = _add_function(
                    name=fm.group("name"),
                    kind="function",
                    start=fm.start(),
                    end=fm.end(),
                    params_text=fm.group("params"),
                    params_abs=body_start + fm.start("params"),
                    suffix=fm.group("suffix") or "",
                )
                if fact is not None:
                    functions.append(fact)

            for cm in _CONSTRUCTOR_RE.finditer(body):
                _check_context()
                fact = _add_function(
                    name="constructor",
                    kind="constructor",
                    start=cm.start(),
                    end=cm.end(),
                    params_text=cm.group("params"),
                    params_abs=body_start + cm.start("params"),
                    suffix=cm.group("suffix") or "",
                )
                if fact is not None:
                    functions.append(fact)

            for mm in _MODIFIER_DECL_RE.finditer(body):
                _check_context()
                fact = _add_function(
                    name=mm.group("name"),
                    kind="modifier",
                    start=mm.start(),
                    end=mm.end(),
                    params_text=mm.group("params") or "",
                    params_abs=body_start
                    + (mm.start("params") if mm.group("params") is not None else mm.start()),
                    suffix=mm.group("suffix") or "",
                )
                if fact is not None:
                    modifiers.append(fact)
                    # Modifier as auth guard surface
                    if config.extract_auth_guards and budget.use_fact():
                        auth_guards.append(
                            AuthGuardFact(
                                kind=AuthGuardKind.MODIFIER,
                                expression=mm.group("name"),
                                span=fact.span,
                                enclosing=name,
                            )
                        )

            for rm in _RECEIVE_RE.finditer(body):
                _check_context()
                fact = _add_function(
                    name="receive",
                    kind="receive",
                    start=rm.start(),
                    end=rm.end(),
                    params_text="",
                    params_abs=body_start + rm.start(),
                    suffix=rm.group("suffix") or "",
                )
                if fact is not None:
                    functions.append(fact)
                    if (
                        config.extract_value_effects
                        and budget.use_fact()
                    ):
                        value_effects.append(
                            ValueEffectFact(
                                kind=ValueEffectKind.PAYABLE_RECEIVE,
                                expression="receive()",
                                span=fact.span,
                                enclosing=name,
                            )
                        )

            for fbm in _FALLBACK_RE.finditer(body):
                _check_context()
                fact = _add_function(
                    name="fallback",
                    kind="fallback",
                    start=fbm.start(),
                    end=fbm.end(),
                    params_text=fbm.group("params") or "",
                    params_abs=body_start
                    + (
                        fbm.start("params")
                        if fbm.group("params") is not None
                        else fbm.start()
                    ),
                    suffix=fbm.group("suffix") or "",
                )
                if fact is not None:
                    functions.append(fact)
                    if "payable" in (fbm.group("suffix") or "") and config.extract_value_effects:
                        if budget.use_fact():
                            value_effects.append(
                                ValueEffectFact(
                                    kind=ValueEffectKind.PAYABLE_FALLBACK,
                                    expression="fallback()",
                                    span=fact.span,
                                    enclosing=name,
                                )
                            )

            type_defs.append(
                SolidityTypeDefinition(
                    name=name,
                    kind=kind,
                    span=type_span,
                    inheritance=inheritance,
                    functions=tuple(functions),
                    modifiers=tuple(modifiers),
                    state_variables=tuple(state_vars),
                    events=tuple(events),
                    errors=tuple(errors),
                    calls=tuple(calls),
                    storage_accesses=tuple(storage_accesses),
                    auth_guards=tuple(auth_guards),
                    value_effects=tuple(value_effects),
                    assembly_blocks=tuple(assembly_blocks),
                    unsupported=tuple(type_unsupported),
                )
            )

        # Cap diagnostics
        if budget.limited:
            for msg in budget.limit_messages:
                if len(diagnostics) >= bounds.max_diagnostics:
                    break
                diagnostics.append(
                    ParseDiagnostic(
                        code="resource_limit",
                        message=msg,
                        severity=DiagnosticSeverity.LIMIT,
                    )
                )
                budget.diagnostics = len(diagnostics)

        if len(diagnostics) > bounds.max_diagnostics:
            diagnostics = diagnostics[: bounds.max_diagnostics]

        source_digest = bytes_digest(source_bytes)
        unit = SoliditySourceUnit(
            source_digest=source_digest,
            path=path or "",
            byte_length=byte_length,
            pragmas=tuple(pragmas),
            imports=tuple(imports),
            type_definitions=tuple(type_defs),
            evidence_claims=tuple(evidence_claims),
            unsupported=tuple(unsupported),
        )

        usage = ParseUsage(
            source_bytes=byte_length,
            nodes=budget.nodes,
            max_nesting_seen=budget.max_nesting_seen,
            imports=budget.imports,
            diagnostics=len(diagnostics),
            declarations=budget.declarations,
            calls=budget.calls,
            facts=budget.facts,
            elapsed_ms=_elapsed_ms(),
        )

        if budget.limited:
            status = ParseStatus.PARTIAL
            partial = True
            notes = ("resource limits truncated extraction",)
        elif unsupported or any(t.unsupported for t in type_defs):
            status = ParseStatus.PARTIAL
            partial = True
            notes = ("partial coverage; unsupported syntax preserved explicitly",)
        else:
            status = ParseStatus.OK
            partial = False
            notes = ()

        # Empty source with no constructs is still OK (vacuous).
        return SolidityParseResult(
            status=status,
            identity=identity,
            bounds=bounds,
            config=config,
            usage=usage,
            source_unit=unit,
            diagnostics=tuple(diagnostics),
            partial=partial,
            notes=notes,
        )

    def _extract_body_facts(
        self,
        body_text: str,
        *,
        body_abs: int,
        starts: list[int],
        enclosing: str,
        config: ParserConfig,
        budget: _Budget,
        calls: list[CallFact],
        storage_accesses: list[StorageAccessFact],
        auth_guards: list[AuthGuardFact],
        value_effects: list[ValueEffectFact],
        assembly_blocks: list[AssemblyBlockFact],
        type_unsupported: list[UnsupportedSyntaxFact],
        modifiers_on_fn: tuple[str, ...] = (),
    ) -> None:
        def sp(a: int, b: int) -> SourceSpan:
            return _span_at(starts, body_abs + a, body_abs + b)

        # Modifier applications as auth guards
        if config.extract_auth_guards:
            for mod in modifiers_on_fn:
                if not budget.use_fact():
                    return
                kind = AuthGuardKind.MODIFIER
                low = mod.lower()
                if "onlyowner" in low or mod == "onlyOwner":
                    kind = AuthGuardKind.OWNABLE
                elif "onlyrole" in low or "role" in low:
                    kind = AuthGuardKind.ROLE
                auth_guards.append(
                    AuthGuardFact(
                        kind=kind,
                        expression=mod,
                        span=sp(0, min(len(body_text), 1)),
                        enclosing=enclosing,
                    )
                )
            for m in _ONLY_OWNER_RE.finditer(body_text):
                if not budget.use_fact():
                    return
                tok = m.group(1)
                kind = AuthGuardKind.CUSTOM
                if tok == "onlyOwner":
                    kind = AuthGuardKind.OWNABLE
                elif tok == "onlyRole":
                    kind = AuthGuardKind.ROLE
                auth_guards.append(
                    AuthGuardFact(
                        kind=kind,
                        expression=tok,
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )
            for m in _REQUIRE_RE.finditer(body_text):
                if not budget.use_fact():
                    return
                auth_guards.append(
                    AuthGuardFact(
                        kind=AuthGuardKind.REQUIRE,
                        expression="require",
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )
            for m in _ASSERT_RE.finditer(body_text):
                if not budget.use_fact():
                    return
                auth_guards.append(
                    AuthGuardFact(
                        kind=AuthGuardKind.ASSERT_STMT,
                        expression="assert",
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )
            for m in _REVERT_RE.finditer(body_text):
                if not budget.use_fact():
                    return
                auth_guards.append(
                    AuthGuardFact(
                        kind=AuthGuardKind.REVERT,
                        expression="revert",
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )

        if config.extract_calls:
            for m in _LOW_LEVEL_CALL_RE.finditer(body_text):
                if not budget.use_call() or not budget.use_fact():
                    return
                kind_map = {
                    "call": CallKind.LOW_LEVEL,
                    "delegatecall": CallKind.DELEGATECALL,
                    "staticcall": CallKind.STATICCALL,
                    "callcode": CallKind.CALLCODE,
                }
                calls.append(
                    CallFact(
                        kind=kind_map.get(m.group("kind"), CallKind.LOW_LEVEL),
                        callee=f".{m.group('kind')}",
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )
            for m in _CALL_RE.finditer(body_text):
                if not budget.use_call() or not budget.use_fact():
                    return
                callee = re.sub(r"\s+", " ", m.group("callee")).strip()
                if callee in {"if", "for", "while", "return", "require", "assert"}:
                    continue
                kind = CallKind.INTERNAL
                if callee.startswith("super."):
                    kind = CallKind.SUPER
                elif callee.startswith("new "):
                    kind = CallKind.CREATE
                elif callee.split(".")[0] in _BUILTIN_CALLS or callee in _BUILTIN_CALLS:
                    kind = CallKind.BUILTIN
                elif "." in callee:
                    kind = CallKind.EXTERNAL
                calls.append(
                    CallFact(
                        kind=kind,
                        callee=callee,
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )

        if config.extract_value_effects:
            for m in _VALUE_CALL_RE.finditer(body_text):
                if not budget.use_fact():
                    return
                expr = body_text[m.start() : m.end()]
                if ".transfer" in expr:
                    kind = ValueEffectKind.TRANSFER
                elif ".send" in expr:
                    kind = ValueEffectKind.SEND
                else:
                    kind = ValueEffectKind.CALL_VALUE
                value_effects.append(
                    ValueEffectFact(
                        kind=kind,
                        expression=expr[:128],
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )
            for m in _SELFDESTRUCT_RE.finditer(body_text):
                if not budget.use_fact():
                    return
                value_effects.append(
                    ValueEffectFact(
                        kind=ValueEffectKind.SELFDESTRUCT,
                        expression="selfdestruct",
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )

        if config.extract_storage:
            known_state_ish = re.findall(
                r"\b([A-Za-z_][\w$]*)\b", body_text
            )
            # Assignment writes
            for m in _ASSIGNMENT_RE.finditer(body_text):
                if not budget.use_fact():
                    return
                target = m.group("target")
                if target.split(".")[0] in _KEYWORDS_NOT_STATE:
                    continue
                if target.split(".")[0] in {
                    "uint",
                    "int",
                    "bool",
                    "address",
                    "string",
                    "bytes",
                    "memory",
                    "storage",
                    "calldata",
                }:
                    continue
                storage_accesses.append(
                    StorageAccessFact(
                        kind=StorageAccessKind.WRITE,
                        target=target,
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )
            # Simple reads: bare identifier followed by non-assign operators
            # Keep light to avoid noise; mark known this.x reads.
            for m in re.finditer(
                r"\bthis\.([A-Za-z_][\w$]*)\b", body_text
            ):
                if not budget.use_fact():
                    return
                storage_accesses.append(
                    StorageAccessFact(
                        kind=StorageAccessKind.READ,
                        target=f"this.{m.group(1)}",
                        span=sp(m.start(), m.end()),
                        enclosing=enclosing,
                    )
                )
            del known_state_ish  # reserved for future refinement

        if config.extract_assembly:
            for m in _ASSEMBLY_RE.finditer(body_text):
                if not budget.use_fact() or not budget.use_node():
                    return
                open_i = m.end() - 1
                close_i, depth_i = _match_braces(
                    body_text, open_i, budget.bounds.max_nesting
                )
                budget.note_nesting(depth_i)
                if close_i < 0:
                    type_unsupported.append(
                        UnsupportedSyntaxFact(
                            reason="assembly_unmatched_braces",
                            span=sp(m.start(), m.end()),
                            construct="assembly",
                        )
                    )
                    continue
                preview = body_text[open_i + 1 : close_i].strip()
                assembly_blocks.append(
                    AssemblyBlockFact(
                        span=sp(m.start(), close_i + 1),
                        dialect="assembly",
                        enclosing=enclosing,
                        body_preview=preview[:256],
                    )
                )
                type_unsupported.append(
                    UnsupportedSyntaxFact(
                        reason="assembly_opaque",
                        span=sp(m.start(), close_i + 1),
                        construct="assembly",
                        disposition="preserve_opaque",
                    )
                )


class UnavailableBackend:
    """Stub backend that always reports unavailable (typed UNSUPPORTED)."""

    def __init__(self, backend_id: str = "solc") -> None:
        self._backend_id = backend_id

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def available(self) -> bool:
        return False

    def parse_source(
        self,
        source: str,
        *,
        path: str = "",
        bounds: ParserBounds | None = None,
        config: ParserConfig | None = None,
        context: OperationContext | None = None,
        evidence: Mapping[str, Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> SolidityParseResult:
        bounds = bounds or ParserBounds()
        config = config or ParserConfig(backend=self._backend_id)
        identity = ParserIdentity(
            parser_id=PARSER_ID,
            parser_version=PARSER_VERSION,
            schema_version=PARSER_SCHEMA_VERSION,
            config_digest=config.content_digest,
            bounds_digest=content_digest(bounds.to_dict()),
        )
        return SolidityParseResult(
            status=ParseStatus.UNSUPPORTED,
            identity=identity,
            bounds=bounds,
            config=config,
            usage=ParseUsage(source_bytes=len(source.encode("utf-8"))),
            diagnostics=(
                ParseDiagnostic(
                    code="backend_unavailable",
                    message=(
                        f"parse backend {self._backend_id!r} is not available; "
                        "no system solc is required and nothing is installed at import time"
                    ),
                    severity=DiagnosticSeverity.ERROR,
                ),
            ),
            notes=("capability unavailability is a typed unsupported result",),
        )


@dataclass
class SolidityContractParser:
    """Injected, offline Solidity :class:`~..protocols.ContractParser`.

    Default construction uses the pure-Python inert backend.  Callers may inject
    an optional backend; when the configured backend is unavailable the parse
    returns :attr:`ParseStatus.UNSUPPORTED` rather than installing packages or
    requiring system ``solc``.
    """

    bounds: ParserBounds = field(default_factory=ParserBounds)
    config: ParserConfig = field(default_factory=ParserConfig)
    backend: SolidityParseBackend | None = None
    provider_name: str = PARSER_ID

    def __post_init__(self) -> None:
        if self.backend is None:
            if self.config.backend == "inert":
                object.__setattr__(self, "backend", InertSolidityBackend())
            else:
                # Non-inert without injection → unavailable typed result path.
                object.__setattr__(
                    self,
                    "backend",
                    UnavailableBackend(self.config.backend),
                )
        object.__setattr__(
            self,
            "_capabilities",
            Capabilities(
                provider=self.provider_name,
                chain_namespaces=frozenset({"eip155:*", "solidity"}),
                features=frozenset(
                    {
                        Capability.PARSE_ARTIFACT,
                        Capability.CAPABILITY_DISCOVERY,
                    }
                ),
                metadata=MappingProxyType(
                    {
                        "parser_id": PARSER_ID,
                        "parser_version": PARSER_VERSION,
                        "schema_version": PARSER_SCHEMA_VERSION,
                        "backend": self.config.backend,
                        "import_resolution": "never_network",
                        "requires_solc": False,
                    }
                ),
            ),
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities  # type: ignore[attr-defined]

    @property
    def available(self) -> bool:
        backend = self.backend
        return backend is not None and backend.available

    def parse_source(
        self,
        source: str,
        *,
        path: str = "",
        context: OperationContext | None = None,
        evidence: Mapping[str, Any] | None = None,
        bounds: ParserBounds | None = None,
        config: ParserConfig | None = None,
    ) -> SolidityParseResult:
        """Parse a single Solidity source string offline."""

        use_bounds = bounds or self.bounds
        use_config = config or self.config
        backend = self.backend
        if backend is None or not backend.available:
            return UnavailableBackend(use_config.backend).parse_source(
                source,
                path=path,
                bounds=use_bounds,
                config=use_config,
                context=context,
                evidence=evidence,
            )
        if isinstance(backend, InertSolidityBackend):
            return backend.parse_source(
                source,
                path=path,
                bounds=use_bounds,
                config=use_config,
                context=context,
                evidence=evidence,
            )
        # Generic protocol backend
        return backend.parse_source(
            source,
            path=path,
            bounds=use_bounds,
            config=use_config,
            context=context,
        )

    def parse(
        self,
        artifacts: Sequence[object],
        *,
        context: OperationContext,
    ) -> Sequence[ParsedArtifact]:
        """:class:`ContractParser` batch entrypoint (no network I/O)."""

        context.check_active()
        if not self.available and self.config.backend != "inert":
            # Still produce typed unsupported artifacts.
            pass

        items = list(artifacts)
        total_bytes = 0
        results: list[ParsedArtifact] = []

        for index, artifact in enumerate(items):
            context.check_active()
            source, path, evidence, digest_hint = _coerce_artifact(artifact)
            source_bytes = source.encode("utf-8")
            total_bytes += len(source_bytes)
            enforce_batch_limits(
                item_count=index + 1,
                response_bytes=total_bytes,
                limits=context.limits,
            )
            parse_result = self.parse_source(
                source,
                path=path,
                context=context,
                evidence=evidence,
            )
            artifact_digest = digest_hint or bytes_digest(source_bytes)
            payload = freeze_json(parse_result.to_dict())
            if not isinstance(payload, Mapping):
                raise InvalidRequestError("parse payload must be a mapping")
            results.append(
                ParsedArtifact(
                    artifact_digest=artifact_digest,
                    representation="solidity-source-unit-v1",
                    payload=payload,
                )
            )

        enforce_batch_limits(
            item_count=len(results),
            response_bytes=total_bytes,
            limits=context.limits,
        )
        return tuple(results)


def _coerce_artifact(
    artifact: object,
) -> tuple[str, str, Mapping[str, Any] | None, str]:
    """Normalize batch artifact inputs to (source, path, evidence, digest)."""

    if isinstance(artifact, str):
        return artifact, "", None, ""
    if isinstance(artifact, (bytes, bytearray)):
        data = bytes(artifact)
        return data.decode("utf-8"), "", None, bytes_digest(data)
    if isinstance(artifact, Mapping):
        source = artifact.get("source") or artifact.get("text") or artifact.get("content")
        if source is None and "bytes" in artifact:
            raw = artifact["bytes"]
            if isinstance(raw, str):
                # hex?
                source = raw
            elif isinstance(raw, (bytes, bytearray)):
                source = bytes(raw).decode("utf-8")
        if not isinstance(source, str):
            raise InvalidRequestError(
                "artifact mapping must include string source/text/content"
            )
        path = str(artifact.get("path") or artifact.get("name") or "")
        evidence = {
            k: artifact[k]
            for k in ("compiler", "address", "license", "verified_source", "source")
            if k in artifact and k != "source"
        }
        # Prefer explicit digest if tagged.
        digest = str(artifact.get("content_digest") or artifact.get("digest") or "")
        if digest and not digest.startswith("sha256:"):
            digest = ""
        return source, path, evidence or None, digest
    # Duck-typed objects with .source / .text
    for attr in ("source", "text", "content"):
        if hasattr(artifact, attr):
            value = getattr(artifact, attr)
            if isinstance(value, str):
                path = str(getattr(artifact, "path", "") or "")
                return value, path, None, ""
    raise InvalidRequestError(
        f"unsupported artifact type for Solidity parser: {type(artifact).__name__}"
    )


def parse_solidity(
    source: str,
    *,
    path: str = "",
    bounds: ParserBounds | None = None,
    config: ParserConfig | None = None,
    context: OperationContext | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> SolidityParseResult:
    """Convenience wrapper around :class:`SolidityContractParser.parse_source`."""

    parser = SolidityContractParser(
        bounds=bounds or ParserBounds(),
        config=config or ParserConfig(),
    )
    return parser.parse_source(
        source,
        path=path,
        context=context,
        evidence=evidence,
    )


def ensure_parser_available(parser: SolidityContractParser) -> None:
    """Raise :class:`UnsupportedCapabilityError` if the parser cannot run.

    Prefer typed :attr:`ParseStatus.UNSUPPORTED` results for normal control
    flow; this helper is for fail-closed injection sites that require presence.
    """

    if not parser.available:
        raise UnsupportedCapabilityError(
            f"Solidity parser backend {parser.config.backend!r} is unavailable"
        )


__all__ = [
    "InertSolidityBackend",
    "SolidityContractParser",
    "SolidityParseBackend",
    "UnavailableBackend",
    "ensure_parser_available",
    "parse_solidity",
]
