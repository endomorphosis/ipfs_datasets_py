from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import CanonicalLegalCorpus
from ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery import (
    LegalSourceRecoveryWorkflow,
    build_missing_citation_recovery_query,
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
