"""Deterministic, leakage-safe data splits and retrieval partition fences.

Rows are grouped before assignment by every available source-family signal:
primary source, repository/document, exact content, declared duplicate family,
and generation family.  Near-duplicate detection consumes text only
transiently and persists bounded hashed shingles, never source bodies.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import urlparse

from ..schema import IntentIRDocument, validate_intent_ir


INTENT_SPLIT_MANIFEST_SCHEMA_VERSION: Final = "intent-split-manifest/v1"
INTENT_SPLIT_EXAMPLE_SCHEMA_VERSION: Final = "intent-split-example/v1"
INTENT_RETRIEVAL_FENCE_SCHEMA_VERSION: Final = "intent-retrieval-fence/v1"

TRAIN_PARTITION: Final = "train"
VALIDATION_PARTITION: Final = "validation"
TEST_PARTITION: Final = "test"
HELD_OUT_DOMAIN_PARTITION: Final = "held_out_domain"
HELD_OUT_TIME_REVISION_PARTITION: Final = "held_out_time_revision"
INTENT_PARTITIONS: Final = (
    TRAIN_PARTITION,
    VALIDATION_PARTITION,
    TEST_PARTITION,
    HELD_OUT_DOMAIN_PARTITION,
    HELD_OUT_TIME_REVISION_PARTITION,
)

# Split spellings are retained because evaluation callers commonly use either
# "split" or "partition"; the wire contract always serializes partition names.
TRAIN_SPLIT: Final = TRAIN_PARTITION
VALIDATION_SPLIT: Final = VALIDATION_PARTITION
TEST_SPLIT: Final = TEST_PARTITION
HELD_OUT_DOMAIN_SPLIT: Final = HELD_OUT_DOMAIN_PARTITION
HELD_OUT_TIME_REVISION_SPLIT: Final = HELD_OUT_TIME_REVISION_PARTITION

_MAX_GROUP_VALUES = 256
_MAX_VALUE_CHARS = 1024
_MAX_SHINGLES = 256
_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_SHINGLE_RE = re.compile(r"^[0-9a-f]{16}$")


class IntentSplitError(ValueError):
    """Base class for malformed split contracts."""


class IntentSplitLeakageError(IntentSplitError):
    """Raised when a manifest crosses a source-family boundary."""

    def __init__(self, message: str, result: "IntentSplitGuardResult") -> None:
        super().__init__(message)
        self.result = result


class IntentRetrievalFenceError(IntentSplitError):
    """Raised when retrieval could cross an evaluation partition or snapshot."""

    def __init__(self, message: str, result: "RetrievalFenceResult") -> None:
        super().__init__(message)
        self.result = result


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _get(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Sequence) and not isinstance(
        value, (bytes, bytearray)
    ):
        values = tuple(value)
    else:
        values = (value,)
    result = tuple(sorted({_text(item) for item in values if _text(item)}))
    if len(result) > _MAX_GROUP_VALUES:
        raise IntentSplitError(
            f"split grouping field exceeds {_MAX_GROUP_VALUES} values"
        )
    if any(len(item) > _MAX_VALUE_CHARS or "\x00" in item for item in result):
        raise IntentSplitError("split grouping values must be bounded text")
    return result


def _wire_values(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise IntentSplitError(f"{field_name} must be a sequence of strings")
    if any(not isinstance(item, str) for item in value):
        raise IntentSplitError(f"{field_name} must contain only strings")
    return _values(value)


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for candidate in (text, text[:10]):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            continue
    return None


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _content_digest(value: str) -> str:
    return _digest({"normalized_content": _normalized_text(value)})


def _hashed_shingles(value: str) -> tuple[str, ...]:
    """Return bounded non-plaintext token hashes for duplicate comparison."""

    tokens = re.findall(r"[\w]+", _normalized_text(value), flags=re.UNICODE)
    if not tokens:
        return ()
    hashes = sorted(
        {
            hashlib.blake2s(
                token.encode("utf-8"), digest_size=8, person=b"irfsplit"
            ).hexdigest()
            for token in tokens
        }
    )
    if len(hashes) <= _MAX_SHINGLES:
        return tuple(hashes)
    # Deterministic bottom-k sampling keeps manifests bounded and still lets
    # equivalent/near-equivalent documents compare in the same hash space.
    return tuple(hashes[:_MAX_SHINGLES])


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    left_set = frozenset(left)
    right_set = frozenset(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _repository_key(uri: str) -> str:
    text = _text(uri)
    if not text:
        return ""
    parsed = urlparse(text)
    host = parsed.netloc.casefold()
    parts = tuple(part for part in parsed.path.split("/") if part)
    if host in {"github.com", "www.github.com", "gitlab.com", "www.gitlab.com"}:
        if len(parts) >= 2:
            return f"{host.removeprefix('www.')}/{parts[0].casefold()}/{parts[1].casefold()}"
    if parsed.scheme == "hf" and host == "datasets":
        dataset = parsed.path.split("@", 1)[0].strip("/")
        return f"hf/datasets/{dataset.casefold()}" if dataset else ""
    return host


def _source_document_key(uri: str) -> str:
    text = _text(uri)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.netloc.casefold()}{parsed.path}".rstrip("/")
    return text


def _normalize_digest(value: str) -> str:
    match = _SHA256_RE.fullmatch(_text(value).casefold())
    return f"sha256:{match.group(1)}" if match else ""


def _sample_text(sample: Any) -> str:
    for name in (
        "near_duplicate_text",
        "normalized_text",
        "source_text",
        "raw_source",
        "body",
        "text",
        "skill_md",
        "content",
    ):
        value = _get(sample, name, default=None)
        if isinstance(value, str) and value:
            return value
    if isinstance(sample, IntentIRDocument):
        return "\n".join(
            item.normalized_text
            for item in sorted(
                sample.statements, key=lambda statement: statement.statement_id
            )
        )
    return ""


@dataclass(frozen=True, slots=True)
class IntentSplitExample:
    """Source-free grouping metadata for one evaluation row."""

    sample_id: str
    domain: str = ""
    primary_source_ids: tuple[str, ...] = ()
    repository_ids: tuple[str, ...] = ()
    source_document_ids: tuple[str, ...] = ()
    source_revisions: tuple[str, ...] = ()
    content_digests: tuple[str, ...] = ()
    duplicate_family_ids: tuple[str, ...] = ()
    generation_family_id: str = ""
    observed_date: str = ""
    near_duplicate_signature: tuple[str, ...] = ()
    graph_snapshot_id: str = ""
    embedding_snapshot_id: str = ""
    schema_version: str = INTENT_SPLIT_EXAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sample_id = _text(self.sample_id)
        if not sample_id or len(sample_id) > 512 or "\x00" in sample_id:
            raise IntentSplitError("sample_id must be bounded non-empty text")
        object.__setattr__(self, "sample_id", sample_id)
        object.__setattr__(self, "domain", _text(self.domain).casefold())
        for field_name in (
            "primary_source_ids",
            "repository_ids",
            "source_document_ids",
            "source_revisions",
            "duplicate_family_ids",
        ):
            object.__setattr__(self, field_name, _values(getattr(self, field_name)))
        digests = tuple(
            digest
            for digest in (
                _normalize_digest(item) for item in _values(self.content_digests)
            )
            if digest
        )
        if len(digests) != len(_values(self.content_digests)):
            raise IntentSplitError(
                "content_digests must contain lowercase SHA-256 values"
            )
        object.__setattr__(self, "content_digests", tuple(sorted(set(digests))))
        object.__setattr__(
            self,
            "near_duplicate_signature",
            tuple(sorted(set(_values(self.near_duplicate_signature)))),
        )
        if any(
            not _SHINGLE_RE.fullmatch(item)
            for item in self.near_duplicate_signature
        ):
            raise IntentSplitError(
                "near_duplicate_signature must contain hashed token values"
            )
        object.__setattr__(
            self, "generation_family_id", _text(self.generation_family_id)
        )
        parsed_date = _date(self.observed_date)
        if self.observed_date and parsed_date is None:
            raise IntentSplitError("observed_date must be an ISO-8601 date")
        object.__setattr__(
            self, "observed_date", parsed_date.isoformat() if parsed_date else ""
        )
        for field_name in ("graph_snapshot_id", "embedding_snapshot_id"):
            value = _text(getattr(self, field_name))
            if len(value) > _MAX_VALUE_CHARS or "\x00" in value:
                raise IntentSplitError(f"{field_name} must be bounded text")
            object.__setattr__(self, field_name, value)
        if self.schema_version != INTENT_SPLIT_EXAMPLE_SCHEMA_VERSION:
            raise IntentSplitError("unsupported Intent split example schema")

    @classmethod
    def from_sample(cls, sample: Any, **overrides: Any) -> "IntentSplitExample":
        """Project a document, record, or mapping to source-free split metadata."""

        if isinstance(sample, IntentIRDocument):
            document = validate_intent_ir(sample)
            sources = document.sources
            sample_id = document.document_id
            primary_ids = tuple(item.source_id for item in sources)
            revisions = tuple(item.source_revision for item in sources)
            content_digests = tuple(item.content_sha256 for item in sources)
            repository_ids = tuple(
                filter(
                    None,
                    (
                        _repository_key(item.source_uri)
                        or _repository_key(item.container_uri)
                        for item in sources
                    ),
                )
            )
            document_ids = tuple(
                filter(None, (_source_document_key(item.source_uri) for item in sources))
            )
        else:
            sample_id = _text(
                _get(sample, "sample_id", "example_id", "document_id", "skill_id")
            )
            primary_ids = _values(
                _get(sample, "primary_source_ids", "primary_source_id")
            )
            revisions = _values(
                _get(
                    sample,
                    "source_revisions",
                    "source_revision",
                    "dataset_revision",
                    "revision",
                )
            )
            content_digests = _values(
                _get(
                    sample,
                    "content_digests",
                    "content_sha256",
                    "source_sha256",
                )
            )
            explicit_repositories = _values(
                _get(sample, "repository_ids", "repository_id", "repository")
            )
            uri = _text(
                _get(sample, "source_uri", "source_url", "url", default="")
            )
            repository_ids = explicit_repositories or _values(
                _repository_key(uri)
            )
            document_ids = _values(
                _get(
                    sample,
                    "source_document_ids",
                    "source_document_id",
                    "source_id",
                    default="",
                )
            ) or _values(_source_document_key(uri))

        text = _sample_text(sample)
        normalized_digest = _content_digest(text) if text else ""
        known_digests = tuple(content_digests)
        if normalized_digest:
            known_digests = (*known_digests, normalized_digest)
        generation_family = _text(
            _get(
                sample,
                "generation_family_id",
                "generation_family",
                "prompt_model_hash",
                "generation_hash",
                default="",
            )
        )
        if not generation_family:
            prompt_hash = _text(_get(sample, "prompt_hash", default=""))
            model_hash = _text(_get(sample, "model_hash", default=""))
            if prompt_hash or model_hash:
                generation_family = _digest(
                    {"model_hash": model_hash, "prompt_hash": prompt_hash}
                )

        values = {
            "sample_id": sample_id,
            "domain": _text(_get(sample, "domain", default="")),
            "primary_source_ids": primary_ids,
            "repository_ids": repository_ids,
            "source_document_ids": document_ids,
            "source_revisions": revisions,
            "content_digests": known_digests,
            "duplicate_family_ids": _values(
                _get(
                    sample,
                    "duplicate_family_ids",
                    "duplicate_family_id",
                    "near_duplicate_cluster_id",
                    "dedup_cluster_id",
                    default=(),
                )
            ),
            "generation_family_id": generation_family,
            "observed_date": _text(
                _get(
                    sample,
                    "observed_date",
                    "revision_date",
                    "updated_at",
                    "created_at",
                    "date",
                    default="",
                )
            ),
            "near_duplicate_signature": _hashed_shingles(text),
            "graph_snapshot_id": _text(
                _get(sample, "graph_snapshot_id", default="")
            ),
            "embedding_snapshot_id": _text(
                _get(sample, "embedding_snapshot_id", default="")
            ),
        }
        values.update(overrides)
        return cls(**values)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntentSplitExample":
        allowed = {
            "content_digests",
            "domain",
            "duplicate_family_ids",
            "embedding_snapshot_id",
            "generation_family_id",
            "graph_snapshot_id",
            "near_duplicate_signature",
            "observed_date",
            "primary_source_ids",
            "repository_ids",
            "sample_id",
            "schema_version",
            "source_document_ids",
            "source_revisions",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise IntentSplitError(
                "unknown Intent split example fields: " + ", ".join(unknown)
            )
        return cls(
            sample_id=value.get("sample_id", ""),
            domain=value.get("domain", ""),
            primary_source_ids=_wire_values(
                value.get("primary_source_ids", ()), "primary_source_ids"
            ),
            repository_ids=_wire_values(
                value.get("repository_ids", ()), "repository_ids"
            ),
            source_document_ids=_wire_values(
                value.get("source_document_ids", ()), "source_document_ids"
            ),
            source_revisions=_wire_values(
                value.get("source_revisions", ()), "source_revisions"
            ),
            content_digests=_wire_values(
                value.get("content_digests", ()), "content_digests"
            ),
            duplicate_family_ids=_wire_values(
                value.get("duplicate_family_ids", ()), "duplicate_family_ids"
            ),
            generation_family_id=value.get("generation_family_id", ""),
            observed_date=value.get("observed_date", ""),
            near_duplicate_signature=_wire_values(
                value.get("near_duplicate_signature", ()),
                "near_duplicate_signature",
            ),
            graph_snapshot_id=value.get("graph_snapshot_id", ""),
            embedding_snapshot_id=value.get("embedding_snapshot_id", ""),
            schema_version=value.get(
                "schema_version", INTENT_SPLIT_EXAMPLE_SCHEMA_VERSION
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digests": list(self.content_digests),
            "domain": self.domain,
            "duplicate_family_ids": list(self.duplicate_family_ids),
            "embedding_snapshot_id": self.embedding_snapshot_id,
            "generation_family_id": self.generation_family_id,
            "graph_snapshot_id": self.graph_snapshot_id,
            "near_duplicate_signature": list(self.near_duplicate_signature),
            "observed_date": self.observed_date,
            "primary_source_ids": list(self.primary_source_ids),
            "repository_ids": list(self.repository_ids),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "source_document_ids": list(self.source_document_ids),
            "source_revisions": list(self.source_revisions),
        }


@dataclass(frozen=True, slots=True)
class IntentSplitConfig:
    """Policy for deterministic source-family partition assignment."""

    seed: str = "intent-ir-splits"
    train_ratio: float = 0.70
    validation_ratio: float = 0.15
    test_ratio: float = 0.15
    held_out_domains: tuple[str, ...] = ()
    temporal_holdout_after: str = ""
    held_out_revisions: tuple[str, ...] = ()
    near_duplicate_jaccard_threshold: float = 0.80

    def __post_init__(self) -> None:
        ratios = (self.train_ratio, self.validation_ratio, self.test_ratio)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
            for value in ratios
        ):
            raise IntentSplitError("split ratios must be finite and non-negative")
        if sum(float(value) for value in ratios) <= 0.0:
            raise IntentSplitError("at least one primary split ratio must be positive")
        threshold = float(self.near_duplicate_jaccard_threshold)
        if not 0.0 < threshold <= 1.0 or not math.isfinite(threshold):
            raise IntentSplitError(
                "near_duplicate_jaccard_threshold must be in (0, 1]"
            )
        cutoff = _date(self.temporal_holdout_after)
        if self.temporal_holdout_after and cutoff is None:
            raise IntentSplitError(
                "temporal_holdout_after must be an ISO-8601 date"
            )
        object.__setattr__(self, "seed", _text(self.seed))
        object.__setattr__(
            self,
            "held_out_domains",
            tuple(item.casefold() for item in _values(self.held_out_domains)),
        )
        object.__setattr__(
            self, "held_out_revisions", _values(self.held_out_revisions)
        )
        object.__setattr__(
            self,
            "temporal_holdout_after",
            cutoff.isoformat() if cutoff else "",
        )
        object.__setattr__(
            self, "near_duplicate_jaccard_threshold", threshold
        )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    @property
    def cutoff_date(self) -> date | None:
        return _date(self.temporal_holdout_after)

    def to_dict(self) -> dict[str, Any]:
        return {
            "held_out_domains": list(self.held_out_domains),
            "held_out_revisions": list(self.held_out_revisions),
            "near_duplicate_jaccard_threshold": (
                self.near_duplicate_jaccard_threshold
            ),
            "seed": self.seed,
            "temporal_holdout_after": self.temporal_holdout_after,
            "test_ratio": self.test_ratio,
            "train_ratio": self.train_ratio,
            "validation_ratio": self.validation_ratio,
        }


@dataclass(frozen=True, slots=True)
class IntentLeakageViolation:
    kind: str
    key: str
    partitions: tuple[str, ...]
    sample_ids_by_partition: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sample_ids_by_partition",
            MappingProxyType(
                {
                    key: tuple(value)
                    for key, value in sorted(
                        self.sample_ids_by_partition.items()
                    )
                }
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "partitions": list(self.partitions),
            "sample_ids_by_partition": {
                partition: list(ids)
                for partition, ids in self.sample_ids_by_partition.items()
            },
        }


@dataclass(frozen=True, slots=True)
class IntentSplitGuardResult:
    passed: bool
    violations: tuple[IntentLeakageViolation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [item.to_dict() for item in self.violations],
        }


@dataclass(frozen=True, slots=True)
class IntentSplitManifest:
    """Immutable assignments plus the source-free evidence needed to audit them."""

    examples: tuple[IntentSplitExample, ...]
    assignments: Mapping[str, str]
    config_digest: str
    partitions: tuple[str, ...] = INTENT_PARTITIONS
    metadata: Mapping[str, Any] = field(default_factory=dict)
    assignment_conflicts: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    schema_version: str = INTENT_SPLIT_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != INTENT_SPLIT_MANIFEST_SCHEMA_VERSION:
            raise IntentSplitError("unsupported Intent split manifest schema")
        if not isinstance(self.examples, tuple):
            raise IntentSplitError("split examples must be an immutable tuple")
        normalized_examples: list[IntentSplitExample] = []
        for item in self.examples:
            if isinstance(item, IntentSplitExample):
                normalized_examples.append(item)
            elif isinstance(item, Mapping):
                normalized_examples.append(IntentSplitExample.from_dict(item))
            else:
                raise IntentSplitError(
                    "split examples must contain IntentSplitExample records "
                    "or mappings"
                )
        examples = tuple(
            sorted(normalized_examples, key=lambda item: item.sample_id)
        )
        sample_ids = tuple(item.sample_id for item in examples)
        if len(sample_ids) != len(set(sample_ids)):
            raise IntentSplitError("split examples must have unique sample IDs")
        if not isinstance(self.assignments, Mapping):
            raise IntentSplitError("assignments must be a mapping")
        assignments = {
            _text(sample_id): _text(partition)
            for sample_id, partition in self.assignments.items()
        }
        unknown = sorted(set(assignments.values()) - set(INTENT_PARTITIONS))
        if unknown:
            raise IntentSplitError(f"unknown Intent partitions: {unknown}")
        missing = sorted(set(sample_ids) - set(assignments))
        extra = sorted(set(assignments) - set(sample_ids))
        if missing or extra:
            raise IntentSplitError(
                f"assignments must exactly cover examples; missing={missing[:5]}, "
                f"extra={extra[:5]}"
            )
        partitions = tuple(self.partitions)
        if partitions != INTENT_PARTITIONS:
            raise IntentSplitError(
                "partitions must exactly match the versioned Intent vocabulary"
            )
        config_digest = _text(self.config_digest)
        if (
            not config_digest
            or len(config_digest) > _MAX_VALUE_CHARS
            or "\x00" in config_digest
        ):
            raise IntentSplitError("config_digest must be bounded non-empty text")
        if not isinstance(self.assignment_conflicts, Mapping):
            raise IntentSplitError("assignment_conflicts must be a mapping")
        conflicts = {
            _text(sample_id): tuple(
                sorted(set(_values(candidate_partitions)))
            )
            for sample_id, candidate_partitions in self.assignment_conflicts.items()
            if len(set(_values(candidate_partitions))) > 1
        }
        invalid_conflict_partitions = sorted(
            {
                partition
                for partitions_for_sample in conflicts.values()
                for partition in partitions_for_sample
                if partition not in INTENT_PARTITIONS
            }
        )
        if invalid_conflict_partitions:
            raise IntentSplitError(
                "assignment conflicts contain unknown partitions: "
                + ", ".join(invalid_conflict_partitions)
            )
        if not isinstance(self.metadata, Mapping) or any(
            not isinstance(key, str) for key in self.metadata
        ):
            raise IntentSplitError("split metadata must be a string-keyed mapping")
        metadata = dict(self.metadata)
        unknown_metadata = sorted(
            set(metadata) - {"near_duplicate_jaccard_threshold", "seed"}
        )
        if unknown_metadata:
            raise IntentSplitError(
                "unknown Intent split metadata fields: "
                + ", ".join(unknown_metadata)
            )
        if "seed" in metadata and (
            not isinstance(metadata["seed"], str)
            or len(metadata["seed"]) > _MAX_VALUE_CHARS
            or "\x00" in metadata["seed"]
        ):
            raise IntentSplitError("split metadata seed must be bounded text")
        if "near_duplicate_jaccard_threshold" in metadata:
            threshold = metadata["near_duplicate_jaccard_threshold"]
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
                or not math.isfinite(float(threshold))
                or not 0.0 < float(threshold) <= 1.0
            ):
                raise IntentSplitError(
                    "split metadata duplicate threshold must be in (0, 1]"
                )
        object.__setattr__(self, "examples", examples)
        object.__setattr__(
            self, "assignments", MappingProxyType(dict(sorted(assignments.items())))
        )
        object.__setattr__(self, "config_digest", config_digest)
        object.__setattr__(self, "partitions", partitions)
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(sorted(metadata.items())))
        )
        object.__setattr__(
            self,
            "assignment_conflicts",
            MappingProxyType(dict(sorted(conflicts.items()))),
        )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    @property
    def samples_by_partition(self) -> Mapping[str, tuple[str, ...]]:
        result: dict[str, list[str]] = {item: [] for item in self.partitions}
        for sample_id, partition in self.assignments.items():
            result[partition].append(sample_id)
        return MappingProxyType(
            {
                partition: tuple(sorted(sample_ids))
                for partition, sample_ids in result.items()
            }
        )

    @property
    def samples_by_split(self) -> Mapping[str, tuple[str, ...]]:
        return self.samples_by_partition

    def partition_of(self, sample_id: str) -> str:
        try:
            return self.assignments[sample_id]
        except KeyError:
            raise IntentSplitError(
                f"sample {sample_id!r} is absent from the split manifest"
            ) from None

    def guard_result(self) -> IntentSplitGuardResult:
        return validate_intent_splits(self)

    def require_valid(self) -> IntentSplitGuardResult:
        return require_leakage_safe_splits(self)

    def authorize_retrieval(
        self,
        query_sample_id: str,
        candidate_sample_ids: Sequence[str],
        *,
        graph_snapshot_id: str = "",
        embedding_snapshot_id: str = "",
    ) -> "IntentRetrievalPartitionFence":
        return require_retrieval_partition_fence(
            self,
            query_sample_id,
            candidate_sample_ids,
            graph_snapshot_id=graph_snapshot_id,
            embedding_snapshot_id=embedding_snapshot_id,
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "assignment_conflicts": {
                sample_id: list(partitions)
                for sample_id, partitions in self.assignment_conflicts.items()
            },
            "assignments": dict(self.assignments),
            "config_digest": self.config_digest,
            "examples": [item.to_dict() for item in self.examples],
            "metadata": dict(self.metadata),
            "partitions": list(self.partitions),
            "samples_by_partition": {
                partition: list(sample_ids)
                for partition, sample_ids in self.samples_by_partition.items()
            },
            "schema_version": self.schema_version,
        }
        if include_digest:
            result["manifest_digest"] = self.digest
            result["split_guard"] = self.guard_result().to_dict()
        return result

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntentSplitManifest":
        allowed = {
            "assignment_conflicts",
            "assignments",
            "config_digest",
            "examples",
            "manifest_digest",
            "metadata",
            "partitions",
            "samples_by_partition",
            "samples_by_split",
            "schema_version",
            "split_guard",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise IntentSplitError(
                "unknown Intent split manifest fields: " + ", ".join(unknown)
            )
        examples = tuple(
            IntentSplitExample.from_dict(item)
            for item in value.get("examples", ())
            if isinstance(item, Mapping)
        )
        assignments = value.get("assignments")
        conflicts: dict[str, tuple[str, ...]] = {}
        if not isinstance(assignments, Mapping):
            assignments = {}
            grouped = value.get(
                "samples_by_partition", value.get("samples_by_split", {})
            )
            seen: dict[str, list[str]] = defaultdict(list)
            if isinstance(grouped, Mapping):
                for partition, sample_ids in grouped.items():
                    for sample_id in _values(sample_ids):
                        seen[sample_id].append(_text(partition))
                        assignments[sample_id] = _text(partition)
            conflicts = {
                sample_id: tuple(partitions)
                for sample_id, partitions in seen.items()
                if len(set(partitions)) > 1
            }
        raw_conflicts = value.get("assignment_conflicts", {})
        if isinstance(raw_conflicts, Mapping):
            conflicts.update(
                {
                    _text(sample_id): _values(partitions)
                    for sample_id, partitions in raw_conflicts.items()
                }
            )
        return cls(
            examples=examples,
            assignments=assignments,
            config_digest=_text(value.get("config_digest")),
            partitions=tuple(value.get("partitions", INTENT_PARTITIONS)),
            metadata=(
                value.get("metadata", {})
                if isinstance(value.get("metadata", {}), Mapping)
                else {}
            ),
            assignment_conflicts=conflicts,
            schema_version=value.get(
                "schema_version", INTENT_SPLIT_MANIFEST_SCHEMA_VERSION
            ),
        )


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
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


def _union_values(
    union_find: _UnionFind,
    examples: Sequence[IntentSplitExample],
    values: Any,
) -> None:
    seen: dict[str, str] = {}
    for example in examples:
        for key in values(example):
            previous = seen.setdefault(key, example.sample_id)
            union_find.union(previous, example.sample_id)


def _bucket(*values: str) -> float:
    digest = hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()
    return int(digest[:13], 16) / float(16**13)


def _choose_partition(
    group_id: str,
    examples: Sequence[IntentSplitExample],
    config: IntentSplitConfig,
) -> str:
    cutoff = config.cutoff_date
    held_revisions = frozenset(config.held_out_revisions)
    if any(
        set(item.source_revisions) & held_revisions
        or (
            cutoff is not None
            and bool(item.observed_date)
            and _date(item.observed_date) is not None
            and _date(item.observed_date) > cutoff
        )
        for item in examples
    ):
        return HELD_OUT_TIME_REVISION_PARTITION
    if any(item.domain in config.held_out_domains for item in examples):
        return HELD_OUT_DOMAIN_PARTITION

    ratios = (
        (TRAIN_PARTITION, float(config.train_ratio)),
        (VALIDATION_PARTITION, float(config.validation_ratio)),
        (TEST_PARTITION, float(config.test_ratio)),
    )
    total = sum(weight for _, weight in ratios)
    value = _bucket(config.seed, "primary", group_id) * total
    boundary = 0.0
    for partition, weight in ratios:
        boundary += weight
        if value < boundary:
            return partition
    return ratios[-1][0]  # pragma: no cover - floating-point guard


def build_intent_splits(
    samples: Sequence[Any],
    config: IntentSplitConfig | None = None,
) -> IntentSplitManifest:
    """Group source variants and duplicates before deterministic assignment."""

    resolved = config or IntentSplitConfig()
    examples = tuple(
        sorted(
            (
                item
                if isinstance(item, IntentSplitExample)
                else IntentSplitExample.from_sample(item)
                for item in samples
            ),
            key=lambda item: item.sample_id,
        )
    )
    sample_ids = tuple(item.sample_id for item in examples)
    if len(sample_ids) != len(set(sample_ids)):
        raise IntentSplitError("split input sample IDs must be unique")
    union_find = _UnionFind(sample_ids)
    for values in (
        lambda item: item.primary_source_ids,
        lambda item: item.repository_ids,
        lambda item: item.source_document_ids,
        lambda item: item.content_digests,
        lambda item: item.duplicate_family_ids,
        lambda item: (item.generation_family_id,)
        if item.generation_family_id
        else (),
    ):
        _union_values(union_find, examples, values)
    for index, left in enumerate(examples):
        for right in examples[index + 1 :]:
            if (
                _jaccard(
                    left.near_duplicate_signature,
                    right.near_duplicate_signature,
                )
                >= resolved.near_duplicate_jaccard_threshold
            ):
                union_find.union(left.sample_id, right.sample_id)

    groups: dict[str, list[IntentSplitExample]] = defaultdict(list)
    for example in examples:
        groups[union_find.find(example.sample_id)].append(example)
    assignments: dict[str, str] = {}
    for group_id, members in sorted(groups.items()):
        partition = _choose_partition(group_id, members, resolved)
        for member in members:
            assignments[member.sample_id] = partition
    manifest = IntentSplitManifest(
        examples=examples,
        assignments=assignments,
        config_digest=resolved.digest,
        metadata={
            "near_duplicate_jaccard_threshold": (
                resolved.near_duplicate_jaccard_threshold
            ),
            "seed": resolved.seed,
        },
    )
    require_leakage_safe_splits(manifest)
    return manifest


build_intent_split_manifest = build_intent_splits


def validate_intent_splits(
    manifest: IntentSplitManifest | Mapping[str, Any],
) -> IntentSplitGuardResult:
    """Audit all persisted grouping signals and adversarial duplicates."""

    resolved = (
        manifest
        if isinstance(manifest, IntentSplitManifest)
        else IntentSplitManifest.from_dict(manifest)
    )
    assignments = resolved.assignments
    violations: list[IntentLeakageViolation] = []

    def add(kind: str, key: str, sample_ids: Iterable[str]) -> None:
        by_partition: dict[str, list[str]] = defaultdict(list)
        for sample_id in sorted(set(sample_ids)):
            partition = assignments.get(sample_id)
            if partition:
                by_partition[partition].append(sample_id)
        if len(by_partition) <= 1:
            return
        violations.append(
            IntentLeakageViolation(
                kind=kind,
                key=key,
                partitions=tuple(sorted(by_partition)),
                sample_ids_by_partition={
                    partition: tuple(sorted(ids))
                    for partition, ids in sorted(by_partition.items())
                },
            )
        )

    for sample_id, partitions in resolved.assignment_conflicts.items():
        if len(set(partitions)) > 1:
            violations.append(
                IntentLeakageViolation(
                    kind="assignment",
                    key=sample_id,
                    partitions=tuple(sorted(set(partitions))),
                    sample_ids_by_partition={
                        partition: (sample_id,)
                        for partition in sorted(set(partitions))
                    },
                )
            )

    indexes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for example in resolved.examples:
        for kind, values in (
            ("primary_source", example.primary_source_ids),
            ("repository", example.repository_ids),
            ("source_document", example.source_document_ids),
            ("content", example.content_digests),
            ("duplicate_family", example.duplicate_family_ids),
        ):
            for key in values:
                indexes[(kind, key)].append(example.sample_id)
        if example.generation_family_id:
            indexes[
                ("generation_family", example.generation_family_id)
            ].append(example.sample_id)
    for (kind, key), sample_ids in sorted(indexes.items()):
        add(kind, key, sample_ids)

    threshold = float(
        resolved.metadata.get("near_duplicate_jaccard_threshold", 0.80)
    )
    for index, left in enumerate(resolved.examples):
        for right in resolved.examples[index + 1 :]:
            similarity = _jaccard(
                left.near_duplicate_signature, right.near_duplicate_signature
            )
            if (
                similarity >= threshold
                and assignments[left.sample_id] != assignments[right.sample_id]
            ):
                add(
                    "near_duplicate",
                    _digest(
                        {
                            "left": left.sample_id,
                            "right": right.sample_id,
                            "threshold": threshold,
                        }
                    ),
                    (left.sample_id, right.sample_id),
                )

    unique = {
        (item.kind, item.key, item.partitions): item for item in violations
    }
    ordered = tuple(
        sorted(unique.values(), key=lambda item: (item.kind, item.key))
    )
    return IntentSplitGuardResult(passed=not ordered, violations=ordered)


validate_intent_split_manifest = validate_intent_splits


def require_leakage_safe_splits(
    manifest: IntentSplitManifest | Mapping[str, Any],
) -> IntentSplitGuardResult:
    result = validate_intent_splits(manifest)
    if not result.passed:
        raise IntentSplitLeakageError(
            "Intent split manifest crosses a source-family partition boundary",
            result,
        )
    return result


@dataclass(frozen=True, slots=True)
class RetrievalFenceViolation:
    candidate_sample_id: str
    reason: str
    candidate_partition: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "candidate_partition": self.candidate_partition,
            "candidate_sample_id": self.candidate_sample_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RetrievalFenceResult:
    passed: bool
    query_sample_id: str
    query_partition: str
    violations: tuple[RetrievalFenceViolation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "query_partition": self.query_partition,
            "query_sample_id": self.query_sample_id,
            "violations": [item.to_dict() for item in self.violations],
        }


@dataclass(frozen=True, slots=True)
class IntentRetrievalPartitionFence:
    """Receipt proving a bounded candidate set stayed in one partition."""

    manifest_digest: str
    query_sample_id: str
    partition: str
    candidate_sample_ids: tuple[str, ...]
    graph_snapshot_id: str = ""
    embedding_snapshot_id: str = ""
    schema_version: str = INTENT_RETRIEVAL_FENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.partition not in INTENT_PARTITIONS:
            raise IntentSplitError("retrieval fence has an unknown partition")
        if self.schema_version != INTENT_RETRIEVAL_FENCE_SCHEMA_VERSION:
            raise IntentSplitError("unsupported retrieval fence schema")
        object.__setattr__(
            self,
            "candidate_sample_ids",
            tuple(sorted(set(self.candidate_sample_ids))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_sample_ids": list(self.candidate_sample_ids),
            "embedding_snapshot_id": self.embedding_snapshot_id,
            "graph_snapshot_id": self.graph_snapshot_id,
            "manifest_digest": self.manifest_digest,
            "partition": self.partition,
            "query_sample_id": self.query_sample_id,
            "schema_version": self.schema_version,
        }


def validate_retrieval_partition_fence(
    manifest: IntentSplitManifest | Mapping[str, Any],
    query_sample_id: str,
    candidate_sample_ids: Sequence[str],
    *,
    graph_snapshot_id: str = "",
    embedding_snapshot_id: str = "",
) -> RetrievalFenceResult:
    """Check candidates against partition and immutable snapshot boundaries."""

    resolved = (
        manifest
        if isinstance(manifest, IntentSplitManifest)
        else IntentSplitManifest.from_dict(manifest)
    )
    query_id = _text(query_sample_id)
    query_partition = resolved.assignments.get(query_id, "")
    examples = {item.sample_id: item for item in resolved.examples}
    violations: list[RetrievalFenceViolation] = []
    manifest_guard = validate_intent_splits(resolved)
    if not manifest_guard.passed:
        violations.append(
            RetrievalFenceViolation(
                candidate_sample_id="",
                reason="split_manifest_has_leakage",
            )
        )
    query = examples.get(query_id)
    if query is None or not query_partition:
        violations.append(
            RetrievalFenceViolation(
                candidate_sample_id=query_id,
                reason="query_not_in_manifest",
            )
        )
    expected_graph = _text(graph_snapshot_id) or (
        query.graph_snapshot_id if query else ""
    )
    expected_embedding = _text(embedding_snapshot_id) or (
        query.embedding_snapshot_id if query else ""
    )
    if (
        query is not None
        and graph_snapshot_id
        and query.graph_snapshot_id != _text(graph_snapshot_id)
    ):
        violations.append(
            RetrievalFenceViolation(
                candidate_sample_id=query_id,
                candidate_partition=query_partition,
                reason="query_graph_snapshot_mismatch",
            )
        )
    if (
        query is not None
        and embedding_snapshot_id
        and query.embedding_snapshot_id != _text(embedding_snapshot_id)
    ):
        violations.append(
            RetrievalFenceViolation(
                candidate_sample_id=query_id,
                candidate_partition=query_partition,
                reason="query_embedding_snapshot_mismatch",
            )
        )
    for candidate_id in tuple(dict.fromkeys(_values(candidate_sample_ids))):
        candidate = examples.get(candidate_id)
        candidate_partition = resolved.assignments.get(candidate_id, "")
        if candidate is None or not candidate_partition:
            violations.append(
                RetrievalFenceViolation(
                    candidate_sample_id=candidate_id,
                    reason="candidate_not_in_manifest",
                )
            )
            continue
        if candidate_partition != query_partition:
            violations.append(
                RetrievalFenceViolation(
                    candidate_sample_id=candidate_id,
                    candidate_partition=candidate_partition,
                    reason="cross_partition",
                )
            )
        if expected_graph and candidate.graph_snapshot_id != expected_graph:
            violations.append(
                RetrievalFenceViolation(
                    candidate_sample_id=candidate_id,
                    candidate_partition=candidate_partition,
                    reason="graph_snapshot_mismatch",
                )
            )
        if (
            expected_embedding
            and candidate.embedding_snapshot_id != expected_embedding
        ):
            violations.append(
                RetrievalFenceViolation(
                    candidate_sample_id=candidate_id,
                    candidate_partition=candidate_partition,
                    reason="embedding_snapshot_mismatch",
                )
            )
    ordered = tuple(
        sorted(
            violations,
            key=lambda item: (
                item.candidate_sample_id,
                item.reason,
                item.candidate_partition,
            ),
        )
    )
    return RetrievalFenceResult(
        passed=not ordered,
        query_sample_id=query_id,
        query_partition=query_partition,
        violations=ordered,
    )


def require_retrieval_partition_fence(
    manifest: IntentSplitManifest | Mapping[str, Any],
    query_sample_id: str,
    candidate_sample_ids: Sequence[str],
    *,
    graph_snapshot_id: str = "",
    embedding_snapshot_id: str = "",
) -> IntentRetrievalPartitionFence:
    result = validate_retrieval_partition_fence(
        manifest,
        query_sample_id,
        candidate_sample_ids,
        graph_snapshot_id=graph_snapshot_id,
        embedding_snapshot_id=embedding_snapshot_id,
    )
    if not result.passed:
        raise IntentRetrievalFenceError(
            "Intent retrieval crossed a partition or snapshot fence", result
        )
    resolved = (
        manifest
        if isinstance(manifest, IntentSplitManifest)
        else IntentSplitManifest.from_dict(manifest)
    )
    query = {
        item.sample_id: item for item in resolved.examples
    }[result.query_sample_id]
    return IntentRetrievalPartitionFence(
        manifest_digest=resolved.digest,
        query_sample_id=result.query_sample_id,
        partition=result.query_partition,
        candidate_sample_ids=_values(candidate_sample_ids),
        graph_snapshot_id=_text(graph_snapshot_id) or query.graph_snapshot_id,
        embedding_snapshot_id=(
            _text(embedding_snapshot_id) or query.embedding_snapshot_id
        ),
    )


enforce_retrieval_partition_fence = require_retrieval_partition_fence


__all__ = [
    "HELD_OUT_DOMAIN_PARTITION",
    "HELD_OUT_DOMAIN_SPLIT",
    "HELD_OUT_TIME_REVISION_PARTITION",
    "HELD_OUT_TIME_REVISION_SPLIT",
    "INTENT_PARTITIONS",
    "INTENT_RETRIEVAL_FENCE_SCHEMA_VERSION",
    "INTENT_SPLIT_EXAMPLE_SCHEMA_VERSION",
    "INTENT_SPLIT_MANIFEST_SCHEMA_VERSION",
    "TEST_PARTITION",
    "TEST_SPLIT",
    "TRAIN_PARTITION",
    "TRAIN_SPLIT",
    "VALIDATION_PARTITION",
    "VALIDATION_SPLIT",
    "IntentLeakageViolation",
    "IntentRetrievalFenceError",
    "IntentRetrievalPartitionFence",
    "IntentSplitConfig",
    "IntentSplitError",
    "IntentSplitExample",
    "IntentSplitGuardResult",
    "IntentSplitLeakageError",
    "IntentSplitManifest",
    "RetrievalFenceResult",
    "RetrievalFenceViolation",
    "build_intent_split_manifest",
    "build_intent_splits",
    "enforce_retrieval_partition_fence",
    "require_leakage_safe_splits",
    "require_retrieval_partition_fence",
    "validate_intent_split_manifest",
    "validate_intent_splits",
    "validate_retrieval_partition_fence",
]
