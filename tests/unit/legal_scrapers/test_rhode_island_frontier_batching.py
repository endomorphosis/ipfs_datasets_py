from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    rhode_island_section,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island import (
    RhodeIslandScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island_section import (
    chapter_part_links,
    part_section_links,
    part_subpart_links,
    source_bound_terminal_section_disposition,
    subpart_section_links,
)

ROOT_URL = "https://webserver.rilegislature.gov/Statutes/"
TITLE_1_URL = f"{ROOT_URL}TITLE1/INDEX.HTM"
TITLE_2_URL = f"{ROOT_URL}TITLE2/INDEX.HTM"
CHAPTER_1_1_URL = f"{ROOT_URL}TITLE1/1-1/INDEX.htm"
CHAPTER_1_2_URL = f"{ROOT_URL}TITLE1/1-2/INDEX.htm"
CHAPTER_2_1_URL = f"{ROOT_URL}TITLE2/2-1/INDEX.htm"
PART_2_1_1_URL = f"{ROOT_URL}TITLE2/2-1/2-1/INDEX.htm"
PART_2_1_2_URL = f"{ROOT_URL}TITLE2/2-1/2-2/INDEX.htm"
CHAPTER_6A_2_1_URL = f"{ROOT_URL}TITLE6A/6A-2.1/INDEX.htm"
PART_6A_2_1_5_URL = f"{ROOT_URL}TITLE6A/6A-2.1/6A-5/INDEX.htm"
SUBPART_6A_2_1_5_A_URL = f"{PART_6A_2_1_5_URL[:-9]}6A-A/INDEX.htm"
SUBPART_6A_2_1_5_B_URL = f"{PART_6A_2_1_5_URL[:-9]}6A-B/INDEX.htm"
CHAPTER_7_12_1_URL = f"{ROOT_URL}TITLE7/7-12.1/INDEX.htm"
ARTICLE_7_12_1_11_URL = f"{CHAPTER_7_12_1_URL[:-9]}7-11/INDEX.htm"
NESTED_PART_7_12_1_11_1_URL = f"{ARTICLE_7_12_1_11_URL[:-9]}7-1/INDEX.htm"
NESTED_PART_7_12_1_11_2_URL = f"{ARTICLE_7_12_1_11_URL[:-9]}7-2/INDEX.htm"
NESTED_PART_SECTION_URL = (
    f"{NESTED_PART_7_12_1_11_1_URL[:-9]}7-12.1-1101.htm"
)
CHAPTER_15_23_1_URL = f"{ROOT_URL}TITLE15/15-23.1/INDEX.htm"
ARTICLE_15_23_1_6_URL = f"{CHAPTER_15_23_1_URL[:-9]}15-6/INDEX.htm"
SUBPART_SECTION_URLS = [
    f"{SUBPART_6A_2_1_5_A_URL[:-9]}6A-2.1-501.htm",
    f"{SUBPART_6A_2_1_5_B_URL[:-9]}6A-2.1-508.htm",
]
PART_SECTION_URLS = [
    f"{ROOT_URL}TITLE2/2-1/2-1/2-1-5.htm",
    f"{ROOT_URL}TITLE2/2-1/2-2/2-1-18.htm",
]
SECTION_URLS = [
    f"{ROOT_URL}TITLE1/1-1/1-1-1.htm",
    f"{ROOT_URL}TITLE1/1-1/1-1-2.htm",
    f"{ROOT_URL}TITLE1/1-2/1-2-1.htm",
    f"{ROOT_URL}TITLE2/2-1/2-1-1.htm",
]


def _root_html(*titles: str) -> bytes:
    return (
        "<html><body>"
        + "".join(
            f"<a href='TITLE{title}/INDEX.HTM'>TITLE {title}</a>"
            for title in titles
        )
        + "</body></html>"
    ).encode()


def _title_html(title: str, *chapters: str) -> bytes:
    del title
    return (
        "<html><body>"
        + "".join(
            f"<a href='{chapter}/INDEX.htm'>Chapter {chapter}</a>"
            for chapter in chapters
        )
        + "</body></html>"
    ).encode()


def _chapter_html(*sections: str) -> bytes:
    return (
        "<html><body>"
        + "".join(
            f"<a href='{section}.htm'>§ {section}. Section {section}</a>"
            for section in sections
        )
        + "</body></html>"
    ).encode()


def _chapter_parts_html(chapter: str, *parts: tuple[str, str]) -> bytes:
    local_chapter = chapter.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h2><center>Chapter {local_chapter}<br>Official Chapter</center>"
        "</h2></div><center><h3>Index of Parts</h3></center>"
        + "".join(
            f"<p><a href='{part}/INDEX.htm'>Part {label}&nbsp;Official Part</a></p>"
            for part, label in parts
        )
        + "</body></html>"
    ).encode()


def _chapter_articles_html(
    chapter: str,
    *articles: tuple[str, str],
) -> bytes:
    local_chapter = chapter.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h2><center>Chapter {local_chapter}<br>Official Chapter</center>"
        "</h2></div><center><h3>Index of Articles</h3></center>"
        + "".join(
            f"<p><a href='{article}/INDEX.htm'>Article {label}&nbsp;"
            "Official Article</a></p>"
            for article, label in articles
        )
        + "</body></html>"
    ).encode()


def _part_html(part: str, *sections: str) -> bytes:
    local_part = part.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h3><center>Part {local_part}<br>Official Part</center></h3></div>"
        "<center><h3>Index of Sections</h3></center>"
        + "".join(
            f"<p><a href='{section}.htm'>§ {section}. Official section</a></p>"
            for section in sections
        )
        + "</body></html>"
    ).encode()


def _part_subparts_html(
    part: str,
    *subparts: tuple[str, str],
) -> bytes:
    local_part = part.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h3><center>Part {local_part}<br>Official Part</center></h3></div>"
        "<center><h3>Index of Subparts</h3></center>"
        + "".join(
            f"<p><a href='{subpart}/INDEX.htm'>Subpart {label}&nbsp;"
            "Official Subpart</a></p>"
            for subpart, label in subparts
        )
        + "</body></html>"
    ).encode()


def _article_parts_html(
    article: str,
    *parts: tuple[str, str],
) -> bytes:
    local_article = article.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h3><center>Article {local_article}<br>Official Article"
        "</center></h3></div><center><h3>Index of Parts</h3></center>"
        + "".join(
            f"<p><a href='{part}/INDEX.htm'>Part {label}&nbsp;"
            "Official Part</a></p>"
            for part, label in parts
        )
        + "</body></html>"
    ).encode()


def _subpart_html(subpart: str, *sections: str) -> bytes:
    local_subpart = subpart.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h4><center>Subpart {local_subpart}<br>Official Subpart"
        "</center></h4></div><center><h3>Index of Sections</h3></center>"
        + "".join(
            f"<p><a href='{section}.htm'>§ {section}. Official section</a></p>"
            for section in sections
        )
        + "</body></html>"
    ).encode()


def _nested_part_html(part: str, *sections: str) -> bytes:
    local_part = part.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h4><center>Part {local_part}<br>Official Part"
        "</center></h4></div><center><h3>Index of Sections</h3></center>"
        + "".join(
            f"<p><a href='{section}.htm'>§ {section}. Official section</a></p>"
            for section in sections
        )
        + "</body></html>"
    ).encode()


def _section_html(section: str) -> bytes:
    return (
        "<html><body>"
        "<div>Rhode Island General Laws</div>"
        f"<div>Chapter {'-'.join(section.split('-')[:-1])}</div>"
        "<div>"
        f"<p><b>§ {section}. Official section {section}.</b></p>"
        f"<p>Official Rhode Island statutory text for {section}. "
        "This sufficiently long body is retained without a synthetic fallback.</p>"
        "<div><p>History of Section. P.L. 2025, ch. 1.</p></div>"
        "</div>"
        "</body></html>"
    ).encode()


def _disable_bounded_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_load_partial_checkpoint_statutes",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_load_partial_checkpoint_progress",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )


def test_rhode_island_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = RhodeIslandScraper("RI", "Rhode Island")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "rhode_island_section",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island."
        "RhodeIslandScraper@sha256:"
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


def test_rhode_island_terminal_classifier_is_exact_and_source_bound() -> None:
    html = (
        "<html><body><div>Title 1</div><div>Chapter 1-1</div><div>"
        "<p><b>§ 1-1-1. Repealed.</b></p>"
        "<div><p>History of Section. Repealed by P.L. 2000, ch. 1.</p></div>"
        "</div></body></html>"
    )

    assert source_bound_terminal_section_disposition(
        html,
        section_number="1-1-1",
        source_url=SECTION_URLS[0],
    ) == "repealed"
    assert source_bound_terminal_section_disposition(
        html,
        section_number="1-1-2",
        source_url=SECTION_URLS[0],
    ) is None
    assert source_bound_terminal_section_disposition(
        html.replace("Repealed.", "An active section."),
        section_number="1-1-1",
        source_url=SECTION_URLS[0],
    ) is None

    range_html = (
        "<html><body><p><b>§ 1-1-2 — 1-1-5. Repealed.</b></p></body></html>"
    )
    assert source_bound_terminal_section_disposition(
        range_html,
        section_number="1-1-2",
        source_url=SECTION_URLS[1],
    ) == "repealed_range"
    assert source_bound_terminal_section_disposition(
        range_html.replace("1-1-5", "2-1-5"),
        section_number="1-1-2",
        source_url=SECTION_URLS[1],
    ) is None

    nested_range_url = f"{ROOT_URL}TITLE2/2-1/2-1/2-1-1.htm"
    assert source_bound_terminal_section_disposition(
        "<html><body><b>§ 2-1-1 — 2-1-4. [Superseded.]</b></body></html>",
        section_number="2-1-1",
        source_url=nested_range_url,
    ) == "superseded_range"
    nested_obsolete_url = f"{ROOT_URL}TITLE2/2-1/2-1/2-1-7.htm"
    assert source_bound_terminal_section_disposition(
        "<html><body><b>§ 2-1-7. [Obsolete.]</b></body></html>",
        section_number="2-1-7",
        source_url=nested_obsolete_url,
    ) == "obsolete"


def test_rhode_island_exact_2_1_part_frontier_is_source_bound() -> None:
    chapter_html = _chapter_parts_html(
        "2-1",
        ("2-1", "1"),
        ("2-2", "2"),
        ("2-3", "3"),
    ).decode()

    assert chapter_part_links(
        chapter_html,
        chapter_url=CHAPTER_2_1_URL,
        title_number="2",
        chapter_number="2-1",
    ) == [
        (PART_2_1_1_URL, "Part 1 Official Part"),
        (PART_2_1_2_URL, "Part 2 Official Part"),
        (
            f"{ROOT_URL}TITLE2/2-1/2-3/INDEX.htm",
            "Part 3 Official Part",
        ),
    ]
    assert part_section_links(
        _part_html("2-1", "2-1-5").decode(),
        part_url=PART_2_1_1_URL,
        title_number="2",
        chapter_number="2-1",
        part_number="2-1",
    ) == [(PART_SECTION_URLS[0], "§ 2-1-5. Official section")]


def test_rhode_island_subpart_frontier_is_digest_and_source_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html_bytes = _part_subparts_html(
        "6A-5",
        ("6A-A", "A"),
        ("6A-B", "B"),
    )
    html = html_bytes.decode()
    identity = ("6A", "6A-2.1", "6A-5")
    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {identity: hashlib.sha256(html_bytes).hexdigest()},
    )

    assert part_subpart_links(
        html,
        part_url=PART_6A_2_1_5_URL,
        title_number="6A",
        chapter_number="6A-2.1",
        part_number="6A-5",
        intermediate_label="Part 5 Official Part",
    ) == [
        (SUBPART_6A_2_1_5_A_URL, "Subpart A Official Subpart"),
        (SUBPART_6A_2_1_5_B_URL, "Subpart B Official Subpart"),
    ]
    assert part_subpart_links(
        html.replace("Official Subpart", "Changed Subpart", 1),
        part_url=PART_6A_2_1_5_URL,
        title_number="6A",
        chapter_number="6A-2.1",
        part_number="6A-5",
        intermediate_label="Part 5 Official Part",
    ) == []
    assert part_subpart_links(
        html,
        part_url=PART_6A_2_1_5_URL.replace("TITLE6A", "TITLE7"),
        title_number="6A",
        chapter_number="6A-2.1",
        part_number="6A-5",
        intermediate_label="Part 5 Official Part",
    ) == []

    duplicate_child = html.replace("6A-B/INDEX.htm", "6A-A/INDEX.htm")
    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {identity: hashlib.sha256(duplicate_child.encode()).hexdigest()},
    )
    assert part_subpart_links(
        duplicate_child,
        part_url=PART_6A_2_1_5_URL,
        title_number="6A",
        chapter_number="6A-2.1",
        part_number="6A-5",
        intermediate_label="Part 5 Official Part",
    ) == []


def test_rhode_island_subpart_sections_reject_parent_or_heading_drift() -> None:
    html = _subpart_html("6A-A", "6A-2.1-501").decode()

    assert subpart_section_links(
        html,
        subpart_url=SUBPART_6A_2_1_5_A_URL,
        title_number="6A",
        chapter_number="6A-2.1",
        part_number="6A-5",
        subpart_number="6A-A",
        intermediate_label="Subpart A Official Subpart",
    ) == [
        (SUBPART_SECTION_URLS[0], "§ 6A-2.1-501. Official section")
    ]
    assert subpart_section_links(
        html,
        subpart_url=SUBPART_6A_2_1_5_A_URL,
        title_number="6A",
        chapter_number="6A-2.1",
        part_number="6A-6",
        subpart_number="6A-A",
        intermediate_label="Subpart A Official Subpart",
    ) == []
    assert subpart_section_links(
        html.replace("Subpart A", "Subpart B"),
        subpart_url=SUBPART_6A_2_1_5_A_URL,
        title_number="6A",
        chapter_number="6A-2.1",
        part_number="6A-5",
        subpart_number="6A-A",
        intermediate_label="Subpart A Official Subpart",
    ) == []


def test_rhode_island_exact_article_part_frontier_is_digest_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = ("7", "7-12.1", "7-11")
    assert rhode_island_section._SOURCE_BOUND_SUBPART_INDEX_DIGESTS[identity] == (
        "5a6d02fe5011707edf6cfeb59305114f25e72c1e05c199b697ba81467db7e359"
    )

    html_bytes = _article_parts_html("7-11", ("7-1", "1"), ("7-2", "2"))
    html = html_bytes.decode()
    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {identity: hashlib.sha256(html_bytes).hexdigest()},
    )

    assert part_subpart_links(
        html,
        part_url=ARTICLE_7_12_1_11_URL,
        title_number="7",
        chapter_number="7-12.1",
        part_number="7-11",
        intermediate_label="Article 11 Official Article",
    ) == [
        (NESTED_PART_7_12_1_11_1_URL, "Part 1 Official Part"),
        (
            f"{ARTICLE_7_12_1_11_URL[:-9]}7-2/INDEX.htm",
            "Part 2 Official Part",
        ),
    ]

    drifted = html.replace("Part 2", "Subpart 2")
    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {identity: hashlib.sha256(drifted.encode()).hexdigest()},
    )
    assert part_subpart_links(
        drifted,
        part_url=ARTICLE_7_12_1_11_URL,
        title_number="7",
        chapter_number="7-12.1",
        part_number="7-11",
        intermediate_label="Article 11 Official Article",
    ) == []


def test_rhode_island_retained_title_15_article_part_frontier_is_digest_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = ("15", "15-23.1", "15-6")
    assert rhode_island_section._SOURCE_BOUND_SUBPART_INDEX_DIGESTS[identity] == (
        "9446cef94458118d5701254227571dc6b383abd87e025c9fe9b698c69af14f8e"
    )
    assert identity in rhode_island_section._SOURCE_BOUND_NESTED_PART_INDEX_IDENTITIES

    html_bytes = _article_parts_html("15-6", ("15-1", "1"), ("15-4", "4"))
    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {identity: hashlib.sha256(html_bytes).hexdigest()},
    )

    assert part_subpart_links(
        html_bytes.decode(),
        part_url=ARTICLE_15_23_1_6_URL,
        title_number="15",
        chapter_number="15-23.1",
        part_number="15-6",
        intermediate_label="Article 6 Official Article",
    ) == [
        (f"{ARTICLE_15_23_1_6_URL[:-9]}15-1/INDEX.htm", "Part 1 Official Part"),
        (f"{ARTICLE_15_23_1_6_URL[:-9]}15-4/INDEX.htm", "Part 4 Official Part"),
    ]


def test_rhode_island_exact_nested_part_sections_reject_kind_drift() -> None:
    html = _nested_part_html("7-1", "7-12.1-1101").decode()

    assert subpart_section_links(
        html,
        subpart_url=NESTED_PART_7_12_1_11_1_URL,
        title_number="7",
        chapter_number="7-12.1",
        part_number="7-11",
        subpart_number="7-1",
        intermediate_label="Part 1 Official Part",
    ) == [
        (NESTED_PART_SECTION_URL, "§ 7-12.1-1101. Official section")
    ]
    assert subpart_section_links(
        html.replace("Part 1", "Subpart 1"),
        subpart_url=NESTED_PART_7_12_1_11_1_URL,
        title_number="7",
        chapter_number="7-12.1",
        part_number="7-11",
        subpart_number="7-1",
        intermediate_label="Part 1 Official Part",
    ) == []


@pytest.mark.parametrize(
    ("chapter_html", "chapter_url", "title_number", "chapter_number"),
    [
        (
            _chapter_parts_html("2-1", ("2-1", "1"))
            .decode()
            .replace("Chapter 1", "Chapter 2"),
            CHAPTER_2_1_URL,
            "2",
            "2-1",
        ),
        (
            _chapter_parts_html("2-1", ("2-1", "1"))
            .decode()
            .replace(
                "2-1/INDEX.htm",
                "https://example.com/Statutes/TITLE2/2-1/2-1/INDEX.htm",
            ),
            CHAPTER_2_1_URL,
            "2",
            "2-1",
        ),
        (
            _chapter_parts_html("2-1", ("2-1", "1"))
            .decode()
            .replace(
                "2-1/INDEX.htm",
                "/Statutes/TITLE2/2-2/2-1/INDEX.htm",
            ),
            CHAPTER_2_1_URL,
            "2",
            "2-1",
        ),
        (
            _chapter_parts_html("2-1", ("2-1", "1")).decode(),
            CHAPTER_2_1_URL,
            "1",
            "1-1",
        ),
    ],
)
def test_rhode_island_part_frontier_rejects_identity_or_locator_drift(
    chapter_html: str,
    chapter_url: str,
    title_number: str,
    chapter_number: str,
) -> None:
    assert chapter_part_links(
        chapter_html,
        chapter_url=chapter_url,
        title_number=title_number,
        chapter_number=chapter_number,
    ) == []


def test_rhode_island_part_section_frontier_rejects_prefix_drift() -> None:
    valid = _part_html("2-1", "2-1-5").decode()

    assert part_section_links(
        valid.replace("2-1-5.htm", "/Statutes/TITLE2/2-2/2-1/2-1-5.htm"),
        part_url=PART_2_1_1_URL,
        title_number="2",
        chapter_number="2-1",
        part_number="2-1",
    ) == []
    assert part_section_links(
        valid.replace("2-1-5.htm", "https://example.com/2-1-5.htm"),
        part_url=PART_2_1_1_URL,
        title_number="2",
        chapter_number="2-1",
        part_number="2-1",
    ) == []


@pytest.mark.anyio
async def test_rhode_island_frontier_batch_delegates_exact_residuals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    urls = SECTION_URLS[:2]

    async def _plural(self, requested, **kwargs):
        requested = list(requested)
        calls.append((requested, dict(kwargs)))
        validator = kwargs["content_validator"]
        assert validator(b"<html><body>Official statute</body></html>") is True
        assert validator(b"<html><title>404 Not Found</title></html>") is False
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[b"one", b"two"],
            errors=[None, None],
            transport_receipts=[{}, {}],
            parser_input_envelopes=[None, None],
            stats={},
        )

    monkeypatch.setenv("STATE_SCRAPER_RI_FRONTIER_CONCURRENCY", "7")
    monkeypatch.setenv(
        "STATE_SCRAPER_RI_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
        "3",
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    batch = await scraper._fetch_rhode_island_frontier_batch(
        urls,
        frontier_name="sections",
    )

    assert batch.urls == urls
    assert batch.payloads == [b"one", b"two"]
    assert batch.errors == [None, None]
    assert batch.transport_receipts == [{}, {}]
    assert len(calls) == 1
    requested, kwargs = calls[0]
    assert requested == urls
    assert kwargs["residual_retry_attempts"] == 3
    assert kwargs["max_concurrency"] == 7
    assert kwargs["prefer_direct"] is True
    assert kwargs["common_crawl_domain_terms"] == (
        "webserver.rilegislature.gov",
    )
    assert kwargs["common_crawl_url_terms"] == ("/Statutes/",)
    assert kwargs["wayback_prefix_inventory"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("failure_kind", ["reordered", "missing", "short"])
async def test_rhode_island_frontier_batch_fails_on_alignment_or_body_gap(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    urls = SECTION_URLS[:2]

    async def _plural(self, requested, **_kwargs):
        requested = list(requested)
        returned_urls = (
            list(reversed(requested))
            if failure_kind == "reordered"
            else requested
        )
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
        RhodeIslandScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    with pytest.raises(
        RuntimeError,
        match="changed URL order|unresolved exact URLs|unaligned acquisition rows",
    ):
        await scraper._fetch_rhode_island_frontier_batch(
            urls,
            frontier_name="sections",
        )


@pytest.mark.anyio
async def test_rhode_island_unbounded_batches_every_phase_and_crosses_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        ROOT_URL: _root_html("1", "2"),
        TITLE_1_URL: _title_html("1", "1-1", "1-2"),
        TITLE_2_URL: _title_html("2", "2-1"),
        CHAPTER_1_1_URL: _chapter_html("1-1-1", "1-1-2"),
        CHAPTER_1_2_URL: _chapter_html("1-2-1"),
        CHAPTER_2_1_URL: _chapter_html("2-1-1"),
        **{
            url: _section_html(url.rsplit("/", 1)[-1].removesuffix(".htm"))
            for url in SECTION_URLS
        },
    }
    batch_calls: list[tuple[str, list[str]]] = []
    checkpoint_calls: list[tuple[str, bool]] = []

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return [pages[url] for url in requested]

    async def _singleton_must_not_run(*_args, **_kwargs):
        raise AssertionError("unbounded Rhode Island must use only plural fetches")

    def _checkpoint(
        self,
        statutes,
        *,
        stage_label: str,
        replace_existing_rows: bool = False,
        **_kwargs,
    ) -> bool:
        checkpoint_calls.append((stage_label, replace_existing_rows))
        return True

    def _stale_checkpoint_must_not_load(*_args, **_kwargs):
        raise AssertionError(
            "unbounded Rhode Island must reconstruct the authoritative frontier"
        )

    monkeypatch.setattr(
        RhodeIslandScraper,
        "OFFICIAL_TITLES",
        (("1", "Title 1"), ("2", "Title 2")),
    )
    monkeypatch.setenv("STATE_SCRAPER_RI_SECTION_BATCH_SIZE", "2")
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _batch,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton_must_not_run,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_load_partial_checkpoint_statutes",
        _stale_checkpoint_must_not_load,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_load_partial_checkpoint_progress",
        _stale_checkpoint_must_not_load,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        _checkpoint,
    )
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    rows = await scraper._custom_scrape_rhode_island(
        "Rhode Island General Laws",
        ROOT_URL,
        "R.I. Gen. Laws",
        max_sections=None,
    )

    assert batch_calls == [
        ("root-index", [ROOT_URL]),
        ("title-index", [TITLE_1_URL, TITLE_2_URL]),
        (
            "chapter-index",
            [CHAPTER_1_1_URL, CHAPTER_1_2_URL, CHAPTER_2_1_URL],
        ),
        ("sections", SECTION_URLS),
    ]
    assert [row.section_number for row in rows] == [
        "1-1-1",
        "1-1-2",
        "1-2-1",
        "2-1-1",
    ]
    assert [row.source_url for row in rows] == SECTION_URLS
    assert len({row.statute_id for row in rows}) == 4
    assert checkpoint_calls == [
        ("rhode-island:chapter-discovery", True),
        ("rhode-island:section-discovery", True),
        ("rhode-island:section-scan", True),
        ("rhode-island:section-scan", True),
        ("rhode-island:complete", True),
    ]


@pytest.mark.anyio
async def test_rhode_island_unbounded_batches_nested_part_indexes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        ROOT_URL: _root_html("2"),
        TITLE_2_URL: _title_html("2", "2-1"),
        CHAPTER_2_1_URL: _chapter_parts_html(
            "2-1",
            ("2-1", "1"),
            ("2-2", "2"),
        ),
        PART_2_1_1_URL: _part_html("2-1", "2-1-5"),
        PART_2_1_2_URL: _part_html("2-2", "2-1-18"),
        PART_SECTION_URLS[0]: _section_html("2-1-5"),
        PART_SECTION_URLS[1]: _section_html("2-1-18"),
    }
    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return [pages[url] for url in requested]

    async def _singleton_must_not_run(*_args, **_kwargs):
        raise AssertionError("unbounded nested RI frontier must remain plural")

    monkeypatch.setattr(
        RhodeIslandScraper,
        "OFFICIAL_TITLES",
        (("2", "Title 2"),),
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _batch,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton_must_not_run,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    rows = await scraper._custom_scrape_rhode_island(
        "Rhode Island General Laws",
        ROOT_URL,
        "R.I. Gen. Laws",
        max_sections=None,
    )

    assert batch_calls == [
        ("root-index", [ROOT_URL]),
        ("title-index", [TITLE_2_URL]),
        ("chapter-index", [CHAPTER_2_1_URL]),
        ("part-index", [PART_2_1_1_URL, PART_2_1_2_URL]),
        ("sections", PART_SECTION_URLS),
    ]
    assert [row.section_number for row in rows] == ["2-1-5", "2-1-18"]
    assert [row.chapter_number for row in rows] == ["2-1", "2-1"]
    assert [row.source_url for row in rows] == PART_SECTION_URLS


@pytest.mark.anyio
async def test_rhode_island_unbounded_batches_digest_bound_subparts_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    part_html = _part_subparts_html(
        "6A-5",
        ("6A-A", "A"),
        ("6A-B", "B"),
    )
    pages = {
        ROOT_URL: _root_html("6A"),
        f"{ROOT_URL}TITLE6A/INDEX.HTM": _title_html("6A", "6A-2.1"),
        CHAPTER_6A_2_1_URL: _chapter_parts_html(
            "6A-2.1",
            ("6A-5", "5"),
        ),
        PART_6A_2_1_5_URL: part_html,
        SUBPART_6A_2_1_5_A_URL: _subpart_html("6A-A", "6A-2.1-501"),
        SUBPART_6A_2_1_5_B_URL: _subpart_html("6A-B", "6A-2.1-508"),
        SUBPART_SECTION_URLS[0]: _section_html("6A-2.1-501"),
        SUBPART_SECTION_URLS[1]: _section_html("6A-2.1-508"),
    }
    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return [pages[url] for url in requested]

    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {
            ("6A", "6A-2.1", "6A-5"): hashlib.sha256(
                part_html
            ).hexdigest()
        },
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "OFFICIAL_TITLES",
        (("6A", "Title 6A"),),
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _batch,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    rows = await scraper._custom_scrape_rhode_island(
        "Rhode Island General Laws",
        ROOT_URL,
        "R.I. Gen. Laws",
        max_sections=None,
    )

    assert batch_calls == [
        ("root-index", [ROOT_URL]),
        ("title-index", [f"{ROOT_URL}TITLE6A/INDEX.HTM"]),
        ("chapter-index", [CHAPTER_6A_2_1_URL]),
        ("part-index", [PART_6A_2_1_5_URL]),
        (
            "subpart-index",
            [SUBPART_6A_2_1_5_A_URL, SUBPART_6A_2_1_5_B_URL],
        ),
        ("sections", SUBPART_SECTION_URLS),
    ]
    assert [row.section_number for row in rows] == [
        "6A-2.1-501",
        "6A-2.1-508",
    ]
    assert [row.source_url for row in rows] == SUBPART_SECTION_URLS


@pytest.mark.anyio
async def test_rhode_island_unbounded_batches_exact_article_parts_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article_html = _article_parts_html(
        "7-11",
        ("7-1", "1"),
        ("7-2", "2"),
    )
    nested_section_urls = [
        NESTED_PART_SECTION_URL,
        f"{NESTED_PART_7_12_1_11_2_URL[:-9]}7-12.1-1108.htm",
    ]
    pages = {
        ROOT_URL: _root_html("7"),
        f"{ROOT_URL}TITLE7/INDEX.HTM": _title_html("7", "7-12.1"),
        CHAPTER_7_12_1_URL: _chapter_articles_html(
            "7-12.1",
            ("7-11", "11"),
        ),
        ARTICLE_7_12_1_11_URL: article_html,
        NESTED_PART_7_12_1_11_1_URL: _nested_part_html(
            "7-1",
            "7-12.1-1101",
        ),
        NESTED_PART_7_12_1_11_2_URL: _nested_part_html(
            "7-2",
            "7-12.1-1108",
        ),
        nested_section_urls[0]: _section_html("7-12.1-1101"),
        nested_section_urls[1]: _section_html("7-12.1-1108"),
    }
    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return [pages[url] for url in requested]

    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {
            ("7", "7-12.1", "7-11"): hashlib.sha256(
                article_html
            ).hexdigest()
        },
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "OFFICIAL_TITLES",
        (("7", "Title 7"),),
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _batch,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    rows = await scraper._custom_scrape_rhode_island(
        "Rhode Island General Laws",
        ROOT_URL,
        "R.I. Gen. Laws",
        max_sections=None,
    )

    assert batch_calls == [
        ("root-index", [ROOT_URL]),
        ("title-index", [f"{ROOT_URL}TITLE7/INDEX.HTM"]),
        ("chapter-index", [CHAPTER_7_12_1_URL]),
        ("part-index", [ARTICLE_7_12_1_11_URL]),
        (
            "subpart-index",
            [
                NESTED_PART_7_12_1_11_1_URL,
                NESTED_PART_7_12_1_11_2_URL,
            ],
        ),
        ("sections", nested_section_urls),
    ]
    assert [row.section_number for row in rows] == [
        "7-12.1-1101",
        "7-12.1-1108",
    ]
    assert [row.source_url for row in rows] == nested_section_urls


@pytest.mark.anyio
async def test_rhode_island_nested_parts_preserve_duplicate_section_fail_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        ROOT_URL: _root_html("2"),
        TITLE_2_URL: _title_html("2", "2-1"),
        CHAPTER_2_1_URL: _chapter_parts_html(
            "2-1",
            ("2-1", "1"),
            ("2-2", "2"),
        ),
        PART_2_1_1_URL: _part_html("2-1", "2-1-5"),
        PART_2_1_2_URL: _part_html("2-2", "2-1-5"),
    }

    async def _batch(self, urls, *, frontier_name: str):
        del frontier_name
        return [pages[url] for url in urls]

    monkeypatch.setattr(
        RhodeIslandScraper,
        "OFFICIAL_TITLES",
        (("2", "Title 2"),),
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _batch,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    with pytest.raises(
        RuntimeError,
        match=r"repeated section identity 2-1-5",
    ):
        await scraper._custom_scrape_rhode_island(
            "Rhode Island General Laws",
            ROOT_URL,
            "R.I. Gen. Laws",
            max_sections=None,
        )


@pytest.mark.anyio
async def test_rhode_island_unbounded_rejects_unparseable_required_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        ROOT_URL: _root_html("1"),
        TITLE_1_URL: _title_html("1", "1-1"),
        CHAPTER_1_1_URL: _chapter_html("1-1-1"),
        SECTION_URLS[0]: b"<html><body>navigation shell only</body></html>",
    }

    async def _batch(self, urls, *, frontier_name: str):
        del frontier_name
        return [pages[url] for url in urls]

    monkeypatch.setattr(
        RhodeIslandScraper,
        "OFFICIAL_TITLES",
        (("1", "Title 1"),),
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _batch,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    with pytest.raises(
        RuntimeError,
        match=r"TITLE1/1-1/1-1-1\.htm",
    ):
        await scraper._custom_scrape_rhode_island(
            "Rhode Island General Laws",
            ROOT_URL,
            "R.I. Gen. Laws",
            max_sections=None,
        )


def test_rhode_island_strict_locators_reject_noncanonical_sources() -> None:
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    with pytest.raises(RuntimeError, match="non-canonical title locator"):
        scraper._canonical_rhode_island_title_url(
            "https://example.com/Statutes/TITLE1/INDEX.HTM",
            "1",
        )
    with pytest.raises(RuntimeError, match="non-canonical chapter locator"):
        scraper._canonical_rhode_island_chapter_locator(
            "https://webserver.rilegislature.gov/Statutes/TITLE2/1-1/INDEX.htm",
            title_number="1",
            chapter_number="1-1",
        )
    with pytest.raises(RuntimeError, match="non-canonical section locator"):
        scraper._canonical_rhode_island_section_locator(
            "https://webserver.rilegislature.gov/Statutes/TITLE1/1-2/1-1-1.htm",
            title_number="1",
            chapter_number="1-1",
        )


@pytest.mark.anyio
async def test_rhode_island_bounded_probe_keeps_singleton_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        ROOT_URL: _root_html("1"),
        TITLE_1_URL: _title_html("1", "1-1"),
        CHAPTER_1_1_URL: _chapter_html("1-1-1"),
        SECTION_URLS[0]: _section_html("1-1-1"),
    }
    singleton_calls: list[str] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        del timeout_seconds
        singleton_calls.append(url)
        return pages.get(url, b"")

    async def _plural_must_not_run(*_args, **_kwargs):
        raise AssertionError("bounded Rhode Island probes preserve singleton behavior")

    _disable_bounded_checkpoints(monkeypatch)
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _plural_must_not_run,
    )
    scraper = RhodeIslandScraper("RI", "Rhode Island")

    rows = await scraper._custom_scrape_rhode_island(
        "Rhode Island General Laws",
        ROOT_URL,
        "R.I. Gen. Laws",
        max_sections=1,
    )

    assert singleton_calls == [
        ROOT_URL,
        TITLE_1_URL,
        CHAPTER_1_1_URL,
        SECTION_URLS[0],
    ]
    assert [row.section_number for row in rows] == ["1-1-1"]
    assert rows[0].source_url == SECTION_URLS[0]
