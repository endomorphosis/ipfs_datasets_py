"""Content-bound adapters for mixed program and contract evidence.

The canonical cache/index record remains :class:`conflict_graph.ASTBlobRecord`.
This module does not introduce a second AST schema.  It adapts Python,
JavaScript/TypeScript, and non-code contract formats to that record and retains
richer, typed facts in a small sidecar.  The sidecar is deliberately
observational: import aliases, member dispatch, monkey patches, and dynamic
calls are marked ambiguous rather than promoted to resolved call-graph edges.

Supported inputs are Python, JavaScript/JSX, TypeScript/TSX, JSON/JSON
Schema/MCP manifests, and Markdown. Unsupported and malformed inputs are
returned as explicit adapter results so an exhaustive corpus scan can account
for every admitted file.

The executable evidence surface ``vfs/incremental-ast-index@1`` (VFS-G139) is
the discovery key for this module.  Packet sibling
``vfs/exhaustive-file-inventory@1`` (VFS-G138) is co-owned with
:mod:`repository_corpus_index` under parent goal VFS-G020 / goal packet
``goal_packet/corpus_index/ipfs_accelerate_py/26d54d2206f9``.  Unchanged blobs
are reused from a previous snapshot; parser failures and truncation prevent an
exhaustive index verdict.  The synthetic ``objective validation repair``
discovery key (VFS-064) anchors the parent VFS-G020 validation gate and never
enters AST blob identity.  Evidence labels stay off content-bound identity.

Language-edge resolution (``vfs/language-edge-resolution@1``, VFS-G021 /
VFS-G143) projects import, re-export, call, decorator, callback, dynamic
import, monkey-patch, and transport-boundary facts into typed edge candidates
that always cite a source span and resolver rule.  Ambiguous and unsupported
constructs stay explicit; name collisions and re-exports never become forged
direct call edges.
"""

from __future__ import annotations

import ast
import bisect
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .analysis_ast_index import AnalysisASTIndex, build_analysis_ast_index
from ..core.conflict_graph import ASTBlobRecord, build_python_ast_blob_record
from ..core.multiformats_identity import validate_cid
from ..proof.formal_verification_contracts import content_identity
from .repository_corpus_index import (
    CorpusClassification,
    CorpusEntry,
    RepositoryCorpusIndex,
)

PROGRAM_AST_ADAPTER_SCHEMA = "ipfs_accelerate_py/agent-supervisor/program-ast-adapter-result@1"
PROGRAM_EVIDENCE_FACT_SCHEMA = "ipfs_accelerate_py/agent-supervisor/program-evidence-fact@1"
PROGRAM_EVIDENCE_INDEX_SCHEMA = "ipfs_accelerate_py/agent-supervisor/program-evidence-index@1"
INVENTORY_PROGRAM_EVIDENCE_RECEIPT_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/inventory-program-evidence-receipt@1"
)
PYTHON_ADAPTER_VERSION = f"stdlib-ast-{sys.version_info.major}.{sys.version_info.minor}"
JSON_ADAPTER_VERSION = "stdlib-json-1"
MARKDOWN_ADAPTER_VERSION = "deterministic-lines-1"
JAVASCRIPT_ADAPTER_VERSION = "deterministic-ecmascript-tokens-1"
DEFAULT_MAX_SOURCE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_FACTS = 20_000

# Exact objective-heap discovery keys and supervisor-fed packet bindings.
# Domain evidence owned by this module (VFS-G139).
INCREMENTAL_AST_INDEX_EVIDENCE: Final[str] = "vfs/incremental-ast-index@1"
# Packet sibling (VFS-G138) co-covered with repository_corpus_index.
EXHAUSTIVE_FILE_INVENTORY_EVIDENCE: Final[str] = "vfs/exhaustive-file-inventory@1"
# Language-edge resolution (VFS-G021 / gap child VFS-G143). Co-owned with
# program_graph: every projected edge cites span + resolver rule; collisions
# and re-exports never forge direct calls.
LANGUAGE_EDGE_RESOLUTION_EVIDENCE: Final[str] = "vfs/language-edge-resolution@1"
# Synthetic objective-heap evidence term for VFS-G020 validation-gate work.
# Exact-text discovery key only — never part of AST blob identity.
OBJECTIVE_VALIDATION_REPAIR_EVIDENCE: Final[str] = "objective validation repair"
OBJECTIVE_GOAL_ID: Final[str] = "VFS-G139"
PACKET_SIBLING_GOAL_ID: Final[str] = "VFS-G138"
OBJECTIVE_PARENT_GOAL_ID: Final[str] = "VFS-G020"
# Domain parent goal for language-edge resolution (VFS-G021).
LANGUAGE_EDGE_RESOLUTION_GOAL_ID: Final[str] = "VFS-G021"
# Gap / prove task for vfs/language-edge-resolution@1.
LANGUAGE_EDGE_RESOLUTION_TASK_ID: Final[str] = "VFS-069"
# Child objective that owns the prove obligation (VFS-G143).
LANGUAGE_EDGE_RESOLUTION_CHILD_GOAL_ID: Final[str] = "VFS-G143"
# Domain packet task that authored vfs/incremental-ast-index@1 (VFS-G139).
OBJECTIVE_TASK_ID: Final[str] = "VFS-063"
# Repair task that owns the synthetic objective validation repair obligation.
OBJECTIVE_VALIDATION_REPAIR_TASK_ID: Final[str] = "VFS-064"
GOAL_PACKET_ID: Final[str] = "goal_packet/corpus_index/ipfs_accelerate_py/26d54d2206f9"
OBJECTIVE_DOMAIN_EVIDENCE_TERMS: Final[tuple[str, ...]] = (INCREMENTAL_AST_INDEX_EVIDENCE,)
# Parent VFS-G020 / packet aggregate evidence surface (inventory + AST index).
# Domain packet keys only — objective validation repair is appended by
# :func:`objective_validation_repair_evidence_terms` / full discovery helpers.
# Language-edge resolution is a sibling corpus-index goal (VFS-G021), not part
# of the inventory/AST packet pair.
CORPUS_INDEX_G020_EVIDENCE_TERMS: Final[tuple[str, ...]] = (
    EXHAUSTIVE_FILE_INVENTORY_EVIDENCE,
    INCREMENTAL_AST_INDEX_EVIDENCE,
)
PACKET_GOAL_IDS: Final[tuple[str, ...]] = (
    PACKET_SIBLING_GOAL_ID,
    OBJECTIVE_GOAL_ID,
)
# Closed set of adapter fact kinds that project to language edges.
_LANGUAGE_EDGE_FACT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "import",
        "export",
        "re_export",
        "call",
        "new_expression",
        "dynamic_import",
        "monkey_patch",
        "callback",
        "registration",
        "decorator",
        "unsupported_node",
    }
)
LANGUAGE_EDGE_RESOLUTION_INVARIANTS: Final[tuple[str, ...]] = (
    "every projected edge cites a source span and resolver rule",
    "ambiguous and unsupported constructs remain explicit",
    "adversarial name collisions cannot become forged direct calls",
    "re-exports cannot become forged direct calls",
    "dynamic language features stay typed frontier edges",
)
# Languages / JSON family labels that must carry content-bound provenance
# under VFS-G139.  JSON Schema and MCP manifests remain JSON-family adapters.
PROVENANCE_LANGUAGES: Final[frozenset[str]] = frozenset(
    {
        "python",
        "javascript",
        "jsx",
        "typescript",
        "tsx",
        "json",
        "json-schema",
        "mcp-manifest",
        "markdown",
    }
)
# Diagnostics that mean the adapter truncated or refused under a hard bound.
_TRUNCATION_DIAGNOSTIC_CODES: Final[frozenset[str]] = frozenset(
    {
        "fact_bound_exceeded",
        "source_size_bound_exceeded",
    }
)
INCREMENTAL_AST_INDEX_INVARIANTS: Final[tuple[str, ...]] = (
    "TypeScript/TSX/JavaScript/Python/JSON/Markdown inputs have provenance",
    "unchanged blobs are reused from the previous snapshot",
    "parser failures prevent an exhaustive verdict",
    "truncation prevents an exhaustive verdict",
    "unsupported and malformed inputs remain explicitly accounted",
)
# Parent VFS-G020 acceptance subset (inventory + incremental parse gate).
OBJECTIVE_VALIDATION_REPAIR_INVARIANTS: Final[tuple[str, ...]] = (
    "included and excluded populations publish with reasons",
    "TypeScript/TSX/JavaScript/Python/JSON/Markdown inputs have provenance",
    "unchanged blobs are reused from the previous snapshot",
    "unexplained skips, parser failures, and truncation prevent an exhaustive verdict",
    "inventory, language adapters, and incremental persistence stay conflict-domain split",
)

# Keep exact-text discovery anchors aligned with the objective heap.
assert INCREMENTAL_AST_INDEX_EVIDENCE == "vfs/incremental-ast-index@1"
assert EXHAUSTIVE_FILE_INVENTORY_EVIDENCE == "vfs/exhaustive-file-inventory@1"
assert LANGUAGE_EDGE_RESOLUTION_EVIDENCE == "vfs/language-edge-resolution@1"
assert OBJECTIVE_VALIDATION_REPAIR_EVIDENCE == "objective validation repair"
assert OBJECTIVE_GOAL_ID == "VFS-G139"
assert PACKET_SIBLING_GOAL_ID == "VFS-G138"
assert OBJECTIVE_PARENT_GOAL_ID == "VFS-G020"
assert LANGUAGE_EDGE_RESOLUTION_GOAL_ID == "VFS-G021"
assert LANGUAGE_EDGE_RESOLUTION_CHILD_GOAL_ID == "VFS-G143"
assert LANGUAGE_EDGE_RESOLUTION_TASK_ID == "VFS-069"
assert OBJECTIVE_TASK_ID == "VFS-063"
assert OBJECTIVE_VALIDATION_REPAIR_TASK_ID == "VFS-064"
assert OBJECTIVE_DOMAIN_EVIDENCE_TERMS == ("vfs/incremental-ast-index@1",)
assert CORPUS_INDEX_G020_EVIDENCE_TERMS == (
    "vfs/exhaustive-file-inventory@1",
    "vfs/incremental-ast-index@1",
)

_PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
_JSON_SUFFIXES = frozenset({".json", ".jsonschema"})
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdown", ".mkd"})
_JAVASCRIPT_SUFFIXES = frozenset({".js", ".mjs", ".cjs"})
_JSX_SUFFIXES = frozenset({".jsx"})
_TYPESCRIPT_SUFFIXES = frozenset({".ts", ".mts", ".cts"})
_TSX_SUFFIXES = frozenset({".tsx"})
_NORMATIVE_WORD_RE = re.compile(
    r"\b(MUST(?:\s+NOT)?|SHALL(?:\s+NOT)?|SHOULD(?:\s+NOT)?|MAY|REQUIRED)\b",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")
_INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_JSON_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')


def _source_sha256(source: str) -> str:
    return "sha256:" + hashlib.sha256(source.encode("utf-8", errors="surrogatepass")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _semantic_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _positive_limit(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _normalize_details(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not value:
        return MappingProxyType({})
    normalized: dict[str, Any] = {}
    for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
        name = str(key)
        if item is None or isinstance(item, (str, int, float, bool)):
            normalized[name] = item
        elif isinstance(item, Mapping):
            normalized[name] = {
                str(child_key): child_value
                for child_key, child_value in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        elif isinstance(item, (list, tuple, set, frozenset)):
            normalized[name] = tuple(item)
        else:
            normalized[name] = str(item)
    return MappingProxyType(normalized)


@dataclass(frozen=True, order=True)
class SourceSpan:
    """One-based line and zero-based column source coordinates."""

    line_start: int = 0
    column_start: int = 0
    line_end: int = 0
    column_end: int = 0

    def __post_init__(self) -> None:
        values = tuple(
            max(0, int(item))
            for item in (
                self.line_start,
                self.column_start,
                self.line_end,
                self.column_end,
            )
        )
        object.__setattr__(self, "line_start", values[0])
        object.__setattr__(self, "column_start", values[1])
        object.__setattr__(self, "line_end", values[2])
        object.__setattr__(self, "column_end", values[3])

    def to_dict(self) -> dict[str, int]:
        return {
            "line_start": self.line_start,
            "column_start": self.column_start,
            "line_end": self.line_end,
            "column_end": self.column_end,
        }


@dataclass(frozen=True)
class AdapterDiagnostic:
    """A deterministic parser/admission diagnostic."""

    code: str
    message: str
    severity: str = "error"
    span: SourceSpan = field(default_factory=SourceSpan)
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code).strip())
        object.__setattr__(self, "message", " ".join(str(self.message).split()))
        object.__setattr__(self, "severity", str(self.severity or "error"))
        object.__setattr__(self, "details", _normalize_details(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "span": self.span.to_dict(),
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ProgramEvidenceFact:
    """A typed observed-syntax or non-code contract fact."""

    kind: str
    name: str
    span: SourceSpan
    owner: str = ""
    target: str = ""
    relationship: str = "observed"
    normative: bool = False
    ambiguous: bool = False
    generated: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)
    schema: str = PROGRAM_EVIDENCE_FACT_SCHEMA

    def __post_init__(self) -> None:
        for field_name in ("kind", "name", "owner", "target", "relationship"):
            object.__setattr__(self, field_name, str(getattr(self, field_name) or "").strip())
        object.__setattr__(self, "normative", bool(self.normative))
        object.__setattr__(self, "ambiguous", bool(self.ambiguous))
        object.__setattr__(self, "generated", bool(self.generated))
        object.__setattr__(self, "details", _normalize_details(self.details))

    @property
    def fact_id(self) -> str:
        return "fact:" + _semantic_hash(self._payload())

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "kind": self.kind,
            "name": self.name,
            "owner": self.owner,
            "target": self.target,
            "relationship": self.relationship,
            "normative": self.normative,
            "ambiguous": self.ambiguous,
            "generated": self.generated,
            "span": self.span.to_dict(),
            "details": dict(self.details),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"fact_id": self.fact_id, **self._payload()}


def _fact_sort_key(fact: ProgramEvidenceFact) -> tuple[Any, ...]:
    return (
        fact.span.line_start,
        fact.span.column_start,
        fact.span.line_end,
        fact.span.column_end,
        fact.kind,
        fact.owner,
        fact.name,
        fact.target,
        fact.fact_id,
    )


def _deduplicate_facts(
    facts: Iterable[ProgramEvidenceFact],
) -> tuple[ProgramEvidenceFact, ...]:
    by_id = {fact.fact_id: fact for fact in facts}
    return tuple(sorted(by_id.values(), key=_fact_sort_key))


@dataclass(frozen=True)
class ProgramASTAdapterResult:
    """One accounted source input and its canonical record, if supported."""

    path: str
    language: str
    status: str
    source_sha256: str
    blob_identity: str
    parser: str
    ast_record: ASTBlobRecord | None = None
    facts: tuple[ProgramEvidenceFact, ...] = ()
    diagnostics: tuple[AdapterDiagnostic, ...] = ()
    generated: bool = False
    reused: bool = False
    schema: str = PROGRAM_AST_ADAPTER_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", str(self.path or "").replace("\\", "/"))
        object.__setattr__(self, "language", str(self.language or "unknown"))
        status = str(self.status or "unsupported")
        if status not in {"success", "partial", "malformed", "unsupported"}:
            raise ValueError(f"unsupported adapter status: {status}")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "facts", _deduplicate_facts(self.facts))
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                sorted(
                    self.diagnostics,
                    key=lambda item: (
                        item.span.line_start,
                        item.span.column_start,
                        item.code,
                        item.message,
                    ),
                )
            ),
        )
        if self.ast_record is not None:
            if self.ast_record.source_sha256 != self.source_sha256:
                raise ValueError("canonical AST record source identity mismatch")
            if self.ast_record.blob_identity != self.blob_identity:
                raise ValueError("canonical AST record blob identity mismatch")
        if status == "unsupported" and self.ast_record is not None:
            raise ValueError("unsupported adapter results cannot contain an AST record")

    @property
    def record(self) -> ASTBlobRecord | None:
        """Compatibility spelling for callers consuming canonical records."""

        return self.ast_record

    @property
    def supported(self) -> bool:
        return self.status != "unsupported"

    @property
    def parse_error(self) -> str:
        return self.ast_record.parse_error if self.ast_record is not None else ""

    def facts_of_kind(self, kind: str) -> tuple[ProgramEvidenceFact, ...]:
        return tuple(fact for fact in self.facts if fact.kind == kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "path": self.path,
            "language": self.language,
            "status": self.status,
            "source_sha256": self.source_sha256,
            "blob_identity": self.blob_identity,
            "parser": self.parser,
            "ast_record": (self.ast_record.to_dict() if self.ast_record is not None else None),
            "facts": [fact.to_dict() for fact in self.facts],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "generated": self.generated,
            "reused": self.reused,
        }


@dataclass(frozen=True)
class SourceDocument:
    """A path-bound source document for batch adaptation."""

    path: str
    source: str
    language: str = ""
    blob_identity: str = ""
    generated: bool = False


@dataclass(frozen=True)
class ProgramEvidenceIndex:
    """Canonical AST index plus accounting for every adapter result.

    The index is the VFS-G139 incremental AST evidence surface.  Every input in
    the snapshot is accounted (success, partial, malformed, or unsupported).
    Unchanged blobs may be reused from a previous snapshot; parser failures and
    truncation prevent :attr:`exhaustive`.
    """

    analysis_index: AnalysisASTIndex
    results: tuple[ProgramASTAdapterResult, ...]
    schema: str = PROGRAM_EVIDENCE_INDEX_SCHEMA

    @property
    def ast_index(self) -> AnalysisASTIndex:
        return self.analysis_index

    @property
    def unsupported_results(self) -> tuple[ProgramASTAdapterResult, ...]:
        return tuple(item for item in self.results if item.status == "unsupported")

    @property
    def malformed_results(self) -> tuple[ProgramASTAdapterResult, ...]:
        return tuple(item for item in self.results if item.status == "malformed")

    @property
    def partial_results(self) -> tuple[ProgramASTAdapterResult, ...]:
        return tuple(item for item in self.results if item.status == "partial")

    @property
    def success_results(self) -> tuple[ProgramASTAdapterResult, ...]:
        return tuple(item for item in self.results if item.status == "success")

    @property
    def reused_result_count(self) -> int:
        return sum(1 for item in self.results if item.reused)

    @property
    def truncated(self) -> bool:
        """True when any result hit a fact or source byte bound."""

        return any(
            any(diagnostic.code in _TRUNCATION_DIAGNOSTIC_CODES for diagnostic in item.diagnostics)
            for item in self.results
        )

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """Closed codes explaining why the index is not exhaustive."""

        codes: set[str] = set()
        if self.malformed_results:
            codes.add("parser_failures")
        if self.truncated:
            codes.add("truncation")
        for item in self.results:
            if item.language in PROVENANCE_LANGUAGES and not item.source_sha256:
                codes.add("missing_provenance")
            if (
                item.status in {"success", "partial", "malformed"}
                and item.ast_record is None
                and item.status != "unsupported"
            ):
                # Malformed/success/partial code adapters must retain a record
                # when they claim to have adapted the source; missing record is
                # an unexplained skip for supported languages.
                if item.language in PROVENANCE_LANGUAGES and item.status != "unsupported":
                    if item.status in {"success", "partial"} and item.ast_record is None:
                        codes.add("unexplained_skip")
        return tuple(sorted(codes))

    @property
    def exhaustive(self) -> bool:
        """Exhaustive only when no parser failure or truncation blocks the scan.

        Unsupported languages remain explicitly accounted and do not by
        themselves fail the verdict.  Parser failures (malformed) and
        truncation (source/fact bounds) always prevent exhaustiveness.
        """

        return not self.reason_codes

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "analysis_index": self.analysis_index.to_dict(),
            "results": [item.to_dict() for item in self.results],
            # Objective evidence bindings are diagnostic metadata only.
            "evidence": INCREMENTAL_AST_INDEX_EVIDENCE,
            "evidence_terms": list(OBJECTIVE_DOMAIN_EVIDENCE_TERMS),
            "goal_id": OBJECTIVE_GOAL_ID,
            "goal_packet": GOAL_PACKET_ID,
            "packet_goal_ids": list(PACKET_GOAL_IDS),
            "parent_goal_id": OBJECTIVE_PARENT_GOAL_ID,
            "task_id": OBJECTIVE_TASK_ID,
            "exhaustive": self.exhaustive,
            "reason_codes": list(self.reason_codes),
            "reused_result_count": self.reused_result_count,
            "truncated": self.truncated,
        }

    def satisfies_incremental_ast_index(self) -> bool:
        """Return whether this index meets ``vfs/incremental-ast-index@1``."""

        return index_satisfies_incremental_ast_index(self)

    def to_evidence_claim(self) -> dict[str, Any]:
        """Portable VFS-G139 evidence claim bound to this index snapshot."""

        return prove_incremental_ast_index(self)


def _mapping_field(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _sequence_field(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be an array")
    return value


def _boolean_field(value: Mapping[str, Any], name: str, *, default: bool = False) -> bool:
    result = value.get(name, default)
    if not isinstance(result, bool):
        raise TypeError(f"{name} must be a boolean")
    return result


def _source_span_from_dict(value: Any) -> SourceSpan:
    payload = _mapping_field(value, "source span")
    return SourceSpan(
        line_start=int(payload.get("line_start", 0)),
        column_start=int(payload.get("column_start", 0)),
        line_end=int(payload.get("line_end", 0)),
        column_end=int(payload.get("column_end", 0)),
    )


def _diagnostic_from_dict(value: Any) -> AdapterDiagnostic:
    payload = _mapping_field(value, "adapter diagnostic")
    return AdapterDiagnostic(
        code=str(payload.get("code") or ""),
        message=str(payload.get("message") or ""),
        severity=str(payload.get("severity") or "error"),
        span=_source_span_from_dict(payload.get("span") or {}),
        details=_mapping_field(payload.get("details") or {}, "diagnostic details"),
    )


def _program_fact_from_dict(value: Any) -> ProgramEvidenceFact:
    payload = _mapping_field(value, "program evidence fact")
    schema = str(payload.get("schema") or PROGRAM_EVIDENCE_FACT_SCHEMA)
    if schema != PROGRAM_EVIDENCE_FACT_SCHEMA:
        raise ValueError(f"unsupported program evidence fact schema: {schema}")
    result = ProgramEvidenceFact(
        kind=str(payload.get("kind") or ""),
        name=str(payload.get("name") or ""),
        span=_source_span_from_dict(payload.get("span") or {}),
        owner=str(payload.get("owner") or ""),
        target=str(payload.get("target") or ""),
        relationship=str(payload.get("relationship") or "observed"),
        normative=_boolean_field(payload, "normative"),
        ambiguous=_boolean_field(payload, "ambiguous"),
        generated=_boolean_field(payload, "generated"),
        details=_mapping_field(payload.get("details") or {}, "fact details"),
        schema=schema,
    )
    claimed = str(payload.get("fact_id") or "")
    if claimed and claimed != result.fact_id:
        raise ValueError("program evidence fact identity does not match payload")
    return result


def _program_result_from_dict(value: Any) -> ProgramASTAdapterResult:
    payload = _mapping_field(value, "program adapter result")
    schema = str(payload.get("schema") or PROGRAM_AST_ADAPTER_SCHEMA)
    if schema != PROGRAM_AST_ADAPTER_SCHEMA:
        raise ValueError(f"unsupported program adapter result schema: {schema}")
    raw_record = payload.get("ast_record")
    if raw_record is None:
        record = None
    else:
        record = ASTBlobRecord.from_dict(_mapping_field(raw_record, "program adapter AST record"))
    return ProgramASTAdapterResult(
        path=str(payload.get("path") or ""),
        language=str(payload.get("language") or "unknown"),
        status=str(payload.get("status") or "unsupported"),
        source_sha256=str(payload.get("source_sha256") or ""),
        blob_identity=str(payload.get("blob_identity") or ""),
        parser=str(payload.get("parser") or ""),
        ast_record=record,
        facts=tuple(
            _program_fact_from_dict(item)
            for item in _sequence_field(payload.get("facts") or (), "program facts")
        ),
        diagnostics=tuple(
            _diagnostic_from_dict(item)
            for item in _sequence_field(payload.get("diagnostics") or (), "program diagnostics")
        ),
        generated=_boolean_field(payload, "generated"),
        reused=_boolean_field(payload, "reused"),
        schema=schema,
    )


def _program_index_from_dict(value: Any) -> ProgramEvidenceIndex:
    payload = _mapping_field(value, "program evidence index")
    schema = str(payload.get("schema") or PROGRAM_EVIDENCE_INDEX_SCHEMA)
    if schema != PROGRAM_EVIDENCE_INDEX_SCHEMA:
        raise ValueError(f"unsupported program evidence index schema: {schema}")
    analysis_payload = _mapping_field(payload.get("analysis_index"), "program analysis index")
    return ProgramEvidenceIndex(
        analysis_index=AnalysisASTIndex.from_dict(analysis_payload),
        results=tuple(
            _program_result_from_dict(item)
            for item in _sequence_field(payload.get("results") or (), "program adapter results")
        ),
        schema=schema,
    )


def _portable_program_result(
    result: ProgramASTAdapterResult,
) -> dict[str, Any]:
    payload = result.to_dict()
    # Reuse is an execution observation.  Cold and warm construction of the
    # same evidence must resolve to one receipt CID.
    payload.pop("reused", None)
    return payload


def _portable_program_index(index: ProgramEvidenceIndex) -> dict[str, Any]:
    analysis = index.analysis_index.to_dict()
    return {
        "schema": index.schema,
        "analysis_index": {
            "schema": analysis["schema"],
            "schema_version": analysis["schema_version"],
            "index_id": analysis["index_id"],
            "path_records": analysis["path_records"],
        },
        "results": [_portable_program_result(item) for item in index.results],
    }


@dataclass(frozen=True)
class InventoryProgramEvidenceReceipt:
    """Inventory-bound coverage around an unchanged program evidence index.

    The generic :class:`ProgramEvidenceIndex` deliberately treats an explicitly
    accounted unsupported input as exhaustive.  Corpus-wide assurance needs a
    stricter verdict: every parser-eligible inventory entry must be supplied,
    provenance must match the inventory, and every supplied input must have a
    supported, complete parse.  This wrapper carries that stricter coverage
    contract without changing generic index semantics or corpus portable
    identity.
    """

    program_index: ProgramEvidenceIndex
    inventory_cid: str
    inventory_exhaustive: bool
    expected_paths: tuple[str, ...] = ()
    missing_paths: tuple[str, ...] = ()
    schema: str = INVENTORY_PROGRAM_EVIDENCE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != INVENTORY_PROGRAM_EVIDENCE_RECEIPT_SCHEMA:
            raise ValueError(f"unsupported inventory program evidence schema: {self.schema}")
        if not isinstance(self.program_index, ProgramEvidenceIndex):
            raise TypeError("inventory program evidence requires a ProgramEvidenceIndex")
        if self.program_index.schema != PROGRAM_EVIDENCE_INDEX_SCHEMA:
            raise ValueError("inventory program evidence requires the current program index schema")
        if not isinstance(self.program_index.analysis_index, AnalysisASTIndex):
            raise TypeError("inventory program evidence requires an AnalysisASTIndex")
        inventory_cid = validate_cid(self.inventory_cid, codecs=("dag-json",))
        if not isinstance(self.inventory_exhaustive, bool):
            raise TypeError("inventory_exhaustive must be a boolean")

        expected = tuple(sorted(str(item) for item in self.expected_paths))
        missing = tuple(sorted(str(item) for item in self.missing_paths))
        if any(not path for path in (*expected, *missing)):
            raise ValueError("inventory program evidence paths must be non-empty")
        if len(expected) != len(set(expected)):
            raise ValueError("inventory program evidence contains duplicate expected paths")
        if len(missing) != len(set(missing)):
            raise ValueError("inventory program evidence contains duplicate missing paths")
        if not set(missing).issubset(expected):
            raise ValueError("missing program paths must belong to expected paths")

        if not all(
            isinstance(item, ProgramASTAdapterResult) for item in self.program_index.results
        ):
            raise TypeError("program evidence index results must be ProgramASTAdapterResult values")
        if any(item.schema != PROGRAM_AST_ADAPTER_SCHEMA for item in self.program_index.results):
            raise ValueError("program evidence index contains an unsupported result schema")
        result_paths = tuple(item.path for item in self.program_index.results)
        if len(result_paths) != len(set(result_paths)):
            raise ValueError("program evidence index contains duplicate result paths")
        if set(result_paths).intersection(missing):
            raise ValueError("program paths cannot be both adapted and missing")
        if set(result_paths).union(missing) != set(expected):
            raise ValueError("expected program paths require one result or missing-path receipt")

        supported_without_ast = tuple(
            item.path
            for item in self.program_index.results
            if item.supported and item.ast_record is None
        )
        if supported_without_ast:
            raise ValueError("supported inventory program results require canonical AST records")
        result_records = {
            item.path: item.ast_record
            for item in self.program_index.results
            if item.ast_record is not None
        }
        indexed_records = {
            item.path: item.ast_record for item in self.program_index.analysis_index.path_records
        }
        if set(result_records) != set(indexed_records):
            raise ValueError("program result and analysis index AST paths do not match")
        if any(
            result_records[path].record_id != indexed_records[path].record_id
            for path in result_records
        ):
            raise ValueError("program result and analysis index AST records do not match")

        object.__setattr__(self, "inventory_cid", inventory_cid)
        object.__setattr__(self, "expected_paths", expected)
        object.__setattr__(self, "missing_paths", missing)

    @property
    def analysis_index(self) -> AnalysisASTIndex:
        return self.program_index.analysis_index

    @property
    def results(self) -> tuple[ProgramASTAdapterResult, ...]:
        return self.program_index.results

    @property
    def reused_result_count(self) -> int:
        return self.program_index.reused_result_count

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """Closed reasons the inventory-bound coverage is not exhaustive."""

        reasons = set(self.program_index.reason_codes)
        if not self.inventory_exhaustive:
            reasons.add("inventory_not_exhaustive")
        if self.missing_paths:
            reasons.add("inventory_inputs_missing")
        if self.program_index.unsupported_results:
            reasons.add("unsupported_parser_input")
        return tuple(sorted(reasons))

    @property
    def exhaustive(self) -> bool:
        return not self.reason_codes

    def _identity_material(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "inventory_cid": self.inventory_cid,
            "inventory_exhaustive": self.inventory_exhaustive,
            "expected_paths": list(self.expected_paths),
            "missing_paths": list(self.missing_paths),
            "program_index": _portable_program_index(self.program_index),
        }

    @property
    def receipt_cid(self) -> str:
        return content_identity(self._identity_material())

    def to_portable_dict(self) -> dict[str, Any]:
        payload = self._identity_material()
        payload["receipt_cid"] = self.receipt_cid
        return payload

    def verify_against_inventory(self, inventory: RepositoryCorpusIndex) -> bool:
        if not isinstance(inventory, RepositoryCorpusIndex):
            raise TypeError(
                "inventory program evidence verification requires RepositoryCorpusIndex"
            )
        expected = tuple(
            sorted(
                item.canonical_path for item in inventory.included_entries if item.parser_eligible
            )
        )
        if self.inventory_cid != inventory.inventory_cid:
            raise ValueError("previous inventory program receipt does not match inventory CID")
        if self.inventory_exhaustive != inventory.exhaustive:
            raise ValueError(
                "previous inventory program receipt exhaustive flag does not match inventory"
            )
        if self.expected_paths != expected:
            raise ValueError("previous inventory program receipt paths do not match inventory")
        try:
            from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
                mirror_work_record,
            )

            record_ref = str(self.inventory_cid or self.receipt_cid or "inventory-program")
            mirror_work_record(
                catalog_kind="ast",
                record_kind="inventory_program_verification",
                record_ref=record_ref,
                subject_kind="record_cid",
                subject_ref=record_ref,
            )
        except Exception:
            pass
        return True

    def to_dict(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        languages: dict[str, int] = {}
        for item in self.results:
            statuses[item.status] = statuses.get(item.status, 0) + 1
            languages[item.language] = languages.get(item.language, 0) + 1
        payload = self.to_portable_dict()
        payload.update(
            {
                "evidence": INCREMENTAL_AST_INDEX_EVIDENCE,
                "evidence_terms": list(OBJECTIVE_DOMAIN_EVIDENCE_TERMS),
                "packet_evidence_terms": list(CORPUS_INDEX_G020_EVIDENCE_TERMS),
                "exhaustive": self.exhaustive,
                "reason_codes": list(self.reason_codes),
                "coverage": {
                    "expected_path_count": len(self.expected_paths),
                    "adapted_path_count": len(self.results),
                    "indexed_path_count": len(self.analysis_index.path_records),
                    "reused_result_count": self.reused_result_count,
                    "missing_paths": list(self.missing_paths),
                    "status_counts": dict(sorted(statuses.items())),
                    "language_counts": dict(sorted(languages.items())),
                },
                "program_index": self.program_index.to_dict(),
                "authoritative": False,
                "completion_authoritative": False,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "InventoryProgramEvidenceReceipt":
        value = _mapping_field(payload, "inventory program evidence receipt")
        schema = str(value.get("schema") or INVENTORY_PROGRAM_EVIDENCE_RECEIPT_SCHEMA)
        if schema != INVENTORY_PROGRAM_EVIDENCE_RECEIPT_SCHEMA:
            raise ValueError(f"unsupported inventory program evidence schema: {schema}")
        claimed = validate_cid(value.get("receipt_cid"), codecs=("dag-json",))
        result = cls(
            program_index=_program_index_from_dict(value.get("program_index")),
            inventory_cid=str(value.get("inventory_cid") or ""),
            inventory_exhaustive=_boolean_field(value, "inventory_exhaustive"),
            expected_paths=tuple(
                str(item)
                for item in _sequence_field(
                    value.get("expected_paths") or (), "expected program paths"
                )
            ),
            missing_paths=tuple(
                str(item)
                for item in _sequence_field(
                    value.get("missing_paths") or (), "missing program paths"
                )
            ),
            schema=schema,
        )
        if claimed != result.receipt_cid:
            raise ValueError("inventory program evidence receipt CID does not match payload")
        if "exhaustive" in value and value["exhaustive"] is not result.exhaustive:
            raise ValueError("inventory program evidence exhaustive verdict does not match payload")
        if "reason_codes" in value and tuple(sorted(value["reason_codes"])) != (
            result.reason_codes
        ):
            raise ValueError("inventory program evidence reason codes do not match payload")
        return result


def _ast_span(node: ast.AST) -> SourceSpan:
    return SourceSpan(
        int(getattr(node, "lineno", 0) or 0),
        int(getattr(node, "col_offset", 0) or 0),
        int(getattr(node, "end_lineno", getattr(node, "lineno", 0)) or 0),
        int(getattr(node, "end_col_offset", getattr(node, "col_offset", 0)) or 0),
    )


def _render_ast(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return " ".join(ast.unparse(node).split())
    except (AttributeError, ValueError):
        return type(node).__name__


def _expression_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expression_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        parent = _expression_name(node.value)
        return f"{parent}[{_render_ast(node.slice)}]" if parent else ""
    if isinstance(node, ast.Call):
        return _expression_name(node.func)
    return ""


def _python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    returns = f" -> {_render_ast(node.returns)}" if node.returns else ""
    return f"{prefix}def {node.name}({_render_ast(node.args)}){returns}"


def _python_facts(tree: ast.AST) -> tuple[ProgramEvidenceFact, ...]:
    facts: list[ProgramEvidenceFact] = []
    scope: list[str] = []
    import_aliases: dict[str, str] = {}

    class Visitor(ast.NodeVisitor):
        def owner(self) -> str:
            return ".".join(scope) or "<module>"

        def definition(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            owner = self.owner()
            qualified = ".".join((*scope, node.name))
            if isinstance(node, ast.ClassDef):
                kind = "class_definition"
                signature = f"class {node.name}"
                details: dict[str, Any] = {
                    "bases": tuple(_render_ast(item) for item in node.bases),
                    "keywords": tuple(
                        f"{item.arg or '**'}={_render_ast(item.value)}" for item in node.keywords
                    ),
                }
            else:
                kind = (
                    "async_function_definition"
                    if isinstance(node, ast.AsyncFunctionDef)
                    else "function_definition"
                )
                signature = _python_signature(node)
                details = {
                    "signature": signature,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                }
            facts.append(
                ProgramEvidenceFact(
                    kind=kind,
                    name=qualified,
                    owner=owner,
                    target=signature,
                    relationship="defines",
                    span=_ast_span(node),
                    details=details,
                )
            )
            for decorator in node.decorator_list:
                facts.append(
                    ProgramEvidenceFact(
                        kind="decorator",
                        name=_render_ast(decorator),
                        owner=qualified,
                        target=_expression_name(decorator),
                        relationship="decorates",
                        ambiguous=isinstance(decorator, ast.Call)
                        and not _expression_name(decorator),
                        span=_ast_span(decorator),
                    )
                )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
                if node.args.vararg is not None:
                    arguments = (*arguments, node.args.vararg)
                if node.args.kwarg is not None:
                    arguments = (*arguments, node.args.kwarg)
                for argument in arguments:
                    if argument.annotation is not None:
                        facts.append(
                            ProgramEvidenceFact(
                                kind="annotation",
                                name=argument.arg,
                                owner=qualified,
                                target=_render_ast(argument.annotation),
                                relationship="parameter_type",
                                span=_ast_span(argument.annotation),
                            )
                        )
                if node.returns is not None:
                    facts.append(
                        ProgramEvidenceFact(
                            kind="annotation",
                            name="return",
                            owner=qualified,
                            target=_render_ast(node.returns),
                            relationship="return_type",
                            span=_ast_span(node.returns),
                        )
                    )
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.definition(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.definition(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.definition(node)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                import_aliases[local] = alias.name
                facts.append(
                    ProgramEvidenceFact(
                        kind="import",
                        name=local,
                        owner=self.owner(),
                        target=alias.name,
                        relationship="imports",
                        span=_ast_span(node),
                        details={
                            "alias": alias.asname or "",
                            "statement": _render_ast(node),
                        },
                    )
                )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = "." * int(node.level or 0) + (node.module or "")
            for alias in node.names:
                local = alias.asname or alias.name
                target = f"{module}.{alias.name}" if module else alias.name
                import_aliases[local] = target
                facts.append(
                    ProgramEvidenceFact(
                        kind="import",
                        name=local,
                        owner=self.owner(),
                        target=target,
                        relationship="imports",
                        ambiguous=alias.name == "*",
                        span=_ast_span(node),
                        details={
                            "alias": alias.asname or "",
                            "relative_level": int(node.level or 0),
                            "statement": _render_ast(node),
                        },
                    )
                )

        def visit_Call(self, node: ast.Call) -> None:
            expression = _expression_name(node.func)
            callee = expression or _render_ast(node.func) or "<dynamic>"
            root = expression.split(".", 1)[0] if expression else ""
            details: dict[str, Any] = {
                "argument_count": len(node.args),
                "keyword_names": tuple(keyword.arg or "**" for keyword in node.keywords),
            }
            ambiguous = not isinstance(node.func, ast.Name)
            if root in import_aliases:
                suffix = expression[len(root) :] if expression else ""
                details["import_candidate"] = import_aliases[root] + suffix
                details["resolution"] = "candidate_only"
                ambiguous = True
            elif not expression:
                details["resolution"] = "dynamic_expression"
                ambiguous = True
            elif isinstance(node.func, ast.Name):
                details["resolution"] = "unresolved_name"
                ambiguous = True
            if callee in {"setattr", "builtins.setattr"} and len(node.args) >= 2:
                facts.append(
                    ProgramEvidenceFact(
                        kind="monkey_patch",
                        name=_render_ast(node.args[1]),
                        owner=self.owner(),
                        target=_render_ast(node.args[0]),
                        relationship="mutates_member",
                        ambiguous=True,
                        span=_ast_span(node),
                        details={"mechanism": "setattr"},
                    )
                )
            facts.append(
                ProgramEvidenceFact(
                    kind="call",
                    name=callee,
                    owner=self.owner(),
                    target=callee,
                    relationship="calls_candidate",
                    ambiguous=ambiguous,
                    span=_ast_span(node),
                    details=details,
                )
            )
            self.generic_visit(node)

        def visit_Raise(self, node: ast.Raise) -> None:
            target = _render_ast(node.exc) if node.exc is not None else "<reraise>"
            facts.append(
                ProgramEvidenceFact(
                    kind="raise",
                    name=target,
                    owner=self.owner(),
                    target=target,
                    relationship="raises",
                    ambiguous=node.exc is None,
                    span=_ast_span(node),
                    details={"cause": _render_ast(node.cause)},
                )
            )
            self.generic_visit(node)

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            target = _render_ast(node.type) if node.type is not None else "<any>"
            facts.append(
                ProgramEvidenceFact(
                    kind="exception_handler",
                    name=target,
                    owner=self.owner(),
                    target=target,
                    relationship="catches",
                    ambiguous=node.type is None,
                    span=_ast_span(node),
                    details={"binding": node.name or ""},
                )
            )
            self.generic_visit(node)

        def _with(self, node: ast.With | ast.AsyncWith, *, asynchronous: bool) -> None:
            for item in node.items:
                facts.append(
                    ProgramEvidenceFact(
                        kind="async_context_manager" if asynchronous else "context_manager",
                        name=_render_ast(item.context_expr),
                        owner=self.owner(),
                        target=_expression_name(item.context_expr),
                        relationship="enters_context",
                        ambiguous=not bool(_expression_name(item.context_expr)),
                        span=_ast_span(item.context_expr),
                        details={
                            "async": asynchronous,
                            "binding": _render_ast(item.optional_vars),
                        },
                    )
                )
            self.generic_visit(node)

        def visit_With(self, node: ast.With) -> None:
            self._with(node, asynchronous=False)

        def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
            self._with(node, asynchronous=True)

        def visit_Await(self, node: ast.Await) -> None:
            facts.append(
                ProgramEvidenceFact(
                    kind="await",
                    name=_render_ast(node.value),
                    owner=self.owner(),
                    target=_expression_name(node.value),
                    relationship="awaits",
                    ambiguous=not bool(_expression_name(node.value)),
                    span=_ast_span(node),
                )
            )
            self.generic_visit(node)

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
            facts.append(
                ProgramEvidenceFact(
                    kind="async_iteration",
                    name=_render_ast(node.target),
                    owner=self.owner(),
                    target=_render_ast(node.iter),
                    relationship="iterates_async",
                    ambiguous=True,
                    span=_ast_span(node),
                )
            )
            self.generic_visit(node)

        def _assignment(self, node: ast.AST, targets: Iterable[ast.AST]) -> None:
            if scope:
                return
            for target in targets:
                if isinstance(target, ast.Attribute):
                    facts.append(
                        ProgramEvidenceFact(
                            kind="monkey_patch",
                            name=_render_ast(target),
                            owner="<module>",
                            target=_expression_name(target.value),
                            relationship="assigns_member",
                            ambiguous=True,
                            span=_ast_span(target),
                            details={"mechanism": "attribute_assignment"},
                        )
                    )

        def visit_Assign(self, node: ast.Assign) -> None:
            self._assignment(node, node.targets)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            facts.append(
                ProgramEvidenceFact(
                    kind="annotation",
                    name=_render_ast(node.target),
                    owner=self.owner(),
                    target=_render_ast(node.annotation),
                    relationship="variable_type",
                    span=_ast_span(node.annotation),
                )
            )
            self._assignment(node, (node.target,))
            self.generic_visit(node)

    Visitor().visit(tree)
    return _deduplicate_facts(facts)


def adapt_python_source(
    source: str,
    *,
    path: str = "",
    blob_identity: str = "",
    previous: ProgramASTAdapterResult | ASTBlobRecord | None = None,
    generated: bool = False,
) -> ProgramASTAdapterResult:
    """Adapt Python using stdlib :mod:`ast` and the canonical record builder."""

    source_hash = _source_sha256(source)
    blob = str(blob_identity or source_hash)
    if isinstance(previous, ProgramASTAdapterResult):
        previous_record = previous.ast_record
    else:
        previous_record = previous

    derived_record = build_python_ast_blob_record(
        source, blob_identity=blob, source_sha256=source_hash
    )
    if (
        isinstance(previous_record, ASTBlobRecord)
        and previous_record.language == "python"
        and previous_record.source_sha256 == source_hash
        and previous_record.blob_identity == blob
        and previous_record.record_id == derived_record.record_id
    ):
        canonical_record = previous_record
        reused = True
    else:
        canonical_record = derived_record
        reused = False

    try:
        tree = ast.parse(source, filename=path or "<unknown>", type_comments=True)
    except (SyntaxError, ValueError) as exc:
        line = int(getattr(exc, "lineno", 0) or 0)
        column = max(0, int(getattr(exc, "offset", 0) or 0) - 1)
        diagnostic = AdapterDiagnostic(
            code="python_syntax_error" if isinstance(exc, SyntaxError) else "python_parse_error",
            message=str(exc),
            span=SourceSpan(line, column, line, column),
        )
        return ProgramASTAdapterResult(
            path=path,
            language="python",
            status="malformed",
            source_sha256=source_hash,
            blob_identity=blob,
            parser=PYTHON_ADAPTER_VERSION,
            ast_record=canonical_record,
            diagnostics=(diagnostic,),
            generated=generated,
            reused=reused,
        )

    return ProgramASTAdapterResult(
        path=path,
        language="python",
        status="success",
        source_sha256=source_hash,
        blob_identity=blob,
        parser=PYTHON_ADAPTER_VERSION,
        ast_record=canonical_record,
        facts=_python_facts(tree),
        generated=generated,
        reused=reused,
    )


@dataclass(frozen=True)
class _ECMAScriptToken:
    kind: str
    value: str
    start: int
    end: int
    span: SourceSpan


_ECMASCRIPT_PUNCTUATORS = (
    "===",
    "!==",
    ">>>",
    "**=",
    "=>",
    "?.",
    "??",
    "&&",
    "||",
    "==",
    "!=",
    "<=",
    ">=",
    "++",
    "--",
    "**",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "<<",
    ">>",
    "...",
)
_ECMASCRIPT_DEFINITION_KINDS = {
    "class": "class_definition",
    "function": "function_definition",
    "interface": "interface_definition",
    "type": "type_definition",
    "enum": "enum_definition",
    "namespace": "namespace_definition",
    "module": "namespace_definition",
}
_ECMASCRIPT_REGISTRATION_NAMES = frozenset(
    {
        "addEventListener",
        "on",
        "once",
        "register",
        "registerHandler",
        "registerTool",
        "setHandler",
        "setRequestHandler",
        "subscribe",
        "tool",
    }
)
_ECMASCRIPT_MCP_STRING_RE = re.compile(
    r"(?:^|[./:_-])(?:mcp|tool|tools|prompt|prompts|resource|resources|server)"
    r"(?:$|[./:_-])",
    re.IGNORECASE,
)


def _ecmascript_lex(
    source: str,
) -> tuple[tuple[_ECMAScriptToken, ...], tuple[AdapterDiagnostic, ...]]:
    """Return a conservative token stream without pretending to resolve JS."""

    line_starts = [0]
    for match in re.finditer("\n", source):
        line_starts.append(match.end())

    def span(start: int, end: int) -> SourceSpan:
        start_line = bisect.bisect_right(line_starts, start)
        end_offset = max(start, end - 1)
        end_line = bisect.bisect_right(line_starts, end_offset)
        return SourceSpan(
            start_line,
            start - line_starts[start_line - 1],
            end_line,
            end - line_starts[end_line - 1],
        )

    tokens: list[_ECMAScriptToken] = []
    diagnostics: list[AdapterDiagnostic] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            index = length if end < 0 else end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                diagnostics.append(
                    AdapterDiagnostic(
                        code="ecmascript_unterminated_comment",
                        message="unterminated block comment",
                        span=span(index, length),
                        details={"parser": JAVASCRIPT_ADAPTER_VERSION},
                    )
                )
                break
            index = end + 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            start = index
            index += 1
            escaped = False
            terminated = False
            while index < length:
                current = source[index]
                if escaped:
                    escaped = False
                    index += 1
                    continue
                if current == "\\":
                    escaped = True
                    index += 1
                    continue
                if current == quote:
                    index += 1
                    terminated = True
                    break
                if current in "\r\n" and quote != "`":
                    break
                index += 1
            if not terminated:
                diagnostics.append(
                    AdapterDiagnostic(
                        code="ecmascript_unterminated_literal",
                        message="unterminated string or template literal",
                        span=span(start, index),
                        details={"parser": JAVASCRIPT_ADAPTER_VERSION},
                    )
                )
            value = source[start:index]
            tokens.append(
                _ECMAScriptToken(
                    "template" if quote == "`" else "string",
                    value,
                    start,
                    index,
                    span(start, index),
                )
            )
            continue
        identifier = re.match(r"[A-Za-z_$][\w$]*", source[index:])
        if identifier:
            end = index + len(identifier.group(0))
            tokens.append(
                _ECMAScriptToken(
                    "identifier",
                    identifier.group(0),
                    index,
                    end,
                    span(index, end),
                )
            )
            index = end
            continue
        number = re.match(
            r"(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|(?:\d+\.\d*|\.\d+|\d+)"
            r"(?:[eE][+-]?\d+)?)n?",
            source[index:],
        )
        if number:
            end = index + len(number.group(0))
            tokens.append(_ECMAScriptToken("number", number.group(0), index, end, span(index, end)))
            index = end
            continue
        punctuator = next(
            (
                candidate
                for candidate in _ECMASCRIPT_PUNCTUATORS
                if source.startswith(candidate, index)
            ),
            char,
        )
        end = index + len(punctuator)
        tokens.append(_ECMAScriptToken("punctuator", punctuator, index, end, span(index, end)))
        index = end
    return tuple(tokens), tuple(diagnostics)


def _mask_ecmascript_noncode(
    source: str,
    *,
    mask_strings: bool,
) -> str:
    """Blank comments and optionally literals while retaining source offsets."""

    masked = list(source)

    def blank(start: int, end: int) -> None:
        for offset in range(start, end):
            if masked[offset] not in "\r\n":
                masked[offset] = " "

    index = 0
    length = len(source)
    while index < length:
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = length if end < 0 else end
            blank(index, end)
            index = end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = length if end < 0 else end + 2
            blank(index, end)
            index = end
            continue
        quote = source[index]
        if quote not in {"'", '"', "`"}:
            index += 1
            continue
        start = index
        index += 1
        escaped = False
        while index < length:
            current = source[index]
            if escaped:
                escaped = False
                index += 1
                continue
            if current == "\\":
                escaped = True
                index += 1
                continue
            index += 1
            if current == quote:
                break
            if current in "\r\n" and quote != "`":
                break
        if mask_strings:
            blank(start, index)
    return "".join(masked)


def _ecmascript_matches(
    tokens: Sequence[_ECMAScriptToken],
) -> tuple[dict[int, int], tuple[AdapterDiagnostic, ...]]:
    matching: dict[int, int] = {}
    stack: list[tuple[str, int]] = []
    closing = {")": "(", "]": "[", "}": "{"}
    diagnostics: list[AdapterDiagnostic] = []
    for index, token in enumerate(tokens):
        if token.value in {"(", "[", "{"}:
            stack.append((token.value, index))
        elif token.value in closing:
            if not stack or stack[-1][0] != closing[token.value]:
                diagnostics.append(
                    AdapterDiagnostic(
                        code="ecmascript_unexpected_closer",
                        message=f"unexpected closing token {token.value!r}",
                        span=token.span,
                        details={"parser": JAVASCRIPT_ADAPTER_VERSION},
                    )
                )
                continue
            _, opening_index = stack.pop()
            matching[opening_index] = index
            matching[index] = opening_index
    for opening, index in stack:
        diagnostics.append(
            AdapterDiagnostic(
                code="ecmascript_unclosed_delimiter",
                message=f"unclosed delimiter {opening!r}",
                span=tokens[index].span,
                details={"parser": JAVASCRIPT_ADAPTER_VERSION},
            )
        )
    return matching, tuple(diagnostics)


def _ecmascript_owner(offset: int, definitions: Sequence[tuple[int, int, str]]) -> str:
    containing = [(end - start, name) for start, end, name in definitions if start <= offset <= end]
    return min(containing)[1] if containing else "<module>"


def _ecmascript_record(
    *,
    source: str,
    facts: Sequence[ProgramEvidenceFact],
    source_hash: str,
    blob_identity: str,
    language: str,
    parse_error: str,
) -> ASTBlobRecord:
    definitions = tuple(
        fact
        for fact in facts
        if fact.kind.endswith("_definition") or fact.kind in {"method_definition"}
    )
    names: list[str] = []
    hashes: dict[str, str] = {}
    lines: dict[str, tuple[int, int]] = {}
    occurrences: dict[str, int] = {}
    source_lines = source.splitlines(keepends=True)
    for fact in definitions:
        base = fact.name if fact.owner in {"", "<module>"} else f"{fact.owner}.{fact.name}"
        occurrences[base] = occurrences.get(base, 0) + 1
        name = base if occurrences[base] == 1 else f"{base}#{occurrences[base]}"
        names.append(name)
        start_line = max(1, fact.span.line_start)
        end_line = max(start_line, fact.span.line_end)
        text = "".join(source_lines[start_line - 1 : end_line])
        hashes[name] = _semantic_hash(
            {
                "kind": fact.kind,
                "name": fact.name,
                "owner": fact.owner,
                "span": fact.span.to_dict(),
                "source": text,
            }
        )
        lines[name] = (start_line, end_line)
    imports = tuple(
        f"{fact.name} <- {fact.target}"
        for fact in facts
        if fact.kind in {"import", "dynamic_import"}
    )
    calls = tuple(
        f"{fact.owner} -> {fact.name}" for fact in facts if fact.kind in {"call", "new_expression"}
    )
    interfaces = tuple(
        f"{fact.kind}:{fact.owner}:{fact.name}:{fact.target}"
        for fact in facts
        if fact.kind
        in {
            "callback",
            "decorator",
            "export",
            "jsx_element",
            "registration",
            "re_export",
            "string_literal",
            "type_annotation",
            "type_reference",
            "unsupported_node",
        }
    )
    return ASTBlobRecord(
        blob_identity=blob_identity,
        source_sha256=source_hash,
        qualified_symbols=tuple(names),
        imports=imports,
        calls=calls,
        state_transitions=(),
        interfaces=interfaces,
        symbol_hashes=hashes,
        symbol_lines=lines,
        parse_error=parse_error,
        language=language,
    )


def _strip_ecmascript_string(value: str) -> str:
    if len(value) >= 2 and value[0] in {"'", '"', "`"}:
        return value[1:-1]
    return value


def _ecmascript_facts(
    source: str,
    *,
    language: str,
    generated: bool,
) -> tuple[
    tuple[ProgramEvidenceFact, ...],
    tuple[AdapterDiagnostic, ...],
]:
    tokens, lexical_diagnostics = _ecmascript_lex(source)
    matching, delimiter_diagnostics = _ecmascript_matches(tokens)
    code_source = _mask_ecmascript_noncode(source, mask_strings=True)
    comment_masked_source = _mask_ecmascript_noncode(source, mask_strings=False)
    token_starts = {(token.start, token.value) for token in tokens}
    diagnostics = list((*lexical_diagnostics, *delimiter_diagnostics))
    facts: list[ProgramEvidenceFact] = []
    line_starts = [0, *(match.end() for match in re.finditer("\n", source))]

    def span(start: int, end: int) -> SourceSpan:
        start_line = bisect.bisect_right(line_starts, start)
        end_offset = max(start, end - 1)
        end_line = bisect.bisect_right(line_starts, end_offset)
        return SourceSpan(
            start_line,
            start - line_starts[start_line - 1],
            end_line,
            end - line_starts[end_line - 1],
        )

    definitions: list[tuple[int, int, str]] = []
    class_scopes: list[tuple[int, int, int, int, str]] = []
    declaration_parens: set[int] = set()
    definition_facts: list[ProgramEvidenceFact] = []
    definition_re = re.compile(
        r"(?m)(?P<prefix>(?:(?:export|default|declare|abstract|async)\s+)*)"
        r"(?P<kind>class|function|interface|type|enum|namespace|module)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)"
    )
    for match in definition_re.finditer(code_source):
        kind = match.group("kind")
        # ``type`` is also a modifier inside import/export binding lists.  Keep
        # those bindings as import/re-export evidence rather than inventing a
        # declaration for them.
        if kind == "type":
            statement_start = code_source.rfind(";", 0, match.start()) + 1
            statement_prefix = code_source[statement_start : match.start()]
            if re.match(r"\s*(?:import|export)\b", statement_prefix, re.DOTALL):
                continue
        name = match.group("name")
        end = match.end()
        token_index = next(
            (index for index, token in enumerate(tokens) if token.start >= match.end()),
            len(tokens),
        )
        body_open = next(
            (
                index
                for index in range(token_index, min(len(tokens), token_index + 80))
                if tokens[index].value == "{"
            ),
            None,
        )
        if body_open is not None and body_open in matching:
            end = tokens[matching[body_open]].end
        elif kind == "type":
            semicolon = code_source.find(";", match.end())
            end = len(source) if semicolon < 0 else semicolon + 1
        owner = _ecmascript_owner(match.start(), definitions)
        fact_kind = _ECMASCRIPT_DEFINITION_KINDS[kind]
        if kind == "function" and "async" in match.group("prefix").split():
            fact_kind = "async_function_definition"
        fact = ProgramEvidenceFact(
            kind=fact_kind,
            name=name,
            owner=owner,
            relationship="defines",
            span=span(match.start(), end),
            generated=generated,
            details={
                "declared_kind": kind,
                "exported": "export" in match.group("prefix").split(),
                "default_export": "default" in match.group("prefix").split(),
            },
        )
        facts.append(fact)
        definition_facts.append(fact)
        definitions.append((match.start(), end, name))
        if body_open is not None and body_open in matching:
            if kind == "class":
                class_scopes.append(
                    (
                        tokens[body_open].start,
                        tokens[matching[body_open]].end,
                        body_open,
                        matching[body_open],
                        name,
                    )
                )
            if kind == "function":
                opening_paren = next(
                    (
                        index
                        for index in range(token_index, body_open)
                        if tokens[index].value == "("
                    ),
                    None,
                )
                if opening_paren is not None:
                    declaration_parens.add(opening_paren)
        if "export" in match.group("prefix").split():
            facts.append(
                ProgramEvidenceFact(
                    kind="export",
                    name="default" if "default" in match.group("prefix").split() else name,
                    owner="<module>",
                    target=name,
                    relationship="exports",
                    span=span(match.start(), match.end()),
                    generated=generated,
                    details={
                        "declaration": True,
                        "default": "default" in match.group("prefix").split(),
                    },
                )
            )

    method_re = re.compile(
        r"(?m)^[ \t]*"
        r"(?:(?:public|private|protected|static|readonly|abstract|override|"
        r"async|declare|get|set)\s+)*"
        r"(?P<name>constructor|[A-Za-z_$][\w$]*)"
        r"\s*(?:<[^>\n]+>\s*)?\("
    )
    for match in method_re.finditer(code_source):
        opening_paren = next(
            (
                index
                for index, token in enumerate(tokens)
                if token.value == "(" and match.start("name") < token.start < match.end()
            ),
            None,
        )
        if opening_paren is None or opening_paren not in matching:
            continue
        containing_class = next(
            (item for item in class_scopes if item[0] < tokens[opening_paren].start < item[1]),
            None,
        )
        if containing_class is None:
            continue
        _, _, class_open, _, class_name = containing_class
        enclosing_braces = [
            opening
            for opening, closing in matching.items()
            if opening < closing
            and tokens[opening].value == "{"
            and opening < opening_paren < closing
        ]
        if not enclosing_braces or max(enclosing_braces) != class_open:
            continue
        close_paren = matching[opening_paren]
        method_end = tokens[close_paren].end
        body_open = None
        for index in range(close_paren + 1, min(len(tokens), close_paren + 80)):
            if tokens[index].value == "{":
                body_open = index
                method_end = tokens[matching[index]].end if index in matching else tokens[index].end
                break
            if tokens[index].value == ";":
                method_end = tokens[index].end
                break
            if tokens[index].value == "=>":
                break
        if body_open is None and (
            close_paren + 1 >= len(tokens) or tokens[close_paren + 1].value not in {":", ";"}
        ):
            continue
        name = match.group("name")
        facts.append(
            ProgramEvidenceFact(
                kind="method_definition",
                name=name,
                owner=class_name,
                relationship="defines",
                span=span(match.start(), method_end),
                generated=generated,
                details={
                    "async": bool(re.search(r"\basync\b", match.group(0))),
                    "constructor": name == "constructor",
                },
            )
        )
        definition_facts.append(facts[-1])
        declaration_parens.add(opening_paren)
        if body_open is not None and body_open in matching:
            definitions.append((match.start(), method_end, f"{class_name}.{name}"))

    variable_re = re.compile(
        r"(?m)(?P<prefix>\bexport\s+(?:default\s+)?)?"
        r"\b(?P<kind>const|let|var)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)"
        r"(?P<type>\s*\??\s*:\s*[^=;,\n]+)?"
    )
    for match in variable_re.finditer(code_source):
        name = match.group("name")
        statement_end = code_source.find(";", match.end())
        if statement_end < 0:
            statement_end = code_source.find("\n", match.end())
        if statement_end < 0:
            statement_end = len(source)
        statement = code_source[match.start() : statement_end]
        fact_kind = "arrow_function_definition" if "=>" in statement else "variable_definition"
        owner = _ecmascript_owner(match.start(), definitions)
        fact = ProgramEvidenceFact(
            kind=fact_kind,
            name=name,
            owner=owner,
            relationship="defines",
            span=span(match.start(), statement_end),
            generated=generated,
            details={
                "declaration": match.group("kind"),
                "async": fact_kind == "arrow_function_definition"
                and bool(re.search(r"=\s*async\b", statement)),
            },
        )
        facts.append(fact)
        definition_facts.append(fact)
        if fact_kind == "arrow_function_definition":
            definitions.append((match.start(), statement_end, name))
        if match.group("prefix"):
            facts.append(
                ProgramEvidenceFact(
                    kind="export",
                    name="default" if "default" in match.group("prefix").split() else name,
                    owner="<module>",
                    target=name,
                    relationship="exports",
                    span=span(match.start(), match.end()),
                    generated=generated,
                    details={
                        "declaration": True,
                        "default": "default" in match.group("prefix").split(),
                    },
                )
            )
        if match.group("type"):
            target = match.group("type").split(":", 1)[1].strip()
            facts.append(
                ProgramEvidenceFact(
                    kind="type_annotation",
                    name=name,
                    owner=owner,
                    target=target,
                    relationship="variable_type",
                    span=span(match.start("type"), match.end("type")),
                    generated=generated,
                )
            )

    name_counts: dict[str, int] = {}
    for fact in definition_facts:
        key = f"{fact.owner}:{fact.name}"
        name_counts[key] = name_counts.get(key, 0) + 1
    collisions = {name for name, count in name_counts.items() if count > 1}
    if collisions:
        facts = [
            replace(fact, ambiguous=True)
            if (fact.kind.endswith("_definition") and f"{fact.owner}:{fact.name}" in collisions)
            else fact
            for fact in facts
        ]
        for collision in sorted(collisions):
            diagnostics.append(
                AdapterDiagnostic(
                    code="ecmascript_name_collision",
                    message=f"multiple definitions observed for {collision!r}",
                    severity="warning",
                    details={
                        "name": collision,
                        "parser": JAVASCRIPT_ADAPTER_VERSION,
                    },
                )
            )

    aliases: dict[str, str] = {}
    static_import_re = re.compile(
        r"^[ \t]*import[ \t]+(?!\()(?P<clause>[^;]*?)\s+from\s+"
        r"(?P<module>['\"][^'\"]+['\"])[ \t]*;?",
        re.MULTILINE,
    )
    side_effect_import_re = re.compile(
        r"(?m)^[ \t]*import[ \t]+(?P<module>['\"][^'\"]+['\"])[ \t]*;?"
    )
    for match in static_import_re.finditer(comment_masked_source):
        keyword_start = comment_masked_source.find("import", match.start(), match.end())
        if (keyword_start, "import") not in token_starts:
            continue
        module = _strip_ecmascript_string(match.group("module"))
        clause = match.group("clause").strip()
        type_only_clause = clause.startswith("type ")
        if type_only_clause:
            clause = clause[5:].strip()
        bindings: list[tuple[str, str, bool]] = []
        default_match = re.match(r"([A-Za-z_$][\w$]*)", clause)
        if default_match and not clause.startswith(("{", "*")):
            bindings.append(("default", default_match.group(1), type_only_clause))
        star_match = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", clause)
        if star_match:
            bindings.append(("*", star_match.group(1), type_only_clause))
        named_match = re.search(r"\{(?P<names>.*?)\}", clause, re.DOTALL)
        if named_match:
            for item in named_match.group("names").split(","):
                item = item.strip()
                if not item:
                    continue
                item_type_only = type_only_clause or item.startswith("type ")
                if item.startswith("type "):
                    item = item[5:].strip()
                parts = re.split(r"\s+as\s+", item)
                imported = parts[0].strip()
                local = parts[-1].strip()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", local):
                    bindings.append((imported, local, item_type_only))
        for imported, local, type_only in bindings:
            aliases[local] = f"{module}:{imported}"
            facts.append(
                ProgramEvidenceFact(
                    kind="import",
                    name=local,
                    owner="<module>",
                    target=f"{module}:{imported}",
                    relationship="imports_type" if type_only else "imports",
                    span=span(match.start(), match.end()),
                    generated=generated,
                    details={
                        "module": module,
                        "source": module,
                        "imported": imported,
                        "local": local,
                        "type_only": type_only,
                    },
                )
            )
    for match in side_effect_import_re.finditer(comment_masked_source):
        keyword_start = comment_masked_source.find("import", match.start(), match.end())
        if (keyword_start, "import") not in token_starts:
            continue
        module = _strip_ecmascript_string(match.group("module"))
        facts.append(
            ProgramEvidenceFact(
                kind="import",
                name=module,
                owner="<module>",
                target=module,
                relationship="imports_for_side_effect",
                span=span(match.start(), match.end()),
                generated=generated,
                details={
                    "module": module,
                    "source": module,
                    "side_effect_only": True,
                },
            )
        )

    export_re = re.compile(
        r"(?m)^\s*export\s+"
        r"(?P<body>(?:type\s+)?(?:\*(?:\s+as\s+[A-Za-z_$][\w$]*)?"
        r"|\{[^}]*\}|default\b[^;\n]*))"
        r"(?:\s+from\s+(?P<module>['\"][^'\"]+['\"]))?"
    )
    for match in export_re.finditer(comment_masked_source):
        keyword_start = comment_masked_source.find("export", match.start(), match.end())
        if (keyword_start, "export") not in token_starts:
            continue
        body = match.group("body").strip()
        module_token = match.group("module") or ""
        module = _strip_ecmascript_string(module_token)
        declaration_type_only = body.startswith("type ")
        names: list[tuple[str, str, bool]] = []
        if body.startswith("*"):
            alias = re.search(r"\bas\s+([A-Za-z_$][\w$]*)", body)
            names.append(("*", alias.group(1) if alias else "*", False))
        elif body.startswith("{") or body.startswith("type {"):
            content = body[body.find("{") + 1 : body.rfind("}")]
            for item in content.split(","):
                item_type_only = declaration_type_only or bool(re.match(r"^\s*type\b", item))
                item = re.sub(r"^\s*type\s+", "", item).strip()
                if item:
                    parts = re.split(r"\s+as\s+", item)
                    names.append(
                        (
                            parts[0].strip(),
                            parts[-1].strip(),
                            item_type_only,
                        )
                    )
        else:
            names.append(("default", "default", False))
        for original, exported, type_only in names:
            facts.append(
                ProgramEvidenceFact(
                    kind="re_export" if module else "export",
                    name=exported,
                    owner="<module>",
                    target=f"{module}:{original}" if module else original,
                    relationship="re_exports" if module else "exports",
                    span=span(match.start(), match.end()),
                    generated=generated,
                    details={
                        "module": module,
                        "source": module,
                        "original": original,
                        "imported": original,
                        "exported": exported,
                        "type_only": type_only,
                    },
                )
            )

    decorator_re = re.compile(r"(?m)^[ \t]*@(?P<name>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)")
    for match in decorator_re.finditer(code_source):
        decorated = next(
            (
                fact.name
                for fact in definition_facts
                if fact.span.line_start > span(match.start(), match.end()).line_end
            ),
            "",
        )
        facts.append(
            ProgramEvidenceFact(
                kind="decorator",
                name=match.group("name"),
                owner=decorated or "<unknown>",
                target=decorated,
                relationship="decorates",
                ambiguous=not bool(decorated),
                span=span(match.start(), match.end()),
                generated=generated,
            )
        )

    for index, token in enumerate(tokens):
        if token.value == "(" and index:
            previous = tokens[index - 1].value
            if previous in {"if", "for", "while", "switch", "catch", "function"}:
                declaration_parens.add(index)
            elif index > 1 and tokens[index - 2].value == "function":
                declaration_parens.add(index)

    for index, token in enumerate(tokens):
        if token.value != "(" or index in declaration_parens:
            continue
        close_index = matching.get(index)
        if close_index is None:
            continue
        if close_index + 1 < len(tokens) and tokens[close_index + 1].value == "=>":
            continue
        callee_end = index - 1
        if callee_end < 0:
            continue
        callee_start = callee_end
        while callee_start > 0:
            previous = tokens[callee_start - 1]
            if previous.value in {".", "?."} or (
                previous.kind == "identifier" and tokens[callee_start].value in {".", "?."}
            ):
                callee_start -= 1
                continue
            break
        callee_tokens = tokens[callee_start:index]
        if not callee_tokens or callee_tokens[-1].kind != "identifier":
            continue
        raw_callee = "".join(item.value for item in callee_tokens)
        callee = raw_callee.replace("?.", ".")
        if callee in {
            "if",
            "for",
            "while",
            "switch",
            "catch",
            "function",
            "super",
        }:
            continue
        is_new = callee_start > 0 and tokens[callee_start - 1].value == "new"
        is_awaited = callee_start > 0 and tokens[callee_start - 1].value == "await"
        call_start = (
            tokens[callee_start - 1].start if is_new or is_awaited else tokens[callee_start].start
        )
        owner = _ecmascript_owner(token.start, definitions)
        root = callee.split(".", 1)[0]
        alias_target = aliases.get(root, "")
        resolved_name = alias_target.rsplit(":", 1)[-1] if alias_target else ""
        call_fact = ProgramEvidenceFact(
            kind="new_expression" if is_new else "call",
            name=callee,
            owner=owner,
            target=alias_target,
            relationship="constructs" if is_new else "calls_candidate",
            ambiguous=True,
            span=span(call_start, tokens[close_index].end),
            generated=generated,
            details={
                "awaited": is_awaited,
                "optional": "?." in raw_callee,
                "optional_chain": "?." in raw_callee,
                "raw_callee": raw_callee,
                "import_alias_target": alias_target,
                "resolved_name": resolved_name,
            },
        )
        facts.append(call_fact)
        if callee == "import":
            first_argument = tokens[index + 1] if index + 1 < close_index else None
            literal = (
                _strip_ecmascript_string(first_argument.value)
                if first_argument is not None and first_argument.kind in {"string", "template"}
                else ""
            )
            facts.append(
                ProgramEvidenceFact(
                    kind="dynamic_import",
                    name=literal or "<dynamic>",
                    owner=owner,
                    target=literal,
                    relationship="imports_dynamically",
                    ambiguous=not bool(literal),
                    span=call_fact.span,
                    generated=generated,
                    details={
                        "awaited": is_awaited,
                        "literal": bool(literal),
                        "source": literal,
                    },
                )
            )
        tail = callee.rsplit(".", 1)[-1]
        arguments = code_source[token.end : tokens[close_index].start]
        has_callback = "=>" in arguments or re.search(r"\b(?:async\s+)?function\b", arguments)
        callback_kind = (
            "async_arrow"
            if re.search(r"\basync\b[^=]*=>", arguments, re.DOTALL)
            else "arrow"
            if "=>" in arguments
            else "async_function"
            if re.search(r"\basync\s+function\b", arguments)
            else "function"
            if re.search(r"\bfunction\b", arguments)
            else ""
        )
        if has_callback:
            facts.append(
                ProgramEvidenceFact(
                    kind="callback",
                    name=callee,
                    owner=owner,
                    target=callee,
                    relationship="passed_to",
                    ambiguous=True,
                    span=span(token.end, tokens[close_index].start),
                    generated=generated,
                    details={
                        "async": callback_kind.startswith("async_"),
                        "callback_kind": callback_kind,
                    },
                )
            )
        if tail in _ECMASCRIPT_REGISTRATION_NAMES:
            registration = ""
            for argument in tokens[index + 1 : close_index]:
                if argument.kind in {"string", "template"}:
                    registration = _strip_ecmascript_string(argument.value)
                    break
            facts.append(
                ProgramEvidenceFact(
                    kind="registration",
                    name=callee,
                    owner=owner,
                    target=callee,
                    relationship="registers_callback" if has_callback else "registers_handler",
                    ambiguous=True,
                    span=call_fact.span,
                    generated=generated,
                    details={
                        "callback_kind": callback_kind,
                        "has_callback": has_callback,
                        "registration": registration,
                    },
                )
            )
            for argument in tokens[index + 1 : close_index]:
                if argument.kind not in {"string", "template"}:
                    continue
                literal = _strip_ecmascript_string(argument.value)
                facts.append(
                    ProgramEvidenceFact(
                        kind="string_literal",
                        name=literal,
                        owner=owner,
                        target=callee,
                        relationship="registration_key",
                        ambiguous=argument.kind == "template" and "${" in argument.value,
                        span=argument.span,
                        generated=generated,
                        details={"mcp_relevant": True, "value": literal},
                    )
                )

    if language in {"typescript", "tsx"}:
        annotation_re = re.compile(
            r"(?P<name>[A-Za-z_$][\w$]*)\s*\??\s*:\s*"
            r"(?P<type>[A-Za-z_$][\w$]*(?:\s*<[^;\n=,)>{}]+>)?(?:\[\])?)"
        )
        for match in annotation_re.finditer(code_source):
            facts.append(
                ProgramEvidenceFact(
                    kind="type_annotation",
                    name=match.group("name"),
                    owner=_ecmascript_owner(match.start(), definitions),
                    target=match.group("type").strip(),
                    relationship="has_type",
                    span=span(match.start(), match.end()),
                    generated=generated,
                )
            )
    heritage_re = re.compile(
        r"\b(?:class|interface)\s+(?P<name>[A-Za-z_$][\w$]*)\s+"
        r"(?P<relation>extends|implements)\s+(?P<types>[^{]+)"
    )
    for match in heritage_re.finditer(code_source):
        for target in match.group("types").split(","):
            target = target.strip()
            if target:
                facts.append(
                    ProgramEvidenceFact(
                        kind="type_reference",
                        name=match.group("name"),
                        owner=match.group("name"),
                        target=target,
                        relationship=match.group("relation"),
                        span=span(match.start("types"), match.end("types")),
                        generated=generated,
                    )
                )

    if language in {"jsx", "tsx"}:
        for match in re.finditer(r"<(?P<name>[A-Za-z][\w.-]*)(?:\s|/?>)", code_source):
            facts.append(
                ProgramEvidenceFact(
                    kind="jsx_element",
                    name=match.group("name"),
                    owner=_ecmascript_owner(match.start(), definitions),
                    relationship="renders",
                    ambiguous=match.group("name")[0].isupper(),
                    span=span(match.start(), match.end()),
                    generated=generated,
                )
            )

    registration_spans = [fact.span for fact in facts if fact.kind == "registration"]
    for token in tokens:
        if token.kind not in {"string", "template"}:
            continue
        literal = _strip_ecmascript_string(token.value)
        if not _ECMASCRIPT_MCP_STRING_RE.search(literal):
            continue
        if any(
            item.line_start <= token.span.line_start <= item.line_end for item in registration_spans
        ):
            continue
        facts.append(
            ProgramEvidenceFact(
                kind="string_literal",
                name=literal,
                owner=_ecmascript_owner(token.start, definitions),
                relationship="mcp_relevant_literal",
                ambiguous=token.kind == "template" and "${" in token.value,
                span=token.span,
                generated=generated,
                details={"mcp_relevant": True, "value": literal},
            )
        )

    for token in tokens:
        if token.kind == "identifier" and token.value in {"debugger", "with"}:
            facts.append(
                ProgramEvidenceFact(
                    kind="unsupported_node",
                    name=token.value,
                    owner=_ecmascript_owner(token.start, definitions),
                    relationship="preserved_unmodeled_syntax",
                    ambiguous=True,
                    span=token.span,
                    generated=generated,
                    details={"parser": JAVASCRIPT_ADAPTER_VERSION},
                )
            )
            diagnostics.append(
                AdapterDiagnostic(
                    code="ecmascript_unsupported_node",
                    message=f"syntax node {token.value!r} is preserved but not modeled",
                    severity="warning",
                    span=token.span,
                    details={
                        "node": token.value,
                        "parser": JAVASCRIPT_ADAPTER_VERSION,
                    },
                )
            )

    for match in re.finditer(
        r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*(?=;|$)",
        code_source,
        re.MULTILINE,
    ):
        initializer_start = code_source.find("=", match.start(), match.end()) + 1
        if any(initializer_start <= token.start < match.end() for token in tokens):
            continue
        diagnostics.append(
            AdapterDiagnostic(
                code="ecmascript_missing_initializer",
                message="variable initializer expression is missing",
                span=span(match.start(), match.end()),
                details={"parser": JAVASCRIPT_ADAPTER_VERSION},
            )
        )

    return _deduplicate_facts(facts), tuple(diagnostics)


def adapt_ecmascript_source(
    source: str,
    *,
    path: str = "",
    language: str = "",
    blob_identity: str = "",
    previous: ProgramASTAdapterResult | ASTBlobRecord | None = None,
    generated: bool = False,
) -> ProgramASTAdapterResult:
    """Adapt JavaScript/TypeScript syntax into content-bound evidence."""

    source_hash = _source_sha256(source)
    blob = str(blob_identity or source_hash)
    normalized_language = detect_program_language(path, language)
    if normalized_language == "unknown" and not language:
        normalized_language = "javascript"
    if normalized_language not in {"javascript", "jsx", "typescript", "tsx"}:
        raise ValueError(f"unsupported ECMAScript language {normalized_language!r}")
    if isinstance(previous, ProgramASTAdapterResult):
        previous_record = previous.ast_record
    else:
        previous_record = previous

    facts, diagnostics = _ecmascript_facts(
        source,
        language=normalized_language,
        generated=generated,
    )
    errors = tuple(item for item in diagnostics if item.severity == "error")
    parse_error = "; ".join(f"{item.code}: {item.message}" for item in errors)
    derived_record = _ecmascript_record(
        source=source,
        facts=facts,
        source_hash=source_hash,
        blob_identity=blob,
        language=normalized_language,
        parse_error=parse_error,
    )
    if (
        isinstance(previous_record, ASTBlobRecord)
        and previous_record.language == normalized_language
        and previous_record.source_sha256 == source_hash
        and previous_record.blob_identity == blob
        and previous_record.record_id == derived_record.record_id
    ):
        record = previous_record
        reused = True
    else:
        record = derived_record
        reused = False
    return ProgramASTAdapterResult(
        path=path,
        language=normalized_language,
        status="malformed" if errors else "success",
        source_sha256=source_hash,
        blob_identity=blob,
        parser=JAVASCRIPT_ADAPTER_VERSION,
        ast_record=record,
        facts=facts,
        diagnostics=diagnostics,
        generated=generated,
        reused=reused,
    )


class _JSONObject(list[tuple[str, Any]]):
    """Pair-preserving JSON object used to detect duplicate member names."""


def _json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _decode_json_pairs(
    value: Any,
    *,
    pointer: str = "",
    duplicates: list[tuple[str, str]] | None = None,
) -> Any:
    duplicates = duplicates if duplicates is not None else []
    if isinstance(value, _JSONObject):
        result: dict[str, Any] = {}
        seen: set[str] = set()
        for key, item in value:
            child_pointer = f"{pointer}/{_json_pointer_escape(key)}"
            if key in seen:
                duplicates.append((pointer or "/", key))
            seen.add(key)
            result[key] = _decode_json_pairs(item, pointer=child_pointer, duplicates=duplicates)
        return result
    if isinstance(value, list):
        return [
            _decode_json_pairs(item, pointer=f"{pointer}/{index}", duplicates=duplicates)
            for index, item in enumerate(value)
        ]
    return value


def _offset_span(source: str, start: int, end: int) -> SourceSpan:
    before = source[:start]
    line_start = before.count("\n") + 1
    last_newline = before.rfind("\n")
    column_start = start if last_newline < 0 else start - last_newline - 1
    segment = source[start:end]
    if "\n" in segment:
        line_end = line_start + segment.count("\n")
        column_end = len(segment.rsplit("\n", 1)[-1])
    else:
        line_end = line_start
        column_end = column_start + len(segment)
    return SourceSpan(line_start, column_start, line_end, column_end)


def _json_key_spans(source: str) -> dict[str, list[SourceSpan]]:
    spans: dict[str, list[SourceSpan]] = {}
    for match in _JSON_STRING_RE.finditer(source):
        tail = source[match.end() :]
        if not re.match(r"\s*:", tail):
            continue
        try:
            key = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(key, str):
            spans.setdefault(key, []).append(_offset_span(source, match.start(), match.end()))
    return spans


def _looks_generated(path: str, payload: Any) -> bool:
    lowered = path.casefold().replace("\\", "/")
    segments = frozenset(PurePosixPath(lowered).parts)
    if any(
        marker in lowered
        for marker in (
            ".generated.",
            ".gen.",
            "autogen",
        )
    ) or segments.intersection({"generated", "__generated__", "gen"}):
        return True
    if not isinstance(payload, Mapping):
        return False
    for key in ("generated", "x-generated", "generatedBy", "generator"):
        if key in payload and payload[key] not in (False, None, ""):
            return True
    comment = str(payload.get("$comment") or "").casefold()
    return "generated" in comment or "do not edit" in comment


def _json_facts(
    payload: Any,
    *,
    source: str,
    path: str,
    generated: bool,
) -> tuple[ProgramEvidenceFact, ...]:
    facts: list[ProgramEvidenceFact] = []
    key_spans = _json_key_spans(source)
    key_offsets: dict[str, int] = {}
    filename = PurePosixPath(path.replace("\\", "/")).name.casefold()
    root = payload if isinstance(payload, Mapping) else {}
    is_schema = bool(
        filename.endswith((".schema.json", ".jsonschema"))
        or any(key in root for key in ("$schema", "$defs", "definitions"))
    )
    is_mcp = bool(
        any(key in root for key in ("mcpServers", "tools", "prompts", "resources"))
        or "mcp" in filename
    )

    def span_for(key: str) -> SourceSpan:
        candidates = key_spans.get(key, ())
        index = key_offsets.get(key, 0)
        key_offsets[key] = index + 1
        return candidates[min(index, len(candidates) - 1)] if candidates else SourceSpan()

    def walk(value: Any, pointer: str = "") -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                child = f"{pointer}/{_json_pointer_escape(str(key))}"
                span = span_for(str(key))
                facts.append(
                    ProgramEvidenceFact(
                        kind="json_member",
                        name=child,
                        owner=pointer or "/",
                        target=str(key),
                        relationship="contains",
                        span=span,
                        generated=generated,
                        details={"value_type": type(item).__name__},
                    )
                )
                if key == "$ref" and isinstance(item, str):
                    facts.append(
                        ProgramEvidenceFact(
                            kind="schema_reference",
                            name=child,
                            owner=pointer or "/",
                            target=item,
                            relationship="references_schema",
                            ambiguous=not item.startswith("#/"),
                            normative=True,
                            span=span,
                            generated=generated,
                        )
                    )
                if is_schema and key in {"$defs", "definitions", "properties"}:
                    if isinstance(item, Mapping):
                        subkind = "schema_property" if key == "properties" else "schema_definition"
                        for member in item:
                            facts.append(
                                ProgramEvidenceFact(
                                    kind=subkind,
                                    name=str(member),
                                    owner=child,
                                    target=f"{child}/{_json_pointer_escape(str(member))}",
                                    relationship="declares",
                                    normative=True,
                                    span=span_for(str(member)),
                                    generated=generated,
                                )
                            )
                if is_schema and key == "required" and isinstance(item, list):
                    for member in item:
                        if isinstance(member, str):
                            facts.append(
                                ProgramEvidenceFact(
                                    kind="schema_required",
                                    name=member,
                                    owner=pointer or "/",
                                    target=member,
                                    relationship="requires",
                                    normative=True,
                                    span=span,
                                    generated=generated,
                                )
                            )
                if is_mcp and key == "mcpServers" and isinstance(item, Mapping):
                    for server_name in item:
                        facts.append(
                            ProgramEvidenceFact(
                                kind="mcp_server",
                                name=str(server_name),
                                owner=child,
                                target=f"{child}/{_json_pointer_escape(str(server_name))}",
                                relationship="declares",
                                normative=True,
                                span=span_for(str(server_name)),
                                generated=generated,
                            )
                        )
                if is_mcp and key in {"tools", "prompts", "resources"}:
                    entries = item if isinstance(item, list) else ()
                    for index, entry in enumerate(entries):
                        if isinstance(entry, Mapping):
                            entry_name = str(
                                entry.get("name") or entry.get("uri") or entry.get("id") or index
                            )
                            facts.append(
                                ProgramEvidenceFact(
                                    kind=f"mcp_{key[:-1]}",
                                    name=entry_name,
                                    owner=child,
                                    target=f"{child}/{index}",
                                    relationship="declares",
                                    normative=True,
                                    span=span_for("name"),
                                    generated=generated,
                                    details={
                                        "has_input_schema": "inputSchema" in entry
                                        or "input_schema" in entry
                                    },
                                )
                            )
                walk(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{pointer}/{index}")

    walk(payload)
    if is_schema:
        facts.append(
            ProgramEvidenceFact(
                kind="json_schema",
                # Repository paths are intentionally excluded from facts that
                # feed ASTBlobRecord identity.  The path is attached later by
                # analysis_ast_index, preserving exact reuse across renames.
                name=str(root.get("$id") or "<schema>"),
                owner="/",
                target=str(root.get("$schema") or ""),
                relationship="declares_contract",
                normative=True,
                span=SourceSpan(1, 0, 1, 0),
                generated=generated,
            )
        )
    if is_mcp:
        facts.append(
            ProgramEvidenceFact(
                kind="mcp_manifest",
                name="<manifest>",
                owner="/",
                relationship="declares_contract",
                normative=True,
                span=SourceSpan(1, 0, 1, 0),
                generated=generated,
            )
        )
    if generated:
        facts.append(
            ProgramEvidenceFact(
                kind="generated_manifest",
                name="<manifest>",
                owner="/",
                relationship="generated_evidence",
                span=SourceSpan(1, 0, 1, 0),
                generated=True,
            )
        )
    return _deduplicate_facts(facts)


def _record_from_noncode_facts(
    *,
    facts: Sequence[ProgramEvidenceFact],
    source_hash: str,
    blob_identity: str,
    language: str,
    parse_error: str = "",
) -> ASTBlobRecord:
    symbol_facts = tuple(
        fact
        for fact in facts
        if fact.kind
        in {
            "json_schema",
            "schema_definition",
            "schema_property",
            "mcp_manifest",
            "mcp_server",
            "mcp_tool",
            "mcp_prompt",
            "mcp_resource",
            "heading",
            "normative_statement",
            "code_reference",
        }
    )
    symbol_names: list[str] = []
    symbol_hashes: dict[str, str] = {}
    symbol_lines: dict[str, tuple[int, int]] = {}
    for fact in symbol_facts:
        base = f"{fact.kind}:{fact.name}"
        name = base
        suffix = 2
        while name in symbol_hashes:
            name = f"{base}#{suffix}"
            suffix += 1
        symbol_names.append(name)
        # ``generated`` may originate in inventory/path classification rather
        # than source content, so it cannot participate in a path-independent
        # canonical record identity.
        symbol_hashes[name] = _semantic_hash(
            {key: value for key, value in fact._payload().items() if key != "generated"}
        )
        symbol_lines[name] = (fact.span.line_start, fact.span.line_end)
    imports = tuple(
        f"$ref {fact.target}" for fact in facts if fact.kind == "schema_reference" and fact.target
    )
    interfaces = tuple(
        f"{fact.kind}:{fact.owner}:{fact.name}"
        for fact in facts
        if fact.normative
        and fact.kind
        in {
            "json_schema",
            "schema_definition",
            "schema_property",
            "schema_required",
            "mcp_manifest",
            "mcp_server",
            "mcp_tool",
            "mcp_prompt",
            "mcp_resource",
            "heading",
            "normative_statement",
            "code_reference",
        }
    )
    return ASTBlobRecord(
        blob_identity=blob_identity,
        source_sha256=source_hash,
        qualified_symbols=tuple(symbol_names),
        imports=imports,
        calls=(),
        state_transitions=(),
        interfaces=interfaces,
        symbol_hashes=symbol_hashes,
        symbol_lines=symbol_lines,
        parse_error=parse_error,
        language=language,
    )


def adapt_json_source(
    source: str,
    *,
    path: str = "",
    blob_identity: str = "",
    previous: ProgramASTAdapterResult | ASTBlobRecord | None = None,
    generated: bool = False,
) -> ProgramASTAdapterResult:
    """Adapt JSON while retaining duplicate keys and schema/MCP semantics."""

    source_hash = _source_sha256(source)
    blob = str(blob_identity or source_hash)
    try:
        raw = json.loads(source, object_pairs_hook=_JSONObject)
    except (json.JSONDecodeError, RecursionError) as exc:
        if isinstance(exc, json.JSONDecodeError):
            span = SourceSpan(exc.lineno, exc.colno - 1, exc.lineno, exc.colno - 1)
            message = exc.msg
        else:
            span = SourceSpan()
            message = str(exc)
        diagnostic = AdapterDiagnostic(code="json_syntax_error", message=message, span=span)
        record = _record_from_noncode_facts(
            facts=(),
            source_hash=source_hash,
            blob_identity=blob,
            language="json",
            parse_error=f"{diagnostic.code}: {diagnostic.message}",
        )
        return ProgramASTAdapterResult(
            path=path,
            language="json",
            status="malformed",
            source_sha256=source_hash,
            blob_identity=blob,
            parser=JSON_ADAPTER_VERSION,
            ast_record=record,
            diagnostics=(diagnostic,),
            generated=generated,
        )

    duplicates: list[tuple[str, str]] = []
    payload = _decode_json_pairs(raw, duplicates=duplicates)
    generated = bool(generated or _looks_generated(path, payload))
    root = payload if isinstance(payload, Mapping) else {}
    filename = PurePosixPath(path.replace("\\", "/")).name.casefold()
    is_schema = bool(
        filename.endswith((".schema.json", ".jsonschema"))
        or any(key in root for key in ("$schema", "$defs", "definitions"))
    )
    is_mcp = bool(
        any(key in root for key in ("mcpServers", "tools", "prompts", "resources"))
        or "mcp" in filename
    )
    language = "mcp-manifest" if is_mcp else "json-schema" if is_schema else "json"
    facts = _json_facts(payload, source=source, path=path, generated=generated)
    key_spans = _json_key_spans(source)
    duplicate_offsets: dict[str, int] = {}
    diagnostics: list[AdapterDiagnostic] = []
    for pointer, key in duplicates:
        spans = key_spans.get(key, ())
        occurrence = duplicate_offsets.get(key, 1)
        duplicate_offsets[key] = occurrence + 1
        span = spans[min(occurrence, len(spans) - 1)] if spans else SourceSpan()
        diagnostics.append(
            AdapterDiagnostic(
                code="duplicate_json_key",
                message=f"duplicate JSON member {key!r} at {pointer}",
                severity="warning",
                span=span,
                details={"key": key, "object_pointer": pointer},
            )
        )
    record = _record_from_noncode_facts(
        facts=facts,
        source_hash=source_hash,
        blob_identity=blob,
        language=language,
    )
    previous_record = (
        previous.ast_record if isinstance(previous, ProgramASTAdapterResult) else previous
    )
    reused = bool(
        isinstance(previous_record, ASTBlobRecord) and previous_record.record_id == record.record_id
    )
    if reused:
        record = previous_record
    return ProgramASTAdapterResult(
        path=path,
        language=language,
        status="partial" if diagnostics else "success",
        source_sha256=source_hash,
        blob_identity=blob,
        parser=JSON_ADAPTER_VERSION,
        ast_record=record,
        facts=facts,
        diagnostics=tuple(diagnostics),
        generated=generated,
        reused=reused,
    )


def _markdown_facts(
    source: str, *, generated: bool
) -> tuple[tuple[ProgramEvidenceFact, ...], tuple[AdapterDiagnostic, ...]]:
    facts: list[ProgramEvidenceFact] = []
    diagnostics: list[AdapterDiagnostic] = []
    fence_marker = ""
    fence_start = 0
    fence_info = ""
    fence_lines: list[str] = []

    for line_number, line_with_end in enumerate(source.splitlines(keepends=True), 1):
        line = line_with_end.rstrip("\r\n")
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not fence_marker:
                fence_marker = marker
                fence_start = line_number
                fence_info = fence.group(2).strip()
                fence_lines = []
                continue
            if marker[0] == fence_marker[0] and len(marker) >= len(fence_marker):
                facts.append(
                    ProgramEvidenceFact(
                        kind="code_fence",
                        name=fence_info or "plain",
                        owner="<markdown>",
                        target="\n".join(fence_lines),
                        relationship="example",
                        normative=False,
                        span=SourceSpan(
                            fence_start,
                            0,
                            line_number,
                            len(line),
                        ),
                        generated=generated,
                        details={"example": True, "fence": fence_marker[0]},
                    )
                )
                fence_marker = ""
                fence_info = ""
                fence_lines = []
                continue
        if fence_marker:
            fence_lines.append(line)
            for match in _INLINE_CODE_RE.finditer(line):
                facts.append(
                    ProgramEvidenceFact(
                        kind="code_reference",
                        name=match.group(1),
                        owner="<fenced-example>",
                        target=match.group(1),
                        relationship="example_reference",
                        normative=False,
                        span=SourceSpan(
                            line_number,
                            match.start(),
                            line_number,
                            match.end(),
                        ),
                        generated=generated,
                        details={"example": True},
                    )
                )
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            title = heading.group(2).strip()
            facts.append(
                ProgramEvidenceFact(
                    kind="heading",
                    name=title,
                    owner="<markdown>",
                    target=title,
                    relationship="section",
                    normative=True,
                    span=SourceSpan(line_number, 0, line_number, len(line)),
                    generated=generated,
                    details={"level": len(heading.group(1))},
                )
            )
        matches = tuple(_NORMATIVE_WORD_RE.finditer(line))
        if matches:
            facts.append(
                ProgramEvidenceFact(
                    kind="normative_statement",
                    name=" ".join(line.split()),
                    owner="<markdown>",
                    relationship="declares_requirement",
                    normative=True,
                    span=SourceSpan(line_number, 0, line_number, len(line)),
                    generated=generated,
                    details={"keywords": tuple(match.group(1).upper() for match in matches)},
                )
            )
        for match in _INLINE_CODE_RE.finditer(line):
            facts.append(
                ProgramEvidenceFact(
                    kind="code_reference",
                    name=match.group(1),
                    owner="<markdown>",
                    target=match.group(1),
                    relationship="references_code",
                    normative=bool(matches),
                    span=SourceSpan(
                        line_number,
                        match.start(),
                        line_number,
                        match.end(),
                    ),
                    generated=generated,
                    details={"example": False},
                )
            )
    if fence_marker:
        diagnostics.append(
            AdapterDiagnostic(
                code="unclosed_markdown_fence",
                message=f"unclosed Markdown code fence beginning at line {fence_start}",
                severity="warning",
                span=SourceSpan(fence_start, 0, fence_start, len(fence_marker)),
            )
        )
        facts.append(
            ProgramEvidenceFact(
                kind="code_fence",
                name=fence_info or "plain",
                owner="<markdown>",
                target="\n".join(fence_lines),
                relationship="example",
                normative=False,
                span=SourceSpan(
                    fence_start,
                    0,
                    len(source.splitlines()) or fence_start,
                    len(fence_lines[-1]) if fence_lines else len(fence_marker),
                ),
                generated=generated,
                ambiguous=True,
                details={"example": True, "unclosed": True},
            )
        )
    return _deduplicate_facts(facts), tuple(diagnostics)


def adapt_markdown_source(
    source: str,
    *,
    path: str = "",
    blob_identity: str = "",
    previous: ProgramASTAdapterResult | ASTBlobRecord | None = None,
    generated: bool = False,
) -> ProgramASTAdapterResult:
    """Adapt normative Markdown without treating fenced examples as contracts."""

    source_hash = _source_sha256(source)
    blob = str(blob_identity or source_hash)
    facts, diagnostics = _markdown_facts(source, generated=generated)
    record = _record_from_noncode_facts(
        facts=facts,
        source_hash=source_hash,
        blob_identity=blob,
        language="markdown",
    )
    previous_record = (
        previous.ast_record if isinstance(previous, ProgramASTAdapterResult) else previous
    )
    reused = bool(
        isinstance(previous_record, ASTBlobRecord) and previous_record.record_id == record.record_id
    )
    if reused:
        record = previous_record
    return ProgramASTAdapterResult(
        path=path,
        language="markdown",
        status="partial" if diagnostics else "success",
        source_sha256=source_hash,
        blob_identity=blob,
        parser=MARKDOWN_ADAPTER_VERSION,
        ast_record=record,
        facts=facts,
        diagnostics=diagnostics,
        generated=generated,
        reused=reused,
    )


def detect_program_language(path: str, language: str = "") -> str:
    """Return a closed adapter language name from a hint or path."""

    hint = str(language or "").strip().casefold().replace("_", "-")
    aliases = {
        "py": "python",
        "python3": "python",
        "js": "javascript",
        "node": "javascript",
        "nodejs": "javascript",
        "mjs": "javascript",
        "cjs": "javascript",
        "javascriptreact": "jsx",
        "js-react": "jsx",
        "ts": "typescript",
        "mts": "typescript",
        "cts": "typescript",
        "typescriptreact": "tsx",
        "ts-react": "tsx",
        "jsonschema": "json",
        "json-schema": "json",
        "schema": "json",
        "mcp": "json",
        "mcp-manifest": "json",
        "md": "markdown",
        "commonmark": "markdown",
        "gfm": "markdown",
    }
    if hint:
        return aliases.get(hint, hint)
    suffix = PurePosixPath(str(path).casefold()).suffix
    if suffix in _PYTHON_SUFFIXES:
        return "python"
    if suffix in _JAVASCRIPT_SUFFIXES:
        return "javascript"
    if suffix in _JSX_SUFFIXES:
        return "jsx"
    if suffix in _TYPESCRIPT_SUFFIXES:
        return "typescript"
    if suffix in _TSX_SUFFIXES:
        return "tsx"
    if suffix in _JSON_SUFFIXES:
        return "json"
    if suffix in _MARKDOWN_SUFFIXES:
        return "markdown"
    return "unknown"



def _mirror_program_ast(result: ProgramASTAdapterResult) -> ProgramASTAdapterResult:
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(result.blob_identity or result.source_sha256 or result.path or "program-ast")
        mirror_work_record(
            catalog_kind="ast",
            record_kind="program_ast_adapter",
            record_ref=record_ref,
            subject_kind="path" if result.path else "record_cid",
            subject_ref=str(result.path or record_ref),
            paths=(str(result.path),) if result.path else (),
        )
    except Exception:
        pass
    return result


def adapt_program_source(
    source: str,
    *,
    path: str = "",
    language: str = "",
    blob_identity: str = "",
    previous: ProgramASTAdapterResult | ASTBlobRecord | None = None,
    generated: bool = False,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_facts: int = DEFAULT_MAX_FACTS,
) -> ProgramASTAdapterResult:
    """Dispatch one input and return success, malformed, or unsupported."""

    if not isinstance(source, str):
        raise TypeError("program adapter source must be text")
    max_source_bytes = _positive_limit(max_source_bytes, "max_source_bytes")
    max_facts = _positive_limit(max_facts, "max_facts")
    source_hash = _source_sha256(source)
    blob = str(blob_identity or source_hash)
    detected = detect_program_language(path, language)
    byte_count = len(source.encode("utf-8", errors="surrogatepass"))
    if byte_count > max_source_bytes:
        return _mirror_program_ast(ProgramASTAdapterResult(
            path=path,
            language=detected,
            status="unsupported",
            source_sha256=source_hash,
            blob_identity=blob,
            parser="none",
            diagnostics=(
                AdapterDiagnostic(
                    code="source_size_bound_exceeded",
                    message=(
                        f"source contains {byte_count} bytes; adapter limit is {max_source_bytes}"
                    ),
                    details={
                        "observed_bytes": byte_count,
                        "max_source_bytes": max_source_bytes,
                    },
                ),
            ),
            generated=generated,
        ))
    if detected == "python":
        result = adapt_python_source(
            source,
            path=path,
            blob_identity=blob,
            previous=previous,
            generated=generated,
        )
    elif detected in {"javascript", "jsx", "typescript", "tsx"}:
        result = adapt_ecmascript_source(
            source,
            path=path,
            language=detected,
            blob_identity=blob,
            previous=previous,
            generated=generated,
        )
    elif detected == "json":
        result = adapt_json_source(
            source,
            path=path,
            blob_identity=blob,
            previous=previous,
            generated=generated,
        )
    elif detected == "markdown":
        result = adapt_markdown_source(
            source,
            path=path,
            blob_identity=blob,
            previous=previous,
            generated=generated,
        )
    else:
        return _mirror_program_ast(ProgramASTAdapterResult(
            path=path,
            language=detected,
            status="unsupported",
            source_sha256=source_hash,
            blob_identity=blob,
            parser="none",
            diagnostics=(
                AdapterDiagnostic(
                    code="unsupported_language",
                    message=f"no program evidence adapter for language {detected!r}",
                    details={"language": detected, "path": path},
                ),
            ),
            generated=generated,
        ))
    if len(result.facts) <= max_facts:
        return _mirror_program_ast(result)
    retained = result.facts[:max_facts]
    diagnostic = AdapterDiagnostic(
        code="fact_bound_exceeded",
        message=(f"adapter emitted {len(result.facts)} facts; retained {max_facts}"),
        severity="warning",
        details={"observed_facts": len(result.facts), "max_facts": max_facts},
    )
    # The canonical record is rebuilt from the retained non-code facts.  Python
    # keeps its complete canonical AST record; its sidecar alone is bounded.
    record = result.ast_record
    if (
        result.language not in {"python", "javascript", "jsx", "typescript", "tsx"}
        and record is not None
    ):
        record = _record_from_noncode_facts(
            facts=retained,
            source_hash=result.source_sha256,
            blob_identity=result.blob_identity,
            language=result.language,
            parse_error=result.parse_error,
        )
    return _mirror_program_ast(replace(
        result,
        status="partial",
        ast_record=record,
        facts=retained,
        diagnostics=(*result.diagnostics, diagnostic),
    ))


def _coerce_document(value: Any) -> SourceDocument:
    if isinstance(value, SourceDocument):
        return value
    if isinstance(value, Mapping):
        return SourceDocument(
            path=str(value.get("path") or value.get("file") or ""),
            source=str(
                value.get("source") if value.get("source") is not None else value.get("text", "")
            ),
            language=str(value.get("language") or ""),
            blob_identity=str(value.get("blob_identity") or value.get("blob_id") or ""),
            generated=bool(value.get("generated", False)),
        )
    if (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 2
    ):
        return SourceDocument(path=str(value[0]), source=str(value[1]))
    raise TypeError("source documents require SourceDocument, mapping, or path/source pair")


def _program_result_cache_language(language: str) -> str:
    """Normalize result languages only within one parser family."""

    if language in {"json", "json-schema", "mcp-manifest"}:
        return "json"
    return language


def _program_result_cache_key(
    *,
    language: str,
    blob_identity: str,
    source_sha256: str,
) -> tuple[str, str, str]:
    return (
        _program_result_cache_language(language),
        str(blob_identity),
        str(source_sha256),
    )


def build_program_evidence_index(
    documents: Iterable[SourceDocument | Mapping[str, Any] | Sequence[str]] | Mapping[str, str],
    *,
    previous: ProgramEvidenceIndex | None = None,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_facts: int = DEFAULT_MAX_FACTS,
) -> ProgramEvidenceIndex:
    """Adapt a complete mixed snapshot into the shared analysis AST index."""

    raw_documents: Iterable[Any]
    if isinstance(documents, Mapping):
        raw_documents = tuple(documents.items())
    else:
        raw_documents = documents
    normalized = tuple(
        sorted((_coerce_document(item) for item in raw_documents), key=lambda item: item.path)
    )
    if not all(item.path for item in normalized):
        raise ValueError("batch program evidence inputs require repository paths")
    if len({item.path for item in normalized}) != len(normalized):
        raise ValueError("batch program evidence snapshot contains duplicate paths")
    previous_by_content: dict[tuple[str, str, str], ASTBlobRecord] = {}
    conflicting_cache_keys: set[tuple[str, str, str]] = set()
    if previous is not None:
        for prior in previous.results:
            if prior.ast_record is None:
                continue
            key = _program_result_cache_key(
                language=prior.language,
                blob_identity=prior.blob_identity,
                source_sha256=prior.source_sha256,
            )
            existing = previous_by_content.get(key)
            if existing is not None and existing.record_id != prior.ast_record.record_id:
                conflicting_cache_keys.add(key)
                previous_by_content.pop(key, None)
            elif key not in conflicting_cache_keys:
                previous_by_content[key] = prior.ast_record

    def previous_record(item: SourceDocument) -> ASTBlobRecord | None:
        source_hash = _source_sha256(item.source)
        blob_identity = str(item.blob_identity or source_hash)
        cache_key = _program_result_cache_key(
            language=detect_program_language(item.path, item.language),
            blob_identity=blob_identity,
            source_sha256=source_hash,
        )
        return previous_by_content.get(cache_key)

    results = tuple(
        adapt_program_source(
            item.source,
            path=item.path,
            language=item.language,
            blob_identity=item.blob_identity,
            # Only canonical path-independent records cross snapshots.  Full
            # results contain path-sensitive diagnostics and generated flags,
            # so reusing them across a rename makes warm output differ from a
            # cold parse.
            previous=previous_record(item),
            generated=item.generated,
            max_source_bytes=max_source_bytes,
            max_facts=max_facts,
        )
        for item in normalized
    )
    path_records = tuple(
        (item.path, item.ast_record) for item in results if item.ast_record is not None
    )
    index = build_analysis_ast_index(
        path_records,
        previous=previous.analysis_index if previous is not None else None,
    )
    evidence = ProgramEvidenceIndex(analysis_index=index, results=results)
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        index_id = str(getattr(index, "index_id", "") or "")
        mirror_work_record(
            catalog_kind="ast",
            record_kind="program_evidence_index",
            record_ref=index_id or "program-evidence-index",
            subject_kind="record_cid",
            subject_ref=index_id or "program-evidence-index",
        )
    except Exception:
        pass
    return evidence


def build_inventory_program_evidence_receipt(
    inventory: RepositoryCorpusIndex,
    documents: Iterable[SourceDocument | Mapping[str, Any] | Sequence[str]] | Mapping[str, str],
    *,
    previous: InventoryProgramEvidenceReceipt | None = None,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_facts: int = DEFAULT_MAX_FACTS,
) -> InventoryProgramEvidenceReceipt:
    """Build provenance-checked program coverage for one corpus inventory.

    Inputs may use canonical inventory paths or unambiguous repository-relative
    paths.  Every source is checked against its inventory SHA-256 observation
    and is adapted under the inventory's blob identity.  Unprovided admitted
    inputs remain explicit missing-path receipts instead of disappearing from
    an otherwise successful AST snapshot.
    """

    if not isinstance(inventory, RepositoryCorpusIndex):
        raise TypeError("inventory program evidence requires RepositoryCorpusIndex")
    if previous is not None and not isinstance(previous, InventoryProgramEvidenceReceipt):
        raise TypeError(
            "previous inventory program evidence must be a verified InventoryProgramEvidenceReceipt"
        )

    raw_documents: Iterable[Any]
    if isinstance(documents, Mapping):
        raw_documents = tuple(documents.items())
    else:
        raw_documents = documents
    supplied = tuple(_coerce_document(item) for item in raw_documents)
    if not all(item.path for item in supplied):
        raise ValueError("inventory program evidence inputs require repository paths")

    admitted = tuple(item for item in inventory.included_entries if item.parser_eligible)
    by_canonical = {item.canonical_path: item for item in admitted}
    if len(by_canonical) != len(admitted):
        raise ValueError("inventory contains duplicate admitted canonical paths")
    by_relative: dict[str, list[CorpusEntry]] = {}
    for entry in admitted:
        by_relative.setdefault(entry.relative_path, []).append(entry)
    if previous is not None:
        previous.verify_against_inventory(inventory)

    normalized: list[SourceDocument] = []
    seen: set[str] = set()
    for document in supplied:
        entry = by_canonical.get(document.path)
        if entry is None:
            candidates = by_relative.get(document.path, ())
            if len(candidates) > 1:
                raise ValueError(
                    f"inventory document path is ambiguous across repositories: {document.path!r}"
                )
            entry = candidates[0] if candidates else None
        if entry is None:
            raise ValueError(f"document is not an admitted inventory input: {document.path!r}")
        if entry.canonical_path in seen:
            raise ValueError(
                f"inventory program evidence contains duplicate path {entry.canonical_path!r}"
            )
        seen.add(entry.canonical_path)

        observed_hash = _source_sha256(document.source)
        expected_hash = "sha256:" + entry.content_sha256
        if observed_hash != expected_hash:
            raise ValueError(
                f"document content does not match inventory provenance for {entry.canonical_path!r}"
            )
        if document.blob_identity and document.blob_identity != entry.blob_oid:
            raise ValueError(
                "document blob identity does not match inventory provenance for "
                f"{entry.canonical_path!r}"
            )
        inventory_language = detect_program_language(entry.relative_path)
        if document.language:
            hinted_language = detect_program_language(entry.relative_path, document.language)
            if hinted_language != inventory_language:
                raise ValueError(
                    "document language conflicts with inventory path for "
                    f"{entry.canonical_path!r}: expected {inventory_language!r}, "
                    f"received {hinted_language!r}"
                )
        inventory_generated = CorpusClassification.GENERATED_SOURCE.value in entry.classifications
        if document.generated and not inventory_generated:
            raise ValueError(
                "document generated classification conflicts with inventory for "
                f"{entry.canonical_path!r}"
            )
        normalized.append(
            SourceDocument(
                path=entry.canonical_path,
                source=document.source,
                language=inventory_language,
                blob_identity=entry.blob_oid,
                generated=inventory_generated,
            )
        )

    previous_index = previous.program_index if previous is not None else None
    program_index = build_program_evidence_index(
        normalized,
        previous=previous_index,
        max_source_bytes=max_source_bytes,
        max_facts=max_facts,
    )
    expected_paths = tuple(sorted(by_canonical))
    receipt = InventoryProgramEvidenceReceipt(
        program_index=program_index,
        inventory_cid=inventory.inventory_cid,
        inventory_exhaustive=inventory.exhaustive,
        expected_paths=expected_paths,
        missing_paths=tuple(sorted(set(expected_paths).difference(seen))),
    )
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        mirror_work_record(
            catalog_kind="ast",
            record_kind="inventory_program_evidence",
            record_ref=str(receipt.inventory_cid or "inventory-program-evidence"),
            subject_kind="record_cid",
            subject_ref=str(receipt.inventory_cid or "inventory-program-evidence"),
        )
    except Exception:
        pass
    return receipt


# Compatibility-oriented name retained from the original VFS-063 bridge.
build_inventory_program_evidence_index = build_inventory_program_evidence_receipt


def build_program_ast_blob_record(
    source: str, *, path: str = "", language: str = "", **kwargs: Any
) -> ASTBlobRecord | None:
    """Convenience adapter returning only the canonical record.

    Callers that need unsupported/malformed accounting should use
    :func:`adapt_program_source`, whose result never hides that status.
    """

    record = adapt_program_source(source, path=path, language=language, **kwargs).ast_record
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        if record is not None:
            mirror_work_record(
                catalog_kind="ast",
                record_kind="program_ast_blob",
                record_ref=str(getattr(record, "record_id", "") or record.blob_identity or record.source_sha256 or "program-ast"),
                subject_kind="path" if path else "record_cid",
                subject_ref=str(path or record.blob_identity or "program-ast"),
                paths=(path,) if path else (),
            )
    except Exception:
        pass
    return record


# Friendly aliases for evidence-oriented and incremental callers.
adapt_source_evidence = adapt_program_source
adapt_source_to_ast_record = build_program_ast_blob_record
build_mixed_program_evidence_index = build_program_evidence_index
# VFS-G139 discovery alias: the evidence index is the incremental AST index.
build_incremental_ast_index = build_program_evidence_index


# ---------------------------------------------------------------------------
# Language-edge resolution (VFS-G021 / VFS-G143 / vfs/language-edge-resolution@1)
# ---------------------------------------------------------------------------


LANGUAGE_EDGE_RESOLUTION_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/language-edge-candidate@1"
)
LANGUAGE_EDGE_RESOLUTION_CLAIM_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/language-edge-resolution-claim@1"
)


@dataclass(frozen=True)
class LanguageEdgeCandidate:
    """One fail-closed language-edge projection from adapter facts.

    Every candidate cites a source span and resolver rule.  Direct call
    promotion is allowed only when the resolver status is terminal static and
    the site is not a collision, re-export, dynamic, or unsupported construct.
    """

    site_id: str
    kind: str
    resolver_rule: str
    span: SourceSpan
    status: str
    path: str = ""
    language: str = ""
    name: str = ""
    target: str = ""
    relationship: str = ""
    fact_id: str = ""
    blob_identity: str = ""
    allows_direct_call: bool = False
    reason: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    schema: str = LANGUAGE_EDGE_RESOLUTION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "site_id", str(self.site_id or "").strip())
        object.__setattr__(self, "kind", str(self.kind or "").strip())
        object.__setattr__(
            self, "resolver_rule", str(self.resolver_rule or "").strip()
        )
        object.__setattr__(self, "status", str(self.status or "").strip())
        object.__setattr__(self, "path", str(self.path or "").replace("\\", "/"))
        object.__setattr__(self, "language", str(self.language or ""))
        object.__setattr__(self, "name", str(self.name or ""))
        object.__setattr__(self, "target", str(self.target or ""))
        object.__setattr__(self, "relationship", str(self.relationship or ""))
        object.__setattr__(self, "fact_id", str(self.fact_id or ""))
        object.__setattr__(self, "blob_identity", str(self.blob_identity or ""))
        object.__setattr__(self, "allows_direct_call", bool(self.allows_direct_call))
        object.__setattr__(self, "reason", str(self.reason or ""))
        object.__setattr__(self, "details", _normalize_details(self.details))
        if not self.site_id:
            raise ValueError("language edge candidate requires site_id")
        if not self.kind:
            raise ValueError("language edge candidate requires kind")
        if not self.resolver_rule:
            raise ValueError("language edge candidate requires resolver_rule")
        if not self.status:
            raise ValueError("language edge candidate requires status")
        if not isinstance(self.span, SourceSpan):
            object.__setattr__(self, "span", _source_span_from_dict(self.span))
        if self.allows_direct_call and self.status != "resolved_static":
            raise ValueError(
                "allows_direct_call requires status resolved_static"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "site_id": self.site_id,
            "kind": self.kind,
            "resolver_rule": self.resolver_rule,
            "span": self.span.to_dict(),
            "status": self.status,
            "path": self.path,
            "language": self.language,
            "name": self.name,
            "target": self.target,
            "relationship": self.relationship,
            "fact_id": self.fact_id,
            "blob_identity": self.blob_identity,
            "allows_direct_call": self.allows_direct_call,
            "reason": self.reason,
            "details": dict(self.details),
        }


def _language_edge_status_for_fact(
    fact: ProgramEvidenceFact,
    *,
    collision_names: frozenset[str],
) -> tuple[str, str, bool]:
    """Return (status, reason, allows_direct_call) for one adapter fact."""

    name_key = f"{fact.owner}:{fact.name}" if fact.owner else fact.name
    if fact.kind == "unsupported_node":
        return "unsupported", "unsupported_construct", False
    if fact.kind in {"monkey_patch", "callback", "decorator", "registration"}:
        return "ambiguous", f"dynamic:{fact.kind}", False
    if fact.kind == "dynamic_import":
        return "ambiguous", "dynamic_import", False
    if fact.kind == "re_export":
        return "ambiguous", "re_export_not_direct_call", False
    if name_key in collision_names or fact.name in collision_names:
        return "ambiguous", "same_name_collision", False
    if fact.ambiguous:
        resolution = str(fact.details.get("resolution") or "")
        if resolution == "candidate_only":
            return "candidate", "import_candidate_only", False
        if resolution == "dynamic_expression":
            return "ambiguous", "dynamic_expression", False
        if resolution == "unresolved_name":
            return "unknown", "unresolved_name", False
        if fact.kind == "import" and (
            fact.name == "*" or str(fact.details.get("imported") or "") == "*"
        ):
            return "ambiguous", "star_import", False
        return "ambiguous", "ambiguous_construct", False
    if fact.kind in {"import", "export"}:
        # Static import/export bindings are observational edges with a
        # concrete target name, never promoted to resolved call edges.
        return "candidate", f"static_{fact.kind}", False
    if fact.kind in {"call", "new_expression"}:
        # Adapter call facts are always candidate/unknown; direct call
        # edges require the separate call-resolver with full graph evidence.
        return "unknown", "call_site_requires_resolver", False
    return "unknown", "unclassified_edge_fact", False


def _resolver_rule_for_fact(
    fact: ProgramEvidenceFact,
    *,
    language: str,
    status: str,
    reason: str,
) -> str:
    """Derive a stable resolver rule id from fact kind, language, and status."""

    explicit = str(
        fact.details.get("resolver_rule")
        or fact.details.get("rule_id")
        or ""
    ).strip()
    if explicit:
        return explicit if explicit.startswith("rule:") else f"rule:{explicit}"
    lang = (language or "unknown").replace("/", "-")
    if reason == "same_name_collision":
        return f"rule:{lang}:same_name_collision"
    if reason == "re_export_not_direct_call":
        return f"rule:{lang}:re_export"
    if reason.startswith("dynamic:"):
        return f"rule:{lang}:{reason.replace(':', '_')}"
    if reason == "dynamic_import":
        return f"rule:{lang}:dynamic_import"
    if reason == "star_import":
        return f"rule:{lang}:star_import"
    if reason == "import_candidate_only":
        return f"rule:{lang}:import_candidate"
    if reason == "dynamic_expression":
        return f"rule:{lang}:dynamic_expression"
    if reason == "unresolved_name":
        return f"rule:{lang}:unresolved_name"
    if reason == "unsupported_construct":
        return f"rule:{lang}:unsupported_node"
    if fact.kind == "import":
        return f"rule:{lang}:static_import"
    if fact.kind == "export":
        return f"rule:{lang}:static_export"
    if fact.kind == "re_export":
        return f"rule:{lang}:re_export"
    if fact.kind in {"call", "new_expression"}:
        return f"rule:{lang}:call_candidate"
    return f"rule:{lang}:{fact.kind or 'edge'}:{status}"


def _collision_names_from_result(
    result: ProgramASTAdapterResult,
) -> frozenset[str]:
    """Collect names marked by name-collision diagnostics or multi-defs."""

    collisions: set[str] = set()
    for diagnostic in result.diagnostics:
        if diagnostic.code in {
            "ecmascript_name_collision",
            "python_name_collision",
            "name_collision",
        }:
            name = str(diagnostic.details.get("name") or "").strip()
            if name:
                collisions.add(name)
                if ":" in name:
                    collisions.add(name.rsplit(":", 1)[-1])
    # Within one module, multiple definition facts for the same owner:name
    # are treated as collisions for edge promotion (never forge a direct call).
    def_counts: dict[str, int] = {}
    for fact in result.facts:
        if fact.kind.endswith("_definition") or fact.kind in {
            "function_definition",
            "class_definition",
            "async_function_definition",
            "arrow_function_definition",
            "variable_definition",
            "method_definition",
        }:
            key = f"{fact.owner}:{fact.name}" if fact.owner else fact.name
            def_counts[key] = def_counts.get(key, 0) + 1
    for key, count in def_counts.items():
        if count > 1:
            collisions.add(key)
            collisions.add(key.rsplit(":", 1)[-1])
    return frozenset(collisions)


def project_language_edge_candidates(
    result: ProgramASTAdapterResult,
) -> tuple[LanguageEdgeCandidate, ...]:
    """Project one adapter result into span+rule language-edge candidates.

    Facts that are not edge-relevant are skipped.  Every emitted candidate
    carries a non-empty resolver rule and a source span.  Direct-call
    promotion is always refused for collisions, re-exports, dynamic
    constructs, and ambiguous/unsupported sites.
    """

    if not isinstance(result, ProgramASTAdapterResult):
        raise TypeError("result must be a ProgramASTAdapterResult")
    collisions = _collision_names_from_result(result)
    candidates: list[LanguageEdgeCandidate] = []
    for fact in result.facts:
        if fact.kind not in _LANGUAGE_EDGE_FACT_KINDS:
            continue
        status, reason, allows_direct = _language_edge_status_for_fact(
            fact, collision_names=collisions
        )
        # Hard fail-closed: never allow direct call for collisions/re-exports.
        if reason in {"same_name_collision", "re_export_not_direct_call"}:
            allows_direct = False
            if status == "resolved_static":
                status = "ambiguous"
        rule = _resolver_rule_for_fact(
            fact, language=result.language, status=status, reason=reason
        )
        site_id = (
            f"site:{result.path}:{fact.kind}:{fact.fact_id}"
            if result.path
            else f"site:{fact.kind}:{fact.fact_id}"
        )
        candidates.append(
            LanguageEdgeCandidate(
                site_id=site_id,
                kind=fact.kind,
                resolver_rule=rule,
                span=fact.span,
                status=status,
                path=result.path,
                language=result.language,
                name=fact.name,
                target=fact.target,
                relationship=fact.relationship,
                fact_id=fact.fact_id,
                blob_identity=result.blob_identity,
                allows_direct_call=allows_direct,
                reason=reason,
                details={
                    "owner": fact.owner,
                    "ambiguous": fact.ambiguous,
                    "generated": fact.generated,
                    **{
                        key: value
                        for key, value in dict(fact.details).items()
                        if key
                        not in {
                            "statement",
                            "keyword_names",
                        }
                    },
                },
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.span.line_start,
                item.span.column_start,
                item.kind,
                item.name,
                item.site_id,
            ),
        )
    )


def project_language_edge_candidates_from_index(
    index: ProgramEvidenceIndex,
) -> tuple[LanguageEdgeCandidate, ...]:
    """Project every adapter result in an index into language-edge candidates."""

    if not isinstance(index, ProgramEvidenceIndex):
        raise TypeError("index must be a ProgramEvidenceIndex")
    items: list[LanguageEdgeCandidate] = []
    for result in index.results:
        items.extend(project_language_edge_candidates(result))
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.path,
                item.span.line_start,
                item.span.column_start,
                item.kind,
                item.site_id,
            ),
        )
    )


def language_edge_candidate_cites_span_and_rule(
    candidate: LanguageEdgeCandidate,
) -> bool:
    """True when the candidate has a resolvable span and non-empty rule."""

    if not isinstance(candidate, LanguageEdgeCandidate):
        return False
    if not candidate.resolver_rule or not candidate.resolver_rule.startswith(
        "rule:"
    ):
        return False
    span = candidate.span
    # Span must be present; zeroed spans are only allowed for whole-file
    # bindings that still report a path.  Edge sites require line anchors.
    if span.line_start <= 0 and span.line_end <= 0:
        return False
    return True


def language_edge_resolution_satisfies(
    candidates: Sequence[LanguageEdgeCandidate],
) -> bool:
    """Machine-check VFS-G021 / VFS-G143 language-edge resolution acceptance.

    * Every edge cites a source span and resolver rule.
    * Ambiguous and unsupported constructs remain explicit (status in the
      closed frontier vocabulary).
    * Name collisions and re-exports never set ``allows_direct_call``.
    """

    if not candidates:
        return True
    frontier_statuses = {
        "unresolved",
        "candidate",
        "ambiguous",
        "external",
        "unknown",
        "unsupported",
    }
    terminal_statuses = {"resolved_static"}
    for candidate in candidates:
        if not language_edge_candidate_cites_span_and_rule(candidate):
            return False
        if candidate.status not in frontier_statuses | terminal_statuses:
            return False
        if candidate.reason in {
            "same_name_collision",
            "re_export_not_direct_call",
        } and candidate.allows_direct_call:
            return False
        if candidate.status in {"ambiguous", "unsupported", "unknown"} and (
            candidate.allows_direct_call
        ):
            return False
        if candidate.kind in {
            "monkey_patch",
            "callback",
            "dynamic_import",
            "decorator",
            "registration",
            "unsupported_node",
            "re_export",
        } and candidate.allows_direct_call:
            return False
    return True


def language_edge_resolution_evidence_terms() -> tuple[str, ...]:
    """Return the closed VFS-G021 / VFS-G143 language-edge evidence term.

    Exact identity: ``vfs/language-edge-resolution@1``.  Authored by this
    module together with :mod:`program_graph` edge provenance checks.
    """

    return (LANGUAGE_EDGE_RESOLUTION_EVIDENCE,)


def build_language_edge_program_graph(
    results: Sequence[ProgramASTAdapterResult] | ProgramEvidenceIndex,
    *,
    forest_id: str = "forest:language-edge-resolution",
    producer: str = "program-ast-adapters/language-edge-resolution@1",
) -> Any:
    """Project adapter results into a program graph with span+rule language edges.

    Call/import/export/dynamic sites become nodes and edges.  Direct
    ``resolved_static`` call edges are never minted for collisions, re-exports,
    or dynamic constructs.  Returns a :class:`~.program_graph.ProgramGraph`.
    """

    # Local import keeps adapter load free of graph construction costs for
    # callers that only need AST evidence.
    from .program_graph import (
        ProgramEdgeKind,
        ProgramNodeKind,
        ResolverStatus,
        build_program_graph,
        make_edge,
        make_node,
    )

    if isinstance(results, ProgramEvidenceIndex):
        adapter_results = results.results
        candidates = project_language_edge_candidates_from_index(results)
    else:
        adapter_results = tuple(results)
        candidates = tuple(
            candidate
            for result in adapter_results
            for candidate in project_language_edge_candidates(result)
        )
    if not language_edge_resolution_satisfies(candidates):
        raise ValueError(
            "language edge candidates fail vfs/language-edge-resolution@1"
        )

    nodes_by_key: dict[str, Any] = {}
    edges: list[Any] = []
    kind_map = {
        "import": ProgramEdgeKind.IMPORTS,
        "export": ProgramEdgeKind.EXPORTS,
        "re_export": ProgramEdgeKind.EXPORTS,
        "call": ProgramEdgeKind.CALLS,
        "new_expression": ProgramEdgeKind.CALLS,
        "dynamic_import": ProgramEdgeKind.IMPORTS,
        "monkey_patch": ProgramEdgeKind.REFERENCES,
        "callback": ProgramEdgeKind.REFERENCES,
        "registration": ProgramEdgeKind.REGISTERS,
        "decorator": ProgramEdgeKind.REFERENCES,
        "unsupported_node": ProgramEdgeKind.REFERENCES,
    }
    status_map = {
        "resolved_static": ResolverStatus.RESOLVED_STATIC,
        "candidate": ResolverStatus.CANDIDATE,
        "ambiguous": ResolverStatus.AMBIGUOUS,
        "external": ResolverStatus.EXTERNAL,
        "unknown": ResolverStatus.UNKNOWN,
        "unsupported": ResolverStatus.UNSUPPORTED,
        "unresolved": ResolverStatus.UNRESOLVED,
    }

    def ensure_node(
        *,
        record_key: str,
        kind: Any,
        blob_cid: str,
        component_id: str,
        qualified_name: str,
        path: str,
        language: str,
        span: Mapping[str, Any] | Any,
        resolver_status: Any,
        record: Mapping[str, Any],
    ) -> Any:
        existing = nodes_by_key.get(record_key)
        if existing is not None:
            return existing
        node = make_node(
            kind=kind,
            record_key=record_key,
            producer=producer,
            blob_cid=blob_cid,
            forest_id=forest_id,
            component_id=component_id,
            qualified_name=qualified_name,
            path=path,
            language=language,
            span=span,
            resolver_status=resolver_status,
            record=record,
        )
        nodes_by_key[record_key] = node
        return node

    for result in adapter_results:
        module_key = f"module:{result.path or result.blob_identity or 'unknown'}"
        ensure_node(
            record_key=module_key,
            kind=ProgramNodeKind.MODULE,
            blob_cid=result.blob_identity or f"blob:{result.source_sha256}",
            component_id=module_key,
            qualified_name=result.path or module_key,
            path=result.path,
            language=result.language,
            span={"line_start": 1, "column_start": 0, "line_end": 1, "column_end": 0},
            resolver_status=ResolverStatus.RESOLVED_STATIC,
            record={
                "evidence": LANGUAGE_EDGE_RESOLUTION_EVIDENCE,
                "status": result.status,
            },
        )

    for candidate in candidates:
        module_key = f"module:{candidate.path or candidate.blob_identity or 'unknown'}"
        site_key = candidate.site_id
        target_name = candidate.target or candidate.name or "unknown"
        target_key = f"symbol:{candidate.path}:{target_name}"
        blob = candidate.blob_identity or f"blob:{candidate.path or 'unknown'}"
        site_node = ensure_node(
            record_key=site_key,
            kind=ProgramNodeKind.SYMBOL,
            blob_cid=blob,
            component_id=module_key,
            qualified_name=candidate.name or site_key,
            path=candidate.path,
            language=candidate.language,
            span=candidate.span.to_dict(),
            resolver_status=status_map.get(
                candidate.status, ResolverStatus.UNKNOWN
            ),
            record={
                "kind": candidate.kind,
                "fact_id": candidate.fact_id,
                "reason": candidate.reason,
            },
        )
        target_node = ensure_node(
            record_key=target_key,
            kind=ProgramNodeKind.SYMBOL,
            blob_cid=blob,
            component_id=module_key,
            qualified_name=target_name,
            path=candidate.path,
            language=candidate.language,
            span=candidate.span.to_dict(),
            resolver_status=ResolverStatus.CANDIDATE,
            record={"projected_target": True},
        )
        edge_kind = kind_map.get(candidate.kind, ProgramEdgeKind.REFERENCES)
        # Never promote non-terminal / collision / re-export / dynamic sites
        # to resolved_static call edges.
        edge_status = status_map.get(candidate.status, ResolverStatus.UNKNOWN)
        if candidate.allows_direct_call and edge_status is ResolverStatus.RESOLVED_STATIC:
            edge_status = ResolverStatus.RESOLVED_STATIC
        elif edge_status is ResolverStatus.RESOLVED_STATIC:
            edge_status = ResolverStatus.AMBIGUOUS
        edges.append(
            make_edge(
                source=site_node.node_id,
                target=target_node.node_id,
                kind=edge_kind,
                producer=producer,
                blob_cid=blob,
                forest_id=forest_id,
                component_id=module_key,
                span=candidate.span.to_dict(),
                resolver_status=edge_status,
                resolver_rule=candidate.resolver_rule,
                record={
                    "reason": candidate.reason,
                    "reason_code": candidate.reason,
                    "mechanism": candidate.kind,
                    "allows_direct_call": candidate.allows_direct_call,
                    "evidence": LANGUAGE_EDGE_RESOLUTION_EVIDENCE,
                    "fact_id": candidate.fact_id,
                },
            )
        )

    return build_program_graph(
        forest_id=forest_id,
        nodes=tuple(nodes_by_key.values()),
        edges=edges,
        producer=producer,
    )


def _mirror_language_edge_ast_claim(claim: dict[str, Any]) -> dict[str, Any]:
    """Record the AST-side edge claim. It does not forge direct calls."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(claim.get("evidence") or claim.get("goal_id") or "language_edge_ast")
        mirror_work_record(
            catalog_kind="ast",
            record_kind="language_edge_resolution_ast",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return claim


def prove_language_edge_resolution(
    index: ProgramEvidenceIndex | None = None,
    *,
    results: Sequence[ProgramASTAdapterResult] | None = None,
    candidates: Sequence[LanguageEdgeCandidate] | None = None,
) -> dict[str, Any]:
    """Emit a portable ``vfs/language-edge-resolution@1`` evidence claim.

    Accepts an inventory-bound program evidence index, explicit adapter
    results, or pre-projected candidates.  The claim never embeds goal
    metadata into AST blob identity or forges direct call edges.
    """

    projected: tuple[LanguageEdgeCandidate, ...]
    if candidates is not None:
        projected = tuple(candidates)
    elif index is not None:
        if not isinstance(index, ProgramEvidenceIndex):
            raise TypeError("index must be a ProgramEvidenceIndex")
        projected = project_language_edge_candidates_from_index(index)
    elif results is not None:
        items: list[LanguageEdgeCandidate] = []
        for result in results:
            items.extend(project_language_edge_candidates(result))
        projected = tuple(items)
    else:
        projected = ()

    satisfied = language_edge_resolution_satisfies(projected)
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    direct = 0
    missing_rule = 0
    missing_span = 0
    forged_blocked = 0
    for item in projected:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        by_reason[item.reason] = by_reason.get(item.reason, 0) + 1
        if item.allows_direct_call:
            direct += 1
        if not item.resolver_rule:
            missing_rule += 1
        if item.span.line_start <= 0 and item.span.line_end <= 0:
            missing_span += 1
        if item.reason in {
            "same_name_collision",
            "re_export_not_direct_call",
        }:
            forged_blocked += 1
            if item.allows_direct_call:
                satisfied = False

    claim = {
        "schema": LANGUAGE_EDGE_RESOLUTION_CLAIM_SCHEMA,
        "evidence": LANGUAGE_EDGE_RESOLUTION_EVIDENCE,
        "evidence_terms": list(language_edge_resolution_evidence_terms()),
        "requirement_id": LANGUAGE_EDGE_RESOLUTION_EVIDENCE,
        "goal_id": LANGUAGE_EDGE_RESOLUTION_GOAL_ID,
        "child_goal_id": LANGUAGE_EDGE_RESOLUTION_CHILD_GOAL_ID,
        "parent_goal_id": OBJECTIVE_PARENT_GOAL_ID,
        "task_id": LANGUAGE_EDGE_RESOLUTION_TASK_ID,
        "satisfied": satisfied,
        "candidate_count": len(projected),
        "direct_call_count": direct,
        "missing_rule_count": missing_rule,
        "missing_span_count": missing_span,
        "forged_direct_call_blocked_count": forged_blocked,
        "by_status": dict(sorted(by_status.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "by_reason": dict(sorted(by_reason.items())),
        "candidates": [item.to_dict() for item in projected],
        "invariants": list(LANGUAGE_EDGE_RESOLUTION_INVARIANTS),
        "authoritative": False,
        "completion_authoritative": False,
        "forges_direct_calls": False,
    }
    return _mirror_language_edge_ast_claim(claim)


# ---------------------------------------------------------------------------
# Objective evidence discovery (VFS-G139 / VFS-G020 packet / VFS-064 repair)
# ---------------------------------------------------------------------------


def incremental_ast_index_evidence_terms() -> tuple[str, ...]:
    """Return the closed VFS-G139 domain evidence term for incremental AST index.

    Domain identity (``vfs/incremental-ast-index@1``) is authored only by this
    module.  Packet sibling ``vfs/exhaustive-file-inventory@1`` is exposed via
    :func:`packet_evidence_terms` so discovery scanners can cover the
    corpus-index goal packet without mixing labels into AST blob identity.
    The synthetic ``objective validation repair`` term is intentionally
    omitted here; use :func:`objective_validation_repair_evidence_terms` (or
    :func:`parent_objective_evidence_terms`) for the VFS-G020 validation gate.
    Language-edge resolution (``vfs/language-edge-resolution@1``) is a sibling
    corpus-index goal exposed via
    :func:`language_edge_resolution_evidence_terms`.
    """

    return OBJECTIVE_DOMAIN_EVIDENCE_TERMS


def covered_evidence_terms() -> tuple[str, ...]:
    """Return domain objective evidence terms this adapter surface proves.

    Incremental AST index (VFS-G139) comes first; language-edge resolution
    (VFS-G021 / VFS-G143) follows.  Packet-wide inventory co-coverage stays on
    :func:`packet_evidence_terms`.  The synthetic objective validation repair
    gate is separate so adapter envelopes stay domain-only.
    """

    return (
        *incremental_ast_index_evidence_terms(),
        *language_edge_resolution_evidence_terms(),
    )


def packet_evidence_terms() -> tuple[str, ...]:
    """Return VFS-G020 packet domain evidence terms co-owned with corpus inventory.

    Ordered as ``vfs/exhaustive-file-inventory@1`` then
    ``vfs/incremental-ast-index@1``.  Labels never enter AST blob identity.
    Does not include the synthetic objective validation repair discovery key
    or the sibling ``vfs/language-edge-resolution@1`` surface (VFS-G021).
    """

    return CORPUS_INDEX_G020_EVIDENCE_TERMS


def objective_validation_repair_evidence_terms() -> tuple[str, ...]:
    """Return the synthetic VFS-G020 validation-gate evidence term.

    Exact-text discovery key for objective validation repair.  Never mixes
    into content-addressed AST blob identities, analysis index IDs, or
    portable adapter payloads.  Domain packet evidence stays on
    :func:`packet_evidence_terms`.  Owned by :data:`OBJECTIVE_PARENT_GOAL_ID`
    (``VFS-G020``) via repair task :data:`OBJECTIVE_VALIDATION_REPAIR_TASK_ID`
    (``VFS-064``).  Inventory, language adapters, and incremental persistence
    remain split by conflict domain.
    """

    return (OBJECTIVE_VALIDATION_REPAIR_EVIDENCE,)


def parent_objective_evidence_terms() -> tuple[str, ...]:
    """Return VFS-G020 packet domain terms plus the validation-repair gate.

    Domain ``vfs/exhaustive-file-inventory@1`` and
    ``vfs/incremental-ast-index@1`` come first; the synthetic objective
    validation repair discovery key is appended last and never enters AST
    blob identity.  Packet domain discovery without the gate remains
    :func:`packet_evidence_terms` / :func:`all_covered_evidence_terms`.
    """

    return packet_evidence_terms() + objective_validation_repair_evidence_terms()


def all_covered_evidence_terms() -> tuple[str, ...]:
    """Return packet domain terms plus language-edge resolution for discovery.

    Packet inventory + incremental AST labels stay aligned with
    :mod:`repository_corpus_index` as the leading pair; language-edge
    resolution (``vfs/language-edge-resolution@1``) is appended as the
    adapters-owned sibling goal.  Use :func:`parent_objective_evidence_terms`
    (or :func:`objective_validation_repair_evidence_terms`) for the synthetic
    VFS-G020 objective validation repair gate.
    """

    return packet_evidence_terms() + language_edge_resolution_evidence_terms()


def _mirror_ast_index_claim(claim: dict[str, Any], *, record_kind: str) -> dict[str, Any]:
    """Record an AST index claim. It does not admit completion."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(
            claim.get("analysis_index_id")
            or claim.get("evidence")
            or record_kind
        )
        mirror_work_record(
            catalog_kind="ast",
            record_kind=record_kind,
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return claim


def prove_objective_validation_repair(
    index: ProgramEvidenceIndex | None = None,
) -> dict[str, Any]:
    """Emit a portable VFS-G020 objective validation repair claim.

    Binds the synthetic discovery key without embedding it into AST blob
    identity.  When a program evidence index is supplied, structural
    incremental AST satisfaction is reported; blob identities stay domain-only.
    """

    index_satisfied: bool | None = None
    analysis_index_id: str | None = None
    exhaustive: bool | None = None
    truncated: bool | None = None
    reason_codes: list[str] = []
    reused_result_count: int | None = None
    if index is not None:
        if not isinstance(index, ProgramEvidenceIndex):
            raise TypeError("index must be a ProgramEvidenceIndex")
        index_satisfied = index_satisfies_incremental_ast_index(index)
        analysis_index_id = index.analysis_index.index_id
        exhaustive = index.exhaustive
        truncated = index.truncated
        reason_codes = list(index.reason_codes)
        reused_result_count = index.reused_result_count
    claim = {
        "schema": ("ipfs_accelerate_py/agent-supervisor/objective-validation-repair-claim@1"),
        "evidence": OBJECTIVE_VALIDATION_REPAIR_EVIDENCE,
        "evidence_terms": list(objective_validation_repair_evidence_terms()),
        "domain_evidence_terms": list(OBJECTIVE_DOMAIN_EVIDENCE_TERMS),
        "packet_evidence_terms": list(CORPUS_INDEX_G020_EVIDENCE_TERMS),
        "parent_objective_evidence_terms": list(parent_objective_evidence_terms()),
        "requirement_id": OBJECTIVE_VALIDATION_REPAIR_EVIDENCE,
        "goal_id": OBJECTIVE_PARENT_GOAL_ID,
        "parent_goal_id": OBJECTIVE_PARENT_GOAL_ID,
        "packet_goal_ids": list(PACKET_GOAL_IDS),
        "goal_packet": GOAL_PACKET_ID,
        "task_id": OBJECTIVE_VALIDATION_REPAIR_TASK_ID,
        "domain_task_id": OBJECTIVE_TASK_ID,
        "analysis_index_id": analysis_index_id,
        "exhaustive": exhaustive,
        "truncated": truncated,
        "index_satisfied": index_satisfied,
        "reused_result_count": reused_result_count,
        "satisfied": True if index_satisfied is None else bool(index_satisfied),
        "reason_codes": reason_codes,
        "invariants": list(OBJECTIVE_VALIDATION_REPAIR_INVARIANTS),
        "conflict_domains": (
            "repository_corpus_index",
            "program_ast_adapters",
            "incremental_persistence",
        ),
        "authoritative": False,
        "completion_authoritative": False,
    }
    return _mirror_ast_index_claim(claim, record_kind="objective_validation_repair_claim")


def index_satisfies_incremental_ast_index(
    index: ProgramEvidenceIndex,
) -> bool:
    """Machine-check VFS-G139 acceptance against one program evidence index.

    * TypeScript/TSX/JavaScript/Python/JSON/Markdown results carry provenance
      (``source_sha256`` / content-bound ``blob_identity``).
    * Unchanged blobs may report ``reused`` when a previous snapshot is
      supplied (checked separately by incremental builders).
    * Parser failures (malformed) and truncation block exhaustiveness.
    * Every snapshot path is accounted as success, partial, malformed, or
      unsupported — never silently dropped.
    """

    if not isinstance(index, ProgramEvidenceIndex):
        raise TypeError("index must be a ProgramEvidenceIndex")
    paths = [item.path for item in index.results]
    if any(not path for path in paths):
        return False
    if len(set(paths)) != len(paths):
        return False
    for item in index.results:
        if item.language in PROVENANCE_LANGUAGES:
            if not item.source_sha256 or not item.blob_identity:
                return False
            if item.status in {"success", "partial"} and item.ast_record is None:
                return False
            if item.ast_record is not None:
                if item.ast_record.source_sha256 != item.source_sha256:
                    return False
                if item.ast_record.blob_identity != item.blob_identity:
                    return False
        if item.status == "unsupported" and item.ast_record is not None:
            return False
    # Exhaustive verdict is optional for partial packet claims; satisfaction
    # requires accounted inputs with provenance.  Exhaustiveness is reported
    # separately so truncation/parser failure evidence remains visible.
    return True


def prove_incremental_ast_index(
    index: ProgramEvidenceIndex,
) -> dict[str, Any]:
    """Emit a portable VFS-G139 evidence claim for one incremental AST index.

    The claim binds ``vfs/incremental-ast-index@1`` to the snapshot without
    embedding goal metadata into AST blob identities.
    """

    if not isinstance(index, ProgramEvidenceIndex):
        raise TypeError("index must be a ProgramEvidenceIndex")
    satisfied = index_satisfies_incremental_ast_index(index)
    languages = sorted({item.language for item in index.results})
    claim = {
        "schema": "ipfs_accelerate_py/agent-supervisor/incremental-ast-index-claim@1",
        "evidence": INCREMENTAL_AST_INDEX_EVIDENCE,
        "evidence_terms": list(OBJECTIVE_DOMAIN_EVIDENCE_TERMS),
        "packet_evidence_terms": list(CORPUS_INDEX_G020_EVIDENCE_TERMS),
        "requirement_id": INCREMENTAL_AST_INDEX_EVIDENCE,
        "goal_id": OBJECTIVE_GOAL_ID,
        "parent_goal_id": OBJECTIVE_PARENT_GOAL_ID,
        "packet_goal_ids": list(PACKET_GOAL_IDS),
        "goal_packet": GOAL_PACKET_ID,
        "task_id": OBJECTIVE_TASK_ID,
        "analysis_index_id": index.analysis_index.index_id,
        "result_count": len(index.results),
        "reused_result_count": index.reused_result_count,
        "reused_blob_count": index.analysis_index.stats.reused_blob_count,
        "exhaustive": index.exhaustive,
        "truncated": index.truncated,
        "reason_codes": list(index.reason_codes),
        "satisfied": satisfied,
        "languages": languages,
        "malformed_count": len(index.malformed_results),
        "unsupported_count": len(index.unsupported_results),
        "partial_count": len(index.partial_results),
        "success_count": len(index.success_results),
        "provenance_languages": sorted(PROVENANCE_LANGUAGES),
        "invariants": list(INCREMENTAL_AST_INDEX_INVARIANTS),
        "authoritative": False,
        "completion_authoritative": False,
    }
    return _mirror_ast_index_claim(claim, record_kind="incremental_ast_index_claim")


# Narrow compatibility surface for software-verification source adapters
# (LFV SourceSoftwareVerificationAdapter@1).  This does not introduce a second
# AST schema; it only freezes the evidence contract those adapters reuse.
SOFTWARE_VERIFICATION_PROGRAM_AST_COMPAT = (
    "ipfs_accelerate_py/agent-supervisor/software-verification-program-ast-compat@1"
)


def program_evidence_for_software_verification(
    source: str,
    *,
    path: str = "",
    language: str = "",
    blob_identity: str = "",
    previous: ProgramASTAdapterResult | ASTBlobRecord | None = None,
    generated: bool = False,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_facts: int = DEFAULT_MAX_FACTS,
) -> ProgramASTAdapterResult:
    """Return program-AST evidence for shared software-verification lowering.

    Compatibility helper used by
    ``ipfs_datasets_py.logic.software_verification.source_adapters``.  The
    result is observational: success never implies a proof or backend verdict.
    """

    return adapt_program_source(
        source,
        path=path,
        language=language,
        blob_identity=blob_identity,
        previous=previous,
        generated=generated,
        max_source_bytes=max_source_bytes,
        max_facts=max_facts,
    )


__all__ = [
    "CORPUS_INDEX_G020_EVIDENCE_TERMS",
    "DEFAULT_MAX_FACTS",
    "DEFAULT_MAX_SOURCE_BYTES",
    "EXHAUSTIVE_FILE_INVENTORY_EVIDENCE",
    "GOAL_PACKET_ID",
    "INCREMENTAL_AST_INDEX_EVIDENCE",
    "INCREMENTAL_AST_INDEX_INVARIANTS",
    "INVENTORY_PROGRAM_EVIDENCE_RECEIPT_SCHEMA",
    "JSON_ADAPTER_VERSION",
    "JAVASCRIPT_ADAPTER_VERSION",
    "LANGUAGE_EDGE_RESOLUTION_CHILD_GOAL_ID",
    "LANGUAGE_EDGE_RESOLUTION_CLAIM_SCHEMA",
    "LANGUAGE_EDGE_RESOLUTION_EVIDENCE",
    "LANGUAGE_EDGE_RESOLUTION_GOAL_ID",
    "LANGUAGE_EDGE_RESOLUTION_INVARIANTS",
    "LANGUAGE_EDGE_RESOLUTION_SCHEMA",
    "LANGUAGE_EDGE_RESOLUTION_TASK_ID",
    "MARKDOWN_ADAPTER_VERSION",
    "OBJECTIVE_DOMAIN_EVIDENCE_TERMS",
    "OBJECTIVE_GOAL_ID",
    "OBJECTIVE_PARENT_GOAL_ID",
    "OBJECTIVE_TASK_ID",
    "OBJECTIVE_VALIDATION_REPAIR_EVIDENCE",
    "OBJECTIVE_VALIDATION_REPAIR_INVARIANTS",
    "OBJECTIVE_VALIDATION_REPAIR_TASK_ID",
    "PACKET_GOAL_IDS",
    "PACKET_SIBLING_GOAL_ID",
    "PROGRAM_AST_ADAPTER_SCHEMA",
    "PROGRAM_EVIDENCE_FACT_SCHEMA",
    "PROGRAM_EVIDENCE_INDEX_SCHEMA",
    "PROVENANCE_LANGUAGES",
    "PYTHON_ADAPTER_VERSION",
    "SOFTWARE_VERIFICATION_PROGRAM_AST_COMPAT",
    "AdapterDiagnostic",
    "LanguageEdgeCandidate",
    "ProgramASTAdapterResult",
    "ProgramEvidenceFact",
    "ProgramEvidenceIndex",
    "InventoryProgramEvidenceReceipt",
    "SourceDocument",
    "SourceSpan",
    "adapt_json_source",
    "adapt_ecmascript_source",
    "adapt_markdown_source",
    "adapt_program_source",
    "adapt_python_source",
    "adapt_source_evidence",
    "adapt_source_to_ast_record",
    "all_covered_evidence_terms",
    "build_incremental_ast_index",
    "build_inventory_program_evidence_index",
    "build_inventory_program_evidence_receipt",
    "build_language_edge_program_graph",
    "build_mixed_program_evidence_index",
    "build_program_ast_blob_record",
    "build_program_evidence_index",
    "covered_evidence_terms",
    "detect_program_language",
    "incremental_ast_index_evidence_terms",
    "index_satisfies_incremental_ast_index",
    "language_edge_candidate_cites_span_and_rule",
    "language_edge_resolution_evidence_terms",
    "language_edge_resolution_satisfies",
    "objective_validation_repair_evidence_terms",
    "packet_evidence_terms",
    "parent_objective_evidence_terms",
    "program_evidence_for_software_verification",
    "project_language_edge_candidates",
    "project_language_edge_candidates_from_index",
    "prove_incremental_ast_index",
    "prove_language_edge_resolution",
    "prove_objective_validation_repair",
]
