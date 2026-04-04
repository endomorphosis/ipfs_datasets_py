from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import zipfile


def _load_email_cli_module():
    import importlib.util

    module_path = (
        Path(__file__).resolve().parents[2]
        / "ipfs_datasets_py"
        / "cli"
        / "email_cli.py"
    )
    spec = importlib.util.spec_from_file_location("email_cli_takeout_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_google_voice_takeout_url_from_product_id() -> None:
    module = _load_email_cli_module()
    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(
                [
                    "google-voice-takeout-url",
                    "--product-id",
                    "voice",
                    "--dest",
                    "drive",
                ]
            )
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert payload["product_ids"] == ["voice"]
    assert payload["takeout_url"].startswith("https://takeout.google.com/settings/takeout/custom/voice")


def test_google_voice_takeout_url_from_saved_page_source(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    page_source = tmp_path / "takeout_page.html"
    page_source.write_text(
        """
        <html>
          <body>
            <div data-id="gmail"></div>
            <div data-id="voice"></div>
            <div data-id="my_activity"></div>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(
                [
                    "google-voice-takeout-url",
                    "--page-source",
                    str(page_source),
                    "--dest",
                    "dropbox",
                    "--frequency",
                    "2_months",
                ]
            )
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["candidate_voice_product_ids"] == ["voice"]
    assert payload["product_ids"] == ["voice"]
    assert "dest=dropbox" in payload["takeout_url"]
    assert "frequency=2_months" in payload["takeout_url"]


def test_google_voice_takeout_capture_command_with_mock(tmp_path: Path, monkeypatch) -> None:
    module = _load_email_cli_module()
    output_path = tmp_path / "capture.json"

    def _fake_capture(**_kwargs):
        return {
            "status": "success",
            "download_status": "captured",
            "download_path": str(tmp_path / "voice-takeout.zip"),
        }

    import sys

    helper_module = sys.modules.get("ipfs_datasets_py.processors.multimedia.google_takeout_automation")
    if helper_module is None:
        import importlib

        helper_module = importlib.import_module("ipfs_datasets_py.processors.multimedia.google_takeout_automation")
    monkeypatch.setattr(helper_module, "open_takeout_and_capture_download", _fake_capture)

    try:
        module.main(
            [
                "google-voice-takeout-capture",
                "--product-id",
                "voice",
                "--output",
                str(output_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["browser_capture"]["download_status"] == "captured"


def test_google_voice_takeout_poll_finds_archive(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    archive_path = downloads_dir / "voice-export.zip"
    archive_path.write_bytes(b"zip-bytes")
    output = io.StringIO()

    with redirect_stdout(output):
        try:
            module.main(
                [
                    "google-voice-takeout-poll",
                    "--downloads-dir",
                    str(downloads_dir),
                    "--timeout-ms",
                    "50",
                ]
            )
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["status"] == "success"
    assert payload["download_path"] == str(archive_path)


def test_google_voice_takeout_drive_command_with_mock(tmp_path: Path, monkeypatch) -> None:
    module = _load_email_cli_module()
    output_path = tmp_path / "drive.json"
    captured = {}

    def _fake_drive(**kwargs):
        captured.update(kwargs)
        return {
            "status": "success",
            "artifact": {"id": "file-1", "name": "takeout-voice.zip"},
            "download": {"output_path": str(tmp_path / "takeout-voice.zip")},
        }

    import sys

    helper_module = sys.modules.get("ipfs_datasets_py.processors.multimedia.google_takeout_automation")
    if helper_module is None:
        import importlib

        helper_module = importlib.import_module("ipfs_datasets_py.processors.multimedia.google_takeout_automation")
    monkeypatch.setattr(helper_module, "poll_drive_and_optionally_download", _fake_drive)

    try:
        module.main(
            [
                "google-voice-takeout-drive",
                "--client-secrets",
                str(tmp_path / "client.json"),
                "--account-hint",
                "user@gmail.com",
                "--download-dir",
                str(tmp_path),
                "--modified-after",
                "2026-04-04T00:00:00Z",
                "--output",
                str(output_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["artifact"]["name"] == "takeout-voice.zip"
    assert captured["modified_after"] == "2026-04-04T00:00:00Z"


def test_google_voice_takeout_drive_folder_artifact_is_supported(tmp_path: Path, monkeypatch) -> None:
    module = _load_email_cli_module()
    output_path = tmp_path / "drive-folder.json"

    def _fake_drive(**_kwargs):
        return {
            "status": "success",
            "folder_artifact": {"id": "folder-1", "name": "Takeout"},
            "artifact": {"id": "file-2", "name": "takeout-part-001.zip"},
            "download": {"output_path": str(tmp_path / "takeout-part-001.zip")},
            "download_status": "captured",
        }

    import sys

    helper_module = sys.modules.get("ipfs_datasets_py.processors.multimedia.google_takeout_automation")
    if helper_module is None:
        import importlib

        helper_module = importlib.import_module("ipfs_datasets_py.processors.multimedia.google_takeout_automation")
    monkeypatch.setattr(helper_module, "poll_drive_and_optionally_download", _fake_drive)

    try:
        module.main(
            [
                "google-voice-takeout-drive",
                "--client-secrets",
                str(tmp_path / "client.json"),
                "--account-hint",
                "user@gmail.com",
                "--download-dir",
                str(tmp_path),
                "--output",
                str(output_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["folder_artifact"]["name"] == "Takeout"
    assert payload["artifact"]["name"] == "takeout-part-001.zip"


def test_google_voice_takeout_status_summary_and_json(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    manifest = tmp_path / "takeout_acquisition_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "hydrated",
                "case_slug": "voice-case",
                "product_ids": ["voice"],
                "delivery_destination": "drive",
                "downloads_dir": str(tmp_path / "downloads"),
                "capture_json_path": str(tmp_path / "capture.json"),
                "page_source_path": str(tmp_path / "takeout_page.html"),
                "final_archive_path": str(tmp_path / "voice-takeout.zip"),
                "drive_fallback": {"enabled": True},
                "events": [{"type": "hydrated", "timestamp": "2026-04-04T12:00:00Z"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    text_output = io.StringIO()
    with redirect_stdout(text_output):
        try:
            module.main(["google-voice-takeout-status", str(manifest)])
        except SystemExit as exc:
            assert exc.code == 0

    assert "Status: hydrated" in text_output.getvalue()
    assert "Final archive:" in text_output.getvalue()

    json_output = io.StringIO()
    with redirect_stdout(json_output):
        try:
            module.main(["google-voice-takeout-status", str(manifest), "--json"])
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(json_output.getvalue())
    assert payload["status"] == "hydrated"
    assert payload["case_slug"] == "voice-case"


def test_google_voice_takeout_doctor_pending_and_complete_states(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    pending_manifest = tmp_path / "pending.json"
    pending_manifest.write_text(
        json.dumps(
            {
                "status": "pending_archive",
                "downloads_dir": str(tmp_path / "downloads"),
                "events": [{"type": "pending_archive", "timestamp": "2026-04-04T12:00:00Z"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    pending_output = io.StringIO()
    with redirect_stdout(pending_output):
        try:
            module.main(["google-voice-takeout-doctor", str(pending_manifest)])
        except SystemExit as exc:
            assert exc.code == 0

    assert "Diagnosis: waiting_for_archive" in pending_output.getvalue()
    assert "--resume-from-downloads" in pending_output.getvalue()

    complete_manifest = tmp_path / "complete.json"
    complete_manifest.write_text(
        json.dumps(
            {
                "status": "hydrated",
                "final_archive_path": str(tmp_path / "voice-takeout.zip"),
                "events": [{"type": "hydrated", "timestamp": "2026-04-04T12:30:00Z"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    complete_json = io.StringIO()
    with redirect_stdout(complete_json):
        try:
            module.main(["google-voice-takeout-doctor", str(complete_manifest), "--json"])
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(complete_json.getvalue())
    assert payload["diagnosis"] == "complete"


def test_google_voice_takeout_history_lists_snapshots(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    manifest = tmp_path / "takeout_acquisition_manifest.json"
    history_dir = tmp_path / "takeout_acquisition_history"
    history_dir.mkdir()
    manifest.write_text("{}", encoding="utf-8")
    (history_dir / "20260404_120000_initialized.json").write_text(
        json.dumps({"status": "initialized", "updated_at": "2026-04-04T12:00:00Z"}),
        encoding="utf-8",
    )
    (history_dir / "20260404_123000_hydrated.json").write_text(
        json.dumps({"status": "hydrated", "updated_at": "2026-04-04T12:30:00Z"}),
        encoding="utf-8",
    )

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(["google-voice-takeout-history", str(manifest)])
        except SystemExit as exc:
            assert exc.code == 0

    assert "Snapshots: 2" in output.getvalue()
    assert "hydrated" in output.getvalue()


def test_google_voice_takeout_prune_dry_run_and_apply(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    manifest = tmp_path / "takeout_acquisition_manifest.json"
    history_dir = tmp_path / "takeout_acquisition_history"
    history_dir.mkdir()
    manifest.write_text("{}", encoding="utf-8")
    for index in range(3):
        (history_dir / f"20260404_12000{index}_state.json").write_text(
            json.dumps({"status": f"state-{index}"}),
            encoding="utf-8",
        )

    dry_run_output = io.StringIO()
    with redirect_stdout(dry_run_output):
        try:
            module.main(["google-voice-takeout-prune", str(manifest), "--keep", "2"])
        except SystemExit as exc:
            assert exc.code == 0

    assert "Dry-run" in dry_run_output.getvalue()
    assert len(list(history_dir.glob("*.json"))) == 3

    apply_output = io.StringIO()
    with redirect_stdout(apply_output):
        try:
            module.main(["google-voice-takeout-prune", str(manifest), "--keep", "2", "--apply"])
        except SystemExit as exc:
            assert exc.code == 0

    assert "Applied" in apply_output.getvalue()
    assert len(list(history_dir.glob("*.json"))) == 2


def test_google_voice_takeout_case_summary_reports_history_and_archive(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    history_dir = downloads_dir / "takeout_acquisition_history"
    history_dir.mkdir()
    manifest = downloads_dir / "takeout_acquisition_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "hydrated",
                "case_slug": "case-voice-001",
                "delivery_destination": "drive",
                "product_ids": ["voice"],
                "events": [{"type": "hydrated", "timestamp": "2026-04-04T12:30:00Z"}],
                "final_archive_path": str(downloads_dir / "voice.zip"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for index in range(2):
        (history_dir / f"20260404_12000{index}_state.json").write_text("{}", encoding="utf-8")

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(["google-voice-takeout-case-summary", str(manifest)])
        except SystemExit as exc:
            assert exc.code == 0

    text = output.getvalue()
    assert "Case slug: case-voice-001" in text
    assert "History snapshots: 2" in text
    assert "Final archive:" in text


def test_google_voice_takeout_case_report_writes_markdown_and_html(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    manifest = downloads_dir / "takeout_acquisition_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "hydrated",
                "case_slug": "case-report-001",
                "delivery_destination": "drive",
                "product_ids": ["voice"],
                "events": [{"type": "hydrated", "timestamp": "2026-04-04T12:30:00Z"}],
                "final_archive_path": str(downloads_dir / "voice.zip"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    markdown_path = tmp_path / "report.md"
    html_path = tmp_path / "report.html"

    try:
        module.main(
            [
                "google-voice-takeout-case-report",
                str(manifest),
                "--format",
                "markdown",
                "--output",
                str(markdown_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 0

    try:
        module.main(
            [
                "google-voice-takeout-case-report",
                str(manifest),
                "--format",
                "html",
                "--output",
                str(html_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 0

    assert "# Google Voice Takeout Case Report: case-report-001" in markdown_path.read_text(encoding="utf-8")
    assert "<html" in html_path.read_text(encoding="utf-8").lower()


def test_google_voice_takeout_case_bundle_collects_manifest_history_and_reports(tmp_path: Path) -> None:
    module = _load_email_cli_module()
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    history_dir = downloads_dir / "takeout_acquisition_history"
    history_dir.mkdir()
    manifest = downloads_dir / "takeout_acquisition_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "hydrated",
                "case_slug": "case-bundle-001",
                "delivery_destination": "drive",
                "product_ids": ["voice"],
                "events": [{"type": "hydrated", "timestamp": "2026-04-04T12:30:00Z"}],
                "final_archive_path": str(downloads_dir / "voice.zip"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for index in range(3):
        (history_dir / f"20260404_12000{index}_state.json").write_text("{}", encoding="utf-8")

    bundle_root = tmp_path / "bundles"
    output = io.StringIO()
    with redirect_stdout(output):
        try:
            module.main(
                [
                    "google-voice-takeout-case-bundle",
                    str(manifest),
                    "--output-dir",
                    str(bundle_root),
                    "--history-limit",
                    "2",
                    "--bundle-format",
                    "zip",
                    "--bundle-format",
                    "parquet",
                    "--bundle-format",
                    "car",
                ]
            )
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    bundle_dir = Path(payload["bundle_dir"])
    bundle_artifacts = payload["bundle_artifacts"]
    assert bundle_dir.is_dir()
    assert payload["bundle_formats"] == ["dir", "zip", "parquet", "car"]
    assert (bundle_dir / "takeout_acquisition_manifest.json").is_file()
    assert (bundle_dir / "takeout-case-report.md").is_file()
    assert (bundle_dir / "takeout-case-report.html").is_file()
    assert len(list((bundle_dir / "takeout_acquisition_history").glob("*.json"))) == 2
    assert Path(bundle_artifacts["zip"]).is_file()
    assert Path(bundle_artifacts["parquet"]).is_file()
    assert Path(bundle_artifacts["car"]).is_file()

    with zipfile.ZipFile(bundle_artifacts["zip"]) as archive:
        names = archive.namelist()
    assert any(name.endswith("takeout_acquisition_manifest.json") for name in names)
    assert any(name.endswith("takeout-case-report.md") for name in names)

    import pyarrow.parquet as pq

    table = pq.read_table(bundle_artifacts["parquet"])
    rows = table.to_pylist()
    assert any(row["record_type"] == "case_summary" for row in rows)
    assert any(row["record_type"] == "history_snapshot" for row in rows)
    assert payload["bundle_artifacts"]["car_result"]["success"] is True
