"""FAISS vector index joined to SkillCenter by canonical ``entry_cid``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any, Final

from multiformats import CID

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1_from_digest
from ...profile_g import validate_cid
from .skillcenter_corpus import (
    SKILLCENTER_CORPUS_PRIMARY_KEY,
    SkillCenterCorpusIndex,
)
from .skillcenter_embeddings import (
    iter_skillcenter_embedding_rows,
    load_skillcenter_embedding_corpus,
)


SKILLCENTER_CID_VECTOR_SCHEMA_VERSION: Final = (
    "skillcenter-cid-vector-index/v1"
)
SKILLCENTER_CID_VECTOR_METADATA_SCHEMA_VERSION: Final = (
    "skillcenter-cid-vector-metadata/v1"
)
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024


class SkillCenterCIDVectorError(ValueError):
    """Raised when a CID-keyed vector artifact is invalid."""


@dataclass(frozen=True, slots=True)
class SkillCenterCIDVectorBuildSummary:
    output_dir: str
    dataset_revision: str
    model_name: str
    dimension: int
    vector_count: int
    primary_key: str
    faiss_cid: str
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_revision": self.dataset_revision,
            "dimension": self.dimension,
            "faiss_cid": self.faiss_cid,
            "manifest_sha256": self.manifest_sha256,
            "model_name": self.model_name,
            "output_dir": self.output_dir,
            "primary_key": self.primary_key,
            "vector_count": self.vector_count,
        }


@dataclass(frozen=True, slots=True)
class SkillCenterCIDVectorHit:
    entry_cid: str
    faiss_id: int
    score: float
    metadata: Mapping[str, Any]
    authority: str = "context_only"
    proof_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "entry_cid": self.entry_cid,
            "faiss_id": self.faiss_id,
            "metadata": dict(self.metadata),
            "proof_authority": self.proof_authority,
            "score": self.score,
        }


class SkillCenterCIDVectorIndex:
    """Verified FAISS facade whose metadata primary key is ``entry_cid``."""

    def __init__(
        self,
        *,
        root: Path,
        manifest: Mapping[str, Any],
        faiss_index: Any,
        metadata_rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self.root = root
        self.manifest = dict(manifest)
        self.faiss_index = faiss_index
        self.metadata_rows = tuple(dict(row) for row in metadata_rows)
        self.metadata_by_faiss_id = {
            int(row["faiss_id"]): dict(row) for row in self.metadata_rows
        }

    @classmethod
    def load(
        cls,
        root: str | Path,
        *,
        corpus_dir: str | Path | None = None,
    ) -> "SkillCenterCIDVectorIndex":
        index_root = Path(root).expanduser().resolve()
        manifest_path = index_root / "manifest.json"
        if (
            index_root.is_symlink()
            or not index_root.is_dir()
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
            or manifest_path.stat().st_size > _MAX_MANIFEST_BYTES
        ):
            raise SkillCenterCIDVectorError(
                "vector index must contain a bounded regular manifest"
            )
        try:
            manifest = json.loads(manifest_path.read_bytes())
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCenterCIDVectorError(
                "vector manifest is malformed"
            ) from exc
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("schema_version")
            != SKILLCENTER_CID_VECTOR_SCHEMA_VERSION
            or manifest.get("primary_key")
            != SKILLCENTER_CORPUS_PRIMARY_KEY
        ):
            raise SkillCenterCIDVectorError("unsupported vector manifest")
        files = manifest.get("files")
        if not isinstance(files, Mapping) or set(files) != {
            "faiss",
            "metadata",
        }:
            raise SkillCenterCIDVectorError(
                "vector manifest file set is invalid"
            )
        paths = {
            name: _verify_file_descriptor(index_root, files[name])
            for name in sorted(files)
        }
        faiss, np = _faiss_numpy()
        index = faiss.read_index(str(paths["faiss"]))
        _, pq = _pyarrow()
        metadata_rows = pq.read_table(paths["metadata"]).to_pylist()
        expected = int(manifest.get("vector_count", -1))
        dimension = int(manifest.get("dimension", -1))
        if (
            index.ntotal != expected
            or index.d != dimension
            or len(metadata_rows) != expected
        ):
            raise SkillCenterCIDVectorError(
                "FAISS/vector metadata counts are inconsistent"
            )
        entry_cids = [str(row.get("entry_cid", "")) for row in metadata_rows]
        faiss_ids = [int(row.get("faiss_id", -1)) for row in metadata_rows]
        if (
            entry_cids != sorted(entry_cids)
            or len(set(entry_cids)) != expected
            or len(set(faiss_ids)) != expected
            or any(
                _faiss_id(entry_cid) != faiss_id
                for entry_cid, faiss_id in zip(entry_cids, faiss_ids)
            )
        ):
            raise SkillCenterCIDVectorError(
                "entry_cid/faiss_id mapping is not canonical and unique"
            )
        stored_ids = faiss.vector_to_array(index.id_map).astype(np.int64)
        if set(int(value) for value in stored_ids) != set(faiss_ids):
            raise SkillCenterCIDVectorError(
                "FAISS ID map differs from CID metadata"
            )
        loaded = cls(
            root=index_root,
            manifest=manifest,
            faiss_index=index,
            metadata_rows=metadata_rows,
        )
        if corpus_dir is not None:
            corpus = SkillCenterCorpusIndex.load(
                corpus_dir,
                verify_rows=False,
            )
            if manifest.get("corpus_input") != _corpus_input(corpus):
                raise SkillCenterCIDVectorError(
                    "vector index is not bound to this corpus"
                )
            if set(entry_cids) != corpus.entry_cids:
                raise SkillCenterCIDVectorError(
                    "vector entry_cid coverage differs from corpus"
                )
        return loaded

    @property
    def summary(self) -> SkillCenterCIDVectorBuildSummary:
        return SkillCenterCIDVectorBuildSummary(
            output_dir=str(self.root),
            dataset_revision=str(self.manifest["dataset_revision"]),
            model_name=str(self.manifest["model_name"]),
            dimension=int(self.manifest["dimension"]),
            vector_count=int(self.manifest["vector_count"]),
            primary_key=str(self.manifest["primary_key"]),
            faiss_cid=str(self.manifest["files"]["faiss"]["cid"]),
            manifest_sha256=hashlib.sha256(
                (self.root / "manifest.json").read_bytes()
            ).hexdigest(),
        )

    def search_vector(
        self,
        vector: Sequence[float],
        *,
        k: int = 10,
    ) -> tuple[SkillCenterCIDVectorHit, ...]:
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 1000:
            raise SkillCenterCIDVectorError("k must be between 1 and 1000")
        _, np = _faiss_numpy()
        query = np.asarray([vector], dtype=np.float32)
        if (
            query.shape != (1, int(self.manifest["dimension"]))
            or not np.isfinite(query).all()
        ):
            raise SkillCenterCIDVectorError("query vector is malformed")
        norm = float(np.linalg.norm(query))
        if not math.isfinite(norm) or norm == 0:
            raise SkillCenterCIDVectorError("query vector must be non-zero")
        query /= norm
        scores, identifiers = self.faiss_index.search(
            query,
            min(k, int(self.manifest["vector_count"])),
        )
        hits = []
        for score, faiss_id in zip(scores[0], identifiers[0]):
            if int(faiss_id) < 0:
                continue
            metadata = self.metadata_by_faiss_id[int(faiss_id)]
            hits.append(
                SkillCenterCIDVectorHit(
                    entry_cid=str(metadata["entry_cid"]),
                    faiss_id=int(faiss_id),
                    score=float(score),
                    metadata=metadata,
                )
            )
        return tuple(hits)


def build_skillcenter_cid_vector_index(
    corpus_dir: str | Path,
    embedding_dirs: Sequence[str | Path],
    *,
    output_dir: str | Path,
) -> SkillCenterCIDVectorBuildSummary:
    """Build one FAISS IDMap2 index from complete full-corpus checkpoints."""

    corpus = SkillCenterCorpusIndex.load(corpus_dir, verify_rows=False)
    prepared_dirs = sorted(
        (Path(path).expanduser().resolve() for path in embedding_dirs),
        key=str,
    )
    if not prepared_dirs:
        raise SkillCenterCIDVectorError(
            "at least one embedding checkpoint is required"
        )
    manifests = [
        load_skillcenter_embedding_corpus(path)
        for path in prepared_dirs
    ]
    dimensions = {int(item["dimension"]) for item in manifests}
    models = {str(item["config"]["model_name"]) for item in manifests}
    if len(dimensions) != 1 or 0 in dimensions or len(models) != 1:
        raise SkillCenterCIDVectorError(
            "embedding checkpoints must share one non-zero model/dimension"
        )
    for manifest in manifests:
        config = manifest["config"]
        if (
            not config.get("internal_retrieval_all_records")
            or int(config.get("max_chunks_per_record") or 0) != 1
            or int(manifest["embedded_records"]) != int(
                manifest["source_records_total"]
            )
            or int(manifest["vector_count"]) != int(
                manifest["source_records_total"]
            )
        ):
            raise SkillCenterCIDVectorError(
                "full vector checkpoints must contain one vector per entry"
            )
    embedding_inputs = [
        {
            "manifest_sha256": hashlib.sha256(
                (path / "manifest.json").read_bytes()
            ).hexdigest(),
            "output_dir": str(path),
            "repository_file": manifest["repository_file"],
            "vector_count": manifest["vector_count"],
        }
        for path, manifest in zip(prepared_dirs, manifests)
    ]
    identity = {
        "corpus_input": _corpus_input(corpus),
        "embedding_inputs": embedding_inputs,
        "primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY,
        "schema_version": SKILLCENTER_CID_VECTOR_SCHEMA_VERSION,
    }
    build_identity_sha256 = hashlib.sha256(
        canonical_json_bytes(identity)
    ).hexdigest()
    output = Path(output_dir).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with _build_lock(output):
        if output.exists():
            loaded = SkillCenterCIDVectorIndex.load(
                output,
                corpus_dir=corpus.root,
            )
            if (
                loaded.manifest.get("build_identity_sha256")
                != build_identity_sha256
            ):
                raise SkillCenterCIDVectorError(
                    "existing vector index has different inputs"
                )
            return loaded.summary
        rows = []
        seen: set[str] = set()
        for path in prepared_dirs:
            for row in iter_skillcenter_embedding_rows(path):
                entry_cid = str(row.get("entry_cid", ""))
                if not entry_cid or entry_cid in seen:
                    raise SkillCenterCIDVectorError(
                        "embedding entry_cid values must be present and unique"
                    )
                seen.add(entry_cid)
                rows.append(row)
        if seen != corpus.entry_cids:
            raise SkillCenterCIDVectorError(
                "embedding checkpoints do not cover the canonical corpus"
            )
        rows.sort(key=lambda row: str(row["entry_cid"]))
        faiss, np = _faiss_numpy()
        dimension = next(iter(dimensions))
        vectors = np.asarray(
            [row["embedding"] for row in rows],
            dtype=np.float32,
        )
        if (
            vectors.shape != (len(rows), dimension)
            or not np.isfinite(vectors).all()
        ):
            raise SkillCenterCIDVectorError("embedding matrix is malformed")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if bool((norms == 0).any()):
            raise SkillCenterCIDVectorError("embedding matrix has zero vectors")
        vectors = (vectors / norms).astype(np.float32)
        metadata = []
        identifiers = []
        for row in rows:
            entry_cid = str(row["entry_cid"])
            faiss_id = _faiss_id(entry_cid)
            identifiers.append(faiss_id)
            metadata.append(
                {
                    "domain": str(row["domain"]),
                    "entry_cid": entry_cid,
                    "faiss_id": faiss_id,
                    "language": str(row["language"]),
                    "model_name": str(row["embedding_model"]),
                    "profile": str(row["profile"]),
                    "repository_file": str(row["repository_file"]),
                    "schema_version": (
                        SKILLCENTER_CID_VECTOR_METADATA_SCHEMA_VERSION
                    ),
                    "skill_id": str(row["skill_id"]),
                    "source_type": str(row["source_type"]),
                    "title": str(row["title"]),
                }
            )
        if len(set(identifiers)) != len(identifiers):
            raise SkillCenterCIDVectorError(
                "CID-derived FAISS int64 identifiers collided"
            )
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))
        index.add_with_ids(vectors, np.asarray(identifiers, dtype=np.int64))
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.",
                suffix=".partial",
                dir=output.parent,
            )
        )
        try:
            faiss.write_index(index, str(staging / "vectors.faiss"))
            _write_metadata(staging / "metadata.parquet", metadata)
            files = {
                "faiss": _file_descriptor(
                    staging / "vectors.faiss", root=staging
                ),
                "metadata": _file_descriptor(
                    staging / "metadata.parquet", root=staging
                ),
            }
            manifest = {
                "build_identity_sha256": build_identity_sha256,
                "corpus_input": _corpus_input(corpus),
                "dataset_id": corpus.manifest["dataset_id"],
                "dataset_revision": corpus.manifest["dataset_revision"],
                "dimension": dimension,
                "embedding_inputs": embedding_inputs,
                "files": files,
                "model_name": next(iter(models)),
                "primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY,
                "schema_version": SKILLCENTER_CID_VECTOR_SCHEMA_VERSION,
                "vector_count": len(rows),
            }
            _write_bytes(
                staging / "manifest.json",
                canonical_json_bytes(manifest),
            )
            os.replace(staging, output)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
    return SkillCenterCIDVectorIndex.load(
        output,
        corpus_dir=corpus.root,
    ).summary


def _faiss_id(entry_cid: str) -> int:
    try:
        canonical_cid = validate_cid(entry_cid, path="/entry_cid")
        decoded = CID.decode(canonical_cid)
        if decoded.codec.name != "raw":
            raise SkillCenterCIDVectorError(
                "entry_cid must use the raw multicodec"
            )
        digest = decoded.raw_digest
    except Exception as exc:
        if isinstance(exc, SkillCenterCIDVectorError):
            raise
        raise SkillCenterCIDVectorError("entry_cid is malformed") from exc
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _corpus_input(corpus: SkillCenterCorpusIndex) -> dict[str, Any]:
    return {
        "corpus_cid": corpus.manifest["files"]["corpus"]["cid"],
        "manifest_sha256": hashlib.sha256(
            (corpus.root / "manifest.json").read_bytes()
        ).hexdigest(),
        "source_records": corpus.manifest["source_records"],
    }


def _write_metadata(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    pa, pq = _pyarrow()
    schema = pa.schema(
        [
            ("domain", pa.string(), False),
            ("entry_cid", pa.string(), False),
            ("faiss_id", pa.int64(), False),
            ("language", pa.string(), False),
            ("model_name", pa.string(), False),
            ("profile", pa.string(), False),
            ("repository_file", pa.string(), False),
            ("schema_version", pa.string(), False),
            ("skill_id", pa.string(), False),
            ("source_type", pa.string(), False),
            ("title", pa.string(), False),
        ],
        metadata={
            b"primary_key": b"entry_cid",
            b"schema_version": (
                SKILLCENTER_CID_VECTOR_METADATA_SCHEMA_VERSION.encode()
            ),
        },
    )
    pq.write_table(
        pa.Table.from_pylist(list(rows), schema=schema),
        path,
        compression="zstd",
        row_group_size=4096,
    )


def _file_descriptor(path: Path, *, root: Path) -> dict[str, Any]:
    size_bytes, digest = _file_digest(path)
    return {
        "cid": cid_v1_from_digest(digest),
        "media_type": (
            "application/vnd.apache.parquet"
            if path.suffix == ".parquet"
            else "application/vnd.faiss"
        ),
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": digest.hex(),
        "size_bytes": size_bytes,
    }


def _verify_file_descriptor(root: Path, value: Any) -> Path:
    if not isinstance(value, Mapping):
        raise SkillCenterCIDVectorError("vector file descriptor is missing")
    relative = str(value.get("relative_path") or "")
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise SkillCenterCIDVectorError("vector file path is unsafe")
    path = root.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise SkillCenterCIDVectorError("vector artifact is missing")
    size_bytes, digest = _file_digest(path)
    if (
        size_bytes != int(value.get("size_bytes", -1))
        or digest.hex() != value.get("sha256")
        or cid_v1_from_digest(digest) != value.get("cid")
    ):
        raise SkillCenterCIDVectorError("vector artifact identity mismatch")
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
def _build_lock(output: Path):
    import fcntl

    lock = output.parent / f".{output.name}.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b", closefd=True) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _faiss_numpy() -> tuple[Any, Any]:
    try:
        import faiss
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise SkillCenterCIDVectorError(
            "faiss and numpy are required"
        ) from exc
    return faiss, np


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise SkillCenterCIDVectorError("pyarrow is required") from exc
    return pa, pq


__all__ = [
    "SKILLCENTER_CID_VECTOR_SCHEMA_VERSION",
    "SkillCenterCIDVectorBuildSummary",
    "SkillCenterCIDVectorError",
    "SkillCenterCIDVectorHit",
    "SkillCenterCIDVectorIndex",
    "build_skillcenter_cid_vector_index",
]
