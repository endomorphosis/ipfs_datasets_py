from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.legal_web_archive_search import LegalWebArchiveSearch


class _FakeIndexLoader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def load_federal_index(self):
        self.calls.append(("federal", None))
        return {"url": []}

    def load_state_index(self, state_code=None):
        self.calls.append(("state", state_code))
        return {"url": []}

    def load_municipal_index(self):
        self.calls.append(("municipal", None))
        return {"url": []}

    def _check_local_index(self, jurisdiction_type):
        return None


def test_search_with_indexes_defaults_to_state_when_jurisdiction_missing() -> None:
    searcher = LegalWebArchiveSearch.__new__(LegalWebArchiveSearch)
    searcher.use_indexes = True
    searcher.index_loader = _FakeIndexLoader()
    searcher.query_processor = None

    results = searcher.search_with_indexes("state administrative rules", max_results=5)

    assert results["status"] == "success"
    assert results["jurisdiction_type"] == "state"
    assert searcher.index_loader.calls == [("state", None)]


def test_search_with_indexes_redirects_federal_to_state_in_admin_rules_mode(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES", "1")

    searcher = LegalWebArchiveSearch.__new__(LegalWebArchiveSearch)
    searcher.use_indexes = True
    searcher.index_loader = _FakeIndexLoader()
    searcher.query_processor = None

    results = searcher.search_with_indexes(
        "administrative rules",
        jurisdiction_type="federal",
        max_results=5,
    )

    assert results["status"] == "success"
    assert results["jurisdiction_type"] == "state"
    assert searcher.index_loader.calls == [("state", None)]
