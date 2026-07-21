"""Leakage-resistant corpus splits for LegalIR evaluation.

The split contract is intentionally independent from any trainer.  It produces
a deterministic manifest for LegalIR samples and validates manifests generated
elsewhere before they are used for training, hparam selection, representation
promotion, or Codex TODO projection.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final


LEGAL_IR_EVAL_SPLIT_SCHEMA_VERSION: Final = "legal-ir-eval-splits-v1"

TRAIN_SPLIT: Final = "train"
VALIDATION_SPLIT: Final = "validation"
CANARY_SPLIT: Final = "canary"
HOLDOUT_SPLIT: Final = "holdout"
STATUTE_FAMILY_SPLIT: Final = "statute_family"
JURISDICTION_SPLIT: Final = "jurisdiction"
TEMPORAL_SPLIT: Final = "temporal"
EXTERNAL_TEST_SPLIT: Final = "external_test"

LEGAL_IR_EVAL_SPLITS: Final = (
    TRAIN_SPLIT,
    VALIDATION_SPLIT,
    CANARY_SPLIT,
    HOLDOUT_SPLIT,
    STATUTE_FAMILY_SPLIT,
    JURISDICTION_SPLIT,
    TEMPORAL_SPLIT,
    EXTERNAL_TEST_SPLIT,
)

PROTECTED_LEGAL_IR_SPLITS: Final = (
    VALIDATION_SPLIT,
    CANARY_SPLIT,
    HOLDOUT_SPLIT,
    STATUTE_FAMILY_SPLIT,
    JURISDICTION_SPLIT,
    TEMPORAL_SPLIT,
    EXTERNAL_TEST_SPLIT,
)

TRAINING_OPERATION: Final = "training"
HPARAM_SELECTION_OPERATION: Final = "hparam_selection"
REPRESENTATION_PROMOTION_OPERATION: Final = "representation_promotion"
CODEX_TODO_PROJECTION_OPERATION: Final = "codex_todo_projection"

LEGAL_IR_SPLIT_OPERATION_ALLOWED_SPLITS: Final = {
    TRAINING_OPERATION: frozenset({TRAIN_SPLIT}),
    HPARAM_SELECTION_OPERATION: frozenset({VALIDATION_SPLIT}),
    REPRESENTATION_PROMOTION_OPERATION: frozenset({CANARY_SPLIT}),
    CODEX_TODO_PROJECTION_OPERATION: frozenset({TRAIN_SPLIT, VALIDATION_SPLIT}),
}

LEAKAGE_KEY_KINDS: Final = (
    "example",
    "content",
    "citation_cluster",
    "source_span",
    "amendment",
    "near_duplicate",
)


class LegalIRSplitError(RuntimeError):
    """Base error for LegalIR split guard failures."""


class LegalIRSplitLeakageError(LegalIRSplitError):
    """Raised when leakage crosses a protected split boundary."""

    def __init__(self, message: str, result: "LegalIRSplitGuardResult") -> None:
        super().__init__(message)
        self.result = result


class LegalIRSplitPolicyError(LegalIRSplitError):
    """Raised when an operation attempts to use disallowed split evidence."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        disallowed: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.disallowed = tuple(dict(item) for item in disallowed)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("split value contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict())
    if hasattr(value, "__dict__"):
        return _json_value(
            {
                str(key): item
                for key, item in sorted(vars(value).items())
                if not str(key).startswith("_")
            }
        )
    return repr(value)


def _get(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _string(value: Any) -> str:
    return str(value or "").strip()


def _sequence_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (_string(value),) if _string(value) else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(_string(item) for item in value if _string(item))
    return (_string(value),) if _string(value) else ()


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", _normalized_text(value)))


def _content_hash(text: str) -> str:
    return hashlib.sha256(_normalized_text(text).encode("utf-8")).hexdigest()


def _citation_cluster(value: str) -> str:
    text = str(value or "").lower()
    text = text.replace("§", " ")
    text = re.sub(r"\bu\.?\s*s\.?\s*c\.?\b", "usc", text)
    match = re.search(r"\b(\d+)\s*usc\s*([0-9a-z.-]+)", text)
    if match:
        return f"usc:{match.group(1)}:{match.group(2).rstrip('.')}"
    return re.sub(r"[^a-z0-9]+", ":", text).strip(":")


def _safe_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_.:-]+", "-", str(value or "").strip().lower()).strip("-")


def _date_value(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for candidate in (text, text[:10]):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            pass
    return None


def _source_span(sample: Any) -> tuple[str, int | None, int | None, str]:
    raw_span = _get(sample, "source_span", "span", default=None)
    start: Any = _get(sample, "span_start", "source_start", "char_start", "start", default=None)
    end: Any = _get(sample, "span_end", "source_end", "char_end", "end", default=None)
    span_id = ""
    if isinstance(raw_span, Mapping):
        start = raw_span.get("start", raw_span.get("char_start", start))
        end = raw_span.get("end", raw_span.get("char_end", end))
        span_id = _string(raw_span.get("span_id") or raw_span.get("id"))
    elif raw_span is not None:
        span_id = _string(raw_span)
    source_id = _string(
        _get(
            sample,
            "source_document_id",
            "source_doc_id",
            "document_id",
            "source_id",
            "source_path",
            "url",
            "source",
            default="",
        )
    )
    try:
        resolved_start = int(start) if start is not None and start != "" else None
        resolved_end = int(end) if end is not None and end != "" else None
    except (TypeError, ValueError):
        resolved_start = None
        resolved_end = None
    return source_id, resolved_start, resolved_end, span_id


def _source_span_key(sample: Any) -> str:
    source_id, start, end, span_id = _source_span(sample)
    if start is not None and end is not None:
        return f"{source_id}:{start}:{end}"
    if span_id:
        return f"{source_id}:{span_id}"
    return source_id


@dataclass(frozen=True, slots=True)
class LegalIREvalSplitConfig:
    """Policy for deterministic LegalIR split construction."""

    seed: str = "legal-ir-eval-splits"
    train_ratio: float = 0.55
    validation_ratio: float = 0.15
    canary_ratio: float = 0.10
    holdout_ratio: float = 0.10
    statute_family_ratio: float = 0.05
    jurisdiction_ratio: float = 0.03
    temporal_ratio: float = 0.02
    external_test_sources: tuple[str, ...] = ("external", "external_test", "third_party")
    statute_family_holdout_values: tuple[str, ...] = ()
    jurisdiction_holdout_values: tuple[str, ...] = ()
    temporal_holdout_after: str = ""
    near_duplicate_jaccard_threshold: float = 0.82
    protected_splits: tuple[str, ...] = PROTECTED_LEGAL_IR_SPLITS

    def __post_init__(self) -> None:
        ratios = (
            self.train_ratio,
            self.validation_ratio,
            self.canary_ratio,
            self.holdout_ratio,
            self.statute_family_ratio,
            self.jurisdiction_ratio,
            self.temporal_ratio,
        )
        if any(not math.isfinite(float(value)) or float(value) < 0.0 for value in ratios):
            raise ValueError("split ratios must be finite and non-negative")
        total = sum(float(value) for value in ratios)
        if total <= 0.0:
            raise ValueError("at least one split ratio must be positive")
        if total > 1.0 + 1.0e-12:
            raise ValueError("split ratios must sum to <= 1.0")
        threshold = float(self.near_duplicate_jaccard_threshold)
        if not math.isfinite(threshold) or threshold <= 0.0 or threshold > 1.0:
            raise ValueError("near_duplicate_jaccard_threshold must be in (0, 1]")
        object.__setattr__(self, "near_duplicate_jaccard_threshold", threshold)
        object.__setattr__(self, "external_test_sources", tuple(_safe_key(v) for v in self.external_test_sources if _safe_key(v)))
        object.__setattr__(self, "statute_family_holdout_values", tuple(_safe_key(v) for v in self.statute_family_holdout_values if _safe_key(v)))
        object.__setattr__(self, "jurisdiction_holdout_values", tuple(_safe_key(v) for v in self.jurisdiction_holdout_values if _safe_key(v)))
        protected = tuple(split for split in self.protected_splits if split in LEGAL_IR_EVAL_SPLITS)
        object.__setattr__(self, "protected_splits", protected or PROTECTED_LEGAL_IR_SPLITS)

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    @property
    def temporal_cutoff_date(self) -> date | None:
        return _date_value(self.temporal_holdout_after)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canary_ratio": self.canary_ratio,
            "external_test_sources": list(self.external_test_sources),
            "holdout_ratio": self.holdout_ratio,
            "jurisdiction_holdout_values": list(self.jurisdiction_holdout_values),
            "jurisdiction_ratio": self.jurisdiction_ratio,
            "near_duplicate_jaccard_threshold": self.near_duplicate_jaccard_threshold,
            "protected_splits": list(self.protected_splits),
            "seed": self.seed,
            "statute_family_holdout_values": list(self.statute_family_holdout_values),
            "statute_family_ratio": self.statute_family_ratio,
            "temporal_holdout_after": self.temporal_holdout_after,
            "temporal_ratio": self.temporal_ratio,
            "train_ratio": self.train_ratio,
            "validation_ratio": self.validation_ratio,
        }


@dataclass(frozen=True, slots=True)
class LegalIRSplitExample:
    sample_id: str
    content_hash: str
    citation_clusters: tuple[str, ...] = ()
    source_span_key: str = ""
    amendment_key: str = ""
    statute_family: str = ""
    jurisdiction: str = ""
    effective_date: str = ""
    source_label: str = ""
    near_duplicate_key: str = ""
    token_fingerprint: tuple[str, ...] = ()

    @classmethod
    def from_sample(cls, sample: Any) -> "LegalIRSplitExample":
        text = _string(_get(sample, "normalized_text", "text", "source_text", default=""))
        sample_id = _string(_get(sample, "sample_id", "id", "document_id", default=""))
        content_hash = _content_hash(text)
        if not sample_id:
            sample_id = "sample-" + content_hash[:16]
        citations = _sequence_strings(_get(sample, "citations", default=None))
        citation = _string(_get(sample, "citation", default=""))
        if citation:
            citations = (*citations, citation)
        clusters = tuple(
            dict.fromkeys(_citation_cluster(item) for item in citations if _citation_cluster(item))
        )
        source_span_key = _source_span_key(sample)
        raw_amendment = _string(
            _get(
                sample,
                "amendment_group",
                "amendment_id",
                "revision_group",
                "version_series",
                default="",
            )
        )
        family = _safe_key(
            _get(sample, "statute_family", "legal_family", "family", "title", default="")
        )
        jurisdiction = _safe_key(_get(sample, "jurisdiction", default=""))
        if not jurisdiction and any(cluster.startswith("usc:") for cluster in clusters):
            jurisdiction = "us-federal"
        effective = _date_value(
            _get(
                sample,
                "effective_date",
                "amendment_date",
                "enacted_date",
                "date",
                default=None,
            )
        )
        source_label = _safe_key(_get(sample, "source_label", "source", default=""))
        return cls(
            sample_id=sample_id,
            content_hash=content_hash,
            citation_clusters=clusters,
            source_span_key=source_span_key,
            amendment_key=_safe_key(raw_amendment),
            statute_family=family,
            jurisdiction=jurisdiction,
            effective_date=effective.isoformat() if effective else "",
            source_label=source_label,
            near_duplicate_key="",
            token_fingerprint=tuple(sorted(_tokens(text))),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LegalIRSplitExample":
        return cls(
            sample_id=_string(value.get("sample_id")),
            content_hash=_string(value.get("content_hash")),
            citation_clusters=tuple(_string(item) for item in value.get("citation_clusters", ()) if _string(item)),
            source_span_key=_string(value.get("source_span_key")),
            amendment_key=_string(value.get("amendment_key")),
            statute_family=_string(value.get("statute_family")),
            jurisdiction=_string(value.get("jurisdiction")),
            effective_date=_string(value.get("effective_date")),
            source_label=_string(value.get("source_label")),
            near_duplicate_key=_string(value.get("near_duplicate_key")),
            token_fingerprint=tuple(_string(item) for item in value.get("token_fingerprint", ()) if _string(item)),
        )

    def with_near_duplicate_key(self, key: str) -> "LegalIRSplitExample":
        return LegalIRSplitExample(
            sample_id=self.sample_id,
            content_hash=self.content_hash,
            citation_clusters=self.citation_clusters,
            source_span_key=self.source_span_key,
            amendment_key=self.amendment_key,
            statute_family=self.statute_family,
            jurisdiction=self.jurisdiction,
            effective_date=self.effective_date,
            source_label=self.source_label,
            near_duplicate_key=key,
            token_fingerprint=self.token_fingerprint,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amendment_key": self.amendment_key,
            "citation_clusters": list(self.citation_clusters),
            "content_hash": self.content_hash,
            "effective_date": self.effective_date,
            "jurisdiction": self.jurisdiction,
            "near_duplicate_key": self.near_duplicate_key,
            "sample_id": self.sample_id,
            "source_label": self.source_label,
            "source_span_key": self.source_span_key,
            "statute_family": self.statute_family,
            "token_fingerprint": list(self.token_fingerprint),
        }


@dataclass(frozen=True, slots=True)
class LegalIRLeakageViolation:
    kind: str
    key: str
    splits: tuple[str, ...]
    sample_ids_by_split: Mapping[str, tuple[str, ...]]
    protected_splits: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "protected_splits": list(self.protected_splits),
            "sample_ids_by_split": {
                split: list(ids) for split, ids in sorted(self.sample_ids_by_split.items())
            },
            "splits": list(self.splits),
        }


@dataclass(frozen=True, slots=True)
class LegalIRSplitGuardResult:
    passed: bool
    violations: tuple[LegalIRLeakageViolation, ...] = ()
    blocked_operations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked_operations": list(self.blocked_operations),
            "passed": self.passed,
            "violations": [item.to_dict() for item in self.violations],
        }


@dataclass(frozen=True, slots=True)
class LegalIRSplitManifest:
    examples: tuple[LegalIRSplitExample, ...]
    assignments: Mapping[str, str]
    config_digest: str
    protected_splits: tuple[str, ...] = PROTECTED_LEGAL_IR_SPLITS
    schema_version: str = LEGAL_IR_EVAL_SPLIT_SCHEMA_VERSION
    partition_names: tuple[str, ...] = LEGAL_IR_EVAL_SPLITS
    metadata: Mapping[str, Any] = field(default_factory=dict)
    assignment_conflicts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != LEGAL_IR_EVAL_SPLIT_SCHEMA_VERSION:
            raise ValueError("unsupported LegalIR split schema version")
        examples = tuple(sorted(self.examples, key=lambda item: item.sample_id))
        ids = [item.sample_id for item in examples]
        if len(ids) != len(set(ids)):
            raise ValueError("LegalIR split examples must have unique sample_id values")
        assignments = {str(key): str(value) for key, value in self.assignments.items()}
        invalid_splits = sorted(set(assignments.values()) - set(LEGAL_IR_EVAL_SPLITS))
        if invalid_splits:
            raise ValueError(f"unknown LegalIR split names: {invalid_splits}")
        missing = sorted(set(ids) - set(assignments))
        if missing:
            raise ValueError(f"missing split assignments for samples: {missing[:5]}")
        protected = tuple(split for split in self.protected_splits if split in LEGAL_IR_EVAL_SPLITS)
        object.__setattr__(self, "examples", examples)
        object.__setattr__(self, "assignments", dict(sorted(assignments.items())))
        object.__setattr__(self, "protected_splits", protected or PROTECTED_LEGAL_IR_SPLITS)
        object.__setattr__(self, "partition_names", tuple(self.partition_names))
        object.__setattr__(self, "metadata", dict(sorted(self.metadata.items())))
        object.__setattr__(
            self,
            "assignment_conflicts",
            {
                str(sample_id): tuple(
                    split for split in splits if split in LEGAL_IR_EVAL_SPLITS
                )
                for sample_id, splits in sorted(self.assignment_conflicts.items())
                if len(tuple(splits)) > 1
            },
        )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    @property
    def samples_by_split(self) -> dict[str, list[str]]:
        result = {split: [] for split in self.partition_names}
        for sample_id, split in self.assignments.items():
            result.setdefault(split, []).append(sample_id)
        return {split: sorted(ids) for split, ids in result.items()}

    def guard_result(self) -> LegalIRSplitGuardResult:
        return validate_legal_ir_eval_splits(self)

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "assignments": dict(self.assignments),
            "assignment_conflicts": {
                sample_id: list(splits)
                for sample_id, splits in self.assignment_conflicts.items()
            },
            "config_digest": self.config_digest,
            "examples": [item.to_dict() for item in self.examples],
            "metadata": dict(self.metadata),
            "partition_names": list(self.partition_names),
            "protected_splits": list(self.protected_splits),
            "samples_by_split": self.samples_by_split,
            "schema_version": self.schema_version,
        }
        if include_digest:
            payload["split_manifest_digest"] = self.digest
            payload["legal_ir_split_guard"] = self.guard_result().to_dict()
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "LegalIRSplitManifest":
        examples = tuple(
            LegalIRSplitExample.from_mapping(item)
            for item in payload.get("examples", ())
            if isinstance(item, Mapping)
        )
        assignments = payload.get("assignments")
        if not isinstance(assignments, Mapping):
            samples_by_split = payload.get("samples_by_split", {})
            assignments = {}
            conflicts: dict[str, list[str]] = defaultdict(list)
            if isinstance(samples_by_split, Mapping):
                for split, sample_ids in samples_by_split.items():
                    for sample_id in _sequence_strings(sample_ids):
                        conflicts[sample_id].append(str(split))
                        assignments[sample_id] = str(split)
            assignment_conflicts = {
                sample_id: tuple(dict.fromkeys(splits))
                for sample_id, splits in conflicts.items()
                if len(set(splits)) > 1
            }
        else:
            raw_conflicts = payload.get("assignment_conflicts", {})
            assignment_conflicts = {
                str(sample_id): tuple(_sequence_strings(splits))
                for sample_id, splits in raw_conflicts.items()
            } if isinstance(raw_conflicts, Mapping) else {}
        return cls(
            examples=examples,
            assignments=assignments if isinstance(assignments, Mapping) else {},
            config_digest=_string(payload.get("config_digest") or payload.get("split_config_digest") or ""),
            protected_splits=tuple(_sequence_strings(payload.get("protected_splits"))) or PROTECTED_LEGAL_IR_SPLITS,
            schema_version=_string(payload.get("schema_version") or LEGAL_IR_EVAL_SPLIT_SCHEMA_VERSION),
            partition_names=tuple(_sequence_strings(payload.get("partition_names"))) or LEGAL_IR_EVAL_SPLITS,
            metadata=payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), Mapping) else {},
            assignment_conflicts=assignment_conflicts,
        )


class _UnionFind:
    def __init__(self, values: Sequence[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            parent = self.find(parent)
            self.parent[value] = parent
        return parent

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


def build_legal_ir_eval_splits(
    samples: Sequence[Any],
    config: LegalIREvalSplitConfig | None = None,
) -> LegalIRSplitManifest:
    """Build deterministic LegalIR partitions with leakage clusters intact."""

    cfg = config or LegalIREvalSplitConfig()
    examples = [LegalIRSplitExample.from_sample(sample) for sample in samples]
    examples.sort(key=lambda item: item.sample_id)
    if not examples:
        return LegalIRSplitManifest(
            examples=(),
            assignments={},
            config_digest=cfg.digest,
            protected_splits=cfg.protected_splits,
            metadata={"seed": cfg.seed},
        )

    duplicate_clusters = _near_duplicate_clusters(examples, cfg.near_duplicate_jaccard_threshold)
    examples = [
        item.with_near_duplicate_key(duplicate_clusters.get(item.sample_id, item.content_hash))
        for item in examples
    ]
    by_id = {item.sample_id: item for item in examples}
    uf = _UnionFind(tuple(by_id))
    _union_by_key(uf, examples, lambda item: item.content_hash)
    _union_by_key(uf, examples, lambda item: item.near_duplicate_key)
    _union_by_key(uf, examples, lambda item: item.amendment_key)
    _union_by_key(uf, examples, lambda item: item.source_span_key)
    for citation in sorted({key for item in examples for key in item.citation_clusters}):
        members = [item.sample_id for item in examples if citation in item.citation_clusters]
        for member in members[1:]:
            uf.union(members[0], member)
    _union_overlapping_source_spans(uf, examples)

    groups: dict[str, list[LegalIRSplitExample]] = defaultdict(list)
    for item in examples:
        groups[uf.find(item.sample_id)].append(item)
    assignments: dict[str, str] = {}
    for group_id, group in sorted(groups.items(), key=lambda entry: entry[0]):
        split = _group_split(group, group_id=group_id, config=cfg)
        for item in group:
            assignments[item.sample_id] = split

    return LegalIRSplitManifest(
        examples=tuple(examples),
        assignments=assignments,
        config_digest=cfg.digest,
        protected_splits=cfg.protected_splits,
        metadata={
            "near_duplicate_jaccard_threshold": cfg.near_duplicate_jaccard_threshold,
            "seed": cfg.seed,
        },
    )


def _union_by_key(
    uf: _UnionFind,
    examples: Sequence[LegalIRSplitExample],
    key_fn: Any,
) -> None:
    seen: dict[str, str] = {}
    for item in examples:
        key = str(key_fn(item) or "")
        if not key:
            continue
        previous = seen.setdefault(key, item.sample_id)
        uf.union(previous, item.sample_id)


def _near_duplicate_clusters(
    examples: Sequence[LegalIRSplitExample],
    threshold: float,
) -> dict[str, str]:
    uf = _UnionFind(tuple(item.sample_id for item in examples))
    for index, left in enumerate(examples):
        left_tokens = frozenset(left.token_fingerprint)
        if not left_tokens:
            continue
        for right in examples[index + 1 :]:
            right_tokens = frozenset(right.token_fingerprint)
            if not right_tokens:
                continue
            union = len(left_tokens | right_tokens)
            if union <= 0:
                continue
            similarity = len(left_tokens & right_tokens) / union
            if similarity >= threshold:
                uf.union(left.sample_id, right.sample_id)
    clusters: dict[str, list[str]] = defaultdict(list)
    for item in examples:
        clusters[uf.find(item.sample_id)].append(item.sample_id)
    result: dict[str, str] = {}
    for members in clusters.values():
        key = "near:" + _digest(sorted(members))[:16]
        for member in members:
            result[member] = key
    return result


def _union_overlapping_source_spans(
    uf: _UnionFind,
    examples: Sequence[LegalIRSplitExample],
) -> None:
    spans: list[tuple[str, int, int, str]] = []
    for item in examples:
        match = re.match(r"^(.+):(\d+):(\d+)$", item.source_span_key)
        if not match:
            continue
        start = int(match.group(2))
        end = int(match.group(3))
        if end > start:
            spans.append((match.group(1), start, end, item.sample_id))
    spans.sort()
    for index, (left_source, left_start, left_end, left_id) in enumerate(spans):
        for right_source, right_start, right_end, right_id in spans[index + 1 :]:
            if right_source != left_source:
                break
            if right_start >= left_end:
                break
            if right_end > left_start:
                uf.union(left_id, right_id)


def _group_split(
    group: Sequence[LegalIRSplitExample],
    *,
    group_id: str,
    config: LegalIREvalSplitConfig,
) -> str:
    source_labels = {_safe_key(item.source_label) for item in group if item.source_label}
    if source_labels & set(config.external_test_sources):
        return EXTERNAL_TEST_SPLIT
    cutoff = config.temporal_cutoff_date
    dates = [_date_value(item.effective_date) for item in group if item.effective_date]
    if cutoff is not None and any(value is not None and value > cutoff for value in dates):
        return TEMPORAL_SPLIT
    families = {_safe_key(item.statute_family) for item in group if item.statute_family}
    if families & set(config.statute_family_holdout_values):
        return STATUTE_FAMILY_SPLIT
    jurisdictions = {_safe_key(item.jurisdiction) for item in group if item.jurisdiction}
    if jurisdictions & set(config.jurisdiction_holdout_values):
        return JURISDICTION_SPLIT

    family_key = sorted(families)[0] if families else group_id
    if config.statute_family_ratio > 0.0 and _bucket(config.seed, "family", family_key) < config.statute_family_ratio:
        return STATUTE_FAMILY_SPLIT
    jurisdiction_key = sorted(jurisdictions)[0] if jurisdictions else group_id
    if config.jurisdiction_ratio > 0.0 and _bucket(config.seed, "jurisdiction", jurisdiction_key) < config.jurisdiction_ratio:
        return JURISDICTION_SPLIT
    if config.temporal_ratio > 0.0 and dates and _bucket(config.seed, "temporal", max(dates).isoformat()) < config.temporal_ratio:
        return TEMPORAL_SPLIT

    bucket = _bucket(config.seed, "primary", group_id)
    validation_end = config.validation_ratio
    canary_end = validation_end + config.canary_ratio
    holdout_end = canary_end + config.holdout_ratio
    if bucket < validation_end:
        return VALIDATION_SPLIT
    if bucket < canary_end:
        return CANARY_SPLIT
    if bucket < holdout_end:
        return HOLDOUT_SPLIT
    return TRAIN_SPLIT


def _bucket(*parts: Any) -> float:
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16**12)


def validate_legal_ir_eval_splits(
    manifest: LegalIRSplitManifest | Mapping[str, Any],
) -> LegalIRSplitGuardResult:
    """Validate content, citation, source, amendment, and duplicate isolation."""

    resolved = manifest if isinstance(manifest, LegalIRSplitManifest) else LegalIRSplitManifest.from_mapping(manifest)
    violations: list[LegalIRLeakageViolation] = []
    examples = resolved.examples
    assignments = resolved.assignments
    protected = frozenset(resolved.protected_splits)

    def add(kind: str, key: str, sample_ids: Sequence[str]) -> None:
        by_split: dict[str, list[str]] = defaultdict(list)
        for sample_id in sample_ids:
            split = assignments.get(sample_id, "")
            if split:
                by_split[split].append(sample_id)
        crossed = _crosses_protected_split(by_split, protected)
        if not crossed:
            return
        violations.append(
            LegalIRLeakageViolation(
                kind=kind,
                key=key,
                splits=tuple(sorted(by_split)),
                sample_ids_by_split={
                    split: tuple(sorted(ids)) for split, ids in sorted(by_split.items())
                },
                protected_splits=tuple(sorted(set(by_split) & protected)),
            )
        )

    for sample_id, splits in sorted(resolved.assignment_conflicts.items()):
        by_split = {split: (sample_id,) for split in splits}
        if _crosses_protected_split(by_split, protected):
            violations.append(
                LegalIRLeakageViolation(
                    kind="example",
                    key=sample_id,
                    splits=tuple(sorted(by_split)),
                    sample_ids_by_split={
                        split: tuple(ids)
                        for split, ids in sorted(by_split.items())
                    },
                    protected_splits=tuple(sorted(set(by_split) & protected)),
                )
            )

    add_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in examples:
        add_map[("example", item.sample_id)].append(item.sample_id)
        add_map[("content", item.content_hash)].append(item.sample_id)
        if item.source_span_key:
            add_map[("source_span", item.source_span_key)].append(item.sample_id)
        if item.amendment_key:
            add_map[("amendment", item.amendment_key)].append(item.sample_id)
        if item.near_duplicate_key:
            add_map[("near_duplicate", item.near_duplicate_key)].append(item.sample_id)
        for cluster in item.citation_clusters:
            add_map[("citation_cluster", cluster)].append(item.sample_id)
    for (kind, key), sample_ids in sorted(add_map.items()):
        add(kind, key, sample_ids)
    for violation in _source_overlap_violations(examples, assignments, protected):
        violations.append(violation)

    violations = list({(item.kind, item.key, item.splits): item for item in violations}.values())
    blocked = (
        (
            TRAINING_OPERATION,
            HPARAM_SELECTION_OPERATION,
            REPRESENTATION_PROMOTION_OPERATION,
            CODEX_TODO_PROJECTION_OPERATION,
        )
        if violations
        else ()
    )
    return LegalIRSplitGuardResult(
        passed=not violations,
        violations=tuple(sorted(violations, key=lambda item: (item.kind, item.key))),
        blocked_operations=blocked,
    )


def _crosses_protected_split(
    by_split: Mapping[str, Sequence[str]],
    protected: frozenset[str],
) -> bool:
    non_empty = {split for split, ids in by_split.items() if ids}
    return len(non_empty) > 1 and bool(non_empty & protected)


def _source_overlap_violations(
    examples: Sequence[LegalIRSplitExample],
    assignments: Mapping[str, str],
    protected: frozenset[str],
) -> tuple[LegalIRLeakageViolation, ...]:
    spans: list[tuple[str, int, int, LegalIRSplitExample]] = []
    for item in examples:
        match = re.match(r"^(.+):(\d+):(\d+)$", item.source_span_key)
        if match:
            spans.append((match.group(1), int(match.group(2)), int(match.group(3)), item))
    spans.sort(key=lambda value: (value[0], value[1], value[2], value[3].sample_id))
    violations: list[LegalIRLeakageViolation] = []
    for index, (left_source, left_start, left_end, left) in enumerate(spans):
        for right_source, right_start, right_end, right in spans[index + 1 :]:
            if right_source != left_source:
                break
            if right_start >= left_end:
                break
            if right_end <= left_start:
                continue
            by_split = {
                assignments.get(left.sample_id, ""): (left.sample_id,),
                assignments.get(right.sample_id, ""): (right.sample_id,),
            }
            if _crosses_protected_split(by_split, protected):
                key = f"{left_source}:{max(left_start, right_start)}:{min(left_end, right_end)}"
                violations.append(
                    LegalIRLeakageViolation(
                        kind="source_span",
                        key=key,
                        splits=tuple(sorted(split for split in by_split if split)),
                        sample_ids_by_split={
                            split: tuple(ids)
                            for split, ids in sorted(by_split.items())
                            if split
                        },
                        protected_splits=tuple(sorted(set(by_split) & protected)),
                    )
                )
    return tuple(violations)


def require_legal_ir_split_guard(
    manifest: LegalIRSplitManifest | Mapping[str, Any],
    *,
    operation: str = "",
) -> LegalIRSplitGuardResult:
    result = validate_legal_ir_eval_splits(manifest)
    if not result.passed:
        suffix = f" for {operation}" if operation else ""
        raise LegalIRSplitLeakageError(
            f"LegalIR split leakage blocks protected evaluation use{suffix}",
            result,
        )
    return result


def authorize_legal_ir_split_use(
    manifest: LegalIRSplitManifest | Mapping[str, Any],
    *,
    operation: str,
    items: Sequence[Any] = (),
) -> LegalIRSplitGuardResult:
    resolved = manifest if isinstance(manifest, LegalIRSplitManifest) else LegalIRSplitManifest.from_mapping(manifest)
    result = require_legal_ir_split_guard(resolved, operation=operation)
    normalized_operation = str(operation or "").strip().lower()
    allowed = LEGAL_IR_SPLIT_OPERATION_ALLOWED_SPLITS.get(normalized_operation)
    if allowed is None:
        raise ValueError(f"unknown LegalIR split operation: {operation!r}")
    disallowed: list[dict[str, Any]] = []
    by_id = {item.sample_id: item for item in resolved.examples}
    for item in items:
        sample_ids = _sequence_strings(_get(item, "sample_ids", default=None))
        sample_id = _string(_get(item, "sample_id", "id", default=""))
        if sample_id:
            sample_ids = (*sample_ids, sample_id)
        if not sample_ids:
            citation = _string(_get(item, "citation", default=""))
            if citation:
                cluster = _citation_cluster(citation)
                sample_ids = tuple(
                    example.sample_id
                    for example in resolved.examples
                    if cluster in example.citation_clusters
                )
        if not sample_ids:
            source_key = _source_span_key(item)
            sample_ids = tuple(
                example.sample_id
                for example in resolved.examples
                if example.source_span_key == source_key and source_key
            )
        for sid in dict.fromkeys(sample_ids):
            split = resolved.assignments.get(sid)
            if split is None:
                disallowed.append({"reason": "sample_not_in_split_manifest", "sample_id": sid})
            elif split not in allowed:
                disallowed.append(
                    {
                        "allowed_splits": sorted(allowed),
                        "operation": normalized_operation,
                        "sample_id": sid,
                        "split": split,
                        "known_example": sid in by_id,
                    }
                )
    if disallowed:
        raise LegalIRSplitPolicyError(
            f"LegalIR split policy blocks {normalized_operation}",
            operation=normalized_operation,
            disallowed=disallowed,
        )
    return result


def require_training_split(
    manifest: LegalIRSplitManifest | Mapping[str, Any],
    items: Sequence[Any] = (),
) -> LegalIRSplitGuardResult:
    return authorize_legal_ir_split_use(manifest, operation=TRAINING_OPERATION, items=items)


def require_hparam_selection_split(
    manifest: LegalIRSplitManifest | Mapping[str, Any],
    items: Sequence[Any] = (),
) -> LegalIRSplitGuardResult:
    return authorize_legal_ir_split_use(
        manifest,
        operation=HPARAM_SELECTION_OPERATION,
        items=items,
    )


def require_representation_promotion_split(
    manifest: LegalIRSplitManifest | Mapping[str, Any],
    items: Sequence[Any] = (),
) -> LegalIRSplitGuardResult:
    return authorize_legal_ir_split_use(
        manifest,
        operation=REPRESENTATION_PROMOTION_OPERATION,
        items=items,
    )


def require_codex_todo_projection_split(
    manifest: LegalIRSplitManifest | Mapping[str, Any],
    items: Sequence[Any] = (),
) -> LegalIRSplitGuardResult:
    return authorize_legal_ir_split_use(
        manifest,
        operation=CODEX_TODO_PROJECTION_OPERATION,
        items=items,
    )


def split_guard_from_payload(payload: Mapping[str, Any]) -> LegalIRSplitGuardResult | None:
    """Decode a compact split guard block from rollout/projection payloads."""

    if "passed" in payload and (
        "violations" in payload or "blocked_operations" in payload
    ):
        value: Any = payload
    else:
        value = payload.get("legal_ir_split_guard")
    if not isinstance(value, Mapping):
        value = payload.get("split_guard")
    if not isinstance(value, Mapping):
        manifest = payload.get("legal_ir_split_manifest")
        if isinstance(manifest, Mapping):
            return validate_legal_ir_eval_splits(manifest)
        return None
    violations = tuple(
        LegalIRLeakageViolation(
            kind=_string(item.get("kind")),
            key=_string(item.get("key")),
            splits=tuple(_sequence_strings(item.get("splits"))),
            sample_ids_by_split={
                str(split): tuple(_sequence_strings(ids))
                for split, ids in (item.get("sample_ids_by_split") or {}).items()
            }
            if isinstance(item.get("sample_ids_by_split"), Mapping)
            else {},
            protected_splits=tuple(_sequence_strings(item.get("protected_splits"))),
        )
        for item in value.get("violations", ())
        if isinstance(item, Mapping)
    )
    blocked = tuple(_sequence_strings(value.get("blocked_operations")))
    return LegalIRSplitGuardResult(
        passed=value.get("passed") is True and not violations,
        violations=violations,
        blocked_operations=blocked,
    )


def split_guard_blocks_operation(
    payload: Mapping[str, Any],
    operation: str,
) -> bool:
    guard = split_guard_from_payload(payload)
    if guard is None:
        return False
    if not guard.passed:
        return True
    blocked = {item.strip().lower() for item in guard.blocked_operations}
    return str(operation or "").strip().lower() in blocked


__all__ = [
    "CANARY_SPLIT",
    "CODEX_TODO_PROJECTION_OPERATION",
    "EXTERNAL_TEST_SPLIT",
    "HOLDOUT_SPLIT",
    "HPARAM_SELECTION_OPERATION",
    "JURISDICTION_SPLIT",
    "LEGAL_IR_EVAL_SPLIT_SCHEMA_VERSION",
    "LEGAL_IR_EVAL_SPLITS",
    "PROTECTED_LEGAL_IR_SPLITS",
    "REPRESENTATION_PROMOTION_OPERATION",
    "STATUTE_FAMILY_SPLIT",
    "TEMPORAL_SPLIT",
    "TRAINING_OPERATION",
    "TRAIN_SPLIT",
    "VALIDATION_SPLIT",
    "LegalIREvalSplitConfig",
    "LegalIRLeakageViolation",
    "LegalIRSplitError",
    "LegalIRSplitExample",
    "LegalIRSplitGuardResult",
    "LegalIRSplitLeakageError",
    "LegalIRSplitManifest",
    "LegalIRSplitPolicyError",
    "authorize_legal_ir_split_use",
    "build_legal_ir_eval_splits",
    "require_codex_todo_projection_split",
    "require_hparam_selection_split",
    "require_legal_ir_split_guard",
    "require_representation_promotion_split",
    "require_training_split",
    "split_guard_blocks_operation",
    "split_guard_from_payload",
    "validate_legal_ir_eval_splits",
]
