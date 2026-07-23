from pathlib import Path

from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    WorkspaceDatasetPackager,
    inspect_packaged_workspace_bundle,
    iter_packaged_workspace_chain,
    load_packaged_workspace_dataset,
    load_packaged_workspace_summary_view,
    render_packaged_workspace_report,
)


def test_packaged_workspace_bundle_roundtrip(tmp_path: Path) -> None:
    dataset = WorkspaceDatasetBuilder().build_from_workspace(
        {
            "workspace_id": "ws-packaged-01",
            "workspace_name": "Workspace Packaged",
            "documents": [
                {"id": "doc_1", "title": "Memo", "text": "Notes from the workspace."}
            ],
        }
    )
    package = WorkspaceDatasetPackager().package(
        dataset,
        tmp_path / "bundle",
        package_name="workspace_bundle",
        include_car=False,
    )
    manifest_path = Path(package["manifest_json_path"])

    summary_view = load_packaged_workspace_summary_view(manifest_path)
    assert summary_view["document_count"] == 1
    assert summary_view["collection_count"] >= 0

    inspection = inspect_packaged_workspace_bundle(manifest_path)
    assert inspection["document_count"] == 1
    assert inspection["piece_count"] >= 1

    report_text = render_packaged_workspace_report(manifest_path, report_format="text")
    assert "Packaged Workspace Dataset Report" in report_text

    loaded = load_packaged_workspace_dataset(manifest_path)
    assert len(loaded.get("documents") or []) == 1

    chain = iter_packaged_workspace_chain(manifest_path)
    assert chain
