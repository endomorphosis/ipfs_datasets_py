"""Bounded, exact physical U.S. Code rows for an offline corpus export.

This adapter reuses the inventory's wrapper and corpus decoders. It holds at
most one decoded source shard, not the full text corpus. Published retrieval
dispositions, split membership and producer observations confer no legal or
training admission. Original shard bytes remain part of the export closure.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path
import stat

from . import autoencoder_uscode_import as importer
from . import autoencoder_uscode_inventory as inventory_codec
from .autoencoder_embedding_receipt_set import EmbeddingReceiptSet, ReceiptSetLimits
from .autoencoder_source_partitions import SourcePartitions, SourcePartitionLimits


SCHEMA_VERSION = "autoencoder-uscode-corpus-rows-v1"
ROW_FIELDS = (
    "source_row_id", "inventory_sha256", "source_relative_path", "source_sha256",
    "source_bytes", "row_index", "entry_cid", "legal_id", "source_status",
    "original_status", "wrapper_verified", "duplicate_entry_cid", "source_eligible",
    "record_sha256", "record_json", "text", "text_sha256", "text_bytes",
    "normalized_content_sha256", "document_id", "title", "section", "citation",
    "input_id", "group_id", "split", "eligible_alias_count", "embedding_status",
    "embedding_receipt_sha256", "embedding_result_index",
    "admitted", "formalized", "formalization_status",
)
NULLABLE_FIELDS = frozenset({
    "record_sha256", "record_json", "text", "text_sha256", "text_bytes",
    "normalized_content_sha256", "document_id", "title", "section", "citation",
    "input_id", "group_id", "split", "embedding_receipt_sha256",
    "embedding_result_index",
})
ROW_TYPES = {
    name: ("bool" if name in {"wrapper_verified", "duplicate_entry_cid", "source_eligible",
                             "admitted", "formalized"}
           else "int64" if name in {"source_bytes", "row_index", "text_bytes",
                                    "eligible_alias_count", "embedding_result_index"}
           else "string")
    for name in ROW_FIELDS
}
_QUALIFICATION = {
    "admitted": False, "formalized": False, "source_authority_authenticated": False,
    "original_official_source_bytes_verified": False, "full_federal_corpus_complete": False,
    "global_holdout_verified": False, "training_eligible": False,
}


class USCodeCorpusRowsError(ValueError):
    """A source export is incomplete, inconsistent or changed during reading."""


def _ref(value):
    return {"sha256": importer._sha(value.to_bytes()), "bytes": len(value.to_bytes())}


def _source_row_id(inventory_sha256, relative_path, row_index):
    return "sha256:" + importer._sha(importer._json({
        "schema": "source-inventory-row-v1", "inventory_sha256": inventory_sha256,
        "relative_path": relative_path, "row_index": row_index,
    }))


def _ordinary_path(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise USCodeCorpusRowsError("resolver must return an absolute ordinary path")
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise USCodeCorpusRowsError("source path must not contain symlinks")
        if component == path:
            if not stat.S_ISREG(info.st_mode):
                raise USCodeCorpusRowsError("source artifact must be a regular file")
        elif not stat.S_ISDIR(info.st_mode):
            raise USCodeCorpusRowsError("source ancestor must be a directory")
    return path


class _CapturedResolver:
    """Resolve each exact artifact once; subsequent reads never call the owner."""

    def __init__(self, resolver):
        if not callable(resolver):
            raise USCodeCorpusRowsError("trusted artifact resolver required")
        self.resolver = resolver
        self.entries = {}

    def __call__(self, value):
        ref = importer._reference(value)
        key = ref["sha256"]
        if key not in self.entries:
            if len(self.entries) >= 65536:
                raise USCodeCorpusRowsError("resolved artifact count exceeds bound")
            self.entries[key] = (ref, _ordinary_path(self.resolver(dict(ref))))
        expected, path = self.entries[key]
        if expected != ref:
            raise USCodeCorpusRowsError("artifact digest has conflicting byte sizes")
        return path

    def recheck(self, maximum):
        for ref, path in self.entries.values():
            _ordinary_path(path)
            with importer._verified_file(path, ref, maximum):
                pass


class USCodeCorpusRows:
    """One-shot physical-row stream with detached metadata and final guards.

    ``summary`` and ``verify_final`` require complete iterator exhaustion.
    Abandoning or closing the iterator never establishes complete coverage.
    Callers retaining yielded rows own that memory; this provider retains only
    metadata and the currently bounded decoded shard. No parser or model runs.
    """

    def __init__(self, inventory, *, release, resolver, partitions=None,
                 receipt_set=None, receipt_resolver=None, source_resolver=None,
                 batch_size=64):
        if type(batch_size) is not int or not 1 <= batch_size <= 256:
            raise USCodeCorpusRowsError("batch_size must be within [1,256]")
        if type(inventory) is not inventory_codec.USCodeSourceInventory:
            raise USCodeCorpusRowsError("verified source inventory required")
        if type(release) is not importer.USCodeRelease:
            raise USCodeCorpusRowsError("verified U.S. Code release required")
        if receipt_set is not None and partitions is None:
            raise USCodeCorpusRowsError("receipt set requires source partitions")
        try:
            # Reconstruct bounded codecs rather than trust mutable dataclass
            # internals or claimed digests on objects supplied by a caller.
            limits = inventory_codec.InventoryLimits(**asdict(inventory.limits))
            self._inventory = inventory_codec.USCodeSourceInventory(inventory.to_bytes(), limits)
            importer.USCodeImportLimits(**asdict(release.limits))
            self._resolver = _CapturedResolver(resolver)
            self._release = importer.verify_uscode_release(release, resolver=self._resolver)
            self._data = self._inventory.to_dict()
            if self._data["release"] != inventory_codec._release_metadata(self._release):
                raise USCodeCorpusRowsError("inventory belongs to another exact release")
            declared = [asdict(item) for item in sorted(
                self._release.corpus_shards, key=lambda item: item.relative_path)]
            if [shard["artifact"] for shard in self._data["shards"]] != declared:
                raise USCodeCorpusRowsError("inventory must cover every exact declared corpus shard")
            if any(shard["status"] != "verified" for shard in self._data["shards"]):
                raise USCodeCorpusRowsError("complete verified physical shard inventory required")
            self._partitions = None
            self._partition_rows = {}
            if partitions is not None:
                if type(partitions) is not SourcePartitions:
                    raise USCodeCorpusRowsError("verified source partitions required")
                self._partitions = SourcePartitions(
                    partitions.to_bytes(), self._inventory,
                    SourcePartitionLimits(**asdict(partitions.limits)))
                self._partition_rows = {
                    row["source_row_id"]: row for row in self._partitions.to_dict()["rows"]}
            self._receipt_set = None
            self._receipt_resolver = self._source_resolver = None
            self._coverage = {}
            receipt_verification = None
            if receipt_set is not None:
                if type(receipt_set) is not EmbeddingReceiptSet:
                    raise USCodeCorpusRowsError("verified embedding receipt set required")
                self._receipt_set = EmbeddingReceiptSet(
                    receipt_set.to_bytes(), self._partitions,
                    ReceiptSetLimits(**asdict(receipt_set.limits)))
                self._receipt_resolver = _CapturedResolver(receipt_resolver)
                self._source_resolver = _CapturedResolver(source_resolver)
                receipt_verification = self._receipt_set.verify_all(
                    receipt_resolver=self._receipt_resolver, source_resolver=self._source_resolver)
                self._coverage = {row["input_id"]: row
                                  for row in self._receipt_set.to_dict()["inputs"]}
            self._entries = Counter()
            self._aliases = Counter()
            for shard in self._data["shards"]:
                for row in shard["rows"]:
                    if row["entry_cid"]:
                        self._entries[row["entry_cid"]] += 1
                    if row["status"] == "ready_published_text":
                        self._aliases[row["metadata"]["input_id"]] += 1
            self._sources = tuple({
                "relative_path": item.relative_path, **item.reference,
                "path": str(self._resolver(item.reference)),
            } for item in sorted(self._release.corpus_shards, key=lambda item: item.relative_path))
            manifest_ref = self._release.manifest_reference
            with importer._verified_file(self._resolver(manifest_ref), manifest_ref,
                                         self._release.limits.max_manifest_bytes) as stream:
                manifest_raw = stream.read(self._release.limits.max_manifest_bytes + 1)
            roots = [("provenance/source-inventory.json", self._inventory.to_bytes()),
                     ("provenance/release-manifest.json", manifest_raw)]
            if self._partitions is not None:
                roots.append(("provenance/source-partitions.json", self._partitions.to_bytes()))
            if self._receipt_set is not None:
                roots.append(("provenance/embedding-receipt-set.json", self._receipt_set.to_bytes()))
            self._roots = tuple(roots)
            evidence = []
            for captured, directory, suffix in (
                    (self._receipt_resolver, "embedding-receipts", "json"),
                    (self._source_resolver, "embedding-inputs", "txt")):
                if captured is not None:
                    evidence.extend({
                        "relative_path": f"provenance/{directory}/{ref['sha256']}.{suffix}",
                        **ref, "path": str(path),
                    } for ref, path in captured.entries.values())
            self._evidence = tuple(sorted(evidence, key=lambda item: item["relative_path"]))
            inv_summary = self._inventory.summary()
            self._metadata_raw = importer._json({
                "schema_version": SCHEMA_VERSION, "scope": inventory_codec.SCOPE,
                "release": {"repo_id": self._release.repo_id, "revision": self._release.revision,
                            "manifest": manifest_ref, "import_limits": asdict(self._release.limits)},
                "inventory": _ref(self._inventory),
                "source_partitions": _ref(self._partitions) if self._partitions is not None else None,
                "embedding_receipt_set": _ref(self._receipt_set) if self._receipt_set is not None else None,
                "declared_row_count": inv_summary["declared_row_count"],
                "declared_corpus_shards": inv_summary["declared_corpus_shards"],
                "declared_compressed_bytes": inv_summary["declared_compressed_bytes"],
                "source_inventory_summary": inv_summary,
                "source_partition_verification": (self._partitions.verification_summary()
                                                  if self._partitions is not None else None),
                "receipt_set_verification": receipt_verification,
                "qualification": dict(_QUALIFICATION),
            })
        except (ValueError, TypeError, KeyError, OSError, AttributeError) as exc:
            if isinstance(exc, USCodeCorpusRowsError):
                raise
            raise USCodeCorpusRowsError("invalid or unavailable exact source export inputs") from exc
        self._batch_size = batch_size
        self._started = self._consumed = False
        self._summary_raw = None

    @property
    def metadata(self):
        return importer._parse(self._metadata_raw)

    @property
    def source_artifacts(self):
        return tuple(dict(item) for item in self._sources)

    @property
    def evidence_artifacts(self):
        return tuple(dict(item) for item in self._evidence)

    @property
    def provenance_artifacts(self):
        return tuple({"relative_path": name, "raw": raw} for name, raw in self._roots)

    def _row(self, artifact, row, wrapper):
        meta = row["metadata"] or {}
        identity = meta.get("canonical_identity") or {}
        source_id = _source_row_id(self._inventory.sha256, artifact["relative_path"], row["row_index"])
        assignment = self._partition_rows.get(source_id, {})
        eligible = row["status"] == "ready_published_text"
        binding = self._coverage.get(meta.get("input_id"), {}) if eligible else {}
        if eligible and self._receipt_set is not None and not binding:
            raise USCodeCorpusRowsError("eligible source input lacks complete receipt disposition")
        payload = wrapper.payload if wrapper is not None else {}
        text = payload.get("text") if type(payload.get("text")) is str else None
        result = {
            "source_row_id": source_id, "inventory_sha256": self._inventory.sha256,
            "source_relative_path": artifact["relative_path"], "source_sha256": artifact["sha256"],
            "source_bytes": artifact["bytes"], "row_index": row["row_index"],
            "entry_cid": row["entry_cid"], "legal_id": row["legal_id"],
            "source_status": row["status"], "original_status": row["original_status"],
            "wrapper_verified": row["wrapper_verified"], "duplicate_entry_cid": row["duplicate_entry_cid"],
            "source_eligible": eligible, "record_sha256": meta.get("record_sha256"),
            "record_json": wrapper._payload_json.decode("utf-8") if wrapper is not None else None,
            "text": text, "text_sha256": meta.get("text_sha256"), "text_bytes": meta.get("text_bytes"),
            "normalized_content_sha256": meta.get("normalized_content_sha256"),
            "document_id": identity.get("document_id"), "title": identity.get("title"),
            "section": identity.get("section"), "citation": identity.get("citation"),
            "input_id": meta.get("input_id"), "group_id": assignment.get("group_id"),
            "split": assignment.get("split"),
            "eligible_alias_count": self._aliases[meta["input_id"]] if eligible else 0,
            "embedding_status": (binding["status"] if binding else "unavailable") if eligible else "source_ineligible",
            "embedding_receipt_sha256": binding.get("receipt_sha256"),
            "embedding_result_index": binding.get("result_index"),
            "admitted": False, "formalized": False, "formalization_status": "not_observed",
        }
        return result

    def iter_rows(self):
        if self._started:
            raise USCodeCorpusRowsError("source row iterator is one-shot")
        self._started = True
        return self._iterate()

    def _iterate(self):
        counts = {name: Counter() for name in ("source_status", "original_status", "split", "embedding_status")}
        rows_yielded = 0
        wrapped = verified = failures = fresh = indexed = result = None
        try:
            for shard in self._data["shards"]:
                artifact = shard["artifact"]
                wrapped, verified, failures = importer._read_wrapped_shard_with_rows(
                    self._release, artifact["relative_path"], resolver=self._resolver,
                    batch_size=self._batch_size)
                if not wrapped.complete or wrapped.rows_scanned != artifact["row_count"]:
                    raise USCodeCorpusRowsError("source shard reader returned incomplete physical coverage")
                fresh = inventory_codec._shard_rows(
                    self._release, wrapped, verified, failures,
                    metadata_budget=self._inventory.limits.max_metadata_bytes)
                for row in fresh:
                    if row["entry_cid"] and self._entries[row["entry_cid"]] > 1:
                        row["duplicate_entry_cid"] = True
                        row["status"] = "duplicate_entry_cid"
                if fresh != shard["rows"]:
                    raise USCodeCorpusRowsError("current source rows differ from sealed physical inventory")
                indexed = {row.row_index: row for row in verified}
                for row in fresh:
                    result = self._row(artifact, row, indexed.get(row["row_index"]))
                    for name, counter in counts.items():
                        counter[result[name] if result[name] is not None else "unassigned"] += 1
                    rows_yielded += 1
                    yield result
                    result = None
                # Release the previous shard's source text before decoding the next.
                wrapped = verified = failures = fresh = indexed = result = None
            if rows_yielded != self.metadata["declared_row_count"]:
                raise USCodeCorpusRowsError("exported physical row count differs from complete inventory")
            self._consumed = True
            self.verify_final()
            self._summary_raw = importer._json({
                "schema_version": SCHEMA_VERSION, "scope": inventory_codec.SCOPE,
                "physical_row_count": rows_yielded,
                "source_status_counts": dict(sorted(counts["source_status"].items())),
                "original_status_counts": dict(sorted(counts["original_status"].items())),
                "split_counts": dict(sorted(counts["split"].items())),
                "embedding_status_counts": dict(sorted(counts["embedding_status"].items())),
                "eligible_row_count": sum(self._aliases.values()),
                "eligible_unique_input_count": len(self._aliases),
                "complete_physical_coverage_verified": True,
                "current_all_shard_bytes_reverified": True,
                "current_receipt_closure_bytes_reverified": self._receipt_set is not None,
                "qualification": dict(_QUALIFICATION),
            })
        except (ValueError, TypeError, KeyError, OSError, AttributeError) as exc:
            self._consumed = False
            if isinstance(exc, USCodeCorpusRowsError):
                raise
            raise USCodeCorpusRowsError("source row export verification failed") from exc
        finally:
            wrapped = verified = failures = fresh = indexed = result = None
            if self._summary_raw is None:
                self._consumed = False

    def verify_final(self):
        if not self._consumed:
            raise USCodeCorpusRowsError("complete source row exhaustion required before final verification")
        try:
            self._resolver.recheck(max(self._release.limits.max_manifest_bytes,
                                       self._release.limits.max_shard_bytes))
            if self._receipt_resolver is not None:
                self._receipt_resolver.recheck(64 * 1024**2)
                self._source_resolver.recheck(64 * 1024**2)
            # Public metadata exposes copies only; internal canonical roots must
            # still have the originally bound bytes at the completion boundary.
            expected = dict(self._roots)
            if self._inventory.to_bytes() != expected["provenance/source-inventory.json"]:
                raise USCodeCorpusRowsError("source inventory changed during export")
            if self._partitions is not None and self._partitions.to_bytes() != expected["provenance/source-partitions.json"]:
                raise USCodeCorpusRowsError("source partitions changed during export")
            if self._receipt_set is not None and self._receipt_set.to_bytes() != expected["provenance/embedding-receipt-set.json"]:
                raise USCodeCorpusRowsError("receipt set changed during export")
        except (ValueError, TypeError, KeyError, OSError, AttributeError) as exc:
            if isinstance(exc, USCodeCorpusRowsError):
                raise
            raise USCodeCorpusRowsError("source export closure changed before completion") from exc

    def summary(self):
        if not self._consumed or self._summary_raw is None:
            raise USCodeCorpusRowsError("complete source row exhaustion required before summary")
        self.verify_final()
        return importer._parse(self._summary_raw)
