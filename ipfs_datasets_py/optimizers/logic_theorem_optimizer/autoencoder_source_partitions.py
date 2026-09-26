"""Freeze declared U.S. Code source groups before embedding exclusions.

This codec binds the complete source inventory, not an embedding-bearing v1
CorpusIndex. Every physical row participates in grouping, including excluded
connectors. Selected inputs and produced records retain explicit occurrence
selectors. These integrity checks grant no training-job, source-authority,
global holdout, publication or Lean admission authority.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from types import MappingProxyType

from . import autoencoder_corpus_index as index
from . import autoencoder_uscode_import as importer
from .autoencoder_corpus_manifest import SourceSampleRecord
from .autoencoder_embedding_production import EmbeddingInput, MAX_BYTES, MAX_RECORDS, MAX_TEXT_BYTES, DIMENSION
from .autoencoder_uscode_inventory import (
    USCodeSourceInventory, _fsync_directory, materialize_uscode_inventory_inputs,
)
from .legal_ir_eval_splits import LEGAL_IR_SPLIT_OPERATION_ALLOWED_SPLITS


SCHEMA_VERSION = "autoencoder-source-partitions-v1"
SCOPE = "declared_corpus_family_only"
MAX_PROJECTION_DIMENSION = 4096
MAX_PROJECTION_VALUES = MAX_RECORDS * DIMENSION
_FIELDS = {"schema_version", "scope", "inventory", "grouping_schema",
           "content_normalization", "policy", "rows"}


class SourcePartitionError(ValueError):
    """Incomplete, inconsistent or unauthorized frozen source membership."""


@dataclass(frozen=True)
class SourcePartitionLimits:
    max_rows: int = 65536
    max_bytes: int = 64 * 1024**2

    def __post_init__(self):
        for name, maximum in (("max_rows", 65536), ("max_bytes", 64 * 1024**2)):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= maximum:
                raise SourcePartitionError(f"{name} exceeds source partition bounds")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    try:
        return index._json(value)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise SourcePartitionError("invalid source partition JSON") from exc


def _inventory_rows(inventory, limits):
    if type(inventory) is not USCodeSourceInventory:
        raise SourcePartitionError("verified source inventory required")
    try:
        inventory = USCodeSourceInventory(inventory.to_bytes(), inventory.limits)
        data = inventory.to_dict()
    except (ValueError, TypeError) as exc:
        raise SourcePartitionError("invalid source inventory") from exc
    if any(shard["status"] != "verified" for shard in data["shards"]):
        raise SourcePartitionError("complete declared source inventory required")
    if sum(len(shard["rows"]) for shard in data["shards"]) > limits.max_rows:
        raise SourcePartitionError("physical source rows exceed partition bound")
    rows, occurrences = [], []
    for shard in data["shards"]:
        for row in shard["rows"]:
            meta = row["metadata"]
            if (meta is None or meta["canonical_identity"] is None
                    or meta["text_sha256"] is None):
                raise SourcePartitionError("complete grouping metadata required, including excluded rows")
            row_id = "sha256:" + _sha(_json({"schema": "source-inventory-row-v1",
                "inventory_sha256": inventory.sha256,
                "relative_path": shard["artifact"]["relative_path"], "row_index": row["row_index"]}))
            # SourceArtifact here means the exact extracted text bytes, not
            # the Parquet container. Excluded empty text is still a group key.
            rows.append({"record_id": row_id,
                "source": {"source_kind": "us_code",
                           "document_id": meta["canonical_identity"]["document_id"],
                           "artifact": {"sha256": meta["text_sha256"]}},
                "normalized_content_sha256": meta["normalized_content_sha256"]})
            occurrences.append({"source_row_id": row_id, "entry_cid": row["entry_cid"],
                                "input_id": meta["input_id"],
                                "eligible": row["status"] == "ready_published_text",
                                "identity": meta["canonical_identity"],
                                "text_sha256": meta["text_sha256"], "text_bytes": meta["text_bytes"]})
    return inventory, rows, occurrences


def _payload(inventory, policy, limits):
    if type(limits) is not SourcePartitionLimits or type(policy) is not index.SplitPolicy:
        raise SourcePartitionError("explicit bounded partition policy required")
    try:
        policy = index.SplitPolicy.from_dict(policy.to_dict())
        inventory, rows, occurrences = _inventory_rows(inventory, limits)
        groups, assignments = index._assign(rows, policy)
    except (ValueError, TypeError, UnicodeError) as exc:
        if isinstance(exc, SourcePartitionError):
            raise
        raise SourcePartitionError("invalid source partition policy or grouping") from exc
    payload = {"schema_version": SCHEMA_VERSION, "scope": SCOPE,
               "inventory": {"sha256": inventory.sha256, "bytes": len(inventory.to_bytes())},
               "grouping_schema": index.GROUPING_SCHEMA,
               "content_normalization": index.CONTENT_NORMALIZATION,
               "policy": policy.to_dict(),
               "rows": [{"source_row_id": row["source_row_id"],
                         "group_id": groups[row["source_row_id"]],
                         "split": assignments[row["source_row_id"]]} for row in occurrences]}
    return payload, inventory, occurrences


@dataclass(frozen=True)
class SourcePartitions:
    _raw: bytes
    inventory: USCodeSourceInventory = field(repr=False, compare=False)
    limits: SourcePartitionLimits = SourcePartitionLimits()
    _sha256: str = field(init=False, repr=False)
    _bindings: object = field(init=False, repr=False, compare=False)
    _counts: object = field(init=False, repr=False, compare=False)
    _eligible_counts: object = field(init=False, repr=False, compare=False)
    _summary: object = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if (type(self.limits) is not SourcePartitionLimits or type(self._raw) is not bytes
                or not 1 <= len(self._raw) <= self.limits.max_bytes):
            raise SourcePartitionError("source partitions exceed byte bound")
        try:
            data = index._keys(index._parse(self._raw), _FIELDS, "source partitions")
            policy = index.SplitPolicy.from_dict(data["policy"])
            expected, inventory, occurrences = _payload(self.inventory, policy, self.limits)
        except (ValueError, TypeError, UnicodeError, KeyError) as exc:
            if isinstance(exc, SourcePartitionError):
                raise
            raise SourcePartitionError("invalid source partition artifact") from exc
        if _json(expected) != self._raw:
            raise SourcePartitionError("source partition bytes differ from exact inventory grouping and policy")
        bindings, aliases = {}, {}
        for occurrence, row in zip(occurrences, expected["rows"]):
            if not occurrence["eligible"]:
                continue
            input_id = occurrence["input_id"]
            alias = (row["group_id"], row["split"], _json(occurrence["identity"]),
                     occurrence["text_sha256"], occurrence["text_bytes"])
            if aliases.setdefault(input_id, alias) != alias:
                raise SourcePartitionError("same input identity has inconsistent source aliases")
            entry = occurrence["entry_cid"]
            if entry in bindings:
                raise SourcePartitionError("eligible source occurrence has ambiguous entry identity")
            bindings[entry] = MappingProxyType({"entry_cid": entry, "input_id": input_id, **row})
        counts = Counter(row["split"] for row in expected["rows"])
        eligible = Counter(row["split"] for row in bindings.values())
        object.__setattr__(self, "inventory", inventory)
        object.__setattr__(self, "_sha256", _sha(self._raw))
        object.__setattr__(self, "_bindings", MappingProxyType(bindings))
        object.__setattr__(self, "_counts", MappingProxyType({split: counts[split] for split in index.SPLITS}))
        object.__setattr__(self, "_eligible_counts", MappingProxyType({split: eligible[split] for split in index.SPLITS}))
        object.__setattr__(self, "_summary", MappingProxyType({
            "physical_row_count": len(occurrences), "eligible_row_count": len(bindings),
            "eligible_unique_input_count": len(aliases),
            "group_count": len({row["group_id"] for row in expected["rows"]})}))

    @property
    def sha256(self):
        return self._sha256

    @property
    def partition_counts(self):
        return dict(self._counts)

    @property
    def eligible_partition_counts(self):
        return dict(self._eligible_counts)

    def to_bytes(self):
        return self._raw

    def to_dict(self):
        return index._parse(self._raw)

    def verification_summary(self):
        return {"schema_version": SCHEMA_VERSION, "source_partitions_sha256": self.sha256,
                "source_partitions_bytes": len(self._raw), "scope": SCOPE,
                "inventory_sha256": self.inventory.sha256, **dict(self._summary),
                "partition_counts": self.partition_counts,
                "eligible_partition_counts": self.eligible_partition_counts,
                "complete_declared_inventory_bound": True,
                "source_group_partition_disjoint_verified": True,
                "current_source_bytes_verified": False, "source_authority_authenticated": False,
                "embedding_producer_authenticated": False, "global_holdout_verified": False,
                "unseen_checkpoint_lineage_verified": False, "semantic_duplicate_isolation_verified": False,
                "training_eligible": False, "admitted": False}

    def binding_for(self, entry_cid):
        if type(entry_cid) is not str or entry_cid not in self._bindings:
            raise SourcePartitionError("source entry is absent, excluded or duplicated")
        return dict(self._bindings[entry_cid])

    def entry_cids_for(self, split, *, require_nonempty=True):
        if type(split) is not str or split not in index.SPLITS or type(require_nonempty) is not bool:
            raise SourcePartitionError("unknown split or invalid nonempty requirement")
        result = tuple(key for key, value in self._bindings.items() if value["split"] == split)
        if require_nonempty and not result:
            raise SourcePartitionError("frozen source partition is empty; no resampling allowed")
        return result

    def authorize(self, operation, entry_cids):
        allowed = LEGAL_IR_SPLIT_OPERATION_ALLOWED_SPLITS.get(operation) if type(operation) is str else None
        if allowed is None:
            raise SourcePartitionError("unknown split operation")
        if (type(entry_cids) not in (list, tuple) or not 1 <= len(entry_cids) <= self.limits.max_rows
                or any(type(item) is not str for item in entry_cids) or len(set(entry_cids)) != len(entry_cids)):
            raise SourcePartitionError("source selection must be a bounded nonempty unique sequence")
        for entry in entry_cids:
            if self.binding_for(entry)["split"] not in allowed:
                raise SourcePartitionError("source partition is protected from this operation")

    def project_records(self, records, *, entry_cids):
        """Bind supplied exact records to source assignments; no producer authority."""
        if (type(records) not in (list, tuple) or not 1 <= len(records) <= MAX_RECORDS
                or type(entry_cids) not in (list, tuple) or len(entry_cids) != len(records)
                or any(type(item) is not str for item in entry_cids)
                or len(set(entry_cids)) != len(entry_cids)):
            raise SourcePartitionError("projection needs bounded records and explicit unique source selectors")
        result, record_ids = [], set()
        try:
            # Bound all work before record serialization. The generic record
            # codec permits far larger vectors than this bounded projection.
            total_bytes = total_values = 0
            for original in records:
                if type(original) is not SourceSampleRecord:
                    raise SourcePartitionError("projection requires exact SourceSampleRecord objects")
                vector, text = original.sample.embedding_vector, original.sample.text
                if (type(vector) not in (list, tuple) or not 1 <= len(vector) <= MAX_PROJECTION_DIMENSION
                        or type(text) is not str or len(text) > MAX_TEXT_BYTES):
                    raise SourcePartitionError("projection vector or text exceeds its per-record bound")
                text_bytes = len(text.encode("utf-8"))
                total_bytes += text_bytes
                total_values += len(vector)
                if text_bytes > MAX_TEXT_BYTES or total_bytes > MAX_BYTES or total_values > MAX_PROJECTION_VALUES:
                    raise SourcePartitionError("projection exceeds its aggregate text or numeric bound")
            for original, entry in zip(records, entry_cids):
                record = SourceSampleRecord.from_dict(original.to_dict())
                item = EmbeddingInput.from_source_record(record)
                if record.record_id in record_ids:
                    raise SourcePartitionError("projection duplicates a record")
                binding = self.binding_for(entry)
                if item.input_id != binding["input_id"]:
                    raise SourcePartitionError("produced record differs from selected exact source input")
                result.append({"record_summary": index._summary(record), **binding})
                record_ids.add(record.record_id)
        except (ValueError, TypeError, AttributeError, UnicodeError) as exc:
            if isinstance(exc, SourcePartitionError):
                raise
            raise SourcePartitionError("invalid source record projection") from exc
        return {"schema_version": "autoencoder-source-record-partition-projection-v1",
                "source_partitions": {"sha256": self.sha256, "bytes": len(self._raw)},
                "records": result, "training_eligible": False, "admitted": False}

    def save(self, destination):
        result = importer._write_exclusive(Path(destination), self._raw)
        _fsync_directory(Path(destination).parent)
        return result


def build_source_partitions(inventory, *, policy, limits=SourcePartitionLimits()):
    payload, inventory, _ = _payload(inventory, policy, limits)
    raw = _json(payload)
    return SourcePartitions(raw, inventory, limits)


def load_source_partitions(path, *, expected_sha256, inventory, expected_size_bytes=None,
                           limits=SourcePartitionLimits()):
    if type(limits) is not SourcePartitionLimits:
        raise SourcePartitionError("invalid source partition limits")
    try:
        index._digest(expected_sha256, "expected_sha256")
        path = Path(path).absolute()
        size = path.lstat().st_size if expected_size_bytes is None else expected_size_bytes
        if type(size) is not int or not 1 <= size <= limits.max_bytes:
            raise SourcePartitionError("source partitions exceed expected byte bound")
        with importer._verified_file(path, {"sha256": expected_sha256, "bytes": size}, limits.max_bytes) as stream:
            raw = stream.read(size + 1)
        return SourcePartitions(raw, inventory, limits)
    except (ValueError, OSError, TypeError) as exc:
        if isinstance(exc, SourcePartitionError):
            raise
        raise SourcePartitionError("source partition artifact verification failed") from exc


@dataclass(frozen=True)
class PartitionedSourceInputs:
    materialization: object
    _receipt: bytes = field(repr=False)
    _artifact: bytes = field(repr=False)

    @property
    def inputs(self):
        return self.materialization.inputs

    @property
    def selection_receipt(self):
        return index._parse(self._receipt)

    @property
    def selection_receipt_artifact(self):
        return index._parse(self._artifact)


def materialize_partition_inputs(partitions, entry_cids, output_directory, *, operation, release, resolver):
    if type(partitions) is not SourcePartitions:
        raise SourcePartitionError("verified source partitions required")
    partitions.authorize(operation, entry_cids)
    selected = materialize_uscode_inventory_inputs(partitions.inventory, entry_cids,
        output_directory, release=release, resolver=resolver)
    bindings = [partitions.binding_for(entry) for entry in entry_cids]
    if [item.input_id for item in selected.inputs] != [row["input_id"] for row in bindings]:
        raise SourcePartitionError("materialized inputs differ from frozen source membership")
    raw = _json({"schema_version": "autoencoder-source-partition-selection-v1",
                "source_partitions": {"sha256": partitions.sha256, "bytes": len(partitions.to_bytes())},
                "operation": operation, "bindings": bindings,
                "inventory_selection": {name: selected.selection_receipt_artifact[name] for name in ("sha256", "bytes")},
                "selected_source_bytes_verified": True, "training_eligible": False, "admitted": False})
    artifact = importer._write_exclusive(Path(output_directory) / "source-partition-selection.json", raw)
    _fsync_directory(Path(output_directory))
    return PartitionedSourceInputs(selected, raw, _json(artifact))


__all__ = ["SourcePartitionError", "SourcePartitionLimits", "SourcePartitions", "PartitionedSourceInputs",
           "build_source_partitions", "load_source_partitions", "materialize_partition_inputs"]
