from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    inventory_registered_state_scraper_transport_bypasses,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska import (
    AlaskaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
    ArkansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arizona import (
    ArizonaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import (
    CaliforniaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado import (
    ColoradoScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import (
    DelawareScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida import (
    FloridaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import (
    GeorgiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.idaho import (
    IdahoScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.illinois import (
    IllinoisScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kansas import (
    KansasScraper,
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scraper_type", "state_code", "state_name", "method_name", "url", "fallback", "returns_bytes"),
    (
        (ArizonaScraper, "AZ", "Arizona", "_fetch_official_az_html", "https://www.azleg.gov/ars/1/00001.htm", False, False),
        (CaliforniaScraper, "CA", "California", "_fetch_code_index_page", "https://leginfo.legislature.ca.gov/faces/codes.xhtml", True, True),
        (DelawareScraper, "DE", "Delaware", "_fetch_official_de_html", "https://delcode.delaware.gov/title1/index.html", True, False),
        (FloridaScraper, "FL", "Florida", "_fetch_official_fl_html", "https://www.leg.state.fl.us/Statutes/", True, False),
        (GeorgiaScraper, "GA", "Georgia", "_fetch_official_ga_html", "https://www.legis.ga.gov/legislation/georgia-code", True, False),
        (IdahoScraper, "ID", "Idaho", "_fetch_official_id_html", "https://legislature.idaho.gov/statutesrules/idstat/", False, False),
        (IllinoisScraper, "IL", "Illinois", "_fetch_official_il_html", "https://www.ilga.gov/Legislation/ILCS/Chapters", True, False),
        (KansasScraper, "KS", "Kansas", "_fetch_official_ks_html", "https://www.kslegislature.gov/li/b2025_26/statute/", True, False),
    ),
)
async def test_html_helpers_delegate_exact_bytes_to_shared_transport_adapter(
    monkeypatch: pytest.MonkeyPatch,
    scraper_type: type,
    state_code: str,
    state_name: str,
    method_name: str,
    url: str,
    fallback: bool,
    returns_bytes: bool,
) -> None:
    scraper = scraper_type(state_code, state_name)
    calls: list[tuple[str, dict[str, Any]]] = []
    payload = b"<html><body>official statute bytes</body></html>"

    async def _adapter(request_url: str, **kwargs: Any) -> bytes:
        calls.append((request_url, kwargs))
        return payload

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    result = await getattr(scraper, method_name)(url, timeout_seconds=3)

    assert result == (payload if returns_bytes else payload.decode("utf-8"))
    assert len(calls) == 1
    request_url, kwargs = calls[0]
    assert request_url == url
    assert kwargs["allow_archival_fallback"] is fallback
    assert kwargs["media_type"] == "text/html"
    assert kwargs["provider"] == "requests_direct"
    assert kwargs["timeout_seconds"] >= 1
    assert kwargs["headers"]["Accept"].startswith("text/html")


@pytest.mark.anyio
async def test_alaska_query_fetch_uses_adapter_and_body_bound_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = AlaskaScraper("AK", "Alaska")
    calls: list[tuple[str, dict[str, Any]]] = []
    payload = b'<div><a name="01.02.003"></a>statute</div>'

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        calls.append((url, kwargs))
        return payload

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    html, cursor = await scraper._fetch_statute_chunk("01.02.001", timeout_seconds=4)

    assert html.encode("cp1252") == payload
    assert cursor == "01.02.003"
    assert calls[0][0].endswith("media=print&type=fetch&secStart=01.02.001")
    assert calls[0][1]["allow_archival_fallback"] is True
    assert calls[0][1]["media_type"] == "text/html"


@pytest.mark.anyio
async def test_arkansas_direct_helper_rejects_challenge_through_adapter_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ArkansasScraper("AR", "Arkansas")
    calls: list[dict[str, Any]] = []

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        calls.append(kwargs)
        return b"<html>official Arkansas section</html>"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    result = await scraper._fetch_direct_html("https://law.justia.com/codes/arkansas/")

    assert result == b"<html>official Arkansas section</html>"
    assert calls[0]["allow_archival_fallback"] is False
    validator = calls[0]["content_validator"]
    assert validator(b"<html>official Arkansas section</html>") is True
    assert validator(b"<html>Just a moment; enable JavaScript and cookies</html>") is False


@pytest.mark.anyio
async def test_colorado_transport_selects_html_and_pdf_validators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ColoradoScraper("CO", "Colorado")
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _adapter(url: str, **kwargs: Any) -> bytes:
        calls.append((url, kwargs))
        return b"%PDF fixture" if url.endswith(".pdf") else b"<html>fixture</html>"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    html = await scraper._request_bytes_direct("https://content.leg.colorado.gov/crs")
    pdf = await scraper._request_bytes_direct("https://content.leg.colorado.gov/title.pdf")

    assert html == b"<html>fixture</html>"
    assert pdf == b"%PDF fixture"
    html_kwargs = calls[0][1]
    pdf_kwargs = calls[1][1]
    assert html_kwargs["media_type"] == "text/html"
    assert html_kwargs["content_validator"](html) is True
    assert html_kwargs["content_validator"](pdf) is False
    assert pdf_kwargs["media_type"] == "application/pdf"
    assert pdf_kwargs["content_validator"](pdf) is True
    assert pdf_kwargs["content_validator"](html) is False


def test_batch_a_inventory_keeps_only_non_expressible_transport_blockers() -> None:
    states = "AK AZ AR CA CO CT DE FL GA ID IL KS".split()
    inventory = inventory_registered_state_scraper_transport_bypasses(states)

    assert inventory["candidate_count"] == 0
    assert inventory["gap_jurisdictions"] == []
    candidates = {
        code: [row["call"] for row in inventory["jurisdictions"][code]["candidates"]]
        for code in inventory["gap_jurisdictions"]
    }
    assert candidates == {}
    for code in set(states) - set(inventory["gap_jurisdictions"]):
        row = inventory["jurisdictions"][code]
        assert row["complete"] is True
        assert row["shared_custom_transport_adapter_call_count"] >= 1
