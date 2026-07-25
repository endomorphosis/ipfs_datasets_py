"""Canonical CID-keyed Parquet materialization for SkillCenter.

The corpus table is the authoritative join boundary for lexical, vector, and
graph indexes. Every physical SQLite record becomes exactly one Parquet row.
The ``entry_cid`` primary key is computed from the container-independent
intrinsic record through the shared Intent IR canonicalization profile and the
package CID utilities. Container and source-body CIDs remain explicit
provenance columns.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any, Final

from multiformats import CID

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1_from_digest
from ...profile_g import validate_cid
from ..source_adapters.skillcenter import (
    SKILLCENTER_ENTRY_IDENTITY_SCHEMA_VERSION,
    SkillCenterBundleReader,
    SkillCenterSkillRecord,
)


SKILLCENTER_CORPUS_SCHEMA_VERSION: Final = "skillcenter-corpus/v1"
SKILLCENTER_CORPUS_ROW_SCHEMA_VERSION: Final = "skillcenter-corpus-row/v1"
SKILLCENTER_CORPUS_CID_INDEX_SCHEMA_VERSION: Final = (
    "skillcenter-corpus-cid-index/v1"
)
SKILLCENTER_CORPUS_PRIMARY_KEY: Final = "entry_cid"
DEFAULT_CORPUS_BATCH_SIZE: Final = 512

_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_REQUIRED_FILES = frozenset({"cid_index", "corpus"})


class SkillCenterCorpusError(ValueError):
    """Raised when a CID-keyed corpus build or artifact is invalid."""


@dataclass(frozen=True, slots=True)
class SkillCenterCorpusBuildSummary:
    """Compact result for a built or verified canonical corpus."""

    output_dir: str
    dataset_revision: str
    bundle_count: int
    source_records: int
    unique_entry_cids: int
    corpus_cid: str
    manifest_sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_count": self.bundle_count,
            "corpus_cid": self.corpus_cid,
            "dataset_revision": self.dataset_revision,
            "manifest_sha256": self.manifest_sha256,
            "output_dir": self.output_dir,
            "size_bytes": self.size_bytes,
            "source_records": self.source_records,
            "unique_entry_cids": self.unique_entry_cids,
        }


class SkillCenterCorpusIndex:
    """Verified facade over a canonical SkillCenter Parquet corpus."""

    def __init__(
        self,
        *,
        root: Path,
        manifest: Mapping[str, Any],
        cid_rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self.root = root
        self.manifest = dict(manifest)
        self.cid_rows = tuple(dict(row) for row in cid_rows)
        self._corpus_path = root / str(
            manifest["files"]["corpus"]["relative_path"]
        )
        self._corpus_index_by_cid = {
            str(row["entry_cid"]): int(row["corpus_index"])
            for row in self.cid_rows
        }

    @classmethod
    def load(
        cls,
        root: str | Path,
        *,
        verify_rows: bool = True,
    ) -> "SkillCenterCorpusIndex":
        """Load only after validating file identities and primary-key coverage."""

        index_root = Path(root).expanduser().resolve()
        manifest_path = index_root / "manifest.json"
        if (
            index_root.is_symlink()
            or not index_root.is_dir()
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
            or manifest_path.stat().st_size > _MAX_MANIFEST_BYTES
        ):
            raise SkillCenterCorpusError(
                "corpus must contain a bounded regular manifest.json"
            )
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCenterCorpusError("corpus manifest is malformed") from exc
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("schema_version")
            != SKILLCENTER_CORPUS_SCHEMA_VERSION
            or manifest.get("primary_key") != SKILLCENTER_CORPUS_PRIMARY_KEY
        ):
            raise SkillCenterCorpusError("unsupported corpus manifest")
        files = manifest.get("files")
        if not isinstance(files, Mapping) or set(files) != _REQUIRED_FILES:
            raise SkillCenterCorpusError(
                "corpus manifest has an unexpected file set"
            )
        paths = {
            name: _verify_file_descriptor(index_root, files[name])
            for name in sorted(_REQUIRED_FILES)
        }
        pa, pq = _pyarrow()
        corpus_schema = pq.read_schema(paths["corpus"])
        cid_schema = pq.read_schema(paths["cid_index"])
        _verify_schema_metadata(
            corpus_schema,
            schema_version=SKILLCENTER_CORPUS_ROW_SCHEMA_VERSION,
            primary_key=SKILLCENTER_CORPUS_PRIMARY_KEY,
        )
        _verify_schema_metadata(
            cid_schema,
            schema_version=SKILLCENTER_CORPUS_CID_INDEX_SCHEMA_VERSION,
            primary_key=SKILLCENTER_CORPUS_PRIMARY_KEY,
        )
        expected_rows = int(manifest.get("source_records", -1))
        corpus_metadata = pq.read_metadata(paths["corpus"])
        if corpus_metadata.num_rows != expected_rows:
            raise SkillCenterCorpusError(
                "corpus row count does not match its manifest"
            )
        cid_rows = pq.read_table(paths["cid_index"]).to_pylist()
        if len(cid_rows) != expected_rows:
            raise SkillCenterCorpusError(
                "CID index row count does not match the corpus"
            )
        entry_cids = [str(row.get("entry_cid", "")) for row in cid_rows]
        if (
            entry_cids != sorted(entry_cids)
            or len(set(entry_cids)) != len(entry_cids)
            or any(not value for value in entry_cids)
        ):
            raise SkillCenterCorpusError(
                "entry_cid primary keys must be non-empty, sorted, and unique"
            )
        corpus_indexes = sorted(int(row["corpus_index"]) for row in cid_rows)
        if corpus_indexes != list(range(expected_rows)):
            raise SkillCenterCorpusError(
                "CID index must cover every corpus row exactly once"
            )
        for row in cid_rows:
            _validate_cid_profile(str(row["entry_cid"]), label="entry_cid")
        loaded = cls(root=index_root, manifest=manifest, cid_rows=cid_rows)
        if verify_rows:
            loaded.verify_all_rows()
        return loaded

    @property
    def summary(self) -> SkillCenterCorpusBuildSummary:
        corpus_file = self.manifest["files"]["corpus"]
        manifest_sha = hashlib.sha256(
            (self.root / "manifest.json").read_bytes()
        ).hexdigest()
        return SkillCenterCorpusBuildSummary(
            output_dir=str(self.root),
            dataset_revision=str(self.manifest["dataset_revision"]),
            bundle_count=int(self.manifest["bundle_count"]),
            source_records=int(self.manifest["source_records"]),
            unique_entry_cids=int(self.manifest["unique_entry_cids"]),
            corpus_cid=str(corpus_file["cid"]),
            manifest_sha256=manifest_sha,
            size_bytes=int(corpus_file["size_bytes"]),
        )

    @property
    def entry_cids(self) -> frozenset[str]:
        return frozenset(self._corpus_index_by_cid)

    def iter_rows(
        self,
        *,
        columns: Sequence[str] | None = None,
        batch_size: int = DEFAULT_CORPUS_BATCH_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Stream corpus rows without loading source bodies into memory."""

        _, pq = _pyarrow()
        parquet = pq.ParquetFile(self._corpus_path)
        for batch in parquet.iter_batches(
            batch_size=batch_size,
            columns=None if columns is None else list(columns),
        ):
            for row in batch.to_pylist():
                yield dict(row)

    def iter_records(
        self,
        *,
        batch_size: int = DEFAULT_CORPUS_BATCH_SIZE,
    ) -> Iterator[SkillCenterSkillRecord]:
        """Reconstruct source records for legacy processors during migration."""

        columns = (
            "bundle_sha256",
            "dataset_id",
            "dataset_revision",
            "domain",
            "language",
            "library_md",
            "metadata_yaml",
            "overall_score",
            "primary_source_id",
            "profile",
            "repository_file",
            "skill_id",
            "skill_kind",
            "skill_md",
            "source_id",
            "source_type",
            "source_url",
            "title",
        )
        for row in self.iter_rows(columns=columns, batch_size=batch_size):
            yield SkillCenterSkillRecord(**row)

    def verify_all_rows(self) -> None:
        """Recompute every entry/body/container CID and index foreign key."""

        seen: set[str] = set()
        expected_count = int(self.manifest["source_records"])
        for expected_index, row in enumerate(self.iter_rows()):
            if int(row.get("corpus_index", -1)) != expected_index:
                raise SkillCenterCorpusError(
                    "corpus_index must be dense and ordered"
                )
            record = _record_from_row(row)
            identity = record.entry_identity
            entry_cid = str(row.get("entry_cid", ""))
            if (
                entry_cid != identity.cid
                or bytes(row.get("entry_cid_bytes") or b"")
                != identity.cid_bytes
                or bytes(row.get("entry_multihash") or b"")
                != identity.multihash_bytes
                or str(row.get("entry_sha256", "")) != identity.sha256
                or str(row.get("content_cid", "")) != record.content_cid
                or str(row.get("content_sha256", ""))
                != record.content_sha256
                or str(row.get("bundle_cid", ""))
                != cid_v1_from_digest(bytes.fromhex(record.bundle_sha256))
            ):
                raise SkillCenterCorpusError(
                    f"corpus row {expected_index} has stale CID identity"
                )
            if (
                entry_cid in seen
                or self._corpus_index_by_cid.get(entry_cid)
                != expected_index
            ):
                raise SkillCenterCorpusError(
                    "entry_cid primary-key or CID-index coverage is invalid"
                )
            seen.add(entry_cid)
        if len(seen) != expected_count:
            raise SkillCenterCorpusError(
                "verified corpus row count does not match manifest"
            )


def build_skillcenter_corpus(
    readers: Sequence[SkillCenterBundleReader],
    *,
    output_dir: str | Path,
    batch_size: int = DEFAULT_CORPUS_BATCH_SIZE,
) -> SkillCenterCorpusBuildSummary:
    """Build one atomic CID-keyed Parquet corpus from all supplied readers."""

    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 10_000
    ):
        raise SkillCenterCorpusError(
            "batch_size must be between 1 and 10000"
        )
    prepared = sorted(
        tuple(readers),
        key=lambda reader: reader.repository_file,
    )
    if not prepared:
        raise SkillCenterCorpusError("at least one bundle reader is required")
    manifests = [reader.inspect() for reader in prepared]
    revisions = {item.dataset_revision for item in manifests}
    dataset_ids = {item.dataset_id for item in manifests}
    repository_files = [item.repository_file for item in manifests]
    if (
        len(revisions) != 1
        or len(dataset_ids) != 1
        or len(set(repository_files)) != len(repository_files)
    ):
        raise SkillCenterCorpusError(
            "bundle readers must share one dataset/revision and unique paths"
        )
    inputs = []
    for reader, manifest in zip(prepared, manifests):
        inputs.append(
            {
                **manifest.to_dict(),
                "bundle_cid": cid_v1_from_digest(
                    bytes.fromhex(manifest.local_sha256)
                ),
                "declared_total_skills": (
                    reader.declared_total_skills
                    if reader.declared_total_skills is not None
                    else manifest.total_skills
                ),
            }
        )
    build_identity_payload = {
        "entry_identity_schema_version": (
            SKILLCENTER_ENTRY_IDENTITY_SCHEMA_VERSION
        ),
        "inputs": inputs,
        "primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY,
        "schema_version": SKILLCENTER_CORPUS_SCHEMA_VERSION,
    }
    build_identity_sha256 = hashlib.sha256(
        canonical_json_bytes(build_identity_payload)
    ).hexdigest()
    output = Path(output_dir).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise SkillCenterCorpusError("output_dir must not be a symlink")
    with _build_lock(output):
        if output.exists():
            existing = SkillCenterCorpusIndex.load(output)
            if (
                existing.manifest.get("build_identity_sha256")
                != build_identity_sha256
            ):
                raise SkillCenterCorpusError(
                    "existing corpus was built from different inputs"
                )
            return existing.summary
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.",
                suffix=".partial",
                dir=output.parent,
            )
        )
        try:
            _build_into_directory(
                staging,
                readers=prepared,
                manifests=manifests,
                inputs=inputs,
                build_identity_sha256=build_identity_sha256,
                batch_size=batch_size,
            )
            os.replace(staging, output)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
    return SkillCenterCorpusIndex.load(output).summary


def _build_into_directory(
    root: Path,
    *,
    readers: Sequence[SkillCenterBundleReader],
    manifests: Sequence[Any],
    inputs: Sequence[Mapping[str, Any]],
    build_identity_sha256: str,
    batch_size: int,
) -> None:
    pa, pq = _pyarrow()
    corpus_path = root / "corpus.parquet"
    schema = _corpus_schema(pa)
    writer = pq.ParquetWriter(
        corpus_path,
        schema,
        compression="zstd",
        compression_level=6,
        use_dictionary=True,
        write_statistics=True,
    )
    seen_entry_cids: set[str] = set()
    seen_skill_ids: set[str] = set()
    cid_rows: list[dict[str, Any]] = []
    batch: list[dict[str, Any]] = []
    corpus_index = 0
    try:
        for reader in readers:
            for record in reader.iter_records(batch_size=min(batch_size, 1000)):
                identity = record.entry_identity
                if identity.cid in seen_entry_cids:
                    raise SkillCenterCorpusError(
                        f"duplicate entry_cid across corpus: {identity.cid}"
                    )
                if record.skill_id in seen_skill_ids:
                    raise SkillCenterCorpusError(
                        f"duplicate skill_id across corpus: {record.skill_id}"
                    )
                seen_entry_cids.add(identity.cid)
                seen_skill_ids.add(record.skill_id)
                source_ref = record.to_source_ref()
                row = {
                    "bundle_cid": cid_v1_from_digest(
                        bytes.fromhex(record.bundle_sha256)
                    ),
                    "bundle_sha256": record.bundle_sha256,
                    "content_cid": record.content_cid,
                    "content_sha256": record.content_sha256,
                    "corpus_index": corpus_index,
                    "dataset_id": record.dataset_id,
                    "dataset_revision": record.dataset_revision,
                    "domain": record.domain,
                    "entry_cid": identity.cid,
                    "entry_cid_bytes": identity.cid_bytes,
                    "entry_identity_schema_version": (
                        identity.identity_schema_version
                    ),
                    "entry_multihash": identity.multihash_bytes,
                    "entry_sha256": identity.sha256,
                    "language": record.language,
                    "library_md": record.library_md,
                    "license_expression": record.license_expression,
                    "license_risk": record.license_risk,
                    "metadata_yaml": record.metadata_yaml,
                    "overall_score": record.overall_score,
                    "primary_source_id": record.primary_source_id,
                    "profile": record.profile,
                    "repository_file": record.repository_file,
                    "schema_version": SKILLCENTER_CORPUS_ROW_SCHEMA_VERSION,
                    "skill_id": record.skill_id,
                    "skill_kind": record.skill_kind,
                    "skill_md": record.skill_md,
                    "source_id": record.source_id,
                    "source_ref_id": source_ref.ref_id,
                    "source_type": record.source_type,
                    "source_url": record.source_url,
                    "title": record.title,
                }
                batch.append(row)
                cid_rows.append(
                    {
                        "content_cid": record.content_cid,
                        "corpus_index": corpus_index,
                        "entry_cid": identity.cid,
                        "repository_file": record.repository_file,
                        "schema_version": (
                            SKILLCENTER_CORPUS_CID_INDEX_SCHEMA_VERSION
                        ),
                        "skill_id": record.skill_id,
                    }
                )
                corpus_index += 1
                if len(batch) >= batch_size:
                    writer.write_table(
                        pa.Table.from_pylist(batch, schema=schema),
                        row_group_size=batch_size,
                    )
                    batch.clear()
        if batch:
            writer.write_table(
                pa.Table.from_pylist(batch, schema=schema),
                row_group_size=batch_size,
            )
    finally:
        writer.close()
    if corpus_index != sum(item.total_skills for item in manifests):
        raise SkillCenterCorpusError(
            "written corpus coverage differs from physical bundle counts"
        )
    cid_rows.sort(key=lambda row: str(row["entry_cid"]))
    cid_schema = _cid_index_schema(pa)
    pq.write_table(
        pa.Table.from_pylist(cid_rows, schema=cid_schema),
        root / "cid_index.parquet",
        compression="zstd",
        compression_level=6,
        use_dictionary=True,
        write_statistics=True,
        row_group_size=max(batch_size, 4096),
    )
    files = {
        "cid_index": _file_descriptor(root / "cid_index.parquet", root=root),
        "corpus": _file_descriptor(corpus_path, root=root),
    }
    manifest = {
        "build_identity_sha256": build_identity_sha256,
        "bundle_count": len(manifests),
        "dataset_id": manifests[0].dataset_id,
        "dataset_revision": manifests[0].dataset_revision,
        "entry_identity_schema_version": (
            SKILLCENTER_ENTRY_IDENTITY_SCHEMA_VERSION
        ),
        "files": files,
        "inputs": list(inputs),
        "primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY,
        "schema_version": SKILLCENTER_CORPUS_SCHEMA_VERSION,
        "source_records": corpus_index,
        "unique_entry_cids": len(seen_entry_cids),
        "unique_skill_ids": len(seen_skill_ids),
    }
    _write_bytes(root / "manifest.json", canonical_json_bytes(manifest))


def _corpus_schema(pa: Any) -> Any:
    metadata = {
        b"cid_multicodec": b"raw",
        b"cid_multihash": b"sha2-256",
        b"cid_version": b"1",
        b"primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY.encode(),
        b"schema_version": SKILLCENTER_CORPUS_ROW_SCHEMA_VERSION.encode(),
    }
    return pa.schema(
        [
            ("bundle_cid", pa.string(), False),
            ("bundle_sha256", pa.string(), False),
            ("content_cid", pa.string(), False),
            ("content_sha256", pa.string(), False),
            ("corpus_index", pa.int64(), False),
            ("dataset_id", pa.string(), False),
            ("dataset_revision", pa.string(), False),
            ("domain", pa.string(), False),
            ("entry_cid", pa.string(), False),
            ("entry_cid_bytes", pa.binary(), False),
            ("entry_identity_schema_version", pa.string(), False),
            ("entry_multihash", pa.binary(), False),
            ("entry_sha256", pa.string(), False),
            ("language", pa.string(), False),
            ("library_md", pa.large_string(), False),
            ("license_expression", pa.string(), False),
            ("license_risk", pa.string(), False),
            ("metadata_yaml", pa.large_string(), False),
            ("overall_score", pa.float64(), True),
            ("primary_source_id", pa.string(), False),
            ("profile", pa.string(), False),
            ("repository_file", pa.string(), False),
            ("schema_version", pa.string(), False),
            ("skill_id", pa.string(), False),
            ("skill_kind", pa.string(), False),
            ("skill_md", pa.large_string(), False),
            ("source_id", pa.string(), False),
            ("source_ref_id", pa.string(), False),
            ("source_type", pa.string(), False),
            ("source_url", pa.string(), False),
            ("title", pa.string(), False),
        ],
        metadata=metadata,
    )


def _cid_index_schema(pa: Any) -> Any:
    metadata = {
        b"foreign_key": b"corpus_index->corpus.parquet.corpus_index",
        b"primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY.encode(),
        b"schema_version": (
            SKILLCENTER_CORPUS_CID_INDEX_SCHEMA_VERSION.encode()
        ),
    }
    return pa.schema(
        [
            ("content_cid", pa.string(), False),
            ("corpus_index", pa.int64(), False),
            ("entry_cid", pa.string(), False),
            ("repository_file", pa.string(), False),
            ("schema_version", pa.string(), False),
            ("skill_id", pa.string(), False),
        ],
        metadata=metadata,
    )


def _record_from_row(row: Mapping[str, Any]) -> SkillCenterSkillRecord:
    return SkillCenterSkillRecord(
        bundle_sha256=str(row["bundle_sha256"]),
        dataset_id=str(row["dataset_id"]),
        dataset_revision=str(row["dataset_revision"]),
        domain=str(row["domain"]),
        language=str(row["language"]),
        library_md=str(row["library_md"]),
        metadata_yaml=str(row["metadata_yaml"]),
        overall_score=(
            None
            if row.get("overall_score") is None
            else float(row["overall_score"])
        ),
        primary_source_id=str(row["primary_source_id"]),
        profile=str(row["profile"]),
        repository_file=str(row["repository_file"]),
        skill_id=str(row["skill_id"]),
        skill_kind=str(row["skill_kind"]),
        skill_md=str(row["skill_md"]),
        source_id=str(row["source_id"]),
        source_type=str(row["source_type"]),
        source_url=str(row["source_url"]),
        title=str(row["title"]),
    )


def _verify_schema_metadata(
    schema: Any,
    *,
    schema_version: str,
    primary_key: str,
) -> None:
    metadata = schema.metadata or {}
    if (
        metadata.get(b"schema_version") != schema_version.encode()
        or metadata.get(b"primary_key") != primary_key.encode()
    ):
        raise SkillCenterCorpusError(
            "Parquet schema metadata does not declare the expected primary key"
        )


def _validate_cid_profile(value: str, *, label: str) -> None:
    try:
        canonical = validate_cid(value, path=f"/{label}")
        decoded = CID.decode(canonical)
    except Exception as exc:
        raise SkillCenterCorpusError(f"{label} is not a valid CID") from exc
    if decoded.codec.name != "raw" or decoded.hashfun.name != "sha2-256":
        raise SkillCenterCorpusError(
            f"{label} must use CIDv1/raw/sha2-256"
        )


def _file_descriptor(path: Path, *, root: Path) -> dict[str, Any]:
    size_bytes, digest = _file_digest(path)
    return {
        "cid": cid_v1_from_digest(digest),
        "media_type": "application/vnd.apache.parquet",
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": digest.hex(),
        "size_bytes": size_bytes,
    }


def _verify_file_descriptor(root: Path, value: Any) -> Path:
    if not isinstance(value, Mapping):
        raise SkillCenterCorpusError("file descriptor must be an object")
    relative = value.get("relative_path")
    if not isinstance(relative, str) or not relative:
        raise SkillCenterCorpusError("file descriptor path is missing")
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise SkillCenterCorpusError("file descriptor path is unsafe")
    path = root.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise SkillCenterCorpusError("declared corpus artifact is missing")
    size_bytes, digest = _file_digest(path)
    if (
        size_bytes != int(value.get("size_bytes", -1))
        or digest.hex() != value.get("sha256")
        or cid_v1_from_digest(digest) != value.get("cid")
    ):
        raise SkillCenterCorpusError(
            f"corpus artifact identity mismatch: {relative}"
        )
    return path


def _file_digest(path: Path) -> tuple[int, bytes]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            size_bytes += len(chunk)
            digest.update(chunk)
    return size_bytes, digest.digest()


def _write_bytes(path: Path, payload: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _build_lock(output: Path) -> Iterator[None]:
    import fcntl

    lock_path = output.parent / f".{output.name}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with os.fdopen(descriptor, "a+b", closefd=True) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
    finally:
        pass


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise SkillCenterCorpusError(
            "pyarrow is required for SkillCenter corpus artifacts"
        ) from exc
    return pa, pq


__all__ = [
    "DEFAULT_CORPUS_BATCH_SIZE",
    "SKILLCENTER_CORPUS_CID_INDEX_SCHEMA_VERSION",
    "SKILLCENTER_CORPUS_PRIMARY_KEY",
    "SKILLCENTER_CORPUS_ROW_SCHEMA_VERSION",
    "SKILLCENTER_CORPUS_SCHEMA_VERSION",
    "SkillCenterCorpusBuildSummary",
    "SkillCenterCorpusError",
    "SkillCenterCorpusIndex",
    "build_skillcenter_corpus",
]
