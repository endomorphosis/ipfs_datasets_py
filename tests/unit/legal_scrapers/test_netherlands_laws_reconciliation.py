from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli import main
from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.operations import reconcile_milestone


def test_reconcile_milestone_passes_when_fixture_counts_align(tmp_path: Path) -> None:
    paths = _write_reconciliation_fixture(tmp_path)

    report = reconcile_milestone(**paths)

    assert report["ok"] is True
    assert report["mismatch_count"] == 0
    assert report["network_used"] is False
    assert report["scrape_used"] is False
    assert report["package_build_used"] is False
    assert report["upload_used"] is False
    assert report["summaries"]["catalog"]["counts"]["complete"] == 2
    assert report["summaries"]["package"]["manifest"]["records"]["laws"] == 2


def test_reconcile_milestone_reports_count_and_identifier_drift(tmp_path: Path) -> None:
    paths = _write_reconciliation_fixture(tmp_path)
    package_laws = paths["package_dir"] / "data/laws/ipfs_netherlands_laws.jsonl"
    package_laws.write_text(
        json.dumps({"law_identifier": "BWBR0000001"}) + "\n",
        encoding="utf-8",
    )

    report = reconcile_milestone(**paths)

    assert report["ok"] is False
    mismatch_names = {item["name"] for item in report["mismatches"]}
    assert "base package laws" in mismatch_names
    assert "catalog package-representable identifiers vs base package laws" in mismatch_names
    identifier_mismatch = next(
        item
        for item in report["mismatches"]
        if item["name"] == "catalog package-representable identifiers vs base package laws"
    )
    assert identifier_mismatch["missing_count"] == 1
    assert identifier_mismatch["missing_sample"] == ["BWBR0000002"]


def test_reconcile_milestone_warns_for_missing_optional_artifacts(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    _write_catalog(catalog_path)

    report = reconcile_milestone(
        catalog_path=catalog_path,
        raw_dir=tmp_path / "missing-raw",
        package_dir=tmp_path / "missing-package",
        unified_dir=tmp_path / "missing-unified",
        reports_dir=tmp_path / "missing-reports",
    )

    assert report["ok"] is True
    assert report["warning_count"] > 0
    assert any(item["type"] == "missing_optional_artifact" for item in report["warnings"])


def test_reconcile_milestone_reports_malformed_optional_json_as_mismatch(tmp_path: Path) -> None:
    paths = _write_reconciliation_fixture(tmp_path)
    malformed_manifest = paths["package_dir"] / "dataset_manifest.json"
    malformed_coverage = paths["reports_dir"] / "coverage_report_latest.json"
    malformed_manifest.write_text('{"records": ', encoding="utf-8")
    malformed_coverage.write_text('{"counts": ', encoding="utf-8")

    report = reconcile_milestone(**paths)

    assert report["ok"] is False
    malformed_entries = [
        item
        for item in report["mismatches"]
        if item["type"] == "malformed_json_artifact"
    ]
    malformed_paths = {item["path"] for item in malformed_entries}
    assert str(malformed_manifest) in malformed_paths
    assert str(malformed_coverage) in malformed_paths
    assert {item["name"] for item in malformed_entries} >= {"base package manifest", "coverage report"}
    assert not any(
        item["type"] == "missing_optional_artifact" and item["path"] in malformed_paths
        for item in report["warnings"]
    )


def test_reconcile_cli_writes_report_without_scraping_or_network(tmp_path: Path) -> None:
    paths = _write_reconciliation_fixture(tmp_path)
    out_path = tmp_path / "reconciliation.json"

    exit_code = main(
        [
            "reconcile",
            "--catalog-path",
            str(paths["catalog_path"]),
            "--raw-dir",
            str(paths["raw_dir"]),
            "--package-dir",
            str(paths["package_dir"]),
            "--unified-dir",
            str(paths["unified_dir"]),
            "--reports-dir",
            str(paths["reports_dir"]),
            "--out-path",
            str(out_path),
            "--milestone-name",
            "fixture-5000",
        ]
    )

    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert written["ok"] is True
    assert written["milestone_name"] == "fixture-5000"
    assert written["network_used"] is False
    assert written["scrape_used"] is False


def _write_reconciliation_fixture(tmp_path: Path) -> dict[str, Path]:
    catalog_path = tmp_path / "catalog.sqlite"
    raw_dir = tmp_path / "raw"
    package_dir = tmp_path / "package"
    unified_dir = tmp_path / "unified"
    reports_dir = tmp_path / "reports"
    _write_catalog(catalog_path)

    _write_jsonl(
        raw_dir / "netherlands_laws_index_latest.jsonl",
        [
            {"law_identifier": "BWBR0000001", "title": "Wet 1"},
            {"law_identifier": "BWBR0000002", "title": "Wet 2"},
        ],
    )
    _write_jsonl(
        raw_dir / "netherlands_laws_articles_index_latest.jsonl",
        [
            {"law_identifier": "BWBR0000001", "article_identifier": "BWBR0000001:a1"},
            {"law_identifier": "BWBR0000001", "article_identifier": "BWBR0000001:a2"},
            {"law_identifier": "BWBR0000002", "article_identifier": "BWBR0000002:a1"},
        ],
    )

    _write_json(package_dir / "dataset_manifest.json", {"records": {"laws": 2, "articles": 3, "cid_index": 5}})
    _write_jsonl(
        package_dir / "data/laws/ipfs_netherlands_laws.jsonl",
        [
            {"law_identifier": "BWBR0000001", "cid": "bafylaw1"},
            {"law_identifier": "BWBR0000002", "cid": "bafylaw2"},
        ],
    )
    _write_jsonl(
        package_dir / "data/articles/ipfs_netherlands_laws_articles.jsonl",
        [
            {"law_identifier": "BWBR0000001", "article_identifier": "BWBR0000001:a1", "cid": "bafyarticle1"},
            {"law_identifier": "BWBR0000001", "article_identifier": "BWBR0000001:a2", "cid": "bafyarticle2"},
            {"law_identifier": "BWBR0000002", "article_identifier": "BWBR0000002:a1", "cid": "bafyarticle3"},
        ],
    )
    _write_jsonl(
        package_dir / "data/cid_index/ipfs_netherlands_laws_cid_index.jsonl",
        [
            {"law_identifier": "BWBR0000001", "record_type": "law"},
            {"law_identifier": "BWBR0000002", "record_type": "law"},
            {"law_identifier": "BWBR0000001", "record_type": "article"},
            {"law_identifier": "BWBR0000001", "record_type": "article"},
            {"law_identifier": "BWBR0000002", "record_type": "article"},
        ],
    )

    _write_json(unified_dir / "dataset_manifest.json", {"records": {"laws": 2, "articles": 3, "cid_index": 5}})
    _write_json(
        reports_dir / "coverage_report_latest.json",
        {
            "counts": {"total_discovered_identifiers": 2, "complete": 2, "remaining": 0},
            "article_rows_count": 3,
            "percent_complete": 100.0,
        },
    )
    _write_json(reports_dir / "integrity_report_fixture.json", {"ok": True, "issue_counts": {}})
    return {
        "catalog_path": catalog_path,
        "raw_dir": raw_dir,
        "package_dir": package_dir,
        "unified_dir": unified_dir,
        "reports_dir": reports_dir,
    }


def _write_catalog(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE bwbr_catalog (
                identifier TEXT PRIMARY KEY,
                scrape_state TEXT NOT NULL,
                failure_is_permanent INTEGER NOT NULL DEFAULT 0,
                law_status TEXT NOT NULL DEFAULT 'unknown',
                parser_status TEXT,
                article_extraction_status TEXT,
                article_rows_count INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO bwbr_catalog (
                identifier, scrape_state, failure_is_permanent, law_status,
                parser_status, article_extraction_status, article_rows_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("BWBR0000001", "parsed", 0, "current", "parsed", "articles_extracted", 2),
                ("BWBR0000002", "verified", 0, "historical", "parsed", "articles_extracted", 1),
            ],
        )
        conn.commit()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
