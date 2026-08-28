from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import (
    MississippiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi_lexis import (
    EXPECTED_ROOT_NODE_IDS,
    EXPECTED_TITLE_NAMES,
    EXPECTED_TITLE_NUMBERS,
    OFFICIAL_LEGISLATURE_ENTRY_URL,
    PUBLIC_CONTAINER_CONFIG,
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    RECENT_LEGISLATION_ROOT_LABEL,
    _bind_live_nodes,
    canonical_rendered_root_request,
    canonical_toc_patch_request,
    document_page_url,
    node_from_mapping,
    parse_root_html,
    valid_document_payload,
)

OBSERVED_AT = "2026-08-26T12:00:00+00:00"


def _root_html() -> str:
    labels = [
        RECENT_LEGISLATION_ROOT_LABEL,
        *(
            f"TITLE {number}. {EXPECTED_TITLE_NAMES[int(number)]}"
            for number in EXPECTED_TITLE_NUMBERS
        ),
    ]
    nodes = "".join(
        (
            f'<li class="js-node" data-nodeid="{node_id}" '
            f'data-nodepath="/ROOT/{node_id}" data-level="1" '
            f'data-title="{label}" data-canexpand="true" '
            'data-canopen="false" data-haschildren="true">'
            '<div class="js-node-header">'
            '<button data-command="open-to" data-targetlevel="2"></button>'
            "</div></li>"
        )
        for node_id, label in zip(EXPECTED_ROOT_NODE_IDS, labels, strict=True)
    )
    return (
        "<html><body><p>Mississippi Code Of 1972 Unannotated - Free Public "
        f"Access maintained by LexisNexis</p><ul>{nodes}</ul></body></html>"
    )


def _document_mapping(position: int, root_id: str, title_number: str) -> dict[str, Any]:
    node_id = f"D{position:03d}"
    section_number = "1-99-1" if position == 0 else f"{title_number}-1-1"
    title = (
        f"Miss. Code Ann. § {section_number}. Recent enactment."
        if position == 0
        else f"§ {section_number}. Synthetic retained-shape section."
    )
    token = f"M{position:03d}-ABCD-EFGH-IJKL-{position:05d}-00"
    return {
        "id": node_id,
        "props": {
            "nodeid": node_id,
            "linktemplatetitle": title,
            "level": 2,
            "nodepath": f"/ROOT/{root_id}/{node_id}",
            "canexpand": False,
            "canopen": True,
            "haschildren": False,
            "linkhref": (
                "/shared/document/statutes-legislation/"
                f"urn:contentItem:{token}"
            ),
        },
    }


class _Envelope(SimpleNamespace):
    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition": {
                "body_sha256": hashlib.sha256(bytes(self.body)).hexdigest(),
                "receipt": {"receipt_sha256": self.receipt_sha256},
            }
        }


class _Retained(SimpleNamespace):
    pass


class _Ledger:
    retained_replay_only = True

    def __init__(self) -> None:
        self.entries: dict[str, _Retained] = {}
        self.calls: list[list[tuple[str, dict[str, Any]]]] = []

    @staticmethod
    def _key(url: str, request: dict[str, Any]) -> str:
        return json.dumps(
            [url, request],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def add(
        self,
        url: str,
        request: dict[str, Any],
        body: bytes,
        *,
        source_transport: str = "direct",
    ) -> None:
        digest = hashlib.sha256(body).hexdigest()
        receipt_sha = hashlib.sha256(
            self._key(url, request).encode() + body
        ).hexdigest()
        envelope = _Envelope(body=body, receipt_sha256=receipt_sha)
        self.entries[self._key(url, request)] = _Retained(
            envelope=envelope,
            receipt=SimpleNamespace(content=SimpleNamespace(sha256=digest)),
            transport_receipt={
                "content_sha256": digest,
                "official_url": url,
                "retrieved_at": OBSERVED_AT,
                "source_transport": source_transport,
            },
        )

    def refresh_existing_entries(self) -> None:
        return None

    def replay_retained_parser_inputs(
        self,
        *,
        requests: list[tuple[str, dict[str, Any]]],
    ) -> tuple[_Retained, ...]:
        normalized = [(url, dict(request)) for url, request in requests]
        self.calls.append(normalized)
        return tuple(self.entries[self._key(url, request)] for url, request in normalized)


def _retained_fixture(scraper: MississippiScraper) -> _Ledger:
    ledger = _Ledger()
    ledger.add(
        OFFICIAL_LEGISLATURE_ENTRY_URL,
        scraper._mississippi_get_request(OFFICIAL_LEGISLATURE_ENTRY_URL),
        (
            f"<html><a href='{PUBLIC_ENTRY_URL}'>Mississippi Code of 1972"
            "</a></html>"
        ).encode(),
    )
    ledger.add(
        PUBLIC_ENTRY_URL,
        scraper._mississippi_get_request(PUBLIC_ENTRY_URL),
        (
            "<html><a href='https://advance.lexis.com/container?config="
            f"{PUBLIC_CONTAINER_CONFIG}'>continue</a></html>"
        ).encode(),
    )
    root_payload = _root_html().encode()
    ledger.add(
        PUBLIC_CONTAINER_URL,
        canonical_rendered_root_request(),
        root_payload,
        source_transport="browser_rendered",
    )
    roots = parse_root_html(root_payload.decode())
    bound_roots = _bind_live_nodes(
        roots,
        source_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        receipt_sha256=hashlib.sha256(root_payload).hexdigest(),
    )
    assert len(bound_roots) == len(EXPECTED_ROOT_NODE_IDS)
    title_numbers = ("1", *EXPECTED_TITLE_NUMBERS)
    for position, (root, title_number) in enumerate(
        zip(bound_roots, title_numbers, strict=True)
    ):
        mapping = _document_mapping(position, root.node_id, title_number)
        response = json.dumps(
            {"collections": {"nodes": [mapping]}},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        endpoint, _request_body, patch_request = canonical_toc_patch_request(root)
        ledger.add(
            endpoint,
            patch_request,
            response,
            source_transport="browser_rendered",
        )
        node = node_from_mapping(mapping)
        assert node is not None
        bound = _bind_live_nodes(
            [node],
            source_url=PUBLIC_CONTAINER_URL,
            observed_at=OBSERVED_AT,
            receipt_sha256=hashlib.sha256(response).hexdigest(),
        )[0]
        section_number = bound.section_number
        assert section_number
        url = document_page_url(bound)
        body = (
            "<html><main data-document-content>"
            f"<h1>§ {section_number}. Synthetic section.</h1>"
            "<p>The retained operative public-law text.</p>"
            "</main></html>"
        ).encode()
        ledger.add(url, scraper._mississippi_get_request(url), body)
    return ledger


@pytest.mark.asyncio
async def test_get_seam_is_one_paced_plural_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    urls = [
        "https://advance.lexis.com/documentpage/?one=1",
        "https://advance.lexis.com/documentpage/?two=2",
    ]
    payloads = [
        b"<html><main data-document-content>one</main></html>",
        b"<html><main data-document-content>two</main></html>",
    ]
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(requested: list[str], **kwargs: Any) -> StateLawPageMultiFetchResult:
        calls.append((list(requested), dict(kwargs)))
        return StateLawPageMultiFetchResult(
            urls=list(requested),
            payloads=payloads,
            errors=[None, None],
            transport_receipts=[{}, {}],
            parser_input_envelopes=[None, None],
            stats={},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    batch = await scraper._fetch_mississippi_lexis_get_wave(
        urls,
        frontier_name="body",
        content_validator=valid_document_payload,
    )

    assert batch.urls == urls
    assert len(calls) == 1
    kwargs = calls[0][1]
    assert kwargs["max_concurrency"] == 1
    assert kwargs["direct_request_delay_seconds"] >= 0.05
    assert kwargs["prefer_direct"] is True
    assert kwargs["wayback_prefix_inventory"] is True


def test_retained_replay_closes_same_small_source_frontier_twice() -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    scraper.ENFORCE_OBSERVED_MS_FRONTIER = False
    ledger = _retained_fixture(scraper)
    scraper._state_law_acquisition_ledger = ledger

    rows = asyncio.run(
        scraper._scrape_strict_mississippi_retained_frontier(
            code_name="Mississippi Code"
        )
    )
    first = scraper._last_mississippi_full_frontier
    assert len(rows) == len(EXPECTED_ROOT_NODE_IDS)
    assert all(scraper._is_source_bound_operative_statute_record(row) for row in rows)
    assert first["frontier"]["closed"] is True
    assert first["frontier"]["ordered_request_wave_counts"] == [1, 1, 1, 51, 51]
    assert first["frontier"]["network_requested_pages"] == 0

    scraper._mississippi_retained_replay = True
    replay_rows = asyncio.run(
        scraper._scrape_strict_mississippi_retained_frontier(
            code_name="Mississippi Code"
        )
    )
    replay = scraper._last_mississippi_replayed_frontier
    assert [row.statute_id for row in replay_rows] == [row.statute_id for row in rows]
    assert replay["input_reports"] == first["input_reports"]
    assert replay["frontier"] == first["frontier"]
    assert [len(call) for call in ledger.calls] == [
        1,
        1,
        1,
        51,
        51,
        1,
        1,
        1,
        51,
        51,
    ]


def test_browser_callback_retains_exact_root_and_patch_identities() -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    calls: list[dict[str, Any]] = []

    class _CaptureLedger:
        retained_replay_only = False

        def retain_parser_input(self, **kwargs: Any) -> None:
            calls.append(dict(kwargs))

    scraper._state_law_acquisition_ledger = _CaptureLedger()
    root_payload = _root_html().encode()
    scraper._retain_mississippi_browser_input(
        official_url=PUBLIC_CONTAINER_URL,
        body=root_payload,
        sanitized_request=canonical_rendered_root_request(),
        response_status=200,
        media_type="text/html",
        observed_at=OBSERVED_AT,
    )
    root = parse_root_html(root_payload.decode())[0]
    endpoint, _request_body, patch_request = canonical_toc_patch_request(root)
    scraper._retain_mississippi_browser_input(
        official_url=endpoint,
        body=b'{"collections":{"nodes":[]}}',
        sanitized_request=patch_request,
        response_status=200,
        media_type="application/json",
        observed_at=OBSERVED_AT,
    )

    assert [call["sanitized_request"]["method"] for call in calls] == [
        "GET",
        "PATCH",
    ]
    assert calls[1]["sanitized_request"]["request_body_sha256"]
    assert all(
        call["transport_receipt"]["source_transport"] == "browser_rendered"
        for call in calls
    )


def test_live_coordinator_and_retained_parser_have_disjoint_io_boundaries() -> None:
    acquisition_source = inspect.getsource(
        MississippiScraper._acquire_mississippi_lexis_frontier
    )
    retained_source = inspect.getsource(
        MississippiScraper._scrape_strict_mississippi_retained_frontier
    )
    closure_source = inspect.getsource(
        MississippiScraper.produce_state_law_frontier_closure
    )

    assert "discover_live_inventory" in acquisition_source
    assert "retain_parser_input=self._retain_mississippi_browser_input" in (
        acquisition_source
    )
    assert "_fetch_mississippi_lexis_get_wave" in acquisition_source
    assert "grouped_body_acquisition_contract" in acquisition_source
    assert "_fetch_mississippi_lexis_get_wave" not in retained_source
    assert "discover_live_inventory" not in retained_source
    assert "canonical_toc_patch_request" in retained_source
    assert "_scrape_strict_mississippi_retained_frontier" in closure_source


def test_producer_identity_binds_state_and_shared_closure_dependencies() -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    labels = {
        getattr(item, "__name__", "")
        for item in scraper.state_law_frontier_source_dependencies()
    }
    assert any(label.endswith(".mississippi_lexis") for label in labels)
    assert any(label.endswith(".mississippi_section") for label in labels)
    assert any(label.endswith(".state_archival_fetch") for label in labels)
    assert any(label.endswith(".strict_frontier_closure") for label in labels)
    producer = scraper._state_law_frontier_source_software_version()
    assert producer.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi."
        "MississippiScraper@sha256:"
    )
    assert len(producer.rsplit(":", 1)[-1]) == 64
