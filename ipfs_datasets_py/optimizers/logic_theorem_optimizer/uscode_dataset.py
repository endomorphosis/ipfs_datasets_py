"""U.S. Code parquet dataset adapters for modal daemon tests and training."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, BinaryIO, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

from .legal_samples import LegalSample, build_us_code_sample

HF_USCODE_DATASET_ID = "justicedao/ipfs_uscode"
USCODE_PARQUET_DIR = "uscode_parquet"
USCODE_LAWS_PARQUET = f"{USCODE_PARQUET_DIR}/laws.parquet"
USCODE_EMBEDDINGS_PARQUET = f"{USCODE_PARQUET_DIR}/laws_embeddings.parquet"
USCODE_BM25_PARQUET = f"{USCODE_PARQUET_DIR}/laws_bm25.parquet"
USCODE_LOGIC_PROOF_SAMPLE_PARQUET = (
    f"{USCODE_PARQUET_DIR}/logic_proofs_llm_router_groth16_partial_000000_000150/"
    "laws_logic_proof_artifacts.parquet"
)

_LAW_COLUMNS = (
    "ipfs_cid",
    "title_number",
    "title_name",
    "section_number",
    "law_name",
    "source_url",
    "text",
    "citation_text",
    "normalized_citation",
)
_EMBEDDING_COLUMNS = ("cid", "embedding", "text_chunk_order")

# This opt-in capture is deliberately smaller than the corpus/training readers.
# Limits cover the complete selected population, never a silently truncated row.
RAW_USCODE_SOURCE_PROFILE = "raw-coordinates-v1"
RAW_USCODE_MAX_ROWS = 128
RAW_USCODE_MAX_FILE_BYTES = 1024 * 1024 * 1024
RAW_USCODE_MAX_TEXT_BYTES = 1024 * 1024
RAW_USCODE_MAX_TOTAL_TEXT_BYTES = 8 * 1024 * 1024
RAW_USCODE_MAX_ROW_GROUP_BYTES = 64 * 1024 * 1024
RAW_USCODE_MAX_DECODED_BYTES = 128 * 1024 * 1024


def capture_uscode_source_documents_from_parquet(
    laws_parquet: str | Path, *, source_revision: str, source_path_in_repo: str,
    expected_sha256: str, expected_bytes: int, limit: int, offset: int = 0,
    release_id: str,
) -> dict[str, Any]:
    """Capture pinned physical rows BEFORE the legacy record adapter cleans them.

    The revision is a caller-declared repository witness, not a remote attestation.
    Exact decoded text is retained; offsets into compressed Parquet bytes are not
    invented. This API performs only bounded local I/O and no embedding work.
    """
    if (type(source_revision) is not str
            or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None):
        raise ValueError("source_revision requires an exact lowercase 40-hex commit")
    if (type(expected_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None):
        raise ValueError("expected_sha256 requires an independent lowercase SHA256")
    if (type(source_path_in_repo) is not str or not source_path_in_repo
            or len(source_path_in_repo) > 4096 or "\\" in source_path_in_repo
            or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF
                   for char in source_path_in_repo)
            or PurePosixPath(source_path_in_repo).is_absolute()
            or str(PurePosixPath(source_path_in_repo)) != source_path_in_repo
            or any(part in (".", "..") for part in source_path_in_repo.split("/"))):
        raise ValueError("source_path_in_repo requires a canonical relative POSIX path")
    if (type(expected_bytes) is not int or not 12 <= expected_bytes <= RAW_USCODE_MAX_FILE_BYTES
            or type(limit) is not int or not 1 <= limit <= RAW_USCODE_MAX_ROWS
            or type(offset) is not int or not 0 <= offset <= 10_000_000):
        raise ValueError("source file size, row limit or physical offset exceeds capture bounds")
    if (type(release_id) is not str or not release_id or len(release_id) > 4096
            or any(0xD800 <= ord(char) <= 0xDFFF for char in release_id)):
        raise ValueError("an explicit bounded release_id is required")
    path = Path(laws_parquet)
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_bytes:
            raise ValueError("source must be a regular file of the independently pinned size")
        signature = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                    value.st_mtime_ns, value.st_ctime_ns)
        def verify_unchanged() -> None:
            current = path.lstat()
            if (not stat.S_ISREG(current.st_mode) or signature(current) != signature(before)
                    or signature(os.fstat(fd)) != signature(before)):
                raise ValueError("pinned source changed during raw-row capture")

        with os.fdopen(os.dup(fd), "rb") as source:
            digest = hashlib.sha256()
            hashed_bytes = 0
            for block in iter(lambda: source.read(1024 * 1024), b""):
                hashed_bytes += len(block)
                if hashed_bytes > expected_bytes:
                    raise ValueError("pinned source grew during hashing")
                digest.update(block)
            if hashed_bytes != expected_bytes or digest.hexdigest() != expected_sha256:
                raise ValueError("source SHA256 differs from the independent pin")
            verify_unchanged()
            # Bound the footer before asking Arrow to parse its metadata.
            source.seek(-8, os.SEEK_END)
            trailer = source.read(8)
            footer_size = int.from_bytes(trailer[:4], "little")
            source.seek(0)
            if (source.read(4) != b"PAR1" or trailer[4:] != b"PAR1"
                    or not 0 < footer_size <= min(8 * 1024 * 1024, expected_bytes - 12)):
                raise ValueError("unsupported or oversized Parquet footer")
            source.seek(0)
            import pyarrow as pa
            import pyarrow.parquet as pq

            parquet = pq.ParquetFile(source, thrift_string_size_limit=8 * 1024 * 1024,
                                     thrift_container_size_limit=100_000)
            if (len(parquet.schema_arrow.names) > 128
                    or len(set(parquet.schema_arrow.names)) != len(parquet.schema_arrow.names)
                    or parquet.num_row_groups > 8192
                    or parquet.metadata.num_rows > 10_000_000
                    or offset + limit > parquet.metadata.num_rows):
                raise ValueError("complete physical row selection or Parquet metadata exceeds bounds")
            columns = [name for name in _LAW_COLUMNS if name in parquet.schema_arrow.names]
            if "text" not in columns or "ipfs_cid" not in columns:
                raise ValueError("raw source requires explicit text and ipfs_cid columns")
            for name in columns:
                dtype = parquet.schema_arrow.field(name).type
                if not (pa.types.is_string(dtype) or pa.types.is_large_string(dtype)
                        or pa.types.is_null(dtype)
                        or (name != "text" and pa.types.is_integer(dtype))):
                    raise ValueError("raw source columns require scalar strings or metadata integers")
            documents, total_text, decoded, row_start = [], 0, 0, 0
            for group_index in range(parquet.num_row_groups):
                group = parquet.metadata.row_group(group_index)
                row_end = row_start + group.num_rows
                start, end = max(offset, row_start), min(offset + limit, row_end)
                if start < end:
                    if not 0 <= group.total_byte_size <= RAW_USCODE_MAX_ROW_GROUP_BYTES:
                        raise ValueError("selected Parquet row group exceeds decoded byte bound")
                    decoded += group.total_byte_size
                    if decoded > RAW_USCODE_MAX_DECODED_BYTES:
                        raise ValueError("complete selected row groups exceed decoded byte bound")
                    table = parquet.read_row_group(group_index, columns=columns, use_threads=False)
                    if table.nbytes > RAW_USCODE_MAX_ROW_GROUP_BYTES:
                        raise ValueError("decoded Parquet row group exceeds byte bound")
                    rows = table.slice(start - row_start, end - start).to_pylist()
                    for physical_row, row in enumerate(rows, start):
                        # Do not use from_row.text: it strips and falls back.
                        text = row["text"]
                        if type(text) is not str or not text.strip():
                            raise ValueError("raw selected text must be a nonempty exact string; no fallback")
                        if len(text) > RAW_USCODE_MAX_TEXT_BYTES:
                            raise ValueError("raw selected text exceeds byte bound")
                        raw_text = text.encode("utf-8")
                        total_text += len(raw_text)
                        if (len(raw_text) > RAW_USCODE_MAX_TEXT_BYTES
                                or total_text > RAW_USCODE_MAX_TOTAL_TEXT_BYTES):
                            raise ValueError("complete selected text exceeds byte bound")
                        raw_metadata = {name: row[name] for name in columns if name != "text"}
                        metadata_wire = json.dumps(raw_metadata, ensure_ascii=False,
                            sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
                        if len(metadata_wire) > 48 * 1024:
                            raise ValueError("raw row metadata exceeds byte bound")
                        row_wire = json.dumps(row, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False).encode("utf-8")
                        record = USCodeParquetRecord.from_row(row)
                        if not record.ipfs_cid:
                            raise ValueError("raw selected row requires an explicit nonempty CID")
                        documents.append({
                            "entry_cid": record.ipfs_cid,
                            "legal_id": f"usc:us:{record.title_number}:{record.section_number}",
                            "release_id": release_id, "section": record.section_number,
                            "text": text, "title": record.title_number,
                            "canonical_citation": record.citation,
                            "raw_row_metadata": raw_metadata,
                            "source_witness": {
                                "schema": "ipfs-uscode-physical-row/v1",
                                "dataset_id": HF_USCODE_DATASET_ID,
                                "source_revision": source_revision,
                                "source_path_in_repo": source_path_in_repo,
                                "source_file_sha256": expected_sha256,
                                "source_file_bytes": expected_bytes,
                                "physical_row_ordinal": physical_row,
                                "selected_column_names": columns,
                                "selected_row_sha256": hashlib.sha256(row_wire).hexdigest(),
                                "raw_text_sha256": hashlib.sha256(raw_text).hexdigest(),
                                "raw_text_utf8_bytes": len(raw_text),
                                "repository_revision_authenticated": False,
                                "parquet_file_byte_mapping_verified": False,
                                "legal_meaning_verified": False,
                            },
                        })
                row_start = row_end
                if row_start >= offset + limit:
                    break
            verify_unchanged()
            if len(documents) != limit:
                raise ValueError("complete physical row selection was not captured")
            return {"profile": RAW_USCODE_SOURCE_PROFILE, "documents": documents,
                    "source_file_sha256": expected_sha256, "source_file_bytes": expected_bytes,
                    "source_revision": source_revision, "source_path_in_repo": source_path_in_repo,
                    "physical_row_offset": offset, "physical_row_count": limit,
                    "source_authority_authenticated": False, "legal_meaning_verified": False}
    finally:
        os.close(fd)


@dataclass(frozen=True)
class USCodeParquetRecord:
    """One row from `justicedao/ipfs_uscode` laws parquet data."""

    ipfs_cid: str
    title_number: str
    section_number: str
    text: str
    citation: str
    law_name: str = ""
    title_name: str = ""
    source_url: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "USCodeParquetRecord":
        title = _clean(row.get("title_number")) or "unknown"
        section = _clean(row.get("section_number")) or "unknown"
        citation = (
            _clean(row.get("normalized_citation"))
            or _clean(row.get("citation_text"))
            or _clean(row.get("official_cite"))
            or f"{title} U.S.C. {section}"
        )
        text = _clean(row.get("text")) or _clean(row.get("law_name")) or citation
        return cls(
            ipfs_cid=_clean(row.get("ipfs_cid")) or _clean(row.get("cid")),
            title_number=title,
            section_number=section,
            text=text,
            citation=citation,
            law_name=_clean(row.get("law_name")),
            title_name=_clean(row.get("title_name")),
            source_url=_clean(row.get("source_url")),
        )

    def to_sample(
        self,
        *,
        embedding_vector: Optional[Sequence[float]] = None,
        embedding_model: Optional[str] = None,
    ) -> LegalSample:
        """Convert this record into the modal parser's legal sample contract."""
        resolved_embedding_model = (
            embedding_model
            if embedding_model is not None
            else (
                f"uscode:{USCODE_EMBEDDINGS_PARQUET}"
                if embedding_vector is not None
                else "mock:stable-sha256"
            )
        )
        return build_us_code_sample(
            title=self.title_number,
            section=self.section_number,
            citation=self.citation,
            text=self.text,
            embedding_model=resolved_embedding_model,
            embedding_vector=embedding_vector,
        )


def iter_uscode_records_from_parquet(
    laws_parquet: str | Path | BinaryIO,
    *,
    limit: Optional[int] = None,
    offset: int = 0,
    batch_size: int = 128,
) -> Iterator[USCodeParquetRecord]:
    """Yield U.S. Code records from a local or file-like parquet source."""
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit is not None and limit <= 0:
        return
    skipped = 0
    for row in _iter_parquet_rows(laws_parquet, columns=_LAW_COLUMNS, batch_size=batch_size):
        if skipped < offset:
            skipped += 1
            continue
        yield USCodeParquetRecord.from_row(row)
        if limit is not None:
            limit -= 1
            if limit <= 0:
                break


def load_uscode_embeddings_from_parquet(
    embeddings_parquet: str | Path | BinaryIO,
    *,
    cids: Optional[Iterable[str]] = None,
    max_rows: Optional[int] = None,
    batch_size: int = 512,
) -> Dict[str, List[float]]:
    """Load first embedding vector per CID from `laws_embeddings.parquet`."""
    wanted = {str(cid) for cid in cids} if cids is not None else None
    embeddings: Dict[str, List[float]] = {}
    rows_seen = 0
    for row in _iter_parquet_rows(
        embeddings_parquet, columns=_EMBEDDING_COLUMNS, batch_size=batch_size
    ):
        rows_seen += 1
        cid = _clean(row.get("cid"))
        if not cid or cid in embeddings:
            continue
        if wanted is not None and cid not in wanted:
            if max_rows is not None and rows_seen >= max_rows:
                break
            continue
        vector = row.get("embedding")
        if isinstance(vector, list) and vector:
            embeddings[cid] = [float(value) for value in vector]
        if wanted is not None and wanted.issubset(embeddings):
            break
        if max_rows is not None and rows_seen >= max_rows:
            break
    return embeddings


def load_uscode_samples_from_parquet(
    laws_parquet: str | Path | BinaryIO,
    *,
    embeddings_parquet: str | Path | BinaryIO | None = None,
    limit: int = 25,
    offset: int = 0,
    batch_size: int = 128,
) -> List[LegalSample]:
    """Load deterministic `LegalSample`s from U.S. Code parquet rows."""
    records = list(
        iter_uscode_records_from_parquet(
            laws_parquet,
            limit=limit,
            offset=offset,
            batch_size=batch_size,
        )
    )
    embeddings: Dict[str, List[float]] = {}
    if embeddings_parquet is not None:
        embeddings = load_uscode_embeddings_from_parquet(
            embeddings_parquet,
            cids=[record.ipfs_cid for record in records if record.ipfs_cid],
        )
    return [
        record.to_sample(
            embedding_vector=embeddings.get(record.ipfs_cid),
            embedding_model=(
                f"uscode:{USCODE_EMBEDDINGS_PARQUET}" if record.ipfs_cid in embeddings else None
            ),
        )
        for record in records
    ]


def load_hf_uscode_samples(
    *,
    repo_id: str = HF_USCODE_DATASET_ID,
    laws_path: str = USCODE_LAWS_PARQUET,
    embeddings_path: Optional[str] = None,
    limit: int = 5,
    offset: int = 0,
) -> List[LegalSample]:
    """Load samples directly from the Hugging Face Hub filesystem.

    This function performs network I/O and is intended for opt-in integration
    tests or manual smoke checks, not default unit tests.
    """
    from huggingface_hub import HfFileSystem

    fs = HfFileSystem()
    laws_hf_path = f"datasets/{repo_id}/{laws_path}"
    if embeddings_path is None:
        with fs.open(laws_hf_path, "rb") as laws_file:
            return load_uscode_samples_from_parquet(laws_file, limit=limit, offset=offset)

    embeddings_hf_path = f"datasets/{repo_id}/{embeddings_path}"
    with fs.open(laws_hf_path, "rb") as laws_file:
        records = list(iter_uscode_records_from_parquet(laws_file, limit=limit, offset=offset))
    with fs.open(embeddings_hf_path, "rb") as embeddings_file:
        embeddings = load_uscode_embeddings_from_parquet(
            embeddings_file,
            cids=[record.ipfs_cid for record in records if record.ipfs_cid],
        )
    return [
        record.to_sample(
            embedding_vector=embeddings.get(record.ipfs_cid),
            embedding_model=(
                f"hf:{repo_id}:{embeddings_path}" if record.ipfs_cid in embeddings else None
            ),
        )
        for record in records
    ]


def _iter_parquet_rows(
    parquet_source: str | Path | BinaryIO,
    *,
    columns: Sequence[str],
    batch_size: int,
) -> Iterator[Mapping[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - exercised only without optional dependency
        raise RuntimeError("pyarrow is required to read U.S. Code parquet samples") from exc

    parquet_file = pq.ParquetFile(parquet_source)
    available = set(parquet_file.schema_arrow.names)
    selected = [column for column in columns if column in available]
    for batch in parquet_file.iter_batches(batch_size=batch_size, columns=selected):
        for row in batch.to_pylist():
            yield row


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = [
    "HF_USCODE_DATASET_ID",
    "USCODE_BM25_PARQUET",
    "USCODE_EMBEDDINGS_PARQUET",
    "USCODE_LAWS_PARQUET",
    "USCODE_LOGIC_PROOF_SAMPLE_PARQUET",
    "USCODE_PARQUET_DIR",
    "USCodeParquetRecord",
    "RAW_USCODE_SOURCE_PROFILE",
    "capture_uscode_source_documents_from_parquet",
    "iter_uscode_records_from_parquet",
    "load_hf_uscode_samples",
    "load_uscode_embeddings_from_parquet",
    "load_uscode_samples_from_parquet",
]
