import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming import (
    WyomingScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming_constitution import (
    _TERMINAL,
    _TERMINAL_LEAD,
    _WY_ARTICLE_RE,
    _WY_SECTION_RE,
    parse_wyoming_constitution_text,
)


def _split(scraper: WyomingScraper, text: str, *, title: str = "1"):
    return scraper._split_title_pdf_into_sections(
        code_name="Wyoming Statutes",
        title_number=title,
        title_name=f"Title {title}",
        title_text=text,
        source_url=f"https://www.wyoleg.gov/statutes/compress/title{title}.pdf",
        citation_format="Wyo. Stat.",
    )


def test_wyoming_pdf_headers_are_line_safe_title_bound_and_keep_early_sections():
    scraper = WyomingScraper("WY", "Wyoming")
    text = """
     1-1-101. First operative section.

     First body text is long enough to remain an operative statute row. It cites
1-1-999. This is a body citation, not an official section heading.

     1-1-102. Second operative section.

     Second body text is also long enough to remain an operative statute row.
     1-1-104. First section on a new PDF page.

     This page-bound provision has enough substantive body text for indexing.

     1-1-102. Second operative section.

     2-1-101. Foreign-title overlay.

     1-1-103. Third operative section.

     Third body text is also long enough to remain an operative statute row.
"""

    rows = _split(scraper, text)

    assert [row.section_number for row in rows] == [
        "1-1-101",
        "1-1-102",
        "1-1-104",
        "1-1-103",
    ]
    assert "First body text" in rows[0].full_text
    report = scraper._last_wyoming_title_parse_report
    assert report["candidate_sections"] == 4
    assert report["duplicate_header_occurrences"] == 1
    assert report["foreign_title_headers"] == ["2-1-101"]
    assert report["closed"] is True


def test_wyoming_decimal_title_34_1_is_not_folded_into_title_34():
    scraper = WyomingScraper("WY", "Wyoming")
    text = """
     34.1-1-101. Decimal title provision.

     This official decimal-title provision has enough substantive body text for indexing.

     34-1-101. Different title provision.

     This belongs to title 34 and must not enter the title 34.1 result.
"""

    rows = _split(scraper, text, title="34.1")

    assert [row.section_number for row in rows] == ["34.1-1-101"]
    assert scraper._last_wyoming_title_parse_report["foreign_title_headers"] == ["34-1-101"]


def test_wyoming_terminal_heading_closes_without_becoming_an_index_row():
    scraper = WyomingScraper("WY", "Wyoming")
    text = """
     17-16-1101. Reserved.

     17-16-1102. Operative section.

     This operative provision has enough substantive body text for indexing as law.
"""

    rows = _split(scraper, text, title="17")

    assert [row.section_number for row in rows] == ["17-16-1102"]
    report = scraper._last_wyoming_title_parse_report
    assert report["candidate_sections"] == 2
    assert report["operative_sections"] == 1
    assert report["terminal_sections"] == 1
    assert report["parser_residuals"] == []
    assert report["closed"] is True


def test_wyoming_duplicate_heading_overlay_requires_another_canonical_section():
    scraper = WyomingScraper("WY", "Wyoming")
    text = """
     35-11-318. Title to sequestered and injected carbon dioxide; definitions.

     35-11-318. Geologic sequestration special revenue account.

     (a) Geologic sequestration special revenue account.

     The operative definitions and title provision continue with enough body text to index.

     35-11-319. Certificate of project completion.

     The project completion provision has enough substantive body text for indexing.

     35-11-320. Geologic sequestration special revenue account.

     The special revenue account provision has enough substantive body text for indexing.
"""

    rows = _split(scraper, text, title="35")

    assert [row.section_number for row in rows] == ["35-11-318", "35-11-319", "35-11-320"]
    assert "Geologic sequestration special revenue account" not in rows[0].full_text
    report = scraper._last_wyoming_title_parse_report
    assert report["overlay_duplicate_headers"] == [
        {
            "section_number": "35-11-318",
            "heading": "Geologic sequestration special revenue account",
            "canonical_section_numbers": ["35-11-320"],
            "reason": "alternate_heading_is_canonical_for_other_section",
        }
    ]
    assert report["conflicting_duplicate_headers"] == {}
    assert report["closed"] is True


def test_wyoming_parser_residual_prevents_title_closure():
    scraper = WyomingScraper("WY", "Wyoming")

    assert _split(scraper, "\n     1-1-101. Tiny.\n", title="1") == []
    report = scraper._last_wyoming_title_parse_report
    assert report["parser_residuals"][0]["section_number"] == "1-1-101"
    assert report["closed"] is False


def test_wyoming_constitution_terminal_markers_do_not_drop_reserved_rights():
    text = """
ARTICLE 1 - DECLARATION OF RIGHTS

Article 1, Section 36 Rights not enumerated reserved to people.
The enumeration in this constitution of certain rights shall not deny other rights
retained by the people, and all powers not delegated remain with the people.

ARTICLE 3 - LEGISLATIVE DEPARTMENT

Article 3, Section 4 Vacancies. [Repealed.]

Article 3, Section 5 Terms of members.
Members shall serve the terms established by this constitution and applicable law.

ARTICLE 10 - CORPORATIONS

Article 10, Section 3 Forfeited charters.
[Executed.]
"""

    rows = parse_wyoming_constitution_text(text)

    assert [(row.title_number, row.section_number) for row in rows] == [("1", "36"), ("3", "5")]
    assert "reserved to people" in rows[0].full_text


def test_wyoming_source_bundle_binds_both_pdf_parser_modules():
    scraper = WyomingScraper("WY", "Wyoming")

    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__ for dependency in dependencies] == [
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming_constitution",
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming_title",
    ]
    assert "@sha256:" in scraper._state_law_frontier_source_software_version()


def test_wyoming_catalog_preserves_live_official_presentation_order():
    scraper = WyomingScraper("WY", "Wyoming")

    catalog = scraper._build_deterministic_title_catalog()
    title_numbers = [row[0] for row in catalog]
    enumerated_numbers = [
        row["title_number"] for row in scraper.enumerate_official_catalog()
    ]

    assert title_numbers == list(scraper.OFFICIAL_TITLE_NUMBERS)
    assert enumerated_numbers == title_numbers
    assert title_numbers[0] == "97"
    assert title_numbers[34:38] == ["34", "34.1", "35", "36"]
    assert title_numbers[-1] == "99"
    assert len(title_numbers) == len(set(title_numbers)) == 45


@pytest.mark.anyio
async def test_wyoming_strict_full_mode_ignores_configured_local_shortcuts(
    monkeypatch,
    tmp_path,
):
    local = tmp_path / "title6.txt"
    local.write_text(
        "6-2-101. Local diagnostic row.\n"
        "This local diagnostic text is long enough to be parsed but cannot "
        "authorize a prospective exact corpus.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("WYOMING_TITLE_TEXT", str(local))
    monkeypatch.setenv("WYOMING_CONSTITUTION_TEXT", str(local))
    observed: dict[str, object] = {}
    official_marker = object()

    async def _official(code_name, citation_format, max_sections):
        observed.update(
            {
                "citation_format": citation_format,
                "code_name": code_name,
                "max_sections": max_sections,
            }
        )
        return [official_marker]

    scraper = WyomingScraper("WY", "Wyoming")
    monkeypatch.setattr(scraper, "_scrape_deterministic_title_pdfs", _official)

    rows = await scraper.scrape_code(
        "Wyoming Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert rows == [official_marker]
    assert observed == {
        "citation_format": "Wyo. Stat.",
        "code_name": "Wyoming Statutes",
        "max_sections": 1_000_000,
    }


@pytest.mark.anyio
async def test_wyoming_pdf_frontier_uses_one_plural_same_domain_batch(monkeypatch):
    calls: list[tuple[list[str], dict[str, object]]] = []

    async def _plural(self, urls, **kwargs):
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[b"%PDF-1.7\n" + bytes(str(index), "ascii") * 1024 for index, _ in enumerate(requested)],
            errors=[None] * len(requested),
            transport_receipts=[{"source_transport": "direct"}] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={"common_crawl": {"range_fetches_avoided": 0}},
        )

    monkeypatch.setenv("STATE_SCRAPER_WY_PDF_BATCH_SIZE", "45")
    monkeypatch.setenv("STATE_SCRAPER_WY_PDF_CONCURRENCY", "8")
    monkeypatch.setenv("STATE_SCRAPER_WY_PDF_RESIDUAL_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(
        WyomingScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = WyomingScraper("WY", "Wyoming")
    urls = [row[2] for row in scraper._build_deterministic_title_catalog()]

    result = await scraper._fetch_wyoming_pdf_frontier(urls)

    assert result.urls == urls
    assert len(result.payloads) == 45
    assert [requested for requested, _ in calls] == [urls]
    kwargs = calls[0][1]
    assert kwargs["residual_retry_attempts"] == 2
    assert kwargs["prefer_direct"] is True
    assert kwargs["max_concurrency"] == 8
    assert kwargs["media_type"] == "application/pdf"
    assert kwargs["common_crawl_domain_terms"] == ("www.wyoleg.gov", "wyoleg.gov")
    assert kwargs["common_crawl_url_terms"] == ("/statutes/compress/",)
    assert kwargs["wayback_prefix_inventory"] is True


@pytest.mark.anyio
async def test_wyoming_strict_full_mode_closes_exact_45_plural_payloads(monkeypatch):
    scraper = WyomingScraper("WY", "Wyoming")
    catalog = scraper._build_deterministic_title_catalog()
    urls = [row[2] for row in catalog]
    payload_by_url = {
        url: f"%PDF-test:{title}\n".encode("ascii") + b"x" * 2048
        for title, _name, url in catalog
    }
    observed: dict[str, object] = {}

    async def _frontier(requested):
        requested = list(requested)
        observed["urls"] = requested
        payloads = [payload_by_url[url] for url in requested]
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=[
                {
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "source_transport": "direct",
                }
                for payload in payloads
            ],
            parser_input_envelopes=[None] * len(requested),
            stats={"requested_pages": len(requested)},
        )

    def _extract(payload, *, preserve_layout):
        assert preserve_layout is True
        title = payload.splitlines()[0].decode("ascii").split(":", 1)[1]
        if title == "97":
            return """
ARTICLE 1 - DECLARATION OF RIGHTS

Article 1, Section 1 Source-bound constitutional provision.
The people retain this operative constitutional right in a sufficiently long body.
"""
        section = f"{title}-1-101"
        return (
            f"\n     {section}. Source-bound statutory provision.\n\n"
            "     This official provision contains enough substantive body text for indexing.\n"
        )

    def _checkpoint(rows, **kwargs):
        observed["checkpoint_rows"] = list(rows)
        observed["checkpoint_kwargs"] = dict(kwargs)

    async def _single_fetch_must_not_run(*_args, **_kwargs):
        raise AssertionError("strict Wyoming full mode must not use singleton PDF fetches")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_wyoming_pdf_frontier", _frontier)
    monkeypatch.setattr(scraper, "_extract_pdf_text_from_payload", _extract)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)
    monkeypatch.setattr(scraper, "_extract_pdf_text_layout", _single_fetch_must_not_run)
    monkeypatch.setattr(scraper, "_extract_pdf_text_summary", _single_fetch_must_not_run)

    rows = await scraper._scrape_deterministic_title_pdfs(
        "Wyoming Statutes",
        "Wyo. Stat.",
        max_sections=1_000_000,
    )

    assert observed["urls"] == urls
    assert len(rows) == 45
    assert len({row.statute_id for row in rows}) == 45
    checkpoint = observed["checkpoint_kwargs"]
    assert checkpoint["stage_label"] == "wyoming:title-pdf-complete"
    assert checkpoint["extra"]["titles_scanned"] == 45
    assert checkpoint["extra"]["discovered_sections"] == 45
    assert checkpoint["extra"]["operative_sections"] == 45
    assert checkpoint["extra"]["terminal_sections_classified"] == 0
    first = scraper._last_wyoming_full_frontier
    assert first["frontier"]["disposition"] == {
        "discovered": 45,
        "duplicates": 0,
        "excluded": 0,
        "failed_final": 0,
        "fetched": 45,
        "quarantined": 0,
    }
    assert first["frontier"]["legal_as_of"] == "2026-07-01"

    class _RetainedLedger:
        def refresh_existing_entries(self):
            raise AssertionError("direct replay must not refresh the ledger per batch")

        def replay_retained_parser_inputs(self, *, requests):
            retained = []
            for url, request in requests:
                assert request == {
                    "method": "GET",
                    "url": url,
                    "headers": {"Accept": "application/pdf,*/*;q=0.8"},
                }
                payload = payload_by_url[url]
                digest = hashlib.sha256(payload).hexdigest()
                retained.append(
                    SimpleNamespace(
                        envelope=SimpleNamespace(body=payload),
                        receipt=SimpleNamespace(
                            content=SimpleNamespace(sha256=digest)
                        ),
                        transport_receipt={
                            "content_sha256": digest,
                            "source_transport": "direct",
                        },
                    )
                )
            return tuple(retained)

    scraper._state_law_acquisition_ledger = _RetainedLedger()
    replay_rows = await scraper._replay_wyoming_source_frontier(first)

    assert [row.statute_id for row in replay_rows] == [row.statute_id for row in rows]
    assert (
        scraper._last_wyoming_replayed_frontier["frontier"]
        == first["frontier"]
    )


@pytest.mark.anyio
async def test_wyoming_pdf_batch_fails_closed_on_one_unresolved_payload(monkeypatch):
    async def _plural(self, urls, **_kwargs):
        requested = list(urls)
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[b"" if index == 1 else b"%PDF-1.7\n" + b"x" * 1024 for index, _ in enumerate(requested)],
            errors=["archive miss" if index == 1 else None for index, _ in enumerate(requested)],
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={},
        )

    monkeypatch.setattr(
        WyomingScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = WyomingScraper("WY", "Wyoming")
    urls = [row[2] for row in scraper._build_deterministic_title_catalog()[:3]]

    with pytest.raises(RuntimeError, match="unresolved exact URLs"):
        await scraper._fetch_wyoming_pdf_batch(urls, frontier_name="test")


def test_wyoming_retained_45_pdf_oracle_replay():
    """Replay the opt-in legacy oracle without making a network request."""

    configured = os.getenv("STATE_LAWS_TEST_WY_RETAINED_FETCH_ROOT", "").strip()
    if not configured:
        pytest.skip("STATE_LAWS_TEST_WY_RETAINED_FETCH_ROOT is not configured")
    root = Path(configured).expanduser().resolve()
    object_candidates = (
        root / "shard2" / "output" / "cache" / "fetch" / "objects",
        root / "objects",
        root,
    )
    objects = next(
        (candidate for candidate in object_candidates if candidate.is_dir()),
        None,
    )
    if objects is None:
        pytest.fail(f"retained Wyoming fetch object directory not found below {root}")

    search = subprocess.run(
        [
            "rg",
            "-l",
            r'"url": "https://www\.wyoleg\.gov/statutes/compress/title(?:[0-9]+(?:\.1)?)\.pdf"',
            str(objects),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert search.returncode == 0, search.stderr
    metadata_paths = [Path(line) for line in search.stdout.splitlines() if line]
    assert len(metadata_paths) == 45

    title_payloads: dict[str, Path] = {}
    title_digests: dict[str, str] = {}
    url_pattern = re.compile(r"/title(?P<title>34\.1|\d+)\.pdf$")
    for metadata_path in metadata_paths:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        match = url_pattern.search(str(metadata.get("url") or ""))
        assert match is not None
        raw_title = match.group("title")
        title = raw_title if raw_title == "34.1" else str(int(raw_title))
        payload_path = metadata_path.with_suffix(".bin")
        assert payload_path.is_file()
        payload = payload_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        assert digest == metadata["sha256"]
        assert int(metadata["size"]) == len(payload)
        assert title not in title_payloads
        title_payloads[title] = payload_path
        title_digests[title] = digest

    expected_titles = {str(number) for number in range(1, 43)} | {
        "34.1",
        "97",
        "99",
    }
    assert set(title_payloads) == expected_titles
    assert title_digests["35"] == (
        "1195dea407a948ceb914de6daee6e7d9200427a5949d7aeb2d59f17f4d863e5e"
    )

    totals = {"candidate": 0, "operative": 0, "terminal": 0, "residual": 0}
    unclosed_titles: list[str] = []
    overlays: list[dict[str, object]] = []
    scraper = WyomingScraper("WY", "Wyoming")
    with tempfile.TemporaryDirectory(prefix="wy_retained_45_replay_") as temp_dir:
        for title in sorted(expected_titles, key=scraper._title_sort_key):
            text_path = Path(temp_dir) / f"title-{title}.txt"
            extraction = subprocess.run(
                ["pdftotext", "-layout", str(title_payloads[title]), str(text_path)],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            assert extraction.returncode == 0, extraction.stderr
            text = text_path.read_text(encoding="utf-8", errors="replace")
            if title == "97":
                rows = parse_wyoming_constitution_text(text)
                body = "\n" + text
                articles = list(_WY_ARTICLE_RE.finditer(body))
                candidate_count = 0
                terminal_count = 0
                residual_count = 0
                for article_index, article in enumerate(articles):
                    article_end = (
                        articles[article_index + 1].start()
                        if article_index + 1 < len(articles)
                        else len(body)
                    )
                    span = body[article.end():article_end]
                    section_matches = list(_WY_SECTION_RE.finditer("\n" + span))
                    candidate_count += len(section_matches)
                    for section_index, section_match in enumerate(section_matches):
                        section_end = (
                            section_matches[section_index + 1].start()
                            if section_index + 1 < len(section_matches)
                            else len(span) + 1
                        )
                        raw = re.sub(
                            r"\s+",
                            " ",
                            ("\n" + span)[section_match.end():section_end],
                        ).strip()
                        if _TERMINAL.search(raw) or _TERMINAL_LEAD.match(raw):
                            terminal_count += 1
                        elif len(raw) < 40:
                            residual_count += 1
                closed = (
                    candidate_count
                    == len(rows) + terminal_count + residual_count
                    and residual_count == 0
                )
            else:
                rows = _split(scraper, text, title=title)
                report = scraper._last_wyoming_title_parse_report
                candidate_count = report["candidate_sections"]
                terminal_count = report["terminal_sections"]
                residual_count = len(report["parser_residuals"])
                overlays.extend(report["overlay_duplicate_headers"])
                closed = report["closed"]
            totals["candidate"] += candidate_count
            totals["operative"] += len(rows)
            totals["terminal"] += terminal_count
            totals["residual"] += residual_count
            if not closed:
                unclosed_titles.append(title)

    assert totals == {
        # ``pdftotext -layout`` preserves form-feed page boundaries.  Section
        # headings at the top of a new PDF page are part of the exact source
        # frontier and must not be dropped by a line-start expression.
        "candidate": 21_353,
        "operative": 16_708,
        "terminal": 4_645,
        "residual": 0,
    }
    assert unclosed_titles == []
    assert overlays == [
        {
            "section_number": "35-11-318",
            "heading": "Geologic sequestration special revenue account",
            "canonical_section_numbers": ["35-11-320"],
            "reason": "alternate_heading_is_canonical_for_other_section",
        }
    ]
