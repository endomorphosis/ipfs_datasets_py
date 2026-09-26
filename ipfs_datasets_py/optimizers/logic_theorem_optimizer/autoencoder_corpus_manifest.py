"""Immutable, bounded source/sample/split sidecars for one training batch.

This module verifies byte identity and declared selectors, not legal authority,
embedding producer identity, corpus-wide split independence, or formalization.
The qualified training adapter remains ``legacy_us_code``. Constitution records
can be inventoried in diagnostic manifests; corpus training rejects them until
a source-aware frontend is qualified. No parser, model weights or network is
needed to validate a manifest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any, Callable, Mapping, Sequence

from .autoencoder_training_worker import SampleRecord


SCHEMA_VERSION = "autoencoder-corpus-batch-manifest-v1"
SOURCE_KINDS = frozenset({"us_code", "us_constitution", "diagnostic"})
FRONTEND = "legacy_us_code"


class CorpusManifestError(ValueError):
    """An identity, selector, split or bounded manifest contract is invalid."""


@dataclass(frozen=True)
class ManifestLimits:
    max_records: int = 4096
    max_sources: int = 256
    max_manifest_bytes: int = 64 * 1024 * 1024
    max_source_bytes: int = 256 * 1024 * 1024
    max_total_source_bytes: int = 1024 * 1024 * 1024
    max_sample_text_bytes: int = 1024 * 1024
    max_embedding_dimensions: int = 65536
    max_total_embedding_dimensions: int = 1_000_000

    def __post_init__(self):
        ceilings = {"max_records": 65536, "max_sources": 4096,
                    "max_manifest_bytes": 256 * 1024 * 1024,
                    "max_source_bytes": 1024 * 1024 * 1024,
                    "max_total_source_bytes": 4 * 1024 * 1024 * 1024,
                    "max_sample_text_bytes": 16 * 1024 * 1024,
                    "max_embedding_dimensions": 1_000_000,
                    "max_total_embedding_dimensions": 16_000_000}
        for name, ceiling in ceilings.items():
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= ceiling:
                raise CorpusManifestError(f"{name} exceeds supported bounds")


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise CorpusManifestError("invalid strict JSON value") from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _id(value: Any) -> str:
    return "sha256:" + _sha(_json(value))


def _parse(raw: bytes) -> Any:
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CorpusManifestError("duplicate JSON field")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(CorpusManifestError("nonfinite JSON number")))
    except (UnicodeError, ValueError, RecursionError, OverflowError) as exc:
        raise CorpusManifestError("invalid manifest JSON") from exc


def _keys(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise CorpusManifestError(f"{name} has unknown or missing fields")
    return dict(value)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 4096:
        raise CorpusManifestError(f"{name} must be bounded nonempty text")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise CorpusManifestError(f"{name} must be a lowercase SHA-256")
    return value


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value < 2**63:
        raise CorpusManifestError(f"{name} must be a bounded integer")
    return value


@dataclass(frozen=True)
class SourceArtifact:
    sha256: str
    bytes: int

    def __post_init__(self):
        _digest(self.sha256, "source.sha256")
        _integer(self.bytes, "source.bytes", minimum=1)

    @classmethod
    def from_dict(cls, value):
        return cls(**_keys(value, {"sha256", "bytes"}, "source artifact"))


@dataclass(frozen=True)
class SourceSpan:
    artifact: SourceArtifact
    source_kind: str
    release_id: str
    document_id: str
    language: str
    citation: str
    byte_start: int
    byte_end: int
    normalization: str = "identity"

    def __post_init__(self):
        if not isinstance(self.artifact, SourceArtifact):
            raise CorpusManifestError("source artifact must be SourceArtifact")
        if self.source_kind not in SOURCE_KINDS:
            raise CorpusManifestError("unsupported source_kind")
        for name in ("release_id", "document_id", "language", "citation"):
            _text(getattr(self, name), name)
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", self.language):
            raise CorpusManifestError("language must be an explicit language tag")
        _integer(self.byte_start, "byte_start")
        _integer(self.byte_end, "byte_end", minimum=1)
        if not self.byte_start < self.byte_end <= self.artifact.bytes:
            raise CorpusManifestError("source byte selector is outside the artifact")
        if self.normalization not in {"identity", "whitespace-v1"}:
            raise CorpusManifestError("unsupported source normalization")

    @classmethod
    def from_dict(cls, value):
        data = _keys(value, {"artifact", "source_kind", "release_id", "document_id", "language",
                             "citation", "byte_start", "byte_end", "normalization"}, "source span")
        data["artifact"] = SourceArtifact.from_dict(data["artifact"])
        return cls(**data)


@dataclass(frozen=True)
class EmbeddingProvenance:
    model_id: str
    revision: str
    artifact_sha256: str

    def __post_init__(self):
        _text(self.model_id, "embedding.model_id")
        if not isinstance(self.revision, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.revision):
            raise CorpusManifestError("embedding revision must be an immutable commit digest")
        _digest(self.artifact_sha256, "embedding.artifact_sha256")

    @classmethod
    def from_dict(cls, value):
        return cls(**_keys(value, {"model_id", "revision", "artifact_sha256"}, "embedding provenance"))


def _numeric(value: Any) -> dict[str, str]:
    if type(value) is float and math.isfinite(value):
        return {"kind": "float64", "bits": struct.pack(">d", value).hex()}
    if type(value) is int and value.bit_length() <= 4096:
        return {"kind": "integer", "decimal": str(value)}
    raise CorpusManifestError("embedding values must be bounded finite numeric values")


def _from_numeric(value: Any) -> Any:
    if isinstance(value, Mapping) and set(value) == {"kind", "bits"} and value["kind"] == "float64":
        bits = value["bits"]
        if isinstance(bits, str) and re.fullmatch(r"[0-9a-f]{16}", bits):
            result = struct.unpack(">d", bytes.fromhex(bits))[0]
            if math.isfinite(result):
                return result
    elif isinstance(value, Mapping) and set(value) == {"kind", "decimal"} and value["kind"] == "integer":
        decimal = value["decimal"]
        if isinstance(decimal, str) and len(decimal) <= 1235 and re.fullmatch(r"0|-?[1-9][0-9]*", decimal):
            result = int(decimal)
            if result.bit_length() <= 4096:
                return result
    raise CorpusManifestError("invalid exact embedding number")


def _sample_payload(sample: SampleRecord) -> dict[str, Any]:
    if not isinstance(sample, SampleRecord):
        raise CorpusManifestError("sample must be SampleRecord")
    value = asdict(sample)
    value["embedding_vector"] = ([_numeric(item) for item in sample.embedding_vector]
                                  if sample.embedding_vector is not None else None)
    return value


def _sample_from_payload(value: Any) -> SampleRecord:
    data = _keys(value, {"title", "section", "text", "citation", "embedding_model", "embedding_vector"}, "sample")
    vector = data["embedding_vector"]
    if vector is not None:
        if not isinstance(vector, list):
            raise CorpusManifestError("embedding vector must be an array")
        data["embedding_vector"] = tuple(_from_numeric(item) for item in vector)
    try:
        return SampleRecord.from_dict(data)
    except (ValueError, TypeError, OverflowError) as exc:
        raise CorpusManifestError("invalid sample payload") from exc


@dataclass(frozen=True)
class SourceSampleRecord:
    source: SourceSpan
    sample: SampleRecord
    embedding_provenance: EmbeddingProvenance | None = None
    _record_id: str = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if not isinstance(self.source, SourceSpan) or not isinstance(self.sample, SampleRecord):
            raise CorpusManifestError("source sample requires SourceSpan and SampleRecord")
        if len(self.sample.text.encode("utf-8")) > 16 * 1024 * 1024 or (
            self.sample.embedding_vector is not None and len(self.sample.embedding_vector) > 1_000_000
        ):
            raise CorpusManifestError("sample exceeds supported construction bounds")
        if self.embedding_provenance is not None:
            if not isinstance(self.embedding_provenance, EmbeddingProvenance):
                raise CorpusManifestError("embedding provenance must be EmbeddingProvenance")
            if self.sample.embedding_vector is None or self.embedding_provenance.model_id != self.sample.embedding_model:
                raise CorpusManifestError("embedding provenance does not match the supplied sample vector/model")
        object.__setattr__(self, "_record_id", _id({"schema": "source-aware-sample-record-v1", **self._payload()}))

    def _payload(self):
        return {"source": asdict(self.source), "sample": _sample_payload(self.sample),
                "embedding_provenance": asdict(self.embedding_provenance) if self.embedding_provenance else None}

    @property
    def record_id(self) -> str:
        return self._record_id

    def to_dict(self) -> dict[str, Any]:
        return {"record_id": self.record_id, **self._payload()}

    @classmethod
    def from_dict(cls, value):
        data = _keys(value, {"record_id", "source", "sample", "embedding_provenance"}, "source sample")
        provenance = data["embedding_provenance"]
        result = cls(SourceSpan.from_dict(data["source"]), _sample_from_payload(data["sample"]),
                     EmbeddingProvenance.from_dict(provenance) if provenance is not None else None)
        if result.record_id != data["record_id"]:
            raise CorpusManifestError("source-aware record identity mismatch")
        return result


def _content_key(record: SourceSampleRecord) -> str:
    return _sha(" ".join(record.sample.text.split()).casefold().encode("utf-8"))


def _validate_records(records, training_ids, validation_ids, mode, limits):
    if mode not in {"corpus", "diagnostic"}:
        raise CorpusManifestError("mode must be corpus or diagnostic")
    if not isinstance(records, (list, tuple)) or not 1 <= len(records) <= limits.max_records:
        raise CorpusManifestError("record count exceeds bounded batch limit")
    if any(not isinstance(record, SourceSampleRecord) for record in records):
        raise CorpusManifestError("records must contain SourceSampleRecord values")
    indexed = {record.record_id: record for record in records}
    if len(indexed) != len(records):
        raise CorpusManifestError("duplicate source-aware record identity")
    for split in (training_ids, validation_ids):
        if not isinstance(split, (list, tuple)) or any(not isinstance(item, str) or item not in indexed for item in split):
            raise CorpusManifestError("split references an unknown record")
        if len(split) != len(set(split)):
            raise CorpusManifestError("duplicate record within a split")
        selectors = [(indexed[item].source.artifact.sha256, indexed[item].source.byte_start,
                      indexed[item].source.byte_end) for item in split]
        if len(selectors) != len(set(selectors)):
            raise CorpusManifestError("duplicate source selector within a split")
        # The current adapter cannot distinguish source-only aliases that have
        # exactly the same payload. Refuse an ambiguous sidecar join.
        sample_keys = [_sha(_json(_sample_payload(indexed[item].sample))) for item in split]
        if len(sample_keys) != len(set(sample_keys)):
            raise CorpusManifestError("duplicate sample payload within a split")
    if not training_ids or set(training_ids) | set(validation_ids) != set(indexed):
        raise CorpusManifestError("every batch record must be assigned and training must be nonempty")
    sources = {}
    dimensions = 0
    for record in records:
        source, sample = record.source, record.sample
        previous = sources.setdefault(source.artifact.sha256, source.artifact.bytes)
        if previous != source.artifact.bytes:
            raise CorpusManifestError("source SHA has inconsistent declared sizes")
        if source.artifact.bytes > limits.max_source_bytes:
            raise CorpusManifestError("source exceeds byte bound")
        if len(sample.text.encode("utf-8")) > limits.max_sample_text_bytes:
            raise CorpusManifestError("sample text exceeds byte bound")
        for name in ("title", "section", "embedding_model"):
            _text(getattr(sample, name), "sample." + name)
        if sample.citation is not None:
            _text(sample.citation, "sample.citation")
        size = len(sample.embedding_vector) if sample.embedding_vector is not None else 0
        if size > limits.max_embedding_dimensions:
            raise CorpusManifestError("embedding dimensions exceed bound")
        dimensions += size
        if mode == "corpus":
            if source.source_kind != "us_code" or source.language != "en":
                raise CorpusManifestError("corpus mode requires the qualified English us_code frontend")
            if sample.citation != source.citation:
                raise CorpusManifestError("corpus sample citation must match its explicit source citation")
            if sample.embedding_vector is None or sample.embedding_model.casefold().startswith("mock:") or record.embedding_provenance is None:
                raise CorpusManifestError("corpus mode requires supplied external embeddings with immutable model provenance")
    if len(sources) > limits.max_sources or sum(sources.values()) > limits.max_total_source_bytes:
        raise CorpusManifestError("source closure exceeds aggregate bound")
    if dimensions > limits.max_total_embedding_dimensions:
        raise CorpusManifestError("embedding closure exceeds aggregate dimension bound")
    if mode == "corpus":
        if not validation_ids:
            raise CorpusManifestError("corpus mode requires an explicit validation split")
        train, validation = [indexed[item] for item in training_ids], [indexed[item] for item in validation_ids]
        checks = (
            (lambda record: record.source.artifact.sha256, "source artifact"),
            (lambda record: (record.source.source_kind, record.source.document_id), "document"),
            (_content_key, "normalized content"),
        )
        for key, label in checks:
            if {key(record) for record in train} & {key(record) for record in validation}:
                raise CorpusManifestError(f"cross-split {label} leakage within this batch")


def _read_verified(path: Any, reference: Mapping[str, Any], maximum: int) -> bytes:
    if reference["bytes"] > maximum:
        raise CorpusManifestError("artifact exceeds byte bound")
    try:
        path = Path(path)
        if not path.is_absolute():
            raise CorpusManifestError("resolver must return an absolute local path")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != reference["bytes"]:
                raise CorpusManifestError("artifact is not a regular file of the declared size")
            raw = stream.read(reference["bytes"] + 1)
    except (OSError, TypeError) as exc:
        raise CorpusManifestError("artifact could not be read") from exc
    if len(raw) != reference["bytes"] or _sha(raw) != reference["sha256"]:
        raise CorpusManifestError("artifact byte identity mismatch")
    return raw


@dataclass(frozen=True)
class CorpusManifest:
    """Validated immutable bytes; returned metadata is freshly decoded."""

    _raw: bytes
    limits: ManifestLimits = ManifestLimits()
    _sha256: str = field(init=False, repr=False, compare=False)
    _records: tuple[SourceSampleRecord, ...] = field(init=False, repr=False, compare=False)
    _dataset_snapshot_id: str = field(init=False, repr=False, compare=False)
    _split_snapshot_id: str = field(init=False, repr=False, compare=False)
    _mode: str = field(init=False, repr=False, compare=False)
    _training_record_ids: tuple[str, ...] = field(init=False, repr=False, compare=False)
    _validation_record_ids: tuple[str, ...] = field(init=False, repr=False, compare=False)
    _source_artifacts: tuple[SourceArtifact, ...] = field(init=False, repr=False, compare=False)
    _source_kind_counts: tuple[tuple[str, int], ...] = field(init=False, repr=False, compare=False)
    _language_counts: tuple[tuple[str, int], ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if type(self._raw) is not bytes or not 1 <= len(self._raw) <= self.limits.max_manifest_bytes:
            raise CorpusManifestError("manifest exceeds byte bound")
        data = _keys(_parse(self._raw), {"schema_version", "dataset", "split", "dataset_snapshot_id", "split_snapshot_id"}, "manifest")
        if data["schema_version"] != SCHEMA_VERSION or _json(data) != self._raw:
            raise CorpusManifestError("unsupported or noncanonical manifest bytes")
        dataset = _keys(data["dataset"], {"schema_version", "frontend", "records"}, "dataset")
        split = _keys(data["split"], {"schema_version", "dataset_snapshot_id", "mode", "training_record_ids", "validation_record_ids"}, "split")
        if dataset["schema_version"] != "source-aware-batch-dataset-v1" or dataset["frontend"] != FRONTEND or split["schema_version"] != "ordered-batch-split-v1":
            raise CorpusManifestError("unsupported dataset, frontend or split schema")
        if not isinstance(dataset["records"], list) or len(dataset["records"]) > self.limits.max_records:
            raise CorpusManifestError("record count exceeds bounded batch limit")
        records = tuple(SourceSampleRecord.from_dict(record) for record in dataset["records"])
        _validate_records(records, split["training_record_ids"], split["validation_record_ids"], split["mode"], self.limits)
        if [record.record_id for record in records] != sorted(record.record_id for record in records):
            raise CorpusManifestError("dataset records must be sorted by source-aware identity")
        if data["dataset_snapshot_id"] != _id(dataset) or split["dataset_snapshot_id"] != data["dataset_snapshot_id"] or data["split_snapshot_id"] != _id(split):
            raise CorpusManifestError("dataset or split snapshot identity mismatch")
        artifacts = {record.source.artifact.sha256: record.source.artifact for record in records}
        source_kinds, languages = {}, {}
        for record in records:
            source_kinds[record.source.source_kind] = source_kinds.get(record.source.source_kind, 0) + 1
            languages[record.source.language] = languages.get(record.source.language, 0) + 1
        for name, value in {
            "_sha256": _sha(self._raw), "_records": records, "_dataset_snapshot_id": data["dataset_snapshot_id"],
            "_split_snapshot_id": data["split_snapshot_id"], "_mode": split["mode"],
            "_training_record_ids": tuple(split["training_record_ids"]),
            "_validation_record_ids": tuple(split["validation_record_ids"]),
            "_source_artifacts": tuple(artifacts[key] for key in sorted(artifacts)),
            "_source_kind_counts": tuple(sorted(source_kinds.items())), "_language_counts": tuple(sorted(languages.items())),
        }.items():
            object.__setattr__(self, name, value)

    def to_dict(self):
        return _parse(self._raw)

    def to_bytes(self):
        return self._raw

    @property
    def sha256(self):
        return self._sha256

    @property
    def dataset_snapshot_id(self):
        return self._dataset_snapshot_id

    @property
    def split_snapshot_id(self):
        return self._split_snapshot_id

    @property
    def mode(self):
        return self._mode

    @property
    def records(self):
        return self._records

    @property
    def source_refs(self):
        return tuple(asdict(artifact) for artifact in self._source_artifacts)

    @property
    def source_kind_counts(self):
        return dict(self._source_kind_counts)

    @property
    def language_counts(self):
        return dict(self._language_counts)

    def verification_summary(self):
        return {"mode": self.mode, "dataset_snapshot_id": self.dataset_snapshot_id,
                "split_snapshot_id": self.split_snapshot_id, "frontend": FRONTEND,
                "record_count": len(self.records), "training_record_count": len(self._training_record_ids),
                "validation_record_count": len(self._validation_record_ids), "source_count": len(self._source_artifacts),
                "source_kind_counts": self.source_kind_counts, "language_counts": self.language_counts,
                "batch_split_disjoint": self.mode == "corpus",
                "global_holdout_verified": False, "embedding_producer_authenticated": False,
                "source_authority_authenticated": False}

    def validate_sources(self, resolver: Callable[[Mapping[str, Any]], Any]):
        groups = {}
        for record in self.records:
            groups.setdefault(record.source.artifact.sha256, []).append(record)
        total_bytes = 0
        for reference in self.source_refs:
            try:
                path = resolver(dict(reference))
            except (KeyError, OSError, ValueError) as exc:
                raise CorpusManifestError("source missing from trusted resolver") from exc
            raw = _read_verified(path, reference, self.limits.max_source_bytes)
            try:
                raw.decode("utf-8")
                for record in groups[reference["sha256"]]:
                    source = record.source
                    selected = raw[source.byte_start:source.byte_end].decode("utf-8")
                    if source.normalization == "whitespace-v1":
                        selected = " ".join(selected.split())
                    if selected != record.sample.text:
                        raise CorpusManifestError("source selector does not reproduce the exact sample text")
            except UnicodeError as exc:
                raise CorpusManifestError("source or selector is not exact UTF-8") from exc
            total_bytes += len(raw)
        return {**self.verification_summary(), "source_bytes_verified": total_bytes,
                "source_selectors_verified": True}

    def verify_job_records(self, samples, validation_samples, *, dataset_snapshot_id=None, split_snapshot_id=None):
        if dataset_snapshot_id is not None and dataset_snapshot_id != self.dataset_snapshot_id:
            raise CorpusManifestError("job dataset snapshot identity mismatch")
        if split_snapshot_id is not None and split_snapshot_id != self.split_snapshot_id:
            raise CorpusManifestError("job split snapshot identity mismatch")
        indexed = {record.record_id: record for record in self.records}
        for supplied, record_ids in ((samples, self._training_record_ids), (validation_samples, self._validation_record_ids)):
            if not isinstance(supplied, (tuple, list)) or len(supplied) != len(record_ids):
                raise CorpusManifestError("job sample count differs from ordered split membership")
            for value, record_id in zip(supplied, record_ids):
                try:
                    sample = value if isinstance(value, SampleRecord) else SampleRecord.from_dict(value)
                except (ValueError, TypeError, OverflowError) as exc:
                    raise CorpusManifestError("invalid job sample") from exc
                if _json(_sample_payload(sample)) != _json(_sample_payload(indexed[record_id].sample)):
                    raise CorpusManifestError("job sample differs from ordered exact manifest payload")
        return {**self.verification_summary(), "job_records_verified": True,
                "training_record_ids": list(self._training_record_ids),
                "validation_record_ids": list(self._validation_record_ids)}

    def save(self, destination, *, resolver):
        return write_corpus_manifest(destination, self, resolver=resolver)


def build_corpus_manifest(records: Sequence[SourceSampleRecord], *, training_record_ids: Sequence[str],
                          validation_record_ids: Sequence[str], mode: str = "corpus",
                          limits: ManifestLimits = ManifestLimits()) -> CorpusManifest:
    _validate_records(records, training_record_ids, validation_record_ids, mode, limits)
    dataset = {"schema_version": "source-aware-batch-dataset-v1", "frontend": FRONTEND,
               "records": [record.to_dict() for record in sorted(records, key=lambda item: item.record_id)]}
    dataset_id = _id(dataset)
    split = {"schema_version": "ordered-batch-split-v1", "dataset_snapshot_id": dataset_id, "mode": mode,
             "training_record_ids": list(training_record_ids), "validation_record_ids": list(validation_record_ids)}
    return CorpusManifest(_json({"schema_version": SCHEMA_VERSION, "dataset": dataset, "split": split,
                                 "dataset_snapshot_id": dataset_id, "split_snapshot_id": _id(split)}), limits)


def write_corpus_manifest(destination, manifest: CorpusManifest, *, resolver):
    if not isinstance(manifest, CorpusManifest):
        raise CorpusManifestError("manifest must be CorpusManifest")
    manifest.validate_sources(resolver)
    path = Path(destination)
    with path.open("xb") as stream:
        stream.write(manifest.to_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path.absolute()), "sha256": manifest.sha256, "bytes": len(manifest.to_bytes()),
            "dataset_snapshot_id": manifest.dataset_snapshot_id, "split_snapshot_id": manifest.split_snapshot_id}


def load_corpus_manifest(path, *, expected_sha256: str, expected_size_bytes: int | None = None,
                         limits: ManifestLimits = ManifestLimits()) -> CorpusManifest:
    _digest(expected_sha256, "manifest.sha256")
    path = Path(path).absolute()
    size = path.stat().st_size if expected_size_bytes is None else expected_size_bytes
    _integer(size, "manifest.bytes", minimum=1)
    raw = _read_verified(path, {"sha256": expected_sha256, "bytes": size}, limits.max_manifest_bytes)
    return CorpusManifest(raw, limits)


__all__ = ["CorpusManifestError", "ManifestLimits", "SourceArtifact", "SourceSpan", "EmbeddingProvenance",
           "SourceSampleRecord", "CorpusManifest", "build_corpus_manifest", "write_corpus_manifest", "load_corpus_manifest"]
