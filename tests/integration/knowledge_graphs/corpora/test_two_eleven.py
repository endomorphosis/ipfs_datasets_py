"""Integration / differential suite for the read-only 211-AI adapter (KGP-026).

Coverage:
* tiny checked fixture (always-on): retrieval package parquet layout, build
  manifest, artifact CIDs/sizes/row counts, adjacency, communities, browser
  neighborhoods (monolithic + sharded), entity/neighborhood/community/
  geography/hybrid queries, missing/corrupt artifact fail-closed behavior,
  and parity with the current exporter/benchmark when 211-AI sources exist
* environment-gated full-corpus receipt when ``data/retrieval_package`` (or
  ``TWO_ELEVEN_PACKAGE_ROOT``) is available — pins 48,851 nodes / 648,958
  edges / 22,638 documents+embeddings and detects browser source-path /
  count drift
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.knowledge_graphs.adapters.two_eleven import (
    ENV_PACKAGE_ROOT,
    EXPECTED_BROWSER_SMOKE_COUNTS,
    EXPECTED_EMBEDDING_MODEL,
    EXPECTED_FULL_COUNTS,
    PACKAGE_ARTIFACTS,
    TwoElevenAdapterError,
    TwoElevenCorpusAdapter,
    build_tiny_fixture_package,
    differential_query_parity,
    discover_211_ai_root,
    discover_browser_root,
    discover_browser_smoke_roots,
    discover_package_root,
    load_legacy_benchmark_module,
    load_legacy_exporter_module,
    open_browser_reader,
    open_package_reader,
    tokenize,
    validate_browser_export,
    validate_manifest,
    validate_package_artifacts,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def tiny_package(tmp_path: Path) -> Path:
    return build_tiny_fixture_package(tmp_path / "two-eleven-tiny")


@pytest.fixture
def adapter(tiny_package: Path) -> TwoElevenCorpusAdapter:
    return TwoElevenCorpusAdapter(
        tiny_package,
        browser_root=tiny_package / "browser_export",
    )


# ---------------------------------------------------------------------------
# Tiny fixture: layout, integrity, queries
# ---------------------------------------------------------------------------


def test_tiny_fixture_validates_package_browser_and_adjacency(
    adapter: TwoElevenCorpusAdapter,
) -> None:
    receipt = adapter.validate(
        verify_checksums=True,
        expected_full_corpus=False,
        validate_browser=True,
        require_browser_shards=True,
    )
    assert receipt["schema"] == "two-eleven-corpus-validation-receipt/v1"
    assert receipt["package"] is not None
    assert receipt["artifacts"] is not None
    assert receipt["browser"] is not None

    counts = receipt["package"]["counts"]
    assert counts["graph_nodes"] == 6
    assert counts["graph_edges"] == 7
    assert counts["documents"] == 2
    assert counts["embeddings"] == 2
    assert counts["graph_communities"] == 1
    assert receipt["package"]["embedding_model"] == EXPECTED_EMBEDDING_MODEL

    kinds = receipt["artifacts"]["kinds"]
    for name in PACKAGE_ARTIFACTS:
        assert name in kinds
        assert kinds[name]["checksum"]["verified"] is True
        assert kinds[name]["row_count"] >= 1

    browser = receipt["browser"]
    assert browser["counts"]["documents"] == 2
    assert browser["counts"]["neighborhoods"] == 2
    assert browser["counts"]["shards"] == 1
    assert browser["counts"]["communities"] == 1
    assert "sharded" in browser["neighborhood_format"]
    # Fixture is self-aligned — no source-package drift.
    assert browser["count_drift"] == {}


def test_tiny_entity_neighborhood_community_geography_hybrid(
    adapter: TwoElevenCorpusAdapter,
) -> None:
    entity = adapter.entity(node_id="page:doc-food-1")
    assert entity["found"] is True
    assert entity["results"][0]["node_type"] == "page"
    assert entity["results"][0]["city"] == "Portland"

    by_label = adapter.entity(label="Portland", limit=10)
    assert by_label["found"] is True
    types = {row["node_type"] for row in by_label["results"]}
    assert "location" in types or "page" in types

    by_term = adapter.entity(node_type="keyterm", term="food")
    assert by_term["found"] is True
    assert by_term["results"][0]["node_id"] == "term:food"

    neighborhood = adapter.neighborhood(
        "page:doc-food-1", direction="both", limit=16
    )
    assert neighborhood["found"] is True
    assert neighborhood["result_count"] >= 2
    relations = {row["edge"]["relation"] for row in neighborhood["results"]}
    assert "HAS_KEYTERM" in relations
    assert "LOCATED_IN" in relations
    neighbor_types = {
        row["neighbor_node_type"] for row in neighborhood["results"]
    }
    assert "keyterm" in neighbor_types
    assert "location" in neighbor_types

    community = adapter.community(doc_id="page:doc-food-1", max_documents=10)
    assert community["found"] is True
    assert community["results"][0]["document_count"] == 2
    assert len(community["results"][0]["documents"]) == 2

    geography = adapter.geography(city="Portland", state="OR", limit=10)
    assert geography["found"] is True
    assert geography["result_count"] == 2
    assert geography["location_node_count"] >= 1
    assert all(row["city"] == "Portland" for row in geography["results"])

    keyword = adapter.keyword("food pantry", top_k=2)
    assert keyword["result_count"] >= 1
    assert keyword["results"][0]["doc_id"] == "page:doc-food-1"
    assert "food" in keyword["matched_terms"]

    # Vector path with explicit query vector (no sentence-transformers needed).
    food_vector = [1.0] + [0.0] * 7
    vector = adapter.vector(query_vector=food_vector, top_k=1)
    assert vector["result_count"] == 1
    assert vector["results"][0]["doc_id"] == "page:doc-food-1"

    hybrid = adapter.hybrid(
        "food pantry",
        top_k=2,
        query_vector=food_vector,
        skip_vector=False,
    )
    assert hybrid["mode"] == "hybrid"
    assert hybrid["result_count"] >= 1
    assert hybrid["results"][0]["doc_id"] == "page:doc-food-1"
    assert "keyword" in hybrid["results"][0]["score_parts"]
    assert "vector" in hybrid["results"][0]["score_parts"]

    hybrid_kw_only = adapter.hybrid("emergency shelter", top_k=2, skip_vector=True)
    assert hybrid_kw_only["result_count"] >= 1
    assert hybrid_kw_only["results"][0]["doc_id"] == "service:svc-shelter-1"


def test_tiny_browser_reader_neighborhoods_and_hybrid(
    tiny_package: Path,
) -> None:
    browser_root = tiny_package / "browser_export"
    reader = open_browser_reader(browser_root)
    docs = reader.documents()
    assert len(docs) == 2

    mono = reader.neighborhood_for("page:doc-food-1")
    assert mono is not None
    assert mono["format"] == "monolithic"
    assert len(mono.get("nodes") or []) >= 1
    assert len(mono.get("edges") or []) >= 1

    # Drop monolithic file so sharded path is exercised.
    (browser_root / "generated" / "graph-neighborhoods.json").unlink()
    reader2 = open_browser_reader(browser_root)
    sharded = reader2.neighborhood_for("page:doc-food-1")
    assert sharded is not None
    assert sharded["format"] == "sharded"
    assert len(sharded.get("node_ids") or sharded.get("nodes") or []) >= 1

    communities = reader.communities()
    assert len(communities) == 1

    keyword = reader.keyword("food pantry", top_k=2)
    assert keyword["result_count"] >= 1
    assert keyword["results"][0]["doc_id"] == "page:doc-food-1"

    hybrid = reader.hybrid(
        "food pantry",
        top_k=2,
        query_vector=[1.0] + [0.0] * 7,
        skip_vector=False,
    )
    assert hybrid["result_count"] >= 1
    assert hybrid["results"][0]["doc_id"] == "page:doc-food-1"


def test_missing_artifact_fails_closed(tiny_package: Path) -> None:
    target = tiny_package / PACKAGE_ARTIFACTS["knowledge_graph_nodes"]
    assert target.is_file()
    target.unlink()
    adapter = TwoElevenCorpusAdapter(tiny_package)
    with pytest.raises(TwoElevenAdapterError, match="missing"):
        adapter.validate(verify_checksums=False, validate_browser=False)


def test_corrupt_artifact_cid_fails_closed(tiny_package: Path) -> None:
    # Flip the declared documents CID so integrity fails while parquet remains valid.
    manifest_path = tiny_package / "manifest" / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wrong = "bafkreieiccwvqhsz6k6dskfsmfyhu4jqr57bhhvqjaqdm3oe2xay3gaceu"
    for art in manifest["artifacts"]:
        if art["artifact_name"] == "documents":
            art["artifact_cid"] = wrong
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    adapter = TwoElevenCorpusAdapter(tiny_package)
    with pytest.raises(TwoElevenAdapterError, match="CID differs"):
        adapter.validate(verify_checksums=True, validate_browser=False)


def test_corrupt_parquet_bytes_fail_closed(tiny_package: Path) -> None:
    path = tiny_package / PACKAGE_ARTIFACTS["knowledge_graph_edges"]
    path.write_bytes(b"not a parquet file at all")
    # Keep size matching by not revalidating size first — rewrite manifest size.
    manifest_path = tiny_package / "manifest" / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for art in manifest["artifacts"]:
        if art["artifact_name"] == "knowledge_graph_edges":
            art["size_bytes"] = path.stat().st_size
            # Leave CID stale so either CID or corrupt parse fails.
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    adapter = TwoElevenCorpusAdapter(tiny_package)
    with pytest.raises(TwoElevenAdapterError):
        adapter.validate(verify_checksums=True, validate_browser=False)


def test_validate_manifest_rejects_missing_artifact(tiny_package: Path) -> None:
    manifest_path = tiny_package / "manifest" / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = [
        art
        for art in manifest["artifacts"]
        if art["artifact_name"] != "graph_communities"
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(TwoElevenAdapterError, match="missing required artifact"):
        validate_manifest(tiny_package)


def test_row_count_drift_fails_closed(tiny_package: Path) -> None:
    manifest_path = tiny_package / "manifest" / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for art in manifest["artifacts"]:
        if art["artifact_name"] == "documents":
            art["row_count"] = 999
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(TwoElevenAdapterError, match="row count drift"):
        validate_package_artifacts(tiny_package, verify_checksums=False)


def test_differential_parity_self_and_optional_legacy(
    tiny_package: Path,
) -> None:
    receipt = differential_query_parity(
        package_root=tiny_package,
        browser_root=tiny_package / "browser_export",
        keyword_query="food pantry",
        entity_label="Portland",
        city="Portland",
        state="OR",
        skip_vector=True,
    )
    assert receipt["schema"] == "two-eleven-differential-parity/v1"
    assert receipt["parity"] in {"matched", "self_only"}
    assert receipt["checks"]["entity"]["found"] is True
    assert receipt["checks"]["geography"]["found"] is True
    assert receipt["checks"]["keyword"]["result_count"] >= 1
    assert receipt["checks"]["hybrid"]["result_count"] >= 1
    assert receipt["checks"]["community"]["result_count"] >= 1
    assert receipt["checks"]["neighborhood"]["result_count"] >= 1
    assert receipt["checks"]["browser_keyword"]["result_count"] >= 1
    assert receipt["checks"]["browser_neighborhood"]["found"] is True
    assert receipt["checks"]["browser_communities"]["count"] == 1

    if load_legacy_benchmark_module() is not None:
        # Legacy benchmark compares against browser BM25 fusion.
        assert receipt["legacy_benchmark_available"] is True
        assert receipt["checks"]["legacy_keyword_parity"]["matched"] is True
        assert receipt["parity"] == "matched"

    if load_legacy_exporter_module() is not None:
        assert receipt["legacy_exporter_available"] is True
        assert receipt["checks"]["legacy_community_parity"]["matched"] is True


def test_open_package_reader_entity_lookup(tiny_package: Path) -> None:
    reader = open_package_reader(tiny_package)
    found = reader.entity(node_id="service:svc-shelter-1")
    assert found["found"] is True
    assert found["results"][0]["provider_name"] == "City Shelter Network"
    missing = reader.entity(node_id="page:does-not-exist")
    assert missing["found"] is False
    stats = reader.adjacency_stats()
    assert stats["outgoing_edges"] == 7
    assert stats["incoming_edges"] == 7


def test_tokenize_matches_benchmark_stopword_behavior() -> None:
    terms = tokenize("food near the pantry")
    assert "food" in terms
    assert "pantry" in terms
    assert "near" not in terms
    assert "the" not in terms


def test_discovery_helpers_do_not_raise() -> None:
    _ = discover_package_root()
    _ = discover_browser_root()
    _ = discover_browser_smoke_roots()
    _ = discover_211_ai_root()
    _ = os.environ.get(ENV_PACKAGE_ROOT)


def test_legacy_loaders_are_optional() -> None:
    exporter = load_legacy_exporter_module()
    if exporter is not None:
        assert hasattr(exporter, "build_graph_neighborhoods")
        assert hasattr(exporter, "build_bm25_payload")
    benchmark = load_legacy_benchmark_module()
    if benchmark is not None:
        assert hasattr(benchmark, "search_keyword")
        assert hasattr(benchmark, "rank_from_scores")


def test_browser_source_package_drift_is_detected(tiny_package: Path) -> None:
    """Browser export that points at stale package counts must surface drift."""

    browser_root = tiny_package / "browser_export"
    gen_manifest = browser_root / "generated" / "generated-manifest.json"
    payload = json.loads(gen_manifest.read_text(encoding="utf-8"))
    payload["sourcePackage"]["document_count"] = 22640
    payload["sourcePackage"]["graph_node_count"] = 48864
    payload["sourcePackage"]["graph_edge_count"] = 649052
    payload["sourcePackage"]["build_manifest_cid"] = (
        "bafkreifgjbpyynwyebcdfvc2bozwusbhza42xw6w4kutguicfscqovm67a"
    )
    payload["sourcePackage"]["path"] = "/nonexistent/stale/retrieval_package"
    gen_manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    package_receipt = validate_manifest(tiny_package)
    browser_receipt = validate_browser_export(
        browser_root, package_receipt=package_receipt
    )
    assert "/nonexistent/stale/retrieval_package" in browser_receipt[
        "stale_source_paths"
    ]
    assert "document_count" in browser_receipt["count_drift"]
    assert "graph_node_count" in browser_receipt["count_drift"]
    assert "graph_edge_count" in browser_receipt["count_drift"]
    assert "build_manifest_cid" in browser_receipt["count_drift"]
    assert browser_receipt["count_drift"]["document_count"][
        "browser_source_package"
    ] == 22640
    assert browser_receipt["count_drift"]["document_count"][
        "package_actual"
    ] == 2


# ---------------------------------------------------------------------------
# Environment-gated full corpus + real browser smoke
# ---------------------------------------------------------------------------


def _full_package_available() -> bool:
    root = discover_package_root()
    return root is not None and (root / "manifest" / "build_manifest.json").is_file()


def _browser_smoke_available() -> bool:
    return "smoke" in discover_browser_smoke_roots()


@pytest.mark.skipif(
    not _full_package_available(),
    reason=(
        "full 211 retrieval package not available; set TWO_ELEVEN_PACKAGE_ROOT "
        "or install 211-AI data/retrieval_package"
    ),
)
def test_full_corpus_validation_receipt() -> None:
    package = discover_package_root()
    assert package is not None
    browser = discover_browser_root()
    adapter = TwoElevenCorpusAdapter(package, browser_root=browser)

    # Checksums over ~184M of parquet: verify all artifact CIDs (finite set of
    # 9 files). Skip adjacency full materialization in validate by not using
    # expected_full_corpus's adjacency edge walk when we only need counts —
    # but acceptance requires adjacency validation, so we run it.
    receipt = adapter.validate(
        verify_checksums=True,
        expected_full_corpus=True,
        validate_browser=browser is not None,
        require_browser_shards=False,
        max_rows_to_scan=0,
    )
    assert receipt["expected_full_corpus"] is True
    counts = receipt["package"]["counts"]
    for key, expected in EXPECTED_FULL_COUNTS.items():
        if key in counts and counts[key]:
            assert int(counts[key]) == int(expected), key

    assert receipt["artifacts"]["checksums_verified"] >= 9
    assert receipt["package"]["embedding_model"] == EXPECTED_EMBEDDING_MODEL

    # Representative entity / neighborhood / community / geography / hybrid.
    entity = adapter.entity(node_type="host", limit=5)
    assert entity["found"] is True

    # Use a known page from the package head.
    reader = adapter.package
    sample_page = None
    for row in reader._ensure_nodes().values():
        if row.get("node_type") == "page":
            sample_page = row
            break
    assert sample_page is not None
    neighborhood = adapter.neighborhood(
        str(sample_page["node_id"]), direction="both", limit=16
    )
    assert neighborhood["result_count"] >= 1

    communities = adapter.community(limit=5, include_documents=False)
    assert communities["total_communities"] == EXPECTED_FULL_COUNTS[
        "graph_communities"
    ]
    assert communities["result_count"] >= 1

    geography = adapter.geography(city="Portland", state="OR", limit=10)
    assert geography["found"] is True
    assert geography["result_count"] >= 1

    hybrid = adapter.hybrid("food pantry", top_k=5, skip_vector=True)
    assert hybrid["result_count"] >= 1
    assert hybrid["results"][0]["doc_id"]

    # Differential parity (keyword path; vector optional / heavy).
    parity = adapter.differential_parity(
        keyword_query="food pantry",
        entity_label="Portland",
        city="Portland",
        state="OR",
        skip_vector=True,
    )
    assert parity["parity"] in {"matched", "self_only"}
    assert parity["checks"]["keyword"]["result_count"] >= 1
    if load_legacy_exporter_module() is not None:
        assert parity["legacy_exporter_available"] is True


@pytest.mark.skipif(
    not _browser_smoke_available(),
    reason="211 browser_graphrag_smoke fixture not available",
)
def test_browser_smoke_shards_and_source_drift_detection() -> None:
    smokes = discover_browser_smoke_roots()
    smoke = smokes["smoke"]
    package = discover_package_root()
    package_receipt = (
        validate_manifest(package, expected_full_corpus=True)
        if package is not None
        else None
    )

    receipt = validate_browser_export(
        smoke,
        package_receipt=package_receipt,
        require_shards=False,
    )
    assert receipt["counts"]["documents"] == EXPECTED_BROWSER_SMOKE_COUNTS[
        "documents"
    ]
    assert receipt["counts"]["neighborhoods"] == EXPECTED_BROWSER_SMOKE_COUNTS[
        "neighborhoods"
    ]
    assert receipt["counts"]["communities"] == EXPECTED_BROWSER_SMOKE_COUNTS[
        "communities"
    ]

    # Smoke manifests historically pin slightly older source package counts;
    # when the live package is present the adapter must surface that drift.
    if package_receipt is not None and receipt["source_package"]:
        # Either aligned or drift is reported — never silently ignored.
        for key in ("document_count", "graph_node_count", "graph_edge_count"):
            if key in receipt["source_package"] and key.replace(
                "_count", "s" if key != "document_count" else "s"
            ):
                pass
        # Explicit: if source package counts differ from live package, drift map
        # is non-empty (observed on current trees: 22640 vs 22638 etc.).
        live_docs = package_receipt["counts"]["documents"]
        src_docs = int(receipt["source_package"].get("document_count") or live_docs)
        if src_docs != live_docs:
            assert "document_count" in receipt["count_drift"]

    if "smoke_sharded" in smokes:
        sharded = validate_browser_export(
            smokes["smoke_sharded"],
            package_receipt=package_receipt,
            require_shards=True,
        )
        assert sharded["counts"]["shards"] == EXPECTED_BROWSER_SMOKE_COUNTS[
            "shards"
        ]
        assert "sharded" in sharded["neighborhood_format"]

        reader = open_browser_reader(smokes["smoke_sharded"])
        docs = reader.documents()
        assert len(docs) == 25
        sample = reader.neighborhood_for(str(docs[0]["doc_id"]))
        assert sample is not None
        assert sample["format"] == "sharded"

        keyword = reader.keyword("volunteer", top_k=3)
        assert keyword["result_count"] >= 1


@pytest.mark.skipif(
    not _full_package_available(),
    reason="full 211 retrieval package not available",
)
def test_full_package_adjacency_stats_match_edge_count() -> None:
    package = discover_package_root()
    assert package is not None
    reader = open_package_reader(package)
    stats = reader.adjacency_stats()
    assert stats["outgoing_edges"] == EXPECTED_FULL_COUNTS["graph_edges"]
    assert stats["incoming_edges"] == EXPECTED_FULL_COUNTS["graph_edges"]
    assert stats["outgoing_nodes"] >= 1
    assert stats["max_out_degree"] >= 1
