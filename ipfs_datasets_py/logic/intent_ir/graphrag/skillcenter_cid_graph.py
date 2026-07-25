"""Scalable CID-primary-key knowledge graph for the full SkillCenter corpus."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
from typing import Any, Final

from ipfs_datasets_py.utils.cid_utils import cid_for_bytes

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1_from_digest
from ...profile_g import validate_cid
from .skillcenter_corpus import (
    SKILLCENTER_CORPUS_PRIMARY_KEY,
    SkillCenterCorpusIndex,
)
from .skillcenter_corpus_bm25 import (
    SkillCenterCorpusBM25Hit,
    SkillCenterCorpusBM25Index,
    _neighbor_query_terms,
)


SKILLCENTER_CID_GRAPH_SCHEMA_VERSION: Final = "skillcenter-cid-graph/v1"
SKILLCENTER_CID_GRAPH_NODE_SCHEMA_VERSION: Final = (
    "skillcenter-cid-graph-node/v1"
)
SKILLCENTER_CID_GRAPH_EDGE_SCHEMA_VERSION: Final = (
    "skillcenter-cid-graph-edge/v1"
)
DEFAULT_NEIGHBOR_K: Final = 8
DEFAULT_BATCH_SIZE: Final = 256
DEFAULT_QUERY_WORKERS: Final = 8

_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_NODE_TYPES = frozenset({"BUNDLE", "CONTENT", "DOMAIN", "LICENSE", "SKILL"})
_BASE_EDGE_TYPES = frozenset(
    {"HAS_CONTENT", "HAS_LICENSE", "IN_BUNDLE", "IN_DOMAIN"}
)
_NEIGHBOR_EDGE_TYPE = "BM25_NEIGHBOR_OF"


class SkillCenterCIDGraphError(ValueError):
    """Raised when the CID-keyed graph is invalid."""


@dataclass(frozen=True, slots=True)
class SkillCenterCIDGraphConfig:
    neighbor_k: int = DEFAULT_NEIGHBOR_K
    batch_size: int = DEFAULT_BATCH_SIZE
    query_workers: int = DEFAULT_QUERY_WORKERS

    def __post_init__(self) -> None:
        for name, low, high in (
            ("neighbor_k", 1, 64),
            ("batch_size", 1, 10_000),
            ("query_workers", 1, 64),
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not low <= value <= high
            ):
                raise SkillCenterCIDGraphError(
                    f"{name} must be between {low} and {high}"
                )

    def to_dict(self) -> dict[str, int]:
        return {
            "batch_size": self.batch_size,
            "neighbor_k": self.neighbor_k,
            "query_workers": self.query_workers,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class SkillCenterCIDGraphBuildSummary:
    output_dir: str
    dataset_revision: str
    skill_nodes: int
    graph_nodes: int
    graph_edges: int
    neighbor_edges: int
    graph_cid: str
    sqlite_cid: str
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_revision": self.dataset_revision,
            "graph_cid": self.graph_cid,
            "graph_edges": self.graph_edges,
            "graph_nodes": self.graph_nodes,
            "manifest_sha256": self.manifest_sha256,
            "neighbor_edges": self.neighbor_edges,
            "output_dir": self.output_dir,
            "skill_nodes": self.skill_nodes,
            "sqlite_cid": self.sqlite_cid,
        }


class SkillCenterCIDGraphIndex:
    """Verified read-only facade over a CID-keyed SQLite property graph."""

    def __init__(
        self,
        *,
        root: Path,
        manifest: Mapping[str, Any],
        database_path: Path,
    ) -> None:
        self.root = root
        self.manifest = dict(manifest)
        self.database_path = database_path

    @classmethod
    def load(
        cls,
        root: str | Path,
        *,
        corpus_dir: str | Path | None = None,
        bm25_dir: str | Path | None = None,
        verify_integrity: bool = True,
    ) -> "SkillCenterCIDGraphIndex":
        graph_root = Path(root).expanduser().resolve()
        manifest_path = graph_root / "manifest.json"
        if (
            graph_root.is_symlink()
            or not graph_root.is_dir()
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
            or manifest_path.stat().st_size > _MAX_MANIFEST_BYTES
        ):
            raise SkillCenterCIDGraphError(
                "graph must contain a bounded regular manifest"
            )
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCenterCIDGraphError("graph manifest is malformed") from exc
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("schema_version")
            != SKILLCENTER_CID_GRAPH_SCHEMA_VERSION
            or manifest.get("primary_key")
            != SKILLCENTER_CORPUS_PRIMARY_KEY
        ):
            raise SkillCenterCIDGraphError("unsupported graph manifest")
        database_path = _verify_file_descriptor(
            graph_root,
            manifest.get("sqlite"),
        )
        uri = f"{database_path.as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            if verify_integrity:
                result = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                if result is None or result[0] != "ok":
                    raise SkillCenterCIDGraphError(
                        "graph SQLite integrity check failed"
                    )
            node_count = int(
                connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            )
            edge_count = int(
                connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            )
            skill_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM nodes "
                    "WHERE node_type = 'SKILL' AND node_cid = entry_cid"
                ).fetchone()[0]
            )
            neighbor_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM edges WHERE edge_type = ?",
                    (_NEIGHBOR_EDGE_TYPE,),
                ).fetchone()[0]
            )
            if (
                node_count != int(manifest.get("graph_nodes", -1))
                or edge_count != int(manifest.get("graph_edges", -1))
                or skill_count != int(manifest.get("skill_nodes", -1))
                or neighbor_count != int(manifest.get("neighbor_edges", -1))
            ):
                raise SkillCenterCIDGraphError(
                    "graph counts do not match its manifest"
                )
            invalid_neighbors = int(
                connection.execute(
                    "SELECT COUNT(*) FROM edges e "
                    "LEFT JOIN nodes s ON s.node_cid = e.source_cid "
                    "LEFT JOIN nodes t ON t.node_cid = e.target_cid "
                    "WHERE e.edge_type = ? AND ("
                    "e.retrieval_method != 'bm25-okapi' OR "
                    "e.score IS NULL OR e.score < 0 OR "
                    "s.node_type != 'SKILL' OR t.node_type != 'SKILL')",
                    (_NEIGHBOR_EDGE_TYPE,),
                ).fetchone()[0]
            )
            if invalid_neighbors:
                raise SkillCenterCIDGraphError(
                    "graph contains invalid BM25 neighbor edges"
                )
        loaded = cls(
            root=graph_root,
            manifest=manifest,
            database_path=database_path,
        )
        if corpus_dir is not None or bm25_dir is not None:
            loaded.verify_inputs(corpus_dir=corpus_dir, bm25_dir=bm25_dir)
        return loaded

    @property
    def summary(self) -> SkillCenterCIDGraphBuildSummary:
        return SkillCenterCIDGraphBuildSummary(
            output_dir=str(self.root),
            dataset_revision=str(self.manifest["dataset_revision"]),
            skill_nodes=int(self.manifest["skill_nodes"]),
            graph_nodes=int(self.manifest["graph_nodes"]),
            graph_edges=int(self.manifest["graph_edges"]),
            neighbor_edges=int(self.manifest["neighbor_edges"]),
            graph_cid=str(self.manifest["graph_cid"]),
            sqlite_cid=str(self.manifest["sqlite"]["cid"]),
            manifest_sha256=hashlib.sha256(
                (self.root / "manifest.json").read_bytes()
            ).hexdigest(),
        )

    def neighbors(
        self,
        entry_cid: str,
        *,
        k: int = 10,
    ) -> tuple[dict[str, Any], ...]:
        validate_cid(entry_cid, path="/entry_cid")
        uri = f"{self.database_path.as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT e.target_cid AS entry_cid, e.score, "
                "e.query_terms_json, n.label, n.properties_json "
                "FROM edges e JOIN nodes n ON n.node_cid = e.target_cid "
                "WHERE e.source_cid = ? AND e.edge_type = ? "
                "ORDER BY e.score DESC, e.target_cid LIMIT ?",
                (entry_cid, _NEIGHBOR_EDGE_TYPE, k),
            ).fetchall()
        return tuple(
            {
                "entry_cid": str(row["entry_cid"]),
                "label": str(row["label"]),
                "properties": json.loads(str(row["properties_json"])),
                "query_terms": json.loads(str(row["query_terms_json"])),
                "score": float(row["score"]),
            }
            for row in rows
        )

    def verify_inputs(
        self,
        *,
        corpus_dir: str | Path | None,
        bm25_dir: str | Path | None,
    ) -> None:
        if corpus_dir is not None:
            corpus = SkillCenterCorpusIndex.load(corpus_dir, verify_rows=False)
            if self.manifest.get("corpus_input") != _corpus_input(corpus):
                raise SkillCenterCIDGraphError(
                    "graph is not bound to this corpus"
                )
        if bm25_dir is not None:
            bm25 = SkillCenterCorpusBM25Index.load(
                bm25_dir,
                verify_integrity=False,
            )
            if self.manifest.get("bm25_input") != _bm25_input(bm25):
                raise SkillCenterCIDGraphError(
                    "graph is not bound to this BM25 index"
                )


def build_skillcenter_cid_graph(
    corpus_dir: str | Path,
    bm25_dir: str | Path,
    *,
    output_dir: str | Path,
    config: SkillCenterCIDGraphConfig | None = None,
    progress_callback: Any | None = None,
    max_neighbor_sources: int | None = None,
) -> SkillCenterCIDGraphBuildSummary | dict[str, Any]:
    """Build or resume the complete CID-keyed graph.

    ``max_neighbor_sources`` is an operational checkpoint bound. When supplied,
    a partial progress dictionary is returned after that many new sources.
    """

    if max_neighbor_sources is not None and (
        isinstance(max_neighbor_sources, bool)
        or not isinstance(max_neighbor_sources, int)
        or max_neighbor_sources < 0
    ):
        raise SkillCenterCIDGraphError(
            "max_neighbor_sources must be non-negative or None"
        )
    active_config = config or SkillCenterCIDGraphConfig()
    corpus = SkillCenterCorpusIndex.load(corpus_dir, verify_rows=False)
    bm25 = SkillCenterCorpusBM25Index.load(
        bm25_dir,
        corpus_dir=corpus.root,
        verify_integrity=False,
    )
    corpus_input = _corpus_input(corpus)
    bm25_input = _bm25_input(bm25)
    identity_payload = {
        "bm25_input": bm25_input,
        "config": active_config.to_dict(),
        "corpus_input": corpus_input,
        "primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY,
        "schema_version": SKILLCENTER_CID_GRAPH_SCHEMA_VERSION,
    }
    build_identity_sha256 = hashlib.sha256(
        canonical_json_bytes(identity_payload)
    ).hexdigest()
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink() or not output.is_dir():
        raise SkillCenterCIDGraphError("output_dir must be a real directory")
    with _build_lock(output):
        if (output / "manifest.json").exists():
            existing = SkillCenterCIDGraphIndex.load(
                output,
                corpus_dir=corpus.root,
                bm25_dir=bm25.root,
            )
            if (
                existing.manifest.get("build_identity_sha256")
                != build_identity_sha256
            ):
                raise SkillCenterCIDGraphError(
                    "existing graph was built from different inputs"
                )
            return existing.summary
        partial_path = output / "graph.partial.sqlite"
        connection = sqlite3.connect(partial_path)
        try:
            _initialize_database(
                connection,
                build_identity_sha256=build_identity_sha256,
            )
            _verify_partial_identity(
                connection,
                build_identity_sha256=build_identity_sha256,
            )
            if _state(connection, "base_complete") != "1":
                _build_base_graph(
                    connection,
                    corpus=corpus,
                    config=active_config,
                    progress_callback=progress_callback,
                )
            processed_now = _build_neighbor_edges(
                connection,
                bm25=bm25,
                config=active_config,
                progress_callback=progress_callback,
                max_sources=max_neighbor_sources,
            )
            total_sources = int(
                _state(connection, "neighbor_sources_processed") or "0"
            )
            expected_sources = int(corpus.manifest["source_records"])
            if total_sources < expected_sources:
                connection.commit()
                return {
                    "complete": False,
                    "neighbor_sources_processed": total_sources,
                    "neighbor_sources_processed_now": processed_now,
                    "output_dir": str(output),
                    "source_records": expected_sources,
                }
            _finalize_database(connection)
        finally:
            connection.close()
        final_path = output / "graph.sqlite"
        os.replace(partial_path, final_path)
        descriptor = _file_descriptor(final_path, root=output)
        with closing(sqlite3.connect(final_path)) as verified:
            node_counts = dict(
                verified.execute(
                    "SELECT node_type, COUNT(*) FROM nodes GROUP BY node_type"
                )
            )
            edge_counts = dict(
                verified.execute(
                    "SELECT edge_type, COUNT(*) FROM edges GROUP BY edge_type"
                )
            )
        graph_root_payload = {
            "bm25_input": bm25_input,
            "config_sha256": active_config.digest,
            "corpus_input": corpus_input,
            "edge_counts": edge_counts,
            "node_counts": node_counts,
            "sqlite_cid": descriptor["cid"],
        }
        graph_cid = cid_for_bytes(canonical_json_bytes(graph_root_payload))
        manifest = {
            "bm25_input": bm25_input,
            "build_identity_sha256": build_identity_sha256,
            "config": active_config.to_dict(),
            "config_sha256": active_config.digest,
            "corpus_input": corpus_input,
            "dataset_id": corpus.manifest["dataset_id"],
            "dataset_revision": corpus.manifest["dataset_revision"],
            "edge_counts": edge_counts,
            "graph_cid": graph_cid,
            "graph_edges": sum(int(value) for value in edge_counts.values()),
            "graph_nodes": sum(int(value) for value in node_counts.values()),
            "neighbor_edges": int(edge_counts.get(_NEIGHBOR_EDGE_TYPE, 0)),
            "node_counts": node_counts,
            "primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY,
            "schema_version": SKILLCENTER_CID_GRAPH_SCHEMA_VERSION,
            "skill_nodes": int(node_counts.get("SKILL", 0)),
            "sqlite": descriptor,
        }
        _write_bytes_atomic(
            output / "manifest.json",
            canonical_json_bytes(manifest),
        )
    return SkillCenterCIDGraphIndex.load(
        output,
        corpus_dir=corpus.root,
        bm25_dir=bm25.root,
    ).summary


def _initialize_database(
    connection: sqlite3.Connection,
    *,
    build_identity_sha256: str,
) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;
        PRAGMA foreign_keys = ON;
        PRAGMA temp_store = MEMORY;
        CREATE TABLE IF NOT EXISTS build_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS nodes (
            node_cid TEXT PRIMARY KEY,
            node_type TEXT NOT NULL,
            entry_cid TEXT,
            label TEXT NOT NULL,
            properties_json TEXT NOT NULL,
            schema_version TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS edges (
            edge_cid TEXT PRIMARY KEY,
            edge_type TEXT NOT NULL,
            source_cid TEXT NOT NULL REFERENCES nodes(node_cid),
            target_cid TEXT NOT NULL REFERENCES nodes(node_cid),
            retrieval_method TEXT NOT NULL,
            score REAL,
            query_terms_json TEXT NOT NULL,
            properties_json TEXT NOT NULL,
            schema_version TEXT NOT NULL
        ) WITHOUT ROWID;
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO build_state(key, value) VALUES (?, ?)",
        ("build_identity_sha256", build_identity_sha256),
    )
    connection.commit()


def _verify_partial_identity(
    connection: sqlite3.Connection,
    *,
    build_identity_sha256: str,
) -> None:
    if _state(connection, "build_identity_sha256") != build_identity_sha256:
        raise SkillCenterCIDGraphError(
            "partial graph belongs to different inputs or configuration"
        )


def _build_base_graph(
    connection: sqlite3.Connection,
    *,
    corpus: SkillCenterCorpusIndex,
    config: SkillCenterCIDGraphConfig,
    progress_callback: Any | None,
) -> None:
    last_index = int(_state(connection, "base_last_corpus_index") or "-1")
    columns = (
        "bundle_cid",
        "content_cid",
        "corpus_index",
        "domain",
        "entry_cid",
        "license_expression",
        "profile",
        "repository_file",
        "skill_id",
        "skill_kind",
        "source_type",
        "title",
    )
    pending = 0
    for row in corpus.iter_rows(columns=columns, batch_size=config.batch_size):
        corpus_index = int(row["corpus_index"])
        if corpus_index <= last_index:
            continue
        entry_cid = str(row["entry_cid"])
        bundle_cid = str(row["bundle_cid"])
        content_cid = str(row["content_cid"])
        domain_value = str(row["domain"] or "unknown")
        license_value = str(row["license_expression"] or "unknown")
        domain_cid = _facet_cid("domain", domain_value)
        license_cid = _facet_cid("license", license_value)
        _insert_node(
            connection,
            node_cid=entry_cid,
            node_type="SKILL",
            entry_cid=entry_cid,
            label=str(row["title"]),
            properties={
                "domain": domain_value,
                "entry_cid": entry_cid,
                "profile": str(row["profile"]),
                "repository_file": str(row["repository_file"]),
                "skill_id": str(row["skill_id"]),
                "skill_kind": str(row["skill_kind"]),
                "source_type": str(row["source_type"]),
            },
        )
        _insert_node(
            connection,
            node_cid=bundle_cid,
            node_type="BUNDLE",
            entry_cid=None,
            label=str(row["repository_file"]),
            properties={"repository_file": str(row["repository_file"])},
        )
        _insert_node(
            connection,
            node_cid=content_cid,
            node_type="CONTENT",
            entry_cid=None,
            label=content_cid,
            properties={"content_cid": content_cid},
        )
        _insert_node(
            connection,
            node_cid=domain_cid,
            node_type="DOMAIN",
            entry_cid=None,
            label=domain_value,
            properties={"domain": domain_value},
        )
        _insert_node(
            connection,
            node_cid=license_cid,
            node_type="LICENSE",
            entry_cid=None,
            label=license_value,
            properties={"license_expression": license_value},
        )
        for edge_type, target_cid in (
            ("HAS_CONTENT", content_cid),
            ("HAS_LICENSE", license_cid),
            ("IN_BUNDLE", bundle_cid),
            ("IN_DOMAIN", domain_cid),
        ):
            _insert_edge(
                connection,
                edge_type=edge_type,
                source_cid=entry_cid,
                target_cid=target_cid,
            )
        last_index = corpus_index
        pending += 1
        if pending >= config.batch_size:
            _set_state(connection, "base_last_corpus_index", str(last_index))
            connection.commit()
            pending = 0
            _notify(
                progress_callback,
                {
                    "phase": "base_graph",
                    "records_processed": last_index + 1,
                    "records_total": corpus.manifest["source_records"],
                },
            )
    _set_state(connection, "base_last_corpus_index", str(last_index))
    _set_state(connection, "base_complete", "1")
    connection.commit()


def _build_neighbor_edges(
    connection: sqlite3.Connection,
    *,
    bm25: SkillCenterCorpusBM25Index,
    config: SkillCenterCIDGraphConfig,
    progress_callback: Any | None,
    max_sources: int | None,
) -> int:
    last_entry_cid = _state(connection, "neighbor_last_entry_cid") or ""
    processed_total = int(
        _state(connection, "neighbor_sources_processed") or "0"
    )
    processed_now = 0
    bm25_uri = (
        f"{bm25.database_path.as_uri()}?mode=ro&immutable=1"
    )
    with closing(sqlite3.connect(bm25_uri, uri=True)) as source:
        source.row_factory = sqlite3.Row
        while max_sources is None or processed_now < max_sources:
            limit = config.batch_size
            if max_sources is not None:
                limit = min(limit, max_sources - processed_now)
            if limit <= 0:
                break
            rows = source.execute(
                "SELECT entry_cid, title, domain FROM documents "
                "WHERE entry_cid > ? ORDER BY entry_cid LIMIT ?",
                (last_entry_cid, limit),
            ).fetchall()
            if not rows:
                break
            observations = _query_neighbor_batch(
                bm25,
                [(str(r["entry_cid"]), str(r["title"]), str(r["domain"])) for r in rows],
                k=config.neighbor_k,
                workers=config.query_workers,
            )
            for entry_cid, query_terms, hits in observations:
                for hit in hits:
                    _insert_edge(
                        connection,
                        edge_type=_NEIGHBOR_EDGE_TYPE,
                        source_cid=entry_cid,
                        target_cid=hit.entry_cid,
                        retrieval_method="bm25-okapi",
                        score=hit.score,
                        query_terms=query_terms,
                        properties={
                            "authority": "context_only",
                            "proof_authority": False,
                        },
                    )
            last_entry_cid = str(rows[-1]["entry_cid"])
            processed_now += len(rows)
            processed_total += len(rows)
            _set_state(
                connection,
                "neighbor_last_entry_cid",
                last_entry_cid,
            )
            _set_state(
                connection,
                "neighbor_sources_processed",
                str(processed_total),
            )
            connection.commit()
            _notify(
                progress_callback,
                {
                    "phase": "bm25_neighbors",
                    "sources_processed": processed_total,
                    "sources_total": bm25.manifest["indexed_entries"],
                },
            )
    return processed_now


def _query_neighbor_batch(
    bm25: SkillCenterCorpusBM25Index,
    rows: Sequence[tuple[str, str, str]],
    *,
    k: int,
    workers: int,
) -> list[
    tuple[str, tuple[str, ...], tuple[SkillCenterCorpusBM25Hit, ...]]
]:
    chunks = [list(rows[index::workers]) for index in range(workers)]
    chunks = [chunk for chunk in chunks if chunk]

    def query_chunk(
        chunk: Sequence[tuple[str, str, str]],
    ) -> list[
        tuple[str, tuple[str, ...], tuple[SkillCenterCorpusBM25Hit, ...]]
    ]:
        uri = f"{bm25.database_path.as_uri()}?mode=ro&immutable=1"
        output = []
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            for entry_cid, title, domain in chunk:
                terms = _neighbor_query_terms(title, bm25.config)
                hits = bm25._search_connection(
                    connection,
                    terms=terms,
                    k=k,
                    exclude_entry_cid=entry_cid,
                    filters={"domain": domain},
                    explain=False,
                    title_only=True,
                )
                output.append((entry_cid, terms, hits))
        return output

    if len(chunks) == 1:
        results = [query_chunk(chunks[0])]
    else:
        with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
            results = list(executor.map(query_chunk, chunks))
    flattened = [item for group in results for item in group]
    flattened.sort(key=lambda item: item[0])
    return flattened


def _insert_node(
    connection: sqlite3.Connection,
    *,
    node_cid: str,
    node_type: str,
    entry_cid: str | None,
    label: str,
    properties: Mapping[str, Any],
) -> None:
    if node_type not in _NODE_TYPES:
        raise SkillCenterCIDGraphError(f"unsupported node type: {node_type}")
    validate_cid(node_cid, path="/node_cid")
    payload = (
        node_cid,
        node_type,
        entry_cid,
        label,
        canonical_json_bytes(dict(properties)).decode("utf-8"),
        SKILLCENTER_CID_GRAPH_NODE_SCHEMA_VERSION,
    )
    connection.execute(
        "INSERT OR IGNORE INTO nodes VALUES (?, ?, ?, ?, ?, ?)",
        payload,
    )
    existing = connection.execute(
        "SELECT node_type, entry_cid, label, properties_json, schema_version "
        "FROM nodes WHERE node_cid = ?",
        (node_cid,),
    ).fetchone()
    if existing != payload[1:]:
        raise SkillCenterCIDGraphError(
            f"conflicting node payload for CID {node_cid}"
        )


def _insert_edge(
    connection: sqlite3.Connection,
    *,
    edge_type: str,
    source_cid: str,
    target_cid: str,
    retrieval_method: str = "",
    score: float | None = None,
    query_terms: Sequence[str] = (),
    properties: Mapping[str, Any] | None = None,
) -> None:
    if edge_type not in _BASE_EDGE_TYPES | {_NEIGHBOR_EDGE_TYPE}:
        raise SkillCenterCIDGraphError(f"unsupported edge type: {edge_type}")
    identity = {
        "edge_type": edge_type,
        "query_terms": list(query_terms),
        "retrieval_method": retrieval_method,
        "score": score,
        "source_cid": source_cid,
        "target_cid": target_cid,
    }
    edge_cid = cid_for_bytes(canonical_json_bytes(identity))
    payload = (
        edge_cid,
        edge_type,
        source_cid,
        target_cid,
        retrieval_method,
        score,
        canonical_json_bytes(list(query_terms)).decode("utf-8"),
        canonical_json_bytes(dict(properties or {})).decode("utf-8"),
        SKILLCENTER_CID_GRAPH_EDGE_SCHEMA_VERSION,
    )
    connection.execute(
        "INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        payload,
    )
    existing = connection.execute(
        "SELECT edge_type, source_cid, target_cid, retrieval_method, score, "
        "query_terms_json, properties_json, schema_version "
        "FROM edges WHERE edge_cid = ?",
        (edge_cid,),
    ).fetchone()
    if existing != payload[1:]:
        raise SkillCenterCIDGraphError(
            f"conflicting edge payload for CID {edge_cid}"
        )


def _facet_cid(kind: str, value: str) -> str:
    return cid_for_bytes(
        canonical_json_bytes(
            {
                "kind": kind,
                "schema_version": SKILLCENTER_CID_GRAPH_NODE_SCHEMA_VERSION,
                "value": value,
            }
        )
    )


def _finalize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_nodes_entry
            ON nodes(entry_cid) WHERE entry_cid IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
        CREATE INDEX IF NOT EXISTS idx_edges_source_type
            ON edges(source_cid, edge_type);
        CREATE INDEX IF NOT EXISTS idx_edges_target_type
            ON edges(target_cid, edge_type);
        CREATE INDEX IF NOT EXISTS idx_edges_type_score
            ON edges(edge_type, score DESC);
        """
    )
    _set_state(connection, "complete", "1")
    connection.commit()
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise SkillCenterCIDGraphError(
            "graph database failed final integrity check"
        )
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.commit()


def _state(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT value FROM build_state WHERE key = ?",
        (key,),
    ).fetchone()
    return None if row is None else str(row[0])


def _set_state(
    connection: sqlite3.Connection,
    key: str,
    value: str,
) -> None:
    connection.execute(
        "INSERT INTO build_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _notify(callback: Any | None, payload: Mapping[str, Any]) -> None:
    if callback is not None:
        callback(dict(payload))


def _corpus_input(corpus: SkillCenterCorpusIndex) -> dict[str, Any]:
    manifest_bytes = (corpus.root / "manifest.json").read_bytes()
    return {
        "corpus_cid": corpus.manifest["files"]["corpus"]["cid"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "primary_key": corpus.manifest["primary_key"],
        "source_records": corpus.manifest["source_records"],
    }


def _bm25_input(bm25: SkillCenterCorpusBM25Index) -> dict[str, Any]:
    manifest_bytes = (bm25.root / "manifest.json").read_bytes()
    return {
        "indexed_entries": bm25.manifest["indexed_entries"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "primary_key": bm25.manifest["primary_key"],
        "sqlite_cid": bm25.manifest["sqlite"]["cid"],
    }


def _file_descriptor(path: Path, *, root: Path) -> dict[str, Any]:
    size_bytes, digest = _file_digest(path)
    return {
        "cid": cid_v1_from_digest(digest),
        "media_type": "application/vnd.sqlite3",
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": digest.hex(),
        "size_bytes": size_bytes,
    }


def _verify_file_descriptor(root: Path, value: Any) -> Path:
    if not isinstance(value, Mapping):
        raise SkillCenterCIDGraphError("graph file descriptor is missing")
    relative = value.get("relative_path")
    if not isinstance(relative, str) or not relative:
        raise SkillCenterCIDGraphError("graph file path is missing")
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise SkillCenterCIDGraphError("graph file path is unsafe")
    path = root.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise SkillCenterCIDGraphError("graph SQLite artifact is missing")
    size_bytes, digest = _file_digest(path)
    if (
        size_bytes != int(value.get("size_bytes", -1))
        or digest.hex() != value.get("sha256")
        or cid_v1_from_digest(digest) != value.get("cid")
    ):
        raise SkillCenterCIDGraphError("graph SQLite identity mismatch")
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


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _build_lock(output: Path) -> Iterator[None]:
    import fcntl

    lock_path = output / ".build.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with os.fdopen(descriptor, "a+b", closefd=True) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
    finally:
        pass


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_NEIGHBOR_K",
    "DEFAULT_QUERY_WORKERS",
    "SKILLCENTER_CID_GRAPH_SCHEMA_VERSION",
    "SkillCenterCIDGraphBuildSummary",
    "SkillCenterCIDGraphConfig",
    "SkillCenterCIDGraphError",
    "SkillCenterCIDGraphIndex",
    "build_skillcenter_cid_graph",
]
