import pytest
from pathlib import Path


pytestmark = pytest.mark.anyio


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "legal_scrapers"


def _fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_state_admin_rules_api_defaults_delegate_high_cap_values(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api
    from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as scraper_module

    captured = {}

    async def _fake_scrape_state_admin_rules(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "data": [], "metadata": {}}

    monkeypatch.setattr(scraper_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)

    result = await legal_dataset_api.scrape_state_admin_rules_from_parameters({})

    assert result["status"] == "success"
    assert captured["per_state_timeout_seconds"] == 86400.0
    assert captured["agentic_max_candidates_per_state"] == 1000
    assert captured["agentic_max_fetch_per_state"] == 1000
    assert captured["agentic_max_results_per_domain"] == 1000
    assert captured["agentic_max_hops"] == 4
    assert captured["agentic_max_pages"] == 1000


@pytest.mark.asyncio
async def test_netherlands_laws_api_delegates_parameters(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api
    from ipfs_datasets_py.processors.legal_scrapers import netherlands_laws_scraper as scraper_module

    captured = {}

    async def _fake_scrape_netherlands_laws(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "data": [], "metadata": {}}

    monkeypatch.setattr(scraper_module, "scrape_netherlands_laws", _fake_scrape_netherlands_laws)

    result = await legal_dataset_api.scrape_netherlands_laws_from_parameters(
        {
            "document_urls": ["https://wetten.overheid.nl/BWBR0001854/"],
            "seed_urls": ["https://wetten.overheid.nl/zoeken"],
            "max_documents": 3,
            "include_metadata": False,
            "rate_limit_delay": 1.25,
            "max_seed_pages": 8,
            "crawl_depth": 1,
            "use_default_seeds": True,
            "skip_existing": True,
            "resume": True,
        }
    )

    assert result["status"] == "success"
    assert captured["document_urls"] == ["https://wetten.overheid.nl/BWBR0001854/"]
    assert captured["seed_urls"] == ["https://wetten.overheid.nl/zoeken"]
    assert captured["max_documents"] == 3
    assert captured["include_metadata"] is False
    assert captured["rate_limit_delay"] == 1.25
    assert captured["max_seed_pages"] == 8
    assert captured["crawl_depth"] == 1
    assert captured["use_default_seeds"] is True
    assert captured["skip_existing"] is True
    assert captured["resume"] is True


@pytest.mark.asyncio
async def test_search_netherlands_law_corpus_applies_canonical_defaults(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {"status": "success", "operation": operation, "results": []}

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2, 0.3],
            "auto_setup_venv": False,
        },
        tool_version="4.0.0",
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_cases"
    assert result["tool_version"] == "4.0.0"
    assert result["jurisdiction"] == "NL"
    assert captured["payload"]["hf_dataset_id"] == "justicedao/ipfs_netherlands_laws"
    assert captured["payload"]["hf_parquet_file"] == "netherlands_laws.parquet"
    assert captured["payload"]["chunk_lookup_enabled"] is False
    assert "citation" in captured["payload"]["text_field_candidates"]
    assert "hierarchy_path_text" in captured["payload"]["text_field_candidates"]
    assert captured["payload"]["prefer_current_versions"] is True
    assert captured["payload"]["include_historical_versions"] is True


@pytest.mark.asyncio
async def test_fixture_to_searchable_corpus_result_preserves_article_citation(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _build_article_records,
        _extract_title_and_text,
        _extract_info_metadata,
    )

    parsed = _extract_title_and_text(_fixture_text("netherlands_wetten_document.html"))
    info_metadata = _extract_info_metadata(
        _fixture_text("netherlands_wetten_informatie.html"),
        info_url="https://wetten.overheid.nl/BWBR0001854/informatie",
    )
    document_row = {
        "jurisdiction": "NL",
        "jurisdiction_name": "Netherlands",
        "country": "Netherlands",
        "language": "nl",
        "identifier": "BWBR0001854",
        "official_identifier": "BWBR0001854",
        "title": info_metadata["canonical_title"],
        "canonical_title": info_metadata["canonical_title"],
        "aliases": info_metadata["aliases"],
        "document_type": "wet",
        "text": parsed["text"],
        "source_url": "https://wetten.overheid.nl/BWBR0001854/",
        "information_url": "https://wetten.overheid.nl/BWBR0001854/informatie",
        "effective_date": info_metadata["effective_date"],
        "publication_date": info_metadata["publication_date"],
        "last_modified_date": info_metadata["last_modified_date"],
        "historical_versions": info_metadata["historical_versions"],
        "articles": parsed["structure"]["articles"],
        "chapters": parsed["structure"]["chapters"],
        "parts": parsed["structure"]["parts"],
        "scraped_at": "2026-04-10T00:00:00",
    }
    article_records = _build_article_records(document_row)

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.95,
                    "cid": "cid-1",
                    "case": article_records[0],
                }
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.8, 0.1, 0.1],
            "auto_setup_venv": False,
        },
        tool_version="4.1.0",
    )

    assert result["status"] == "success"
    assert result["results"][0]["case"]["record_type"] == "article"
    assert result["results"][0]["case"]["citation"] == (
        "Sr, Boek 1 Algemene bepalingen, Titel I Reikwijdte van de strafwet, "
        "Afdeling 1 Strafbaarheid, Artikel 1"
    )
    assert result["answers"][0]["canonical_citation"] == (
        "Sr, Boek 1 Algemene bepalingen, Titel I Reikwijdte van de strafwet, "
        "Afdeling 1 Strafbaarheid, Artikel 1"
    )
    assert result["answers"][0]["article_number"] == "1"
    assert result["answers"][0]["match_reason"] == "vector_match"
    assert result["answers"][0]["retrieval_reason"] == "vector_search_fallback"


@pytest.mark.asyncio
async def test_recover_missing_legal_citation_source_api_delegates_parameters(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api
    from ipfs_datasets_py.processors.legal_scrapers import legal_source_recovery as recovery_module

    captured = {}

    async def _fake_recover_missing_legal_citation_source(**kwargs):
        captured.update(kwargs)
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "corpus_key": kwargs["corpus_key"],
            "candidate_files": [
                {
                    "url": "https://www.revisor.mn.gov/statutes/2024/cite/518.17.pdf",
                    "fetch_success": True,
                }
            ],
            "scraper_patch": {
                "patch_path": "/tmp/recovery.patch",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
            },
        }

    monkeypatch.setattr(
        recovery_module,
        "recover_missing_legal_citation_source",
        _fake_recover_missing_legal_citation_source,
    )

    result = await legal_dataset_api.recover_missing_legal_citation_source_from_parameters(
        {
            "citation_text": "Minn. Stat. § 518.17",
            "normalized_citation": "Minn. Stat. § 518.17",
            "corpus_key": "state_laws",
            "state": "mn",
            "candidate_corpora": ["state_laws", "state_admin_rules"],
            "metadata": {"source": "bluebook"},
            "max_candidates": 5,
            "archive_top_k": 2,
            "publish_to_hf": True,
            "hf_token": "token-123",
        },
        tool_version="5.0.0",
    )

    assert result["status"] == "tracked"
    assert result["operation"] == "recover_missing_legal_citation_source"
    assert result["tool_version"] == "5.0.0"
    assert result["candidate_files"][0]["fetch_success"] is True
    assert result["scraper_patch"]["target_file"] == "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py"
    assert captured["citation_text"] == "Minn. Stat. § 518.17"
    assert captured["normalized_citation"] == "Minn. Stat. § 518.17"
    assert captured["corpus_key"] == "state_laws"
    assert captured["state_code"] == "MN"
    assert captured["metadata"]["source"] == "bluebook"
    assert captured["metadata"]["candidate_corpora"] == ["state_laws", "state_admin_rules"]
    assert captured["max_candidates"] == 5
    assert captured["archive_top_k"] == 2
    assert captured["publish_to_hf"] is True
    assert captured["hf_token"] == "token-123"

async def test_netherlands_search_prefers_current_versions(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.99,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2018-01-01",
                        "version_start_date": "2018-01-01",
                        "version_end_date": "2020-12-31",
                        "is_current": False,
                        "citation": "Sr, Artikel 1",
                    },
                },
                {
                    "score": 0.90,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "version_start_date": "2024-01-01",
                        "version_end_date": "",
                        "is_current": True,
                        "citation": "Sr, Artikel 1",
                    },
                },
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {"collection_name": "nl_laws", "query_vector": [0.1, 0.2], "auto_setup_venv": False},
    )

    assert result["results"][0]["case"]["law_version_identifier"] == "BWBR0001854@2024-01-01"
    assert result["results"][1]["case"]["law_version_identifier"] == "BWBR0001854@2018-01-01"


@pytest.mark.asyncio
async def test_netherlands_search_can_filter_to_current_versions_only(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {"score": 0.9, "case": {"law_version_identifier": "BWBR0001854@2018-01-01", "is_current": False}},
                {"score": 0.8, "case": {"law_version_identifier": "BWBR0001854@2024-01-01", "is_current": True}},
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "include_historical_versions": False,
            "auto_setup_venv": False,
        },
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["case"]["law_version_identifier"] == "BWBR0001854@2024-01-01"


@pytest.mark.asyncio
async def test_netherlands_search_as_of_date_selects_matching_version(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.95,
                    "case": {
                        "law_version_identifier": "BWBR0001854@2012-01-01",
                        "version_start_date": "2012-01-01",
                        "version_end_date": "2023-12-31",
                        "is_current": False,
                        "citation": "Sr, Artikel 1",
                    },
                },
                {
                    "score": 0.94,
                    "case": {
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "version_start_date": "2024-01-01",
                        "version_end_date": "",
                        "is_current": True,
                        "citation": "Sr, Artikel 1",
                    },
                },
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "as_of_date": "2018-01-01",
            "auto_setup_venv": False,
        },
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["case"]["law_version_identifier"] == "BWBR0001854@2012-01-01"
    assert result["results"][0]["case"]["citation"] == "Sr, Artikel 1"


@pytest.mark.asyncio
async def test_netherlands_search_effective_date_can_select_specific_version(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {"score": 0.9, "case": {"law_version_identifier": "BWBR0001854@2012-01-01", "version_start_date": "2012-01-01", "is_current": False, "citation": "Sr, Artikel 1"}},
                {"score": 0.8, "case": {"law_version_identifier": "BWBR0001854@2024-01-01", "version_start_date": "2024-01-01", "is_current": True, "citation": "Sr, Artikel 1"}},
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "effective_date": "2024-01-01",
            "auto_setup_venv": False,
        },
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["case"]["law_version_identifier"] == "BWBR0001854@2024-01-01"
    assert result["results"][0]["case"]["citation"] == "Sr, Artikel 1"


async def test_netherlands_citation_query_identifier_lookup_prioritizes_exact_article(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.70,
                    "case": {
                        "law_identifier": "BWBR0009999",
                        "law_version_identifier": "BWBR0009999@2024-01-01",
                        "article_number": "1",
                        "citation": "Other, Artikel 1",
                        "aliases": ["Other"],
                        "is_current": True,
                    },
                },
                {
                    "score": 0.65,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "article_number": "1",
                        "citation": "Sr, Artikel 1",
                        "aliases": ["Sr"],
                        "is_current": True,
                    },
                },
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "citation_query": "BWBR0001854 artikel 1",
            "auto_setup_venv": False,
        },
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["case"]["law_identifier"] == "BWBR0001854"
    assert result["results"][0]["case"]["article_number"] == "1"
    assert result["answers"][0]["law_identifier"] == "BWBR0001854"
    assert result["answers"][0]["match_reason"] == "identifier_article_match"
    assert result["answers"][0]["retrieval_reason"] == "citation_grounded_retrieval"


async def test_netherlands_citation_query_title_lookup_prioritizes_exact_article(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.88,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "2",
                        "citation": "Sr, Artikel 2",
                        "is_current": True,
                    },
                },
                {
                    "score": 0.84,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "1",
                        "citation": "Sr, Artikel 1",
                        "is_current": True,
                    },
                },
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "citation_query": "Wetboek van Strafrecht artikel 1",
            "auto_setup_venv": False,
        },
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["case"]["article_number"] == "1"
    assert result["results"][0]["case"]["citation"] == "Sr, Artikel 1"
    assert result["answers"][0]["canonical_citation"] == "Sr, Artikel 1"
    assert result["answers"][0]["match_reason"] == "title_article_match"


async def test_netherlands_citation_query_falls_back_to_vector_results_when_unparsed(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {"score": 0.91, "case": {"citation": "Sr, Artikel 1", "is_current": True}},
                {"score": 0.83, "case": {"citation": "Sr, Artikel 2", "is_current": True}},
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "citation_query": "something broad without dutch citation structure",
            "auto_setup_venv": False,
        },
    )

    assert len(result["results"]) == 2
    assert result["results"][0]["score"] == 0.91
    assert len(result["answers"]) == 2
    assert result["answers"][0]["retrieval_reason"] == "vector_search_fallback"


async def test_netherlands_citation_query_respects_temporal_filtering(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.95,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2012-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "1",
                        "citation": "Sr, Artikel 1",
                        "version_start_date": "2012-01-01",
                        "version_end_date": "2023-12-31",
                        "is_current": False,
                    },
                },
                {
                    "score": 0.94,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "1",
                        "citation": "Sr, Artikel 1",
                        "version_start_date": "2024-01-01",
                        "version_end_date": "",
                        "is_current": True,
                    },
                },
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "citation_query": "Sr artikel 1",
            "as_of_date": "2018-01-01",
            "auto_setup_venv": False,
        },
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["case"]["law_version_identifier"] == "BWBR0001854@2012-01-01"
    assert result["results"][0]["case"]["citation"] == "Sr, Artikel 1"
    assert result["answers"][0]["law_version_identifier"] == "BWBR0001854@2012-01-01"
    assert result["answers"][0]["version_end_date"] == "2023-12-31"


async def test_netherlands_citation_query_formats_alias_based_answer(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.91,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "1",
                        "citation": "Sr, Artikel 1",
                        "hierarchy_path": [{"kind": "artikel", "label": "Artikel 1", "number": "1"}],
                        "hierarchy_labels": ["Artikel 1"],
                        "effective_date": "2024-01-01",
                        "version_start_date": "2024-01-01",
                        "version_end_date": "",
                        "source_url": "https://wetten.overheid.nl/BWBR0001854/2024-01-01/0/",
                        "information_url": "https://wetten.overheid.nl/BWBR0001854/2024-01-01/0/informatie",
                        "text": "Geen feit is strafbaar dan uit kracht van wet.",
                        "is_current": True,
                    },
                }
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "citation_query": "Sr artikel 1",
            "auto_setup_venv": False,
        },
    )

    answer = result["answers"][0]
    assert answer["canonical_citation"] == "Sr, Artikel 1"
    assert answer["aliases"] == ["Sr"]
    assert answer["article_number"] == "1"
    assert answer["match_reason"] == "alias_article_match"
    assert answer["article_text"] == "Geen feit is strafbaar dan uit kracht van wet."


async def test_netherlands_citation_query_range_returns_multiple_article_answers(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.93,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "2",
                        "citation": "Sr, Artikel 2",
                        "hierarchy_path": [{"kind": "artikel", "label": "Artikel 2", "number": "2"}],
                        "hierarchy_labels": ["Artikel 2"],
                        "text": "De Nederlandse strafwet is toepasselijk.",
                        "is_current": True,
                    },
                },
                {
                    "score": 0.94,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "1",
                        "citation": "Sr, Artikel 1",
                        "hierarchy_path": [{"kind": "artikel", "label": "Artikel 1", "number": "1"}],
                        "hierarchy_labels": ["Artikel 1"],
                        "text": "Geen feit is strafbaar dan uit kracht van wet.",
                        "is_current": True,
                    },
                },
                {
                    "score": 0.80,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "4",
                        "citation": "Sr, Artikel 4",
                        "hierarchy_path": [{"kind": "artikel", "label": "Artikel 4", "number": "4"}],
                        "hierarchy_labels": ["Artikel 4"],
                        "text": "Buiten bereik.",
                        "is_current": True,
                    },
                },
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "citation_query": "Sr artikelen 1-2",
            "auto_setup_venv": False,
        },
    )

    assert [answer["article_number"] for answer in result["answers"]] == ["1", "2"]
    assert result["answers"][0]["canonical_citation"] == "Sr, Artikel 1"
    assert result["answers"][1]["canonical_citation"] == "Sr, Artikel 2"


async def test_netherlands_answer_context_neighbors_includes_previous_and_next(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.97,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "2",
                        "citation": "Sr, Artikel 2",
                        "hierarchy_path": [
                            {"kind": "boek", "label": "Boek 1", "number": "1"},
                            {"kind": "artikel", "label": "Artikel 2", "number": "2"},
                        ],
                        "hierarchy_labels": ["Boek 1", "Artikel 2"],
                        "text": "Zie artikel 1 en artikel 3.",
                        "is_current": True,
                    },
                },
                {
                    "score": 0.90,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "1",
                        "citation": "Sr, Artikel 1",
                        "hierarchy_path": [
                            {"kind": "boek", "label": "Boek 1", "number": "1"},
                            {"kind": "artikel", "label": "Artikel 1", "number": "1"},
                        ],
                        "hierarchy_labels": ["Boek 1", "Artikel 1"],
                        "text": "Eerste bepaling.",
                        "is_current": True,
                    },
                },
                {
                    "score": 0.89,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "3",
                        "citation": "Sr, Artikel 3",
                        "hierarchy_path": [
                            {"kind": "boek", "label": "Boek 1", "number": "1"},
                            {"kind": "artikel", "label": "Artikel 3", "number": "3"},
                        ],
                        "hierarchy_labels": ["Boek 1", "Artikel 3"],
                        "text": "Derde bepaling.",
                        "is_current": True,
                    },
                },
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "citation_query": "Sr artikel 2",
            "context_mode": "neighbors",
            "auto_setup_venv": False,
        },
    )

    answer = result["answers"][0]
    assert answer["previous_article"]["article_number"] == "1"
    assert answer["next_article"]["article_number"] == "3"
    assert answer["referenced_articles"] == ["1", "3"]


async def test_netherlands_answer_context_hierarchy_includes_siblings(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.97,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "2",
                        "citation": "Sr, Titel I, Artikel 2",
                        "hierarchy_path": [
                            {"kind": "boek", "label": "Boek 1", "number": "1"},
                            {"kind": "titel", "label": "Titel I", "number": "I"},
                            {"kind": "artikel", "label": "Artikel 2", "number": "2"},
                        ],
                        "hierarchy_labels": ["Boek 1", "Titel I", "Artikel 2"],
                        "text": "Zie artikelen 1 en 3.",
                        "is_current": True,
                    },
                },
                {
                    "score": 0.95,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "1",
                        "citation": "Sr, Titel I, Artikel 1",
                        "hierarchy_path": [
                            {"kind": "boek", "label": "Boek 1", "number": "1"},
                            {"kind": "titel", "label": "Titel I", "number": "I"},
                            {"kind": "artikel", "label": "Artikel 1", "number": "1"},
                        ],
                        "hierarchy_labels": ["Boek 1", "Titel I", "Artikel 1"],
                        "text": "Eerste bepaling.",
                        "is_current": True,
                    },
                },
                {
                    "score": 0.92,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "4",
                        "citation": "Sr, Titel II, Artikel 4",
                        "hierarchy_path": [
                            {"kind": "boek", "label": "Boek 1", "number": "1"},
                            {"kind": "titel", "label": "Titel II", "number": "II"},
                            {"kind": "artikel", "label": "Artikel 4", "number": "4"},
                        ],
                        "hierarchy_labels": ["Boek 1", "Titel II", "Artikel 4"],
                        "text": "Andere titel.",
                        "is_current": True,
                    },
                },
                {
                    "score": 0.94,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "3",
                        "citation": "Sr, Titel I, Artikel 3",
                        "hierarchy_path": [
                            {"kind": "boek", "label": "Boek 1", "number": "1"},
                            {"kind": "titel", "label": "Titel I", "number": "I"},
                            {"kind": "artikel", "label": "Artikel 3", "number": "3"},
                        ],
                        "hierarchy_labels": ["Boek 1", "Titel I", "Artikel 3"],
                        "text": "Derde bepaling.",
                        "is_current": True,
                    },
                },
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "citation_query": "Sr artikel 2",
            "context_mode": "hierarchy",
            "auto_setup_venv": False,
        },
    )

    answer = result["answers"][0]
    assert answer["previous_article"]["article_number"] == "1"
    assert answer["next_article"]["article_number"] == "3"
    assert [item["article_number"] for item in answer["sibling_articles"]] == ["1", "3"]
    assert answer["referenced_articles"] == ["1", "3"]


async def test_netherlands_answer_exact_mode_keeps_context_empty(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search_cases(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "operation": "search_cases",
            "tool_version": tool_version,
            "results": [
                {
                    "score": 0.91,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "1",
                        "citation": "Sr, Artikel 1",
                        "hierarchy_path": [{"kind": "artikel", "label": "Artikel 1", "number": "1"}],
                        "hierarchy_labels": ["Artikel 1"],
                        "text": "Zie artikel 2.",
                        "is_current": True,
                    },
                },
                {
                    "score": 0.90,
                    "case": {
                        "law_identifier": "BWBR0001854",
                        "law_version_identifier": "BWBR0001854@2024-01-01",
                        "canonical_title": "Wetboek van Strafrecht",
                        "aliases": ["Sr"],
                        "article_number": "2",
                        "citation": "Sr, Artikel 2",
                        "hierarchy_path": [{"kind": "artikel", "label": "Artikel 2", "number": "2"}],
                        "hierarchy_labels": ["Artikel 2"],
                        "text": "Tweede bepaling.",
                        "is_current": True,
                    },
                },
            ],
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "search_caselaw_access_cases_from_parameters",
        _fake_search_cases,
    )

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "nl_laws",
            "query_vector": [0.1, 0.2],
            "citation_query": "Sr artikel 1",
            "auto_setup_venv": False,
        },
    )

    answer = result["answers"][0]
    assert answer["previous_article"] is None
    assert answer["next_article"] is None
    assert answer["sibling_articles"] == []
    assert answer["referenced_articles"] == ["2"]
