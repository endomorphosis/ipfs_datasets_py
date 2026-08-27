from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland import (
    MarylandScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland_section import (
    parse_maryland_section_html,
    source_bound_maryland_terminal_disposition,
)


ARTICLE = {"DisplayText": "Education - (GEC)", "Value": "gec"}
SECTION_CODES = [f"10-{number}" for number in range(801, 811)]


def _catalog_url(article: dict[str, str] = ARTICLE) -> str:
    return (
        "https://mgaleg.maryland.gov/mgawebsite/api/Laws/GetSections"
        f"?articleCode={article['Value']}&enactments=false"
    )


def _catalog_payload(section_codes: list[str] = SECTION_CODES) -> bytes:
    return json.dumps(
        [
            {"DisplayText": section, "Value": section}
            for section in section_codes
        ]
    ).encode()


def _section_url(section: str) -> str:
    return (
        "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText"
        f"?article=GEC&section={section}&enactments=false"
    )


def _section_payload(section: str) -> bytes:
    body = (
        f"Official Maryland statutory text for section {section}. "
        "This retained provision supplies substantive public-law text. "
    ) * 4
    return (
        "<html><body><div id='StatuteText'>"
        f"<div>§ {section}. Education provision.</div><p>{body}</p>"
        "</div></body></html>"
    ).encode()


def _configure_frontier(
    monkeypatch: pytest.MonkeyPatch,
    scraper: MarylandScraper,
) -> list[dict[str, Any]]:
    checkpoints: list[dict[str, Any]] = []

    async def _articles() -> list[dict[str, str]]:
        return [dict(ARTICLE)]

    async def _sections(**_kwargs: Any) -> list[tuple[str, str]]:
        return [(section, section) for section in SECTION_CODES]

    async def _catalogs(
        urls,
        **_kwargs: Any,
    ) -> dict[str, object]:
        requested = list(urls)
        assert requested == [_catalog_url()]
        return {
            requested[0]: json.loads(_catalog_payload().decode()),
        }

    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("unbounded Maryland must not fetch section singletons")

    def _checkpoint(*_args: Any, **kwargs: Any) -> bool:
        checkpoints.append(dict(kwargs))
        return True

    monkeypatch.setattr(scraper, "_list_article_payload", _articles)
    monkeypatch.setattr(scraper, "_list_section_codes", _sections)
    monkeypatch.setattr(
        scraper,
        "_fetch_maryland_section_catalog_frontier",
        _catalogs,
    )
    monkeypatch.setattr(scraper, "_fetch_text_direct", _forbid_singleton)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)
    return checkpoints


@pytest.mark.anyio
async def test_maryland_unbounded_sections_use_one_evidence_bound_plural_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    checkpoints = _configure_frontier(monkeypatch, scraper)
    scraper._state_law_acquisition_ledger = object()
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        payloads = [_section_payload(section) for section in SECTION_CODES]
        receipts = [
            {
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            }
            for url, payload in zip(requested, payloads, strict=True)
        ]
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=receipts,
            parser_input_envelopes=[
                SimpleNamespace(body=payload) for payload in payloads
            ],
            stats={"requested_pages": len(requested)},
        )

    monkeypatch.setenv("STATE_SCRAPER_MD_SECTION_CONCURRENCY", "4")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    statutes = await scraper._scrape_api_sections(
        "Maryland Code",
        max_statutes=None,
    )

    expected_urls = [_section_url(section) for section in SECTION_CODES]
    assert calls == [
        (
            expected_urls,
            {
                "timeout_seconds": 35,
                "media_type": "text/html",
                "max_concurrency": 4,
                "prefer_direct": True,
                "common_crawl_domain_terms": ("mgaleg.maryland.gov",),
                "common_crawl_url_terms": ("/mgawebsite/Laws/StatuteText",),
                "common_crawl_mime_terms": ("html",),
                "wayback_prefix_inventory": True,
            },
        )
    ]
    assert [row.section_number for row in statutes] == SECTION_CODES
    assert [row.source_url for row in statutes] == expected_urls
    assert checkpoints[-1]["stage_label"] == "maryland:complete"
    assert checkpoints[-1]["extra"]["scanned_candidates"] == 10
    assert checkpoints[-1]["extra"]["discovered_candidates"] == 10


@pytest.mark.anyio
async def test_maryland_strict_getsections_uses_one_plural_catalog_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    articles = [
        dict(ARTICLE),
        {"DisplayText": "Estates and Trusts - (GET)", "Value": "get"},
    ]
    section_by_article = {"gec": "10-801", "get": "1-101"}
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _articles() -> list[dict[str, str]]:
        return list(articles)

    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("strict Maryland catalogs must not fetch singletons")

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        if all("/api/Laws/GetSections" in url for url in requested):
            payloads = [
                _catalog_payload([section_by_article[url.split("articleCode=", 1)[1].split("&", 1)[0]]])
                for url in requested
            ]
        else:
            payloads = [
                _section_payload(url.split("section=", 1)[1].split("&", 1)[0])
                for url in requested
            ]
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={"requested_pages": len(requested)},
        )

    monkeypatch.setattr(scraper, "_list_article_payload", _articles)
    monkeypatch.setattr(scraper, "_fetch_json", _forbid_singleton)
    monkeypatch.setattr(scraper, "_fetch_text_direct", _forbid_singleton)
    monkeypatch.setenv("STATE_SCRAPER_MD_SECTION_CONCURRENCY", "8")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)

    rows = await scraper._scrape_api_sections(
        "Maryland Code",
        max_statutes=None,
    )

    expected_catalogs = [_catalog_url(article) for article in articles]
    assert calls[0][0] == expected_catalogs
    assert calls[0][1]["media_type"] == "application/json"
    assert calls[0][1]["content_validator"](_catalog_payload(["1-101"])) is True
    assert sum(
        all("/api/Laws/GetSections" in url for url in requested)
        for requested, _kwargs in calls
    ) == 1
    expected_leaves = [
        _section_url("10-801"),
        (
            "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText"
            "?article=GET&section=1-101&enactments=false"
        ),
    ]
    assert calls[1][0] == expected_leaves
    assert calls[1][1]["wayback_prefix_inventory"] is True
    assert calls[1][1]["max_concurrency"] == 8
    assert len(calls) == 2
    assert [row.section_number for row in rows] == ["10-801", "1-101"]


def test_maryland_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "maryland_section",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland."
        "MarylandScraper@sha256:"
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
async def test_maryland_getsections_plural_retries_only_residual_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    urls = [
        _catalog_url(dict(ARTICLE)),
        _catalog_url({"DisplayText": "Estates - (GET)", "Value": "get"}),
    ]
    calls: list[list[str]] = []

    async def _plural(requested_urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append(requested)
        if len(calls) == 1:
            return StateLawPageMultiFetchResult(
                urls=requested,
                payloads=[_catalog_payload(["10-801"]), b""],
                errors=[None, "temporary miss"],
                transport_receipts=[None, None],
                parser_input_envelopes=[None, None],
                stats={},
            )
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[_catalog_payload(["1-101"])],
            errors=[None],
            transport_receipts=[None],
            parser_input_envelopes=[None],
            stats={},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    parsed = await scraper._fetch_maryland_section_catalog_frontier(
        urls,
        residual_retry_attempts=1,
    )

    assert calls == [urls, [urls[1]]]
    assert list(parsed) == urls


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("malformation", "expected"),
    [
        ("short", "unaligned acquisition rows"),
        ("reordered", "changed URL order or identity"),
        ("miss", "frontier is incomplete"),
    ],
)
async def test_maryland_getsections_plural_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
    expected: str,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    urls = [
        _catalog_url(dict(ARTICLE)),
        _catalog_url({"DisplayText": "Estates - (GET)", "Value": "get"}),
    ]

    async def _malformed(requested_urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        result = StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[
                _catalog_payload(["10-801"]),
                _catalog_payload(["1-101"]),
            ],
            errors=[None, None],
            transport_receipts=[None, None],
            parser_input_envelopes=[None, None],
            stats={},
        )
        if malformation == "short":
            result.parser_input_envelopes = [None]
        elif malformation == "reordered":
            result.urls = list(reversed(requested))
        else:
            result.payloads[1] = b""
            result.errors[1] = "archive miss"
        return result

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _malformed,
    )

    with pytest.raises(RuntimeError, match=expected):
        await scraper._fetch_maryland_section_catalog_frontier(
            urls,
            residual_retry_attempts=0,
        )


@pytest.mark.anyio
async def test_maryland_plural_batch_fails_closed_on_one_typed_miss_without_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    checkpoints = _configure_frontier(monkeypatch, scraper)

    async def _plural(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        payloads = [_section_payload(section) for section in SECTION_CODES]
        payloads[4] = b""
        errors: list[str | None] = [None] * len(requested)
        errors[4] = "TimeoutError: residual archival fallback exceeded its deadline"
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=errors,
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={"failed_pages": 1},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    with pytest.raises(RuntimeError, match="10-805.*residual archival fallback"):
        await scraper._scrape_api_sections(
            "Maryland Code",
            max_statutes=None,
        )

    assert checkpoints[-1]["stage_label"] == "maryland:unresolved-section"
    assert checkpoints[-1]["extra"]["scanned_candidates"] == 10
    assert checkpoints[-1]["extra"]["discovered_candidates"] == 10
    assert checkpoints[-1]["extra"]["unresolved_sections_count"] == 1


@pytest.mark.anyio
async def test_maryland_plural_batch_records_source_bound_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    checkpoints = _configure_frontier(monkeypatch, scraper)
    terminal_payload = (
        "<html><body><div id='StatuteText'>§10–801. Reserved.</div></body></html>"
    ).encode()

    async def _plural(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        payloads = [_section_payload(section) for section in SECTION_CODES]
        payloads[0] = terminal_payload
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    statutes = await scraper._scrape_api_sections(
        "Maryland Code",
        max_statutes=None,
    )

    assert [row.section_number for row in statutes] == SECTION_CODES[1:]
    complete = checkpoints[-1]
    assert complete["stage_label"] == "maryland:complete"
    assert complete["extra"]["terminal_sections_classified"] == 1
    assert complete["extra"]["terminal_disposition_counts"] == {"reserved": 1}
    assert complete["extra"]["terminal_section_dispositions"] == [
        {
            "article_code": "GEC",
            "content_sha256": hashlib.sha256(terminal_payload).hexdigest(),
            "disposition": "reserved",
            "section_number": "10-801",
            "source_url": _section_url("10-801"),
        }
    ]


@pytest.mark.anyio
async def test_maryland_unbounded_api_frontier_does_not_clip_at_two_thousand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    payload = [
        {"DisplayText": f"{number}-101", "Value": str(number)}
        for number in range(1, 2006)
    ]

    async def _json(_url: str) -> list[dict[str, str]]:
        return payload

    monkeypatch.setattr(scraper, "_fetch_json", _json)

    exact = await scraper._list_section_codes(
        article_value="gab",
        article_code="GAB",
        budget=None,
    )
    bounded = await scraper._list_section_codes(
        article_value="gab",
        article_code="GAB",
        budget=17,
    )

    assert len(exact) == 2005
    assert exact[-1] == ("2005-101", "2005-101")
    assert len(bounded) == 17


@pytest.mark.anyio
async def test_maryland_unbounded_empty_article_frontier_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    checkpoints: list[dict[str, Any]] = []

    async def _articles() -> list[dict[str, str]]:
        return [dict(ARTICLE)]

    async def _sections(**_kwargs: Any) -> list[tuple[str, str]]:
        return []

    async def _catalogs(urls, **_kwargs: Any) -> dict[str, object]:
        requested = list(urls)
        return {requested[0]: []}

    def _checkpoint(*_args: Any, **kwargs: Any) -> bool:
        checkpoints.append(dict(kwargs))
        return True

    monkeypatch.setattr(scraper, "_list_article_payload", _articles)
    monkeypatch.setattr(scraper, "_list_section_codes", _sections)
    monkeypatch.setattr(
        scraper,
        "_fetch_maryland_section_catalog_frontier",
        _catalogs,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)

    with pytest.raises(RuntimeError, match="article=GEC"):
        await scraper._scrape_api_sections("Maryland Code", max_statutes=None)

    assert checkpoints[-1]["stage_label"] == "maryland:empty-section-frontier"


@pytest.mark.parametrize(
    ("section", "body"),
    [
        ("2-110", "This part applies statewide."),
        ("3-321", "The common law crime of sodomy has been repealed."),
        ("7-315", "Milk is the State drink."),
    ],
)
def test_maryland_short_or_repeal_worded_operative_sections_are_retained(
    section: str,
    body: str,
) -> None:
    url = (
        "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText"
        f"?article=GAB&section={section}&enactments=false"
    )
    html = f"<div id='StatuteText'>§{section}.<br><br>{body}</div>"

    row = parse_maryland_section_html(
        html,
        source_url=url,
        expected_article_code="GAB",
    )

    assert row is not None
    assert row.section_number == section
    assert row.full_text == body
    assert row.structured_data["record_type"] == "maryland_api_section"


def test_maryland_decimal_identity_uses_the_complete_api_selected_section() -> None:
    url = _section_url("15-1628.2")
    body = "A pharmacy benefits manager shall provide an exact appeal process."
    html = f"<div id='StatuteText'>§15–1628.2<br><br>{body}</div>"

    row = parse_maryland_section_html(
        html,
        source_url=url,
        expected_article_code="GEC",
    )

    assert row is not None
    assert row.section_number == "15-1628.2"
    assert row.statute_id == "Maryland Code [GEC] § 15-1628.2"
    assert (
        parse_maryland_section_html(
            html,
            source_url=_section_url("15-1628"),
            expected_article_code="GEC",
        )
        is None
    )


@pytest.mark.parametrize(
    ("section", "content", "expected"),
    [
        ("21-1308", "§21–1308.", "heading_only"),
        ("23-1201", "§23–1201. Reserved.", "reserved"),
    ],
)
def test_maryland_terminal_dispositions_are_exact_and_source_bound(
    section: str,
    content: str,
    expected: str,
) -> None:
    url = _section_url(section)
    html = f"<div id='StatuteText'>{content}</div>"

    assert source_bound_maryland_terminal_disposition(
        html,
        source_url=url,
        expected_article_code="GEC",
    ) == expected
    assert source_bound_maryland_terminal_disposition(
        html,
        source_url=_section_url(f"{section}A"),
        expected_article_code="GEC",
    ) is None


def test_maryland_repeal_language_is_not_a_terminal_marker() -> None:
    section = "3-321"
    html = (
        "<div id='StatuteText'>§3–321.<br><br>"
        "The common law crime of sodomy has been repealed.</div>"
    )

    assert source_bound_maryland_terminal_disposition(
        html,
        source_url=_section_url(section),
        expected_article_code="GEC",
    ) is None


@pytest.mark.anyio
@pytest.mark.parametrize("malformation", ["reordered", "short-vector"])
async def test_maryland_plural_batch_fails_closed_on_alignment_drift(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    _configure_frontier(monkeypatch, scraper)

    async def _malformed(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        payloads = [_section_payload(section) for section in SECTION_CODES]
        if malformation == "reordered":
            returned_urls = list(reversed(requested))
            errors: list[str | None] = [None] * len(requested)
        else:
            returned_urls = requested
            errors = [None] * (len(requested) - 1)
        return StateLawPageMultiFetchResult(
            urls=returned_urls,
            payloads=payloads,
            errors=errors,
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _malformed,
    )

    expected = (
        "changed URL order or identity"
        if malformation == "reordered"
        else "unaligned acquisition rows"
    )
    with pytest.raises(RuntimeError, match=expected):
        await scraper._scrape_api_sections("Maryland Code", max_statutes=None)


@pytest.mark.anyio
async def test_maryland_strict_plural_batch_rejects_unbound_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MarylandScraper("MD", "Maryland")
    _configure_frontier(monkeypatch, scraper)
    scraper._state_law_acquisition_ledger = object()

    async def _plural(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        payloads = [_section_payload(section) for section in SECTION_CODES]
        receipts = [
            {
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            }
            for url, payload in zip(requested, payloads, strict=True)
        ]
        receipts[3] = {**receipts[3], "official_url": requested[2]}
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=receipts,
            parser_input_envelopes=[
                SimpleNamespace(body=payload) for payload in payloads
            ],
            stats={},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    with pytest.raises(RuntimeError, match="unbound transport receipt"):
        await scraper._scrape_api_sections("Maryland Code", max_statutes=None)
