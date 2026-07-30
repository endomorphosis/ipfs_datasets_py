"""Corpus differential and migration verification reports (KGP-028).

Produces revision-bound count, schema, checksum, provenance, entity/edge, and
golden-query differentials between a baseline (legacy reader / source snapshot)
and a candidate (adapter / migrated snapshot).

Design rules (normative for this module):

* Reports are **read-only** and **content-addressed**; mismatches cannot be
  auto-waived. Only explicitly declared :class:`ExpectedDifference` entries may
  classify a divergence as expected.
* **Sample** and **full** modes: sample compares a bounded entity/edge subset
  plus all counts/schema/checksum/provenance/golden queries; full compares every
  entity and edge.
* Unexplained missing or extra entities, edges, or golden-query results cause
  the report to **fail**.
* Expected **ordering** and **precision** differences must be classified
  explicitly (``expected_ordering`` / ``expected_precision``).
* Every unexpected mismatch retains **bounded evidence** sufficient to
  reproduce the mismatch (path, ids, clipped baseline/candidate values).

This module is deliberately free of adapter imports so it can compare any
corpus that can materialize a :class:`CorpusSnapshot`.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Iterable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

REPORT_SCHEMA_VERSION: Final = "kg-corpus-differential-report/v1"
MULTI_REPORT_SCHEMA_VERSION: Final = "kg-multi-corpus-differential-report/v1"
SNAPSHOT_SCHEMA_VERSION: Final = "kg-corpus-snapshot/v1"
CANONICAL_JSON_PROFILE: Final = "kg-canonical-json-v1"

KNOWN_CORPORA: Final = frozenset(
    {
        "cvefixes",
        "skillcenter",
        "two_eleven",
        "code_evidence",
    }
)

DEFAULT_MAX_EVIDENCE_ITEMS: Final = 64
DEFAULT_MAX_EVIDENCE_BYTES: Final = 8_192
DEFAULT_MAX_SAMPLE_ENTITIES: Final = 256
DEFAULT_MAX_SAMPLE_EDGES: Final = 512
DEFAULT_PRECISION_ATOL: Final = 1e-9
DEFAULT_PRECISION_RTOL: Final = 1e-9
DEFAULT_RESULT_ID_KEYS: Final = (
    "id",
    "entity_id",
    "node_id",
    "node_cid",
    "entry_cid",
    "doc_id",
    "cid",
    "key",
)


class DiffMode(str, Enum):
    """Verification breadth."""

    SAMPLE = "sample"
    FULL = "full"


class DifferenceKind(str, Enum):
    """What aspect of the corpus diverged."""

    COUNT = "count"
    SCHEMA = "schema"
    CHECKSUM = "checksum"
    PROVENANCE = "provenance"
    ENTITY = "entity"
    EDGE = "edge"
    GOLDEN_QUERY = "golden_query"
    REVISION = "revision"
    CORPUS = "corpus"


class DifferenceClassification(str, Enum):
    """How a divergence is classified for gating."""

    MATCH = "match"
    EXPECTED_ORDERING = "expected_ordering"
    EXPECTED_PRECISION = "expected_precision"
    EXPECTED_DECLARED = "expected_declared"
    MISSING = "missing"
    EXTRA = "extra"
    VALUE_MISMATCH = "value_mismatch"
    UNEXPECTED = "unexpected"


_EXPECTED_CLASSIFICATIONS: Final = frozenset(
    {
        DifferenceClassification.EXPECTED_ORDERING,
        DifferenceClassification.EXPECTED_PRECISION,
        DifferenceClassification.EXPECTED_DECLARED,
        DifferenceClassification.MATCH,
    }
)

_FAILING_CLASSIFICATIONS: Final = frozenset(
    {
        DifferenceClassification.MISSING,
        DifferenceClassification.EXTRA,
        DifferenceClassification.VALUE_MISMATCH,
        DifferenceClassification.UNEXPECTED,
    }
)


class DifferentialVerificationError(Exception):
    """Raised when a differential report fails closed."""

    def __init__(
        self,
        message: str,
        *,
        report: Optional["DifferentialReport"] = None,
    ) -> None:
        super().__init__(message)
        self.report = report


# ---------------------------------------------------------------------------
# Canonical serialization helpers
# ---------------------------------------------------------------------------


def _is_json_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def canonicalize(value: Any) -> Any:
    """Return a JSON-safe, deterministically ordered structure."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(k): canonicalize(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, set):
        items = [canonicalize(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize *value* as canonical UTF-8 JSON."""

    return json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def content_address(value: Any) -> str:
    """SHA-256 hex digest of the canonical JSON encoding of *value*."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _clip_evidence(value: Any, *, max_bytes: int) -> Any:
    """Clip a value so its canonical encoding stays within *max_bytes*."""

    canon = canonicalize(value)
    raw = canonical_json_bytes(canon)
    if len(raw) <= max_bytes:
        return canon
    # Prefer a structured truncation marker over partial JSON.
    summary: dict[str, Any] = {
        "_truncated": True,
        "_original_bytes": len(raw),
        "_max_bytes": max_bytes,
        "_type": type(value).__name__,
    }
    if isinstance(value, Mapping):
        summary["_keys"] = sorted(str(k) for k in value.keys())[:32]
        summary["_key_count"] = len(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        summary["_length"] = len(value)
        head = [canonicalize(item) for item in list(value)[:8]]
        head_bytes = canonical_json_bytes(head)
        if len(head_bytes) <= max_bytes // 2:
            summary["_head"] = head
    elif isinstance(value, str):
        keep = max(16, max_bytes // 4)
        summary["_prefix"] = value[:keep]
        summary["_length"] = len(value)
    else:
        text = str(value)
        summary["_repr_prefix"] = text[: max(16, max_bytes // 4)]
    return summary


def _stable_id(record: Mapping[str, Any], *, fallback_prefix: str, index: int) -> str:
    """Extract a stable identity from a node/edge/result record."""

    for key in DEFAULT_RESULT_ID_KEYS:
        if key in record and record[key] is not None:
            return str(record[key])
    # Composite fallbacks for edges.
    src = record.get("source") or record.get("from") or record.get("src")
    dst = record.get("target") or record.get("to") or record.get("dst")
    kind = record.get("type") or record.get("edge_type") or record.get("kind")
    if src is not None and dst is not None:
        return f"{kind or 'edge'}:{src}->{dst}"
    return f"{fallback_prefix}:{index}:{content_address(record)[:16]}"


def _floats_close(
    left: float,
    right: float,
    *,
    atol: float,
    rtol: float,
) -> bool:
    if math.isnan(left) and math.isnan(right):
        return True
    if math.isinf(left) or math.isinf(right):
        return left == right
    return abs(left - right) <= max(atol, rtol * max(abs(left), abs(right)))


def _values_equal(
    left: Any,
    right: Any,
    *,
    atol: float,
    rtol: float,
    ignore_order: bool = False,
) -> bool:
    """Structural equality with optional multiset comparison and float tolerance."""

    if isinstance(left, float) and isinstance(right, float):
        return _floats_close(left, right, atol=atol, rtol=rtol)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return _floats_close(float(left), float(right), atol=atol, rtol=rtol)
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left.keys()) != set(right.keys()):
            return False
        return all(
            _values_equal(
                left[k],
                right[k],
                atol=atol,
                rtol=rtol,
                ignore_order=ignore_order,
            )
            for k in left
        )
    if (
        isinstance(left, Sequence)
        and isinstance(right, Sequence)
        and not isinstance(left, (str, bytes))
        and not isinstance(right, (str, bytes))
    ):
        if ignore_order:
            if len(left) != len(right):
                return False
            # Multiset equality via canonical digests (order-insensitive).
            left_keys = sorted(content_address(item) for item in left)
            right_keys = sorted(content_address(item) for item in right)
            if left_keys != right_keys:
                # Fall back to float-tolerant pairwise matching for score lists.
                remaining = list(right)
                for item in left:
                    matched_idx = None
                    for idx, candidate in enumerate(remaining):
                        if _values_equal(
                            item,
                            candidate,
                            atol=atol,
                            rtol=rtol,
                            ignore_order=True,
                        ):
                            matched_idx = idx
                            break
                    if matched_idx is None:
                        return False
                    remaining.pop(matched_idx)
                return True
            return True
        if len(left) != len(right):
            return False
        return all(
            _values_equal(
                a,
                b,
                atol=atol,
                rtol=rtol,
                ignore_order=False,
            )
            for a, b in zip(left, right)
        )
    return left == right


def _is_precision_only_diff(
    left: Any,
    right: Any,
    *,
    atol: float,
    rtol: float,
) -> bool:
    """True when structures match except for float precision within tolerance."""

    if _values_equal(left, right, atol=0.0, rtol=0.0):
        return False
    return _values_equal(left, right, atol=atol, rtol=rtol)


def _is_ordering_only_diff(
    left: Any,
    right: Any,
    *,
    atol: float,
    rtol: float,
) -> bool:
    """True when sequences match as multisets but differ in order."""

    if not (
        isinstance(left, Sequence)
        and isinstance(right, Sequence)
        and not isinstance(left, (str, bytes))
        and not isinstance(right, (str, bytes))
    ):
        return False
    if _values_equal(left, right, atol=atol, rtol=rtol, ignore_order=False):
        return False
    return _values_equal(left, right, atol=atol, rtol=rtol, ignore_order=True)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedDifference:
    """An explicitly declared, non-auto-waived expected divergence.

    Conflict policy: mismatches cannot be auto-waived. Callers must declare
    each expected ordering/precision/schema drift with a path and reason.
    """

    kind: DifferenceKind
    classification: DifferenceClassification
    path: str
    reason: str
    corpus_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.classification not in _EXPECTED_CLASSIFICATIONS - {
            DifferenceClassification.MATCH
        }:
            # Only expected_* classifications are valid for declarations.
            if self.classification not in {
                DifferenceClassification.EXPECTED_ORDERING,
                DifferenceClassification.EXPECTED_PRECISION,
                DifferenceClassification.EXPECTED_DECLARED,
            }:
                raise ValueError(
                    "ExpectedDifference.classification must be "
                    "expected_ordering, expected_precision, or expected_declared; "
                    f"got {self.classification!r}"
                )
        if not self.path:
            raise ValueError("ExpectedDifference.path must be non-empty")
        if not self.reason:
            raise ValueError("ExpectedDifference.reason must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "classification": self.classification.value,
            "path": self.path,
            "reason": self.reason,
            "corpus_id": self.corpus_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExpectedDifference":
        return cls(
            kind=DifferenceKind(str(data["kind"])),
            classification=DifferenceClassification(str(data["classification"])),
            path=str(data["path"]),
            reason=str(data["reason"]),
            corpus_id=(
                str(data["corpus_id"]) if data.get("corpus_id") is not None else None
            ),
        )


@dataclass
class MismatchEvidence:
    """Bounded evidence retained so a mismatch can be reproduced offline."""

    path: str
    kind: DifferenceKind
    classification: DifferenceClassification
    baseline: Any = None
    candidate: Any = None
    entity_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    query_name: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind.value,
            "classification": self.classification.value,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "entity_ids": list(self.entity_ids),
            "edge_ids": list(self.edge_ids),
            "query_name": self.query_name,
            "notes": list(self.notes),
        }


@dataclass
class SectionDiff:
    """Diff summary for one comparison section."""

    name: str
    matched: bool
    missing_keys: list[str] = field(default_factory=list)
    extra_keys: list[str] = field(default_factory=list)
    changed_keys: list[str] = field(default_factory=list)
    expected_classifications: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "matched": self.matched,
            "missing_keys": list(self.missing_keys),
            "extra_keys": list(self.extra_keys),
            "changed_keys": list(self.changed_keys),
            "expected_classifications": list(self.expected_classifications),
            "details": canonicalize(self.details),
        }


@dataclass
class CorpusSnapshot:
    """Revision-bound, content-addressable view of one corpus state.

    Adapters and tests materialize this from validation receipts, fixtures, or
    golden-query results. The verifier never mutates snapshots.
    """

    corpus_id: str
    revision: str
    counts: dict[str, int] = field(default_factory=dict)
    schema: dict[str, Any] = field(default_factory=dict)
    checksums: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    golden_queries: dict[str, list[Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.corpus_id:
            raise ValueError("corpus_id is required")
        if not self.revision:
            raise ValueError("revision is required (revision-bound snapshots only)")
        # Normalize counts to int.
        self.counts = {str(k): int(v) for k, v in self.counts.items()}
        self.checksums = {str(k): str(v) for k, v in self.checksums.items()}
        self.entities = [dict(item) for item in self.entities]
        self.edges = [dict(item) for item in self.edges]
        self.golden_queries = {
            str(k): list(v) for k, v in self.golden_queries.items()
        }

    @property
    def entity_index(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for idx, entity in enumerate(self.entities):
            eid = _stable_id(entity, fallback_prefix="entity", index=idx)
            index[eid] = entity
        return index

    @property
    def edge_index(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for idx, edge in enumerate(self.edges):
            eid = _stable_id(edge, fallback_prefix="edge", index=idx)
            index[eid] = edge
        return index

    def fingerprint(self) -> str:
        """Content address of the full snapshot payload."""

        return content_address(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SNAPSHOT_SCHEMA_VERSION,
            "corpus_id": self.corpus_id,
            "revision": self.revision,
            "counts": dict(self.counts),
            "schema_payload": canonicalize(self.schema),
            "checksums": dict(self.checksums),
            "provenance": canonicalize(self.provenance),
            "entities": canonicalize(self.entities),
            "edges": canonicalize(self.edges),
            "golden_queries": canonicalize(self.golden_queries),
            "metadata": canonicalize(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CorpusSnapshot":
        schema_payload = data.get("schema_payload")
        if schema_payload is None:
            schema_payload = data.get("schema")
            if isinstance(schema_payload, str):
                # Distinguish report schema version strings from payload maps.
                schema_payload = {}
        return cls(
            corpus_id=str(data["corpus_id"]),
            revision=str(data["revision"]),
            counts=dict(data.get("counts") or {}),
            schema=dict(schema_payload or {}),
            checksums=dict(data.get("checksums") or {}),
            provenance=dict(data.get("provenance") or {}),
            entities=list(data.get("entities") or []),
            edges=list(data.get("edges") or []),
            golden_queries=dict(data.get("golden_queries") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_validation_receipt(
        cls,
        *,
        corpus_id: str,
        revision: str,
        receipt: Mapping[str, Any],
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        edges: Optional[Sequence[Mapping[str, Any]]] = None,
        golden_queries: Optional[Mapping[str, Sequence[Any]]] = None,
        checksums: Optional[Mapping[str, str]] = None,
        schema: Optional[Mapping[str, Any]] = None,
        provenance: Optional[Mapping[str, Any]] = None,
        counts: Optional[Mapping[str, int]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "CorpusSnapshot":
        """Build a snapshot from a corpus adapter validation receipt.

        Pulls common nested keys (``counts``, ``provenance``, ``manifest``)
        used by CVEfixes / SkillCenter / 211 / code-evidence receipts.
        """

        receipt = dict(receipt)
        derived_counts: dict[str, int] = {}
        if counts is not None:
            derived_counts.update({str(k): int(v) for k, v in counts.items()})
        else:
            for key in ("counts",):
                block = receipt.get(key)
                if isinstance(block, Mapping):
                    for ck, cv in block.items():
                        if isinstance(cv, (int, float)) and not isinstance(cv, bool):
                            derived_counts[str(ck)] = int(cv)
            manifest = receipt.get("manifest")
            if isinstance(manifest, Mapping):
                m_counts = manifest.get("counts")
                if isinstance(m_counts, Mapping):
                    for ck, cv in m_counts.items():
                        if isinstance(cv, (int, float)) and not isinstance(cv, bool):
                            derived_counts[str(ck)] = int(cv)

        derived_provenance = dict(provenance or {})
        if not derived_provenance:
            prov = receipt.get("provenance")
            if isinstance(prov, Mapping):
                derived_provenance = dict(prov)

        derived_schema = dict(schema or {})
        if not derived_schema:
            if "schema" in receipt and isinstance(receipt["schema"], str):
                derived_schema["receipt_schema"] = receipt["schema"]
            manifest = receipt.get("manifest")
            if isinstance(manifest, Mapping):
                if "schema_version" in manifest:
                    derived_schema["schema_version"] = manifest["schema_version"]
                if "primary_key" in manifest:
                    derived_schema["primary_key"] = manifest["primary_key"]
            if "kinds" in (receipt.get("shards") or {}):
                kinds = receipt["shards"]["kinds"]
                if isinstance(kinds, Mapping):
                    derived_schema["shard_kinds"] = sorted(str(k) for k in kinds.keys())

        derived_checksums: dict[str, str] = dict(checksums or {})
        if not derived_checksums:
            shards = receipt.get("shards")
            if isinstance(shards, Mapping):
                # Prefer explicit digest maps when present.
                digests = shards.get("digests") or shards.get("checksums")
                if isinstance(digests, Mapping):
                    derived_checksums = {
                        str(k): str(v) for k, v in digests.items()
                    }

        return cls(
            corpus_id=corpus_id,
            revision=revision,
            counts=derived_counts,
            schema=derived_schema,
            checksums=derived_checksums,
            provenance=derived_provenance,
            entities=[dict(e) for e in (entities or [])],
            edges=[dict(e) for e in (edges or [])],
            golden_queries={
                str(k): list(v) for k, v in (golden_queries or {}).items()
            },
            metadata={
                "source": "validation_receipt",
                "receipt_schema": receipt.get("schema"),
                **dict(metadata or {}),
            },
        )


@dataclass
class DifferentialReport:
    """Content-addressed differential report for one corpus pair."""

    corpus_id: str
    mode: DiffMode
    baseline_revision: str
    candidate_revision: str
    passed: bool
    count_diff: SectionDiff
    schema_diff: SectionDiff
    checksum_diff: SectionDiff
    provenance_diff: SectionDiff
    entity_diff: SectionDiff
    edge_diff: SectionDiff
    golden_query_diff: SectionDiff
    expected_differences: list[ExpectedDifference] = field(default_factory=list)
    unexpected_mismatches: list[MismatchEvidence] = field(default_factory=list)
    evidence: list[MismatchEvidence] = field(default_factory=list)
    baseline_fingerprint: str = ""
    candidate_fingerprint: str = ""
    report_digest: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": REPORT_SCHEMA_VERSION,
            "canonical_json_profile": CANONICAL_JSON_PROFILE,
            "corpus_id": self.corpus_id,
            "mode": self.mode.value,
            "baseline_revision": self.baseline_revision,
            "candidate_revision": self.candidate_revision,
            "passed": self.passed,
            "baseline_fingerprint": self.baseline_fingerprint,
            "candidate_fingerprint": self.candidate_fingerprint,
            "count_diff": self.count_diff.to_dict(),
            "schema_diff": self.schema_diff.to_dict(),
            "checksum_diff": self.checksum_diff.to_dict(),
            "provenance_diff": self.provenance_diff.to_dict(),
            "entity_diff": self.entity_diff.to_dict(),
            "edge_diff": self.edge_diff.to_dict(),
            "golden_query_diff": self.golden_query_diff.to_dict(),
            "expected_differences": [e.to_dict() for e in self.expected_differences],
            "unexpected_mismatches": [
                m.to_dict() for m in self.unexpected_mismatches
            ],
            "evidence": [m.to_dict() for m in self.evidence],
            "metadata": canonicalize(self.metadata),
        }
        # Digest excludes itself so the report is content-addressed.
        if not self.report_digest:
            self.report_digest = content_address(payload)
        payload["report_digest"] = self.report_digest
        return payload

    def raise_if_failed(self) -> None:
        if self.passed:
            return
        unexpected = len(self.unexpected_mismatches)
        raise DifferentialVerificationError(
            f"corpus differential failed for {self.corpus_id!r} "
            f"(mode={self.mode.value}, unexpected={unexpected}, "
            f"digest={self.report_digest or content_address(self.to_dict())})",
            report=self,
        )


@dataclass
class MultiCorpusDifferentialReport:
    """Aggregate report covering every corpus under comparison."""

    mode: DiffMode
    reports: list[DifferentialReport] = field(default_factory=list)
    passed: bool = True
    report_digest: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": MULTI_REPORT_SCHEMA_VERSION,
            "mode": self.mode.value,
            "passed": self.passed,
            "corpus_ids": [r.corpus_id for r in self.reports],
            "reports": [r.to_dict() for r in self.reports],
            "metadata": canonicalize(self.metadata),
        }
        if not self.report_digest:
            self.report_digest = content_address(
                {
                    "schema": MULTI_REPORT_SCHEMA_VERSION,
                    "mode": self.mode.value,
                    "passed": self.passed,
                    "reports": [
                        {
                            "corpus_id": r.corpus_id,
                            "report_digest": r.report_digest
                            or content_address(r.to_dict()),
                            "passed": r.passed,
                        }
                        for r in self.reports
                    ],
                }
            )
        payload["report_digest"] = self.report_digest
        return payload

    def raise_if_failed(self) -> None:
        if self.passed:
            return
        failed = [r.corpus_id for r in self.reports if not r.passed]
        raise DifferentialVerificationError(
            f"multi-corpus differential failed for: {', '.join(failed)}",
            report=None,
        )


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


class CorpusDifferentialVerifier:
    """Compare baseline vs candidate corpus snapshots.

    Usage::

        verifier = CorpusDifferentialVerifier(mode=DiffMode.SAMPLE)
        report = verifier.compare(baseline, candidate)
        report.raise_if_failed()

    Expected ordering/precision differences must be declared explicitly via
    ``expected_differences``; undeclared diffs fail the report.
    """

    def __init__(
        self,
        *,
        mode: DiffMode | str = DiffMode.FULL,
        expected_differences: Optional[Sequence[ExpectedDifference]] = None,
        max_evidence_items: int = DEFAULT_MAX_EVIDENCE_ITEMS,
        max_evidence_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES,
        max_sample_entities: int = DEFAULT_MAX_SAMPLE_ENTITIES,
        max_sample_edges: int = DEFAULT_MAX_SAMPLE_EDGES,
        sample_entity_ids: Optional[Sequence[str]] = None,
        sample_edge_ids: Optional[Sequence[str]] = None,
        precision_atol: float = DEFAULT_PRECISION_ATOL,
        precision_rtol: float = DEFAULT_PRECISION_RTOL,
        require_known_corpus: bool = False,
    ) -> None:
        if isinstance(mode, str):
            mode = DiffMode(mode)
        if mode not in (DiffMode.SAMPLE, DiffMode.FULL):
            raise ValueError(f"unsupported DiffMode: {mode!r}")
        if max_evidence_items < 1:
            raise ValueError("max_evidence_items must be >= 1")
        if max_evidence_bytes < 64:
            raise ValueError("max_evidence_bytes must be >= 64")
        self.mode = mode
        self.expected_differences = list(expected_differences or [])
        self.max_evidence_items = max_evidence_items
        self.max_evidence_bytes = max_evidence_bytes
        self.max_sample_entities = max_sample_entities
        self.max_sample_edges = max_sample_edges
        self.sample_entity_ids = (
            set(sample_entity_ids) if sample_entity_ids is not None else None
        )
        self.sample_edge_ids = (
            set(sample_edge_ids) if sample_edge_ids is not None else None
        )
        self.precision_atol = float(precision_atol)
        self.precision_rtol = float(precision_rtol)
        self.require_known_corpus = require_known_corpus

    # -- public API ---------------------------------------------------------

    def compare(
        self,
        baseline: CorpusSnapshot,
        candidate: CorpusSnapshot,
    ) -> DifferentialReport:
        """Produce a revision-bound differential report for one corpus pair."""

        if baseline.corpus_id != candidate.corpus_id:
            raise DifferentialVerificationError(
                f"corpus_id mismatch: baseline={baseline.corpus_id!r} "
                f"candidate={candidate.corpus_id!r}"
            )
        if self.require_known_corpus and baseline.corpus_id not in KNOWN_CORPORA:
            raise DifferentialVerificationError(
                f"unknown corpus_id {baseline.corpus_id!r}; known={sorted(KNOWN_CORPORA)}"
            )

        evidence: list[MismatchEvidence] = []
        unexpected: list[MismatchEvidence] = []
        declared = [
            d
            for d in self.expected_differences
            if d.corpus_id is None or d.corpus_id == baseline.corpus_id
        ]

        count_diff = self._diff_mapping_section(
            name="counts",
            kind=DifferenceKind.COUNT,
            baseline_map={k: v for k, v in baseline.counts.items()},
            candidate_map={k: v for k, v in candidate.counts.items()},
            path_prefix="counts",
            declared=declared,
            evidence=evidence,
            unexpected=unexpected,
        )
        schema_diff = self._diff_mapping_section(
            name="schema",
            kind=DifferenceKind.SCHEMA,
            baseline_map=dict(baseline.schema),
            candidate_map=dict(candidate.schema),
            path_prefix="schema",
            declared=declared,
            evidence=evidence,
            unexpected=unexpected,
        )
        checksum_diff = self._diff_mapping_section(
            name="checksums",
            kind=DifferenceKind.CHECKSUM,
            baseline_map=dict(baseline.checksums),
            candidate_map=dict(candidate.checksums),
            path_prefix="checksums",
            declared=declared,
            evidence=evidence,
            unexpected=unexpected,
        )
        provenance_diff = self._diff_mapping_section(
            name="provenance",
            kind=DifferenceKind.PROVENANCE,
            baseline_map=dict(baseline.provenance),
            candidate_map=dict(candidate.provenance),
            path_prefix="provenance",
            declared=declared,
            evidence=evidence,
            unexpected=unexpected,
        )
        entity_diff = self._diff_record_index(
            name="entities",
            kind=DifferenceKind.ENTITY,
            baseline_index=baseline.entity_index,
            candidate_index=candidate.entity_index,
            path_prefix="entities",
            declared=declared,
            evidence=evidence,
            unexpected=unexpected,
            sample_ids=self.sample_entity_ids,
            max_sample=self.max_sample_entities,
            id_field="entity_ids",
        )
        edge_diff = self._diff_record_index(
            name="edges",
            kind=DifferenceKind.EDGE,
            baseline_index=baseline.edge_index,
            candidate_index=candidate.edge_index,
            path_prefix="edges",
            declared=declared,
            evidence=evidence,
            unexpected=unexpected,
            sample_ids=self.sample_edge_ids,
            max_sample=self.max_sample_edges,
            id_field="edge_ids",
        )
        golden_query_diff = self._diff_golden_queries(
            baseline.golden_queries,
            candidate.golden_queries,
            declared=declared,
            evidence=evidence,
            unexpected=unexpected,
        )

        # Revision binding: revisions are recorded always; mismatch is unexpected
        # unless explicitly declared on path "revision".
        if baseline.revision != candidate.revision:
            path = "revision"
            classification = self._classify_declared(
                path,
                DifferenceKind.REVISION,
                declared,
                default=DifferenceClassification.VALUE_MISMATCH,
            )
            item = self._make_evidence(
                path=path,
                kind=DifferenceKind.REVISION,
                classification=classification,
                baseline=baseline.revision,
                candidate=candidate.revision,
            )
            evidence.append(item)
            if classification in _FAILING_CLASSIFICATIONS:
                unexpected.append(item)

        passed = len(unexpected) == 0
        report = DifferentialReport(
            corpus_id=baseline.corpus_id,
            mode=self.mode,
            baseline_revision=baseline.revision,
            candidate_revision=candidate.revision,
            passed=passed,
            count_diff=count_diff,
            schema_diff=schema_diff,
            checksum_diff=checksum_diff,
            provenance_diff=provenance_diff,
            entity_diff=entity_diff,
            edge_diff=edge_diff,
            golden_query_diff=golden_query_diff,
            expected_differences=list(declared),
            unexpected_mismatches=unexpected[: self.max_evidence_items],
            evidence=evidence[: self.max_evidence_items],
            baseline_fingerprint=baseline.fingerprint(),
            candidate_fingerprint=candidate.fingerprint(),
            metadata={
                "max_evidence_items": self.max_evidence_items,
                "max_evidence_bytes": self.max_evidence_bytes,
                "precision_atol": self.precision_atol,
                "precision_rtol": self.precision_rtol,
                "sample_entity_limit": (
                    self.max_sample_entities
                    if self.mode is DiffMode.SAMPLE
                    else None
                ),
                "sample_edge_limit": (
                    self.max_sample_edges if self.mode is DiffMode.SAMPLE else None
                ),
            },
        )
        # Materialize digest.
        _ = report.to_dict()
        return report

    def compare_all(
        self,
        pairs: Sequence[tuple[CorpusSnapshot, CorpusSnapshot]],
    ) -> MultiCorpusDifferentialReport:
        """Compare every (baseline, candidate) pair; fail if any fails."""

        if not pairs:
            raise DifferentialVerificationError(
                "compare_all requires at least one corpus pair"
            )
        reports: list[DifferentialReport] = []
        for baseline, candidate in pairs:
            reports.append(self.compare(baseline, candidate))
        passed = all(r.passed for r in reports)
        multi = MultiCorpusDifferentialReport(
            mode=self.mode,
            reports=reports,
            passed=passed,
            metadata={"pair_count": len(pairs)},
        )
        _ = multi.to_dict()
        return multi

    def assert_equivalent(
        self,
        baseline: CorpusSnapshot,
        candidate: CorpusSnapshot,
    ) -> DifferentialReport:
        """Compare and raise :class:`DifferentialVerificationError` on failure."""

        report = self.compare(baseline, candidate)
        report.raise_if_failed()
        return report

    # -- section helpers ----------------------------------------------------

    def _lookup_declaration(
        self,
        path: str,
        kind: DifferenceKind,
        declared: Sequence[ExpectedDifference],
    ) -> Optional[ExpectedDifference]:
        # Exact path match preferred; then prefix match on path.
        exact = [
            d
            for d in declared
            if d.path == path and (d.kind == kind or True)
        ]
        if exact:
            # Prefer same kind when multiple declarations share a path.
            same_kind = [d for d in exact if d.kind == kind]
            return (same_kind or exact)[0]
        prefix = [
            d
            for d in declared
            if path == d.path
            or path.startswith(d.path + ".")
            or path.startswith(d.path + "[")
        ]
        if prefix:
            same_kind = [d for d in prefix if d.kind == kind]
            return (same_kind or prefix)[0]
        return None

    def _classify_declared(
        self,
        path: str,
        kind: DifferenceKind,
        declared: Sequence[ExpectedDifference],
        *,
        default: DifferenceClassification,
    ) -> DifferenceClassification:
        hit = self._lookup_declaration(path, kind, declared)
        if hit is None:
            return default
        return hit.classification

    def _make_evidence(
        self,
        *,
        path: str,
        kind: DifferenceKind,
        classification: DifferenceClassification,
        baseline: Any = None,
        candidate: Any = None,
        entity_ids: Optional[Sequence[str]] = None,
        edge_ids: Optional[Sequence[str]] = None,
        query_name: Optional[str] = None,
        notes: Optional[Sequence[str]] = None,
    ) -> MismatchEvidence:
        return MismatchEvidence(
            path=path,
            kind=kind,
            classification=classification,
            baseline=_clip_evidence(baseline, max_bytes=self.max_evidence_bytes),
            candidate=_clip_evidence(candidate, max_bytes=self.max_evidence_bytes),
            entity_ids=list(entity_ids or []),
            edge_ids=list(edge_ids or []),
            query_name=query_name,
            notes=list(notes or []),
        )

    def _record_mapping_change(
        self,
        *,
        path: str,
        kind: DifferenceKind,
        baseline_value: Any,
        candidate_value: Any,
        declared: Sequence[ExpectedDifference],
        evidence: list[MismatchEvidence],
        unexpected: list[MismatchEvidence],
        missing: bool = False,
        extra: bool = False,
    ) -> DifferenceClassification:
        if missing:
            default = DifferenceClassification.MISSING
        elif extra:
            default = DifferenceClassification.EXTRA
        elif _is_precision_only_diff(
            baseline_value,
            candidate_value,
            atol=self.precision_atol,
            rtol=self.precision_rtol,
        ):
            # Precision-only still fails unless declared expected_precision.
            default = DifferenceClassification.VALUE_MISMATCH
            classification = self._classify_declared(
                path, kind, declared, default=default
            )
            if classification is DifferenceClassification.EXPECTED_PRECISION:
                item = self._make_evidence(
                    path=path,
                    kind=kind,
                    classification=classification,
                    baseline=baseline_value,
                    candidate=candidate_value,
                    notes=["precision-only difference within configured tolerance"],
                )
                evidence.append(item)
                return classification
            # Also allow expected_declared to cover precision.
            if classification is DifferenceClassification.EXPECTED_DECLARED:
                item = self._make_evidence(
                    path=path,
                    kind=kind,
                    classification=classification,
                    baseline=baseline_value,
                    candidate=candidate_value,
                )
                evidence.append(item)
                return classification
        elif _is_ordering_only_diff(
            baseline_value,
            candidate_value,
            atol=self.precision_atol,
            rtol=self.precision_rtol,
        ):
            default = DifferenceClassification.VALUE_MISMATCH
            classification = self._classify_declared(
                path, kind, declared, default=default
            )
            if classification is DifferenceClassification.EXPECTED_ORDERING:
                item = self._make_evidence(
                    path=path,
                    kind=kind,
                    classification=classification,
                    baseline=baseline_value,
                    candidate=candidate_value,
                    notes=["ordering-only difference"],
                )
                evidence.append(item)
                return classification
            if classification is DifferenceClassification.EXPECTED_DECLARED:
                item = self._make_evidence(
                    path=path,
                    kind=kind,
                    classification=classification,
                    baseline=baseline_value,
                    candidate=candidate_value,
                )
                evidence.append(item)
                return classification
        else:
            default = DifferenceClassification.VALUE_MISMATCH

        classification = self._classify_declared(
            path, kind, declared, default=default
        )
        item = self._make_evidence(
            path=path,
            kind=kind,
            classification=classification,
            baseline=baseline_value,
            candidate=candidate_value,
        )
        evidence.append(item)
        if classification in _FAILING_CLASSIFICATIONS:
            unexpected.append(item)
        return classification

    def _diff_mapping_section(
        self,
        *,
        name: str,
        kind: DifferenceKind,
        baseline_map: Mapping[str, Any],
        candidate_map: Mapping[str, Any],
        path_prefix: str,
        declared: Sequence[ExpectedDifference],
        evidence: list[MismatchEvidence],
        unexpected: list[MismatchEvidence],
    ) -> SectionDiff:
        baseline_keys = set(baseline_map.keys())
        candidate_keys = set(candidate_map.keys())
        missing = sorted(baseline_keys - candidate_keys)
        extra = sorted(candidate_keys - baseline_keys)
        shared = sorted(baseline_keys & candidate_keys)
        changed: list[str] = []
        expected_classifications: list[str] = []

        for key in missing:
            path = f"{path_prefix}.{key}"
            classification = self._record_mapping_change(
                path=path,
                kind=kind,
                baseline_value=baseline_map[key],
                candidate_value=None,
                declared=declared,
                evidence=evidence,
                unexpected=unexpected,
                missing=True,
            )
            if classification in _EXPECTED_CLASSIFICATIONS:
                expected_classifications.append(f"{path}:{classification.value}")

        for key in extra:
            path = f"{path_prefix}.{key}"
            classification = self._record_mapping_change(
                path=path,
                kind=kind,
                baseline_value=None,
                candidate_value=candidate_map[key],
                declared=declared,
                evidence=evidence,
                unexpected=unexpected,
                extra=True,
            )
            if classification in _EXPECTED_CLASSIFICATIONS:
                expected_classifications.append(f"{path}:{classification.value}")

        for key in shared:
            left = baseline_map[key]
            right = candidate_map[key]
            if _values_equal(
                left,
                right,
                atol=self.precision_atol,
                rtol=self.precision_rtol,
            ) and _values_equal(left, right, atol=0.0, rtol=0.0):
                continue
            # Treat exact match under float tolerance with zero-tolerance
            # mismatch as potential precision-only path below.
            if _values_equal(
                left, right, atol=0.0, rtol=0.0
            ):
                continue
            path = f"{path_prefix}.{key}"
            changed.append(key)
            classification = self._record_mapping_change(
                path=path,
                kind=kind,
                baseline_value=left,
                candidate_value=right,
                declared=declared,
                evidence=evidence,
                unexpected=unexpected,
            )
            if classification in _EXPECTED_CLASSIFICATIONS:
                expected_classifications.append(f"{path}:{classification.value}")

        # Section is matched when every divergence under this prefix is either
        # absent or explicitly classified as expected (never auto-waived).
        section_unexpected = [
            u
            for u in unexpected
            if u.path == path_prefix or u.path.startswith(path_prefix + ".")
        ]
        matched = len(section_unexpected) == 0

        return SectionDiff(
            name=name,
            matched=matched,
            missing_keys=missing,
            extra_keys=extra,
            changed_keys=changed,
            expected_classifications=expected_classifications,
            details={
                "baseline_key_count": len(baseline_keys),
                "candidate_key_count": len(candidate_keys),
            },
        )

    def _select_ids(
        self,
        baseline_ids: set[str],
        candidate_ids: set[str],
        *,
        sample_ids: Optional[set[str]],
        max_sample: int,
    ) -> tuple[set[str], set[str], set[str]]:
        """Return (compare_ids, missing_scope, extra_scope) based on mode."""

        if self.mode is DiffMode.FULL:
            return (
                baseline_ids | candidate_ids,
                baseline_ids - candidate_ids,
                candidate_ids - baseline_ids,
            )

        # SAMPLE mode: restrict entity/edge membership checks to the sample
        # universe so full-corpus extras outside the sample do not fail.
        if sample_ids is not None:
            universe = set(sample_ids)
        else:
            # Deterministic sample: sorted baseline ids, then fill from candidate.
            ordered = sorted(baseline_ids)
            if len(ordered) < max_sample:
                ordered.extend(
                    sorted(candidate_ids - baseline_ids)[
                        : max_sample - len(ordered)
                    ]
                )
            universe = set(ordered[:max_sample])

        compare_ids = universe
        missing = (baseline_ids & universe) - candidate_ids
        extra = (candidate_ids & universe) - baseline_ids
        return compare_ids, missing, extra

    def _diff_record_index(
        self,
        *,
        name: str,
        kind: DifferenceKind,
        baseline_index: Mapping[str, Mapping[str, Any]],
        candidate_index: Mapping[str, Mapping[str, Any]],
        path_prefix: str,
        declared: Sequence[ExpectedDifference],
        evidence: list[MismatchEvidence],
        unexpected: list[MismatchEvidence],
        sample_ids: Optional[set[str]],
        max_sample: int,
        id_field: str,
    ) -> SectionDiff:
        baseline_ids = set(baseline_index.keys())
        candidate_ids = set(candidate_index.keys())
        compare_ids, missing, extra = self._select_ids(
            baseline_ids,
            candidate_ids,
            sample_ids=sample_ids,
            max_sample=max_sample,
        )
        missing_list = sorted(missing)
        extra_list = sorted(extra)
        changed: list[str] = []
        expected_classifications: list[str] = []

        for rid in missing_list:
            path = f"{path_prefix}[{rid}]"
            classification = self._record_mapping_change(
                path=path,
                kind=kind,
                baseline_value=dict(baseline_index[rid]),
                candidate_value=None,
                declared=declared,
                evidence=evidence,
                unexpected=unexpected,
                missing=True,
            )
            # Annotate ids on the last evidence item.
            if evidence:
                if id_field == "entity_ids":
                    evidence[-1].entity_ids = [rid]
                else:
                    evidence[-1].edge_ids = [rid]
            if classification in _EXPECTED_CLASSIFICATIONS:
                expected_classifications.append(f"{path}:{classification.value}")

        for rid in extra_list:
            path = f"{path_prefix}[{rid}]"
            classification = self._record_mapping_change(
                path=path,
                kind=kind,
                baseline_value=None,
                candidate_value=dict(candidate_index[rid]),
                declared=declared,
                evidence=evidence,
                unexpected=unexpected,
                extra=True,
            )
            if evidence:
                if id_field == "entity_ids":
                    evidence[-1].entity_ids = [rid]
                else:
                    evidence[-1].edge_ids = [rid]
            if classification in _EXPECTED_CLASSIFICATIONS:
                expected_classifications.append(f"{path}:{classification.value}")

        shared = sorted((baseline_ids & candidate_ids) & compare_ids)
        for rid in shared:
            left = dict(baseline_index[rid])
            right = dict(candidate_index[rid])
            if _values_equal(left, right, atol=0.0, rtol=0.0):
                continue
            path = f"{path_prefix}[{rid}]"
            changed.append(rid)
            classification = self._record_mapping_change(
                path=path,
                kind=kind,
                baseline_value=left,
                candidate_value=right,
                declared=declared,
                evidence=evidence,
                unexpected=unexpected,
            )
            if evidence:
                if id_field == "entity_ids":
                    evidence[-1].entity_ids = [rid]
                else:
                    evidence[-1].edge_ids = [rid]
            if classification in _EXPECTED_CLASSIFICATIONS:
                expected_classifications.append(f"{path}:{classification.value}")

        section_unexpected = [
            u
            for u in unexpected
            if u.path == path_prefix or u.path.startswith(path_prefix)
        ]
        return SectionDiff(
            name=name,
            matched=len(section_unexpected) == 0,
            missing_keys=missing_list,
            extra_keys=extra_list,
            changed_keys=changed,
            expected_classifications=expected_classifications,
            details={
                "mode": self.mode.value,
                "baseline_count": len(baseline_ids),
                "candidate_count": len(candidate_ids),
                "compared_id_count": len(compare_ids),
                "sample_limit": max_sample if self.mode is DiffMode.SAMPLE else None,
            },
        )

    def _diff_golden_queries(
        self,
        baseline_queries: Mapping[str, Sequence[Any]],
        candidate_queries: Mapping[str, Sequence[Any]],
        *,
        declared: Sequence[ExpectedDifference],
        evidence: list[MismatchEvidence],
        unexpected: list[MismatchEvidence],
    ) -> SectionDiff:
        path_prefix = "golden_queries"
        baseline_keys = set(baseline_queries.keys())
        candidate_keys = set(candidate_queries.keys())
        missing = sorted(baseline_keys - candidate_keys)
        extra = sorted(candidate_keys - baseline_keys)
        changed: list[str] = []
        expected_classifications: list[str] = []

        for key in missing:
            path = f"{path_prefix}.{key}"
            classification = self._record_mapping_change(
                path=path,
                kind=DifferenceKind.GOLDEN_QUERY,
                baseline_value=list(baseline_queries[key]),
                candidate_value=None,
                declared=declared,
                evidence=evidence,
                unexpected=unexpected,
                missing=True,
            )
            if evidence:
                evidence[-1].query_name = key
            if classification in _EXPECTED_CLASSIFICATIONS:
                expected_classifications.append(f"{path}:{classification.value}")
            # Also surface missing result ids as entity-like evidence notes.
            if classification in _FAILING_CLASSIFICATIONS:
                result_ids = [
                    _stable_id(dict(r), fallback_prefix="result", index=i)
                    if isinstance(r, Mapping)
                    else f"result:{i}"
                    for i, r in enumerate(baseline_queries[key])
                ]
                if evidence:
                    evidence[-1].notes.append(
                        f"missing query results: {result_ids[:16]}"
                    )

        for key in extra:
            path = f"{path_prefix}.{key}"
            classification = self._record_mapping_change(
                path=path,
                kind=DifferenceKind.GOLDEN_QUERY,
                baseline_value=None,
                candidate_value=list(candidate_queries[key]),
                declared=declared,
                evidence=evidence,
                unexpected=unexpected,
                extra=True,
            )
            if evidence:
                evidence[-1].query_name = key
            if classification in _EXPECTED_CLASSIFICATIONS:
                expected_classifications.append(f"{path}:{classification.value}")

        for key in sorted(baseline_keys & candidate_keys):
            left = list(baseline_queries[key])
            right = list(candidate_queries[key])
            if _values_equal(left, right, atol=0.0, rtol=0.0):
                continue
            path = f"{path_prefix}.{key}"
            changed.append(key)

            # Detect missing/extra result identities even when lengths differ.
            left_ids = [
                _stable_id(dict(r), fallback_prefix="result", index=i)
                if isinstance(r, Mapping)
                else content_address(r)
                for i, r in enumerate(left)
            ]
            right_ids = [
                _stable_id(dict(r), fallback_prefix="result", index=i)
                if isinstance(r, Mapping)
                else content_address(r)
                for i, r in enumerate(right)
            ]
            missing_results = [
                rid for rid in left_ids if rid not in set(right_ids)
            ]
            extra_results = [
                rid for rid in right_ids if rid not in set(left_ids)
            ]

            if missing_results or extra_results:
                # Unexplained missing/extra results always fail unless declared.
                if missing_results:
                    m_path = f"{path}.results"
                    classification = self._classify_declared(
                        m_path,
                        DifferenceKind.GOLDEN_QUERY,
                        declared,
                        default=DifferenceClassification.MISSING,
                    )
                    # Also accept declaration on the query path itself.
                    if classification in _FAILING_CLASSIFICATIONS:
                        classification = self._classify_declared(
                            path,
                            DifferenceKind.GOLDEN_QUERY,
                            declared,
                            default=DifferenceClassification.MISSING,
                        )
                    item = self._make_evidence(
                        path=m_path,
                        kind=DifferenceKind.GOLDEN_QUERY,
                        classification=classification,
                        baseline=missing_results[:32],
                        candidate=[],
                        query_name=key,
                        notes=["unexplained missing golden-query results"]
                        if classification in _FAILING_CLASSIFICATIONS
                        else ["declared missing golden-query results"],
                    )
                    evidence.append(item)
                    if classification in _FAILING_CLASSIFICATIONS:
                        unexpected.append(item)
                    else:
                        expected_classifications.append(
                            f"{m_path}:{classification.value}"
                        )
                if extra_results:
                    e_path = f"{path}.results"
                    classification = self._classify_declared(
                        e_path,
                        DifferenceKind.GOLDEN_QUERY,
                        declared,
                        default=DifferenceClassification.EXTRA,
                    )
                    if classification in _FAILING_CLASSIFICATIONS:
                        classification = self._classify_declared(
                            path,
                            DifferenceKind.GOLDEN_QUERY,
                            declared,
                            default=DifferenceClassification.EXTRA,
                        )
                    item = self._make_evidence(
                        path=e_path,
                        kind=DifferenceKind.GOLDEN_QUERY,
                        classification=classification,
                        baseline=[],
                        candidate=extra_results[:32],
                        query_name=key,
                        notes=["unexplained extra golden-query results"]
                        if classification in _FAILING_CLASSIFICATIONS
                        else ["declared extra golden-query results"],
                    )
                    evidence.append(item)
                    if classification in _FAILING_CLASSIFICATIONS:
                        unexpected.append(item)
                    else:
                        expected_classifications.append(
                            f"{e_path}:{classification.value}"
                        )
                # If membership already failed, still record value/order diffs
                # only when membership is clean — skip further when unexpected.
                continue

            # Same multiset of results: ordering or precision (or both).
            classification = self._record_mapping_change(
                path=path,
                kind=DifferenceKind.GOLDEN_QUERY,
                baseline_value=left,
                candidate_value=right,
                declared=declared,
                evidence=evidence,
                unexpected=unexpected,
            )
            if evidence:
                evidence[-1].query_name = key
            if classification in _EXPECTED_CLASSIFICATIONS:
                expected_classifications.append(f"{path}:{classification.value}")

        section_unexpected = [
            u
            for u in unexpected
            if u.path == path_prefix or u.path.startswith(path_prefix + ".")
        ]
        return SectionDiff(
            name="golden_queries",
            matched=len(section_unexpected) == 0,
            missing_keys=missing,
            extra_keys=extra,
            changed_keys=changed,
            expected_classifications=expected_classifications,
            details={
                "baseline_query_count": len(baseline_keys),
                "candidate_query_count": len(candidate_keys),
            },
        )


# ---------------------------------------------------------------------------
# Convenience builders for the four production corpora
# ---------------------------------------------------------------------------


def build_minimal_snapshot(
    corpus_id: str,
    revision: str,
    *,
    counts: Optional[Mapping[str, int]] = None,
    schema: Optional[Mapping[str, Any]] = None,
    checksums: Optional[Mapping[str, str]] = None,
    provenance: Optional[Mapping[str, Any]] = None,
    entities: Optional[Sequence[Mapping[str, Any]]] = None,
    edges: Optional[Sequence[Mapping[str, Any]]] = None,
    golden_queries: Optional[Mapping[str, Sequence[Any]]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> CorpusSnapshot:
    """Factory for tests and offline report tooling."""

    return CorpusSnapshot(
        corpus_id=corpus_id,
        revision=revision,
        counts=dict(counts or {}),
        schema=dict(schema or {}),
        checksums=dict(checksums or {}),
        provenance=dict(provenance or {}),
        entities=[dict(e) for e in (entities or [])],
        edges=[dict(e) for e in (edges or [])],
        golden_queries={str(k): list(v) for k, v in (golden_queries or {}).items()},
        metadata=dict(metadata or {}),
    )


def verify_corpus_pair(
    baseline: CorpusSnapshot,
    candidate: CorpusSnapshot,
    *,
    mode: DiffMode | str = DiffMode.FULL,
    expected_differences: Optional[Sequence[ExpectedDifference]] = None,
    **kwargs: Any,
) -> DifferentialReport:
    """One-shot compare helper."""

    verifier = CorpusDifferentialVerifier(
        mode=mode,
        expected_differences=expected_differences,
        **kwargs,
    )
    return verifier.compare(baseline, candidate)


def verify_all_corpora(
    pairs: Sequence[tuple[CorpusSnapshot, CorpusSnapshot]],
    *,
    mode: DiffMode | str = DiffMode.FULL,
    expected_differences: Optional[Sequence[ExpectedDifference]] = None,
    **kwargs: Any,
) -> MultiCorpusDifferentialReport:
    """One-shot multi-corpus compare helper."""

    verifier = CorpusDifferentialVerifier(
        mode=mode,
        expected_differences=expected_differences,
        **kwargs,
    )
    return verifier.compare_all(pairs)


__all__ = [
    "CANONICAL_JSON_PROFILE",
    "KNOWN_CORPORA",
    "MULTI_REPORT_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "CorpusDifferentialVerifier",
    "CorpusSnapshot",
    "DiffMode",
    "DifferenceClassification",
    "DifferenceKind",
    "DifferentialReport",
    "DifferentialVerificationError",
    "ExpectedDifference",
    "MismatchEvidence",
    "MultiCorpusDifferentialReport",
    "SectionDiff",
    "build_minimal_snapshot",
    "canonical_json_bytes",
    "canonicalize",
    "content_address",
    "verify_all_corpora",
    "verify_corpus_pair",
]
