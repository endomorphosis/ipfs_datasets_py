"""
Phase B2 unit tests — web_scraping_tools category.

Covers: scrape_url_tool, scrape_multiple_urls_tool, check_scraper_methods_tool

web_scraping_tools imports from processors.web_archiving which requires pydantic,
bs4, playwright, etc.  We inject a minimal module stub into sys.modules before
importing the tool functions so the tests work without those heavy deps.
"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest.mock as m
import pytest


# ---------------------------------------------------------------------------
# Build the unified_web_scraper module stub before any tool import
# ---------------------------------------------------------------------------

def _build_scraper_stub() -> None:
    """
    Inject a minimal stub for
    ipfs_datasets_py.processors.web_archiving.unified_web_scraper
    so that web_scraping_tools can be imported without pydantic / bs4.
    """
    if "ipfs_datasets_py.processors.web_archiving.unified_web_scraper" in sys.modules:
        return  # already installed

    # Ensure parent stubs don't interfere
    for dep in ("bs4", "pydantic", "playwright", "playwright.async_api"):
        if dep not in sys.modules:
            sys.modules[dep] = m.MagicMock()
    if "ipfs_datasets_py.processors.web_archiving" not in sys.modules:
        sys.modules["ipfs_datasets_py.processors.web_archiving"] = m.MagicMock()

    mod = types.ModuleType(
        "ipfs_datasets_py.processors.web_archiving.unified_web_scraper"
    )

    # ---- ScraperConfig ----
    class _Config:
        def __init__(self, **kw: object) -> None:
            for k, v in kw.items():
                setattr(self, k, v)

    # ---- Fake scrape result ----
    class _Result:
        def __init__(self, url: str, success: bool = True) -> None:
            self.success = success
            self.url = url
            self.content = "test content"
            self.html = "<html>test</html>"
            self.title = "Test Page"
            self.text = "test content"
            self.links: list = []
            self.method_used = type("M", (), {"value": "requests_only"})()
            self.metadata: dict = {}
            self.extraction_time = 0.05
            self.timestamp = "2026-01-01T00:00:00"
            self.errors: list = []

    # ---- Fake scraper ----
    class _Scraper:
        def __init__(self, config: object = None) -> None:
            self.available_methods: dict = {}

        def scrape_sync(self, url: str, method: object = None, **kw: object) -> "_Result":
            return _Result(url, success=True)

        def scrape_multiple_sync(
            self,
            urls: list,
            max_concurrent: int = 5,
            method: object = None,
            **kw: object,
        ) -> list:
            return [_Result(u, success=True) for u in urls]

    # ---- Fake ScraperMethod enum-like ----
    class _MethodVal:
        def __init__(self, v: str) -> None:
            self.value = v

    class _ScraperMethod:
        PLAYWRIGHT = _MethodVal("playwright")
        BS4 = _MethodVal("beautifulsoup")

        def __iter__(self):  # type: ignore[no-untyped-def]
            return iter([self.PLAYWRIGHT, self.BS4])

        def __call__(self, v: str) -> None:  # type: ignore[override]
            raise ValueError(f"Invalid method: {v}")

    async def _scrape_url(url: str, config: object = None) -> dict:
        return {"url": url, "status": "success", "content": ""}

    async def _scrape_urls(urls: list, config: object = None) -> list:
        return [{"url": u, "status": "success"} for u in urls]

    mod.ScraperConfig = _Config  # type: ignore[attr-defined]
    mod.ScraperMethod = _ScraperMethod()  # type: ignore[attr-defined]
    mod.UnifiedWebScraper = _Scraper  # type: ignore[attr-defined]
    mod.scrape_url = _scrape_url  # type: ignore[attr-defined]
    mod.scrape_urls = _scrape_urls  # type: ignore[attr-defined]

    sys.modules["ipfs_datasets_py.processors.web_archiving.unified_web_scraper"] = mod


_build_scraper_stub()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# scrape_url_tool
# ---------------------------------------------------------------------------

class TestScrapeUrlTool:
    """Tests for web_scraping_tools.unified_scraper_tool.scrape_url_tool()."""

    def setup_method(self) -> None:
        _build_scraper_stub()
        from ipfs_datasets_py.mcp_server.tools.web_scraping_tools.unified_scraper_tool import (
            scrape_url_tool,
        )
        self.fn = scrape_url_tool

    def test_returns_dict(self) -> None:
        result = _run(self.fn("http://example.com"))
        assert isinstance(result, dict)

    def test_has_status_key(self) -> None:
        result = _run(self.fn("http://example.com"))
        assert "status" in result

    def test_has_url_key(self) -> None:
        result = _run(self.fn("http://example.com"))
        assert "url" in result

    def test_timeout_param(self) -> None:
        result = _run(self.fn("http://example.com", timeout=10))
        assert isinstance(result, dict)

    def test_extract_links_param(self) -> None:
        result = _run(self.fn("http://example.com", extract_links=False))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# scrape_multiple_urls_tool
# ---------------------------------------------------------------------------

class TestScrapeMultipleUrlsTool:
    """Tests for web_scraping_tools.unified_scraper_tool.scrape_multiple_urls_tool()."""

    def setup_method(self) -> None:
        _build_scraper_stub()
        from ipfs_datasets_py.mcp_server.tools.web_scraping_tools.unified_scraper_tool import (
            scrape_multiple_urls_tool,
        )
        self.fn = scrape_multiple_urls_tool

    def test_returns_dict(self) -> None:
        result = _run(self.fn(["http://example.com"]))
        assert isinstance(result, dict)

    def test_has_status_key(self) -> None:
        result = _run(self.fn(["http://example.com"]))
        assert "status" in result

    def test_empty_list(self) -> None:
        result = _run(self.fn([]))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# check_scraper_methods_tool
# ---------------------------------------------------------------------------

class TestCheckScraperMethodsTool:
    """Tests for web_scraping_tools.unified_scraper_tool.check_scraper_methods_tool()."""

    def setup_method(self) -> None:
        _build_scraper_stub()
        from ipfs_datasets_py.mcp_server.tools.web_scraping_tools.unified_scraper_tool import (
            check_scraper_methods_tool,
        )
        self.fn = check_scraper_methods_tool

    def test_returns_dict(self) -> None:
        result = _run(self.fn())
        assert isinstance(result, dict)

    def test_has_status_key(self) -> None:
        result = _run(self.fn())
        assert "status" in result

    def test_has_all_methods_key(self) -> None:
        result = _run(self.fn())
        assert "all_methods" in result or "available_methods" in result
