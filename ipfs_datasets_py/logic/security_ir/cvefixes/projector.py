"""Loss-aware vulnerable/fixed semantic projection for CVEfixes rows.

Source code, diffs, descriptions, and model output are untrusted, inert data.
This module never imports or executes projected code and never treats a
projection as policy authority.  It produces canonical :class:`CodeUnit`
records, observed semantic candidates, and explicit diagnostics for evidence
that cannot be projected safely.

The projector intentionally stops before graph construction and Security IR
conversion.  Those stages can consume the stable identities emitted here
without having to reinterpret an ambiguous source row.
"""

from __future__ import annotations

import ast
import base64
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import re
import textwrap
from types import MappingProxyType
from typing import Any, Final, Protocol

from ...ir_core.identity import CanonicalIdentity, canonical_identity
from .schemas import CodeUnit, canonical_config_cid
from .source_snapshot import (
    CVEFIXES_DATASET_ID,
    CVEFIXES_REVISION,
    CVEfixesSourceRow,
)


PROJECTOR_SCHEMA_VERSION: Final = "cvefixes-semantic-projector/v1"
PROJECTOR_CONFIG_SCHEMA_VERSION: Final = "cvefixes-semantic-projector-config/v1"
AMBIGUOUS_PATH: Final = "<ambiguous>"
UNKNOWN_PATH: Final = "<unknown>"
_IR_CORE_CID_HEADER: Final = b"\x01\x55\x12\x20"


class ProjectionError(ValueError):
    """Raised for malformed projector configuration or caller-supplied facts."""


def _validate_cid(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"b[a-z2-7]{58}", value):
        raise ProjectionError(f"{label} must be an ir_core raw/sha2-256 CIDv1")
    try:
        encoded = value[1:].upper()
        raw = base64.b32decode(encoded + ("=" * ((-len(encoded)) % 8)))
    except (ValueError, base64.binascii.Error) as exc:
        raise ProjectionError(
            f"{label} must be an ir_core raw/sha2-256 CIDv1"
        ) from exc
    if len(raw) != 36 or not raw.startswith(_IR_CORE_CID_HEADER):
        raise ProjectionError(f"{label} must be an ir_core raw/sha2-256 CIDv1")
    return value


class UnitKind(str, Enum):
    FILE = "file"
    HUNK = "hunk"
    SYMBOL = "symbol"


class EvidencePolarity(str, Enum):
    """How a code unit participates in vulnerable/fixed evaluation."""

    VULNERABLE_POSITIVE = "vulnerable_positive"
    FIXED_NEGATIVE = "fixed_negative"


class SemanticKind(str, Enum):
    PRECONDITION = "precondition"
    ACTION = "action"
    EFFECT = "effect"
    MITIGATION = "mitigation"


class ExtractionMethod(str, Enum):
    DETERMINISTIC_SYNTAX = "deterministic_syntax"
    MODEL_ASSISTED = "model_assisted"


class DiagnosticCode(str, Enum):
    UNSUPPORTED_LANGUAGE = "language.unsupported"
    AMBIGUOUS_PATH = "path.ambiguous"
    UNKNOWN_PATH = "path.unknown"
    PATH_MISMATCH = "path.diff_not_declared"
    AMBIGUOUS_HUNK = "hunk.ambiguous"
    DIFF_UNPARSEABLE = "diff.unparseable"
    MISSING_VULNERABLE = "pair.vulnerable_missing"
    MISSING_FIXED = "pair.fixed_missing"
    SYNTAX_UNPARSEABLE = "syntax.unparseable"
    LIMIT_EXCEEDED = "projection.limit_exceeded"
    NO_SEMANTIC_FACTS = "semantic.no_deterministic_facts"


@dataclass(frozen=True, slots=True)
class ProjectorConfig:
    """Resource bounds and public-output limits included in every identity."""

    max_hunks: int = 2_048
    max_symbols_per_unit: int = 4_096
    max_semantic_facts: int = 65_536
    max_excerpt_chars: int = 512
    max_predicate_chars: int = 4_096
    schema_version: str = PROJECTOR_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_hunks",
            "max_symbols_per_unit",
            "max_semantic_facts",
            "max_excerpt_chars",
            "max_predicate_chars",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ProjectionError(f"{name} must be a positive integer")
        if self.schema_version != PROJECTOR_CONFIG_SCHEMA_VERSION:
            raise ProjectionError(
                f"unsupported projector config schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_excerpt_chars": self.max_excerpt_chars,
            "max_hunks": self.max_hunks,
            "max_predicate_chars": self.max_predicate_chars,
            "max_semantic_facts": self.max_semantic_facts,
            "max_symbols_per_unit": self.max_symbols_per_unit,
            "schema_version": self.schema_version,
        }

    @property
    def cid(self) -> str:
        return canonical_config_cid(
            self.to_dict(), schema_version=self.schema_version
        )


@dataclass(frozen=True, slots=True)
class ProjectionDiagnostic:
    """A retained reason why source evidence was incomplete or ambiguous."""

    code: DiagnosticCode
    message: str
    path: str = ""
    unit_kind: str = ""
    unit_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, DiagnosticCode):
            raise ProjectionError("diagnostic code must be DiagnosticCode")
        if not isinstance(self.message, str) or not self.message:
            raise ProjectionError("diagnostic message must be non-empty")
        if self.unit_index is not None and (
            type(self.unit_index) is not int or self.unit_index < 0
        ):
            raise ProjectionError("diagnostic unit_index must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "path": self.path,
            "unit_index": self.unit_index,
            "unit_kind": self.unit_kind,
        }


@dataclass(frozen=True, slots=True)
class ModelSemanticCandidate:
    """An explicitly model-assisted candidate supplied by a separate stage.

    The model identity and immutable revision are mandatory.  The projector
    only binds this inert output to an existing code unit; it never invokes a
    model itself.
    """

    kind: SemanticKind
    predicate: str
    evidence_polarity: EvidencePolarity
    code_unit_cid: str
    model_id: str
    model_revision: str
    confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SemanticKind):
            raise ProjectionError("model candidate kind must be SemanticKind")
        if not isinstance(self.evidence_polarity, EvidencePolarity):
            raise ProjectionError(
                "model candidate evidence_polarity must be EvidencePolarity"
            )
        for name in ("predicate", "code_unit_cid", "model_id", "model_revision"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or "\x00" in value
            ):
                raise ProjectionError(f"model candidate {name} is invalid")
        _validate_cid(self.code_unit_cid, "model candidate code_unit_cid")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ProjectionError(
                "model candidate confidence must be between zero and one"
            )


@dataclass(frozen=True, slots=True)
class SemanticFact:
    """A non-authoritative observed candidate bound to exact code evidence."""

    kind: SemanticKind
    predicate: str
    evidence_polarity: EvidencePolarity
    extraction_method: ExtractionMethod
    code_unit_cid: str
    source_cid: str
    config_cid: str
    confidence: float = 1.0
    model_id: str = ""
    model_revision: str = ""
    fact_id: str = ""
    schema_version: str = PROJECTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SemanticKind):
            raise ProjectionError("semantic kind must be SemanticKind")
        if not isinstance(self.evidence_polarity, EvidencePolarity):
            raise ProjectionError("semantic evidence polarity is invalid")
        if not isinstance(self.extraction_method, ExtractionMethod):
            raise ProjectionError("semantic extraction method is invalid")
        for name in ("predicate", "code_unit_cid", "source_cid", "config_cid"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or "\x00" in value
            ):
                raise ProjectionError(f"semantic {name} is invalid")
        for name in ("code_unit_cid", "source_cid", "config_cid"):
            _validate_cid(getattr(self, name), f"semantic {name}")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ProjectionError("semantic confidence must be between zero and one")
        object.__setattr__(self, "confidence", float(self.confidence))
        if self.schema_version != PROJECTOR_SCHEMA_VERSION:
            raise ProjectionError(
                f"unsupported semantic fact schema {self.schema_version!r}"
            )
        if self.extraction_method is ExtractionMethod.DETERMINISTIC_SYNTAX:
            if self.confidence != 1.0 or self.model_id or self.model_revision:
                raise ProjectionError(
                    "deterministic facts cannot carry model identity or confidence"
                )
        elif not self.model_id or not self.model_revision:
            raise ProjectionError(
                "model-assisted facts require model_id and model_revision"
            )
        computed = self.identity.cid
        if self.fact_id and self.fact_id != computed:
            raise ProjectionError("semantic fact_id does not match content")
        object.__setattr__(self, "fact_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "authority": "observed_candidate",
            "code_unit_cid": self.code_unit_cid,
            "confidence": self.confidence,
            "config_cid": self.config_cid,
            "evidence_polarity": self.evidence_polarity.value,
            "extraction_method": self.extraction_method.value,
            "grants_execution_authority": False,
            "kind": self.kind.value,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "predicate": self.predicate,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain="cvefixes-security-ir/semantic-fact",
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.fact_id

    def to_dict(self) -> dict[str, Any]:
        return {"fact_id": self.fact_id, **self.deterministic_dict()}


@dataclass(frozen=True, slots=True)
class VulnerableFixedPair:
    """Loss-aware pairing; either side can be absent but never silently lost."""

    unit_kind: UnitKind
    path: str
    unit_index: int
    symbol: str
    vulnerable_cid: str
    fixed_cid: str
    source_cid: str
    pair_id: str = ""
    schema_version: str = PROJECTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.unit_kind, UnitKind):
            raise ProjectionError("pair unit_kind must be UnitKind")
        if not isinstance(self.path, str) or not self.path:
            raise ProjectionError("pair path must be non-empty")
        if type(self.unit_index) is not int or self.unit_index < 0:
            raise ProjectionError("pair unit_index must be non-negative")
        if not self.vulnerable_cid and not self.fixed_cid:
            raise ProjectionError("pair must retain at least one side")
        _validate_cid(self.source_cid, "pair source_cid")
        for name in ("vulnerable_cid", "fixed_cid"):
            value = getattr(self, name)
            if value:
                _validate_cid(value, f"pair {name}")
        if self.schema_version != PROJECTOR_SCHEMA_VERSION:
            raise ProjectionError(
                f"unsupported pair schema {self.schema_version!r}"
            )
        computed = self.identity.cid
        if self.pair_id and self.pair_id != computed:
            raise ProjectionError("pair_id does not match content")
        object.__setattr__(self, "pair_id", computed)

    @property
    def complete(self) -> bool:
        return bool(self.vulnerable_cid and self.fixed_cid)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "fixed_cid": self.fixed_cid,
            "path": self.path,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "symbol": self.symbol,
            "unit_index": self.unit_index,
            "unit_kind": self.unit_kind.value,
            "vulnerable_cid": self.vulnerable_cid,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain="cvefixes-security-ir/vulnerable-fixed-pair",
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.pair_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "pair_id": self.pair_id,
            **self.deterministic_dict(),
        }


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """Complete deterministic result, including abstentions and diagnostics."""

    source_cid: str
    config_cid: str
    language: str
    code_units: tuple[CodeUnit, ...]
    pairs: tuple[VulnerableFixedPair, ...]
    semantic_facts: tuple[SemanticFact, ...]
    diagnostics: tuple[ProjectionDiagnostic, ...]
    projection_id: str = ""
    schema_version: str = PROJECTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_cid or not self.config_cid:
            raise ProjectionError("projection source_cid and config_cid are required")
        _validate_cid(self.source_cid, "projection source_cid")
        _validate_cid(self.config_cid, "projection config_cid")
        if self.schema_version != PROJECTOR_SCHEMA_VERSION:
            raise ProjectionError(
                f"unsupported projection schema {self.schema_version!r}"
            )
        units = tuple(sorted(self.code_units, key=lambda item: item.cid))
        pairs = tuple(sorted(self.pairs, key=lambda item: item.cid))
        facts = tuple(sorted(self.semantic_facts, key=lambda item: item.cid))
        diagnostics = tuple(
            sorted(
                self.diagnostics,
                key=lambda item: (
                    item.code.value,
                    item.path,
                    item.unit_kind,
                    -1 if item.unit_index is None else item.unit_index,
                    item.message,
                ),
            )
        )
        if len({item.cid for item in units}) != len(units):
            raise ProjectionError("projection contains duplicate code units")
        if len({item.cid for item in pairs}) != len(pairs):
            raise ProjectionError("projection contains duplicate pairs")
        if len({item.cid for item in facts}) != len(facts):
            raise ProjectionError("projection contains duplicate semantic facts")
        unit_ids = {item.cid for item in units}
        if any(
            cid and cid not in unit_ids
            for pair in pairs
            for cid in (pair.vulnerable_cid, pair.fixed_cid)
        ):
            raise ProjectionError("pair references a code unit outside the result")
        if any(item.code_unit_cid not in unit_ids for item in facts):
            raise ProjectionError(
                "semantic fact references a code unit outside the result"
            )
        object.__setattr__(self, "code_units", units)
        object.__setattr__(self, "pairs", pairs)
        object.__setattr__(self, "semantic_facts", facts)
        object.__setattr__(self, "diagnostics", diagnostics)
        computed = self.identity.cid
        if self.projection_id and self.projection_id != computed:
            raise ProjectionError("projection_id does not match content")
        object.__setattr__(self, "projection_id", computed)

    @property
    def complete_pairs(self) -> tuple[VulnerableFixedPair, ...]:
        return tuple(item for item in self.pairs if item.complete)

    @property
    def supported(self) -> bool:
        return not any(
            item.code is DiagnosticCode.UNSUPPORTED_LANGUAGE
            for item in self.diagnostics
        )

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "code_units": [item.to_dict() for item in self.code_units],
            "config_cid": self.config_cid,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "language": self.language,
            "pairs": [item.to_dict() for item in self.pairs],
            "schema_version": self.schema_version,
            "semantic_facts": [item.to_dict() for item in self.semantic_facts],
            "source_cid": self.source_cid,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain="cvefixes-security-ir/projection",
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.projection_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            **self.deterministic_dict(),
        }


@dataclass(frozen=True, slots=True)
class SymbolObservation:
    name: str
    kind: str
    start_line: int
    end_line: int
    body: str


@dataclass(frozen=True, slots=True)
class SyntaxObservation:
    kind: SemanticKind
    predicate: str


@dataclass(frozen=True, slots=True)
class LanguageProjection:
    symbols: tuple[SymbolObservation, ...] = ()
    observations: tuple[SyntaxObservation, ...] = ()


class LanguageAdapter(Protocol):
    """Deterministic, non-executing syntax projection interface."""

    language: str
    version: str

    def project(self, source: str) -> LanguageProjection:
        """Parse inert source or raise ``SyntaxError`` when it is not parseable."""


def _qualified_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return "<dynamic>"


class PythonLanguageAdapter:
    """Standard-library Python AST adapter; parsing never imports source code."""

    language = "python"
    version = "python-ast/v1"

    def project(self, source: str) -> LanguageProjection:
        normalized = textwrap.dedent(source)
        tree = ast.parse(normalized, mode="exec")
        lines = normalized.splitlines(keepends=True)
        symbols: list[SymbolObservation] = []
        observations: set[SyntaxObservation] = set()
        stack: list[str] = []

        class Visitor(ast.NodeVisitor):
            def _visit_symbol(self, node: ast.AST, name: str, kind: str) -> None:
                qualified = ".".join((*stack, name))
                start = int(getattr(node, "lineno", 1))
                end = int(getattr(node, "end_lineno", start))
                symbols.append(
                    SymbolObservation(
                        name=qualified,
                        kind=kind,
                        start_line=start,
                        end_line=end,
                        body="".join(lines[start - 1 : end]),
                    )
                )
                stack.append(name)
                self.generic_visit(node)
                stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._visit_symbol(node, node.name, "function")

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._visit_symbol(node, node.name, "async_function")

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self._visit_symbol(node, node.name, "class")

            def visit_Call(self, node: ast.Call) -> None:
                observations.add(
                    SyntaxObservation(
                        SemanticKind.ACTION,
                        f"call:{_qualified_call_name(node.func)}",
                    )
                )
                self.generic_visit(node)

            def visit_If(self, node: ast.If) -> None:
                observations.add(
                    SyntaxObservation(
                        SemanticKind.PRECONDITION,
                        "condition:" + ast.dump(node.test, include_attributes=False),
                    )
                )
                self.generic_visit(node)

            def visit_While(self, node: ast.While) -> None:
                observations.add(
                    SyntaxObservation(
                        SemanticKind.PRECONDITION,
                        "condition:" + ast.dump(node.test, include_attributes=False),
                    )
                )
                self.generic_visit(node)

            def visit_Assert(self, node: ast.Assert) -> None:
                observations.add(
                    SyntaxObservation(
                        SemanticKind.PRECONDITION,
                        "assert:" + ast.dump(node.test, include_attributes=False),
                    )
                )
                self.generic_visit(node)

            def visit_Return(self, node: ast.Return) -> None:
                observations.add(SyntaxObservation(SemanticKind.EFFECT, "return"))
                self.generic_visit(node)

            def visit_Raise(self, node: ast.Raise) -> None:
                name = (
                    _qualified_call_name(node.exc.func)
                    if isinstance(node.exc, ast.Call)
                    else type(node.exc).__name__ if node.exc is not None else "reraised"
                )
                observations.add(
                    SyntaxObservation(SemanticKind.EFFECT, f"raise:{name}")
                )
                self.generic_visit(node)

        Visitor().visit(tree)
        return LanguageProjection(
            symbols=tuple(
                sorted(
                    symbols,
                    key=lambda item: (
                        item.name,
                        item.kind,
                        item.start_line,
                        item.end_line,
                    ),
                )
            ),
            observations=tuple(
                sorted(observations, key=lambda item: (item.kind.value, item.predicate))
            ),
        )


_LANGUAGE_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "py": "python",
        "python": "python",
        "python2": "python",
        "python3": "python",
    }
)


class LanguageAdapterRegistry:
    """Immutable-by-construction lookup for reviewed deterministic adapters."""

    def __init__(
        self,
        adapters: Iterable[LanguageAdapter] = (PythonLanguageAdapter(),),
        aliases: Mapping[str, str] = _LANGUAGE_ALIASES,
    ) -> None:
        values: dict[str, LanguageAdapter] = {}
        for adapter in adapters:
            language = getattr(adapter, "language", "")
            version = getattr(adapter, "version", "")
            if (
                not isinstance(language, str)
                or not language
                or language != language.lower()
                or not isinstance(version, str)
                or not version
                or not callable(getattr(adapter, "project", None))
            ):
                raise ProjectionError("language adapter contract is invalid")
            if language in values:
                raise ProjectionError(f"duplicate language adapter {language!r}")
            values[language] = adapter
        normalized_aliases: dict[str, str] = {}
        for alias, target in aliases.items():
            if (
                not isinstance(alias, str)
                or not alias
                or not isinstance(target, str)
                or target not in values
            ):
                raise ProjectionError("language alias references no adapter")
            normalized_aliases[alias.casefold()] = target
        for language in values:
            normalized_aliases.setdefault(language, language)
        self._adapters = MappingProxyType(values)
        self._aliases = MappingProxyType(normalized_aliases)

    def normalize(self, language: str | None) -> str:
        if not isinstance(language, str) or not language.strip():
            return "unknown"
        value = language.strip().casefold()
        return self._aliases.get(value, value)

    def resolve(self, language: str | None) -> LanguageAdapter | None:
        return self._adapters.get(self.normalize(language))

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapters": {
                name: adapter.version
                for name, adapter in sorted(self._adapters.items())
            },
            "aliases": dict(sorted(self._aliases.items())),
        }


DEFAULT_LANGUAGE_ADAPTERS: Final = LanguageAdapterRegistry()


@dataclass(frozen=True, slots=True)
class _DiffHunk:
    path: str
    old_start: int
    new_start: int
    old_body: str
    new_body: str
    header: str
    ambiguous: bool = False


_HUNK_RE: Final = re.compile(
    r"^@@ -(?P<old>[0-9]+)(?:,(?P<old_count>[0-9]+))? "
    r"\+(?P<new>[0-9]+)(?:,(?P<new_count>[0-9]+))? @@(?P<label>.*)$"
)


def _diff_path(value: str) -> str:
    value = value.split("\t", 1)[0].strip()
    if value in {"/dev/null", ""}:
        return ""
    if value.startswith(("a/", "b/")):
        return value[2:]
    return value


def _parse_diff(
    diff: str,
    declared_paths: tuple[str, ...],
    *,
    max_hunks: int,
) -> tuple[tuple[_DiffHunk, ...], tuple[ProjectionDiagnostic, ...]]:
    if not diff:
        return (), ()
    lines = diff.splitlines(keepends=True)
    hunks: list[_DiffHunk] = []
    diagnostics: list[ProjectionDiagnostic] = []
    current_old_path = ""
    current_new_path = ""
    current_header = ""
    old_start = 0
    new_start = 0
    old_lines: list[str] = []
    new_lines: list[str] = []
    saw_header = False
    in_hunk = False

    def selected_path() -> tuple[str, bool]:
        path = current_new_path or current_old_path
        if path:
            return path, False
        if len(declared_paths) == 1:
            return declared_paths[0], False
        return (AMBIGUOUS_PATH if declared_paths else UNKNOWN_PATH), True

    def flush() -> None:
        nonlocal old_lines, new_lines
        if not old_lines and not new_lines:
            return
        path, ambiguous = selected_path()
        hunks.append(
            _DiffHunk(
                path=path,
                old_start=old_start,
                new_start=new_start,
                old_body="".join(old_lines),
                new_body="".join(new_lines),
                header=current_header,
                ambiguous=ambiguous,
            )
        )
        old_lines = []
        new_lines = []

    for line in lines:
        if line.startswith("diff --git "):
            flush()
            current_old_path = ""
            current_new_path = ""
            current_header = ""
            in_hunk = False
            continue
        if not in_hunk and line.startswith("--- "):
            current_old_path = _diff_path(line[4:])
            continue
        if not in_hunk and line.startswith("+++ "):
            current_new_path = _diff_path(line[4:])
            continue
        match = _HUNK_RE.match(line.rstrip("\r\n"))
        if match:
            flush()
            saw_header = True
            in_hunk = True
            current_header = line.rstrip("\r\n")
            old_start = int(match.group("old"))
            new_start = int(match.group("new"))
            continue
        if line.startswith("\\ No newline at end of file"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            new_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            old_lines.append(line[1:])
        elif line.startswith(" "):
            old_lines.append(line[1:])
            new_lines.append(line[1:])
        elif line.startswith(
            (
                "index ",
                "new file mode ",
                "deleted file mode ",
                "old mode ",
                "new mode ",
                "similarity index ",
                "rename from ",
                "rename to ",
                "Binary files ",
            )
        ):
            continue
        elif not saw_header and line.strip():
            # A context-less source often stores only ``-``/``+`` lines.  Any
            # other material means its boundaries cannot be interpreted.
            diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.DIFF_UNPARSEABLE,
                    "diff contains content outside a unified hunk",
                )
            )
    flush()
    if len(hunks) > max_hunks:
        diagnostics.append(
            ProjectionDiagnostic(
                DiagnosticCode.LIMIT_EXCEEDED,
                f"diff has {len(hunks)} hunks; retained first {max_hunks}",
                unit_kind=UnitKind.HUNK.value,
            )
        )
        hunks = hunks[:max_hunks]
    for index, hunk in enumerate(hunks):
        if hunk.ambiguous:
            diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.AMBIGUOUS_HUNK,
                    "hunk could not be assigned to exactly one declared path",
                    path=hunk.path,
                    unit_kind=UnitKind.HUNK.value,
                    unit_index=index,
                )
            )
        if (
            hunk.path not in {AMBIGUOUS_PATH, UNKNOWN_PATH}
            and declared_paths
            and hunk.path not in declared_paths
        ):
            diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.PATH_MISMATCH,
                    "diff path is not present in the row's declared file_paths",
                    path=hunk.path,
                    unit_kind=UnitKind.HUNK.value,
                    unit_index=index,
                )
            )
    return tuple(hunks), tuple(diagnostics)


def canonical_source_row_cid(row: CVEfixesSourceRow) -> str:
    """Return the pinned-row identity used when no upstream CID is supplied."""

    if not isinstance(row, CVEfixesSourceRow):
        raise TypeError("row must be CVEfixesSourceRow")
    return canonical_identity(
        {
            "dataset_id": CVEFIXES_DATASET_ID,
            "row": row.to_dict(),
            "source_revision": CVEFIXES_REVISION,
        },
        domain="cvefixes-security-ir/pinned-source-row",
        schema_version="cvefixes-pinned-source-row/v1",
    ).cid


@dataclass(slots=True)
class _ProjectionBuilder:
    row: CVEfixesSourceRow
    source_cid: str
    config: ProjectorConfig
    config_cid: str
    language: str
    adapter: LanguageAdapter | None
    units: list[CodeUnit] = field(default_factory=list)
    pairs: list[VulnerableFixedPair] = field(default_factory=list)
    facts: list[SemanticFact] = field(default_factory=list)
    diagnostics: list[ProjectionDiagnostic] = field(default_factory=list)

    def bounded_predicate(self, value: str) -> str:
        if len(value) <= self.config.max_predicate_chars:
            return value
        message = (
            "semantic predicate exceeded max_predicate_chars; retained a "
            "bounded prefix and full-content digest"
        )
        if not any(
            item.code is DiagnosticCode.LIMIT_EXCEEDED
            and item.message == message
            for item in self.diagnostics
        ):
            self.diagnostics.append(
                ProjectionDiagnostic(DiagnosticCode.LIMIT_EXCEEDED, message)
            )
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        suffix = f":sha256:{digest}"
        if self.config.max_predicate_chars <= len(suffix):
            return suffix[-self.config.max_predicate_chars :]
        return value[: self.config.max_predicate_chars - len(suffix)] + suffix

    def add_pair(
        self,
        *,
        unit_kind: UnitKind,
        path: str,
        unit_index: int,
        vulnerable_body: str,
        fixed_body: str,
        parent_cids: tuple[str, ...],
        symbol: str = "",
        start_lines: tuple[int, int] = (0, 0),
        extra_payload: Mapping[str, Any] | None = None,
        derive_syntax: bool = True,
    ) -> VulnerableFixedPair:
        pair_key = (
            f"{unit_kind.value}:{path}:{unit_index}:"
            f"{symbol or '<anonymous>'}"
        )
        side_units: dict[str, CodeUnit] = {}
        for polarity, body, start_line in (
            ("vulnerable", vulnerable_body, start_lines[0]),
            ("fixed", fixed_body, start_lines[1]),
        ):
            if not body:
                continue
            body_identity = canonical_identity(
                {"body": body},
                domain="cvefixes-security-ir/code-body",
                schema_version="cvefixes-code-body/v1",
            )
            payload: dict[str, Any] = {
                "body_cid": body_identity.cid,
                "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "commit_hash": self.row.hash,
                "cve_id": self.row.cve_id,
                "end_line": (
                    start_line + max(0, len(body.splitlines()) - 1)
                    if start_line
                    else 0
                ),
                "evidence_polarity": (
                    EvidencePolarity.VULNERABLE_POSITIVE.value
                    if polarity == "vulnerable"
                    else EvidencePolarity.FIXED_NEGATIVE.value
                ),
                "excerpt": body[: self.config.max_excerpt_chars],
                "excerpt_truncated": len(body) > self.config.max_excerpt_chars,
                "extraction_method": ExtractionMethod.DETERMINISTIC_SYNTAX.value,
                "grants_execution_authority": False,
                "pair_key": pair_key,
                "repository": self.row.repo_url,
                "source_revision": CVEFIXES_REVISION,
                "source_row_index": self.row.row_index,
                "start_line": start_line,
                "symbol": symbol,
            }
            if extra_payload:
                payload.update(extra_payload)
            unit = CodeUnit(
                source_cids=(self.source_cid,),
                parent_cids=parent_cids,
                config_cid=self.config_cid,
                unit_kind=unit_kind.value,
                language=self.language,
                path=path,
                polarity=polarity,
                payload=payload,
            )
            self.units.append(unit)
            side_units[polarity] = unit
        pair = VulnerableFixedPair(
            unit_kind=unit_kind,
            path=path,
            unit_index=unit_index,
            symbol=symbol,
            vulnerable_cid=(
                side_units["vulnerable"].cid if "vulnerable" in side_units else ""
            ),
            fixed_cid=side_units["fixed"].cid if "fixed" in side_units else "",
            source_cid=self.source_cid,
        )
        self.pairs.append(pair)
        if "vulnerable" not in side_units:
            self.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.MISSING_VULNERABLE,
                    "fixed evidence has no vulnerable counterpart",
                    path=path,
                    unit_kind=unit_kind.value,
                    unit_index=unit_index,
                )
            )
        if "fixed" not in side_units:
            self.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.MISSING_FIXED,
                    "vulnerable evidence has no fixed counterpart",
                    path=path,
                    unit_kind=unit_kind.value,
                    unit_index=unit_index,
                )
            )
        if derive_syntax and self.adapter is not None:
            self._derive_syntax(
                pair,
                vulnerable_body,
                fixed_body,
                side_units,
                path=path,
                unit_index=unit_index,
                parent_cids=parent_cids,
            )
        return pair

    def _derive_syntax(
        self,
        pair: VulnerableFixedPair,
        vulnerable_body: str,
        fixed_body: str,
        side_units: Mapping[str, CodeUnit],
        *,
        path: str,
        unit_index: int,
        parent_cids: tuple[str, ...],
    ) -> None:
        projections: dict[str, LanguageProjection] = {}
        for polarity, body in (
            ("vulnerable", vulnerable_body),
            ("fixed", fixed_body),
        ):
            if not body:
                continue
            try:
                projections[polarity] = self.adapter.project(body)
            except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
                self.diagnostics.append(
                    ProjectionDiagnostic(
                        DiagnosticCode.SYNTAX_UNPARSEABLE,
                        f"{polarity} source was retained but syntax projection "
                        f"abstained ({type(exc).__name__})",
                        path=path,
                        unit_kind=pair.unit_kind.value,
                        unit_index=unit_index,
                    )
                )

        for polarity, projection in projections.items():
            code_unit = side_units[polarity]
            evidence = (
                EvidencePolarity.VULNERABLE_POSITIVE
                if polarity == "vulnerable"
                else EvidencePolarity.FIXED_NEGATIVE
            )
            for observation in projection.observations:
                self.facts.append(
                    SemanticFact(
                        kind=observation.kind,
                        predicate=self.bounded_predicate(observation.predicate),
                        evidence_polarity=evidence,
                        extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                        code_unit_cid=code_unit.cid,
                        source_cid=self.source_cid,
                        config_cid=self.config_cid,
                    )
                )

        vulnerable_observations = set(
            projections.get("vulnerable", LanguageProjection()).observations
        )
        fixed_observations = set(
            projections.get("fixed", LanguageProjection()).observations
        )
        fixed_unit = side_units.get("fixed")
        if fixed_unit is not None:
            for observation in sorted(
                fixed_observations - vulnerable_observations,
                key=lambda item: (item.kind.value, item.predicate),
            ):
                if observation.kind in {
                    SemanticKind.ACTION,
                    SemanticKind.PRECONDITION,
                }:
                    self.facts.append(
                        SemanticFact(
                            kind=SemanticKind.MITIGATION,
                            predicate=self.bounded_predicate(
                                (
                                    "added_guard:"
                                    if observation.kind
                                    is SemanticKind.PRECONDITION
                                    else "added_action:"
                                )
                                + observation.predicate
                            ),
                            evidence_polarity=EvidencePolarity.FIXED_NEGATIVE,
                            extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                            code_unit_cid=fixed_unit.cid,
                            source_cid=self.source_cid,
                            config_cid=self.config_cid,
                        )
                    )

        # Symbol pairs are derived only from a file-level parse.  A hunk often
        # lacks surrounding indentation and cannot establish symbol bounds.
        if pair.unit_kind is not UnitKind.FILE:
            return
        vulnerable_symbols = {
            (item.name, item.kind): item
            for item in projections.get("vulnerable", LanguageProjection()).symbols
        }
        fixed_symbols = {
            (item.name, item.kind): item
            for item in projections.get("fixed", LanguageProjection()).symbols
        }
        symbol_keys = sorted(set(vulnerable_symbols) | set(fixed_symbols))
        if len(symbol_keys) > self.config.max_symbols_per_unit:
            self.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.LIMIT_EXCEEDED,
                    f"file has {len(symbol_keys)} symbols; retained first "
                    f"{self.config.max_symbols_per_unit}",
                    path=path,
                    unit_kind=UnitKind.SYMBOL.value,
                )
            )
            symbol_keys = symbol_keys[: self.config.max_symbols_per_unit]
        for symbol_index, key in enumerate(symbol_keys):
            vulnerable_symbol = vulnerable_symbols.get(key)
            fixed_symbol = fixed_symbols.get(key)
            self.add_pair(
                unit_kind=UnitKind.SYMBOL,
                path=path,
                unit_index=symbol_index,
                symbol=key[0],
                vulnerable_body=(
                    vulnerable_symbol.body if vulnerable_symbol is not None else ""
                ),
                fixed_body=fixed_symbol.body if fixed_symbol is not None else "",
                start_lines=(
                    vulnerable_symbol.start_line if vulnerable_symbol else 0,
                    fixed_symbol.start_line if fixed_symbol else 0,
                ),
                parent_cids=tuple(
                    cid
                    for cid in (pair.vulnerable_cid, pair.fixed_cid)
                    if cid
                ),
                extra_payload={"symbol_kind": key[1]},
                derive_syntax=False,
            )


class VulnerableFixedProjector:
    """Project validated source rows without inventing missing associations."""

    def __init__(
        self,
        config: ProjectorConfig = ProjectorConfig(),
        registry: LanguageAdapterRegistry = DEFAULT_LANGUAGE_ADAPTERS,
    ) -> None:
        if not isinstance(config, ProjectorConfig):
            raise TypeError("config must be ProjectorConfig")
        if not isinstance(registry, LanguageAdapterRegistry):
            raise TypeError("registry must be LanguageAdapterRegistry")
        self.config = config
        self.registry = registry
        self.config_cid = canonical_config_cid(
            {
                "language_registry": registry.to_dict(),
                "projector": config.to_dict(),
            },
            schema_version=PROJECTOR_CONFIG_SCHEMA_VERSION,
        )

    def project(
        self,
        row: CVEfixesSourceRow,
        *,
        source_cid: str | None = None,
        model_candidates: Sequence[ModelSemanticCandidate] = (),
    ) -> ProjectionResult:
        if not isinstance(row, CVEfixesSourceRow):
            raise TypeError("row must be CVEfixesSourceRow")
        if isinstance(model_candidates, (str, bytes, bytearray)) or not isinstance(
            model_candidates, Sequence
        ):
            raise TypeError("model_candidates must be a sequence")
        if not all(
            isinstance(item, ModelSemanticCandidate) for item in model_candidates
        ):
            raise TypeError(
                "every model_candidates item must be ModelSemanticCandidate"
            )
        source_cid = source_cid or canonical_source_row_cid(row)
        _validate_cid(source_cid, "source_cid")
        language = self.registry.normalize(row.language)
        adapter = self.registry.resolve(row.language)
        builder = _ProjectionBuilder(
            row=row,
            source_cid=source_cid,
            config=self.config,
            config_cid=self.config_cid,
            language=language,
            adapter=adapter,
        )
        if adapter is None:
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.UNSUPPORTED_LANGUAGE,
                    f"no reviewed deterministic adapter for language {language!r}; "
                    "code evidence was retained without syntax claims",
                )
            )

        declared_paths = tuple(dict.fromkeys(row.file_paths))
        if len(declared_paths) == 1:
            file_path = declared_paths[0]
        elif declared_paths:
            file_path = AMBIGUOUS_PATH
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.AMBIGUOUS_PATH,
                    "row-level vulnerable/fixed bodies cannot be assigned across "
                    "multiple declared paths",
                    path=file_path,
                    unit_kind=UnitKind.FILE.value,
                    unit_index=0,
                )
            )
        else:
            file_path = UNKNOWN_PATH
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.UNKNOWN_PATH,
                    "row has no declared path; code evidence retained at unknown path",
                    path=file_path,
                    unit_kind=UnitKind.FILE.value,
                    unit_index=0,
                )
            )

        if row.vulnerable_code or row.fixed_code:
            builder.add_pair(
                unit_kind=UnitKind.FILE,
                path=file_path,
                unit_index=0,
                vulnerable_body=row.vulnerable_code or "",
                fixed_body=row.fixed_code or "",
                parent_cids=(source_cid,),
                extra_payload={"candidate_paths": list(declared_paths)},
            )

        hunks, diff_diagnostics = _parse_diff(
            row.diff_with_context or "",
            declared_paths,
            max_hunks=self.config.max_hunks,
        )
        builder.diagnostics.extend(diff_diagnostics)
        for index, hunk in enumerate(hunks):
            builder.add_pair(
                unit_kind=UnitKind.HUNK,
                path=hunk.path,
                unit_index=index,
                vulnerable_body=hunk.old_body,
                fixed_body=hunk.new_body,
                parent_cids=(source_cid,),
                start_lines=(hunk.old_start, hunk.new_start),
                extra_payload={
                    "candidate_paths": list(declared_paths),
                    "diff_header": hunk.header,
                    "path_ambiguous": hunk.ambiguous,
                },
            )

        if not builder.units:
            # Retain an explicit diagnostic-only result rather than dropping
            # rows whose source bodies are absent.
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.DIFF_UNPARSEABLE,
                    "row contains no projectable vulnerable, fixed, or diff body",
                )
            )

        unit_by_cid = {item.cid: item for item in builder.units}
        for candidate in model_candidates:
            try:
                unit = unit_by_cid[candidate.code_unit_cid]
            except KeyError as exc:
                raise ProjectionError(
                    "model candidate references a code unit outside this projection"
                ) from exc
            expected_polarity = (
                EvidencePolarity.VULNERABLE_POSITIVE
                if unit.polarity == "vulnerable"
                else EvidencePolarity.FIXED_NEGATIVE
            )
            if candidate.evidence_polarity is not expected_polarity:
                raise ProjectionError(
                    "model candidate polarity conflicts with its code unit"
                )
            builder.facts.append(
                SemanticFact(
                    kind=candidate.kind,
                    predicate=builder.bounded_predicate(candidate.predicate),
                    evidence_polarity=candidate.evidence_polarity,
                    extraction_method=ExtractionMethod.MODEL_ASSISTED,
                    code_unit_cid=candidate.code_unit_cid,
                    source_cid=source_cid,
                    config_cid=self.config_cid,
                    confidence=candidate.confidence,
                    model_id=candidate.model_id,
                    model_revision=candidate.model_revision,
                )
            )

        if len(builder.facts) > self.config.max_semantic_facts:
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.LIMIT_EXCEEDED,
                    f"projection has {len(builder.facts)} semantic facts; retained "
                    f"first {self.config.max_semantic_facts}",
                )
            )
            builder.facts = sorted(
                builder.facts,
                key=lambda item: (
                    item.code_unit_cid,
                    item.kind.value,
                    item.predicate,
                    item.extraction_method.value,
                ),
            )[: self.config.max_semantic_facts]
        if adapter is not None and builder.units and not builder.facts:
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.NO_SEMANTIC_FACTS,
                    "supported syntax yielded no grounded semantic observations",
                )
            )

        return ProjectionResult(
            source_cid=source_cid,
            config_cid=self.config_cid,
            language=language,
            code_units=tuple(builder.units),
            pairs=tuple(builder.pairs),
            semantic_facts=tuple(builder.facts),
            diagnostics=tuple(builder.diagnostics),
        )


DEFAULT_PROJECTOR: Final = VulnerableFixedProjector()


def project_cvefixes_row(
    row: CVEfixesSourceRow,
    *,
    source_cid: str | None = None,
    config: ProjectorConfig = ProjectorConfig(),
    registry: LanguageAdapterRegistry = DEFAULT_LANGUAGE_ADAPTERS,
    model_candidates: Sequence[ModelSemanticCandidate] = (),
) -> ProjectionResult:
    """Project one validated row into loss-aware non-authoritative evidence."""

    return VulnerableFixedProjector(config, registry).project(
        row,
        source_cid=source_cid,
        model_candidates=model_candidates,
    )


# Descriptive compatibility spellings for downstream pipeline tasks.
CVEfixesProjector = VulnerableFixedProjector
SemanticProjector = VulnerableFixedProjector
project_row = project_cvefixes_row


__all__ = [
    "AMBIGUOUS_PATH",
    "CVEfixesProjector",
    "DEFAULT_LANGUAGE_ADAPTERS",
    "DEFAULT_PROJECTOR",
    "DiagnosticCode",
    "EvidencePolarity",
    "ExtractionMethod",
    "LanguageAdapter",
    "LanguageAdapterRegistry",
    "LanguageProjection",
    "ModelSemanticCandidate",
    "PROJECTOR_CONFIG_SCHEMA_VERSION",
    "PROJECTOR_SCHEMA_VERSION",
    "ProjectionDiagnostic",
    "ProjectionError",
    "ProjectionResult",
    "ProjectorConfig",
    "PythonLanguageAdapter",
    "SemanticFact",
    "SemanticKind",
    "SemanticProjector",
    "SymbolObservation",
    "SyntaxObservation",
    "UNKNOWN_PATH",
    "UnitKind",
    "VulnerableFixedPair",
    "VulnerableFixedProjector",
    "canonical_source_row_cid",
    "project_cvefixes_row",
    "project_row",
]
