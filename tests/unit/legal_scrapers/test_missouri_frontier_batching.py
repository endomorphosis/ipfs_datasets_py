from __future__ import annotations

import hashlib
import inspect
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawRetainedReplayOnlyError,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri import (
    MissouriScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri_chapter import (
    authoritative_chapter_section_variants,
    chapter_page_identity,
    chapter_section_variants,
    chapter_sections,
    section_body_identity,
    section_page_identity,
    source_bound_empty_chapter_disposition,
    statute_from_section_html,
)


def _receipt_sha256(url: str, content_sha256: str, retrieved_at: str) -> str:
    return hashlib.sha256(
        f"{url}\n{content_sha256}\n{retrieved_at}".encode()
    ).hexdigest()


def _chapter_html(
    chapter: str,
    sections: list[str],
    *,
    chapter_title: str | None = None,
    footer_section: str | None = "3.090",
) -> bytes:
    title = chapter_title or f"Official title for Chapter {chapter}"
    rows = "".join(
        "<tr>"
        "<td><a href='/main/PageSelect.aspx?section="
        f"{section}&amp;bid={index + 100}&amp;hl='>{section}</a></td>"
        f"<td>Official title for {section} (8/28/2025)</td>"
        "</tr>"
        for index, section in enumerate(sections)
    )
    footer = ""
    if footer_section is not None:
        footer = (
            "<div id='BOTTOM'><table><tr><td>"
            "<a href='https://revisor.mo.gov/main/OneSection.aspx?section="
            f"{footer_section}'>{footer_section}</a>"
            "</td></tr></table></div>"
        )
    return (
        "<html><head><title>Missouri Revisor of Statutes - Revised Statutes "
        f"of Missouri, RSMo Chapter {chapter}</title></head><body>"
        f"<div class='lr-font-norm'>Chapter {chapter} {title}</div>"
        f"<table>{rows}</table>{footer}</body></html>"
    ).encode()


def _frontier_result(
    urls: list[str],
    payloads: list[bytes],
    *,
    source_transport: str = "direct",
    retrieved_at: str = "2026-08-25T12:00:00Z",
    archive_timestamp: str = "",
) -> StateLawPageMultiFetchResult:
    receipts = []
    envelopes = []
    for index, url in enumerate(urls):
        content_sha256 = hashlib.sha256(payloads[index]).hexdigest()
        receipt_sha256 = _receipt_sha256(url, content_sha256, retrieved_at)
        transport = {
            "content_sha256": content_sha256,
            "official_url": url,
            "source_transport": source_transport,
        }
        if archive_timestamp:
            transport["archive_timestamp"] = archive_timestamp
        receipts.append(dict(transport))
        envelopes.append(
            {
                "acquisition": {
                    "receipt": {
                        "endpoint": url,
                        "content": {"sha256": content_sha256},
                        "metadata": {"transport_receipt": dict(transport)},
                        "receipt_sha256": receipt_sha256,
                        "retrieved_at": retrieved_at,
                    }
                }
            }
        )
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=[None] * len(urls),
        transport_receipts=receipts,
        parser_input_envelopes=envelopes,
        stats={},
    )


def _variant_chapter_html(
    chapter: str,
    rows: list[tuple[str, str, str, str]],
    *,
    chapter_title: str = "Variant chapter",
) -> bytes:
    table_rows = "".join(
        "<tr><td><a href='/main/PageSelect.aspx?section="
        f"{section}&amp;bid={bid}&amp;hl='>{section}</a></td>"
        f"<td>{title} ({effective_date})</td></tr>"
        for section, bid, title, effective_date in rows
    )
    return (
        "<html><head><title>Missouri Revisor of Statutes - Revised Statutes "
        f"of Missouri, RSMo Chapter {chapter}</title></head><body>"
        f"<div class='lr-font-norm'>Chapter {chapter} {chapter_title}</div>"
        f"<table>{table_rows}</table>"
        "<div id='BOTTOM'><a href='https://revisor.mo.gov/main/"
        "OneSection.aspx?section=3.090'>3.090</a></div></body></html>"
    ).encode()


def _section_html(section: str) -> bytes:
    return (
        "<html><body><div id='TOP'></div><div><div><div class='norm'>"
        f"<p class='norm'>{section}. "
        + ("Official Missouri statutory text. " * 12)
        + "</p><div class='foot'>---- (L. 2025 H.B. 1)</div>"
        "</div></div></div><div id='BOTTOM'></div></body></html>"
    ).encode()


def _page_select_body_unavailable_html(section: str, bid: str) -> bytes:
    return (
        "<html><head><title>Missouri Revisor of Statutes - Revised Statutes "
        f"of Missouri, RSMo Section {section}</title>"
        f"<meta property='og:title' content='{section}'>"
        "<meta property='og:url' content='https://revisor.mo.gov/main/"
        f"OneSection.aspx?section={section}&amp;bid={bid}'></head>"
        "<body><div id='TOP'></div><div><table><tr>"
        f"<td><a href='/main/PageSelect.aspx?section={section}&amp;bid={bid}'>"
        f"{section}</a></td></tr></table></div><div id='BOTTOM'></div></body></html>"
    ).encode()


def _page_select_identity_mismatch_html(
    requested_section: str,
    bid: str,
    observed_section: str,
) -> bytes:
    source_bound_head = (
        "<html><head><title>Missouri Revisor of Statutes - Revised Statutes "
        f"of Missouri, RSMo Section {requested_section}</title>"
        f"<meta property='og:title' content='{requested_section}'>"
        "<meta property='og:url' content='https://revisor.mo.gov/main/"
        f"OneSection.aspx?section={requested_section}&amp;bid={bid}'></head><body>"
    ).encode()
    return _section_html(observed_section).replace(
        b"<html><body>",
        source_bound_head,
        1,
    )


class _MissouriRetainedLedger:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = dict(pages)
        self.refresh_calls = 0
        self.requests: list[str] = []

    def refresh_existing_entries(self) -> None:
        self.refresh_calls += 1

    def replay_retained_parser_input(self, *, official_url: str, sanitized_request):
        assert dict(sanitized_request) == {"method": "GET", "url": official_url}
        self.requests.append(official_url)
        payload = self.pages.get(official_url)
        if payload is None:
            return None
        digest = hashlib.sha256(payload).hexdigest()
        transport = {
            "content_sha256": digest,
            "official_url": official_url,
            "source_transport": "direct",
        }
        receipt_mapping = {
            "content": {"sha256": digest},
            "endpoint": official_url,
            "metadata": {"transport_receipt": dict(transport)},
            "receipt_sha256": _receipt_sha256(
                official_url,
                digest,
                "2026-08-25T12:00:00Z",
            ),
            "retrieved_at": "2026-08-25T12:00:00Z",
        }
        envelope_mapping = {"acquisition": {"receipt": receipt_mapping}}
        envelope = SimpleNamespace(
            body=payload,
            to_dict=lambda: envelope_mapping,
        )
        return SimpleNamespace(
            envelope=envelope,
            receipt=SimpleNamespace(
                content=SimpleNamespace(sha256=digest),
            ),
            transport_receipt=transport,
        )


class _MissouriRetainedReplayOnlyLedger(_MissouriRetainedLedger):
    retained_replay_only = True

    def replay_retained_parser_input(self, *, official_url: str, sanitized_request):
        retained = super().replay_retained_parser_input(
            official_url=official_url,
            sanitized_request=sanitized_request,
        )
        if retained is None:
            raise StateLawRetainedReplayOnlyError(
                f"retained-replay-only ledger miss: {official_url}"
            )
        return retained


def _canonical_projection(
    scraper: MissouriScraper,
    rows: list[Any],
) -> dict[str, Any]:
    return build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="MO",
    )


def test_missouri_section_identity_allows_official_footnote_asterisk() -> None:
    source_url = (
        "https://revisor.mo.gov/main/"
        "PageSelect.aspx?section=8.500&bid=175&hl="
    )
    html = _section_html("8.500").replace(b">8.500.", b">*8.500.")

    statute = statute_from_section_html(
        html.decode(),
        section_number="8.500",
        source_url=source_url,
        source_record_bid="175",
    )

    assert statute is not None
    assert statute.section_number == "8.500"
    assert statute.source_url == source_url
    assert statute.full_text.startswith("*8.500.")


def test_missouri_section_body_identity_is_exact() -> None:
    assert section_body_identity(_section_html("51.282").decode()) == "51.282"
    assert section_body_identity("<html><body>navigation only</body></html>") == ""


def test_missouri_section_page_identity_requires_independent_exact_markers() -> None:
    exact = _page_select_body_unavailable_html("70.655", "57378").decode()
    assert section_page_identity(exact) == "70.655"
    assert section_body_identity(exact) == ""
    assert section_page_identity(exact.replace("og:title' content='70.655", "og:title' content='70.656")) == ""


_EMPTY_CHAPTER_CASES = (
    ("152", "Private Car Tax", "empty_chapter"),
    (
        "203",
        "Air Conservation (Transferred to Chapter 643)",
        "transferred",
    ),
    (
        "255",
        (
            "Division of Commerce and Industrial Development "
            "(Transferred to Chapter 625)"
        ),
        "transferred",
    ),
    ("280", "Treated Timber Products", "empty_chapter"),
    ("312", "Nonintoxicating Beer", "empty_chapter"),
    ("318", "Pool Tables", "empty_chapter"),
    ("342", "Stationary Engineers", "empty_chapter"),
    ("460", "Estates of Convicts", "empty_chapter"),
    ("560", "Fines", "empty_chapter"),
    ("564", "Inchoate Offenses", "empty_chapter"),
)


def test_missouri_frontier_identity_binds_sibling_parser() -> None:
    scraper = MissouriScraper("MO", "Missouri")

    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "missouri_chapter",
        "state_laws_multifetch_acquisition",
        "wayback_machine_engine",
    ]


def test_missouri_producer_digest_binds_plural_transport_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MissouriScraper("MO", "Missouri")
    dependencies = scraper.state_law_frontier_source_dependencies()
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri."
        "MissouriScraper@sha256:"
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


@pytest.mark.parametrize(
    ("chapter", "chapter_title", "disposition"),
    _EMPTY_CHAPTER_CASES,
)
def test_missouri_source_bound_empty_chapters_accept_exact_current_shells(
    chapter: str,
    chapter_title: str,
    disposition: str,
) -> None:
    html = _chapter_html(
        chapter,
        [],
        chapter_title=chapter_title,
    ).decode()
    source_url = (
        f"https://revisor.mo.gov/main/OneChapter.aspx?chapter={chapter}"
    )

    assert chapter_page_identity(html) == (chapter, chapter_title)
    assert chapter_sections(html, chapter) == []
    assert (
        source_bound_empty_chapter_disposition(
            html,
            chapter_number=chapter,
            source_url=source_url,
        )
        == disposition
    )


@pytest.mark.parametrize(
    ("chapter", "chapter_title", "sections", "footer_section", "source_url"),
    [
        (
            "151",
            "Civil Actions",
            [],
            "3.090",
            "https://revisor.mo.gov/main/OneChapter.aspx?chapter=151",
        ),
        (
            "152",
            "Private Car Taxes",
            [],
            "3.090",
            "https://revisor.mo.gov/main/OneChapter.aspx?chapter=152",
        ),
        (
            "152",
            "Private Car Tax",
            ["152.010"],
            "3.090",
            "https://revisor.mo.gov/main/OneChapter.aspx?chapter=152",
        ),
        (
            "152",
            "Private Car Tax",
            [],
            "3.091",
            "https://revisor.mo.gov/main/OneChapter.aspx?chapter=152",
        ),
        (
            "152",
            "Private Car Tax",
            [],
            None,
            "https://revisor.mo.gov/main/OneChapter.aspx?chapter=152",
        ),
        (
            "152",
            "Private Car Tax",
            [],
            "3.090",
            "https://revisor.mo.gov/main/OneChapter.aspx?chapter=152&copy=1",
        ),
    ],
)
def test_missouri_source_bound_empty_chapters_reject_drift(
    chapter: str,
    chapter_title: str,
    sections: list[str],
    footer_section: str | None,
    source_url: str,
) -> None:
    html = _chapter_html(
        chapter,
        sections,
        chapter_title=chapter_title,
        footer_section=footer_section,
    ).decode()

    assert (
        source_bound_empty_chapter_disposition(
            html,
            chapter_number=chapter,
            source_url=source_url,
        )
        is None
    )


def test_missouri_chapter_variants_preserve_bid_date_and_resolve_as_of_date() -> None:
    html = _variant_chapter_html(
        "167",
        [
            (
                "167.910",
                "60449",
                "(Repealed L. 2026 S.B. 890)",
                "8/28/2026",
            ),
            (
                "167.910",
                "60450",
                "(Repealed L. 2026 S.B. 890)",
                "8/28/2026",
            ),
            ("167.910", "35838", "Current substantive text", "8/28/2018"),
            ("167.910", "35840", "Current consolidated text", "8/28/2018"),
        ],
    ).decode()

    variants = chapter_section_variants(html, "167")

    assert [variant.bid for variant in variants] == [
        "60449",
        "60450",
        "35838",
        "35840",
    ]
    assert variants[0].source_url == (
        "https://revisor.mo.gov/main/PageSelect.aspx?section=167.910&bid=60449&hl="
    )
    assert variants[0].effective_date_text == "8/28/2026"
    assert variants[0].terminal_disposition == "repealed"

    current, excluded = authoritative_chapter_section_variants(
        variants,
        as_of_date=date(2026, 8, 25),
    )
    current_reversed, _ = authoritative_chapter_section_variants(
        list(reversed(variants)),
        as_of_date=date(2026, 8, 25),
    )
    future, _ = authoritative_chapter_section_variants(
        variants,
        as_of_date=date(2026, 8, 28),
    )

    assert [variant.bid for variant in current] == ["35840"]
    assert [variant.bid for variant in current_reversed] == ["35840"]
    assert len(excluded) == 3
    assert [variant.bid for variant in future] == ["60450"]
    assert future[0].terminal_disposition == "repealed"


def test_missouri_evidence_context_accepts_production_envelope_object() -> None:
    url = "https://revisor.mo.gov/main/OneChapter.aspx?chapter=1"
    result = _frontier_result([url], [_chapter_html("1", ["1.010"])])
    mapping = result.parser_input_envelopes[0]

    class _ProductionEnvelopeShape:
        def to_dict(self) -> dict[str, Any]:
            return mapping

    context = MissouriScraper(
        "MO",
        "Missouri",
    )._missouri_chapter_evidence_context(
        source_url=url,
        transport_receipt=result.transport_receipts[0],
        parser_input_envelope=_ProductionEnvelopeShape(),
    )

    assert context["source_transport"] == "direct"
    assert context["as_of_date"] == date(2026, 8, 25)


def test_missouri_ucc_hyphenated_section_keeps_exact_source_record_identity() -> None:
    html = _variant_chapter_html(
        "400",
        [("400.2A-101", "22749", "Short title.", "8/28/1992")],
        chapter_title="Uniform Commercial Code",
    ).decode()

    variants = chapter_section_variants(html, "400")

    assert len(variants) == 1
    variant = variants[0]
    assert variant.section_number == "400.2A-101"
    assert variant.source_url == (
        "https://revisor.mo.gov/main/"
        "PageSelect.aspx?section=400.2A-101&bid=22749&hl="
    )
    statute = statute_from_section_html(
        _section_html("400.2A-101").decode(),
        section_number=variant.section_number,
        section_title=variant.section_title,
        source_url=variant.source_url,
        source_record_bid=variant.bid,
        effective_date=variant.effective_date_text,
    )
    assert statute is not None
    assert statute.source_url == variant.source_url
    assert statute.structured_data["source_record_id"] == variant.source_url


@pytest.mark.anyio
async def test_missouri_terminal_chapter_identity_is_retained_in_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"
    chapter_urls = [
        "https://revisor.mo.gov/main/OneChapter.aspx?chapter=1",
        "https://revisor.mo.gov/main/OneChapter.aspx?chapter=152",
    ]
    page_select_url = (
        "https://revisor.mo.gov/main/PageSelect.aspx?section=1.010&bid=100&hl="
    )
    one_section_url = (
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.010"
    )
    home_html = (
        b"<a href='/main/OneChapter.aspx?chapter=1'>Chapter 1</a>"
        b"<a href='/main/OneChapter.aspx?chapter=152'>Chapter 152</a>"
    )
    checkpoint_extras: dict[str, dict[str, Any]] = {}

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return home_html

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        if frontier_name == "chapter-index":
            assert requested == chapter_urls
            return _frontier_result(
                requested,
                [
                    _chapter_html("1", ["1.010"]),
                    _chapter_html(
                        "152",
                        [],
                        chapter_title="Private Car Tax",
                    ),
                ],
            )
        assert frontier_name == "source-ordered-one-section-residuals"
        assert requested == [one_section_url]
        return _frontier_result(requested, [_section_html("1.010")])

    def _checkpoint(self, statutes, *, stage_label: str, extra=None, **_kwargs):
        checkpoint_extras[stage_label] = dict(extra or {})
        return True

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(MissouriScraper, "_write_partial_checkpoint", _checkpoint)
    scraper = MissouriScraper("MO", "Missouri")

    rows = await scraper._custom_scrape_missouri(
        "Missouri Revised Statutes",
        home_url,
        "Mo. Rev. Stat.",
        max_sections=None,
    )

    expected_terminal = {
        "chapter_number": "152",
        "chapter_title": "Private Car Tax",
        "disposition": "empty_chapter",
        "source_url": chapter_urls[1],
        "as_of_date": "2026-08-25",
        "receipt_sha256": _receipt_sha256(
            chapter_urls[1],
            hashlib.sha256(
                _chapter_html("152", [], chapter_title="Private Car Tax")
            ).hexdigest(),
            "2026-08-25T12:00:00Z",
        ),
        "source_transport": "direct",
    }
    assert [row.section_number for row in rows] == ["1.010"]
    assert rows[0].source_url == one_section_url
    assert rows[0].structured_data["source_frontier_record_url"] == page_select_url
    assert checkpoint_extras["missouri:chapter-discovery"][
        "terminal_chapter_dispositions"
    ] == []
    for stage in (
        "missouri:section-discovery",
        "missouri:section-scan",
        "missouri:complete",
    ):
        assert checkpoint_extras[stage]["terminal_chapters_classified"] == 1
        assert checkpoint_extras[stage]["terminal_chapter_dispositions"] == [
            expected_terminal
        ]


@pytest.mark.anyio
async def test_missouri_frontier_batch_uses_shared_grouped_warc_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.010",
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.020",
    ]
    observed: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(self, requested, **kwargs):
        requested = list(requested)
        observed.append((requested, dict(kwargs)))
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[b"one", b"two"],
            errors=[None, None],
            transport_receipts=[{}, {}],
            parser_input_envelopes=[None, None],
            stats={"requested_pages": 2},
        )

    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = MissouriScraper("MO", "Missouri")

    batch = await scraper._fetch_missouri_frontier_batch(
        urls,
        frontier_name="sections",
    )

    assert batch.payloads == [b"one", b"two"]
    validator = observed[0][1].pop("content_validator")
    assert callable(validator)
    assert validator(b"ordinary official Missouri page") is True
    assert observed == [
        (
            urls,
            {
                "residual_retry_attempts": 1,
                "timeout_seconds": 20,
                "media_type": "text/html",
                "max_concurrency": 16,
                "prefer_direct": True,
                "common_crawl_domain_terms": ("revisor.mo.gov",),
                "common_crawl_url_terms": ("/main/",),
                "common_crawl_mime_terms": ("html",),
                "wayback_prefix_inventory": True,
            },
        )
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("frontier_name", "url"),
    [
        (
            "chapter-index",
            "https://revisor.mo.gov/main/OneChapter.aspx?chapter=1",
        ),
        (
            "sections-1-1",
            "https://revisor.mo.gov/main/OneSection.aspx?section=1.010",
        ),
    ],
)
async def test_missouri_batches_reject_nofish_robot_throttle_before_retention(
    monkeypatch: pytest.MonkeyPatch,
    frontier_name: str,
    url: str,
) -> None:
    observed_validators = []

    async def _plural(self, requested, **kwargs):
        requested = list(requested)
        validator = kwargs["content_validator"]
        observed_validators.append(validator)
        assert validator(
            b"<html><form action='/main/nofish.aspx'>Try again</form></html>"
        ) is False
        assert validator(
            b"<html><body>Are you double clicking links?</body></html>"
        ) is False
        assert validator(b"<html><body>Official Missouri content</body></html>") is True
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[b"<html><body>Official Missouri content</body></html>"],
            errors=[None],
            transport_receipts=[{}],
            parser_input_envelopes=[None],
            stats={},
        )

    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = MissouriScraper("MO", "Missouri")

    batch = await scraper._fetch_missouri_frontier_batch(
        [url],
        frontier_name=frontier_name,
    )

    assert batch.payloads == [b"<html><body>Official Missouri content</body></html>"]
    assert len(observed_validators) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("failure_kind", ["reordered", "missing", "short"])
async def test_missouri_frontier_batch_fails_closed_on_identity_or_body_gap(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    urls = [
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.010",
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.020",
    ]

    async def _plural(self, requested, **_kwargs):
        requested = list(requested)
        returned_urls = list(reversed(requested)) if failure_kind == "reordered" else requested
        errors = [None, "unavailable" if failure_kind == "missing" else None]
        if failure_kind == "short":
            errors = errors[:1]
        return StateLawPageMultiFetchResult(
            urls=returned_urls,
            payloads=[b"one", b"" if failure_kind == "missing" else b"two"],
            errors=errors,
            transport_receipts=[{}, {}],
            parser_input_envelopes=[None, None],
            stats={},
        )

    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = MissouriScraper("MO", "Missouri")

    with pytest.raises(
        RuntimeError,
        match="changed URL order|unresolved exact URLs|unaligned acquisition rows",
    ):
        await scraper._fetch_missouri_frontier_batch(urls, frontier_name="sections")


@pytest.mark.anyio
async def test_missouri_unbounded_crawl_batches_known_chapters_and_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"
    chapter_urls = [
        "https://revisor.mo.gov/main/OneChapter.aspx?chapter=1",
        "https://revisor.mo.gov/main/OneChapter.aspx?chapter=2",
    ]
    page_select_urls = [
        "https://revisor.mo.gov/main/PageSelect.aspx?section=1.010&bid=100&hl=",
        "https://revisor.mo.gov/main/PageSelect.aspx?section=1.020&bid=101&hl=",
        "https://revisor.mo.gov/main/PageSelect.aspx?section=2.010&bid=100&hl=",
    ]
    one_section_urls = [
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.010",
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.020",
        "https://revisor.mo.gov/main/OneSection.aspx?section=2.010",
    ]
    home_html = (
        "<html><body>"
        "<a href='/main/OneChapter.aspx?chapter=1'>Chapter 1</a>"
        "<a href='/main/OneChapter.aspx?chapter=2'>Chapter 2</a>"
        "</body></html>"
    ).encode()
    pages = {
        chapter_urls[0]: _chapter_html("1", ["1.010", "1.020"]),
        chapter_urls[1]: _chapter_html("2", ["2.010"]),
        one_section_urls[0]: _section_html("1.010"),
        one_section_urls[1]: _section_html("1.020"),
        one_section_urls[2]: _section_html("2.010"),
    }
    singleton_calls: list[str] = []
    batch_calls: list[tuple[str, list[str]]] = []
    checkpoint_calls: list[tuple[str, bool]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        singleton_calls.append(url)
        assert timeout_seconds == 20
        assert url == home_url
        return home_html

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return _frontier_result(requested, [pages[url] for url in requested])

    def _checkpoint(
        self,
        statutes,
        *,
        stage_label: str,
        replace_existing_rows: bool = False,
        **_kwargs,
    ):
        checkpoint_calls.append((stage_label, replace_existing_rows))
        return True

    def _stale_checkpoint_must_not_load(*_args, **_kwargs):
        raise AssertionError("unbounded Missouri must rebuild its authoritative frontier")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(MissouriScraper, "_write_partial_checkpoint", _checkpoint)
    monkeypatch.setattr(
        MissouriScraper,
        "_load_partial_checkpoint_statutes",
        _stale_checkpoint_must_not_load,
    )
    monkeypatch.setattr(
        MissouriScraper,
        "_load_partial_checkpoint_progress",
        _stale_checkpoint_must_not_load,
    )

    scraper = MissouriScraper("MO", "Missouri")
    rows = await scraper._custom_scrape_missouri(
        "Missouri Revised Statutes",
        home_url,
        "Mo. Rev. Stat.",
        max_sections=None,
    )

    assert singleton_calls == [home_url]
    assert batch_calls == [
        ("chapter-index", chapter_urls),
        ("source-ordered-one-section-residuals", one_section_urls),
    ]
    assert [row.section_number for row in rows] == ["1.010", "1.020", "2.010"]
    assert [row.source_url for row in rows] == one_section_urls
    assert [row.structured_data["source_record_id"] for row in rows] == one_section_urls
    assert [
        row.structured_data["source_frontier_record_url"] for row in rows
    ] == page_select_urls
    assert [row.structured_data["source_record_bid"] for row in rows] == [
        "100",
        "101",
        "100",
    ]
    assert [row.structured_data["effective_date"] for row in rows] == [
        "8/28/2025",
        "8/28/2025",
        "8/28/2025",
    ]
    assert len({row.statute_id for row in rows}) == 3
    assert scraper._last_missouri_section_acquisition_plan[
        "one_section_plural_wave_count"
    ] == 1
    assert scraper._last_missouri_section_acquisition_plan[
        "residual_one_section_count"
    ] == 3
    assert checkpoint_calls == [
        ("missouri:chapter-discovery", True),
        ("missouri:section-discovery", True),
        ("missouri:section-scan", True),
        ("missouri:complete", True),
    ]


@pytest.mark.anyio
async def test_missouri_complete_retained_only_one_section_skips_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = MissouriScraper.OFFICIAL_ENTRY_URL
    chapter_url = "https://revisor.mo.gov/main/OneChapter.aspx?chapter=1"
    page_select_url = (
        "https://revisor.mo.gov/main/PageSelect.aspx?section=1.010&bid=100&hl="
    )
    one_section_url = (
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.010"
    )
    home_payload = b"<a href='/main/OneChapter.aspx?chapter=1'>Chapter 1</a>"
    chapter_payload = _chapter_html("1", ["1.010"])
    calls: list[tuple[str, list[str]]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return home_payload

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        calls.append((frontier_name, requested))
        if frontier_name == "chapter-index":
            return _frontier_result(requested, [chapter_payload])
        raise AssertionError("retained-only section inputs must not enter transport")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = MissouriScraper("MO", "Missouri")
    ledger = _MissouriRetainedReplayOnlyLedger(
        {one_section_url: _section_html("1.010")}
    )
    scraper._state_law_acquisition_ledger = ledger

    rows = await scraper._custom_scrape_missouri(
        "Missouri Revised Statutes",
        home_url,
        "Mo. Rev. Stat.",
        max_sections=None,
    )

    assert calls == [("chapter-index", [chapter_url])]
    assert [row.source_url for row in rows] == [one_section_url]
    assert rows[0].structured_data["source_frontier_record_url"] == page_select_url
    plan = scraper._last_missouri_section_acquisition_plan
    assert plan["retained_page_select_count"] == 0
    assert plan["retained_one_section_count"] == 1
    assert plan["residual_one_section_count"] == 0
    assert plan["one_section_plural_wave_count"] == 0


@pytest.mark.anyio
async def test_missouri_unbounded_crawl_rejects_wrong_chapter_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"
    chapter_url = "https://revisor.mo.gov/main/OneChapter.aspx?chapter=1"

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return b"<a href='/main/OneChapter.aspx?chapter=1'>Chapter 1</a>"

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        assert frontier_name == "chapter-index"
        assert requested == [chapter_url]
        return _frontier_result(requested, [_chapter_html("2", ["2.010"])])

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = MissouriScraper("MO", "Missouri")

    with pytest.raises(RuntimeError, match="requested chapter identity"):
        await scraper._custom_scrape_missouri(
            "Missouri Revised Statutes",
            home_url,
            "Mo. Rev. Stat.",
            max_sections=None,
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("chapter", "archive_timestamp"),
    [("276", "20191208103345"), ("307", "20191209110908")],
)
async def test_missouri_current_crawl_rejects_old_archive_only_chapter_body(
    monkeypatch: pytest.MonkeyPatch,
    chapter: str,
    archive_timestamp: str,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"
    chapter_url = (
        f"https://revisor.mo.gov/main/OneChapter.aspx?chapter={chapter}"
    )
    chapter_payload = _chapter_html(chapter, [f"{chapter}.010"])

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return (
            f"<a href='/main/OneChapter.aspx?chapter={chapter}'>"
            f"Chapter {chapter}</a>"
        ).encode()

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        assert frontier_name == "chapter-index"
        return _frontier_result(
            requested,
            [chapter_payload],
            source_transport="wayback",
            archive_timestamp=archive_timestamp,
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = MissouriScraper("MO", "Missouri")

    context = scraper._missouri_chapter_evidence_context(
        source_url=chapter_url,
        transport_receipt=_frontier_result(
            [chapter_url],
            [chapter_payload],
            source_transport="wayback",
            archive_timestamp=archive_timestamp,
        ).transport_receipts[0],
        parser_input_envelope=_frontier_result(
            [chapter_url],
            [chapter_payload],
            source_transport="wayback",
            archive_timestamp=archive_timestamp,
        ).parser_input_envelopes[0],
    )
    assert context["as_of_date"] == date(
        int(archive_timestamp[:4]),
        int(archive_timestamp[4:6]),
        int(archive_timestamp[6:8]),
    )

    with pytest.raises(RuntimeError, match="only historical as-of authority"):
        await scraper._custom_scrape_missouri(
            "Missouri Revised Statutes",
            home_url,
            "Mo. Rev. Stat.",
            max_sections=None,
        )


@pytest.mark.anyio
async def test_missouri_unbounded_crawl_selects_exact_current_page_select_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"
    chapter_url = "https://revisor.mo.gov/main/OneChapter.aspx?chapter=167"
    selected_url = (
        "https://revisor.mo.gov/main/"
        "PageSelect.aspx?section=167.910&bid=35840&hl="
    )
    chapter_payload = _variant_chapter_html(
        "167",
        [
            (
                "167.910",
                "60450",
                "(Repealed L. 2026 S.B. 890)",
                "8/28/2026",
            ),
            ("167.910", "35838", "Current substantive text", "8/28/2018"),
            ("167.910", "35840", "Current consolidated text", "8/28/2018"),
        ],
    )
    batch_calls: list[tuple[str, list[str]]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return b"<a href='/main/OneChapter.aspx?chapter=167'>Chapter 167</a>"

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        if frontier_name == "chapter-index":
            return _frontier_result(requested, [chapter_payload])
        raise AssertionError("retained PageSelect input must not enter a fetch wave")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = MissouriScraper("MO", "Missouri")
    scraper._state_law_acquisition_ledger = _MissouriRetainedLedger(
        {selected_url: _section_html("167.910")}
    )

    rows = await scraper._custom_scrape_missouri(
        "Missouri Revised Statutes",
        home_url,
        "Mo. Rev. Stat.",
        max_sections=None,
    )

    assert batch_calls == [
        ("chapter-index", [chapter_url]),
    ]
    assert len(rows) == 1
    assert rows[0].source_url == selected_url
    assert rows[0].structured_data["source_record_id"] == selected_url
    assert rows[0].structured_data["source_record_bid"] == "35840"
    assert rows[0].structured_data["effective_date"] == "8/28/2018"
    plan = scraper._last_missouri_section_acquisition_plan
    assert plan["retained_page_select_count"] == 1
    assert plan["retained_page_select_parser_input_count"] == 1
    assert plan["residual_one_section_count"] == 0
    assert plan["one_section_plural_wave_count"] == 0


@pytest.mark.anyio
async def test_missouri_identity_mismatch_uses_batched_exact_one_section_residual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"
    chapter_url = "https://revisor.mo.gov/main/OneChapter.aspx?chapter=51"
    page_select_url = (
        "https://revisor.mo.gov/main/"
        "PageSelect.aspx?section=51.282&bid=1860&hl="
    )
    fallback_url = (
        "https://revisor.mo.gov/main/OneSection.aspx?section=51.282"
    )
    chapter_payload = _variant_chapter_html(
        "51",
        [("51.282", "1860", "Compensation of certain county clerks", "5/13/1988")],
    )
    batch_calls: list[tuple[str, list[str]]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return b"<a href='/main/OneChapter.aspx?chapter=51'>Chapter 51</a>"

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        if frontier_name == "chapter-index":
            return _frontier_result(requested, [chapter_payload])
        assert frontier_name == "source-ordered-one-section-residuals"
        assert requested == [fallback_url]
        return _frontier_result(requested, [_section_html("51.282")])

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )

    scraper = MissouriScraper("MO", "Missouri")
    scraper._state_law_acquisition_ledger = _MissouriRetainedLedger(
        {
            page_select_url: _page_select_identity_mismatch_html(
                "51.282",
                "1860",
                "51.280",
            )
        }
    )
    rows = await scraper._custom_scrape_missouri(
        "Missouri Revised Statutes",
        home_url,
        "Mo. Rev. Stat.",
        max_sections=None,
    )

    assert batch_calls == [
        ("chapter-index", [chapter_url]),
        ("source-ordered-one-section-residuals", [fallback_url]),
    ]
    assert len(rows) == 1
    assert rows[0].section_number == "51.282"
    assert rows[0].source_url == fallback_url
    assert rows[0].structured_data["source_record_id"] == fallback_url
    assert rows[0].structured_data["source_record_bid"] == "1860"
    assert rows[0].structured_data["source_frontier_record_url"] == page_select_url
    assert rows[0].structured_data["source_identity_fallback_reason"] == (
        "official_page_select_body_identity_mismatch"
    )


@pytest.mark.anyio
async def test_missouri_exact_page_shell_uses_batched_one_section_residual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = MissouriScraper.OFFICIAL_ENTRY_URL
    chapter_url = MissouriScraper("MO", "Missouri").official_chapter_url("70")
    page_select_url = (
        "https://revisor.mo.gov/main/"
        "PageSelect.aspx?section=70.655&bid=57378&hl="
    )
    fallback_url = "https://revisor.mo.gov/main/OneSection.aspx?section=70.655"
    chapter_payload = _variant_chapter_html(
        "70",
        [("70.655", "57378", "Official current provision", "8/28/2025")],
    )
    batch_calls: list[tuple[str, list[str]]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return b"<a href='/main/OneChapter.aspx?chapter=70'>Chapter 70</a>"

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        if frontier_name == "chapter-index":
            return _frontier_result(requested, [chapter_payload])
        assert frontier_name == "source-ordered-one-section-residuals"
        assert requested == [fallback_url]
        return _frontier_result(requested, [_section_html("70.655")])

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )

    scraper = MissouriScraper("MO", "Missouri")
    scraper._state_law_acquisition_ledger = _MissouriRetainedLedger(
        {
            page_select_url: _page_select_body_unavailable_html(
                "70.655",
                "57378",
            )
        }
    )
    rows = await scraper._custom_scrape_missouri(
        "Missouri Revised Statutes",
        home_url,
        "Mo. Rev. Stat.",
        max_sections=None,
    )

    assert batch_calls == [
        ("chapter-index", [chapter_url]),
        ("source-ordered-one-section-residuals", [fallback_url]),
    ]
    assert [row.section_number for row in rows] == ["70.655"]
    assert rows[0].source_url == fallback_url
    assert rows[0].structured_data["source_frontier_record_url"] == page_select_url
    assert rows[0].structured_data["source_identity_fallback_reason"] == (
        "official_page_select_body_unavailable"
    )


@pytest.mark.anyio
async def test_missouri_unavailable_page_select_uses_one_plural_residual_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"
    chapter_url = "https://revisor.mo.gov/main/OneChapter.aspx?chapter=71"
    page_select_urls = [
        "https://revisor.mo.gov/main/"
        "PageSelect.aspx?section=71.017&bid=3414&hl=",
        "https://revisor.mo.gov/main/"
        "PageSelect.aspx?section=71.018&bid=3415&hl=",
    ]
    fallback_urls = [
        "https://revisor.mo.gov/main/OneSection.aspx?section=71.017",
        "https://revisor.mo.gov/main/OneSection.aspx?section=71.018",
    ]
    chapter_payload = _variant_chapter_html(
        "71",
        [
            ("71.017", "3414", "First official current provision", "8/28/1997"),
            ("71.018", "3415", "Second official current provision", "8/28/1997"),
        ],
    )
    batch_calls: list[tuple[str, list[str], bool]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return b"<a href='/main/OneChapter.aspx?chapter=71'>Chapter 71</a>"

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        batch_calls.append((frontier_name, requested, allow_residuals))
        if frontier_name == "chapter-index":
            return _frontier_result(requested, [chapter_payload])
        assert frontier_name == "source-ordered-one-section-residuals"
        assert requested == fallback_urls
        return _frontier_result(
            requested,
            [_section_html("71.017"), _section_html("71.018")],
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )

    rows = await MissouriScraper("MO", "Missouri")._custom_scrape_missouri(
        "Missouri Revised Statutes",
        home_url,
        "Mo. Rev. Stat.",
        max_sections=None,
    )

    assert batch_calls == [
        ("chapter-index", [chapter_url], False),
        ("source-ordered-one-section-residuals", fallback_urls, False),
    ]
    assert [row.section_number for row in rows] == ["71.017", "71.018"]
    assert [row.source_url for row in rows] == fallback_urls
    assert [
        row.structured_data["source_frontier_record_url"] for row in rows
    ] == page_select_urls
    assert {
        row.structured_data["source_identity_fallback_reason"] for row in rows
    } == {"official_page_select_unavailable"}


@pytest.mark.anyio
async def test_missouri_retained_replay_closes_variants_rights_and_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home_url = MissouriScraper.OFFICIAL_ENTRY_URL
    chapter_url = "https://revisor.mo.gov/main/OneChapter.aspx?chapter=1"
    section_urls = [
        "https://revisor.mo.gov/main/PageSelect.aspx?section=1.010&bid=100&hl=",
        "https://revisor.mo.gov/main/PageSelect.aspx?section=1.020&bid=102&hl=",
    ]
    fallback_url = "https://revisor.mo.gov/main/OneSection.aspx?section=1.020"
    home_payload = b"<a href='/main/OneChapter.aspx?chapter=1'>Chapter 1</a>"
    chapter_payload = _variant_chapter_html(
        "1",
        [
            ("1.010", "100", "First current provision", "8/28/2025"),
            ("1.010", "101", "Future amended provision", "8/28/2027"),
            ("1.020", "102", "Second current provision", "8/28/2024"),
        ],
    )
    pages = {
        home_url: home_payload,
        chapter_url: chapter_payload,
        section_urls[0]: _section_html("1.010"),
        section_urls[1]: _page_select_identity_mismatch_html(
            "1.020",
            "102",
            "1.019",
        ),
        fallback_url: _section_html("1.020"),
    }

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return home_payload

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        if frontier_name == "chapter-index":
            assert allow_residuals is False
            return _frontier_result(requested, [chapter_payload])
        raise AssertionError("complete retained inputs must not enter a fetch wave")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = MissouriScraper("MO", "Missouri")
    ledger = _MissouriRetainedLedger(pages)
    scraper._state_law_acquisition_ledger = ledger
    rows = await scraper._custom_scrape_missouri(
        "Missouri Revised Statutes",
        home_url,
        "Mo. Rev. Stat.",
        max_sections=None,
    )

    first = scraper._last_missouri_full_frontier
    assert [row.section_number for row in rows] == ["1.010", "1.020"]
    assert rows[1].source_url == fallback_url
    assert rows[1].structured_data["source_identity_fallback_reason"] == (
        "official_page_select_body_identity_mismatch"
    )
    assert first["frontier"]["disposition"] == {
        "discovered": 3,
        "duplicates": 0,
        "excluded": 1,
        "failed_final": 0,
        "fetched": 2,
        "quarantined": 0,
    }
    assert first["frontier"]["terminal_section_dispositions"] == {
        "future_effective_variant": 1,
    }
    assert first["frontier"]["hierarchy_disposition"] == {
        "active": 1,
        "discovered": 1,
        "duplicates": 0,
        "terminal": 0,
        "unclassified": 0,
    }
    assert first["section_acquisition_plan"]["one_section_plural_wave_count"] == 0
    assert first["section_acquisition_plan"]["retained_page_select_count"] == 2
    assert first["section_acquisition_plan"]["retained_one_section_count"] == 1

    captured: dict[str, Any] = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "missouri-closure.json"

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["missouri-revisor-html"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "missouri-test@sha256:" + ("a" * 64),
    )
    projection = _canonical_projection(scraper, rows)
    reversed_projection = {
        **projection,
        "canonical_keys": list(reversed(projection["canonical_keys"])),
    }
    with pytest.raises(RuntimeError, match="canonical identities"):
        await scraper.produce_state_law_frontier_closure(
            canonical_output_projection=reversed_projection,
        )

    retained = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert retained == tmp_path / "missouri-closure.json"
    assert captured["completion"]["rights"] == {
        "basis": "public_law_no_state_copyright",
        "decision": "admit",
        "scope": "statutory_text",
    }
    assert captured["completion"]["replay"]["network_requests"] == 0
    assert captured["completion"]["index_keys"]["canonical_keys"] == projection[
        "canonical_keys"
    ]
    assert captured["completion"]["transport"]["per_page_archive_loop"] is False
    assert ledger.refresh_calls == 3
    assert ledger.requests == [
        section_urls[0],
        section_urls[1],
        fallback_url,
    ] + [
        home_url,
        chapter_url,
        section_urls[0],
        section_urls[1],
        fallback_url,
    ] * 2


@pytest.mark.anyio
async def test_missouri_unbounded_crawl_rejects_unparseable_retained_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"
    chapter_url = "https://revisor.mo.gov/main/OneChapter.aspx?chapter=1"
    section_url = (
        "https://revisor.mo.gov/main/PageSelect.aspx?section=1.010&bid=100&hl="
    )

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return b"<a href='/main/OneChapter.aspx?chapter=1'>Chapter 1</a>"

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        if frontier_name == "chapter-index":
            assert requested == [chapter_url]
            return _frontier_result(requested, [_chapter_html("1", ["1.010"])])
        raise AssertionError("invalid retained PageSelect must fail before acquisition")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(MissouriScraper, "_write_partial_checkpoint", lambda *a, **k: True)

    scraper = MissouriScraper("MO", "Missouri")
    scraper._state_law_acquisition_ledger = _MissouriRetainedLedger(
        {section_url: _section_html("1.020")}
    )

    with pytest.raises(RuntimeError, match=r"PageSelect\.aspx\?section=1\.010"):
        await scraper._custom_scrape_missouri(
            "Missouri Revised Statutes",
            home_url,
            "Mo. Rev. Stat.",
            max_sections=None,
        )


@pytest.mark.anyio
async def test_missouri_unbounded_crawl_rejects_loose_footer_section_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"
    chapter_url = "https://revisor.mo.gov/main/OneChapter.aspx?chapter=565"

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return b"<a href='/main/OneChapter.aspx?chapter=565'>Chapter 565</a>"

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        assert frontier_name == "chapter-index"
        requested = list(urls)
        assert requested == [chapter_url]
        return _frontier_result(
            requested,
            [
                _chapter_html(
                "565",
                [],
                chapter_title="Offenses Against the Person",
                )
            ],
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(MissouriScraper, "_write_partial_checkpoint", lambda *a, **k: True)
    scraper = MissouriScraper("MO", "Missouri")

    with pytest.raises(RuntimeError, match="no source-bound terminal disposition"):
        await scraper._custom_scrape_missouri(
            "Missouri Revised Statutes",
            home_url,
            "Mo. Rev. Stat.",
            max_sections=None,
        )


@pytest.mark.anyio
async def test_missouri_unbounded_crawl_rejects_noncanonical_home_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = "https://revisor.mo.gov/main/Home.aspx"

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return (
            b"<a href='https://example.invalid/main/OneChapter.aspx?chapter=1'>"
            b"Chapter 1</a>"
        )

    async def _batch_must_not_run(*_args, **_kwargs):
        raise AssertionError("invalid Home locator must fail before acquisition")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_missouri_frontier_batch",
        _batch_must_not_run,
    )
    scraper = MissouriScraper("MO", "Missouri")

    with pytest.raises(RuntimeError, match="non-canonical chapter locator"):
        await scraper._custom_scrape_missouri(
            "Missouri Revised Statutes",
            home_url,
            "Mo. Rev. Stat.",
            max_sections=None,
        )
