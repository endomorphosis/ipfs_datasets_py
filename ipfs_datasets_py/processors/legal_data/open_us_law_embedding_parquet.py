"""Append-only Parquet checkpoint for Open US Law embeddings.

Each batch writes a new ``part-XXXXXX.parquet`` file. Completed parts are
never rewritten. A tiny ``manifest.json`` records config digest, batch
count, and part inventory — not the vector map.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    CHECKPOINT_SCHEMA_VERSION,
    PINNED_DIMENSION,
    TASK_ID,
    EmbeddingCheckpointError,
    EmbeddingRecord,
    record_from_checkpoint,
)

PARQUET_CHECKPOINT_SCHEMA: Final = "open-us-law-embedding-parquet-checkpoint/v1"
PART_SCHEMA_VERSION: Final = "open-us-law-embedding-parquet-row/v1"
MANIFEST_NAME: Final = "manifest.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _arrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise EmbeddingCheckpointError(
            "pyarrow is required for parquet embedding checkpoints"
        ) from exc
    return pa, pq


def embedding_parquet_schema():
    pa, _pq = _arrow()
    return pa.schema(
        [
            pa.field("chunk_cid", pa.string(), nullable=False),
            pa.field("chunk_id", pa.string()),
            pa.field("entry_cid", pa.string()),
            pa.field("input_hash", pa.string(), nullable=False),
            pa.field("dimension", pa.int32(), nullable=False),
            pa.field("l2_norm", pa.float32(), nullable=False),
            pa.field(
                "embedding",
                pa.list_(pa.float32(), PINNED_DIMENSION),
                nullable=False,
            ),
        ]
    )


def is_parquet_checkpoint_path(path: Path | str | None) -> bool:
    if path is None:
        return False
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix in {".json", ".ckpt"}:
        return False
    if suffix in {".parquet", ".pq"}:
        return True
    return True


def parquet_checkpoint_root(path: Path | str) -> Path:
    target = Path(path)
    if target.suffix.lower() in {".parquet", ".pq"}:
        return target.parent / target.stem
    return target


def _records_to_table(records: Sequence[EmbeddingRecord]):
    pa, _pq = _arrow()
    schema = embedding_parquet_schema()
    if not records:
        return pa.Table.from_pylist([], schema=schema)
    rows = [
        {
            "chunk_cid": rec.chunk_cid,
            "chunk_id": rec.chunk_id,
            "entry_cid": rec.entry_cid,
            "input_hash": rec.input_hash,
            "dimension": int(rec.dimension),
            "l2_norm": float(rec.l2_norm),
            "embedding": [float(x) for x in rec.embedding],
        }
        for rec in records
    ]
    return pa.Table.from_pylist(rows, schema=schema)


def _row_to_checkpoint_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    embedding = row.get("embedding")
    if hasattr(embedding, "tolist"):
        embedding = embedding.tolist()
    return {
        "chunk_cid": str(row.get("chunk_cid") or ""),
        "chunk_id": row.get("chunk_id"),
        "dimension": int(row.get("dimension") or PINNED_DIMENSION),
        "embedding": [float(x) for x in list(embedding or ())],
        "entry_cid": row.get("entry_cid"),
        "input_hash": str(row.get("input_hash") or ""),
        "l2_norm": float(row.get("l2_norm") or 0.0),
    }


@dataclass
class ParquetEmbeddingCheckpoint:
    """Directory of immutable parquet parts plus a tiny manifest."""

    root: Path
    config_digest: str
    batch_count: int = 0
    row_count: int = 0
    parts: list[dict[str, Any]] = field(default_factory=list)
    _skip_index: dict[str, str] | None = field(
        default=None, repr=False, compare=False
    )

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    def to_manifest(self) -> dict[str, Any]:
        return {
            "batch_count": self.batch_count,
            "config_digest": self.config_digest,
            "parts": list(self.parts),
            "row_count": self.row_count,
            "schema_version": PARQUET_CHECKPOINT_SCHEMA,
            "task_id": TASK_ID,
            "vectors_stored_in": "parquet_parts",
        }

    def write_manifest(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_manifest(), indent=2, sort_keys=True) + "\n"
        tmp = self.manifest_path.with_name(f".{self.manifest_path.name}.partial")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.manifest_path)

    @classmethod
    def create(cls, root: Path, *, config_digest: str) -> "ParquetEmbeddingCheckpoint":
        store = cls(root=Path(root), config_digest=config_digest)
        store.write_manifest()
        return store

    @classmethod
    def load(cls, root: Path, *, config_digest: str) -> "ParquetEmbeddingCheckpoint":
        target = parquet_checkpoint_root(root)
        manifest_path = target / MANIFEST_NAME
        if not manifest_path.is_file():
            return cls.create(target, config_digest=config_digest)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise EmbeddingCheckpointError("parquet checkpoint manifest must be an object")
        schema = payload.get("schema_version")
        if schema != PARQUET_CHECKPOINT_SCHEMA:
            raise EmbeddingCheckpointError(
                f"unsupported parquet checkpoint schema_version: {schema!r}"
            )
        if payload.get("task_id") != TASK_ID:
            raise EmbeddingCheckpointError(
                f"parquet checkpoint task_id {payload.get('task_id')!r} != {TASK_ID!r}"
            )
        stored_digest = str(payload.get("config_digest") or "")
        if stored_digest != config_digest:
            raise EmbeddingCheckpointError(
                "checkpoint config_digest does not match active pin"
            )
        parts = payload.get("parts") or []
        if not isinstance(parts, list):
            raise EmbeddingCheckpointError("parquet checkpoint parts must be a list")
        return cls(
            root=target,
            config_digest=config_digest,
            batch_count=int(payload.get("batch_count") or 0),
            row_count=int(payload.get("row_count") or 0),
            parts=[dict(item) for item in parts if isinstance(item, Mapping)],
        )

    def append(self, records: Sequence[EmbeddingRecord]) -> Path:
        if not records:
            return self.manifest_path
        self.root.mkdir(parents=True, exist_ok=True)
        part_index = len(self.parts)
        name = f"part-{part_index:06d}.parquet"
        dest = self.root / name
        if dest.exists():
            raise EmbeddingCheckpointError(f"refusing to overwrite parquet part: {dest}")
        pa, pq = _arrow()
        table = _records_to_table(records)
        temporary = dest.with_name(f".{dest.name}.partial")
        try:
            pq.write_table(
                table,
                temporary,
                compression="zstd",
                compression_level=3,
                use_dictionary=True,
                write_statistics=True,
            )
            temporary.replace(dest)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        self.parts.append(
            {
                "name": name,
                "rows": int(table.num_rows),
                "sha256": _sha256_file(dest),
            }
        )
        self.batch_count += 1
        self.row_count += int(table.num_rows)
        if self._skip_index is None:
            skip: dict[str, str] = {}
            prior_parts = self.parts[:-1]
            if prior_parts:
                _pa, pq = _arrow()
                for item in prior_parts:
                    path = self.root / str(item["name"])
                    table = pq.read_table(
                        path, columns=["chunk_cid", "input_hash"]
                    )
                    for cid, digest in zip(
                        table.column("chunk_cid").to_pylist(),
                        table.column("input_hash").to_pylist(),
                    ):
                        skip[str(cid or "")] = str(digest or "")
            self._skip_index = skip
        for rec in records:
            self._skip_index[rec.chunk_cid] = rec.input_hash
        self.write_manifest()
        return dest

    def iter_part_paths(self) -> list[Path]:
        return [self.root / str(part["name"]) for part in self.parts]

    def load_skip_index(self) -> dict[str, str]:
        """Map completed ``chunk_cid`` to ``input_hash`` without loading vectors."""

        if self._skip_index is not None:
            return self._skip_index
        _pa, pq = _arrow()
        skip: dict[str, str] = {}
        for path in self.iter_part_paths():
            if not path.is_file():
                raise EmbeddingCheckpointError(f"missing parquet part: {path}")
            table = pq.read_table(path, columns=["chunk_cid", "input_hash"])
            cids = table.column("chunk_cid").to_pylist()
            hashes = table.column("input_hash").to_pylist()
            for cid, digest in zip(cids, hashes):
                key = str(cid or "")
                if not key:
                    raise EmbeddingCheckpointError("parquet row missing chunk_cid")
                skip[key] = str(digest or "")
        self._skip_index = skip
        return skip

    def load_records_for_cids(
        self,
        cids: Iterable[str],
        *,
        config,
    ) -> dict[str, EmbeddingRecord]:
        """Load embedding records only for the requested chunk CIDs."""

        wanted = {str(cid) for cid in cids if str(cid)}
        if not wanted:
            return {}
        _pa, pq = _arrow()
        records: dict[str, EmbeddingRecord] = {}
        remaining = set(wanted)
        for path in self.iter_part_paths():
            if not remaining:
                break
            if not path.is_file():
                raise EmbeddingCheckpointError(f"missing parquet part: {path}")
            cid_table = pq.read_table(path, columns=["chunk_cid"])
            part_cids = [str(item or "") for item in cid_table.column("chunk_cid").to_pylist()]
            if not remaining.intersection(part_cids):
                continue
            table = pq.read_table(path)
            for row in table.to_pylist():
                payload = _row_to_checkpoint_payload(row)
                cid = payload["chunk_cid"]
                if cid not in remaining:
                    continue
                records[cid] = record_from_checkpoint(cid, payload, config)
                remaining.discard(cid)
        return records

    def load_completed_payloads(self) -> dict[str, dict[str, Any]]:
        pa, pq = _arrow()
        completed: dict[str, dict[str, Any]] = {}
        for path in self.iter_part_paths():
            if not path.is_file():
                raise EmbeddingCheckpointError(f"missing parquet part: {path}")
            table = pq.read_table(path)
            for row in table.to_pylist():
                payload = _row_to_checkpoint_payload(row)
                cid = payload["chunk_cid"]
                if not cid:
                    raise EmbeddingCheckpointError("parquet row missing chunk_cid")
                completed[cid] = payload
        return completed


def load_parquet_checkpoint_records(
    root: Path,
    *,
    config,
) -> dict[str, EmbeddingRecord]:
    store = ParquetEmbeddingCheckpoint.load(root, config_digest=config.digest)
    records: dict[str, EmbeddingRecord] = {}
    for cid, payload in store.load_completed_payloads().items():
        records[cid] = record_from_checkpoint(cid, payload, config)
    return records
