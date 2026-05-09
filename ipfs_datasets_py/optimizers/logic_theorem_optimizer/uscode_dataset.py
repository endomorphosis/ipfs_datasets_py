"""U.S. Code parquet dataset adapters for modal daemon tests and training."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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

    def to_sample(self, *, embedding_vector: Optional[Sequence[float]] = None) -> LegalSample:
        """Convert this record into the modal parser's legal sample contract."""
        return build_us_code_sample(
            title=self.title_number,
            section=self.section_number,
            citation=self.citation,
            text=self.text,
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
    for row in _iter_parquet_rows(embeddings_parquet, columns=_EMBEDDING_COLUMNS, batch_size=batch_size):
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
        record.to_sample(embedding_vector=embeddings.get(record.ipfs_cid))
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
        record.to_sample(embedding_vector=embeddings.get(record.ipfs_cid))
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
    "iter_uscode_records_from_parquet",
    "load_hf_uscode_samples",
    "load_uscode_embeddings_from_parquet",
    "load_uscode_samples_from_parquet",
]
