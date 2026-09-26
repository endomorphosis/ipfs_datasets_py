"""Frozen cross-batch partitions over a bounded, declared source selection.

The index stores source metadata and exact record/sample/embedding digests, not
training text or vectors. Connected document lineages, source artifacts and
normalized content share one partition. Assignments are fixed by an integer
policy and seed before training; empty partitions fail selection rather than
triggering resampling. Existing batch identities and model/proof success are
unchanged.

Index integrity establishes isolation only within its enumerated selection.
It does not authenticate source authority or embedding producers, prove federal
corpus completeness, find semantic paraphrases, or attest unseen model lineage.
Consequently this module never claims a globally held-out result or an admit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .autoencoder_corpus_manifest import (
    CorpusManifest, CorpusManifestError, EmbeddingProvenance, SourceSampleRecord, SourceSpan,
)
from .legal_ir_eval_splits import (
    CANARY_SPLIT, HOLDOUT_SPLIT, HPARAM_SELECTION_OPERATION,
    LEGAL_IR_SPLIT_OPERATION_ALLOWED_SPLITS, TRAIN_SPLIT, TRAINING_OPERATION, VALIDATION_SPLIT,
)


SCHEMA_VERSION = "autoencoder-corpus-selection-index-v1"
GROUPING_SCHEMA = "document-source-content-connected-groups-v1"
CONTENT_NORMALIZATION = "unicode-whitespace-casefold-v1"
SPLITS = (TRAIN_SPLIT, VALIDATION_SPLIT, CANARY_SPLIT, HOLDOUT_SPLIT)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RECORD_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


class CorpusIndexError(ValueError):
    """Invalid, corrupt, over-budget or mismatched frozen index membership."""


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise CorpusIndexError("invalid strict index JSON") from exc


def _parse(raw: bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise CorpusIndexError("duplicate JSON field")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(CorpusIndexError("nonfinite JSON value")))
    except (UnicodeError, ValueError, RecursionError, OverflowError) as exc:
        raise CorpusIndexError("invalid index JSON") from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise CorpusIndexError(f"{name} must be a lowercase SHA-256")
    return value


def _keys(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise CorpusIndexError(f"{name} has unknown or missing fields")
    return dict(value)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class IndexLimits:
    max_records: int = 65536
    max_index_bytes: int = 64 * 1024 * 1024
    max_release_manifests: int = 128

    def __post_init__(self):
        for name, maximum in (("max_records", 65536), ("max_index_bytes", 64 * 1024 * 1024),
                              ("max_release_manifests", 128)):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= maximum:
                raise CorpusIndexError(f"{name} exceeds the bounded index contract")


@dataclass(frozen=True)
class IndexScope:
    """Caller-declared release roots and exact selection identity, never completeness."""

    selection_sha256: str
    release_manifest_sha256s: tuple[str, ...]
    completeness: str = "selected_subset"

    def __post_init__(self):
        _digest(self.selection_sha256, "scope.selection_sha256")
        refs = self.release_manifest_sha256s
        if not isinstance(refs, (list, tuple)) or not 1 <= len(refs) <= 128:
            raise CorpusIndexError("scope requires bounded release manifest identities")
        for item in refs:
            _digest(item, "scope.release_manifest_sha256")
        if len(set(refs)) != len(refs):
            raise CorpusIndexError("duplicate release manifest identity")
        if self.completeness != "selected_subset":
            raise CorpusIndexError("index scope completeness must be selected_subset")
        object.__setattr__(self, "release_manifest_sha256s", tuple(sorted(refs)))

    def to_dict(self):
        return {"selection_sha256": self.selection_sha256,
                "release_manifest_sha256s": list(self.release_manifest_sha256s), "completeness": self.completeness}

    @classmethod
    def from_dict(cls, value):
        return cls(**_keys(value, {"selection_sha256", "release_manifest_sha256s", "completeness"}, "scope"))


@dataclass(frozen=True)
class SplitPolicy:
    """Integer basis points; the seed and proportions must be frozen before use."""

    seed: str
    train: int = 8000
    validation: int = 1000
    canary: int = 500
    holdout: int = 500

    def __post_init__(self):
        if not isinstance(self.seed, str) or not self.seed.strip() or len(self.seed.encode("utf-8")) > 4096:
            raise CorpusIndexError("policy.seed must be bounded nonempty text")
        values = [getattr(self, split) for split in SPLITS]
        if any(type(value) is not int or not 0 <= value <= 10000 for value in values) or sum(values) != 10000:
            raise CorpusIndexError("split proportions must be integer basis points summing to 10000")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**_keys(value, {"seed", *SPLITS}, "split policy"))


def _summary(record: SourceSampleRecord) -> dict[str, Any]:
    if not isinstance(record, SourceSampleRecord):
        raise CorpusIndexError("index records must be immutable SourceSampleRecord objects")
    payload = record.to_dict()
    # The existing record codec represents floats by exact float64 bits, so
    # equal-valued integers, floats and signed zero keep distinct identities.
    return {"record_id": record.record_id, "source": payload["source"],
            "sample_payload_sha256": _sha(_json(payload["sample"])),
            "embedding_provenance": payload["embedding_provenance"],
            "normalized_content_sha256": _sha(" ".join(record.sample.text.split()).casefold().encode("utf-8"))}


def _validate_summary(value: Any) -> dict[str, Any]:
    result = _keys(value, {"record_id", "source", "sample_payload_sha256", "embedding_provenance",
                           "normalized_content_sha256"}, "record summary")
    if not isinstance(result["record_id"], str) or not _RECORD_ID.fullmatch(result["record_id"]):
        raise CorpusIndexError("record identity must be a full source-aware SHA-256")
    _digest(result["sample_payload_sha256"], "sample_payload_sha256")
    _digest(result["normalized_content_sha256"], "normalized_content_sha256")
    try:
        source = SourceSpan.from_dict(result["source"])
        if asdict(source) != result["source"]:
            raise CorpusIndexError("noncanonical source metadata")
        if result["embedding_provenance"] is not None:
            provenance = EmbeddingProvenance.from_dict(result["embedding_provenance"])
            if asdict(provenance) != result["embedding_provenance"]:
                raise CorpusIndexError("noncanonical embedding provenance")
    except (CorpusManifestError, TypeError, ValueError) as exc:
        raise CorpusIndexError("invalid source or embedding summary") from exc
    return result


def _group_keys(row: Mapping[str, Any]) -> tuple[str, ...]:
    source = row["source"]
    # Release and embedding producer identities are bound metadata, not global
    # union keys. Document identity intentionally spans releases and languages.
    return tuple(_json(value).decode("ascii") for value in (
        ["document", source["source_kind"], source["document_id"]],
        ["source_artifact", source["artifact"]["sha256"]],
        ["normalized_content", row["normalized_content_sha256"]],
    ))


def _assign(rows: Sequence[Mapping[str, Any]], policy: SplitPolicy) -> tuple[dict[str, str], dict[str, str]]:
    """Union explicit keys in near-linear work; no pairwise fuzzy comparisons."""
    parent = {row["record_id"]: row["record_id"] for row in rows}
    sizes = {key: 1 for key in parent}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left, right):
        left, right = find(left), find(right)
        if left == right:
            return
        if sizes[left] < sizes[right]:
            left, right = right, left
        parent[right] = left
        sizes[left] += sizes[right]

    seen: dict[str, str] = {}
    keys_by_record = {}
    for row in rows:
        record_id = row["record_id"]
        keys = _group_keys(row)
        keys_by_record[record_id] = keys
        for key in keys:
            union(record_id, seen.setdefault(key, record_id))
    grouped_keys: dict[str, set[str]] = {}
    for record_id, keys in keys_by_record.items():
        grouped_keys.setdefault(find(record_id), set()).update(keys)
    group_ids = {root: "sha256:" + _sha(_json({"schema": GROUPING_SCHEMA, "keys": sorted(keys)}))
                 for root, keys in grouped_keys.items()}
    split_by_group = {}
    for group_id in group_ids.values():
        digest = _sha(_json({"schema": "integer-group-assignment-v1", "seed": policy.seed, "group_id": group_id}))
        bucket = int(digest, 16) % 10000
        boundary = 0
        for split in SPLITS:
            boundary += getattr(policy, split)
            if bucket < boundary:
                split_by_group[group_id] = split
                break
    record_groups = {record_id: group_ids[find(record_id)] for record_id in sorted(parent)}
    assignments = {record_id: split_by_group[group_id] for record_id, group_id in record_groups.items()}
    return record_groups, assignments


_FIELDS = {"schema_version", "grouping_schema", "content_normalization", "scope", "policy",
           "records", "record_groups", "assignments"}


@dataclass(frozen=True)
class CorpusIndex:
    """Strict immutable bytes with cached immutable lookup metadata."""

    _raw: bytes
    limits: IndexLimits = IndexLimits()
    _sha256: str = field(init=False, repr=False, compare=False)
    _scope: IndexScope = field(init=False, repr=False, compare=False)
    _policy: SplitPolicy = field(init=False, repr=False, compare=False)
    _summaries: Mapping[str, Mapping[str, Any]] = field(init=False, repr=False, compare=False)
    _assignments: Mapping[str, str] = field(init=False, repr=False, compare=False)
    _groups: Mapping[str, str] = field(init=False, repr=False, compare=False)
    _partitions: Mapping[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if type(self._raw) is not bytes or not 1 <= len(self._raw) <= self.limits.max_index_bytes:
            raise CorpusIndexError("index exceeds byte bound")
        data = _keys(_parse(self._raw), _FIELDS, "index")
        if (data["schema_version"] != SCHEMA_VERSION or data["grouping_schema"] != GROUPING_SCHEMA
                or data["content_normalization"] != CONTENT_NORMALIZATION or _json(data) != self._raw):
            raise CorpusIndexError("unsupported or noncanonical index bytes")
        scope = IndexScope.from_dict(data["scope"])
        policy = SplitPolicy.from_dict(data["policy"])
        if scope.to_dict() != data["scope"]:
            raise CorpusIndexError("release identities must be sorted canonically")
        if len(scope.release_manifest_sha256s) > self.limits.max_release_manifests:
            raise CorpusIndexError("release manifest count exceeds bound")
        rows = data["records"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= self.limits.max_records:
            raise CorpusIndexError("record count exceeds index bound")
        rows = [_validate_summary(row) for row in rows]
        record_ids = [row["record_id"] for row in rows]
        if record_ids != sorted(set(record_ids)):
            raise CorpusIndexError("record summaries must have sorted unique identities")
        sources: dict[str, int] = {}
        for row in rows:
            ref = row["source"]["artifact"]
            if sources.setdefault(ref["sha256"], ref["bytes"]) != ref["bytes"]:
                raise CorpusIndexError("source hash has inconsistent byte sizes")
        groups, assignments = _assign(rows, policy)
        if data["record_groups"] != groups or data["assignments"] != assignments:
            raise CorpusIndexError("grouping or frozen assignment does not match deterministic policy")
        for name, value in {
            "_sha256": _sha(self._raw), "_scope": scope, "_policy": policy,
            "_summaries": _freeze({row["record_id"]: row for row in rows}),
            "_assignments": MappingProxyType(assignments), "_groups": MappingProxyType(groups),
            "_partitions": MappingProxyType({split: tuple(key for key in record_ids if assignments[key] == split)
                                               for split in SPLITS}),
        }.items():
            object.__setattr__(self, name, value)

    @property
    def sha256(self) -> str:
        return self._sha256

    @property
    def index_id(self) -> str:
        return "sha256:" + self.sha256

    @property
    def scope(self) -> IndexScope:
        return self._scope

    @property
    def policy(self) -> SplitPolicy:
        return self._policy

    @property
    def assignments(self) -> dict[str, str]:
        return dict(self._assignments)

    @property
    def record_groups(self) -> dict[str, str]:
        return dict(self._groups)

    @property
    def partition_counts(self) -> dict[str, int]:
        return {split: len(ids) for split, ids in self._partitions.items()}

    def record_ids_for(self, split: str, *, require_nonempty: bool = True) -> tuple[str, ...]:
        if split not in SPLITS or type(require_nonempty) is not bool:
            raise CorpusIndexError("unknown split or invalid nonempty requirement")
        result = self._partitions[split]
        if require_nonempty and not result:
            raise CorpusIndexError(f"frozen {split} partition is empty; no automatic resampling is allowed")
        return result

    def to_bytes(self) -> bytes:
        return self._raw

    def to_dict(self) -> dict[str, Any]:
        return _parse(self._raw)

    def verification_summary(self) -> dict[str, Any]:
        return {"index_id": self.index_id, "index_sha256": self.sha256, "scope": self.scope.to_dict(),
                "record_count": len(self._summaries), "group_count": len(set(self._groups.values())),
                "partition_counts": self.partition_counts, "indexed_partition_disjoint_verified": True,
                "global_holdout_verified": False, "corpus_complete": False,
                "source_bytes_verified": False, "source_authority_authenticated": False,
                "embedding_producer_authenticated": False, "semantic_duplicate_isolation_verified": False,
                "unseen_checkpoint_lineage_verified": False, "admitted": False}

    def authorize(self, operation: str, record_ids: Sequence[str]) -> None:
        allowed = LEGAL_IR_SPLIT_OPERATION_ALLOWED_SPLITS.get(operation)
        if allowed is None:
            raise CorpusIndexError("unknown split operation")
        if (not isinstance(record_ids, (list, tuple)) or len(record_ids) > self.limits.max_records
                or any(not isinstance(item, str) for item in record_ids)
                or len(set(record_ids)) != len(record_ids)):
            raise CorpusIndexError("operation record identities must be a bounded unique sequence")
        for record_id in record_ids:
            split = self._assignments.get(record_id)
            if split is None:
                raise CorpusIndexError("operation refers to a record outside the frozen index")
            if split not in allowed:
                raise CorpusIndexError(f"{split} record is protected from {operation}")

    def verify_batch(self, manifest: CorpusManifest) -> dict[str, Any]:
        if not isinstance(manifest, CorpusManifest):
            raise CorpusIndexError("batch must be a verified CorpusManifest object")
        for record in manifest.records:
            expected = self._summaries.get(record.record_id)
            if expected is None or _summary(record) != expected:
                raise CorpusIndexError("batch record differs from the exact frozen index summary")
        # Existing batch bytes remain authoritative for row order. They are not
        # sorted or rewritten when selecting an indexed subset.
        split = manifest.to_dict()["split"]
        training = split["training_record_ids"]
        validation = split["validation_record_ids"]
        self.authorize(TRAINING_OPERATION, training)
        self.authorize(HPARAM_SELECTION_OPERATION, validation)
        return {**self.verification_summary(), "dataset_snapshot_id": manifest.dataset_snapshot_id,
                "split_snapshot_id": manifest.split_snapshot_id, "batch_mode": manifest.mode,
                "training_record_ids": list(training), "validation_record_ids": list(validation),
                "batch_index_membership_verified": True}

    def save(self, destination: str | Path) -> dict[str, Any]:
        path = Path(destination)
        with path.open("xb") as stream:
            stream.write(self._raw)
            stream.flush()
            os.fsync(stream.fileno())
        return {"path": str(path.absolute()), "sha256": self.sha256, "bytes": len(self._raw), "index_id": self.index_id}


def build_corpus_index(records: Sequence[SourceSampleRecord], *, scope: IndexScope,
                       policy: SplitPolicy, limits: IndexLimits = IndexLimits()) -> CorpusIndex:
    if not isinstance(scope, IndexScope) or not isinstance(policy, SplitPolicy):
        raise CorpusIndexError("index requires explicit IndexScope and SplitPolicy")
    if not isinstance(records, (list, tuple)) or not 1 <= len(records) <= limits.max_records:
        raise CorpusIndexError("record count exceeds index bound")
    rows = sorted((_summary(record) for record in records), key=lambda row: row["record_id"])
    if len({row["record_id"] for row in rows}) != len(rows):
        raise CorpusIndexError("duplicate indexed record identity")
    groups, assignments = _assign(rows, policy)
    return CorpusIndex(_json({"schema_version": SCHEMA_VERSION, "grouping_schema": GROUPING_SCHEMA,
                              "content_normalization": CONTENT_NORMALIZATION, "scope": scope.to_dict(),
                              "policy": policy.to_dict(), "records": rows,
                              "record_groups": groups, "assignments": assignments}), limits)


def load_corpus_index(path: str | Path, *, expected_sha256: str,
                      expected_size_bytes: int | None = None,
                      limits: IndexLimits = IndexLimits()) -> CorpusIndex:
    _digest(expected_sha256, "expected_sha256")
    if expected_size_bytes is not None and (type(expected_size_bytes) is not int
            or not 1 <= expected_size_bytes <= limits.max_index_bytes):
        raise CorpusIndexError("index exceeds expected byte bound")
    try:
        fd = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= limits.max_index_bytes
                    or expected_size_bytes is not None and info.st_size != expected_size_bytes):
                raise CorpusIndexError("index must be a regular file of the bounded expected size")
            raw = stream.read(info.st_size + 1)
            if len(raw) != info.st_size:
                raise CorpusIndexError("index changed while reading")
    except (OSError, TypeError) as exc:
        raise CorpusIndexError("index artifact could not be read") from exc
    if _sha(raw) != expected_sha256:
        raise CorpusIndexError("index SHA-256 mismatch")
    return CorpusIndex(raw, limits)


__all__ = ["SCHEMA_VERSION", "GROUPING_SCHEMA", "CONTENT_NORMALIZATION", "SPLITS", "CorpusIndexError",
           "IndexLimits", "IndexScope", "SplitPolicy", "CorpusIndex", "build_corpus_index", "load_corpus_index"]
