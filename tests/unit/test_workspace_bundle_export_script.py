from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import load_packaged_workspace_summary_view


def _load_workspace_bundle_export_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "legal_data" / "export_workspace_dataset_bundle.py"
    spec = importlib.util.spec_from_file_location("workspace_bundle_export_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_email_export_json(tmp_path: Path) -> Path:
    export_path = tmp_path / "email_export.json"
    export_path.write_text(
        json.dumps(
            {
                "status": "success",
                "protocol": "imap",
                "server": "mail.example.com",
                "folder": "INBOX",
                "emails": [
                    {
                        "message_id_header": "<message-1@example.com>",
                        "subject": "Inspection notice",
                        "from": "tenant@example.com",
                        "to": "advocate@example.com",
                        "date": "2026-03-24T06:00:00Z",
                        "body_text": "Please review the attached inspection notice and lease.",
                        "attachments": [{"filename": "notice.pdf", "size": 1234}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return export_path


def _build_imap_snippet_summary_json(tmp_path: Path) -> Path:
    body_path = tmp_path / "body.txt"
    headers_path = tmp_path / "headers.txt"
    body_path.write_text("IMAP snippet body text.", encoding="utf-8")
    headers_path.write_text("From: tenant@example.com\nSubject: Snippet\n", encoding="utf-8")

    summary_path = tmp_path / "imap_snippets_summary.json"
    summary_path.write_text(
        json.dumps(
            [
                {"seq": 1, "body_path": str(body_path), "headers_path": str(headers_path)},
                {"seq": 2, "body_path": str(body_path), "headers_path": str(headers_path)},
            ]
        ),
        encoding="utf-8",
    )
    return summary_path


def _build_google_voice_manifest_json(tmp_path: Path) -> Path:
    bundle_dir = tmp_path / "google_voice_bundle_1"
    bundle_dir.mkdir()
    manifest_path = tmp_path / "google_voice_manifest.json"
    transcript_path = bundle_dir / "transcript.txt"
    event_json_path = bundle_dir / "event.json"
    source_html_path = bundle_dir / "source.html"
    enrichment_path = bundle_dir / "audio.whisper.txt"
    attachment_text_path = bundle_dir / "inspection_notes.txt"

    transcript_path.write_text(
        "Tenant: Please send the inspection notice.\nAdvocate: I will send it tonight.\n",
        encoding="utf-8",
    )
    enrichment_path.write_text("Generated Google Voice enrichment transcript.", encoding="utf-8")
    attachment_text_path.write_text("Inspection notes attached to the Google Voice event.", encoding="utf-8")
    source_html_path.write_text("<html><body>voice event</body></html>", encoding="utf-8")
    event_json_path.write_text(
        json.dumps(
            {
                "event_id": "voice_1",
                "event_type": "text_message",
                "title": "Text conversation",
                "timestamp": "2026-03-24T04:56:14Z",
                "phone_numbers": ["(503) 555-0100"],
                "attachments": [
                    {"path": str(bundle_dir / "audio.mp3"), "kind": "audio"},
                    {"path": str(attachment_text_path), "kind": "document", "content_type": "text/plain", "filename": "inspection_notes.txt"},
                ],
                "enrichments": [{"path": str(enrichment_path), "kind": "transcription", "source_attachment": str(bundle_dir / "audio.mp3")}],
                "source_kind": "takeout",
                "source_html_path": str(source_html_path),
            }
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "status": "success",
                "source_kind": "takeout",
                "manifest_path": str(manifest_path),
                "bundles": [
                    {
                        "event_id": "voice_1",
                        "event_type": "text_message",
                        "title": "Text conversation",
                        "evidence_title": "Text conversation with advocate",
                        "timestamp": "2026-03-24T04:56:14Z",
                        "bundle_dir": str(bundle_dir),
                        "event_json_path": str(event_json_path),
                        "parsed_path": str(event_json_path),
                        "transcript_path": str(transcript_path),
                        "source_html_path": str(source_html_path),
                        "participants": ["(503) 555-0100"],
                        "phone_numbers": ["(503) 555-0100"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_workspace_bundle_export_script_auto_detects_email_input(tmp_path: Path) -> None:
    module = _load_workspace_bundle_export_module()
    export_path = _build_email_export_json(tmp_path)
    output_dir = tmp_path / "email_package"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-path",
                str(export_path),
                "--output-dir",
                str(output_dir),
                "--package-name",
                "email_package",
                "--no-car",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["input_type"] == "email-export"
    assert payload["input_type_resolution"] == "auto"
    assert payload["summary"]["document_count"] == 1

    manifest_path = Path(payload["manifest_json_path"])
    assert manifest_path.is_file()

    summary = load_packaged_workspace_summary_view(manifest_path)
    assert summary["workspace_id"] == "inbox"
    assert summary["source_type"] == "email"
    assert summary["input_type"] == "email-export"
    assert summary["input_type_resolution"] == "auto"
    assert summary["document_count"] == 1


def test_workspace_bundle_export_script_accepts_explicit_imap_input_type(tmp_path: Path) -> None:
    module = _load_workspace_bundle_export_module()
    summary_path = _build_imap_snippet_summary_json(tmp_path)
    output_dir = tmp_path / "imap_package"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-type",
                "imap-snippet-summary",
                "--input-path",
                str(summary_path),
                "--output-dir",
                str(output_dir),
                "--package-name",
                "imap_package",
                "--no-car",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["input_type"] == "imap-snippet-summary"
    assert payload["input_type_resolution"] == "explicit"
    assert payload["summary"]["document_count"] == 2

    manifest_path = Path(payload["manifest_json_path"])
    assert manifest_path.is_file()

    summary = load_packaged_workspace_summary_view(manifest_path)
    assert summary["source_type"] == "imap_snippets"
    assert summary["input_type"] == "imap-snippet-summary"
    assert summary["input_type_resolution"] == "explicit"
    assert summary["document_count"] == 2


def test_workspace_bundle_export_script_auto_detects_imap_input(tmp_path: Path) -> None:
    module = _load_workspace_bundle_export_module()
    summary_path = _build_imap_snippet_summary_json(tmp_path)
    output_dir = tmp_path / "imap_package_auto"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-path",
                str(summary_path),
                "--output-dir",
                str(output_dir),
                "--package-name",
                "imap_package_auto",
                "--no-car",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["input_type"] == "imap-snippet-summary"
    assert payload["input_type_resolution"] == "auto"
    assert payload["summary"]["document_count"] == 2

    manifest_path = Path(payload["manifest_json_path"])
    assert manifest_path.is_file()

    summary = load_packaged_workspace_summary_view(manifest_path)
    assert summary["source_type"] == "imap_snippets"
    assert summary["input_type"] == "imap-snippet-summary"
    assert summary["input_type_resolution"] == "auto"
    assert summary["document_count"] == 2


def test_workspace_bundle_export_script_auto_detects_google_voice_materialized_input(tmp_path: Path) -> None:
    module = _load_workspace_bundle_export_module()
    manifest_path = _build_google_voice_manifest_json(tmp_path)
    output_dir = tmp_path / "google_voice_package"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--input-path",
                str(manifest_path),
                "--output-dir",
                str(output_dir),
                "--package-name",
                "google_voice_package",
                "--no-car",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["input_type"] == "google-voice-manifest"
    assert payload["input_type_resolution"] == "auto"
    assert payload["summary"]["document_count"] == 3

    packaged_summary = load_packaged_workspace_summary_view(Path(payload["manifest_json_path"]))
    assert packaged_summary["source_type"] == "google_voice"
    assert packaged_summary["input_type"] == "google-voice-manifest"
    assert packaged_summary["document_count"] == 3