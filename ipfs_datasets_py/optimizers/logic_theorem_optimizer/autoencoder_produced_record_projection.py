"""Exact bounded batch membership over source-frozen producer campaigns.

The batch manifest owns payload and ordered roles. This immutable metadata
projection binds that manifest to source occurrences and original producer
leaves without rebuilding partitions after embedding failures. Metadata loading
never asserts current source/leaf bytes, job eligibility or Lean admission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import autoencoder_corpus_index as index
from . import autoencoder_embedding_production as production
from . import autoencoder_embedding_receipt_set as receipt_sets
from . import autoencoder_uscode_import as importer
from .autoencoder_corpus_manifest import CorpusManifest, ManifestLimits, SourceSampleRecord
from .autoencoder_uscode_inventory import _fsync_directory
from .legal_ir_eval_splits import TRAINING_OPERATION, HPARAM_SELECTION_OPERATION


SCHEMA_VERSION = "autoencoder-produced-record-projection-v1"
_FIELDS = {"schema_version", "receipt_set", "source_partitions", "corpus_manifest",
           "dataset_snapshot_id", "split_snapshot_id", "records",
           "training_record_ids", "validation_record_ids"}
_BINDING_FIELDS = {"entry_cid", "source_row_id", "input_id", "group_id", "split",
                   "receipt_sha256", "result_index", "status"}


class ProjectionError(ValueError):
    """Invalid, mismatched or unauthorized produced-record batch projection."""


@dataclass(frozen=True)
class ProjectionLimits:
    max_records: int = 256
    max_bytes: int = 4 * 1024**2
    max_leaf_bytes: int = 64 * 1024**2
    max_source_bytes: int = 64 * 1024**2

    def __post_init__(self):
        for name, bound in (("max_records", 256), ("max_bytes", 4 * 1024**2),
                            ("max_leaf_bytes", 64 * 1024**2), ("max_source_bytes", 64 * 1024**2)):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= bound:
                raise ProjectionError(f"{name} exceeds projection bounds")


def _reference(value):
    return {"sha256": value.sha256, "bytes": len(value.to_bytes())}


def _root(value):
    # The exact immutable codec is already validated at construction/load.
    # Reuse its frozen metadata rather than reparse the full campaign per batch.
    if type(value) is not receipt_sets.EmbeddingReceiptSet or not value.native_execution_profile:
        raise ProjectionError("projection requires an exact native-profile receipt set")
    return value


def _manifest(value, limits):
    if (type(limits) is not ProjectionLimits or type(value) is not CorpusManifest
            or not 1 <= len(value.to_bytes()) <= production.MAX_BYTES
            or not 1 <= len(value.records) <= limits.max_records):
        raise ProjectionError("projection requires a bounded exact corpus manifest")
    # Preflight cached records before any further serialization or conversion.
    text_bytes = 0
    for record in value.records:
        if type(record) is not SourceSampleRecord:
            raise ProjectionError("manifest requires exact source-aware records")
        text, vector = record.sample.text, record.sample.embedding_vector
        if (type(text) is not str or len(text) > production.MAX_TEXT_BYTES
                or type(vector) not in (list, tuple) or len(vector) != production.DIMENSION):
            raise ProjectionError("manifest text or vector exceeds projection profile")
        size = len(text.encode("utf-8"))
        text_bytes += size
        if size > production.MAX_TEXT_BYTES or text_bytes > production.MAX_BYTES:
            raise ProjectionError("manifest text exceeds projection byte bound")
    bounded = ManifestLimits(max_records=limits.max_records, max_sources=limits.max_records,
        max_manifest_bytes=production.MAX_BYTES, max_source_bytes=limits.max_source_bytes,
        max_total_source_bytes=limits.max_source_bytes, max_sample_text_bytes=production.MAX_TEXT_BYTES,
        max_embedding_dimensions=production.DIMENSION,
        max_total_embedding_dimensions=limits.max_records * production.DIMENSION)
    value = CorpusManifest(value.to_bytes(), bounded)
    if value.mode != "corpus":
        raise ProjectionError("produced-record projection requires corpus mode")
    return value


def _roles(root, rows, training, validation):
    by_id = {row["record_summary"]["record_id"]: row for row in rows}
    groups = []
    for ids, operation in ((training, TRAINING_OPERATION), (validation, HPARAM_SELECTION_OPERATION)):
        if (type(ids) is not list or not ids or any(type(key) is not str or key not in by_id for key in ids)
                or len(set(ids)) != len(ids)):
            raise ProjectionError("projection requires complete ordered unique training and validation roles")
        entries = [by_id[key]["entry_cid"] for key in ids]
        root.partitions.authorize(operation, entries)
        groups.append((operation, ids, entries))
    if set(training) & set(validation) or set(training) | set(validation) != set(by_id):
        raise ProjectionError("every projected record must have one disjoint batch role")
    return groups


def _artifacts(root, rows, limits):
    leaves = root.selected_leaf_artifacts([row["entry_cid"] for row in rows])
    sources = {}
    for row in rows:
        ref = receipt_sets._ref(row["record_summary"]["source"]["artifact"])
        receipt_sets._add_sources(sources, [ref])
    if (sum(ref["bytes"] for ref in leaves) > limits.max_leaf_bytes
            or sum(ref["bytes"] for ref in sources.values()) > limits.max_source_bytes):
        raise ProjectionError("selected leaf or source closure exceeds projection byte bound")
    return {"leaf_receipts": list(leaves), "source_artifacts": [sources[key] for key in sorted(sources)]}


@dataclass(frozen=True)
class ProducedRecordProjection:
    _raw: bytes
    receipt_set: receipt_sets.EmbeddingReceiptSet = field(repr=False, compare=False)
    limits: ProjectionLimits = ProjectionLimits()
    _sha256: str = field(init=False, repr=False)
    _selected_raw: bytes = field(init=False, repr=False)

    def __post_init__(self):
        if (type(self.limits) is not ProjectionLimits or type(self._raw) is not bytes
                or not 1 <= len(self._raw) <= self.limits.max_bytes):
            raise ProjectionError("projection root exceeds byte bound")
        try:
            root = _root(self.receipt_set)
            data = production._keys(production._parse(self._raw), _FIELDS, "produced-record projection")
            if data["schema_version"] != SCHEMA_VERSION or production._canonical(data) != self._raw:
                raise ProjectionError("unsupported or noncanonical projection bytes")
            if (receipt_sets._ref(data["receipt_set"]) != _reference(root)
                    or receipt_sets._ref(data["source_partitions"]) != _reference(root.partitions)):
                raise ProjectionError("projection differs from its exact campaign or source partitions")
            receipt_sets._ref(data["corpus_manifest"])
            for key in ("dataset_snapshot_id", "split_snapshot_id"):
                if type(data[key]) is not str or not index._RECORD_ID.fullmatch(data[key]):
                    raise ProjectionError("invalid exact batch snapshot identity")
            rows = data["records"]
            if type(rows) is not list or not 1 <= len(rows) <= self.limits.max_records:
                raise ProjectionError("projection record count exceeds bound")
            record_ids, entries = [], []
            profile = production._parse(root._profile_raw)["model"]
            for row in rows:
                production._keys(row, {"record_summary", *_BINDING_FIELDS}, "projected record")
                production._integer(row["result_index"], "producer result ordinal", 0, production.MAX_RECORDS - 1)
                summary = index._validate_summary(row["record_summary"])
                binding = root.binding_for(row["entry_cid"])
                if ({key: row[key] for key in _BINDING_FIELDS} != binding or binding["status"] != "embedded"):
                    raise ProjectionError("projected row differs from successful frozen source/leaf membership")
                provenance = summary["embedding_provenance"]
                if (provenance != {"model_id": profile["model_id"], "revision": profile["revision"],
                                   "artifact_sha256": binding["receipt_sha256"]}
                        or summary["source"]["source_kind"] != "us_code" or summary["source"]["language"] != "en"):
                    raise ProjectionError("projected record differs from qualified frontend or original leaf provenance")
                record_ids.append(summary["record_id"])
                entries.append(row["entry_cid"])
            if record_ids != sorted(set(record_ids)) or len(set(entries)) != len(entries):
                raise ProjectionError("projected records must preserve canonical unique manifest order and selectors")
            _roles(root, rows, data["training_record_ids"], data["validation_record_ids"])
            selected = _artifacts(root, rows, self.limits)
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
            if isinstance(exc, ProjectionError):
                raise
            raise ProjectionError("invalid produced-record projection metadata") from exc
        object.__setattr__(self, "_sha256", receipt_sets._sha(self._raw))
        object.__setattr__(self, "_selected_raw", production._canonical(selected))

    @property
    def sha256(self):
        return self._sha256

    def to_bytes(self):
        return self._raw

    def to_dict(self):
        return production._parse(self._raw)

    def selected_artifacts(self):
        return production._parse(self._selected_raw)

    def summary(self):
        data, selected = self.to_dict(), self.selected_artifacts()
        return {"schema_version": SCHEMA_VERSION, "projection_sha256": self.sha256,
                "projection_bytes": len(self._raw), "receipt_set": data["receipt_set"],
                "source_partitions": data["source_partitions"], "corpus_manifest": data["corpus_manifest"],
                "dataset_snapshot_id": data["dataset_snapshot_id"], "split_snapshot_id": data["split_snapshot_id"],
                "record_count": len(data["records"]), "training_record_count": len(data["training_record_ids"]),
                "validation_record_count": len(data["validation_record_ids"]),
                "selected_leaf_count": len(selected["leaf_receipts"]), "source_count": len(selected["source_artifacts"]),
                "current_selected_leaf_bytes_verified": False, "current_selected_source_bytes_verified": False,
                "supplied_manifest_verified": False, "native_execution_profile": True,
                "runtime_cryptographically_attested": False, "source_authority_authenticated": False,
                "global_holdout_verified": False, "corpus_complete": False,
                "training_eligible": False, "admitted": False}

    def authorize(self, operation, record_ids):
        try:
            rows = self.to_dict()["records"]
            by_id = {row["record_summary"]["record_id"]: row["entry_cid"] for row in rows}
            if (type(record_ids) not in (list, tuple) or not 1 <= len(record_ids) <= len(rows)
                    or any(type(key) is not str or key not in by_id for key in record_ids)
                    or len(set(record_ids)) != len(record_ids)):
                raise ProjectionError("operation must select bounded unique projected records")
            self.receipt_set.partitions.authorize(operation, [by_id[key] for key in record_ids])
        except (ValueError, TypeError, KeyError) as exc:
            raise ProjectionError("projected records are protected from this operation") from exc

    def verify_batch(self, manifest, *, receipt_resolver, source_resolver):
        try:
            manifest = _manifest(manifest, self.limits)
            data = self.to_dict()
            if (data["corpus_manifest"] != _reference(manifest)
                    or data["dataset_snapshot_id"] != manifest.dataset_snapshot_id
                    or data["split_snapshot_id"] != manifest.split_snapshot_id
                    or data["training_record_ids"] != list(manifest._training_record_ids)
                    or data["validation_record_ids"] != list(manifest._validation_record_ids)):
                raise ProjectionError("batch differs from exact projected manifest or ordered roles")
            if [row["record_summary"] for row in data["records"]] != [index._summary(record) for record in manifest.records]:
                raise ProjectionError("batch source/vector/provenance differs from exact projected summaries")
            # Authorize all groups and preflight the complete selected closure
            # before calling either resolver, including a bad validation group.
            groups = _roles(self.receipt_set, data["records"], data["training_record_ids"], data["validation_record_ids"])
            selected = self.selected_artifacts()
            receipt_resolver = receipt_sets._captured_resolver(receipt_resolver)
            source_resolver = receipt_sets._captured_resolver(source_resolver)
            by_id = {record.record_id: record for record in manifest.records}
            verified = 0
            for operation, ids, entries in groups:
                checked = self.receipt_set.verify_records([by_id[key] for key in ids], entry_cids=entries,
                    operation=operation, receipt_resolver=receipt_resolver, source_resolver=source_resolver)
                verified += checked["supplied_records_verified"]
            # Catch a later operation group's resolver mutating earlier files.
            receipt_sets._rehash(selected["leaf_receipts"], receipt_resolver, "projected receipt leaf")
            receipt_sets._rehash(selected["source_artifacts"], source_resolver, "projected source")
        except (ValueError, TypeError, KeyError, AttributeError, OSError, UnicodeError) as exc:
            if isinstance(exc, ProjectionError):
                raise
            raise ProjectionError("projected batch/source/producer verification failed") from exc
        return {**self.summary(), "supplied_manifest_verified": True,
                "supplied_records_verified": verified, "current_selected_leaf_bytes_verified": True,
                "current_selected_source_bytes_verified": True, "unselected_leaf_bytes_reverified": False,
                "unselected_source_bytes_reverified": False}

    def save(self, destination):
        result = importer._write_exclusive(Path(destination), self._raw)
        _fsync_directory(Path(destination).parent)
        return result


def build_produced_record_projection(receipt_set, manifest, *, entry_cids, receipt_resolver, source_resolver,
                                     limits=ProjectionLimits()):
    try:
        root = _root(receipt_set)
        manifest = _manifest(manifest, limits)
        projected = root.partitions.project_records(manifest.records, entry_cids=entry_cids)
        rows = [{"record_summary": row["record_summary"], **root.binding_for(row["entry_cid"])}
                for row in projected["records"]]
        raw = production._canonical({"schema_version": SCHEMA_VERSION, "receipt_set": _reference(root),
            "source_partitions": _reference(root.partitions), "corpus_manifest": _reference(manifest),
            "dataset_snapshot_id": manifest.dataset_snapshot_id, "split_snapshot_id": manifest.split_snapshot_id,
            "records": rows, "training_record_ids": list(manifest._training_record_ids),
            "validation_record_ids": list(manifest._validation_record_ids)})
        projection = ProducedRecordProjection(raw, root, limits)
        projection.verify_batch(manifest, receipt_resolver=receipt_resolver, source_resolver=source_resolver)
        return projection
    except (ValueError, TypeError, KeyError, AttributeError, OSError, UnicodeError) as exc:
        if isinstance(exc, ProjectionError):
            raise
        raise ProjectionError("cannot build exact produced-record projection") from exc


def load_produced_record_projection(path, *, expected_sha256, receipt_set, expected_size_bytes=None,
                                    limits=ProjectionLimits()):
    try:
        if type(limits) is not ProjectionLimits:
            raise ProjectionError("invalid projection limits")
        production._digest(expected_sha256, "projection SHA-256")
        path = Path(path).absolute()
        size = path.lstat().st_size if expected_size_bytes is None else expected_size_bytes
        production._integer(size, "projection bytes", 1, limits.max_bytes)
        with importer._verified_file(path, {"sha256": expected_sha256, "bytes": size}, limits.max_bytes) as stream:
            raw = stream.read(size + 1)
        return ProducedRecordProjection(raw, receipt_set, limits)
    except (ValueError, TypeError, OSError) as exc:
        if isinstance(exc, ProjectionError):
            raise
        raise ProjectionError("projection artifact verification failed") from exc


__all__ = ["ProjectionError", "ProjectionLimits", "ProducedRecordProjection",
           "build_produced_record_projection", "load_produced_record_projection"]
