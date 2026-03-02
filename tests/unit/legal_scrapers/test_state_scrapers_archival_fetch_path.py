import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama import AlabamaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import BaseStateScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import GeorgiaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import IndianaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import LouisianaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import NewYorkScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import OklahomaScraper


class _FakeResponse:
    def __init__(self, content: bytes):
        self.status_code = 200
        self.content = content
        self.text = content.decode("utf-8", errors="replace")

    def raise_for_status(self) -> None:
        return None


@pytest.mark.anyio
async def test_oklahoma_request_text_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        return _FakeResponse(b"<html><body><div>Oklahoma statute body text section 1.2.3.</div></body></html>")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = OklahomaScraper("OK", "Oklahoma")
    text = await scraper._request_text("https://example.ok/statute", headers={}, timeout=20)

    assert "Oklahoma statute body" in text
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_alabama_scrape_uses_archival_fetch_path(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = (
            "<html><body>"
            "<a href='/code/title1'>Title 1 General Provisions</a>"
            "</body></html>"
        ).encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = AlabamaScraper("AL", "Alabama")
    statutes = await scraper.scrape_code("Alabama Code", "http://example.al/code")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_indiana_pdf_fetch_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        # Minimal payload is enough for fetch analytics validation.
        return _FakeResponse(b"%PDF-1.4 fake pdf bytes")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = IndianaScraper("IN", "Indiana")
    _ = await scraper._request_bytes(
        "http://web.archive.org/web/20170215063144/http://iga.in.gov/static-documents/x.pdf",
        headers={},
        timeout=20,
    )

    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_georgia_custom_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = (
            "<html><body>"
            "<a href='/law/title1'>Title 1 General Provisions</a>"
            "</body></html>"
        ).encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = GeorgiaScraper("GA", "Georgia")
    statutes = await scraper._custom_scrape_georgia("Official Code of Georgia", "http://example.ga/laws", "Ga. Code Ann.")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_louisiana_archival_request_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = (
            "<html><body>"
            "<span id='ctl00_PageBody_LabelName'>9:100</span>"
            "<span id='ctl00_PageBody_LabelDocument'>A legal text body with section 9:100 content.</span>"
            "</body></html>"
        ).encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = LouisianaScraper("LA", "Louisiana")
    text = await scraper._request_text("http://example.la/law", headers={}, timeout=20)

    assert "legal text body" in text.lower()
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_new_york_fallback_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = (
            "<html><body>"
            "<a href='/laws/n.y._civil_practice_law_and_rules_section_101'>CPLR section 101</a>"
            "</body></html>"
        ).encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = NewYorkScraper("NY", "New York")
    statutes = await scraper._scrape_public_law_updates("New York Consolidated Laws", max_sections=5)

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0
