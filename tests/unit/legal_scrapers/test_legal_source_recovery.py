from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import CanonicalLegalCorpus
from ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery import (
    LegalSourceRecoveryWorkflow,
    build_recovery_feedback_entries_from_citation_audit,
    build_missing_citation_recovery_query,
    recover_citation_audit_feedback,
)


class _FakeLiveSearcher:
    def search(self, query: str, max_results: int = 20, **kwargs):
        return {
            "results": [
                {
                    "title": "Minnesota Statutes 518.17",
                    "url": "https://www.revisor.mn.gov/statutes/cite/518.17",
                    "source": "brave",
                },
                {
                    "title": "Secondary explainer",
                    "url": "https://example.org/mn-518-17",
                    "source": "brave",
                },
            ]
        }


class _FakeArchiveSearcher:
    def search_with_indexes(
        self,
        query: str,
        jurisdiction_type: str | None = None,
        state_code: str | None = None,
        max_results: int = 50,
    ):
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
        return [
            SimpleNamespace(
                url=url,
                success=True,
                source="wayback",
                error=None,
                timestamp=datetime(2024, 1, 2, 3, 4, 5),
            )
            for url in urls
        ]


@pytest.mark.anyio
async def test_legal_source_recovery_tracks_and_publishes_manifest(monkeypatch, tmp_path):
    published = {}

    def _fake_publish(**kwargs):
        published.update(kwargs)
        return {"repo_id": kwargs["repo_id"], "path_in_repo": kwargs["path_in_repo"], "uploaded": True}

    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )

    workflow = LegalSourceRecoveryWorkflow(
        live_searcher=_FakeLiveSearcher(),
        archive_searcher=_FakeArchiveSearcher(),
        archiver=_FakeArchiver(),
        publish_func=_fake_publish,
        now_factory=lambda: datetime(2024, 1, 2, 3, 4, 5),
    )

    result = await workflow.recover_unresolved_citation(
        citation_text="Minn. Stat. § 518.17",
        normalized_citation="Minn. Stat. § 518.17",
        corpus_key="state_laws",
        state_code="MN",
        metadata={"candidate_corpora": ["state_laws"]},
        publish_to_hf=True,
    )

    assert result.status == "tracked_and_published"
    assert result.corpus_key == "state_laws"
    assert result.candidate_count == 3
    assert result.archived_count == 3
    assert result.publish_report == {
        "repo_id": "justicedao/ipfs_state_laws",
        "path_in_repo": "source_recovery/20240102_030405_minn-stat-518-17",
        "uploaded": True,
    }

    manifest_path = Path(result.manifest_path)
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["citation_text"] == "Minn. Stat. § 518.17"
    assert manifest["corpus_key"] == "state_laws"
    assert manifest["hf_dataset_id"] == "justicedao/ipfs_state_laws"
    assert manifest["search_query"].startswith("Minn. Stat. § 518.17 MN statute")
    assert manifest["candidates"][0]["url"] == "https://www.revisor.mn.gov/statutes/cite/518.17"
    assert result.promotion_preview["hf_dataset_id"] == "justicedao/ipfs_state_laws"
    assert result.promotion_preview["target_parquet_file"] == "STATE-MN.parquet"
    assert result.release_plan_preview["artifacts"]["hf_dataset_id"] == "justicedao/ipfs_state_laws"

    assert published["repo_id"] == "justicedao/ipfs_state_laws"
    assert published["path_in_repo"] == "source_recovery/20240102_030405_minn-stat-518-17"
    assert Path(published["local_dir"]) == manifest_path.parent


def test_build_missing_citation_recovery_query_prefers_official_domains():
    query = build_missing_citation_recovery_query(
        "42 U.S.C. § 1983",
        corpus_key="us_code",
    )

    assert "42 U.S.C. § 1983" in query
    assert "site:uscode.house.gov" in query
    assert "site:govinfo.gov" in query


def test_build_recovery_feedback_entries_from_citation_audit_flattens_unresolved_documents():
    entries = build_recovery_feedback_entries_from_citation_audit(
        {
            "document_count": 2,
            "unresolved_documents": [
                {
                    "document_id": "doc_1",
                    "document_title": "Motion",
                    "unmatched_citations": [
                        {
                            "citation_text": "Minn. Stat. § 999.999",
                            "normalized_citation": "Minn. Stat. § 999.999",
                            "citation_type": "state_statute",
                            "metadata": {
                                "state_code": "MN",
                                "recovery_corpus_key": "state_laws",
                                "candidate_corpora": ["state_laws"],
                                "preferred_dataset_ids": ["justicedao/ipfs_state_laws"],
                                "preferred_parquet_files": ["STATE-MN.parquet"],
                                "recovery_query": "Minn. Stat. § 999.999 MN statute site:.gov OR site:.us",
                            },
                        }
                    ],
                }
            ],
        }
    )

    assert len(entries) == 1
    assert entries[0]["document_id"] == "doc_1"
    assert entries[0]["corpus_key"] == "state_laws"
    assert entries[0]["preferred_dataset_ids"] == ["justicedao/ipfs_state_laws"]
    assert entries[0]["preferred_parquet_files"] == ["STATE-MN.parquet"]


@pytest.mark.anyio
async def test_recover_citation_audit_feedback_emits_promotion_metadata(monkeypatch, tmp_path):
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

    result = await recover_citation_audit_feedback(
        {
            "document_count": 1,
            "unmatched_citation_count": 1,
            "unresolved_documents": [
                {
                    "document_id": "doc_1",
                    "document_title": "Motion",
                    "unmatched_citations": [
                        {
                            "citation_text": "Minn. Stat. § 518.17",
                            "normalized_citation": "Minn. Stat. § 518.17",
                            "citation_type": "state_statute",
                            "metadata": {
                                "state_code": "MN",
                                "recovery_corpus_key": "state_laws",
                                "candidate_corpora": ["state_laws"],
                                "preferred_dataset_ids": ["justicedao/ipfs_state_laws"],
                                "preferred_parquet_files": ["STATE-MN.parquet"],
                            },
                        }
                    ],
                }
            ],
        },
        workflow=workflow,
    )

    assert result["feedback_entry_count"] == 1
    assert result["recovery_count"] == 1
    recovery = result["recoveries"][0]
    assert recovery["feedback_entry"]["document_id"] == "doc_1"
    assert recovery["promotion_preview"]["hf_dataset_id"] == "justicedao/ipfs_state_laws"
    assert recovery["promotion_preview"]["target_parquet_file"] == "STATE-MN.parquet"
    assert recovery["release_plan_preview"]["artifacts"]["hf_dataset_id"] == "justicedao/ipfs_state_laws"


@pytest.mark.anyio
async def test_legal_source_recovery_uses_multi_engine_fallback_and_reports_backend_status(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )

    async def _fake_multi_engine_search(self, *, query: str, engines, max_results: int):
        return {
            "status": "success",
            "results": [
                {
                    "title": "Alaska Statutes",
                    "url": "https://www.akleg.gov/basis/statutes.asp",
                    "engine": "duckduckgo",
                }
            ],
        }

    monkeypatch.setattr(
        LegalSourceRecoveryWorkflow,
        "_multi_engine_search",
        _fake_multi_engine_search,
    )
    monkeypatch.setattr(
        LegalSourceRecoveryWorkflow,
        "_search_backend_status",
        lambda self: {
            "brave_configured": False,
            "duckduckgo_configured": True,
            "archive_search_available": bool(self._archive_searcher is not None),
            "live_search_available": bool(self._live_searcher is not None),
            "brave_api_key_env": "",
            "datasets_available": False,
        },
    )

    class _EmptyLiveSearcher:
        def search(self, query: str, max_results: int = 20, **kwargs):
            return {"results": []}

    class _EmptyArchiveSearcher:
        def search_with_indexes(self, query: str, jurisdiction_type: str | None = None, state_code: str | None = None, max_results: int = 50):
            return {"results": []}

    workflow = LegalSourceRecoveryWorkflow(
        live_searcher=_EmptyLiveSearcher(),
        archive_searcher=_EmptyArchiveSearcher(),
        archiver=_FakeArchiver(),
        now_factory=lambda: datetime(2024, 1, 2, 3, 4, 5),
    )

    result = await workflow.recover_unresolved_citation(
        citation_text="AK official statutes",
        normalized_citation="AK official statutes",
        corpus_key="state_laws",
        state_code="AK",
        metadata={"candidate_corpora": ["state_laws"]},
    )

    assert result.candidate_count == 1
    assert result.candidates[0].url == "https://www.akleg.gov/basis/statutes.asp"
    assert result.search_backend_status["multi_engine_used"] is True
    assert "duckduckgo" in result.search_backend_status["engines_attempted"]
