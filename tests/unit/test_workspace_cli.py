from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path


from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    export_workspace_dataset_single_parquet,
    load_packaged_workspace_summary_view,
)


def _load_workspace_cli_module():
    module_path = Path(__file__).resolve().parents[2] / "ipfs_datasets_py" / "cli" / "workspace_cli.py"
    spec = importlib.util.spec_from_file_location("workspace_cli_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_workspace_bundle(tmp_path: Path) -> Path:
    dataset = WorkspaceDatasetBuilder().build_from_workspace(
        {
            "workspace_id": "cli-01",
            "workspace_name": "CLI Workspace",
            "source_type": "email",
            "collections": [{"id": "thread-1", "title": "Thread 1"}],
            "documents": [
                {
                    "id": "doc_1",
                    "subject": "Invoice follow-up",
                    "body": "Breach of contract allegations and invoice dispute details.",
                    "document_type": "email",
                }
            ],
        }
    )
    bundle_path = tmp_path / "workspace_bundle.parquet"
    export_workspace_dataset_single_parquet(dataset, bundle_path)
    return bundle_path


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


def _build_discord_export_json(tmp_path: Path) -> Path:
    export_path = tmp_path / "discord_export.json"
    export_path.write_text(
        json.dumps(
            {
                "guild_id": "guild_1",
                "guild_name": "Tenant Support",
                "channel_id": "channel_9",
                "channel_name": "housing-help",
                "messages": [
                    {
                        "id": "message_1",
                        "timestamp": "2026-03-24T05:00:00Z",
                        "author": "advocate",
                        "content": "Please upload the lease and all inspection notices.",
                        "attachments": [{"url": "https://example.com/lease.pdf"}],
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


def test_workspace_cli_can_emit_summary_json(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    bundle_path = _build_workspace_bundle(tmp_path)

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main([
            "--input-path",
            str(bundle_path),
            "--action",
            "summary",
            "--json",
        ])

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["workspace_id"] == "cli-01"
    assert payload["document_count"] == 1


def test_workspace_cli_can_emit_inspection_field_subset_text(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    bundle_path = _build_workspace_bundle(tmp_path)

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main([
            "--input-path",
            str(bundle_path),
            "--action",
            "inspect",
            "--fields",
            "workspace_id,row_count,sections",
        ])

    rendered = output.getvalue()
    assert result == 0
    assert "Workspace Bundle Inspection" in rendered
    assert "workspace_id: cli-01" in rendered
    assert "row_count:" in rendered
    assert "sections:" in rendered


def test_workspace_cli_can_render_markdown_report(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    bundle_path = _build_workspace_bundle(tmp_path)

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main([
            "--input-path",
            str(bundle_path),
            "--action",
            "report",
            "--report-format",
            "markdown",
        ])

    rendered = output.getvalue()
    assert result == 0
    assert rendered.startswith("# Workspace Dataset Bundle Report\n")
    assert "- Workspace ID: cli-01" in rendered


def test_workspace_cli_can_package_workspace_bundle(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    workspace_path = tmp_path / "workspace.json"
    workspace_path.write_text(
        json.dumps(
            {
                "workspace_id": "cli-packaged-01",
                "workspace_name": "CLI Packaged Workspace",
                "documents": [
                    {"id": "doc_1", "title": "Memo", "text": "Workspace packaging test."}
                ],
            }
        ),
        encoding="utf-8",
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--action",
                "package",
                "--input-json",
                str(workspace_path),
                "--output-dir",
                str(tmp_path / "workspace_bundle"),
                "--package-name",
                "workspace_bundle",
                "--no-car",
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["summary"]["document_count"] == 1
    assert "manifest_json_path" in payload


def test_workspace_cli_can_read_packaged_summary(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    workspace = WorkspaceDatasetBuilder().build_from_workspace(
        {
            "workspace_id": "cli-packaged-02",
            "workspace_name": "CLI Packaged Summary",
            "documents": [
                {"id": "doc_1", "title": "Memo", "text": "Workspace packaging summary test."}
            ],
        }
    )
    from ipfs_datasets_py.processors.legal_data import package_workspace_dataset

    package = package_workspace_dataset(
        workspace,
        tmp_path / "packaged_summary",
        package_name="workspace_bundle",
        include_car=False,
    )

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--action",
                "package-summary",
                "--input-path",
                str(package["manifest_json_path"]),
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["document_count"] == 1
    assert payload["workspace_id"] == "cli-packaged-02"


def test_workspace_cli_can_package_email_export_without_input_type(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    export_path = _build_email_export_json(tmp_path)

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--action",
                "package",
                "--input-path",
                str(export_path),
                "--output-dir",
                str(tmp_path / "email_package"),
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
    assert payload["piece_count"] >= 1
    manifest_path = Path(payload["manifest_json_path"])
    assert manifest_path.is_file()

    summary = load_packaged_workspace_summary_view(manifest_path)
    assert summary["input_type"] == "email-export"
    assert summary["input_type_resolution"] == "auto"
    assert summary["source_type"] == "email"


def test_workspace_cli_package_inspect_and_report_preserve_input_provenance(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    export_path = _build_email_export_json(tmp_path)
    manifest_output = io.StringIO()

    with redirect_stdout(manifest_output):
        package_result = module.main(
            [
                "--action",
                "package",
                "--input-path",
                str(export_path),
                "--output-dir",
                str(tmp_path / "email_package_readback"),
                "--package-name",
                "email_package_readback",
                "--no-car",
                "--json",
            ]
        )

    assert package_result == 0
    package_payload = json.loads(manifest_output.getvalue())
    manifest_path = Path(package_payload["manifest_json_path"])
    assert manifest_path.is_file()

    inspect_output = io.StringIO()
    with redirect_stdout(inspect_output):
        inspect_result = module.main(
            [
                "--action",
                "package-inspect",
                "--input-path",
                str(manifest_path),
                "--json",
            ]
        )

    assert inspect_result == 0
    inspect_payload = json.loads(inspect_output.getvalue())
    assert inspect_payload["input_type"] == "email-export"
    assert inspect_payload["input_type_resolution"] == "auto"
    assert inspect_payload["source_type"] == "email"

    report_output = io.StringIO()
    with redirect_stdout(report_output):
        report_result = module.main(
            [
                "--action",
                "package-report",
                "--input-path",
                str(manifest_path),
                "--report-format",
                "text",
            ]
        )

    assert report_result == 0
    rendered = report_output.getvalue()
    assert "Packaged Workspace Dataset Report" in rendered
    assert "Input Type: email-export" in rendered
    assert "Input Type Resolution: auto" in rendered


def test_workspace_cli_can_package_imap_summary_without_input_type(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    summary_path = _build_imap_snippet_summary_json(tmp_path)

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--action",
                "package",
                "--input-path",
                str(summary_path),
                "--output-dir",
                str(tmp_path / "imap_package"),
                "--package-name",
                "imap_package",
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
    assert summary["input_type"] == "imap-snippet-summary"
    assert summary["input_type_resolution"] == "auto"
    assert summary["source_type"] == "imap_snippets"


def test_ipfs_datasets_cli_dispatches_workspace_package_command(tmp_path: Path, monkeypatch) -> None:
    export_path = _build_discord_export_json(tmp_path)
    output_dir = tmp_path / "discord_package_dispatch"

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
                    "workspace",
                    "--action",
                    "package",
                    "--input-path",
                    str(export_path),
                    "--output-dir",
                    str(output_dir),
                    "--package-name",
                    "discord_package_dispatch",
                    "--no-car",
                    "--json",
                ],
            )
            module.main()
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["input_type"] == "discord-export"
    assert payload["input_type_resolution"] == "auto"
    assert payload["summary"]["document_count"] == 1
    manifest_path = Path(payload["manifest_json_path"])
    assert manifest_path.is_file()

    summary = load_packaged_workspace_summary_view(manifest_path)
    assert summary["input_type"] == "discord-export"
    assert summary["input_type_resolution"] == "auto"
    assert summary["source_type"] == "discord"


def test_workspace_cli_can_package_google_voice_materialized_manifest(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    export_path = _build_google_voice_manifest_json(tmp_path)

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--action",
                "package",
                "--input-path",
                str(export_path),
                "--output-dir",
                str(tmp_path / "google_voice_package"),
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
    manifest_path = Path(payload["manifest_json_path"])
    assert manifest_path.is_file()

    summary = load_packaged_workspace_summary_view(manifest_path)
    assert summary["source_type"] == "google_voice"
    assert summary["input_type"] == "google-voice-manifest"
    assert summary["input_type_resolution"] == "auto"
    assert summary["document_count"] == 3
    assert len(summary["collection_overview"]) == 2
    assert summary["collection_overview"][1] == {
        "id": "google_voice_bundle_voice_1",
        "title": "Text conversation with advocate",
        "source_type": "google_voice_bundle",
        "parent_document_id": "voice_1",
        "document_count": 3,
    }

    inspect_output = io.StringIO()
    with redirect_stdout(inspect_output):
        inspect_result = module.main(
            [
                "--action",
                "package-inspect",
                "--input-path",
                str(manifest_path),
                "--json",
            ]
        )

    assert inspect_result == 0
    inspect_payload = json.loads(inspect_output.getvalue())
    assert inspect_payload["collection_overview"][1]["id"] == "google_voice_bundle_voice_1"
    assert inspect_payload["collection_overview"][1]["document_count"] == 3

    report_output = io.StringIO()
    with redirect_stdout(report_output):
        report_result = module.main(
            [
                "--action",
                "package-report",
                "--input-path",
                str(manifest_path),
                "--report-format",
                "text",
            ]
        )

    assert report_result == 0
    rendered = report_output.getvalue()
    assert "Collection Overview:" in rendered
    assert "google_voice_bundle_voice_1 [google_voice_bundle] (3 docs)" in rendered


def test_ipfs_datasets_cli_dispatches_workspace_command(tmp_path: Path, monkeypatch) -> None:
    bundle_path = _build_workspace_bundle(tmp_path)

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
                    "workspace",
                    "--json",
                    "--input-path",
                    str(bundle_path),
                    "--action",
                    "summary",
                ],
            )
            module.main()
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["workspace_name"] == "CLI Workspace"
    assert payload["bm25_document_count"] == 1


def test_workspace_cli_can_export_email_bundle_json(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    export_path = _build_email_export_json(tmp_path)
    output_parquet = tmp_path / "email_bundle.parquet"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--action",
                "export",
                "--input-type",
                "email-export",
                "--input-path",
                str(export_path),
                "--output-parquet",
                str(output_parquet),
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["workspace_name"] == "INBOX"
    assert payload["input_type"] == "email-export"
    assert payload["input_type_resolution"] == "explicit"
    assert payload["document_count"] == 1
    assert Path(payload["export"]["parquet_path"]).is_file()


def test_workspace_cli_can_export_email_bundle_without_input_type(tmp_path: Path) -> None:
    module = _load_workspace_cli_module()
    export_path = _build_email_export_json(tmp_path)
    output_parquet = tmp_path / "email_bundle_autodetect.parquet"

    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            [
                "--action",
                "export",
                "--input-path",
                str(export_path),
                "--output-parquet",
                str(output_parquet),
                "--json",
            ]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["workspace_name"] == "INBOX"
    assert payload["input_type"] == "email-export"
    assert payload["input_type_resolution"] == "auto"
    assert Path(payload["export"]["parquet_path"]).is_file()


def test_ipfs_datasets_cli_dispatches_workspace_export_command(tmp_path: Path, monkeypatch) -> None:
    export_path = _build_email_export_json(tmp_path)
    output_parquet = tmp_path / "email_bundle_dispatch.parquet"

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
                    "workspace",
                    "--action",
                    "export",
                    "--input-path",
                    str(export_path),
                    "--output-parquet",
                    str(output_parquet),
                    "--json",
                ],
            )
            module.main()
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["workspace_id"] == "inbox"
    assert payload["input_type_resolution"] == "auto"
    assert payload["input_type"] == "email-export"
    assert Path(payload["export"]["parquet_path"]).is_file()


def test_ipfs_datasets_cli_dispatches_workspace_export_google_voice_autodetect(tmp_path: Path, monkeypatch) -> None:
    export_path = _build_google_voice_manifest_json(tmp_path)
    output_parquet = tmp_path / "voice_bundle_dispatch.parquet"

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
                    "workspace",
                    "--action",
                    "export",
                    "--input-path",
                    str(export_path),
                    "--output-parquet",
                    str(output_parquet),
                    "--json",
                ],
            )
            module.main()
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["input_type"] == "google-voice-manifest"
    assert payload["input_type_resolution"] == "auto"
    assert payload["source_type"] == "google_voice"
    assert payload["document_count"] == 3
    assert payload["bm25_document_count"] == 3
    assert Path(payload["export"]["parquet_path"]).is_file()


def test_ipfs_datasets_cli_dispatches_workspace_export_discord_autodetect(tmp_path: Path, monkeypatch) -> None:
    export_path = _build_discord_export_json(tmp_path)
    output_parquet = tmp_path / "discord_bundle_dispatch.parquet"

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
                    "workspace",
                    "--action",
                    "export",
                    "--input-path",
                    str(export_path),
                    "--output-parquet",
                    str(output_parquet),
                    "--json",
                ],
            )
            module.main()
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["input_type"] == "discord-export"
    assert payload["input_type_resolution"] == "auto"
    assert payload["source_type"] == "discord"
    assert Path(payload["export"]["parquet_path"]).is_file()
