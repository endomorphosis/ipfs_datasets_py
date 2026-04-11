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
        }
    )

    assert result["status"] == "success"
    assert captured["document_urls"] == ["https://wetten.overheid.nl/BWBR0001854/"]
    assert captured["seed_urls"] == ["https://wetten.overheid.nl/zoeken"]
    assert captured["max_documents"] == 3
    assert captured["include_metadata"] is False
    assert captured["rate_limit_delay"] == 1.25


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
