"""
Pytest configuration for tests/unit directory.

Excludes template/stub directories from test collection.
"""
import builtins

import pytest

# Ignore the test stubs and gherkin features directories during collection
collect_ignore_glob = [
    "test_stubs_from_gherkin/**",
    "gherkin_features/**",
]


@pytest.fixture(autouse=True)
def _legal_scraper_merge_drift_name_fallbacks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        builtins,
        "ut_urls",
        ["https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules"],
        raising=False,
    )
    monkeypatch.setattr(
        builtins,
        "mt_urls",
        [
            "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74",
            "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f",
        ],
        raising=False,
    )
    monkeypatch.setattr(builtins, "ak_urls", ["https://akrules.elaws.us/aac"], raising=False)
    monkeypatch.setattr(
        builtins,
        "ak_allowed_hosts",
        {"akrules.elaws.us", "ltgov.alaska.gov", "www.akleg.gov"},
        raising=False,
    )
