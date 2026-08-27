from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    inventory_registered_state_scraper_transport_bypasses,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii import HawaiiScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import IndianaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa import IowaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky import KentuckyScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import LouisianaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland import MarylandScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts import (
    MassachusettsScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon import OregonScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota import (
    SouthDakotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee import (
    TennesseeScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming import (
    WyomingScraper,
)


@pytest.mark.anyio
async def test_kentucky_official_fetch_uses_shared_direct_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    seen: Dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        seen.update(url=url, **kwargs)
        return b"official KRS bytes"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)

    assert await scraper._fetch_official_ky_bytes("https://example.test/krs", 7) == b"official KRS bytes"
    assert seen["timeout_seconds"] == 7
    assert seen["allow_archival_fallback"] is True
    assert seen["provider"] == "requests_direct"


@pytest.mark.anyio
async def test_oregon_rule_retry_validates_adapter_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OregonScraper("OR", "Oregon")
    seen: Dict[str, Any] = {}

    async def _archival(*args: Any, **kwargs: Any) -> bytes:
        return b"<html>unrelated page</html>"

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        payload = b"<html>Rules of Civil Procedure</html>"
        assert kwargs["content_validator"](payload) is True
        assert kwargs["content_validator"](b"<html>wrong</html>") is False
        seen.update(url=url, **kwargs)
        return payload

    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _archival)
    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)

    html = await scraper._fetch_rule_page_html_with_direct_fallback(
        "https://example.test/orcp",
        expected_terms=["rules of civil procedure"],
        timeout_seconds=11,
    )

    assert "Rules of Civil Procedure" in html
    assert seen["allow_archival_fallback"] is False


@pytest.mark.anyio
async def test_south_dakota_json_fetch_validates_adapter_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    payload = b'{"Statute":"1-1-1"}'
    seen: Dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        assert kwargs["content_validator"](payload) is True
        assert kwargs["content_validator"](b"<html>blocked</html>") is False
        seen.update(url=url, **kwargs)
        return payload

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)

    assert await scraper._request_json("https://example.test/api", {}, 13) == {
        "Statute": "1-1-1"
    }
    assert seen["media_type"] == "application/json"
    assert seen["allow_archival_fallback"] is False


@pytest.mark.anyio
async def test_tennessee_reader_fetch_uses_shared_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    seen: Dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        seen.update(url=url, **kwargs)
        return b"# Tennessee Code section"

    monkeypatch.setattr(scraper, "_fetch_non_authoritative_reference_bytes", _adapter)

    text = await scraper._fetch_justia_section_markdown(
        "https://law.justia.com/codes/tennessee/2024/title-1/section-1-1-1/"
    )

    assert text.startswith("# Tennessee")
    assert seen["url"].startswith("https://r.jina.ai/http://")
    assert seen["enable_common_crawl"] is False


@pytest.mark.anyio
async def test_hawaii_direct_bytes_use_shared_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    seen: Dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        seen.update(url=url, **kwargs)
        return b"archived Hawaii bytes"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)

    payload = await scraper._request_bytes_direct(
        "https://web.archive.org/web/20240101/https://example.test/hrscurrent/",
        {"User-Agent": "test"},
        9,
    )

    assert payload == b"archived Hawaii bytes"
    assert seen["allow_archival_fallback"] is False


@pytest.mark.anyio
async def test_indiana_zip_bundle_uses_exact_adapter_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IndianaScraper("IN", "Indiana")
    zip_payload = b"PK\x03\x04" + (b"x" * 60)
    seen: Dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        assert kwargs["content_validator"](zip_payload) is True
        assert kwargs["content_validator"](b"PK\x03\x04short") is False
        assert kwargs["content_validator"](b"not a zip" + (b"x" * 80)) is False
        seen.update(url=url, **kwargs)
        return zip_payload

    monkeypatch.setenv("INDIANA_CODE_ZIP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("INDIANA_CODE_YEAR", "2026")
    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)

    result = await scraper._download_indiana_code_bundle()

    assert result is not None
    year, bundle_path, bundle_url = result
    assert year == 2026
    assert bundle_url.endswith("2026-Indiana-Code-html.zip")
    assert bundle_path.read_bytes() == zip_payload
    assert seen["allow_archival_fallback"] is True
    assert seen["media_type"] == "application/zip"


@pytest.mark.anyio
async def test_iowa_direct_text_and_bytes_use_shared_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IowaScraper("IA", "Iowa")
    calls: list[Dict[str, Any]] = []

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        calls.append({"url": url, **kwargs})
        return b"Iowa parser input"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)

    assert await scraper._request_text_direct("https://example.test/code", 8) == "Iowa parser input"
    assert await scraper._request_bytes_direct("https://example.test/code.xml", 9) == b"Iowa parser input"
    assert all(call["allow_archival_fallback"] is False for call in calls)


@pytest.mark.anyio
async def test_louisiana_wayback_replay_uses_shared_direct_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    seen: Dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        seen.update(url=url, **kwargs)
        return b"<html>Louisiana archived law</html>"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)

    text = await scraper._request_text(
        "https://web.archive.org/web/20240101/https://legis.la.gov/Legis/Law.aspx?d=1",
        {"User-Agent": "test"},
        10,
    )

    assert "Louisiana archived law" in text
    assert seen["allow_archival_fallback"] is False


@pytest.mark.anyio
async def test_maryland_json_and_text_use_shared_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    payloads = [b'[{"Value":"GSG"}]', b"<html>Maryland code</html>"]
    calls: list[Dict[str, Any]] = []

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        payload = payloads[len(calls)]
        if "content_validator" in kwargs:
            assert kwargs["content_validator"](payload) is True
            assert kwargs["content_validator"](b"not json") is False
        calls.append({"url": url, **kwargs})
        return payload

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)

    assert await scraper._fetch_json("https://example.test/articles") == [{"Value": "GSG"}]
    assert await scraper._fetch_text_direct("https://example.test/toc", 12) == "<html>Maryland code</html>"
    assert all(call["allow_archival_fallback"] is True for call in calls)


@pytest.mark.anyio
async def test_massachusetts_direct_text_uses_shared_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MassachusettsScraper("MA", "Massachusetts")
    seen: Dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        seen.update(url=url, **kwargs)
        return b"<html>Massachusetts General Laws</html>"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)

    text = await scraper._request_text_direct("https://example.test/mgl", 14)

    assert "General Laws" in text
    assert seen["allow_archival_fallback"] is False


@pytest.mark.anyio
async def test_wyoming_browser_catalog_uses_shared_render_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WyomingScraper("WY", "Wyoming")
    seen: Dict[str, Any] = {}

    async def _browser_adapter(url: str, **kwargs: Any) -> bytes:
        seen.update(url=url, **kwargs)
        return (
            b"<html><body>"
            b"<a href='/statutes/compress/title1.pdf'>Title 1 - General Provisions</a>"
            b"<a href='https://untrusted.example/statutes/compress/title2.pdf'>Title 2</a>"
            b"</body></html>"
        )

    async def _pdf_text(url: str, max_chars=None) -> str:
        del max_chars
        assert url == "https://www.wyoleg.gov/statutes/compress/title1.pdf"
        return "Official Wyoming statute text. " * 5

    monkeypatch.setattr(
        scraper,
        "_fetch_browser_parser_input_with_transport",
        _browser_adapter,
    )
    monkeypatch.setattr(scraper, "_extract_pdf_text_summary", _pdf_text)

    rows = await scraper._scrape_with_playwright(
        "Wyoming Statutes",
        "https://www.wyoleg.gov/stateStatutes/StatutesDownload",
        "Wyo. Stat.",
        max_sections=5,
    )

    assert [row.section_number for row in rows] == ["1"]
    assert seen["allowed_final_hosts"] == ("www.wyoleg.gov", "wyoleg.gov")
    assert seen["pagination"] == {"kind": "wyoming_title_pdf_catalog"}


def test_batch_inventory_retains_only_truthful_browser_session_and_cdx_blockers() -> None:
    states = ["KY", "OR", "SD", "TN", "WY", "HI", "IN", "IA", "LA", "MD", "MA"]
    report = inventory_registered_state_scraper_transport_bypasses(states)

    assert report["candidate_count"] == 0
    assert report["gap_jurisdictions"] == []
    assert {
        code: report["jurisdictions"][code]["candidate_count"]
        for code in states
    } == {
        "KY": 0,
        "OR": 0,
        "SD": 0,
        "TN": 0,
        "WY": 0,
        "HI": 0,
        "IN": 0,
        "IA": 0,
        "LA": 0,
        "MD": 0,
        "MA": 0,
    }
