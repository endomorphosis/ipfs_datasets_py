from __future__ import annotations

import asyncio
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
    recover_missing_legal_citation_source,
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


class _FakeFetchAPI:
    def fetch(self, request, **kwargs):
        url = request if isinstance(request, str) else request.url
        if url == "https://www.revisor.mn.gov/statutes/cite/518.17":
            return SimpleNamespace(
                success=True,
                document=SimpleNamespace(
                    title="Minnesota Statutes 518.17",
                    text="Official statute page",
                    html="<a href=\"https://www.revisor.mn.gov/statutes/2024/cite/518.17.pdf\">Download PDF</a>",
                    content_type="text/html",
                    metadata={
                        "content_type": "text/html",
                        "links": [
                            {
                                "url": "https://www.revisor.mn.gov/statutes/2024/cite/518.17.pdf",
                                "text": "Download PDF",
                            }
                        ],
                    },
                    extraction_provenance={"method": "requests_only"},
                ),
                errors=[],
            )
        if url == "https://www.revisor.mn.gov/statutes/2024/cite/518.17.pdf":
            return SimpleNamespace(
                success=True,
                document=SimpleNamespace(
                    title="Minnesota Statutes 518.17 PDF",
                    text="Minnesota Statutes 518.17 full text",
                    html="",
                    content_type="application/pdf",
                    metadata={
                        "content_type": "application/pdf",
                        "raw_bytes": b"%PDF-1.4 fake",
                    },
                    extraction_provenance={"method": "requests_only"},
                ),
                errors=[],
            )
        return SimpleNamespace(success=False, document=None, errors=[SimpleNamespace(message="not found")])


class _FakePatchManager:
    def __init__(self):
        self.saved = []

    def save_patch(self, patch, output_path=None):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(patch.diff_content, encoding="utf-8")
        output_path.with_suffix(".json").write_text(json.dumps(patch.to_dict(), indent=2), encoding="utf-8")
        self.saved.append((patch, output_path))
        return output_path


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
        fetch_api=_FakeFetchAPI(),
        patch_manager=_FakePatchManager(),
        enable_candidate_file_fetch=True,
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
    assert manifest["search_query"].startswith("Minn. Stat. § 518.17 MN Minnesota official statutes code legislature")
    assert manifest["candidates"][0]["url"] == "https://www.revisor.mn.gov/statutes/cite/518.17"
    assert manifest["candidate_files"][0]["url"] == "https://www.revisor.mn.gov/statutes/2024/cite/518.17.pdf"
    assert manifest["candidate_files"][0]["artifact_path"].endswith(".pdf")
    assert manifest["scraper_patch"]["target_file"] == "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py"
    assert Path(manifest["scraper_patch"]["patch_path"]).exists()
    assert result.promotion_preview["hf_dataset_id"] == "justicedao/ipfs_state_laws"
    assert result.promotion_preview["target_parquet_file"] == "STATE-MN.parquet"
    assert result.release_plan_preview["artifacts"]["hf_dataset_id"] == "justicedao/ipfs_state_laws"

    assert published["repo_id"] == "justicedao/ipfs_state_laws"
    assert published["path_in_repo"] == "source_recovery/20240102_030405_minn-stat-518-17"
    assert Path(published["local_dir"]) == manifest_path.parent
    assert published["allow_patterns"] == ["*.json", "candidate_files/*", "patches/*"]


@pytest.mark.anyio
async def test_legal_source_recovery_discovers_candidate_files_and_writes_patch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )

    patch_manager = _FakePatchManager()
    workflow = LegalSourceRecoveryWorkflow(
        live_searcher=_FakeLiveSearcher(),
        archive_searcher=_FakeArchiveSearcher(),
        archiver=_FakeArchiver(),
        fetch_api=_FakeFetchAPI(),
        patch_manager=patch_manager,
        enable_candidate_file_fetch=True,
        now_factory=lambda: datetime(2024, 1, 2, 3, 4, 5),
    )

    result = await workflow.recover_unresolved_citation(
        citation_text="Minn. Stat. § 518.17",
        normalized_citation="Minn. Stat. § 518.17",
        corpus_key="state_laws",
        state_code="MN",
        metadata={"candidate_corpora": ["state_laws"]},
    )

    assert result.candidate_files
    assert result.candidate_files[0].url == "https://www.revisor.mn.gov/statutes/2024/cite/518.17.pdf"
    assert result.candidate_files[0].fetch_success is True
    assert result.candidate_files[0].artifact_path is not None
    assert Path(result.candidate_files[0].artifact_path).exists()
    assert result.scraper_patch is not None
    assert result.scraper_patch.host == "www.revisor.mn.gov"
    assert result.scraper_patch.extraction_recipe_path is not None
    assert Path(result.scraper_patch.extraction_recipe_path).exists()
    assert patch_manager.saved
    patch_text = Path(result.scraper_patch.patch_path).read_text(encoding="utf-8")
    assert "UnifiedWebArchivingAPI.fetch" in patch_text
    assert "++# preferred_fetch_path" not in patch_text
    assert "CommonCrawlSearchEngine.search_domain" in patch_text
    assert "_extract_recovered_www_revisor_mn_gov_text" in patch_text
    assert "https://www.revisor.mn.gov/statutes/2024/cite/518.17.pdf" in patch_text
    artifact_metadata = json.loads(Path(result.candidate_files[0].metadata_path).read_text(encoding="utf-8"))
    assert artifact_metadata["extraction_recipe"]["parser_kind"] == "pdf"
    assert "CommonCrawlSearchEngine.search_domain(host, query=citation_query)" in artifact_metadata["extraction_recipe"]["fallback_fetch_paths"]


@pytest.mark.anyio
async def test_public_recover_missing_legal_citation_source_emits_candidate_files_and_patch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )

    fake_searcher = SimpleNamespace(
        legal_searcher=_FakeLiveSearcher(),
        search_with_indexes=_FakeArchiveSearcher().search_with_indexes,
    )

    monkeypatch.setattr(
        LegalSourceRecoveryWorkflow,
        "_searcher",
        lambda self: fake_searcher,
    )
    monkeypatch.setattr(
        LegalSourceRecoveryWorkflow,
        "_archiver_instance",
        lambda self: _FakeArchiver(),
    )
    monkeypatch.setattr(
        LegalSourceRecoveryWorkflow,
        "_fetch_api_instance",
        lambda self: _FakeFetchAPI(),
    )
    monkeypatch.setattr(
        LegalSourceRecoveryWorkflow,
        "_patch_manager_instance",
        lambda self, *, manifest_dir: _FakePatchManager(),
    )

    result = await recover_missing_legal_citation_source(
        citation_text="Minn. Stat. § 518.17",
        normalized_citation="Minn. Stat. § 518.17",
        corpus_key="state_laws",
        state_code="MN",
        metadata={"candidate_corpora": ["state_laws"]},
        archive_top_k=1,
        enable_candidate_file_fetch=True,
    )

    assert result["status"] == "tracked"
    assert result["candidate_files"]
    assert result["candidate_files"][0]["url"] == "https://www.revisor.mn.gov/statutes/2024/cite/518.17.pdf"
    assert result["candidate_files"][0]["fetch_success"] is True
    assert result["scraper_patch"]["host"] == "www.revisor.mn.gov"
    assert Path(result["scraper_patch"]["patch_path"]).exists()


@pytest.mark.anyio
async def test_legal_source_recovery_times_out_multi_engine_search_and_still_writes_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery._SEARCH_TIMEOUT_SECONDS",
        0.01,
    )

    workflow = LegalSourceRecoveryWorkflow(
        now_factory=lambda: datetime(2024, 1, 2, 3, 4, 5),
    )

    async def _slow_multi_engine_search(*, query: str, engines: list[str], max_results: int):
        del query, engines, max_results
        await asyncio.sleep(0.2)
        return {"status": "success", "results": []}

    monkeypatch.setattr(workflow, "_multi_engine_search", _slow_multi_engine_search)
    monkeypatch.setattr(
        workflow,
        "_searcher",
        lambda: None,
    )
    monkeypatch.setattr(
        workflow,
        "_search_backend_status",
        lambda: {
            "brave_configured": False,
            "duckduckgo_configured": True,
            "archive_search_available": False,
            "live_search_available": False,
            "brave_api_key_env": "",
            "datasets_available": False,
        },
    )

    result = await workflow.recover_unresolved_citation(
        citation_text="Minn. Stat. § 518.17",
        normalized_citation="Minn. Stat. § 518.17",
        corpus_key="state_laws",
        state_code="MN",
        metadata={"candidate_corpora": ["state_laws"]},
        archive_top_k=0,
    )

    assert result.status == "tracked"
    assert result.candidate_count == 1
    assert result.candidates[0].source == "citation_url_hint"
    assert result.candidates[0].url == "https://www.revisor.mn.gov/statutes/cite/518.17"
    assert result.search_backend_status["multi_engine_error"] == "multi_engine_timeout"
    assert result.manifest_path is not None
    assert Path(result.manifest_path).exists()


def test_legal_source_recovery_official_hint_domains_cover_bluebook_fuzz_states():
    assert LegalSourceRecoveryWorkflow._official_hint_domains(corpus_key="state_laws", state_code="MN")[:1] == [
        "revisor.mn.gov"
    ]
    assert "oregonlegislature.gov" in LegalSourceRecoveryWorkflow._official_hint_domains(
        corpus_key="state_laws",
        state_code="OR",
    )


def test_build_missing_citation_recovery_query_prefers_official_domains():
    query = build_missing_citation_recovery_query(
        "42 U.S.C. § 1983",
        corpus_key="us_code",
    )

    assert "42 U.S.C. § 1983" in query
    assert "site:uscode.house.gov" in query
    assert "site:govinfo.gov" in query


def test_build_missing_citation_recovery_query_state_laws_includes_state_name_and_official_hints():
    query = build_missing_citation_recovery_query(
        "AK official statutes",
        corpus_key="state_laws",
        state_code="AK",
    )

    assert "AK" in query
    assert "Alaska" in query
    assert "official statutes code legislature" in query
    assert "site:.gov" in query


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


@pytest.mark.anyio
async def test_legal_source_recovery_uses_common_crawl_fallback_when_searches_miss(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CanonicalLegalCorpus,
        "default_local_root",
        lambda self: Path(tmp_path) / self.local_root_name,
    )
    monkeypatch.setenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_ALWAYS", "1")
    monkeypatch.setenv("LEGAL_SOURCE_RECOVERY_ENABLE_COMMON_CRAWL", "1")
    monkeypatch.setenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_YEAR", "2024")
    monkeypatch.setenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_MAX_PARQUET_FILES", "2")
    monkeypatch.setenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_PER_PARQUET_LIMIT", "25")

    from ipfs_datasets_py.processors.web_archiving import common_crawl_integration
    observed_search_kwargs = {}

    class _FakeCommonCrawlSearchEngine:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def is_available(self):
            return True

        def search_domain(self, domain, max_matches=100, collection=None, **kwargs):
            observed_search_kwargs.update(kwargs)
            return [
                {
                    "url": f"https://{domain}/download/title42-section1983.pdf",
                    "title": "Recovered official PDF",
                    "mime": "application/pdf",
                    "timestamp": "20240101000000",
                    "collection": "CC-MAIN-2024-10",
                }
            ]

    monkeypatch.setattr(common_crawl_integration, "CommonCrawlSearchEngine", _FakeCommonCrawlSearchEngine)
    monkeypatch.setattr(
        LegalSourceRecoveryWorkflow,
        "_search_backend_status",
        lambda self: {
            "brave_configured": False,
            "duckduckgo_configured": False,
            "archive_search_available": False,
            "live_search_available": False,
            "brave_api_key_env": "",
            "datasets_available": False,
        },
    )

    workflow = LegalSourceRecoveryWorkflow(
        now_factory=lambda: datetime(2024, 1, 2, 3, 4, 5),
    )

    result = await workflow.recover_unresolved_citation(
        citation_text="42 U.S.C. § 1983",
        normalized_citation="42 U.S.C. § 1983",
        corpus_key="us_code",
        state_code=None,
        archive_top_k=0,
    )

    assert result.candidate_count == 3
    assert result.candidates[0].source == "common_crawl_indexes"
    assert result.candidates[0].url == "https://uscode.house.gov/download/title42-section1983.pdf"
    assert result.search_backend_status["common_crawl_used"] is True
    assert result.search_backend_status["common_crawl_available"] is True
    assert result.search_backend_status["common_crawl_domains"][0] == "uscode.house.gov"
    assert observed_search_kwargs["year"] == "2024"
    assert observed_search_kwargs["max_parquet_files"] == 2
    assert observed_search_kwargs["per_parquet_limit"] == 25
    assert result.scraper_patch is not None
    assert result.scraper_patch.host == "uscode.house.gov"
