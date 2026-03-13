from __future__ import annotations

from types import SimpleNamespace
import sys
import types

import pytest

from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
    ScraperConfig,
    ScraperMethod,
    ScraperResult,
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


def test_parse_method_names_accepts_cloudflare_alias() -> None:
    methods = UnifiedWebScraper._parse_method_names(["cloudflare", "requests"])

    assert methods == [
        ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
        ScraperMethod.REQUESTS_ONLY,
    ]


class _FakeResponse:
    def __init__(self, *, content: bytes, headers: dict[str, str] | None = None, status_code: int = 200, text: str | None = None):
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code
        self.text = text if text is not None else content.decode("utf-8", errors="replace")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.mark.anyio
async def test_requests_only_retries_with_relaxed_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = pytest.importorskip("requests")
    calls: list[bool] = []

    def _fake_get(_url: str, *, timeout: int, verify: bool, **_kwargs):
        calls.append(verify)
        if verify:
            raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")
        return _FakeResponse(
            content=b"<html><title>Recovered</title><body>ok</body></html>",
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    scraper = UnifiedWebScraper(ScraperConfig(timeout=5, verify_ssl=True, retry_insecure_ssl=True))
    scraper.session = SimpleNamespace(get=_fake_get)

    result = await scraper._scrape_requests_only("https://badssl.example.gov/")

    assert result.success is True
    assert result.title == "Recovered"
    assert result.metadata["ssl_verification_relaxed"] is True
    assert calls == [True, False]


@pytest.mark.anyio
async def test_beautifulsoup_returns_pdf_bytes_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_bytes = b"%PDF-1.4 fake"

    scraper = UnifiedWebScraper(ScraperConfig())
    scraper.session = SimpleNamespace(
        get=lambda *_args, **_kwargs: _FakeResponse(
            content=pdf_bytes,
            headers={
                "Content-Type": "application/pdf",
                "Content-Disposition": 'attachment; filename="rules.pdf"',
            },
        )
    )

    async def _fake_extract_pdf_text(_raw: bytes) -> str:
        return "Parsed PDF text"

    monkeypatch.setattr(scraper, "_extract_pdf_text", _fake_extract_pdf_text)

    result = await scraper._scrape_beautifulsoup("https://example.gov/rules")

    assert result.success is True
    assert result.title == "rules.pdf"
    assert result.text == "Parsed PDF text"
    assert result.metadata["binary_document"] is True
    assert result.metadata["content_type"] == "application/pdf"
    assert result.metadata["raw_bytes"] == pdf_bytes


@pytest.mark.anyio
async def test_cloudflare_browser_rendering_returns_completed_record(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = UnifiedWebScraper(
        ScraperConfig(
            cloudflare_account_id="acct-test",
            cloudflare_api_token="token-test",
        )
    )

    async def _fake_crawl(url: str, **kwargs):
        assert url == "https://example.gov/rules"
        assert kwargs["account_id"] == "acct-test"
        assert kwargs["api_token"] == "token-test"
        return {
            "status": "success",
            "job_id": "job-123",
            "job": {"status": "completed"},
            "records": [
                {
                    "url": "https://example.gov/rules",
                    "status": "completed",
                    "markdown": "# Rules\n\nCurrent administrative rules.",
                    "metadata": {
                        "title": "Example Rules",
                        "status": 200,
                    },
                }
            ],
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine.crawl_with_cloudflare_browser_rendering",
        _fake_crawl,
    )

    result = await scraper._scrape_cloudflare_browser_rendering("https://example.gov/rules")

    assert result.success is True
    assert result.method_used == ScraperMethod.CLOUDFLARE_BROWSER_RENDERING
    assert result.title == "Example Rules"
    assert result.text == "# Rules\n\nCurrent administrative rules."
    assert result.metadata["cloudflare_job_id"] == "job-123"
    assert result.metadata["cloudflare_record_status"] == "completed"


@pytest.mark.anyio
async def test_cloudflare_browser_rendering_preserves_rate_limit_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = UnifiedWebScraper(
        ScraperConfig(
            cloudflare_account_id="acct-test",
            cloudflare_api_token="token-test",
            cloudflare_max_rate_limit_wait_seconds=30.0,
        )
    )

    async def _fake_crawl(url: str, **kwargs):
        assert url == "https://example.gov/rules"
        assert kwargs["max_rate_limit_wait_seconds"] == 30.0
        return {
            "status": "rate_limited",
            "error": "2001: Rate limit exceeded",
            "retryable": True,
            "retry_after_seconds": 600.0,
            "retry_at_utc": "2026-03-12T00:00:00+00:00",
            "wait_budget_exhausted": True,
            "rate_limit_diagnostics": {
                "cf_ray": "test-ray",
                "cf_auditlog_id": "audit-id",
                "error_code": "2001",
            },
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine.crawl_with_cloudflare_browser_rendering",
        _fake_crawl,
    )

    result = await scraper._scrape_cloudflare_browser_rendering("https://example.gov/rules")

    assert result.success is False
    assert result.method_used == ScraperMethod.CLOUDFLARE_BROWSER_RENDERING
    assert result.metadata["cloudflare_status"] == "rate_limited"
    assert result.metadata["retryable"] is True
    assert result.metadata["retry_after_seconds"] == 600.0
    assert result.metadata["retry_at_utc"] == "2026-03-12T00:00:00+00:00"
    assert result.metadata["wait_budget_exhausted"] is True
    assert result.metadata["rate_limit_diagnostics"]["cf_ray"] == "test-ray"
    assert result.metadata["rate_limit_diagnostics"]["cf_auditlog_id"] == "audit-id"


@pytest.mark.anyio
async def test_cloudflare_browser_rendering_marks_browser_challenge_record(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = UnifiedWebScraper(
        ScraperConfig(
            cloudflare_account_id="acct-test",
            cloudflare_api_token="token-test",
        )
    )

    async def _fake_crawl(url: str, **kwargs):
        return {
            "status": "success",
            "job_id": "job-403",
            "job": {"status": "completed"},
            "records": [
                {
                    "url": url,
                    "status": "errored",
                    "markdown": "Just a moment...\nEnable JavaScript and cookies to continue",
                    "metadata": {
                        "status": 403,
                        "title": "Just a moment...",
                    },
                }
            ],
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine.crawl_with_cloudflare_browser_rendering",
        _fake_crawl,
    )

    result = await scraper._scrape_cloudflare_browser_rendering("https://example.gov/rules")

    assert result.success is False
    assert result.method_used == ScraperMethod.CLOUDFLARE_BROWSER_RENDERING
    assert result.metadata["cloudflare_status"] == "browser_challenge"
    assert result.metadata["cloudflare_http_status"] == 403
    assert result.metadata["cloudflare_browser_challenge_detected"] is True
    assert "browser challenge detected" in result.errors[0]


@pytest.mark.anyio
async def test_cloudflare_browser_rendering_rejects_completed_js_shell_record(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = UnifiedWebScraper(
        ScraperConfig(
            cloudflare_account_id="acct-test",
            cloudflare_api_token="token-test",
        )
    )

    async def _fake_crawl(url: str, **kwargs):
        return {
            "status": "success",
            "job_id": "job-shell",
            "job": {"status": "completed"},
            "records": [
                {
                    "url": url,
                    "status": "completed",
                    "markdown": "Indiana Register\nYou need to enable JavaScript to run this app.",
                    "html": "<html><head><title>Indiana Register</title></head><body>You need to enable JavaScript to run this app.</body></html>",
                    "metadata": {
                        "status": 200,
                        "title": "Indiana Register",
                    },
                }
            ],
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine.crawl_with_cloudflare_browser_rendering",
        _fake_crawl,
    )

    result = await scraper._scrape_cloudflare_browser_rendering("https://example.gov/rules")

    assert result.success is False
    assert result.method_used == ScraperMethod.CLOUDFLARE_BROWSER_RENDERING
    assert result.metadata["cloudflare_status"] == "browser_challenge"
    assert result.metadata["cloudflare_http_status"] == 200
    assert result.metadata["cloudflare_browser_challenge_detected"] is True
    assert "browser challenge detected" in result.errors[0]


@pytest.mark.anyio
async def test_binary_pdf_uses_repo_pdf_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePDFProcessor:
        async def _decompose_pdf(self, pdf_path):
            assert str(pdf_path).endswith(".pdf")
            return {
                "pages": [
                    {
                        "text_blocks": [
                            {"content": "Rule 1. Scope."},
                            {"content": "Authority and purpose."},
                        ]
                    }
                ]
            }

        def _extract_native_text(self, text_blocks):
            return "\n".join(block["content"] for block in text_blocks)

        async def _process_ocr(self, _decomposed_content):
            return {}

    fake_pdf_module = SimpleNamespace(PDFProcessor=FakePDFProcessor)
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.processors.specialized.pdf", fake_pdf_module)

    extracted = await UnifiedWebScraper._extract_pdf_text(b"%PDF-1.4 fake pdf bytes")

    assert "Rule 1. Scope." in extracted
    assert "Authority and purpose." in extracted


@pytest.mark.anyio
async def test_fallback_submits_archive_is_only_after_snapshot_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = UnifiedWebScraper(
        ScraperConfig(
            preferred_methods=[ScraperMethod.ARCHIVE_IS],
            archive_is_submit_on_miss=True,
            archive_is_submit_retries=1,
        )
    )
    scraper.available_methods[ScraperMethod.ARCHIVE_IS] = True

    calls: list[bool] = []

    async def _fake_scrape_archive_is(url: str, submit_on_miss: bool = False, **_kwargs):
        calls.append(submit_on_miss)
        if submit_on_miss:
            return ScraperResult(
                url=url,
                success=False,
                method_used=ScraperMethod.ARCHIVE_IS,
                errors=["Archive.is capture submitted and is still pending"],
            )
        return ScraperResult(
            url=url,
            success=False,
            method_used=ScraperMethod.ARCHIVE_IS,
            errors=["Archive.is returned no archived snapshot"],
        )

    monkeypatch.setattr(scraper, "_scrape_archive_is", _fake_scrape_archive_is)

    result = await scraper._scrape_with_fallback("https://example.gov/moved")

    assert result.success is False
    assert calls == [False, True]
    assert "Archive.is capture submitted and is still pending" in result.errors


# ---------------------------------------------------------------------------
# RTF support in _is_binary_document_response and _build_binary_document_result
# ---------------------------------------------------------------------------


def test_rtf_url_flagged_as_binary_document_response() -> None:
    scraper = UnifiedWebScraper(ScraperConfig())
    assert scraper._is_binary_document_response(
        url="https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
        content_type="text/html",
        content_disposition="",
    )


def test_rtf_content_type_flagged_as_binary_document_response() -> None:
    scraper = UnifiedWebScraper(ScraperConfig())
    assert scraper._is_binary_document_response(
        url="https://example.gov/document",
        content_type="application/rtf",
        content_disposition="",
    )


@pytest.mark.anyio
async def test_extract_rtf_text_fallback_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    """_extract_rtf_text returns plain text via regex fallback when RTFExtractor unavailable."""
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.processors.file_converter", None)

    rtf_bytes = rb"{\rtf1\ansi{\*\generator Msftedit;}\pard ARTICLE I General Rules\par}"
    extracted = await UnifiedWebScraper._extract_rtf_text(rtf_bytes)
    assert "ARTICLE" in extracted or "General" in extracted


@pytest.mark.anyio
async def test_build_binary_document_result_extracts_rtf_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_binary_document_result calls _extract_rtf_text for .rtf URLs."""
    scraper = UnifiedWebScraper(ScraperConfig())

    async def _fake_extract_rtf(rtf_bytes: bytes) -> str:
        return "ARTICLE I General Rules"

    monkeypatch.setattr(UnifiedWebScraper, "_extract_rtf_text", staticmethod(_fake_extract_rtf))

    class _FakeResp:
        headers: dict = {"Content-Type": "application/rtf", "Content-Disposition": ""}
        content = b"{\\rtf1 fake rtf content}"
        status_code = 200

    result = await scraper._build_binary_document_result(
        url="https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
        response=_FakeResp(),
        method=ScraperMethod.BEAUTIFULSOUP,
        ssl_verification_relaxed=False,
    )

    assert result.success is True
    assert "ARTICLE I" in result.text
