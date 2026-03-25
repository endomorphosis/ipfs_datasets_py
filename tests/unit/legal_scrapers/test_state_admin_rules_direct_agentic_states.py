from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as scraper_module


@pytest.mark.anyio
async def test_connecticut_skips_base_state_laws_scrape_for_admin_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scrape_calls: list[dict[str, object]] = []

    async def _fake_scrape_state_laws(**kwargs):
        scrape_calls.append(dict(kwargs))
        return {
            "status": "success",
            "data": [],
            "metadata": {"states_scraped": kwargs.get("states") or []},
        }

    async def _fake_agentic_discover_admin_state_blocks(**kwargs):
        assert kwargs["states"] == ["CT"]
        return {"status": "success", "state_blocks": [], "kg_rows": [], "report": {}}

    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_agentic_discover_admin_state_blocks", _fake_agentic_discover_admin_state_blocks)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scraper_module.scrape_state_admin_rules(
        states=["CT"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=False,
        require_substantive_rule_text=True,
    )

    assert result["status"] in {"success", "partial_success"}
    assert scrape_calls == []


@pytest.mark.anyio
async def test_michigan_skips_base_state_laws_scrape_for_admin_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scrape_calls: list[dict[str, object]] = []

    async def _fake_scrape_state_laws(**kwargs):
        scrape_calls.append(dict(kwargs))
        return {
            "status": "success",
            "data": [],
            "metadata": {"states_scraped": kwargs.get("states") or []},
        }

    async def _fake_agentic_discover_admin_state_blocks(**kwargs):
        assert kwargs["states"] == ["MI"]
        return {"status": "success", "state_blocks": [], "kg_rows": [], "report": {}}

    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_agentic_discover_admin_state_blocks", _fake_agentic_discover_admin_state_blocks)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scraper_module.scrape_state_admin_rules(
        states=["MI"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=False,
        require_substantive_rule_text=True,
    )

    assert result["status"] in {"success", "partial_success"}
    assert scrape_calls == []
