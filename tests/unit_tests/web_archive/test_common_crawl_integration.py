from ipfs_datasets_py.processors.web_archiving.common_crawl_integration import (
    CommonCrawlSearchEngine,
    _normalize_cc_jurisdiction,
)


def test_normalize_cc_jurisdiction_treats_state_gov_domains_as_state() -> None:
    jurisdiction, state_code = _normalize_cc_jurisdiction("azsos.gov", "federal", None)

    assert jurisdiction == "state"
    assert state_code == "AZ"


def test_normalize_cc_jurisdiction_preserves_explicit_federal_hosts() -> None:
    jurisdiction, state_code = _normalize_cc_jurisdiction("va.gov", "federal", None)

    assert jurisdiction == "federal"
    assert state_code == "VA"


def test_search_domain_hf_redirects_stateish_domains_before_hf_lookup() -> None:
    engine = CommonCrawlSearchEngine.__new__(CommonCrawlSearchEngine)
    observed = {}

    class _FakeHF:
        def search(self, **kwargs):
            observed.update(kwargs)
            return [
                {
                    "url": "https://apps.azsos.gov/rules",
                    "timestamp": "20260325000000",
                }
            ]

    engine.hf_search = _FakeHF()
    engine._normalize_records = CommonCrawlSearchEngine._normalize_records

    records = engine._search_domain_hf("apps.azsos.gov", 5, None, jurisdiction="federal")

    assert records
    assert observed["jurisdiction"] == "state"
    assert observed["state_code"] == "AZ"
    assert records[0]["url"] == "https://apps.azsos.gov/rules"
