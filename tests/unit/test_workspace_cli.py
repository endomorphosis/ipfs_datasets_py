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