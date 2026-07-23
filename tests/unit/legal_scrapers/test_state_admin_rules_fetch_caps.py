from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as scraper_module


def test_max_fetch_cap_for_state_prefers_state_specific_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LEGAL_ADMIN_RULES_MAX_FETCH_PER_STATE_JSON",
        '{"CA": 120, "AZ": 90}',
    )
    monkeypatch.setenv("LEGAL_ADMIN_RULES_MAX_FETCH_PER_STATE", "75")

    assert scraper_module._max_fetch_cap_for_state("CA") == 120
    assert scraper_module._max_fetch_cap_for_state("AZ") == 90
    assert scraper_module._max_fetch_cap_for_state("TX") == 75


def test_max_fetch_cap_for_state_ignores_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEGAL_ADMIN_RULES_MAX_FETCH_PER_STATE_JSON", '{"CA": "bad", "AZ": 0}')
    monkeypatch.setenv("LEGAL_ADMIN_RULES_MAX_FETCH_PER_STATE", "0")

    assert scraper_module._max_fetch_cap_for_state("CA") is None
    assert scraper_module._max_fetch_cap_for_state("AZ") is None
    assert scraper_module._max_fetch_cap_for_state("TX") is None
