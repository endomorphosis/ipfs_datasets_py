from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path


def _load_script_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "ops"
        / "legal_data"
        / "run_email_authority_enrichment.py"
    )
    spec = importlib.util.spec_from_file_location("run_email_authority_enrichment_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_email_authority_enrichment_script_passes_catalog_path(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()

    handoff = tmp_path / "email_timeline_handoff.json"
    handoff.write_text("{}", encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")

    def _fake_enrich(path: str, **kwargs):
        assert str(path) == str(handoff)
        assert str(kwargs.get("catalog_path")) == str(catalog)
        return {
            "status": "success",
            "email_timeline_handoff_path": str(path),
            "catalog_path": str(kwargs.get("catalog_path") or ""),
            "summary": {"query_count": 0, "queries_with_hits": 0, "seed_authority_count": 0},
            "output_path": str(tmp_path / "email_authority_enrichment.json"),
            "markdown_output_path": str(tmp_path / "email_authority_enrichment.md"),
        }

    monkeypatch.setattr(module, "enrich_email_timeline_authorities", _fake_enrich)

    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = module.main([
            "--input",
            str(handoff),
            "--catalog-path",
            str(catalog),
            "--json",
        ])

    assert exit_code == 0
    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert payload["catalog_path"] == str(catalog)
