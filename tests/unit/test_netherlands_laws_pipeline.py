from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pytest


MODULES = [
    "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws",
    "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.api",
    "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli",
    "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.operations",
    "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.upload",
    "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders.common",
    "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders.normalized_package",
    "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders.ipfs_package",
    "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders.ipfs_indexes",
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _raw_fixture(raw_dir: Path) -> Path:
    law_rows = [
        {
            "record_type": "law",
            "jurisdiction": "NL",
            "language": "nl",
            "identifier": "BWBRTEST1",
            "law_identifier": "BWBRTEST1",
            "title": "Test Netherlands Law",
            "canonical_title": "Test Netherlands Law",
            "text": "Algemene testwet met bepalingen over documenten en registers.",
            "source_url": "https://wetten.overheid.nl/BWBRTEST1/",
            "document_type": "wet",
            "citation": "Testwet",
            "law_status": "current",
            "is_current": True,
            "valid_from": "2024-01-01",
            "valid_to": "",
            "effective_date": "2024-01-01",
            "retrieved_at": "2026-04-10T00:00:00",
            "status_source": "wetten.overheid.nl/informatie",
            "status_confidence": "high",
            "status_note": "Official status text indicates the law is current",
            "article_count": 2,
            "metadata": {},
        }
    ]
    article_rows = [
        {
            "record_type": "article",
            "law_identifier": "BWBRTEST1",
            "article_identifier": "BWBRTEST1:artikel:1",
            "article_number": "1",
            "citation": "Testwet, Artikel 1",
            "hierarchy_path": ["Artikel 1"],
            "hierarchy_path_text": "Artikel 1",
            "law_status": "current",
            "is_current": True,
            "valid_from": "2024-01-01",
            "valid_to": "",
            "effective_date": "2024-01-01",
            "retrieved_at": "2026-04-10T00:00:00",
            "status_source": "wetten.overheid.nl/informatie",
            "status_confidence": "high",
            "status_note": "Official status text indicates the law is current",
            "text": "Artikel een regelt documenten, registers en openbare toegang.",
        },
        {
            "record_type": "article",
            "law_identifier": "BWBRTEST1",
            "article_identifier": "BWBRTEST1:artikel:2",
            "article_number": "2",
            "citation": "Testwet, Artikel 2",
            "hierarchy_path": ["Artikel 2"],
            "hierarchy_path_text": "Artikel 2",
            "law_status": "current",
            "is_current": True,
            "valid_from": "2024-01-01",
            "valid_to": "",
            "effective_date": "2024-01-01",
            "retrieved_at": "2026-04-10T00:00:00",
            "status_source": "wetten.overheid.nl/informatie",
            "status_confidence": "high",
            "status_note": "Official status text indicates the law is current",
            "text": "Artikel twee regelt bewaring, wijziging en digitale bekendmaking.",
        },
        {
            "record_type": "article",
            "law_identifier": "BWBRTEST1",
            "article_identifier": "BWBRTEST1:artikel:3",
            "article_number": "3",
            "citation": "Testwet, Artikel 3",
            "hierarchy_path": ["Artikel 3"],
            "hierarchy_path_text": "Artikel 3",
            "law_status": "current",
            "is_current": True,
            "valid_from": "2024-01-01",
            "valid_to": "",
            "effective_date": "2024-01-01",
            "retrieved_at": "2026-04-10T00:00:00",
            "status_source": "wetten.overheid.nl/informatie",
            "status_confidence": "high",
            "status_note": "Official status text indicates the law is current",
            "text": "Artikel drie regelt toezicht, bezwaar en administratieve uitvoering.",
        },
    ]
    _write_jsonl(raw_dir / "netherlands_laws_index_latest.jsonl", law_rows)
    _write_jsonl(raw_dir / "netherlands_laws_articles_index_latest.jsonl", article_rows)
    _write_jsonl(raw_dir / "netherlands_laws_search_index_latest.jsonl", [*law_rows, *article_rows])
    (raw_dir / "netherlands_laws_run_metadata_latest.json").write_text(
        json.dumps(
            {
                "max_documents": 1,
                "records_count": 1,
                "article_records_count": 3,
                "search_records_count": 4,
                "law_status_counts": {"current": 1, "historical": 0, "repealed": 0, "superseded": 0, "unknown": 0},
                "current_laws_count": 1,
                "historical_repealed_superseded_laws_count": 0,
                "unknown_status_laws_count": 0,
                "ambiguous_status_laws_count": 0,
            }
        ),
        encoding="utf-8",
    )
    return raw_dir


def _load_script(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_builder_modules_import_correctly():
    for module in MODULES:
        assert importlib.import_module(module)


def test_package_managed_paths_are_used():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws import paths
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.upload import UPLOAD_TARGETS

    assert paths.PACKAGE_RAW_OUTPUT_DIR.is_relative_to(paths.RAW_DATA_DIR)
    assert paths.HF_DATA_DIR.is_relative_to(paths.DATASETS_DIR)
    assert paths.PACKAGE_RAW_OUTPUT_DIR != paths.LEGACY_NL_OUTPUT_DOCS_DIR
    assert paths.HF_DATA_DIR != paths.LEGACY_HF_READY_DIR
    for target in UPLOAD_TARGETS.values():
        assert target.local_dir.is_relative_to(paths.HF_DATA_DIR)


def test_compatibility_wrappers_import_package_builder_mains():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders import ipfs_indexes, ipfs_package, normalized_package

    root = Path(__file__).resolve().parents[2]
    wrappers = root / "scripts" / "ops" / "legal_data"
    assert _load_script(wrappers / "build_normalized_netherlands_laws_package.py").main is normalized_package.main
    assert _load_script(wrappers / "build_ipfs_netherlands_laws_package.py").main is ipfs_package.main
    assert _load_script(wrappers / "build_ipfs_netherlands_laws_indexes.py").main is ipfs_indexes.main


def test_scrape_cli_accepts_underscore_boolean_aliases():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli import build_parser

    args = build_parser().parse_args(
        [
            "scrape",
            "--use_default_seeds",
            "true",
            "--max_seed_pages",
            "3",
            "--crawl_depth",
            "2",
            "--max_documents",
            "10",
            "--rate_limit_delay",
            "0.1",
            "--resume",
            "true",
        ]
    )

    assert args.use_default_seeds is True
    assert args.max_seed_pages == 3
    assert args.crawl_depth == 2
    assert args.max_documents == 10
    assert args.rate_limit_delay == 0.1
    assert args.resume is True


def test_scrape_cli_accepts_full_discovery_without_seed_page_cap():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli import build_parser

    args = build_parser().parse_args(["scrape", "--full_discovery", "--max_seed_pages", "0"])

    assert args.full_discovery is True
    assert args.max_seed_pages == 0


def test_operational_cli_commands_parse_catalog_arguments(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli import build_parser

    catalog_path = tmp_path / "catalog.sqlite"
    discovery_path = tmp_path / "discovery.jsonl"
    args = build_parser().parse_args(
        [
            "discover",
            "--discovery_jsonl",
            str(discovery_path),
            "--catalog_path",
            str(catalog_path),
        ]
    )
    assert args.command == "discover"
    assert args.discovery_jsonl == discovery_path
    assert args.catalog_path == catalog_path

    queue_args = build_parser().parse_args(["queue", "--catalog_path", str(catalog_path), "--limit", "10"])
    assert queue_args.command == "queue"
    assert queue_args.limit == 10

    scrape_args = build_parser().parse_args(["scrape", "--from_catalog", "--batch_size", "5"])
    assert scrape_args.from_catalog is True
    assert scrape_args.batch_size == 5


def test_persistent_catalog_import_queue_and_coverage(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.operations import (
        coverage_report,
        import_discovery_catalog,
        queue_identifiers,
    )

    discovery = tmp_path / "discovery.jsonl"
    discovery.write_text(
        "\n".join(
            [
                json.dumps({"identifier": "BWBR0000001", "source_url": "https://wetten.overheid.nl/BWBR0000001/"}),
                json.dumps({"identifier": "BWBR0000001", "source_url": "https://wetten.overheid.nl/BWBR0000001/"}),
                json.dumps({"identifier": "BWBR0000002", "document_type": "wet"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.sqlite"

    imported = import_discovery_catalog(discovery_jsonl_path=discovery, catalog_path=catalog_path)
    assert imported["inserted"] == 2
    assert imported["duplicate_input_rows"] == 1
    assert imported["total_discovered_identifiers"] == 2

    queued = queue_identifiers(catalog_path=catalog_path, limit=1)
    assert queued["queued_count"] == 1

    report = coverage_report(catalog_path=catalog_path, out_path=tmp_path / "coverage.json")
    assert report["counts"]["total_discovered_identifiers"] == 2
    assert report["counts"]["queued"] == 1
    assert report["counts"]["discovered"] == 1
    assert report["percent_complete"] == 0.0
    assert (tmp_path / "coverage.json").exists()


def test_retry_policy_only_requeues_transient_failures(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.operations import (
        classify_failure,
        import_discovery_catalog,
        mark_failure,
        queue_identifiers,
        retry_failures,
    )

    discovery = tmp_path / "discovery.jsonl"
    discovery.write_text(
        "\n".join(
            [
                json.dumps({"identifier": "BWBR0000001"}),
                json.dumps({"identifier": "BWBR0000002"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.sqlite"
    import_discovery_catalog(discovery_jsonl_path=discovery, catalog_path=catalog_path)
    queue_identifiers(catalog_path=catalog_path, identifiers=["BWBR0000001", "BWBR0000002"])

    assert classify_failure("HTTP 504 for https://wetten.overheid.nl/BWBR0000001/")["retryable"] is True
    assert classify_failure("No law text extracted")["retryable"] is False

    transient = mark_failure(catalog_path=catalog_path, identifier="BWBR0000001", message="HTTP 504 for source")
    permanent = mark_failure(catalog_path=catalog_path, identifier="BWBR0000002", message="No law text extracted")
    assert transient["failure_is_transient"] == 1
    assert permanent["failure_is_permanent"] == 1

    retried = retry_failures(catalog_path=catalog_path)
    assert retried["queued_identifiers"] == ["BWBR0000001"]


def test_catalog_sync_incremental_delta_and_integrity(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.operations import (
        build_incremental_hf_delta,
        coverage_report,
        import_discovery_catalog,
        sync_catalog_from_raw,
        validate_integrity,
    )

    raw_dir = _raw_fixture(tmp_path / "raw")
    discovery = tmp_path / "discovery.jsonl"
    discovery.write_text(json.dumps({"identifier": "BWBRTEST1"}) + "\n", encoding="utf-8")
    catalog_path = tmp_path / "catalog.sqlite"
    import_discovery_catalog(discovery_jsonl_path=discovery, catalog_path=catalog_path)

    synced = sync_catalog_from_raw(catalog_path=catalog_path, raw_dir=raw_dir)
    assert synced["updated_identifiers"] == ["BWBRTEST1"]
    report = coverage_report(catalog_path=catalog_path, out_path=None)
    assert report["counts"]["parsed"] == 1
    assert report["counts"]["complete"] == 1
    assert report["law_status_counts"]["current"] == 1

    delta = build_incremental_hf_delta(catalog_path=catalog_path, raw_dir=raw_dir, out_dir=tmp_path / "delta")
    assert delta["records"] == {"laws": 1, "articles": 3, "cid_index": 4, "index_rows": 4}
    assert (tmp_path / "delta" / "incremental_manifest.json").exists()

    ok_report = validate_integrity(
        catalog_path=catalog_path,
        raw_dir=raw_dir,
        package_dir=tmp_path / "missing_package",
        graph_dir=tmp_path / "missing_graph",
    )
    assert ok_report["ok"] is True

    orphan = {
        "record_type": "article",
        "law_identifier": "BWBRMISSING1",
        "article_identifier": "BWBRMISSING1:artikel:1",
        "law_status": "unknown",
        "text": "Orphan row.",
    }
    with (raw_dir / "netherlands_laws_articles_index_latest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(orphan) + "\n")
    bad_report = validate_integrity(
        catalog_path=catalog_path,
        raw_dir=raw_dir,
        package_dir=tmp_path / "missing_package",
        graph_dir=tmp_path / "missing_graph",
    )
    assert bad_report["ok"] is False
    assert bad_report["issue_counts"]["orphan_article_rows"] == 1


def test_ipfs_package_manifest_has_cids_hashes_counts_and_upload_target(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders.ipfs_package import build_ipfs_cid_package
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.upload import DatasetUploadTarget, assert_local_upload_ready

    raw_dir = _raw_fixture(tmp_path / "raw")
    out_dir = build_ipfs_cid_package(raw_dir=raw_dir, out_dir=tmp_path / "hf" / "base", repo_id="justicedao/ipfs_netherlands_laws")
    manifest = json.loads((out_dir / "dataset_manifest.json").read_text(encoding="utf-8"))

    assert manifest["repo_target"] == "justicedao/ipfs_netherlands_laws"
    assert manifest["upload_target"] == "justicedao/ipfs_netherlands_laws"
    assert manifest["records"] == {"laws": 1, "articles": 3, "cid_index": 4}
    for rel, info in manifest["files"].items():
        assert info["sha256"]
        assert info["file_cid"].startswith("b")
        if rel.endswith(".jsonl") or rel.endswith(".parquet"):
            assert "records" in info

    laws = [json.loads(line) for line in (out_dir / "data/laws/ipfs_netherlands_laws.jsonl").read_text().splitlines()]
    assert laws[0]["cid"].startswith("b")
    assert laws[0]["content_address"] == f"ipfs://{laws[0]['cid']}"
    assert laws[0]["law_status"] == "current"
    assert laws[0]["is_current"] is True
    assert laws[0]["status_confidence"] == "high"

    target = DatasetUploadTarget("base", out_dir, "justicedao/ipfs_netherlands_laws", ("dataset_manifest.json",))
    assert assert_local_upload_ready(target)["records"]["laws"] == 1


def test_index_manifests_have_cids_hashes_counts_and_upload_targets(tmp_path):
    pytest.importorskip("faiss")
    pytest.importorskip("sklearn")

    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders.ipfs_indexes import (
        build_bm25_index,
        build_knowledge_graph,
        build_vector_index,
    )
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders.ipfs_package import build_ipfs_cid_package

    raw_dir = _raw_fixture(tmp_path / "raw")
    source_dir = build_ipfs_cid_package(raw_dir=raw_dir, out_dir=tmp_path / "hf" / "base")
    outputs = [
        build_vector_index(source_dir=source_dir, out_dir=tmp_path / "hf" / "vector", repo_id="justicedao/ipfs_netherlands_laws_vector_index"),
        build_bm25_index(source_dir=source_dir, out_dir=tmp_path / "hf" / "bm25", repo_id="justicedao/ipfs_netherlands_laws_bm25_index"),
        build_knowledge_graph(source_dir=source_dir, out_dir=tmp_path / "hf" / "kg", repo_id="justicedao/ipfs_netherlands_laws_knowledge_graph"),
    ]

    for out_dir in outputs:
        manifest = json.loads((out_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
        assert manifest["repo_target"].startswith("justicedao/")
        assert manifest["upload_target"] == manifest["repo_target"]
        assert manifest["records"]
        assert manifest["files"]
        assert any("records" in info for info in manifest["files"].values())
        for info in manifest["files"].values():
            assert info["sha256"]
            assert info["file_cid"].startswith("b")

    vector_mapping = [
        json.loads(line)
        for line in (outputs[0] / "data/mapping/ipfs_netherlands_laws_vector_mapping.jsonl").read_text().splitlines()
    ]
    bm25_documents = [
        json.loads(line)
        for line in (outputs[1] / "data/documents/ipfs_netherlands_laws_bm25_documents.jsonl").read_text().splitlines()
    ]
    kg_nodes = [
        json.loads(line)
        for line in (outputs[2] / "data/nodes/ipfs_netherlands_laws_kg_nodes.jsonl").read_text().splitlines()
    ]
    kg_graph = json.loads((outputs[2] / "data/graph/ipfs_netherlands_laws_kg.jsonld").read_text())

    assert vector_mapping[0]["law_status"] == "current"
    assert bm25_documents[0]["law_status"] == "current"
    assert kg_nodes[0]["law_status"] == "current"
    assert kg_graph["@graph"][0]["law_status"] == "current"
