"""Shared GraphRAG engine: SkillCenter locators + patent term graph + nested BM25."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import write_zstd_parquet
from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import BM25LayoutConfig, fts5_idf
from ipfs_datasets_py.retrieval.hf_graphrag.engine import (
    CONTAINS_TERM_EDGE,
    PRIMARY_KEY,
    assign_document_identities,
    build_contains_term_graph,
    build_digest_manifest,
    convert_json_routing_to_parquet,
    dataset_card_configs,
    edge_establishes_legal_authority,
    nest_exploded_postings,
    retrieval_method_for_edge_type,
    write_standard_compact_indexes,
)


def test_sha256_key_to_cidv1_rewrites_hex_and_prefixed_keys() -> None:
    from ipfs_datasets_py.retrieval.hf_graphrag.engine import (
        is_cidv1_key,
        sha256_key_to_cidv1,
    )

    digest = "ab" * 32
    cid = sha256_key_to_cidv1(digest)
    assert is_cidv1_key(cid)
    assert sha256_key_to_cidv1("sha256:" + digest) == cid
    assert sha256_key_to_cidv1(cid) == cid
    suffixed = sha256_key_to_cidv1("sha256:" + digest + ":00000000")
    assert suffixed.startswith(cid) and suffixed.endswith(":00000000")


def test_assign_document_identities_coerces_hex_entry_cid() -> None:
    digest = "cd" * 32
    rows = assign_document_identities([{"legal_id": "oul:1", "entry_cid": digest}])
    from ipfs_datasets_py.retrieval.hf_graphrag.engine import is_cidv1_key

    assert is_cidv1_key(rows[0]["entry_cid"])


def test_assign_document_identities_from_content_sha256() -> None:
    digest = "ab" * 32
    rows = assign_document_identities(
        [{"legal_id": "fr:1", "content_sha256": digest, "title": "Notice"}]
    )
    assert rows[0]["document_index"] == 0
    assert rows[0][PRIMARY_KEY].startswith("bafkrei")
    assert rows[0]["legal_id"] == "fr:1"


def test_nest_exploded_postings_skips_rows_without_document_index() -> None:
    from ipfs_datasets_py.retrieval.hf_graphrag.engine import nest_exploded_postings

    cells = nest_exploded_postings(
        [
            {"term": "(1)", "document_indices": None},
            {"term": "(1)", "document_index": 3, "tf": 2},
        ],
        document_count=4,
        document_lengths={3: 8},
    )
    assert cells[0]["document_indices"] == [3]


def test_nest_exploded_postings_flattens_singleton_nested_cells() -> None:
    from ipfs_datasets_py.retrieval.hf_graphrag.engine import nest_exploded_postings

    cells = nest_exploded_postings(
        [
            {"term": "(1)", "document_indices": [0], "body_frequencies": [2]},
            {"term": "(1)", "document_indices": [1], "body_frequencies": [1]},
        ],
        document_count=2,
        document_lengths={0: 10, 1: 4},
    )
    assert len(cells) == 1
    assert cells[0]["document_indices"] == [0, 1]
    assert cells[0]["body_frequencies"] == [2, 1]


def test_nest_exploded_postings_builds_pointer_cells() -> None:
    hits = [
        {"term": "foia", "document_index": 0, "tf": 3},
        {"term": "foia", "document_index": 1, "tf": 1},
        {"term": "agency", "document_index": 0, "title_tf": 1, "body_tf": 2},
    ]
    cells = nest_exploded_postings(
        hits, document_count=2, document_lengths={0: 10, 1: 4}
    )
    by_term = {cell["term"]: cell for cell in cells}
    assert by_term["foia"]["document_indices"] == [0, 1]
    assert by_term["foia"]["body_frequencies"] == [3, 1]
    assert by_term["agency"]["title_frequencies"] == [1]
    assert by_term["foia"]["idf"] == fts5_idf(2, 2)
    assert len(by_term["foia"]["document_indices"]) <= 4096


def test_consumer_tokenizer_is_admitted() -> None:
    config = BM25LayoutConfig(tokenizer="uscode-bm25-tokenizer/v1")
    assert config.tokenizer == "uscode-bm25-tokenizer/v1"


def test_contains_term_graph_and_authority_split() -> None:
    nodes, edges = build_contains_term_graph(
        {"foia": [("bafkreidocaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 3.0)]}
    )
    assert nodes[0].node_type == "bm25_term"
    assert nodes[0].label == "foia"
    assert edges[0].edge_type == CONTAINS_TERM_EDGE
    assert edges[0].retrieval_method == "bm25"
    assert retrieval_method_for_edge_type("CITES") == "graph"
    assert retrieval_method_for_edge_type("BM25_NEIGHBOR_OF") == "bm25"
    assert retrieval_method_for_edge_type("EMBEDDING_NEIGHBOR_OF") == "embedding"
    assert edge_establishes_legal_authority("CITES") is True
    assert edge_establishes_legal_authority(CONTAINS_TERM_EDGE) is False


def test_dataset_card_and_digest_manifest() -> None:
    configs = dataset_card_configs()
    names = {item["config_name"] for item in configs}
    assert "bm25_keyword_index" in names
    assert "graph_outgoing_adjacency_index" in names
    manifest = build_digest_manifest(
        dataset_repo_id="justicedao/example",
        schema_version="example/v1",
        counts={"corpus_rows": 2},
        bm25={"k1": 1.2, "tokenizer": "uscode-bm25-tokenizer/v1"},
    )
    assert manifest["primary_key"] == PRIMARY_KEY
    assert "viewer_configs" in manifest


def test_write_hub_search_pack_emits_skill_and_scripts(tmp_path: Path) -> None:
    from ipfs_datasets_py.retrieval.hf_graphrag.engine import write_hub_search_pack

    copied = write_hub_search_pack(
        tmp_path,
        repo_id="justicedao/example-graphrag",
        pretty_name="Example GraphRAG",
        domain_notes="Similarity edges cannot establish legal authority.",
    )
    skill = tmp_path / copied["skill"]
    assert (skill / "SKILL.md").is_file()
    text = (skill / "SKILL.md").read_text()
    assert "name: query-hf-graphrag" in text
    assert "justicedao/example-graphrag" in text
    assert (skill / "agents" / "openai.yaml").is_file()
    assert (skill / "references" / "schema.md").is_file()
    assert (tmp_path / "scripts" / "query_hf_graphrag.py").is_file()
    wrapper = (skill / "scripts" / "query_hf_graphrag.py").read_text()
    assert "runpy.run_path" in wrapper


def test_write_standard_compact_indexes_and_json_upgrade(tmp_path: Path) -> None:
    corpus = tmp_path / "data" / "corpus"
    corpus.mkdir(parents=True)
    write_zstd_parquet(
        corpus / "part-000000.parquet",
        [
            {"entry_cid": "bafkreiaaa", "document_index": 0},
            {"entry_cid": "bafkreibbb", "document_index": 1},
        ],
    )
    written = write_standard_compact_indexes(tmp_path, families=("corpus",))
    assert written["corpus"].row_count == 1
    table = pq.read_table(tmp_path / "indexes" / "corpus_chunks.parquet")
    assert table.column("first_key")[0].as_py() == "bafkreiaaa"
    assert table.column("sha256")[0].as_py()
    assert str(table.column("cid")[0].as_py()).startswith("bafkrei")

    adj = tmp_path / "data" / "graph" / "adjacency" / "outgoing"
    adj.mkdir(parents=True)
    write_zstd_parquet(
        adj / "part-000000.parquet",
        [{"node_cid": "bafkreinode", "neighbor_count": 1}],
    )
    routing = tmp_path / "indexes" / "graph_outgoing_adjacency.json"
    routing.parent.mkdir(parents=True, exist_ok=True)
    routing.write_text(
        '{"routing":[{"first_key":"bafkreinode","last_key":"bafkreinode",'
        '"relative_path":"data/graph/adjacency/outgoing/part-000000.parquet",'
        '"row_count":1,"shard_id":0}]}\n',
        encoding="utf-8",
    )
    converted = convert_json_routing_to_parquet(
        tmp_path,
        "indexes/graph_outgoing_adjacency.json",
        index_path="indexes/graph_outgoing_adjacency.parquet",
        kind="graph_outgoing_adjacency",
        key_fields=("node_cid",),
    )
    assert converted.row_count == 1
    assert (tmp_path / "indexes" / "graph_outgoing_adjacency.parquet").is_file()


def test_unwrap_exploded_term_entry_cid_posting(tmp_path: Path) -> None:
    import json

    from ipfs_datasets_py.retrieval.hf_graphrag.engine import is_cidv1_key
    from ipfs_datasets_py.retrieval.hf_graphrag.upgrade import unwrap_sha256_family_file

    digest = "ab" * 32
    from ipfs_datasets_py.retrieval.hf_graphrag.engine import sha256_key_to_cidv1

    cid = sha256_key_to_cidv1(digest)
    src = tmp_path / "in.parquet"
    write_zstd_parquet(
        src,
        [
            {
                "record_json": json.dumps(
                    {"entry_cid": digest, "family": "bm25_postings", "term": "(1)", "tf": 2}
                )
            }
        ],
    )
    dest = tmp_path / "out.parquet"
    unwrap_sha256_family_file(
        src, dest, family="bm25_postings", cid_to_index={cid: 7}
    )
    row = pq.read_table(dest).to_pylist()[0]
    assert row["term"] == "(1)"
    assert row["document_index"] == 7
    assert row["tf"] == 2
    assert is_cidv1_key(row["entry_cid"])


def test_unwrap_sha256_posting_emits_nested_cid_cells(tmp_path: Path) -> None:
    import json

    from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import write_zstd_parquet
    from ipfs_datasets_py.retrieval.hf_graphrag.engine import is_cidv1_key, sha256_key_to_cidv1
    from ipfs_datasets_py.retrieval.hf_graphrag.upgrade import unwrap_sha256_family_file

    digest = "ab" * 32
    payload = {
        "term": "foia",
        "idf": 1.2,
        "document_frequency": 1,
        "cells": [
            {
                "pointer_count": 1,
                "pointers": [
                    {
                        "document_index": 0,
                        "entry_cid": digest,
                        "field_tf": {"body": 2, "title": 1},
                        "tf": 3,
                    }
                ],
            }
        ],
    }
    src = tmp_path / "in.parquet"
    write_zstd_parquet(src, [{"record_json": json.dumps(payload)}])
    dest = tmp_path / "out.parquet"
    unwrap_sha256_family_file(src, dest, family="bm25_postings", lengths={0: 10})
    import pyarrow.parquet as pq

    row = pq.read_table(dest).to_pylist()[0]
    assert row["term"] == "foia"
    assert row["document_indices"] == [0]
    assert row["body_frequencies"] == [2]
    assert is_cidv1_key(sha256_key_to_cidv1(digest))


def test_graphrag_parallel_exports_pack_repair_and_pool() -> None:
    from ipfs_datasets_py.processors.legal_data import graphrag_parallel as gp

    assert "bm25_postings" in gp.RANGE_ROUTED_FAMILIES
    plan = gp.graphrag_process_pool_plan()
    assert plan.workers >= 1
    assert gp.pack_range_routed_family is gp.rewrite_range_routed_family or callable(
        gp.pack_range_routed_family
    )
    assert callable(gp.repair_graphrag_range_routing)
    assert callable(gp.write_term_sorted_posting_shards)
    assert callable(gp.covering_locator_rows)


def test_manifest_aliases_refresh_keyword_shard_digest(tmp_path: Path) -> None:
    import json

    from ipfs_datasets_py.retrieval.hf_graphrag.engine import CompactIndexWriteResult
    from ipfs_datasets_py.retrieval.hf_graphrag.repair import _update_manifest_indexes

    stale = "aa" * 32
    fresh = "bb" * 32
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "indexes": {
                    "bm25_keyword_shards": {
                        "relative_path": "indexes/bm25_keyword_shards.parquet",
                        "sha256": stale,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _update_manifest_indexes(
        tmp_path,
        {
            "bm25_postings": CompactIndexWriteResult(
                index_path="indexes/bm25_keyword_shards.parquet",
                row_count=2,
                shard_count=1,
                descriptor={
                    "relative_path": "indexes/bm25_keyword_shards.parquet",
                    "sha256": fresh,
                },
                hierarchical=False,
            )
        },
    )
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert payload["indexes"]["bm25_keyword_shards"]["sha256"] == fresh
    assert payload["indexes"]["bm25_postings"]["sha256"] == fresh


def test_state_laws_overlay_keeps_hive_partitions_and_dumps() -> None:
    from ipfs_datasets_py.retrieval.hf_graphrag.hub_overlay import (
        STATE_LAWS_KEEP_PREFIXES,
        _keep_remote,
        _overlay_extra,
    )

    keep = STATE_LAWS_KEEP_PREFIXES
    assert _keep_remote("data/bm25/documents/jurisdiction=AK/part-000000.parquet", keep)
    assert _keep_remote("STATE-AK.parquet", keep)
    assert _keep_remote("source_recovery/foo.parquet", keep)
    assert _keep_remote("data/vectors/ids.parquet", keep)
    assert not _keep_remote("data/graph/adjacency/in/part-000000.parquet", keep)
    assert _overlay_extra("data/graph/adjacency/in/part-000000.parquet")


def test_release_needs_sha256_upgrade_detects_hex_and_skips_cidv1(tmp_path: Path) -> None:
    from ipfs_datasets_py.retrieval.hf_graphrag.upgrade import (
        diagnose_release_identities,
        release_needs_sha256_upgrade,
    )

    corpus = tmp_path / "data" / "corpus"
    corpus.mkdir(parents=True)
    write_zstd_parquet(
        corpus / "part-000000.parquet",
        [{"entry_cid": "ab" * 32, "legal_id": "oul:1"}],
    )
    report = diagnose_release_identities(tmp_path)
    assert report["corpus"]["sha256_or_hex"] == 1
    assert release_needs_sha256_upgrade(tmp_path) is True
    write_zstd_parquet(
        corpus / "part-000000.parquet",
        [{"entry_cid": "bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "legal_id": "oul:1"}],
    )
    assert release_needs_sha256_upgrade(tmp_path) is False


def test_empty_adjacency_shard_is_skipped(tmp_path: Path) -> None:
    incoming = tmp_path / "data" / "graph" / "adjacency" / "incoming"
    incoming.mkdir(parents=True)
    write_zstd_parquet(incoming / "part-000000.parquet", [])
    written = write_standard_compact_indexes(
        tmp_path, families=("graph_incoming_adjacency",)
    )
    assert "graph_incoming_adjacency" not in written


def test_catalog_family_index_uses_minmax_when_unsorted(tmp_path: Path) -> None:
    """graph_edges are walked via adjacency, not range-routed.

    Compact locators still need first_key <= last_key. Unsorted shards
    must use the min/max span rather than first/last row.
    """

    edges = tmp_path / "data" / "graph" / "edges"
    edges.mkdir(parents=True)
    write_zstd_parquet(
        edges / "part-000000.parquet",
        [
            {"edge_cid": "bafkreibbb", "src": "a"},
            {"edge_cid": "bafkreiaaa", "src": "b"},
        ],
    )
    written = write_standard_compact_indexes(tmp_path, families=("graph_edges",))
    assert written["graph_edges"].row_count == 1
    table = pq.read_table(tmp_path / "indexes" / "graph_edge_chunks.parquet")
    first = table.column("first_key")[0].as_py()
    last = table.column("last_key")[0].as_py()
    assert first == "bafkreiaaa"
    assert last == "bafkreibbb"
    assert first <= last


def test_vector_index_skips_ids_sidecar(tmp_path: Path) -> None:
    vec = tmp_path / "data" / "vectors"
    vec.mkdir(parents=True)
    write_zstd_parquet(
        vec / "centroid-000000-part-000000.parquet",
        [{"entry_cid": "bafkreiaaa", "document_index": 0}],
    )
    write_zstd_parquet(
        vec / "ids.parquet",
        [{"row": 0, "legal_id": "fr:1"}],
    )
    written = write_standard_compact_indexes(tmp_path, families=("vectors",))
    assert written["vectors"].row_count == 1
    table = pq.read_table(tmp_path / "indexes" / "vector_chunks.parquet")
    assert table.num_rows == 1
    assert "ids.parquet" not in table.column("relative_path").to_pylist()[0]
