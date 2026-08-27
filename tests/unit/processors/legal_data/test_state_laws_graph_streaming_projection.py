"""Focused tests for the disk-backed state-law graph projector seam."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import fixture_bm25_config
from ipfs_datasets_py.processors.legal_data.state_laws_bm25_physical import (
    write_state_laws_bm25_physical_layout_from_iterable,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus_physical import (
    StateLawsStreamingCorpusPhysicalLayout,
    write_state_laws_corpus_physical_layout_from_iterable,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph import (
    GraphEdgeType,
    StateLawsGraphEdge,
    StateLawsGraphNode,
    StateLawsGraphProjector,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph_physical import (
    write_state_laws_streaming_graph_layout,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph_streaming_projection import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    PERFORMS_NETWORK_IO,
    StateLawsStreamingGraphProjectionError,
    graph_corpus_row_from_parent_mapping,
    project_state_laws_streaming_graph_from_corpus,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    AdmissionStatus,
    CorpusRecord,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
)
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_graph import (
    StreamingGraphConfig,
)

RELEASE_POINT = "state-laws-v2-2026-08-24"


def _sha256(seed: str, *, prefixed: bool = False) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"sha256:{digest}" if prefixed else digest


def _record(
    code: str,
    section: str,
    text: str,
    *,
    code_family: str = "code",
    public_laws: tuple[str, ...] = (),
    cites: tuple[str, ...] = (),
    amends: tuple[str, ...] = (),
    repeals: tuple[str, ...] = (),
    transfers: tuple[str, ...] = (),
) -> CorpusRecord:
    return CorpusRecord(
        entry_cid=_sha256(f"entry-{code}-{section}", prefixed=True),
        legal_id=(f"state:{code}:{code_family}:1:{section};edition=2026-official"),
        source_cid=_sha256(f"source-{code}-{section}", prefixed=True),
        jurisdiction=code,
        code_family=code_family,
        section=section,
        admission_status=AdmissionStatus.ADMITTED,
        admission_reason="verified official full-frontier acquisition",
        release_point=RELEASE_POINT,
        source_checksum=_sha256(f"snapshot-{code}"),
        verification_result=VerificationResult.VERIFIED,
        acquisition_time="2026-08-24T00:00:00Z",
        official_source_url=f"https://legislature.{code.lower()}.gov/code",
        acquisition_receipt_id=f"scrape-{code.lower()}-sealed",
        parser_version="state-law-parser-v2",
        text=text,
        title="1",
        edition_as_of="2026-official",
        observed_at="2026-08-24T00:00:00Z",
        public_laws=public_laws,
        cites=cites,
        amends=amends,
        repeals=repeals,
        transfers=transfers,
    )


def _receipt(code: str, row_count: int) -> SourceReceiptRecord:
    url = f"https://legislature.{code.lower()}.gov/code"
    checksum = _sha256(f"snapshot-{code}")
    return SourceReceiptRecord(
        receipt_id=f"scrape-{code.lower()}-sealed",
        jurisdiction=code,
        official_source_url=url,
        release_point=RELEASE_POINT,
        observation_time="2026-08-24T00:00:00Z",
        source_authority_class=SourceAuthorityClass.OFFICIAL,
        source_checksum=checksum,
        verification_result=VerificationResult.VERIFIED,
        discovered=row_count,
        fetched=row_count,
        excluded=0,
        quarantined=0,
        failed_final=0,
        frontier_closed=True,
        relative_path=f"receipts/scrape/{code.lower()}.json",
        start_urls=(url,),
        content_hashes=(checksum,),
        payload={
            "adapter_input_row_count": row_count,
            "admission_eligible": True,
            "qualification_reasons": [],
            "reported_canonical_row_count": row_count,
        },
    )


def _layout(tmp_path: Path) -> StateLawsStreamingCorpusPhysicalLayout:
    records = [
        _record(
            "AL",
            "1",
            "See § 2 and § 999. Compare Cal. Penal Code § 187. "
            "This enactment follows Pub. L. 112-29.",
            public_laws=("Pub. L. 117-58",),
            cites=("state:AL:code:1:2;edition=2026-official",),
            amends=("state:AL:code:1:2;edition=2026-official",),
            repeals=("state:AL:code:1:2;edition=2026-official",),
            transfers=("state:AL:code:1:2;edition=2026-official",),
        ),
        _record("AL", "2", "Section two supplies the controlling rule."),
        _record("AK", "1", "Alaska section one has independent provenance."),
        _record(
            "CA",
            "187",
            "California section 187 supplies the cross-state rule.",
            code_family="penal-code",
        ),
    ]
    return write_state_laws_corpus_physical_layout_from_iterable(
        iter(reversed(records)),
        source_receipts=[_receipt("AK", 1), _receipt("AL", 2), _receipt("CA", 1)],
        output_dir=tmp_path / "release",
        max_rows_per_shard=1,
        max_records_in_memory=2,
    )


def _graph_rows(layout: StateLawsStreamingCorpusPhysicalLayout) -> list[Any]:
    rows: list[Any] = []
    for descriptor in layout.data_descriptors:
        for value in pq.read_table(
            Path(layout.output_dir) / descriptor.relative_path
        ).to_pylist():
            rows.append(graph_corpus_row_from_parent_mapping(value))
    return rows


def test_disk_backed_projection_has_exact_materialized_ontology_parity(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    expected = StateLawsGraphProjector().project(_graph_rows(layout))

    stage = project_state_laws_streaming_graph_from_corpus(
        layout,
        tmp_path / "projection",
        max_parent_rows_per_batch=1,
    )
    actual_nodes = tuple(stage.iter_nodes())
    actual_edges = tuple(stage.iter_edges())

    assert stage.production_ready is True
    assert stage.corpus_row_count == 4
    assert stage.max_parent_rows_per_batch == 1
    assert stage.max_projected_edges_per_parent > 0
    assert {item.node_cid: item.to_dict() for item in actual_nodes} == {
        item.node_cid: item.to_dict() for item in expected.nodes
    }
    assert {item.edge_cid: item.to_dict() for item in actual_edges} == {
        item.edge_cid: item.to_dict() for item in expected.edges
    }
    assert any(item.edge_type is GraphEdgeType.CITES for item in actual_edges)
    assert any(
        item.edge_type is GraphEdgeType.CITES_UNRESOLVED for item in actual_edges
    )
    assert all(isinstance(item, StateLawsGraphNode) for item in actual_nodes)
    assert all(isinstance(item, StateLawsGraphEdge) for item in actual_edges)
    explicit_edges = [
        item for item in actual_edges if item.payload.get("origin") == "explicit_field"
    ]
    assert {
        GraphEdgeType.CITES,
        GraphEdgeType.CODIFIES,
        GraphEdgeType.AMENDS,
        GraphEdgeType.REPEALS,
        GraphEdgeType.TRANSFERS,
    } <= {item.edge_type for item in explicit_edges}


def test_parent_parquet_bridge_preserves_explicit_relation_arrays_exactly(
    tmp_path: Path,
) -> None:
    rows = _graph_rows(_layout(tmp_path))
    relation_row = next(
        row for row in rows if row.legal_id.startswith("state:AL:code:1:1;")
    )

    assert relation_row.public_laws == ("Pub. L. 117-58",)
    assert relation_row.cites == ("state:AL:code:1:2;edition=2026-official",)
    assert relation_row.amends == ("state:AL:code:1:2;edition=2026-official",)
    assert relation_row.repeals == ("state:AL:code:1:2;edition=2026-official",)
    assert relation_row.transfers == ("state:AL:code:1:2;edition=2026-official",)


def test_parent_bridge_keeps_pre_extension_rows_backward_compatible() -> None:
    payload = _record("AL", "1", "An older canonical parent row.").to_dict()
    for field_name in (
        "public_laws",
        "cites",
        "amends",
        "repeals",
        "transfers",
    ):
        payload.pop(field_name)

    row = graph_corpus_row_from_parent_mapping(payload)

    assert (row.public_laws, row.cites, row.amends, row.repeals, row.transfers) == (
        (),
        (),
        (),
        (),
        (),
    )


def test_projection_streams_are_one_shot_and_registry_does_not_store_corpus_text(
    tmp_path: Path,
) -> None:
    stage = project_state_laws_streaming_graph_from_corpus(
        _layout(tmp_path),
        tmp_path / "projection",
        max_parent_rows_per_batch=2,
    )

    nodes = stage.iter_nodes()
    edges = stage.iter_edges()
    assert len(tuple(nodes)) == stage.node_count
    assert len(tuple(edges)) == stage.edge_count
    with pytest.raises(StateLawsStreamingGraphProjectionError, match="one-shot"):
        stage.iter_nodes()
    with pytest.raises(StateLawsStreamingGraphProjectionError, match="one-shot"):
        stage.iter_edges()

    with sqlite3.connect(stage.database_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(legal_ids)")
        }
    assert {"edges", "legal_ids", "locators", "metadata", "nodes"} <= tables
    assert "text" not in columns
    assert stage.to_dict()["shared_graph_writer_reused"] is True
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert PERFORMS_NETWORK_IO is False


def test_projection_reuses_helpers_without_calling_materialized_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(tmp_path)

    def forbidden_materialization(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("full-corpus StateLawsGraphProjector.project was called")

    monkeypatch.setattr(StateLawsGraphProjector, "project", forbidden_materialization)
    stage = project_state_laws_streaming_graph_from_corpus(
        layout,
        tmp_path / "projection",
    )
    assert stage.production_ready is True
    assert stage.node_count > layout.row_count
    assert stage.edge_count > layout.row_count


def test_projection_streams_feed_the_shared_physical_writer_directly(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    graph_rows = _graph_rows(layout)
    bm25 = write_state_laws_bm25_physical_layout_from_iterable(
        (
            {
                "body": row.text,
                "chunk_cid": _sha256(f"chunk-{position}", prefixed=True),
                "disposition": "admitted",
                "entry_cid": row.entry_cid,
                "heading": row.legal_id,
                "jurisdiction_code": row.jurisdiction_code,
                "legal_id": row.legal_id,
                "section": row.section,
                "title": row.title,
            }
            for position, row in enumerate(graph_rows)
        ),
        tmp_path / "bm25",
        config=fixture_bm25_config(
            max_records_in_memory=2,
            max_rows_per_shard=2,
            postings_per_cell=2,
        ),
    )
    stage = project_state_laws_streaming_graph_from_corpus(
        layout,
        tmp_path / "projection",
        max_parent_rows_per_batch=1,
    )

    physical = write_state_laws_streaming_graph_layout(
        stage.iter_nodes(),
        stage.iter_edges(),
        tmp_path / "graph",
        bm25=bm25,
        config=StreamingGraphConfig(
            max_rows_per_shard=2,
            max_pointers_per_page=2,
            max_pointers_per_shard=4,
            max_records_in_memory=2,
        ),
    )

    assert physical.production_ready is True
    assert physical.counts["nodes"] == stage.node_count
    assert physical.counts["edges"] == stage.edge_count


def test_projection_rejects_tampered_parent_shard_before_replay(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    shard = Path(layout.output_dir) / layout.data_descriptors[0].relative_path
    shard.write_bytes(b"tampered")

    with pytest.raises(Exception, match="descriptor failed"):
        project_state_laws_streaming_graph_from_corpus(
            layout,
            tmp_path / "projection",
        )


def test_projection_refuses_to_overwrite_an_existing_work_stage(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    target = tmp_path / "projection"
    target.mkdir()

    with pytest.raises(StateLawsStreamingGraphProjectionError, match="already exists"):
        project_state_laws_streaming_graph_from_corpus(layout, target)
