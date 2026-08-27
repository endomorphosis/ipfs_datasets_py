"""Fail-closed Arkansas delegated-source discovery and body transport."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import arkansas_lexis
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
    ArkansasDelegatedCorpusBlockedError,
    ArkansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas_lexis import (
    PUBLIC_CONTAINER_URL,
    ArkansasLexisNode,
    document_page_url,
)

RECEIPT_SHA256 = "a" * 64
SECTION_PATH = (
    "/shared/document/statutes-legislation/"
    "urn:contentItem:4WVC-V220-R03K-21P9-00008-00"
)
BODY_HTML = b"""
<!doctype html><html><body>
  <div id="document-content">
    <h1>1-1-101. Extension of western boundary line.</h1>
    <p>The western boundary line of the State of Arkansas is extended according
    to the enacted terms stated in this section, and this sentence is statutory text.</p>
    <h2>History</h2><p>Publisher editorial history must not be admitted.</p>
  </div>
</body></html>
"""


def _verified_node() -> ArkansasLexisNode:
    raw = ArkansasLexisNode(
        node_id="AABAABAAC",
        title="1-1-101. Extension of western boundary line.",
        level=3,
        node_path="/ROOT/AAB/AABAAB/AABAABAAC",
        can_expand=False,
        can_open=True,
        has_children=False,
        link_href=SECTION_PATH,
        subscribed=True,
        purchase_required=False,
        list_price=0.0,
        net_price=0.0,
        pricing_present=True,
        currency_code="USD",
        usage_type_code="subscription",
        document_status="Available",
    )
    bound = arkansas_lexis._bind_live_nodes(
        [raw],
        source_url=PUBLIC_CONTAINER_URL,
        observed_at=datetime.now(UTC).isoformat(),
        receipt_sha256=RECEIPT_SHA256,
    )
    assert len(bound) == 1
    return bound[0]


def test_document_page_url_is_stable_and_exactly_bound() -> None:
    url = document_page_url(_verified_node())
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "advance.lexis.com"
    assert parsed.path == "/documentpage/"
    assert query == {
        "pdmfid": [arkansas_lexis.TOC_SEARCH_MFID],
        "config": [arkansas_lexis.TOC_DOCUMENT_CONFIG],
        "pddocfullpath": [SECTION_PATH],
    }
    assert "crid" not in query
    assert "prid" not in query


def test_arkansas_source_bundle_binds_delegated_lexis_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ArkansasScraper("AR", "Arkansas")
    assert scraper.state_law_frontier_source_dependencies() == (arkansas_lexis,)

    baseline = scraper._state_law_frontier_source_software_version()
    helper_path = Path(arkansas_lexis.__file__).resolve()
    original_read_bytes = Path.read_bytes

    def _read_with_helper_drift(path: Path) -> bytes:
        payload = original_read_bytes(path)
        if path.resolve() == helper_path:
            return payload + b"\n# simulated Arkansas Lexis parser drift\n"
        return payload

    monkeypatch.setattr(Path, "read_bytes", _read_with_helper_drift)
    changed = scraper._state_law_frontier_source_software_version()

    assert changed != baseline
    assert changed.split("@sha256:", 1)[0] == baseline.split("@sha256:", 1)[0]


def test_delegated_body_parser_rejects_captcha_and_removes_editorial_history() -> None:
    scraper = ArkansasScraper("AR", "Arkansas")

    body = scraper._delegated_lexis_body_text(
        BODY_HTML,
        section_number="1-1-101",
    )

    assert body.startswith("1-1-101. Extension of western boundary line.")
    assert "statutory text" in body
    assert "Publisher editorial history" not in body
    assert (
        scraper._delegated_lexis_body_text(
            b"<html><body>Captcha Validation PawFirstDocAccess</body></html>",
            section_number="1-1-101",
        )
        == ""
    )


def test_shared_archival_client_can_disable_archive_is_per_call(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
        ArchivalFetchClient,
    )

    client = ArchivalFetchClient(
        request_timeout_seconds=1,
        enable_direct=False,
    )

    async def _wayback_miss(_url: str):
        return None

    async def _unexpected_archive_is(_url: str):
        raise AssertionError("archive.is submission must remain disabled")

    monkeypatch.delenv("LEGAL_SCRAPER_DISABLE_WAYBACK", raising=False)
    monkeypatch.delenv("LEGAL_SCRAPER_DISABLE_ARCHIVE_IS", raising=False)
    monkeypatch.setattr(client, "_is_stage_backed_off", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(client, "_fetch_from_wayback", _wayback_miss)
    monkeypatch.setattr(client, "_fetch_from_archive_is", _unexpected_archive_is)

    with pytest.raises(RuntimeError, match="Unable to fetch URL"):
        asyncio.run(
            client.fetch_with_fallback(
                "https://advance.lexis.com/documentpage/?exact=true",
                enable_common_crawl=False,
                enable_archive_is=False,
            )
        )


def test_shared_archival_client_keeps_archive_is_enabled_by_default(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
        ArchivalFetchClient,
        FetchResult,
    )

    client = ArchivalFetchClient(
        request_timeout_seconds=1,
        enable_direct=False,
    )
    target_url = "https://example.gov/exact-statute"

    async def _wayback_miss(_url: str):
        return None

    async def _archive_is_hit(url: str):
        return FetchResult(
            url=url,
            content=b"<html><body>archived statute</body></html>",
            source="archive_is",
            fetched_at="2026-08-24T00:00:00+00:00",
            archive_url="https://archive.is/AbCdE",
        )

    monkeypatch.delenv("LEGAL_SCRAPER_DISABLE_WAYBACK", raising=False)
    monkeypatch.delenv("LEGAL_SCRAPER_DISABLE_ARCHIVE_IS", raising=False)
    monkeypatch.setattr(client, "_is_stage_backed_off", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(client, "_fetch_from_wayback", _wayback_miss)
    monkeypatch.setattr(client, "_fetch_from_archive_is", _archive_is_hit)

    result = asyncio.run(
        client.fetch_with_fallback(target_url, enable_common_crawl=False)
    )

    assert result.source == "archive_is"


def test_arkansas_plural_wayback_inventory_forbids_legacy_page_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        state_archival_fetch,
    )
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    urls = [
        f"https://advance.lexis.com/documentpage/?exact-urn={index}"
        for index in range(4)
    ]
    common_crawl_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    wayback_inventory_calls: list[tuple[str, ...]] = []
    legacy_wayback_calls: list[str] = []
    archive_is_calls: list[str] = []
    scraper = ArkansasScraper("AR", "Arkansas")

    async def _common_crawl_inventory(*, domain_terms, url_terms, **_kwargs):
        common_crawl_calls.append((tuple(domain_terms), tuple(url_terms)))
        return []

    async def _wayback_inventory(target_urls, **_kwargs):
        wayback_inventory_calls.append(tuple(target_urls))
        return {
            "status": "complete",
            "captures_by_url": {},
            "stats": {
                "requested_pages": len(target_urls),
                "unique_pages": len(set(target_urls)),
                "prefix_queries_planned": 1,
                "prefix_queries_attempted": 1,
                "prefix_queries_succeeded": 1,
                "matched_pages": 0,
                "unmatched_pages": len(target_urls),
            },
        }

    async def _legacy_wayback(_self, url: str):
        legacy_wayback_calls.append(url)
        raise AssertionError("legacy per-page Wayback must remain disabled")

    async def _archive_is(_self, url: str):
        archive_is_calls.append(url)
        raise AssertionError("archive.is must remain disabled for the plural wave")

    monkeypatch.setattr(scraper, "_search_state_common_crawl_records", _common_crawl_inventory)
    monkeypatch.setattr(
        wayback_machine_engine,
        "fetch_wayback_capture_inventory",
        _wayback_inventory,
    )
    monkeypatch.setattr(
        state_archival_fetch.ArchivalFetchClient,
        "_fetch_direct",
        lambda _self, _url, **_kwargs: None,
    )
    monkeypatch.setattr(
        state_archival_fetch.ArchivalFetchClient,
        "_fetch_from_wayback",
        _legacy_wayback,
    )
    monkeypatch.setattr(
        state_archival_fetch.ArchivalFetchClient,
        "_fetch_from_archive_is",
        _archive_is,
    )

    batch = asyncio.run(
        scraper._fetch_page_contents_with_archival_fallback(
            urls,
            content_validator=bool,
            prefer_direct=True,
            common_crawl_domain_terms=("advance.lexis.com",),
            common_crawl_url_terms=("/documentpage/",),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
        )
    )

    assert common_crawl_calls == [(('advance.lexis.com',), ('/documentpage/',))]
    assert wayback_inventory_calls == [tuple(urls)]
    assert legacy_wayback_calls == []
    assert archive_is_calls == []
    assert batch.stats["common_crawl_inventory_queries"] == 1
    assert batch.stats["fallback_requests"] == 0
    assert batch.stats["per_page_archive_fallback_disabled"] is True
    assert batch.stats["grouped_inventory_residual_pages"] == 4


def test_shared_common_crawl_result_retains_exact_warc_transport_evidence(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
        ArchivalFetchClient,
    )

    body = b"<html><body>exact archived body</body></html>"
    indexed_url = "https://advance.lexis.com/documentpage/?exact=true"
    warc_member = (
        b"WARC/1.0\r\nWARC-Type: response\r\nWARC-Target-URI: "
        + indexed_url.encode("ascii")
        + b"\r\n\r\n"
        + b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
        + str(len(body)).encode("ascii")
        + b"\r\n\r\n"
        + body
    )
    raw_warc = gzip.compress(warc_member)
    filename = (
        "crawl-data/CC-MAIN-2026-30/segments/1720000000000.0/warc/"
        "CC-MAIN-20260824000000-example.warc.gz"
    )
    client = ArchivalFetchClient(content_validator=lambda payload: payload == body)

    class _SharedEngine:
        def fetch_warc_record(
            self,
            warc_filename: str,
            warc_offset: int,
            warc_length: int,
            **kwargs,
        ) -> bytes:
            assert warc_filename == filename
            assert warc_offset == 0
            assert warc_length == len(raw_warc)
            assert kwargs["max_bytes"] == len(raw_warc)
            return raw_warc

    result = client._fetch_from_common_crawl_warc_record(
        indexed_url,
        {
            "url": indexed_url,
            "timestamp": "20260824000000",
            "warc_filename": filename,
            "warc_offset": 0,
            "warc_length": len(raw_warc),
        },
        engine=_SharedEngine(),
    )

    assert result is not None
    assert result.common_crawl_indexed_url == indexed_url
    assert result.common_crawl_warc_filename == filename
    assert result.common_crawl_warc_offset == 0
    assert result.common_crawl_warc_length == len(raw_warc)
    assert result.common_crawl_collection == "CC-MAIN-2026-30"
    assert result.archive_timestamp == "20260824000000"
    assert result.status_code == 200
    assert result.content_sha256 == hashlib.sha256(body).hexdigest()


def test_shared_common_crawl_warc_fetch_rejects_locator_length_drift() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
        ArchivalFetchClient,
    )

    expected_length = 128

    class _ShortReadEngine:
        def fetch_warc_record(self, *_args, **_kwargs) -> bytes:
            return b"short-read"

    result = ArchivalFetchClient()._fetch_from_common_crawl_warc_record(
        "https://advance.lexis.com/documentpage/?exact=true",
        {
            "warc_filename": "crawl-data/CC-MAIN-2026-30/example.warc.gz",
            "warc_offset": 12,
            "warc_length": expected_length,
        },
        engine=_ShortReadEngine(),
    )

    assert result is None


def test_verified_direct_delegated_bytes_receive_shared_transport_receipt(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        state_archival_fetch,
    )

    class _Client:
        def __init__(self, **kwargs):
            assert kwargs["content_validator"](BODY_HTML) is True

        async def fetch_with_fallback(self, url: str, **kwargs):
            assert kwargs == {
                "enable_common_crawl": False,
                "enable_archive_is": False,
            }
            return SimpleNamespace(
                url=url,
                content=BODY_HTML,
                source="direct",
                archive_url=None,
                archive_timestamp=None,
            )

    monkeypatch.setattr(state_archival_fetch, "ArchivalFetchClient", _Client)
    scraper = ArkansasScraper("AR", "Arkansas")

    row, diagnostic = asyncio.run(
        scraper._fetch_verified_delegated_lexis_statute(
            code_name="Arkansas Code",
            node=_verified_node(),
        )
    )

    assert row is not None
    assert row.section_number == "1-1-101"
    assert row.source_url == document_page_url(_verified_node())
    assert row.structured_data["source_authority_class"] == "official"
    assert row.structured_data["transport_receipt"]["source_transport"] == "direct"
    assert row.structured_data["content_sha256"] == hashlib.sha256(BODY_HTML).hexdigest()
    assert row.structured_data["full_corpus_admissible"] is False
    assert row.structured_data["delegated_inventory_scope_only"] is True
    assert diagnostic["disposition"] == "verified_body_probe"


def test_unbound_wayback_body_is_rejected_even_when_text_looks_valid(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        state_archival_fetch,
    )

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def fetch_with_fallback(self, url: str, **kwargs):
            assert kwargs == {
                "enable_common_crawl": False,
                "enable_archive_is": False,
            }
            return SimpleNamespace(
                url=url,
                content=BODY_HTML,
                source="wayback",
                archive_url=(
                    "https://web.archive.org/web/20250102030405id_/"
                    "https://advance.lexis.com/documentpage/?unrelated=true"
                ),
                archive_timestamp="20250102030405",
            )

    monkeypatch.setattr(state_archival_fetch, "ArchivalFetchClient", _Client)

    row, diagnostic = asyncio.run(
        ArkansasScraper("AR", "Arkansas")._fetch_verified_delegated_lexis_statute(
            code_name="Arkansas Code",
            node=_verified_node(),
        )
    )

    assert row is None
    assert "wayback_official_url_mismatch" in diagnostic["error"]


def test_common_crawl_body_requires_exact_index_and_warc_range_binding(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        state_archival_fetch,
    )

    source_url = document_page_url(_verified_node())
    warc_filename = (
        "crawl-data/CC-MAIN-2026-30/segments/1720000000000.0/warc/"
        "CC-MAIN-20260824000000-example.warc.gz"
    )

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def fetch_with_fallback(self, url: str, **kwargs):
            assert url == source_url
            assert kwargs == {
                "enable_common_crawl": False,
                "enable_archive_is": False,
            }
            return SimpleNamespace(
                url=url,
                content=BODY_HTML,
                source="common_crawl",
                archive_url=f"https://data.commoncrawl.org/{warc_filename}",
                archive_timestamp="20260824000000",
                status_code=206,
                common_crawl_indexed_url=url,
                common_crawl_warc_filename=warc_filename,
                common_crawl_warc_offset=123,
                common_crawl_warc_length=456,
                common_crawl_collection="CC-MAIN-2026-30",
                content_sha256=hashlib.sha256(BODY_HTML).hexdigest(),
            )

    monkeypatch.setattr(state_archival_fetch, "ArchivalFetchClient", _Client)

    row, diagnostic = asyncio.run(
        ArkansasScraper("AR", "Arkansas")._fetch_verified_delegated_lexis_statute(
            code_name="Arkansas Code",
            node=_verified_node(),
        )
    )

    assert row is not None
    evidence = row.structured_data["common_crawl_transport_evidence"]
    assert evidence["indexed_url"] == source_url
    assert evidence["warc_offset"] == 123
    assert diagnostic["common_crawl_transport_evidence"] == evidence


def test_common_crawl_body_rejects_different_indexed_lexis_locator(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        state_archival_fetch,
    )

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def fetch_with_fallback(self, url: str, **_kwargs):
            return SimpleNamespace(
                url=url,
                content=BODY_HTML,
                source="common_crawl",
                archive_url=(
                    "https://data.commoncrawl.org/crawl-data/CC-MAIN-2026-30/"
                    "segments/1/warc/example.warc.gz"
                ),
                archive_timestamp="20260824000000",
                status_code=206,
                common_crawl_indexed_url=f"{url}&unrelated=true",
                common_crawl_warc_filename=(
                    "crawl-data/CC-MAIN-2026-30/segments/1/warc/example.warc.gz"
                ),
                common_crawl_warc_offset=123,
                common_crawl_warc_length=456,
                common_crawl_collection="CC-MAIN-2026-30",
                content_sha256=hashlib.sha256(BODY_HTML).hexdigest(),
            )

    monkeypatch.setattr(state_archival_fetch, "ArchivalFetchClient", _Client)

    row, diagnostic = asyncio.run(
        ArkansasScraper("AR", "Arkansas")._fetch_verified_delegated_lexis_statute(
            code_name="Arkansas Code",
            node=_verified_node(),
        )
    )

    assert row is None
    assert diagnostic["error"] == "common_crawl_indexed_url_mismatch"


def test_full_corpus_raises_receipted_blocker_before_secondary_recovery(
    monkeypatch,
) -> None:
    scraper = ArkansasScraper("AR", "Arkansas")
    checkpoints: list[tuple[list[object], dict[str, object]]] = []
    evidence = {
        "schema_version": "arkansas-delegated-body-probe/v1",
        "disposition": "delegated_body_access_blocked",
        "delegation_verified": True,
        "frontier": {
            "title_inventory_closed": True,
            "discovered_title_count": 28,
            "statute_locator_count": 81,
        },
        "body_probes": [
            {
                "section_number": "1-1-101",
                "disposition": "unavailable",
                "error": "live body rejected and no exact Wayback body was found",
            }
        ],
        "secondary_recovery_admitted": False,
    }

    async def _no_official(*_args, **_kwargs):
        return []

    async def _probe(**_kwargs):
        return evidence

    async def _forbidden_justia(*_args, **_kwargs):
        raise AssertionError("secondary Justia rows must not enter a full corpus")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_scrape_official_arkansas_code", _no_official)
    monkeypatch.setattr(scraper, "_probe_delegated_arkansas_code", _probe)
    monkeypatch.setattr(scraper, "_scrape_justia_titles", _forbidden_justia)
    monkeypatch.setattr(
        scraper,
        "_write_partial_checkpoint",
        lambda rows, **kwargs: checkpoints.append((list(rows), kwargs)) or True,
    )

    with pytest.raises(
        ArkansasDelegatedCorpusBlockedError,
        match="delegated_body_access_blocked",
    ) as exc_info:
        asyncio.run(
            scraper.scrape_code(
                "Arkansas Code",
                scraper.OFFICIAL_CODE_INDEX,
                max_statutes=None,
            )
        )

    assert exc_info.value.evidence == evidence
    assert checkpoints[-1][1]["stage_label"] == "arkansas:delegated_body_blocked"
    assert checkpoints[-1][1]["extra"]["arkansas_delegated_frontier"] == evidence
