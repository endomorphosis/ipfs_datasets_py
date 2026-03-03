import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama import AlabamaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import BaseStateScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import CaliforniaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado import ColoradoScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut import ConnecticutScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import MississippiScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida import FloridaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import GeorgiaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.generic import GenericStateScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii import HawaiiScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import IndianaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import LouisianaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri import MissouriScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import NewYorkScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import OklahomaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon import OregonScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon_admin_rules import OregonAdministrativeRulesScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island import RhodeIslandScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota import SouthDakotaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee import TennesseeScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas import TexasScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import DelawareScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico import NewMexicoScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming import WyomingScraper


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


@pytest.mark.anyio
async def test_texas_section_fetch_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        body = ("Texas section body content with legal text. " * 20).encode("utf-8")
        return _FakeResponse(b"<html><body><div>" + body + b"</div></body></html>")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = TexasScraper("TX", "Texas")
    text = await scraper._fetch_section_text("https://example.tx/section", fallback_text="fallback")

    assert "Texas section body" in text
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_florida_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = (
            "<html><body>"
            "<a href='/statutes/title1'>Florida statute title 1</a>"
            "</body></html>"
        ).encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = FloridaScraper("FL", "Florida")
    statutes = await scraper.scrape_code("Florida Statutes", "http://example.fl/statutes")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_colorado_pdf_summary_fetch_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        return _FakeResponse(b"%PDF-1.4 fake colorado pdf")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = ColoradoScraper("CO", "Colorado")
    _ = await scraper._extract_pdf_text_summary("https://example.co/doc.pdf")

    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_connecticut_custom_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = (
            "<html><body>"
            "<a href='/current/pub/chap001.htm'>Chapter 001 General Provisions</a>"
            "</body></html>"
        ).encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = ConnecticutScraper("CT", "Connecticut")
    statutes = await scraper._custom_scrape_connecticut("Connecticut General Statutes", "https://example.ct/titles", "Conn. Gen. Stat.")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_rhode_island_custom_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = (
            "<html><body>"
            "<a href='/statutes/title1/chapter1'>Title 1 Chapter 1</a>"
            "</body></html>"
        ).encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = RhodeIslandScraper("RI", "Rhode Island")
    statutes = await scraper._custom_scrape_rhode_island("Rhode Island General Laws", "http://example.ri/statutes", "R.I. Gen. Laws")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_south_dakota_request_json_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        payload = b'{"Statute":"1-1-1","CatchLine":"General law","Html":"<p>Long legal text</p>"}'
        return _FakeResponse(payload)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = SouthDakotaScraper("SD", "South Dakota")
    data = await scraper._request_json("https://example.sd/api", headers={}, timeout=20)

    assert data.get("Statute") == "1-1-1"
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_delaware_custom_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = (
            "<html><body>"
            "<a href='/title1/c001/index.html'>Chapter 1</a>"
            "</body></html>"
        ).encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = DelawareScraper("DE", "Delaware")
    statutes = await scraper._custom_scrape_delaware("Delaware Code", "https://example.de/title1", "Del. Code")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_wyoming_custom_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = (
            "<html><body>"
            "<a href='/stateStatutes/title1'>Title 1 General Provisions</a>"
            "</body></html>"
        ).encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = WyomingScraper("WY", "Wyoming")
    statutes = await scraper._custom_scrape_wyoming("Wyoming Statutes", "https://example.wy/statutes", "Wyo. Stat.")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_california_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    html = (
            "<html><body>"
            "<a href='/faces/codes_displayText.xhtml?lawCode=PEN&amp;sectionNum=187.'>Section 187</a>"
            "</body></html>"
    ).encode("utf-8")

    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return html

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = CaliforniaScraper("CA", "California")
    statutes = await scraper.scrape_code("Penal Code", "https://example.ca/codes")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_new_mexico_request_bytes_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        return _FakeResponse(b"%PDF-1.4 fake new mexico statute")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = NewMexicoScraper("NM", "New Mexico")
    payload = await scraper._request_bytes("https://example.nm/statute.pdf", headers={}, timeout=20)

    assert payload.startswith(b"%PDF")
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_mississippi_request_text_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = "<html><body><h1>History of Actions</h1><p>House Bill 1234</p></body></html>".encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr("requests.get", _fake_get)

    scraper = MississippiScraper("MS", "Mississippi")
    text = await scraper._request_text("https://example.ms/history/HB1234.htm", headers={}, timeout=20)

    assert "History of Actions" in text
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_hawaii_request_text_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return b"<html><body>Hawaii statute archive text</body></html>"

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = HawaiiScraper("HI", "Hawaii")
    text = await scraper._request_text("https://example.hi/archive", headers={}, timeout=20)

    assert "Hawaii statute" in text
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_tennessee_custom_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    html = (
        "<html><body>"
        "<a href='/acts/title10'>Title 10 criminal code</a>"
        "</body></html>"
    ).encode("utf-8")

    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return html

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = TennesseeScraper("TN", "Tennessee")
    statutes = await scraper._custom_scrape_tennessee("Tennessee Code Annotated", "https://example.tn/archives", "Tenn. Code Ann.")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_missouri_custom_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    home_html = (
        "<html><body>"
        "<a href='/main/OneChapter.aspx?chapter=1'>Chapter 1</a>"
        "</body></html>"
    ).encode("utf-8")
    chapter_html = (
        "<html><body>"
        "<a href='/main/OneSection.aspx?section=1.010'>Section 1.010</a>"
        "</body></html>"
    ).encode("utf-8")

    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if "OneChapter.aspx" in url:
            return chapter_html
        return home_html

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = MissouriScraper("MO", "Missouri")
    statutes = await scraper._custom_scrape_missouri("Missouri Revised Statutes", "https://example.mo/home", "Mo. Rev. Stat.")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_generic_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    html = (
        "<html><body>"
        "<a href='/code/section-1'>Section 1.010 definitions</a>"
        "</body></html>"
    ).encode("utf-8")

    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return html

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = GenericStateScraper("ZZ", "Test State")
    statutes = await scraper.scrape_code("Test Code", "https://example.zz/code")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_oklahoma_cdx_discovery_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    cdx_json = b'[["urlkey","timestamp","original"],["u","20200101120000","https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=12345"]]'

    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return cdx_json

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = OklahomaScraper("OK", "Oklahoma")
    urls = await scraper._discover_oscn_document_urls_via_cdx(headers={})

    assert any("CiteID=12345" in url for url in urls)
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_oregon_discover_chapter_urls_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    html = (
        "<html><body>"
        "<a href='/bills_laws/ors/ors001.html'>Chapter 1</a>"
        "<a href='/bills_laws/ors/ors002.html'>Chapter 2</a>"
        "</body></html>"
    ).encode("utf-8")

    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return html

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = OregonScraper("OR", "Oregon")
    urls = await scraper._discover_chapter_urls("https://www.oregonlegislature.gov/bills_laws/ors/ors001.html")

    assert len(urls) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_oregon_admin_rules_cdx_discovery_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    cdx_json = b'[["original"],["https://secure.sos.state.or.us/oard/displayChapterRules.action?selectedChapter=137"]]'

    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return cdx_json

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = OregonScraper("OR", "Oregon")
    helper = OregonAdministrativeRulesScraper(scraper)
    urls = await helper._discover_chapter_urls_from_cdx()

    assert any("selectedChapter=137" in url for url in urls)
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


def test_generic_get_code_list_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    html = (
        "<html><body>"
        "<a href='/codes/title-1'>Title 1 General Code</a>"
        "</body></html>"
    ).encode("utf-8")

    def _fake_fetch_sync(self, url: str, timeout_seconds: int = 30) -> bytes:
        self._record_fetch_event(provider="test_fake_sync", success=True)
        return html

    monkeypatch.setattr(GenericStateScraper, "_fetch_url_bytes_sync", _fake_fetch_sync)

    scraper = GenericStateScraper("ZZ", "Test State")
    codes = scraper.get_code_list()

    assert len(codes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0
