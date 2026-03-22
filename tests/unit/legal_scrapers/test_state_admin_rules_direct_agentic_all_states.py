from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as scraper_module
from ipfs_datasets_py.processors.legal_scrapers import state_scrapers as state_scrapers_module


@pytest.mark.anyio
async def test_direct_agentic_all_states_env_skips_base_scrape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scrape_calls: list[dict[str, object]] = []

    async def _fake_scrape_state_laws(**kwargs):
        scrape_calls.append(dict(kwargs))
        return {"status": "success", "data": [], "metadata": {"states_scraped": []}}

    async def _fake_agentic_discover_admin_state_blocks(**kwargs):
        return {"status": "success", "state_blocks": [], "kg_rows": [], "report": {}}

    monkeypatch.setenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES", "1")
    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_agentic_discover_admin_state_blocks", _fake_agentic_discover_admin_state_blocks)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scraper_module.scrape_state_admin_rules(
        states=["AL", "CT"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=False,
        require_substantive_rule_text=True,
    )

    assert result["status"] in {"success", "partial_success"}
    assert scrape_calls == []
    assert result["metadata"]["direct_agentic_all_states"] is True
    assert result["metadata"]["base_scrape_skipped_states"] == ["AL", "CT"]


@pytest.mark.anyio
async def test_direct_agentic_all_states_env_skips_zero_rule_fallback_scrape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scrape_calls: list[dict[str, object]] = []

    async def _fake_scrape_state_laws(**kwargs):
        scrape_calls.append(dict(kwargs))
        return {"status": "success", "data": [], "metadata": {"states_scraped": []}}

    async def _fake_agentic_discover_admin_state_blocks(**kwargs):
        return {"status": "success", "state_blocks": [], "kg_rows": [], "report": {}}

    monkeypatch.setenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES", "1")
    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_agentic_discover_admin_state_blocks", _fake_agentic_discover_admin_state_blocks)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scraper_module.scrape_state_admin_rules(
        states=["AK"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=True,
        require_substantive_rule_text=True,
    )

    assert result["status"] in {"success", "partial_success"}
    assert scrape_calls == []


def test_extract_seed_urls_for_state_uses_only_admin_labeled_code_list_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeScraper:
        def get_base_url(self) -> str:
            return "https://example.gov"

        def get_code_list(self) -> list[dict[str, str]]:
            return [
                {"name": "General Statutes", "url": "https://example.gov/statutes"},
                {"name": "Administrative Code", "url": "https://example.gov/admin/code"},
                {"name": "Agency Rules", "url": "https://example.gov/rules"},
            ]

        def _identify_legal_area(self, name: str) -> str:
            return "administrative" if "rules" in name.lower() else "statutory"

    monkeypatch.setitem(scraper_module._STATE_ADMIN_SOURCE_MAP, "ZZ", [])
    monkeypatch.setattr(state_scrapers_module, "get_scraper_for_state", lambda *args, **kwargs: _FakeScraper())
    monkeypatch.setattr(state_scrapers_module, "GenericStateScraper", _FakeScraper)
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])

    urls = scraper_module._extract_seed_urls_for_state("ZZ", "Zeta")

    assert "https://example.gov/admin/code" in urls
    assert "https://example.gov/rules" in urls
    assert "https://example.gov/statutes" not in urls
