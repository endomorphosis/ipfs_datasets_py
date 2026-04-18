from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import CanonicalLegalCorpus
from ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery import LegalSourceRecoveryWorkflow
from ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery_promotion import (
    build_recovery_manifest_promotion_row,
    build_recovery_manifest_release_plan,
    load_recovery_manifest,
    merge_recovery_manifest_into_canonical_dataset,
    promote_recovery_manifest_to_canonical_bundle,
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
