"""Exact-frontier tests for Georgia's archived official statute bodies."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
    verify_state_law_transport_receipt,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import (
    GeorgiaFullCorpusIncompleteError,
    GeorgiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archive import (
    official_section_url,
    parse_georgia_archive_html,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archived_official import (
    INVENTORY_SCHEMA,
    INVENTORY_SOURCE_KIND,
    MANIFEST_ENV,
    GeorgiaArchivedOfficialCorpusError,
    _heading_active_on,
    _heading_expected_disposition,
    acquire_georgia_archived_official_corpus,
    acquire_georgia_archived_official_with_shared_transport,
    build_georgia_delegated_inventory,
    load_georgia_archived_official_corpus,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_lexis import (
    ADVANCE_ORIGIN,
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    GeorgiaLexisDiscoveryResult,
    _bind_live_toc_nodes,
    _mark_live_expansion_closed,
    parse_toc_dom_rows,
    parse_toc_payload,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_title import (
    parse_georgia_title_text,
)


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_registered_source_bundle_binds_exact_delegated_inventory_parser() -> None:
    scraper = GeorgiaScraper("GA", "Georgia")
    dependency_names = {
        str(getattr(module, "__name__", ""))
        for module in scraper.state_law_frontier_source_dependencies()
    }

    assert (
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_lexis"
        in dependency_names
    )


def _inventory() -> dict[str, object]:
    sections = []
    expansions = []
    for title in range(1, 54):
        section = f"{title}-1-1"
        node_id = f"S{title:02d}"
        expansion_id = f"T{title:02d}"
        expansions.append(expansion_id)
        sections.append(
            {
                "document_url": (
                    f"{ADVANCE_ORIGIN}/shared/document/statutes-legislation/"
                    f"urn:contentItem:GA{title:02d}-TEST-BODY-00000-00"
                ),
                "evidence_sha256": f"{title:064x}",
                "evidence_verified": True,
                "expected_disposition": "admit",
                "heading": f"{section}. Test provision for Title {title}.",
                "node_id": node_id,
                "node_path": f"/ROOT/{expansion_id}/{node_id}",
                "section_number": section,
                "source_authority_class": "official",
            }
        )
    locator_rows = [
        {"section_number": row["section_number"], "document_url": row["document_url"]}
        for row in sections
    ]
    frontier = {
        "closed": True,
        "discovered_section_count": len(sections),
        "expanded_node_ids": expansions,
        "expected_title_count": 53,
        "failed_final": 0,
        "frontier_closed": True,
        "required_expandable_node_ids": expansions,
        "section_locator_digest_sha256": _digest(locator_rows),
        "section_locator_frontier_closed": True,
        "sections": sections,
        "title_inventory_closed": True,
        "title_numbers": [str(number) for number in range(1, 54)],
        "toc_exhausted": True,
        "unresolved_expandable_node_ids": [],
        "unvisited_continuation_links": [],
    }
    frontier["frontier_digest_sha256"] = _digest(frontier)
    return {
        "container_url": PUBLIC_CONTAINER_URL,
        "delegation_verified": True,
        "edition_as_of": "2024-01-01",
        "edition_identifier": "ocga-2024-01-01",
        "entry_url": PUBLIC_ENTRY_URL,
        "frontier": frontier,
        "jurisdiction": "GA",
        "observed_at": "2026-08-24T00:00:00+00:00",
        "official_source": True,
        "patch_response_sha256": {
            expansion: f"{title:064x}"
            for title, expansion in enumerate(expansions, start=1)
        },
        "root_rendered_sha256": "a" * 64,
        "schema": INVENTORY_SCHEMA,
        "source_authority_class": "official",
        "source_kind": INVENTORY_SOURCE_KIND,
        "verification_result": "verified",
    }


def _exhaustive_live_discovery() -> GeorgiaLexisDiscoveryResult:
    observed_at = "2026-08-24T00:00:00+00:00"
    root_rows = [
        {
            "nodeid": f"T{title:02d}",
            "title": f"TITLE {title} Fixture title",
            "level": "1",
            "nodepath": f"/ROOT/T{title:02d}",
            "haschildren": "true",
        }
        for title in range(1, 54)
    ]
    roots = _bind_live_toc_nodes(
        parse_toc_dom_rows(root_rows),
        source_url=PUBLIC_CONTAINER_URL,
        observed_at=observed_at,
        receipt_sha256="a" * 64,
    )
    nodes = []
    expanded = []
    patch_hashes = []
    for title, root in enumerate(roots, start=1):
        receipt_sha256 = f"{title:064x}"
        chapter_id = f"C{title:02d}"
        section_id = f"S{title:02d}"
        section = f"{title}-1-1"
        raw_nodes = parse_toc_payload(
            {
                "collections": {
                    "tocnodes": [
                        {
                            "id": chapter_id,
                            "props": {
                                "linktemplatetitle": "CHAPTER 1 Fixture chapter",
                                "level": 2,
                                "nodepath": f"{root.node_path}/{chapter_id}",
                                "canexpand": True,
                                "haschildren": True,
                            },
                            "data": {},
                        },
                        {
                            "id": section_id,
                            "props": {
                                "linktemplatetitle": f"{section}. Fixture statute.",
                                "level": 3,
                                "nodepath": (
                                    f"{root.node_path}/{chapter_id}/{section_id}"
                                ),
                                "canopen": True,
                                "haschildren": False,
                                "linkhref": (
                                    "/shared/document/statutes-legislation/"
                                    f"urn:contentItem:GA{title:02d}-TEST-BODY-00000-00"
                                ),
                                "subscribed": True,
                                "tocpricing": {
                                    "currencycode": "USD",
                                    "listprice": 0,
                                    "netprice": 0,
                                    "purchaserequired": False,
                                    "usagetypecode": "subscription",
                                    "documentstatus": "Available",
                                },
                            },
                            "data": {},
                        },
                    ]
                }
            }
        )
        bound = _bind_live_toc_nodes(
            raw_nodes,
            source_url=PUBLIC_CONTAINER_URL,
            observed_at=observed_at,
            receipt_sha256=receipt_sha256,
        )
        closed_root = _mark_live_expansion_closed(root)
        closed_chapter = _mark_live_expansion_closed(bound[0])
        assert closed_root is not None
        assert closed_chapter is not None
        nodes.extend([closed_root, closed_chapter, bound[1]])
        expanded.extend([root.node_id, chapter_id])
        patch_hashes.extend(
            [
                (root.node_id, receipt_sha256),
                (chapter_id, receipt_sha256),
            ]
        )
    return GeorgiaLexisDiscoveryResult(
        status="official_toc",
        final_url=PUBLIC_CONTAINER_URL,
        delegation_verified=True,
        nodes=tuple(nodes),
        expanded_node_ids=tuple(expanded),
        diagnostics=(),
        observed_at=observed_at,
        root_rendered_sha256="a" * 64,
        patch_response_sha256=tuple(patch_hashes),
    )


def test_exhaustive_live_toc_builds_exact_delegated_section_inventory() -> None:
    inventory = build_georgia_delegated_inventory(
        _exhaustive_live_discovery(),
        edition_as_of="2024-01-01",
        edition_identifier="ocga-2024-01-01",
    )

    assert inventory["schema"] == INVENTORY_SCHEMA
    assert inventory["frontier"]["closed"] is True
    assert inventory["frontier"]["discovered_section_count"] == 53
    assert inventory["frontier"]["title_numbers"] == [
        str(title) for title in range(1, 54)
    ]
    assert len(inventory["patch_response_sha256"]) == 106
    assert inventory["frontier"]["sections"][0]["section_number"] == "1-1-1"
    assert inventory["frontier"]["sections"][-1]["section_number"] == "53-1-1"


def test_effective_date_headings_select_only_the_version_in_force() -> None:
    as_of = date(2026, 8, 24)

    assert _heading_active_on(
        "25-4-8. [Effective until July 1, 2027] Qualifications.",
        as_of=as_of,
    )
    assert not _heading_active_on(
        "25-4-8. [Effective July 1, 2027] Qualifications.",
        as_of=as_of,
    )
    assert _heading_expected_disposition(
        "34-8-180. [Repealed effective January 1, 2027] Assessment.",
        as_of=as_of,
    ) == "admit"
    assert _heading_expected_disposition(
        "21-2-140. [Repealed] Mandatory drug testing.",
        as_of=as_of,
    ) == "exclude_nonoperative"


def _html(section: str, *, long_body: bool = False) -> bytes:
    body = (
        ("The enacted text of this Georgia statute remains complete. " * 360)
        if long_body
        else ("The enacted text of this Georgia statute controls the legal rule. " * 4)
    )
    return (
        "<html><body><main>"
        f"<h1>{section}. Test provision.</h1>"
        f"<p>{body}</p>"
        "<h2>Editor's Notes</h2>"
        "<p>Publisher editorial discussion must never enter the statute body.</p>"
        "<h2>Judicial Decisions</h2><p>Commercial annotation.</p>"
        "</main></body></html>"
    ).encode()


class _ArchiveClient:
    def __init__(self, *, fail_section: str = "") -> None:
        self.fail_section = fail_section
        self.requested: list[str] = []

    async def fetch_with_fallback(self, url: str) -> SimpleNamespace:
        self.requested.append(url)
        section = url.rstrip("/").rsplit("section-", 1)[-1]
        if section == self.fail_section:
            raise RuntimeError("bounded fixture miss")
        return SimpleNamespace(
            archive_timestamp="20240102030405",
            archive_url=f"https://web.archive.org/web/20240102030405id_/{url}",
            content=_html(section, long_body=section == "1-1-1"),
            fetched_at="2026-08-24T01:02:03+00:00",
            source="wayback",
            url=url,
        )


class _BatchArchiveClient:
    def __init__(self) -> None:
        self.requests: list[tuple[list[str], dict[str, object]]] = []

    async def fetch_many_with_fallback(
        self,
        urls: list[str],
        **kwargs: object,
    ) -> SimpleNamespace:
        requested = list(urls)
        self.requests.append((requested, dict(kwargs)))
        results = []
        for index, url in enumerate(requested):
            section = url.rstrip("/").rsplit("section-", 1)[-1]
            payload = _html(section, long_body=section == "1-1-1")
            results.append(
                SimpleNamespace(
                    archive_timestamp="20240102030405",
                    archive_url=(
                        "https://data.commoncrawl.org/crawl-data/CC-MAIN-2024-10/"
                        "segments/fixture/warc/shared.warc.gz"
                    ),
                    common_crawl_collection="CC-MAIN-2024-10",
                    common_crawl_indexed_url=url,
                    common_crawl_warc_filename=(
                        "crawl-data/CC-MAIN-2024-10/segments/fixture/warc/"
                        "shared.warc.gz"
                    ),
                    common_crawl_warc_length=len(payload),
                    common_crawl_warc_offset=1_000 + index * 10_000,
                    content=payload,
                    content_sha256=hashlib.sha256(payload).hexdigest(),
                    fetched_at="2026-08-24T01:02:03+00:00",
                    source="common_crawl",
                    status_code=200,
                    url=url,
                )
            )
        return SimpleNamespace(
            errors=[None] * len(requested),
            results=results,
            stats={
                "requested_pages": len(requested),
                "unique_pages": len(requested),
                "domains": 1,
                "common_crawl": {
                    "warc_objects": 1,
                    "range_fetch_calls": 1,
                    "naive_range_fetches": len(requested),
                    "range_fetches_avoided": len(requested) - 1,
                },
            },
        )


class _MisalignedBatchArchiveClient(_BatchArchiveClient):
    async def fetch_many_with_fallback(
        self,
        urls: list[str],
        **kwargs: object,
    ) -> SimpleNamespace:
        batch = await super().fetch_many_with_fallback(urls, **kwargs)
        batch.results[0].url = official_section_url("53-99-99")
        return batch


class _SharedPageBatchFetcher:
    def __init__(self) -> None:
        self.requests: list[tuple[list[str], dict[str, object]]] = []

    async def __call__(
        self,
        urls: list[str],
        **kwargs: object,
    ) -> SimpleNamespace:
        requested = list(urls)
        self.requests.append((requested, dict(kwargs)))
        payloads = [
            _html(
                url.rstrip("/").rsplit("section-", 1)[-1],
                long_body=url.endswith("section-1-1-1"),
            )
            for url in requested
        ]
        receipts = [
            {
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            }
            for url, payload in zip(requested, payloads, strict=True)
        ]
        envelope = SimpleNamespace(
            acquisition=SimpleNamespace(
                receipt=SimpleNamespace(retrieved_at="2026-08-24T01:02:03+00:00")
            )
        )
        return SimpleNamespace(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=receipts,
            parser_input_envelopes=[envelope] * len(requested),
            stats={
                "requested_pages": len(requested),
                "unique_pages": len(requested),
                "common_crawl_inventory_queries": 1,
                "common_crawl": {
                    "warc_objects": 1,
                    "range_fetch_calls": 1,
                    "range_fetches_avoided": len(requested) - 1,
                },
            },
        )


async def _acquire(tmp_path: Path, *, fail_section: str = "") -> tuple[dict, _ArchiveClient]:
    client = _ArchiveClient(fail_section=fail_section)
    result = await acquire_georgia_archived_official_corpus(
        _inventory(),
        tmp_path / "ga",
        fetch_client=client,
        require_batched_transport=False,
    )
    return result, client


@pytest.mark.anyio
async def test_acquisition_batches_whole_frontier_and_retains_warc_savings(
    tmp_path: Path,
) -> None:
    client = _BatchArchiveClient()
    pointers = [(official_section_url("1-1-1"), {"filename": "fixture"})]

    result = await acquire_georgia_archived_official_corpus(
        _inventory(),
        tmp_path / "ga-batch",
        fetch_client=client,
        common_crawl_records=pointers,
        common_crawl_engine=object(),
        max_concurrency=3,
    )

    assert result["closed"] is True
    assert len(client.requests) == 1
    urls, kwargs = client.requests[0]
    assert len(urls) == 53
    assert len({url.split("/", 3)[2] for url in urls}) == 1
    assert kwargs["common_crawl_records"] == pointers
    assert kwargs["common_crawl_record_loader"] is None
    assert kwargs["max_concurrency"] == 3
    assert kwargs["prefer_direct"] is False
    assert result["manifest"]["transport_batch"]["common_crawl"] == {
        "warc_objects": 1,
        "range_fetch_calls": 1,
        "naive_range_fetches": 53,
        "range_fetches_avoided": 52,
    }
    first = result["manifest"]["artifacts"][0]
    assert first["common_crawl_warc_filename"].endswith("shared.warc.gz")
    assert first["common_crawl_warc_offset"] == 1_000


@pytest.mark.anyio
async def test_acquisition_reuses_restart_safe_shared_page_batch_seam(
    tmp_path: Path,
) -> None:
    page_fetcher = _SharedPageBatchFetcher()

    result = await acquire_georgia_archived_official_corpus(
        _inventory(),
        tmp_path / "ga-shared-page-batch",
        page_batch_fetcher=page_fetcher,
        max_concurrency=5,
    )

    assert result["closed"] is True
    assert len(page_fetcher.requests) == 1
    urls, kwargs = page_fetcher.requests[0]
    assert len(urls) == 53
    assert kwargs["max_concurrency"] == 5
    assert kwargs["prefer_direct"] is False
    assert kwargs["common_crawl_domain_terms"] == (
        "www.legis.ga.gov",
        "legis.ga.gov",
    )
    assert kwargs["common_crawl_url_terms"] == (
        "/legislation/georgia-code/",
    )
    assert kwargs["common_crawl_mime_terms"] == ("html",)
    assert kwargs["wayback_prefix_inventory"] is True
    assert callable(kwargs["content_validator"])
    assert result["manifest"]["transport_batch"]["common_crawl_inventory_queries"] == 1
    assert result["manifest"]["transport_batch"]["common_crawl"][
        "range_fetch_calls"
    ] == 1
    assert all(
        row["source_transport"] == "direct"
        for row in result["manifest"]["artifacts"]
    )


@pytest.mark.anyio
async def test_shared_transport_wrapper_attaches_prospective_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    page_fetcher = _SharedPageBatchFetcher()

    async def _shared_batch(self: GeorgiaScraper, urls: list[str], **kwargs: object):
        ledger = self._state_law_acquisition_ledger
        observed["jurisdiction"] = ledger.jurisdiction
        observed["parser_name"] = ledger.parser_name
        observed["ledger_root"] = ledger.root
        return await page_fetcher(urls, **kwargs)

    monkeypatch.setattr(
        GeorgiaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _shared_batch,
    )
    evidence_root = tmp_path / "evidence"
    result = await acquire_georgia_archived_official_with_shared_transport(
        _inventory(),
        tmp_path / "ga-shared-wrapper",
        acquisition_evidence_root=evidence_root,
        max_concurrency=4,
    )

    assert result["closed"] is True
    assert observed == {
        "jurisdiction": "GA",
        "parser_name": "GeorgiaScraper",
        "ledger_root": evidence_root.resolve(),
    }
    assert result["acquisition_evidence_root"] == str(
        (evidence_root / "GA").resolve()
    )
    assert result["retained_parser_inputs"] == 0


@pytest.mark.anyio
async def test_acquisition_loads_archive_inventory_once_for_the_whole_frontier(
    tmp_path: Path,
) -> None:
    client = _BatchArchiveClient()
    loader_calls: list[list[str]] = []

    async def _record_loader(urls: list[str]) -> list[tuple[str, dict[str, object]]]:
        requested = list(urls)
        loader_calls.append(requested)
        return [(url, {"filename": "fixture"}) for url in requested]

    original_batch = client.fetch_many_with_fallback

    async def _batch_with_loader(urls: list[str], **kwargs: object) -> SimpleNamespace:
        loader = kwargs["common_crawl_record_loader"]
        assert callable(loader)
        await loader(list(urls))
        return await original_batch(urls, **kwargs)

    client.fetch_many_with_fallback = _batch_with_loader  # type: ignore[method-assign]
    result = await acquire_georgia_archived_official_corpus(
        _inventory(),
        tmp_path / "ga-loader-batch",
        fetch_client=client,
        common_crawl_record_loader=_record_loader,
        common_crawl_engine=object(),
    )

    assert result["closed"] is True
    assert len(loader_calls) == 1
    assert loader_calls[0] == [
        official_section_url(f"{title}-1-1") for title in range(1, 54)
    ]


@pytest.mark.anyio
async def test_acquisition_refuses_legacy_per_page_transport_by_default(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        GeorgiaArchivedOfficialCorpusError,
        match="shared archival multi-fetch transport",
    ):
        await acquire_georgia_archived_official_corpus(
            _inventory(),
            tmp_path / "ga-no-per-page",
            fetch_client=_ArchiveClient(),
        )


@pytest.mark.anyio
async def test_acquisition_rejects_a_batch_response_in_the_wrong_locator_slot(
    tmp_path: Path,
) -> None:
    result = await acquire_georgia_archived_official_corpus(
        _inventory(),
        tmp_path / "ga-misaligned-batch",
        fetch_client=_MisalignedBatchArchiveClient(),
    )

    assert result["closed"] is False
    first = result["manifest"]["artifacts"][0]
    assert first["status"] == "failed"
    assert "did not match its official locator" in first["error"]


@pytest.mark.anyio
async def test_closed_manifest_reconciles_exact_53_title_body_frontier(
    tmp_path: Path,
) -> None:
    result, client = await _acquire(tmp_path)

    assert result["closed"] is True
    assert len(client.requested) == 53
    assert result["manifest"]["transport_batch"]["requested_pages"] == 53
    assert result["manifest"]["transport_batch"]["fallback_requests"] == 53
    assert result["manifest"]["transport_batch"]["legacy_per_page_fallback"] is True
    assert all(url.startswith("https://www.legis.ga.gov/") for url in client.requested)
    assert all("lexis" not in url.lower() and "justia" not in url.lower() for url in client.requested)

    corpus = load_georgia_archived_official_corpus(result["manifest_path"])
    assert len(corpus.statutes) == 53
    assert {row.title_number for row in corpus.statutes} == {
        str(number) for number in range(1, 54)
    }
    assert {
        key: value
        for key, value in corpus.receipt["frontier"].items()
        if key != "frontier_digest_sha256"
    } == {
        "closed": True,
        "discovered": 53,
        "duplicates": 0,
        "excluded": 0,
        "failed_final": 0,
        "fetched": 53,
        "frontier_closed": True,
        "quarantined": 0,
        "section_numbers_sha256": _digest(
            sorted(f"{number}-1-1" for number in range(1, 54))
        ),
    }
    first = next(row for row in corpus.statutes if row.section_number == "1-1-1")
    assert len(first.full_text) > 14_000
    assert "Publisher editorial discussion" not in first.full_text
    assert "Commercial annotation" not in first.full_text
    assert first.structured_data["full_corpus_admissible"] is True
    assert first.structured_data["statutory_text_only"] is True
    assert first.structured_data["source_authority_class"] == "official"
    assert first.structured_data["fetch_transport"] == "wayback"
    assert len(first.structured_data["body_sha256"]) == 64
    assert len(first.structured_data["manifest_sha256"]) == 64
    normalized_receipt = first.structured_data["transport_receipt"]
    verified_transport = verify_state_law_transport_receipt(
        normalized_receipt,
        official_url=first.source_url,
        content_sha256=first.structured_data["body_sha256"],
    )
    assert verified_transport.leaf_transport == "wayback"
    assert normalized_receipt["official_url"] == first.source_url
    assert first.structured_data["archive_source_url"] == verified_transport.archive_url


@pytest.mark.anyio
async def test_full_scraper_admits_only_verified_archived_official_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _client = await _acquire(tmp_path)
    monkeypatch.setenv(MANIFEST_ENV, result["manifest_path"])
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    for name in (
        "GEORGIA_TITLE_TEXT",
        "GEORGIA_TITLE_TEXT_DIR",
        "GEORGIA_TITLE_PDF",
        "GEORGIA_TITLE_PDF_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    scraper = GeorgiaScraper("GA", "Georgia")
    rows = await scraper.scrape_code(
        "Official Code of Georgia Annotated",
        "https://www.legis.ga.gov/legislation/georgia-code",
        max_statutes=None,
    )

    assert len(rows) == 53
    assert scraper._last_full_corpus_frontier["closed"] is True
    assert scraper._last_full_corpus_frontier["acquisition_method"] == (
        "hash_bound_archived_official"
    )

    fetch = scraper.fetch_official("GA")
    assert fetch.transport_kind == "archived_https"
    assert fetch.frontier["closed"] is True
    assert fetch.frontier["bundle_closed"] is True
    assert fetch.frontier["expected_index_units"] == 53
    assert len(fetch.rows) == 53
    assert all(str(row["canonical_key"]).startswith("ga:section-") for row in fetch.rows)
    assert all(len(str(row["full_text"])) > 40 for row in fetch.rows)
    assert all("official clean statutory catalog unit" not in str(row["full_text"]) for row in fetch.rows)
    assert all(
        isinstance((row.get("structured_data") or {}).get("transport_receipt"), dict)
        for row in fetch.rows
    )

    from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
        verify_receipt_frontier,
    )
    from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
        build_receipt_from_artifacts,
        load_rows,
        write_retained_artifacts,
    )

    evidence_root = tmp_path / "retained"
    checkpoint = write_retained_artifacts(evidence_root, fetch, uncapped=True)
    retained_rows = load_rows(evidence_root, "GA")
    receipt = build_receipt_from_artifacts(evidence_root, "GA")
    assert checkpoint.row_count == 53
    assert len(retained_rows) == 53
    assert all(str(row["canonical_key"]).startswith("ga:section-") for row in retained_rows)
    assert receipt["transport"]["kind"] == "archived_https"
    assert receipt["edition"] == fetch.edition
    assert receipt["legal_as_of"] == fetch.legal_as_of
    assert receipt["observed_at"] == fetch.observed_at
    assert verify_receipt_frontier(receipt).ok is True


@pytest.mark.anyio
async def test_georgia_closure_replays_hash_bound_manifest_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _client = await _acquire(tmp_path / "acquired")
    monkeypatch.setenv(MANIFEST_ENV, result["manifest_path"])
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    scraper = GeorgiaScraper("GA", "Georgia")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "release-evidence",
        jurisdiction="GA",
        parser_name="GeorgiaScraper",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    rows = await scraper.scrape_code(
        "Official Code of Georgia Annotated",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="GA",
    )

    async def _forbid_network(*_args, **_kwargs):
        raise AssertionError("Georgia retained closure must not fetch the network")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _forbid_network,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["official-georgia-code"],
    )
    closure_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    receipt = closure["completion_receipt"]

    assert len(rows) == len(ledger.entries) == 53
    assert ledger.audit_parser_output_coverage(
        [row.to_dict() for row in rows]
    )["complete"] is True
    assert receipt["disposition"] == {
        "discovered": 53,
        "duplicates": 0,
        "excluded": 0,
        "failed_final": 0,
        "fetched": 53,
        "quarantined": 0,
    }
    assert receipt["rights"]["basis"] == "public_law_no_state_copyright"
    assert receipt["transport"]["retained_replay_network_requests"] == 0
    assert receipt["frontier"] == closure["replayed_frontier"]


def test_fetch_official_never_admits_title_catalog_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(MANIFEST_ENV, raising=False)

    with pytest.raises(GeorgiaFullCorpusIncompleteError) as exc_info:
        GeorgiaScraper("GA", "Georgia").fetch_official("GA")

    assert exc_info.value.evidence["title_catalog_body_admissible"] is False
    assert exc_info.value.evidence["full_corpus_admissible"] is False


@pytest.mark.anyio
async def test_incomplete_archival_run_emits_open_receipt_and_cannot_admit(
    tmp_path: Path,
) -> None:
    result, _client = await _acquire(tmp_path, fail_section="53-1-1")

    assert result["closed"] is False
    assert result["frontier"]["failed_final"] == 1
    assert result["frontier"]["fetched"] == 52
    with pytest.raises(GeorgiaArchivedOfficialCorpusError, match="frontier is not closed"):
        load_georgia_archived_official_corpus(result["manifest_path"])


@pytest.mark.anyio
async def test_full_scraper_reports_invalid_manifest_as_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _client = await _acquire(tmp_path, fail_section="53-1-1")
    monkeypatch.setenv(MANIFEST_ENV, result["manifest_path"])
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    with pytest.raises(GeorgiaFullCorpusIncompleteError) as exc_info:
        await GeorgiaScraper("GA", "Georgia").scrape_code(
            "Official Code of Georgia Annotated",
            "https://www.legis.ga.gov/legislation/georgia-code",
            max_statutes=None,
        )

    assert exc_info.value.evidence["full_corpus_admissible"] is False
    assert "frontier is not closed" in exc_info.value.evidence["archived_official_reason"]


@pytest.mark.anyio
async def test_tampered_body_bytes_fail_the_manifest_hash_binding(tmp_path: Path) -> None:
    result, _client = await _acquire(tmp_path)
    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_path = manifest_path.parent / manifest["artifacts"][0]["path"]
    artifact_path.write_bytes(artifact_path.read_bytes() + b"tampered")

    with pytest.raises(GeorgiaArchivedOfficialCorpusError, match="body SHA-256 mismatch"):
        load_georgia_archived_official_corpus(manifest_path)


@pytest.mark.anyio
async def test_manifest_rejects_secondary_or_unbound_body_source(tmp_path: Path) -> None:
    result, _client = await _acquire(tmp_path)
    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["official_url"] = (
        "https://law.justia.com/codes/georgia/title-1/chapter-1/section-1-1-1/"
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(GeorgiaArchivedOfficialCorpusError, match="exact official locator"):
        load_georgia_archived_official_corpus(manifest_path)


@pytest.mark.anyio
async def test_durable_cache_requires_original_transport_receipt(tmp_path: Path) -> None:
    result, _client = await _acquire(tmp_path)
    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = manifest["artifacts"][0]
    origin = deepcopy(artifact)
    origin["content_sha256"] = artifact["sha256"]
    artifact["source_transport"] = "durable_cache"
    artifact["origin_transport_receipt"] = origin
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    corpus = load_georgia_archived_official_corpus(manifest_path)
    assert len(corpus.statutes) == 53
    cached_row = next(row for row in corpus.statutes if row.section_number == "1-1-1")
    cached_transport = verify_state_law_transport_receipt(
        cached_row.structured_data["transport_receipt"]
    )
    assert cached_transport.transport_chain == ("durable_cache", "wayback")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["artifacts"][0]["origin_transport_receipt"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(GeorgiaArchivedOfficialCorpusError, match="original transport receipt"):
        load_georgia_archived_official_corpus(manifest_path)


@pytest.mark.anyio
async def test_delegated_inventory_refuses_justia_locator(tmp_path: Path) -> None:
    inventory = _inventory()
    inventory["frontier"]["sections"][0]["document_url"] = (
        "https://law.justia.com/codes/georgia/title-1/chapter-1/section-1-1-1/"
    )
    inventory["frontier"]["section_locator_digest_sha256"] = _digest(
        [
            {
                "section_number": row["section_number"],
                "document_url": row["document_url"],
            }
            for row in inventory["frontier"]["sections"]
        ]
    )
    inventory["frontier"].pop("frontier_digest_sha256")
    inventory["frontier"]["frontier_digest_sha256"] = _digest(inventory["frontier"])
    with pytest.raises(GeorgiaArchivedOfficialCorpusError, match="delegated Lexis"):
        # Validation happens before the output directory or transport is used.
        await acquire_georgia_archived_official_corpus(
            inventory,
            tmp_path / "never-created",
            fetch_client=_ArchiveClient(),
        )


def test_statutory_parsers_do_not_truncate_and_strip_editorial_material() -> None:
    body = "This is enacted statutory text. " * 700
    text = (
        f"16-1-1. Short title.\n{body}\n"
        "History\nGa. L. editorial compilation material that is not enacted text."
    )

    title_rows = parse_georgia_title_text(text)
    archive_rows = parse_georgia_archive_html(f"<html><main>{text}</main></html>")

    assert len(title_rows) == len(archive_rows) == 1
    assert len(title_rows[0].full_text) > 14_000
    assert len(archive_rows[0].full_text) > 14_000
    assert "editorial compilation" not in title_rows[0].full_text
    assert "editorial compilation" not in archive_rows[0].full_text
    assert title_rows[0].structured_data["source_authority_class"] == "unverified"
    assert title_rows[0].structured_data["full_corpus_admissible"] is False


@pytest.mark.anyio
async def test_legacy_section_parser_refuses_an_unrelated_archived_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = GeorgiaScraper("GA", "Georgia")

    async def _wrong_html(_url: str, timeout_seconds: int = 18) -> str:
        return (
            "<html><main><h1>1-1-1. Unrelated provision.</h1><p>"
            + ("This is an unrelated archived Georgia section. " * 5)
            + "</p></main></html>"
        )

    monkeypatch.setattr(scraper, "_fetch_official_ga_html", _wrong_html)
    row = await scraper._parse_section_page(
        code_name="Official Code of Georgia Annotated",
        section_url=official_section_url("16-1-1"),
        section_label="16-1-1",
        title_label="Title 16",
        chapter_label="Chapter 1",
    )
    assert row is None


def test_unattributed_durable_cache_is_recovery_not_live_official() -> None:
    scraper = GeorgiaScraper("GA", "Georgia")
    for provider in ("fetch_cache", "ipfs_page_cache", "durable_cache", "unified_api"):
        authority, kind = scraper._classify_html_transport(provider)
        assert authority == "recovery"
        assert kind == "official_georgia_code_html_via_archive"


def test_official_section_locator_is_exact_for_each_inventory_section() -> None:
    for title in range(1, 54):
        section = f"{title}-1-1"
        assert official_section_url(section) == (
            "https://www.legis.ga.gov/legislation/georgia-code/"
            f"title-{title}/chapter-1/section-{section}"
        )
