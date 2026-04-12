from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path


from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    export_workspace_dataset_single_parquet,
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
    manifest_path = tmp_path / "google_voice_manifest.json"
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
                        "bundle_dir": "/tmp/google_voice_bundle_1",
                        "text_content": "Tenant: Please send the inspection notice.\nAdvocate: I will send it tonight.",
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
    assert "- Document Count: 1" in rendered


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