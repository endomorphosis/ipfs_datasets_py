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
