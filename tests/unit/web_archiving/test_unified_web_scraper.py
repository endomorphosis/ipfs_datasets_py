from __future__ import annotations

import sys
import types

import pytest

from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
    ScraperConfig,
    ScraperMethod,
    UnifiedWebScraper,
)


class _FakeLocator:
    def __init__(self, page: "_FakePage", kind: str) -> None:
        self._page = page
        self._kind = kind

    async def inner_text(self) -> str:
        if self._kind != "body":
            raise AssertionError(f"unexpected inner_text locator: {self._kind}")
        return self._page.current_text

    async def evaluate_all(self, _script: str):
        if self._kind != "a":
            raise AssertionError(f"unexpected evaluate_all locator: {self._kind}")
        return self._page.current_links


class _FakePage:
    def __init__(self) -> None:
        self.goto_wait_until = None
        self.goto_timeout = None
        self.wait_states: list[tuple[str, int]] = []
        self.wait_timeouts: list[int] = []
        self.current_text = "You need to enable JavaScript to run this app."
        self.current_links = []

    async def goto(self, _url: str, wait_until: str, timeout: int) -> None:
        self.goto_wait_until = wait_until
        self.goto_timeout = timeout

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.wait_states.append((state, timeout))

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        self.wait_timeouts.append(timeout_ms)
        if len(self.wait_timeouts) >= 2:
            self.current_text = "Indiana Administrative Code\nTITLE 10 Office of Attorney General\nARTICLE 1 UNCLAIMED PROPERTY"
            self.current_links = [
                {
                    "href": "https://iar.iga.in.gov/code/current/10/1",
                    "text": "ARTICLE 1 UNCLAIMED PROPERTY",
                }
            ]

    def locator(self, kind: str) -> _FakeLocator:
        return _FakeLocator(self, kind)

    async def content(self) -> str:
        return "<html><body><div id='root'></div></body></html>"

    async def title(self) -> str:
        return "Indiana Administrative Code | IARP"


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.closed = False

    async def new_page(self) -> _FakePage:
        return self._page

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.context_kwargs = None
        self.closed = False

    async def new_context(self, **kwargs) -> _FakeContext:
        self.context_kwargs = kwargs
        return _FakeContext(self._page)

    async def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self._browser = browser
        self.launch_kwargs = None

    async def launch(self, **kwargs) -> _FakeBrowser:
        self.launch_kwargs = kwargs
        return self._browser


class _FakePlaywrightManager:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.anyio
async def test_playwright_scraper_waits_for_hydrated_dom(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage()
    browser = _FakeBrowser(page)
    chromium = _FakeChromium(browser)

    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = lambda: _FakePlaywrightManager(chromium)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)

    scraper = UnifiedWebScraper(
        ScraperConfig(
            timeout=5,
            playwright_hydration_wait_ms=10,
            playwright_shell_retry_wait_ms=20,
        )
    )

    result = await scraper._scrape_playwright("https://iar.iga.in.gov/code")

    assert result.success is True
    assert result.method_used == ScraperMethod.PLAYWRIGHT
    assert "TITLE 10 Office of Attorney General" in result.text
    assert result.links == [
        {
            "url": "https://iar.iga.in.gov/code/current/10/1",
            "text": "ARTICLE 1 UNCLAIMED PROPERTY",
        }
    ]
    assert page.goto_wait_until == "domcontentloaded"
    assert page.wait_timeouts == [10, 20]
    assert browser.context_kwargs["locale"] == "en-US"
    assert browser.context_kwargs["viewport"] == {"width": 1440, "height": 900}
    assert "Mozilla/5.0" in browser.context_kwargs["user_agent"]


def test_common_crawl_search_options_autodetect_local_collection_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    home = tmp_path
    parquet_root = home / "ccindex_storage" / "parquet"
    collection_dir = parquet_root / "cc_pointers_by_collection" / "2025" / "CC-MAIN-2025-47"
    collection_dir.mkdir(parents=True)

    collection_db = home / "ccindex_storage" / "duckdb" / "cc_pointers_by_collection" / "CC-MAIN-2025-47.duckdb"
    collection_db.parent.mkdir(parents=True)
    collection_db.write_text("", encoding="ascii")

    monkeypatch.setenv("HOME", str(home))

    scraper = UnifiedWebScraper(ScraperConfig())

    options, meta_mode, hf_fallback_allowed = scraper._resolve_common_crawl_search_options(max_matches=7)

    assert options["parquet_root"] == parquet_root.resolve()
    assert options["collection_db"] == collection_db.resolve()
    assert options["max_matches"] == 7
    assert meta_mode == "collection"
    assert hf_fallback_allowed is True
    assert "hf_remote_meta" not in options


def test_common_crawl_search_options_enable_hf_remote_when_no_local_meta(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    scraper = UnifiedWebScraper(ScraperConfig())

    options, meta_mode, hf_fallback_allowed = scraper._resolve_common_crawl_search_options(max_matches=5)

    assert meta_mode == "none"
    assert hf_fallback_allowed is True
    assert options["hf_remote_meta"] is True
    assert options["hf_meta_index_dataset"] == "Publicus/common_crawl_pointer_indices"
    assert options["hf_pointer_dataset"] == "Publicus/common_crawl_pointers_by_collection"
    assert options["hf_revision"] == "main"
