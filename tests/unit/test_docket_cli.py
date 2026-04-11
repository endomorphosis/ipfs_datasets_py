from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import (
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
