from pathlib import Path

from ipfs_datasets_py.processors.web_archiving.search_engines.base import (
    SearchEngineAdapter,
    SearchEngineConfig,
    SearchEngineResponse,
    SearchEngineResult,
)


class _DummySearchEngine(SearchEngineAdapter):
    def search(self, query: str, max_results: int = 20, offset: int = 0, **kwargs):
        return SearchEngineResponse(
            results=[
                SearchEngineResult(
                    title="Minnesota statute",
                    url="https://www.revisor.mn.gov/statutes/cite/609.185",
                    snippet="Murder in the first degree.",
                    engine="dummy",
                    domain="revisor.mn.gov",
                )
            ],
            engine="dummy",
            query=query,
            total_results=1,
            took_ms=12.0,
        )

    def test_connection(self) -> bool:
        return True


def test_search_engine_persistent_cache_round_trips_between_instances(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SEARCH_CACHE_ENABLED", "1")
    monkeypatch.setenv("IPFS_DATASETS_SEARCH_CACHE_DIR", str(tmp_path))

    config = SearchEngineConfig(engine_type="dummy", cache_ttl_seconds=3600)
    first = _DummySearchEngine(config)
    cache_key = first._get_cache_key("Minn. Stat. 609.185", max_results=1)
    first._save_to_cache(cache_key, first.search("Minn. Stat. 609.185", max_results=1))

    second = _DummySearchEngine(config)
    cached = second._get_from_cache(cache_key)

    assert cached is not None
    assert cached.from_cache is True
    assert cached.results[0].url == "https://www.revisor.mn.gov/statutes/cite/609.185"
    assert cached.metadata["persistent_cache"]["namespace"] == "search_results"


def test_search_engine_persistent_cache_can_be_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SEARCH_CACHE_ENABLED", "0")
    monkeypatch.setenv("IPFS_DATASETS_SEARCH_CACHE_DIR", str(tmp_path))

    engine = _DummySearchEngine(SearchEngineConfig(engine_type="dummy"))

    assert engine.get_stats()["persistent_cache_enabled"] is False
