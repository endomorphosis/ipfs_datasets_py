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

