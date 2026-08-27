"""Disk-backed state-law ontology projection for the streaming graph writer.

This module is the bounded seam between the admitted parent-corpus layout and
the shared GraphRAG streaming graph writer.  It deliberately does not own a
second graph writer or a second ontology implementation:

* parent rows are replayed from the verified canonical Parquet shards;
* :class:`StateLawsGraphProjector` supplies the existing structure, citation,
  amendment, and edge-typing algorithms;
* SQLite supplies the global node registry, legal-identity locator, and exact
  edge-CID deduplication without materialising the corpus or projection; and
* the result exposes one-shot ``StateLawsGraphNode`` and
  ``StateLawsGraphEdge`` iterables accepted directly by
  ``write_state_laws_streaming_graph_layout``.

The first corpus replay registers every structural endpoint and citation
locator.  The second replay projects citations and amendments.  Citation
resolution prefetches only locator candidates mentioned by the current parent
row before calling the existing resolver, so its small in-memory candidate set
has the same semantics as the former full-corpus sets.

All work is local.  This module performs no network, upload, or publication
operation.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

from ipfs_datasets_py.processors.legal_data.state_laws_corpus_physical import (
    StateLawsStreamingCorpusPhysicalLayout,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph import (
    DEFAULT_EDITION,
    GraphCorpusRow,
    Hierarchy,
    ResolutionStatus,
    SourceSpan,
    StateLawsGraphEdge,
    StateLawsGraphNode,
    StateLawsGraphProjector,
    extract_citation_mentions,
    strip_subsection_qualifier,
)
from ipfs_datasets_py.processors.legal_data.state_laws_identity import (
    parse_legal_id,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    AdmissionStatus,
    CorpusRecord,
    canonical_json_dumps,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    atomic_staging,
    file_digest,
    resolve_release_root,
    verify_descriptor,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ROWS_PER_PHYSICAL_SHARD,
)

SCHEMA_VERSION: Final = "state-laws-streaming-graph-projection/v1"
PROJECTION_DB_FILENAME: Final = "projection.sqlite3"
DEFAULT_PARENT_ROWS_PER_BATCH: Final = 64

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False
PRODUCTION_READY: Final = True


class StateLawsStreamingGraphProjectionError(ValueError):
    """Raised when bounded graph projection cannot be proved exact."""


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _writable_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA temp_store = FILE")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE nodes (
            node_key TEXT PRIMARY KEY,
            node_cid TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE edges (
            edge_cid TEXT PRIMARY KEY,
            edge_type TEXT NOT NULL,
            payload_json TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE legal_ids (
            legal_id TEXT PRIMARY KEY,
            jurisdiction_code TEXT NOT NULL,
            code_family TEXT NOT NULL,
            title TEXT,
            section TEXT NOT NULL,
            node_key TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE locators (
            jurisdiction_code TEXT NOT NULL,
            code_family TEXT NOT NULL,
            section TEXT NOT NULL,
            legal_id TEXT NOT NULL,
            PRIMARY KEY (
                jurisdiction_code,
                code_family,
                section,
                legal_id
            )
        ) WITHOUT ROWID;

        CREATE INDEX locator_lookup
            ON locators (jurisdiction_code, code_family, section);
        CREATE INDEX usc_lookup
            ON legal_ids (code_family, title, section);
        """
    )
    return connection


def _node_from_mapping(value: Mapping[str, Any]) -> StateLawsGraphNode:
    return StateLawsGraphNode(
        node_type=value.get("node_type") or "",
        node_key=str(value.get("node_key") or ""),
        label=str(value.get("label") or ""),
        legal_id=value.get("legal_id"),
        entry_cid=value.get("entry_cid"),
        payload=value.get("payload") or {},
        ontology_version=str(value.get("ontology_version") or ""),
        schema_version=str(value.get("schema_version") or ""),
        node_cid=str(value.get("node_cid") or ""),
    )


def _edge_from_mapping(value: Mapping[str, Any]) -> StateLawsGraphEdge:
    source_span = value.get("source_span")
    return StateLawsGraphEdge(
        edge_type=value.get("edge_type") or "",
        source_node_cid=str(value.get("source_node_cid") or ""),
        target_node_cid=str(value.get("target_node_cid") or ""),
        edge_class=value.get("edge_class") or "",
        source_span=(
            SourceSpan.from_mapping(source_span)
            if isinstance(source_span, Mapping)
            else None
        ),
        resolution_status=(
            ResolutionStatus.coerce(value["resolution_status"])
            if value.get("resolution_status") is not None
            else None
        ),
        weight=value.get("weight"),
        payload=value.get("payload") or {},
        ontology_version=str(value.get("ontology_version") or ""),
        schema_version=str(value.get("schema_version") or ""),
        edge_cid=str(value.get("edge_cid") or ""),
    )


class _SqliteNodeRegistry(MutableMapping[str, StateLawsGraphNode]):
    """The mapping protocol used by the existing projector helpers."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def __getitem__(self, key: str) -> StateLawsGraphNode:
        row = self.connection.execute(
            "SELECT payload_json FROM nodes WHERE node_key = ?", (str(key),)
        ).fetchone()
        if row is None:
            raise KeyError(key)
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, Mapping):
            raise StateLawsStreamingGraphProjectionError(
                f"node registry payload for {key!r} is not a mapping"
            )
        return _node_from_mapping(payload)

    def __setitem__(self, key: str, value: StateLawsGraphNode) -> None:
        if not isinstance(value, StateLawsGraphNode):
            raise StateLawsStreamingGraphProjectionError(
                "node registry accepts only StateLawsGraphNode values"
            )
        if str(key) != value.node_key:
            raise StateLawsStreamingGraphProjectionError(
                "node registry key differs from node.node_key"
            )
        payload_json = canonical_json_dumps(value.to_dict())
        try:
            self.connection.execute(
                "INSERT INTO nodes (node_key, node_cid, payload_json) VALUES (?, ?, ?)",
                (value.node_key, value.node_cid, payload_json),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.connection.execute(
                "SELECT node_key, payload_json FROM nodes "
                "WHERE node_key = ? OR node_cid = ?",
                (value.node_key, value.node_cid),
            ).fetchone()
            if existing is None:
                raise StateLawsStreamingGraphProjectionError(
                    f"failed to register graph node {value.node_key!r}"
                ) from exc
            # StateLawsGraphProjector has first-row-wins semantics for a
            # repeated node_key.  A CID collision across different node keys,
            # however, would violate durable identity.
            if str(existing["node_key"]) != value.node_key:
                raise StateLawsStreamingGraphProjectionError(
                    f"node CID {value.node_cid!r} identifies multiple node keys"
                ) from exc

    def __delitem__(self, key: str) -> None:
        raise TypeError("state-law projection nodes are append-only")

    def __iter__(self) -> Iterator[str]:
        cursor = self.connection.execute("SELECT node_key FROM nodes ORDER BY node_key")
        for row in cursor:
            yield str(row["node_key"])

    def __len__(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()
        return int(row["n"] if row is not None else 0)


def graph_corpus_row_from_parent_mapping(value: Mapping[str, Any]) -> GraphCorpusRow:
    """Bridge one canonical parent row into the existing graph-row schema."""

    record = CorpusRecord.from_mapping(value)
    if record.admission_status is not AdmissionStatus.ADMITTED:
        raise StateLawsStreamingGraphProjectionError(
            f"parent {record.entry_cid!r} is not admitted"
        )
    identity = parse_legal_id(record.legal_id)
    row = GraphCorpusRow(
        entry_cid=record.entry_cid,
        legal_id=record.legal_id,
        text=record.text,
        jurisdiction_code=record.jurisdiction,
        code_family=record.code_family,
        edition=identity.edition or record.edition_as_of or DEFAULT_EDITION,
        hierarchy=Hierarchy(
            title=record.title or identity.title,
            chapter=record.chapter or identity.chapter,
            part=identity.part,
            article=identity.article,
            section=record.section or identity.section,
            subsection=record.subsection or identity.subsection,
        ),
        source_cid=record.source_cid,
        configuration=record.admission_status.value,
        admission_status=record.admission_status.value,
        acquisition_receipt_cid=record.acquisition_receipt_id,
        official_source_url=record.official_source_url,
        observed_at=record.observed_at,
        public_laws=record.public_laws,
        cites=record.cites,
        amends=record.amends,
        repeals=record.repeals,
        transfers=record.transfers,
    )
    if (
        row.jurisdiction_code != identity.jurisdiction
        or row.code_family != identity.code_family
        or row.section != identity.section
    ):
        raise StateLawsStreamingGraphProjectionError(
            f"parent {record.entry_cid!r} fields diverge from legal_id"
        )
    return row


def _verify_corpus_layout(corpus: StateLawsStreamingCorpusPhysicalLayout) -> None:
    if not isinstance(corpus, StateLawsStreamingCorpusPhysicalLayout):
        raise StateLawsStreamingGraphProjectionError(
            "corpus must be a StateLawsStreamingCorpusPhysicalLayout"
        )
    if corpus.production_ready is not True:
        raise StateLawsStreamingGraphProjectionError(
            "parent corpus layout is not production-ready"
        )
    root = Path(corpus.output_dir)
    for descriptor in corpus.descriptors:
        verify_descriptor(root, descriptor)


def _iter_parent_graph_rows(
    corpus: StateLawsStreamingCorpusPhysicalLayout,
    *,
    batch_size: int,
) -> Iterator[GraphCorpusRow]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - release dependency
        raise StateLawsStreamingGraphProjectionError(
            "pyarrow is required to replay state-law parent shards"
        ) from exc

    expected_index = 0
    previous_order: tuple[str, str] | None = None
    root = Path(corpus.output_dir)
    for descriptor in corpus.data_descriptors:
        path = verify_descriptor(root, descriptor)
        parquet = pq.ParquetFile(path)
        shard_count = 0
        for batch in parquet.iter_batches(batch_size=batch_size):
            for value in batch.to_pylist():
                if not isinstance(value, Mapping):
                    raise StateLawsStreamingGraphProjectionError(
                        "parent Parquet row is not a mapping"
                    )
                document_index = value.get("document_index")
                if document_index != expected_index:
                    raise StateLawsStreamingGraphProjectionError(
                        "parent document indexes are not dense in replay order: "
                        f"expected {expected_index}, got {document_index!r}"
                    )
                order = (
                    str(
                        value.get("jurisdiction_code")
                        or value.get("jurisdiction")
                        or ""
                    ),
                    str(value.get("entry_cid") or ""),
                )
                if previous_order is not None and order <= previous_order:
                    raise StateLawsStreamingGraphProjectionError(
                        "parent corpus replay is not in canonical "
                        "(jurisdiction_code, entry_cid) order"
                    )
                row = graph_corpus_row_from_parent_mapping(value)
                if order[0] != row.jurisdiction_code:
                    raise StateLawsStreamingGraphProjectionError(
                        "parent jurisdiction columns disagree"
                    )
                yield row
                previous_order = order
                expected_index += 1
                shard_count += 1
        if shard_count != descriptor.row_count:
            raise StateLawsStreamingGraphProjectionError(
                f"parent shard {descriptor.relative_path!r} row count drifted"
            )
    if expected_index != corpus.row_count:
        raise StateLawsStreamingGraphProjectionError(
            "parent replay count differs from the verified corpus layout"
        )


def _register_legal_identity(
    connection: sqlite3.Connection,
    row: GraphCorpusRow,
) -> None:
    identities = [(row.legal_id, row.hierarchy, _leaf_node_key(row))]
    parent_id = strip_subsection_qualifier(row.legal_id)
    if parent_id != row.legal_id:
        identities.append(
            (
                parent_id,
                Hierarchy(
                    title=row.title,
                    chapter=row.chapter,
                    part=row.hierarchy.part,
                    article=row.hierarchy.article,
                    section=row.section,
                ),
                f"section:{parent_id}",
            )
        )
    for legal_id, hierarchy, node_key in identities:
        if not hierarchy.section:
            raise StateLawsStreamingGraphProjectionError(
                f"graph row {row.entry_cid!r} has no section locator"
            )
        connection.execute(
            "INSERT OR IGNORE INTO legal_ids "
            "(legal_id, jurisdiction_code, code_family, title, section, node_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                legal_id,
                row.jurisdiction_code,
                row.code_family,
                hierarchy.title,
                hierarchy.section,
                node_key,
            ),
        )
        connection.execute(
            "INSERT OR IGNORE INTO locators "
            "(jurisdiction_code, code_family, section, legal_id) "
            "VALUES (?, ?, ?, ?)",
            (
                row.jurisdiction_code,
                row.code_family,
                hierarchy.section,
                legal_id,
            ),
        )


def _leaf_node_key(row: GraphCorpusRow) -> str:
    if row.subsection:
        return f"subsection:{row.legal_id}"
    return f"section:{strip_subsection_qualifier(row.legal_id)}"


def _citation_candidates(
    connection: sqlite3.Connection,
    row: GraphCorpusRow,
) -> tuple[set[str], dict[tuple[str, str, str], tuple[str, ...]]]:
    """Fetch only the global identity rows relevant to this parent's mentions."""

    known: set[str] = set()
    locators: dict[tuple[str, str, str], tuple[str, ...]] = {}
    for mention in extract_citation_mentions(
        row.text,
        default_jurisdiction=row.jurisdiction_code,
        default_code_family=row.code_family,
    ):
        if mention.kind == "public_law":
            continue
        jurisdiction = mention.jurisdiction_code or row.jurisdiction_code
        code_family = mention.code_family or row.code_family
        section = mention.section
        if jurisdiction and code_family and section:
            key = (jurisdiction, code_family, section)
            if key not in locators:
                matches = tuple(
                    str(item["legal_id"])
                    for item in connection.execute(
                        "SELECT legal_id FROM locators "
                        "WHERE jurisdiction_code = ? AND code_family = ? "
                        "AND section = ? ORDER BY legal_id",
                        key,
                    )
                )
                locators[key] = matches
                known.update(matches)

        # The existing resolver has a federal-USC fallback when no locator is
        # available.  Query the same title/section slice on disk instead of
        # iterating every known legal identity into a Python set.
        if mention.kind == "usc" and mention.title and mention.section:
            known.update(
                str(item["legal_id"])
                for item in connection.execute(
                    "SELECT legal_id FROM legal_ids "
                    "WHERE code_family = 'usc' AND title = ? AND section = ? "
                    "ORDER BY legal_id",
                    (mention.title, mention.section),
                )
            )
    return known, locators


def _store_edges(
    connection: sqlite3.Connection,
    edges: list[StateLawsGraphEdge],
) -> int:
    inserted = 0
    for edge in edges:
        if not isinstance(edge, StateLawsGraphEdge):
            raise StateLawsStreamingGraphProjectionError(
                "existing projector emitted a non-state-law edge"
            )
        payload_json = canonical_json_dumps(edge.to_dict())
        try:
            connection.execute(
                "INSERT INTO edges (edge_cid, edge_type, payload_json) "
                "VALUES (?, ?, ?)",
                (edge.edge_cid, edge.edge_type.value, payload_json),
            )
            inserted += 1
        except sqlite3.IntegrityError as exc:
            existing = connection.execute(
                "SELECT payload_json FROM edges WHERE edge_cid = ?",
                (edge.edge_cid,),
            ).fetchone()
            if existing is None or str(existing["payload_json"]) != payload_json:
                raise StateLawsStreamingGraphProjectionError(
                    f"edge CID collision for {edge.edge_cid!r}"
                ) from exc
    return inserted


def _corpus_fingerprint(corpus: StateLawsStreamingCorpusPhysicalLayout) -> str:
    return content_sha256(
        canonical_json_dumps(
            {
                "corpus_index_sha256": corpus.corpus_index_descriptor.sha256,
                "data": [
                    {
                        "path": item.relative_path,
                        "row_count": item.row_count,
                        "sha256": item.sha256,
                    }
                    for item in corpus.data_descriptors
                ],
                "row_count": corpus.row_count,
                "sort_receipts": {
                    key: dict(value) for key, value in corpus.sort_receipts.items()
                },
            }
        )
    )


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["key"]): str(row["value"])
        for row in connection.execute("SELECT key, value FROM metadata")
    }


@dataclass(slots=True)
class StateLawsStreamingGraphProjectionStage:
    """Committed disk-backed projector result with one-shot typed streams."""

    database_path: str
    database_size_bytes: int
    database_sha256: str
    corpus_fingerprint: str
    corpus_row_count: int
    node_count: int
    edge_count: int
    duplicate_edge_count: int
    max_parent_rows_per_batch: int
    max_projected_edges_per_parent: int
    _nodes_claimed: bool = field(default=False, init=False, repr=False)
    _edges_claimed: bool = field(default=False, init=False, repr=False)
    _verified: bool = field(default=False, init=False, repr=False)

    @property
    def production_ready(self) -> bool:
        return (
            PRODUCTION_READY
            and self._verified
            and self.corpus_row_count > 0
            and self.node_count > 0
            and self.edge_count > 0
            and 1 <= self.max_parent_rows_per_batch <= MAX_ROWS_PER_PHYSICAL_SHARD
        )

    @property
    def counts(self) -> Mapping[str, int]:
        return {
            "corpus_documents": self.corpus_row_count,
            "graph_nodes": self.node_count,
            "graph_edges": self.edge_count,
            "deduplicated_graph_edges": self.duplicate_edge_count,
        }

    def verify(self) -> None:
        path = Path(self.database_path)
        size, digest = file_digest(path)
        if size != self.database_size_bytes or digest.hex() != self.database_sha256:
            raise StateLawsStreamingGraphProjectionError(
                "projection database size/sha256 verification failed"
            )
        with _read_only_connection(path) as connection:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]) != "ok":
                raise StateLawsStreamingGraphProjectionError(
                    "projection SQLite integrity check failed"
                )
            metadata = _metadata(connection)
            required = {
                "citation_resolution": "disk_backed_candidate_locator_prefetch",
                "corpus_fingerprint": self.corpus_fingerprint,
                "corpus_replays": "2",
                "edge_count": str(self.edge_count),
                "node_count": str(self.node_count),
                "ontology_algorithms": "StateLawsGraphProjector",
                "schema_version": SCHEMA_VERSION,
                "shared_graph_writer_reused": "true",
                "storage_backend": "sqlite",
            }
            for key, expected in required.items():
                if metadata.get(key) != expected:
                    raise StateLawsStreamingGraphProjectionError(
                        f"projection metadata {key!r} failed verification"
                    )
            node_count = int(
                connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            )
            edge_count = int(
                connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            )
            if node_count != self.node_count or edge_count != self.edge_count:
                raise StateLawsStreamingGraphProjectionError(
                    "projection database counts failed verification"
                )
        self._verified = True

    def iter_nodes(self) -> Iterator[StateLawsGraphNode]:
        if not self.production_ready:
            raise StateLawsStreamingGraphProjectionError(
                "projection stage must verify before node replay"
            )
        if self._nodes_claimed:
            raise StateLawsStreamingGraphProjectionError(
                "projection node iterable is one-shot and was already claimed"
            )
        self._nodes_claimed = True
        return self._iter_nodes()

    def _iter_nodes(self) -> Iterator[StateLawsGraphNode]:
        count = 0
        with _read_only_connection(Path(self.database_path)) as connection:
            for row in connection.execute(
                "SELECT payload_json FROM nodes ORDER BY node_cid"
            ):
                payload = json.loads(str(row["payload_json"]))
                if not isinstance(payload, Mapping):
                    raise StateLawsStreamingGraphProjectionError(
                        "stored graph node is not a mapping"
                    )
                count += 1
                yield _node_from_mapping(payload)
        if count != self.node_count:
            raise StateLawsStreamingGraphProjectionError(
                "node replay count differs from projection receipt"
            )

    def iter_edges(self) -> Iterator[StateLawsGraphEdge]:
        if not self.production_ready:
            raise StateLawsStreamingGraphProjectionError(
                "projection stage must verify before edge replay"
            )
        if self._edges_claimed:
            raise StateLawsStreamingGraphProjectionError(
                "projection edge iterable is one-shot and was already claimed"
            )
        self._edges_claimed = True
        return self._iter_edges()

    def _iter_edges(self) -> Iterator[StateLawsGraphEdge]:
        count = 0
        with _read_only_connection(Path(self.database_path)) as connection:
            for row in connection.execute(
                "SELECT payload_json FROM edges ORDER BY edge_cid"
            ):
                payload = json.loads(str(row["payload_json"]))
                if not isinstance(payload, Mapping):
                    raise StateLawsStreamingGraphProjectionError(
                        "stored graph edge is not a mapping"
                    )
                count += 1
                yield _edge_from_mapping(payload)
        if count != self.edge_count:
            raise StateLawsStreamingGraphProjectionError(
                "edge replay count differs from projection receipt"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounds": {
                "max_parent_rows_per_batch": self.max_parent_rows_per_batch,
                "max_projected_edges_per_parent": (self.max_projected_edges_per_parent),
            },
            "corpus_fingerprint": self.corpus_fingerprint,
            "counts": dict(self.counts),
            "database": {
                "path": PROJECTION_DB_FILENAME,
                "sha256": self.database_sha256,
                "size_bytes": self.database_size_bytes,
            },
            "production_ready": self.production_ready,
            "schema_version": SCHEMA_VERSION,
            "shared_graph_writer_reused": True,
            "storage_backend": "sqlite",
        }


def project_state_laws_streaming_graph_from_corpus(
    corpus: StateLawsStreamingCorpusPhysicalLayout,
    work_dir: str | Path,
    *,
    max_parent_rows_per_batch: int = DEFAULT_PARENT_ROWS_PER_BATCH,
) -> StateLawsStreamingGraphProjectionStage:
    """Project a verified canonical parent layout into bounded graph streams."""

    if (
        isinstance(max_parent_rows_per_batch, bool)
        or not isinstance(max_parent_rows_per_batch, int)
        or not 1 <= max_parent_rows_per_batch <= MAX_ROWS_PER_PHYSICAL_SHARD
    ):
        raise StateLawsStreamingGraphProjectionError(
            "max_parent_rows_per_batch must be within the physical row bound"
        )
    _verify_corpus_layout(corpus)

    target = Path(work_dir).expanduser().resolve(strict=False)
    if target.exists():
        raise StateLawsStreamingGraphProjectionError(
            f"projection work_dir already exists: {target}"
        )
    if target.name in {"", ".", ".."}:
        raise StateLawsStreamingGraphProjectionError("projection work_dir is unsafe")
    parent = resolve_release_root(target.parent, must_exist=False)
    corpus_fingerprint = _corpus_fingerprint(corpus)

    node_count = 0
    edge_count = 0
    duplicate_edge_count = 0
    max_edges_per_parent = 0

    with atomic_staging(parent, prefix=".state-laws-graph-project-") as staging:
        staged_dir = staging.path / target.name
        staged_dir.mkdir(parents=True, exist_ok=False)
        database_path = staged_dir / PROJECTION_DB_FILENAME
        connection = _writable_connection(database_path)
        registry = _SqliteNodeRegistry(connection)
        projector = StateLawsGraphProjector()
        try:
            # First replay: all structural endpoints and legal locators must
            # exist before a citation is resolved.
            for row in _iter_parent_graph_rows(
                corpus, batch_size=max_parent_rows_per_batch
            ):
                projected: list[StateLawsGraphEdge] = []
                projector._project_structure(registry, projected, row)
                _register_legal_identity(connection, row)
                inserted = _store_edges(connection, projected)
                duplicate_edge_count += len(projected) - inserted
                max_edges_per_parent = max(max_edges_per_parent, len(projected))

            # Second replay: use the on-disk legal locator and canonical node
            # registry while reusing the existing citation/amendment logic.
            for row in _iter_parent_graph_rows(
                corpus, batch_size=max_parent_rows_per_batch
            ):
                known, locators = _citation_candidates(connection, row)
                projected = []
                projector._project_citations(
                    registry,
                    projected,
                    row,
                    known_legal_ids=known,
                    locator_index=locators,
                )
                projector._project_amendments(registry, projected, row)
                inserted = _store_edges(connection, projected)
                duplicate_edge_count += len(projected) - inserted
                max_edges_per_parent = max(max_edges_per_parent, len(projected))

            node_count = len(registry)
            edge_count_row = connection.execute(
                "SELECT COUNT(*) AS n FROM edges"
            ).fetchone()
            edge_count = int(edge_count_row["n"] if edge_count_row is not None else 0)
            if node_count < 1 or edge_count < 1:
                raise StateLawsStreamingGraphProjectionError(
                    "bounded projection produced an empty node/edge family"
                )
            metadata = {
                "citation_resolution": "disk_backed_candidate_locator_prefetch",
                "corpus_fingerprint": corpus_fingerprint,
                "corpus_replays": "2",
                "edge_count": str(edge_count),
                "node_count": str(node_count),
                "ontology_algorithms": "StateLawsGraphProjector",
                "schema_version": SCHEMA_VERSION,
                "shared_graph_writer_reused": "true",
                "storage_backend": "sqlite",
            }
            connection.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                sorted(metadata.items()),
            )
            connection.commit()
            connection.execute("PRAGMA optimize")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        staging.commit_tree(target.name, overwrite=False)

    final_database = target / PROJECTION_DB_FILENAME
    database_size, database_digest = file_digest(final_database)
    result = StateLawsStreamingGraphProjectionStage(
        database_path=str(final_database),
        database_size_bytes=database_size,
        database_sha256=database_digest.hex(),
        corpus_fingerprint=corpus_fingerprint,
        corpus_row_count=corpus.row_count,
        node_count=node_count,
        edge_count=edge_count,
        duplicate_edge_count=duplicate_edge_count,
        max_parent_rows_per_batch=max_parent_rows_per_batch,
        max_projected_edges_per_parent=max_edges_per_parent,
    )
    result.verify()
    return result


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "DEFAULT_PARENT_ROWS_PER_BATCH",
    "PERFORMS_NETWORK_IO",
    "PRODUCTION_READY",
    "PROJECTION_DB_FILENAME",
    "SCHEMA_VERSION",
    "StateLawsStreamingGraphProjectionError",
    "StateLawsStreamingGraphProjectionStage",
    "graph_corpus_row_from_parent_mapping",
    "project_state_laws_streaming_graph_from_corpus",
]
