"""Deterministic, incremental query index over canonical AST blob records.

This module intentionally implements no source parser.  Parsing, legacy-record
coercion, and the path-independent schema are owned by :mod:`conflict_graph`;
this module only attaches repository paths to those immutable
``ASTBlobRecord`` values and projects their facts into compact, bounded
evidence references.

Every build input is a complete current snapshot.  A previous index is only a
cache: records whose content identity is unchanged are reused, while evidence
from changed or removed paths is excluded and recorded as invalidated.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from ..core.conflict_graph import (
    ASTBlobRecord,
    coerce_ast_blob_record,
    index_ast_blob_records,
)


ANALYSIS_AST_INDEX_SCHEMA_VERSION = 1
ANALYSIS_AST_INDEX_SCHEMA = "ipfs_accelerate_py/agent-supervisor/analysis-ast-index@1"
DEFAULT_QUERY_MAX_RESULTS = 20
DEFAULT_QUERY_MAX_BYTES = 32_768
HARD_QUERY_MAX_RESULTS = 100
HARD_QUERY_MAX_BYTES = 1_048_576
MIN_QUERY_MAX_BYTES = 256

_PATH_FIELDS = ("path", "root_relative_path", "new_path", "file")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class AnalysisASTIndexError(ValueError):
    """Raised when AST index input is malformed or unsafe."""


class ASTEvidenceKind(str, Enum):
    """Kinds of compact evidence exposed by the query API."""

    PATH = "path"
    SYMBOL = "symbol"
    DEFINITION = "definition"
    IMPORT = "import"
    CALL = "call"
    REFERENCE = "reference"
    OBJECTIVE_TERM = "objective_term"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _identity(prefix: str, value: Any) -> str:
    return f"{prefix}:sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _repo_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        raise AnalysisASTIndexError("AST records require a repository path")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise AnalysisASTIndexError(f"repository path escapes its root: {value!r}")
    return path.as_posix()


def _module_name(path: str) -> str:
    value = path[:-3] if path.endswith(".py") else path
    parts = list(PurePosixPath(value).parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _tokens(value: str) -> tuple[str, ...]:
    """Return stable search terms, splitting separators and camel case."""

    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value))
    return tuple(word.casefold() for word in _WORD_RE.findall(expanded))


def _query_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, Mapping):
        values = value.keys()
    else:
        try:
            values = iter(value)
        except TypeError:
            values = (value,)
    return " ".join(str(item).strip() for item in values if str(item).strip())


@dataclass(frozen=True)
class QueryBounds:
    """Effective hard bounds for one query response."""

    max_results: int = DEFAULT_QUERY_MAX_RESULTS
    max_bytes: int = DEFAULT_QUERY_MAX_BYTES

    def __post_init__(self) -> None:
        if isinstance(self.max_results, bool) or int(self.max_results) < 1:
            raise AnalysisASTIndexError("max_results must be a positive integer")
        if isinstance(self.max_bytes, bool) or int(self.max_bytes) < MIN_QUERY_MAX_BYTES:
            raise AnalysisASTIndexError(f"max_bytes must be at least {MIN_QUERY_MAX_BYTES}")
        object.__setattr__(self, "max_results", min(int(self.max_results), HARD_QUERY_MAX_RESULTS))
        object.__setattr__(self, "max_bytes", min(int(self.max_bytes), HARD_QUERY_MAX_BYTES))


@dataclass(frozen=True)
class IndexedASTPath:
    """A repository path bound to one existing canonical AST record."""

    path: str
    ast_record: ASTBlobRecord

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _repo_path(self.path))
        if not isinstance(self.ast_record, ASTBlobRecord):
            raise AnalysisASTIndexError("indexed paths must contain canonical ASTBlobRecord values")

    @property
    def blob_identity(self) -> str:
        return self.ast_record.blob_identity

    @property
    def source_sha256(self) -> str:
        return self.ast_record.source_sha256

    @property
    def record_id(self) -> str:
        return self.ast_record.record_id

    @property
    def module(self) -> str:
        return _module_name(self.path)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "ast_record": self.ast_record.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IndexedASTPath":
        payload = value.get("ast_record")
        if not isinstance(payload, Mapping):
            raise AnalysisASTIndexError("indexed AST path is missing ast_record")
        return cls(
            path=str(value.get("path") or ""),
            ast_record=ASTBlobRecord.from_dict(payload),
        )


@dataclass(frozen=True)
class ASTBlobInvalidation:
    """Compact audit receipt for evidence removed from a former path."""

    path: str
    blob_identity: str
    source_sha256: str
    record_id: str
    reason: str
    replacement_blob_identity: str = ""
    replacement_record_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _repo_path(self.path))
        for name in (
            "blob_identity",
            "source_sha256",
            "record_id",
            "replacement_blob_identity",
            "replacement_record_id",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        reason = str(self.reason or "").strip()
        if reason not in {"blob_changed", "path_deleted"}:
            raise AnalysisASTIndexError(f"unsupported AST invalidation reason {reason!r}")
        if not self.record_id:
            raise AnalysisASTIndexError("AST invalidations require a record identity")
        object.__setattr__(self, "reason", reason)

    @property
    def invalidation_id(self) -> str:
        return _identity("ast-invalidation", self._content_dict())

    def _content_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "blob_identity": self.blob_identity,
            "source_sha256": self.source_sha256,
            "record_id": self.record_id,
            "reason": self.reason,
            "replacement_blob_identity": self.replacement_blob_identity,
            "replacement_record_id": self.replacement_record_id,
        }

    def to_dict(self) -> dict[str, str]:
        return {"invalidation_id": self.invalidation_id, **self._content_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ASTBlobInvalidation":
        result = cls(
            path=str(value.get("path") or ""),
            blob_identity=str(value.get("blob_identity") or ""),
            source_sha256=str(value.get("source_sha256") or ""),
            record_id=str(value.get("record_id") or ""),
            reason=str(value.get("reason") or ""),
            replacement_blob_identity=str(value.get("replacement_blob_identity") or ""),
            replacement_record_id=str(value.get("replacement_record_id") or ""),
        )
        claimed = str(value.get("invalidation_id") or "")
        if claimed and claimed != result.invalidation_id:
            raise AnalysisASTIndexError("AST invalidation identity does not match payload")
        return result


@dataclass(frozen=True)
class AnalysisASTIndexStats:
    scanned_path_count: int = 0
    indexed_blob_count: int = 0
    reused_blob_count: int = 0
    new_blob_count: int = 0
    changed_path_count: int = 0
    deleted_path_count: int = 0
    renamed_path_count: int = 0
    invalidated_blob_count: int = 0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = int(getattr(self, name))
            if value < 0:
                raise AnalysisASTIndexError(f"{name} must not be negative")
            object.__setattr__(self, name, value)

    @property
    def cache_hit_ratio(self) -> float:
        return self.reused_blob_count / self.indexed_blob_count if self.indexed_blob_count else 0.0

    @property
    def reused_record_count(self) -> int:
        return self.reused_blob_count

    @property
    def invalidated_record_count(self) -> int:
        return self.invalidated_blob_count

    @property
    def scanned_record_count(self) -> int:
        return self.scanned_path_count

    @property
    def changed_blob_count(self) -> int:
        return self.changed_path_count

    @property
    def deleted_blob_count(self) -> int:
        return self.deleted_path_count

    @property
    def renamed_blob_count(self) -> int:
        return self.renamed_path_count

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "cache_hit_ratio": self.cache_hit_ratio}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalysisASTIndexStats":
        return cls(**{name: int(value.get(name, 0)) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class ASTEvidenceReference:
    """One compact source/blob-addressed query hit."""

    kind: ASTEvidenceKind
    path: str
    blob_identity: str
    source_sha256: str
    record_id: str
    value: str
    symbol: str = ""
    target: str = ""
    relationship: str = ""
    line_start: int = 0
    line_end: int = 0
    symbol_hash: str = ""
    score: int = 0
    ranking_explanations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ASTEvidenceKind(self.kind))
        object.__setattr__(self, "path", _repo_path(self.path))
        for name in (
            "blob_identity",
            "source_sha256",
            "record_id",
            "value",
            "symbol",
            "target",
            "relationship",
            "symbol_hash",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        object.__setattr__(self, "line_start", max(0, int(self.line_start)))
        object.__setattr__(self, "line_end", max(0, int(self.line_end)))
        object.__setattr__(self, "score", max(0, int(self.score)))
        object.__setattr__(
            self,
            "ranking_explanations",
            tuple(str(item) for item in self.ranking_explanations if str(item)),
        )
        if not self.record_id or not self.value:
            raise AnalysisASTIndexError("AST evidence references require record_id and value")

    @property
    def ranking_explanation(self) -> str:
        return "; ".join(self.ranking_explanations)

    @property
    def source_identity(self) -> str:
        return self.source_sha256

    @property
    def blob_id(self) -> str:
        return self.blob_identity

    @property
    def source_hash(self) -> str:
        return self.source_sha256

    @property
    def evidence_id(self) -> str:
        return _identity(
            "ast-evidence",
            {"kind": self.kind.value, **self._content_dict()},
        )

    @property
    def explanation(self) -> str:
        return self.ranking_explanation

    def with_ranking(self, score: int, explanations: Sequence[str]) -> "ASTEvidenceReference":
        return ASTEvidenceReference(
            **{
                **self._content_dict(),
                "kind": self.kind,
                "score": score,
                "ranking_explanations": tuple(explanations),
            }
        )

    def _content_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "blob_identity": self.blob_identity,
            "source_sha256": self.source_sha256,
            "record_id": self.record_id,
            "value": self.value,
            "symbol": self.symbol,
            "target": self.target,
            "relationship": self.relationship,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "symbol_hash": self.symbol_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            **self._content_dict(),
            "score": self.score,
            "ranking_explanations": list(self.ranking_explanations),
        }


@dataclass(frozen=True)
class ASTQueryTruncation:
    """Explicit count and byte truncation metadata."""

    truncated: bool
    result_limit_reached: bool
    byte_limit_reached: bool
    total_matches: int
    returned_results: int
    omitted_results: int
    max_results: int
    max_bytes: int
    encoded_bytes: int = 0

    @property
    def is_truncated(self) -> bool:
        return self.truncated

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ASTEvidenceQueryResult:
    """A deterministic response whose compact JSON fits the requested bounds."""

    query_kind: ASTEvidenceKind
    query: str
    evidence: tuple[ASTEvidenceReference, ...]
    truncation: ASTQueryTruncation

    @property
    def results(self) -> tuple[ASTEvidenceReference, ...]:
        return self.evidence

    @property
    def matches(self) -> tuple[ASTEvidenceReference, ...]:
        return self.evidence

    @property
    def items(self) -> tuple[ASTEvidenceReference, ...]:
        return self.evidence

    @property
    def truncated(self) -> bool:
        return self.truncation.truncated

    @property
    def total_matches(self) -> int:
        return self.truncation.total_matches

    @property
    def byte_count(self) -> int:
        return self.truncation.encoded_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_kind": self.query_kind.value,
            "query": self.query,
            "evidence": [item.to_dict() for item in self.evidence],
            "truncation": self.truncation.to_dict(),
        }

    def to_json(self, *, indent: int | None = None) -> str:
        if indent is None:
            return _canonical_json(self.to_dict())
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)


def _reference_sort_key(item: ASTEvidenceReference) -> tuple[Any, ...]:
    return (
        -item.score,
        item.path,
        item.kind.value,
        item.symbol,
        item.target,
        item.value,
        item.record_id,
    )


def _rank(query: str, values: Iterable[str]) -> tuple[int, tuple[str, ...]]:
    normalized = query.casefold().strip()
    query_tokens = _tokens(query)
    candidates = tuple(str(value) for value in values if str(value))
    if not normalized:
        return 1, ("all_entries",)

    score = 0
    reasons: list[str] = []
    lowered = tuple(value.casefold() for value in candidates)
    if normalized in lowered:
        score = 100
        reasons.append("exact_match")
    elif any(value.rsplit(".", 1)[-1] == normalized for value in lowered):
        score = 90
        reasons.append("exact_leaf_match")
    candidate_tokens = {token for value in candidates for token in _tokens(value)}
    overlap = tuple(sorted(set(query_tokens).intersection(candidate_tokens)))
    if query_tokens and overlap:
        coverage = len(overlap) / len(set(query_tokens))
        token_score = 50 + int(20 * coverage)
        if token_score > score:
            score = token_score
        reasons.append(f"term_overlap:{len(overlap)}/{len(set(query_tokens))}")
    return score, tuple(dict.fromkeys(reasons))


def _query_result(
    kind: ASTEvidenceKind,
    query: str,
    ranked: Sequence[ASTEvidenceReference],
    bounds: QueryBounds,
) -> ASTEvidenceQueryResult:
    total = len(ranked)
    count_limited = total > bounds.max_results
    candidates = list(ranked[: bounds.max_results])

    def make(
        evidence: Sequence[ASTEvidenceReference],
        *,
        byte_limited: bool,
        encoded_bytes: int = 0,
    ) -> ASTEvidenceQueryResult:
        omitted = total - len(evidence)
        truncation = ASTQueryTruncation(
            truncated=omitted > 0,
            result_limit_reached=count_limited,
            byte_limit_reached=byte_limited,
            total_matches=total,
            returned_results=len(evidence),
            omitted_results=omitted,
            max_results=bounds.max_results,
            max_bytes=bounds.max_bytes,
            encoded_bytes=encoded_bytes,
        )
        return ASTEvidenceQueryResult(
            query_kind=kind,
            query=query,
            evidence=tuple(evidence),
            truncation=truncation,
        )

    # Add evidence in rank order.  Recompute the final envelope at each step so
    # identities, explanations, metadata, and UTF-8 widths all count.
    accepted: list[ASTEvidenceReference] = []
    byte_limited = False
    for candidate in candidates:
        probe = make((*accepted, candidate), byte_limited=False)
        if len(probe.to_json().encode("utf-8")) > bounds.max_bytes:
            byte_limited = True
            break
        accepted.append(candidate)
    if len(accepted) < len(candidates):
        byte_limited = True

    def finalized(
        evidence: Sequence[ASTEvidenceReference],
        limited: bool,
    ) -> ASTEvidenceQueryResult:
        result = make(evidence, byte_limited=limited)
        for _ in range(8):
            size = len(result.to_json().encode("utf-8"))
            updated = make(evidence, byte_limited=limited, encoded_bytes=size)
            if updated.truncation.encoded_bytes == result.truncation.encoded_bytes:
                return updated
            result = updated
        return result

    # encoded_bytes and byte_limit_reached are serialized too.  If those final
    # fields cross the ceiling, remove only as many lowest-ranked hits as are
    # necessary instead of discarding the whole response.
    result = finalized(accepted, byte_limited)
    while accepted and len(result.to_json().encode("utf-8")) > bounds.max_bytes:
        accepted.pop()
        byte_limited = True
        result = finalized(accepted, byte_limited)

    # The fixed envelope can exceed the bound for a sufficiently long query.
    if len(result.to_json().encode("utf-8")) > bounds.max_bytes:
        raise AnalysisASTIndexError(
            "max_bytes is too small for query metadata; shorten the query or increase max_bytes"
        )
    return result


@dataclass(frozen=True)
class AnalysisASTIndex:
    """Immutable current AST evidence snapshot and incremental cache metadata."""

    path_records: tuple[IndexedASTPath, ...]
    invalidations: tuple[ASTBlobInvalidation, ...] = ()
    stats: AnalysisASTIndexStats = field(default_factory=AnalysisASTIndexStats)
    schema_version: int = ANALYSIS_AST_INDEX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if int(self.schema_version) != ANALYSIS_AST_INDEX_SCHEMA_VERSION:
            raise AnalysisASTIndexError(
                f"unsupported analysis AST index schema version {self.schema_version}"
            )
        records = tuple(sorted(self.path_records, key=lambda item: item.path))
        if len({item.path for item in records}) != len(records):
            raise AnalysisASTIndexError("AST index paths must be unique")
        object.__setattr__(self, "path_records", records)
        by_id = {item.invalidation_id: item for item in self.invalidations}
        object.__setattr__(
            self,
            "invalidations",
            tuple(sorted(by_id.values(), key=lambda item: item.invalidation_id)),
        )
        object.__setattr__(self, "schema_version", int(self.schema_version))

    @property
    def index_id(self) -> str:
        # Cache statistics and transition history do not alter current
        # evidence identity.  Cold and warm builds of one snapshot agree.
        return _identity(
            "analysis-ast-index",
            {
                "schema": ANALYSIS_AST_INDEX_SCHEMA,
                "schema_version": self.schema_version,
                "path_records": [item.to_dict() for item in self.path_records],
            },
        )

    @property
    def records(self) -> tuple[IndexedASTPath, ...]:
        return self.path_records

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.path_records)

    @property
    def ast_blob_records(self) -> tuple[ASTBlobRecord, ...]:
        by_id = {item.record_id: item.ast_record for item in self.path_records}
        return tuple(by_id[key] for key in sorted(by_id))

    @property
    def blob_records(self) -> tuple[ASTBlobRecord, ...]:
        return self.ast_blob_records

    @property
    def active_blob_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({item.blob_identity for item in self.path_records if item.blob_identity})
        )

    @property
    def invalidated_blob_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({item.blob_identity for item in self.invalidations if item.blob_identity})
        )

    def record_for_path(self, path: str) -> IndexedASTPath | None:
        normalized = _repo_path(path)
        return next((item for item in self.path_records if item.path == normalized), None)

    lookup_path = record_for_path

    def _base_reference(
        self,
        indexed: IndexedASTPath,
        kind: ASTEvidenceKind,
        value: str,
        **fields: Any,
    ) -> ASTEvidenceReference:
        return ASTEvidenceReference(
            kind=kind,
            path=indexed.path,
            blob_identity=indexed.blob_identity,
            source_sha256=indexed.source_sha256,
            record_id=indexed.record_id,
            value=value,
            **fields,
        )

    def _path_references(self) -> tuple[ASTEvidenceReference, ...]:
        return tuple(
            self._base_reference(item, ASTEvidenceKind.PATH, item.path)
            for item in self.path_records
        )

    def _definition_references(
        self, *, kind: ASTEvidenceKind = ASTEvidenceKind.DEFINITION
    ) -> tuple[ASTEvidenceReference, ...]:
        result: list[ASTEvidenceReference] = []
        for item in self.path_records:
            record = item.ast_record
            for symbol in record.qualified_symbols:
                start, end = record.symbol_lines.get(symbol, (0, 0))
                qualified = f"{item.module}.{symbol}" if item.module else symbol
                result.append(
                    self._base_reference(
                        item,
                        kind,
                        qualified,
                        symbol=symbol,
                        target=qualified,
                        relationship="defines",
                        line_start=start,
                        line_end=end,
                        symbol_hash=record.symbol_hashes.get(symbol, ""),
                    )
                )
        return tuple(result)

    def _import_references(
        self, *, kind: ASTEvidenceKind = ASTEvidenceKind.IMPORT
    ) -> tuple[ASTEvidenceReference, ...]:
        result: list[ASTEvidenceReference] = []
        for item in self.path_records:
            for imported in item.ast_record.imports:
                result.append(
                    self._base_reference(
                        item,
                        kind,
                        imported,
                        target=imported,
                        relationship="imports",
                    )
                )
        return tuple(result)

    def _call_references(
        self, *, kind: ASTEvidenceKind = ASTEvidenceKind.CALL
    ) -> tuple[ASTEvidenceReference, ...]:
        result: list[ASTEvidenceReference] = []
        for item in self.path_records:
            for call in item.ast_record.calls:
                owner, separator, callee = call.partition("->")
                result.append(
                    self._base_reference(
                        item,
                        kind,
                        call,
                        symbol=owner if separator else "",
                        target=callee if separator else call,
                        relationship="calls",
                    )
                )
        return tuple(result)

    def _supplemental_references(self) -> tuple[ASTEvidenceReference, ...]:
        """Project remaining canonical facts for objective-term retrieval."""

        result: list[ASTEvidenceReference] = []
        for item in self.path_records:
            for interface in item.ast_record.interfaces:
                symbol = interface.split(":", 1)[0].split("(", 1)[0]
                result.append(
                    self._base_reference(
                        item,
                        ASTEvidenceKind.REFERENCE,
                        interface,
                        symbol=symbol,
                        target=interface,
                        relationship="interface",
                    )
                )
            for transition in item.ast_record.state_transitions:
                owner = transition.split(":", 1)[0]
                result.append(
                    self._base_reference(
                        item,
                        ASTEvidenceKind.REFERENCE,
                        transition,
                        symbol=owner,
                        target=transition,
                        relationship="state_transition",
                    )
                )
        return tuple(result)

    def _run_query(
        self,
        kind: ASTEvidenceKind,
        query: Any,
        references: Iterable[ASTEvidenceReference],
        *,
        max_results: int,
        max_bytes: int,
    ) -> ASTEvidenceQueryResult:
        text = _query_text(query)
        bounds = QueryBounds(max_results=max_results, max_bytes=max_bytes)
        ranked: list[ASTEvidenceReference] = []
        for reference in references:
            score, reasons = _rank(
                text,
                (
                    reference.value,
                    reference.path,
                    reference.symbol,
                    reference.target,
                    reference.relationship,
                ),
            )
            if score:
                ranked.append(reference.with_ranking(score, reasons))
        ranked.sort(key=_reference_sort_key)
        return _query_result(kind, text, ranked, bounds)

    def query_paths(
        self,
        query: Any = "",
        *,
        max_results: int = DEFAULT_QUERY_MAX_RESULTS,
        max_bytes: int = DEFAULT_QUERY_MAX_BYTES,
    ) -> ASTEvidenceQueryResult:
        return self._run_query(
            ASTEvidenceKind.PATH,
            query,
            self._path_references(),
            max_results=max_results,
            max_bytes=max_bytes,
        )

    def query_symbols(
        self,
        query: Any = "",
        *,
        max_results: int = DEFAULT_QUERY_MAX_RESULTS,
        max_bytes: int = DEFAULT_QUERY_MAX_BYTES,
    ) -> ASTEvidenceQueryResult:
        return self._run_query(
            ASTEvidenceKind.SYMBOL,
            query,
            self._definition_references(kind=ASTEvidenceKind.SYMBOL),
            max_results=max_results,
            max_bytes=max_bytes,
        )

    def query_definitions(
        self,
        query: Any = "",
        *,
        max_results: int = DEFAULT_QUERY_MAX_RESULTS,
        max_bytes: int = DEFAULT_QUERY_MAX_BYTES,
    ) -> ASTEvidenceQueryResult:
        return self._run_query(
            ASTEvidenceKind.DEFINITION,
            query,
            self._definition_references(),
            max_results=max_results,
            max_bytes=max_bytes,
        )

    def query_imports(
        self,
        query: Any = "",
        *,
        max_results: int = DEFAULT_QUERY_MAX_RESULTS,
        max_bytes: int = DEFAULT_QUERY_MAX_BYTES,
    ) -> ASTEvidenceQueryResult:
        return self._run_query(
            ASTEvidenceKind.IMPORT,
            query,
            self._import_references(),
            max_results=max_results,
            max_bytes=max_bytes,
        )

    def query_calls(
        self,
        query: Any = "",
        *,
        max_results: int = DEFAULT_QUERY_MAX_RESULTS,
        max_bytes: int = DEFAULT_QUERY_MAX_BYTES,
    ) -> ASTEvidenceQueryResult:
        return self._run_query(
            ASTEvidenceKind.CALL,
            query,
            self._call_references(),
            max_results=max_results,
            max_bytes=max_bytes,
        )

    def query_references(
        self,
        query: Any = "",
        *,
        max_results: int = DEFAULT_QUERY_MAX_RESULTS,
        max_bytes: int = DEFAULT_QUERY_MAX_BYTES,
    ) -> ASTEvidenceQueryResult:
        references = (
            *self._import_references(kind=ASTEvidenceKind.REFERENCE),
            *self._call_references(kind=ASTEvidenceKind.REFERENCE),
        )
        return self._run_query(
            ASTEvidenceKind.REFERENCE,
            query,
            references,
            max_results=max_results,
            max_bytes=max_bytes,
        )

    def query_objective_terms(
        self,
        query: Any,
        *,
        max_results: int = DEFAULT_QUERY_MAX_RESULTS,
        max_bytes: int = DEFAULT_QUERY_MAX_BYTES,
    ) -> ASTEvidenceQueryResult:
        references = (
            *self._path_references(),
            *self._definition_references(),
            *self._import_references(),
            *self._call_references(),
            *self._supplemental_references(),
        )
        return self._run_query(
            ASTEvidenceKind.OBJECTIVE_TERM,
            query,
            references,
            max_results=max_results,
            max_bytes=max_bytes,
        )

    def query(
        self,
        kind: ASTEvidenceKind | str,
        query: Any = "",
        *,
        max_results: int = DEFAULT_QUERY_MAX_RESULTS,
        max_bytes: int = DEFAULT_QUERY_MAX_BYTES,
    ) -> ASTEvidenceQueryResult:
        normalized = ASTEvidenceKind(kind)
        methods = {
            ASTEvidenceKind.PATH: self.query_paths,
            ASTEvidenceKind.SYMBOL: self.query_symbols,
            ASTEvidenceKind.DEFINITION: self.query_definitions,
            ASTEvidenceKind.IMPORT: self.query_imports,
            ASTEvidenceKind.CALL: self.query_calls,
            ASTEvidenceKind.REFERENCE: self.query_references,
            ASTEvidenceKind.OBJECTIVE_TERM: self.query_objective_terms,
        }
        return methods[normalized](query, max_results=max_results, max_bytes=max_bytes)

    # Readable compatibility spellings for callers that use lookup/search.
    lookup_paths = query_paths
    lookup_path_evidence = query_paths
    lookup_symbols = query_symbols
    lookup_definitions = query_definitions
    lookup_imports = query_imports
    lookup_calls = query_calls
    lookup_references = query_references
    query_path = query_paths
    query_symbol = query_symbols
    query_definition = query_definitions
    query_import = query_imports
    query_call = query_calls
    query_reference = query_references
    query_objective_term = query_objective_terms
    search_objective_terms = query_objective_terms
    search = query

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ANALYSIS_AST_INDEX_SCHEMA,
            "schema_version": self.schema_version,
            "index_id": self.index_id,
            "path_records": [item.to_dict() for item in self.path_records],
            "invalidations": [item.to_dict() for item in self.invalidations],
            "stats": self.stats.to_dict(),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalysisASTIndex":
        schema = value.get("schema")
        if schema not in (None, "", ANALYSIS_AST_INDEX_SCHEMA):
            raise AnalysisASTIndexError(f"unsupported analysis AST index schema {schema!r}")
        result = cls(
            path_records=tuple(
                IndexedASTPath.from_dict(item) for item in value.get("path_records", ())
            ),
            invalidations=tuple(
                ASTBlobInvalidation.from_dict(item) for item in value.get("invalidations", ())
            ),
            stats=AnalysisASTIndexStats.from_dict(value.get("stats") or {}),
            schema_version=int(value.get("schema_version", ANALYSIS_AST_INDEX_SCHEMA_VERSION)),
        )
        claimed = str(value.get("index_id") or "")
        if claimed and claimed != result.index_id:
            raise AnalysisASTIndexError("analysis AST index identity does not match payload")
        return result

    @classmethod
    def from_json(cls, value: str | bytes) -> "AnalysisASTIndex":
        payload = json.loads(value)
        if not isinstance(payload, Mapping):
            raise AnalysisASTIndexError("analysis AST index JSON must contain an object")
        return cls.from_dict(payload)


def _path_from_mapping(value: Mapping[str, Any]) -> str:
    for name in _PATH_FIELDS:
        if value.get(name) not in (None, ""):
            return str(value[name])
    return ""


def _coerce_path_record(value: Any) -> IndexedASTPath:
    if isinstance(value, IndexedASTPath):
        return value
    if (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 2
    ):
        path, raw_record = value
    elif isinstance(value, Mapping):
        path = _path_from_mapping(value)
        raw_record = (
            value.get("ast_record") or value.get("record") or value.get("blob_record") or value
        )
    else:
        raise AnalysisASTIndexError(
            "AST inputs require a repository path in a path/record pair or path-bearing mapping"
        )
    record = coerce_ast_blob_record(raw_record)
    if record is None:
        raise AnalysisASTIndexError(f"could not coerce canonical AST record for path {path!r}")
    if not record.blob_identity or not record.source_sha256:
        raise AnalysisASTIndexError(
            f"canonical AST record for path {path!r} requires blob and source identities"
        )
    if isinstance(raw_record, Mapping):
        claimed = str(raw_record.get("record_id") or "")
        if claimed.startswith("ast-sha256:") and claimed != record.record_id:
            raise AnalysisASTIndexError(
                f"canonical AST record identity does not match payload for path {path!r}"
            )
    return IndexedASTPath(path=str(path), ast_record=record)


def _expand_inputs(values: Any) -> tuple[Any, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, Mapping):
        # A single canonical/path-bearing record.
        if _path_from_mapping(values) or any(
            name in values
            for name in (
                "ast_record",
                "record",
                "blob_record",
                "blob_identity",
                "source_sha256",
            )
        ):
            return (values,)
        # Convenient {path: ASTBlobRecord} snapshot.
        return tuple((path, record) for path, record in values.items())
    if isinstance(values, (str, bytes, bytearray)):
        raise AnalysisASTIndexError("AST index inputs must not be text")
    return tuple(values)


def build_analysis_ast_index(
    records: Iterable[Any] | Mapping[str, Any] = (),
    *,
    ast_records: Iterable[Any] | Mapping[str, Any] = (),
    ast_blob_records: Iterable[Any] | Mapping[str, Any] = (),
    path_records: Iterable[Any] | Mapping[str, Any] = (),
    previous: AnalysisASTIndex | Mapping[str, Any] | None = None,
    previous_index: AnalysisASTIndex | Mapping[str, Any] | None = None,
    exhaustive: bool = False,
) -> AnalysisASTIndex:
    """Build a complete current snapshot, reusing unchanged canonical records.

    Inputs must associate every ``ASTBlobRecord`` with a repository path,
    either via a path-bearing mapping, ``(path, record)`` pair, or a
    ``{path: record}`` mapping.  No source is read and no parser callback is
    accepted by design.
    """

    if previous is not None and previous_index is not None:
        raise AnalysisASTIndexError("provide only one of previous or previous_index")
    if previous is None:
        previous = previous_index
    if previous is not None and not isinstance(previous, AnalysisASTIndex):
        previous = AnalysisASTIndex.from_dict(previous)
    prior = None if exhaustive else previous

    raw = (
        *_expand_inputs(records),
        *_expand_inputs(ast_records),
        *_expand_inputs(ast_blob_records),
        *_expand_inputs(path_records),
    )
    normalized = [_coerce_path_record(item) for item in raw]
    normalized.sort(key=lambda item: (item.path, item.record_id))
    if len({item.path for item in normalized}) != len(normalized):
        raise AnalysisASTIndexError("AST snapshot contains duplicate paths")

    prior_records = prior.path_records if prior is not None else ()
    # Required canonical cache helper: it indexes by blob, source, and record
    # identity without introducing a parallel content schema.
    cached = index_ast_blob_records(item.ast_record for item in prior_records)
    prior_ids = {item.record_id for item in prior_records}
    current: list[IndexedASTPath] = []
    for item in normalized:
        candidate = (
            cached.get(item.record_id)
            or cached.get(item.blob_identity)
            or cached.get(item.source_sha256)
        )
        if candidate is not None and candidate.record_id == item.record_id:
            current.append(IndexedASTPath(item.path, candidate))
        else:
            current.append(item)

    prior_by_path = {item.path: item for item in prior_records}
    current_by_path = {item.path: item for item in current}
    current_paths_by_id: dict[str, set[str]] = {}
    for item in current:
        current_paths_by_id.setdefault(item.record_id, set()).add(item.path)
    prior_paths = set(prior_by_path)
    rename_targets_by_id = {
        record_id: sorted(paths - prior_paths) for record_id, paths in current_paths_by_id.items()
    }

    changed = 0
    deleted = 0
    renamed = 0
    additions: list[ASTBlobInvalidation] = []
    for path, old in sorted(prior_by_path.items()):
        replacement = current_by_path.get(path)
        if replacement is not None:
            if replacement.record_id == old.record_id:
                continue
            changed += 1
            additions.append(
                ASTBlobInvalidation(
                    path=path,
                    blob_identity=old.blob_identity,
                    source_sha256=old.source_sha256,
                    record_id=old.record_id,
                    reason="blob_changed",
                    replacement_blob_identity=replacement.blob_identity,
                    replacement_record_id=replacement.record_id,
                )
            )
        elif rename_targets_by_id.get(old.record_id):
            # The immutable parse is reusable; only its former path projection
            # disappeared.  This is a rename, not a blob invalidation.
            rename_targets_by_id[old.record_id].pop(0)
            renamed += 1
        else:
            deleted += 1
            additions.append(
                ASTBlobInvalidation(
                    path=path,
                    blob_identity=old.blob_identity,
                    source_sha256=old.source_sha256,
                    record_id=old.record_id,
                    reason="path_deleted",
                )
            )

    unique_current_ids = {item.record_id for item in current}
    all_invalidations = (
        *(prior.invalidations if prior is not None else ()),
        *additions,
    )
    stats = AnalysisASTIndexStats(
        scanned_path_count=len(current),
        indexed_blob_count=len(unique_current_ids),
        reused_blob_count=len(unique_current_ids.intersection(prior_ids)),
        new_blob_count=len(unique_current_ids - prior_ids),
        changed_path_count=changed,
        deleted_path_count=deleted,
        renamed_path_count=renamed,
        invalidated_blob_count=len({item.record_id for item in additions}),
    )
    index = AnalysisASTIndex(
        path_records=tuple(current),
        invalidations=tuple(all_invalidations),
        stats=stats,
    )
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        mirror_work_record(
            catalog_kind="ast",
            record_kind="ast",
            record_ref=index.index_id,
            subject_kind="record_cid",
            subject_ref=index.index_id,
            paths=index.paths,
        )
    except Exception:
        pass
    return index


# Concise aliases keep the standalone tranche friendly to both analysis and
# evidence-oriented callers without exporting through agent_supervisor.__init__.
ASTEvidenceIndex = AnalysisASTIndex
AnalysisASTEvidenceIndex = AnalysisASTIndex
ASTIndexStats = AnalysisASTIndexStats
build_ast_evidence_index = build_analysis_ast_index
build_incremental_ast_index = build_analysis_ast_index
build_ast_index = build_analysis_ast_index


__all__ = [
    "ANALYSIS_AST_INDEX_SCHEMA",
    "ANALYSIS_AST_INDEX_SCHEMA_VERSION",
    "ASTBlobInvalidation",
    "ASTEvidenceIndex",
    "ASTEvidenceKind",
    "ASTEvidenceQueryResult",
    "ASTEvidenceReference",
    "ASTIndexStats",
    "ASTQueryTruncation",
    "AnalysisASTEvidenceIndex",
    "AnalysisASTIndex",
    "AnalysisASTIndexError",
    "AnalysisASTIndexStats",
    "DEFAULT_QUERY_MAX_BYTES",
    "DEFAULT_QUERY_MAX_RESULTS",
    "HARD_QUERY_MAX_BYTES",
    "HARD_QUERY_MAX_RESULTS",
    "IndexedASTPath",
    "QueryBounds",
    "build_analysis_ast_index",
    "build_ast_evidence_index",
    "build_ast_index",
    "build_incremental_ast_index",
]
