"""Query-compatible physical Parquet writer for state-law BM25 indexes.

The LCR-027 builder deliberately owns the legal tokenizer, seven-field
projection, scoring statistics, and in-memory term/document routes.  This
module is the narrow physical adapter for that already-built index.  It writes
direct-column, bounded Parquet artifacts understood by
``retrieval.hf_graphrag.query``:

* ``data/bm25/documents/part-NNNNNN.parquet``;
* ``data/bm25/postings/part-NNNNNN.parquet``;
* ``indexes/bm25_document_chunks.parquet``; and
* ``indexes/bm25_keyword_shards.parquet``.

Posting rows retain exact parallel TF arrays for all seven legal fields.  The
generic query engine's ``title_frequencies`` column is the exact legal title
field; ``body_frequencies`` is the raw sum of the other legal fields so every
legal-tokenizer term remains remotely searchable.  The manifest opts the
shared query engine into exact named-field scoring through the retained
``legal_*_frequencies`` and ``legal_*_lengths`` arrays.

This module stages local files only.  It performs no network I/O and never
authorizes publication or upload.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (
    FIELD_ORDER,
    Bm25BoundError,
    Bm25CoverageError,
    LegalBm25Document,
    StateLawsBm25Config,
    StateLawsBm25Index,
    TermPosting,
    assert_externally_sorted,
    assert_postings_reconcile,
    assert_shards_bounded,
    default_bm25_config,
    document_route_key,
    project_legal_document,
    shared_tokenizer_identity,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    reject_positional_durable_identity,
    validate_entry_cid,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactWriterConfig,
    atomic_staging,
    confine_path,
    describe_file,
    resolve_release_root,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    manifest_descriptor as _manifest_descriptor,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    COMPACT_INDEX_SCHEMA_VERSION,
    MAX_POINTERS_PER_ROW,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    ArtifactDescriptor,
    ArtifactFamily,
    CompactIndexRow,
    normalize_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_bm25 import (
    StreamingMultiFieldBM25Config,
    StreamingMultiFieldBM25Layout,
    StreamingMultiFieldBM25Profile,
    StreamingMultiFieldDocument,
    write_streaming_multifield_bm25_layout,
)

SCHEMA_VERSION: Final = "state-laws-bm25-physical/v1"
DOCUMENT_SCHEMA_VERSION: Final = "state-laws-bm25-document-physical/v1"
POSTING_SCHEMA_VERSION: Final = "state-laws-bm25-posting-physical/v2"

DOCUMENT_DATA_DIR: Final = "data/bm25/documents"
POSTING_DATA_DIR: Final = "data/bm25/postings"
DOCUMENT_INDEX_PATH: Final = "indexes/bm25_document_chunks.parquet"
KEYWORD_INDEX_PATH: Final = "indexes/bm25_keyword_shards.parquet"
CANONICAL_CHUNK_ARTIFACT_DIGEST_CONTRACT: Final = (
    "corpus_chunks_index_descriptor_sha256"
)

# Generic two-field query compatibility.  Exact per-field arrays remain in
# each posting row under ``legal_<field>_frequencies``.
QUERY_TITLE_FIELDS: Final = ("title",)
QUERY_BODY_FIELDS: Final = tuple(
    field_name for field_name in FIELD_ORDER if field_name not in QUERY_TITLE_FIELDS
)

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False

# Compatibility fence: the index adapter below starts from an already
# materialised ``StateLawsBm25Index``.  Production callers must use the
# iterable writer, which never constructs that object graph.
INDEX_TO_LAYOUT_PRODUCTION_READY: Final = False
ITERABLE_TO_LAYOUT_PRODUCTION_READY: Final = True


class StateLawsBm25PhysicalError(ValueError):
    """Raised when an LCR-027 index cannot be exported losslessly."""


@dataclass(frozen=True, slots=True)
class StateLawsBm25PhysicalLayout:
    """Descriptors and manifest values for one committed physical layout."""

    output_dir: str
    index: StateLawsBm25Index
    document_descriptors: tuple[ArtifactDescriptor, ...]
    posting_descriptors: tuple[ArtifactDescriptor, ...]
    document_index_descriptor: ArtifactDescriptor
    keyword_index_descriptor: ArtifactDescriptor
    document_route_rows: tuple[Mapping[str, Any], ...]
    keyword_route_rows: tuple[Mapping[str, Any], ...]
    posting_row_count: int

    @property
    def production_ready(self) -> bool:
        """The compatibility exporter is memory-bound before it is called."""

        return INDEX_TO_LAYOUT_PRODUCTION_READY

    @property
    def indexes(self) -> dict[str, dict[str, Any]]:
        return {
            "bm25_document_chunks": _manifest_descriptor(
                self.document_index_descriptor
            ),
            "bm25_keyword_shards": _manifest_descriptor(self.keyword_index_descriptor),
        }

    @property
    def descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return (
            *self.document_descriptors,
            *self.posting_descriptors,
            self.document_index_descriptor,
            self.keyword_index_descriptor,
        )

    @property
    def counts(self) -> dict[str, int]:
        return {
            "bm25_document_chunks": len(self.document_descriptors),
            "bm25_documents": self.index.document_count,
            "bm25_keyword_shards": len(self.posting_descriptors),
            "bm25_posting_rows": self.posting_row_count,
            "bm25_postings": self.index.posting_count,
            "bm25_terms": self.index.term_count,
            "bm25_token_instances": self.index.token_instance_count,
        }

    def to_manifest_fragment(self) -> dict[str, Any]:
        """Return query-ready values for a parent release manifest."""

        source_bm25 = dict(self.index.to_manifest_fragment()["bm25"])
        tokenizer_contract = source_bm25.pop("tokenizer")
        source_bm25.update(
            {
                "average_document_length": self.index.average_document_length,
                "body_weight": self.index.config.field_weights.body,
                "config": self.index.config.to_dict(),
                "fields": list(FIELD_ORDER),
                "physical_schema_version": SCHEMA_VERSION,
                "query_field_projection": {
                    "body_frequencies": list(QUERY_BODY_FIELDS),
                    "exact_field_lengths": True,
                    "exact_field_prefix": "legal_",
                    "title_frequencies": list(QUERY_TITLE_FIELDS),
                },
                "query_analyzer": {
                    "required": True,
                    "tokenizer_id": self.index.tokenizer_id,
                },
                "title_weight": self.index.config.field_weights.title,
                "tokenizer": self.index.tokenizer_id,
                "tokenizer_contract": tokenizer_contract,
            }
        )
        return {
            "bm25": source_bm25,
            "configs": {
                "bm25_documents": f"{DOCUMENT_DATA_DIR}/*.parquet",
                "bm25_keyword_index": KEYWORD_INDEX_PATH,
                "bm25_postings": f"{POSTING_DATA_DIR}/*.parquet",
            },
            "counts": self.counts,
            "indexes": self.indexes,
        }


@dataclass(frozen=True, slots=True)
class StateLawsStreamingBm25PhysicalLayout:
    """Production state-law wrapper around the shared streaming layout."""

    layout: StreamingMultiFieldBM25Layout
    config: StateLawsBm25Config
    canonical_chunk_artifact_digest: str | None = None

    @property
    def output_dir(self) -> str:
        return self.layout.output_dir

    @property
    def production_ready(self) -> bool:
        return ITERABLE_TO_LAYOUT_PRODUCTION_READY

    @property
    def descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return self.layout.descriptors

    @property
    def document_descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return self.layout.document_descriptors

    @property
    def posting_descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return self.layout.posting_descriptors

    @property
    def document_index_descriptor(self) -> ArtifactDescriptor:
        return self.layout.document_index_descriptor

    @property
    def keyword_index_descriptor(self) -> ArtifactDescriptor:
        return self.layout.keyword_index_descriptor

    @property
    def document_route_rows(self) -> tuple[Mapping[str, Any], ...]:
        return self.layout.document_route_rows

    @property
    def keyword_route_rows(self) -> tuple[Mapping[str, Any], ...]:
        return self.layout.keyword_route_rows

    @property
    def sort_receipts(self) -> Mapping[str, Mapping[str, Any]]:
        return self.layout.sort_receipts

    @property
    def checkpoint_path(self) -> str | None:
        return self.layout.checkpoint_path

    @property
    def resumed_stages(self) -> tuple[str, ...]:
        return self.layout.resumed_stages

    @property
    def executed_stages(self) -> tuple[str, ...]:
        return self.layout.executed_stages

    def _iter_document_key_rows(self) -> Iterator[Mapping[str, Any]]:
        """Stream and count-check physical document identities once per pass."""

        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - optional release extra
            raise StateLawsBm25PhysicalError(
                "pyarrow is required to read BM25 document-key evidence"
            ) from exc
        root = Path(self.output_dir)
        observed = 0
        for descriptor in self.document_descriptors:
            path = confine_path(root, descriptor.relative_path)
            parquet = pq.ParquetFile(path)
            for batch in parquet.iter_batches(
                batch_size=MAX_ROWS_PER_PHYSICAL_SHARD,
                columns=[
                    "chunk_cid",
                    "document_index",
                    "entry_cid",
                    "parent_entry_cid",
                ],
            ):
                for row in batch.to_pylist():
                    observed += 1
                    yield row
        if observed != self.layout.document_count:
            raise StateLawsBm25PhysicalError(
                "BM25 document-key evidence row count does not match the layout"
            )

    def iter_parent_entry_cids(self) -> Iterator[str]:
        """Stream parent keys from bounded Parquet batches for release parity."""

        for row in self._iter_document_key_rows():
            parent = row.get("parent_entry_cid") or row.get("entry_cid")
            if not isinstance(parent, str) or not parent.strip():
                raise StateLawsBm25PhysicalError(
                    "BM25 document lacks parent-entry key evidence"
                )
            yield parent.strip()

    def iter_chunk_cids(self) -> Iterator[str]:
        """Stream canonical chunk IDs for exact BM25/vector set parity.

        Duplicate IDs remain observable to the bounded external-sort parity
        gate.  The production builder independently rejects duplicate source
        identities before writing the physical document layout.
        """

        for row in self._iter_document_key_rows():
            entry_cid = row.get("entry_cid")
            chunk_cid = row.get("chunk_cid")
            if (
                not isinstance(chunk_cid, str)
                or not chunk_cid.strip()
                or entry_cid != chunk_cid
            ):
                raise StateLawsBm25PhysicalError(
                    "BM25 document chunk_cid is empty or not bound to entry_cid"
                )
            yield chunk_cid.strip()

    def iter_document_chunk_keys(self) -> Iterator[tuple[int, str]]:
        """Stream the exact positional chunk mapping used by query hydration."""

        for expected_document_index, row in enumerate(
            self._iter_document_key_rows()
        ):
            document_index = int(row.get("document_index", -1))
            chunk_cid = str(row.get("chunk_cid") or "").strip()
            if document_index != expected_document_index:
                raise StateLawsBm25PhysicalError(
                    "BM25 document indexes are not dense and canonical"
                )
            if not chunk_cid or row.get("entry_cid") != chunk_cid:
                raise StateLawsBm25PhysicalError(
                    "BM25 positional chunk evidence is empty or unbound"
                )
            yield document_index, chunk_cid

    def iter_vocabulary_document_frequencies(self) -> Iterator[tuple[str, int]]:
        """Stream the unique physical vocabulary and DF proof in lexical order."""

        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - optional release extra
            raise StateLawsBm25PhysicalError(
                "pyarrow is required to read BM25 vocabulary evidence"
            ) from exc
        root = Path(self.output_dir)
        previous: str | None = None
        for descriptor in self.posting_descriptors:
            path = confine_path(root, descriptor.relative_path)
            parquet = pq.ParquetFile(path)
            for batch in parquet.iter_batches(
                batch_size=MAX_ROWS_PER_PHYSICAL_SHARD,
                columns=[
                    "document_frequency",
                    "posting_chunk_index",
                    "term",
                ],
            ):
                for row in batch.to_pylist():
                    if int(row["posting_chunk_index"]) != 0:
                        continue
                    term = str(row["term"])
                    if previous is not None and previous >= term:
                        raise StateLawsBm25PhysicalError(
                            "physical BM25 vocabulary is not strictly ordered"
                        )
                    previous = term
                    yield term, int(row["document_frequency"])

    @property
    def key_evidence(self) -> dict[str, Iterable[str]]:
        """Replayable, disk-backed parent-key evidence for the local assembler."""

        return {"parent_entry_cids": self.iter_parent_entry_cids()}

    @property
    def counts(self) -> dict[str, int]:
        return self.layout.counts

    @property
    def indexes(self) -> dict[str, dict[str, Any]]:
        return {
            "bm25_document_chunks": _manifest_descriptor(
                self.layout.document_index_descriptor
            ),
            "bm25_keyword_shards": _manifest_descriptor(
                self.layout.keyword_index_descriptor
            ),
        }

    def to_manifest_fragment(self) -> dict[str, Any]:
        """Return query-ready metadata without authorizing or publishing it."""

        bm25 = {
            "average_document_length": self.layout.average_document_length,
            "average_field_lengths": dict(self.layout.average_field_lengths),
            "b": self.config.b,
            "body_weight": self.config.field_weights.body,
            "config": self.config.to_dict(),
            "config_digest": self.config.digest,
            "corpus_root_cid": self.layout.source_root_cid,
            "document_count": self.layout.document_count,
            "document_frequency_sha256": self.layout.document_frequency_sha256,
            "field_weights": self.config.field_weights.to_dict(),
            "fields": list(FIELD_ORDER),
            "index_root_cid": self.layout.index_root_cid,
            "k1": self.config.k1,
            "physical_schema_version": SCHEMA_VERSION,
            "physical_vocabulary_proof": {
                "document_frequency_column": "document_frequency",
                "document_frequency_sha256": (
                    self.layout.document_frequency_sha256
                ),
                "keyword_index_path": KEYWORD_INDEX_PATH,
                "posting_glob": f"{POSTING_DATA_DIR}/*.parquet",
                "posting_rows_are_lexicographic": True,
                "term_column": "term",
                "vocabulary_sha256": self.layout.vocabulary_sha256,
            },
            "production_builder": "shared_streaming_multifield",
            "query_field_projection": {
                "body_frequencies": list(QUERY_BODY_FIELDS),
                "exact_field_lengths": True,
                "exact_field_prefix": "legal_",
                "title_frequencies": list(QUERY_TITLE_FIELDS),
            },
            "query_analyzer": {
                "required": True,
                "tokenizer_id": self.config.tokenizer_id,
            },
            "title_weight": self.config.field_weights.title,
            "term_count": self.layout.term_count,
            "token_instance_count": self.layout.token_instance_count,
            "tokenizer": self.config.tokenizer_id,
            "tokenizer_contract": shared_tokenizer_identity(self.config),
            "vocabulary_sha256": self.layout.vocabulary_sha256,
        }
        if self.canonical_chunk_artifact_digest is not None:
            bm25.update(
                {
                    "canonical_chunk_artifact_digest": (
                        self.canonical_chunk_artifact_digest
                    ),
                    "canonical_chunk_artifact_digest_contract": (
                        CANONICAL_CHUNK_ARTIFACT_DIGEST_CONTRACT
                    ),
                }
            )
        return {
            "bm25": bm25,
            "configs": {
                "bm25_documents": f"{DOCUMENT_DATA_DIR}/*.parquet",
                "bm25_keyword_index": KEYWORD_INDEX_PATH,
                "bm25_postings": f"{POSTING_DATA_DIR}/*.parquet",
            },
            "counts": self.counts,
            "indexes": self.indexes,
        }


def _pyarrow() -> Any:
    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise StateLawsBm25PhysicalError(
            "pyarrow is required for the state-law BM25 physical layout"
        ) from exc
    return pa


def _document_schema(pa: Any, index: StateLawsBm25Index) -> Any:
    fields: list[tuple[str, Any, bool]] = [
        ("schema_version", pa.string(), False),
        ("document_index", pa.int64(), False),
        ("route_key", pa.string(), False),
        ("entry_cid", pa.string(), False),
        ("chunk_cid", pa.string(), False),
        ("parent_entry_cid", pa.string(), True),
        ("chunk_id", pa.string(), True),
        ("legal_id", pa.string(), True),
        ("jurisdiction_code", pa.string(), False),
        ("census_region", pa.string(), False),
        ("title_code", pa.string(), True),
        ("section", pa.string(), True),
        ("record_type", pa.string(), False),
        ("document_length", pa.int64(), False),
    ]
    fields.extend(
        (f"{field_name}_length", pa.int64(), False) for field_name in FIELD_ORDER
    )
    return pa.schema(
        fields,
        metadata={
            b"primary_key": b"entry_cid",
            b"schema_version": DOCUMENT_SCHEMA_VERSION.encode("ascii"),
            b"tokenizer": index.tokenizer_id.encode("ascii"),
        },
    )


def _posting_schema(pa: Any, index: StateLawsBm25Index) -> Any:
    int_list = pa.list_(pa.int64())
    float_list = pa.list_(pa.float64())
    fields: list[tuple[str, Any, bool]] = [
        ("schema_version", pa.string(), False),
        ("term", pa.string(), False),
        ("document_frequency", pa.int64(), False),
        ("corpus_frequency", pa.int64(), False),
        ("weighted_corpus_frequency", pa.float64(), False),
        ("idf", pa.float64(), False),
        ("posting_chunk_count", pa.int32(), False),
        ("posting_chunk_index", pa.int32(), False),
        ("pointer_count", pa.int32(), False),
        ("document_indices", int_list, False),
        ("document_lengths", int_list, False),
        ("entry_cids", pa.list_(pa.string()), False),
        ("chunk_cids", pa.list_(pa.string()), False),
        ("title_frequencies", int_list, False),
        ("body_frequencies", int_list, False),
        ("total_frequencies", int_list, False),
        ("weighted_frequencies", float_list, False),
    ]
    fields.extend(
        (f"legal_{field_name}_frequencies", int_list, False)
        for field_name in FIELD_ORDER
    )
    fields.extend(
        (f"legal_{field_name}_lengths", int_list, False)
        for field_name in FIELD_ORDER
    )
    return pa.schema(
        fields,
        metadata={
            b"b": repr(index.config.b).encode("ascii"),
            b"field_weights": str(index.config.field_weights.to_dict()).encode("utf-8"),
            b"k1": repr(index.config.k1).encode("ascii"),
            b"schema_version": POSTING_SCHEMA_VERSION.encode("ascii"),
            b"tokenizer": index.tokenizer_id.encode("ascii"),
        },
    )


def _streaming_document_schema(
    pa: Any,
    profile: StreamingMultiFieldBM25Profile,
) -> Any:
    """Direct-column state-law schema supplied to the shared writer."""

    fields: list[tuple[str, Any, bool]] = [
        ("schema_version", pa.string(), False),
        ("document_index", pa.int64(), False),
        ("route_key", pa.string(), False),
        ("entry_cid", pa.string(), False),
        ("chunk_cid", pa.string(), False),
        ("parent_entry_cid", pa.string(), True),
        ("chunk_id", pa.string(), True),
        ("legal_id", pa.string(), True),
        ("jurisdiction_code", pa.string(), False),
        ("census_region", pa.string(), False),
        ("title_code", pa.string(), True),
        ("section", pa.string(), True),
        ("record_type", pa.string(), False),
        ("document_length", pa.int64(), False),
    ]
    fields.extend(
        (f"{field_name}_length", pa.int64(), False)
        for field_name in profile.field_names
    )
    return pa.schema(
        fields,
        metadata={
            b"primary_key": b"entry_cid",
            b"schema_version": profile.document_schema_version.encode("ascii"),
            b"tokenizer": profile.tokenizer_id.encode("ascii"),
        },
    )


def _streaming_identity_key(row: Mapping[str, Any]) -> str:
    for name in ("chunk_cid", "entry_cid", "record_id", "cid"):
        value = row.get(name)
        if isinstance(value, str) and value.strip():
            identity = value.strip()
            reject_positional_durable_identity(identity, name=name)
            if identity.lower().startswith("row-"):
                raise StateLawsBm25PhysicalError(
                    f"positional identity is forbidden: {identity!r}"
                )
            return validate_entry_cid(identity, name=name)
    raise StateLawsBm25PhysicalError(
        "admitted source row is missing durable chunk_cid / entry_cid"
    )


def _streaming_order_key(row: Mapping[str, Any]) -> tuple[str, str]:
    """Use the canonical order shared by chunk, BM25, and vector layouts.

    ``chunk_index`` is local to a parent statute and therefore cannot be an
    independent global ordering axis.  Ordering by durable chunk identity
    within jurisdiction matches the persisted chunk store and the embedding
    store consumed by vector production, keeping positional hydration sound.
    """
    jurisdiction = (
        str(row.get("jurisdiction_code") or row.get("jurisdiction") or "")
        .strip()
        .upper()
    )
    return (jurisdiction, _streaming_identity_key(row))


def _streaming_projector(
    config: StateLawsBm25Config,
):
    def project(
        row: Mapping[str, Any],
        document_index: int,
    ) -> StreamingMultiFieldDocument:
        document = project_legal_document(
            row,
            document_index=document_index,
            config=config,
        )
        if document.jurisdiction_code is None or document.census_region is None:
            raise StateLawsBm25PhysicalError(
                "production BM25 documents require jurisdiction routing fields: "
                f"{document.entry_cid}"
            )
        return StreamingMultiFieldDocument(
            entry_cid=document.entry_cid,
            chunk_cid=document.chunk_cid,
            field_terms={name: document.fields[name].terms for name in FIELD_ORDER},
            payload={
                "census_region": document.census_region,
                "chunk_id": document.chunk_id,
                "jurisdiction_code": document.jurisdiction_code,
                "legal_id": document.legal_id,
                "parent_entry_cid": document.parent_entry_cid,
                "record_type": document.record_type,
                "section": document.section,
                "title_code": document.title_code,
            },
        )

    return project


def write_state_laws_bm25_physical_layout_from_iterable(
    rows: Iterable[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    config: StateLawsBm25Config | None = None,
    canonical_chunk_artifact_digest: str | None = None,
    checkpoint_dir: str | Path | None = None,
    resume: bool = False,
) -> StateLawsStreamingBm25PhysicalLayout:
    """Production BM25 writer over a one-shot iterable of admitted chunks.

    The source is consumed exactly once.  Sorting and vocabulary/posting
    aggregation are disk-backed and bounded by ``config.max_records_in_memory``.
    The function stages local artifacts only and does not create a manifest.

    For restart/reuse, pass ``canonical_chunk_artifact_digest`` and
    ``checkpoint_dir``.  ``resume=False`` starts a fresh checkpointed build;
    ``resume=True`` reuses only verified matching stages.  The digest is the
    SHA-256 from the canonical chunk layout's ``corpus_index_descriptor``;
    that index transitively binds every canonical chunk shard.  Existing
    callers that omit the checkpoint arguments retain the one-shot
    non-checkpointed path.
    """

    selected = config or default_bm25_config()
    if not isinstance(selected, StateLawsBm25Config):
        raise StateLawsBm25PhysicalError("config must be a StateLawsBm25Config")
    if not isinstance(resume, bool):
        raise StateLawsBm25PhysicalError("resume must be a boolean")
    checkpoint_requested = (
        canonical_chunk_artifact_digest is not None
        or checkpoint_dir is not None
        or resume
    )
    normalized_chunk_digest: str | None = None
    if checkpoint_requested:
        if canonical_chunk_artifact_digest is None or checkpoint_dir is None:
            raise StateLawsBm25PhysicalError(
                "canonical_chunk_artifact_digest and checkpoint_dir are both "
                "required for resumable BM25 construction"
            )
        try:
            normalized_chunk_digest = normalize_sha256(
                canonical_chunk_artifact_digest,
                name="canonical_chunk_artifact_digest",
            )
        except Exception as exc:
            raise StateLawsBm25PhysicalError(
                "canonical_chunk_artifact_digest must be a SHA-256 digest"
            ) from exc
    profile = StreamingMultiFieldBM25Profile(
        field_names=FIELD_ORDER,
        field_weights=selected.field_weights.to_dict(),
        query_title_fields=QUERY_TITLE_FIELDS,
        query_body_fields=QUERY_BODY_FIELDS,
        tokenizer_id=selected.tokenizer_id,
        document_schema_version=DOCUMENT_SCHEMA_VERSION,
        posting_schema_version=POSTING_SCHEMA_VERSION,
        config_digest=selected.digest,
        physical_schema_version=SCHEMA_VERSION,
        exact_frequency_prefix="legal_",
        emit_exact_field_lengths=True,
        document_data_dir=DOCUMENT_DATA_DIR,
        posting_data_dir=POSTING_DATA_DIR,
        document_index_path=DOCUMENT_INDEX_PATH,
        keyword_index_path=KEYWORD_INDEX_PATH,
        k1=selected.k1,
        b=selected.b,
    )
    shared_config = StreamingMultiFieldBM25Config(
        max_records_in_memory=selected.max_records_in_memory,
        max_rows_per_shard=selected.max_rows_per_shard,
        postings_per_row=selected.postings_per_cell,
        max_routing_rows=MAX_ROUTING_ROWS_PER_INDEX,
        max_documents=selected.max_documents,
    )
    layout = write_streaming_multifield_bm25_layout(
        rows,
        output_dir,
        profile=profile,
        config=shared_config,
        identity_key=_streaming_identity_key,
        order_key=_streaming_order_key,
        project_document=_streaming_projector(selected),
        document_schema_factory=_streaming_document_schema,
        checkpoint_dir=checkpoint_dir,
        source_digest=normalized_chunk_digest,
        resume=resume,
    )
    return StateLawsStreamingBm25PhysicalLayout(
        layout=layout,
        config=selected,
        canonical_chunk_artifact_digest=normalized_chunk_digest,
    )


# A discoverable spelling for callers that prefer the build mode in the name.
write_state_laws_bm25_physical_layout_streaming = (
    write_state_laws_bm25_physical_layout_from_iterable
)


def _document_row(document: LegalBm25Document) -> dict[str, Any]:
    if document.jurisdiction_code is None or document.census_region is None:
        raise StateLawsBm25PhysicalError(
            f"BM25 document lacks jurisdiction routing fields: {document.entry_cid}"
        )
    row: dict[str, Any] = {
        "census_region": document.census_region,
        "chunk_cid": document.chunk_cid,
        "chunk_id": document.chunk_id,
        "document_index": document.document_index,
        "document_length": document.total_length,
        "entry_cid": document.entry_cid,
        "jurisdiction_code": document.jurisdiction_code,
        "legal_id": document.legal_id,
        "parent_entry_cid": document.parent_entry_cid,
        "record_type": document.record_type,
        "route_key": document_route_key(document.document_index),
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "section": document.section,
        "title_code": document.title_code,
    }
    for field_name in FIELD_ORDER:
        row[f"{field_name}_length"] = document.field_length(field_name)
    return row


def _posting_rows(
    posting: TermPosting,
    *,
    documents_by_index: Sequence[LegalBm25Document],
    index: StateLawsBm25Index,
) -> tuple[dict[str, Any], ...]:
    all_pointers = tuple(pointer for cell in posting.cells for pointer in cell.pointers)
    corpus_frequency = sum(pointer.tf for pointer in all_pointers)
    weighted_corpus_frequency = sum(
        sum(
            float(tf) * index.config.field_weights.weight_for(field_name)
            for field_name, tf in pointer.field_tf.items()
        )
        for pointer in all_pointers
    )
    rows: list[dict[str, Any]] = []
    chunk_count = len(posting.cells)
    for chunk_index, cell in enumerate(posting.cells):
        if cell.pointer_count > index.config.postings_per_cell:
            raise Bm25BoundError(
                f"posting cell for {posting.term!r} exceeds configured pointer bound"
            )
        exact = {
            field_name: [
                int(pointer.field_tf.get(field_name, 0)) for pointer in cell.pointers
            ]
            for field_name in FIELD_ORDER
        }
        document_indices = [pointer.document_index for pointer in cell.pointers]
        try:
            documents = [documents_by_index[value] for value in document_indices]
        except IndexError as exc:
            raise Bm25CoverageError(
                f"posting for {posting.term!r} points at an unknown document"
            ) from exc
        total_frequencies = [pointer.tf for pointer in cell.pointers]
        for offset, pointer in enumerate(cell.pointers):
            exact_total = sum(exact[name][offset] for name in FIELD_ORDER)
            if exact_total != pointer.tf:
                raise Bm25CoverageError(
                    f"field TF parity failed for {posting.term!r} and "
                    f"{pointer.entry_cid}"
                )
        row: dict[str, Any] = {
            "body_frequencies": [
                sum(exact[name][offset] for name in QUERY_BODY_FIELDS)
                for offset in range(cell.pointer_count)
            ],
            "chunk_cids": [
                pointer.chunk_cid or pointer.entry_cid for pointer in cell.pointers
            ],
            "corpus_frequency": corpus_frequency,
            "document_frequency": posting.document_frequency,
            "document_indices": document_indices,
            "document_lengths": [document.total_length for document in documents],
            "entry_cids": [pointer.entry_cid for pointer in cell.pointers],
            "idf": posting.idf,
            "pointer_count": cell.pointer_count,
            "posting_chunk_count": chunk_count,
            "posting_chunk_index": chunk_index,
            "schema_version": POSTING_SCHEMA_VERSION,
            "term": posting.term,
            "title_frequencies": exact["title"],
            "total_frequencies": total_frequencies,
            "weighted_corpus_frequency": weighted_corpus_frequency,
            "weighted_frequencies": [
                sum(
                    float(exact[name][offset])
                    * index.config.field_weights.weight_for(name)
                    for name in FIELD_ORDER
                )
                for offset in range(cell.pointer_count)
            ],
        }
        for field_name in FIELD_ORDER:
            row[f"legal_{field_name}_frequencies"] = exact[field_name]
            row[f"legal_{field_name}_lengths"] = [
                document.field_length(field_name) for document in documents
            ]
        rows.append(row)
    return tuple(rows)


def _iter_document_parts(
    index: StateLawsBm25Index,
) -> Iterator[tuple[dict[str, Any], ...]]:
    expected_document_index = 0
    for source_shard in index.document_shards:
        rows: list[dict[str, Any]] = []
        for source_row in source_shard.documents:
            document_index = int(source_row["document_index"])
            if document_index != expected_document_index:
                raise Bm25CoverageError(
                    "document physical projection changed document order or coverage"
                )
            try:
                document = index.documents[document_index]
            except IndexError as exc:
                raise Bm25CoverageError(
                    f"document shard points at unknown document {document_index}"
                ) from exc
            if document.document_index != document_index:
                raise Bm25CoverageError(
                    "BM25 documents are not densely ordered by document_index"
                )
            rows.append(_document_row(document))
            expected_document_index += 1
        if len(rows) > index.config.max_rows_per_shard:
            raise Bm25BoundError("document physical shard exceeds configured bound")
        yield tuple(rows)
    if expected_document_index != index.document_count:
        raise Bm25CoverageError(
            "document physical projection changed document order or coverage"
        )


def _iter_posting_parts(
    index: StateLawsBm25Index,
) -> Iterator[tuple[dict[str, Any], ...]]:
    pending: list[dict[str, Any]] = []
    previous_term: str | None = None
    term_count = 0
    pointer_count = 0
    for source_shard in index.term_shards:
        for posting in source_shard.terms:
            if previous_term is not None and previous_term >= posting.term:
                raise Bm25CoverageError(
                    "BM25 vocabulary must be globally sorted and unique before export"
                )
            previous_term = posting.term
            term_count += 1
            group = _posting_rows(
                posting,
                documents_by_index=index.documents,
                index=index,
            )
            pointer_count += sum(len(row["document_indices"]) for row in group)
            if len(group) > index.config.max_rows_per_shard:
                raise Bm25BoundError(
                    f"term {posting.term!r} requires {len(group)} physical rows, "
                    f"exceeding the per-shard bound "
                    f"{index.config.max_rows_per_shard}; a term may not span "
                    "overlapping route ranges"
                )
            if pending and len(pending) + len(group) > index.config.max_rows_per_shard:
                yield tuple(pending)
                pending = []
            pending.extend(group)
    if pending:
        yield tuple(pending)
    if term_count == 0:
        raise Bm25CoverageError("BM25 physical export produced no posting rows")
    if term_count != index.term_count:
        raise Bm25CoverageError(
            f"physical term count {term_count} != index term count {index.term_count}"
        )
    if pointer_count != index.posting_count:
        raise Bm25CoverageError(
            f"physical posting count {pointer_count} != index posting count "
            f"{index.posting_count}"
        )


def _route_row(
    descriptor: ArtifactDescriptor,
    *,
    first_key: str,
    last_key: str,
    shard_id: int,
    kind: str,
    start_document_index: int | None = None,
    end_document_index: int | None = None,
) -> dict[str, Any]:
    return CompactIndexRow(
        relative_path=descriptor.relative_path,
        sha256=descriptor.sha256,
        size_bytes=descriptor.size_bytes,
        row_count=descriptor.row_count,
        shard_id=shard_id,
        first_key=first_key,
        last_key=last_key,
        kind=kind,
        content_cid=descriptor.content_cid,
        start_document_index=start_document_index,
        end_document_index=end_document_index,
    ).to_dict()


def _describe_committed(
    root: Path,
    descriptor: ArtifactDescriptor,
) -> ArtifactDescriptor:
    return describe_file(
        confine_path(root, descriptor.relative_path),
        root=root,
        row_count=descriptor.row_count,
        family=descriptor.family,
        schema_id=descriptor.schema_id,
        first_key=descriptor.first_key,
        last_key=descriptor.last_key,
        shard_id=descriptor.shard_id,
        metadata=dict(descriptor.metadata),
    )


def write_state_laws_bm25_physical_layout(
    index: StateLawsBm25Index,
    output_dir: str | Path,
) -> StateLawsBm25PhysicalLayout:
    """Compatibility export for an existing, memory-bound LCR-027 index.

    This API preserves fixture and local-release callers. It is not the
    production corpus path; use
    :func:`write_state_laws_bm25_physical_layout_from_iterable` instead.
    """

    if not isinstance(index, StateLawsBm25Index):
        raise StateLawsBm25PhysicalError("index must be an existing StateLawsBm25Index")
    assert_shards_bounded(index)
    assert_externally_sorted(index)
    assert_postings_reconcile(index)
    if index.config.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise Bm25BoundError("configured row bound exceeds the physical maximum")
    if index.config.postings_per_cell > MAX_POINTERS_PER_ROW:
        raise Bm25BoundError("configured pointer bound exceeds the physical maximum")

    root = resolve_release_root(output_dir, must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    for relative_path in ("data/bm25", DOCUMENT_INDEX_PATH, KEYWORD_INDEX_PATH):
        if confine_path(root, relative_path).is_symlink():
            raise StateLawsBm25PhysicalError(
                f"refusing to replace symlinked BM25 output: {relative_path}"
            )
    pa = _pyarrow()
    shard_config = ArtifactWriterConfig(
        max_rows_per_shard=index.config.max_rows_per_shard,
        max_pointers_per_row=index.config.postings_per_cell,
        max_routing_rows=MAX_ROUTING_ROWS_PER_INDEX,
    )
    route_config = ArtifactWriterConfig(
        max_rows_per_shard=MAX_ROUTING_ROWS_PER_INDEX,
        max_pointers_per_row=index.config.postings_per_cell,
        max_routing_rows=MAX_ROUTING_ROWS_PER_INDEX,
    )

    document_descriptors: list[ArtifactDescriptor] = []
    posting_descriptors: list[ArtifactDescriptor] = []
    document_routes: list[dict[str, Any]] = []
    keyword_routes: list[dict[str, Any]] = []

    document_index_descriptor: ArtifactDescriptor
    keyword_index_descriptor: ArtifactDescriptor
    posting_row_count = 0
    with atomic_staging(root, prefix=".state-laws-bm25-") as session:
        for shard_id, rows in enumerate(_iter_document_parts(index)):
            if shard_id >= MAX_ROUTING_ROWS_PER_INDEX:
                raise Bm25BoundError(
                    "document shard count exceeds the flat query routing-index bound"
                )
            relative_path = f"{DOCUMENT_DATA_DIR}/part-{shard_id:06d}.parquet"
            staged_path = session.confine(relative_path)
            write_zstd_parquet(
                staged_path,
                rows,
                config=shard_config,
                schema=_document_schema(pa, index),
            )
            descriptor = describe_file(
                staged_path,
                root=session.staging_dir,
                row_count=len(rows),
                family=ArtifactFamily.BM25_DOCUMENTS,
                schema_id=DOCUMENT_SCHEMA_VERSION,
                first_key=str(rows[0]["route_key"]),
                last_key=str(rows[-1]["route_key"]),
                shard_id=shard_id,
                metadata={"direct_columns": True},
            )
            document_descriptors.append(descriptor)
            route = _route_row(
                descriptor,
                first_key=str(rows[0]["route_key"]),
                last_key=str(rows[-1]["route_key"]),
                shard_id=shard_id,
                kind="bm25_documents",
                start_document_index=int(rows[0]["document_index"]),
                end_document_index=int(rows[-1]["document_index"]),
            )
            route["document_count"] = len(rows)
            document_routes.append(route)

        previous_last: str | None = None
        for shard_id, rows in enumerate(_iter_posting_parts(index)):
            if shard_id >= MAX_ROUTING_ROWS_PER_INDEX:
                raise Bm25BoundError(
                    "posting shard count exceeds the flat query routing-index bound"
                )
            posting_row_count += len(rows)
            first_term = str(rows[0]["term"])
            last_term = str(rows[-1]["term"])
            if previous_last is not None and previous_last >= first_term:
                raise Bm25CoverageError(
                    "physical BM25 term routes overlap or are not ordered"
                )
            previous_last = last_term
            relative_path = f"{POSTING_DATA_DIR}/part-{shard_id:06d}.parquet"
            staged_path = session.confine(relative_path)
            write_zstd_parquet(
                staged_path,
                rows,
                config=shard_config,
                schema=_posting_schema(pa, index),
            )
            pointer_count = sum(len(row["document_indices"]) for row in rows)
            descriptor = describe_file(
                staged_path,
                root=session.staging_dir,
                row_count=len(rows),
                family=ArtifactFamily.BM25_POSTINGS,
                schema_id=POSTING_SCHEMA_VERSION,
                first_key=first_term,
                last_key=last_term,
                shard_id=shard_id,
                metadata={
                    "direct_columns": True,
                    "pointer_count": pointer_count,
                    "term_count": len({str(row["term"]) for row in rows}),
                },
            )
            posting_descriptors.append(descriptor)
            route = _route_row(
                descriptor,
                first_key=first_term,
                last_key=last_term,
                shard_id=shard_id,
                kind="bm25_postings",
            )
            route.update(
                {
                    "posting_count": pointer_count,
                    "term_count": len({str(row["term"]) for row in rows}),
                    "token_instance_count": sum(
                        sum(int(value) for value in row["total_frequencies"])
                        for row in rows
                    ),
                }
            )
            keyword_routes.append(route)

        document_index_path = session.confine(DOCUMENT_INDEX_PATH)
        write_zstd_parquet(
            document_index_path,
            document_routes,
            config=route_config,
        )
        document_index_descriptor = describe_file(
            document_index_path,
            root=session.staging_dir,
            row_count=len(document_routes),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=COMPACT_INDEX_SCHEMA_VERSION,
            metadata={"direct_columns": True, "kind": "bm25_documents"},
        )

        keyword_index_path = session.confine(KEYWORD_INDEX_PATH)
        write_zstd_parquet(
            keyword_index_path,
            keyword_routes,
            config=route_config,
        )
        keyword_index_descriptor = describe_file(
            keyword_index_path,
            root=session.staging_dir,
            row_count=len(keyword_routes),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=COMPACT_INDEX_SCHEMA_VERSION,
            metadata={"direct_columns": True, "kind": "bm25_postings"},
        )

        # ``data/bm25`` is owned by this adapter, but the surrounding data and
        # indexes directories may contain other release families.
        session.commit_tree("data/bm25")
        for relative_path in (DOCUMENT_INDEX_PATH, KEYWORD_INDEX_PATH):
            session.commit_file(relative_path)

    committed_documents = tuple(
        _describe_committed(root, descriptor) for descriptor in document_descriptors
    )
    committed_postings = tuple(
        _describe_committed(root, descriptor) for descriptor in posting_descriptors
    )
    committed_document_index = _describe_committed(root, document_index_descriptor)
    committed_keyword_index = _describe_committed(root, keyword_index_descriptor)

    return StateLawsBm25PhysicalLayout(
        output_dir=str(root),
        index=index,
        document_descriptors=committed_documents,
        posting_descriptors=committed_postings,
        document_index_descriptor=committed_document_index,
        keyword_index_descriptor=committed_keyword_index,
        document_route_rows=tuple(dict(row) for row in document_routes),
        keyword_route_rows=tuple(dict(row) for row in keyword_routes),
        posting_row_count=posting_row_count,
    )


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CANONICAL_CHUNK_ARTIFACT_DIGEST_CONTRACT",
    "DOCUMENT_DATA_DIR",
    "DOCUMENT_INDEX_PATH",
    "DOCUMENT_SCHEMA_VERSION",
    "INDEX_TO_LAYOUT_PRODUCTION_READY",
    "ITERABLE_TO_LAYOUT_PRODUCTION_READY",
    "KEYWORD_INDEX_PATH",
    "POSTING_DATA_DIR",
    "POSTING_SCHEMA_VERSION",
    "QUERY_BODY_FIELDS",
    "QUERY_TITLE_FIELDS",
    "SCHEMA_VERSION",
    "StateLawsBm25PhysicalError",
    "StateLawsBm25PhysicalLayout",
    "StateLawsStreamingBm25PhysicalLayout",
    "write_state_laws_bm25_physical_layout",
    "write_state_laws_bm25_physical_layout_from_iterable",
    "write_state_laws_bm25_physical_layout_streaming",
]
