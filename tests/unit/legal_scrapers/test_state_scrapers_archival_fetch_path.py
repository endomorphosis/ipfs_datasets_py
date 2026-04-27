import io
import zipfile

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama import AlabamaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import CaliforniaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado import ColoradoScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut import ConnecticutScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import MississippiScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida import FloridaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import GeorgiaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.generic import GenericStateScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii import HawaiiScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.illinois import IllinoisScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import IndianaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kansas import KansasScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import LouisianaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts import MassachusettsScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maine import MaineScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland import MarylandScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan import MichiganScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import MinnesotaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri import MissouriScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana import MontanaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska import NebraskaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada import NevadaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import NewYorkScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_dakota import NorthDakotaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import OklahomaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio import OhioScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon import OregonScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon_admin_rules import OregonAdministrativeRulesScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania import PennsylvaniaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island import RhodeIslandScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_carolina import SouthCarolinaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota import SouthDakotaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee import TennesseeScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas import TexasScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import DelawareScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import NewHampshireScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico import NewMexicoScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah import UtahScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming import WyomingScraper


class _FakeResponse:
    def __init__(self, content: bytes):
        self.status_code = 200
        self.content = content
        self.text = content.decode("utf-8", errors="replace")

    def raise_for_status(self) -> None:
        return None


def _make_fake_archival_fetch(fake_get):
    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        response = fake_get(url)
        return bytes(getattr(response, "content", b""))

    return _fake_fetch_with_archival


@pytest.mark.anyio
async def test_oklahoma_request_text_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        return _FakeResponse(b"<html><body><div>Oklahoma statute body text section 1.2.3.</div></body></html>")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

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

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

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

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

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

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

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

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

    scraper = LouisianaScraper("LA", "Louisiana")
    text = await scraper._request_text("http://example.la/law", headers={}, timeout=20)

    assert "legal text body" in text.lower()
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_louisiana_live_toc_discovers_law_pages(monkeypatch: pytest.MonkeyPatch):
    toc_html = (
        "<html><body><form action='./Laws_Toc.aspx?folder=75&level=Parent'>"
        "<input type='hidden' name='__VIEWSTATE' value='abc' />"
        "<input type='hidden' name='__EVENTVALIDATION' value='def' />"
        "<a href=\"javascript:__doPostBack('ctl00$ctl00$PageBody$PageContent$ListViewTOC1$ctrl0$LinkButton1a','')\">TITLE 1</a>"
        "</form></body></html>"
    )
    title_response_html = (
        "<html><body>"
        "<a href='Law.aspx?d=74079'>RS 1:1</a>"
        "<a href='Law.aspx?d=74089'>RS 1:2</a>"
        "</body></html>"
    )

    class _Resp:
        def __init__(self, text: str):
            self.status_code = 200
            self.text = text

        def raise_for_status(self):
            return None

    class _Session:
        def get(self, url, timeout=30, headers=None):
            return _Resp(toc_html)

        def post(self, url, data=None, timeout=45, headers=None):
            return _Resp(title_response_html)

    async def _fake_request_text(self, law_url: str, headers, timeout: int) -> str:
        if law_url.endswith("74079"):
            return (
                "<html><body>"
                "<span id='ctl00_PageBody_LabelName'>RS 1:1</span>"
                "<span id='ctl00_PageBody_LabelDocument'>"
                + ("Louisiana statute text one. " * 20)
                + "</span></body></html>"
            )
        return (
            "<html><body>"
            "<span id='ctl00_PageBody_LabelName'>RS 1:2</span>"
            "<span id='ctl00_PageBody_LabelDocument'>"
            + ("Louisiana statute text two. " * 20)
            + "</span></body></html>"
        )

    monkeypatch.setattr("requests.Session", _Session)
    monkeypatch.setattr(LouisianaScraper, "_request_text", _fake_request_text)

    scraper = LouisianaScraper("LA", "Louisiana")
    statutes = await scraper.scrape_code("Louisiana Revised Statutes", "https://legis.la.gov/legis/Laws_Toc.aspx", max_statutes=2)

    assert [row.section_number for row in statutes] == ["RS 1:1", "RS 1:2"]
    assert statutes[0].structured_data["discovery_method"] == "live_toc_postback"
    assert "Louisiana statute text one." in statutes[0].full_text


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

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

    scraper = NewYorkScraper("NY", "New York")
    statutes = await scraper._scrape_public_law_updates("New York Consolidated Laws", max_sections=5)

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_new_york_structured_public_law_crawl(monkeypatch: pytest.MonkeyPatch):
    payloads = {
        "https://r.jina.ai/http://https://newyork.public.law/laws": (
            "[Civil Practice Law & Rules](https://newyork.public.law/laws/n.y._civil_practice_law_&_rules)"
        ),
        "https://r.jina.ai/http://https://newyork.public.law/laws/n.y._civil_practice_law_&_rules": (
            "[1 Short Title Sections 101-102](https://newyork.public.law/laws/n.y._civil_practice_law_&_rules_article_1)"
        ),
        "https://r.jina.ai/http://https://newyork.public.law/laws/n.y._civil_practice_law_&_rules_article_1": (
            "[101 Short title](https://newyork.public.law/laws/n.y._civil_practice_law_&_rules_section_101)"
            "[102 Amendment](https://newyork.public.law/laws/n.y._civil_practice_law_&_rules_section_102)"
        ),
        "https://r.jina.ai/http://https://newyork.public.law/laws/n.y._civil_practice_law_&_rules_section_101": (
            "# N.Y. Civil Practice Law & Rules § 101 Short title\n\n"
            + ("Section 101 body text. " * 20)
        ),
        "https://r.jina.ai/http://https://newyork.public.law/laws/n.y._civil_practice_law_&_rules_section_102": (
            "# N.Y. Civil Practice Law & Rules § 102 Amendment\n\n"
            + ("Section 102 body text. " * 20)
        ),
    }

    async def _fake_request_text_direct(self, url: str, timeout: int = 24) -> str:
        return payloads.get(url, "")

    scraper = NewYorkScraper("NY", "New York")
    monkeypatch.setattr(NewYorkScraper, "_request_text_direct", _fake_request_text_direct)

    statutes = await scraper._scrape_public_law_structured("New York Consolidated Laws", max_sections=2)

    assert [row.section_number for row in statutes] == ["101", "102"]
    assert statutes[0].structured_data["source_kind"] == "public_law_structured_markdown"
    assert statutes[0].structured_data["discovery_method"] == "public_law_hierarchical_crawl"


@pytest.mark.anyio
async def test_texas_section_fetch_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        body = ("Texas section body content with legal text. " * 20).encode("utf-8")
        return _FakeResponse(b"<html><body><div>" + body + b"</div></body></html>")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

    scraper = TexasScraper("TX", "Texas")
    text = await scraper._fetch_section_text("https://example.tx/section", fallback_text="fallback")

    assert "Texas section body" in text
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_texas_admin_code_landing_page_returns_no_synthetic_section(monkeypatch: pytest.MonkeyPatch):
    landing_html = (
        "<html><head><meta http-equiv='refresh' content='0; url=https://texreg.sos.state.tx.us/public/readtac$ext.ViewTAC' /></head>"
        "<body><h1>Texas Administrative Code</h1><p>Welcome to the Texas Administrative Code.</p>"
        "<p>View the current Texas Administrative Code and publication details.</p></body></html>"
    ).encode("utf-8")

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return landing_html

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = TexasScraper("TX", "Texas")
    statutes = await scraper._scrape_texas_admin_code(
        code_name="Texas Administrative Code",
        code_url="https://texreg.sos.state.tx.us/public/readtac$ext.ViewTAC",
    )

    assert statutes == []


@pytest.mark.anyio
async def test_texas_statutory_code_uses_official_html_zip(monkeypatch: pytest.MonkeyPatch):
    downloads_json = b'{"StatuteCode":[{"code":"PE","CodeName":"Penal Code","Html":"/Zips/PE.htm.zip"}]}'
    chapter_html = (
        "<html><body><pre>"
        "<p class='center'>PENAL CODE</p>"
        "<p class='center'>TITLE 1. INTRODUCTORY PROVISIONS</p>"
        "<p class='center'>CHAPTER 1. GENERAL PROVISIONS</p>"
        "<p><a name='1.01'></a></p>"
        "<p><a>Sec. 1.01. SHORT TITLE.</a> This code shall be known and may be cited as the Penal Code.</p>"
        "<p>Acts 1973, 63rd Leg., p. 883, ch. 399.</p>"
        "<p><a name='1.02'></a></p>"
        "<p><a>Sec. 1.02. OBJECTIVES OF CODE.</a> The general purposes of this code are to establish a system of prohibitions. "
        + ("More statutory substance. " * 20)
        + "</p></pre></body></html>"
    ).encode("utf-8")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pe.1.htm", chapter_html)
    zip_bytes = zip_buffer.getvalue()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if url.endswith("StatuteCodeDownloads.json"):
            return downloads_json
        if url.endswith("/Zips/PE.htm.zip"):
            return zip_bytes
        return b"<html><body>Angular shell should not be parsed as statutes.</body></html>"

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = TexasScraper("TX", "Texas")
    statutes = await scraper.scrape_code("Penal Code", "https://statutes.capitol.texas.gov/Docs/PE/htm/PE.1.htm", max_statutes=2)

    assert [statute.section_number for statute in statutes] == ["1.01", "1.02"]
    assert statutes[0].structured_data["source_kind"] == "official_texas_statutes_html_zip"
    assert "SHORT TITLE" in statutes[0].section_name


@pytest.mark.anyio
async def test_tennessee_full_corpus_uses_justia_listing_and_section_markdown(monkeypatch: pytest.MonkeyPatch):
    index_html = (
        "<html><body>"
        "<a href='/codes/tennessee/2024/'>2024 Tennessee Code</a>"
        "</body></html>"
    ).encode("utf-8")
    year_html = (
        "<html><body>"
        "<a href='/codes/tennessee/title-1/'>Title 1 - CODE AND STATUTES</a>"
        "</body></html>"
    ).encode("utf-8")
    title_html = (
        "<html><body>"
        "<a href='/codes/tennessee/title-1/chapter-2/'>Chapter 2 - ENACTMENT OF CODE</a>"
        "</body></html>"
    ).encode("utf-8")
    chapter_html = (
        "<html><body>"
        "<a href='/codes/tennessee/title-1/chapter-2/section-1-2-101/'>Section 1-2-101 - Designation of code</a>"
        "<a href='/codes/tennessee/title-1/chapter-2/section-1-2-102/'>Section 1-2-102 - Preservation of enrolled draft</a>"
        "</body></html>"
    ).encode("utf-8")

    async def _fake_listing(self, url: str, timeout_seconds: int = 30) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if url == "https://law.justia.com/codes/tennessee/":
            return index_html
        if url == "https://law.justia.com/codes/tennessee/2024/":
            return year_html
        if url == "https://law.justia.com/codes/tennessee/title-1/":
            return title_html
        if url == "https://law.justia.com/codes/tennessee/title-1/chapter-2/":
            return chapter_html
        return b""

    async def _fake_section_markdown(self, url: str, timeout_seconds: int = 25) -> str:
        self._record_fetch_event(provider="test_fake", success=True)
        section_number = "1-2-101" if url.endswith("1-2-101/") else "1-2-102"
        caption = "Designation of code" if section_number == "1-2-101" else "Preservation of enrolled draft"
        return (
            f"# Tennessee Code § {section_number} (2024) - {caption} :: 2024 Tennessee Code\n\n"
            f"Section {section_number} - {caption}\n"
            f"TN Code § {section_number} (2024)\n"
            + ("Statutory text for testing. " * 25)
            + "\nDisclaimer: footer"
        )

    monkeypatch.setattr(TennesseeScraper, "_fetch_justia_listing_html", _fake_listing)
    monkeypatch.setattr(TennesseeScraper, "_fetch_justia_section_markdown", _fake_section_markdown)

    scraper = TennesseeScraper("TN", "Tennessee")
    statutes = await scraper.scrape_code("Tennessee Code Annotated", "https://law.justia.com/codes/tennessee/2024/", max_statutes=2)

    assert [statute.section_number for statute in statutes] == ["1-2-101", "1-2-102"]
    assert statutes[0].official_cite == "Tenn. Code Ann. § 1-2-101"
    assert statutes[0].structured_data["discovery_method"] == "justia_tennessee_code_tree"
    assert "Statutory text for testing." in statutes[0].full_text


@pytest.mark.anyio
async def test_new_hampshire_full_corpus_discovers_more_than_twelve_titles(monkeypatch: pytest.MonkeyPatch):
    title_links = "".join(
        f"<a href='NHTOC/title{i}.htm'>TITLE {i}: Title {i}</a>"
        for i in range(1, 15)
    )
    root_url = "https://web.archive.org/web/20250124114611/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm"
    title_pages = {
        f"https://web.archive.org/web/20250124114611/https://www.gencourt.state.nh.us/rsa/html/NHTOC/title{i}.htm": (
            f"<html><body><a href='chapter{i}.htm'>CHAPTER {i}: Chapter {i}</a></body></html>"
        ).encode("utf-8")
        for i in range(1, 15)
    }

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if url == root_url:
            return f"<html><body>{title_links}</body></html>".encode("utf-8")
        if url in title_pages:
            return title_pages[url]
        return b""

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = NewHampshireScraper("NH", "New Hampshire")
    statutes = await scraper._scrape_archived_title_stubs("New Hampshire Revised Statutes", max_statutes=None)

    assert statutes == []


@pytest.mark.anyio
async def test_new_hampshire_full_corpus_prefers_section_text_over_index_stubs(monkeypatch: pytest.MonkeyPatch):
    root_url = "https://web.archive.org/web/20250124114611/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm"
    title_url = "https://web.archive.org/web/20250124114611/https://www.gencourt.state.nh.us/rsa/html/NHTOC/NHTOC-I.htm"
    chapter_url = "https://web.archive.org/web/20250124114611/https://www.gencourt.state.nh.us/rsa/html/NHTOC/NHTOC-I-1.htm"
    section_url = "https://web.archive.org/web/20100306184310/http://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm"

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if url == root_url:
            return b"<html><body><a href='NHTOC/NHTOC-I.htm'>TITLE I: THE STATE AND ITS GOVERNMENT</a></body></html>"
        if url == title_url:
            return b"<html><body><a href='NHTOC-I-1.htm'>CHAPTER 1: STATE BOUNDARIES</a></body></html>"
        if url == chapter_url:
            return (
                b"<html><body>"
                b"<a href='/web/20100306184310/http://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm'>"
                b"Section 1:1 Perambulation of the New Hampshire Line."
                b"</a></body></html>"
            )
        if url == section_url:
            return (
                b"<html><body>Section 1:1 Perambulation of the New Hampshire Line. "
                + (b"Boundary text " * 40)
                + b"Source. 1901, 1:1.</body></html>"
            )
        return b""

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = NewHampshireScraper("NH", "New Hampshire")
    statutes = await scraper._scrape_archived_title_stubs("New Hampshire Revised Statutes", max_statutes=5)

    assert len(statutes) == 1
    assert statutes[0].section_number == "1:1"
    assert statutes[0].official_cite == "N.H. Rev. Stat. § 1:1"
    assert "Boundary text" in statutes[0].full_text


@pytest.mark.anyio
async def test_north_dakota_official_index_discovers_cencode_pdfs(monkeypatch: pytest.MonkeyPatch):
    index_html = (
        "<html><body>"
        "<a href='/cencode/t01c01.pdf#nameddest=1-01-01'>1-01-01</a>"
        "<a href='/cencode/t01c02.pdf#nameddest=1-02-01'>1-02-01</a>"
        "</body></html>"
    ).encode("utf-8")
    pdf_payload = b"%PDF-1.4 fake pdf bytes"

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if url.endswith("/general-information/north-dakota-century-code/index.html"):
            return index_html
        if url.endswith("/cencode/t01c01.pdf") or url.endswith("/cencode/t01c02.pdf"):
            return pdf_payload
        return b""

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)
    monkeypatch.setattr(
        NorthDakotaScraper,
        "_extract_pdf_text",
        lambda self, pdf_bytes, max_chars: ("North Dakota Century Code chapter text. " * 20)[:max_chars],
    )

    scraper = NorthDakotaScraper("ND", "North Dakota")
    statutes = await scraper._scrape_official_index_pdfs("North Dakota Century Code", max_statutes=2)

    assert [row.section_number for row in statutes] == ["01-01", "01-02"]
    assert statutes[0].structured_data["source_kind"] == "official_modern_index_pdf"
    assert "chapter text" in statutes[0].full_text.lower()


@pytest.mark.anyio
async def test_massachusetts_full_corpus_uses_ajax_title_chapter_section_tree(monkeypatch: pytest.MonkeyPatch):
    pages = {
        "https://malegislature.gov/Laws/GeneralLaws": (
            "<html><body>"
            "<a href='/Laws/GeneralLaws/PartI'>Part I</a>"
            "</body></html>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/PartI": (
            "<html><body>"
            "<a onclick=\"accordionAjaxLoad('1', '1', 'I')\">Title I</a>"
            "</body></html>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/GetChaptersForTitle?partId=1&titleId=1&code=I": (
            "<div id='titleI'>"
            "<ul>"
            "<li><a href='/Laws/GeneralLaws/PartI/TitleI/Chapter1'>Chapter 1</a></li>"
            "</ul>"
            "</div>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleI/Chapter1": (
            "<html><body>"
            "<a href='/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section1'>Section 1</a>"
            "<a href='/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section2'>Section 2</a>"
            "</body></html>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section1": (
            "<html><body>"
            "<h2 class='genLawHeading'>Citizens of commonwealth defined</h2>"
            "<p>Section 1. " + ("Massachusetts section one text. " * 12) + "</p>"
            "</body></html>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section2": (
            "<html><body>"
            "<h2 class='genLawHeading'>Jurisdiction</h2>"
            "<p>Section 2. " + ("Massachusetts section two text. " * 12) + "</p>"
            "</body></html>"
        ),
    }

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        return pages.get(url, "")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Massachusetts full-corpus path should use the official AJAX tree before generic scraping")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    scraper = MassachusettsScraper("MA", "Massachusetts")
    monkeypatch.setattr(MassachusettsScraper, "_request_text_direct", _fake_request_text_direct)
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)

    statutes = await scraper.scrape_code(
        "Massachusetts General Laws",
        "https://malegislature.gov/Laws/GeneralLaws",
        max_statutes=2,
    )

    assert [statute.section_number for statute in statutes] == ["1", "2"]
    assert statutes[0].structured_data["source_kind"] == "official_massachusetts_general_laws_html"
    assert statutes[0].structured_data["discovery_method"] == "official_part_title_chapter_section"


@pytest.mark.anyio
async def test_ohio_full_corpus_uses_official_title_chapter_section_tree(monkeypatch: pytest.MonkeyPatch):
    pages = {
        "https://codes.ohio.gov/ohio-revised-code": (
            "<html><body>"
            "<a href='ohio-revised-code/title-1'>Title 1 | State Government</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://codes.ohio.gov/ohio-revised-code/title-1": (
            "<html><body>"
            "<a href='chapter-101'>Chapter 101 | General Assembly</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://codes.ohio.gov/ohio-revised-code/chapter-101": (
            "<html><body>"
            "<a href='section-101.01'>Section 101.01 | Example one.</a>"
            "<a href='section-101.02'>Section 101.02 | Example two.</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://codes.ohio.gov/ohio-revised-code/section-101.01": (
            "<html><body><main>"
            "<h1>Section 101.01 | Example one.</h1>"
            "<p>Section 101.01 Example one. " + ("Ohio text one. " * 20) + "</p>"
            "</main></body></html>"
        ).encode("utf-8"),
        "https://codes.ohio.gov/ohio-revised-code/section-101.02": (
            "<html><body><main>"
            "<h1>Section 101.02 | Example two.</h1>"
            "<p>Section 101.02 Example two. " + ("Ohio text two. " * 20) + "</p>"
            "</main></body></html>"
        ).encode("utf-8"),
    }

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Ohio full-corpus path should use the official title/chapter/section tree before generic scraping")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = OhioScraper("OH", "Ohio")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)

    statutes = await scraper.scrape_code(
        "Ohio Revised Code",
        "https://codes.ohio.gov/ohio-revised-code",
        max_statutes=2,
    )

    assert [statute.section_number for statute in statutes] == ["101.01", "101.02"]
    assert statutes[0].structured_data["source_kind"] == "official_ohio_revised_code_html"
    assert statutes[0].structured_data["discovery_method"] == "official_title_chapter_section"


@pytest.mark.anyio
async def test_utah_full_corpus_uses_versioned_title_chapter_part_section_tree(monkeypatch: pytest.MonkeyPatch):
    pages = {
        "https://le.utah.gov/xcode/Title1/1.html": (
            "<html><body><script>"
            'var versionDefault="C1_1800010118000101";'
            "</script></body></html>"
        ).encode("utf-8"),
        "https://le.utah.gov/xcode/Title1/C1_1800010118000101.html": (
            "<html><body><div id='content'><table id='childtbl'>"
            "<tr><td><a href='../Title1/Chapter1/1-1.html?v=C1-1_1800010118000101'>Chapter 1</a></td><td>General Provisions</td></tr>"
            "</table></div></body></html>"
        ).encode("utf-8"),
        "https://le.utah.gov/xcode/Title1/Chapter1/C1-1_1800010118000101.html": (
            "<html><body><div id='content'><table id='childtbl'>"
            "<tr><td><a href='../../Title1/Chapter1/1-1-P1.html?v=C1-1-P1_1800010118000101'>Part 1</a></td><td>Intro Part</td></tr>"
            "</table></div></body></html>"
        ).encode("utf-8"),
        "https://le.utah.gov/xcode/Title1/Chapter1/C1-1-P1_1800010118000101.html": (
            "<html><body><div id='content'><table id='childtbl'>"
            "<tr><td><a href='../../Title1/Chapter1/1-1-S101.html?v=C1-1-S101_2025050720250507'>Section 101</a></td><td>Definitions.</td></tr>"
            "<tr><td><a href='../../Title1/Chapter1/1-1-S102.html?v=C1-1-S102_2025050720250507'>Section 102</a></td><td>Applicability.</td></tr>"
            "</table></div></body></html>"
        ).encode("utf-8"),
        "https://le.utah.gov/xcode/Title1/Chapter1/C1-1-S101_2025050720250507.html": (
            "<html><body><div id='content'>"
            "<h3 class='heading'>Title 1 Chapter 1 Section 1-1-101 Definitions.</h3>"
            "<p>1-1-101. " + ("Utah section one text. " * 20) + "</p>"
            "</div></body></html>"
        ).encode("utf-8"),
        "https://le.utah.gov/xcode/Title1/Chapter1/C1-1-S102_2025050720250507.html": (
            "<html><body><div id='content'>"
            "<h3 class='heading'>Title 1 Chapter 1 Section 1-1-102 Applicability.</h3>"
            "<p>1-1-102. " + ("Utah section two text. " * 20) + "</p>"
            "</div></body></html>"
        ).encode("utf-8"),
    }

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return pages.get(url, b"")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = UtahScraper("UT", "Utah")
    statutes = await scraper.scrape_code("Utah Code", "https://le.utah.gov/xcode/code.html", max_statutes=2)

    assert [statute.section_number for statute in statutes] == ["1-1-101", "1-1-102"]
    assert statutes[0].structured_data["source_kind"] == "official_utah_code_versioned_html"
    assert statutes[0].structured_data["discovery_method"] == "official_title_chapter_part_section"


@pytest.mark.anyio
async def test_utah_full_corpus_prefers_root_xml_code_tree(monkeypatch: pytest.MonkeyPatch):
    pages = {
        "https://le.utah.gov/xcode/code.html": (
            "<html><body><script>"
            'var versionDefault="C_1800010118000101";'
            "</script></body></html>"
        ).encode("utf-8"),
        "https://le.utah.gov/xcode/C_1800010118000101.xml": (
            "<code>"
            "<title number='3'>"
            "<catchline>Uniform Agricultural Cooperative Association Act</catchline>"
            "<chapter number='3-1'>"
            "<catchline>General Provisions</catchline>"
            "<section number='3-1-1'>"
            "<catchline>Declaration of policy.</catchline>"
            + ("Utah XML section one text. " * 20)
            + "</section>"
            "<section number='3-1-2'>"
            "<catchline>Definitions.</catchline>"
            + ("Utah XML section two text. " * 20)
            + "</section>"
            "</chapter>"
            "</title>"
            "</code>"
        ).encode("utf-8"),
    }

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return pages.get(url, b"")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = UtahScraper("UT", "Utah")
    statutes = await scraper.scrape_code("Utah Code", "https://le.utah.gov/xcode/code.html", max_statutes=2)

    assert [statute.section_number for statute in statutes] == ["3-1-1", "3-1-2"]
    assert statutes[0].structured_data["source_kind"] == "official_utah_code_xml"
    assert statutes[0].structured_data["discovery_method"] == "official_root_xml_title_chapter_section"


@pytest.mark.anyio
async def test_florida_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_fetch_official_fl_html(self, url: str, timeout_seconds: int = 12) -> str:
        self._record_fetch_event(provider="requests_direct", success=True)
        if "Display_Index" in url or url.endswith("/statutes"):
            return (
                "<html><body>"
                "<a href='index.cfm?App_mode=Display_Index&Title_Request=I#TitleI'>TITLE I</a>"
                "<a href='index.cfm?App_mode=Display_Statute&URL=0000-0099/0001/0001ContentsIndex.html'>Chapter 1</a>"
                "</body></html>"
            )
        return (
            "<html><body>"
            "<span class='TitleNumber'>TITLE I</span>"
            "<span class='TitleName'>CONSTRUCTION OF STATUTES</span>"
            "<span class='ChapterNumber'>Chapter 1</span>"
            "<span class='ChapterName'>GENERAL PROVISIONS</span>"
            "<div class='Section'>"
            "<span class='SectionNumber'>1.01</span>"
            "<span class='Catchline'>Definitions.</span>"
            "<div class='SectionBody'>The word person includes individuals and business entities. "
            "This test statute has enough words to avoid the short-text filter and exercise parsing.</div>"
            "</div>"
            "</body></html>"
        )

    monkeypatch.setattr(FloridaScraper, "_fetch_official_fl_html", _fake_fetch_official_fl_html)

    scraper = FloridaScraper("FL", "Florida")
    statutes = await scraper.scrape_code("Florida Statutes", "http://example.fl/statutes")

    assert len(statutes) >= 1
    assert statutes[0].official_cite == "Fla. Stat. § 1.01"
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_illinois_scrape_records_official_full_act_sections(monkeypatch: pytest.MonkeyPatch):
    async def _fake_fetch_official_il_html(self, url: str, timeout_seconds: int = 20) -> str:
        self._record_fetch_event(provider="requests_direct", success=True)
        if "Chapters" in url:
            return (
                "<html><body>"
                "<a class='list-group-item' href='/Legislation/ILCS/Acts?ChapterID=2&ChapterNumber=5&Chapter=GENERAL PROVISIONS&MajorTopic=GOVERNMENT'>"
                "CHAPTER 5 GENERAL PROVISIONS</a>"
                "</body></html>"
            )
        if "Acts?" in url:
            return (
                "<html><body>"
                "<a class='list-group-item' href='/Legislation/ILCS/Articles?ActID=74&ChapterID=2&Chapter=GENERAL PROVISIONS&MajorTopic=GOVERNMENT'>"
                "5 ILCS 5/ U. S. Constitution Amendment Act.</a>"
                "</body></html>"
            )
        if "Articles?" in url:
            return (
                "<html><body>"
                "<a href='/legislation/ILCS/details?ActID=74&ChapterID=2&SeqStart=&&ChapAct=FullText'>View Entire Act</a>"
                "</body></html>"
            )
        return (
            "<html><body>"
            "<code>(5 ILCS 5/0.01)</code><br><code>Sec. 0.01. Short title. "
            "This Act may be cited as the U. S. Constitution Amendment Act.</code>"
            "<br><code>(Source: P.A. 86-1324.)</code>"
            "<code>(5 ILCS 5/1)</code><br><code>Sec. 1. Whenever Congress proposes an amendment, "
            "the General Assembly may consider the amendment under this section.</code>"
            "<br><code>(Source: Laws 1961, p. 1983.)</code>"
            "</body></html>"
        )

    monkeypatch.setattr(IllinoisScraper, "_fetch_official_il_html", _fake_fetch_official_il_html)

    scraper = IllinoisScraper("IL", "Illinois")
    statutes = await scraper.scrape_code("Illinois Compiled Statutes", "https://example.il/Legislation/ILCS/Chapters")

    assert len(statutes) == 2
    assert statutes[0].official_cite == "5 ILCS 5/0.01"
    assert statutes[0].structured_data["source_kind"] == "official_illinois_ilga_full_act_html"
    assert statutes[0].structured_data["skip_hydrate"] is True
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_kansas_parse_section_page_uses_statute_paragraphs(monkeypatch: pytest.MonkeyPatch):
    async def _fake_fetch_official_ks_html(self, url: str, timeout_seconds: int = 18) -> str:
        self._record_fetch_event(provider="requests_direct", success=True)
        return (
            "<html><body>"
            "<div id='main'></div>"
            "<p class='p_pt'><span class='stat_5f_number'>1-201.</span> "
            "<span class='stat_5f_caption'>Membership; appointment; qualifications.</span> "
            "(a) There is hereby created a board of accountancy for this state.</p>"
            "<p class='p_pt'>(b) Each member shall serve for a term of three years "
            "and until a successor is appointed and qualified.</p>"
            "<p class='p_pt'><span class='t_bold'>History:</span> L. 1951, ch. 1, sec. 1.</p>"
            "</body></html>"
        )

    monkeypatch.setattr(KansasScraper, "_fetch_official_ks_html", _fake_fetch_official_ks_html)

    scraper = KansasScraper("KS", "Kansas")
    statute = await scraper._parse_section_page(
        code_name="Kansas Statutes",
        section_url="https://example.ks/001_002_0001_k/",
        section_label="1-201 - Membership; appointment; qualifications.",
        chapter_label="Chapter 1. - ACCOUNTANTS, CERTIFIED PUBLIC",
        article_label="Article 2. - STATE BOARD OF ACCOUNTANCY",
    )

    assert statute is not None
    assert statute.official_cite == "K.S.A. 1-201"
    assert statute.structured_data["source_kind"] == "official_kansas_statutes_html"
    assert statute.structured_data["skip_hydrate"] is True
    assert "created a board of accountancy" in statute.full_text


@pytest.mark.anyio
async def test_maine_direct_seed_sections_parse_official_body(monkeypatch: pytest.MonkeyPatch):
    html = (
        "<html><body>"
        "<div class='heading_structure'>Title 1: GENERAL PROVISIONS Chapter 1</div>"
        "<div class='row section-content'><div class='MRSSection status_current'>"
        "<h3 class='heading_section'>§1. Extent of sovereignty and jurisdiction</h3>"
        "<div class='mrs-text indpara MRSIndentedPara status_current IP'>"
        "The jurisdiction and sovereignty of the State extend to all places within its boundaries, "
        "subject only to such rights of concurrent jurisdiction as are granted by law. "
        "This sentence provides enough official body text to pass the statute quality filter.</div>"
        "<div class='qhistory'>SECTION HISTORY PL 1985, c. 802, §1 (AMD).</div>"
        "</div></div>"
        "</body></html>"
    ).encode("utf-8")

    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return html

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = MaineScraper("ME", "Maine")
    statutes = await scraper.scrape_code("Maine Revised Statutes", "https://example.me/statutes", max_statutes=1)

    assert len(statutes) == 1
    assert statutes[0].official_cite == "Me. Rev. Stat. tit. 1, § 1"
    assert statutes[0].structured_data["source_kind"] == "official_maine_revised_statutes_html"
    assert "jurisdiction and sovereignty" in statutes[0].full_text


@pytest.mark.anyio
async def test_maine_official_hierarchy_uses_title_chapter_section_tree(monkeypatch: pytest.MonkeyPatch):
    pages = {
        "https://legislature.maine.gov/statutes/": (
            "<html><body>"
            "<a href='1/title1ch0sec0.html'>TITLE 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://legislature.maine.gov/statutes/1/title1ch0sec0.html": (
            "<html><body>"
            "<a href='./title1ch1sec0.html'>Chapter 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://legislature.maine.gov/statutes/1/title1ch1sec0.html": (
            "<html><body>"
            "<a href='./title1sec1.html'>1 §1. Extent of sovereignty and jurisdiction</a>"
            "<a href='./title1sec2.html'>1 §2. Offshore waters and submerged land</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://legislature.maine.gov/statutes/1/title1sec1.html": (
            "<html><body>"
            "<div class='heading_section'>§1. Extent of sovereignty and jurisdiction</div>"
            "<div class='row section-content'>" + ("Maine section one text. " * 20) + "</div>"
            "</body></html>"
        ).encode("utf-8"),
        "https://legislature.maine.gov/statutes/1/title1sec2.html": (
            "<html><body>"
            "<div class='heading_section'>§2. Offshore waters and submerged land</div>"
            "<div class='row section-content'>" + ("Maine section two text. " * 20) + "</div>"
            "</body></html>"
        ).encode("utf-8"),
    }

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return pages.get(url, b"")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = MaineScraper("ME", "Maine")
    statutes = await scraper._scrape_official_title_chapter_section_tree("Maine Revised Statutes", max_statutes=2)

    assert [row.section_number for row in statutes] == ["1", "2"]
    assert statutes[0].structured_data["source_kind"] == "official_maine_revised_statutes_html"
    assert statutes[0].structured_data["discovery_method"] == "official_title_chapter_section"


@pytest.mark.anyio
async def test_michigan_full_corpus_uses_chapter_index_act_section_tree(monkeypatch: pytest.MonkeyPatch):
    pages = {
        "https://www.legislature.mi.gov/Laws/ChapterIndex": (
            "<html><body>"
            "<a href='/Home/GetObject?objectName=mcl-chap750'>Chapter 750</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-chap750": (
            "<html><body>"
            "<a href='/Laws/MCL?objectName=mcl-Act-328-of-1931'>Act 328 of 1931</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-Act-328-of-1931": (
            "<html><body>"
            "<a href='/Laws/MCL?objectName=mcl-750-1'>Section 750.1</a>"
            "<a href='/Laws/MCL?objectName=mcl-750-2'>Section 750.2</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-750-1": (
            "<html><body><main>"
            "<h1>750.1 Short title.</h1>"
            "<p>" + ("Michigan section one text. " * 20) + "</p>"
            "</main></body></html>"
        ).encode("utf-8"),
        "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-750-2": (
            "<html><body><main>"
            "<h1>750.2 Definitions.</h1>"
            "<p>" + ("Michigan section two text. " * 20) + "</p>"
            "</main></body></html>"
        ).encode("utf-8"),
    }

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return pages.get(url, b"")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = MichiganScraper("MI", "Michigan")
    statutes = await scraper.scrape_code(
        "Michigan Compiled Laws",
        "https://www.legislature.mi.gov/Laws/ChapterIndex",
        max_statutes=2,
    )

    assert [row.section_number for row in statutes] == ["750.1", "750.2"]
    assert statutes[0].structured_data["source_kind"] == "official_michigan_compiled_laws_html"
    assert statutes[0].structured_data["discovery_method"] == "official_chapter_index_act_section"


@pytest.mark.anyio
async def test_montana_jina_seed_sections_parse_mca_body(monkeypatch: pytest.MonkeyPatch):
    markdown = (
        "Title: 45-5-102. Deliberate homicide, MCA\n\n"
        "URL Source: https://leg.mt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html\n\n"
        "Markdown Content:\n"
        "## Montana Code Annotated 2025\n\n"
        "45-5-102. Deliberate homicide. (1) A person commits the offense of deliberate homicide if:\n\n"
        "(a) the person purposely or knowingly causes the death of another human being;\n\n"
        "(b) the person attempts to commit robbery and in the course of the offense causes death; or\n\n"
        "(2) A person convicted of the offense shall be punished as provided by law. "
        "This sentence provides enough statutory text to pass validation.\n"
    ).encode("utf-8")

    async def _fake_fetch_with_archival(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return markdown

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch_with_archival)

    scraper = MontanaScraper("MT", "Montana")
    statutes = await scraper.scrape_code("Montana Code Annotated", "https://example.mt/mca", max_statutes=1)

    assert len(statutes) == 1
    assert statutes[0].official_cite == "Mont. Code Ann. § 45-5-102"
    assert statutes[0].structured_data["source_kind"] == "jina_reader_montana_mca_official"
    assert "Deliberate homicide" in statutes[0].full_text


@pytest.mark.anyio
async def test_montana_official_hierarchy_uses_title_chapter_part_section_tree(monkeypatch: pytest.MonkeyPatch):
    payloads = {
        "https://r.jina.ai/http://https://leg.mt.gov/bills/mca/": (
            "[TITLE 45. CRIMES](https://mca.legmt.gov/bills/mca/title_0450/chapters_index.html)"
        ).encode("utf-8"),
        "https://r.jina.ai/http://https://mca.legmt.gov/bills/mca/title_0450/chapters_index.html": (
            "[CHAPTER 5. OFFENSES AGAINST THE PERSON](https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/parts_index.html)"
        ).encode("utf-8"),
        "https://r.jina.ai/http://https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/parts_index.html": (
            "[Part 1. Homicide](https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/part_0010/sections_index.html)"
        ).encode("utf-8"),
        "https://r.jina.ai/http://https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/part_0010/sections_index.html": (
            "[45-5-101 Repealed](https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0010/0450-0050-0010-0010.html)"
            "[45-5-102 Deliberate homicide](https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html)"
        ).encode("utf-8"),
        "https://r.jina.ai/http://https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0010/0450-0050-0010-0010.html": (
            "Title: 45-5-101. Repealed, MCA\n\nMarkdown Content:\n45-5-101. Repealed. " + ("Repealed text. " * 20)
        ).encode("utf-8"),
        "https://r.jina.ai/http://https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html": (
            "Title: 45-5-102. Deliberate homicide, MCA\n\nMarkdown Content:\n45-5-102. Deliberate homicide. "
            + ("Montana homicide text. " * 20)
        ).encode("utf-8"),
    }

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return payloads.get(url, b"")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = MontanaScraper("MT", "Montana")
    statutes = await scraper._scrape_official_mca_tree("Montana Code Annotated", max_statutes=2)

    assert [row.section_number for row in statutes] == ["45-5-101", "45-5-102"]
    assert statutes[0].structured_data["source_kind"] == "jina_reader_montana_mca_hierarchical"
    assert statutes[0].structured_data["discovery_method"] == "official_mca_title_chapter_part_section"


@pytest.mark.anyio
async def test_document_extraction_skips_html_served_from_pdf_url(monkeypatch: pytest.MonkeyPatch):
    async def _fail_pdf_processor(_raw: bytes) -> str:
        raise AssertionError("HTML payload should not reach PDF/OCR extraction")

    from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import UnifiedWebScraper

    monkeypatch.setattr(UnifiedWebScraper, "_extract_pdf_text", staticmethod(_fail_pdf_processor))

    scraper = OklahomaScraper("OK", "Oklahoma")
    result = await scraper._extract_text_from_document_bytes(
        source_url="https://web.archive.org/web/20220101000000/https://example.test/code/1.pdf",
        raw_bytes=b"<!DOCTYPE html><html><body>Wayback replay page, not a PDF</body></html>",
    )

    assert result is None


@pytest.mark.anyio
async def test_colorado_pdf_summary_fetch_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        return _FakeResponse(b"%PDF-1.4 fake colorado pdf")

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

    scraper = ColoradoScraper("CO", "Colorado")
    _ = await scraper._extract_pdf_text_summary("https://example.co/doc.pdf")

    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_colorado_publication_detail_pages_yield_statutes(monkeypatch: pytest.MonkeyPatch):
    search_html = (
        "<html><body>"
        "<div class='views-row'>"
        "<a href='/publications/section-14-10-114-crs-pre-2014'>Section 14-10-114, C.R.S., pre-2014</a>"
        "<a href='/sites/default/files/14-10-114pre20140101.pdf'>Download File</a>"
        "</div>"
        "<div class='views-row'>"
        "<a href='/publications/source-note-2-3-1203-crs-pre-2016'>Source Note for 2-3-1203, C.R.S. (pre 2016)</a>"
        "</div>"
        "</body></html>"
    ).encode("utf-8")
    detail_html = (
        "<html><body><article>"
        "Staff Publications Section 14-10-114, C.R.S., pre-2014 Published: November 3, 2016 "
        + ("This version of section 14-10-114, C.R.S., was effective until January 1, 2014. " * 10)
        + "View Document"
        "</article></body></html>"
    ).encode("utf-8")
    source_note_html = (
        "<html><body><article>"
        "Source Note for 2-3-1203, C.R.S. (pre 2016) "
        + ("Historical source note text. " * 20)
        + "</article></body></html>"
    ).encode("utf-8")

    async def _fake_request(self, url: str, timeout_seconds: int = 45) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if "publication-search" in url:
            return search_html
        if url.endswith("/publications/section-14-10-114-crs-pre-2014"):
            return detail_html
        if url.endswith("/publications/source-note-2-3-1203-crs-pre-2016"):
            return source_note_html
        return b""

    monkeypatch.setattr(ColoradoScraper, "_request_bytes_direct", _fake_request)

    scraper = ColoradoScraper("CO", "Colorado")
    statutes = await scraper.scrape_code("Colorado Revised Statutes", "https://content.leg.colorado.gov/publication-search?search_api_fulltext=crs", max_statutes=2)

    assert [row.section_number for row in statutes] == ["14-10-114", "2-3-1203"]
    assert statutes[0].structured_data["source_kind"] == "official_colorado_publication_html"
    assert "effective until January 1, 2014" in statutes[0].full_text
    assert "Historical source note text." in statutes[1].full_text


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

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

    scraper = ConnecticutScraper("CT", "Connecticut")
    statutes = await scraper._custom_scrape_connecticut("Connecticut General Statutes", "https://example.ct/titles", "Conn. Gen. Stat.")

    assert len(statutes) >= 1
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_pennsylvania_bounded_run_prefers_consolidated_title_pdfs(monkeypatch: pytest.MonkeyPatch):
    index_html = (
        "<html><body>"
        "<a href='/statutes/consolidated/view-statute?txtType=HTM&ttl=01'>GENERAL PROVISIONS</a>"
        "<a href='/statutes/consolidated/view-statute?txtType=PDF&ttl=01'>PDF</a>"
        "</body></html>"
    ).encode("utf-8")

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if url == "https://www.palegis.us/statutes/consolidated":
            return index_html
        return b""

    async def _fake_request_pdf_bytes(self, url: str, timeout: int = 45) -> bytes:
        return b"%PDF-1.4 fake"

    def _fake_extract_pdf_text(self, pdf_bytes: bytes, max_chars: int) -> str:
        return (
            "TABLE OF CONTENTS\n"
            "§ 101. Short title.\n"
            "§ 102. Citation of Pennsylvania Consolidated Statutes.\n"
            "\f"
            "Chapter 1. Short Title\n"
            "§ 101. Short title.\n"
            + ("This title shall be known and may be cited as the Pennsylvania Consolidated Statutes. " * 4)
            + "\n§ 102. Citation of Pennsylvania Consolidated Statutes.\n"
            + ("The Pennsylvania Consolidated Statutes may be cited by title and section. " * 4)
        )[:max_chars]

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)
    monkeypatch.setattr(PennsylvaniaScraper, "_request_pdf_bytes", _fake_request_pdf_bytes)
    monkeypatch.setattr(PennsylvaniaScraper, "_extract_pdf_text_preserve_layout", _fake_extract_pdf_text)

    scraper = PennsylvaniaScraper("PA", "Pennsylvania")
    statutes = await scraper.scrape_code(
        "Pennsylvania Consolidated Statutes",
        "https://www.palegis.us/statutes/consolidated",
        max_statutes=2,
    )

    assert [statute.section_number for statute in statutes] == ["101", "102"]
    assert statutes[0].official_cite == "Pa. Cons. Stat. tit. 01 § 101"
    assert statutes[0].structured_data["source_kind"] == "official_pennsylvania_title_pdf"
    assert statutes[0].structured_data["discovery_method"] == "official_consolidated_title_pdf_index"


@pytest.mark.anyio
async def test_connecticut_full_corpus_bounded_run_does_not_short_circuit_to_direct_chapters(monkeypatch: pytest.MonkeyPatch):
    async def _fake_live_titles(self, code_name: str, max_statutes: int = 120):
        return []

    async def _fake_archived_titles(self, code_name: str, max_statutes: int = 120):
        return []

    async def _fake_custom(self, code_name: str, code_url: str, citation_format: str, max_sections: int = 100):
        return [
            NormalizedStatute(
                state_code="CT",
                state_name="Connecticut",
                statute_id="CT-1-1",
                code_name=code_name,
                section_number="1-1",
                section_name="Definitions",
                full_text="Connecticut section one text " * 20,
                source_url="https://www.cga.ct.gov/current/pub/chap_001.htm#sec_1-1",
                official_cite="Conn. Gen. Stat. § 1-1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_connecticut_section_html",
                    "discovery_method": "official_custom_section_parse",
                    "skip_hydrate": True,
                },
            ),
            NormalizedStatute(
                state_code="CT",
                state_name="Connecticut",
                statute_id="CT-1-2",
                code_name=code_name,
                section_number="1-2",
                section_name="Rules of construction",
                full_text="Connecticut section two text " * 20,
                source_url="https://www.cga.ct.gov/current/pub/chap_001.htm#sec_1-2",
                official_cite="Conn. Gen. Stat. § 1-2",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_connecticut_section_html",
                    "discovery_method": "official_custom_section_parse",
                    "skip_hydrate": True,
                },
            ),
        ]

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Connecticut bounded full-corpus run should stay on the richer custom path before generic scraping")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(ConnecticutScraper, "_scrape_live_title_stubs", _fake_live_titles)
    monkeypatch.setattr(ConnecticutScraper, "_scrape_archived_chapter_stubs", _fake_archived_titles)
    monkeypatch.setattr(ConnecticutScraper, "_custom_scrape_connecticut", _fake_custom)

    scraper = ConnecticutScraper("CT", "Connecticut")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    statutes = await scraper.scrape_code("Connecticut General Statutes", "https://www.cga.ct.gov/current/pub/titles.htm", max_statutes=2)

    assert [row.section_number for row in statutes] == ["1-1", "1-2"]
    assert statutes[0].structured_data["source_kind"] == "official_connecticut_section_html"


@pytest.mark.anyio
async def test_connecticut_custom_scrape_extracts_real_chapter_sections(monkeypatch: pytest.MonkeyPatch):
    title_html = (
        "<html><body>"
        "<a href='chap_001.htm'>Chapter 1</a>"
        "<a href='chap_002.htm'>Chapter 2</a>"
        "</body></html>"
    ).encode("utf-8")
    chapter_html = (
        "<html><head><title>Chapter 1 - Construction of Statutes</title></head><body>"
        "<h4 id='TOC'>Table of Contents</h4>"
        "<p class='toc_catchln'><a href='#sec_1-1'>Sec. 1-1. Words and phrases. Construction of statutes.</a></p>"
        "<p class='toc_catchln'><a href='#sec_1-2'>Sec. 1-2. Legal notices.</a></p>"
        "<hr class='chaps_pg_bar'/>"
        "<p><span class='catchln' id='sec_1-1'>Sec. 1-1. Words and phrases. Construction of statutes.</span> "
        + ("Statutory text one. " * 20)
        + "</p>"
        "<p class='source-first'>(1949 Rev.)</p>"
        "<table class='nav_tbl'><tr><td>nav</td></tr></table>"
        "<p><span class='catchln' id='sec_1-2'>Sec. 1-2. Legal notices.</span> "
        + ("Statutory text two. " * 20)
        + "</p>"
        "<p class='history-first'>History text.</p>"
        "<table class='nav_tbl'><tr><td>nav</td></tr></table>"
        "</body></html>"
    ).encode("utf-8")

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if url.endswith("titles.htm"):
            return title_html
        if url.endswith("chap_001.htm"):
            return chapter_html
        if url.endswith("chap_002.htm"):
            return b"<html><body></body></html>"
        return b""

    monkeypatch.setattr(ConnecticutScraper, "_fetch_connecticut_page", _fake_fetch)
    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = ConnecticutScraper("CT", "Connecticut")
    statutes = await scraper._custom_scrape_connecticut(
        "Connecticut General Statutes",
        "https://www.cga.ct.gov/current/pub/titles.htm",
        "Conn. Gen. Stat.",
        max_sections=2,
    )

    assert [statute.section_number for statute in statutes] == ["1-1", "1-2"]
    assert statutes[0].structured_data["source_kind"] == "official_connecticut_chapter_html"
    assert statutes[0].structured_data["discovery_method"] == "official_title_chapter_section_html"
    assert "Statutory text one." in statutes[0].full_text
    assert statutes[1].section_name == "Legal notices"


@pytest.mark.anyio
async def test_maryland_full_corpus_bounded_run_prefers_api_sections(monkeypatch: pytest.MonkeyPatch):
    async def _fake_api_sections(self, code_name: str, max_statutes: int):
        return [
            NormalizedStatute(
                state_code="MD",
                state_name="Maryland",
                statute_id="MD-1-101",
                code_name=code_name,
                section_number="1-101",
                section_name="State Government § 1-101",
                full_text="Maryland section one text " * 20,
                source_url="https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=GSG&section=1-101&enactments=false",
                official_cite="Md. Code § 1-101",
                metadata=StatuteMetadata(),
                structured_data={
                    "record_type": "maryland_api_section",
                    "source_kind": "official_maryland_api_section_html",
                    "discovery_method": "official_articles_sections_api",
                    "skip_hydrate": True,
                },
            ),
            NormalizedStatute(
                state_code="MD",
                state_name="Maryland",
                statute_id="MD-1-102",
                code_name=code_name,
                section_number="1-102",
                section_name="State Government § 1-102",
                full_text="Maryland section two text " * 20,
                source_url="https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=GSG&section=1-102&enactments=false",
                official_cite="Md. Code § 1-102",
                metadata=StatuteMetadata(),
                structured_data={
                    "record_type": "maryland_api_section",
                    "source_kind": "official_maryland_api_section_html",
                    "discovery_method": "official_articles_sections_api",
                    "skip_hydrate": True,
                },
            ),
        ]

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Maryland bounded full-corpus run should prefer API-backed sections before generic scraping")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(MarylandScraper, "_scrape_api_sections", _fake_api_sections)

    scraper = MarylandScraper("MD", "Maryland")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    monkeypatch.setattr(scraper, "_playwright_scrape", _fail_generic)
    statutes = await scraper.scrape_code("Maryland Code", "https://mgaleg.maryland.gov/mgawebsite/Laws/Statutes", max_statutes=2)

    assert [row.section_number for row in statutes] == ["1-101", "1-102"]
    assert statutes[0].structured_data["source_kind"] == "official_maryland_api_section_html"


@pytest.mark.anyio
async def test_maryland_section_identity_includes_article_context(monkeypatch: pytest.MonkeyPatch):
    html_payload = (
        "<html><body><div id='StatuteText'>"
        "§ 1-101. Maryland section text. "
        + ("Substantive text. " * 20)
        + "</div></body></html>"
    )

    async def _fake_fetch_text(self, url: str, timeout: int = 45) -> str:
        return html_payload

    monkeypatch.setattr(MarylandScraper, "_fetch_text_direct", _fake_fetch_text)

    scraper = MarylandScraper("MD", "Maryland")
    statute = await scraper._build_statute_from_section_page(
        code_name="Maryland Code",
        article_label="State Government (GSG)",
        section_label="1-101",
        section_number="1-101",
        section_url="https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=GSG&section=1-101&enactments=false",
    )

    assert statute is not None
    assert statute.statute_id == "Maryland Code [GSG] § 1-101"
    assert statute.official_cite == "Md. Code, State Government § 1-101"
    assert statute.structured_data["article_name"] == "State Government"
    assert statute.structured_data["article_code"] == "GSG"


@pytest.mark.anyio
async def test_minnesota_root_index_does_not_become_a_synthetic_section(monkeypatch: pytest.MonkeyPatch):
    async def _fail_build(*args, **kwargs):
        raise AssertionError("Minnesota scraper should not try to build a direct section from the root statutes index")

    async def _fake_chapter_sections(self, code_name: str, max_statutes: int):
        return [
            NormalizedStatute(
                state_code="MN",
                state_name="Minnesota",
                statute_id="Minnesota Statutes § 1.01",
                code_name=code_name,
                section_number="1.01",
                section_name="1.01 Extent",
                full_text="Minnesota section text " * 20,
                source_url="https://www.revisor.mn.gov/statutes/cite/1.01",
                official_cite="Minn. Stat. § 1.01",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_minnesota_statutes_html",
                    "discovery_method": "official_seed_or_section_page",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setattr(MinnesotaScraper, "_build_statute_from_section_page", _fail_build)
    monkeypatch.setattr(MinnesotaScraper, "_scrape_chapter_sections", _fake_chapter_sections)

    scraper = MinnesotaScraper("MN", "Minnesota")
    statutes = await scraper.scrape_code(
        "Minnesota Statutes",
        "https://www.revisor.mn.gov/statutes/",
        max_statutes=1,
    )

    assert [row.section_number for row in statutes] == ["1.01"]


@pytest.mark.anyio
async def test_rhode_island_custom_scrape_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fetch", success=True)
        normalized = str(url).lower()
        if normalized.endswith("/title1/index.htm"):
            return (
                "<html><body>"
                "<a href='/Statutes/TITLE1/1-1/INDEX.htm'>Chapter 1-1 Airports</a>"
                "</body></html>"
            ).encode("utf-8")
        if normalized.endswith("/title1/1-1/index.htm"):
            return (
                "<html><body>"
                "<a href='/Statutes/TITLE1/1-1/1-1-1.htm'>§ 1-1-1. General law.</a>"
                "</body></html>"
            ).encode("utf-8")
        return b""

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = RhodeIslandScraper("RI", "Rhode Island")
    statutes = await scraper._custom_scrape_rhode_island("Rhode Island General Laws", "http://example.ri/statutes", "R.I. Gen. Laws")

    assert len(statutes) >= 1
    assert statutes[0].section_number == "1-1-1"
    assert statutes[0].chapter_number == "1-1"
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_south_dakota_request_json_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        payload = b'{"Statute":"1-1-1","CatchLine":"General law","Html":"<p>Long legal text</p>"}'
        return _FakeResponse(payload)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

    scraper = SouthDakotaScraper("SD", "South Dakota")
    data = await scraper._request_json("https://example.sd/api", headers={}, timeout=20)

    assert data.get("Statute") == "1-1-1"
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_south_dakota_full_corpus_uses_api_next_links(monkeypatch: pytest.MonkeyPatch):
    payloads = {
        "1-1-1": {
            "Statute": "1-1-1",
            "CatchLine": "First section",
            "Next": "1-1-2",
            "Html": "<p>1-1-1. First section. " + ("Long legal text. " * 30) + "</p>",
        },
        "1-1-2": {
            "Statute": "1-1-2",
            "CatchLine": "Second section",
            "Next": "",
            "Html": "<p>1-1-2. Second section. " + ("More legal text. " * 30) + "</p>",
        },
    }
    requested: list[str] = []

    async def _fake_request_json(url: str, headers: dict, timeout: int) -> dict:
        section = url.rstrip("/").rsplit("/", 1)[-1]
        requested.append(section)
        return payloads.get(section, {})

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("full-corpus South Dakota should use the official JSON API")

    scraper = SouthDakotaScraper("SD", "South Dakota")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_request_json", _fake_request_json)
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)

    statutes = await scraper.scrape_code("South Dakota Codified Laws", "https://sdlegislature.gov/", max_statutes=2)

    assert [statute.section_number for statute in statutes] == ["1-1-1", "1-1-2"]
    assert requested[:2] == ["1-1-1", "1-1-2"]
    assert "1-1-2" in requested


@pytest.mark.anyio
async def test_south_carolina_full_corpus_uses_official_title_and_chapter_pages(monkeypatch: pytest.MonkeyPatch):
    pages = {
        "https://www.scstatehouse.gov/code/statmast.php": (
            "<html><body>"
            "<a href='/code/title16.php'>Title 16 - Crimes and Offenses</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.scstatehouse.gov/code/title16.php": (
            "<html><body>"
            "<table><tr><td><a href='/code/t16c003.php'>HTML</a></td></tr></table>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.scstatehouse.gov/code/t16c003.php": (
            "<html><body>"
            "<span style='font-weight: bold;'> SECTION 16-3-10.</span> Murder defined.<br /><br />"
            "Murder is the killing of any person with malice aforethought. "
            "This section has substantial statutory body text for parsing.<br /><br />"
            "HISTORY: 1962 Code SECTION 16-51.<br /><br />"
            "<span style='font-weight: bold;'> SECTION 16-3-20.</span> Punishment for murder.<br /><br />"
            "Punishment for murder includes detailed text and conditions. "
            "This section also contains enough body text to be retained.<br /><br />"
            "HISTORY: 1962 Code SECTION 16-52.<br /><br />"
            "</body></html>"
        ).encode("utf-8"),
    }

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        return pages.get(url, b"")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = SouthCarolinaScraper("SC", "South Carolina")
    statutes = await scraper.scrape_code(
        "South Carolina Code of Laws",
        "https://www.scstatehouse.gov/code/statmast.php",
        max_statutes=None,
    )

    assert [statute.section_number for statute in statutes] == ["16-3-10", "16-3-20"]
    assert statutes[0].structured_data["source_kind"] == "official_south_carolina_code_html"
    assert "Murder defined" in statutes[0].section_name


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

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

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

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

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

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

    scraper = NewMexicoScraper("NM", "New Mexico")
    payload = await scraper._request_bytes("https://example.nm/statute.pdf", headers={}, timeout=20)

    assert payload.startswith(b"%PDF")
    analytics = scraper.get_fetch_analytics_snapshot()
    assert int(analytics.get("attempted") or 0) > 0


@pytest.mark.anyio
async def test_new_mexico_nav_date_chapter_pdf_splits_into_sections(monkeypatch: pytest.MonkeyPatch):
    nav_page = (
        "<html><body>"
        "<a href='/nmos/nmsa/en/item/4351/index.do'>Chapter 1 - Elections</a>"
        "<a href='/nmos/nmsa/en/4351/1/document.do'></a>"
        "</body></html>"
    ).encode("utf-8")
    chapter_text = (
        "CHAPTER 1\nElections\n"
        "1-1-1. Election Code.\n"
        + ("Election code text. " * 20)
        + "\n\n1-1-2. Headings.\n"
        + ("Heading text. " * 20)
        + "\n\n1-1-3. Shall and may.\n"
        + ("Shall and may text. " * 20)
    )

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        self._record_fetch_event(provider="test_fake", success=True)
        if "nav_date.do" in url:
            return nav_page
        return b""

    async def _fake_request_bytes(self, pdf_url: str, headers, timeout: int) -> bytes:
        return b"%PDF-1.4 fake chapter bytes"

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)
    monkeypatch.setattr(NewMexicoScraper, "_request_bytes", _fake_request_bytes)
    monkeypatch.setattr(
        NewMexicoScraper,
        "_extract_pdf_text_preserve_layout",
        lambda self, pdf_bytes, max_chars: chapter_text[:max_chars],
    )

    scraper = NewMexicoScraper("NM", "New Mexico")
    statutes = await scraper.scrape_code(
        "New Mexico Statutes",
        "https://www.nmlegis.gov",
        max_statutes=3,
    )

    assert [row.section_number for row in statutes] == ["1-1-1", "1-1-2", "1-1-3"]
    assert statutes[0].structured_data["source_kind"] == "official_nmonesource_chapter_pdf"
    assert statutes[0].structured_data["discovery_method"] == "official_nav_date_chapter_pdf_sections"
    assert "Election code text." in statutes[0].full_text


@pytest.mark.anyio
async def test_nevada_bounded_run_prefers_official_inline_sections(monkeypatch: pytest.MonkeyPatch):
    index_html = (
        "<html><body>"
        "<a href='NRS-001.html'>Chapter 1</a>"
        "</body></html>"
    )
    chapter_html = (
        "<html><body>"
        "<p class='COLeadline'><a href='#NRS001Sec010'>NRS 1.010</a> Courts of justice.</p>"
        "<p class='COLeadline'><a href='#NRS001Sec020'>NRS 1.020</a> Courts of record.</p>"
        "<p class='DocHeading'>GENERAL PROVISIONS</p>"
        "<p class='SectBody'><span class='Empty'><a name='NRS001Sec010'></a>NRS </span><span class='Section'>1.010</span><span class='Leadline'>Courts of justice.</span> The following shall be the courts of justice for this State:</p>"
        "<p class='SectBody'>1. The Supreme Court.</p>"
        "<p class='SectBody'>2. The Court of Appeals.</p>"
        "<p class='SectBody'><span class='Empty'><a name='NRS001Sec020'></a>NRS </span><span class='Section'>1.020</span><span class='Leadline'>Courts of record.</span> Every court of record shall keep records.</p>"
        "<p class='SectBody'>The clerk shall preserve all papers.</p>"
        "</body></html>"
    )

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        if url.endswith("/NRS/"):
            return index_html
        return chapter_html

    monkeypatch.setattr(NevadaScraper, "_request_text_direct", _fake_request_text_direct)

    scraper = NevadaScraper("NV", "Nevada")
    statutes = await scraper.scrape_code(
        "Nevada Revised Statutes",
        "https://www.leg.state.nv.us/NRS/",
        max_statutes=2,
    )

    assert len(statutes) >= 1
    assert statutes[0].section_number == "1.010"
    assert statutes[0].structured_data["source_kind"] == "official_nevada_revised_statutes_html"
    assert statutes[0].structured_data["discovery_method"] == "official_title_chapter_inline_sections"
    assert statutes[0].source_url.endswith("#NRS001Sec010")
    assert "The Supreme Court." in statutes[0].full_text


@pytest.mark.anyio
async def test_nebraska_bounded_run_prefers_official_chapter_index_sections(monkeypatch: pytest.MonkeyPatch):
    browse_html = (
        "<html><body>"
        "<a href='/laws/browse-chapters.php?chapter=01'>Chapter 1</a>"
        "</body></html>"
    )
    chapter_html = (
        "<html><body>"
        "<a href='/laws/statutes.php?statute=1-101'>View Statute 1-101</a>"
        "<a href='/laws/statutes.php?statute=1-102'>View Statute 1-102</a>"
        "</body></html>"
    )
    section_html = (
        "<html><body>"
        "<div class='card-body'><div class='statute'><h2>1-101.</h2><h3>General powers and duties.</h3>"
        + ("Nebraska statutory text. " * 20)
        + "</div></div>"
        "</body></html>"
    )

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        if url.endswith("browse-statutes.php"):
            return browse_html
        if "browse-chapters.php" in url:
            return chapter_html
        return section_html

    monkeypatch.setattr(NebraskaScraper, "_request_text_direct", _fake_request_text_direct)

    scraper = NebraskaScraper("NE", "Nebraska")
    statutes = await scraper.scrape_code(
        "Nebraska Revised Statutes",
        "https://nebraskalegislature.gov/laws/browse-statutes.php",
        max_statutes=2,
    )

    assert len(statutes) >= 1
    assert statutes[0].section_number == "1-101"
    assert statutes[0].structured_data["source_kind"] == "official_nebraska_statutes_html"
    assert statutes[0].structured_data["discovery_method"] == "official_chapter_index_sections"
    assert "Nebraska statutory text." in statutes[0].full_text


@pytest.mark.anyio
async def test_mississippi_request_text_records_fetch_analytics(monkeypatch: pytest.MonkeyPatch):
    async def _fake_unified_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b""

    def _fake_get(url: str, *args, **kwargs):
        html = "<html><body><h1>History of Actions</h1><p>House Bill 1234</p></body></html>".encode("utf-8")
        return _FakeResponse(html)

    monkeypatch.setattr(BaseStateScraper, "_fetch_page_content_with_archival_fallback", _make_fake_archival_fetch(_fake_get))

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
