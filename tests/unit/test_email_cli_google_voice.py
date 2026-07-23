from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path


def _build_voice_takeout(tmp_path: Path) -> Path:
    voice_dir = tmp_path / "Takeout" / "Voice" / "Messages" / "thread-001"
    voice_dir.mkdir(parents=True)
    (voice_dir / "Text - Advocate.html").write_text(
        """
        <html>
          <head><title>Text conversation with (503) 555-0100</title></head>
          <body>
            <div>2026-03-24T04:56:14Z</div>
            <div>Tenant: Please send the inspection notice.</div>
            <div>Advocate: I will send it tonight.</div>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    (voice_dir / "metadata.json").write_text('{"participants":["(503) 555-0100"]}', encoding="utf-8")
    return tmp_path


def _build_voice_vault_export(tmp_path: Path) -> Path:
    voice_dir = tmp_path / "Exports" / "Voice" / "users" / "tenant@example.com" / "conversation-001"
    voice_dir.mkdir(parents=True)
    (voice_dir / "conversation.html").write_text(
        """
        <html>
          <head><title>Voicemail from (503) 555-0101</title></head>
          <body>
            <div>2026-03-25T09:15:00Z</div>
            <div>Voicemail transcript: Please call me back about the inspection.</div>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    (voice_dir / "call-log.json").write_text(
        '{"direction":"incoming","participants":["(503) 555-0101"]}',
        encoding="utf-8",
    )
    (voice_dir / "voicemail.mp3").write_bytes(b"vault-audio")
    return tmp_path


def _build_voice_data_export(tmp_path: Path) -> Path:
    voice_dir = tmp_path / "workspace-export" / "voice" / "tenant-001"
    voice_dir.mkdir(parents=True)
    (voice_dir / "messages.txt").write_text(
        "2026-03-26T12:30:00Z Tenant +1 (503) 555-0102 asked for a copy of the notice.",
        encoding="utf-8",
    )
    (voice_dir / "metadata.json").write_text(
        '{"participants":["+1 (503) 555-0102"],"type":"text"}',
        encoding="utf-8",
    )
    return tmp_path


def _load_email_cli_module():
    import importlib.util

    module_path = (
        Path(__file__).resolve().parents[2]
        / "ipfs_datasets_py"
        / "cli"
        / "email_cli.py"
    )
    spec = importlib.util.spec_from_file_location("email_cli_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_email_cli_google_voice_summary(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    source = _build_voice_takeout(tmp_path)

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(["google-voice", str(source), "--summary-only"])
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert payload["event_count"] == 1
    assert "text_message" in payload["event_types"]


def test_email_cli_google_voice_materialize(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    source = _build_voice_takeout(tmp_path / "source")
    output_dir = tmp_path / "bundles"

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(["google-voice", str(source), "--materialize", "--output-dir", str(output_dir)])
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert payload["event_count"] == 1
    assert Path(payload["manifest_path"]).is_file()
    bundle = payload["bundles"][0]
    evidence_record = payload["mediator_evidence_records"][0]
    assert Path(bundle["event_json_path"]).is_file()
    assert Path(bundle["transcript_path"]).is_file()
    assert Path(bundle["source_html_path"]).is_file()
    assert evidence_record["source"] == "google_voice_takeout"
    assert evidence_record["metadata"]["event_id"] == bundle["event_id"]


def test_email_cli_google_voice_vault_summary(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    source = _build_voice_vault_export(tmp_path)

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(["google-voice-vault", str(source), "--summary-only"])
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert payload["source_kind"] == "vault_export"
    assert payload["event_count"] == 1
    assert "voicemail" in payload["event_types"]


def test_email_cli_google_voice_data_export_materialize(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    source = _build_voice_data_export(tmp_path / "source")
    output_dir = tmp_path / "bundles"

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(
                [
                    "google-voice-data-export",
                    str(source),
                    "--materialize",
                    "--output-dir",
                    str(output_dir),
                ]
            )
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert payload["source_kind"] == "data_export"
    assert payload["event_count"] == 1
    assert Path(payload["manifest_path"]).is_file()
    assert payload["mediator_evidence_records"][0]["source"] == "google_voice_data_export"


def test_email_cli_google_voice_watch_once(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    _build_voice_takeout(watch_dir / "incoming-001")
    output_dir = tmp_path / "hydrated"

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(
                [
                    "google-voice-watch",
                    str(watch_dir),
                    "--output-dir",
                    str(output_dir),
                    "--source-kind",
                    "takeout",
                    "--once",
                ]
            )
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert payload["processed_count"] == 1
    assert Path(payload["processed"][0]["manifest_path"]).is_file()
