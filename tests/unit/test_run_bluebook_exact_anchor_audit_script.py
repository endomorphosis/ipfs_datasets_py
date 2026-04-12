from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "ops"
        / "legal_data"
        / "run_bluebook_exact_anchor_audit.py"
    )
    spec = importlib.util.spec_from_file_location("run_bluebook_exact_anchor_audit_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_bluebook_exact_anchor_audit_script_writes_outputs(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()

    input_path = tmp_path / "documents.json"
    input_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_1",
                        "title": "Sample",
                        "text": "See 38 Mich. 90.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    output_json = tmp_path / "audit.json"
    output_report = tmp_path / "audit.txt"

    fake_payload = {
        "source": "bluebook_exact_anchor_guarantee_audit",
        "require_exact_anchor": True,
        "document_count": 1,
        "citation_count": 1,
        "matched_citation_count": 1,
        "exact_anchor_match_count": 1,
        "non_exact_match_count": 0,
        "exact_anchor_match_ratio": 1.0,
        "non_exact_matches": [],
        "resolution_audit": {"documents": []},
    }

    def _fake_audit(documents, **kwargs):
        assert len(list(documents)) == 1
        assert bool(kwargs.get("exhaustive")) is True
        return dict(fake_payload)

    monkeypatch.setattr(module, "audit_bluebook_exact_anchor_guarantees_for_documents", _fake_audit)

    exit_code = module.main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_json),
            "--report-output",
            str(output_report),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["source"] == "bluebook_exact_anchor_guarantee_audit"
    assert payload["input_path"] == str(input_path.resolve())
    report_text = output_report.read_text(encoding="utf-8")
    assert "Bluebook Exact-Anchor Guarantee Audit" in report_text
    assert "non_exact_match_count: 0" in report_text


def test_run_bluebook_exact_anchor_audit_script_returns_two_when_non_exact(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()

    input_path = tmp_path / "documents.json"
    input_path.write_text("[]", encoding="utf-8")

    def _fake_audit(_documents, **_kwargs):
        return {
            "source": "bluebook_exact_anchor_guarantee_audit",
            "require_exact_anchor": False,
            "document_count": 0,
            "citation_count": 0,
            "matched_citation_count": 0,
            "exact_anchor_match_count": 0,
            "non_exact_match_count": 1,
            "exact_anchor_match_ratio": 0.0,
            "non_exact_matches": [
                {
                    "document_id": "doc_1",
                    "citation_text": "38 Mich. 90",
                    "resolution_method": "citation_url_fallback",
                }
            ],
            "resolution_audit": {"documents": []},
        }

    monkeypatch.setattr(module, "audit_bluebook_exact_anchor_guarantees_for_documents", _fake_audit)

    exit_code = module.main(["--input", str(input_path), "--json"])
    assert exit_code == 2
