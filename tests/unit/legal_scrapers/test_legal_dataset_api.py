import pytest


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
