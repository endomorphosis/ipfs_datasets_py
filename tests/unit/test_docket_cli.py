from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import (
    DocketDatasetBuilder,
    load_packaged_courtlistener_fetch_cache,
    load_packaged_docket_dataset,
)


def _load_docket_cli_module():
    module_path = Path(__file__).resolve().parents[2] / "ipfs_datasets_py" / "cli" / "docket_cli.py"
    spec = importlib.util.spec_from_file_location("docket_cli_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docket_cli_main_json_output_from_json_file(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    docket_path = tmp_path / "docket.json"
    docket_path.write_text(
        json.dumps(
            {
                "docket_id": "1:24-cv-1001",
                "case_name": "Doe v. Acme",
                "court": "D. Example",
                "documents": [
                    {"id": "doc_1", "title": "Complaint", "text": "Breach of contract allegations."}
                ],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "docket_dataset.json"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "json",
                "--input-path",
                str(docket_path),
                "--output",
                str(output_path),
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert Path(payload["output_path"]).exists()
    assert payload["summary"]["document_count"] == 1


def test_ipfs_datasets_cli_dispatches_docket_command(tmp_path: Path, monkeypatch) -> None:
    docket_path = tmp_path / "docket.json"
    docket_path.write_text(
        json.dumps(
            {
                "docket_id": "1:24-cv-1001",
                "case_name": "Doe v. Acme",
                "documents": [
                    {"id": "doc_1", "title": "Complaint", "text": "Breach of contract allegations."}
                ],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "docket_dataset.json"

    module_path = Path(__file__).resolve().parents[2] / "ipfs_datasets_cli.py"
    spec = importlib.util.spec_from_file_location("ipfs_datasets_cli_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            monkeypatch.setattr(
                module.sys,
                "argv",
                [
                    "ipfs-datasets",
                    "docket",
                    "--json",
                    "--input-type",
                    "json",
                    "--input-path",
                    str(docket_path),
                    "--output",
                    str(output_path),
                ],
            )
            module.main()
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert payload["summary"]["document_count"] == 1


def test_docket_cli_main_json_output_from_courtlistener(tmp_path: Path, monkeypatch) -> None:
    module = _load_docket_cli_module()
    output_path = tmp_path / "courtlistener_docket_dataset.json"

    monkeypatch.setattr(
        module,
        "fetch_courtlistener_docket",
        lambda *args, **kwargs: {
            "docket_id": "cl-123",
            "case_name": "Doe v. CourtListener",
            "court": "D. Example",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "CourtListener summary",
                    "text": "Plaintiff must file a response within 14 days.",
                }
            ],
            "source_type": "courtlistener",
        },
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "courtlistener",
                "--input-path",
                "12345",
                "--output",
                str(output_path),
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert Path(payload["output_path"]).exists()
    assert payload["summary"]["document_count"] == 1


def test_docket_cli_can_write_parquet_only_bundle(tmp_path: Path, monkeypatch) -> None:
    module = _load_docket_cli_module()
    output_path = tmp_path / "courtlistener_docket_dataset.json"
    parquet_dir = tmp_path / "parquet_bundle"

    monkeypatch.setattr(
        module,
        "fetch_courtlistener_docket",
        lambda *args, **kwargs: {
            "docket_id": "cl-123",
            "case_name": "Doe v. CourtListener",
            "court": "D. Example",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "CourtListener summary",
                    "text": "Plaintiff must file a response within 14 days.",
                }
            ],
            "source_type": "courtlistener",
        },
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "courtlistener",
                "--input-path",
                "12345",
                "--output",
                str(output_path),
                "--parquet-dir",
                str(parquet_dir),
                "--package-name",
                "courtlistener_bundle",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    package = payload["package"]
    assert Path(package["manifest_parquet_path"]).exists()
    assert not package.get("manifest_car_path")


def test_docket_cli_can_write_zipped_bundle(tmp_path: Path, monkeypatch) -> None:
    module = _load_docket_cli_module()
    output_path = tmp_path / "courtlistener_docket_dataset.json"
    parquet_dir = tmp_path / "parquet_bundle"

    monkeypatch.setattr(
        module,
        "fetch_courtlistener_docket",
        lambda *args, **kwargs: {
            "docket_id": "cl-123",
            "case_name": "Doe v. CourtListener",
            "court": "D. Example",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "CourtListener summary",
                    "text": "Plaintiff must file a response within 14 days.",
                }
            ],
            "source_type": "courtlistener",
        },
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "courtlistener",
                "--input-path",
                "12345",
                "--output",
                str(output_path),
                "--parquet-dir",
                str(parquet_dir),
                "--package-name",
                "courtlistener_bundle",
                "--zip-package",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    package = payload["package"]
    assert Path(package["manifest_parquet_path"]).exists()
    assert Path(package["zip_path"]).exists()


def test_docket_cli_can_write_courtlistener_cache_bundle(tmp_path: Path, monkeypatch) -> None:
    module = _load_docket_cli_module()
    output_path = tmp_path / "courtlistener_docket_dataset.json"
    cache_package_dir = tmp_path / "cache_bundle"
    cache_dir = tmp_path / "shared_cache"
    index_dir = cache_dir / "courtlistener_json" / "index"
    payload_dir = cache_dir / "courtlistener_json" / "payload"
    index_dir.mkdir(parents=True, exist_ok=True)
    payload_dir.mkdir(parents=True, exist_ok=True)
    payload_file = payload_dir / "abc123.json"
    payload_file.write_text(json.dumps({"url": "https://example.test/api", "answer": 42}), encoding="utf-8")
    (index_dir / "abc123.json").write_text(
        json.dumps(
            {
                "cache_key": "abc123",
                "url": "https://example.test/api",
                "normalized_url": "https://example.test/api",
                "payload_path": str(payload_file),
                "ipfs_cid": "bafytestcid",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "fetch_courtlistener_docket",
        lambda *args, **kwargs: {
            "docket_id": "cl-123",
            "case_name": "Doe v. CourtListener",
            "court": "D. Example",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "CourtListener summary",
                    "text": "Plaintiff must file a response within 14 days.",
                }
            ],
            "source_type": "courtlistener",
        },
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "courtlistener",
                "--input-path",
                "12345",
                "--output",
                str(output_path),
                "--courtlistener-cache-dir",
                str(cache_dir),
                "--courtlistener-cache-package-dir",
                str(cache_package_dir),
                "--zip-package",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    cache_package = payload["courtlistener_cache_package"]
    assert Path(cache_package["manifest_parquet_path"]).exists()
    assert Path(cache_package["zip_path"]).exists()
    assert cache_package["summary"]["cache_index_count"] == 1


def test_docket_cli_end_to_end_exports_and_reloads_docket_and_cache_bundles(tmp_path: Path, monkeypatch) -> None:
    module = _load_docket_cli_module()
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))
    output_path = tmp_path / "courtlistener_docket_dataset.json"
    package_dir = tmp_path / "docket_bundle"
    cache_package_dir = tmp_path / "cache_bundle"
    cache_dir = tmp_path / "shared_cache"
    index_dir = cache_dir / "courtlistener_json" / "index"
    payload_dir = cache_dir / "courtlistener_json" / "payload"
    index_dir.mkdir(parents=True, exist_ok=True)
    payload_dir.mkdir(parents=True, exist_ok=True)
    payload_file = payload_dir / "abc123.json"
    payload_file.write_text(json.dumps({"url": "https://example.test/api", "answer": 42}), encoding="utf-8")
    (index_dir / "abc123.json").write_text(
        json.dumps(
            {
                "cache_key": "abc123",
                "url": "https://example.test/api",
                "normalized_url": "https://example.test/api",
                "payload_path": str(payload_file),
                "ipfs_cid": "bafytestcid",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "fetch_courtlistener_docket",
        lambda *args, **kwargs: {
            "docket_id": "cl-123",
            "case_name": "Doe v. CourtListener",
            "court": "D. Example",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Complaint",
                    "text": "Plaintiff alleges breach of contract and seeks damages.",
                },
                {
                    "id": "doc_2",
                    "title": "Order",
                    "text": "Defendant shall file an answer by 4/7/2026.",
                },
            ],
            "source_type": "courtlistener",
        },
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "courtlistener",
                "--input-path",
                "12345",
                "--output",
                str(output_path),
                "--package-dir",
                str(package_dir),
                "--package-name",
                "courtlistener_bundle",
                "--courtlistener-cache-dir",
                str(cache_dir),
                "--courtlistener-cache-package-dir",
                str(cache_package_dir),
                "--zip-package",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    docket_package = payload["package"]
    cache_package = payload["courtlistener_cache_package"]

    loaded_docket_from_manifest = load_packaged_docket_dataset(docket_package["manifest_json_path"])
    loaded_docket_from_zip = load_packaged_docket_dataset(docket_package["zip_path"])
    loaded_cache_from_manifest = load_packaged_courtlistener_fetch_cache(cache_package["manifest_json_path"])
    loaded_cache_from_zip = load_packaged_courtlistener_fetch_cache(cache_package["zip_path"])

    assert loaded_docket_from_manifest["docket_id"] == "cl-123"
    assert loaded_docket_from_zip["docket_id"] == "cl-123"
    assert len(loaded_docket_from_manifest["documents"]) == 2
    assert len(loaded_docket_from_zip["documents"]) == 2
    assert loaded_cache_from_manifest["summary"]["cache_index_count"] == 1
    assert loaded_cache_from_zip["summary"]["cache_index_count"] == 1


def test_docket_cli_can_enrich_packaged_bundle_with_tactician_queries(tmp_path: Path, monkeypatch) -> None:
    module = _load_docket_cli_module()
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))

    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-999",
            "case_name": "Packaged Enrichment Test",
            "court": "D. Example",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Summons Returned Executed",
                    "text": "Defendant served on 3/17/2026, answer due 4/7/2026.",
                },
                {
                    "id": "doc_2",
                    "title": "Extension of Time to File Answer",
                    "text": "Defendant moves for extension of time. Responses due by 4/21/2026.",
                },
            ],
        }
    )
    package = dataset.write_package(tmp_path / "bundle", package_name="packaged_enrichment_test")
    output_path = tmp_path / "enriched_view.json"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--output",
                str(output_path),
                "--enrich-query",
                "answer due deadline",
                "--enrich-query",
                "responses due extension of time",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    enriched = json.loads(Path(payload["output_path"]).read_text(encoding="utf-8"))
    assert enriched["metadata"]["tactician_enriched"] is True
    assert enriched["metadata"]["tactician_enrichment_query_count"] == 2
    assert len(enriched["tactician_enrichments"]) == 2
    assert enriched["proof_assistant"]["proof_store"]["summary"]["packet_count"] >= 1
    assert enriched["proof_assistant"]["summary"]["proof_packet_count"] >= 1
    assert enriched["attached_proof_assistant_packet"]["proof_id"]


def test_docket_cli_json_summary_surfaces_latest_routing_reason_for_packaged_enrichment(tmp_path: Path, monkeypatch) -> None:
    module = _load_docket_cli_module()
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))

    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1000",
            "case_name": "CLI Routing Summary Test",
            "court": "D. Example",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Complaint",
                    "text": "Plaintiff seeks relief under 42 U.S.C. § 1983.",
                },
            ],
            "authorities": [
                {
                    "id": "linked_authority_usc_1983",
                    "title": "Civil action for deprivation of rights",
                    "text": "Every person who, under color of state law...",
                    "authority_type": "linked_citation",
                    "citation_type": "usc",
                    "citation_text": "42 U.S.C. § 1983",
                    "normalized_citation": "42 U.S.C. § 1983",
                    "matched": True,
                    "corpus_key": "us_code",
                    "dataset_id": "justicedao/ipfs_uscode",
                    "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
                    "source_cid": "bafyuscode1983",
                    "source_ref": "uscode_parquet/source.parquet",
                    "metadata": {
                        "candidate_corpora": ["us_code"],
                        "preferred_dataset_ids": ["justicedao/ipfs_uscode"],
                        "preferred_parquet_files": ["uscode.parquet"],
                    },
                }
            ],
        }
    )
    package = dataset.write_package(tmp_path / "bundle_summary", package_name="cli_routing_summary_test", include_car=False)
    output_path = tmp_path / "enriched_summary_view.json"
    enriched_payload = dataset.to_dict()
    enriched_payload["attached_proof_assistant_packet"] = {
        "routing_explanation": {
            "routing_reason": (
                "Preferred parser corpora were ranked from linked citation '42 U.S.C. § 1983', "
                "which points first to 'us_code'. Official source: "
                "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983."
            ),
            "routing_evidence": [
                {
                    "citation_text": "42 U.S.C. § 1983",
                    "matched": True,
                    "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
                }
            ],
        }
    }
    monkeypatch.setattr(
        module,
        "enrich_packaged_docket_with_tactician",
        lambda *args, **kwargs: enriched_payload,
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--output",
                str(output_path),
                "--enrich-query",
                "proof gap constitutional claim",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["summary"]["has_latest_proof_packet_routing_explanation"] is True
    assert "42 U.S.C. § 1983" in payload["summary"]["latest_proof_packet_routing_reason"]


def test_docket_cli_can_inspect_packaged_bundle_routing_provenance(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1001",
            "case_name": "CLI Inspect Test",
            "court": "D. Example",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Complaint",
                    "text": "Plaintiff seeks relief under 42 U.S.C. § 1983.",
                },
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": (
            "Preferred parser corpora were ranked from linked citation '42 U.S.C. § 1983', "
            "which points first to 'us_code'. Official source: "
            "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983."
        ),
        "routing_evidence": [
            {
                "citation_text": "42 U.S.C. § 1983",
                "matched": True,
                "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
            }
        ],
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "authority_backed": True,
    }
    package = dataset.write_package(tmp_path / "inspect_bundle", package_name="inspect_bundle", include_car=False)
    output_path = tmp_path / "inspect_view.json"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--output",
                str(output_path),
                "--inspect-packaged",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    inspection = payload["inspection"]
    assert inspection["routing_provenance_piece_present"] is True
    assert "42 U.S.C. § 1983" in inspection["latest_routing_reason"]
    assert inspection["preferred_corpus_priority"] == ["us_code"]
    assert inspection["top_routing_citation"] == "42 U.S.C. § 1983"
    assert "uscode.house.gov" in inspection["top_routing_source_url"]


def test_docket_cli_prints_human_readable_packaged_inspection(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1002",
            "case_name": "CLI Inspect Text Test",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": (
            "Preferred parser corpora were ranked from linked citation '42 U.S.C. § 1983', "
            "which points first to 'us_code'."
        ),
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "routing_evidence": [{"citation_text": "42 U.S.C. § 1983"}],
        "authority_backed": True,
    }
    package = dataset.write_package(tmp_path / "inspect_text_bundle", package_name="inspect_text_bundle", include_car=False)
    output_path = tmp_path / "inspect_text_view.json"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--output",
                str(output_path),
                "--inspect-packaged",
            ]
        )

    assert result == 0
    text = output.getvalue()
    assert "Packaged Inspection" in text
    assert "latest_routing_reason: Preferred parser corpora were ranked from linked citation '42 U.S.C. § 1983'" in text
    assert "top_routing_citation: 42 U.S.C. § 1983" in text
    assert "top_routing_source_url:" in text
    assert "preferred_corpus_priority: us_code" in text


def test_docket_cli_can_export_packaged_markdown_report(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1003",
            "case_name": "CLI Report Test",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": (
            "Preferred parser corpora were ranked from linked citation '42 U.S.C. § 1983', "
            "which points first to 'us_code'."
        ),
        "routing_evidence": [
            {
                "citation_text": "42 U.S.C. § 1983",
                "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
                "source_title": "42 U.S.C. § 1983",
            }
        ],
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "authority_backed": True,
    }
    package = dataset.write_package(tmp_path / "inspect_report_bundle", package_name="inspect_report_bundle", include_car=False)
    output_path = tmp_path / "inspect_report_view.json"
    report_path = tmp_path / "packaged_report.md"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--output",
                str(output_path),
                "--export-packaged-report",
                str(report_path),
                "--report-format",
                "markdown",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["inspection_report"]["report_format"] == "markdown"
    assert Path(payload["inspection_report"]["report_path"]).exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "# Packaged Docket Provenance Report" in report_text
    assert "42 U.S.C. § 1983" in report_text
    assert "Preferred Corpus Priority: us_code" in report_text


def test_docket_cli_can_export_packaged_json_report(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1004",
            "case_name": "CLI JSON Report Test",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": "Preferred parser corpora were ranked from linked citation '42 U.S.C. § 1983'.",
        "routing_evidence": [
            {
                "citation_text": "42 U.S.C. § 1983",
                "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
            }
        ],
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "authority_backed": True,
    }
    package = dataset.write_package(tmp_path / "inspect_json_report_bundle", package_name="inspect_json_report_bundle", include_car=False)
    output_path = tmp_path / "inspect_json_report_view.json"
    report_path = tmp_path / "packaged_report.json"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--output",
                str(output_path),
                "--export-packaged-report",
                str(report_path),
                "--report-format",
                "json",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["inspection_report"]["report_format"] == "json"
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["top_routing_citation"] == "42 U.S.C. § 1983"
    assert report_payload["preferred_corpus_priority"] == ["us_code"]


def test_docket_cli_can_load_archived_packaged_report_in_json_mode(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1005",
            "case_name": "CLI Load Report Test",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": "Archived report routing reason.",
        "routing_evidence": [{"citation_text": "42 U.S.C. § 1983"}],
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "authority_backed": True,
    }
    package = dataset.write_package(tmp_path / "load_report_bundle", package_name="load_report_bundle", include_car=False)
    output_path = tmp_path / "load_report_view.json"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--output",
                str(output_path),
                "--load-packaged-report",
                "--report-format",
                "parsed",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["loaded_packaged_report"]["latest_routing_reason"] == "Archived report routing reason."
    assert payload["loaded_packaged_report"]["preferred_corpus_priority"] == ["us_code"]


def test_docket_cli_prints_loaded_archived_markdown_report(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1006",
            "case_name": "CLI Print Archived Report Test",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": "Archived markdown routing reason.",
        "routing_evidence": [{"citation_text": "42 U.S.C. § 1983"}],
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "authority_backed": True,
    }
    package = dataset.write_package(tmp_path / "print_report_bundle", package_name="print_report_bundle", include_car=False)
    output_path = tmp_path / "print_report_view.json"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--output",
                str(output_path),
                "--load-packaged-report",
                "--report-format",
                "markdown",
            ]
        )

    assert result == 0
    text = output.getvalue()
    assert "Packaged Docket Provenance Report" in text
    assert "Archived markdown routing reason." in text


def test_docket_cli_can_load_packaged_report_without_output(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1007",
            "case_name": "CLI No Output Report Test",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": "No-output packaged report routing reason.",
        "routing_evidence": [{"citation_text": "42 U.S.C. § 1983"}],
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "authority_backed": True,
    }
    package = dataset.write_package(tmp_path / "no_output_bundle", package_name="no_output_bundle", include_car=False)

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--load-packaged-report",
                "--report-format",
                "parsed",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert "output_path" not in payload
    assert payload["loaded_packaged_report"]["latest_routing_reason"] == "No-output packaged report routing reason."


def test_docket_cli_packaged_read_only_path_skips_full_dataset_load(tmp_path: Path, monkeypatch) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1008",
            "case_name": "CLI Lightweight Packaged Read",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": "Lightweight packaged read routing reason.",
        "routing_evidence": [{"citation_text": "42 U.S.C. § 1983"}],
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "authority_backed": True,
    }
    package = dataset.write_package(
        tmp_path / "lightweight_read_bundle",
        package_name="lightweight_read_bundle",
        include_car=False,
    )

    monkeypatch.setattr(
        module,
        "load_packaged_docket_dataset",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full packaged load should not run")),
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--load-packaged-report",
                "--report-format",
                "parsed",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["loaded_packaged_report"]["latest_routing_reason"] == "Lightweight packaged read routing reason."
    assert payload["summary"]["document_count"] == 1


def test_docket_cli_packaged_read_only_path_skips_minimal_document_view(tmp_path: Path, monkeypatch) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1009",
            "case_name": "CLI Summary View Read",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": "Summary-view packaged read routing reason.",
        "routing_evidence": [{"citation_text": "42 U.S.C. § 1983"}],
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "authority_backed": True,
    }
    package = dataset.write_package(
        tmp_path / "summary_view_bundle",
        package_name="summary_view_bundle",
        include_car=False,
    )

    original_packager = module.DocketDatasetPackager

    class GuardedPackager(original_packager):
        def load_minimal_dataset_view(self, manifest_path):
            raise AssertionError("minimal document view should not run for packaged read-only CLI path")

    monkeypatch.setattr(module, "DocketDatasetPackager", GuardedPackager)

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--inspect-packaged",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["inspection"]["latest_routing_reason"] == "Summary-view packaged read routing reason."
    assert payload["summary"]["document_count"] == 1


def test_docket_cli_can_emit_packaged_summary_only_json_without_output(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1010",
            "case_name": "CLI Summary Only JSON",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    dataset.metadata["latest_proof_packet_routing_explanation"] = {
        "routing_reason": "Summary-only routing reason.",
        "routing_evidence": [{"citation_text": "42 U.S.C. § 1983"}],
        "preferred_corpus_priority": ["us_code"],
        "preferred_state_codes": [],
        "authority_backed": True,
    }
    package = dataset.write_package(
        tmp_path / "summary_only_json_bundle",
        package_name="summary_only_json_bundle",
        include_car=False,
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--summary-only",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert "output_path" not in payload
    assert payload["packaged_summary_view"]["document_count"] == 1
    assert payload["packaged_summary_view"]["case_name"] == "CLI Summary Only JSON"


def test_docket_cli_prints_packaged_summary_only_text(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1011",
            "case_name": "CLI Summary Only Text",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Plaintiff seeks relief under 42 U.S.C. § 1983."},
            ],
        }
    )
    package = dataset.write_package(
        tmp_path / "summary_only_text_bundle",
        package_name="summary_only_text_bundle",
        include_car=False,
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "packaged",
                "--input-path",
                str(package["manifest_json_path"]),
                "--summary-only",
            ]
        )

    assert result == 0
    text = output.getvalue()
    assert "Packaged Summary" in text
    assert "document_count: 1" in text
    assert "case_name: CLI Summary Only Text" in text


def test_docket_cli_requires_output_for_non_read_only_paths(tmp_path: Path) -> None:
    module = _load_docket_cli_module()
    docket_path = tmp_path / "docket.json"
    docket_path.write_text(
        json.dumps(
            {
                "docket_id": "1:24-cv-1001",
                "case_name": "Doe v. Acme",
                "court": "D. Example",
                "documents": [
                    {"id": "doc_1", "title": "Complaint", "text": "Breach of contract allegations."}
                ],
            }
        ),
        encoding="utf-8",
    )

    try:
        module.main(
            [
                "--input-type",
                "json",
                "--input-path",
                str(docket_path),
                "--json",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected parser error when --output is omitted for non-read-only command")
