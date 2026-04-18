from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import CanonicalLegalCorpus
from ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery import LegalSourceRecoveryWorkflow
from ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery_promotion import (
    build_recovery_manifest_promotion_row,
    build_recovery_manifest_release_plan,
    load_recovery_manifest,
    merge_recovery_manifests_into_canonical_datasets,
    merge_recovery_manifest_into_canonical_dataset,
    promote_recovery_manifest_to_canonical_bundle,
    _resolve_hf_token,
    _upload_huggingface_parquet,
)


class _FakeLiveSearcher:
    def search(self, query: str, max_results: int = 20, **kwargs):
        return {
            "results": [
                {
                    "title": "Minnesota Statutes 518.17",
                    "url": "https://www.revisor.mn.gov/statutes/cite/518.17",
                    "source": "brave",
                }
            ]
        }


class _FakeArchiveSearcher:
    def search_with_indexes(self, query: str, jurisdiction_type: str | None = None, state_code: str | None = None, max_results: int = 50):
        return {
            "results": [
                {
                    "title": "Archived Minnesota Statutes 518.17",
                    "url": "https://archive.org/details/mn-stat-518-17",
                    "source": "common_crawl_indexes",
                }
            ]
        }


class _FakeArchiver:
    async def archive_urls_parallel(self, urls, jurisdiction=None, state_code=None):
        return []


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_recovery_manifest_can_be_promoted_to_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )

    workflow = LegalSourceRecoveryWorkflow(
        live_searcher=_FakeLiveSearcher(),
        archive_searcher=_FakeArchiveSearcher(),
        archiver=_FakeArchiver(),
        now_factory=lambda: datetime(2024, 1, 2, 3, 4, 5),
    )

    result = await workflow.recover_unresolved_citation(
        citation_text="Minn. Stat. § 518.17",
        normalized_citation="Minn. Stat. § 518.17",
        corpus_key="state_laws",
        state_code="MN",
        metadata={"candidate_corpora": ["state_laws"]},
        publish_to_hf=False,
    )

    manifest = load_recovery_manifest(result.manifest_path or "")
    row = build_recovery_manifest_promotion_row(manifest)
    bundle = promote_recovery_manifest_to_canonical_bundle(result.manifest_path or "")

    assert manifest["corpus_key"] == "state_laws"
    assert row["hf_dataset_id"] == "justicedao/ipfs_state_laws"
    assert row["target_parquet_path"] == "state_laws_parquet_cid/STATE-MN.parquet"
    assert row["primary_candidate_url"] == "https://www.revisor.mn.gov/statutes/cite/518.17"
    assert bundle["row_count"] == 1
    assert Path(bundle["json_path"]).exists()
    assert Path(bundle["metadata_path"]).exists()
    assert Path(bundle["parquet_path"]).exists()

    rows = json.loads(Path(bundle["json_path"]).read_text(encoding="utf-8"))
    assert rows[0]["normalized_citation"] == "Minn. Stat. § 518.17"
    assert rows[0]["promotion_output_dir"].endswith("canonical_promotion")

    merge_report = merge_recovery_manifest_into_canonical_dataset(result.manifest_path or "")
    merge_report_repeat = merge_recovery_manifest_into_canonical_dataset(result.manifest_path or "")
    second_manifest_dir = Path(result.manifest_path or "").parent.parent / "second-run-mn-518-17"
    second_manifest_dir.mkdir(parents=True)
    second_manifest_path = second_manifest_dir / "recovery_manifest.json"
    second_manifest_payload = json.loads(Path(result.manifest_path or "").read_text(encoding="utf-8"))
    second_manifest_payload["manifest_directory"] = str(second_manifest_dir)
    second_manifest_path.write_text(json.dumps(second_manifest_payload, indent=2), encoding="utf-8")
    merge_report_second_manifest = merge_recovery_manifest_into_canonical_dataset(second_manifest_path)

    assert merge_report["status"] == "success"
    assert Path(merge_report["target_local_parquet_path"]).exists()
    assert Path(merge_report["merge_report_path"]).exists()
    assert merge_report_repeat["merged_row_count"] == 1
    assert merge_report_repeat["deduplicated_count"] >= 1
    assert merge_report_second_manifest["merged_row_count"] == 1
    assert merge_report_second_manifest["deduplicated_count"] >= 1

    import pyarrow.parquet as pq

    merged_rows = pq.read_table(merge_report["target_local_parquet_path"]).to_pylist()
    assert len(merged_rows) == 1
    assert merged_rows[0]["normalized_citation"] == "Minn. Stat. § 518.17"


@pytest.mark.anyio
async def test_recovery_manifest_merge_can_hydrate_current_hf_parquet(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )

    workflow = LegalSourceRecoveryWorkflow(
        live_searcher=_FakeLiveSearcher(),
        archive_searcher=_FakeArchiveSearcher(),
        archiver=_FakeArchiver(),
        now_factory=lambda: datetime(2024, 1, 2, 3, 4, 5),
    )

    result = await workflow.recover_unresolved_citation(
        citation_text="Minn. Stat. § 518.17",
        normalized_citation="Minn. Stat. § 518.17",
        corpus_key="state_laws",
        state_code="MN",
        metadata={"candidate_corpora": ["state_laws"]},
        publish_to_hf=False,
    )

    import pyarrow as pa
    import pyarrow.parquet as pq

    remote_hf_parquet = tmp_path / "hf-current" / "STATE-MN.parquet"
    remote_hf_parquet.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_type": "legal_source_recovery_manifest",
                    "corpus_key": "state_laws",
                    "hf_dataset_id": "justicedao/ipfs_state_laws",
                    "normalized_citation": "Minn. Stat. § 518.175",
                    "primary_candidate_url": "https://www.revisor.mn.gov/statutes/cite/518.175",
                    "target_parquet_path": "state_laws_parquet_cid/STATE-MN.parquet",
                }
            ]
        ),
        remote_hf_parquet,
    )

    def _fake_hf_downloader(**kwargs):
        assert kwargs["repo_id"] == "justicedao/ipfs_state_laws"
        assert kwargs["repo_path"] == "state_laws_parquet_cid/STATE-MN.parquet"
        assert kwargs["hf_revision"] == "main"
        return remote_hf_parquet

    merge_report = merge_recovery_manifest_into_canonical_dataset(
        result.manifest_path or "",
        hydrate_from_hf=True,
        hf_revision="main",
        hf_downloader=_fake_hf_downloader,
    )

    assert merge_report["status"] == "success"
    assert merge_report["existing_rows_source"] == "huggingface_dataset_parquet"
    assert merge_report["upload_ready"] is True
    assert merge_report["existing_row_count"] == 1
    assert merge_report["incoming_row_count"] == 1
    assert merge_report["merged_row_count"] == 2
    assert merge_report["target_parquet_path"] == "state_laws_parquet_cid/STATE-MN.parquet"
    assert merge_report["hf_source_path"] == str(remote_hf_parquet.resolve())

    merged_rows = pq.read_table(merge_report["target_local_parquet_path"]).to_pylist()
    normalized_citations = {str(row.get("normalized_citation") or "") for row in merged_rows}
    assert normalized_citations == {"Minn. Stat. § 518.17", "Minn. Stat. § 518.175"}


@pytest.mark.anyio
async def test_recovery_manifest_merge_publishes_only_after_hf_hydration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )

    workflow = LegalSourceRecoveryWorkflow(
        live_searcher=_FakeLiveSearcher(),
        archive_searcher=_FakeArchiveSearcher(),
        archiver=_FakeArchiver(),
        now_factory=lambda: datetime(2024, 1, 2, 3, 4, 5),
    )

    result = await workflow.recover_unresolved_citation(
        citation_text="Minn. Stat. § 518.17",
        normalized_citation="Minn. Stat. § 518.17",
        corpus_key="state_laws",
        state_code="MN",
        metadata={"candidate_corpora": ["state_laws"]},
        publish_to_hf=False,
    )

    unsafe_report = merge_recovery_manifest_into_canonical_dataset(
        result.manifest_path or "",
        publish_merged_to_hf=True,
    )

    assert unsafe_report["status"] == "error"
    assert "requires hydrate_from_hf=True" in unsafe_report["error"]

    import pyarrow as pa
    import pyarrow.parquet as pq

    remote_hf_parquet = tmp_path / "hf-current" / "STATE-MN.parquet"
    remote_hf_parquet.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_type": "legal_source_recovery_manifest",
                    "corpus_key": "state_laws",
                    "hf_dataset_id": "justicedao/ipfs_state_laws",
                    "normalized_citation": "Minn. Stat. § 518.175",
                    "primary_candidate_url": "https://www.revisor.mn.gov/statutes/cite/518.175",
                    "target_parquet_path": "state_laws_parquet_cid/STATE-MN.parquet",
                }
            ]
        ),
        remote_hf_parquet,
    )

    def _fake_hf_downloader(**kwargs):
        return remote_hf_parquet

    def _fake_hf_uploader(**kwargs):
        assert Path(kwargs["local_path"]).is_file()
        assert kwargs["repo_id"] == "justicedao/ipfs_state_laws"
        assert kwargs["repo_path"] == "state_laws_parquet_cid/STATE-MN.parquet"
        assert kwargs["hf_token"] == "test-token"
        assert kwargs["commit_message"] == "Merge citation recovery"
        return {
            "status": "success",
            "repo_id": kwargs["repo_id"],
            "path_in_repo": kwargs["repo_path"],
            "upload_commit": "https://huggingface.co/datasets/justicedao/ipfs_state_laws/commit/test",
        }

    safe_report = merge_recovery_manifest_into_canonical_dataset(
        result.manifest_path or "",
        hydrate_from_hf=True,
        publish_merged_to_hf=True,
        hf_token="test-token",
        hf_commit_message="Merge citation recovery",
        hf_downloader=_fake_hf_downloader,
        hf_uploader=_fake_hf_uploader,
    )

    assert safe_report["status"] == "success"
    assert safe_report["upload_ready"] is True
    assert safe_report["published_merged_to_hf"] is True
    assert safe_report["publish_report"]["path_in_repo"] == "state_laws_parquet_cid/STATE-MN.parquet"


def test_hf_parquet_hydration_uses_known_repo_path_aliases(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import legal_source_recovery_promotion as promotion

    downloaded_paths = []

    def _fake_download(**kwargs):
        downloaded_paths.append(kwargs["repo_path"])
        if kwargs["repo_path"] == "uscode_parquet/uscode.parquet":
            raise FileNotFoundError("missing stale registry path")
        target = tmp_path / "laws.parquet"
        target.write_bytes(b"PAR1")
        return target

    monkeypatch.setattr(promotion, "_download_huggingface_parquet", _fake_download)

    downloaded_path, resolved_path = promotion._download_huggingface_parquet_with_repo_path(
        repo_id="justicedao/ipfs_uscode",
        repo_path="uscode_parquet/uscode.parquet",
    )

    assert downloaded_path == tmp_path / "laws.parquet"
    assert resolved_path == "uscode_parquet/laws.parquet"
    assert downloaded_paths == ["uscode_parquet/uscode.parquet", "uscode_parquet/laws.parquet"]


def test_hf_upload_uses_environment_token_alias(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import legal_source_recovery_promotion as promotion

    local_path = tmp_path / "STATE-MN.parquet"
    local_path.write_bytes(b"PAR1")
    captured = {}

    class _FakeHfApi:
        def __init__(self, token=None):
            captured["token"] = token

        def upload_file(self, **kwargs):
            captured["upload"] = dict(kwargs)
            return "https://huggingface.co/datasets/justicedao/ipfs_state_laws/commit/env-token"

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HUGGINGFACEHUB_API_TOKEN", "env-write-token")
    monkeypatch.setattr(promotion, "HfApi", _FakeHfApi, raising=False)
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(HfApi=_FakeHfApi))

    report = _upload_huggingface_parquet(
        local_path=local_path,
        repo_id="justicedao/ipfs_state_laws",
        repo_path="state_laws_parquet_cid/STATE-MN.parquet",
    )

    assert report["status"] == "success"
    assert captured["token"] == "env-write-token"
    assert captured["upload"]["repo_type"] == "dataset"
    assert captured["upload"]["path_in_repo"] == "state_laws_parquet_cid/STATE-MN.parquet"


def test_hf_token_resolver_uses_secret_keyring(monkeypatch):
    token_names = (
        "HF_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGINGFACEHUB_API_TOKEN",
        "HUGGINGFACE_API_TOKEN",
        "HUGGINGFACE_API_KEY",
        "IPFS_DATASETS_PY_HF_API_TOKEN",
        "HF_API_TOKEN",
    )
    for name in token_names:
        monkeypatch.delenv(name, raising=False)

    class _EmptyVault:
        def get(self, name):
            return ""

    keyring_values = {
        ("huggingface_hub", "default"): "keyring-write-token",
    }
    fake_keyring = types.SimpleNamespace(
        get_password=lambda service, account: keyring_values.get((service, account), "")
    )
    fake_vault_module = types.SimpleNamespace(get_secrets_vault=lambda: _EmptyVault())

    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.mcp_server.secrets_vault", fake_vault_module)

    assert _resolve_hf_token() == "keyring-write-token"


def test_hf_folder_publisher_uses_shared_keyring_resolver(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_data import legal_source_recovery_promotion as promotion

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "repair" / "publish_parquet_to_hf.py"
    spec = importlib.util.spec_from_file_location("publish_parquet_to_hf_under_test", script_path)
    assert spec is not None and spec.loader is not None
    publish_parquet_to_hf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publish_parquet_to_hf)

    local_dir = tmp_path / "manifest"
    local_dir.mkdir()
    (local_dir / "recovery_manifest.json").write_text("{}", encoding="utf-8")
    captured = {}

    class _FakeHfApi:
        def __init__(self, token=None):
            captured["token"] = token

        def upload_folder(self, **kwargs):
            captured["upload"] = dict(kwargs)
            return "https://huggingface.co/datasets/justicedao/ipfs_state_laws/commit/keyring"

    monkeypatch.setattr(promotion, "_resolve_hf_token", lambda token=None: "shared-keyring-token")
    monkeypatch.setattr(publish_parquet_to_hf, "HfApi", _FakeHfApi)

    report = publish_parquet_to_hf.publish(
        local_dir=local_dir,
        repo_id="justicedao/ipfs_state_laws",
        commit_message="Track missing legal source",
        create_repo=False,
        token=None,
        path_in_repo="source_recovery/test",
        allow_patterns=["*.json"],
        do_verify=False,
        cid_column="cid",
    )

    assert report["repo_id"] == "justicedao/ipfs_state_laws"
    assert captured["token"] == "shared-keyring-token"
    assert captured["upload"]["path_in_repo"] == "source_recovery/test"


@pytest.mark.anyio
async def test_recovery_manifest_batch_merge_hydrates_once_per_target(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )

    manifest_paths = []
    for citation, url in [
        ("Minn. Stat. § 518.17", "https://www.revisor.mn.gov/statutes/cite/518.17"),
        ("Minn. Stat. § 518.175", "https://www.revisor.mn.gov/statutes/cite/518.175"),
    ]:
        manifest_dir = tmp_path / citation.replace(" ", "-")
        manifest_dir.mkdir()
        manifest_path = manifest_dir / "recovery_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "corpus_key": "state_laws",
                    "state_code": "MN",
                    "hf_dataset_id": "justicedao/ipfs_state_laws",
                    "citation_text": citation,
                    "normalized_citation": citation,
                    "candidates": [{"url": url, "title": citation, "score": 10}],
                    "archived_sources": [],
                }
            ),
            encoding="utf-8",
        )
        manifest_paths.append(manifest_path)

    import pyarrow as pa
    import pyarrow.parquet as pq

    remote_hf_parquet = tmp_path / "hf-current" / "STATE-MN.parquet"
    remote_hf_parquet.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_type": "legal_source_recovery_manifest",
                    "corpus_key": "state_laws",
                    "hf_dataset_id": "justicedao/ipfs_state_laws",
                    "normalized_citation": "Minn. Stat. § 609.02",
                    "primary_candidate_url": "https://www.revisor.mn.gov/statutes/cite/609.02",
                    "target_parquet_path": "state_laws_parquet_cid/STATE-MN.parquet",
                }
            ]
        ),
        remote_hf_parquet,
    )
    download_calls = []

    def _fake_hf_downloader(**kwargs):
        download_calls.append(kwargs)
        return remote_hf_parquet

    report = merge_recovery_manifests_into_canonical_datasets(
        manifest_paths,
        output_dir=tmp_path / "merged",
        hydrate_from_hf=True,
        hf_downloader=_fake_hf_downloader,
    )

    assert report["status"] == "success"
    assert report["target_count"] == 1
    assert len(download_calls) == 1
    target = report["targets"][0]
    assert target["existing_row_count"] == 1
    assert target["incoming_row_count"] == 2
    assert target["merged_row_count"] == 3

    merged_rows = pq.read_table(target["target_local_parquet_path"]).to_pylist()
    normalized_citations = {str(row.get("normalized_citation") or "") for row in merged_rows}
    assert normalized_citations == {
        "Minn. Stat. § 518.17",
        "Minn. Stat. § 518.175",
        "Minn. Stat. § 609.02",
    }


@pytest.mark.anyio
async def test_recovery_manifest_release_plan_matches_daemon_style(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )

    workflow = LegalSourceRecoveryWorkflow(
        live_searcher=_FakeLiveSearcher(),
        archive_searcher=_FakeArchiveSearcher(),
        archiver=_FakeArchiver(),
        now_factory=lambda: datetime(2024, 1, 2, 3, 4, 5),
    )

    result = await workflow.recover_unresolved_citation(
        citation_text="Minn. Stat. § 518.17",
        normalized_citation="Minn. Stat. § 518.17",
        corpus_key="state_laws",
        state_code="MN",
        metadata={"candidate_corpora": ["state_laws"]},
        publish_to_hf=False,
    )

    preview = build_recovery_manifest_release_plan(
        result.manifest_path or "",
        workspace_root=tmp_path,
        python_bin="/usr/bin/python3",
    )

    assert preview["status"] == "planned"
    assert preview["preview"] is True
    assert preview["corpus"] == "state_laws"
    assert preview["artifacts"]["promotion_output_dir"].endswith("canonical_promotion")
    assert preview["commands"][0]["stage"] == "promote_bundle"
    assert "promote_recovery_manifest_to_canonical_bundle" in preview["commands"][0]["command"]
    assert preview["commands"][1]["stage"] == "merge_into_canonical_dataset"
    assert preview["commands"][1]["status"] == "ready"
    assert "merge_recovery_manifest_into_canonical_dataset" in preview["commands"][1]["command"]
