"""Bounded offline imports from the descriptor-bound U.S. Code release.

Only the direct ``publicus-ir-graphrag/v2`` root-artifact profile is supported.
Published retrieval dispositions and source claims are preserved as claims;
they do not prove official-source identity, legal currentness, or Lean admission.
Extracted UTF-8 artifacts contain the exact published ``text`` field, not the
original official XML/HTML. No parser, embedding generation or network runs here.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Callable, Mapping, Sequence

from .autoencoder_corpus_manifest import SourceArtifact, SourceSampleRecord, SourceSpan
from .autoencoder_training_worker import SampleRecord


RELEASE_SCHEMA = "uscode-sparse-graphrag-release-schema-v2"
RELEASE_PROFILE = "publicus-ir-graphrag/v2"
WRAPPER_COLUMNS = ("entry_cid", "legal_id", "family", "record_sha256", "record_json")


class USCodeImportError(ValueError):
    """Missing, inconsistent, corrupt or over-budget release input."""


@dataclass(frozen=True)
class USCodeImportLimits:
    max_manifest_bytes: int = 8 * 1024 * 1024
    max_artifacts: int = 16384
    max_shard_bytes: int = 256 * 1024 * 1024
    max_uncompressed_shard_bytes: int = 256 * 1024 * 1024
    max_rows_per_shard: int = 4096
    max_record_bytes: int = 2 * 1024 * 1024
    max_text_bytes: int = 1024 * 1024
    max_verified_rows: int = 4096
    max_verified_shards: int = 16
    max_verified_shard_bytes: int = 1024 * 1024 * 1024
    max_extracted_rows: int = 256
    max_extracted_bytes: int = 256 * 1024 * 1024

    def __post_init__(self):
        ceilings = {"max_manifest_bytes": 64 * 1024 * 1024, "max_artifacts": 65536,
                    "max_shard_bytes": 1024 * 1024 * 1024, "max_uncompressed_shard_bytes": 1024 * 1024 * 1024,
                    "max_rows_per_shard": 4096, "max_record_bytes": 16 * 1024 * 1024,
                    "max_text_bytes": 16 * 1024 * 1024, "max_verified_rows": 65536,
                    "max_verified_shards": 256, "max_verified_shard_bytes": 4 * 1024 * 1024 * 1024,
                    "max_extracted_rows": 4096,
                    "max_extracted_bytes": 1024 * 1024 * 1024}
        for name, ceiling in ceilings.items():
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= ceiling:
                raise USCodeImportError(f"{name} exceeds supported bounds")


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise USCodeImportError("invalid strict JSON payload") from exc


def _parse(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise USCodeImportError("duplicate JSON field")
            result[key] = value
        return result
    try:
        result = json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(USCodeImportError("nonfinite JSON")))
        _json(result)  # Also catches exponent-overflow float values.
        return result
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise USCodeImportError("invalid release JSON") from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise USCodeImportError("expected lowercase SHA-256")
    return value


def _int(value: Any, label: str, minimum=0) -> int:
    if type(value) is not int or not minimum <= value < 2**63:
        raise USCodeImportError(f"invalid bounded {label}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 4096:
        raise USCodeImportError(f"invalid bounded {label}")
    return value


def _reference(value: Any) -> dict[str, Any]:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if not isinstance(value, Mapping):
        raise USCodeImportError("artifact descriptor must be a mapping")
    return {"sha256": _digest(value.get("sha256")), "bytes": _int(value.get("bytes"), "artifact bytes", 1)}


def _path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise USCodeImportError("unsafe release-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in value.split("/")) or str(path) != value:
        raise USCodeImportError("unsafe release-relative path")
    return value


def _resolve_artifact(resolver, reference):
    try:
        return resolver(dict(reference))
    except (KeyError, ValueError, OSError, TypeError) as exc:
        raise USCodeImportError("artifact is absent from the trusted resolver") from exc


@contextmanager
def _verified_file(path, reference, maximum):
    if reference["bytes"] > maximum:
        raise USCodeImportError("artifact exceeds byte bound")
    try:
        path = Path(path)
        if not path.is_absolute():
            raise USCodeImportError("resolver must return an absolute local path")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != reference["bytes"]:
                raise USCodeImportError("artifact is not a regular file of declared size")
            digest = hashlib.sha256()
            size = 0
            for raw in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(raw)
                if size > reference["bytes"]:
                    raise USCodeImportError("artifact grew beyond its bound")
                digest.update(raw)
            if size != reference["bytes"] or digest.hexdigest() != reference["sha256"]:
                raise USCodeImportError("artifact byte identity mismatch")
            stream.seek(0)
            yield stream
            # Decode through this same open handle, then recheck its bytes so
            # concurrent in-place writes cannot produce a successful import.
            stream.seek(0)
            digest = hashlib.sha256()
            size = 0
            for raw in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(raw)
                if size > reference["bytes"]:
                    raise USCodeImportError("artifact changed while decoding")
                digest.update(raw)
            if size != reference["bytes"] or digest.hexdigest() != reference["sha256"]:
                raise USCodeImportError("artifact changed while decoding")
    except (OSError, TypeError) as exc:
        raise USCodeImportError("immutable artifact could not be read") from exc


@dataclass(frozen=True)
class ReleaseArtifact:
    relative_path: str
    family: str
    sha256: str
    bytes: int
    row_count: int
    schema_id: str
    media_type: str

    @property
    def reference(self):
        return {"sha256": self.sha256, "bytes": self.bytes}


@dataclass(frozen=True)
class USCodeRelease:
    repo_id: str
    revision: str
    _manifest_reference: SourceArtifact
    artifacts: tuple[ReleaseArtifact, ...]
    model_id: str
    model_revision: str
    vector_space_id: str
    release_point: str
    source_revision: str
    manifest_digest: str
    limits: USCodeImportLimits

    @property
    def manifest_reference(self):
        return asdict(self._manifest_reference)

    @property
    def release_id(self):
        return f"hf:{self.repo_id}@{self.revision}#manifest-sha256:{self._manifest_reference.sha256}"

    @property
    def corpus_shards(self):
        return tuple(artifact for artifact in self.artifacts if artifact.family == "corpus")

    def artifact(self, relative_path):
        matches = [artifact for artifact in self.artifacts if artifact.relative_path == relative_path]
        if len(matches) != 1:
            raise USCodeImportError("artifact is absent from the pinned root manifest")
        return matches[0]


def load_uscode_release(manifest_artifact, *, repo_id: str, revision: str, resolver=None,
                        limits: USCodeImportLimits = USCodeImportLimits()) -> USCodeRelease:
    if not isinstance(repo_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo_id):
        raise USCodeImportError("invalid explicit dataset repository")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise USCodeImportError("release revision must be an immutable commit")
    descriptor = asdict(manifest_artifact) if is_dataclass(manifest_artifact) else dict(manifest_artifact)
    reference = _reference(descriptor)
    path = _resolve_artifact(resolver, reference) if resolver is not None else descriptor.get("path")
    with _verified_file(path, reference, limits.max_manifest_bytes) as stream:
        manifest = _parse(stream.read(limits.max_manifest_bytes + 1))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != RELEASE_SCHEMA or manifest.get("release_profile") != RELEASE_PROFILE:
        raise USCodeImportError("unsupported direct root release profile")
    if manifest.get("dataset_repo_id") != repo_id or manifest.get("default_excludes_recovery") is not True:
        raise USCodeImportError("release repository or recovery exclusion mismatch")
    digest = _digest(manifest.get("manifest_digest"))
    if _sha(_json({key: value for key, value in manifest.items() if key != "manifest_digest"})) != digest:
        raise USCodeImportError("manifest internal digest mismatch")
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list) or not 1 <= len(raw_artifacts) <= limits.max_artifacts:
        raise USCodeImportError("root artifact count exceeds bound")
    artifacts = []
    paths = set()
    for raw in raw_artifacts:
        if not isinstance(raw, dict):
            raise USCodeImportError("invalid root artifact descriptor")
        path = _path(raw.get("relative_path"))
        if path in paths:
            raise USCodeImportError("duplicate release artifact path")
        paths.add(path)
        family = _text(raw.get("family"), "artifact family")
        artifact = ReleaseArtifact(path, family, _digest(raw.get("sha256")),
            _int(raw.get("size_bytes"), "artifact size", 1), _int(raw.get("row_count"), "artifact row count"),
            _text(raw.get("schema_id"), "artifact schema"), _text(raw.get("media_type"), "artifact media type"))
        if family == "corpus" and (not path.startswith("data/corpus/") or artifact.schema_id != "uscode-corpus-row/v1"):
            raise USCodeImportError("unsupported corpus artifact descriptor")
        if family in {"corpus", "vectors"} and not 1 <= artifact.row_count <= limits.max_rows_per_shard:
            raise USCodeImportError("selected family row count exceeds physical shard bound")
        artifacts.append(artifact)
    if not any(artifact.family == "corpus" for artifact in artifacts):
        raise USCodeImportError("release has no corpus family")
    model_revision = _text(manifest.get("model_revision"), "model revision")
    source_revision = _text(manifest.get("source_revision"), "source revision")
    if not re.fullmatch(r"[0-9a-f]{40}", model_revision) or not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise USCodeImportError("release model/source revision is mutable")
    return USCodeRelease(repo_id, revision, SourceArtifact(**reference), tuple(artifacts),
        _text(manifest.get("model_id"), "model ID"), model_revision,
        _text(manifest.get("vector_space_id"), "vector space"), _text(manifest.get("release_point"), "release point"),
        source_revision, digest, limits)


def verify_uscode_release(release: USCodeRelease, *, resolver) -> USCodeRelease:
    """Revalidate public release fields against the exact immutable root bytes."""
    if not isinstance(release, USCodeRelease):
        raise USCodeImportError("release must be verified USCodeRelease")
    fresh = load_uscode_release(release.manifest_reference, repo_id=release.repo_id,
                               revision=release.revision, resolver=resolver, limits=release.limits)
    if fresh != release:
        raise USCodeImportError("release metadata differs from its pinned root manifest")
    return fresh


@dataclass(frozen=True)
class RowDisposition:
    row_index: int
    status: str
    entry_cid: str = ""
    legal_id: str = ""


@dataclass(frozen=True)
class VerifiedWrappedRow:
    row_index: int
    entry_cid: str
    legal_id: str | None
    family: str
    record_sha256: str
    _payload_json: bytes = field(repr=False)

    @property
    def payload(self):
        return _parse(self._payload_json)


@dataclass(frozen=True)
class WrappedShard:
    artifact: ReleaseArtifact
    rows: tuple[VerifiedWrappedRow, ...]
    dispositions: tuple[RowDisposition, ...]
    rows_scanned: int
    complete: bool


def read_wrapped_shard(release: USCodeRelease, relative_path: str, *, resolver,
                       max_rows: int | None = None, batch_size: int = 64) -> WrappedShard:
    result, _, _ = _read_wrapped_shard_with_rows(
        release, relative_path, resolver=resolver, max_rows=max_rows, batch_size=batch_size)
    return result


def _read_wrapped_shard_with_rows(release: USCodeRelease, relative_path: str, *, resolver,
                                max_rows: int | None = None, batch_size: int = 64):
    """Also retain verified duplicates and original wrapper failures for inventories."""
    import pyarrow.parquet as pq

    release = verify_uscode_release(release, resolver=resolver)
    artifact = release.artifact(relative_path)
    if artifact.family not in {"corpus", "vectors"} or artifact.media_type != "application/vnd.apache.parquet":
        raise USCodeImportError("only selected corpus/vector Parquet families are supported")
    if type(batch_size) is not int or not 1 <= batch_size <= 256:
        raise USCodeImportError("batch_size must be within [1,256]")
    if max_rows is not None and (type(max_rows) is not int or not 1 <= max_rows <= release.limits.max_rows_per_shard):
        raise USCodeImportError("max_rows exceeds selected shard bound")
    take = min(max_rows or artifact.row_count, artifact.row_count)
    good, dispositions = [], []
    with _verified_file(_resolve_artifact(resolver, artifact.reference), artifact.reference, release.limits.max_shard_bytes) as stream:
        parquet = pq.ParquetFile(stream)
        if tuple(parquet.schema_arrow.names) != WRAPPER_COLUMNS or any(str(item.type) != "string" for item in parquet.schema_arrow):
            raise USCodeImportError("unsupported exact wrapper Parquet schema")
        if parquet.metadata.num_rows != artifact.row_count:
            raise USCodeImportError("Parquet row count differs from root descriptor")
        if sum(parquet.metadata.row_group(index).total_byte_size for index in range(parquet.metadata.num_row_groups)) > release.limits.max_uncompressed_shard_bytes:
            raise USCodeImportError("uncompressed shard exceeds byte bound")
        for batch in parquet.iter_batches(batch_size=min(batch_size, take), columns=list(WRAPPER_COLUMNS)):
            for wrapper in batch.to_pylist():
                if len(dispositions) >= take:
                    break
                index = len(dispositions)
                entry = wrapper.get("entry_cid")
                legal = wrapper.get("legal_id")
                status = "invalid_wrapper"
                try:
                    if not isinstance(entry, str) or not entry or not isinstance(legal, str) or wrapper.get("family") != artifact.family:
                        raise USCodeImportError("wrapper identity/family mismatch")
                    raw = wrapper.get("record_json")
                    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > release.limits.max_record_bytes:
                        raise USCodeImportError("record JSON exceeds bound")
                    raw = raw.encode("utf-8")
                    status = "record_hash_mismatch"
                    if _sha(raw) != _digest(wrapper.get("record_sha256")):
                        raise USCodeImportError("record JSON digest mismatch")
                    status = "invalid_record_json"
                    payload = _parse(raw)
                    if not isinstance(payload, dict) or _json(payload) != raw:
                        raise USCodeImportError("record JSON must be canonical object")
                    status = "wrapper_identity_mismatch"
                    if payload.get("entry_cid") != entry or payload.get("family") != artifact.family or (payload.get("legal_id") or "") != legal:
                        raise USCodeImportError("wrapper and payload identities differ")
                    good.append(VerifiedWrappedRow(index, entry, legal or None, artifact.family, wrapper["record_sha256"], raw))
                    status = "verified_wrapper"
                except (USCodeImportError, UnicodeError, TypeError, ValueError):
                    pass
                dispositions.append(RowDisposition(index, status, entry if isinstance(entry, str) else "", legal if isinstance(legal, str) else ""))
            if len(dispositions) >= take:
                break
    verified_rows = tuple(good)
    wrapper_failures = tuple(item for item in dispositions if item.status != "verified_wrapper")
    counts = {}
    for row in good:
        counts[row.entry_cid] = counts.get(row.entry_cid, 0) + 1
    duplicates = {key for key, count in counts.items() if count > 1}
    if duplicates:
        good = [row for row in good if row.entry_cid not in duplicates]
        dispositions = [replace(item, status="duplicate_entry_cid") if item.entry_cid in duplicates else item for item in dispositions]
    return (WrappedShard(artifact, tuple(good), tuple(dispositions), len(dispositions),
                         len(dispositions) == artifact.row_count), verified_rows, wrapper_failures)


@dataclass(frozen=True)
class VerifiedUSCodeRow:
    entry_cid: str
    legal_id: str
    document_id: str
    title: str
    section: str
    canonical_citation: str
    release_point: str
    text: str
    record_sha256: str
    row_index: int
    shard: ReleaseArtifact
    release_id: str
    _source_claims_json: bytes = field(repr=False)

    @property
    def source_claims(self):
        return _parse(self._source_claims_json)

    @property
    def text_sha256(self):
        return _sha(self.text.encode("utf-8"))

    @property
    def shard_reference(self):
        return self.shard.reference


@dataclass(frozen=True)
class CorpusShardResult:
    artifact: ReleaseArtifact
    records: tuple[VerifiedUSCodeRow, ...]
    dispositions: tuple[RowDisposition, ...]
    rows_scanned: int
    complete: bool

    @property
    def status_counts(self):
        result = {}
        for item in self.dispositions:
            result[item.status] = result.get(item.status, 0) + 1
        return result


def read_corpus_shard(release: USCodeRelease, relative_path: str, *, resolver,
                      max_rows: int | None = None, batch_size: int = 64) -> CorpusShardResult:
    if release.artifact(relative_path).family != "corpus":
        raise USCodeImportError("selected shard is not the corpus family")
    wrapped = read_wrapped_shard(release, relative_path, resolver=resolver, max_rows=max_rows, batch_size=batch_size)
    return _decode_corpus_shard(release, wrapped)


def _decode_corpus_shard(release: USCodeRelease, wrapped: WrappedShard) -> CorpusShardResult:
    """Decode already verified wrapper rows without another physical read."""
    from ...processors.legal_data.uscode_identity import parse_legal_id, normalize_title, normalize_section_token
    from ...processors.legal_data.uscode_release_schema import CorpusRecord, validate_entry_cid

    dispositions = list(wrapped.dispositions)
    records = []
    for row in wrapped.rows:
        payload = row.payload
        status = "invalid_corpus_record"
        try:
            if payload.get("admission_status") != "admitted":
                status = "retrieval_disposition_excluded"
                raise USCodeImportError("published retrieval disposition is not included")
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                status = "missing_text"
                raise USCodeImportError("published text is absent")
            if len(text.encode("utf-8")) > release.limits.max_text_bytes:
                status = "text_exceeds_bound"
                raise USCodeImportError("published text exceeds extraction bound")
            status = "invalid_corpus_record"
            CorpusRecord.from_mapping(payload)
            status = "identity_mismatch"
            if validate_entry_cid(row.entry_cid) != row.entry_cid or payload.get("schema_version") != RELEASE_SCHEMA:
                raise USCodeImportError("noncanonical entry identity/schema")
            identity = parse_legal_id(row.legal_id)
            if identity.legal_id != row.legal_id or identity.jurisdiction != "us":
                raise USCodeImportError("noncanonical legal identity")
            if normalize_title(payload.get("title")) != identity.title or normalize_section_token(payload.get("section")) != identity.section:
                raise USCodeImportError("row title/section differs from canonical legal identity")
            for name, alias in (("subsection", "subsection"), ("appendix", "appendix"), ("note", "note"),
                                ("granule", "granule_id"), ("edition", "edition"), ("schedule", "schedule"), ("kind", "kind")):
                if payload.get(alias) is not None and replace(identity, **{name: payload[alias]}).legal_id != identity.legal_id:
                    raise USCodeImportError("row qualifier differs from canonical legal identity")
            status = "release_point_mismatch"
            if payload.get("release_point") != release.release_point:
                raise USCodeImportError("row release point differs from pinned root")
            claims = {name: payload.get(name) for name in (
                "source_cid", "source_checksum", "official_source_url", "package_id", "granule_id",
                "release_point", "verification_result", "acquisition_time", "observed_at", "effective_date",
                "admission_status", "admission_reason")}
            records.append(VerifiedUSCodeRow(row.entry_cid, identity.legal_id, replace(identity, edition=None).legal_id,
                identity.title, identity.section, identity.canonical_citation, payload["release_point"], text,
                row.record_sha256, row.row_index, wrapped.artifact, release.release_id, _json(claims)))
            status = "ready_published_text"
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            pass
        dispositions[row.row_index] = replace(dispositions[row.row_index], status=status)
    return CorpusShardResult(wrapped.artifact, tuple(records), tuple(dispositions), wrapped.rows_scanned, wrapped.complete)


def verify_uscode_rows(release: USCodeRelease, records: Sequence[VerifiedUSCodeRow], *, resolver) -> tuple[VerifiedUSCodeRow, ...]:
    """Reestablish physical row membership before using public row dataclasses.

    Each selected shard is read once, through its pinned descriptor, and every
    supplied row field is compared with the fresh row at the declared ordinal.
    This prevents a changed text, CID, locator or source claim from borrowing a
    previously valid row digest. Unselected rows in those shards are inventoried
    by the same strict decoder; they do not enter the returned selection.
    """
    release = verify_uscode_release(release, resolver=resolver)
    if not isinstance(records, (tuple, list)) or not 1 <= len(records) <= release.limits.max_verified_rows:
        raise USCodeImportError("selected row verification count exceeds bound")
    if any(not isinstance(row, VerifiedUSCodeRow) or row.release_id != release.release_id
           or row.shard != release.artifact(row.shard.relative_path) for row in records):
        raise USCodeImportError("selected row belongs to another verified release")
    if len({row.entry_cid for row in records}) != len(records):
        raise USCodeImportError("duplicate selected entry CID")
    if len({(row.shard.relative_path, row.row_index) for row in records}) != len(records):
        raise USCodeImportError("duplicate selected physical row")
    by_shard = {}
    for row in records:
        by_shard.setdefault(row.shard.relative_path, []).append(row)
    if len(by_shard) > release.limits.max_verified_shards or sum(
        release.artifact(relative_path).bytes for relative_path in by_shard
    ) > release.limits.max_verified_shard_bytes:
        raise USCodeImportError("selected shard verification closure exceeds aggregate bound")
    verified = {}
    for relative_path, selected in by_shard.items():
        decoded = read_corpus_shard(release, relative_path, resolver=resolver)
        indexed = {row.row_index: row for row in decoded.records}
        for row in selected:
            fresh = indexed.get(row.row_index)
            if fresh is None or fresh != row:
                raise USCodeImportError("selected row differs from its verified shard content")
            verified[(relative_path, row.row_index)] = fresh
    return tuple(verified[(row.shard.relative_path, row.row_index)] for row in records)


def _write_exclusive(path: Path, raw: bytes):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path.absolute()), "sha256": _sha(raw), "bytes": len(raw)}


@dataclass(frozen=True)
class ExtractedUSCodeSource:
    row: VerifiedUSCodeRow
    path: str
    artifact: SourceArtifact

    @property
    def reference(self):
        return {"path": self.path, **asdict(self.artifact)}


@dataclass(frozen=True)
class ExtractedUSCodeBatch:
    sources: tuple[ExtractedUSCodeSource, ...]
    _receipt_json: bytes = field(repr=False)
    _receipt_descriptor_json: bytes = field(repr=False)

    @property
    def receipt(self):
        return _parse(self._receipt_json)

    @property
    def receipt_artifact(self):
        return _parse(self._receipt_descriptor_json)

    def source_records(self, *, embedding_vectors: Mapping[str, Sequence[float]], embedding_model: str,
                       mode: str = "diagnostic") -> tuple[SourceSampleRecord, ...]:
        if mode != "diagnostic":
            raise USCodeImportError("corpus assembly requires a qualified embedding producer/input binding; unavailable in this import profile")
        if not isinstance(embedding_vectors, Mapping) or set(embedding_vectors) != {source.row.entry_cid for source in self.sources}:
            raise USCodeImportError("explicit embedding selection must match every extracted row exactly")
        if not isinstance(embedding_model, str) or not embedding_model.strip() or embedding_model.casefold().startswith("mock:"):
            raise USCodeImportError("diagnostic import requires explicitly supplied external vectors; mock fallback is disabled")
        result = []
        for source in self.sources:
            row = source.row
            sample = SampleRecord(row.title, row.section, row.text, citation=row.canonical_citation,
                embedding_model=embedding_model, embedding_vector=tuple(embedding_vectors[row.entry_cid]))
            span = SourceSpan(source.artifact, "us_code", row.release_id, row.document_id, "en", row.canonical_citation,
                              0, source.artifact.bytes, "identity")
            result.append(SourceSampleRecord(span, sample, embedding_provenance=None))
        return tuple(result)


def extract_uscode_rows(records: Sequence[VerifiedUSCodeRow], output_directory, *, release: USCodeRelease, resolver) -> ExtractedUSCodeBatch:
    if not isinstance(records, (tuple, list)) or not 1 <= len(records) <= release.limits.max_extracted_rows:
        raise USCodeImportError("extraction row count exceeds bound")
    records = verify_uscode_rows(release, records, resolver=resolver)
    if sum(len(row.text.encode("utf-8")) for row in records) > release.limits.max_extracted_bytes:
        raise USCodeImportError("extraction bytes exceed bound")
    output = Path(output_directory).absolute()
    output.mkdir(parents=False, exist_ok=False)
    sources, bindings = [], []
    for index, row in enumerate(records):
        raw = row.text.encode("utf-8")
        descriptor = _write_exclusive(output / f"source-{index:06d}.txt", raw)
        source = ExtractedUSCodeSource(row, descriptor["path"], SourceArtifact(descriptor["sha256"], descriptor["bytes"]))
        sources.append(source)
        bindings.append({"entry_cid": row.entry_cid, "legal_id": row.legal_id, "document_id": row.document_id,
            "canonical_citation": row.canonical_citation, "release_point": row.release_point,
            "shard": {"relative_path": row.shard.relative_path, **row.shard.reference},
            "row_index": row.row_index, "record_sha256": row.record_sha256,
            "extracted_text": asdict(source.artifact), "source_claims": row.source_claims})
    receipt = {"schema_version": "autoencoder-uscode-import-receipt-v1", "repo_id": release.repo_id,
        "revision": release.revision, "manifest": release.manifest_reference, "release_id": release.release_id,
        "manifest_digest": release.manifest_digest,
        "source_revision": release.source_revision, "release_point": release.release_point,
        "selection_scope": "selected_published_rows", "record_count": len(records), "rows": bindings,
        "extraction": "exact published text field UTF-8; identity byte selector",
        "original_official_source_bytes_verified": False, "source_claims_authenticated": False,
        "training_eligible": False, "embedding_producer_verified": False, "admitted": False}
    raw = _json(receipt)
    saved = _write_exclusive(output / "import-receipt.json", raw)
    fd = os.open(output, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return ExtractedUSCodeBatch(tuple(sources), raw, _json(saved))


__all__ = ["USCodeImportError", "USCodeImportLimits", "ReleaseArtifact", "USCodeRelease",
           "VerifiedWrappedRow", "WrappedShard", "VerifiedUSCodeRow", "CorpusShardResult", "RowDisposition",
           "ExtractedUSCodeBatch", "ExtractedUSCodeSource", "load_uscode_release", "read_wrapped_shard",
           "read_corpus_shard", "verify_uscode_release", "verify_uscode_rows", "extract_uscode_rows"]
