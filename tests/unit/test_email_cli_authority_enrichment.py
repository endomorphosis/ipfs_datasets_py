from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path


def _load_email_cli_module():
    import importlib.util

    module_path = (
        Path(__file__).resolve().parents[2]
        / "ipfs_datasets_py"
        / "cli"
        / "email_cli.py"
    )
    spec = importlib.util.spec_from_file_location("email_cli_authority_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_email_cli_authority_enrichment_passes_catalog_path(tmp_path: Path, monkeypatch) -> None:
    module = _load_email_cli_module()

    timeline_path = tmp_path / "email_timeline_handoff.json"
    timeline_path.write_text("{}", encoding="utf-8")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text("{}", encoding="utf-8")
    output_json = tmp_path / "authority_cli_output.json"

    import ipfs_datasets_py.processors.legal_data as legal_data

    def _fake_enrich(path: str, **kwargs):
        assert str(path) == str(timeline_path)
        assert str(kwargs.get("catalog_path")) == str(catalog_path)
        return {
            "status": "success",
            "email_timeline_handoff_path": str(path),
            "catalog_path": str(kwargs.get("catalog_path") or ""),
            "query_plan": [],
            "query_results": [],
            "summary": {"query_count": 0},
        }

    monkeypatch.setattr(legal_data, "enrich_email_timeline_authorities", _fake_enrich)

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(
                [
                    "authority-enrichment",
                    str(timeline_path),
                    "--catalog-path",
                    str(catalog_path),
                    "--output",
                    str(output_json),
                ]
            )
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["catalog_path"] == str(catalog_path)


def test_email_cli_authority_enrichment_error_payload_includes_catalog_path(tmp_path: Path, monkeypatch) -> None:
    module = _load_email_cli_module()

    timeline_path = tmp_path / "email_timeline_handoff.json"
    timeline_path.write_text("{}", encoding="utf-8")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text("{}", encoding="utf-8")

    import ipfs_datasets_py.processors.legal_data as legal_data

    def _fake_enrich(_path: str, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(legal_data, "enrich_email_timeline_authorities", _fake_enrich)

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(
                [
                    "authority-enrichment",
                    str(timeline_path),
                    "--catalog-path",
                    str(catalog_path),
                ]
            )
        except SystemExit as exc:
            assert exc.code == 1

    payload = json.loads(output.getvalue())
    assert payload["status"] == "error"
    assert payload["catalog_path"] == str(catalog_path)
