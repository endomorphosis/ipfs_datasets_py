from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    inventory_registered_state_scraper_transport_bypasses,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
    MinnesotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import (
    MississippiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada import (
    NevadaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
    NewHampshireScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_jersey import (
    NewJerseyScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico import (
    NewMexicoScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import (
    NewYorkScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
    NorthCarolinaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import (
    OklahomaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania import (
    PennsylvaniaScraper,
)


ASSIGNED_STATES = "MN MS NE NV NH NJ NM NY NC ND OK PA".split()


def test_batch_c_transport_inventory_keeps_only_truthful_residuals() -> None:
    inventory = inventory_registered_state_scraper_transport_bypasses(ASSIGNED_STATES)

    assert inventory["candidate_count"] == 0
    assert inventory["gap_jurisdictions"] == []
    assert {
        state: row["shared_custom_transport_adapter_call_count"]
        for state, row in inventory["jurisdictions"].items()
    } == {
        "MN": 1,
        "MS": 2,
        "NE": 1,
        "NV": 1,
        "NH": 1,
        "NJ": 2,
        "NM": 1,
        "NY": 1,
        "NC": 1,
        "ND": 0,
        "OK": 1,
        "PA": 1,
    }
    assert {
        state: [candidate["parser_scope"] for candidate in row["candidates"]]
        for state, row in inventory["jurisdictions"].items()
        if row["candidates"]
    } == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scraper_type", "state_code", "state_name", "payload", "expected"),
    [
        (MinnesotaScraper, "MN", "Minnesota", b"Minnesota text", "Minnesota text"),
        (
            NevadaScraper,
            "NV",
            "Nevada",
            "Nevada \u00a7 text".encode("windows-1252"),
            "Nevada \u00a7 text",
        ),
    ],
)
async def test_official_text_helpers_parse_only_adapter_bytes(
    monkeypatch: pytest.MonkeyPatch,
    scraper_type: type,
    state_code: str,
    state_name: str,
    payload: bytes,
    expected: str,
) -> None:
    scraper = scraper_type(state_code, state_name)
    observed: dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        observed["url"] = url
        observed.update(kwargs)
        return payload

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    text = await scraper._request_text_direct(scraper.get_base_url(), timeout=7)

    assert text == expected
    assert observed["timeout_seconds"] == 7
    assert observed["allow_archival_fallback"] is True
    assert observed["media_type"] == "text/html"


@pytest.mark.asyncio
async def test_binary_helpers_apply_pdf_validation_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        calls.append((url, kwargs))
        return b"%PDF-1.7 retained"

    new_jersey = NewJerseyScraper("NJ", "New Jersey")
    pennsylvania = PennsylvaniaScraper("PA", "Pennsylvania")
    monkeypatch.setattr(new_jersey, "_fetch_parser_input_with_transport", _adapter)
    monkeypatch.setattr(pennsylvania, "_fetch_parser_input_with_transport", _adapter)

    assert await new_jersey._request_bytes_direct(
        "https://pub.njleg.state.nj.us/example.PDF",
        timeout=11,
    ) == b"%PDF-1.7 retained"
    assert await pennsylvania._request_pdf_bytes(
        "https://www.legis.state.pa.us/example.pdf",
        timeout=13,
    ) == b"%PDF-1.7 retained"

    for _url, kwargs in calls:
        assert kwargs["allow_archival_fallback"] is True
        assert kwargs["media_type"] == "application/pdf"
        assert kwargs["content_validator"](b"%PDF-1.7") is True
        assert kwargs["content_validator"](b"<html>blocked</html>") is False


@pytest.mark.asyncio
async def test_new_mexico_direct_helper_returns_only_retained_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NewMexicoScraper("NM", "New Mexico")
    observed: dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        observed["url"] = url
        observed.update(kwargs)
        return b"retained NMOneSource bytes"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    result = await scraper._request_bytes_direct(scraper.OFFICIAL_ENTRY_URL, timeout=9)

    assert result == b"retained NMOneSource bytes"
    assert observed["provider"] == "new_mexico_direct_nmonesource"
    assert observed["allow_archival_fallback"] is True


@pytest.mark.asyncio
async def test_mississippi_official_tls_paths_use_shared_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        calls.append((url, kwargs))
        return b"official Mississippi text"

    async def _external(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("official URL must not use the external-source transport")

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    monkeypatch.setattr(scraper, "_request_external_source_text_direct", _external)

    url = "https://www.legislature.ms.gov/legislation/ms-code/"
    assert await scraper._request_text_direct(url, timeout=8) == "official Mississippi text"
    assert await scraper._request_text_with_insecure_tls_retry(
        url=url,
        headers={"User-Agent": "test-agent"},
        timeout=8,
    ) == "official Mississippi text"

    assert calls[0][1].get("verify_tls", True) is True
    assert calls[0][1]["allow_archival_fallback"] is False
    assert calls[1][1]["verify_tls"] is False
    assert calls[1][1]["allow_archival_fallback"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scraper", "official_url", "external_url", "external_method_name"),
    [
        (
            NewHampshireScraper("NH", "New Hampshire"),
            "https://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm",
            "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm",
            "_request_archival_source_text_direct",
        ),
        (
            NewYorkScraper("NY", "New York"),
            "https://www.nysenate.gov/legislation/laws/PEN/1.00",
            "https://r.jina.ai/http://https://www.nysenate.gov/legislation/laws/PEN/1.00",
            "_request_external_source_text_direct",
        ),
    ],
)
async def test_official_and_external_source_hops_are_not_conflated(
    monkeypatch: pytest.MonkeyPatch,
    scraper: Any,
    official_url: str,
    external_url: str,
    external_method_name: str,
) -> None:
    adapter_urls: list[str] = []
    external_urls: list[str] = []

    async def _adapter(url: str, **_kwargs: Any) -> bytes:
        adapter_urls.append(url)
        return b"official retained text"

    async def _external(url: str, **_kwargs: Any) -> str:
        external_urls.append(url)
        return "explicit external-source text"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    monkeypatch.setattr(scraper, external_method_name, _external)

    assert await scraper._request_text_direct(official_url, timeout=6) == "official retained text"
    assert await scraper._request_text_direct(external_url, timeout=6) == (
        "explicit external-source text"
    )
    assert adapter_urls == [official_url]
    assert external_urls == [external_url]


@pytest.mark.asyncio
async def test_oklahoma_live_oscn_uses_nonarchival_adapter_and_antibot_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OklahomaScraper("OK", "Oklahoma")
    observed: dict[str, Any] = {}

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        observed["url"] = url
        observed.update(kwargs)
        return b"<html>official OSCN statute</html>"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    url = "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=1"
    text = await scraper._request_live_oscn_text(url, {}, timeout=30)

    assert text == "<html>official OSCN statute</html>"
    assert observed["timeout_seconds"] == 12
    assert observed["allow_archival_fallback"] is False
    assert observed["content_validator"](b"ordinary statute") is True
    assert observed["content_validator"](b"Just a moment...") is False


@pytest.mark.asyncio
async def test_north_carolina_official_tail_uses_adapter_but_secondary_tail_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    adapter_urls: list[str] = []
    secondary_urls: list[str] = []

    async def _archival(*_args: Any, **_kwargs: Any) -> bytes:
        return b""

    async def _adapter(url: str, **_kwargs: Any) -> bytes:
        adapter_urls.append(url)
        return b"official NC statute"

    async def _secondary(url: str, **_kwargs: Any) -> str:
        secondary_urls.append(url)
        return "declared Justia fallback"

    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _archival)
    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    monkeypatch.setattr(scraper, "_request_secondary_source_text_direct", _secondary)

    official = "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-1.html"
    secondary = "https://law.justia.com/codes/north-carolina/chapter-1/"
    assert await scraper._request_text_direct(official, timeout=1) == "official NC statute"
    assert await scraper._request_text_direct(secondary, timeout=1) == (
        "declared Justia fallback"
    )
    assert adapter_urls == [official]
    assert secondary_urls == [secondary]
