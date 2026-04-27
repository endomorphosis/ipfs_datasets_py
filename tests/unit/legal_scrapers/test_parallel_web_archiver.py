from __future__ import annotations

import sys
import types

import pytest

from ipfs_datasets_py.processors.legal_scrapers.parallel_web_archiver import (
    ArchiveResult,
    ParallelWebArchiver,
)
from ipfs_datasets_py.processors.legal_scrapers import parallel_web_archiver as archiver_module
from ipfs_datasets_py.processors.legal_scrapers import huggingface_api_search as hf_search_module


@pytest.mark.anyio
async def test_archive_urls_parallel_gathers_each_url_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archiver_module, "HAVE_AIOHTTP", True)
    monkeypatch.setattr(archiver_module.SharedFetchCache, "from_env", staticmethod(lambda: None))

    seen_urls: list[str] = []

    async def _fake_archive_single_url(
        self: ParallelWebArchiver,
        url: str,
        *,
        jurisdiction: str | None = None,
        state_code: str | None = None,
    ) -> ArchiveResult:
        seen_urls.append(url)
        return ArchiveResult(
            url=url,
            success=True,
            content=f"content:{url}",
            source="test",
        )

    monkeypatch.setattr(ParallelWebArchiver, "_archive_single_url", _fake_archive_single_url)

    archiver = ParallelWebArchiver(max_concurrent=2)
    urls = [
        "https://example.com/one",
        "https://example.com/two",
        "https://example.com/three",
    ]

    results = await archiver.archive_urls_parallel(urls)

    assert seen_urls == urls
    assert [result.url for result in results] == urls
    assert [result.content for result in results] == [f"content:{url}" for url in urls]


def test_parallel_web_archiver_initializes_hf_search_without_explicit_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    class _FakeSearch:
        def __init__(self, api_key=None, **kwargs):
            observed["api_key"] = api_key
            observed["kwargs"] = dict(kwargs)

    monkeypatch.setattr(archiver_module, "HAVE_HF_API", True)
    monkeypatch.setattr(archiver_module, "HuggingFaceAPISearch", _FakeSearch)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)

    archiver = ParallelWebArchiver(use_warc_pointers=True)

    assert archiver.use_warc_pointers is True
    assert isinstance(archiver._hf_search, _FakeSearch)
    assert observed["api_key"] is None


def test_huggingface_api_search_uses_cli_token_and_org_bill_to(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeInferenceClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(hf_search_module, "InferenceClient", _FakeInferenceClient)
    monkeypatch.setattr(hf_search_module, "HAVE_HF_HUB", True)
    monkeypatch.setenv("HF_ORGANIZATION", "Publicus")
    monkeypatch.delenv("IPFS_DATASETS_PY_HF_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACEHUB_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_API_TOKEN", raising=False)
    monkeypatch.setattr(hf_search_module.importlib, "import_module", lambda name: type("_Hub", (), {"get_token": staticmethod(lambda: "cli-token")})())

    searcher = hf_search_module.HuggingFaceAPISearch(use_streaming=False)

    assert searcher.api_key == "cli-token"
    assert searcher.bill_to == "Publicus"
    assert captured["token"] == "cli-token"
    assert captured["bill_to"] == "Publicus"


def test_huggingface_api_search_honors_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hf_search_module, "HAVE_DATASETS", True)
    monkeypatch.setattr(
        hf_search_module,
        "load_dataset",
        lambda *args, **kwargs: iter(
            [
                {"url": "https://example.com/1", "text": "epa enforcement action"},
                {"url": "https://example.com/2", "text": "epa water guidance"},
            ]
        ),
        raising=False,
    )

    searcher = hf_search_module.HuggingFaceAPISearch(api_key="hf-test-token", use_streaming=True, max_results=10)

    results = searcher.search("epa", max_results=1)

    assert len(results) == 1
    assert results[0]["url"] == "https://example.com/1"


def test_huggingface_api_search_defaults_to_state_jurisdiction(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def _fake_search_state(query, state_code=None, filters=None, max_results=None):
        observed["query"] = query
        observed["state_code"] = state_code
        observed["filters"] = filters
        observed["max_results"] = max_results
        return [{"url": "https://example.com/state"}]

    def _fail_search_federal(*args, **kwargs):
        raise AssertionError("federal search should not be the default")

    searcher = hf_search_module.HuggingFaceAPISearch(use_streaming=False)
    monkeypatch.setattr(searcher, "search_state", _fake_search_state)
    monkeypatch.setattr(searcher, "search_federal", _fail_search_federal)

    results = searcher.search("administrative rules")

    assert results == [{"url": "https://example.com/state"}]
    assert observed["query"] == "administrative rules"
    assert observed["state_code"] is None


def test_huggingface_api_search_redirects_federal_to_state_in_admin_rules_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def _fake_search_state(query, state_code=None, filters=None, max_results=None):
        observed["query"] = query
        observed["state_code"] = state_code
        return [{"url": "https://example.com/state"}]

    def _fail_search_federal(*args, **kwargs):
        raise AssertionError("federal search should be redirected in admin-rules mode")

    monkeypatch.setenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES", "1")

    searcher = hf_search_module.HuggingFaceAPISearch(use_streaming=False)
    monkeypatch.setattr(searcher, "search_state", _fake_search_state)
    monkeypatch.setattr(searcher, "search_federal", _fail_search_federal)

    results = searcher.search("administrative rules", jurisdiction="federal")

    assert results == [{"url": "https://example.com/state"}]
    assert observed["query"] == "administrative rules"


def test_huggingface_api_search_search_federal_redirects_in_admin_rules_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def _fake_search_state(query, state_code=None, filters=None, max_results=None):
        observed["query"] = query
        observed["state_code"] = state_code
        observed["filters"] = filters
        observed["max_results"] = max_results
        return [{"url": "https://example.com/state"}]

    monkeypatch.setenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES", "1")

    searcher = hf_search_module.HuggingFaceAPISearch(use_streaming=False)
    monkeypatch.setattr(searcher, "search_state", _fake_search_state)

    results = searcher.search_federal("administrative rules", filters={"kind": "rule"}, max_results=3)

    assert results == [{"url": "https://example.com/state"}]
    assert observed["query"] == "administrative rules"
    assert observed["filters"] == {"kind": "rule"}
    assert observed["max_results"] == 3


@pytest.mark.anyio
async def test_get_warc_pointer_uses_passed_state_context(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    class _FakeSearch:
        def search(self, **kwargs):
            observed.update(kwargs)
            return [{"url": kwargs["query"], "warc_file": "crawl.warc.gz", "warc_offset": 10, "warc_length": 20}]

    monkeypatch.setattr(archiver_module, "HAVE_HF_API", True)

    archiver = ParallelWebArchiver(use_warc_pointers=False)
    archiver._hf_search = _FakeSearch()

    result = await archiver.get_warc_pointer(
        "https://rules.example.gov/title-1",
        jurisdiction="state",
        state_code="tx",
    )

    assert result is not None
    assert observed["jurisdiction"] == "state"
    assert observed["state_code"] == "TX"
    assert observed["max_results"] == 1
    assert result["warc_file"] == "crawl.warc.gz"


@pytest.mark.anyio
async def test_get_warc_pointer_normalizes_state_index_pointer_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSearch:
        def search(self, **kwargs):
            return [
                {
                    "url": kwargs["query"],
                    "warc_filename": "crawl-data/state.warc.gz",
                    "warc_offset": "10",
                    "warc_length": "20",
                    "state_code": "TX",
                }
            ]

    archiver = ParallelWebArchiver(use_warc_pointers=False)
    archiver._hf_search = _FakeSearch()

    result = await archiver.get_warc_pointer("https://rules.example.gov/title-1", jurisdiction="state", state_code="TX")

    assert result is not None
    assert result["warc_file"] == "crawl-data/state.warc.gz"
    assert result["warc_filename"] == "crawl-data/state.warc.gz"
    assert result["warc_offset"] == 10
    assert result["warc_length"] == 20


@pytest.mark.anyio
async def test_archive_via_warc_fetches_body_from_state_index_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSearch:
        def search(self, **kwargs):
            return [
                {
                    "url": kwargs["query"],
                    "warc_filename": "crawl-data/state.warc.gz",
                    "warc_offset": 10,
                    "warc_length": 20,
                    "state_code": "TX",
                }
            ]

    class _FakeCommonCrawlSearchEngine:
        def __init__(self, mode="local"):
            self.mode = mode

        def fetch_warc_record(self, warc_filename, warc_offset, warc_length):
            assert warc_filename == "crawl-data/state.warc.gz"
            assert warc_offset == 10
            assert warc_length == 20
            return b"fake gz member"

    fake_integration = types.ModuleType("ipfs_datasets_py.processors.web_archiving.common_crawl_integration")
    fake_integration.CommonCrawlSearchEngine = _FakeCommonCrawlSearchEngine
    fake_integration._ensure_common_crawl_import_path = lambda: None

    fake_ccapi = types.SimpleNamespace(
        extract_http_from_warc_gzip_member=lambda raw, **kwargs: types.SimpleNamespace(
            ok=True,
            body_text_preview="Recovered administrative rule text",
        )
    )

    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.processors.web_archiving.common_crawl_integration", fake_integration)
    monkeypatch.setitem(sys.modules, "common_crawl_search_engine", types.ModuleType("common_crawl_search_engine"))
    monkeypatch.setitem(sys.modules, "common_crawl_search_engine.ccindex", types.SimpleNamespace(api=fake_ccapi))
    monkeypatch.setitem(sys.modules, "common_crawl_search_engine.ccindex.api", fake_ccapi)

    archiver = ParallelWebArchiver(use_warc_pointers=False)
    archiver._hf_search = _FakeSearch()

    result = await archiver._archive_via_warc(
        "https://rules.example.gov/title-1",
        jurisdiction="state",
        state_code="TX",
    )

    assert result is not None
    assert result.success is True
    assert result.source == "warc"
    assert result.content == "Recovered administrative rule text"
    assert result.warc_pointer is not None
    assert result.warc_pointer["warc_file"] == "crawl-data/state.warc.gz"


@pytest.mark.anyio
async def test_archive_urls_parallel_threads_state_context_into_single_url_archives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(archiver_module, "HAVE_AIOHTTP", True)
    monkeypatch.setattr(archiver_module.SharedFetchCache, "from_env", staticmethod(lambda: None))

    observed: list[tuple[str, str | None, str | None]] = []

    async def _fake_archive_single_url(
        self: ParallelWebArchiver,
        url: str,
        *,
        jurisdiction: str | None = None,
        state_code: str | None = None,
    ) -> ArchiveResult:
        observed.append((url, jurisdiction, state_code))
        return ArchiveResult(url=url, success=True, content="ok", source="test")

    monkeypatch.setattr(ParallelWebArchiver, "_archive_single_url", _fake_archive_single_url)

    archiver = ParallelWebArchiver(max_concurrent=2)
    await archiver.archive_urls_parallel(
        ["https://rules.example.gov/1", "https://rules.example.gov/2"],
        jurisdiction="state",
        state_code="az",
    )

    assert sorted(observed) == sorted([
        ("https://rules.example.gov/1", "state", "AZ"),
        ("https://rules.example.gov/2", "state", "AZ"),
    ])
