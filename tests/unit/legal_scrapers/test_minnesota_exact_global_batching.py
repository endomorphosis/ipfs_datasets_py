from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    minnesota_section,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
    MinnesotaScraper,
)


MN_ALIAS_URL = "https://www.revisor.mn.gov/statutes/cite/296.01-1"
MN_ALIAS_SHA256 = (
    "04a01e0bb5ce4817e0ca76ab1e9a67bfa80920ed4155adbbd9fcbbfc7dbb6893"
)
MN_SEE_NOTE_URL = "https://www.revisor.mn.gov/statutes/cite/352.91"
MN_SEE_NOTE_SHA256 = (
    "2ac0e1bd344a9117b4a71b8a19226a4ebe4ea67211fe59b34c8bb5319408c12a"
)


def _mn_terminal_see_note_payload() -> bytes:
    return (
        "<html><body><div id='header'><h1>2025 Minnesota Statutes</h1></div>"
        "<div class='sr_by_subd' id='stat.352.91'><h1>352.91</h1>"
        "<div class='subd' id='stat.352.91.1'>"
        "<p>[Repealed, 1996 c 408 art 8 s 29]</p></div>"
        "<div class='subd' id='stat.352.91.3c'>"
        "<p>MS 2025 Supp [Repealed, 2025 c 37 art 5 s 11]</p>"
        "<p class='see_note'>[See Note.]</p></div>"
        "<div class='subd' id='stat.352.91.3f'>"
        "<p>MS 2025 Supp [Repealed, 2025 c 37 art 5 s 11]</p>"
        "<p class='see_note'>[See Note.]</p></div></div>"
        "<p><b>NOTE: </b>The repeal of subdivision 3c is effective later.</p>"
        "<div class='subd' id='stat.352.91.3c'>"
        "<p>Quoted amendment text is not an operative .section.</p></div>"
        "</body></html>"
    ).encode()


def _bind_mn_terminal_see_note_contract(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    monkeypatch.setattr(
        minnesota_section,
        "_EXACT_TERMINAL_SEE_NOTE_CONTRACTS",
        {
            MN_SEE_NOTE_URL: {
                "content_byte_size": len(payload),
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "subdivision_ids": (
                    "stat.352.91.3c",
                    "stat.352.91.3f",
                ),
            }
        },
    )


def _aligned_result(urls: list[str]) -> StateLawPageMultiFetchResult:
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=[f"official:{url}".encode() for url in urls],
        errors=[None] * len(urls),
        transport_receipts=[None] * len(urls),
        parser_input_envelopes=[None] * len(urls),
        stats={"requested_pages": len(urls)},
    )


def test_minnesota_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "minnesota_section",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota."
        "MinnesotaScraper@sha256:"
    )

    archival_source = inspect.getsourcefile(dependencies[1])
    assert archival_source is not None
    archival_path = Path(archival_source).resolve()
    original_read_bytes = Path.read_bytes

    def _read_mutated_dependency(path: Path) -> bytes:
        payload = original_read_bytes(path)
        if path.resolve() == archival_path:
            return payload + b"\n# synthetic producer-affecting mutation\n"
        return payload

    monkeypatch.setattr(Path, "read_bytes", _read_mutated_dependency)

    assert scraper._state_law_frontier_source_software_version() != baseline


@pytest.mark.anyio
async def test_minnesota_plural_policy_uses_one_inventory_and_residual_only_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    urls = [
        "https://www.revisor.mn.gov/statutes/cite/1.01",
        "https://www.revisor.mn.gov/statutes/cite/2.01",
        "https://www.revisor.mn.gov/statutes/cite/3.01",
    ]
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _retrying(requested_urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append((requested, dict(kwargs)))
        return _aligned_result(requested)

    monkeypatch.setenv("STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS", "0")
    monkeypatch.setenv("STATE_SCRAPER_MN_FRONTIER_RESIDUAL_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _retrying,
    )

    payloads = await scraper._fetch_minnesota_frontier_in_chunks(
        urls,
        frontier_name="section",
    )

    assert [requested for requested, _kwargs in calls] == [urls]
    assert payloads == [f"official:{url}".encode() for url in urls]
    kwargs = calls[0][1]
    assert kwargs["residual_retry_attempts"] == 2
    assert kwargs["repeat_grouped_archive_inventory_on_residual"] is False
    assert kwargs["wayback_prefix_inventory"] is True
    assert kwargs["common_crawl_domain_terms"] == ("www.revisor.mn.gov",)
    assert kwargs["common_crawl_url_terms"] == ("/statutes/",)


def test_minnesota_terminal_display_alias_is_exact_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        "<html><body><div class='sr' id='stat.296.01-1'>"
        "<b>296.01</b> [Repealed, 1998 c 299 s 31]"
        "</div></body></html>"
    ).encode()
    monkeypatch.setattr(
        minnesota_section,
        "_EXACT_TERMINAL_DISPLAY_CITATION_ALIASES",
        {
            MN_ALIAS_URL: {
                "content_byte_size": len(payload),
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "display_citation": "296.01",
            }
        },
    )

    classified = minnesota_section.classify_minnesota_terminal_section_html(
        payload.decode(),
        source_url=MN_ALIAS_URL,
    )

    assert classified is not None
    assert classified["disposition"] == "repealed"
    assert classified["section_number"] == "296.01-1"
    assert (
        minnesota_section.classify_minnesota_terminal_section_html(
            (payload + b" ").decode(),
            source_url=MN_ALIAS_URL,
        )
        is None
    )


def test_minnesota_terminal_display_alias_replays_retained_contract() -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_MN_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Minnesota acquisition evidence")

    payload_path = Path(evidence_root) / "MN" / "objects" / f"{MN_ALIAS_SHA256}.bin"
    payload = payload_path.read_bytes()
    assert len(payload) == 60883
    assert hashlib.sha256(payload).hexdigest() == MN_ALIAS_SHA256

    classified = minnesota_section.classify_minnesota_terminal_section_html(
        payload.decode("utf-8"),
        source_url=MN_ALIAS_URL,
    )
    assert classified is not None
    assert classified["disposition"] == "repealed"
    assert classified["section_number"] == "296.01-1"


def test_minnesota_terminal_see_note_contract_is_exact_and_source_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _mn_terminal_see_note_payload()
    _bind_mn_terminal_see_note_contract(monkeypatch, payload)

    classified = minnesota_section.classify_minnesota_terminal_section_html(
        payload.decode(),
        source_url=MN_SEE_NOTE_URL,
        expected_edition=MinnesotaScraper.OFFICIAL_EDITION,
    )

    assert classified is not None
    assert classified["disposition"] == "repealed"
    assert classified["section_number"] == "352.91"
    assert classified["source_blocks"] == 3
    assert classified["marker_texts"] == [
        "[Repealed, 1996 c 408 art 8 s 29]",
        "MS 2025 Supp [Repealed, 2025 c 37 art 5 s 11]",
        "MS 2025 Supp [Repealed, 2025 c 37 art 5 s 11]",
    ]
    assert (
        minnesota_section.classify_minnesota_terminal_section_html(
            (payload + b" ").decode(),
            source_url=MN_SEE_NOTE_URL,
            expected_edition=MinnesotaScraper.OFFICIAL_EDITION,
        )
        is None
    )


@pytest.mark.parametrize(
    "old,new",
    (
        (b"class='see_note'", b"class='editorial_note'"),
        (b"[See Note.]", b"[See Other Note.]"),
        (b"stat.352.91.3f", b"stat.352.91.3g"),
    ),
)
def test_minnesota_terminal_see_note_contract_rejects_dom_drift(
    monkeypatch: pytest.MonkeyPatch,
    old: bytes,
    new: bytes,
) -> None:
    payload = _mn_terminal_see_note_payload().replace(old, new)
    _bind_mn_terminal_see_note_contract(monkeypatch, payload)

    assert (
        minnesota_section.classify_minnesota_terminal_section_html(
            payload.decode(),
            source_url=MN_SEE_NOTE_URL,
            expected_edition=MinnesotaScraper.OFFICIAL_EDITION,
        )
        is None
    )


def test_minnesota_terminal_see_note_replays_retained_contract() -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_MN_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Minnesota acquisition evidence")

    payload_path = (
        Path(evidence_root) / "MN" / "objects" / f"{MN_SEE_NOTE_SHA256}.bin"
    )
    payload = payload_path.read_bytes()
    assert len(payload) == 97874
    assert hashlib.sha256(payload).hexdigest() == MN_SEE_NOTE_SHA256

    classified = minnesota_section.classify_minnesota_terminal_section_html(
        payload.decode("utf-8"),
        source_url=MN_SEE_NOTE_URL,
        expected_edition=MinnesotaScraper.OFFICIAL_EDITION,
    )
    assert classified is not None
    assert classified["disposition"] == "repealed"
    assert classified["section_number"] == "352.91"
    assert classified["source_blocks"] == 20
