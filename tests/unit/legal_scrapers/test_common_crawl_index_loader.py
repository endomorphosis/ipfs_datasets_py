from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.common_crawl_index_loader import CommonCrawlIndexLoader


def test_load_federal_index_redirects_to_state_in_admin_rules_mode(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES", "1")

    loader = CommonCrawlIndexLoader.__new__(CommonCrawlIndexLoader)
    loader._loaded_indexes = {}

    observed: dict[str, object] = {}

    def _fake_load_state_index(self, state_code=None, force_refresh=False):
        observed["state_code"] = state_code
        observed["force_refresh"] = force_refresh
        return {"kind": "state"}

    monkeypatch.setattr(CommonCrawlIndexLoader, "load_state_index", _fake_load_state_index)

    result = CommonCrawlIndexLoader.load_federal_index(loader, force_refresh=True)

    assert result == {"kind": "state"}
    assert observed == {"state_code": None, "force_refresh": True}
